"""JSON-RPC 2.0 sidecar over stdio with Content-Length framing (ARCHITECTURE section 6).

No network listener. The desktop shell supervises this process; every method is a thin call into ``screen2code.api``.
"""
from __future__ import annotations

import base64
import json
import sys
import threading
import traceback
from pathlib import Path
from typing import Any, BinaryIO, Callable

from .. import __version__
from ..api import Project
from ..core import CancelToken, S2CError
from ..core.log import scrub
from ..core.models import ModelStore

RPC_VERSION = 1
MAX_MESSAGE = 64 * 1024 * 1024
MAX_ARTIFACT = 16 * 1024 * 1024
# the UI may read only these project areas and file types; everything else is a method of its own (ir.get, settings.get, ...)
ARTIFACT_DIRS = ("renders", "evaluations", "exports", "refinements", "ir")
ARTIFACT_TYPES = {".png": "image/png", ".json": "application/json", ".md": "text/markdown", ".html": "text/html", ".css": "text/css", ".txt": "text/plain"}
JSON = dict[str, Any]


class RpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(message)
        self.code, self.message, self.data = code, message, data


def read_frame(stream: BinaryIO) -> bytes | None:
    length = None
    while True:
        line = stream.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            break
        if line.lower().startswith(b"content-length:"):
            try:
                length = int(line.split(b":", 1)[1])
            except ValueError as e:
                raise RpcError(-32700, "invalid Content-Length") from e
    if length is None or length < 0 or length > MAX_MESSAGE:
        raise RpcError(-32600, "missing or oversized message")
    body = stream.read(length)
    if len(body) != length:
        return None
    return body


class Server:
    def __init__(self, inp: BinaryIO, out: BinaryIO):
        self.inp, self.out = inp, out
        self.lock = threading.Lock()
        self.cancels: dict[Any, CancelToken] = {}
        self.initialized = False
        self.methods: dict[str, Callable[[JSON, Any], Any]] = {
            "initialize": self.m_initialize, "shutdown": lambda p, i: None, "project.create": self.m_create, "project.open": self.m_open, "import.images": self.m_import,
            "analysis.start": self.m_analysis, "ir.get": self.m_ir, "generate.run": self.m_generate, "render.run": self.m_render, "compare.get": self.m_compare,
            "models.list": self.m_models, "settings.get": self.m_settings, "project.status": self.m_status, "reconcile.get": self.m_reconcile,
            "source.image": self.m_source_image, "artifact.read": self.m_artifact, "refine.run": self.m_refine, "refine.list": self.m_refine_list,
        }

    # -- transport
    def send(self, obj: JSON) -> None:
        data = json.dumps(obj, sort_keys=True, default=str).encode("utf-8")
        with self.lock:
            self.out.write(b"Content-Length: %d\r\n\r\n" % len(data) + data)
            self.out.flush()

    def notify(self, method: str, params: JSON) -> None:
        self.send({"jsonrpc": "2.0", "method": method, "params": params})

    def reply(self, rid: Any, result: Any = None, error: RpcError | None = None) -> None:
        if error:
            self.send({"jsonrpc": "2.0", "id": rid, "error": {"code": error.code, "message": error.message, **({"data": error.data} if error.data is not None else {})}})
        else:
            self.send({"jsonrpc": "2.0", "id": rid, "result": result})

    def serve(self) -> None:
        threads: list[threading.Thread] = []
        while True:
            try:
                frame = read_frame(self.inp)
            except RpcError as e:
                self.reply(None, error=e)
                continue
            if frame is None:
                break
            try:
                msg = json.loads(frame.decode("utf-8"))
                if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
                    raise RpcError(-32600, "not a JSON-RPC 2.0 message")
            except (ValueError, UnicodeDecodeError):
                self.reply(None, error=RpcError(-32700, "parse error"))
                continue
            except RpcError as e:
                self.reply(None, error=e)
                continue
            method, rid, params = msg.get("method"), msg.get("id"), msg.get("params", {})
            if method == "$/cancel":
                tok = self.cancels.get((params or {}).get("id"))
                if tok:
                    tok.cancel()
                continue
            if method == "exit":
                break
            if not isinstance(method, str) or not isinstance(params, dict):
                if rid is not None:
                    self.reply(rid, error=RpcError(-32600, "invalid request"))
                continue
            t = threading.Thread(target=self.handle, args=(method, params, rid), daemon=True)
            t.start()
            threads.append(t)
            if method == "shutdown":
                t.join()
        for t in threads:
            t.join(timeout=5)

    def handle(self, method: str, params: JSON, rid: Any) -> None:
        try:
            if method not in self.methods:
                raise RpcError(-32601, f"unknown method {method!r}")
            if method != "initialize" and not self.initialized:
                raise RpcError(-32002, "server not initialized")
            self.cancels[rid] = CancelToken()
            res = self.methods[method](params, rid)
            if rid is not None:
                self.reply(rid, res)
        except RpcError as e:
            if rid is not None:
                self.reply(rid, error=e)
        except S2CError as e:
            if rid is not None:
                self.reply(rid, error=RpcError(-32000, scrub(str(e)), scrub(e.to_dict())))
        except (KeyError, TypeError, ValueError) as e:
            if rid is not None:
                self.reply(rid, error=RpcError(-32602, f"invalid params: {type(e).__name__}: {e}"))
        except Exception as e:  # noqa: BLE001 - reported to the client with context, never swallowed
            if rid is not None:
                self.reply(rid, error=RpcError(-32603, scrub(f"internal error: {type(e).__name__}: {e}"), {"trace": scrub(traceback.format_exc(limit=3))}))
        finally:
            self.cancels.pop(rid, None)

    # -- parameter validation (every method validates its own params; a malformed request is -32602, never an internal error)
    @staticmethod
    def req(p: JSON, key: str, typ: type | tuple[type, ...], *, optional: bool = False) -> Any:
        v = p.get(key)
        if v is None:
            if optional:
                return None
            raise RpcError(-32602, f"missing parameter {key!r}")
        if isinstance(v, bool) and typ is not bool and bool not in (typ if isinstance(typ, tuple) else (typ,)):
            raise RpcError(-32602, f"parameter {key!r} must be {typ}")
        if not isinstance(v, typ):
            raise RpcError(-32602, f"parameter {key!r} must be {typ.__name__ if isinstance(typ, type) else typ}")
        return v

    @staticmethod
    def num(p: JSON, key: str, lo: float, hi: float) -> float | None:
        v = p.get(key)
        if v is None:
            return None
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
            raise RpcError(-32602, f"parameter {key!r} must be a number in [{lo}, {hi}]")
        return float(v)

    # -- methods
    def proj(self, p: JSON) -> Project:
        self.req(p, "project", str)
        ov = self.req(p, "overrides", dict, optional=True)
        return Project.open(Path(p["project"]), ov)

    def progress(self, rid: Any) -> Callable[[Any], None]:
        return lambda ev: self.notify("progress", {"id": rid, "stage": ev.stage, "status": ev.status, "progress": ev.progress, "message": ev.message})

    def m_initialize(self, p: JSON, rid: Any) -> JSON:
        if p.get("rpc_version") != RPC_VERSION:
            raise RpcError(-32001, f"incompatible rpc_version {p.get('rpc_version')!r}; server speaks {RPC_VERSION}")
        self.initialized = True
        return {"server_version": __version__, "rpc_version": RPC_VERSION, "capabilities": sorted(self.methods)}

    def m_create(self, p: JSON, rid: Any) -> JSON:
        pr = Project.create(Path(self.req(p, "path", str)), self.req(p, "name", str, optional=True), self.req(p, "overrides", dict, optional=True))
        return {"project": str(pr.root), "name": pr.name}

    def m_open(self, p: JSON, rid: Any) -> JSON:
        pr = self.proj({"project": self.req(p, "path", str), "overrides": p.get("overrides")})
        return {"project": str(pr.root), "name": pr.name, "inputs": pr._inputs(), "has_ir": pr.store.exists("ir/project.ir.json")}

    def m_import(self, p: JSON, rid: Any) -> JSON:
        paths = self.req(p, "paths", list)
        if not paths or not all(isinstance(x, str) for x in paths):
            raise RpcError(-32602, "paths must be a non-empty list of strings")
        declared = self.req(p, "declared", dict, optional=True)
        if declared is not None and not set(declared) <= {"page_hint", "viewport_width", "device_pixel_ratio"}:
            raise RpcError(-32602, "declared accepts only page_hint, viewport_width, device_pixel_ratio")
        return {"inputs": self.proj(p).import_images([Path(x) for x in paths], declared)}

    def m_analysis(self, p: JSON, rid: Any) -> JSON:
        pr = self.proj(p)
        r = pr.reconstruct(listener=self.progress(rid), cancel=self.cancels[rid])
        return {"content_hash": r.content_hash, "nodes": r.nodes, "pages": r.pages, "quality": r.quality, "diagnostics": r.diagnostics}

    def m_ir(self, p: JSON, rid: Any) -> JSON:
        return {"ir": self.proj(p).ir}

    def m_generate(self, p: JSON, rid: Any) -> JSON:
        pr = self.proj(p)
        target = self.req(p, "target", str, optional=True) or "html"
        if target not in ("html", "react"):
            raise RpcError(-32602, f"unsupported generation target {target!r}")
        out = self.req(p, "out", str, optional=True)
        # the client chooses a location inside the project only; exporting elsewhere is a CLI/API decision of the user, not a UI request
        out_dir = pr.store.ws.resolve(out) if out else None
        return pr.generate(target, out_dir, self.req(p, "options", dict, optional=True), overwrite=bool(p.get("overwrite", True)))

    def m_render(self, p: JSON, rid: Any) -> JSON:
        pr = self.proj(p)
        return {"renders": [{"screen": s, "screenshot": str(pr.render(p.get("target", "html"), screen=s).screenshot)} for s in sorted(pr.ir["screens"])]}

    def m_compare(self, p: JSON, rid: Any) -> JSON:
        r = self.proj(p).evaluate(p.get("screen"))
        return {k: r[k] for k in ("metrics", "worst_nodes", "exclusions", "unavailable_metrics", "artifacts", "size")}

    def m_models(self, p: JSON, rid: Any) -> JSON:
        from ..cli.main import models_dir

        return {"models": ModelStore(models_dir()).list(), "directory": str(models_dir())}

    def m_settings(self, p: JSON, rid: Any) -> JSON:
        return {"config": scrub(self.proj(p).cfg)}

    def m_status(self, p: JSON, rid: Any) -> JSON:
        pr = self.proj(p)
        has_ir = pr.store.exists("ir/project.ir.json")
        screens: list[JSON] = []
        if has_ir:
            ir = pr.ir
            for sid, s in sorted(ir["screens"].items()):
                screens.append({"id": sid, "page": s["resolved"]["page"], "page_name": ir["pages"][s["resolved"]["page"]]["name"], "viewport_width": s["resolved"]["viewport_width"],
                                "rendered": pr.store.exists(f"renders/{sid}.render.json"), "evaluated": pr.store.exists(f"evaluations/{sid}/report.json")})
        return {"project": str(pr.root), "name": pr.name, "inputs": pr._inputs(), "has_ir": has_ir, "screens": screens,
                "reconciliation": pr.store.exists("ir/reconciliation.json")}

    def m_reconcile(self, p: JSON, rid: Any) -> JSON:
        pr = self.proj(p)
        if not pr.store.exists("ir/reconciliation.json"):
            raise RpcError(-32004, "no reconciliation report: run analysis first")
        return {"report": pr.store.read_json("ir/reconciliation.json")}

    def m_source_image(self, p: JSON, rid: Any) -> JSON:
        pr = self.proj(p)
        scr = self.req(p, "screen", str)
        ir = pr.ir
        if scr not in ir["screens"]:
            raise RpcError(-32602, f"unknown screen {scr!r}")
        sha = ir["sources"][ir["screens"][scr]["source"]]["sha256"]
        data = pr.store.artifacts.path(sha, ".png").read_bytes()
        return {"media_type": "image/png", "data_base64": base64.b64encode(data).decode("ascii"), "bytes": len(data)}

    def m_artifact(self, p: JSON, rid: Any) -> JSON:
        """Read one file of the project for display. Only project-relative paths under a fixed set of directories and file types; size-limited."""
        pr = self.proj(p)
        rel = self.req(p, "path", str)
        target = pr.store.ws.resolve(rel)  # rejects absolute paths, '..', and symlink escapes
        root = pr.store.ws.root
        top = target.relative_to(root).parts[0] if target != root and target.is_relative_to(root) else ""
        if top not in ARTIFACT_DIRS:
            raise RpcError(-32602, f"path is not in a readable project area ({', '.join(ARTIFACT_DIRS)})")
        mt = ARTIFACT_TYPES.get(target.suffix.lower())
        if mt is None:
            raise RpcError(-32602, f"file type {target.suffix!r} is not readable through this method")
        if not target.is_file():
            raise RpcError(-32004, f"no such file: {rel}")
        size = target.stat().st_size
        if size > MAX_ARTIFACT:
            raise RpcError(-32602, f"file is {size} bytes; the limit is {MAX_ARTIFACT}")
        data = target.read_bytes()
        if mt.startswith("image/"):
            return {"media_type": mt, "data_base64": base64.b64encode(data).decode("ascii"), "bytes": size}
        return {"media_type": mt, "text": data.decode("utf-8", errors="replace"), "bytes": size}

    def m_refine(self, p: JSON, rid: Any) -> JSON:
        pr = self.proj(p)
        mi = self.num(p, "max_iterations", 1, 20)
        return pr.refine(screen=self.req(p, "screen", str, optional=True), max_iterations=int(mi) if mi is not None else None, apply=bool(p.get("apply", False)),
                         listener=self.progress(rid), cancel=self.cancels[rid])

    def m_refine_list(self, p: JSON, rid: Any) -> JSON:
        pr = self.proj(p)
        base = pr.root / "refinements"
        runs = []
        if base.is_dir():
            for d in sorted(q for q in base.iterdir() if q.is_dir() and q.name.startswith("run-")):
                f = d / "run.json"
                if f.is_file():
                    r = json.loads(f.read_text(encoding="utf-8"))
                    runs.append({"name": d.name, "path": f"refinements/{d.name}", "screen": r["config"]["screen"], "before": r["before"], "after": r["after"], "improved": r["improved"],
                                 "stop_reason": r["stop_reason"], "applied": r["applied"], "iterations": r["iterations"]})
        return {"runs": runs}


def main() -> None:
    Server(sys.stdin.buffer, sys.stdout.buffer).serve()


if __name__ == "__main__":
    main()
