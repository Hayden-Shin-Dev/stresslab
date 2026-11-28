const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const ctx={window:{},Intl,Date};
for(const name of ['scenario-window','scenario-workspace']) vm.runInNewContext(fs.readFileSync(path.join(__dirname,`../site/whatif-v6/assets/${name}.js`),'utf8'),ctx);
test('default identities equal configured Kiwoom top 20; no seeded prices',()=>{
 const universe=JSON.parse(fs.readFileSync(path.join(__dirname,'../../../../ingestion/kiwoom/universe.json')));
 assert.deepEqual(JSON.parse(JSON.stringify(ctx.window.whatIfScenarioDefaultAssets)),universe.assets.map(a=>({code:a.asset_id,name:a.name,market:a.market})));
 const html=ctx.window.whatIfScenarioDataPanel({market:{rows:[]},mode:'live'});
 assert.equal((html.match(/class="fig-quote-row /g)||[]).length,20);
 assert.equal((html.match(/시세 미수신/g)||[]).length,20);
});
test('partial quote reception retains 20 selectable stocks and genuine timestamps',()=>{
 const html=ctx.window.whatIfScenarioDataPanel({market:{receivedAt:'2026-11-23T01:00:00Z',rows:[{code:'005930',name:'삼성전자',price:178850}]},mode:'live',portfolioLots:[{code:'005930'}]});
 assert.equal((html.match(/data-gx="p63-add-lot"/g)||[]).length,20);
 assert.match(html,/178,850/);assert.match(html,/보유 중 · 추가/);
 assert.doesNotMatch(html,/2026년/); // client polling time must not be presented as trade/collection time
});
test('evidence preserves raw units, rejects absent numbers, escapes server labels',()=>{
 const rows=[{label:'<script>bad</script>',value:-1.94,unit:'%p'},{label:'동반 하락',value:.017,unit:'ratio'},{label:'동조화',value:.23,unit:'corr'},{label:'없음',value:null,unit:'%'},{label:'잘못된 값',value:NaN}];
 const before=JSON.stringify(rows);const html=ctx.window.whatIfScenarioEvidenceTable(rows);
 assert.equal(JSON.stringify(rows),before);assert.equal((html.match(/<tr><th scope="row">/g)||[]).length,3);
 assert.match(html,/>1.7<\/strong> <span>%/);assert.match(html,/>0.23<\/strong> <span>상관계수/);
 assert.match(html,/data-raw-value="0.017"/);assert.match(html,/>-1.94<\/strong> <span>%p/);
 assert.doesNotMatch(html,/<script>/);assert.doesNotMatch(html,/NaN|없음/);
});
test('chat history pages keep the question and all agent replies in the same round',()=>{
 const messages=[
  {kind:'simulation',runId:'old'},{runId:'old'},
  {kind:'simulation',runId:'current'},{runId:'current'},
  {me:true,runId:'current'},{runId:'current'},{runId:'current'},
  {me:true,runId:'current'},{runId:'current'},
  {me:true,runId:'current'},{runId:'current'},{runId:'current'},
 ];
 const start=ctx.window.whatIfScenarioEarlierMessages(messages,messages.length);
 assert.equal(start,4);
 assert.equal(ctx.window.whatIfScenarioEarlierMessages(messages,start),0);
 assert.equal(ctx.window.whatIfScenarioEarlierMessages([],0),0);
});
