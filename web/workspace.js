/* One shell and a small DOM component set shared by every product page. */
(() => {
  "use strict";
  const make=(tag,text,className)=>{const node=document.createElement(tag);if(text!=null)node.textContent=text;if(className)node.className=className;return node;};
  const paths={
    play:"m9 5 11 7-11 7Z",pause:"M8 5v14M16 5v14",
    sun:"M12 3v2m0 14v2M3 12h2m14 0h2M5.6 5.6 7 7m10 10 1.4 1.4M5.6 18.4 7 17m10-10 1.4-1.4M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0",
    moon:"M20.5 14.1A8.5 8.5 0 0 1 9.9 3.5 8.5 8.5 0 1 0 20.5 14.1Z",
    menu:"M4 6h16M4 12h16M4 18h16",chevron:"m6 9 6 6 6-6",close:"m6 6 12 12M6 18 18 6",
    arrow:"M4 12h16m-6-6 6 6-6 6",bag:"M5 7h14l2 14H3L5 7Zm3 0V5a4 4 0 0 1 8 0v2",
    store:"M3 10h18L19 3H5l-2 7Zm2 0v11h14V10M9 21v-7h6v7M8 3l-1 7m9-7 1 7",
    courier:"M7 16a4 4 0 1 1-8 0 4 4 0 0 1 8 0m18 0a4 4 0 1 1-8 0 4 4 0 0 1 8 0M3 16l5-8 5 8H3m5-8h9m-1-4 5 12M7 5h4",
    team:"M3 20v-3a4 4 0 0 1 4-4h2a4 4 0 0 1 4 4v3m3-7a4 4 0 0 1 4 4v3M11 6a3 3 0 1 1-6 0 3 3 0 0 1 6 0m5-3a3 3 0 0 1 0 6",
    rain:"M7 15H6a4 4 0 0 1 0-8 6 6 0 0 1 11-1 4.5 4.5 0 0 1 1 9M8 18l-1 3m6-3-1 3m6-3-1 3",
    check:"m5 12 4 4L20 5",search:"M16 10a6 6 0 1 1-12 0 6 6 0 0 1 12 0m-2 4 6 6",
    box:"m3 7 9-5 9 5v10l-9 5-9-5V7Zm0 0 9 5 9-5M12 12v10M7 4.8l10 5",
    code:"m8 6-6 6 6 6m8-12 6 6-6 6M14 3l-4 18"
  };
  function icon(name){
    const svg=document.createElementNS("http://www.w3.org/2000/svg","svg");
    svg.setAttribute("viewBox","0 0 24 24");svg.setAttribute("aria-hidden","true");svg.classList.add("ui-icon");
    const path=document.createElementNS(svg.namespaceURI,"path");path.setAttribute("d",paths[name]||paths.box);svg.append(path);return svg;
  }
  function button(label,{href,primary=false,icon:iconName}={}){
    const node=make(href?"a":"button",null,"ui-button"+(primary?" primary":""));
    if(href)node.href=href;else node.type="button";
    if(iconName)node.append(icon(iconName));node.append(make("span",label));return node;
  }
  function tooltip(label,technical){
    const node=make("span",label,"ui-tooltip");node.tabIndex=0;
    const hint=make("span",technical);hint.setAttribute("role","tooltip");
    hint.id="hint-"+Math.random().toString(36).slice(2);node.setAttribute("aria-describedby",hint.id);node.append(hint);return node;
  }
  function drawer(id,title,content){
    const panel=make("dialog",null,"ui-drawer");panel.id=id;
    const heading=make("h2",title);heading.id=id+"-title";panel.setAttribute("aria-labelledby",heading.id);
    const header=make("header"),close=button("Close");close.dataset.drawerClose="";header.append(heading,close);
    panel.append(header,content);document.body.append(panel);return panel;
  }
  let trigger=null;
  document.addEventListener("click",event=>{
    const opener=event.target.closest("[data-drawer-open]");
    if(opener){const panel=document.getElementById(opener.dataset.drawerOpen);if(panel){trigger=opener;panel.showModal();}}
    const closer=event.target.closest("[data-drawer-close]");
    if(closer)closer.closest("dialog")?.close();
  });
  document.addEventListener("close",event=>{if(event.target.classList?.contains("ui-drawer"))trigger?.focus();},true);
  window.ProductUI={make,icon,button,tooltip,drawer};
  document.querySelectorAll("[data-icon]").forEach(node=>node.replaceChildren(icon(node.dataset.icon)));
  let theme="light";try{theme=localStorage.getItem("mds-theme")==="dark"?"dark":"light";}catch{}
  document.documentElement.dataset.theme=theme;
  const mount=document.getElementById("workspace-shell");if(!mount)return;
  const search=document.getElementById("open-search");
  const header=make("header",null,"workspace-header");
  const brand=make("a",null,"workspace-brand");brand.href="/";brand.setAttribute("aria-label","Madrid home");
  const logo=document.createElementNS("http://www.w3.org/2000/svg","svg");logo.setAttribute("viewBox","0 0 36 32");logo.setAttribute("aria-hidden","true");logo.classList.add("workspace-logo");
  const mark=document.createElementNS(logo.namespaceURI,"path");mark.setAttribute("d","M2 27 11 5h6l-9 22Zm11 0 9-22h6l-9 22Zm10-17 10 17h-7l-6-10Z");mark.setAttribute("fill","currentColor");logo.append(mark);
  brand.append(logo,make("span","Madrid"));
  const nav=make("nav",null,"workspace-navigation");nav.id="workspace-navigation";nav.setAttribute("aria-label","Primary");
  for(const [href,label] of [["/","How it works"],["/watch","Watch it live"],["/agents","Meet the agents"]]){
    const link=make("a",label);link.href=href;if(location.pathname===href)link.setAttribute("aria-current","page");nav.append(link);
  }
  const actions=make("div",null,"workspace-actions");
  const engineers=make("details",null,"workspace-engineers"),summary=make("summary","For engineers");
  summary.append(icon("chevron"));const links=make("nav",null,"workspace-engineer-links");links.setAttribute("aria-label","For engineers");
  for(const [slug,label] of [["operations","Operations"],["restaurants","Restaurants"],["inventory","Inventory"],["health","Health"],["traces","Traces"],["architecture","Architecture chapters"]]){
    const link=make("a",label);link.href="/engineers/"+slug;if(location.pathname===link.getAttribute("href"))link.setAttribute("aria-current","page");links.append(link);
  }
  if(search)links.append(search);else {const link=make("a","Search the documentation");link.href="/engineers/architecture?search=1";links.append(link);}
  engineers.append(summary,links);
  const toggle=button("",{});toggle.className="workspace-theme";
  function paintTheme(){const dark=document.documentElement.dataset.theme==="dark";toggle.replaceChildren(icon(dark?"sun":"moon"));toggle.setAttribute("aria-label",dark?"Use light appearance":"Use dark appearance");toggle.title=toggle.getAttribute("aria-label");toggle.setAttribute("aria-pressed",String(dark));}
  paintTheme();toggle.addEventListener("click",()=>{const next=document.documentElement.dataset.theme==="dark"?"light":"dark";document.documentElement.dataset.theme=next;try{localStorage.setItem("mds-theme",next);}catch{}paintTheme();window.dispatchEvent(new CustomEvent("themechange",{detail:{theme:next}}));});
  const cta=button("Watch it run",{href:"/watch",primary:true,icon:"play"});cta.classList.add("workspace-cta");
  const menu=button("",{});menu.className="workspace-menu";menu.append(icon("menu"));menu.setAttribute("aria-label","Open navigation");menu.setAttribute("aria-controls",nav.id);menu.setAttribute("aria-expanded","false");
  const closeMenu=()=>{header.removeAttribute("data-menu-open");menu.setAttribute("aria-expanded","false");menu.setAttribute("aria-label","Open navigation");engineers.open=false;};
  menu.addEventListener("click",()=>{const open=menu.getAttribute("aria-expanded")!=="true";header.toggleAttribute("data-menu-open",open);menu.setAttribute("aria-expanded",String(open));menu.setAttribute("aria-label",open?"Close navigation":"Open navigation");});
  header.addEventListener("keydown",event=>{if(event.key==="Escape"){const wasEngineer=engineers.open;closeMenu();(wasEngineer?summary:menu).focus();}});
  document.addEventListener("click",event=>{if(!header.contains(event.target))closeMenu();});
  nav.addEventListener("click",closeMenu);
  actions.append(engineers,toggle,cta,menu);header.append(brand,nav,actions);
  const skip=make("a","Skip to content","workspace-skip");skip.href=document.body.dataset.page==="architecture"?"#reader":"#main";
  mount.replaceChildren(skip,header);
  const engineer=location.pathname.startsWith("/engineers/");
  if(engineer){
    document.body.dataset.audience="engineer";
    const environment=make("div","Local workspace · synthetic simulation","workspace-environment");environment.id="workspace-environment";mount.append(environment);
    fetch("/api/runtime").then(r=>r.ok?r.json():null).then(runtime=>{if(runtime?.mode==="replay")environment.textContent="Recorded examples · read-only replay";else if(runtime?.mode==="live")environment.textContent="Private live workspace · authorized access";}).catch(()=>{environment.textContent="Recorded examples · live services unavailable";});
  }else document.body.dataset.audience="visitor";
  if(!document.querySelector(".workspace-footer")){
    const footer=make("footer",null,"workspace-footer");footer.append(make("span","Madrid delivery sim · built to be explored."));
    const footerNav=make("nav");footerNav.setAttribute("aria-label","Footer");
    for(const [label,href] of [["GitHub","https://github.com/alejandrofrank/madrid-delivery-sim"],["Documentation","/engineers/architecture"],["Contact","https://github.com/alejandrofrank"]]){const link=make("a",label);link.href=href;footerNav.append(link);}
    footer.append(footerNav);document.body.append(footer);
  }
})();
