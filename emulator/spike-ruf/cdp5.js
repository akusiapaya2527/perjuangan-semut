const { spawn } = require("child_process");
const PORT = 9337;
const chrome = spawn("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ["--headless=new","--no-sandbox","--window-size=1000,1000","--user-data-dir=/tmp/ruf-cdp5",
   `--remote-debugging-port=${PORT}`,"about:blank"],{stdio:"ignore"});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function getWs(){for(let i=0;i<40;i++){try{const t=await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();const p=t.find(x=>x.type==="page");if(p)return p.webSocketDebuggerUrl;}catch(e){}await sleep(250);}}
let id=0;
const send=(ws,m,p)=>new Promise(r=>{const mid=++id;const h=e=>{const m=JSON.parse(e.data);if(m.id===mid){ws.removeEventListener("message",h);r(m.result||m.error);}};ws.addEventListener("message",h);ws.send(JSON.stringify({id:mid,method:m,params:p}));});
(async()=>{
  const ws=new WebSocket(await getWs());
  await new Promise(r=>ws.onopen=r);
  await send(ws,"Page.enable"); await send(ws,"Runtime.enable"); await send(ws,"Network.enable");
  const logs=[]; const reqs=[];
  ws.addEventListener("message",e=>{const m=JSON.parse(e.data);
    if(m.method==="Network.requestWillBeSent")reqs.push(m.params.request.url);
    if(m.method==="Network.loadingFailed")reqs.push("FAILED:"+m.params.errorText+" "+(m.params.errorText||""));
    if(m.method==="Runtime.consoleAPICalled"){const a=(m.params.args||[]).map(x=>x.type==="string"?x.value:x.description||x.value).join(" ");logs.push("[console."+m.params.type+"] "+a);}
    if(m.method==="Runtime.exceptionThrown"){const d=m.params.exceptionDetails;logs.push("[EXCEPTION] "+(d.exception&&d.exception.description?d.exception.description.split("\n")[0]:d.text));}});
  await send(ws,"Page.navigate",{url:"http://127.0.0.1:8099/"});
  await sleep(6000);
  await send(ws,"Runtime.evaluate",{expression:`document.getElementById('host').children[0].load({url:'antwarsmobilestarling.swf'})`});
  await sleep(30000);
  console.log("--- requests ---"); reqs.forEach(r=>console.log(r));
  console.log("--- console ---"); logs.forEach(l=>console.log(l));
  const shot = await send(ws,"Page.captureScreenshot",{format:"png"});
  require("fs").writeFileSync("cdp5-shot.png", Buffer.from(shot.data,"base64"));
  ws.close(); chrome.kill("SIGKILL"); process.exit(0);
})().catch(e=>{console.error(e);chrome.kill("SIGKILL");process.exit(1);});
