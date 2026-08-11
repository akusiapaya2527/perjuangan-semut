const { spawn } = require("child_process");
const fs = require("fs");
const PORT = 9369;
const chrome = spawn("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ["--headless=new","--no-sandbox","--window-size=1000,900","--user-data-dir=/tmp/ruf-cdp35",
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
    if(m.method==="Runtime.exceptionThrown"){logs.push("[EXCEPTION] "+(m.params.exceptionDetails&&(m.params.exceptionDetails.text+" "+m.params.exceptionDetails.exception&&m.params.exceptionDetails.exception.description)));}});
  await send(ws,"Page.navigate",{url:"http://127.0.0.1:8099/"});
  for(let i=0;i<90;i++){
    await sleep(1000);
    if(logs.some(l=>l.includes("IN_HALL"))){break;}
  }
  await sleep(3000);
  const probe=await send(ws,"Runtime.evaluate",{expression:`(()=>{const el=document.querySelector('ruffle-player');const root=el&&el.shadowRoot;const canvas=root&&root.querySelector('canvas');const r=canvas?canvas.getBoundingClientRect():null;return JSON.stringify({hasShadow:!!root,canvasR:r&&{x:r.x,y:r.y,w:r.width,h:r.height},canvasTag:canvas&&canvas.tagName});})()`,returnByValue:true});
  console.log("probe:",probe.result?.value);
  const clickExpr=`(()=>{const el=document.querySelector('ruffle-player');const root=el&&el.shadowRoot;const canvas=root&&root.querySelector('canvas');if(!canvas)return 'no canvas';const r=canvas.getBoundingClientRect();const x=r.left+554-20;const y=r.top+365-1;const opts={bubbles:true,cancelable:true,composed:true,clientX:x,clientY:y,pointerId:1,pointerType:'mouse',button:0,buttons:1,isPrimary:true};canvas.dispatchEvent(new PointerEvent('pointerdown',opts));canvas.dispatchEvent(new PointerEvent('pointerup',{...opts,buttons:0}));canvas.dispatchEvent(new MouseEvent('mousedown',opts));canvas.dispatchEvent(new MouseEvent('mouseup',{...opts,buttons:0}));canvas.dispatchEvent(new MouseEvent('click',{...opts,buttons:0}));return 'clicked '+x+','+y;})()`;
  const jr=await send(ws,"Runtime.evaluate",{expression:clickExpr,returnByValue:true});
  console.log("js click:",jr.result?.value);
  await sleep(5000);
  console.log("lobby after js click:",logs.some(l=>l.includes("IN_SHOW_BT_HALL")), "| battle:",logs.some(l=>l.includes("connect host:127.0.0.1 port:9002")));
  try{const shot=await send(ws,"Page.captureScreenshot",{format:"png"});fs.writeFileSync("cdp27.png",Buffer.from(shot.data,"base64"));}catch(e){}
  ws.close(); chrome.kill("SIGKILL"); process.exit(0);
})().catch(e=>{console.error(e);chrome.kill("SIGKILL");process.exit(1);});
