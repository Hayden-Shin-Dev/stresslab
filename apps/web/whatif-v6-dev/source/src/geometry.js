/* World coordinates are 1536x1024, independent of display size. */
function gxWalkable(room,x,y){
  if(!Number.isFinite(x)||!Number.isFinite(y))return false;
  if(room==='office'||room==='lab')return x>=365&&x<=1090&&y>=465&&y<=875;
  return (x>=180&&x<=1390&&y>=845&&y<=965)||(x>=190&&x<=380&&y>=480&&y<=965);
}
function gxNearest(room,x,y){
  let best=null,d=Infinity;
  for(let yy=16;yy<1024;yy+=32)for(let xx=16;xx<1536;xx+=32){
    if(!gxWalkable(room,xx,yy))continue;
    const n=(xx-x)**2+(yy-y)**2;if(n<d){d=n;best={x:xx,y:yy};}
  }
  return best;
}
function gxPath(room,from,to){
  const a=gxNearest(room,from.x,from.y),b=gxNearest(room,to.x,to.y);if(!a||!b)return [];
  const key=p=>p.x+','+p.y,q=[a],prev=new Map([[key(a),null]]);let end=null;
  for(let i=0;i<q.length;i++){
    const p=q[i];if(key(p)===key(b)){end=p;break;}
    for(const [dx,dy] of [[32,0],[-32,0],[0,32],[0,-32]]){
      const n={x:p.x+dx,y:p.y+dy},k=key(n);if(prev.has(k)||!gxWalkable(room,n.x,n.y))continue;
      prev.set(k,p);q.push(n);
    }
  }
  if(!end)return [];
  const path=[];for(let p=end;p;p=prev.get(key(p)))path.unshift(p);
  return path;
}
function gxClampWindow(r,vw,vh){
  const w=Math.min(Math.max(280,r.w),Math.max(280,vw-85)),h=Math.min(Math.max(380,r.h),Math.max(380,vh-20));
  return {x:Math.min(Math.max(75,r.x),Math.max(75,vw-w-8)),y:Math.min(Math.max(8,r.y),Math.max(8,vh-h-8)),w,h};
}
if(typeof module!=='undefined'&&module.exports)module.exports={gxWalkable,gxNearest,gxPath,gxClampWindow};
