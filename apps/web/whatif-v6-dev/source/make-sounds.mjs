import fs from 'node:fs';
const rate=24000;
for(const kind of ['click','step']){
 const duration=kind==='click'?.065:.09,n=Math.floor(rate*duration),data=Buffer.alloc(44+n*2);data.write('RIFF');data.writeUInt32LE(36+n*2,4);data.write('WAVEfmt ',8);data.writeUInt32LE(16,16);data.writeUInt16LE(1,20);data.writeUInt16LE(1,22);data.writeUInt32LE(rate,24);data.writeUInt32LE(rate*2,28);data.writeUInt16LE(2,32);data.writeUInt16LE(16,34);data.write('data',36);data.writeUInt32LE(n*2,40);let seed=217,low=0;
 for(let i=0;i<n;i++){const t=i/rate;seed=(Math.imul(seed,1664525)+1013904223)>>>0;const noise=seed/4294967296*2-1;low=.7*low+.3*noise;const envelope=Math.min(1,t/.003)*Math.exp(-t/(kind==='click'?.016:.023));const value=kind==='click'?(Math.sin(t*2*Math.PI*(t<.022?850:1250))*.43+low*.16)*envelope:(Math.sin(t*2*Math.PI*125)*.35+low*.65)*envelope;data.writeInt16LE(Math.round(Math.max(-1,Math.min(1,value))*.5*32767),44+i*2);}
 fs.writeFileSync('assets/sfx_'+kind+'50.wav',data);
}
console.log('Created original click and wooden-floor footstep WAV assets');
