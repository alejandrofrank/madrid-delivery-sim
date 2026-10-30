"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const {createDisplayClock, pointAt, courierPosition, markerLabel} = require("../web/courier_motion.js");

const run = {id: "day-a", sim_time: 0, duration: 1200, wall_seconds: 120, status: "running"};
const route = {points: [[-3.7, 40.4, 0], [-3.69, 40.41, 30], [-3.69, 40.41, 90], [-3.68, 40.42, 120]]};

test("duplicate snapshots never rewind display time or courier movement", () => {
  const clock = createDisplayClock();
  clock.accept(run, 1000);
  const before = clock.time(3000);
  const courier = {status: "to_pickup", route, lat: 40.4, lon: -3.7};
  const position = courierPosition(courier, before);
  assert.equal(clock.accept({...run}, 3000), before);
  assert.deepEqual(courierPosition(courier, clock.time(3000)), position);
  clock.accept({...run}, 4000);
  assert.equal(clock.time(4000), 30);
  assert.equal(clock.time(20000), 60, "projection is bounded to one simulation step");
  clock.accept({...run}, 20000);
  assert.equal(clock.time(21000), 60);
});

test("advancing ticks preserve progress; another run resets its own clock", () => {
  const clock = createDisplayClock();
  clock.accept(run, 0);
  assert.equal(clock.time(10000), 60);
  assert.equal(clock.accept({...run, sim_time: 60}, 10000), 60);
  assert.equal(clock.time(12000), 80);
  assert.equal(clock.accept({...run, sim_time: 0}, 12000), 80, "late packets are ignored");
  assert.equal(clock.accept({...run, id: "day-b", sim_time: 0}, 12000), 0);
  assert.equal(clock.time(13000), 10);
});

test("completed and unpaced runs do not extrapolate past authoritative time", () => {
  const clock = createDisplayClock();
  clock.accept({...run, sim_time: 1190}, 0);
  assert.equal(clock.time(5000), 1200);
  assert.equal(clock.accept({...run, status: "complete", sim_time: 1200}, 5000), 1200);
  assert.equal(clock.time(50000), 1200);
  clock.accept({...run, id: "unpaced", wall_seconds: 0, sim_time: 300}, 50000);
  assert.equal(clock.time(60000), 300);
  assert.equal(clock.accept(null, 60000), 0);
});

test("route interpolation respects preparation waits and completion", () => {
  assert.deepEqual(pointAt(route, -10), [40.4, -3.7]);
  assert.deepEqual(pointAt(route, 30), [40.41, -3.69]);
  assert.deepEqual(pointAt(route, 60), [40.41, -3.69]);
  assert.deepEqual(pointAt(route, 90), [40.41, -3.69]);
  assert.deepEqual(pointAt(route, 120), [40.42, -3.68]);
  assert.deepEqual(pointAt(route, 999), [40.42, -3.68]);
  assert.equal(pointAt({points: []}, 0), null);
});

test("active and repositioning routes share placement; idle falls back to stored point", () => {
  const courier = {lat: 41, lon: -4, route};
  for (const status of ["to_pickup", "delivering", "repositioning"]) {
    assert.deepEqual(courierPosition({...courier, status}, 60), [40.41, -3.69]);
  }
  assert.deepEqual(courierPosition({...courier, status: "idle"}, 60), [41, -4]);
  assert.deepEqual(courierPosition({...courier, route: null, reposition_route: route, status: "repositioning"}, 60), [40.41, -3.69]);
  assert.deepEqual(courierPosition({...courier, route: null, status: "delivering"}, 60), [41, -4]);
});

test("courier labels carry mode and stable numeric identity", () => {
  assert.equal(markerLabel({id: "chamberi-01", mode: "bike"}), "B01");
  assert.equal(markerLabel({id: "retiro-03", mode: "moto"}), "M03");
  assert.equal(markerLabel({id: "vallecas-05", mode: "van"}), "V05");
});
