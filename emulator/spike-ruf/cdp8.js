const { spawn } = require("child_process");
const PORT = 9340;
const chrome = spawn("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ["--headless=new","--no-sandbox","--window-size=1000,1000","--user-data-dir=/tmp/ruf-cdp8",
   `--remote-debugging-port=${PORT}`,"about:blank"],{stdio:"ignore"});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function getWs(){for(let i=0;i<40;i++){try{const t=await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();const p=t.find(x=>x.type==="page");if(p)return p.webSocketDebuggerUrl;}catch(e){}await sleep(250);}}
let id=0;
const send=(ws,m,p)=>new Promise(r=>{const mid=++id;const h=e=>{const m=JSON.parse(e.data);if(m.id===mid){ws.removeEventListener("message",h);r(m.result||m.error);}};ws.addEventListener("message",h);ws.send(JSON.stringify({id:mid,method:m,params:p}));});
(async()=>{
  const ws=new WebSocket(await getWs());
  await new Promise(r=>ws.onopen=r);
  await send(ws,"Page.enable"); await send(ws,"Runtime.enable");
  await send(ws,"Page.navigate",{url:"http://127.0.0.1:8099/"});
  await sleep(5000);
  await send(ws,"Runtime.evaluate",{expression:`document.getElementById('host').children[0].load({url:'antwarsmobilestarling.swf'})`});
  await sleep(40000);
  const r = await send(ws,"Runtime.evaluate",{expression:`(()=>{
    const player = document.getElementById('host').children[0];
    const sr = player.shadowRoot;
    const canvases = sr ? sr.querySelectorAll('canvas') : [];
    const out = {shadowRoot: !!sr, canvasCount: canvases.length, html: sr ? sr.innerHTML.slice(0,500) : 'none'};
    out.canvases = Array.from(canvases).map((c,i)=>{
      try {
        const gl = c.getContext('webgl2') || c.getContext('webgl');
        const w=c.width, h=c.height;
        const d = new Uint8Array(w*h*4);
        gl.readPixels(0,0,w,h,gl.RGBA,gl.UNSIGNED_BYTE,d);
        let nonBlack=0;
        for(let j=0;j<d.length;j+=4){ if(d[j]>10||d[j+1]>10||d[j+2]>10) nonBlack++; }
        return {i,w,h,nonBlackPct:(100*nonBlack/(w*h)).toFixed(2)};
      } catch(e){ return {i,err:e.message}; }
    });
    return JSON.stringify(out);
  })()`,returnByValue:true});
  console.log("SHADOW:", r.result && r.result.value);
  ws.close(); chrome.kill("SIGKILL"); process.exit(0);
})().catch(e=>{console.error(e);chrome.kill("SIGKILL");process.exit(1);});
