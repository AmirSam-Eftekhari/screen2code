// Attaches the Tauri shell as the UI's host. Does nothing when another host (e.g. a test harness) is already present or Tauri is absent.
(function () {
  if (window.s2cHost || !window.__TAURI__ || !window.__TAURI__.core) return;
  const invoke = window.__TAURI__.core.invoke;
  window.s2cHost = {
    send: function (message) { invoke("s2c_send", { message: message }); },
    poll: function () { return invoke("s2c_poll"); },
  };
})();
