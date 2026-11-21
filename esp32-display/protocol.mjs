export const WIDTH = 466, HEIGHT = 466, FRAME_BYTES = WIDTH * HEIGHT * 2;
const table = Array.from({length:256},(_,i)=>{
  for(let b=0;b<8;b++) i=(i>>>1)^((i&1)?0xedb88320:0);
  return i>>>0;
});
export function crc32(bytes) {
  let c=0xffffffff;
  for(const b of bytes)c=(c>>>8)^table[(c^b)&255];
  return (c^0xffffffff)>>>0;
}
export function encodeFrame(frame, previous, sequence) {
  if(frame.length!==FRAME_BYTES)throw Error('Invalid frame dimensions');
  const tiles=[];
  for(let y=0;y<HEIGHT;y+=32)for(let x=0;x<WIDTH;x+=32){
    const w=Math.min(32,WIDTH-x),h=Math.min(32,HEIGHT-y);
    let changed=!previous;
    if(previous)for(let row=0;row<h&&!changed;row++){
      const pos=((y+row)*WIDTH+x)*2;
      for(let i=pos;i<pos+w*2;i++)if(frame[i]!==previous[i]){changed=true;break;}
    }
    if(!changed)continue;
    const tile=new Uint8Array(8+w*h*2),view=new DataView(tile.buffer);
    [x,y,w,h].forEach((n,i)=>view.setUint16(i*2,n,true));
    for(let row=0;row<h;row++)tile.set(frame.subarray(((y+row)*WIDTH+x)*2,((y+row)*WIDTH+x+w)*2),8+row*w*2);
    tiles.push(tile);
  }
  const payloadBytes=tiles.reduce((n,t)=>n+t.length,0);
  const packet=new Uint8Array(20+payloadBytes),view=new DataView(packet.buffer);
  packet.set([65,83,85,49]);view.setUint32(4,sequence>>>0,true);
  view.setUint32(8,payloadBytes,true);view.setUint32(12,crc32(frame),true);view.setUint32(16,tiles.length,true);
  let offset=20;for(const tile of tiles){packet.set(tile,offset);offset+=tile.length;}
  return typeof Buffer==='undefined'?packet:Buffer.from(packet);
}
