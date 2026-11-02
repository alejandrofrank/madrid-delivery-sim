import * as THREE from './vendor/three/three.module.js';
import {OrbitControls} from './vendor/three/OrbitControls.js';

const positions={inventory:[-7,.8],fulfillment:[-3,2.5],dispatcher:[1,.5],courier:[4,4],judge:[6,-4],household:[10.5,.7],restaurant:[-8,-5],market:[-2,-5],customer_service:[3,-5]};
const orderPath=[[-8,4],[-7,.8],[-3,2.5],[.4,3.4],[9,-.5]];
const v=(p,y=0)=>new THREE.Vector3(p[0],y,p[1]);
const mix=(a,b,t)=>v(a).lerp(v(b),t);
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
 controls.minPolarAngle=.55;controls.maxPolarAngle=1.1;
 const resources=new Set(),models=new Map(),labels=new Map(),home=new Map();
 const material=(color,extra={})=>{const m=new THREE.MeshStandardMaterial({color,roughness:.65,metalness:.2,...extra});resources.add(m);return m;};
 const floor=material(0x364c55),wall=material(0x607783),edge=material(0x263d48),alloy=material(0xa9bdc6),black=material(0x14262f),road=material(0x1b2b35),wood=material(0xa78d64),white=material(0xc2d3d8);
 const cargo=[material(0x8baf8b),material(0xb6a073),material(0x8aa5b5)];
 function mesh(g,m,x,y,z,parent=world){resources.add(g);const obj=new THREE.Mesh(g,m);obj.position.set(x,y,z);obj.castShadow=true;obj.receiveShadow=true;parent.add(obj);return obj;}
 const box=(x,y,z,w,h,d,m=alloy,parent=world)=>mesh(new THREE.BoxGeometry(w,h,d),m,x,y,z,parent);
 const cyl=(x,y,z,r,h,m=alloy,parent=world)=>mesh(new THREE.CylinderGeometry(r,r,h,16),m,x,y,z,parent);
 function line(points,color=0x8db9e3,dashed=false){
  const g=new THREE.BufferGeometry().setFromPoints(points.map(p=>new THREE.Vector3(...p)));resources.add(g);
  const m=dashed?new THREE.LineDashedMaterial({color,dashSize:.22,gapSize:.15}):new THREE.LineBasicMaterial({color});resources.add(m);
  const obj=new THREE.Line(g,m);if(dashed)obj.computeLineDistances();world.add(obj);return obj;
 }
 // One continuous cutaway: warehouse floor, loading curb and neighbourhood.
 box(0,-.5,0,24,.8,15,edge);box(-4.5,-.04,-1,13,.18,11,floor);
 box(7,-.05,-2,9,.18,9,material(0x405660));box(4.5,-.02,4,15,.2,3.4,road);
 box(-10.8,1.1,-1,.2,2.3,11,wall);box(-4.5,.7,-6.4,13,1.5,.2,wall);
 for(let x=-1;x<12;x+=1.8)box(x,.09,4,.85,.025,.08,white);
 for(let x=.1;x<2.1;x+=.35)box(x,.11,2.6,.16,.03,.75,wood);
 // Stock is seated on actual shelf planes.
 for(const x of [-9,-6.3]){
  for(const z of [-2.6,-.1]){
   for(const dx of [-.9,.9])for(const dz of [-.38,.38])box(x+dx,1.05,z+dz,.06,2.2,.06,alloy);
   for(const y of [.25,1,1.75]){
    box(x,y,z,1.95,.08,.9,alloy);
    for(let i=0;i<4;i++)box(x-.69+i*.45,y+.25,z,.35,.42,.57,cargo[i%3]);
   }
  }
 }
 // A packing bench and conveyor lead towards the dock.
 box(-3.1,.86,1.1,2.4,.18,1.2,wood);
 for(const x of [-4.1,-2.1])for(const z of [.65,1.55])box(x,.4,z,.12,.8,.12,alloy);
 box(-3,.99,1.1,.75,.12,.55,white);
 for(let x=-1.65;x<.6;x+=.26){const roll=cyl(x,.6,2.7,.08,1,alloy);roll.rotation.x=Math.PI/2;}
 box(-.5,.35,2.7,2.8,.15,1.2,edge);
 // Dispatch and support desks have screens, not a second delivery lane.
 function desk(x,z,w=2){
  box(x,.8,z,w,.15,.9,wood);box(x-.65,.36,z,.16,.72,.55,edge);box(x+.65,.36,z,.16,.72,.55,edge);
  box(x,1.22,z-.15,.9,.55,.08,black);box(x,1.24,z-.095,.76,.4,.02,material(0x55848d));box(x,1,z-.1,.08,.25,.08,alloy);
 }
 desk(1,-.65);desk(3,-6.1);desk(6,-5.1);
 // Kitchen and ingredient supplier are separate meal specialists.
 box(-8,1,-6,3,.15,1,alloy);box(-8,.5,-6,2.8,.9,.9,edge);
 for(const x of [-8.7,-7.8])cyl(x,1.12,-6,.25,.08,black);
 box(-8,2,-6,2.6,.3,.9,wall);box(-8,2.45,-6,.6,.6,.5,alloy);
 for(const x of [-3.1,-1.7]){
  box(x,.13,-5.8,1.2,.18,1.1,wood);
  for(const y of [.5,1.15])box(x,y,-5.8,1,.6,.85,cargo[1]);
 }
 // Doorstep: shallow facade keeps the delivery destination readable.
 box(10.6,1.9,-2.5,2.4,3.8,2.3,wall);box(10.6,4,-2.5,2.8,.25,2.7,edge);
 box(10.1,1,-1.32,.8,2,.05,wood);cyl(10.37,1,-1.26,.04,.08,alloy).rotation.x=Math.PI/2;
 for(const x of [9.9,11.2])box(x,2.8,-1.31,.7,.7,.04,black);
 box(10.1,.13,-.8,1.5,.22,.8,white);
 // Demo order is an input terminal, never a household-created store request.
 box(-8,.36,4,1.1,.7,.7,edge);const tablet=box(-8,.75,4,1,.12,.7,black);tablet.rotation.x=.3;
 const packet=material(0xe9bc71),parcel=new THREE.Group();world.add(parcel);parcel.scale.setScalar(1.3);
 box(0,.32,0,.6,.62,.48,packet,parcel);box(0,.64,0,.1,.025,.49,white,parcel);
 const evidence=mesh(new THREE.OctahedronGeometry(.12),material(0x8db9e3,{emissive:0x8db9e3,emissiveIntensity:.4}),0,0,0);
 evidence.visible=false;
 const route=line([[-7,.15,.8],[-5,.15,.8],[-5,.15,2.5],[-3,.15,2.5],[.4,.15,3.4],[4,.15,4],[9,.15,4],[9,.15,-.5]],0x6d9b9e);
 const reviewLine=line([[9,.2,-.5],[7.5,2.2,-2.5],[6,1.5,-4]],0x8db9e3,true);
 reviewLine.material.dashSize=.05;reviewLine.material.gapSize=.14;
 const requestLine=line([[-7,1.9,.8],[-5,2.6,1.8],[-3,1.9,2.5]],0x8db9e3,true);requestLine.visible=false;
 reviewLine.visible=false;
 const ringMaterial=new THREE.MeshBasicMaterial({color:0xffffff,transparent:true,opacity:.8,side:THREE.DoubleSide});resources.add(ringMaterial);
 const ownerRing=mesh(new THREE.RingGeometry(.65,.7,40),ringMaterial,0,.13,0);ownerRing.rotation.x=-Math.PI/2;ownerRing.castShadow=false;
 const labelLayer=document.createElement('div');labelLayer.className='delivery-scene-labels';labelLayer.setAttribute('aria-hidden','true');host.append(labelLayer);
 for(const agent of data.agents){
  const model=createAgentModel({detail:false});model.decorate(agent);model.root.scale.setScalar(.56);model.root.position.copy(v(positions[agent.id]));model.root.rotation.y=.2;
  model.root.userData.agent=agent.id;world.add(model.root);models.set(agent.id,model);home.set(agent.id,model.root.position.clone());
  const label=document.createElement('span');label.className='scene-role-label';label.dataset.agent=agent.id;label.style.setProperty('--role-color',agent.visual.color);
  label.append(window.AgentRoleSymbols.icon(agent.visual),document.createTextNode(agent.visual.label));labelLayer.append(label);labels.set(agent.id,label);
 }
 const lit=new THREE.HemisphereLight(0xdceaf1,0x33454d,2.6);scene.add(lit);
 const key=new THREE.DirectionalLight(0xffefd7,3.8);key.position.set(-8,18,10);key.castShadow=true;key.shadow.mapSize.set(1024,1024);
 Object.assign(key.shadow.camera,{left:-16,right:16,top:14,bottom:-14,near:.1,far:70});key.shadow.normalBias=.08;scene.add(key);
 const fill=new THREE.DirectionalLight(0x8db9e3,1.5);fill.position.set(10,8,-8);scene.add(fill);
 let current=0,progress=0,playing=false,shown=true,visible=true,dirty=true,disposed=false,last=0,raf=0,hovered=null,frames=0;
 const target=new THREE.Vector3(0,.4,0);
 // Fit occupied geometry, not the empty upper corners of a giant bounding box.
 world.updateMatrixWorld(true);const fitPoints=[];
 world.traverse(obj=>{if(obj.isMesh&&obj.visible){obj.geometry.computeBoundingBox();const b=obj.geometry.boundingBox;
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
 function reset(){camera.position.set(8,18,38);controls.target.copy(target);camera.lookAt(target);camera.zoom=1;fit();}
 function setState(index,fraction,isPlaying){
  current=index;progress=fraction;playing=isPlaying;
  for(const [id,model]of models)model.root.position.copy(home.get(id));
  const t=THREE.MathUtils.smoothstep(progress,0,1);
  let point=v(orderPath[Math.min(index,4)]),owner=data.story.steps[index]?.agent;
  if(index===0)point=mix(orderPath[0],orderPath[1],t);
  if(index===1)point=mix(orderPath[1],orderPath[2],t);
  if(index===2)point=mix(orderPath[2],orderPath[3],t);
  if(index===3)point=mix(orderPath[3],[4,4],t);
  if(index===4){
   const path=[[4,4],[9,4],[9,-.5]],distance=t*2;
   point=distance<1?mix(path[0],path[1],distance):mix(path[1],path[2],distance-1);
   models.get('courier').root.position.copy(point);
  }
  if(index===1){const picker=models.get('fulfillment').root;picker.position.copy(point);owner='inventory';}
  parcel.position.copy(point);parcel.position.y=index===4?.7:index===0?.85:.15;requestLine.visible=index===1;
  if(index===5){models.get('courier').root.position.copy(v(orderPath[4]));parcel.position.copy(v(orderPath[4],.12));evidence.visible=true;reviewLine.visible=true;
   evidence.position.copy(v(orderPath[4],.9)).lerp(v(positions.judge,1.7),t);evidence.position.y+=Math.sin(t*Math.PI)*1.5;
  }else{evidence.visible=false;reviewLine.visible=false;}
  const active=owner&&models.get(owner);ownerRing.position.copy(active?active.root.position:point);ownerRing.position.y=.14;
  for(const [id,label]of labels)label.classList.toggle('is-owner',id===owner);
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
  canvas.dataset.agents=JSON.stringify(bounds);
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
 canvas.addEventListener('pointerup',e=>{if(down&&Math.hypot(e.clientX-down[0],e.clientY-down[1])<6){const id=hit(e);if(id)onAgent(id);}down=null;});
 canvas.addEventListener('keydown',e=>{
  if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home'].includes(e.key))return;e.preventDefault();
  if(e.key==='Home'){reset();return;}const s=new THREE.Spherical().setFromVector3(camera.position.clone().sub(target));
  if(e.key==='ArrowLeft')s.theta-=.1;if(e.key==='ArrowRight')s.theta+=.1;
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
  if(disposed)return;disposed=true;cancelAnimationFrame(raf);resize.disconnect();intersection.disconnect();controls.dispose();canvas.removeEventListener('webglcontextlost',lost);
  for(const model of models.values())for(const item of model.resources)item.dispose();
  for(const item of resources)item.dispose();renderer.dispose();canvas.remove();labelLayer.remove();
 }
 reset();setState(0,0,false);raf=requestAnimationFrame(draw);
 return {setState,highlight,reset,dispose,show(value){shown=value;dirty=true;if(value)fit();}};
}
