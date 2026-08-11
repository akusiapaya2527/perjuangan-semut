const { execSync, spawn } = require("child_process");
const fs = require("fs");

const URL = process.env.TEST_URL || "http://127.0.0.1:8099/";
const PORT = 9333;
const WAIT = Number(process.env.TEST_WAIT || "25");

const chrome = spawn(
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  [
    "--headless=new",
    "--no-sandbox",
    "--window-size=1000,1000",
    "--user-data-dir=/tmp/ruf-cdp",
    `--remote-debugging-port=${PORT}`,
    "about:blank",
  ],
  { stdio: "ignore" }
);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function getWsUrl() {
  for (let i = 0; i < 40; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/json/list`);
      const tabs = await res.json();
      const page = tabs.find((t) => t.type === "page");
      if (page) return page.webSocketDebuggerUrl;
    } catch (e) {}
    await sleep(250);
  }
  throw new Error("no CDP endpoint");
}

function connect(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    ws.onopen = () => resolve(ws);
    ws.onerror = (e) => reject(e);
  });
}

let id = 0;
function send(ws, method, params) {
  return new Promise((resolve) => {
    const mid = ++id;
    const handler = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id === mid) {
        ws.removeEventListener("message", handler);
        resolve(m.result || m.error);
      }
    };
    ws.addEventListener("message", handler);
    ws.send(JSON.stringify({ id: mid, method, params }));
  });
}

(async () => {
  const ws = await connect(await getWsUrl());
  await send(ws, "Page.enable");
  await send(ws, "Runtime.enable");
  await send(ws, "Console.enable");
  await send(ws, "Emulation.setDeviceMetricsOverride", {
    width: 1000,
    height: 1000,
    deviceScaleFactor: 1,
    mobile: false,
  });

  const logs = [];
  ws.addEventListener("message", (ev) => {
    const m = JSON.parse(ev.data);
    if (m.method === "Runtime.consoleAPICalled") {
      const args = (m.params.args || [])
        .map((a) => (a.type === "string" ? a.value : a.description || a.value))
        .join(" ");
      logs.push(`[console.${m.params.type}] ${args}`);
    } else if (m.method === "Runtime.exceptionThrown") {
      const d = m.params.exceptionDetails;
      logs.push(
        `[EXCEPTION] ${d.exception && d.exception.description ? d.exception.description.split("\n")[0] : d.text} @ ${d.url}:${d.lineNumber}`
      );
    }
  });

  console.log(`navigating ${URL}`);
  await send(ws, "Page.navigate", { url: URL });
  await sleep(WAIT * 1000);

  for (const l of logs) console.log(l);

  const shot = await send(ws, "Page.captureScreenshot", { format: "png" });
  if (shot && shot.data) fs.writeFileSync("cdp-shot.png", Buffer.from(shot.data, "base64"));

  const state = await send(ws, "Runtime.evaluate", {
    expression: `document.getElementById('log') ? document.getElementById('log').textContent : 'NO LOG DIV'`,
    returnByValue: true,
  });
  console.log("--- #log content ---");
  console.log(state.result && state.result.value);
  console.log("--- total console lines:", logs.length);

  ws.close();
  chrome.kill("SIGKILL");
  process.exit(0);
})().catch((e) => {
  console.error("cdp error:", e);
  chrome.kill("SIGKILL");
  process.exit(1);
});
