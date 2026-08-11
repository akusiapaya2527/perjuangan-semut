const { spawn } = require("child_process");
const PORT = 9366;
const chrome = spawn("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ["--headless=new","--no-sandbox","--window-size=1000,900","--user-data-dir=/tmp/ruf-cdp32",
   `--remote-debugging-port=${PORT}`,"about:blank"],{stdio:"ignore"});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function getWs(){for(let i=0;i<40;i++){try{const t=await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();const p=t.find(x=>x.type==="page");if(p)return p.webSocketDebuggerUrl;}catch(e){}await sleep(250);}}
let id=0;
const send=(ws,m,p)=>new Promise(r=>{const mid=++id;const h=e=>{const m=JSON.parse(e.data);if(m.id===mid){ws.removeEventListener("message",h);r(m.result||m.error);}};ws.addEventListener("message",h);ws.send(JSON.stringify({id:mid,method:m,params:p}));});
(async()=>{
  const ws=new WebSocket(await getWs());
  await new Promise(r=>ws.onopen=r);
  await send(ws,"Page.enable"); await send(ws,"Runtime.enable");
  await send(ws,"Page.navigate",{url:"http://127.0.0.1:8099/"});
  await sleep(30000);
  const r=await send(ws,"Runtime.evaluate",{expression:`JSON.stringify({iw:window.innerWidth,ih:window.innerHeight,cw:document.documentElement.clientWidth,ch:document.documentElement.clientHeight,canvas:(document.querySelector('canvas,ruffle-player')?document.querySelector('canvas')?.getBoundingClientRect()??document.querySelector('ruffle-player').getBoundingClientRect():null)})`,returnByValue:true});
  console.log(r.result.value);
  ws.close(); chrome.kill("SIGKILL"); process.exit(0);
})().catch(e=>{console.error(e);chrome.kill("SIGKILL");process.exit(1);});
