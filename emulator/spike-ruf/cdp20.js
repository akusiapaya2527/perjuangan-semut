const { spawn } = require("child_process");
const PORT = process.argv[2];
const PROFILE = "/tmp/ruf-" + process.argv[3];
const chrome = spawn("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ["--headless=new","--no-sandbox","--window-size=1000,900","--user-data-dir="+PROFILE,
   `--remote-debugging-port=${PORT}`,"about:blank"],{stdio:"ignore"});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function getWs(){for(let i=0;i<40;i++){try{const t=await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();const p=t.find(x=>x.type==="page");if(p)return p.webSocketDebuggerUrl;}catch(e){}await sleep(250);}}
let id=0;
const send=(ws,m,p)=>new Promise(r=>{const mid=++id;const h=e=>{const m=JSON.parse(e.data);if(m.id===mid){ws.removeEventListener("message",h);r(m.result||m.error);}};ws.addEventListener("message",h);ws.send(JSON.stringify({id:mid,method:m,params:p}));});
async function click(ws,x,y){
  await send(ws,"Input.dispatchMouseEvent",{type:"mousePressed",x,y,button:"left",clickCount:1});
  await sleep(60);
  await send(ws,"Input.dispatchMouseEvent",{type:"mouseReleased",x,y,button:"left",clickCount:1});
}
(async()=>{
  const ws=new WebSocket(await getWs());
  await new Promise(r=>ws.onopen=r);
  await send(ws,"Page.enable"); await send(ws,"Runtime.enable");
  const errs=[];
  ws.addEventListener("message",e=>{const m=JSON.parse(e.data);
    if(m.method==="Runtime.consoleAPICalled"&&m.params.type==="error"){const a=(m.params.args||[]).map(x=>x.type==="string"?x.value:x.description||x.value).join(" ");errs.push(a);}
    if(m.method==="Runtime.exceptionThrown"){errs.push("EXC "+(m.params.exceptionDetails&&m.params.exceptionDetails.text));}});
  await send(ws,"Page.navigate",{url:"http://127.0.0.1:8099/"});
  await sleep(45000);
  await click(ws,534,365);
  await sleep(8000);
  console.log("RUN ERRORS:", errs.length);
  errs.slice(0,8).forEach(e=>console.log("  ",e.slice(0,200)));
  ws.close(); chrome.kill("SIGKILL"); process.exit(0);
})().catch(e=>{console.error(e);chrome.kill("SIGKILL");process.exit(1);});
