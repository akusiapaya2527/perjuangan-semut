const { spawn } = require("child_process");
const PORT = 9344;
const chrome = spawn("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ["--headless=new","--no-sandbox","--window-size=760,800","--user-data-dir=/tmp/ruf-cdp12",
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
    if(m.method==="Runtime.consoleAPICalled"){const a=(m.params.args||[]).map(x=>x.type==="string"?x.value:x.description||x.value).join(" ");logs.push("[console."+m.params.type+"] "+a);}});
  await send(ws,"Page.navigate",{url:"http://127.0.0.1:8100/cube.html"});
  await sleep(20000);
  logs.forEach(l=>console.log(l));
  const r = await send(ws,"Runtime.evaluate",{expression:`(()=>{
    const player=document.getElementById('host').children[0];
    const sr=player.shadowRoot;
    const c=sr?srw = sr.querySelector('canvas'):null;
    if(!c) return JSON.stringify({canvas:false});
    const gl=c.getContext('webgl2')||c.getContext('webgl');
    const w=c.width,h=c.height;
    const d=new Uint8Array(w*h*4);
    gl.readPixels(0,0,w,h,gl.RGBA,gl.UNSIGNED_BYTE,d);
    let nonBg=0; const seen=new Set();
    for(let j=0;j<d.length;j+=4){const r2=d[j],g2=d[j+1],b2=d[j+2];
      if(!(r2<=8&&g2<=8&&b2<=8)){nonBg++; seen.add(r2+','+g2+','+b2);}}
    return JSON.stringify({canvas:true,w,h,nonBgPct:(100*nonBg/(w*h)).toFixed(2),distinctColors:seen.size, sample:[...seen].slice(0,6)});
  })()`,returnByValue:true});
  console.log("RESULT:", r.result && r.result.value);
  ws.close(); chrome.kill("SIGKILL"); process.exit(0);
})().catch(e=>{console.error(e);chrome.kill("SIGKILL");process.exit(1);});
