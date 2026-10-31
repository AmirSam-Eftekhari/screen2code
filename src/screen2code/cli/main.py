"""Command-line interface (ARCHITECTURE section 7). A thin layer over ``screen2code.api``; no engine logic lives here."""
from __future__ import annotations

import functools
import json
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any, Callable

import click

from .. import __version__
from ..api import Project
from ..core import ERROR_REGISTRY, S2CError
from ..core.errors import EXIT
from ..core.models import ModelManifest, ModelStore
from ..ir import SCHEMA_VERSION, migrate, validate
from ..ir.migrate import MigrationError


def emit(ctx: click.Context, obj: Any, human: Callable[[], str] | None = None) -> None:
    if ctx.obj["json"]:
        click.echo(json.dumps(obj, indent=2, sort_keys=True, default=str))
    elif human:
        click.echo(human())


def handled(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Map S2CError to stable exit codes with actionable output; never swallow unexpected errors silently."""

    @functools.wraps(fn)
    @click.pass_context
    def wrapper(ctx: click.Context, *a: Any, **kw: Any) -> Any:
        try:
            return ctx.invoke(fn, *a, **kw)
        except S2CError as e:
            if ctx.obj["json"]:
                click.echo(json.dumps({"error": e.to_dict()}, indent=2, sort_keys=True))
            else:
                click.echo(f"error: {e}", err=True)
                for d in e.details.get("diagnostics", [])[:10]:
                    click.echo(f"  {d['code']} {d['path']}: {d['message']}", err=True)
            ctx.exit(e.exit_code)
        except (click.ClickException, click.exceptions.Exit):
            raise
        except Exception as e:  # noqa: BLE001
            if ctx.obj["debug"]:
                raise
            msg = f"unexpected {type(e).__name__}: {e}"
            click.echo(json.dumps({"error": {"code": "S2C-INTERNAL", "message": msg}}) if ctx.obj["json"] else f"error: {msg} (re-run with --debug for a traceback)", err=not ctx.obj["json"])
            ctx.exit(EXIT["general"])

    return wrapper


def progress(ctx: click.Context) -> Callable[[Any], None]:
    def cb(ev: Any) -> None:
        if not ctx.obj["json"] and not ctx.obj["quiet"] and ev.status in ("running", "failed", "degraded"):
            click.echo(f"[{ev.stage}] {ev.status}" + (f": {ev.message}" if ev.message else ""), err=True)
    return cb


def overrides(ctx: click.Context) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if ctx.obj["allow_no_sandbox"]:
        out["render"] = {"allow_no_sandbox": True}
    if ctx.obj["redact_text"]:
        out["privacy"] = {"redact_text": True}
    return out


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output (suitable for CI).")
@click.option("--quiet", is_flag=True, help="Suppress progress output.")
@click.option("--debug", is_flag=True, help="Show tracebacks for unexpected errors.")
@click.option("--allow-no-sandbox", is_flag=True, help="Render without the Chromium sandbox (explicit opt-in; JavaScript stays disabled, network blocked).")
@click.option("--redact-text", is_flag=True, help="Remove recognized text from the IR, evidence and exports (text only: the screenshot and extracted raster assets stay on disk; see docs/SECURITY.md).")
@click.version_option(__version__, prog_name="screen2code")
@click.pass_context
def cli(ctx: click.Context, as_json: bool, quiet: bool, debug: bool, allow_no_sandbox: bool, redact_text: bool) -> None:
    """Screen2Code: see it, understand it, rebuild it."""
    ctx.obj = {"json": as_json, "quiet": quiet, "debug": debug, "allow_no_sandbox": allow_no_sandbox, "redact_text": redact_text}


@cli.command()
@click.argument("path", type=click.Path(path_type=Path))
@click.option("--name", default=None)
@handled
@click.pass_context
def init(ctx: click.Context, path: Path, name: str | None) -> None:
    """Create a new project directory."""
    p = Project.create(path, name)
    emit(ctx, {"project": str(p.root)}, lambda: f"created project at {p.root}")


@cli.command(name="import")
@click.argument("project", type=click.Path(path_type=Path))
@click.argument("images", nargs=-1, type=click.Path(exists=True, path_type=Path))
@click.option("--dpr", type=float, default=None, help="Declared device pixel ratio of the screenshots.")
@click.option("--viewport-width", type=float, default=None)
@click.option("--page", default=None, help="Declare the page these screenshots belong to; screenshots of one page with different widths are related.")
@click.option("--manifest", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="TOML manifest with [[screen]] tables (file, page, viewport_width, device_pixel_ratio).")
@handled
@click.pass_context
def import_cmd(ctx: click.Context, project: Path, images: tuple[Path, ...], dpr: float | None, viewport_width: float | None, page: str | None, manifest: Path | None) -> None:
    """Validate and import screenshots (PNG, JPEG, WebP) into a project."""
    declared = {k: v for k, v in (("device_pixel_ratio", dpr), ("viewport_width", viewport_width), ("page_hint", page)) if v is not None}
    proj = Project.open_or_create(project, overrides=overrides(ctx))
    items = proj.import_manifest(manifest) if manifest else proj.import_images(list(images), declared)
    emit(ctx, {"inputs": items}, lambda: "\n".join(f"imported {i['name']} {i['pixel_size']['w']}x{i['pixel_size']['h']} sha256={i['sha256'][:12]}" for i in items))


def _target_project(ctx: click.Context, target: Path, project: Path | None) -> tuple[Project, bool]:
    """``target`` is a project directory, or an image/directory of images to import into ``project``."""
    if (target / "project.toml").exists():
        return Project.open(target, overrides(ctx)), False
    proj = Project.open_or_create(project or (Path.cwd() / f"{target.stem}.s2c"), overrides=overrides(ctx))
    proj.import_images([target])
    return proj, True


@cli.command()
@click.argument("target", type=click.Path(exists=True, path_type=Path))
@click.option("--project", type=click.Path(path_type=Path), default=None, help="Project directory (created if missing) when TARGET is an image or folder.")
@handled
@click.pass_context
def reconstruct(ctx: click.Context, target: Path, project: Path | None) -> None:
    """Analyze screenshots and commit a validated IR (stages S0-S10)."""
    proj, _ = _target_project(ctx, target, project)
    r = proj.reconstruct(listener=progress(ctx))
    emit(ctx, {"project": str(proj.root), "ir": str(r.ir_path), "content_hash": r.content_hash, "nodes": r.nodes, "pages": r.pages, "quality": r.quality},
         lambda: f"committed {r.nodes} nodes on {r.pages} page(s)\n  ir: {r.ir_path}\n  hash: {r.content_hash}\n  partial nodes: {r.quality['partial_nodes']}, uncertain text: {r.quality['uncertain_text']}")


cli.add_command(reconstruct, name="analyze")


@cli.command()
@click.argument("project", type=click.Path(exists=True, path_type=Path))
@click.option("--target", type=click.Choice(["html", "react"]), default="html", show_default=True)
@click.option("--out", type=click.Path(path_type=Path), default=None)
@click.option("--asset-policy", type=click.Choice(["strict", "default", "permissive"]), default=None)
@handled
@click.pass_context
def generate(ctx: click.Context, project: Path, target: str, out: Path | None, asset_policy: str | None) -> None:
    """Generate project files from the committed IR."""
    res = Project.open(project, overrides(ctx)).generate(target, out, {"asset_policy": asset_policy} if asset_policy else None)
    emit(ctx, res, lambda: f"generated {len(res['files'])} files in {res['out']}\n  warnings: {len(res['report']['warnings'])}  uncertain text: {len(res['report']['uncertain_text'])}")


@cli.command()
@click.argument("project", type=click.Path(exists=True, path_type=Path))
@handled
@click.pass_context
def render(ctx: click.Context, project: Path) -> None:
    """Render the generated static HTML in Chromium (JavaScript disabled, offline)."""
    p = Project.open(project, overrides(ctx))
    out = [p.render(screen=s) for s in sorted(p.ir["screens"])]
    emit(ctx, {"screenshots": [str(o.screenshot) for o in out], "browser": out[0].record["browser"], "sandbox": out[0].record["chromium_sandbox"]},
         lambda: "\n".join(f"rendered {o.screenshot} ({o.record['browser']}, sandbox={o.record['chromium_sandbox']})" for o in out))


@cli.command()
@click.argument("project", type=click.Path(exists=True, path_type=Path))
@handled
@click.pass_context
def evaluate(ctx: click.Context, project: Path) -> None:
    """Compare the rendering against the reference and write metrics and artifacts."""
    p = Project.open(project, overrides(ctx))
    reps = {s: p.evaluate(s) for s in sorted(p.ir["screens"])}

    def human() -> str:
        L = []
        for s, r in reps.items():
            m = r["metrics"]
            L.append(f"{s}: SSIM {m['ssim']['ssim']}  edge F1 {m['edge']['edge_f1']}  layout IoU {m['layout']['layout_mean_iou']}  pixel mismatch {m['pixel']['mismatch_fraction']}  composite {m['composite']['composite']}\n  report: {r['artifacts']['markdown']}")
        return "\n".join(L)

    emit(ctx, {s: {"metrics": r["metrics"], "artifacts": r["artifacts"]} for s, r in reps.items()}, human)


@cli.command()
@click.argument("project", type=click.Path(exists=True, path_type=Path))
@click.option("--max-iterations", type=int, default=None, help="Iteration limit (default thresholds.refine.max_iterations).")
@click.option("--time-limit", type=float, default=300.0, show_default=True, help="Wall-clock limit in seconds.")
@click.option("--epsilon", type=float, default=0.002, show_default=True, help="Minimum composite improvement to keep an iteration.")
@click.option("--screen", default=None)
@click.option("--apply", "apply_", is_flag=True, help="Write the improved IR to ir/project.ir.json (the previous IR is backed up).")
@handled
@click.pass_context
def refine(ctx: click.Context, project: Path, max_iterations: int | None, time_limit: float, epsilon: float, screen: str | None, apply_: bool) -> None:
    """Measured refinement: adjust the IR within bounds, re-render, and keep only measured improvements."""
    res = Project.open(project, overrides(ctx)).refine(screen=screen, max_iterations=max_iterations, time_limit_s=time_limit, epsilon=epsilon, apply=apply_, listener=progress(ctx))
    def human() -> str:
        L = [f"refinement {res['run']}", f"  stop: {res['stop_reason']}", f"  improved: {res['improved']} (best iteration {res['best_iteration']})"]
        L += [f"  {k}: {res['before'][k]} -> {res['after'][k]}" for k in res["before"]]
        L += [f"  iter {h['iteration']}: {'kept' if h['accepted'] else 'rejected'} - {h['reason']}" for h in res["iterations"]]
        return "\n".join(L + ([f"  applied; backup {res['backup']}"] if res["applied"] else ["  committed IR unchanged (use --apply)"]))
    emit(ctx, res, human)


@cli.command()
@click.argument("target", type=click.Path(exists=True, path_type=Path))
@click.option("--project", type=click.Path(path_type=Path), default=None)
@handled
@click.pass_context
def run(ctx: click.Context, target: Path, project: Path | None) -> None:
    """Reconstruct, generate, render, and evaluate in one step."""
    proj, _ = _target_project(ctx, target, project)
    res = proj.run(listener=progress(ctx))
    first = next(iter(res["evaluation"].values()))

    def human() -> str:
        m = first["metrics"]
        return (f"project: {proj.root}\ncommitted {res['commit']['nodes']} nodes\ngenerated: {proj.root / 'exports' / 'html'}\n"
                f"SSIM {m['ssim']['ssim']}  edge F1 {m['edge']['edge_f1']}  layout IoU {m['layout']['layout_mean_iou']}  composite {m['composite']['composite']}\nreport: {first['artifacts']['markdown']}")

    emit(ctx, {"project": str(proj.root), **{k: res[k] for k in ("commit", "generation")}, "evaluation": {s: r["metrics"] for s, r in res["evaluation"].items()}}, human)


@cli.group(name="ir")
def ir_group() -> None:
    """Inspect, validate, and migrate IR documents."""


@ir_group.command(name="validate")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--level", type=click.IntRange(0, 3), default=3, show_default=True)
@handled
@click.pass_context
def ir_validate(ctx: click.Context, file: Path, level: int) -> None:
    """Validate an IR file (L0 schema, L1 references, L2 semantics, L3 quality)."""
    try:
        doc = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise S2CError("S2C-IR-INVALID", f"cannot read {file}: {e}") from e
    rep = validate(doc, level)
    emit(ctx, {"valid": rep.ok, "errors": len(rep.errors), "warnings": len(rep.warnings), "diagnostics": [d.to_dict() for d in rep.diagnostics]},
         lambda: "\n".join([str(d) for d in rep.diagnostics] + [("valid" if rep.ok else "INVALID") + f": {len(rep.errors)} error(s), {len(rep.warnings)} warning(s)"]))
    if not rep.ok:
        ctx.exit(EXIT["validation"])


@ir_group.command(name="migrate")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-o", "--output", type=click.Path(path_type=Path), default=None)
@handled
@click.pass_context
def ir_migrate(ctx: click.Context, file: Path, output: Path | None) -> None:
    """Migrate an IR file forward to the current schema version."""
    from ..ir import canonical_dumps

    try:
        out, chain = migrate(json.loads(file.read_text(encoding="utf-8")))
    except MigrationError as e:
        raise S2CError("S2C-IR-INVALID", str(e)) from e
    if output:
        output.write_text(canonical_dumps(out) + "\n", encoding="utf-8")
    emit(ctx, {"chain": chain, "output": str(output) if output else None}, lambda: f"schema versions: {' -> '.join(chain)}" + (f"\nwrote {output}" if output else ""))


@ir_group.command(name="schema")
def ir_schema() -> None:
    """Print the JSON Schema of the current IR version."""
    from ..ir import schema_text

    click.echo(schema_text(), nl=False)


@cli.command()
@click.pass_context
@handled
def doctor(ctx: click.Context) -> None:
    """Check the environment: OCR, browser, fonts, limits."""
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str, required: bool = True) -> None:
        checks.append({"check": name, "ok": ok, "detail": detail, "required": required})

    add("python", sys.version_info >= (3, 11), platform.python_version())
    from ..vision import TesseractOCR

    t = TesseractOCR()
    ok, why = t.available()
    add("ocr (tesseract)", ok, t.version if ok else why)
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            exe = Path(pw.chromium.executable_path)
            add("browser (chromium)", exe.exists(), str(exe) if exe.exists() else "Chromium is not installed (python -m playwright install chromium)")
            sandbox_ok = None
            if exe.exists():
                try:
                    b = pw.chromium.launch(chromium_sandbox=True, timeout=15000)
                    b.close()
                    sandbox_ok = True
                except Exception:  # noqa: BLE001 - reported, not hidden
                    sandbox_ok = False
            add("browser sandbox", bool(sandbox_ok), "available" if sandbox_ok else "unavailable here: rendering needs --allow-no-sandbox (explicit opt-in)", required=False)
    except Exception as e:  # noqa: BLE001
        add("browser (chromium)", False, f"Playwright unavailable: {type(e).__name__}")
    from ..rendering import resolve_fonts

    fonts = resolve_fonts()
    add("fonts", all(f["sha256"] for f in fonts.values()), "; ".join(f"{k}={v['family']}" for k, v in fonts.items()), required=False)
    for mod in ("numpy", "PIL", "cv2", "skimage"):
        try:
            __import__(mod)
            add(f"library {mod}", True, "ok")
        except ImportError:
            add(f"library {mod}", False, "missing")
    bad = [c for c in checks if c["required"] and not c["ok"]]
    emit(ctx, {"ok": not bad, "checks": checks}, lambda: "\n".join(f"{'ok ' if c['ok'] else ('FAIL' if c['required'] else 'note')}  {c['check']}: {c['detail']}" for c in checks))
    if bad:
        ctx.exit(EXIT["provider"])


def models_dir() -> Path:
    from platformdirs import user_data_dir

    return Path(os.environ.get("SCREEN2CODE_MODELS", user_data_dir("Screen2Code")) ) / ("" if os.environ.get("SCREEN2CODE_MODELS") else "models")


@cli.group()
def models() -> None:
    """Manage locally installed models (nothing is bundled or downloaded automatically)."""


@models.command(name="list")
@handled
@click.pass_context
def models_list(ctx: click.Context) -> None:
    items = ModelStore(models_dir()).list()
    emit(ctx, {"models": items, "directory": str(models_dir())}, lambda: "\n".join(f"{m['id']} {m['version']} {m['license_spdx']} ({m['license_class']})" for m in items) or f"no models installed ({models_dir()})")


@models.command(name="install")
@click.option("--manifest", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--file", "file", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--accept-license", is_flag=True, help="Explicitly accept a non-permissive license (bring-your-own models only).")
@handled
@click.pass_context
def models_install(ctx: click.Context, manifest: Path, file: Path, accept_license: bool) -> None:
    """Install a model from a local file after verifying its manifest checksum and license."""
    m = ModelManifest.from_dict(json.loads(manifest.read_text(encoding="utf-8")))
    dest = ModelStore(models_dir()).install_from_file(m, file, accept_license=accept_license)
    emit(ctx, {"installed": str(dest)}, lambda: f"installed {m.id} {m.version} -> {dest}")


@models.command(name="verify")
@click.argument("model_id")
@click.argument("version")
@handled
@click.pass_context
def models_verify(ctx: click.Context, model_id: str, version: str) -> None:
    ModelStore(models_dir()).verify(model_id, version)
    emit(ctx, {"verified": True}, lambda: f"{model_id} {version}: checksum ok")


@models.command(name="remove")
@click.argument("model_id")
@click.argument("version")
@handled
@click.pass_context
def models_remove(ctx: click.Context, model_id: str, version: str) -> None:
    ModelStore(models_dir()).remove(model_id, version)
    emit(ctx, {"removed": True}, lambda: f"removed {model_id} {version}")


@cli.command()
@click.option("--tier", type=click.Choice(["smoke", "standard", "full"]), default="smoke", show_default=True)
@click.option("--seed", type=int, default=1, show_default=True)
@click.option("--out", type=click.Path(path_type=Path), default=Path("benchmarks/results"), show_default=True)
@click.option("--repeat-check", is_flag=True, help="Re-run reconstruction in a fresh project and verify identical IR hashes.")
@handled
@click.pass_context
def benchmark(ctx: click.Context, tier: str, seed: int, out: Path, repeat_check: bool) -> None:
    """Run the reproducible synthetic benchmark and write a pinned run record."""
    from ..benchmark import run_benchmark

    run_dir = out / f"{tier}-seed{seed}"
    run = run_benchmark(tier, seed, run_dir, overrides(ctx), repeat_check=repeat_check)
    slim = {k: run[k] for k in ("run_id", "valid", "missing_pins", "seconds", "structure", "visual", "baselines", "determinism")}
    emit(ctx, {**slim, "directory": str(run_dir)}, lambda: (f"run {run['run_id']} valid={run['valid']} ({run['seconds']} s)\n  structure recall {run['structure']['recall']['mean']}, text CER {run['structure']['text_cer']['mean']}, "
                                                          f"SSIM {run['visual']['ssim']['mean']}\n  summary: {run_dir / 'summary.md'}"))
    if not run["valid"]:
        ctx.exit(EXIT["general"])


@cli.command()
def serve() -> None:
    """Run the JSON-RPC sidecar on stdio (used by the desktop application)."""
    from ..server.main import main as serve_main

    serve_main()


@cli.command(name="errors")
@handled
@click.pass_context
def errors_cmd(ctx: click.Context) -> None:
    """List the stable error codes."""
    emit(ctx, {c: {"category": v[0], "summary": v[1]} for c, v in sorted(ERROR_REGISTRY.items())}, lambda: "\n".join(f"{c}  [{v[0]}]  {v[1]}" for c, v in sorted(ERROR_REGISTRY.items())))


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
