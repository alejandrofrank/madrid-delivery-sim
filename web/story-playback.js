/* Pure recorded-time sampling: no invented motion across snapshot boundaries. */
export function frameAt(frames,time){
  let lo=0,hi=frames.length-1;
  while(lo<hi){const mid=Math.ceil((lo+hi)/2);if(frames[mid].time<=time)lo=mid;else hi=mid-1;}
  return frames[lo];
}
export function courierPosition(data,state,time){
  const route=state[3]>=0?data.routes[state[3]]:null;
  if(!route?.length)return state.slice(0,2);
  if(time<=route[0][2])return route[0].slice(0,2);
  let lo=0,hi=route.length-1;
  while(lo<hi){const mid=Math.ceil((lo+hi)/2);if(route[mid][2]<=time)lo=mid;else hi=mid-1;}
  const a=route[lo],b=route[lo+1];if(!b)return a.slice(0,2);
  const fraction=(time-a[2])/(b[2]-a[2]);return [a[0]+(b[0]-a[0])*fraction,a[1]+(b[1]-a[1])*fraction];
}
