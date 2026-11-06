// Deterministic 3D render of one closed-loop simulation scenario (data from tools/viz3d/export_scene.py).
// window.setFrame(i) draws frame i at FPS; tools/viz3d/capture.py screenshots every frame into a video.
// Display only: poses are interpolated between recorded 100 ms windows; nothing is re-simulated.
import * as THREE from '../../flyhead/monitor/web/vendor/three.module.js';

const Q = new URLSearchParams(location.search);
const FPS = +(Q.get('fps') || 20), SPEED = +(Q.get('speed') || 1);
const COLORS = {FORWARD: '#4c9be8', EXPLORE: '#7fc8f8', TURN_LEFT: '#9b8de0', TURN_RIGHT: '#c08de0', HOLD: '#9e9e9e',
  REST: '#c9c9c9', FREEZE: '#f2c14e', ESCAPE_PROGRAM: '#e4572e', BACK_OFF: '#f08a4b', FLEE: '#b0306a'};
const DESC = {
  person_front: 'A person walks toward the robot from the front at 0.5 m/s and stops 0.7 m away.',
  person_left: 'A person approaches from the left at 0.5 m/s and stops 0.7 m away.',
  person_right: 'A person approaches from the right at 0.5 m/s and stops 0.7 m away.',
  loom_front: 'An object approaches head-on at 0.6 m/s: a looming stimulus from the front.',
  loom_left: 'An object approaches from the left at 0.6 m/s.',
  loom_right: 'An object approaches from the right at 0.6 m/s.',
  wall_ahead: 'The robot drives toward the end wall of a lane on the real map.',
  roam_open: 'Free roaming on the open floor of the real map, driven only by the brain.',
};
const $ = id => document.getElementById(id);
const b64 = (s, T) => { const b = atob(s), u = new Uint8Array(b.length); for (let i = 0; i < b.length; i++) u[i] = b.charCodeAt(i); return new T(u.buffer); };

const scene = await (await fetch(Q.get('scene'))).json();
const B = scene.brain, N = scene.blind, OBJ = scene.objects;
const T0 = B[0][0], T1 = B[B.length - 1][0];
const NFRAMES = Math.floor((T1 - T0) / SPEED * FPS) + 1;
const kind = scene.scenario.split('_')[0];
$('desc').textContent = DESC[scene.scenario] || scene.scenario;

// ---------------------------------------------------------------- renderer, camera, light
const renderer = new THREE.WebGLRenderer({antialias: true, preserveDrawingBuffer: true});
renderer.setPixelRatio(1); renderer.setSize(1600, 900);
renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
document.body.prepend(renderer.domElement);
const S = new THREE.Scene();
S.background = new THREE.Color('#050506'); S.fog = new THREE.Fog('#050506', 9, 22);
const cam = new THREE.PerspectiveCamera(40, 1600 / 900, 0.05, 80);
cam.setViewOffset(1600, 900, 190, 0, 1600, 900);   // scene centre sits left of the side panel
S.add(new THREE.HemisphereLight('#c9d6ff', '#1a1410', 0.9));
const key = new THREE.DirectionalLight('#ffffff', 2.2);
key.position.set(4, 7, 3); key.castShadow = true; key.shadow.mapSize.set(2048, 2048);
Object.assign(key.shadow.camera, {left: -4, right: 4, top: 4, bottom: -4, near: 0.5, far: 20});
S.add(key, key.target);
const rim = new THREE.DirectionalLight('#9fb4ff', 0.9); rim.position.set(-5, 3, -4); S.add(rim);

// ---------------------------------------------------------------- site cloud (height colour like the console)
{
  const pos = b64(scene.cloud.pos, Int16Array), h = b64(scene.cloud.h, Uint8Array), n = scene.cloud.n;
  const P = new Float32Array(n * 3), C = new Float32Array(n * 3), c = new THREE.Color();
  const ramp = ['#2340d8', '#1f9be0', '#16c6a0', '#7fd84a', '#f2d03b', '#f2803b', '#e0303a'].map(s => new THREE.Color(s));
  for (let i = 0; i < n; i++) {
    P[3 * i] = pos[3 * i] / 100; P[3 * i + 1] = pos[3 * i + 1] / 100; P[3 * i + 2] = pos[3 * i + 2] / 100;
    const u = h[i] / 255 * (ramp.length - 1), k = Math.min(ramp.length - 2, Math.floor(u));
    c.copy(ramp[k]).lerp(ramp[k + 1], u - k);
    const dim = P[3 * i + 1] < 0.08 ? 0.16 : 0.6 + 0.4 * Math.min(1, P[3 * i + 1] / 0.5);   // floor layer stays dark
    C[3 * i] = c.r * dim; C[3 * i + 1] = c.g * dim; C[3 * i + 2] = c.b * dim;
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(P, 3)); g.setAttribute('color', new THREE.BufferAttribute(C, 3));
  S.add(new THREE.Points(g, new THREE.PointsMaterial({size: 0.022, vertexColors: true, transparent: true, opacity: 0.95, depthWrite: false})));
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(80, 80), new THREE.ShadowMaterial({opacity: 0.45}));
  floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; S.add(floor);
}

// ---------------------------------------------------------------- DIABLO (vendor meshes, URDF frame, mm)
function parseSTL(buf) {
  const dv = new DataView(buf), n = dv.getUint32(80, true), P = new Float32Array(n * 9);
  for (let i = 0; i < n; i++) {
    const o = 84 + 50 * i + 12;
    for (let j = 0; j < 3; j++) {
      const x = dv.getFloat32(o + 12 * j, true), y = dv.getFloat32(o + 12 * j + 4, true), z = dv.getFloat32(o + 12 * j + 8, true);
      P[9 * i + 3 * j] = x / 1000; P[9 * i + 3 * j + 1] = z / 1000; P[9 * i + 3 * j + 2] = -y / 1000;   // URDF -> y up
    }
  }
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(P, 3)); g.computeVertexNormals();
  return g;
}
const PARTS = ['base_link', 'motor_left_link_1', 'motor_right_link_1', 'leg_left_link_1', 'leg_right_link_1',
  'leg2_left_link_1', 'leg2_right_link_1', 'wheel_left_link_1', 'wheel_right_link_1'];
const geos = {};
await Promise.all(PARTS.map(async p => { geos[p] = parseSTL(await (await fetch(`./assets/diablo/${p}.stl`)).arrayBuffer()); }));
const AXLE_Y = 0.099, WHEEL_R = 0.094;
function makeRobot(ghost) {
  const root = new THREE.Group(), wheels = [];
  const shell = ghost ? new THREE.MeshStandardMaterial({color: '#8fa6d6', emissive: '#1c2a4a', transparent: true, opacity: 0.42, depthWrite: false, roughness: .6})
    : new THREE.MeshStandardMaterial({color: '#e2e4ea', metalness: 0.35, roughness: 0.34, emissive: '#1a1b20'});
  const dark = ghost ? shell : new THREE.MeshStandardMaterial({color: '#4a4c54', metalness: 0.45, roughness: 0.5});
  const tyre = ghost ? shell : new THREE.MeshStandardMaterial({color: '#151517', roughness: 0.9});
  for (const p of PARTS) {
    const m = new THREE.Mesh(geos[p], p.startsWith('wheel') ? tyre : p.startsWith('base') ? shell : dark);
    m.castShadow = !ghost;
    if (p.startsWith('wheel')) {
      geos[p].computeBoundingBox(); const c = geos[p].boundingBox.getCenter(new THREE.Vector3());
      const pivot = new THREE.Group(); pivot.position.set(c.x, AXLE_Y, c.z); m.position.set(-c.x, -AXLE_Y, -c.z);
      pivot.add(m); root.add(pivot); wheels.push(pivot);
    } else root.add(m);
  }
  if (!ghost) {   // L1 LiDAR marker (rear-facing on the real robot), drawn as a small dark puck
    const lidar = new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.05, 0.06, 32), dark);
    lidar.position.set(-0.11, 0.47, 0); root.add(lidar);
  }
  S.add(root);
  return {root, wheels};
}
const RB = makeRobot(false), RN = N.length ? makeRobot(true) : null;

// ---------------------------------------------------------------- objects (0.25 m cylinders in the simulation)
function makePerson() {
  const g = new THREE.Group(), m = new THREE.MeshStandardMaterial({color: '#d8d2c8', roughness: .7, metalness: .05});
  const add = (geo, x, y, z) => { const o = new THREE.Mesh(geo, m); o.position.set(x, y, z); o.castShadow = true; g.add(o); };
  add(new THREE.CapsuleGeometry(0.07, 0.72, 6, 12), 0, 0.43, 0.09); add(new THREE.CapsuleGeometry(0.07, 0.72, 6, 12), 0, 0.43, -0.09);
  add(new THREE.CapsuleGeometry(0.17, 0.42, 8, 16), 0, 1.08, 0);
  add(new THREE.CapsuleGeometry(0.05, 0.55, 6, 12), 0, 1.06, 0.24); add(new THREE.CapsuleGeometry(0.05, 0.55, 6, 12), 0, 1.06, -0.24);
  add(new THREE.SphereGeometry(0.11, 20, 16), 0, 1.55, 0);
  const ring = new THREE.Mesh(new THREE.RingGeometry(0.24, 0.26, 48), new THREE.MeshBasicMaterial({color: '#ff8a7a', transparent: true, opacity: .7}));
  ring.rotation.x = -Math.PI / 2; ring.position.y = 0.01; g.add(ring);
  S.add(g); return g;
}
function makeLoom() {
  const g = new THREE.Group();
  const body = new THREE.Mesh(new THREE.CylinderGeometry(scene.object_radius, scene.object_radius, 1.0, 48),
    new THREE.MeshStandardMaterial({color: '#e4572e', emissive: '#4a1608', roughness: .45, metalness: .2}));
  body.position.y = 0.5; body.castShadow = true; g.add(body); S.add(g); return g;
}
const objs = (OBJ[0] || []).map(() => kind === 'person' ? makePerson() : makeLoom());
$('objLegend').innerHTML = !objs.length ? '' : kind === 'person'
  ? '<i style="background:#d8d2c8"></i>Person (a 0.25 m cylinder in the simulation)'
  : '<i style="background:#e4572e"></i>Looming object (0.25 m cylinder)';

// ---------------------------------------------------------------- trails
const toV = (x, y, h = 0.02) => new THREE.Vector3(x, h, -y);
const trailB = (() => {
  const P = new Float32Array(B.length * 3), C = new Float32Array(B.length * 3), c = new THREE.Color();
  B.forEach((r, i) => { const v = toV(r[1], r[2]); P.set([v.x, v.y, v.z], 3 * i); c.set(COLORS[r[4]] || '#888'); C.set([c.r, c.g, c.b], 3 * i); });
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(P, 3)); g.setAttribute('color', new THREE.BufferAttribute(C, 3));
  const l = new THREE.Line(g, new THREE.LineBasicMaterial({vertexColors: true, linewidth: 2})); S.add(l); return l;
})();
const trailN = N.length ? (() => {
  const P = new Float32Array(N.length * 3); N.forEach((r, i) => { const v = toV(r[1], r[2], 0.015); P.set([v.x, v.y, v.z], 3 * i); });
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(P, 3));
  const l = new THREE.Line(g, new THREE.LineDashedMaterial({color: '#9a9aa2', dashSize: .08, gapSize: .06, transparent: true, opacity: .7}));
  l.computeLineDistances(); S.add(l); return l;
})() : null;

// ---------------------------------------------------------------- precomputed: wheel travel, smoothed camera
// signed wheel travel: distance between windows, negative while the executed command reverses
function cumDist(R, vIdx) {
  const d = [0];
  for (let i = 1; i < R.length; i++) d.push(d[i - 1] + Math.hypot(R[i][1] - R[i - 1][1], R[i][2] - R[i - 1][2]) * (R[i][vIdx] < 0 ? -1 : 1));
  return d;
}
const distB = cumDist(B, 5), distN = N.length ? cumDist(N, 4) : [];
function sample(R, t, extra) {
  const k = (t - R[0][0]) / 0.1, i = Math.max(0, Math.min(R.length - 1, Math.floor(k))), j = Math.min(R.length - 1, i + 1), a = Math.min(1, Math.max(0, k - i));
  let dy = R[j][3] - R[i][3]; dy = Math.atan2(Math.sin(dy), Math.cos(dy));
  return {i, x: R[i][1] + (R[j][1] - R[i][1]) * a, y: R[i][2] + (R[j][2] - R[i][2]) * a, yaw: R[i][3] + dy * a,
    d: extra ? extra[i] + (extra[j] - extra[i]) * a : 0};
}
const camPath = [];
{
  // Fixed viewing azimuth per scenario, so a turn of the robot never swings the camera behind the stimulus:
  // with an object, look perpendicular to the robot-object line (both stay side by side on screen);
  // without one, look obliquely across the robot's start heading. The camera only pans to follow.
  const o0 = (OBJ[0] || [])[0];
  let az = o0 ? Math.atan2(o0[1] - B[0][2], o0[0] - B[0][1]) - Math.PI / 2 : B[0][3] - 2.2;
  const DIST = o0 ? 4.9 : 4.6, HEIGHT = o0 ? 2.7 : 3.0;
  let cx = null, tx = null;
  for (let f = 0; f < NFRAMES; f++) {
    const t = T0 + f / FPS * SPEED, s = sample(B, t);
    let ox = s.x, oy = s.y;
    const ob = OBJ[s.i] || [];
    if (ob.length) { const o = ob[0]; ox = (s.x + o[0]) / 2; oy = (s.y + o[1]) / 2; }
    const want = new THREE.Vector3(ox + Math.cos(az) * DIST, HEIGHT, -(oy + Math.sin(az) * DIST));
    const look = new THREE.Vector3(ox, 0.3, -oy);
    cx = cx ? cx.lerp(want, 0.08) : want.clone(); tx = tx ? tx.lerp(look, 0.12) : look.clone();
    camPath.push([cx.clone(), tx.clone()]);
  }
}

// ---------------------------------------------------------------- HUD
const reads = $('reads');
const READ_KEYS = (() => { const m = {}; B.forEach(r => Object.entries(r[15] || {}).forEach(([k, v]) => { m[k] = Math.max(m[k] || 0, v); })); return Object.entries(m).sort((a, b) => b[1] - a[1]).slice(0, 4).map(e => e[0]); })();
reads.innerHTML = READ_KEYS.map(k => `<div class="row"><span>${k.replace('_left', ' L').replace('_right', ' R')}</span><div class="bar"><i data-k="${k}" style="background:#c08de0"></i></div><b data-v="${k}"></b></div>`).join('');
const used = [...new Set(B.map(r => r[4]))];
$('tl').innerHTML = B.map(r => `<i style="flex:1;background:${COLORS[r[4]] || '#666'}"></i>`).join('');
$('tlabels').innerHTML = used.map(s => `<span><b style="background:${COLORS[s] || '#666'}"></b>${s.replace('_', ' ').toLowerCase()}</span>`).join('');
const bar = (id, v, max) => { $(id).style.width = Math.max(0, Math.min(100, 100 * Math.abs(v) / max)) + '%'; };
const tags = $('tags');
const tag = (() => { const el = document.createElement('div'); el.className = 'tag'; tags.appendChild(el); return el; })();
function project(v) { const p = v.clone().project(cam); return [(p.x * .5 + .5) * 1600, (-p.y * .5 + .5) * 900, p.z < 1]; }

// ---------------------------------------------------------------- one frame
window.NFRAMES = NFRAMES; window.FPS = FPS;
window.setFrame = f => {
  f = Math.max(0, Math.min(NFRAMES - 1, f));
  const t = T0 + f / FPS * SPEED, s = sample(B, t, distB), r = B[s.i];
  RB.root.position.set(s.x, 0, -s.y); RB.root.rotation.y = s.yaw;
  RB.wheels.forEach(w => { w.rotation.z = -s.d / WHEEL_R; });
  if (RN) { const n = sample(N, t, distN); RN.root.position.set(n.x, 0, -n.y); RN.root.rotation.y = n.yaw; RN.wheels.forEach(w => { w.rotation.z = -n.d / WHEEL_R; }); }
  const ob = OBJ[s.i] || [], ob2 = OBJ[Math.min(OBJ.length - 1, s.i + 1)] || ob, a = Math.min(1, Math.max(0, (t - T0) / 0.1 - s.i));
  objs.forEach((o, k) => {
    if (!ob[k]) { o.visible = false; return; }
    o.visible = true;
    const x = ob[k][0] + ((ob2[k] || ob[k])[0] - ob[k][0]) * a, y = ob[k][1] + ((ob2[k] || ob[k])[1] - ob[k][1]) * a;
    o.position.set(x, 0, -y); o.rotation.y = Math.atan2(s.y - y, s.x - x);   // the person faces the robot
  });
  trailB.geometry.setDrawRange(0, s.i + 1);
  if (trailN) trailN.geometry.setDrawRange(0, Math.min(N.length, s.i + 1));
  const [cp, tp] = camPath[f]; cam.position.copy(cp); cam.lookAt(tp);
  key.position.set(s.x + 3, 7, -s.y + 3); key.target.position.set(s.x, 0, -s.y);
  // HUD
  $('tval').textContent = (t - T0).toFixed(1) + ' s';
  $('state').textContent = (r[4] || '—').replace('_', ' '); $('state').style.background = COLORS[r[4]] || '#888';
  bar('bLoomL', r[8], 0.6); bar('bLoomR', r[9], 0.6); $('vLoomL').textContent = r[8].toFixed(2); $('vLoomR').textContent = r[9].toFixed(2);
  bar('bLcL', r[10], 120); bar('bLcR', r[11], 120); $('vLcL').textContent = r[10].toFixed(0); $('vLcR').textContent = r[11].toFixed(0);
  bar('bGf', r[12], 200); bar('bMdn', r[13], 100); bar('bP9', r[14], 60);
  $('vGf').textContent = (+r[12]).toFixed(0); $('vMdn').textContent = (+r[13]).toFixed(0); $('vP9').textContent = (+r[14]).toFixed(0);
  READ_KEYS.forEach(k => { const v = (r[15] || {})[k] || 0; reads.querySelector(`[data-k="${k}"]`).style.width = Math.min(100, v) + '%'; reads.querySelector(`[data-v="${k}"]`).textContent = v.toFixed(0); });
  bar('bV', r[5], 0.3); bar('bW', r[6], 1.0); bar('bClr', r[7], 3.0);
  $('vV').textContent = r[5].toFixed(2); $('vW').textContent = r[6].toFixed(2); $('vClr').textContent = r[7].toFixed(2) + ' m';
  $('cursor').style.left = (100 * s.i / (B.length - 1)) + '%';
  renderer.render(S, cam);
  const [px, py, vis] = project(new THREE.Vector3(s.x, 0.78, -s.y));
  tag.style.display = vis ? 'block' : 'none'; tag.style.left = px + 'px'; tag.style.top = py + 'px';
  tag.textContent = 'decision: ' + (r[4] || '').replace('_', ' ').toLowerCase();
  return f;
};
window.setFrame(0);
window.READY = true;
