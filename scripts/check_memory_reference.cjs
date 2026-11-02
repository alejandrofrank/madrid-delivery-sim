/** In-place documentation: real projections, keyboard tabs, sources and chapter links. */
const assert=require("node:assert/strict");
module.exports=async function checkMemory(page,data,capture,out){
 const agent=data.agents.find(a=>a.id==="restaurant");
 const ref=agent.panels.find(p=>p.id==="memory").reference;
 await page.locator('.team-agent[data-agent="restaurant"]').click();
 await page.locator("#anatomy-part-select").selectOption("memory");
 const canvas=page.locator(".anatomy-illustration canvas");
 const camera=await canvas.getAttribute("data-camera");
 assert.equal(await page.locator(".memory-reference h4").first().innerText(),ref.format);
 assert(await page.getByText("One synthetic restaurant.order record",{exact:true}).isVisible());
 for(const group of ref.fields){
  await page.locator(".memory-record-groups button").filter({hasText:group.title}).click();
  for(const key of group.keys)assert((await page.locator(".memory-record-fields").innerText()).includes(key));
 }
 await page.getByRole("tab",{name:"Core view",exact:true}).click();
 for(const [mode,projection] of Object.entries(ref.contracts[0].projections)){
  await page.locator("#memory-profile").selectOption(mode);
  const raw=await page.locator(".memory-tab-content .memory-code").first().innerText();
  assert.deepEqual(mode==="text"?raw:JSON.parse(raw),projection);
 }
 await page.getByRole("tab",{name:"Local / GCP",exact:true}).click();
 for(const place of ["local","gcp"]){
  await page.locator("#memory-storage").selectOption(place);
  assert((await page.locator(".memory-tab-content").innerText()).includes(ref.storage[place].status));
  for(const node of ref.storage[place].nodes)assert((await page.locator(".memory-storage-flow").innerText()).includes(node[0]));
 }
 await page.getByRole("tab",{name:"Constraints",exact:true}).click();
 assert((await page.locator(".memory-bounds").innerText()).includes("8192"));
 await page.getByText("What the tests prove",{exact:true}).click();
 for(const text of ref.evidence)assert((await page.locator(".memory-tab-content").innerText()).includes(text));
 await page.getByRole("tab",{name:"Constraints",exact:true}).focus();
 await page.keyboard.press("Home");
 assert.equal(await page.getByRole("tab",{name:"Record",exact:true}).getAttribute("aria-selected"),"true");
 assert.equal(await canvas.getAttribute("data-camera"),camera);
 assert.equal(await page.getByText("Read the docs chapter",{exact:true}).count(),0);
 const url=page.url();
 await page.locator(".anatomy-full-reference>summary").click();
 await page.locator(".anatomy-inline-article").waitFor();
 assert((await page.locator(".anatomy-inline-article").innerText()).includes("Semantic recall and the core"));
 // Chapter navigation stays in the inspector, and source dialogs retain context.
 await page.locator(".anatomy-inline-article a").filter({hasText:"restaurant ADK adapter"}).click();
 assert.equal(page.url(),url);
 await page.getByRole("button",{name:"Back to component reference",exact:true}).click();
 await page.locator(".anatomy-inline-article [data-source]").filter({hasText:"typed contracts"}).click();
 await page.locator("#source-dialog[open]").waitFor();
 await page.waitForFunction(()=>document.querySelector("#source-code").textContent.includes("CONTRACTS"));
 await page.keyboard.press("Escape");
 await page.waitForURL(url);
 assert.equal(page.url(),url);
 assert.equal(await canvas.getAttribute("data-camera"),camera);
 await page.locator(".anatomy-full-reference>summary").click();
 // The classifier must not inherit a generic persistent-memory demonstration.
 await page.locator('.team-agent[data-agent="customer_service"]').click();
 await page.locator("#anatomy-part-select").selectOption("memory");
 assert.equal(await page.locator("#memory-profile").count(),0);
 assert((await page.locator(".memory-reference").innerText()).includes("no persistent memory contract"));
 await page.locator('.team-agent[data-agent="inventory"]').click();
 await page.locator("#anatomy-part-select").selectOption("memory");
 await page.locator("#memory-kind").selectOption("inventory.shipment");
 assert((await page.locator(".memory-record-fields").innerText()).includes("expected_sim"));
 await page.locator('.team-agent[data-agent="restaurant"]').click();
 for(const [name,width,height] of [["desktop",1463,753],["mobile",390,844]]){
  await page.setViewportSize({width,height});
  await page.locator("#anatomy-part-select").selectOption("memory");
  for(const tab of ["Record","Core view","Local / GCP","Constraints"]){
   await page.getByRole("tab",{name:tab,exact:true}).click();
   if(tab==="Local / GCP")await page.locator("#memory-storage").selectOption("gcp");
   if(tab==="Core view")await page.locator("#memory-profile").selectOption("json");
   await page.evaluate(()=>{document.querySelector("#anatomy-inspector").scrollTop=0;document.activeElement?.blur();scrollTo(0,0);});
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   await capture(page,out+"/memory-"+name+"-"+tab.toLowerCase().replaceAll(/[^a-z]+/g,"-")+".png");
  }
 }
 await page.setViewportSize({width:1440,height:1000});
};
