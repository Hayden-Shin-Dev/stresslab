// Calendar and intraday grouping for the existing saved simulation paths.
function p512KSTDate(at){const t=new Date(at||Date.now());const d=new Date((Number.isFinite(+t)?+t:Date.now())+9*3600000);d.setUTCHours(0,0,0,0);return d;}
function p512DayKey(d){return d.toISOString().slice(0,10);}
function p512PeriodKey(d,mode){if(mode==='year')return p512DayKey(d).slice(0,4);if(mode==='month')return p512DayKey(d).slice(0,7);if(mode==='week'){const m=new Date(d);m.setUTCDate(m.getUTCDate()-(m.getUTCDay()+6)%7);return p512DayKey(m);}return p512DayKey(d);}
function p512Unit(res){return res.mode==='minute'?res.minutes+'분':({day:'일',week:'주',month:'월',year:'년',tick:'1틱'})[res.mode]||'일';}
function p512Clock(minutes){return String(9+Math.floor(minutes/60)).padStart(2,'0')+':'+String(minutes%60).padStart(2,'0');}
function p512Forecast(run,paths,res){
 const days=Math.max(1,Math.min(20,Number(run.horizon)||5)),date=p512KSTDate(run.at),buckets=[];
 for(let d=0;d<days;){date.setUTCDate(date.getUTCDate()+1);if(!date.getUTCDay()||date.getUTCDay()===6)continue;
  if(res.mode==='minute')for(let m=0;m<390;m+=res.minutes)buckets.push({from:(d+m/390)/days,to:(d+Math.min(390,m+res.minutes)/390)/days,label:p512DayKey(date)+' '+p512Clock(Math.min(390,m+res.minutes)),period:p512DayKey(date)});
  else{const period=p512PeriodKey(date,res.mode),last=buckets.at(-1),partial=['week','month','year'].includes(res.mode);if(last?.period===period)last.to=(d+1)/days;else buckets.push({from:d/days,to:(d+1)/days,period,label:period+(res.mode==='week'?' 주':'')+(partial?' (부분기간)':'')});}d++;
 }
 const series={};for(const [k,points]of Object.entries(paths)){const at=t=>{const x=t*(points.length-1),i=Math.floor(x);return points[i]+(points[Math.min(i+1,points.length-1)]-points[i])*(x-i);};series[k]=buckets.map(b=>{const open=at(b.from),close=at(b.to),inside=points.filter((_,i)=>i/(points.length-1)>b.from&&i/(points.length-1)<b.to);return {...b,open,close,high:Math.max(open,close,...inside),low:Math.min(open,close,...inside)};});}
 return {mode:res.mode,minutes:res.minutes,unit:p512Unit(res),days,buckets,series,count:buckets.length};
}
function p512History(history,res,limit,offset=0,at){
 const dates=[],d=p512KSTDate(at);while(d.getUTCDay()===0||d.getUTCDay()===6)d.setUTCDate(d.getUTCDate()-1);
 for(let n=0;n<history.length;n++){dates.unshift(new Date(d));do{d.setUTCDate(d.getUTCDate()-1);}while(d.getUTCDay()===0||d.getUTCDay()===6);}
 if(res.mode==='minute'){
  const perDay=Math.ceil(390/res.minutes),total=history.length*perDay,end=Math.max(1,total-Math.min(offset,total-2)),start=Math.max(0,end-limit),rows=[];
  for(let n=start;n<end;n++){const i=Math.floor(n/perDay),m=n%perDay*res.minutes,from=m/390,to=Math.min(390,m+res.minutes)/390,a=history[Math.max(0,i-1)],b=history[i],open=a+(b-a)*from,close=a+(b-a)*to;rows.push({open,close,high:Math.max(open,close),low:Math.min(open,close),index:n,label:p512DayKey(dates[i])+' '+p512Clock(Math.min(390,m+res.minutes))});}return rows;
 }
 const rows=[];for(let i=0;i<history.length;i++){const key=p512PeriodKey(dates[i],res.mode),open=history[Math.max(0,i-1)],close=history[i],last=rows.at(-1);if(last?.period===key){last.close=close;last.high=Math.max(last.high,open,close);last.low=Math.min(last.low,open,close);}else rows.push({period:key,label:key+(res.mode==='week'?' 주':''),open,close,high:Math.max(open,close),low:Math.min(open,close),index:i});}
 const end=Math.max(2,rows.length-Math.min(offset,Math.max(0,rows.length-2)));return rows.slice(Math.max(0,end-limit),end);
}
function p512Ticks(rows){return rows.map((r,i)=>{const prev=rows[i-1],sameDay=prev?.tradeAt?.slice(0,10)===r.tradeAt?.slice(0,10),delta=sameDay&&Number.isFinite(r.volume)&&Number.isFinite(prev?.volume)&&r.volume>=prev.volume?r.volume-prev.volume:null;return {open:r.price,high:r.price,low:r.price,close:r.price,label:r.tradeAt,index:i,volumeDelta:Number.isFinite(r.tradeVolume)&&r.tradeVolume>0?r.tradeVolume:delta};});}
