const { spawn } = require("child_process");
const fs = require("fs");
const PORT = 9364;
const chrome = spawn("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ["--headless=new","--no-sandbox","--window-size=1000,900","--user-data-dir=/tmp/ruf-cdp30",
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
  const logs=[];
  ws.addEventListener("message",e=>{const m=JSON.parse(e.data);
    if(m.method==="Runtime.consoleAPICalled"){const a=(m.params.args||[]).map(x=>x.type==="string"?x.value:x.description||x.value).join(" ");logs.push("[console."+m.params.type+"] "+a);}
    if(m.method==="Runtime.exceptionThrown"){logs.push("[EXCEPTION] "+(m.params.exceptionDetails&&(m.params.exceptionDetails.text+" "+m.params.exceptionDetails.exception&&m.params.exceptionDetails.exception.description)));}});
  await send(ws,"Page.navigate",{url:"http://127.0.0.1:8099/"});
  let hall=false;
  for(let i=0;i<80;i++){
    await sleep(1000);
    if(logs.some(l=>l.includes("当前共有滚动项"))){
      hall=true;
      await sleep(2000);
      break;
    }
  }
  console.log("hall ready: "+hall);
  if(hall){
    console.log("-- clicking lobby at 534,365 --");
    await click(ws,534,365);
  }
  await sleep(9000);
  const key=["mySocket","sendcmd","connect host","CONNECT Event","flush pending","Error #","sendLogin","loginSuccessful"];
  const filtered=logs.filter(l=>key.some(k=>l.includes(k)));
  console.log("-- filtered mySocket logs --");
  filtered.forEach(l=>console.log(l));
  if(filtered.length===0) console.log("(no mySocket logs captured)");
  try{const shot=await send(ws,"Page.captureScreenshot",{format:"png"});fs.writeFileSync("cdp22.png",Buffer.from(shot.data,"base64"));console.log("saved cdp22.png");}catch(e){console.log("shot fail",e);}
  ws.close(); chrome.kill("SIGKILL"); process.exit(0);
})().catch(e=>{console.error(e);chrome.kill("SIGKILL");process.exit(1);});
