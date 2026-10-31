import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactElement, ReactNode } from "react";
import { Json, Progress, Rpc, RpcError } from "./rpc";

// ---------------------------------------------------------------- shared state
interface Task { id: number; label: string; stage: string; progress: number; message: string }
interface Ctx {
  rpc: Rpc;
  project: string;
  status: Json | null;
  ir: Json | null;
  overrides: Json;
  setOverrides: (o: Json) => void;
  task: Task | null;
  error: { code: number | string; message: string; data?: Json } | null;
  setError: (e: Ctx["error"]) => void;
  setProject: (p: string) => void;
  refresh: () => Promise<void>;
  run: <T = Json>(label: string, method: string, params?: Json, opts?: { cancellable?: boolean }) => Promise<T | undefined>;
  cancel: () => void;
}
const C = createContext<Ctx>(null as unknown as Ctx);
const useC = () => useContext(C);

const pretty = (v: Json) => JSON.stringify(v, null, 2);
const fmt = (n: Json) => (typeof n === "number" ? (Number.isInteger(n) ? String(n) : n.toFixed(4)) : String(n));

function useImage(method: string, params: Json | null): { url: string | null; err: string | null } {
  const { rpc, project, overrides } = useC();
  const [state, set] = useState<{ url: string | null; err: string | null }>({ url: null, err: null });
  const key = params ? JSON.stringify(params) : "";
  useEffect(() => {
    if (!params) { set({ url: null, err: null }); return; }
    let live = true;
    rpc.call(method, { project, overrides, ...params })
      .then((r) => live && set({ url: `data:${r.media_type};base64,${r.data_base64}`, err: null }))
      .catch((e: RpcError) => live && set({ url: null, err: e.message }));
    return () => { live = false; };
  }, [key, project]); // eslint-disable-line react-hooks/exhaustive-deps
  return state;
}

function Img({ method, params, alt, testid }: { method: string; params: Json | null; alt: string; testid?: string }) {
  const { url, err } = useImage(method, params);
  if (err) return <div className="muted" data-testid={testid ? `${testid}-missing` : undefined}>{alt}: not available ({err})</div>;
  if (!url) return <div className="muted">{params ? "loading…" : "—"}</div>;
  return <img src={url} alt={alt} data-testid={testid} style={{ maxWidth: "100%" }} />;
}

const Badge = ({ kind, children }: { kind: string; children: ReactNode }) => <span className={`badge ${kind}`}>{children}</span>;

function KV({ rows }: { rows: [string, Json][] }) {
  return <table className="kv"><tbody>{rows.map(([k, v]) => <tr key={k}><th>{k}</th><td>{typeof v === "object" ? <pre>{pretty(v)}</pre> : String(v)}</td></tr>)}</tbody></table>;
}

// ---------------------------------------------------------------- views
function ProjectView() {
  const { project, setProject, status, run, overrides, refresh, task } = useC();
  const [path, setPath] = useState(project);
  const [files, setFiles] = useState("");
  const [hint, setHint] = useState("");
  const [width, setWidth] = useState("");
  const open = async () => { if (await run("Opening project", "project.open", { path, overrides })) { setProject(path); } };
  const create = async () => { if (await run("Creating project", "project.create", { path, name: path.split(/[\\/]/).pop() || "project", overrides })) setProject(path); };
  const imp = async () => {
    const declared: Json = {};
    if (hint) declared.page_hint = hint;
    if (width) declared.viewport_width = Number(width);
    await run("Importing", "import.images", { project, paths: files.split("\n").map((s) => s.trim()).filter(Boolean), declared: Object.keys(declared).length ? declared : undefined, overrides });
    await refresh();
  };
  const analyze = async () => { await run("Analyzing", "analysis.start", { project, overrides }, { cancellable: true }); await refresh(); };
  return (
    <div>
      <h2>Project</h2>
      <div className="row">
        <input data-testid="project-path" value={path} onChange={(e) => setPath(e.target.value)} placeholder="project directory" />
        <button data-testid="project-create" onClick={create} disabled={!!task}>Create</button>
        <button data-testid="project-open" onClick={open} disabled={!!task}>Open</button>
      </div>
      {project && (
        <>
          <h3>Import screenshots</h3>
          <p className="muted">One path per line. Declaring the same page name for several screens asks Screen2Code to reconcile them as one responsive page; it will say so if it cannot.</p>
          <textarea data-testid="import-paths" rows={3} value={files} onChange={(e) => setFiles(e.target.value)} />
          <div className="row">
            <input data-testid="import-hint" value={hint} onChange={(e) => setHint(e.target.value)} placeholder="page name (optional)" />
            <input data-testid="import-width" value={width} onChange={(e) => setWidth(e.target.value)} placeholder="viewport width px (optional)" />
            <button data-testid="import-run" onClick={imp} disabled={!!task || !files.trim()}>Import</button>
          </div>
          <h3>Inputs</h3>
          <table data-testid="inputs"><thead><tr><th>source</th><th>declared</th></tr></thead>
            <tbody>{(status?.inputs ?? []).map((i: Json, k: number) => <tr key={k}><td>{i.path ?? i.name ?? i.source ?? i.sha256}</td><td>{i.declared ? pretty(i.declared) : ""}</td></tr>)}</tbody></table>
          <button data-testid="analyze" className="primary" onClick={analyze} disabled={!!task || !(status?.inputs?.length)}>Analyze</button>
          {status?.has_ir && <p data-testid="analysis-done">IR present: {status.screens.length} screen(s).</p>}
        </>
      )}
    </div>
  );
}

function useScreen(): [string, (s: string) => void, Json[]] {
  const { status } = useC();
  const screens: Json[] = status?.screens ?? [];
  const [scr, setScr] = useState("");
  useEffect(() => { if (screens.length && !screens.some((s) => s.id === scr)) setScr(screens[0].id); }, [screens, scr]);
  return [scr, setScr, screens];
}
function ScreenPicker({ scr, setScr, screens }: { scr: string; setScr: (s: string) => void; screens: Json[] }) {
  return <select data-testid="screen-select" value={scr} onChange={(e) => setScr(e.target.value)}>{screens.map((s) => <option key={s.id} value={s.id}>{s.page_name} @ {s.viewport_width}px</option>)}</select>;
}
function NeedIR() { return <p className="muted" data-testid="need-ir">No IR yet. Import screenshots and run Analyze first.</p>; }

function RegionsView() {
  const { ir } = useC();
  const [scr, setScr, screens] = useScreen();
  const [sel, setSel] = useState<string | null>(null);
  if (!ir || !screens.length) return <NeedIR />;
  const screen = ir.screens[scr];
  const regionNode: Record<string, string> = {};
  for (const [nid, r] of Object.entries<Json>(ir.realizations[scr]?.nodes ?? {})) for (const rid of r.regions) regionNode[rid] = regionNode[rid] ?? nid;
  const regions = Object.values<Json>(ir.regions).filter((r) => r.source === screen?.source);
  const src = ir.sources[screen?.source];
  const W = src?.width ?? 1, H = src?.height ?? 1;
  return (
    <div>
      <h2>Regions</h2>
      <ScreenPicker {...{ scr, setScr, screens }} />
      <p className="muted" data-testid="region-count">{regions.length} measured region(s). Rectangles are observations; click one to see the node it realizes.</p>
      <div className="split">
        <div className="stage" style={{ position: "relative" }}>
          <Img method="source.image" params={{ screen: scr }} alt="original" testid="original-image" />
          <svg viewBox={`0 0 ${W} ${H}`} className="overlay" data-testid="region-overlay">
            {regions.map((r) => <rect key={r.id} data-testid="region-rect" x={r.rect.x} y={r.rect.y} width={r.rect.w} height={r.rect.h} className={sel === r.id ? "sel" : ""} onClick={() => setSel(r.id)} />)}
          </svg>
        </div>
        <div>
          {sel ? <div data-testid="region-detail"><KV rows={[["region", sel], ["rect", ir.regions[sel].rect], ["basis", ir.regions[sel].basis], ["node", regionNode[sel] ?? "(none)"], ["node kind", ir.nodes[regionNode[sel]]?.kind ?? ""]]} /></div> : <p className="muted">Select a region.</p>}
        </div>
      </div>
    </div>
  );
}

function TreeNode({ ir, id, sel, onSel, depth }: { ir: Json; id: string; sel: string; onSel: (i: string) => void; depth: number }) {
  const n = ir.nodes[id];
  const label = n.kind === "text" ? JSON.stringify(n.text?.content?.value ?? "").slice(0, 28) : n.kind === "instance" ? `instance ${ir.components[n.instance.component]?.name ?? ""}` : n.role ?? "";
  return (
    <div>
      <div className={`tnode ${sel === id ? "sel" : ""}`} style={{ paddingLeft: depth * 12 }} data-testid="tree-node" onClick={() => onSel(id)}>{n.kind} <span className="muted">{label}</span></div>
      {(n.children ?? []).map((c: string) => <TreeNode key={c} {...{ ir, sel, onSel }} id={c} depth={depth + 1} />)}
    </div>
  );
}

function InspectorView() {
  const { ir } = useC();
  const [pid, setPid] = useState("");
  const [sel, setSel] = useState("");
  if (!ir) return <NeedIR />;
  const pages = Object.values<Json>(ir.pages);
  const page = ir.pages[pid] ?? pages[0];
  const pageId = Object.keys(ir.pages).find((k) => ir.pages[k] === page)!;
  const n = ir.nodes[sel];
  const ev = (id: string) => ir.evidence[id];
  return (
    <div>
      <h2>Inspector</h2>
      <select data-testid="page-select" value={pageId} onChange={(e) => { setPid(e.target.value); setSel(""); }}>{Object.entries<Json>(ir.pages).map(([k, p]) => <option key={k} value={k}>{p.name}</option>)}</select>
      <div className="split">
        <div className="tree" data-testid="tree"><TreeNode ir={ir} id={page.root} sel={sel} onSel={setSel} depth={0} /></div>
        <div data-testid="node-detail">
          {!n ? <p className="muted">Select a node. Each facet shows whether it was observed (evidence) or inferred (method, basis, confidence).</p> : (
            <>
              <h3>{n.kind} <span className="muted">{n.id}</span></h3>
              <KV rows={[["role", n.role ?? "—"], ["status", n.status ?? "—"], ["layout", n.layout ?? "—"], ["size", n.size ?? "—"], ["spacing", n.spacing ?? "—"], ["style", n.style ?? "—"], ["text", n.text ? n.text.content : "—"]]} />
              <h4>Provenance</h4>
              <table data-testid="provenance"><thead><tr><th>facet</th><th>origin</th><th>basis</th><th>confidence</th><th>method</th><th>evidence</th></tr></thead>
                <tbody>{Object.entries<Json>(n.inference ?? {}).map(([f, rec]) => (
                  <tr key={f}><td>{f}</td>
                    <td><Badge kind={rec.basis === "measured" || rec.basis === "reported" ? "obs" : "inf"}>{n.origin?.[f] ?? (rec.basis === "default" ? "default" : "inferred")}</Badge></td>
                    <td>{rec.basis}</td><td>{rec.confidence != null ? fmt(rec.confidence) : ""}</td><td>{rec.method}</td>
                    <td>{(rec.supports ?? []).map((s: string) => <div key={s} className="muted">{ev(s)?.kind ?? s}</div>)}</td></tr>))}</tbody></table>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function DesignSystemView() {
  const { ir, status, rpc, project, overrides } = useC();
  const [rep, setRep] = useState<Json | null>(null);
  useEffect(() => { if (status?.reconciliation) rpc.call("reconcile.get", { project, overrides }).then((r) => setRep(r.report)).catch(() => setRep(null)); }, [status?.reconciliation, project]); // eslint-disable-line
  if (!ir) return <NeedIR />;
  const comps = Object.entries<Json>(ir.components ?? {});
  const instances = (cid: string) => Object.values<Json>(ir.nodes).filter((n) => n.kind === "instance" && n.instance.component === cid).length;
  return (
    <div>
      <h2>Design system</h2>
      <h3>Tokens ({Object.keys(ir.tokens ?? {}).length})</h3>
      <table data-testid="tokens"><thead><tr><th>name</th><th>type</th><th>value</th><th>confidence</th></tr></thead>
        <tbody>{Object.values<Json>(ir.tokens ?? {}).map((t) => <tr key={t.id}><td>{t.name}</td><td>{t.type}</td><td>{t.value && typeof t.value === "object" ? JSON.stringify(t.value) : String(t.value)}</td><td>{t.inference?.confidence != null ? fmt(t.inference.confidence) : ""}</td></tr>)}</tbody></table>
      <h3>Components ({comps.length})</h3>
      <table data-testid="components"><thead><tr><th>name</th><th>instances</th></tr></thead>
        <tbody>{comps.map(([id, c]) => <tr key={id}><td>{c.name}</td><td>{instances(id)}</td></tr>)}</tbody></table>
      {rep && (
        <>
          <h3>Reconciliation decisions</h3>
          <div data-testid="reconciliation">
            {(rep.pages?.groups ?? []).map((g: Json, k: number) => <div key={k} className="card"><b>{g.page}</b>: <Badge kind={g.decision === "unified" ? "obs" : "inf"}>{g.decision}</Badge> widths {JSON.stringify(g.widths)}
              {(g.separate ?? []).map((s: Json, i: number) => <div key={i} className="muted">{(s.reasons ?? [s.reason]).join("; ")}</div>)}</div>)}
          </div>
          <h3>Near misses (reported, not merged)</h3>
          <pre data-testid="near-misses">{pretty({ colors: rep.tokens?.near_miss_colors ?? [], components: rep.components?.near_misses ?? [], skipped_responsive: rep.components?.skipped_responsive ?? [] })}</pre>
        </>
      )}
    </div>
  );
}

function GenerateView() {
  const { project, overrides, run, rpc, task, refresh } = useC();
  const [target, setTarget] = useState("html");
  const [res, setRes] = useState<Json | null>(null);
  const [file, setFile] = useState("");
  const [text, setText] = useState("");
  const gen = async () => { const r = await run("Generating", "generate.run", { project, target, overrides }); if (r) { setRes(r); setFile(""); setText(""); await refresh(); } };
  const open = async (f: string) => { setFile(f); const r = await rpc.call("artifact.read", { project, path: `exports/${target}/${f}`, overrides }).catch((e: RpcError) => ({ text: `not readable: ${e.message}` })); setText(r.text ?? ""); };
  return (
    <div>
      <h2>Generate</h2>
      <div className="row">
        <select data-testid="target-select" value={target} onChange={(e) => setTarget(e.target.value)}><option value="html">HTML/CSS</option><option value="react">React</option></select>
        <button data-testid="generate" className="primary" onClick={gen} disabled={!!task}>Generate</button>
      </div>
      <p className="warn">Generated code is untrusted. It is shown as text and is never executed from this window. HTML is rendered only by the Render step, offline with JavaScript disabled.</p>
      {res && (
        <div className="split">
          <div data-testid="generated-files">{(res.files as string[]).map((f) => <div key={f} className={`tnode ${f === file ? "sel" : ""}`} onClick={() => open(f)}>{f}</div>)}
            {res.report?.limitations && <><h4>Limitations</h4><pre>{pretty(res.report.limitations)}</pre></>}
            {res.report?.deviations && <><h4>Deviations</h4><pre data-testid="deviations">{pretty(res.report.deviations)}</pre></>}</div>
          <pre data-testid="file-text" className="code">{text}</pre>
        </div>
      )}
    </div>
  );
}

const IMAGES: [string, string][] = [["reference", "Original"], ["generated", "Rendered"], ["overlay", "Overlay"], ["difference", "Difference"]];

function EvaluateView() {
  const { project, overrides, run, rpc, task, refresh } = useC();
  const [scr, setScr, screens] = useScreen();
  const [ev, setEv] = useState<Json | null>(null);
  const [rec, setRec] = useState<Json | null>(null);
  const [tab, setTab] = useState("difference");
  const go = async () => {
    if (!(await run("Rendering", "render.run", { project, target: "html", overrides }, { cancellable: true }))) return;
    const r = await run("Evaluating", "compare.get", { project, screen: scr, overrides });
    if (r) {
      setEv(r);
      const rr = await rpc.call("artifact.read", { project, path: `renders/${scr}.render.json`, overrides }).catch(() => null);
      setRec(rr ? JSON.parse(rr.text) : null);
      await refresh();
    }
  };
  if (!screens.length) return <NeedIR />;
  const rel = (abs: string) => abs.replace(/\\/g, "/").replace(/^.*?\/(evaluations|renders)\//, "$1/");
  const art = ev?.artifacts ?? {};
  return (
    <div>
      <h2>Render &amp; evaluate</h2>
      <div className="row"><ScreenPicker {...{ scr, setScr, screens }} /><button data-testid="render-eval" className="primary" onClick={go} disabled={!!task}>Render + evaluate</button></div>
      {ev && (
        <>
          {rec && <p data-testid="sandbox-state" className={rec.chromium_sandbox ? "" : "warn"}>Chromium sandbox: {rec.chromium_sandbox ? "on" : "OFF (explicitly waived for this render)"}; JavaScript: {String(rec.javascript_enabled ?? rec.javascript ?? "disabled")}</p>}
          <div className="tabs">{IMAGES.filter(([k]) => art[k]).map(([k, l]) => <button key={k} data-testid={`tab-${k}`} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>)}</div>
          <Img method="artifact.read" params={art[tab] ? { path: rel(art[tab]) } : null} alt={tab} testid="eval-image" />
          <h3>Metrics</h3>
          <table data-testid="metrics"><tbody>{Object.entries<Json>(ev.metrics).map(([k, v]) => <tr key={k}><th>{k}</th><td>{typeof v === "object" ? Object.entries<Json>(v).filter(([, x]) => typeof x === "number").map(([a, x]) => <span key={a} className="chip">{a}: {fmt(x)}</span>) : fmt(v)}</td></tr>)}</tbody></table>
          {(ev.unavailable_metrics ?? []).length > 0 && <><h4>Unavailable metrics</h4><pre data-testid="unavailable">{pretty(ev.unavailable_metrics)}</pre></>}
          {(ev.exclusions ?? []).length > 0 && <><h4>Exclusions</h4><pre>{pretty(ev.exclusions)}</pre></>}
          <h4>Worst nodes</h4><pre data-testid="worst-nodes">{pretty(ev.worst_nodes ?? [])}</pre>
        </>
      )}
    </div>
  );
}

function RefineView() {
  const { project, overrides, run, rpc, task, refresh } = useC();
  const [scr, setScr, screens] = useScreen();
  const [iters, setIters] = useState("3");
  const [apply, setApply] = useState(false);
  const [res, setRes] = useState<Json | null>(null);
  const [runs, setRuns] = useState<Json[]>([]);
  const [pick, setPick] = useState<string[]>([]);
  const list = useCallback(async () => { const r = await rpc.call("refine.list", { project, overrides }).catch(() => ({ runs: [] })); setRuns(r.runs); }, [rpc, project, overrides]);
  useEffect(() => { if (project) list(); }, [project]); // eslint-disable-line
  const go = async () => { const r = await run("Refining", "refine.run", { project, screen: scr, max_iterations: Number(iters), apply, overrides }, { cancellable: true }); if (r) { setRes(r); await list(); await refresh(); } };
  if (!screens.length) return <NeedIR />;
  const chosen = runs.filter((r) => pick.includes(r.name));
  return (
    <div>
      <h2>Refine</h2>
      <div className="row">
        <ScreenPicker {...{ scr, setScr, screens }} />
        <input data-testid="refine-iters" value={iters} onChange={(e) => setIters(e.target.value)} size={3} />
        <label><input type="checkbox" data-testid="refine-apply" checked={apply} onChange={(e) => setApply(e.target.checked)} /> apply result to IR</label>
        <button data-testid="refine-run" className="primary" onClick={go} disabled={!!task}>Run refinement</button>
      </div>
      <p className="muted">Refinement only keeps a change that improves the measured composite; without “apply”, the project IR is not modified.</p>
      {res && <div data-testid="refine-result" className="card"><KV rows={[["before", res.before], ["after", res.after], ["improved", res.improved], ["stop reason", res.stop_reason], ["applied", res.applied]]} /></div>}
      <h3>Runs</h3>
      <table data-testid="refine-runs"><thead><tr><th></th><th>run</th><th>before</th><th>after</th><th>improved</th><th>stop reason</th><th>applied</th></tr></thead>
        <tbody>{runs.map((r) => <tr key={r.name}><td><input type="checkbox" checked={pick.includes(r.name)} onChange={(e) => setPick(e.target.checked ? [...pick.slice(-1), r.name] : pick.filter((x) => x !== r.name))} /></td>
          <td>{r.name}</td><td>{fmt(r.before)}</td><td>{fmt(r.after)}</td><td>{String(r.improved)}</td><td>{r.stop_reason}</td><td>{String(r.applied)}</td></tr>)}</tbody></table>
      {chosen.length === 2 && <div data-testid="refine-compare" className="split">{chosen.map((r) => <div key={r.name}><h4>{r.name}</h4><Img method="artifact.read" params={{ path: `${r.path}/final/evaluation/difference.png` }} alt={`${r.name} difference`} /></div>)}
        <p>Δ after: {fmt(chosen[1].after - chosen[0].after)}</p></div>}
    </div>
  );
}

function ReportsView() {
  const { project, overrides, rpc, status } = useC();
  const [text, setText] = useState("");
  const [name, setName] = useState("");
  const open = async (title: string, path: string) => { setName(title); const r = await rpc.call("artifact.read", { project, path, overrides }).catch((e: RpcError) => ({ text: `not available: ${e.message}` })); setText(r.text); };
  const items: [string, string][] = [];
  if (status?.reconciliation) items.push(["reconciliation.json", "ir/reconciliation.json"]);
  for (const s of status?.screens ?? []) if (s.evaluated) items.push([`${s.page_name} @ ${s.viewport_width}px: report`, `evaluations/${s.id}/REPORT.md`]);
  return (
    <div><h2>Reports &amp; artifacts</h2>
      <div className="split"><div data-testid="report-list">{items.length === 0 && <p className="muted">Nothing yet.</p>}{items.map(([t, p]) => <div key={p} className={`tnode ${name === t ? "sel" : ""}`} onClick={() => open(t, p)}>{t}</div>)}</div>
        <pre className="code" data-testid="report-text">{text}</pre></div></div>
  );
}

function SettingsView() {
  const { project, rpc, overrides, setOverrides } = useC();
  const [cfg, setCfg] = useState<Json | null>(null);
  const [models, setModels] = useState<Json | null>(null);
  const waived = !!overrides?.render?.allow_no_sandbox;
  const redacting = !!overrides?.privacy?.redact_text;
  useEffect(() => { if (project) rpc.call("settings.get", { project, overrides }).then((r) => setCfg(r.config)).catch(() => setCfg(null)); rpc.call("models.list", {}).then(setModels).catch(() => setModels(null)); }, [project, waived]); // eslint-disable-line
  const toggle = (on: boolean) => {
    if (on && !window.confirm("Run Chromium without its sandbox? Only do this inside a container or VM you already trust. It will be recorded on every render.")) return;
    setOverrides(on ? { ...overrides, render: { ...(overrides.render ?? {}), allow_no_sandbox: true } } : { ...overrides, render: { ...(overrides.render ?? {}), allow_no_sandbox: false } });
  };
  return (
    <div><h2>Settings</h2>
      <label><input type="checkbox" data-testid="waive-sandbox" checked={waived} onChange={(e) => toggle(e.target.checked)} /> Allow Chromium without sandbox (unsafe, explicit waiver)</label>
      <div><label><input type="checkbox" data-testid="redact-text" checked={redacting} onChange={(e) => setOverrides({ ...overrides, privacy: { ...(overrides.privacy ?? {}), redact_text: e.target.checked } })} /> Redact recognized text on the next Analyze</label></div>
      <p className="muted">Removes recognized text from the IR, evidence and exports. It does not mask pixels: the imported screenshot and extracted image assets stay in the project folder, so this does not make a project safe to share.</p>
      <h3>Effective configuration (secrets removed)</h3><pre data-testid="config">{cfg ? pretty(cfg) : "—"}</pre>
      <h3>Models</h3><pre data-testid="models">{models ? pretty(models) : "—"}</pre></div>
  );
}

// ---------------------------------------------------------------- shell
const VIEWS: [string, string, () => ReactElement][] = [
  ["project", "Project", ProjectView], ["regions", "Regions", RegionsView], ["inspector", "Inspector", InspectorView], ["design", "Design system", DesignSystemView],
  ["generate", "Generate", GenerateView], ["evaluate", "Render & evaluate", EvaluateView], ["refine", "Refine", RefineView], ["reports", "Reports", ReportsView], ["settings", "Settings", SettingsView],
];

export function App({ rpc }: { rpc: Rpc }) {
  const [view, setView] = useState("project");
  const [project, setProject] = useState("");
  const [status, setStatus] = useState<Json | null>(null);
  const [ir, setIr] = useState<Json | null>(null);
  const [overrides, setOverrides] = useState<Json>({});
  const [task, setTask] = useState<Task | null>(null);
  const [error, setError] = useState<Ctx["error"]>(null);
  const [ready, setReady] = useState<string>("connecting…");
  const taskRef = useRef<Task | null>(null);
  taskRef.current = task;

  useEffect(() => {
    rpc.call("initialize", { rpc_version: 1 }).then((r) => setReady(`connected (sidecar ${r.version ?? r.server ?? "ok"})`)).catch((e: RpcError) => setReady(`sidecar error: ${e.message}`));
    return rpc.onProgress((p: Progress) => { if (taskRef.current && p.id === taskRef.current.id) setTask({ ...taskRef.current, stage: p.stage, progress: p.progress, message: p.message }); });
  }, [rpc]);

  const refresh = useCallback(async () => {
    if (!project) { setStatus(null); setIr(null); return; }
    try {
      const st = await rpc.call("project.status", { project, overrides });
      setStatus(st);
      setIr(st.has_ir ? (await rpc.call("ir.get", { project, overrides })).ir : null);
    } catch (e) { const x = e as RpcError; setError({ code: x.code, message: x.message, data: x.data }); }
  }, [rpc, project, overrides]);
  useEffect(() => { refresh(); }, [project]); // eslint-disable-line

  const run: Ctx["run"] = useCallback(async (label, method, params = {}) => {
    const call = rpc.start(method, params);
    setTask({ id: call.id, label, stage: "", progress: 0, message: "" });
    setError(null);
    try { return await call.promise; }
    catch (e) { const x = e as RpcError; setError({ code: x.data?.code ?? x.code, message: x.message, data: x.data }); return undefined; }
    finally { setTask(null); }
  }, [rpc]);
  const cancel = useCallback(() => { if (taskRef.current) rpc.cancel(taskRef.current.id); }, [rpc]);

  const ctx = useMemo<Ctx>(() => ({ rpc, project, status, ir, overrides, setOverrides, task, error, setError, setProject, refresh, run, cancel }), [rpc, project, status, ir, overrides, task, error, refresh, run, cancel]);
  const View = VIEWS.find((v) => v[0] === view)![2];
  return (
    <C.Provider value={ctx}>
      <div className="app">
        <nav>
          <div className="brand">Screen2Code</div>
          {VIEWS.map(([id, label]) => <button key={id} data-testid={`nav-${id}`} className={view === id ? "on" : ""} onClick={() => setView(id)}>{label}</button>)}
          <div className="muted small" data-testid="connection">{ready}</div>
        </nav>
        <main>
          {overrides?.render?.allow_no_sandbox && <div className="banner warn" data-testid="sandbox-banner">Chromium sandbox is waived for this session.</div>}
          {task && <div className="banner" data-testid="task"><b>{task.label}</b> {task.stage && `· ${task.stage}`} {task.message && `· ${task.message}`}
            <progress value={task.progress} max={1} /> <button data-testid="cancel" onClick={cancel}>Cancel</button></div>}
          {error && <div className="banner err" data-testid="error"><b>{String(error.code)}</b> {error.message} <button onClick={() => setError(null)}>dismiss</button>
            {error.data?.diagnostics && <pre>{pretty(error.data.diagnostics)}</pre>}</div>}
          <View />
        </main>
      </div>
    </C.Provider>
  );
}
