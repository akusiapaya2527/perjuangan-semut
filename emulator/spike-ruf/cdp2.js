const { spawn } = require("child_process");
const PORT = 9334;
const chrome = spawn("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ["--headless=new","--no-sandbox","--window-size=1000,1000","--user-data-dir=/tmp/ruf-cdp2",
   `--remote-debugging-port=${PORT}`,"about:blank"],{stdio:"ignore"});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function getWs(){for(let i=0;i<40;i++){try{const t=await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();const p=t.find(x=>x.type==="page");if(p)return p.webSocketDebuggerUrl;}catch(e){}await sleep(250);}}
let id=0;
const send=(ws,m,p)=>new Promise(r=>{const mid=++id;const h=e=>{const m=JSON.parse(e.data);if(m.id===mid){ws.removeEventListener("message",h);r(m.result||m.error);}};ws.addEventListener("message",h);ws.send(JSON.stringify({id:mid,method:m,params:p}));});
(async()=>{
  const ws=new WebSocket(await getWs());
  await new Promise(r=>ws.onopen=r);
  await send(ws,"Page.enable"); await send(ws,"Runtime.enable");
  const logs=[];
  ws.addEventListener("message",e=>{const m=JSON.parse(e.data);
    if(m.method==="Runtime.consoleAPICalled"){const a=(m.params.args||[]).map(x=>x.type==="string"?x.value:x.description||x.value).join(" ");logs.push("[console."+m.params.type+"] "+a);}
    if(m.method==="Runtime.exceptionThrown"){const d=m.params.exceptionDetails;logs.push("[EXCEPTION] "+(d.exception&&d.exception.description?d.exception.description.split("\n")[0]:d.text)+" @"+d.url+":"+d.lineNumber);}});
  await send(ws,"Page.navigate",{url:"http://127.0.0.1:8099/"});
  await sleep(20000);
  const expr = `(()=>{
    const out={};
    out.hasNewest = !!window.RufflePlayer && typeof window.RufflePlayer.newest;
    out.config = JSON.stringify(window.RufflePlayer && window.RufflePlayer.config);
    const rp = window.RufflePlayer && window.RufflePlayer.newest && window.RufflePlayer.newest();
    out.rpConfig = rp ? JSON.stringify(rp.config) : 'NO RP';
    const host = document.getElementById('host');
    out.hostChildren = host ? host.children.length : -1;
    out.playerInfo = host && host.children[0] ? {tag:host.children[0].tagName, cls:host.children[0].className} : 'none';
    out.perf = performance.getEntriesByType('resource').filter(e=>e.name.indexOf('.swf')>=0).map(e=>e.name+' '+Math.round(e.duration)+'ms');
    out.titles = document.title;
    return JSON.stringify(out);
  })()`;
  const r = await send(ws,"Runtime.evaluate",{expression:expr,returnByValue:true});
  console.log("DIAG:", r.result && r.result.value);
  logs.forEach(l=>console.log(l));
  ws.close(); chrome.kill("SIGKILL"); process.exit(0);
})().catch(e=>{console.error(e);chrome.kill("SIGKILL");process.exit(1);});
