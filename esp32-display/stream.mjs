import {createRequire} from 'node:module';
import {readFile,writeFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import {Socket} from 'node:net';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.ASURADA_PLAYWRIGHT || 'playwright');
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const args=process.argv.slice(2);
function arg(name,fallback){let i=args.indexOf(name);return i<0?fallback:args[i+1];}
const host=arg('--host','192.168.4.1');
const feed=path.resolve(arg('--feed',path.join(root,'asurada-core/runtime_logs/dashboard/live_payload.json')));
const fps=Number(arg('--fps','15'));
const preview=arg('--preview',null);
const label=arg('--label','');
const browser=await chromium.launch({headless:true,executablePath:process.env.ASURADA_CHROMIUM || undefined});
let sample=null;
// Serve the existing page and JS byte-for-byte. No change to core or dashboard.
const http=createServer(async(req,res)=>{
  try {
    if(req.url.startsWith('/api/latest')){
      sample=JSON.parse(await readFile(feed,'utf8'));
      res.setHeader('Content-Type','application/json');res.end(JSON.stringify(sample));return;
    }
    const name=req.url.split('?')[0];
    const files={'/':'index.html','/app.js':'app.js','/subject.png':'subject.png'};
    if(!files[name]){res.writeHead(404);res.end();return;}
    res.setHeader('Content-Type',name.endsWith('.js')?'application/javascript':name.endsWith('.png')?'image/png':'text/html');
    res.end(await readFile(path.join(root,'live-dashboard/static',files[name])));
  }catch(e){res.writeHead(503);res.end('Feed unavailable');}
});
await new Promise(resolve=>http.listen(0,'127.0.0.1',resolve));
const page=await browser.newPage({viewport:{width:600,height:600}});
// This private renderer polls its selected feed, never another runtime's WS port.
await page.routeWebSocket(/.*/,ws=>ws.close());
await page.goto(`http://127.0.0.1:${http.address().port}`);
await page.waitForFunction(()=>typeof state!=='undefined' && state.current);
await page.evaluate(source=>{
  window.deviceProtocol=new Function(source.replace(/\bexport /g,'')+';return {crc32,encodeFrame};')();
},await readFile(path.join(root,'esp32-display/protocol.mjs'),'utf8'));
await page.evaluate(()=>{
  // Suppress only the decorative bezel in this private renderer. Keep every
  // instrument at its original coordinate so the lower gap labels stay visible.
  drawOuterShell=()=>{};
  window.deviceCanvas=document.createElement('canvas');deviceCanvas.width=466;deviceCanvas.height=466;
  window.deviceCtx=deviceCanvas.getContext('2d',{willReadFrequently:true});
});
async function capture(sequence=0,full=true){
  return page.evaluate(({label,sequence,full})=>{
    const c=deviceCtx;c.fillStyle='#000';c.fillRect(0,0,466,466);
    c.imageSmoothingEnabled=true;c.imageSmoothingQuality='high';
    // Device-only circular mask; no crop of the original instrument layout.
    c.save();c.beginPath();c.arc(233,233,233,0,Math.PI*2);c.clip();
    c.drawImage(document.getElementById('cluster'),0,0,466,466);
    c.restore();
    const timestamp=Number(state.current?.source_timestamp_ms || state.current?.timestamp_ms || 0);
    const stale=Date.now()-timestamp>2500;
    if(label || stale){
      c.fillStyle='#090b14';c.fillRect(148,42,170,21);
      c.fillStyle='#ffcd67';c.font='bold 13px Arial';c.textAlign='center';
      c.fillText(stale?'NO LIVE DATA':label,233,57);
    }
    const rgba=c.getImageData(0,0,466,466).data;
    const out=new Uint8Array(466*466*2);
    for(let i=0,j=0;i<rgba.length;i+=4,j+=2){const v=((rgba[i]&248)<<8)|((rgba[i+1]&252)<<3)|(rgba[i+2]>>>3);out[j]=v&255;out[j+1]=v>>>8;}
    const packet=deviceProtocol.encodeFrame(out,full?null:window.devicePrevious,sequence);
    window.devicePrevious=out;
    let s='';for(let i=0;i<packet.length;i+=8192)s+=String.fromCharCode(...packet.subarray(i,i+8192));
    return btoa(s);
  },{label,sequence,full});
}
let socket;
async function shutdown(){socket?.destroy();await browser.close();http.close();}
process.on('SIGINT',async()=>{await shutdown();process.exit(0);});
process.on('SIGTERM',async()=>{await shutdown();process.exit(0);});
if(preview){
  await page.waitForTimeout(2500);await capture();
  const png=await page.evaluate(()=>deviceCanvas.toDataURL('image/png').split(',')[1]);
  await writeFile(preview,Buffer.from(png,'base64'));await shutdown();process.exit(0);
}
let sequence=0;
for(;;){
  try{
    socket=new Socket();socket.setNoDelay(true);
    await new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>{socket.destroy();reject(Error('Connection timeout'));},4000);
      function failed(error){clearTimeout(timer);reject(error);}
      socket.once('error',failed);
      socket.connect(19750,host,()=>{clearTimeout(timer);socket.off('error',failed);resolve();});
    });
    console.log(JSON.stringify({event:'connected',host,feed}));
    let full=true;
    let windowStarted=Date.now(),windowFrames=0,windowLatencies=[];
    while(!socket.destroyed){
      const start=Date.now();
      const packet=Buffer.from(await capture(++sequence,full),'base64');
      const expectedCRC=packet.readUInt32LE(12);
      await new Promise((resolve,reject)=>{
        let received=Buffer.alloc(0);
        const timer=setTimeout(()=>finish(Error('ACK timeout')),3000);
        function finish(error){clearTimeout(timer);socket.off('data',onData);socket.off('error',onError);socket.off('close',onClose);error?reject(error):resolve();}
        function onError(e){finish(e);}function onClose(){finish(Error('Disconnected'));}
        function onData(data){received=Buffer.concat([received,data]);if(received.length<16)return;
          if(received.length!==16||received.toString('ascii',0,4)!=='ACK1'||received.readUInt32LE(4)!==(sequence>>>0)||received.readUInt32LE(8)!==expectedCRC){finish(Error('Invalid frame ACK'));return;}
          windowFrames++;windowLatencies.push(Date.now()-start);
          if(sequence%30===1){
            const sorted=[...windowLatencies].sort((a,b)=>a-b);
            console.log(JSON.stringify({event:'frame_verified',sequence,at_ms:Date.now(),bytes:packet.length,latency_ms:Date.now()-start,draw_ms:received.readUInt32LE(12),crc:expectedCRC,source_timestamp_ms:sample?.source_timestamp_ms,fps:Number((windowFrames*1000/(Date.now()-windowStarted)).toFixed(2)),p95_ms:sorted[Math.ceil(sorted.length*.95)-1]}));
            windowStarted=Date.now();windowFrames=0;windowLatencies=[];
          }
          finish();
        }
        socket.on('data',onData);socket.once('error',onError);socket.once('close',onClose);socket.write(packet);
      });
      full=false;
      await new Promise(r=>setTimeout(r,Math.max(0,1000/fps-(Date.now()-start))));
    }
  }catch(e){console.error(JSON.stringify({event:'reconnect',error:e.message}));socket?.destroy();await new Promise(r=>setTimeout(r,1000));}
}
