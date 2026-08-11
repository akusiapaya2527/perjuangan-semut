const { spawn } = require("child_process");
const fs = require("fs");
const PORT = 9367;
const chrome = spawn("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ["--headless=new","--no-sandbox","--window-size=1000,900","--user-data-dir=/tmp/ruf-cdp33",
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
  for(let i=0;i<90;i++){
    await sleep(1000);
    if(logs.some(l=>l.includes("IN_HALL"))){
      hall=true;
      await sleep(3000);
      break;
    }
  }
  console.log("hall ready: "+hall);
  if(hall){
    const spots=[[554,365],[534,365],[554,340],[554,390],[490,365],[620,365],[554,300],[554,430],[800,300]];
    let got=false;
    for(let t=0;t<spots.length;t++){
      const [x,y]=spots[t];
      console.log("-- click at "+x+","+y+" --");
      await click(ws,x,y);
      await sleep(4000);
      if(logs.some(l=>l.includes("IN_SHOW_BT_HALL"))||logs.some(l=>l.includes("connect host:127.0.0.1 port:9002"))){
        got=true; console.log("HIT at "+x+","+y); break;
      }
    }
    console.log("lobby triggered: "+got);
  }
  await sleep(8000);
  const key=["IN_SHOW_BT_HALL","connect host:9002","CONNECT Event","flush pending","sendcmd: 0","Error #","BTHALLSCREEN","bt login successful","mySocket"];
  const filtered=logs.filter(l=>key.some(k=>l.includes(k)));
  console.log("-- filtered logs --");
  filtered.forEach(l=>console.log(l));
  if(filtered.length===0) console.log("(no matching logs)");
  try{const shot=await send(ws,"Page.captureScreenshot",{format:"png"});fs.writeFileSync("cdp25.png",Buffer.from(shot.data,"base64"));console.log("saved cdp25.png");}catch(e){console.log("shot fail",e);}
  ws.close(); chrome.kill("SIGKILL"); process.exit(0);
})().catch(e=>{console.error(e);chrome.kill("SIGKILL");process.exit(1);});
