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
export async function createStoreScene(host,initial,status,onFailure){
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
 const owned=new Set();
 function box(x,y,z,w,h,d,color){const geometry=new THREE.BoxGeometry(w,h,d),material=new THREE.MeshStandardMaterial({color,roughness:.85});owned.add(geometry);owned.add(material);const mesh=new THREE.Mesh(geometry,material);mesh.position.set(x,y,z);return mesh;}
 root.add(box(layout.width/2,-.15,layout.depth/2,layout.width+.5,.3,layout.depth+.5,0x213943));
 const cold=layout.cold_zone;root.add(box(cold.x+cold.width/2,.02,cold.z+cold.depth/2,cold.width,.04,cold.depth,0x315f78));
 root.add(box(layout.packing.x,.5,layout.packing.z,1.4,1,1,0x7c9694),box(layout.dock.x,.02,layout.dock.z,2.3,.04,2.4,0x8c7145));
 function label(text,x,z){const c=document.createElement('canvas');c.width=512;c.height=64;const ctx=c.getContext('2d');ctx.font='600 30px sans-serif';ctx.textAlign='center';ctx.fillStyle='#d9eaf3';ctx.fillText(text,256,40);const texture=new THREE.CanvasTexture(c),mat=new THREE.SpriteMaterial({map:texture,depthTest:false});owned.add(texture);owned.add(mat);const sprite=new THREE.Sprite(mat);sprite.position.set(x,.35,z);sprite.scale.set(4,.5,1);root.add(sprite);}
 label('PACK',layout.packing.x+1,layout.packing.z+1.3);label('COURIER DOCK',layout.dock.x-1,layout.dock.z+1.5);label('COLD',cold.x+2,.5);
 const racks=[];for(let a=0;a<layout.config.aisles;a++)for(let b=0;b<layout.config.bays;b++){const m=box(a*3+2,1.05,b*2+2,.9,2.1,1.6,0x708994);racks.push(m);root.add(m);}
 for(const s of layout.slots){const m=box(s.x+s.side*.55,s.y,s.z,.28,.24,.42,s.zone==='cold'?0x8ec8da:0xb1a181);root.add(m);slots.set(s.id,m);}
 function fitted(model,w,h,d){const copy=model.clone(true),bounds=new THREE.Box3().setFromObject(copy),size=bounds.getSize(new THREE.Vector3());copy.scale.multiplyScalar(Math.min(w/size.x,h/size.y,d/size.z));const adjusted=new THREE.Box3().setFromObject(copy),center=adjusted.getCenter(new THREE.Vector3());copy.position.set(-center.x,-adjusted.min.y,-center.z);const group=new THREE.Group();group.add(copy);return group;}
 const rackCopies=[];
 const loaded=await Promise.all(['shelving','robot','forklift','cart','pallet','produce','packaged'].map(asset));
 if(loaded[0])for(const r of racks){const m=fitted(loaded[0],1.1,2.2,1.7);m.position.set(r.position.x,0,r.position.z);root.add(m);rackCopies.push(m);r.visible=false;}
 // Repeated rack meshes share one draw call per geometry/material.
 root.updateMatrixWorld(true);
 const batches=new Map();
 for(const rack of rackCopies)rack.traverse(mesh=>{if(!mesh.isMesh)return;const key=mesh.geometry.uuid+':'+(Array.isArray(mesh.material)?mesh.material.map(m=>m.uuid).join(','):mesh.material.uuid);if(!batches.has(key))batches.set(key,{geometry:mesh.geometry,material:mesh.material,matrices:[]});batches.get(key).matrices.push(mesh.matrixWorld.clone());mesh.visible=false;});
 for(const batch of batches.values()){const mesh=new THREE.InstancedMesh(batch.geometry,batch.material,batch.matrices.length);batch.matrices.forEach((matrix,i)=>mesh.setMatrixAt(i,matrix));mesh.instanceMatrix.needsUpdate=true;root.add(mesh);owned.add(mesh);}
 for(const w of state.workers){const i=w.kind==='forklift'?2:w.kind==='staff'?3:1;const m=loaded[i]?fitted(loaded[i],.9,1.15,1.15):box(0,.45,0,.65,.9,.65,w.kind==='forklift'?0xd3b476:0x56cbbb);if(!loaded[i])m.geometry.translate(0,.45,0);root.add(m);workers.set(w.id,m);}
 if(loaded[4]){const m=fitted(loaded[4],1.2,.2,1.2);m.position.set(layout.dock.x-1.8,0,layout.dock.z);root.add(m);}
 for(const [i,s] of layout.slots.entries())if(i<8){const model=loaded[s.category==='produce'?5:6];if(model){const m=fitted(model,.3,.3,.3);m.position.set(s.x+s.side*.65,s.y+.15,s.z);root.add(m);}}
 status(loaded.some(m=>!m)?'Some models unavailable; simple shapes shown.':'3D cutaway · local SimReady models');
 function fit(){controls.target.set(layout.width/2,0,layout.depth/2);camera.position.set(layout.width+6,20,layout.depth+10);controls.update();}fit();
 function resize(){const w=host.clientWidth,h=host.clientHeight;if(!w||!h)return;camera.aspect=w/h;camera.updateProjectionMatrix();renderer.setSize(w,h,false);}
 const observer=new ResizeObserver(resize);observer.observe(host);resize();
 function clear(group){for(const child of [...group.children]){group.remove(child);child.geometry?.dispose();child.material?.dispose();owned.delete(child.geometry);owned.delete(child.material);}}
 function line(points){for(let i=1;i<points.length;i++){const a=new THREE.Vector3(points[i-1][0],.13,points[i-1][1]),b=new THREE.Vector3(points[i][0],.13,points[i][1]),length=a.distanceTo(b);if(!length)continue;const m=new THREE.Mesh(new THREE.CylinderGeometry(.07,.07,length,5),new THREE.MeshBasicMaterial({color:0x52e5d5}));m.position.copy(a).add(b).multiplyScalar(.5);m.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),b.sub(a).normalize());routes.add(m);}}
 function update(next,selected,clock){
  state=next;order=selected;sim=clock.sim;rate=clock.rate;received=performance.now();
  const stock=new Map(state.shelves.map(s=>[s.slot,s.quantity]));
  for(const s of layout.slots){const m=slots.get(s.id),wanted=order&&Object.hasOwn(order.lines,s.sku);m.visible=stock.get(s.id)>0;m.material.color.setHex(wanted?(order.picked[s.sku]?0x83d6a2:0x52e5d5):(s.zone==='cold'?0x8ec8da:0xb1a181));m.scale.setScalar(wanted?1.45:1);}
  clear(routes);clear(hazards);clear(basket);
  for(const w of state.workers)if(w.route&&(!order||w.task?.order_id===order.order_id))line(w.route.points);
  for(const n of state.conditions.blocked){const [x,z]=layout.nodes[n];hazards.add(box(x,.3,z,.85,.6,.85,0xe8ae63));}
  for(const id of state.conditions.broken){const w=state.workers.find(w=>w.id===id);if(w)hazards.add(box(w.position[0],1.3,w.position[1],.9,.12,.9,0xe98f85));}
  const count=order?Object.values(order.picked).reduce((a,b)=>a+b,0):0;
  for(let i=0;i<count;i++)basket.add(box((i%3)*.2,1.1,Math.floor(i/3)*.2,.16,.18,.16,0x83d6a2));
 }
 function position(w,t){const points=w.route?.points;if(!points?.length)return w.position;for(let i=1;i<points.length;i++){const a=points[i-1],b=points[i];if(t<=b[2]){const f=Math.max(0,Math.min(1,(t-a[2])/(b[2]-a[2]||1)));return[a[0]+(b[0]-a[0])*f,a[1]+(b[1]-a[1])*f];}}return points.at(-1);}
 function draw(now){if(disposed)return;requestAnimationFrame(draw);if(document.hidden||now-last<33||!host.offsetParent)return;last=now;
  const time=sim+(reduced.matches?0:Math.min(10,(now-received)/1000*rate));
  for(const w of state.workers){const p=position(w,time),m=workers.get(w.id);if(m)m.position.set(p[0],0,p[1]);}
  const owner=order&&workers.get(order.worker);basket.visible=!!owner;if(owner)basket.position.copy(owner.position);
  if(tracking&&owner){const target=owner.position.clone();target.y=.6;const delta=target.clone().sub(controls.target).multiplyScalar(reduced.matches?1:.065);controls.target.add(delta);camera.position.add(delta);}
  controls.update();renderer.render(scene,camera);
  renderer.domElement.dataset.drawCalls=String(renderer.info.render.calls);
  renderer.domElement.dataset.triangles=String(renderer.info.render.triangles);
 }requestAnimationFrame(draw);
 renderer.domElement.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','-'].includes(e.key))return;e.preventDefault();const off=camera.position.clone().sub(controls.target);
  if(e.key==='+'||e.key==='-')off.multiplyScalar(e.key==='+'?.85:1.15);
  else{const s=new THREE.Spherical().setFromVector3(off);s.theta+=e.key==='ArrowLeft'?.15:e.key==='ArrowRight'?-.15:0;s.phi=Math.max(.2,Math.min(1.45,s.phi+(e.key==='ArrowUp'?-.1:e.key==='ArrowDown'?.1:0)));off.setFromSpherical(s);}
  camera.position.copy(controls.target).add(off);controls.update();
 });
 renderer.domElement.addEventListener('webglcontextlost',e=>{e.preventDefault();onFailure?.();});
 return {update,fit,track(value){tracking=value;if(value)camera.position.sub(controls.target).normalize().multiplyScalar(13).add(controls.target);},
 dispose(){disposed=true;observer.disconnect();controls.dispose();renderer.dispose();owned.forEach(item=>item.dispose());clear(routes);clear(hazards);clear(basket);renderer.domElement.remove();}};
}
