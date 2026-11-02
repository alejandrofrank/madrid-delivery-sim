/* Stable role symbols: shared by controls, beacons and the full robot. */
window.AgentRoleSymbols=(()=>{
 const paths={
  stock:'M4 7 12 3 20 7 20 17 12 21 4 17Z M4 7 12 11 20 7 M12 11V21',
  pick:'M5 3V10L9 14 M19 3V10L15 14 M9 14V19H15V14 M9 8H15',
  dispatch:'M4 12H12V4H20 M12 12V20H20 M17 1 20 4 17 7 M17 17 20 20 17 23',
  deliver:'M3 12H21 M14 5 21 12 14 19 M4 5H8 M4 19H8',
  review:'M5 3H19V21H5Z M8 11 11 14 17 8 M8 18H16',
  home:'M3 11 12 3 21 11 M6 9V21H18V9 M10 21V15H14V21',
  kitchen:'M5 3V10 M2 3V7Q2 10 5 10Q8 10 8 7V3 M5 10V21 M18 3Q14 7 15 12H18 M18 3V21',
  supply:'M3 9H13V18H3Z M13 12H18L21 15V18H13 M5 18V21H8V18 M16 18V21H19V18 M6 5H14',
  support:'M4 13V10A8 8 0 0 1 20 10V16 M4 10H7V17H4Z M17 10H20V17H17Z M20 16Q20 21 13 21H11',
 };
 function icon(visual){
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');svg.classList.add('role-symbol');
  const p=document.createElementNS(svg.namespaceURI,'path');p.setAttribute('d',paths[visual.symbol]||paths.stock);p.setAttribute('fill','none');p.setAttribute('stroke','currentColor');p.setAttribute('stroke-width','1.7');p.setAttribute('stroke-linecap','round');p.setAttribute('stroke-linejoin','round');svg.append(p);return svg;
 }
 function paint(canvas,visual){
  const ctx=canvas.getContext('2d'),size=canvas.width;ctx.clearRect(0,0,size,size);
  ctx.fillStyle=visual.color;ctx.beginPath();ctx.arc(size/2,size/2,size*.47,0,Math.PI*2);ctx.fill();
  ctx.save();ctx.translate(size*.17,size*.17);ctx.scale(size*.66/24,size*.66/24);
  ctx.strokeStyle='#0c151c';ctx.lineWidth=1.8;ctx.lineJoin='round';ctx.lineCap='round';ctx.stroke(new Path2D(paths[visual.symbol]||paths.stock));ctx.restore();
 }
 return {icon,paint};
})();