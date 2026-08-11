const { spawn } = require("child_process");
const PORT = 9370;
const chrome = spawn("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ["--headless=new","--no-sandbox","--window-size=1000,900","--user-data-dir=/tmp/ruf-cdp36",
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
  await send(ws,"Page.bringToFront");
  for(let i=0;i<90;i++){
    await sleep(1000);
    if(logs.some(l=>l.includes("IN_HALL"))){break;}
  }
  await sleep(2000);
  console.log("focus check:",(await send(ws,"Runtime.evaluate",{expression:`document.hasFocus()`,returnByValue:true})).result?.value);
  // move mouse first, then press/release with longer hold
  await send(ws,"Input.dispatchMouseEvent",{type:"mouseMoved",x:554,y:365});
  await sleep(200);
  for(let i=0;i<6;i++){
    await send(ws,"Input.dispatchMouseEvent",{type:"mousePressed",x:554,y:365,button:"left",clickCount:1});
    await sleep(120);
    await send(ws,"Input.dispatchMouseEvent",{type:"mouseReleased",x:554,y:365,button:"left",clickCount:1});
    await sleep(3500);
    if(logs.some(l=>l.includes("IN_SHOW_BT_HALL"))||logs.some(l=>l.includes("connect host:127.0.0.1 port:9002"))){
      console.log("CLICK HIT on attempt "+(i+1)); break;
    }
    await send(ws,"Input.dispatchMouseEvent",{type:"mouseMoved",x:400,y:200});
    await send(ws,"Input.dispatchMouseEvent",{type:"mouseMoved",x:554,y:365});
    await sleep(500);
  }
  console.log("lobby:",logs.some(l=>l.includes("IN_SHOW_BT_HALL")), "| battle:",logs.some(l=>l.includes("connect host:127.0.0.1 port:9002")));
  logs.filter(l=>l.includes("mySocket")||l.includes("BTHALLSCREEN")||l.includes("flush")||l.includes("IN_SHOW")).slice(-15).forEach(l=>console.log(l));
  ws.close(); chrome.kill("SIGKILL"); process.exit(0);
})().catch(e=>{console.error(e);chrome.kill("SIGKILL");process.exit(1);});
