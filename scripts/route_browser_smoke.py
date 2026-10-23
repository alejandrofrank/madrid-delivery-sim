"""Verify route traces and authoritative departure timing in the real map renderer."""

# ruff: noqa: E501 -- JavaScript fixtures exercise the browser renderer.
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("http://127.0.0.1:8010/delivery-lab", wait_until="networkidle")
    page.wait_for_selector('#city[data-node-count="1024"]')
    result = page.evaluate("""() => {
      const check=(condition,message)=>{if(!condition)throw Error(message);};
      const path=[{id:0,x:0,y:0},{id:1,x:100,y:0},{id:2,x:100,y:100}];
      let p=routeProgress(path,[10,20],20);
      check(p.position.x===100&&p.position.y===50,'Position must follow per-edge traffic durations');
      check(p.travelled.length===3&&p.remaining.length===2,'Split at current courier position');
      check(routeProgress(path,[10,20],10).position.y===0,'Exact junction boundary');
      check(routeProgress(path,[10,20],100).remaining.length===0,'No remaining route after arrival');
      check(routeProgress(path,[0,20],2)===null,'Invalid durations rejected');
      const savedCity=city,savedSnapshot=snapshot;
      city={nodes:path,edges:[{from:0,to:1,travel_seconds:10},{from:1,to:2,travel_seconds:20}],stores:[]};
      const job={basket:'trace-check',courier:'bike-1',status:'assigned',route:[0,1,2],route_durations:[10,20],depart_sim:0,accepted:false};
      const data={run:{sim_time:20},jobs:[job],fleet:[{id:'bike-1',node:0,status:'active'}],attempts:[]};
      drawMovement(data);
      check(!document.querySelector('[data-route-part="travelled"]'),'Unaccepted assignments must not move');
      check(document.querySelector('[data-courier] circle').getAttribute('cx')==='0','Waiting courier remains at authoritative node');
      job.accepted=true;drawMovement(data);
      check(document.querySelector('[data-courier] circle').getAttribute('cy')==='50','Accepted departure at zero uses elapsed time');
      check(document.querySelector('[data-route-part="remaining"]').getAttribute('stroke-dasharray')!=='none','Future route is dashed');
      check(document.querySelector('[data-route-end]'),'Destination marker exists');
      job.route=[0,2];drawMovement(data);
      check(!document.querySelector('[data-route-basket]'),'Never bridge absent road edges');
      city=savedCity;if(savedSnapshot)drawMovement(savedSnapshot);
      return {timing:'passed',route_splitting:'passed',unaccepted_departure:'passed',invalid_edges:'passed'};
    }""")
    assert not errors, errors
    Path("artifacts").mkdir(exist_ok=True)
    page.screenshot(path="artifacts/route-rendering.png", full_page=True)
    print(json.dumps(result))
    browser.close()
