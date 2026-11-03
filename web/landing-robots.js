import * as THREE from './vendor/three/three.module.js';
import {createAgentModel} from './agent-anatomy-3d.js';

// An illustrated role handoff, separate from the measured city recording.
// The parent owns the only animation clock and pauses it when out of view.
export function createLandingRobots(host,agents){
  const renderer=new THREE.WebGLRenderer({antialias:true,alpha:true,powerPreference:'low-power'});
  renderer.setPixelRatio(Math.min(devicePixelRatio||1,1.5));renderer.setClearColor(0,0);
  renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;
  host.append(renderer.domElement);renderer.domElement.setAttribute('aria-hidden','true');
  const scene=new THREE.Scene(),camera=new THREE.OrthographicCamera(-5,5,4,-4,.1,80);
  camera.position.set(8,7,16);camera.lookAt(0,1.7,0);
  scene.add(new THREE.HemisphereLight(0xffffff,0x718b64,2.8));
  const key=new THREE.DirectionalLight(0xfff5df,3.5);key.position.set(-5,10,8);key.castShadow=true;key.shadow.mapSize.set(512,512);scene.add(key);
  const models=agents.map((agent,index)=>{const model=createAgentModel({detail:false});model.decorate(agent);model.root.position.x=index?2:-2;model.root.rotation.y=index?-.3:.5;scene.add(model.root);return model;});
  const plane=new THREE.Mesh(new THREE.PlaneGeometry(14,8),new THREE.ShadowMaterial({opacity:.12}));plane.rotation.x=-Math.PI/2;plane.receiveShadow=true;scene.add(plane);
  const bag=new THREE.Mesh(new THREE.BoxGeometry(.8,.75,.6),new THREE.MeshStandardMaterial({color:0xb88649,roughness:.85}));bag.castShadow=true;bag.position.y=1.9;scene.add(bag);
  let time=0;
  function fit(){const {width,height}=host.getBoundingClientRect();if(!width||!height)return;renderer.setSize(width,height,false);const span=5.9;camera.left=-span*width/height/2;camera.right=-camera.left;camera.top=span/2;camera.bottom=-span/2;camera.updateProjectionMatrix();render();}
  function render(){
    const phase=(time%8)/8,travel=Math.min(1,Math.max(0,(phase-.15)/.6)),ease=travel*travel*(3-2*travel);
    bag.position.x=-1.15+ease*2.3;bag.position.y=1.9+Math.sin(travel*Math.PI)*.2;
    models.forEach((model,index)=>{model.rig.rotation.y=Math.sin(time*.7+index)*.035;model.fan.rotation.z=time*(index?-.7:.7);});
    renderer.render(scene,camera);
  }
  const observer=new ResizeObserver(fit);observer.observe(host);fit();
  return {setTime(value){time=value;render();},theme:render,dispose(){observer.disconnect();models.forEach(model=>model.resources.forEach(item=>item.dispose()));plane.geometry.dispose();plane.material.dispose();bag.geometry.dispose();bag.material.dispose();renderer.dispose();renderer.domElement.remove();}};
}
