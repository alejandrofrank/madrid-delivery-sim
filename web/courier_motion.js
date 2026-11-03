/* Pure movement helpers shared by the baseline renderer and its regression checks. */
(function (root, factory) {
  "use strict";
  const helpers = factory();
  if (typeof module === "object" && module.exports) module.exports = helpers;
  else root.CourierMotion = helpers;
})(typeof globalThis === "object" ? globalThis : this, function () {
  "use strict";
  const movingStatuses = new Set(["to_pickup", "delivering", "repositioning"]);

  function createDisplayClock({maxLead = 60} = {}) {
    const leadLimit = Math.max(0, Math.min(60, Number(maxLead) || 0));
    let runId = null, sim = 0, anchor = 0, displayed = 0;
    let duration = Infinity, rate = 0, running = false;

    function time(now) {
      const elapsed = running ? Math.max(0, now - anchor) / 1000 * rate : 0;
      displayed = Math.max(displayed, Math.min(duration, sim + leadLimit, sim + elapsed));
      return displayed;
    }

    function accept(run, now) {
      if (!run) {
        runId = null; sim = 0; anchor = now; displayed = 0;
        duration = Infinity; rate = 0; running = false;
        return displayed;
      }
      const nextSim = Number(run.sim_time) || 0;
      if (run.id !== runId) {
        runId = run.id; sim = nextSim; anchor = now; displayed = nextSim;
      } else if (nextSim > sim) {
        time(now);
        sim = nextSim; anchor = now; displayed = Math.max(displayed, sim);
      } else if (nextSim < sim) {
        return time(now); // A delayed packet cannot move this run's clock backward.
      }
      // Duplicate snapshots preserve the anchor, including their elapsed lead.
      duration = Number.isFinite(run.duration) ? run.duration : Infinity;
      running = run.status === "running" && Number(run.wall_seconds) > 0;
      rate = running ? Math.max(0, Number(run.duration) / Number(run.wall_seconds)) : 0;
      return time(now);
    }

    return {accept, time};
  }

  function pointAt(route, sim) {
    const points = route?.points;
    if (!points?.length) return null;
    if (sim <= points[0][2]) return [points[0][1], points[0][0]];
    for (let i = 1; i < points.length; i++) {
      const a = points[i - 1], b = points[i];
      if (sim <= b[2]) {
        const fraction = Math.max(0, Math.min(1, (sim - a[2]) / Math.max(.0001, b[2] - a[2])));
        return [a[1] + fraction * (b[1] - a[1]), a[0] + fraction * (b[0] - a[0])];
      }
    }
    const end = points[points.length - 1];
    return [end[1], end[0]];
  }

  function courierPosition(courier, sim) {
    const route = courier.route || courier.reposition_route;
    const moving = movingStatuses.has(courier.status) ? pointAt(route, sim) : null;
    return moving || [courier.lat, courier.lon];
  }

  // The entire small motion recording is available before playback starts.
  // Snapshot refreshes never own this clock. Both ends of every interval are
  // known, including a route assigned/replanned during the next snapshot.
  function createReplayMotion(data) {
    const tracks = new Map();
    const routeFor = position => data.routes[position[2]] || [];
    const at = (position, time) => {
      const p = pointAt({points:routeFor(position)},time);
      return p ? [p[1],p[0],time] : [position[0],position[1],time];
    };
    data.couriers.forEach((id, index) => {
      const points = [at(data.frames[0].positions[index], data.frames[0].time)];
      for (let f=1; f<data.frames.length; f++) {
        const previous=data.frames[f-1], next=data.frames[f];
        const a=previous.positions[index], b=next.positions[index];
        const oldRoute=routeFor(a), newRoute=routeFor(b);
        const changed=a[2]!==b[2] && newRoute.length;
        const switchAt=changed?Math.max(previous.time,newRoute[0][2]):Infinity;
        for(const p of oldRoute)
          if(p[2]>previous.time && p[2]<next.time && p[2]<switchAt)points.push(p);
        if(changed)for(const p of newRoute)
          if(p[2]>previous.time && p[2]<next.time && p[2]>=switchAt)points.push(p);
        points.push(at(b,next.time));
      }
      tracks.set(id,points);
    });
    return {
      duration:data.duration,
      position(id, seconds) {
        const points=tracks.get(id);if(!points)return null;
        const time=Math.max(0,Math.min(60,seconds))/60*data.duration;
        let lo=0,hi=points.length-1;
        while(lo<hi){const mid=Math.ceil((lo+hi)/2);if(points[mid][2]<=time)lo=mid;else hi=mid-1;}
        const a=points[lo],b=points[lo+1];if(!b)return [a[1],a[0]];
        const t=Math.max(0,Math.min(1,(time-a[2])/Math.max(.000001,b[2]-a[2])));
        return [a[1]+(b[1]-a[1])*t,a[0]+(b[0]-a[0])*t];
      }
    };
  }

  function motionFromStates(frames) {
    const ids=frames[0].couriers.map(c=>c.id),routes=[],references=new Map();
    return {duration:frames.at(-1).run.duration,couriers:ids,routes,frames:frames.map(frame=>{
      const byId=new Map(frame.couriers.map(c=>[c.id,c]));
      return {time:frame.run.sim_time,positions:ids.map(id=>{
        const c=byId.get(id),route=c.route||c.reposition_route;
        let ref=-1;
        if(route?.points?.length&&movingStatuses.has(c.status)){
          const key=JSON.stringify(route.points);
          if(!references.has(key)){references.set(key,routes.length);routes.push(route.points);}
          ref=references.get(key);
        }
        return [c.lon,c.lat,ref];
      })};
    })};
  }

  function markerLabel(courier) {
    const suffix = String(courier.id).match(/(\d+)$/)?.[1] || "";
    return String(courier.mode || "").slice(0, 1).toUpperCase() + suffix;
  }

  return {createDisplayClock, pointAt, courierPosition, createReplayMotion, motionFromStates, markerLabel};
});
