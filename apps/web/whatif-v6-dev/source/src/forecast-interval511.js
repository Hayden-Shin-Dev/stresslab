// Re-express the saved forecast over the same horizon; never extend five days into five months.
function p511Forecast(run, paths, mode) {
 const days=Math.max(1,Math.min(20,Number(run.horizon)||5)), unit=mode==='minute'?'5분봉':mode==='month'?'월봉':'일봉';
 const stamp=new Date(run.at||Date.now());
 const date=new Date((Number.isFinite(+stamp)?+stamp:Date.now())+9*3600000);
 date.setUTCHours(0,0,0,0);
 const sessions=[];
 for(let n=0;n<days;){date.setUTCDate(date.getUTCDate()+1);if(date.getUTCDay()%6){sessions.push(new Date(date));n++;}}
 const key=d=>d.toISOString().slice(0,10), buckets=[];
 for(let d=0;d<days;d++) {
  if(mode==='minute')for(let m=0;m<78;m++)buckets.push({from:(d+m/78)/days,to:(d+(m+1)/78)/days,label:key(sessions[d])+' '+String(9+Math.floor((m+1)*5/60)).padStart(2,'0')+':'+String((m+1)*5%60).padStart(2,'0'),period:key(sessions[d])});
  else if(mode==='month'){
   const period=key(sessions[d]).slice(0,7),last=buckets.at(-1);
   if(last?.period===period)last.to=(d+1)/days;
   else buckets.push({from:d/days,to:(d+1)/days,label:period+' (부분월)',period});
  }else buckets.push({from:d/days,to:(d+1)/days,label:key(sessions[d]),period:key(sessions[d])});
 }
 const series={};
 for(const [scenario,points] of Object.entries(paths)){
  const at=t=>{const pos=t*(points.length-1),i=Math.floor(pos),f=pos-i;return points[i]+((points[Math.min(i+1,points.length-1)]-points[i])*f);};
  series[scenario]=buckets.map(b=>{const open=at(b.from),close=at(b.to),inside=points.filter((_,i)=>i/(points.length-1)>b.from&&i/(points.length-1)<b.to);return {...b,open,close,high:Math.max(open,close,...inside),low:Math.min(open,close,...inside)};});
 }
 return {mode,unit,days,buckets,series,count:buckets.length};
}
