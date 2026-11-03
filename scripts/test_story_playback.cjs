const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const modulePromise=fs.readFile('web/story-playback.js','utf8').then(source=>import('data:text/javascript;base64,'+Buffer.from(source).toString('base64')));
test('snapshot changes only at its recorded time',async()=>{
 const {frameAt}=await modulePromise,frames=[{time:0,id:0},{time:60,id:1},{time:120,id:2}];
 assert.equal(frameAt(frames,-1).id,0);assert.equal(frameAt(frames,59.99).id,0);assert.equal(frameAt(frames,60).id,1);assert.equal(frameAt(frames,999).id,2);
});
test('couriers wait at repeated vertices and interpolate along the recorded street',async()=>{
 const {courierPosition}=await modulePromise,data={routes:[[[10,20,0],[10,20,10],[30,20,20],[30,40,30]]]},moving=[10,20,2,0];
 assert.deepEqual(courierPosition(data,moving,5),[10,20]);assert.deepEqual(courierPosition(data,moving,15),[20,20]);assert.deepEqual(courierPosition(data,moving,25),[30,30]);assert.deepEqual(courierPosition(data,moving,60),[30,40]);assert.deepEqual(courierPosition(data,[1,2,0,-1],15),[1,2]);
});
