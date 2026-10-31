// JSON-RPC 2.0 client for the Screen2Code sidecar. Transport-agnostic: the host (Tauri shell or a test harness) supplies `window.s2cHost`.
// The host owns Content-Length framing and the process; this file only produces/consumes JSON message strings.

export type Json = any; // eslint-disable-line @typescript-eslint/no-explicit-any

export interface S2cHost {
  /** Send one JSON-RPC message (a JSON string) to the sidecar. */
  send(message: string): void;
  /** Optional: return messages received from the sidecar since the last call (used when the host cannot push). */
  poll?(): Promise<string[]>;
}

declare global {
  interface Window {
    s2cHost?: S2cHost;
    __s2cReceive?: (message: string) => void;
  }
}

export class RpcError extends Error {
  code: number;
  data: Json;
  constructor(code: number, message: string, data?: Json) {
    super(message);
    this.code = code;
    this.data = data;
  }
}

export interface Progress {
  id: number;
  stage: string;
  status: string;
  progress: number;
  message: string;
}

export interface Call<T> {
  id: number;
  promise: Promise<T>;
}

type Pending = { resolve: (v: Json) => void; reject: (e: RpcError) => void };

export class Rpc {
  private nextId = 1;
  private pending = new Map<number, Pending>();
  private progressListeners = new Set<(p: Progress) => void>();
  private host: S2cHost;

  constructor(host: S2cHost) {
    this.host = host;
    window.__s2cReceive = (m: string) => this.receive(m);
    if (host.poll) {
      const poll = host.poll.bind(host);
      setInterval(async () => {
        for (const m of await poll()) this.receive(m);
      }, 40);
    }
  }

  private receive(raw: string): void {
    let msg: Json;
    try {
      msg = JSON.parse(raw);
    } catch {
      return; // a malformed frame from the sidecar is dropped; pending calls time out in the caller's UI state
    }
    if (msg.method === "progress" && msg.params) {
      this.progressListeners.forEach((l) => l(msg.params as Progress));
      return;
    }
    if (msg.id == null) return;
    const p = this.pending.get(msg.id);
    if (!p) return;
    this.pending.delete(msg.id);
    if (msg.error) p.reject(new RpcError(msg.error.code, msg.error.message, msg.error.data));
    else p.resolve(msg.result);
  }

  start<T = Json>(method: string, params: Record<string, Json> = {}): Call<T> {
    const id = this.nextId++;
    const promise = new Promise<T>((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
    });
    this.host.send(JSON.stringify({ jsonrpc: "2.0", id, method, params }));
    return { id, promise };
  }

  call<T = Json>(method: string, params: Record<string, Json> = {}): Promise<T> {
    return this.start<T>(method, params).promise;
  }

  cancel(id: number): void {
    this.host.send(JSON.stringify({ jsonrpc: "2.0", method: "$/cancel", params: { id } }));
  }

  onProgress(fn: (p: Progress) => void): () => void {
    this.progressListeners.add(fn);
    return () => this.progressListeners.delete(fn);
  }
}
