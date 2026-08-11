const { spawn } = require("child_process");
const PORT = 9368;
const chrome = spawn("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ["--headless=new","--no-sandbox","--window-size=1000,900","--user-data-dir=/tmp/ruf-cdp34",
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
  for(let i=0;i<90;i++){
    await sleep(1000);
    if(logs.some(l=>l.includes("IN_HALL"))){break;}
  }
  await sleep(3000);
  const probe=await send(ws,"Runtime.evaluate",{expression:`JSON.stringify({hit554:document.elementFromPoint(554,365)?.tagName,hit20:document.elementFromPoint(20,1)?.tagName,canvas:document.querySelector('canvas')?.tagName,ruffle:!!document.querySelector('ruffle-player')})`,returnByValue:true});
  console.log("elementFromPoint:",probe.result.value);
  console.log("-- CDP Input click at 554,365 --");
  await click(ws,554,365);
  await sleep(4000);
  console.log("after CDP click: lobby="+logs.some(l=>l.includes("IN_SHOW_BT_HALL")));
  console.log("-- JS synthetic click via Runtime.evaluate --");
  const jsres=await send(ws,"Runtime.evaluate",{expression:`(()=>{const c=document.querySelector('canvas');if(!c)return 'no canvas';const r=c.getBoundingClientRect();const x=r.left+0.7033*760;const y=r.top+90+0.7033*390;const o={bubbles:true,cancelable:true,clientX:x,clientY:y,view:window};for(const t of ['pointerdown','mousedown']){c.dispatchEvent(new PointerEvent(t,{...o,pointerId:1,isPrimary:true,button:0,buttons:1}));}for(const t of ['pointerup','mouseup','click']){c.dispatchEvent(new PointerEvent(t,{...o,pointerId:1,isPrimary:true,button:0,buttons:0}));}return 'dispatched at '+x+','+y;})()`,returnByValue:true});
  console.log(jsres.result?.value||JSON.stringify(jsres));
  await sleep(5000);
  console.log("after JS click: lobby="+logs.some(l=>l.includes("IN_SHOW_BT_HALL")));
  const key=["IN_SHOW_BT_HALL","connect host:9002","BTHALLSCREEN","Error #","Guide","guide"];
  logs.filter(l=>key.some(k=>l.includes(k))).slice(-40).forEach(l=>console.log(l));
  ws.close(); chrome.kill("SIGKILL"); process.exit(0);
})().catch(e=>{console.error(e);chrome.kill("SIGKILL");process.exit(1);});
