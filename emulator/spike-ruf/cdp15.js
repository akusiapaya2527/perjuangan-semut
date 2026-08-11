const { spawn } = require("child_process");
const PORT = 9351;
const chrome = spawn("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ["--headless=new","--no-sandbox","--window-size=1000,900","--user-data-dir=/tmp/ruf-cdp15",
   `--remote-debugging-port=${PORT}`,"about:blank"],{stdio:"ignore"});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function getWs(){for(let i=0;i<40;i++){try{const t=await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();const p=t.find(x=>x.type==="page");if(p)return p.webSocketDebuggerUrl;}catch(e){}await sleep(250);}}
let id=0;
const send=(ws,m,p)=>new Promise(r=>{const mid=++id;const h=e=>{const m=JSON.parse(e.data);if(m.id===mid){ws.removeEventListener("message",h);r(m.result||m.error);}};ws.addEventListener("message",h);ws.send(JSON.stringify({id:mid,method:m,params:p}));});
(async()=>{
  const ws=new WebSocket(await getWs());
  await new Promise(r=>ws.onopen=r);
  await send(ws,"Page.enable"); await send(ws,"Runtime.enable");
  ws.addEventListener("message",e=>{const m=JSON.parse(e.data);
    if(m.method==="Runtime.consoleAPICalled"){const a=(m.params.args||[]).map(x=>x.type==="string"?x.value:x.description||x.value).join(" ");console.log("[console."+m.params.type+"] "+a);}
    if(m.method==="Runtime.exceptionThrown"){console.log("[EXCEPTION] "+(m.params.exceptionDetails&&(m.params.exceptionDetails.exception&&m.params.exceptionDetails.exception.description||m.params.exceptionDetails.text)));}
    if(m.method==="Network.loadingFailed"){console.log("[NETFAIL] "+m.params.requestId+" "+(m.params.errorText||m.params.type));}});
  await send(ws,"Network.enable");
  await send(ws,"Page.navigate",{url:"http://127.0.0.1:8099/"});
  await sleep(15000);
  const evaljs=async(expr)=>{const r=await send(ws,"Runtime.evaluate",{expression:expr,returnByValue:true,awaitPromise:true});return r&&r.result&&r.result.value;};
  const info=await evaljs(`(function(){
    const p=document.querySelector('ruffle-player');
    if(!p) return 'no player element';
    const c=p.shadowRoot?p.shadowRoot.querySelector('canvas'):null;
    return JSON.stringify({
      src:p.getAttribute('src'),
      isPlaying:typeof p.isPlaying==='function'?p.isPlaying():'n/a',
      internalPlayState:p.internalPlayState,
      canvas: c?{w:c.width,h:c.height,cssW:c.style.width,cssH:c.style.height}:null,
      shadowHtml: p.shadowRoot? p.shadowRoot.innerHTML.slice(0,300):null
    });
  })()`);
  console.log("PLAYER STATE:", info);
  ws.close(); chrome.kill("SIGKILL"); process.exit(0);
})().catch(e=>{console.error(e);chrome.kill("SIGKILL");process.exit(1);});
