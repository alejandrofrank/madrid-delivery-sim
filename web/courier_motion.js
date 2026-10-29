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

  function markerLabel(courier) {
    const suffix = String(courier.id).match(/(\d+)$/)?.[1] || "";
    return String(courier.mode || "").slice(0, 1).toUpperCase() + suffix;
  }

  return {createDisplayClock, pointAt, courierPosition, markerLabel};
});
