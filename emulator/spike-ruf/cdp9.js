const { spawn } = require("child_process");
const PORT = 9341;
const chrome = spawn("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ["--headless=new","--no-sandbox","--window-size=1000,1000","--user-data-dir=/tmp/ruf-cdp9",
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
    if(m.method==="Runtime.exceptionThrown"){const d=m.params.exceptionDetails;logs.push("[EXCEPTION] "+(d.exception&&d.exception.description?d.exception.description.split("\n")[0]:d.text));}});
  await send(ws,"Page.navigate",{url:"http://127.0.0.1:8100/"});
  await sleep(15000);
  const r = await send(ws,"Runtime.evaluate",{expression:`(()=>{
    const player = document.getElementById('host').children[0];
    const sr = player.shadowRoot;
    const c = sr ? sr.querySelector('canvas') : null;
    if(!c) return JSON.stringify({canvas:false});
    const gl = c.getContext('webgl2')||c.getContext('webgl');
    const w=c.width,h=c.height;
    const d=new Uint8Array(w*h*4);
    gl.readPixels(0,0,w,h,gl.RGBA,gl.UNSIGNED_BYTE,d);
    let red=0,green=0,blue=0,gray=0;
    for(let j=0;j<d.length;j+=4){const r=d[j],g=d[j+1],b=d[j+2];
      if(r>120&&g<80&&b<80)red++;
      else if(g>120&&r<80&&b<80)green++;
      else if(b>120&&r<80&&g<80)blue++;
      else if(r>60&&g>60&&b>60)gray++;}
    const tot=w*h;
    return JSON.stringify({canvas:true,w,h,redPct:(100*red/tot).toFixed(2),greenPct:(100*green/tot).toFixed(2),bluePct:(100*blue/tot).toFixed(2),grayPct:(100*gray/tot).toFixed(2)});
  })()`,returnByValue:true});
  console.log("RESULT:", r.result && r.result.value);
  console.log("--- console ---"); logs.forEach(l=>console.log(l));
  ws.close(); chrome.kill("SIGKILL"); process.exit(0);
})().catch(e=>{console.error(e);chrome.kill("SIGKILL");process.exit(1);});
