/* WHAT IF / Voxel Motion — WebGL2, no animation dependencies.
 * Based on the user-supplied voxel_cube_stack.webm visual reference.
 * Original footage is NOT decoded into a model or converted to coordinates;
 * this is an independent procedural recreation of its visual mechanism.
 *
 * Public interface:
 *   const voxels = new window.WhatIfVoxel(canvas, { intensity: .5 });
 *   voxels.setIntensity(0.8);      // 0..1
 *   voxels.setScenario({rateBp: 60, fxPct: 3, oilPct: 5, vixPt: 12});
 *   voxels.pause(); voxels.play(); voxels.destroy();
 */
(() => {
  'use strict';
  const VERTEX = `#version 300 es
  precision highp float;
  layout(location=0) in vec3 aPosition;
  layout(location=1) in vec3 aNormal;
  layout(location=2) in vec4 aInstance; // xyz position, w = visible unit height
  uniform mat4 uViewProjection;
  out vec3 vNormal;
  out vec3 vLocal;
  out vec3 vWorld;
  void main() {
    vec3 world = vec3(aInstance.x + aPosition.x * 0.985,
                      aInstance.y + aPosition.y * aInstance.w,
                      aInstance.z + aPosition.z * 0.985);
    gl_Position = uViewProjection * vec4(world, 1.0);
    vNormal = aNormal;
    vLocal = aPosition;
    vWorld = world;
  }`;
  const FRAGMENT = `#version 300 es
  precision highp float;
  in vec3 vNormal;
  in vec3 vLocal;
  in vec3 vWorld;
  uniform float uTime;
  out vec4 outColor;
  void main() {
    vec3 n = normalize(vNormal);
    float light = max(dot(n, normalize(vec3(-0.4, 0.95, 0.38))), 0.0);
    vec3 top = vec3(0.94, 1.00, 0.66);
    vec3 east = vec3(0.40, 0.48, 0.17);
    vec3 west = vec3(0.17, 0.23, 0.09);
    vec3 base = n.y > 0.5 ? top : (n.x > 0.5 || n.z > 0.5 ? east : west);
    float ambient = n.y > 0.5 ? 0.94 : 0.60;
    vec3 color = base * (ambient + light * (n.y > 0.5 ? 0.14 : 0.12));
    // thin grid borders on the cube top — keeps every voxel clearly readable
    if (n.y > 0.5) {
      float edge = min(0.5 - abs(vLocal.x), 0.5 - abs(vLocal.z));
      float line = 1.0 - smoothstep(0.00, 0.055, edge);
      color = mix(color, vec3(0.60, 0.70, 0.24), line * 0.30);
    }
    outColor = vec4(color, 1.0);
  }`;
  const FLOOR_VERTEX = `#version 300 es
  precision highp float;
  layout(location=0) in vec3 aPosition;
  uniform mat4 uViewProjection;
  out vec2 vUV;
  void main(){
    vUV = aPosition.xz;
    gl_Position = uViewProjection * vec4(aPosition,1.0);
  }`;
  const FLOOR_FRAGMENT = `#version 300 es
  precision highp float;
  in vec2 vUV;
  out vec4 outColor;
  void main(){
    vec2 grid = abs(fract(vUV + 0.5) - 0.5);
    float nearestLine = 0.5 - max(grid.x, grid.y);
    float border = 1.0 - smoothstep(0.0, 0.042, nearestLine);
    vec3 ground = vec3(0.80, 0.87, 0.32);
    vec3 line = vec3(0.45, 0.52, 0.18);
    outColor = vec4(mix(ground,line,border * 0.42),1.0);
  }`;

  function shader(gl, type, source) {
    const sh = gl.createShader(type);
    gl.shaderSource(sh,source); gl.compileShader(sh);
    if(!gl.getShaderParameter(sh,gl.COMPILE_STATUS)) {
      throw new Error(gl.getShaderInfoLog(sh)||'Shader compile error');
    }
    return sh;
  }
  function program(gl, vertex, fragment) {
    const p=gl.createProgram();
    gl.attachShader(p,shader(gl,gl.VERTEX_SHADER,vertex));
    gl.attachShader(p,shader(gl,gl.FRAGMENT_SHADER,fragment));
    gl.linkProgram(p);
    if(!gl.getProgramParameter(p,gl.LINK_STATUS))throw new Error(gl.getProgramInfoLog(p));
    return p;
  }
  function perspective(fov, aspect, near, far) {
    const f=1/Math.tan(fov/2), nf=1/(near-far);
    return new Float32Array([f/aspect,0,0,0, 0,f,0,0, 0,0,(far+near)*nf,-1, 0,0,2*far*near*nf,0]);
  }
  function norm(a) {const s=1/Math.hypot(...a);return a.map(n=>n*s);}
  function cross(a,b) {return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];}
  function dot(a,b) {return a[0]*b[0]+a[1]*b[1]+a[2]*b[2];}
  function lookAt(eye, center) {
    const z=norm(eye.map((n,i)=>n-center[i]));
    const x=norm(cross([0,1,0],z));
    const y=cross(z,x);
    return new Float32Array([x[0],y[0],z[0],0,x[1],y[1],z[1],0,x[2],y[2],z[2],0,-dot(x,eye),-dot(y,eye),-dot(z,eye),1]);
  }
  function multiply(a,b) {
    const out=new Float32Array(16);
    for(let c=0;c<4;c++)for(let r=0;r<4;r++){
      out[c*4+r] = a[r]*b[c*4]+a[4+r]*b[c*4+1]+a[8+r]*b[c*4+2]+a[12+r]*b[c*4+3];
    }
    return out;
  }
  function buildCube(){
    const arr=[];
    function face(n, v){for(const k of [0,1,2,0,2,3])arr.push(...v[k],...n);}
    face([0,1,0],[[-.5,1,-.5],[.5,1,-.5],[.5,1,.5],[-.5,1,.5]]);
    face([0,-1,0],[[-.5,0,.5],[.5,0,.5],[.5,0,-.5],[-.5,0,-.5]]);
    face([1,0,0],[[.5,0,-.5],[.5,0,.5],[.5,1,.5],[.5,1,-.5]]);
    face([-1,0,0],[[-.5,0,.5],[-.5,0,-.5],[-.5,1,-.5],[-.5,1,.5]]);
    face([0,0,1],[[.5,0,.5],[-.5,0,.5],[-.5,1,.5],[.5,1,.5]]);
    face([0,0,-1],[[-.5,0,-.5],[.5,0,-.5],[.5,1,-.5],[-.5,1,-.5]]);
    return new Float32Array(arr);
  }
  function gauss(x,z,cx,cz,sx,sz){const dx=(x-cx)/sx,dz=(z-cz)/sz;return Math.exp(-0.5*(dx*dx+dz*dz));}
  function smoothstep(a,b,x){const t=Math.max(0,Math.min(1,(x-a)/(b-a)));return t*t*(3-2*t);}
  function lerp(a,b,t){return a+(b-a)*t;}
  class WhatIfVoxel {
    constructor(canvas, options={}){
      this.canvas=canvas;
      this.gl=canvas.getContext('webgl2',{alpha:false,antialias:true,powerPreference:'high-performance'});
      if(!this.gl)throw new Error('WebGL2 지원 브라우저가 필요합니다.');
      this.options={ cols:30,rows:26,layers:10, intensity:0.5, ...options };
      this.intensity=Math.min(1,Math.max(0,this.options.intensity));
      this.width=this.options.cols;this.depth=this.options.rows;
      this.pointer={x:0,y:0};this.elapsed=0;this.paused=false;this.visible=true;
      this._raf=0;this._last=0;this._frameAcc=0;this._destroyed=false;this._pausedFrameDrawn=false;
      this._instances=new Float32Array(this.width*this.depth*this.options.layers*4);
      this._heights=new Float32Array(this.width*this.depth);
      this.initGL();
      this.onPointer=(e)=>{const r=canvas.getBoundingClientRect();this.pointer.x=((e.clientX-r.left)/r.width-.5)*2;this.pointer.y=((e.clientY-r.top)/r.height-.5)*2;};
      this.onOut=()=>{this.pointer.x=0;this.pointer.y=0;};
      this.onResize=()=>this.resize();
      canvas.addEventListener('pointermove',this.onPointer);
      canvas.addEventListener('pointerleave',this.onOut);
      this.resizeObserver=new ResizeObserver(this.onResize);
      this.resizeObserver.observe(canvas);
      this.intersectionObserver=new IntersectionObserver(entries=>{this.visible=entries[0]?.isIntersecting??true;});
      this.intersectionObserver.observe(canvas);
      this.motionQuery=window.matchMedia('(prefers-reduced-motion: reduce)');
      if(this.motionQuery.matches)this.paused=true;
      this.resize();this.tick(performance.now());
    }
    initGL(){
      const gl=this.gl;
      this.cubeProgram=program(gl,VERTEX,FRAGMENT);
      this.floorProgram=program(gl,FLOOR_VERTEX,FLOOR_FRAGMENT);
      this.cubeVao=gl.createVertexArray();gl.bindVertexArray(this.cubeVao);
      const geometry=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,geometry);gl.bufferData(gl.ARRAY_BUFFER,buildCube(),gl.STATIC_DRAW);
      gl.enableVertexAttribArray(0);gl.vertexAttribPointer(0,3,gl.FLOAT,false,24,0);
      gl.enableVertexAttribArray(1);gl.vertexAttribPointer(1,3,gl.FLOAT,false,24,12);
      this.instanceBuffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,this.instanceBuffer);
      gl.bufferData(gl.ARRAY_BUFFER,this._instances.byteLength,gl.DYNAMIC_DRAW);
      gl.enableVertexAttribArray(2);gl.vertexAttribPointer(2,4,gl.FLOAT,false,16,0);gl.vertexAttribDivisor(2,1);
      gl.bindVertexArray(null);
      this.floorVao=gl.createVertexArray();gl.bindVertexArray(this.floorVao);
      const x=this.width/2+11,z=this.depth/2+11;
      const floor=new Float32Array([-x,-0.09,-z, x,-0.09,-z, x,-0.09,z, -x,-0.09,-z, x,-0.09,z, -x,-0.09,z]);
      const floorBuf=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,floorBuf);gl.bufferData(gl.ARRAY_BUFFER,floor,gl.STATIC_DRAW);
      gl.enableVertexAttribArray(0);gl.vertexAttribPointer(0,3,gl.FLOAT,false,12,0);
      gl.bindVertexArray(null);
      this._buffers=[geometry,this.instanceBuffer,floorBuf];
      this._uCube=gl.getUniformLocation(this.cubeProgram,'uViewProjection');
      this._uFloor=gl.getUniformLocation(this.floorProgram,'uViewProjection');
      gl.enable(gl.DEPTH_TEST);gl.depthFunc(gl.LEQUAL);
      gl.disable(gl.CULL_FACE);
    }
    resize(){
      if(this._destroyed)return;
      const rect=this.canvas.getBoundingClientRect();
      const dpr=Math.min(window.devicePixelRatio||1,1.6);
      const w=Math.max(1,Math.round(rect.width*dpr));const h=Math.max(1,Math.round(rect.height*dpr));
      if(this.canvas.width!==w||this.canvas.height!==h){this.canvas.width=w;this.canvas.height=h;this.gl.viewport(0,0,w,h);}
    }
    setIntensity(value){this.intensity=Math.max(0,Math.min(1,Number(value)||0));}
    setScenario({rateBp=0,fxPct=0,oilPct=0,vixPt=0}={}){
      // Visual mapping only, NOT a financial model / return forecast.
      const stress=Math.abs(rateBp)/300*.30+Math.abs(fxPct)/30*.30+Math.abs(oilPct)/80*.20+Math.abs(vixPt)/80*.20;
      this.setIntensity(Math.min(1,stress));
    }
    pause(){this.paused=true;this._pausedFrameDrawn=false;}
    play(){this.paused=false;this._pausedFrameDrawn=false;}
    get isPaused(){return this.paused;}
    targetHeight(x,z,t){
      const intensity=this.intensity;
      const breath=Math.sin(t*.78)*.65;
      const drift=Math.sin(t*.3)*1.3;
      // Form A: broad concentric platform with several irregular stepped mounds.
      const r=Math.hypot(x+1.2,z+0.8);
      const a=Math.max(0,6.1-r*.40)
        + 2.8*gauss(x,z,-7+drift,4,3.5,3.8)
        + 2.1*gauss(x,z,7,-5+drift,3,3)
        - 3.3*gauss(x,z,0.5,0.3,2.0,1.8)
        + .55*Math.cos(x*.8+z*.41);
      // Form B: a terraced central pyramid, like the middle of the source clip.
      const cx=drift*.7,cz=-1.0;
      const b=Math.max(0,9.7-Math.max(Math.abs(x-cx)*.93,Math.abs(z-cz)*1.15))
        + 1.4*gauss(x,z,8,5,3.3,3.3)
        + .35*Math.cos(x*.95-z*.72);
      // Form C: softer multi-lobed wave terrain.
      const c=4.2*gauss(x,z,-5+drift,-2,6,5)
        +5.1*gauss(x,z,6,2+drift,4.2,3.8)
        +2.4*gauss(x,z,-.5,-7,4,3)
        -.6*Math.sin(x*.65+z*.82);
      const phase=((t%12)+12)%12;
      let h;
      if(phase<1.5) h=lerp(0,Math.max(0,a),smoothstep(0.1,1.5,phase));
      else if(phase<3.9) h=lerp(a,c,smoothstep(1.6,3.9,phase));
      else if(phase<6.8) h=lerp(c,b,smoothstep(4,6.8,phase));
      else if(phase<9.2) h=lerp(b,a,smoothstep(6.9,9.2,phase));
      else h=lerp(a,0,smoothstep(10,12,phase));
      // The slider controls overall elevation and active variation.
      const sx=x-this.pointer.x*2.0, sz=z-this.pointer.y*1.5;
      const active=gauss(sx,sz,this.pointer.x*4,this.pointer.y*3,5,5);
      const pointerEffect=(Math.abs(this.pointer.x)+Math.abs(this.pointer.y))*.85*active;
      return Math.min(this.options.layers,Math.max(0,(h+breath*.14)*(0.62+intensity*.70)+pointerEffect));
    }
    draw(t){
      const gl=this.gl;
      const {width,depth}=this;
      const frame=this._instances;
      let cursor=0;
      for(let z=0;z<depth;z++)for(let x=0;x<width;x++){
        const wx=x-(width-1)/2, wz=z-(depth-1)/2;
        const id=z*width+x;
        const target=this.targetHeight(wx,wz,t);
        const previous=this._heights[id];
        const current=previous + (target-previous)*.26;
        this._heights[id]=current;
        const maxLevel=Math.min(this.options.layers,Math.ceil(current));
        for(let level=0;level<maxLevel;level++){
          const remaining=Math.min(1,Math.max(0,current-level));
          if(remaining<.035)continue;
          frame[cursor++]=wx;
          frame[cursor++]=level;
          frame[cursor++]=wz;
          frame[cursor++]=remaining;
        }
      }
      const n=cursor/4;
      gl.clearColor(0.954,1.0,0.0,1);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
      const aspect=this.canvas.width/this.canvas.height;
      const proj=perspective((aspect<.8?54:41)*Math.PI/180,aspect,.1,150);
      const theta=this.pointer.x*.08+Math.sin(t*.10)*.05;
      const eye=[25*Math.cos(theta)-22*Math.sin(theta),19-this.pointer.y*.7,31*Math.cos(theta)+17*Math.sin(theta)];
      const view=lookAt(eye,[0,6.0,0]);
      const vp=multiply(proj,view);
      gl.useProgram(this.floorProgram);gl.uniformMatrix4fv(this._uFloor,false,vp);
      gl.bindVertexArray(this.floorVao);gl.drawArrays(gl.TRIANGLES,0,6);
      gl.useProgram(this.cubeProgram);gl.uniformMatrix4fv(this._uCube,false,vp);
      gl.bindVertexArray(this.cubeVao);
      gl.bindBuffer(gl.ARRAY_BUFFER,this.instanceBuffer);
      gl.bufferSubData(gl.ARRAY_BUFFER,0,frame.subarray(0,cursor));
      gl.drawArraysInstanced(gl.TRIANGLES,0,36,n);
      gl.bindVertexArray(null);
    }
    tick(now){
      if(this._destroyed)return;
      this._raf=requestAnimationFrame(t=>this.tick(t));
      const dt=this._last?Math.min((now-this._last)/1000,.05):.016;this._last=now;
      if(!this.visible)return;
      if(this.paused){
        if(!this._pausedFrameDrawn){ this.draw(this.elapsed); this._pausedFrameDrawn=true; }
        return;
      }
      this._pausedFrameDrawn=false;
      this.elapsed+=dt;
      // ~50fps maximum: keep adequate headroom for the rest of the web app.
      this._frameAcc+=dt;
      if(this._frameAcc<1/50)return;
      this._frameAcc=0;
      this.draw(this.elapsed);
    }
    destroy(){
      this._destroyed=true;cancelAnimationFrame(this._raf);
      this.canvas.removeEventListener('pointermove',this.onPointer);
      this.canvas.removeEventListener('pointerleave',this.onOut);
      this.resizeObserver.disconnect();this.intersectionObserver.disconnect();
      const gl=this.gl;for(const buf of this._buffers)gl.deleteBuffer(buf);
      gl.deleteVertexArray(this.cubeVao);gl.deleteVertexArray(this.floorVao);
      gl.deleteProgram(this.cubeProgram);gl.deleteProgram(this.floorProgram);
    }
  }
  window.WhatIfVoxel=WhatIfVoxel;
})();
