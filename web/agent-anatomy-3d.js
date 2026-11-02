import * as THREE from './vendor/three/three.module.js';
import {OrbitControls} from './vendor/three/OrbitControls.js';
import {mergeGeometries} from './vendor/three/BufferGeometryUtils.js';

// Geometry is a visual metaphor. All role facts come from the anatomy API.
const anchors = {
  mission:[0,3.65,.45], persona:[0,3.17,.74], tools:[1.48,1.7,.35],
  memory:[-.85,2.25,.56], policy:[1.04,2.68,.6], limits:[.61,2.13,.76],
  model:[0,2.18,.92], protocols:[.67,4.15,0], events:[-1.04,3.09,-.05],
  evals:[0,1.52,.85], environment:[.9,.58,.66],
};
export function createAgentModel({detail=true}={}) {
  const resources=new Set(), parts=new Map(), root=new THREE.Group(), rig=new THREE.Group();
  root.add(rig);
  const mat=(color,metalness=.45,roughness=.32,extra={})=>{
    const m=new THREE.MeshStandardMaterial({color,metalness,roughness,...extra});
    resources.add(m); return m;
  };
  const alloy=mat(0xb2c5ce,.65,.3), dark=mat(0x243640,.7,.3);
  const rubber=mat(0x101d24,.12,.82), metal=mat(0x647f8e,.8,.24);
  const light=mat(0x60dfd3,.25,.28,{emissive:0x1ca999,emissiveIntensity:.35});
  const glass=mat(0x153c48,.55,.16), pale=mat(0xc3d2d4,.4,.5);
  const accent=mat(0x478b91,.65,.34);accent.userData.rolePaint=true;
  const beacon=mat(0x60dfd3,.2,.3,{emissive:0x60dfd3,emissiveIntensity:.35});beacon.userData.roleBeacon=true;
  const geometry=g=>{resources.add(g);return g;};
  function part(id){const p=new THREE.Group(); p.userData.part=id;rig.add(p);parts.set(id,p);return p;}
  function mesh(g,m,parent,x=0,y=0,z=0){
    const obj=new THREE.Mesh(geometry(g),m);obj.position.set(x,y,z);
    obj.castShadow=true;obj.receiveShadow=true;parent.add(obj);return obj;
  }
  function bevel(w,h,d,r=.08) {
    if(!detail)return new THREE.BoxGeometry(w,h,d);
    const s=new THREE.Shape(),x=-w/2,y=-h/2;
    s.moveTo(x+r,y);s.lineTo(x+w-r,y);s.quadraticCurveTo(x+w,y,x+w,y+r);
    s.lineTo(x+w,y+h-r);s.quadraticCurveTo(x+w,y+h,x+w-r,y+h);
    s.lineTo(x+r,y+h);s.quadraticCurveTo(x,y+h,x,y+h-r);
    s.lineTo(x,y+r);s.quadraticCurveTo(x,y,x+r,y);
    const g=new THREE.ExtrudeGeometry(s,{depth:d-.06,bevelEnabled:true,bevelSegments:2,steps:1,bevelSize:.03,bevelThickness:.03,curveSegments:5});
    g.translate(0,0,-d/2+.03);return g;
  }
  const box=(p,x,y,z,w,h,d,m=alloy,r=.07)=>mesh(bevel(w,h,d,r),m,p,x,y,z);
  const cylinder=(p,x,y,z,r,h,m=metal,r2=r)=>mesh(new THREE.CylinderGeometry(r,r2,h,detail?24:10),m,p,x,y,z);
  const sphere=(p,x,y,z,r,m=metal)=>mesh(new THREE.SphereGeometry(r,detail?18:8,detail?12:6),m,p,x,y,z);
  const tube=(p,points,r,m=metal)=>{
    const curve=new THREE.CatmullRomCurve3(points.map(v=>new THREE.Vector3(...v)));
    return mesh(new THREE.TubeGeometry(curve,detail?16:6,r,detail?8:5,false),m,p);
  };
  const ring=(p,x,y,z,r,t,m=metal)=>mesh(new THREE.TorusGeometry(r,t,detail?10:6,detail?36:12),m,p,x,y,z);
  const base=part('environment');
  box(base,0,.96,0,1.58,.4,1.05,dark);
  for(const side of [-1,1]){
    box(base,side*.88,.46,0,.52,.77,1.72,rubber,.2);
    box(base,side*1.15,.46,0,.08,.47,1.42,metal,.12).rotation.y=Math.PI/2;
    for(const z of [-.55,0,.55]){
      const wheel=cylinder(base,side*1.17,.44,z,.24,.08,dark);
      wheel.rotation.z=Math.PI/2;
      const hub=cylinder(base,side*1.22,.44,z,.115,.09,alloy);
      hub.rotation.z=Math.PI/2;
    }
    for(let i=0;i<9;i++)box(base,side*.88,.83,-.72+i*.18,.55,.065,.08,metal,.015);
  }
  cylinder(base,0,1.18,0,.45,.2,metal);
  const cage=part('policy');
  box(cage,0,2.12,0,1.5,1.55,1.02,dark,.15);
  box(cage,0,1.38,0,1.75,.15,1.3,alloy);
  for(const x of [-.83,.83]){
    tube(cage,[[x,1.43,.62],[x,2.7,.62],[x*.78,2.89,.4]],.055,metal);
    sphere(cage,x,2.69,.64,.09,alloy);
  }
  box(cage,0,2.84,.53,1.57,.1,.12,metal,.025);
  const cab=part('mission');
  cylinder(cab,0,2.94,0,.35,.16,metal);
  box(cab,0,3.32,0,1.5,.69,1.14,alloy,.16);
  box(cab,0,3.68,0,1.38,.08,1.03,accent,.025);
  box(cab,0,3.47,.58,1.17,.21,.04,glass,.04);
  for(const x of [-.55,.55])box(cab,x,3.49,.61,.03,.14,.035,metal,.012);
  const face=part('persona');
  box(face,0,3.14,.59,1.16,.22,.14,dark,.055);
  for(const x of [-.3,.3]){
    box(face,x,3.15,.675,.21,.065,.025,light,.025);
    box(face,x,3.1,.685,.12,.016,.025,metal,.005);
  }
  const engine=part('model');
  box(engine,0,2.18,.54,.76,.81,.19,metal,.12);
  ring(engine,0,2.2,.7,.29,.055,dark);
  ring(engine,0,2.2,.74,.22,.025,light);
  const fan=new THREE.Group();engine.add(fan);fan.position.set(0,2.2,.76);
  for(let i=0;i<8;i++){
    const a=i*Math.PI/4;
    const blade=box(fan,Math.sin(a)*.13,Math.cos(a)*.13,0,.095,.17,.035,dark,.02);
    blade.rotation.z=-a-.35;
  }
  sphere(engine,0,2.2,.79,.075,alloy);
  const memory=part('memory');
  cylinder(memory,-.68,2.12,.48,.22,1.08,metal);
  cylinder(memory,-.68,2.12,.48,.2,.75,glass);
  for(const y of [1.65,1.82,2.42,2.6])cylinder(memory,-.68,y,.48,.24,.07,alloy);
  for(const y of [1.96,2.1,2.24])box(memory,-.68,y,.685,.12,.04,.035,light,.008);
  tube(memory,[[-.68,2.65,.48],[-.68,2.78,.25],[-.3,2.7,0]],.05,rubber);
  const budget=part('limits');
  box(budget,.59,2.14,.58,.25,.72,.23,alloy,.04);
  box(budget,.59,2.14,.71,.15,.56,.025,dark,.02);
  const budgetBars=[];
  for(let i=0;i<5;i++)budgetBars.push(box(budget,.59,1.94+i*.1,.735,.1,.035,.025,mat(0x647f8e),.005));
  const arms=part('tools');
  const forearms=[];
  for(const s of [-1,1]){
    sphere(arms,s*.96,2.62,0,.22,metal);
    box(arms,s*1.15,2.37,0,.36,.57,.49,alloy,.1).rotation.z=s*.23;
    const elbow=cylinder(arms,s*1.25,2.03,.03,.2,.52,dark);elbow.rotation.x=Math.PI/2;
    ring(arms,s*1.25,2.03,.31,.12,.025,metal);
    const forearm=new THREE.Group();forearm.position.set(s*1.27,1.99,.06);arms.add(forearm);
    box(forearm,0,-.28,0,.28,.53,.36,metal,.07);
    box(forearm,0,-.24,.2,.12,.29,.06,accent,.025);
    for(const side of [-1,1]){
      box(forearm,side*.15,-.66,.07,.1,.28,.15,alloy,.035).rotation.z=side*.16;
      box(forearm,side*.1,-.8,.12,.16,.09,.21,dark,.025);
    }
    forearms.push(forearm);
    tube(arms,[[s*.92,2.65,-.2],[s*1.34,2.45,-.25],[s*1.25,2.03,-.19]],.045,rubber);
  }
  const aerial=part('protocols');
  box(aerial,.54,3.72,-.2,.25,.11,.28,dark,.03);
  cylinder(aerial,.54,3.96,-.2,.035,.44,metal);
  sphere(aerial,.54,4.2,-.2,.14,beacon);
  const dish=cylinder(aerial,.54,4.12,-.2,.19,.06,alloy,.08);dish.rotation.x=.4;
  const events=part('events');
  for(const s of [-1,1]){
    tube(events,[[s*.67,2.72,-.38],[s*.95,2.91,-.38],[s*.95,3.2,-.38]],.11,metal);
    cylinder(events,s*.95,3.21,-.38,.145,.09,dark);
    for(const y of [2.97,3.06,3.15])cylinder(events,s*.95,y,-.38,.13,.035,alloy);
  }
  const sticker=part('evals');
  box(sticker,0,1.55,.59,.52,.24,.16,pale,.04);
  const check=mesh(new THREE.TorusGeometry(.075,.012,8,20),accent,sticker,0,1.56,.68);
  check.scale.y=.85;
  for(const x of [-.62,.62])for(const y of [1.5,2.73])sphere(cage,x,y,.65,.038,metal);
  // A second rear canister gives the silhouette real volume from every orbit.
  cylinder(memory,.35,2.2,-.64,.25,.92,dark);
  for(const y of [1.79,2.61])cylinder(memory,.35,y,-.64,.27,.08,metal);

  function badge(parent,x,y,z,w,h,width,height){
    const surface=document.createElement('canvas');surface.width=width;surface.height=height;
    const texture=new THREE.CanvasTexture(surface);texture.colorSpace=THREE.SRGBColorSpace;resources.add(texture);
    const material=mat(0xffffff,.15,.7,{map:texture});
    mesh(new THREE.PlaneGeometry(w,h),material,parent,x,y,z);
    return {surface,texture,material};
  }
  const roleLight=badge(aerial,.54,4.3,-.04,.38,.38,96,96);
  roleLight.material.transparent=true;roleLight.material.depthWrite=false;
  const roleBadge=badge(cab,0,3.47,.617,1.03,.14,512,72);
  const toolBadges=detail?[-1,1].flatMap(side=>[2.48,2.28].map(y=>badge(arms,side*1.15,y,.267,.19,.16,96,80))):[];
  function paintIcon(target,tool){
    const ctx=target.surface.getContext('2d');ctx.clearRect(0,0,96,80);ctx.fillStyle='#153c48';ctx.fillRect(0,0,96,80);
    if(!tool){target.texture.needsUpdate=true;return;}
    ctx.strokeStyle='#c3d2d4';ctx.lineWidth=5;ctx.lineCap='round';ctx.lineJoin='round';ctx.beginPath();
    const icon=tool.icon;
    if(icon==='search'){ctx.arc(41,32,17,0,Math.PI*2);ctx.moveTo(54,46);ctx.lineTo(69,61);}
    else if(icon==='shield'){ctx.moveTo(48,12);ctx.lineTo(71,22);ctx.lineTo(65,48);ctx.lineTo(48,65);ctx.lineTo(31,48);ctx.lineTo(25,22);ctx.closePath();}
    else if(icon==='message'){ctx.rect(22,17,52,34);ctx.moveTo(38,51);ctx.lineTo(31,66);ctx.lineTo(53,51);}
    else if(icon==='route'){ctx.moveTo(22,58);ctx.lineTo(42,58);ctx.lineTo(42,25);ctx.lineTo(73,25);ctx.moveTo(61,15);ctx.lineTo(73,25);ctx.lineTo(61,35);}
    else if(icon==='clock'){ctx.arc(48,39,25,0,Math.PI*2);ctx.moveTo(48,21);ctx.lineTo(48,39);ctx.lineTo(64,47);}
    else if(icon==='memory'){ctx.rect(26,14,44,52);ctx.moveTo(36,28);ctx.lineTo(60,28);ctx.moveTo(36,40);ctx.lineTo(60,40);ctx.moveTo(36,52);ctx.lineTo(60,52);}
    else{ctx.rect(25,19,46,42);ctx.moveTo(25,32);ctx.lineTo(71,32);ctx.moveTo(48,19);ctx.lineTo(48,41);}
    ctx.stroke();target.texture.needsUpdate=true;
  }
  function decorate(agent,canvas){
    const color=agent.visual?.color||"#23d8ce";
    window.AgentRoleSymbols.paint(roleLight.surface,agent.visual);roleLight.texture.needsUpdate=true;
    for(const material of resources){
      if(material.userData?.rolePaint)material.color.set(color);
      if(material.userData?.roleBeacon){material.color.set(color);material.emissive.set(color);}
    }
    rig.traverse(obj=>{if(obj.isMesh&&obj.material.userData.roleBeacon&&obj.userData.originalEmissive)obj.userData.originalEmissive.set(color);});
    if(canvas)canvas.dataset.roleColor=color;
    const ctx=roleBadge.surface.getContext('2d');ctx.fillStyle='#153c48';ctx.fillRect(0,0,512,72);
    ctx.fillStyle='#e5eef5';ctx.font='600 38px "IBM Plex Sans", sans-serif';ctx.textAlign='center';ctx.textBaseline='middle';
    ctx.fillText(agent.badge,256,37,480);roleBadge.texture.needsUpdate=true;
    const lit=Math.ceil(agent.budget.fraction*5);
    budgetBars.forEach((bar,i)=>{
      bar.material.color.setHex(i<lit?0x60dfd3:0x647f8e);
      bar.userData.originalEmissive?.setHex(i<lit?0x1ca999:0);
      bar.userData.originalIntensity=i<lit?.35:0;
    });
    toolBadges.forEach((badge,index)=>paintIcon(badge,agent.tool_badges[index]));
    if(canvas){canvas.dataset.budget=JSON.stringify({...agent.budget,bars:lit});
    canvas.dataset.tools=JSON.stringify(agent.tool_badges.map(t=>t.id));
    canvas.dataset.badge=agent.badge;}
  }

  // Batch rigid surfaces by material while keeping the articulated groups separate.
  function batch(parent){
    for(const child of [...parent.children])if(child.isGroup)batch(child);
    const buckets=new Map();
    for(const child of parent.children)if(child.isMesh){
      const bucket=buckets.get(child.material)||[];bucket.push(child);buckets.set(child.material,bucket);
    }
    for(const [material,meshes] of buckets){
      if(meshes.length<2)continue;
      const geometries=meshes.map(child=>{
        child.updateMatrix();const copy=child.geometry.index?child.geometry.toNonIndexed():child.geometry.clone();
        copy.applyMatrix4(child.matrix);return copy;
      });
      const merged=mergeGeometries(geometries,false);geometries.forEach(g=>g.dispose());
      if(!merged)continue;
      meshes.forEach(child=>parent.remove(child));mesh(merged,material,parent);
    }
  }
  if(!detail){
    rig.updateMatrixWorld(true);
    const flat=new THREE.Group();
    rig.traverse(obj=>{if(obj.isMesh){
      const copy=new THREE.Mesh(obj.geometry,obj.material);
      copy.applyMatrix4(obj.matrixWorld);flat.add(copy);
    }});
    rig.clear();rig.add(flat);batch(flat);
  }else batch(rig);
  const ownedMaterials=new Set();
  if(detail)for(const p of parts.values())p.traverse(obj=>{
    if(obj.isMesh){obj.material=obj.material.clone();resources.add(obj.material);ownedMaterials.add(obj.material);
      obj.userData.originalEmissive=obj.material.emissive.clone();obj.userData.originalIntensity=obj.material.emissiveIntensity;}
  });
  return {resources,parts,root,rig,mat,mesh,ring,metal,fan,forearms,decorate};
}

export function createAgentScene(host, {onPart, onFailure, buttons}) {
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const renderer = new THREE.WebGLRenderer({antialias:true,alpha:false,preserveDrawingBuffer:true,powerPreference:'low-power'});
  renderer.setPixelRatio(Math.min(devicePixelRatio,1.5));
  renderer.setClearColor(0x0c151c);
  renderer.shadowMap.enabled=true; renderer.shadowMap.type=THREE.PCFSoftShadowMap;
  renderer.toneMapping=THREE.ACESFilmicToneMapping; renderer.toneMappingExposure=1.3;
  const canvas=renderer.domElement;
  canvas.tabIndex=0; canvas.setAttribute('role','img');
  canvas.setAttribute('aria-label','3D agent. Drag to rotate, arrows to orbit, plus and minus to zoom. Select a component using the adjacent controls.');
  host.prepend(canvas);
  const scene=new THREE.Scene();
  scene.fog=new THREE.Fog(0x0c151c,15,32);
  const camera=new THREE.PerspectiveCamera(34,1,.1,60);
  const controls=new OrbitControls(camera,canvas);
  controls.enablePan=false; controls.enableDamping=false;
  controls.minDistance=4; controls.maxDistance=20;
  controls.minPolarAngle=.45; controls.maxPolarAngle=1.55;
  controls.enableZoom=false; // Page scrolling remains native; explicit buttons/keys zoom.
  const {resources,parts,root,rig,mat,mesh,ring,metal,fan,forearms,decorate}=createAgentModel();
  scene.add(root);
  const platform=mesh(new THREE.CylinderGeometry(2.35,2.43,.13,80),mat(0x182730,.5,.6),scene,0,-.035,0);
  platform.receiveShadow=true;
  const trim=ring(scene,0,.04,0,2.25,.012,metal);trim.rotation.x=-Math.PI/2;
  const floor=mesh(new THREE.PlaneGeometry(100,100),mat(0x0c151c,.1,.9),scene,0,-.11,0);
  floor.rotation.x=-Math.PI/2;floor.castShadow=false;
  scene.add(new THREE.HemisphereLight(0xc8dde7,0x223038,2.2));
  const key=new THREE.SpotLight(0xe9f3fa,105,30,.55,.75,1);
  key.position.set(-4,8,6);key.target.position.set(0,1.9,0);key.castShadow=true;
  key.shadow.mapSize.set(1024,1024);key.shadow.bias=-.0003;key.shadow.normalBias=.03;
  scene.add(key,key.target);
  const rim=new THREE.DirectionalLight(0x7ba6b5,3.2);rim.position.set(4,5,-5);scene.add(rim);
  const fill=new THREE.DirectionalLight(0x9cc4ca,1.1);fill.position.set(4,2,5);scene.add(fill);
  let disposed=false,selected=null,hovered=null,motion=true,visible=true,last=0,clock=0;
  let dirty=true,frames=0,totalMs=0,fps=30,raf=0,viewWidth=0,viewHeight=0;
  const bodyBox=new THREE.Box3().setFromObject(rig);
  const baseTarget=bodyBox.getCenter(new THREE.Vector3());
  const baseDirection=new THREE.Vector3(5.6,1.65,8.6).normalize();
  const basePosition=baseTarget.clone().addScaledVector(baseDirection,10);
  const corners=box=>{
    const points=[];
    for(const x of [box.min.x,box.max.x])for(const y of [box.min.y,box.max.y])
      for(const z of [box.min.z,box.max.z])points.push(new THREE.Vector3(x,y,z));
    return points;
  };
  // Fit the actual body, excluding the floor, for this orbit and viewport.
  // Selection never changes the camera; resizing and orbiting retain a safe margin.
  function fitFrame(exact=false){
    scene.updateMatrixWorld(true);
    const direction=camera.position.clone().sub(baseTarget).normalize();
    const right=new THREE.Vector3().crossVectors(camera.up,direction).normalize();
    const up=new THREE.Vector3().crossVectors(direction,right);
    const vertical=Math.tan(THREE.MathUtils.degToRad(camera.fov)/2),horizontal=vertical*camera.aspect;
    let distance=0;
    for(const corner of corners(new THREE.Box3().setFromObject(rig))){
      const v=corner.sub(baseTarget),depth=v.dot(direction);
      distance=Math.max(distance,Math.abs(v.dot(right))/horizontal+depth,Math.abs(v.dot(up))/vertical+depth);
    }
    distance*=1.1;
    controls.minDistance=distance;controls.maxDistance=distance*1.4;
    const radius=exact?distance:Math.max(distance,Math.min(controls.maxDistance,camera.position.distanceTo(baseTarget)));
    camera.position.copy(baseTarget).addScaledVector(direction,radius);
    controls.target.copy(baseTarget);
  }
  function reset(){
    selected=null;root.rotation.y=0;delete canvas.dataset.viewWidth;
    camera.position.copy(basePosition);controls.target.copy(baseTarget);fitFrame(true);
    highlight();
  }
  function focus(id){
    selected=id;delete canvas.dataset.viewWidth;highlight();
  }
  function highlight(){
    for(const [id,p] of parts)p.traverse(obj=>{
      if(!obj.isMesh)return;
      obj.material.emissive.copy(obj.userData.originalEmissive);
      obj.material.emissiveIntensity=obj.userData.originalIntensity;
      if(id===(hovered||selected)){obj.material.emissive.setHex(0x32b2ad);obj.material.emissiveIntensity=.21;}
    });
    dirty=true;
  }
  const ray=new THREE.Raycaster(),pointer=new THREE.Vector2();
  const hit=event=>{
    const rect=canvas.getBoundingClientRect();
    pointer.set((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1);
    ray.setFromCamera(pointer,camera);
    const intersect=ray.intersectObject(rig,true)[0];
    let obj=intersect?.object;while(obj&&!obj.userData.part)obj=obj.parent;
    return obj?.userData.part||null;
  };
  let down=null;
  canvas.addEventListener('pointerdown',event=>{down=[event.clientX,event.clientY];});
  canvas.addEventListener('pointermove',event=>{const next=hit(event);if(next!==hovered){hovered=next;highlight();canvas.style.cursor=next?'pointer':'grab';}});
  canvas.addEventListener('pointerleave',()=>{hovered=null;highlight();});
  canvas.addEventListener('pointerup',event=>{
    if(down&&Math.hypot(event.clientX-down[0],event.clientY-down[1])<5){const id=hit(event);if(id)onPart(id);}
    down=null;
  });
  canvas.addEventListener('keydown',event=>{
    if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','=','-'].includes(event.key)){
      event.preventDefault();delete canvas.dataset.viewWidth;
      const v=camera.position.clone().sub(controls.target),s=new THREE.Spherical().setFromVector3(v);
      if(event.key==='ArrowLeft')s.theta-=.12;if(event.key==='ArrowRight')s.theta+=.12;
      if(event.key==='ArrowUp')s.phi=Math.max(.45,s.phi-.1);if(event.key==='ArrowDown')s.phi=Math.min(1.55,s.phi+.1);
      if(event.key==='+'||event.key==='=')s.radius=Math.max(controls.minDistance,s.radius*.9);if(event.key==='-')s.radius=Math.min(controls.maxDistance,s.radius*1.1);
      camera.position.copy(controls.target).add(new THREE.Vector3().setFromSpherical(s));dirty=true;
    }
  });
  controls.addEventListener('change',()=>{fitFrame();dirty=true;});
  function resize(){
    const w=host.clientWidth,h=host.clientHeight;if(!w||!h)return;
    if(w===viewWidth&&h===viewHeight)return;
    viewWidth=w;viewHeight=h;delete canvas.dataset.viewWidth;delete canvas.dataset.viewHeight;
    camera.aspect=w/h;camera.updateProjectionMatrix();renderer.setSize(w,h,false);
    fitFrame(true);
    dirty=true;
  }
  const resizeObserver=new ResizeObserver(resize);resizeObserver.observe(host);
  const intersection=new IntersectionObserver(entries=>{visible=entries[0]?.isIntersecting;dirty=true;});intersection.observe(host);
  function project(){
    scene.updateMatrixWorld(true);camera.updateMatrixWorld();
    const projected=corners(new THREE.Box3().setFromObject(rig)).map(p=>p.project(camera));
    canvas.dataset.bodyBounds=JSON.stringify({
      left:Math.min(...projected.map(p=>(p.x+1)/2)),right:Math.max(...projected.map(p=>(p.x+1)/2)),
      top:Math.min(...projected.map(p=>(1-p.y)/2)),bottom:Math.max(...projected.map(p=>(1-p.y)/2)),
    });
    for(const [id,button] of Object.entries(buttons)){
      const point=rig.localToWorld(new THREE.Vector3(...anchors[id])).project(camera);
      const x=(point.x+1)/2*host.clientWidth,y=(1-point.y)/2*host.clientHeight;
      button.hidden=false;
      button.style.transform='translate('+Math.max(22,Math.min(host.clientWidth-22,x)).toFixed(1)+'px,'+Math.max(22,Math.min(host.clientHeight-22,y)).toFixed(1)+'px) translate(-50%,-50%)';
    }
  }
  const onLost=event=>{event.preventDefault();dispose();onFailure();};
  canvas.addEventListener('webglcontextlost',onLost);
  const onReduced=()=>{if(reduced.matches){root.rotation.y=0;rig.position.y=0;}dirty=true;};
  reduced.addEventListener('change',onReduced);
  function draw(now){
    if(disposed)return;
    raf=requestAnimationFrame(draw);
    if(dirty){const bounds=host.getBoundingClientRect();visible=bounds.width>0&&bounds.height>0&&bounds.bottom>0&&bounds.top<innerHeight;}
    if(document.hidden||!visible||host.hidden||now-last<1000/fps)return;
    resize(); // Layout may change before ResizeObserver delivers its callback.
    const dt=Math.min((now-last)/1000,.08);last=now;
    const animate=motion&&!reduced.matches;
    if(animate){
      clock+=dt;rig.position.y=Math.sin(clock*1.2)*.018;
      fan.rotation.z=clock*.22;
      forearms[0].rotation.x=Math.sin(clock*.65)*.025;
      forearms[1].rotation.x=-Math.sin(clock*.65)*.025;
      if(!selected&&!down)root.rotation.y=Math.sin(clock*.2)*.13;
      dirty=true;
    }
    if(!dirty)return;
    // Changing pixel ratio clears the drawing buffer; do it before this frame renders.
    if(frames===45&&totalMs/frames>35){renderer.setPixelRatio(1);fps=15;}
    const start=performance.now();controls.update();project();renderer.render(scene,camera);dirty=false;
    canvas.dataset.render=JSON.stringify({calls:renderer.info.render.calls,triangles:renderer.info.render.triangles});
    canvas.dataset.camera=[...camera.position.toArray(),...controls.target.toArray()].map(v=>v.toFixed(2)).join(',');
    canvas.dataset.viewWidth=String(viewWidth);canvas.dataset.viewHeight=String(viewHeight);canvas.dataset.frames=String(frames);canvas.dataset.motion=animate?'playing':'paused';canvas.dataset.part=selected||'';
    frames++;totalMs+=performance.now()-start;
  }
  function dispose(){
    if(disposed)return;disposed=true;cancelAnimationFrame(raf);resizeObserver.disconnect();intersection.disconnect();controls.dispose();
    reduced.removeEventListener('change',onReduced);canvas.removeEventListener('webglcontextlost',onLost);
    for(const item of resources)item.dispose();renderer.dispose();canvas.remove();
  }
  camera.position.copy(basePosition);controls.target.copy(baseTarget);resize();raf=requestAnimationFrame(draw);
  return {focus,reset,dispose,pause(value){motion=!value;dirty=true;},hover(id){hovered=id;highlight();},
    agent(agent){canvas.dataset.agent=agent.id;decorate(agent,canvas);reset();},
    wake(){dirty=true;resize();}};
}
