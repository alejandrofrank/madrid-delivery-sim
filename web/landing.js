import {courierPosition, frameAt} from './story-playback.js';

const canvas=document.getElementById('story-canvas'),ctx=canvas.getContext('2d');
const progress=document.getElementById('story-progress'),pause=document.getElementById('story-pause');
const reduced=matchMedia('(prefers-reduced-motion: reduce)');
let data,clock=1440,playing=!reduced.matches,visible=true,last=0,raf=0,robots=null;
let width=0,height=0,dpr=1,project,backdrop,palette;
const css=name=>getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const line=(context,points)=>{points.forEach((p,i)=>{const [x,y]=project(p);i?context.lineTo(x,y):context.moveTo(x,y);});};
function fit(){
  if(!data||!ctx)return;
  const box=canvas.getBoundingClientRect();width=box.width;height=box.height;dpr=Math.min(devicePixelRatio||1,2);
  canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);
  const mobile=width<=700,mapHeight=mobile?470:height*1.45,mapWidth=mapHeight*data.map.aspect_ratio;
  const left=mobile?(width-mapWidth)/2:width*.70-mapWidth/2,top=mobile?285:height*.44-mapHeight/2;
  project=p=>[left+p[0]/data.map.units*mapWidth,top+p[1]/data.map.units*mapHeight];
  palette={ground:css('--map-ground'),road:css('--map-road'),edge:css('--map-edge'),route:css('--map-route'),label:css('--map-label'),ink:css('--ui-ink'),surface:css('--ui-surface'),accent:css('--ui-accent'),muted:css('--ui-muted')};
  backdrop=document.createElement('canvas');backdrop.width=canvas.width;backdrop.height=canvas.height;
  const base=backdrop.getContext('2d');base.setTransform(dpr,0,0,dpr,0,0);base.fillStyle=palette.ground;base.fillRect(0,0,width,height);
  base.beginPath();for(const road of data.map.roads)line(base,road);base.lineWidth=3.8;base.strokeStyle=palette.edge;base.stroke();base.lineWidth=2.5;base.strokeStyle=palette.road;base.stroke();
  const named=new Set();base.textAlign='center';base.font='500 13px "IBM Plex Sans", sans-serif';
  for(const site of data.map.sites){
    const [x,y]=project(site.point);base.fillStyle=palette.muted;base.globalAlpha=.5;base.fillRect(x-2,y-2,4,4);base.globalAlpha=1;
    if(site.kind==='hub'&&!named.has(site.district)){named.add(site.district);base.fillStyle=palette.label;base.fillText(site.district,x,y-23);}
  }
  draw();
}
function draw(){
  if(!data||!ctx||!backdrop)return;
  ctx.clearRect(0,0,width,height);ctx.drawImage(backdrop,0,0,width,height);
  const frame=frameAt(data.frames,clock),active=[];
  frame.couriers.forEach((state,index)=>{
    if(state[2]===4||state[2]===5)return;
    const moving=state[3]>=0,route=moving?data.routes[state[3]]:null;
    if(route){ctx.beginPath();line(ctx,route);ctx.strokeStyle=palette.route;ctx.globalAlpha=.45;ctx.lineWidth=2.4;ctx.stroke();ctx.globalAlpha=1;}
    active.push({point:project(courierPosition(data,state,clock)),moving,index});
  });
  for(const order of data.orders){
    if(order.site==null||clock<order.created||clock>order.created+200)continue;
    const [x,y]=project(data.map.sites[order.site].point),phase=(clock-order.created)/200;
    ctx.beginPath();ctx.arc(x,y,7+phase*15,0,Math.PI*2);ctx.strokeStyle=palette.accent;ctx.lineWidth=2;ctx.globalAlpha=1-phase;ctx.stroke();ctx.globalAlpha=1;
    ctx.fillStyle=palette.surface;ctx.strokeStyle=palette.ink;ctx.lineWidth=1.8;ctx.fillRect(x-5,y-5,10,10);ctx.strokeRect(x-5,y-5,10,10);
  }
  for(const {point:[x,y],moving} of active){
    ctx.beginPath();ctx.arc(x,y,moving?5.8:3.2,0,Math.PI*2);ctx.fillStyle=moving?palette.accent:palette.surface;ctx.fill();ctx.strokeStyle=moving?palette.surface:palette.muted;ctx.lineWidth=moving?1.8:1.2;ctx.stroke();
  }
  progress.value=String(Math.round(clock));document.getElementById('story-time').textContent=Math.floor(clock/60)+' min / 2 hours';
  robots?.setTime(clock/data.clock.duration*data.clock.playback_seconds);
  canvas.dataset.simTime=String(Math.round(clock));
}
function syncButton(){pause.replaceChildren(window.ProductUI.icon(playing?'pause':'play'));pause.setAttribute('aria-label',playing?'Pause recorded shift':'Play recorded shift');pause.setAttribute('aria-pressed',String(!playing));}
function tick(now){raf=0;if(last)clock=(clock+(now-last)/1000*data.clock.duration/data.clock.playback_seconds)%data.clock.duration;last=now;draw();schedule();}
function schedule(){if(data&&playing&&visible&&!document.hidden&&!raf)raf=requestAnimationFrame(tick);}
function suspend(){if(raf)cancelAnimationFrame(raf);raf=0;last=0;}
pause.addEventListener('click',()=>{playing=!playing;syncButton();suspend();schedule();});
progress.addEventListener('input',()=>{clock=Number(progress.value);last=0;draw();});
new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;visible?schedule():suspend();}).observe(document.querySelector('.story-opening'));
document.addEventListener('visibilitychange',()=>{document.hidden?suspend():schedule();});
reduced.addEventListener('change',()=>{playing=!reduced.matches;suspend();syncButton();draw();schedule();});
window.addEventListener('themechange',()=>{fit();robots?.theme();});new ResizeObserver(fit).observe(canvas);
const stepObserver=new IntersectionObserver(entries=>{for(const entry of entries)if(entry.isIntersecting){entry.target.classList.add('flow-visible');stepObserver.unobserve(entry.target);}},{threshold:.65});
document.querySelectorAll('.story-steps li').forEach(node=>stepObserver.observe(node));
async function load(){
  const failure=document.getElementById('story-map-fallback');failure.hidden=true;
  try{
    const response=await fetch('/static/data/story-replay.json');if(!response.ok)throw Error('Recording unavailable');data=await response.json();
    const o=data.outcomes;document.getElementById('story-on-time').textContent=o.on_time+' / '+o.delivered;document.getElementById('story-recovered').textContent=o.resolved_disruptions+' / '+o.disruptions;document.getElementById('story-cost').textContent=new Intl.NumberFormat('en-IE',{style:'currency',currency:'EUR'}).format(o.cost_per_delivery_eur);
    fit();syncButton();schedule();
    try{const [{createLandingRobots},roleResponse]=await Promise.all([import('./landing-robots.js?v=63575595c096'),fetch('/static/data/story-agents.json')]);if(!roleResponse.ok)throw Error('Roles unavailable');robots=createLandingRobots(document.getElementById('story-robots'),await roleResponse.json());draw();}catch{document.getElementById('story-handoff').hidden=true;}
  }catch{failure.hidden=false;pause.disabled=true;progress.disabled=true;}
}
document.getElementById('story-retry').addEventListener('click',()=>{pause.disabled=false;progress.disabled=false;load();});
window.addEventListener('pagehide',()=>{suspend();robots?.dispose();});
load();
