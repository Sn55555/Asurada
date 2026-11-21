import assert from 'node:assert/strict';
import {test} from 'node:test';
import {crc32,encodeFrame,FRAME_BYTES,WIDTH} from './protocol.mjs';
function decode(packet,previous=Buffer.alloc(FRAME_BYTES)){
  assert.equal(packet.toString('ascii',0,4),'ASU1');
  assert.equal(packet.readUInt32LE(8),packet.length-20);
  const out=Buffer.from(previous);let offset=20;
  for(let i=0;i<packet.readUInt32LE(16);i++){
    const x=packet.readUInt16LE(offset),y=packet.readUInt16LE(offset+2),w=packet.readUInt16LE(offset+4),h=packet.readUInt16LE(offset+6);offset+=8;
    assert.ok(x+w<=466&&y+h<=466);
    for(let row=0;row<h;row++){packet.copy(out,((y+row)*WIDTH+x)*2,offset,offset+w*2);offset+=w*2;}
  }
  assert.equal(offset,packet.length);assert.equal(crc32(out),packet.readUInt32LE(12));return out;
}
test('CRC agrees with standard independent known vector',()=>assert.equal(crc32(Buffer.from('123456789')),0xcbf43926));
test('full frame preserves every RGB565 byte including clipped edge tiles',()=>{
  const frame=Buffer.alloc(FRAME_BYTES);for(let i=0;i<frame.length;i++)frame[i]=(i*73+17)%256;
  const packet=encodeFrame(frame,null,1);assert.equal(packet.readUInt32LE(16),225);assert.deepEqual(decode(packet),frame);
});
test('sparse delta updates opposite corners and leaves other pixels unchanged',()=>{
  const before=Buffer.alloc(FRAME_BYTES,0x5a),after=Buffer.from(before);after[0]=7;after[FRAME_BYTES-1]=9;
  const packet=encodeFrame(after,before,2);assert.equal(packet.readUInt32LE(16),2);assert.deepEqual(decode(packet,before),after);
});
test('unchanged heartbeat and corrupted frame detection',()=>{
  const frame=Buffer.alloc(FRAME_BYTES,0x17),packet=encodeFrame(frame,frame,3);
  assert.equal(packet.length,20);assert.deepEqual(decode(packet,frame),frame);
  const full=encodeFrame(frame,null,4);full[30]^=1;assert.throws(()=>decode(full));
});
