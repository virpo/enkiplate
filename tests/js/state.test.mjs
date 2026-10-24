import { test } from 'node:test';
import assert from 'node:assert/strict';
import { stateQueue, makeId } from '../../web/state.js';

test('an acknowledgement during a grade save cannot erase the new answer', async () => {
  let current={index:1,pending:[{id:'A'}]}, persisted;
  let release, started;
  const saving=new Promise(resolve=>{started=resolve});
  const blocked=new Promise(resolve=>{release=resolve});
  const commit=stateQueue(()=>current,async next=>{if(next.index===2&&next.pending.length===2){started();await blocked}persisted=structuredClone(next)},next=>{current=next});
  const grade=commit(s=>({...s,index:2,pending:[...s.pending,{id:'B'}]}));
  await saving;
  const acknowledgement=commit(s=>({...s,pending:s.pending.filter(e=>e.id!=='A')}));
  release(); await Promise.all([grade,acknowledgement]);
  assert.deepEqual(persisted,{index:2,pending:[{id:'B'}]});
});
test('ID generation works without randomUUID',()=>{
  const a=makeId(),b=makeId();assert.match(a,/^[a-f0-9]{32}$/);assert.notEqual(a,b);
});

import { refreshedState, maintainStudy } from '../../web/state.js';
test('a replacement for a missing kept card starts on the front',()=>{
  const current={cards:[{id:'missing'}],index:0,side:'back',pending:[]};
  assert.equal(refreshedState(current,{cards:[{id:'replacement'}]},true,'missing').side,'front');
  assert.equal(refreshedState(current,{cards:[{id:'missing'}]},true,'missing').side,'back');
});
test('periodic maintenance retries a failed service without an online event',async()=>{
  let current={cards:[{id:'cached'}],index:0,side:'front',pending:[{id:'answer'}],saved_at:0,valid_until:0};
  let available=false,calls=0,refreshed=false;
  const sync=async()=>{calls++;if(!available)throw Error('service down');current={...current,pending:[]}};
  await assert.rejects(maintainStudy(()=>current,sync,async()=>{},async()=>{}));
  available=true;
  await maintainStudy(()=>current,sync,async()=>{refreshed=true},async()=>{},()=>700000);
  assert.equal(calls,2);assert.equal(current.pending.length,0);assert.ok(refreshed);
});
