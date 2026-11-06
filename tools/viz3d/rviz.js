// RViz2-style deterministic render of one closed-loop simulation scenario (data from tools/viz3d/export_scene.py).
// The window chrome reproduces RViz2's layout; the 3D view follows RViz conventions (grid, TF axes, PointCloud2 with
// AxisColor on Z, nav_msgs/Path, Marker cylinders, a jsk-style OverlayText and Plotter2D). The data are the recorded
// simulation windows; poses are interpolated between 100 ms windows for display only. Nothing is re-simulated.
import * as THREE from '../../flyhead/monitor/web/vendor/three.module.js';

const Q = new URLSearchParams(location.search);
const FPS = +(Q.get('fps') || 20), SPEED = +(Q.get('speed') || 1);
const VW = 966, VH = 684;
const $ = id => document.getElementById(id);
const b64 = (s, T) => { const b = atob(s), u = new Uint8Array(b.length); for (let i = 0; i < b.length; i++) u[i] = b.charCodeAt(i); return new T(u.buffer); };

const scene = await (await fetch(Q.get('scene'))).json();
const B = scene.brain, N = scene.blind, OBJ = scene.objects;
const T0 = B[0][0], T1 = B[B.length - 1][0];
const NFRAMES = Math.floor((T1 - T0) / SPEED * FPS) + 1;
const REFLEX = scene.mode === 'reflex';
const kind = REFLEX ? 'person' : scene.scenario.split('_')[0];
const NOBJ = Math.max(...OBJ.map(o => (o || []).length));
const HAS_OBJ = NOBJ > 0;
const ARM2 = REFLEX ? 'planner_arm' : 'no_brain';

// ---------------------------------------------------------------- 3D view (RViz look: flat light, no shadows)
const renderer = new THREE.WebGLRenderer({antialias: true, preserveDrawingBuffer: true});
renderer.setPixelRatio(1); renderer.setSize(VW, VH); renderer.outputColorSpace = THREE.SRGBColorSpace;
$('viewport').prepend(renderer.domElement);
const S = new THREE.Scene(); S.background = new THREE.Color(48 / 255, 48 / 255, 48 / 255);
const cam = new THREE.PerspectiveCamera(45, VW / VH, 0.01, 200);
S.add(new THREE.AmbientLight('#ffffff', 0.55));
const head = new THREE.DirectionalLight('#ffffff', 1.25); cam.add(head); head.position.set(0, 0, 1); S.add(cam);

// Grid (cell 1 m, 20 cells, offset to the scenario like the Grid display's Offset property)
const GX = Math.round(B[0][1]), GY = Math.round(B[0][2]);
{
  const g = new THREE.GridHelper(20, 20, 0xa0a0a4, 0xa0a0a4);
  g.material.transparent = true; g.material.opacity = 0.5; g.position.set(GX, 0.001, -GY); S.add(g);
}
// TF axes (red x, green y, blue z), drawn as RViz does: shafts with arrow heads
function axes(len, rad) {
  const g = new THREE.Group();
  const mk = (color, rot) => {
    const m = new THREE.MeshLambertMaterial({color});
    const shaft = new THREE.Mesh(new THREE.CylinderGeometry(rad, rad, len * 0.8, 12), m); shaft.position.y = len * 0.4;
    const tip = new THREE.Mesh(new THREE.ConeGeometry(rad * 2.2, len * 0.2, 12), m); tip.position.y = len * 0.9;
    const a = new THREE.Group(); a.add(shaft, tip); rot(a); g.add(a);
  };
  mk('#ff0000', a => { a.rotation.z = -Math.PI / 2; });        // x (map +x)
  mk('#00ff00', a => { a.rotation.x = -Math.PI / 2; });        // y (map +y = three -z)
  mk('#0000ff', () => {});                                     // z (up)
  return g;
}
const mapAxes = axes(1.0, 0.03); S.add(mapAxes);

// PointCloud2 /map_cloud: Flat Squares 0.03 m, AxisColor on Z (RViz rainbow), floor layer thinned for legibility
let NPTS = 0;
{
  const pos = b64(scene.cloud.pos, Int16Array), n = scene.cloud.n;
  const P = [], C = [], c = new THREE.Color();
  for (let i = 0; i < n; i++) {
    const y = pos[3 * i + 1] / 100;
    if (y < 0.05 && (i % 4)) continue;
    P.push(pos[3 * i] / 100, y, pos[3 * i + 2] / 100);
    c.setHSL(0.72 * (1 - Math.min(1, Math.max(0, y / 2.0))), 1, 0.5);   // rainbow: low = blue/violet, high = red
    C.push(c.r, c.g, c.b);
  }
  NPTS = P.length / 3;
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(P, 3)); g.setAttribute('color', new THREE.Float32BufferAttribute(C, 3));
  S.add(new THREE.Points(g, new THREE.PointsMaterial({size: 0.03, vertexColors: true})));
}

// RobotModel: DIABLO vendor meshes (URDF frame, mm)
function parseSTL(buf) {
  const dv = new DataView(buf), n = dv.getUint32(80, true), P = new Float32Array(n * 9);
  for (let i = 0; i < n; i++) {
    const o = 84 + 50 * i + 12;
    for (let j = 0; j < 3; j++) {
      const x = dv.getFloat32(o + 12 * j, true), y = dv.getFloat32(o + 12 * j + 4, true), z = dv.getFloat32(o + 12 * j + 8, true);
      P[9 * i + 3 * j] = x / 1000; P[9 * i + 3 * j + 1] = z / 1000; P[9 * i + 3 * j + 2] = -y / 1000;
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
function makeRobot(alpha) {
  const root = new THREE.Group(), wheels = [];
  const tr = alpha < 1 ? {transparent: true, opacity: alpha, depthWrite: false} : {};
  const body = new THREE.MeshLambertMaterial({color: '#c8c8c8', ...tr}), dark = new THREE.MeshLambertMaterial({color: '#5a5a5a', ...tr});
  for (const p of PARTS) {
    const m = new THREE.Mesh(geos[p], p.startsWith('base') ? body : dark);
    if (p.startsWith('wheel')) {
      geos[p].computeBoundingBox(); const c = geos[p].boundingBox.getCenter(new THREE.Vector3());
      const pivot = new THREE.Group(); pivot.position.set(c.x, AXLE_Y, c.z); m.position.set(-c.x, -AXLE_Y, -c.z);
      pivot.add(m); root.add(pivot); wheels.push(pivot);
    } else root.add(m);
  }
  const tf = axes(0.32, 0.012); tf.position.y = 0.002; root.add(tf);
  S.add(root);
  return {root, wheels};
}
const RB = makeRobot(1), RN = N.length ? makeRobot(0.4) : null;

// MarkerArray /flyhead/sim/objects: CYLINDER markers with the simulation's radius
const objH = kind === 'person' ? 1.7 : 1.0;
const objs = Array.from({length: NOBJ}, (_, k) => {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(scene.object_radius, scene.object_radius, objH, 32),
    new THREE.MeshLambertMaterial({color: kind === 'person' ? '#ff8c00' : '#ff3b30', transparent: true, opacity: REFLEX && k ? 0.3 : 0.85, depthWrite: !(REFLEX && k)}));
  m.position.y = objH / 2; const g = new THREE.Group(); g.add(m); S.add(g); return g;
});

// goal marker (stage 6): a yellow sphere on a pole
if (scene.goal) {
  const m = new THREE.MeshLambertMaterial({color: '#ffd400'});
  const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.015, 0.015, 0.6, 8), m); pole.position.set(scene.goal[0], 0.3, -scene.goal[1]);
  const ball = new THREE.Mesh(new THREE.SphereGeometry(0.09, 20, 14), m); ball.position.set(scene.goal[0], 0.62, -scene.goal[1]);
  S.add(pole, ball);
}

// nav_msgs/Path: brain (25;255;0), no-brain (85;170;255)
function pathLine(R, color) {
  const P = new Float32Array(R.length * 3); R.forEach((r, i) => P.set([r[1], 0.01, -r[2]], 3 * i));
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(P, 3));
  const l = new THREE.Line(g, new THREE.LineBasicMaterial({color})); S.add(l); return l;
}
const pathB = pathLine(B, '#19ff00'), pathN = N.length ? pathLine(N, '#55aaff') : null;

// ---------------------------------------------------------------- motion helpers (same as render.js)
function cumDist(R, vIdx) {
  const d = [0];
  for (let i = 1; i < R.length; i++) d.push(d[i - 1] + Math.hypot(R[i][1] - R[i - 1][1], R[i][2] - R[i - 1][2]) * (R[i][vIdx] < 0 ? -1 : 1));
  return d;
}
const distB = cumDist(B, 5), distN = N.length ? cumDist(N, 4) : [];
function sample(R, t, extra) {
  const k = (t - R[0][0]) / 0.1, i = Math.max(0, Math.min(R.length - 1, Math.floor(k))), j = Math.min(R.length - 1, i + 1), a = Math.min(1, Math.max(0, k - i));
  let dy = R[j][3] - R[i][3]; dy = Math.atan2(Math.sin(dy), Math.cos(dy));
  return {i, a, x: R[i][1] + (R[j][1] - R[i][1]) * a, y: R[i][2] + (R[j][2] - R[i][2]) * a, yaw: R[i][3] + dy * a,
    d: extra ? extra[i] + (extra[j] - extra[i]) * a : 0};
}
// Orbit view: fixed yaw per scenario (perpendicular to the robot-object line), focal point pans to follow
const camPath = [];
{
  const o0 = (OBJ[0] || [])[0];
  const az = REFLEX ? 2.2 : o0 ? Math.atan2(o0[1] - B[0][2], o0[0] - B[0][1]) - Math.PI / 2 : B[0][3] - 2.2;
  const DIST = REFLEX ? 7.5 : o0 ? 5.6 : 5.2, PITCH = REFLEX ? 0.8 : 0.62;
  let fx = null;
  for (let f = 0; f < NFRAMES; f++) {
    const t = T0 + f / FPS * SPEED, s = sample(B, t);
    let ox = s.x, oy = s.y; const ob = OBJ[s.i] || [];
    if (ob.length && ob[0] && !REFLEX) { ox = (s.x + ob[0][0]) / 2; oy = (s.y + ob[0][1]) / 2; }
    const want = new THREE.Vector3(ox, 0, -oy);
    fx = fx ? fx.lerp(want, 0.1) : want.clone();
    camPath.push({focal: fx.clone(), yaw: az, pitch: PITCH, dist: DIST});
  }
}

// ---------------------------------------------------------------- 2D overlays: labels, OverlayText, Plotter2D
const labels = $('labels');
const mkLabel = color => { const el = document.createElement('div'); el.className = 'lbl'; el.style.color = color; labels.appendChild(el); return el; };
const lblMap = mkLabel('#ffffff'), lblBase = mkLabel('#ffffff'), lblBlind = RN ? mkLabel('#ffffff') : null, lblState = mkLabel('#ffffff');
const lblObj = objs.map(() => mkLabel('#ffd27a'));
function place(el, v, text) {
  const p = v.clone().project(cam), vis = p.z < 1 && Math.abs(p.x) < 1.1 && Math.abs(p.y) < 1.1;
  el.style.display = vis ? 'block' : 'none';
  el.style.left = ((p.x * .5 + .5) * VW) + 'px'; el.style.top = ((-p.y * .5 + .5) * VH) + 'px';
  if (text !== undefined) el.textContent = text;
}
const plot = $('plot').getContext('2d');
function drawPlot(i) {
  const W = 300, H = 132, x0 = 34, y0 = 22, w = W - x0 - 10, h = H - y0 - 20, span = 80;   // last 8 s
  plot.clearRect(0, 0, W, H);
  plot.fillStyle = '#e6f2ff'; plot.font = '12px "DejaVu Sans Mono",Consolas,monospace';
  plot.fillText('/flyhead/brain/gf_hz  /lc9_hz', 8, 15);
  plot.strokeStyle = 'rgba(230,242,255,.35)'; plot.strokeRect(x0, y0, w, h);
  const lo = Math.max(0, i - span), series = [[12, '#ff6b5a', 200], [10, '#4dd9c3', 120]];
  plot.fillStyle = 'rgba(230,242,255,.6)'; plot.fillText('200', 4, y0 + 8); plot.fillText('0', 18, y0 + h);
  for (const [k, col, max] of series) {
    plot.strokeStyle = col; plot.lineWidth = 1.6; plot.beginPath();
    for (let j = lo; j <= i; j++) { const xx = x0 + w * (j - (i - span)) / span, yy = y0 + h - h * Math.min(1, (+B[j][k] || 0) / max); j === lo ? plot.moveTo(xx, yy) : plot.lineTo(xx, yy); }
    plot.stroke();
  }
}

// ---------------------------------------------------------------- Displays and Views docks (static RViz properties)
const row = (k, v, d, opts = {}) => `<div class="tr${opts.alt ? ' alt' : ''}${opts.sel ? ' sel' : ''}"><div class="k" style="padding-left:${4 + d * 14}px">` +
  `<span class="arr">${opts.arr || ''}</span>${opts.cb !== undefined ? `<span class="cb">${opts.cb ? '✓' : ''}</span>` : ''}` +
  `${opts.ic ? `<span class="ic" style="background:${opts.ic}"></span>` : ''}<span>${k}</span></div><div class="v"${opts.vid ? ` id="${opts.vid}"` : ''}>${v}</div></div>`;
const ok = '<span class="ok">✔</span>';
let alt = false; const R = (...a) => { alt = !alt; return row(a[0], a[1], a[2], {...(a[3] || {}), alt}); };
$('dtree').innerHTML = [
  R('Global Options', '', 0, {arr: '▾', ic: '#7a8fb5'}),
  R('Fixed Frame', 'map', 1), R('Background Color', '<span class="sw" style="background:#303030"></span>48; 48; 48', 1), R('Frame Rate', '30', 1),
  R('Global Status: Ok', '', 0, {arr: '▸', ic: '#2e8b2e'}),
  R('Grid', '', 0, {arr: '▸', cb: true, ic: '#9a9a9a'}),
  R('RobotModel', '', 0, {arr: '▾', cb: true, ic: '#c8a24a'}),
  R('Status: Ok', '', 1, {arr: '▸'}), R('Description Topic', '/robot_description', 1), R('Alpha', '1', 1),
  R(REFLEX ? 'RobotModel (planner arm)' : 'RobotModel (no brain)', '', 0, {arr: '▸', cb: true, ic: '#c8a24a'}),
  R('TF', '', 0, {arr: '▸', cb: true, ic: '#d24a4a'}),
  R('PointCloud2', '', 0, {arr: '▾', cb: true, ic: '#4a8fd2', sel: true}),
  R('Status: Ok', '', 1, {arr: '▸'}), R('Topic', '/map_cloud', 1), R('Style', 'Flat Squares', 1), R('Size (m)', '0.03', 1),
  R('Color Transformer', 'AxisColor', 1), R('Axis', 'Z', 1), R('Points', String(NPTS.toLocaleString('en-US')), 1),
  R('Path', '', 0, {arr: '▾', cb: true, ic: '#19c000'}),
  R('Topic', '/flyhead/brain/path', 1), R('Color', '<span class="sw" style="background:#19ff00"></span>25; 255; 0', 1),
  R('Path', '', 0, {arr: '▸', cb: !!N.length, ic: '#19c000'}),
  R('MarkerArray', '', 0, {arr: '▾', cb: true, ic: '#d2a04a'}),
  R('Topic', '/flyhead/sim/objects', 1), R('Namespaces', REFLEX ? 'person; goal' : HAS_OBJ ? (kind === 'person' ? 'person' : 'looming_object') : '—', 1),
  R('OverlayText', '', 0, {arr: '▸', cb: true, ic: '#6a6ad2'}),
  R('Plotter2D', '', 0, {arr: '▸', cb: !REFLEX, ic: '#6a6ad2'}),
].join('');
$('vtree').innerHTML = [
  row('Type', 'Orbit (rviz)', 0, {alt: true}),
  row('Current View', 'Orbit (rviz)', 0, {arr: '▾'}),
  row('Near Clip Distance', '0.01', 1, {alt: true}), row('Invert Z Axis', '<span class="cb"></span>', 1),
  row('Target Frame', '&lt;Fixed Frame&gt;', 1, {alt: true}),
  row('Distance', '', 1, {vid: 'vDist'}), row('Focal Shape Size', '0.05', 1, {alt: true}), row('Focal Shape Fixed Size', '<span class="cb">✓</span>', 1),
  row('Yaw', '', 1, {vid: 'vYaw', alt: true}), row('Pitch', '', 1, {vid: 'vPitch'}), row('Focal Point', '', 1, {vid: 'vFocal', alt: true}),
  row('Saved', '', 0, {arr: '▸'}),
].join('');

// ---------------------------------------------------------------- one frame
window.NFRAMES = NFRAMES; window.FPS = FPS;
window.setFrame = f => {
  f = Math.max(0, Math.min(NFRAMES - 1, f));
  const t = T0 + f / FPS * SPEED, s = sample(B, t, distB), r = B[s.i];
  RB.root.position.set(s.x, 0, -s.y); RB.root.rotation.y = s.yaw; RB.wheels.forEach(w => { w.rotation.z = -s.d / WHEEL_R; });
  let n = null;
  if (RN) { n = sample(N, t, distN); RN.root.position.set(n.x, 0, -n.y); RN.root.rotation.y = n.yaw; RN.wheels.forEach(w => { w.rotation.z = -n.d / WHEEL_R; }); }
  const ob = OBJ[s.i] || [], ob2 = OBJ[Math.min(OBJ.length - 1, s.i + 1)] || ob;
  objs.forEach((o, k) => {
    if (!ob[k]) { o.visible = false; return; }
    o.visible = true; o.position.set(ob[k][0] + ((ob2[k] || ob[k])[0] - ob[k][0]) * s.a, 0, -(ob[k][1] + ((ob2[k] || ob[k])[1] - ob[k][1]) * s.a));
  });
  pathB.geometry.setDrawRange(0, s.i + 1); if (pathN) pathN.geometry.setDrawRange(0, Math.min(N.length, s.i + 1));
  const c = camPath[f];
  cam.position.set(c.focal.x + Math.cos(c.yaw) * Math.cos(c.pitch) * c.dist, Math.sin(c.pitch) * c.dist, c.focal.z - Math.sin(c.yaw) * Math.cos(c.pitch) * c.dist);
  cam.lookAt(c.focal); cam.updateMatrixWorld();
  renderer.render(S, cam);
  // labels (TF frame names, TEXT_VIEW_FACING markers)
  place(lblMap, new THREE.Vector3(0, 0.15, 0), 'map');
  place(lblBase, new THREE.Vector3(s.x, 0.62, -s.y), 'base_link');
  if (lblBlind) place(lblBlind, new THREE.Vector3(n.x, 0.62, -n.y), ARM2 + '/base_link');
  place(lblState, new THREE.Vector3(s.x, 0.86, -s.y), (r[4] || '').toLowerCase());
  objs.forEach((o, k) => { if (o.visible) place(lblObj[k], new THREE.Vector3(o.position.x, objH + 0.18, o.position.z), REFLEX ? (k ? 'person (planner arm)' : 'person (sim)') : kind === 'person' ? 'person (sim)' : 'looming object (sim)'); else lblObj[k].style.display = 'none'; });
  // OverlayText
  const rd = Object.entries(r[15] || {}).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([k, v]) => `${k} ${v.toFixed(0)}`).join('  ') || '—';
  const ex = (scene.extra || [])[s.i];
  $('ovlText').textContent = REFLEX ?
    `FlyHead · closed-loop SIMULATION (not a robot run)  ${SPEED}x playback\n` +
    `stage 6    SLAM planner + fly-brain reflexes, same seed and person\n` +
    `solid      reflex arm: brain takes over on FREEZE / ESCAPE\n` +
    `ghost      planner arm: brain in shadow, never acts\n` +
    `state      ${r[4]}\n` +
    `command    ${ex[0]} (nav: ${ex[1]})\n` +
    `takeovers  ${ex[2]}   person ${ex[3] == null ? '-' : ex[3].toFixed(2) + ' m'}\n` +
    `cmd_vel    v ${(+r[5]).toFixed(2)} m/s   w ${(+r[6]).toFixed(2)} rad/s\n` +
    `wall       ${(+r[7]).toFixed(2)} m` :
    `FlyHead · closed-loop SIMULATION (not a robot run)${SPEED !== 1 ? `  ${SPEED}x playback` : ''}\n` +
    `scenario   ${scene.scenario}\n` +
    `brain      FlyWire v783, 138,639 LIF neurons, decoder v${scene.decoder}\n` +
    `state      ${r[4]}\n` +
    `loom L/R   ${(+r[8]).toFixed(2)} / ${(+r[9]).toFixed(2)} rad/s   LC9 ${(+r[10]).toFixed(0)} / ${(+r[11]).toFixed(0)} Hz\n` +
    `GF ${(+r[12]).toFixed(0)}  MDN ${(+r[13]).toFixed(0)}  P9 ${(+r[14]).toFixed(0)} Hz\n` +
    `DN         ${rd}\n` +
    `cmd_vel    v ${(+r[5]).toFixed(2)} m/s   w ${(+r[6]).toFixed(2)} rad/s\n` +
    `clearance  ${(+r[7]).toFixed(2)} m`;
  if (REFLEX) $('ovlPlot').style.display = 'none'; else drawPlot(s.i);
  // docks and time panel
  $('vDist').textContent = c.dist.toFixed(2);
  $('vYaw').textContent = (((c.yaw % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI)).toFixed(4);
  $('vPitch').textContent = c.pitch.toFixed(4);
  $('vFocal').textContent = `${c.focal.x.toFixed(2)}; ${(-c.focal.z).toFixed(2)}; 0`;
  const el = (t - T0).toFixed(2);
  // use_sim_time: ROS time is the simulation clock; this offline render plays it back in real time
  $('rosT').value = el; $('rosE').value = el; $('wallT').value = el; $('wallE').value = el;
  return f;
};
window.setFrame(0);
window.READY = true;
