import * as THREE from './vendor/three/three.module.js';
import {OrbitControls} from './vendor/three/OrbitControls.js';

const positions={inventory:[-11,1.5],fulfillment:[-5,3.8],dispatcher:[2,1],courier:[5,7],judge:[10,-6],household:[13,3.2],restaurant:[-11,-7],market:[-4,-7],customer_service:[3,-7]};
const v=(p,y=0)=>new THREE.Vector3(p[0],y,p[1]);
export function createDeliveryScene(host,data,{onAgent,onFailure,createAgentModel}){
 const renderer=new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true,powerPreference:'low-power'});
 renderer.setPixelRatio(Math.min(devicePixelRatio,1.3));renderer.setClearColor(0x0c151c);
 renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;
 renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.35;
 const canvas=renderer.domElement;canvas.className='delivery-scene-canvas';canvas.tabIndex=0;
 canvas.setAttribute('role','img');canvas.setAttribute('aria-label','Shared 3D delivery scene. Drag or use arrow keys to orbit. Click a robot, or use the named role buttons below.');
 host.prepend(canvas);
 const scene=new THREE.Scene(),world=new THREE.Group();scene.add(world);
 const camera=new THREE.OrthographicCamera(-15,15,10,-10,.1,120);
 const controls=new OrbitControls(camera,canvas);controls.enablePan=false;controls.enableZoom=false;controls.enableDamping=false;
 controls.minPolarAngle=.55;controls.maxPolarAngle=1.1;controls.minAzimuthAngle=-.3;controls.maxAzimuthAngle=.3;
 const narrow=matchMedia('(max-width:700px)');
 function interactionMode(){controls.enabled=!narrow.matches;canvas.style.touchAction=narrow.matches?'pan-x pan-y':'none';}
 interactionMode();narrow.addEventListener('change',interactionMode);
 const resources=new Set(),models=new Map(),labels=new Map(),home=new Map(),boxBatches=new Map();
 const material=(color,extra={})=>{const m=new THREE.MeshStandardMaterial({color,roughness:.65,metalness:.2,...extra});resources.add(m);return m;};
 const floor=material(0x364c55),wall=material(0x607783),edge=material(0x263d48),alloy=material(0xa9bdc6),black=material(0x14262f),road=material(0x1b2b35),wood=material(0xa78d64),white=material(0xc2d3d8);
 const cargo=[material(0x8baf8b),material(0xb6a073),material(0x8aa5b5)];
 function mesh(g,m,x,y,z,parent=world){resources.add(g);const obj=new THREE.Mesh(g,m);obj.position.set(x,y,z);obj.castShadow=true;obj.receiveShadow=true;parent.add(obj);return obj;}
 const box=(x,y,z,w,h,d,m=alloy,parent=world)=>mesh(new THREE.BoxGeometry(w,h,d),m,x,y,z,parent);
 // Static architectural boxes share one instanced draw per material.
 function block(x,y,z,w,h,d,m=alloy){
   if(!boxBatches.has(m))boxBatches.set(m,[]);
   boxBatches.get(m).push({x,y,z,w,h,d});
 }
 const cyl=(x,y,z,r,h,m=alloy,parent=world)=>mesh(new THREE.CylinderGeometry(r,r,h,16),m,x,y,z,parent);
 function curve(points){return new THREE.CatmullRomCurve3(points.map(p=>new THREE.Vector3(...p)),false,'centripetal');}
 function track(path,color,radius=.07,pattern='solid'){
   const group=new THREE.Group(),m=material(color,{emissive:color,emissiveIntensity:.25});world.add(group);
   if(pattern==='solid'){
     mesh(new THREE.TubeGeometry(path,80,radius,6,false),m,0,0,0,group);
   }else{
     const count=Math.ceil(path.getLength()/(pattern==='dots'?.48:.85));
     const geometry=pattern==='dots'?new THREE.SphereGeometry(radius*1.35,6,4):new THREE.CylinderGeometry(radius,radius,.38,6);
     resources.add(geometry);const instances=new THREE.InstancedMesh(geometry,m,count);group.add(instances);
     const matrix=new THREE.Matrix4(),rotation=new THREE.Quaternion(),up=new THREE.Vector3(0,1,0);
     for(let i=0;i<count;i++){const t=i/Math.max(1,count-1);rotation.setFromUnitVectors(up,path.getTangentAt(t));matrix.compose(path.getPointAt(t),rotation,new THREE.Vector3(1,1,1));instances.setMatrixAt(i,matrix);}
   }
   group.traverse(o=>{o.castShadow=false;o.receiveShadow=false;});return group;
 }
 // Larger rooms share a central loading court; low front walls keep the work visible.
 block(0,-.35,-.5,34,.5,24,edge);
 function room(x,z,w,d,m=floor){
   block(x,-.02,z,w,.16,d,m);
   block(x,1.45,z-d/2,w,2.9,.2,wall);
   block(x-w/2,.72,z-1.2,.18,1.45,d-2.4,wall);
   block(x+w/2,.72,z-1.2,.18,1.45,d-2.4,wall);
   // A real doorway, with a low cutaway frontage on each side.
   const wing=(w-2.4)/2;
   block(x-w/2+wing/2,.28,z+d/2,wing,.56,.16,wall);
   block(x+w/2-wing/2,.28,z+d/2,wing,.56,.16,wall);
   block(x,.04,z+d/2,2.4,.08,.5,alloy);
 }
 room(-11,-7.1,6,5.6);room(-4,-7.1,6,5.6);
 room(3,-7.1,6,5.6);room(10.3,-7.1,6.2,5.6);
 room(-11,1.1,8,8);room(-4.5,1.6,4.4,7);
 room(2,.2,5,5.8);
 block(13,0,1.2,5,.18,5.6,floor);
 block(1,.01,7,31,.12,3,road);
 for(let x=-13;x<16;x+=2)block(x,.09,8,.9,.025,.1,white);
 for(let x=-.2;x<2;x+=.4)block(x,.13,4.8,.2,.03,.8,wood);
 // Shelf planes support the goods. Batching keeps the enlarged setting inexpensive.
 for(const z of [-1.3,1.3]){
   const x=-13.4;
   for(const dx of [-.9,.9])for(const dz of [-.4,.4])block(x+dx,1.05,z+dz,.06,2.2,.06,alloy);
   for(const y of [.25,1,1.75]){
     block(x,y,z,2,.08,.95,alloy);
     for(let i=0;i<4;i++)block(x-.69+i*.45,y+.25,z,.35,.42,.57,cargo[i%3]);
   }
 }
 block(-4.5,.86,1.3,2.8,.18,1.2,wood);
 for(const x of [-5.65,-3.35])for(const z of [.85,1.75])block(x,.4,z,.12,.8,.12,alloy);
 block(-4.5,.99,1.3,.75,.12,.55,white);
 for(let x=-3.2;x<.4;x+=.28){const roll=cyl(x,.6,4.5,.08,1,alloy);roll.rotation.x=Math.PI/2;}
 block(-1.5,.35,4.5,3.8,.15,1.2,edge);
 const screen=material(0x55848d);
 function desk(x,z){
   block(x,.8,z,2.5,.15,1.1,wood);
   for(const dx of [-.9,.9])block(x+dx,.36,z,.16,.72,.7,edge);
   block(x,1.28,z-.15,1.2,.65,.08,black);block(x,1.3,z-.095,1.06,.5,.02,screen);
   block(x,1,z-.1,.08,.3,.08,alloy);block(x,.91,z+.25,.65,.05,.2,black);
 }
 desk(2,-.5);desk(3,-8.3);desk(10,-7.8);
 // Review has a records cabinet; support has two consultation seats.
 for(const x of [8.1,12.3])block(x,.8,-8.4,.7,1.6,.75,alloy);
 for(const x of [1.3,4.7]){block(x,.5,-5.4,.7,.18,.7,wood);block(x,.9,-5.1,.7,.7,.15,alloy);}
 block(-11,1,-8.6,3.8,.15,1.2,alloy);block(-11,.5,-8.6,3.6,.9,1.1,edge);
 for(const x of [-12,-11])cyl(x,1.12,-8.6,.28,.08,black);
 block(-11,2,-8.6,3,.3,1.2,wall);block(-11,2.45,-8.6,.6,.6,.5,alloy);
 for(const x of [-5.3,-3.1])for(const z of [-8.5,-6.9]){
   block(x,.13,z,1.4,.18,1.2,wood);block(x,.6,z,1.15,.7,1,cargo[1]);
 }
 // The household is across the street from the dispatch office.
 block(13.4,1.8,.1,4,3.6,2.6,wall);block(13.4,3.7,.1,4.4,.25,3,edge);
 block(12.4,1,1.42,1,2,.05,wood);block(14.3,2.1,1.42,1.2,1.1,.04,black);
 block(12.4,.13,2,1.8,.22,1,white);
 // Controller routing is infrastructure, not a tenth agent.
 block(-.4,.32,-2.5,1.2,.6,1,edge);block(-.4,.66,-2.5,1,.08,.8,screen);
 block(-14,.36,7,1.1,.7,.7,edge);const tablet=box(-14,.75,7,1,.12,.7,black);tablet.rotation.x=.3;
 for(const [m,items]of boxBatches){
   const geometry=new THREE.BoxGeometry(1,1,1);resources.add(geometry);
   const batch=new THREE.InstancedMesh(geometry,m,items.length),matrix=new THREE.Matrix4();
   for(let i=0;i<items.length;i++){const p=items[i];matrix.makeScale(p.w,p.h,p.d);matrix.setPosition(p.x,p.y,p.z);batch.setMatrixAt(i,matrix);}
   batch.receiveShadow=true;world.add(batch);batch.computeBoundingBox();
 }
 const packet=material(0xe9bc71),parcel=new THREE.Group();world.add(parcel);parcel.scale.setScalar(1.3);
 box(0,.32,0,.6,.62,.48,packet,parcel);box(0,.64,0,.1,.025,.49,white,parcel);
 const evidence=mesh(new THREE.OctahedronGeometry(.23),material(0xc1a1ef,{emissive:0xc1a1ef,emissiveIntensity:.5}),0,0,0);
 const request=mesh(new THREE.SphereGeometry(.21,12,8),material(0x84ccff,{emissive:0x84ccff,emissiveIntensity:.7}),0,0,0);
 const legs=[
   curve([[-14,.7,7],[-12,.7,5],[-11,.7,1.5]]),
   curve([[-11,.7,1.5],[-9,.7,3.8],[-5,.7,3.8]]),
   curve([[-5,.7,3.8],[-2,.7,4.8],[1,.7,5]]),
   curve([[1,.7,5],[3,.7,6.5],[5,.7,7]]),
   curve([[5,.7,7],[10.8,.7,7],[12,.7,6],[12,.7,3.3]])
 ];
 for(const leg of legs){
   const ground=curve(leg.points.map(p=>[p.x,.13,p.z]));
   track(ground,0x78c6a8,.085);
 }
 const requestPaths=[
   curve([[-.4,1.2,-2.5],[-6,3,-1.5],[-11,1.9,1.5]]),
   curve([[-11,1.9,1.5],[-6,3,-1.5],[-.4,1.2,-2.5],[-3,2.6,1],[-5,1.9,3.8]])
 ];
 const requestLines=requestPaths.map(path=>track(path,0x84ccff,.085,'dashes'));
 const reviewPath=curve([[12,.9,3.3],[15.8,4.7,2],[15.8,4.7,-2],[10,1.8,-6]]);
 const reviewLine=track(reviewPath,0xc1a1ef,.085,'dots');
 const ringMaterial=new THREE.MeshBasicMaterial({color:0xffffff,transparent:true,opacity:.8,side:THREE.DoubleSide});resources.add(ringMaterial);
 const ownerRing=mesh(new THREE.RingGeometry(.65,.7,40),ringMaterial,0,.13,0);ownerRing.rotation.x=-Math.PI/2;ownerRing.castShadow=false;
 const labelLayer=document.createElement('div');labelLayer.className='delivery-scene-labels';labelLayer.setAttribute('aria-hidden','true');host.append(labelLayer);
 for(const agent of data.agents){
  const model=createAgentModel({detail:false});model.decorate(agent);model.root.scale.setScalar(.64);model.root.position.copy(v(positions[agent.id]));model.root.rotation.y=.2;
  model.root.userData.agent=agent.id;world.add(model.root);models.set(agent.id,model);home.set(agent.id,model.root.position.clone());
  const label=document.createElement('span');label.className='scene-role-label';label.dataset.agent=agent.id;label.style.setProperty('--role-color',agent.visual.color);
  label.append(window.AgentRoleSymbols.icon(agent.visual),document.createTextNode(agent.visual.label));labelLayer.append(label);labels.set(agent.id,label);
 }
 const controllerLabel=document.createElement('span');controllerLabel.className='scene-role-label scene-controller';
 controllerLabel.textContent='Router';labelLayer.append(controllerLabel);
 const lit=new THREE.HemisphereLight(0xdceaf1,0x33454d,2.6);scene.add(lit);
 const key=new THREE.DirectionalLight(0xffefd7,3.8);key.position.set(-8,18,10);key.castShadow=true;key.shadow.mapSize.set(1024,1024);
 Object.assign(key.shadow.camera,{left:-22,right:22,top:20,bottom:-20,near:.1,far:80});key.shadow.normalBias=.08;scene.add(key);
 const fill=new THREE.DirectionalLight(0x8db9e3,1.5);fill.position.set(10,8,-8);scene.add(fill);
 let current=0,progress=0,playing=false,shown=true,visible=true,dirty=true,disposed=false,last=0,raf=0,hovered=null,frames=0,focusStep=null;
 const target=new THREE.Vector3(0,.4,0);
 // Fit occupied geometry, not the empty upper corners of a giant bounding box.
 world.updateMatrixWorld(true);const fitPoints=[];
 world.traverse(obj=>{if(obj.isMesh&&obj.visible){obj.geometry.computeBoundingBox();const b=obj.isInstancedMesh?obj.boundingBox:obj.geometry.boundingBox;if(!b)return;
  for(const x of [b.min.x,b.max.x])for(const y of [b.min.y,b.max.y])for(const z of [b.min.z,b.max.z])fitPoints.push(new THREE.Vector3(x,y,z).applyMatrix4(obj.matrixWorld));}});
 for(const model of models.values())fitPoints.push(model.root.position.clone().add(new THREE.Vector3(0,3.4,0)));
 function fit(){
  const w=host.clientWidth,h=host.clientHeight;if(!w||!h)return;
  const aspect=w/h;camera.left=-15;camera.right=15;camera.top=15/aspect;camera.bottom=-15/aspect;camera.updateProjectionMatrix();
  // Fit the shared physical bounds, not floating labels or a distant backdrop.
  camera.updateMatrixWorld();const projected=fitPoints.map(p=>p.clone().project(camera));
  const extent=Math.max(...projected.map(p=>Math.max(Math.abs(p.x)/.95,Math.abs(p.y)/.91)));
  camera.zoom/=extent;camera.updateProjectionMatrix();delete canvas.dataset.viewWidth;delete canvas.dataset.viewHeight;renderer.setSize(w,h,false);dirty=true;
 }
 function reset(){camera.position.set(4,27,39);controls.target.copy(target);camera.lookAt(target);camera.zoom=1;fit();}
 function setState(index,fraction,isPlaying){
  if(current!==index)focusStep=index;
  current=index;progress=fraction;playing=isPlaying;
  for(const [id,model]of models)model.root.position.copy(home.get(id));
  const t=THREE.MathUtils.smoothstep(progress,0,1);
  const owner=data.story.steps[index]?.agent;
  const point=index<5?legs[index].getPointAt(t):legs[4].getPointAt(1);
  // Work stays completed as the next handoff starts.
  const picker=models.get('fulfillment').root;
  if(index===0)picker.position.copy(v(positions.fulfillment).lerp(v([-9.6,2.5]),t));
  if(index===1){picker.position.copy(point);picker.position.x+=1.4*(1-t);picker.position.z+=1*(1-t);picker.position.y=0;}
  if(index>=2)picker.position.copy(v(positions.fulfillment));
  if(index>=4){const courier=models.get('courier').root;courier.position.copy(index===4?point:legs[4].getPointAt(1));courier.position.y=0;}
  parcel.position.copy(point);
  requestLines.forEach((line,i)=>line.visible=index===i);
  request.visible=index<2;
  if(request.visible)request.position.copy(requestPaths[index].getPointAt(t));
  evidence.visible=index===5;reviewLine.visible=index===5;
  if(evidence.visible)evidence.position.copy(reviewPath.getPointAt(t));
  const active=owner&&models.get(owner);ownerRing.position.copy(active?active.root.position:point);ownerRing.position.y=.14;
  for(const [id,label]of labels)label.classList.toggle('is-owner',id===owner);
  canvas.dataset.rooms='7';canvas.dataset.communication=index<2?'a2a':index===5?'evidence':'handoff';
  canvas.dataset.step=String(index);canvas.dataset.progress=fraction.toFixed(3);canvas.dataset.playing=String(isPlaying);
  canvas.dataset.parcel=JSON.stringify(parcel.position.toArray().map(n=>+n.toFixed(2)));canvas.dataset.evidence=String(evidence.visible);
  dirty=true;
 }
 function project(){
  scene.updateMatrixWorld(true);camera.updateMatrixWorld();const bounds={};
  for(const [id,model]of models){
   const p=model.root.position.clone().add(new THREE.Vector3(0,3.25,0)).project(camera);
   const x=(p.x+1)/2*host.clientWidth,y=(1-p.y)/2*host.clientHeight;
   labels.get(id).style.transform='translate('+x.toFixed(1)+'px,'+y.toFixed(1)+'px) translate(-50%,-100%)';
   const hit=model.root.position.clone().add(new THREE.Vector3(0,1.35,0)).project(camera);
   bounds[id]={x:(hit.x+1)/2,y:(1-hit.y)/2};
  }
  const router=v([-.4,-2.5],.9).project(camera);
  controllerLabel.style.transform='translate('+((router.x+1)/2*host.clientWidth).toFixed(1)+'px,'+((1-router.y)/2*host.clientHeight).toFixed(1)+'px) translate(-50%,-100%)';
  canvas.dataset.agents=JSON.stringify(bounds);
  if(focusStep!==null){
    if(narrow.matches){
      const focus=focusStep<5?legs[focusStep].getPointAt(.5):v(positions.judge);
      focus.project(camera);
      const viewport=host.parentElement;
      viewport.scrollTo({left:(focus.x+1)/2*host.clientWidth-viewport.clientWidth/2,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
    }
    focusStep=null;
  }
 }
 const ray=new THREE.Raycaster(),pointer=new THREE.Vector2();let down=null;
 function hit(event){
  const r=canvas.getBoundingClientRect();pointer.set((event.clientX-r.left)/r.width*2-1,-(event.clientY-r.top)/r.height*2+1);ray.setFromCamera(pointer,camera);
  let o=ray.intersectObjects([...models.values()].map(m=>m.root),true)[0]?.object;while(o&&!o.userData.agent)o=o.parent;return o?.userData.agent;
 }
 function highlight(id){hovered=id;for(const [key,label]of labels)label.classList.toggle('is-hovered',id===key);dirty=true;}
 canvas.addEventListener('pointerdown',e=>{down=[e.clientX,e.clientY];});
 canvas.addEventListener('pointermove',e=>{const id=hit(e);if(id!==hovered)highlight(id);canvas.style.cursor=id?'pointer':'grab';});
 canvas.addEventListener('pointerleave',()=>highlight(null));
 canvas.addEventListener('pointercancel',()=>{down=null;});
 canvas.addEventListener('pointerup',e=>{if(down&&Math.hypot(e.clientX-down[0],e.clientY-down[1])<6){const id=hit(e);if(id)onAgent(id);}down=null;});
 canvas.addEventListener('keydown',e=>{
  if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home'].includes(e.key))return;e.preventDefault();
  if(narrow.matches){
    if(e.key==='Home')host.parentElement.scrollTo({left:0,behavior:'instant'});
    if(e.key==='ArrowLeft'||e.key==='ArrowRight')host.parentElement.scrollBy({left:e.key==='ArrowLeft'?-200:200,behavior:'instant'});
    return;
  }
  if(e.key==='Home'){reset();return;}const s=new THREE.Spherical().setFromVector3(camera.position.clone().sub(target));
  if(e.key==='ArrowLeft')s.theta=Math.max(-.3,s.theta-.1);if(e.key==='ArrowRight')s.theta=Math.min(.3,s.theta+.1);
  if(e.key==='ArrowUp')s.phi=Math.max(.55,s.phi-.1);if(e.key==='ArrowDown')s.phi=Math.min(1.1,s.phi+.1);
  camera.position.copy(target).add(new THREE.Vector3().setFromSpherical(s));camera.lookAt(target);fit();
 });
 controls.addEventListener('change',()=>{fit();dirty=true;});
 const resize=new ResizeObserver(fit);resize.observe(host);
 const intersection=new IntersectionObserver(e=>{visible=!!e[0]?.isIntersecting;dirty=true;});intersection.observe(host);
 const lost=e=>{e.preventDefault();dispose();onFailure();};canvas.addEventListener('webglcontextlost',lost);
 function draw(now){
  if(disposed)return;raf=requestAnimationFrame(draw);
  if(dirty){const bounds=host.getBoundingClientRect();visible=bounds.width>0&&bounds.height>0&&bounds.bottom>0&&bounds.top<innerHeight;}
  if(!shown||!visible||document.hidden||now-last<1000/30||!dirty)return;
  last=now;project();renderer.render(scene,camera);dirty=false;frames++;
  canvas.dataset.viewWidth=String(host.clientWidth);canvas.dataset.viewHeight=String(host.clientHeight);canvas.dataset.frames=String(frames);canvas.dataset.render=JSON.stringify({calls:renderer.info.render.calls,triangles:renderer.info.render.triangles});
  canvas.dataset.visuals=JSON.stringify(data.agents.map(a=>({id:a.id,...a.visual})));
 }
 function dispose(){
  if(disposed)return;disposed=true;cancelAnimationFrame(raf);resize.disconnect();intersection.disconnect();narrow.removeEventListener("change",interactionMode);controls.dispose();canvas.removeEventListener('webglcontextlost',lost);
  for(const model of models.values())for(const item of model.resources)item.dispose();
  for(const item of resources)item.dispose();renderer.dispose();canvas.remove();labelLayer.remove();
 }
 reset();setState(0,0,false);raf=requestAnimationFrame(draw);
 return {setState,highlight,reset,dispose,show(value){shown=value;dirty=true;if(value)fit();}};
}
