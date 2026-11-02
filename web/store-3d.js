import * as THREE from './vendor/three/three.module.js';
import {OrbitControls} from './vendor/three/OrbitControls.js';
import {GLTFLoader} from './vendor/three/GLTFLoader.js';
import {MeshoptDecoder} from './vendor/three/meshopt_decoder.module.js';
const reduced=matchMedia('(prefers-reduced-motion: reduce)'),cache=new Map();
const loader=new GLTFLoader().setMeshoptDecoder(MeshoptDecoder);
function asset(role){if(!cache.has(role))cache.set(role,loader.loadAsync('/static/vendor/simready/'+role+'.glb').then(g=>{
 // Approximate the forklift glass with alpha blending: refraction rerenders
 // the entire store and costs more than the glass contributes at this scale.
 g.scene.traverse(mesh=>{for(const material of (Array.isArray(mesh.material)?mesh.material:[mesh.material]))if(material?.transmission>0){material.transmission=0;material.transparent=true;material.opacity=.28;material.depthWrite=false;}});
 return g.scene;
}).catch(()=>null));return cache.get(role);}
export async function createStoreScene(host,initial,status,onFailure,onTrack){
 const renderer=new THREE.WebGLRenderer({antialias:true,powerPreference:'low-power'});
 renderer.setPixelRatio(Math.min(devicePixelRatio,1.5));renderer.setClearColor(0x172832);
 renderer.domElement.tabIndex=0;renderer.domElement.setAttribute('aria-label','Store cutaway. Arrow keys orbit; plus and minus zoom. Order details alongside.');
 host.prepend(renderer.domElement);
 const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(42,1,.1,160),root=new THREE.Group();
 scene.add(root,new THREE.HemisphereLight(0xe6f4ff,0x45534d,2.5));
 const light=new THREE.DirectionalLight(0xfff0d7,2.3);light.position.set(-6,22,10);scene.add(light);
 const controls=new OrbitControls(camera,renderer.domElement);controls.maxPolarAngle=1.45;controls.minDistance=5;controls.maxDistance=65;
 const layout=initial.layout,workers=new Map(),slots=new Map(),routes=new THREE.Group(),hazards=new THREE.Group(),basket=new THREE.Group();
 root.add(routes,hazards,basket);
 let state=initial,order=null,tracking=false,disposed=false,last=0,sim=0,rate=0,received=performance.now();
 const owned=new Set(),labels=new Map(),rings=new Map();let dirty=true,trackedWorker=null,overview=true;
 const labelLayer=document.createElement('div');labelLayer.className='store-worker-labels';host.append(labelLayer);
 controls.addEventListener('change',()=>{dirty=true;});
 controls.addEventListener('start',()=>{overview=false;});
 function box(x,y,z,w,h,d,color){const geometry=new THREE.BoxGeometry(w,h,d),material=new THREE.MeshStandardMaterial({color,roughness:.85});owned.add(geometry);owned.add(material);const mesh=new THREE.Mesh(geometry,material);mesh.position.set(x,y,z);return mesh;}
 root.add(box(layout.width/2,-.15,layout.depth/2,layout.width+.5,.3,layout.depth+.5,0x213943));
 const cold=layout.cold_zone;root.add(box(cold.x+cold.width/2,.02,cold.z+cold.depth/2,cold.width,.04,cold.depth,0x315f78));
 root.add(box(layout.packing.x,.5,layout.packing.z+.9,1.4,1,1,0x7c9694),box(layout.dock.x,.02,layout.dock.z,2.3,.04,2.4,0x8c7145));
 function label(text,x,z){const c=document.createElement('canvas');c.width=512;c.height=64;const ctx=c.getContext('2d');ctx.font='600 30px sans-serif';ctx.textAlign='center';ctx.fillStyle='#d9eaf3';ctx.fillText(text,256,40);const texture=new THREE.CanvasTexture(c),mat=new THREE.SpriteMaterial({map:texture,depthTest:false});owned.add(texture);owned.add(mat);const sprite=new THREE.Sprite(mat);sprite.position.set(x,.35,z);sprite.scale.set(4,.5,1);root.add(sprite);}
 label('PACK',layout.packing.x+1,layout.packing.z+1.3);label('COURIER DOCK',layout.dock.x-1,layout.dock.z+1.5);label('COLD',cold.x+2,.5);
 function fitted(model,w,h,d){const copy=model.clone(true),bounds=new THREE.Box3().setFromObject(copy),size=bounds.getSize(new THREE.Vector3());copy.scale.multiplyScalar(Math.min(w/size.x,h/size.y,d/size.z));const adjusted=new THREE.Box3().setFromObject(copy),center=adjusted.getCenter(new THREE.Vector3());copy.position.set(-center.x,-adjusted.min.y,-center.z);const group=new THREE.Group();group.add(copy);return group;}
 const loaded=await Promise.all(['shelving','robot','forklift','cart','pallet','produce','packaged'].map(asset));
 // Logical shelf levels are seated on the actual model decks, not outside its bounds.
 let rack;
 if(loaded[0])rack=fitted(loaded[0],1.1,2.2,1.7);
 else{
  rack=new THREE.Group();
  for(const x of [-.25,.25])for(const z of [-.77,.77])rack.add(box(x,1.1,z,.045,2.2,.045,0x708994));
  for(let level=0;level<layout.config.levels;level++)rack.add(box(0,.45+level*.6-.025,0,.55,.05,1.6,0x708994));
 }
 rack.updateMatrixWorld(true);
 const bounds=new THREE.Box3().setFromObject(rack),rackWidth=bounds.max.x-bounds.min.x,faceOffset=rackWidth*.25;
 const ray=new THREE.Raycaster(),down=new THREE.Vector3(0,-1,0),normal=new THREE.Vector3();
 function decks(side){
  ray.set(new THREE.Vector3(side*faceOffset,bounds.max.y+1,0),down);const heights=[];
  for(const hit of ray.intersectObject(rack,true)){
   if(!hit.face)continue;
   normal.copy(hit.face.normal).applyNormalMatrix(new THREE.Matrix3().getNormalMatrix(hit.object.matrixWorld));
   if(normal.y<.8||(loaded[0]&&hit.point.y>bounds.max.y-.06))continue;
   if(!heights.some(y=>Math.abs(y-hit.point.y)<.025))heights.push(hit.point.y);
  }
  heights.sort((a,b)=>a-b);
  return heights.slice(heights.length>layout.config.levels?1:0).slice(0,layout.config.levels);
 }
 const supports={[-1]:decks(-1),[1]:decks(1)},rackCopies=[];
 for(let a=0;a<layout.config.aisles;a++)for(let b=0;b<layout.config.bays;b++){
  const copy=rack.clone(true);copy.position.set(a*3+2,0,b*2+2);copy.updateMatrixWorld(true);rackCopies.push(copy);
 }
 const batches=new Map();
 for(const copy of rackCopies)copy.traverse(mesh=>{
  if(!mesh.isMesh)return;
  const key=mesh.geometry.uuid+':'+(Array.isArray(mesh.material)?mesh.material.map(m=>m.uuid).join(','):mesh.material.uuid);
  if(!batches.has(key))batches.set(key,{geometry:mesh.geometry,material:mesh.material,matrices:[]});
  batches.get(key).matrices.push(mesh.matrixWorld.clone());
 });
 for(const batch of batches.values()){
  const mesh=new THREE.InstancedMesh(batch.geometry,batch.material,batch.matrices.length);
  batch.matrices.forEach((matrix,i)=>mesh.setMatrixAt(i,matrix));mesh.instanceMatrix.needsUpdate=true;root.add(mesh);owned.add(mesh);
 }
 // Products share draw calls too; every stocked face gets a seated representative model.
 const productParts=[],identity=new THREE.Matrix4(),zero=new THREE.Matrix4().makeScale(0,0,0);
 let supportErrors=0,maxGap=0;
 for(const role of ['produce','packaged']){
  const model=loaded[role==='produce'?5:6],template=model?fitted(model,rackWidth*.39,.28,.38):new THREE.Group();
  if(!model)template.add(box(0,.14,0,rackWidth*.39,.28,.34,0xb1a181));
  template.updateMatrixWorld(true);
  const members=layout.slots.filter(s=>(s.category==='produce'?'produce':'packaged')===role),parts=[];
  template.traverse(part=>{
   if(!part.isMesh)return;
   const mesh=new THREE.InstancedMesh(part.geometry,part.material,members.length);
   root.add(mesh);owned.add(mesh);parts.push({mesh,local:part.matrixWorld.clone()});productParts.push(mesh);
  });
  const productBounds=new THREE.Box3().setFromObject(template);
  members.forEach((s,index)=>{
   const support=supports[s.side][s.level-1],y=support??s.y,x=s.x+s.side*faceOffset;
   if(support===undefined)root.add(box(s.x,y-.025,s.z,rackWidth,.05,1.6,0x708994));
   const matrix=new THREE.Matrix4().makeTranslation(x,y+.002,s.z),item=productBounds.clone().applyMatrix4(matrix);
   slots.set(s.id,{parts,index,matrix,x,y,z:s.z});
   maxGap=Math.max(maxGap,Math.abs(item.min.y-y));
   if(item.min.x<s.x+bounds.min.x-.01||item.max.x>s.x+bounds.max.x+.01)supportErrors++;
   if(support!==undefined){
    ray.set(new THREE.Vector3(s.side*faceOffset,item.min.y+.005,0),down);
    const hits=ray.intersectObject(rack,true).filter(hit=>hit.point.y<=item.min.y+.001);
    if(!hits.length||Math.abs(hits[0].point.y-y)>.015)supportErrors++;
   }
  });
 }
 renderer.domElement.dataset.shelfSupport=JSON.stringify({slots:slots.size,errors:supportErrors,maxGap});
 const markerGeometry=new THREE.BoxGeometry(rackWidth*.46,.014,.44),markerMaterial=new THREE.MeshBasicMaterial({color:0xffffff});
 owned.add(markerGeometry);owned.add(markerMaterial);
 const shelfMarkers=new THREE.InstancedMesh(markerGeometry,markerMaterial,layout.slots.length);root.add(shelfMarkers);owned.add(shelfMarkers);
 const markerMatrix=new THREE.Matrix4(),markerColor=new THREE.Color();
 for(const w of state.workers){const i=w.kind==='forklift'?2:w.kind==='staff'?3:1;const m=loaded[i]?fitted(loaded[i],1.05,w.kind==='forklift'?1.5:1.2,1.4):box(0,.45,0,.65,.9,.65,w.kind==='forklift'?0xd3b476:0x56cbbb);if(!loaded[i])m.geometry.translate(0,.45,0);root.add(m);workers.set(w.id,m);}
 // Low warehouse robots carry a visible tote; its contents travel with the worker.
 for(const w of state.workers)if(w.kind==='robot'){
  const tote=new THREE.Group();
  tote.add(box(0,.29,0,.56,.04,.56,0x708994));
  for(const side of [-1,1]){
   tote.add(box(side*.27,.41,0,.025,.22,.56,0x708994));
   tote.add(box(0,.41,side*.27,.56,.22,.025,0x708994));
  }
  workers.get(w.id).add(tote);
 }
 function watch(id){
  trackedWorker=id;tracking=true;overview=false;camera.position.sub(controls.target).normalize().multiplyScalar(13).add(controls.target);dirty=true;for(const [workerId,button] of labels)button.setAttribute('aria-pressed',String(workerId===id));onTrack?.();
 }
 for(const w of state.workers){
  const geometry=new THREE.RingGeometry(.43,.5,28),material=new THREE.MeshBasicMaterial({color:0x52e5d5,side:THREE.DoubleSide,depthTest:false});
  owned.add(geometry);owned.add(material);const ring=new THREE.Mesh(geometry,material);ring.rotation.x=-Math.PI/2;ring.renderOrder=5;root.add(ring);rings.set(w.id,ring);
  const button=document.createElement('button');button.className='store-worker-label';button.dataset.worker=w.id;button.innerHTML='<strong></strong><span></span>';
  button.addEventListener('click',()=>watch(w.id));labelLayer.append(button);labels.set(w.id,button);
 }
 if(loaded[4]){const m=fitted(loaded[4],1.2,.2,1.2);m.position.set(layout.dock.x-1.8,0,layout.dock.z);root.add(m);}
 status(loaded.some(m=>!m)?'Some models unavailable; simple shapes shown.':'3D cutaway · local SimReady models');
 // Fit the actual floor envelope in both projection axes; a portrait canvas
 // needs more distance than a wide one. Tracking and manual orbit keep their zoom.
 const fitCorners=[];
 for(const x of [-.6,layout.width+.6])for(const y of [-.3,2.8])for(const z of [-.6,layout.depth+1])fitCorners.push(new THREE.Vector3(x,y,z));
 function fit(){
  trackedWorker=null;tracking=false;overview=true;
  controls.target.set(layout.width/2,1.1,layout.depth/2);
  const direction=new THREE.Vector3(layout.width/2+6,20,layout.depth/2+10).normalize();
  const right=new THREE.Vector3().crossVectors(camera.up,direction).normalize(),up=new THREE.Vector3().crossVectors(direction,right);
  const vertical=Math.tan(THREE.MathUtils.degToRad(camera.fov/2))*.9,horizontal=vertical*camera.aspect;
  let distance=5;
  for(const corner of fitCorners){const relative=corner.clone().sub(controls.target),depth=relative.dot(direction);distance=Math.max(distance,depth+Math.abs(relative.dot(right))/horizontal,depth+Math.abs(relative.dot(up))/vertical);}
  controls.maxDistance=Math.max(65,distance*2);camera.far=Math.max(160,distance+layout.width+layout.depth+30);
  camera.position.copy(direction).multiplyScalar(distance).add(controls.target);camera.updateProjectionMatrix();controls.update();dirty=true;
 }fit();
 function resize(){const w=host.clientWidth,h=host.clientHeight;if(!w||!h)return;camera.aspect=w/h;camera.updateProjectionMatrix();renderer.setSize(w,h,false);if(overview)fit();dirty=true;}
 const observer=new ResizeObserver(resize);observer.observe(host);resize();
 function clear(group){for(const child of [...group.children]){group.remove(child);child.geometry?.dispose();child.material?.dispose();owned.delete(child.geometry);owned.delete(child.material);}}
 function line(points){for(let i=1;i<points.length;i++){const a=new THREE.Vector3(points[i-1][0],.13,points[i-1][1]),b=new THREE.Vector3(points[i][0],.13,points[i][1]),length=a.distanceTo(b);if(!length)continue;const m=new THREE.Mesh(new THREE.CylinderGeometry(.07,.07,length,5),new THREE.MeshBasicMaterial({color:0x52e5d5}));m.position.copy(a).add(b).multiplyScalar(.5);m.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),b.sub(a).normalize());routes.add(m);}}
 function update(next,selected,clock){
  if(order?.order_id!==selected?.order_id)trackedWorker=null;
  state=next;order=selected;sim=clock.sim;rate=clock.rate;received=performance.now();dirty=true;
  const stock=new Map(state.shelves.map(s=>[s.slot,s.quantity]));
  layout.slots.forEach((s,index)=>{
   const p=slots.get(s.id),wanted=order&&Object.hasOwn(order.lines,s.sku);
   for(const part of p.parts)part.mesh.setMatrixAt(p.index,stock.get(s.id)>0?identity.multiplyMatrices(p.matrix,part.local):zero);
   markerMatrix.makeTranslation(p.x,p.y+.008,p.z);shelfMarkers.setMatrixAt(index,wanted?markerMatrix:zero);
   shelfMarkers.setColorAt(index,markerColor.setHex((order?.picked[s.sku]||0)>=(order?.lines[s.sku]||1)?0x83d6a2:stock.get(s.id)>0?0x52e5d5:0xe8ae63));
  });
  for(const mesh of productParts){mesh.instanceMatrix.needsUpdate=true;mesh.computeBoundingSphere();}
  shelfMarkers.instanceMatrix.needsUpdate=true;if(shelfMarkers.instanceColor)shelfMarkers.instanceColor.needsUpdate=true;
  clear(routes);clear(hazards);clear(basket);
  for(const w of state.workers)if(w.route&&(!order||w.task?.order_id===order.order_id))line(w.route.points);
  for(const w of state.workers){
   const title=w.kind==='forklift'?'Forklift':(w.kind==='staff'?'Picker ':'Robot ')+w.id.split('-').at(-1);
   const task=!w.available?'Offline':w.task?.action?.replaceAll('_',' ')||'Idle',button=labels.get(w.id);
   button.querySelector('strong').textContent=title;button.querySelector('span').textContent=task;
   button.setAttribute('aria-label','Follow '+title+' · '+task);
   button.dataset.state=!w.available?'offline':w.route||w.task?'working':'idle';
   rings.get(w.id).material.color.setHex(!w.available?0xe98f85:w.route||w.task?0x52e5d5:0xaac0cf);
  }
  for(const n of state.conditions.blocked){const [x,z]=layout.nodes[n];hazards.add(box(x,.3,z,.85,.6,.85,0xe8ae63));}
  for(const id of state.conditions.broken){const w=state.workers.find(w=>w.id===id);if(w)hazards.add(box(w.position[0],1.3,w.position[1],.9,.12,.9,0xe98f85));}
  const count=order?Object.values(order.picked).reduce((a,b)=>a+b,0):0;
  for(let i=0;i<count;i++)basket.add(box(((i%3)-1)*.15,.6,Math.floor(i/3)*.15-.075,.13,.16,.13,0x83d6a2));
 }
 function position(w,t){const points=w.route?.points;if(!points?.length)return w.position;for(let i=1;i<points.length;i++){const a=points[i-1],b=points[i];if(t<=b[2]){const f=Math.max(0,Math.min(1,(t-a[2])/(b[2]-a[2]||1)));return[a[0]+(b[0]-a[0])*f,a[1]+(b[1]-a[1])*f];}}return points.at(-1);}
 const projected=new THREE.Vector3();let slowFrames=0,interval=33;
 function draw(now){
  if(disposed)return;requestAnimationFrame(draw);
  if(document.hidden||now-last<interval||!host.offsetParent)return;
  const moving=!reduced.matches&&rate>0&&state.workers.some(w=>w.route?.points.at(-1)?.[2]>sim)&&(now-received)*rate<10000;
  if(!dirty&&!moving)return;last=now;dirty=false;
  const time=sim+(reduced.matches?0:Math.min(10,(now-received)/1000*rate));
  for(const w of state.workers){
   const p=position(w,time),next=position(w,time+.1),m=workers.get(w.id);if(!m)continue;
   m.position.set(p[0],0,p[1]);
   if(Math.hypot(next[0]-p[0],next[1]-p[1])>.001)m.rotation.y=Math.atan2(next[0]-p[0],next[1]-p[1]);
   rings.get(w.id).position.set(p[0],.035,p[1]);
  }
  const owner=order&&workers.get(order.worker);basket.visible=!!owner;if(owner)basket.position.copy(owner.position);
  const tracked=workers.get(trackedWorker)||owner;
  if(tracking&&tracked){
   const target=tracked.position.clone();target.y=.6;
   const delta=target.clone().sub(controls.target).multiplyScalar(reduced.matches?1:.12);
   controls.target.add(delta);camera.position.add(delta);if(delta.length()>.002)dirty=true;
  }
  controls.update();renderer.render(scene,camera);
  if(overview){
   const extent={x:0,y:0};
   for(const corner of fitCorners){projected.copy(corner).project(camera);extent.x=Math.max(extent.x,Math.abs(projected.x));extent.y=Math.max(extent.y,Math.abs(projected.y));}
   renderer.domElement.dataset.overviewBounds=JSON.stringify(extent);
  }else delete renderer.domElement.dataset.overviewBounds;
  const occupied=[];
  for(const w of state.workers){
   const button=labels.get(w.id),model=workers.get(w.id);
   projected.copy(model.position);projected.y=1.55;projected.project(camera);
   button.hidden=projected.z>1||Math.abs(projected.x)>1.1||Math.abs(projected.y)>1.1;
   const x=(projected.x+1)*host.clientWidth/2;let y=(1-projected.y)*host.clientHeight/2;
   for(const other of occupied)if(Math.abs(x-other.x)<100&&Math.abs(y-other.y)<40)y=other.y-42;
   occupied.push({x,y});
   button.style.transform='translate(-50%,-100%) translate('+x+'px,'+y+'px)';
   button.setAttribute('aria-pressed',String(tracking&&(trackedWorker===w.id||!trackedWorker&&order?.worker===w.id)));
   button.dataset.x=model.position.x.toFixed(3);button.dataset.z=model.position.z.toFixed(3);
  }
  renderer.domElement.dataset.drawCalls=String(renderer.info.render.calls);
  renderer.domElement.dataset.triangles=String(renderer.info.render.triangles);
  // Software GPUs may use less resolution; the authoritative sim clock is unchanged.
  if(performance.now()-now>60)slowFrames++;else slowFrames=0;
  if(slowFrames===4){renderer.setPixelRatio(.8);interval=66;resize();}
 }requestAnimationFrame(draw);
 renderer.domElement.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','-'].includes(e.key))return;e.preventDefault();overview=false;const off=camera.position.clone().sub(controls.target);
  if(e.key==='+'||e.key==='-')off.multiplyScalar(e.key==='+'?.85:1.15);
  else{const s=new THREE.Spherical().setFromVector3(off);s.theta+=e.key==='ArrowLeft'?.15:e.key==='ArrowRight'?-.15:0;s.phi=Math.max(.2,Math.min(1.45,s.phi+(e.key==='ArrowUp'?-.1:e.key==='ArrowDown'?.1:0)));off.setFromSpherical(s);}
  camera.position.copy(controls.target).add(off);controls.update();dirty=true;
 });
 renderer.domElement.addEventListener('webglcontextlost',e=>{e.preventDefault();onFailure?.();});
 return {update,fit,track(value){tracking=value;overview=false;trackedWorker=null;dirty=true;if(value)camera.position.sub(controls.target).normalize().multiplyScalar(13).add(controls.target);},
 dispose(){disposed=true;observer.disconnect();controls.dispose();renderer.dispose();owned.forEach(item=>item.dispose());clear(routes);clear(hazards);clear(basket);renderer.domElement.remove();labelLayer.remove();}};
}
