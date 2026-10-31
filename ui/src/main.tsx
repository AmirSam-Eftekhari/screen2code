import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { Rpc } from "./rpc";

const host = window.s2cHost;
const root = createRoot(document.getElementById("root")!);
if (!host) {
  root.render(<div style={{ padding: 24 }} data-testid="no-host">No Screen2Code host is attached. Open this UI from the desktop shell (or a test harness that provides <code>window.s2cHost</code>).</div>);
} else {
  root.render(<App rpc={new Rpc(host)} />);
}
