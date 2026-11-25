const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {webcrypto}=require('node:crypto');
const source=fs.readFileSync(require('node:path').join(__dirname,'../site/whatif-v6/assets/handoff-comparison.js'),'utf8');
const delay=ms=>new Promise(r=>setTimeout(r,ms));
async function until(fn){for(let i=0;i<200;i++){if(fn())return;await delay(10);}assert.fail('condition not reached');}
function setup(handler){const calls=[];const box={window:{},crypto:webcrypto,structuredClone,AbortSignal,setTimeout,clearTimeout,fetch:async(url,opts)=>{calls.push({url,...opts,body:opts.body&&JSON.parse(opts.body)});const value=await handler(calls.at(-1));return {ok:true,json:async()=>value};}};vm.runInNewContext(source,box);return {calls,chat:box.window.installWhatIfComparison({roles:()=>['risk'],repaint:()=>{}})};}
const click=(chat,key)=>chat.click({hasAttribute:name=>name===key});

test('changing baseline revokes unfinished comparison before starting latest snapshot',async()=>{
 let release;let count=0;
 const {calls,chat}=setup(async c=>{
   if(c.url==='/api/debates')return {debate_id:'d-'+(++count)};
   if(c.url.endsWith('/cancel'))return {status:'cancelled'};
   if(c.url.includes('/d-1/events'))return await new Promise(r=>release=r);
   return {events:[{seq:1,type:'debate.completed',payload:{}}]};
 });
 chat.configure(['a','b'],'a');assert.equal(calls.length,0);click(chat,'data-comparison-start');
 await until(()=>release);chat.configure(['a','b'],'b');
 await until(()=>calls.filter(c=>c.url==='/api/debates').length===2);
 release({events:[{seq:1,type:'message.created',payload:{display_text:'STALE OUTPUT',role:'risk'}}]});
 await until(()=>chat.html().includes('비교 토론 완료'));
 assert.ok(!chat.html().includes('STALE OUTPUT'));
 assert.equal(calls.filter(c=>c.url==='/api/debates')[1].body.baseline_run_id,'b');
 assert.ok(calls.findIndex(c=>c.url.endsWith('/cancel'))<calls.findLastIndex(c=>c.url==='/api/debates'));
 chat.configure(['a','c'],'c');await delay(900);assert.equal(count,2);
});

test('uncertain acceptance is retried with same idempotency key before cancellation',async()=>{
 let n=0;
 const {calls,chat}=setup(async c=>{
   if(c.url==='/api/debates'){if(++n===1)throw Error('network');return {debate_id:'d-existing'};}
   return {status:'completed'};
 });
 chat.configure(['a','b'],'a');click(chat,'data-comparison-start');await until(()=>chat.html().includes('접수 여부가 불확실'));
 click(chat,'data-comparison-start');assert.equal(n,1);
 click(chat,'data-comparison-cancel');await until(()=>chat.html().includes('이미 완료되어'));
 assert.equal(calls[0].headers['Idempotency-Key'],calls[1].headers['Idempotency-Key']);
 assert.deepEqual(calls[0].body,calls[1].body);
 assert.ok(!chat.html().includes('미완료 응답 삭제됨'));
});
