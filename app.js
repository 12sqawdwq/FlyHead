/* 刑天展示页：滚动驱动的爆炸视图。无构建步骤，file:// 可直接打开。 */
(function () {
  'use strict';
  var T = window.THREE, D = window.XT_DATA;
  var $ = function (s) { return document.querySelector(s); };
  var $$ = function (s) { return Array.prototype.slice.call(document.querySelectorAll(s)); };
  var LANG = 'en';
  try { LANG = (/[?&]lang=(en|zh)/.exec(location.search) || [])[1] || localStorage.getItem('xt_lang') || 'en'; } catch (e) {}
  if (LANG !== 'zh') LANG = 'en';
  function Z(en, zh) { return LANG === 'zh' ? zh : en; }
  if (LANG === 'zh') {
    document.documentElement.lang = 'zh-CN';
    document.title = '刑天：果蝇全脑连接组驱动的轮腿机器人';
    $$('[data-zh]').forEach(function (el) { el.innerHTML = el.dataset.zh; });
    $('#langBtn').textContent = 'EN'; $('#langBtn').lang = 'en';
  }
  $('#langBtn').addEventListener('click', function () {
    try { localStorage.setItem('xt_lang', LANG === 'zh' ? 'en' : 'zh'); } catch (e) {}
    if (/[?&]lang=/.test(location.search)) location.search = 'lang=' + (LANG === 'zh' ? 'en' : 'zh'); else location.reload();
  });
  var reduceMq = matchMedia('(prefers-reduced-motion: reduce)');
  var COLORS = { LC4: 0xE8583A, LPLC2: 0x9468DB, LC9: 0x169A87, DN: 0xF4F1E8 };

  var clamp = function (x, a, b) { return Math.min(b === undefined ? 1 : b, Math.max(a === undefined ? 0 : a, x)); };
  var smooth = function (x) { x = clamp(x); return x * x * (3 - 2 * x); };
  var range = function (x, a, b) { return smooth((x - a) / (b - a)); };
  var lerp = function (a, b, t) { return a + (b - a) * t; };
  function bytes(b64) {
    var s = atob(b64), u = new Uint8Array(s.length);
    for (var i = 0; i < s.length; i++) u[i] = s.charCodeAt(i);
    return u;
  }
  var int16 = function (b) { return new Int16Array(bytes(b).buffer); };

  var canvas = $('#stage'), renderer;
  try {
    renderer = new T.WebGLRenderer({ canvas: canvas, antialias: true, powerPreference: 'high-performance' });
  } catch (e) {
    $('#nogl').hidden = false; canvas.style.display = 'none'; return;
  }
  renderer.outputColorSpace = T.SRGBColorSpace;
  renderer.toneMapping = T.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = T.PCFSoftShadowMap;

  var scene = new T.Scene();
  var camera = new T.PerspectiveCamera(26, 1, 0.05, 220);

  var stageFloor = [];
  /* ---------- 背景与布光 ---------- */
  (function () {
    var c = document.createElement('canvas'); c.width = c.height = 512;
    var g = c.getContext('2d');
    var r = g.createRadialGradient(290, 300, 20, 256, 256, 400);
    r.addColorStop(0, '#141518'); r.addColorStop(.5, '#08090a'); r.addColorStop(1, '#000000');
    g.fillStyle = r; g.fillRect(0, 0, 512, 512);
    var t = new T.CanvasTexture(c); t.colorSpace = T.SRGBColorSpace;
    scene.background = t;
    scene.backgroundIntensity = 1;

    var env = new T.Scene();
    env.background = new T.Color(0x1d1e21);
    function panel(col, w, h, p) {
      var m = new T.Mesh(new T.PlaneGeometry(w, h), new T.MeshBasicMaterial({ color: col, side: T.DoubleSide }));
      m.position.set(p[0], p[1], p[2]); m.lookAt(0, 0, 0); env.add(m);
    }
    panel(new T.Color(13, 12.4, 11.6), 8, 4, [-2, 6, 3]);
    panel(new T.Color(3, 2.95, 2.9), 5, 5, [1, 2, 7]);
    panel(new T.Color(22, 21, 20), .5, 8, [4.2, 3, 4.6]);
    panel(new T.Color(16, 18, 21), .4, 8, [-5, 2, -3.4]);
    panel(new T.Color(18, 11, 8), 6, .3, [0, -1, 6.5]);
    panel(new T.Color(4.4, 4.8, 5.4), 2.4, 7, [7, 1, 2]);
    panel(new T.Color(3.6, 3.3, 3.1), 2.4, 6, [-7, 1, -2]);
    panel(new T.Color(1.4, 1.4, 1.5), 8, 2, [0, 2, -7]);
    panel(new T.Color(.5, .5, .5), 10, 10, [0, -6, 0]);
    var pm = new T.PMREMGenerator(renderer);
    scene.environment = pm.fromScene(env, 0.035).texture;
    pm.dispose();

    var key = new T.DirectionalLight(0xfff4e8, 2.1);
    key.position.set(-1.6, 3.4, 1.8); key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    var sc = key.shadow.camera; sc.left = -1.6; sc.right = 1.6; sc.top = 1.6; sc.bottom = -1.6; sc.near = .5; sc.far = 8;
    key.shadow.radius = 7; key.shadow.bias = -0.0006; key.shadow.normalBias = 0.004;
    scene.add(key);
    var rim = new T.DirectionalLight(0xa9c4e8, 1.1); rim.position.set(2.4, 1.2, -2.6); scene.add(rim);

    // 地面：光池 + 影子 + 0.35 m 车体圆环（真实比例）
    var fc = document.createElement('canvas'); fc.width = fc.height = 512;
    var fg = fc.getContext('2d');
    var fr = fg.createRadialGradient(256, 256, 8, 256, 256, 256);
    fr.addColorStop(0, 'rgba(30,31,34,.86)'); fr.addColorStop(.5, 'rgba(16,17,19,.88)'); fr.addColorStop(1, 'rgba(0,0,0,0)');
    fg.fillStyle = fr; fg.fillRect(0, 0, 512, 512);
    var ft = new T.CanvasTexture(fc); ft.colorSpace = T.SRGBColorSpace;
    var pool = new T.Mesh(new T.CircleGeometry(2.6, 64), new T.MeshBasicMaterial({ map: ft, transparent: true, depthWrite: false, toneMapped: false }));
    pool.rotation.x = -Math.PI / 2; pool.position.y = -.002; scene.add(pool);
    var shadow = new T.Mesh(new T.CircleGeometry(2.6, 64), new T.ShadowMaterial({ opacity: .62 }));
    shadow.rotation.x = -Math.PI / 2; shadow.receiveShadow = true; scene.add(shadow);
    stageFloor = [pool, shadow];
  })();

  /* ---------- 机器人：厂商网格 + 展示细节层 + 示意件 ---------- */
  var HIP = .379, KNEE = .239, WHEELY = .099, LINK = .14;
  function meshGeo(name) {
    var r = D.robot[name], g = new T.BufferGeometry();
    var p = int16(r.pos), P = new Float32Array(p.length);
    for (var i = 0; i < p.length; i++) P[i] = p[i] / r.q;
    g.setAttribute('position', new T.BufferAttribute(P, 3));
    g.setAttribute('normal', new T.BufferAttribute(new Int8Array(bytes(r.nor).buffer), 3, true));
    g.setIndex(new T.BufferAttribute(new Uint16Array(bytes(r.idx).buffer), 1));
    return g;
  }
  var MATS = {
    ti: { color: 0x7d8188, metalness: .9, roughness: .36 },
    steel: { color: 0xb9bcc0, metalness: 1, roughness: .27 },
    gun: { color: 0x3a3d42, metalness: .95, roughness: .34 },
    carbon: { color: 0x131417, metalness: .55, roughness: .42 },
    black: { color: 0x08090a, metalness: .3, roughness: .55 },
    rubber: { color: 0x101113, metalness: 0, roughness: .78 },
    pcb: { color: 0x0f1f1b, metalness: .25, roughness: .5 },
    glass: { color: 0x050607, metalness: 1, roughness: .07 },
    accent: { color: 0xE8583A, metalness: .3, roughness: .4, emissive: 0xE8583A, emissiveIntensity: .85 },
    light: { color: 0xf4efe4, metalness: 0, roughness: .4, emissive: 0xfff3df, emissiveIntensity: 1.5 }
  };
  var robot = new T.Group(); scene.add(robot);
  var parts = {};
  function addPart(id, opts) {
    var outer = new T.Group(), inner = new T.Group();
    inner.matrixAutoUpdate = false;
    outer.add(inner); robot.add(outer);
    var sg = opts.side || 0, holder = new T.Group();
    if (sg < 0) holder.scale.x = -1; // 细节层统一按 +X 一侧建模，另一侧镜像
    inner.add(holder);
    var p = {
      id: id, outer: outer, inner: inner, holder: holder, off: opts.off, delay: opts.delay || 0, side: sg, mats: [], cache: {},
      anchor: new T.Vector3().fromArray(opts.anchor || [0, 0, 0]), label: opts.label, chain: opts.chain || 'body', dim: 0, edges: []
    };
    parts[id] = p; return p;
  }
  function pm(p, key) { // 每个部件独立材质，便于聚焦压暗
    if (!p.cache[key]) {
      var m = new T.MeshStandardMaterial(MATS[key]);
      p.cache[key] = m;
      p.mats.push({ m: m, c: m.color.clone(), e: m.emissiveIntensity });
    }
    return p.cache[key];
  }
  function add(p, geo, key, x, y, z, parent) {
    var m = new T.Mesh(geo, pm(p, key));
    m.position.set(x || 0, y || 0, z || 0); m.castShadow = key !== 'light' && key !== 'accent';
    (parent || p.holder).add(m); return m;
  }
  function inst(p, geo, key, list) {
    var m = new T.InstancedMesh(geo, pm(p, key), list.length);
    list.forEach(function (o, i) { m.setMatrixAt(i, o); });
    m.castShadow = true; p.holder.add(m); return m;
  }
  function cylX(r, h, seg) { var g = new T.CylinderGeometry(r, r, h, seg || 32); g.rotateZ(Math.PI / 2); return g; }
  function latheX(pr, seg) { // [[半径, x], ...]，绕 X 轴
    var g = new T.LatheGeometry(pr.map(function (a) { return new T.Vector2(a[0], a[1]); }), seg || 64);
    g.rotateZ(-Math.PI / 2); return g;
  }
  function torusX(R, r) { var g = new T.TorusGeometry(R, r, 8, 80); g.rotateY(Math.PI / 2); return g; }
  var mx = function () { return new T.Matrix4(); };
  function boltRing(p, x, cy, cz, R, n, s, key, phase) {
    var list = [], g = cylX(s || .0032, (s || .0032) * .75, 6);
    for (var i = 0; i < n; i++) {
      var a = (i + (phase || 0)) / n * Math.PI * 2;
      list.push(mx().makeTranslation(x, cy + Math.cos(a) * R, cz + Math.sin(a) * R));
    }
    return inst(p, g, key || 'steel', list);
  }
  function capsuleShape(l, w) {
    var s = new T.Shape(), r = w / 2;
    s.moveTo(-l / 2 + r, -r); s.lineTo(l / 2 - r, -r); s.absarc(l / 2 - r, 0, r, -Math.PI / 2, Math.PI / 2, false);
    s.lineTo(-l / 2 + r, r); s.absarc(-l / 2 + r, 0, r, Math.PI / 2, Math.PI * 1.5, false);
    return s;
  }
  function slotPlate(l, w, d) { // 沿 Y 的长圆形薄板，法向 +X
    var g = new T.ExtrudeGeometry(capsuleShape(l, w), { depth: d, bevelEnabled: true, bevelSize: .0006, bevelThickness: .0006, bevelSegments: 2, curveSegments: 10 });
    g.rotateZ(Math.PI / 2); g.rotateY(Math.PI / 2); return g;
  }
  function tube(points, r) { return new T.TubeGeometry(new T.CatmullRomCurve3(points.map(function (a) { return new T.Vector3(a[0], a[1], a[2]); })), 36, r, 8); }
  function box(w, h, d) { return new T.BoxGeometry(w, h, d); }

  // 底盘：厂商外壳，加前脸、格栅与后部接口（后者为展示细节）
  var base = addPart('base', { off: [0, .3, 0], delay: 0, anchor: [0, .5, .1] });
  add(base, meshGeo('base_link'), 'ti', 0, 0, 0, base.inner);
  (function () {
    add(base, box(.15, .05, .003), 'glass', 0, .365, .2098);
    add(base, box(.152, .0018, .0034), 'steel', 0, .3908, .2098);
    add(base, box(.152, .0018, .0034), 'steel', 0, .3392, .2098);
    [-1, 1].forEach(function (s) { add(base, box(.03, .0028, .001), 'light', s * .06, .365, .2118); });
    var list = [], tilt = -Math.atan2(66, 77) + Math.PI / 2 - Math.PI / 2;
    for (var i = 0; i < 8; i++) {
      var u = .12 + i * .1, z = lerp(.143, .209, u), y = lerp(.474, .397, u);
      list.push(mx().compose(new T.Vector3(0, y + .001, z + .001), new T.Quaternion().setFromAxisAngle(new T.Vector3(1, 0, 0), tilt), new T.Vector3(1, 1, 1)));
    }
    inst(base, box(.12, .0024, .0052), 'black', list);
    add(base, box(.11, .08, .0026), 'carbon', 0, .375, -.1605);
    [[-.034, .39], [0, .39], [.034, .39]].forEach(function (a) {
      add(base, new T.CylinderGeometry(.0078, .0078, .007, 24).rotateX(Math.PI / 2), 'steel', a[0], a[1], -.1632);
      add(base, new T.CylinderGeometry(.0046, .0046, .0075, 20).rotateX(Math.PI / 2), 'black', a[0], a[1], -.1636);
    });
    add(base, box(.07, .0032, .0012), 'accent', 0, .36, -.1622);
    [[-.05, .347], [.05, .347], [-.05, .403], [.05, .403]].forEach(function (a) { add(base, new T.CylinderGeometry(.0028, .0028, .002, 6).rotateX(Math.PI / 2), 'steel', a[0], a[1], -.1622); });
    add(base, box(.13, .004, .2), 'carbon', 0, .2585, .015);
    add(base, tube([[-.05, .49, -.104], [-.05, .528, -.09], [-.02, .54, -.076], [.02, .54, -.076], [.05, .528, -.09], [.05, .49, -.104]], .0045), 'carbon');
  })();
  // 顶部导轨（独立拆下）
  var deck = addPart('deck', { off: [0, .42, -.03], delay: .02, anchor: [.045, .512, .02] });
  (function () {
    [-1, 1].forEach(function (s) {
      add(deck, box(.012, .007, .13), 'gun', s * .045, .5065, -.012);
      var list = [];
      for (var i = 0; i < 5; i++) list.push(mx().makeTranslation(s * .045, .5105, -.06 + i * .024));
      inst(deck, new T.CylinderGeometry(.0028, .0028, .002, 6), 'steel', list);
    });
    add(deck, box(.102, .0035, .012), 'gun', 0, .5055, -.05);
    add(deck, box(.102, .0035, .012), 'gun', 0, .5055, .04);
  })();

  [[1, 'L'], [-1, 'R']].forEach(function (s) {
    var sg = s[0], k = s[1], lab = sg > 0;
    var motor = addPart('motor' + k, { off: [sg * .13, .08, 0], delay: .1, side: sg, anchor: [.15, HIP + .05, 0] });
    add(motor, meshGeo(sg > 0 ? 'motor_left_link_1' : 'motor_right_link_1'), 'steel', 0, 0, 0, motor.inner);
    add(motor, cylX(.076, .0012, 72), 'gun', .1724, HIP, 0);
    boltRing(motor, .1735, HIP, 0, .064, 14, .0032);
    add(motor, torusX(.0725, .0011), 'accent', .1732, HIP, 0);

    var fin = addPart('fin' + k, { off: [sg * .21, .08, 0], delay: .14, side: sg, anchor: [.135, HIP + .08, 0] });
    add(fin, cylX(.0785, .036, 64), 'black', .133, HIP, 0);
    (function () {
      var list = [], g = box(.032, .0135, .0021);
      for (var i = 0; i < 54; i++) {
        var a = i / 54 * Math.PI * 2;
        list.push(mx().compose(new T.Vector3(.133, HIP + Math.cos(a) * .0845, Math.sin(a) * .0845), new T.Quaternion().setFromAxisAngle(new T.Vector3(1, 0, 0), a), new T.Vector3(1, 1, 1)));
      }
      inst(fin, g, 'gun', list);
    })();

    var up = addPart('upper' + k, { off: [sg * .285, .03, -.05], delay: .2, side: sg, chain: 'upper', anchor: [.19, HIP - .07, 0] });
    add(up, meshGeo(sg > 0 ? 'leg_left_link_1' : 'leg_right_link_1'), 'steel', 0, 0, 0, up.inner);
    add(up, slotPlate(.075, .019, .0009), 'black', .1875, (HIP + KNEE) / 2 + .002, 0);
    add(up, latheX([[0, .0035], [.012, .0035], [.0145, .0028], [.024, .0022], [.0285, .001], [.0285, 0]], 48), 'gun', .1878, HIP, 0);
    boltRing(up, .1913, HIP, 0, .0205, 8, .0024);
    add(up, cylX(.0062, .0014, 24), 'accent', .1916, HIP, 0);
    add(up, latheX([[0, .002], [.008, .002], [.0135, .001], [.0135, 0]], 32), 'gun', .1878, KNEE, 0);
    boltRing(up, .1898, KNEE, 0, .0104, 5, .0016);
    add(up, tube([[.185, HIP - .02, -.034], [.186, HIP - .06, -.031], [.186, HIP - .1, -.022], [.185, KNEE + .012, -.015]], .0026), 'rubber');
    add(up, box(.008, .004, .009), 'accent', .1855, .335, -.029);
    add(up, box(.008, .004, .009), 'gun', .1855, .29, -.024);

    var low = addPart('lower' + k, { off: [sg * .36, .02, .05], delay: .26, side: sg, chain: 'lower', anchor: [.216, KNEE - .03, 0] });
    add(low, meshGeo(sg > 0 ? 'leg2_left_link_1' : 'leg2_right_link_1'), 'steel', 0, 0, 0, low.inner);
    add(low, slotPlate(.052, .015, .0009), 'black', .2148, KNEE - .042, 0);
    add(low, latheX([[0, .0025], [.0075, .0025], [.0135, .0012], [.0135, 0]], 32), 'gun', .2152, KNEE, 0);
    boltRing(low, .2176, KNEE, 0, .0102, 5, .0016);
    add(low, tube([[.1865, KNEE - .012, .02], [.186, KNEE - .05, .026], [.186, KNEE - .09, .024], [.186, WHEELY + .03, .018]], .0026), 'rubber');
    add(low, box(.006, .004, .009), 'accent', .1858, KNEE - .05, .025);

    // 车轮：外形尺寸按厂商网格（半径 94 mm、宽 52 mm），胎面、辐条等为展示细节
    var W0 = .241;
    var rim = addPart('rim' + k, { off: [sg * .44, 0, 0], delay: .32, side: sg, chain: 'lower', anchor: [W0 + .024, WHEELY + .03, 0] });
    add(rim, latheX([[.053, -.023], [.0655, -.024], [.0655, .024], [.057, .024], [.0535, .017], [.051, -.006], [.051, -.018], [.053, -.023]], 72), 'ti', W0, WHEELY, 0);
    add(rim, cylX(.051, .02, 64), 'gun', W0 - .012, WHEELY, 0);
    add(rim, latheX([[0, .0275], [.0105, .0275], [.0135, .0235], [.0245, .0205], [.0265, .012], [.0265, -.002], [0, -.002]], 48), 'gun', W0, WHEELY, 0);
    (function () {
      var sh = new T.Shape(); sh.moveTo(-.0058, 0); sh.lineTo(.0058, 0); sh.lineTo(.0028, .034); sh.lineTo(-.0028, .034); sh.closePath();
      var g = new T.ExtrudeGeometry(sh, { depth: .0058, bevelEnabled: true, bevelSize: .0007, bevelThickness: .0007, bevelSegments: 2 });
      g.rotateY(Math.PI / 2);
      var list = [];
      for (var i = 0; i < 7; i++) {
        list.push(mx().makeTranslation(W0 + .0125, WHEELY, 0).multiply(mx().makeRotationX(i / 7 * Math.PI * 2)).multiply(mx().makeTranslation(0, .0235, 0)));
      }
      inst(rim, g, 'ti', list);
    })();
    boltRing(rim, W0 + .0282, WHEELY, 0, .0168, 7, .0021);
    add(rim, cylX(.0058, .0016, 24), 'accent', W0 + .0282, WHEELY, 0);
    add(rim, torusX(.0595, .0009), 'accent', W0 + .0226, WHEELY, 0);

    var tire = addPart('tire' + k, { off: [sg * .53, 0, 0], delay: .38, side: sg, chain: 'lower', anchor: [W0 + .024, WHEELY + .08, 0] });
    add(tire, latheX([[.0655, -.0255], [.08, -.0262], [.0875, -.0245], [.0925, -.019], [.094, -.0095], [.094, .0095], [.0925, .019], [.0875, .0245], [.08, .0262], [.0655, .0255], [.0655, -.0255]], 96), 'rubber', W0, WHEELY, 0);
    (function () {
      var g = box(.0118, .0026, .0078), list = [], n = 62;
      for (var row = -1; row <= 1; row += 2) {
        for (var i = 0; i < n; i++) {
          var a = (i + (row > 0 ? .5 : 0)) / n * Math.PI * 2;
          list.push(mx().makeTranslation(W0 + row * .0102, WHEELY, 0).multiply(mx().makeRotationX(a)).multiply(mx().makeTranslation(0, .0938, 0)).multiply(mx().makeRotationY(row * .55)));
        }
      }
      inst(tire, g, 'rubber', list);
      add(tire, torusX(.0835, .0005), 'gun', W0 + .0252, WHEELY, 0);
    })();

    // 侧板：沿厂商外壳轮廓内缩，髋部开孔
    var panel = addPart('panel' + k, { off: [sg * .07, .3, 0], delay: .03, side: sg, anchor: [.09, .455, -.06] });
    (function () {
      var o = [[-.145, .345], [-.131, .452], [-.098, .477], [-.06, .489], [0, .494], [.06, .49], [.1, .48], [.135, .463], [.193, .392], [.193, .34], [.13, .303], [-.1, .3], [-.13, .316]];
      var sh = new T.Shape();
      o.forEach(function (a, i) { var X = -a[0], Y = a[1]; if (i) sh.lineTo(X, Y); else sh.moveTo(X, Y); });
      sh.closePath();
      var hole = new T.Path(); hole.absarc(0, HIP, .073, 0, Math.PI * 2, true); sh.holes.push(hole);
      var g = new T.ExtrudeGeometry(sh, { depth: .0018, bevelEnabled: true, bevelSize: .0012, bevelThickness: .0008, bevelSegments: 2, curveSegments: 48 });
      g.rotateY(Math.PI / 2);
      add(panel, g, 'carbon', .0885, 0, 0);
      add(panel, new T.TorusGeometry(.0745, .0014, 8, 72).rotateY(Math.PI / 2), 'steel', .0905, HIP, 0);
      var slats = [];
      for (var i = 0; i < 6; i++) slats.push(mx().makeTranslation(.0909, .41, -.128 + i * .0098));
      inst(panel, box(.0012, .056, .0048), 'black', slats);
      var screws = [];
      o.forEach(function (a, ix) { if (ix % 2 === 0) screws.push(mx().makeTranslation(.0912, a[1] + (a[1] > HIP ? -.008 : .008), a[0] * .95)); });
      inst(panel, cylX(.0024, .0014, 6), 'steel', screws);
      add(panel, box(.0009, .0024, .11), 'accent', .0913, .4655, .092).rotation.x = -.42;
    })();
  });

  // 示意件：实物位置未测绘，只作说明
  function outline(p, geo, m) {
    var mat = new T.LineBasicMaterial({ color: 0xe9e5da, transparent: true, opacity: .34 });
    var e = new T.LineSegments(new T.EdgesGeometry(geo, 30), mat);
    e.position.copy(m.position); p.holder.add(e); p.edges.push(mat);
  }
  function sAdd(p, geo, key, x, y, z, noEdge) { var m = add(p, geo, key, x, y, z); if (!noEdge) outline(p, geo, m); return m; }
  var LIDAR_Y = .49, LIDAR_Z = .11; // 0.11 m：slam/docs/navigation.md，转向点在 LiDAR 后方
  function lat(pr, seg) { return new T.LatheGeometry(pr.map(function (a) { return new T.Vector2(a[0], a[1]); }), seg || 48); }
  var lidar = addPart('lidar', { off: [0, .55, .05], delay: .04, anchor: [0, LIDAR_Y + .06, LIDAR_Z] });
  sAdd(lidar, box(.09, .006, .09), 'gun', 0, LIDAR_Y + .003, LIDAR_Z);
  sAdd(lidar, lat([[0, 0], [.038, 0], [.039, .004], [.039, .022], [.036, .025], [0, .025]]), 'ti', 0, LIDAR_Y + .006, LIDAR_Z);
  var lidarHead = new T.Group(); lidarHead.position.set(0, LIDAR_Y + .031, LIDAR_Z); lidar.holder.add(lidarHead);
  add(lidar, lat([[.0352, 0], [.033, .022], [.031, .03], [0, .03]]), 'glass', 0, 0, 0, lidarHead);
  add(lidar, lat([[0, .004], [.027, .004], [.031, 0], [0, 0]]), 'gun', 0, .03, 0, lidarHead);
  add(lidar, box(.012, .017, .004), 'light', 0, .012, .0335, lidarHead);
  add(lidar, box(.004, .004, .014), 'gun', .021, .032, 0, lidarHead);
  add(lidar, new T.TorusGeometry(.0393, .0009, 8, 72).rotateX(Math.PI / 2), 'accent', 0, LIDAR_Y + .0265, LIDAR_Z);
  [[.034, .034], [-.034, .034], [.034, -.034], [-.034, -.034]].forEach(function (a) { add(lidar, new T.CylinderGeometry(.0028, .0028, .002, 6), 'steel', a[0], LIDAR_Y + .0065, LIDAR_Z + a[1]); });

  var compute = addPart('compute', { off: [0, .48, .28], delay: .02, anchor: [.06, .425, .03] });
  sAdd(compute, box(.15, .003, .105), 'pcb', 0, .405, .03);
  (function () {
    var list = [];
    for (var i = 0; i < 11; i++) list.push(mx().makeTranslation(-.046 + i * .0092, .421, .017));
    inst(compute, box(.0028, .022, .058), 'gun', list);
    sAdd(compute, box(.098, .005, .062), 'gun', 0, .4085, .017);
    [[.052, .058, .02, .006, .016], [-.054, .06, .016, .008, .014], [.058, .02, .018, .01, .02], [.03, .066, .05, .012, .012]].forEach(function (c) {
      add(compute, box(c[2], c[3], c[4]), 'black', c[0], .4065 + c[3] / 2, c[1]);
    });
    add(compute, box(.014, .0015, .014), 'accent', -.03, .4074, .068);
  })();

  var radio = addPart('radio', { off: [-.1, .52, -.12], delay: .05, anchor: [.012, .57, -.03] });
  sAdd(radio, box(.05, .009, .05), 'gun', 0, .5, -.03);
  [-1, 1].forEach(function (s) {
    add(radio, lat([[0, 0], [.0052, 0], [.0052, .012], [.0036, .014], [.003, .085], [.0018, .092], [0, .092]], 16), 'black', s * .014, .504, -.03);
    add(radio, new T.CylinderGeometry(.0034, .0034, .002, 16), 'accent', s * .014, .519, -.03);
  });

  var battery = addPart('battery', { off: [0, -.08, -.32], delay: .06, anchor: [.066, .34, -.04] });
  sAdd(battery, box(.132, .06, .2), 'carbon', 0, .32, -.02);
  (function () {
    var list = [];
    for (var i = 0; i < 2; i++) list.push(mx().makeTranslation(0, .32, -.075 + i * .11));
    inst(battery, box(.1345, .0625, .012), 'gun', list);
    var cells = [];
    for (var ix = 0; ix < 6; ix++) for (var iz = 0; iz < 3; iz++) cells.push(mx().makeTranslation(-.05 + ix * .02, .351, -.04 + iz * .04));
    inst(battery, new T.CylinderGeometry(.0072, .0072, .0018, 18), 'steel', cells);
    add(battery, box(.03, .012, .008), 'accent', 0, .33, .083);
  })();

  var camBody = addPart('camera', { off: [.14, .28, .34], delay: .03, anchor: [.045, .365, .225] });
  sAdd(camBody, box(.095, .026, .022), 'gun', 0, .365, .222);
  [-.03, 0, .03].forEach(function (x, i) {
    add(camBody, new T.CylinderGeometry(.0088, .0088, .003, 24).rotateX(Math.PI / 2), 'steel', x, .365, .2335);
    add(camBody, new T.CylinderGeometry(.0064, .0064, .0034, 24).rotateX(Math.PI / 2), i === 1 ? 'black' : 'glass', x, .365, .2338);
  });

var A = new T.Matrix4(), B = new T.Matrix4(), C = new T.Matrix4();
  function aboutX(y0, angle, out) {
    A.makeTranslation(0, y0, 0); B.makeRotationX(angle); C.makeTranslation(0, -y0, 0);
    return out.copy(A).multiply(B).multiply(C);
  }
  var mUpper = new T.Matrix4(), mLower = new T.Matrix4(), mKnee = new T.Matrix4();
  var mBody = new T.Matrix4(), mTmp = new T.Matrix4(), mTmp2 = new T.Matrix4(), mSide = new T.Matrix4();
  var eulerBody = new T.Euler(), HALF_TRACK = .241;
  // 动效状态：示意的轮腿动力学。驱动它的 v、w 来自轨迹或记录，响应曲线是展示用的
  var PH = { pitch: 0, pitchV: 0, roll: 0, rollV: 0, bob: 0, bobV: 0, leg: 0, spinL: 0, spinR: 0, vf: 0, wf: 0, dist: 0, sway: 0 };
  var physCmdV = 0, physCmdW = 0;
  function stepPhysics(dt, now, k) {
    var prevV = PH.vf, dtc = Math.max(dt, .004);
    PH.vf += (physCmdV - PH.vf) * (1 - Math.exp(-dt * 3.6));
    PH.wf += (physCmdW - PH.wf) * (1 - Math.exp(-dt * 4.2));
    var acc = (PH.vf - prevV) / dtc, avf = Math.abs(PH.vf), awf = Math.abs(PH.wf);
    PH.dist += avf * dt;
    // 自平衡：静止时也有细微的前后晃动，车轮跟着来回补偿
    var t = now * .001, swayPos = (Math.sin(t * 1.7) * .0052 + Math.sin(t * .67 + 1) * .0034) * k, dSway = swayPos - PH.sway; PH.sway = swayPos;
    var pitchT = clamp(acc * .85 + PH.vf * .62, -.28, .28) + (Math.sin(t * 1.7 + .5) * .011 + Math.sin(t * .67) * .007);
    var rough = Math.sin(PH.dist * 12.3) * .016 * clamp(avf * 6) + Math.sin(PH.dist * 5.1 + 1) * .012 * clamp(avf * 6);
    var bobT = clamp(Math.abs(acc) * .09 + awf * .1 + avf * .16, 0, .17) + rough;
    var rollT = clamp(PH.wf * Math.max(avf, .22) * .75, -.2, .2);
    function spring(key, target, kk, c) { // 半隐式，带一点过冲
      PH[key + 'V'] += (kk * (target - PH[key]) - c * PH[key + 'V']) * dt;
      PH[key] += PH[key + 'V'] * dt;
    }
    spring('pitch', pitchT, 70, 8.5); spring('roll', rollT, 58, 8); spring('bob', bobT, 90, 11);
    PH.leg = PH.pitch * .72;
    PH.spinL += ((PH.vf - PH.wf * HALF_TRACK) * dt + dSway) / .094;
    PH.spinR += ((PH.vf + PH.wf * HALF_TRACK) * dt + dSway) / .094;
  }
  function setPose(a, k) {
    k = k || 0;
    var aL = a + (PH.bob + PH.roll * 1.05) * k, aR = a + (PH.bob - PH.roll * 1.05) * k;
    var dL = 2 * LINK * (1 - Math.cos(aL)), dR = 2 * LINK * (1 - Math.cos(aR));
    var drop = (dL + dR) / 2, rollAng = (dL - dR) / (2 * HALF_TRACK);
    // 机身绕髋轴俯仰、侧倾；腿走自己的连杆，轮子留在地面
    eulerBody.set(PH.pitch * k, 0, -rollAng * 1, 'XYZ');
    mBody.makeTranslation(0, HIP - drop, 0).multiply(mTmp.makeRotationFromEuler(eulerBody)).multiply(mTmp2.makeTranslation(0, -HIP, 0));
    for (var id in parts) {
      var p = parts[id];
      if (p.chain === 'body') { p.inner.matrix.copy(mBody); }
      else {
        var aS = p.side > 0 ? aL : aR, dS = p.side > 0 ? dL : dR;
        mSide.makeTranslation(0, -dS, 0);
        aboutX(HIP, aS + PH.leg * k, mUpper);
        if (p.chain === 'upper') p.inner.matrix.copy(mSide).multiply(mUpper);
        else {
          aboutX(KNEE, -2 * aS, mKnee);
          p.inner.matrix.copy(mSide).multiply(mUpper).multiply(mKnee);
          if (id.indexOf('rim') === 0 || id.indexOf('tire') === 0) {
            var ang = (p.side > 0 ? PH.spinL : PH.spinR) * (k > 0 ? 1 : 0);
            aboutX(WHEELY, ang, mTmp); p.inner.matrix.multiply(mTmp);
          }
        }
      }
      p.inner.matrixWorldNeedsUpdate = true;
    }
  }
  function setExplode(e) {
    for (var id in parts) {
      var p = parts[id];
      var t = smooth((e - p.delay * .5) / (1 - p.delay * .5));
      p.outer.position.set(p.off[0] * t, p.off[1] * t, p.off[2] * t);
    }
  }

  /* ---------- 地面标注与扇区 ---------- */
  var footRing = new T.Mesh(new T.RingGeometry(.345, .35, 96), new T.MeshBasicMaterial({ color: 0xece9e2, transparent: true, opacity: 0, side: T.DoubleSide, depthWrite: false }));
  footRing.rotation.x = -Math.PI / 2; footRing.position.y = .004; scene.add(footRing);
  var turnMark = new T.Mesh(new T.CircleGeometry(.012, 24), new T.MeshBasicMaterial({ color: 0xE8583A, transparent: true, opacity: 0, depthWrite: false }));
  turnMark.rotation.x = -Math.PI / 2; turnMark.position.y = .005; scene.add(turnMark);

  // 场地全景时标出机器人位置（机器人按真实比例，全景下很小）
  var siteMark = new T.Mesh(new T.RingGeometry(.92, 1, 64), new T.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0, side: T.DoubleSide, depthTest: false }));
  siteMark.rotation.x = -Math.PI / 2; siteMark.position.y = .01; siteMark.renderOrder = 4; scene.add(siteMark);
  var SECTORS = 24;
  var wedgeGeo = new T.RingGeometry(.47, .66, 10, 1, (-90 - 6.6) * Math.PI / 180, 13.2 * Math.PI / 180);
  wedgeGeo.rotateX(-Math.PI / 2);
  var wedges = new T.InstancedMesh(wedgeGeo, new T.MeshBasicMaterial({ transparent: true, depthWrite: false, opacity: 1, side: T.DoubleSide, toneMapped: false }), SECTORS);
  wedges.position.y = .006; wedges.renderOrder = 2;
  var dummy = new T.Object3D();
  for (var i = 0; i < SECTORS; i++) {
    dummy.rotation.y = ((i + .5) * 15 - 180) * Math.PI / 180; dummy.updateMatrix(); wedges.setMatrixAt(i, dummy.matrix);
    wedges.setColorAt(i, new T.Color(0));
  }
  scene.add(wedges);
  // 03 章：录制轨迹上的逼近片段。射线终点和扇区由底图几何按 retina.py 的规则算出（非运行记录）
  function makeRun(d) {
    var q = int16(d.ranges_mm), n = d.steps.length, stopT = 0;
    for (var i = 0; i < n; i++) if (d.rec[i][4] && Math.abs(d.rec[i][7]) < .01) { stopT = d.steps[i][3]; break; }
    return { steps: d.steps, rec: d.rec, r: function (k, i) { return q[k * 24 + i] / 1000; }, n: n, dur: d.steps[n - 1][3], stopT: stopT, longest: d.longest_stop_s, path: d.path_m };
  }
  var RUNS = {}, SC_ORDER = ['wall', 'person', 'roam'], SC_SPEED = { wall: 3, person: 2.5, roam: 8 };
  SC_ORDER.forEach(function (k) { RUNS[k] = { brain: makeRun(D.map.drive[k].brain), blind: makeRun(D.map.drive[k].blind) }; });
  var SC_TEXT = {
    wall: { blind: Z('stopped after %p m', '走 %p m 后被拦停'), brain: Z('corrects course and gets past, %p m in all', '修正方向走过去，全程 %p m') },
    person: { blind: Z('stuck in front of the person after %p m', '走 %p m 后卡在人前'), brain: Z('turns and leaves, %p m in all', '转身离开，全程 %p m') },
    roam: { blind: Z('never moves again after %p m', '走 %p m 后再没动'), brain: Z('%p m in all, shorter stops', '全程 %p m，停得更短') }
  };
  var driveScn = 'wall', driveMode = 'brain', DRIVE = RUNS.wall.brain, dbw = 0, stuckS = 0;
  function stepLine(line, steps) {
    var P = new Float32Array(steps.length * 3);
    for (var i = 0; i < steps.length; i++) { P[i * 3] = steps[i][0]; P[i * 3 + 1] = .03; P[i * 3 + 2] = steps[i][1]; }
    line.geometry.dispose();
    line.geometry = new T.BufferGeometry().setAttribute('position', new T.BufferAttribute(P, 3));
    if (line.computeLineDistances && line.material.isLineDashedMaterial) line.computeLineDistances();
  }
  function setDrive(scn, m) {
    driveScn = scn; driveMode = m; DRIVE = RUNS[scn][m]; DRIVE_SPEED = SC_SPEED[scn]; driveT = 0; driveUi = ''; stuckS = 0;
    $$('.dv button').forEach(function (b) { var on = b.dataset.m === m; b.classList.toggle('on', on); b.setAttribute('aria-pressed', on); });
    $$('.dvs button').forEach(function (b) { var on = b.dataset.sc === scn; b.classList.toggle('on', on); b.setAttribute('aria-pressed', on); });
    var l = $('#dStatL');
    if (l) {
      var r = $('#dStatR'), a = RUNS[scn];
      l.classList.toggle('dim', m !== 'blind'); r.classList.toggle('dim', m !== 'brain');
      $('#dStatLv').textContent = a.blind.longest.toFixed(1); $('#dStatRv').textContent = a.brain.longest.toFixed(1);
      $('#dStatLt').textContent = Z('No brain: ', '不带脑：') + SC_TEXT[scn].blind.replace('%p', a.blind.path.toFixed(1));
      $('#dStatRt').textContent = Z('With brain: ', '带脑：') + SC_TEXT[scn].brain.replace('%p', a.brain.path.toFixed(1));
    }
    if (blindLine) {
      stepLine(blindLine, RUNS[scn].blind.steps); stepLine(brainPath, RUNS[scn].brain.steps);
      var bs = RUNS[scn].blind.steps, last = bs[bs.length - 1];
      blindDot.position.set(last[0], .02, last[1]);
    }
  }
  var objWalk = 0;
  var mapShift = new T.Matrix4(), driveTheta = new Float32Array(24), driveUi = '';
  var DRIVE_SPEED = 2.6, DRIVE_HOLD = 1.6, driveT = 0;
  var rayPos = new Float32Array(24 * 6), rayCol = new Float32Array(24 * 6);
  var rayGeo = new T.BufferGeometry();
  rayGeo.setAttribute('position', new T.BufferAttribute(rayPos, 3));
  rayGeo.setAttribute('color', new T.BufferAttribute(rayCol, 3));
  var rays = new T.LineSegments(rayGeo, new T.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: .9, depthWrite: false, toneMapped: false }));
  rays.frustumCulled = false; rays.visible = false; rays.renderOrder = 3; scene.add(rays);
  var hitPos = new Float32Array(24 * 3), hitCol = new Float32Array(24 * 3);
  var hitGeo = new T.BufferGeometry();
  hitGeo.setAttribute('position', new T.BufferAttribute(hitPos, 3));
  hitGeo.setAttribute('color', new T.BufferAttribute(hitCol, 3));
  var hits = new T.Points(hitGeo, new T.PointsMaterial({ vertexColors: true, size: .1, transparent: true, opacity: .95, depthWrite: false, toneMapped: false }));
  hits.frustumCulled = false; hits.visible = false; hits.renderOrder = 3; scene.add(hits);

  /* ---------- 场地云图：控制台内置底图，同样裁掉 2 m 以上并按高度分 9 色带 ---------- */
  var mapMat, mapPts, pathLine;
  (function () {
    var q = int16(D.map.points), n = q.length / 3, P = new Float32Array(q.length), C = new Float32Array(q.length);
    var BANDS = ['#0000ff', '#0055ff', '#00aaff', '#00ffff', '#00ff80', '#55ff00', '#ffff00', '#ffaa00', '#ff0000'].map(function (h) { return new T.Color(h); });
    var Z_LO = -.4, Z_HI = 2.2; // slam/console/web/index.html
    for (var i = 0; i < n; i++) {
      P[i * 3] = q[i * 3] / D.map.quant; P[i * 3 + 1] = q[i * 3 + 1] / D.map.quant; P[i * 3 + 2] = q[i * 3 + 2] / D.map.quant;
      var z = P[i * 3 + 1] - .2; // 还原 xt_map 的 z：地面在 LiDAR 下方约 0.2 m
      var b = BANDS[Math.max(0, Math.min(8, Math.floor((z - Z_LO) / (Z_HI - Z_LO) * 9)))];
      C[i * 3] = b.r; C[i * 3 + 1] = b.g; C[i * 3 + 2] = b.b;
    }
    var g = new T.BufferGeometry();
    g.setAttribute('position', new T.BufferAttribute(P, 3));
    g.setAttribute('color', new T.BufferAttribute(C, 3));
    mapMat = new T.ShaderMaterial({
      transparent: true, depthWrite: false,
      uniforms: { uReveal: { value: 0 }, uA: { value: 0 }, uPx: { value: 1 }, uFloor: { value: 1 } },
      vertexShader: 'attribute vec3 color;uniform float uReveal,uPx,uFloor;varying vec3 vC;varying float vE,vD;void main(){vec4 mv=modelViewMatrix*vec4(position,1.);gl_Position=projectionMatrix*mv;vD=length(position.xz);vE=(1.-smoothstep(uReveal-1.5,uReveal,vD))*mix(uFloor,1.,smoothstep(.3,.62,position.y));vC=color;gl_PointSize=uPx*clamp(46./-mv.z,1.25,3.);}',
      fragmentShader: 'uniform float uA,uReveal;varying vec3 vC;varying float vE,vD;void main(){vec2 c=gl_PointCoord-.5;if(dot(c,c)>.25)discard;float front=1.-smoothstep(0.,1.2,abs(vD-uReveal));gl_FragColor=vec4(pow(vC,vec3(.4545))*.9+vec3(.5)*front,uA*vE);}'
    });
    mapPts = new T.Points(g, mapMat); mapPts.frustumCulled = false; mapPts.visible = false; mapPts.matrixAutoUpdate = false;
    scene.add(mapPts);
    var tq = int16(D.map.path), TP = new Float32Array(tq.length);
    for (i = 0; i < tq.length; i++) TP[i] = tq[i] / D.map.quant;
    var tg = new T.BufferGeometry(); tg.setAttribute('position', new T.BufferAttribute(TP, 3));
    pathLine = new T.Line(tg, new T.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0, depthTest: false }));
    pathLine.frustumCulled = false; pathLine.renderOrder = 3; pathLine.visible = false; pathLine.matrixAutoUpdate = false; scene.add(pathLine);
  })();

  // 不带脑的盲车对照：同一起点，直行到本机保护急停（stage3_009 wall_ahead_blind）
  var blindLine, blindDot, brainPath;
  (function () {
    blindLine = new T.Line(new T.BufferGeometry(), new T.LineDashedMaterial({ color: 0xece9e2, dashSize: .09, gapSize: .07, transparent: true, opacity: 0, depthTest: false }));
    blindLine.frustumCulled = false; blindLine.matrixAutoUpdate = false; blindLine.renderOrder = 3; scene.add(blindLine);
    blindDot = new T.Mesh(new T.RingGeometry(.1, .125, 40), new T.MeshBasicMaterial({ color: 0xece9e2, transparent: true, opacity: 0, side: T.DoubleSide, depthTest: false }));
    blindDot.rotation.x = -Math.PI / 2;
    var holder = new T.Group(); holder.matrixAutoUpdate = false; holder.add(blindDot); scene.add(holder); blindDot.userData.holder = holder;
    brainPath = new T.Line(new T.BufferGeometry(), new T.LineBasicMaterial({ color: 0xE8583A, transparent: true, opacity: 0, depthTest: false }));
    brainPath.frustumCulled = false; brainPath.matrixAutoUpdate = false; brainPath.renderOrder = 3; scene.add(brainPath);
  })();

  /* ---------- 脑：真实坐标 ---------- */
  var BRAIN_POS = new T.Vector3(0, 1.02, -.03), BRAIN_SCALE = .5; // 画在机器人正上方只是构图
  var brain = new T.Group(); brain.position.copy(BRAIN_POS); brain.scale.setScalar(BRAIN_SCALE); brain.visible = false; scene.add(brain);
  var LINK_START = new T.Vector3(.014, .6, -.03);
  function decodeBrain(b64) {
    var q = int16(b64), o = new Float32Array(q.length);
    for (var i = 0; i < q.length; i++) o[i] = q[i] / D.brain.quant;
    return o;
  }
  var brainUni = { uForm: { value: 0 }, uA: { value: 1 }, uPx: { value: 1 }, uOrigin: { value: new T.Vector3() }, uRegion: { value: 0 }, uFocus: { value: -1 } };
  // 脑区：颜色绑定 FlyWire 注释（build_data.py region_of）；功能为文献概述
  var REGIONS = [
    { k: 'LA', c: '#14A594', col: -1, n: Z('Lamina', '薄板'), f: Z('First stop after the eye', '视觉的第一站') },
    { k: 'ME', c: '#2F80E0', col: -1, n: Z('Medulla', '髓质'), f: Z('Motion and colour', '运动与颜色') },
    { k: 'LOC', c: '#A98CF5', col: -1, n: Z('Lobula complex', '小叶复合体'), f: Z('Shape and wide-field motion', '形状与大范围运动') },
    { k: 'VPN', c: '#E0559A', col: -1, n: Z('Visual projection', '视觉投射'), f: Z('Looming and features, sent inward', '逼近与特征，传入中脑'), tag: Z('Robot input enters here', '机器人输入从这里进') },
    { k: 'MB', c: '#D08A1C', col: 1, n: Z('Mushroom body', '蘑菇体'), f: Z('Learning and memory', '学习与记忆') },
    { k: 'CX', c: '#6FA52E', col: 1, n: Z('Central complex', '中央复合体'), f: Z('Heading and navigation', '朝向与导航') },
    { k: 'OL', c: '#EE8A63', col: 1, n: Z('Olfactory pathway', '嗅觉通路'), f: Z('Antennal lobe and lateral horn: smell', '触角叶与侧角：嗅觉') },
    { k: 'DN', c: '#F4F1E8', col: 1, n: Z('Descending neurons', '下降神经元'), f: Z('Commands to the body', '向身体发指令'), tag: Z('Robot output read here', '机器人输出从这里读') }
  ];
  function hex3(h) { return [parseInt(h.slice(1, 3), 16) / 255, parseInt(h.slice(3, 5), 16) / 255, parseInt(h.slice(5, 7), 16) / 255]; }
  brainUni.uOrigin.value.copy(LINK_START).sub(BRAIN_POS).divideScalar(BRAIN_SCALE);
  (function () {
    var bg = decodeBrain(D.brain.background), n = bg.length / 3, seed = new Float32Array(n);
    for (var i = 0; i < n; i++) seed[i] = Math.random();
    var rawR = atob(D.brain.background_region), rid = new Float32Array(n), rc = new Float32Array(n * 3);
    var rgb = REGIONS.map(function (r) { return hex3(r.c); });
    var sums = REGIONS.map(function () { return [0, 0, 0, 0]; });
    for (i = 0; i < n; i++) {
      var ri = rawR.charCodeAt(i), c3 = rgb[ri] || [.6, .6, .58];
      rid[i] = ri; rc[i * 3] = c3[0]; rc[i * 3 + 1] = c3[1]; rc[i * 3 + 2] = c3[2];
      if (REGIONS[ri] && bg[i * 3] * REGIONS[ri].col > 0) { var sm = sums[ri]; sm[0] += bg[i * 3]; sm[1] += bg[i * 3 + 1]; sm[2] += bg[i * 3 + 2]; sm[3]++; }
    }
    REGIONS.forEach(function (r, ix) { var sm = sums[ix]; r.pos = new T.Vector3(sm[0] / sm[3], sm[1] / sm[3], sm[2] / sm[3]); });
    var g = new T.BufferGeometry();
    g.setAttribute('position', new T.BufferAttribute(bg, 3));
    g.setAttribute('seed', new T.BufferAttribute(seed, 1));
    g.setAttribute('rid', new T.BufferAttribute(rid, 1));
    g.setAttribute('rc', new T.BufferAttribute(rc, 3));
    var m = new T.ShaderMaterial({
      transparent: true, depthWrite: false, depthTest: false, blending: T.AdditiveBlending, uniforms: brainUni,
      vertexShader: 'attribute float seed,rid;attribute vec3 rc;uniform float uForm,uPx,uRegion,uFocus;uniform vec3 uOrigin;varying vec3 vC;varying float vK;void main(){float k=smoothstep(seed*.55,seed*.55+.45,uForm);vec3 p=mix(uOrigin,position,k);vec4 mv=modelViewMatrix*vec4(p,1.);gl_Position=projectionMatrix*mv;float on=(uFocus<0.||abs(rid-uFocus)<.5)?1.:.05;float grey=rid>7.5?1.:0.;vC=mix(vec3(.74,.73,.70)*(.55+seed*.45),rc*(.8+seed*.4),uRegion);vK=mix(.36,mix(.5,.1,grey),uRegion)*on;gl_PointSize=uPx*clamp(7./-mv.z,1.1,2.4)*(1.+uRegion*.3);}',
      fragmentShader: 'uniform float uA;varying vec3 vC;varying float vK;void main(){vec2 c=gl_PointCoord-.5;float d=dot(c,c);if(d>.25)discard;gl_FragColor=vec4(vC,uA*vK*(1.-d*3.));}'
    });
    var pts = new T.Points(g, m); pts.frustumCulled = false; brain.add(pts);
  })();

  var groups = {};
  Object.keys(D.brain.groups).forEach(function (t) {
    var sides = D.brain.groups[t];
    groups[t] = {};
    Object.keys(sides).forEach(function (s) { groups[t][s] = decodeBrain(sides[s]); });
  });
  var hiUni = { uHi: { value: 0 }, uDn: { value: 0 }, uPx: { value: 1 }, uK: { value: new T.Vector3(1, 1, 1) }, uD: { value: new T.Vector4(1, 1, 1, 1) }, uDo: { value: 1 } };
  (function () {
    var pos = [], col = [], kind = [];
    var add = function (t, c, k) {
      ['left', 'right', 'other'].forEach(function (s) {
        var a = groups[t][s]; if (!a) return;
        for (var i = 0; i < a.length; i += 3) { pos.push(a[i], a[i + 1], a[i + 2]); col.push(c.r, c.g, c.b); kind.push(k); }
      });
    };
    add('LC4', new T.Color(COLORS.LC4), 0); add('LPLC2', new T.Color(COLORS.LPLC2), 1); add('LC9', new T.Color(COLORS.LC9), 2);
    var dn = new T.Color(COLORS.DN);
    var dnKind = { DNp09: 3, DNa02: 4, MDN: 5, DNp01: 6 };
    ['DNp01', 'DNp02', 'DNp04', 'DNp06', 'DNp11', 'DNp09', 'DNa01', 'DNa02', 'MDN'].forEach(function (t) { add(t, dn, dnKind[t] || 7); });
    var g = new T.BufferGeometry();
    g.setAttribute('position', new T.BufferAttribute(new Float32Array(pos), 3));
    g.setAttribute('color', new T.BufferAttribute(new Float32Array(col), 3));
    g.setAttribute('kind', new T.BufferAttribute(new Float32Array(kind), 1));
    var m = new T.ShaderMaterial({
      transparent: true, depthWrite: false, depthTest: false, blending: T.AdditiveBlending, uniforms: hiUni,
      vertexShader: 'attribute vec3 color;attribute float kind;uniform float uHi,uDn,uPx,uDo;uniform vec3 uK;uniform vec4 uD;varying vec3 vC;varying float vA;void main(){vec4 mv=modelViewMatrix*vec4(position,1.);gl_Position=projectionMatrix*mv;bool dn=kind>2.5;float w=dn?uDn*(kind<3.5?uD.x:kind<4.5?uD.y:kind<5.5?uD.z:kind<6.5?uD.w:uDo):uHi*(kind<.5?uK.x:kind<1.5?uK.y:uK.z);vA=w;vC=color;gl_PointSize=uPx*(dn?5.:3.2);}',
      fragmentShader: 'varying vec3 vC;varying float vA;void main(){vec2 c=gl_PointCoord-.5;float d=dot(c,c);if(d>.25)discard;gl_FragColor=vec4(vC*1.25,vA*(1.-d*2.6));}'
    });
    var pts = new T.Points(g, m); pts.frustumCulled = false; brain.add(pts);
  })();

  // 脉冲：路径与时序都是示意
  var CH = { L: 0, R: 1, F: 2, M: 3 };
  var pulseUni = { uT: { value: 0 }, uFlow: { value: 0 }, uPx: { value: 1 }, uCh: { value: new T.Vector4(1, 0, 0, 0) } };
  function pick(arr) { var i = Math.floor(Math.random() * arr.length / 3) * 3; return [arr[i], arr[i + 1], arr[i + 2]]; }
  (function () {
    var bgAll = decodeBrain(D.brain.background), hubs = [];
    for (var i = 0; i < bgAll.length; i += 3) {
      if (Math.abs(bgAll[i]) < .34 && Math.abs(bgAll[i + 1]) < .36 && hubs.length < 3000) hubs.push(bgAll[i], bgAll[i + 1], bgAll[i + 2]);
    }
    var a = [], b = [], c = [], s = [], ch = [], col = [];
    var colLC4 = new T.Color(COLORS.LC4), colP = new T.Color(COLORS.LPLC2), colC9 = new T.Color(COLORS.LC9);
    function push(from, to, channel, color) {
      var A0 = pick(from), M = pick(hubs), E = pick(to);
      a.push.apply(a, A0); b.push.apply(b, M); c.push.apply(c, E); s.push(Math.random()); ch.push(channel); col.push(color.r, color.g, color.b);
    }
    ['left', 'right'].forEach(function (side) {
      var other = side === 'left' ? 'right' : 'left', chn = side === 'left' ? CH.L : CH.R;
      for (var i = 0; i < 520; i++) {
        var useP = i % 3 > 0;
        var src = groups[useP ? 'LPLC2' : 'LC4'][side];
        var r = i % 10;
        var to = r < 5 ? groups.DNp01[side] : r < 7 ? groups.DNp02[side] : r < 8 ? groups.DNp04[side] : r < 9 ? groups.DNp11[side] : groups.DNa02[other];
        push(src, to, chn, useP ? colP : colLC4);
      }
    });
    for (i = 0; i < 300; i++) push(i % 2 ? groups.LPLC2.left : groups.LPLC2.right, i % 4 < 2 ? groups.MDN.left : (groups.MDN.right || groups.MDN.left), CH.M, colP);
    for (i = 0; i < 700; i++) push(i % 2 ? groups.LC9.left : groups.LC9.right, i % 4 < 2 ? groups.DNp09.left : groups.DNp09.right, CH.F, colC9);
    var g = new T.BufferGeometry();
    g.setAttribute('position', new T.BufferAttribute(new Float32Array(a), 3));
    g.setAttribute('mid', new T.BufferAttribute(new Float32Array(b), 3));
    g.setAttribute('end', new T.BufferAttribute(new Float32Array(c), 3));
    g.setAttribute('seed', new T.BufferAttribute(new Float32Array(s), 1));
    g.setAttribute('ch', new T.BufferAttribute(new Float32Array(ch), 1));
    g.setAttribute('col', new T.BufferAttribute(new Float32Array(col), 3));
    var m = new T.ShaderMaterial({
      transparent: true, depthWrite: false, depthTest: false, blending: T.AdditiveBlending, uniforms: pulseUni,
      vertexShader: 'attribute vec3 mid,end,col;attribute float seed,ch;uniform float uT,uFlow,uPx;uniform vec4 uCh;varying vec3 vC;varying float vA;void main(){float t=fract(seed+uT*.2);float u=1.-t;vec3 p=u*u*position+2.*u*t*mid+t*t*end;vec4 mv=modelViewMatrix*vec4(p,1.);gl_Position=projectionMatrix*mv;float w=ch<.5?uCh.x:ch<1.5?uCh.y:ch<2.5?uCh.z:uCh.w;float gate=1.-smoothstep(uFlow-.08,uFlow,t);vA=w*gate*smoothstep(0.,.05,t)*(1.-smoothstep(.93,1.,t));vC=mix(col,vec3(1.,.97,.9),smoothstep(.55,1.,t));gl_PointSize=uPx*1.8;}',
      fragmentShader: 'varying vec3 vC;varying float vA;void main(){vec2 c=gl_PointCoord-.5;float d=dot(c,c);if(d>.25)discard;gl_FragColor=vec4(vC*1.25,vA*(1.-d*3.));}'
    });
    var pts = new T.Points(g, m); pts.frustumCulled = false; brain.add(pts);
  })();

  // 机身与脑之间的两条信号通路（示意）：向上进视叶，向下回底盘
  function sideCentroid(side) {
    var v = new T.Vector3(), n = 0;
    ['LC4', 'LPLC2'].forEach(function (t) { var a = groups[t][side]; for (var i = 0; i < a.length; i += 3) { v.x += a[i]; v.y += a[i + 1]; v.z += a[i + 2]; n++; } });
    return v.divideScalar(n);
  }
  brain.updateMatrixWorld(true);
  function makeStream(from, to, bend, color, n, size) {
    var mid = from.clone().lerp(to, .5).add(bend);
    var g = new T.BufferGeometry().setAttribute('position', new T.BufferAttribute(new Float32Array(n * 3), 3));
    var m = new T.PointsMaterial({ color: color, size: size, transparent: true, opacity: 0, depthWrite: false, depthTest: false, blending: T.AdditiveBlending });
    var pts = new T.Points(g, m); pts.frustumCulled = false; pts.renderOrder = 6; scene.add(pts);
    var line = new T.Line(new T.BufferGeometry().setFromPoints(new T.QuadraticBezierCurve3(from, mid, to).getPoints(40)), new T.LineBasicMaterial({ color: color, transparent: true, opacity: 0, depthTest: false }));
    line.frustumCulled = false; line.renderOrder = 5; scene.add(line);
    var curve = new T.QuadraticBezierCurve3(from, mid, to), tmp = new T.Vector3();
    return {
      curve: curve, m: m,
      update: function (a, t) {
        pts.visible = line.visible = a > .003; m.opacity = a; line.material.opacity = a * .34;
        if (!pts.visible) return;
        var lp = g.attributes.position;
        for (var i = 0; i < n; i++) { curve.getPoint(((i / n + t) % 1 + 1) % 1, tmp); lp.setXYZ(i, tmp.x, tmp.y, tmp.z); }
        lp.needsUpdate = true;
      }
    };
  }
  var LIDAR_TOP = new T.Vector3(0, LIDAR_Y + .05, LIDAR_Z);
  var upL = makeStream(LIDAR_TOP, sideCentroid('left').applyMatrix4(brain.matrixWorld), new T.Vector3(.13, -.05, 0), COLORS.LC4, 16, .017);
  var upR = makeStream(LIDAR_TOP, sideCentroid('right').applyMatrix4(brain.matrixWorld), new T.Vector3(-.13, -.05, 0), COLORS.LC4, 16, .017);
  var downS = makeStream(dnAnchor('DNp01').applyMatrix4(brain.matrixWorld), new T.Vector3(0, .53, -.01), new T.Vector3(0, 0, 0), 0xf4f1e8, 18, .02);

  /* ---------- 决策回放的场景件 ---------- */
  var person = new T.Group();
  // 人：按约 7.5 头身比例程序化生成的环线扫描人形，步态为简化的生物力学曲线。走法和位置都是示意
  var personMat = new T.PointsMaterial({ color: 0xe9e5da, size: .0088, transparent: true, opacity: .9, depthWrite: false });
  var limbs = {};
  (function () {
    function interp(tab, y) { // tab: [[y, rx, rz, cz], ...]，y 递增
      for (var i = 0; i < tab.length - 1; i++) {
        if (y <= tab[i + 1][0]) {
          var f = smooth((y - tab[i][0]) / (tab[i + 1][0] - tab[i][0]));
          return [lerp(tab[i][1], tab[i + 1][1], f), lerp(tab[i][2], tab[i + 1][2], f), lerp(tab[i][3] || 0, tab[i + 1][3] || 0, f)];
        }
      }
      var l = tab[tab.length - 1]; return [l[1], l[2], l[3] || 0];
    }
    function rings(tab, dy, ds) { // 水平环线，像 LiDAR 逐线扫过
      var pts = [], y0 = tab[0][0], y1 = tab[tab.length - 1][0];
      for (var y = y0; y <= y1 + 1e-6; y += dy) {
        var v = interp(tab, y), rx = v[0], rz = v[1], c = 2 * Math.PI * Math.sqrt((rx * rx + rz * rz) / 2);
        var n = Math.max(8, Math.round(c / ds));
        var ph = y * 37.1;
        for (var k = 0; k < n; k++) {
          var a = ph + k / n * Math.PI * 2;
          pts.push(rx * Math.cos(a), y, v[2] + rz * Math.sin(a));
        }
      }
      return pts;
    }
    function ellip(cy, ry, rx, rz, cz) { // 椭球按环线取样
      var tab = [], N = 14;
      for (var i = 0; i <= N; i++) {
        var u = -1 + 2 * i / N, r = Math.sqrt(Math.max(.0004, 1 - u * u));
        tab.push([cy + ry * u, rx * r, rz * r, cz || 0]);
      }
      return tab;
    }
    function cloud(tab, dy, ds) {
      var g = new T.BufferGeometry().setAttribute('position', new T.BufferAttribute(new Float32Array(rings(tab, dy || .017, ds || .017)), 3));
      var o = new T.Points(g, personMat); o.frustumCulled = false; return o;
    }
    var body = new T.Group(); person.add(body); limbs.body = body;
    var chest = new T.Group(); chest.position.y = 1.0; body.add(chest); limbs.chest = chest;
    // 髋到腰
    body.add(cloud([[.8, .09, .08], [.84, .15, .1, -.004], [.9, .168, .113, -.008], [.96, .158, .104, -.004], [1.0, .146, .096]]));
    // 腰、胸、肩（以腰为原点，便于扭转）
    chest.add(cloud([[0, .146, .096], [.07, .133, .09], [.18, .15, .1, .005], [.28, .17, .108, .008], [.36, .178, .102, .004], [.41, .165, .08], [.445, .085, .062], [.5, .052, .052, .006]]));
    chest.add(cloud(ellip(.605, .118, .077, .096, .012), .014, .014));
    [-1, 1].forEach(function (sd) {
      var key = sd > 0 ? 'A' : 'B';
      // 手臂
      var arm = new T.Group(); arm.position.set(sd * .2, .395, 0); chest.add(arm); limbs['arm' + key] = arm;
      arm.add(cloud([[-.3, .036, .038], [-.16, .043, .046], [-.03, .048, .05], [.015, .036, .038]]));
      var fore = new T.Group(); fore.position.y = -.3; arm.add(fore); limbs['fore' + key] = fore;
      fore.add(cloud([[-.26, .025, .029], [-.14, .033, .036], [-.02, .036, .038]]));
      fore.add(cloud(ellip(-.33, .07, .02, .036, .006), .014, .014));
      // 腿
      var leg = new T.Group(); leg.position.set(sd * .088, .88, 0); body.add(leg); limbs['leg' + key] = leg;
      leg.add(cloud([[-.4, .05, .054], [-.3, .058, .064], [-.14, .072, .078], [-.02, .082, .09], [.03, .07, .08]]));
      var calf = new T.Group(); calf.position.y = -.4; leg.add(calf); limbs['calf' + key] = calf;
      calf.add(cloud([[-.38, .03, .034], [-.26, .036, .04, -.004], [-.12, .05, .058, -.01], [-.03, .05, .054], [.02, .05, .054]]));
      var foot = new T.Group(); foot.position.y = -.4; calf.add(foot); limbs['foot' + key] = foot;
      var ftab = [];
      for (var i = 0; i <= 12; i++) { var u = i / 12; ftab.push([-.08 + u * .07, .04 * (1 - u * .35), .125 * Math.sqrt(1 - u * u * .85), .058 - u * .03]); }
      foot.add(cloud(ftab, .009, .012));
    });
  })();
  function wrapPi(a) { a = (a + Math.PI) % (Math.PI * 2); if (a < 0) a += Math.PI * 2; return a - Math.PI; }
  function legPose(key, ph, amp) {
    var hip = (.05 + .44 * Math.sin(ph)) * amp;
    var kb = wrapPi(ph + .42);
    var knee = (.1 + 1.0 * Math.exp(-kb * kb / (2 * .62 * .62))) * amp;
    limbs['leg' + key].rotation.x = -hip;
    limbs['calf' + key].rotation.x = knee;
    limbs['foot' + key].rotation.x = (hip - knee) * .9 + .22 * Math.max(0, Math.sin(ph - 2.2)) * amp;
  }
  function walkPose(phi, amp) {
    legPose('A', phi, amp); legPose('B', phi + Math.PI, amp);
    // 手臂与同侧腿反相
    limbs.armA.rotation.x = .34 * Math.sin(phi) * amp + .02; limbs.armB.rotation.x = -.34 * Math.sin(phi) * amp + .02;
    limbs.armA.rotation.z = .05; limbs.armB.rotation.z = -.05;
    limbs.foreA.rotation.x = -(.22 + .2 * Math.max(0, -Math.sin(phi)) * amp); limbs.foreB.rotation.x = -(.22 + .2 * Math.max(0, Math.sin(phi)) * amp);
    limbs.body.position.y = (-.034 * Math.pow(Math.sin(phi), 2) + .014) * amp;
    limbs.body.position.x = .014 * Math.sin(phi) * amp;
    limbs.body.rotation.y = -.09 * Math.sin(phi) * amp;
    limbs.chest.rotation.y = .17 * Math.sin(phi) * amp;
    limbs.chest.rotation.x = .035 * amp;
  }
  person.visible = false; scene.add(person);
  var intent = new T.Group(); intent.position.y = .012; intent.renderOrder = 3; intent.visible = false; scene.add(intent);
  function flatMat() { return new T.MeshBasicMaterial({ color: 0xf4f1e8, transparent: true, opacity: 0, side: T.DoubleSide, depthWrite: false, toneMapped: false }); }
  function arrowGeo(len) {
    var sh = new T.Shape(); var w = .014, hw = .042, hl = .06;
    sh.moveTo(-w, 0); sh.lineTo(w, 0); sh.lineTo(w, len - hl); sh.lineTo(hw, len - hl); sh.lineTo(0, len); sh.lineTo(-hw, len - hl); sh.lineTo(-w, len - hl); sh.closePath();
    var g = new T.ShapeGeometry(sh); g.rotateX(Math.PI / 2); return g;
  }
  var arrowF = new T.Mesh(arrowGeo(.3), flatMat()); arrowF.position.z = .42; intent.add(arrowF);
  var arrowB = new T.Mesh(arrowGeo(.3), flatMat()); arrowB.rotation.y = Math.PI; arrowB.position.z = -.3; intent.add(arrowB);
  function arcGeo(sign) { // 从前方开始，沿转向方向的弧形箭头；+ = 向左（ROS 偏航为正）
    var pts = new T.Shape(), R0 = .395, R1 = .425, A = 1.05, n = 28, k, a;
    function P(r, ang) { return [sign * Math.sin(ang) * r, Math.cos(ang) * r]; }
    var s0 = P(R1, .12); pts.moveTo(s0[0], s0[1]);
    for (k = 1; k <= n; k++) { a = .12 + A * k / n; var q = P(R1, a); pts.lineTo(q[0], q[1]); }
    var o = P(.45, .12 + A), t = P(.41, .12 + A + .2), ii = P(.37, .12 + A);
    pts.lineTo(o[0], o[1]); pts.lineTo(t[0], t[1]); pts.lineTo(ii[0], ii[1]);
    for (k = n; k >= 0; k--) { a = .12 + A * k / n; var q2 = P(R0, a); pts.lineTo(q2[0], q2[1]); }
    pts.closePath();
    var g = new T.ShapeGeometry(pts); g.rotateX(Math.PI / 2); return g;
  }
  var arcL = new T.Mesh(arcGeo(1), flatMat()); intent.add(arcL);
  var arcR = new T.Mesh(arcGeo(-1), flatMat()); intent.add(arcR);

  var rt = 0, PREROLL = 4.5, HOLD_END = 2.6, moveUi = '';
  var worldG = new T.Group(); worldG.visible = false; scene.add(worldG);
  var gridMat = new T.LineBasicMaterial({ color: 0xece9e2, transparent: true, opacity: 0, depthWrite: false });
  (function () {
    var v = [], R0 = 6, stepG = .5;
    for (var g = -R0; g <= R0 + 1e-6; g += stepG) { v.push(g, .008, -R0, g, .008, R0, -R0, .008, g, R0, .008, g); }
    var geo = new T.BufferGeometry().setAttribute('position', new T.Float32BufferAttribute(v, 3));
    worldG.add(new T.LineSegments(geo, gridMat));
  })();
  var startMat = new T.MeshBasicMaterial({ color: 0xE8583A, transparent: true, opacity: 0, side: T.DoubleSide, depthWrite: false });
  var startRing = new T.Mesh(new T.RingGeometry(.335, .35, 72), startMat); startRing.rotation.x = -Math.PI / 2; startRing.position.y = .012; worldG.add(startRing);
  var startDot = new T.Mesh(new T.CircleGeometry(.018, 24), startMat); startDot.rotation.x = -Math.PI / 2; startDot.position.y = .012; worldG.add(startDot);
  var trailGeo = new T.BufferGeometry().setAttribute('position', new T.BufferAttribute(new Float32Array([0, .014, 0, 0, .014, 0]), 3));
  var trailMat = new T.LineBasicMaterial({ color: 0xE8583A, transparent: true, opacity: 0, depthTest: false });
  var trail = new T.Line(trailGeo, trailMat); trail.frustumCulled = false; worldG.add(trail);
  var pulseMat = new T.MeshBasicMaterial({ color: 0xE8583A, transparent: true, opacity: 0, side: T.DoubleSide, depthWrite: false, toneMapped: false });
  var pulse = new T.Mesh(new T.RingGeometry(.92, 1, 72), pulseMat); pulse.rotation.x = -Math.PI / 2; pulse.position.y = .016; pulse.visible = false; scene.add(pulse);
  // 起点 x,z -> 终点 x,z（机器人左 +X、前 +Z）；终点距离约 0.95 m，协议要求人停在约 0.7 m
  var PATHS = { left: [1.5, -3.4, .82, .47], right: [-1.5, -3.4, -.82, .47], front: [0, 4.7, 0, 1] };
  function peakIdx(rows) { var b = 0, m = -1; rows.forEach(function (r, i) { var v = r[5] + r[6]; if (v > m) { m = v; b = i; } }); return b; }

  /* ---------- 镜头时间线 ---------- */
  // p: 滚动进度；az/el 度；r 距离；t 目标点；sx 横向构图；ex 拆解量；a 膝部姿态（弧度）
  var K = [
    { p: 0, az: 27, el: 6, r: 2.7, t: [0, .5, 0], ex: 0, a: .52 },
    { p: .07, az: 38, el: 7, r: 2.7, t: [0, .5, 0], ex: 0, a: .52 },
    { p: .185, az: 14, el: 11, r: 4.9, t: [0, .47, 0], ex: 1, a: .12 },
    { p: .205, az: 18, el: 11, r: 4.9, t: [0, .47, 0], ex: 1, a: .12 },
    { p: .25, az: 58, el: 7, r: 3.2, t: [0, .24, 0], ex: .42, a: .5 },
    { p: .335, az: 96, el: 5, r: 3.2, t: [0, .24, 0], ex: .42, a: .62 },
    { p: .4, az: 170, el: 56, r: 62, t: [0, .3, 0], ex: 0, a: .4 },
    { p: .43, az: 186, el: 52, r: 58, t: [0, .3, 0], ex: 0, a: .4 },
    { p: .448, az: 194, el: 50, r: 56, t: [0, .3, 0], ex: 0, a: .4 },
    { p: .464, az: 186, el: 24, r: 6.6, t: [0, .62, 0], ex: 0, a: .4 },
    { p: .5, az: 194, el: 22, r: 6.2, t: [0, .62, 0], ex: 0, a: .4 },
    { p: .54, az: -30, el: 12, r: 3.7, t: [0, .56, 0], ex: .72, a: .3 },
    { p: .605, az: -14, el: 12, r: 3.7, t: [0, .56, 0], ex: .72, a: .3 },
    { p: .655, az: 10, el: 5, r: 4.1, t: [0, .6, 0], ex: .16, a: .5 },
    { p: .76, az: 2, el: 6, r: 4.8, t: [0, .34, 0], ex: .06, a: .5 },
    { p: .812, az: -2, el: 6, r: 4.8, t: [0, .34, 0], ex: .04, a: .5 },
    { p: .865, az: -8, el: 6, r: 4.8, t: [0, .34, 0], ex: .03, a: .5 },
    { p: .885, az: -22, el: 6, r: 5.1, t: [0, .82, 0], ex: 0, a: .5 },
    { p: .945, az: -18, el: 6, r: 5.1, t: [0, .82, 0], ex: 0, a: .5 },
    { p: .978, az: 38, el: 7, r: 2.7, t: [0, .5, 0], ex: 0, a: .52 },
    { p: 1, az: 27, el: 6, r: 2.7, t: [0, .5, 0], ex: 0, a: .52 }
  ];
  var FOCUS = [
    { from: .215, to: .335, on: ['motor', 'fin', 'upper', 'lower', 'rim', 'tire'], dim: .7 },
    { from: .345, to: .5, on: ['lidar'], dim: .25 },
    { from: .512, to: .61, on: ['compute', 'radio', 'lidar', 'camera', 'battery'], dim: .66 },
    { from: .62, to: .955, on: [], dim: .12 }
  ];
  var LABELS = {
    all: [.13, .207],
    sets: [
      { from: .13, to: .207, ids: ['base', 'motorL', 'upperL', 'lowerL', 'tireL', 'lidar', 'compute', 'radio', 'battery', 'camera'] },
      { from: .235, to: .33, ids: ['motorL', 'upperL', 'lowerL', 'rimL', 'tireL'] },
      { from: .535, to: .603, ids: ['compute', 'radio', 'lidar', 'camera', 'battery'] }
    ]
  };
  var LABEL_DIR = {
    base: [-74, -26], motorL: [84, -56], finL: [52, -106], upperL: [70, -60], lowerL: [84, 56], rimL: [64, 72], tireL: [70, -44],
    lidar: [74, -14], compute: [120, -34], radio: [-96, -18], battery: [-82, 52], camera: [-150, -30]
  };

  function sample(p) {
    var i = 0; while (i < K.length - 2 && p > K[i + 1].p) i++;
    var a = K[i], b = K[i + 1], t = smooth((p - a.p) / (b.p - a.p));
    return {
      az: lerp(a.az, b.az, t), el: lerp(a.el, b.el, t), r: lerp(a.r, b.r, t),
      tx: lerp(a.t[0], b.t[0], t), ty: lerp(a.t[1], b.t[1], t), tz: lerp(a.t[2], b.t[2], t),
      ex: lerp(a.ex, b.ex, t), a: lerp(a.a, b.a, t)
    };
  }

  /* ---------- DOM ---------- */
  var labelsEl = $('#labels'), leaders = $('#leaders'), SVGNS = 'http://www.w3.org/2000/svg';
  function mkLabel(lines, cls) {
    var el = document.createElement('div'); el.className = 'lab ' + (cls || ''); el.style.opacity = 0;
    el.innerHTML = '<b>' + lines[0] + '</b>' + (lines[1] ? '<span>' + lines[1] + '</span>' : '');
    labelsEl.appendChild(el);
    var path = document.createElementNS(SVGNS, 'path'); path.style.opacity = 0; leaders.appendChild(path);
    var dot = document.createElementNS(SVGNS, 'circle'); dot.setAttribute('r', '1.8'); dot.style.opacity = 0; leaders.appendChild(dot);
    return { el: el, path: path, dot: dot, a: 0 };
  }
  var PART_NAMES = { base: Z('Chassis', '底盘'), motorL: Z('Hip motor', '髋电机'), upperL: Z('Upper link', '上连杆'), lowerL: Z('Lower link', '下连杆'), rimL: Z('Hub', '轮毂'), tireL: Z('Tire', '轮胎'), lidar: 'L1 LiDAR', compute: Z('Onboard computer', '机载计算'), radio: Z('Radio', '无线'), battery: Z('Battery', '电池'), camera: Z('Camera', '相机') };
  Object.keys(PART_NAMES).forEach(function (id) {
    var p = parts[id]; p.ui = mkLabel([PART_NAMES[id]], p.edges.length ? 'sch' : '');
    if (p.edges.length) p.ui.path.setAttribute('class', 'sch');
  });
  function dnAnchor(t) {
    var v = new T.Vector3(), n = 0;
    ['left', 'right'].forEach(function (s) { var a = groups[t][s]; if (!a) return; for (var i = 0; i < a.length; i += 3) { v.x += a[i]; v.y += a[i + 1]; v.z += a[i + 2]; n++; } });
    return v.divideScalar(n);
  }
  function sideAnchor(t, col) { // 屏幕右侧对应果蝇左侧（从前方看）
    var a = groups[t][col > 0 ? 'left' : 'right'] || groups[t].left || groups[t].right, v3 = new T.Vector3();
    for (var i = 0; i < a.length; i += 3) { v3.x += a[i]; v3.y += a[i + 1]; v3.z += a[i + 2]; }
    return v3.divideScalar(a.length / 3);
  }
  function withDot(ui, c) { var i = document.createElement('i'); i.className = 'dot'; i.style.background = c; ui.el.insertBefore(i, ui.el.firstChild); ui.color = c; return ui; }
  // 脑区标签固定在脑两侧空白处，用箭头指回区域
  REGIONS.forEach(function (r, ix) {
    r.ui = withDot(mkLabel([r.n, r.f], 'rg ' + (r.col < 0 ? 'to-l' : 'to-r')), r.c);
    if (r.tag) { var em = document.createElement('em'); em.textContent = r.tag; r.ui.el.appendChild(em); }
    r.ui.el.addEventListener('mouseenter', function () { brainUni.uFocus.value = ix; dirty = true; });
    r.ui.el.addEventListener('mouseleave', function () { brainUni.uFocus.value = -1; dirty = true; });
  });
  var rgByCol = { '-1': REGIONS.filter(function (r) { return r.col < 0; }), '1': REGIONS.filter(function (r) { return r.col > 0; }) };
  [-1, 1].forEach(function (c) { rgByCol[c].sort(function (a, b) { return b.pos.y - a.pos.y; }); });
  var rgLegend = $('#rgLegend');
  if (rgLegend) rgLegend.innerHTML = REGIONS.map(function (r) { return '<li><i style="background:' + r.c + '"></i><b>' + r.n + '</b><span>' + r.f + '</span></li>'; }).join('');
  // 映射与回放章节的细胞标签：col/slot 分别对应两段的版式
  var dnLabels = [
    { t: 'DNp09', n: Z('forward', '前进'), map: [1, 0], rep: [-1, 0] }, { t: 'DNa02', n: Z('turn', '转向'), map: [1, 1], rep: [1, 1] },
    { t: 'MDN', n: Z('back', '后退'), map: [1, 2], rep: [-1, 1] }, { t: 'DNp01', n: Z('giant fibre, escape', '巨纤维，逃逸'), map: [1, 3], rep: [1, 0] }
  ];
  dnLabels.forEach(function (d) {
    d.ui = withDot(mkLabel([d.t, d.n], 'dn'), '#F4F1E8');
    d.posL = sideAnchor(d.t, -1); d.posR = sideAnchor(d.t, 1);
  });
  var inLabels = [
    { t: 'LC9', n: Z('free space ahead (proxy)', '前方开阔（代理）'), c: '#' + COLORS.LC9.toString(16).padStart(6, '0'), slot: 0 },
    { t: 'LC4', n: Z('looming (proxy)', '逼近（代理）'), c: '#' + COLORS.LC4.toString(16).padStart(6, '0'), slot: 1 },
    { t: 'LPLC2', n: Z('looming (proxy)', '逼近（代理）'), c: '#' + COLORS.LPLC2.toString(16).padStart(6, '0'), slot: 2 }
  ];
  inLabels.forEach(function (d) { d.ui = withDot(mkLabel([d.t, d.n], 'dn'), d.c); d.pos = sideAnchor(d.t, -1); });
    var personLabel = mkLabel([Z('Person (illustrative)', '人（示意）')], 'sch');
  function decisionText(r) {
    return { left: Z('Turn left', '向左转'), right: Z('Turn right', '向右转'), back: Z('Back away', '后退'), forward: Z('Forward', '前进'), hold: Z('Hold', '停住') }[r[16]];
  }
  var blindLabel = mkLabel([Z('No-brain robot stops here', '盲车停在这里')], 'sch');
  var noBrainLabel = mkLabel([Z('No brain', '没有脑')], 'sch');
  var upLabel = mkLabel([Z('Input', '输入')], '');
  var downLabel = mkLabel([Z('Output', '输出')], '');

  var W = 1, H = 1, narrow = false, DPR = 1;
  function resize() {
    W = window.innerWidth; H = window.innerHeight;
    narrow = W <= 820 || H <= 640;
    DPR = Math.min(window.devicePixelRatio || 1, narrow ? 1.5 : 1.75);
    renderer.setPixelRatio(DPR); renderer.setSize(W, H, false);
    camera.aspect = W / H;
    leaders.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    mapMat.uniforms.uPx.value = DPR; brainUni.uPx.value = DPR; hiUni.uPx.value = DPR * (narrow ? .8 : 1); pulseUni.uPx.value = DPR;
    if (cards) cards.forEach(function (c) { c.shown = -1; });
    dirty = true; measure();
  }
  var trackEl = $('#track'), trackLen = 1;
  function measure() { trackLen = Math.max(1, trackEl.offsetHeight - window.innerHeight); }
  function scrollP() { return clamp(window.scrollY / trackLen); }
  function goto(p, smoothly) {
    window.scrollTo({ top: p * trackLen, behavior: smoothly && !reduceMq.matches ? 'smooth' : 'auto' });
  }

  var cards = $$('.card').map(function (el) {
    return {
      el: el, from: +el.dataset.from, to: +el.dataset.to, shown: -1,
      nums: Array.prototype.map.call(el.querySelectorAll('.num'), function (n) { return { el: n, v: +n.dataset.v, d: +(n.dataset.d || 0), sep: !!n.dataset.sep }; })
    };
  });
  function fmtNum(n, x) { // 数字随滚动跳到记录值
    var t = x.toFixed(n.d);
    return n.sep ? t.replace(/\B(?=(\d{3})+(?!\d))/g, ',') : t;
  }
  var railFill = $('#railFill'), railThumb = $('#railThumb'), railTrack = $('#railTrack');
  var lastEx = 0;

  /* 场景数据：loom_005/RESULTS.md Stage 1（runs/stage1_001） */
  // 指令上限与逃逸程序：loom_005/decoder.py（decode、DecoderV6）。标签名对应被点亮的通路
  var SCN = {
    single: { ch: [1, 0, 0, 0], k: [1, 1, .25] }
  };
  var MAP = {
    forward: { ch: [0, 0, 1, 0], k: [.15, .15, 1], d: [1, .1, .1, .1], v: .15, w: 0, on: ['LC9', 'DNp09'] },
    turn: { ch: [1, 0, 0, 0], k: [1, 1, .15], d: [.1, 1, .1, .35], v: 0, w: -.4, on: ['LC4', 'LPLC2', 'DNa02'] },
    back: { ch: [1, 1, 0, 1], k: [1, 1, .15], d: [.1, .1, 1, .35], v: -.1, w: 0, on: ['LC4', 'LPLC2', 'MDN'] },
    escape: { ch: [1, 1, 0, 0], k: [1, 1, .15], d: [.1, .1, .1, 1], v: -.3, w: 0, on: ['LC4', 'LPLC2', 'DNp01'] }
  };
  var MAP_ORDER = ['forward', 'turn', 'back', 'escape'], mapAct = 'forward', mapPick = null, mapPickP = 0;
  var dTarget = new T.Vector4(1, 1, 1, 1);
  function setAct(a) {
    if (a === mapAct) return;
    mapAct = a; dirty = true;
    $$('.amap button').forEach(function (b) { var on = b.dataset.a === a; b.classList.toggle('on', on); b.setAttribute('aria-pressed', on); });
  }
  $$('.amap button').forEach(function (b) {
    b.setAttribute('aria-pressed', b.classList.contains('on'));
    b.addEventListener('click', function () { mapPick = b.dataset.a; mapPickP = pNow; setAct(mapPick); });
  });
  var currentScn = 'single', chTarget = new T.Vector4(1, 0, 0, 0), kTarget = new T.Vector3(1, 1, .25);
  function setScn(name) {
    currentScn = name; var s = SCN[name];
    chTarget.fromArray(s.ch); kTarget.fromArray(s.k);
    dirty = true;
  }

  /* ---------- 决策回放 UI 与右下角神经元面板：数字全部来自 stage4_002 ---------- */
  var currentEp = 'front';
  var STATE_ZH = { FORWARD: Z('Forward', '前进'), ESCAPE: Z('Escape', '逃逸'), ESCAPE_PROGRAM: Z('Turning away', '转身避开'), TURN_LEFT: Z('Turn left', '左转'), TURN_RIGHT: Z('Turn right', '右转'), HOLD: Z('Hold', '保持'), BACK_OFF: Z('Back off', '后退'), FLEE: Z('Leaving', '离开'), FREEZE: Z('Freeze', '定住'), REST: Z('Rest', '休息') };
  $$('.rp button').forEach(function (b) {
    b.addEventListener('click', function () {
      currentEp = b.dataset.e;
      $$('.rp button').forEach(function (x) { var on = x === b; x.classList.toggle('on', on); x.setAttribute('aria-pressed', on); });
      uiKey = ''; rt = 0; dirty = true;
    });
  });
  var decisionEl = $('#decision');
  var neuro = $('#neuro'), nc = $('#neuroCanvas'), nctx = nc.getContext('2d');
  var decB = $('#decision b'), decS = $('#decision span');
  function regSide(t, side) { var a = groups[t][side]; return a ? a.length / 3 : 0; }
  // 同类型同侧的细胞共用一个输入速率（loom_005/retina.py rates_vector），因此逐点点亮是忠实的
  var CELLS = [
    { t: 'LC4', side: 'left', c: '#E8583A', col: 1 }, { t: 'LPLC2', side: 'left', c: '#9468DB', col: 1 }, { t: 'LC9', side: 'left', c: '#169A87', col: 3 },
    { t: 'LC4', side: 'right', c: '#E8583A', col: 2 }, { t: 'LPLC2', side: 'right', c: '#9468DB', col: 2 }, { t: 'LC9', side: 'right', c: '#169A87', col: 4 }
  ].map(function (o) { o.n = regSide(o.t, o.side); return o; });
  var READ = [
    { n: Z('DNp01 L', 'DNp01 左'), i: 5, max: 210 }, { n: Z('DNp01 R', 'DNp01 右'), i: 6, max: 210 }, { n: 'DNp09', i: 7, max: 140 }, { n: 'MDN', i: 8, max: 120 }, { n: Z('DNa02 R−L', 'DNa02 右−左'), i: 9, max: 60, signed: true }
  ];
  var uiKey = '';
  function drawNeuro(ep, idx) {
    var W2 = nc.clientWidth, H2 = nc.clientHeight, dp = Math.min(window.devicePixelRatio || 1, 2);
    if (nc.width !== W2 * dp) { nc.width = W2 * dp; nc.height = H2 * dp; }
    var g = nctx; g.setTransform(dp, 0, 0, dp, 0, 0); g.clearRect(0, 0, W2, H2);
    var row = ep.rows[idx];
    var ink = '#ece9e2', ink2 = '#a9a8a3', ink3 = '#8f8e8a';
    g.textBaseline = 'middle';
    // 输入细胞：每点一个 root_id
    var cols = [[Z('Loom L', '左 loom'), 0], [Z('Loom R', '右 loom'), W2 * .31], [Z('LC9 L', 'LC9左'), W2 * .62], [Z('LC9 R', 'LC9右'), W2 * .82]];
    g.font = '10.5px "Noto Sans SC","Microsoft YaHei",sans-serif';
    var gridY = 16, s = 5.2;
    function grid(list, x0, w, rate, maxRate) {
      var y = gridY, perRow = Math.max(4, Math.floor(w / s)), a = .1 + .9 * clamp(rate / maxRate);
      list.forEach(function (o) {
        g.fillStyle = o.c; g.globalAlpha = a;
        for (var i = 0; i < o.n; i++) {
          g.beginPath(); g.arc(x0 + (i % perRow) * s + 2, y + Math.floor(i / perRow) * s + 2, 1.65, 0, 7); g.fill();
        }
        y += Math.ceil(o.n / perRow) * s + 3;
      });
      g.globalAlpha = 1;
    }
    var L4 = CELLS.filter(function (o) { return o.side === 'left' && o.t !== 'LC9'; }), R4 = CELLS.filter(function (o) { return o.side === 'right' && o.t !== 'LC9'; });
    grid(L4, 0, W2 * .28, row[1], 400); grid(R4, W2 * .31, W2 * .28, row[2], 400);
    grid(CELLS.filter(function (o) { return o.side === 'left' && o.t === 'LC9'; }), W2 * .62, W2 * .17, row[3], 120);
    grid(CELLS.filter(function (o) { return o.side === 'right' && o.t === 'LC9'; }), W2 * .82, W2 * .17, row[4], 120);
    var vals = [row[1], row[2], row[3], row[4]];
    cols.forEach(function (c, i) {
      g.fillStyle = ink2; g.textAlign = 'left'; g.fillText(c[0], c[1], 6);
      var tw = g.measureText(c[0]).width;
      g.fillStyle = ink; g.font = '10.5px "Cascadia Mono",Consolas,monospace'; g.fillText(String(vals[i]), c[1] + tw + 5, 6);
      g.font = '10.5px "Noto Sans SC","Microsoft YaHei",sans-serif';
    });
    // 读出：每窗一格的历史，当前窗高亮
    var top = H2 - READ.length * 19 - 2, labelW = 76, valW = 34, gw = W2 - labelW - valW, n = ep.rows.length, cw = gw / n;
    READ.forEach(function (r, ri) {
      var y = top + ri * 19;
      g.fillStyle = ink2; g.textAlign = 'left'; g.font = '10.5px "Cascadia Mono","Noto Sans SC",Consolas,monospace'; g.fillText(r.n, 0, y + 7);
      ep.rows.forEach(function (w, ci) {
        var v = w[r.i], a = clamp(Math.abs(v) / r.max);
        g.fillStyle = 'rgba(236,233,226,' + (.05 + .9 * a).toFixed(3) + ')';
        g.fillRect(labelW + ci * cw + 1, y, Math.max(1, cw - 2), 14);
      });
      g.fillStyle = ink; g.textAlign = 'right'; g.fillText(String(row[r.i]), W2, y + 7);
    });
    g.strokeStyle = ink; g.lineWidth = 1; g.strokeRect(labelW + idx * cw + .5, top - 3, Math.max(1, cw - 1), READ.length * 19 + 1);
    g.textAlign = 'left';
  }
  function updateReplayUi(ep, idx, row, rw, p, inRecord) {
    var pw = narrow ? 0 : range(p, .885, .9) * (1 - range(p, .94, .955));
    neuro.style.opacity = pw; neuro.style.visibility = pw > .002 ? 'visible' : 'hidden';
    var key = currentEp + '|' + idx + '|' + W + '|' + inRecord;
    if (key === uiKey) return;
    uiKey = key;
    if (rw > .01) decB.textContent = inRecord ? decisionText(row) : Z('Person approaching', '有人走近');
    if (p >= .885) {
      drawNeuro(ep, idx);
      nc.setAttribute('aria-label', 'Loom ' + row[1] + ' / ' + row[2] + ', DNp01 ' + row[5] + ' / ' + row[6] + ', DNp09 ' + row[7] + ', MDN ' + row[8] + ' Hz');
    }
  }

  /* ---------- 拖动旋转与进度拖动 ---------- */
  var drag = null, offAz = 0, offEl = 0, offAzT = 0, offElT = 0;
  canvas.addEventListener('pointerdown', function (e) {
    drag = { x: e.clientX, y: e.clientY, az: offAzT, el: offElT, pointerType: e.pointerType, id: e.pointerId, moved: false };
    canvas.setPointerCapture(e.pointerId); canvas.classList.add('drag');
  });
  canvas.addEventListener('pointermove', function (e) {
    if (!drag) return;
    var dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    offAzT = drag.az - dx * .32;
    if (drag.pointerType !== 'touch') offElT = clamp(drag.el + dy * .2, -22, 42);
    dirty = true;
  });
  function endDrag() { drag = null; canvas.classList.remove('drag'); }
  canvas.addEventListener('pointerup', endDrag);
  canvas.addEventListener('pointercancel', endDrag);

  var railDrag = false;
  function railFromEvent(e) { var r = railTrack.getBoundingClientRect(); goto(clamp((e.clientY - r.top) / r.height)); }
  railTrack.addEventListener('pointerdown', function (e) { railDrag = true; railTrack.setPointerCapture(e.pointerId); railFromEvent(e); e.preventDefault(); });
  railTrack.addEventListener('pointermove', function (e) { if (railDrag) railFromEvent(e); });
  railTrack.addEventListener('pointerup', function () { railDrag = false; });
  railTrack.addEventListener('pointercancel', function () { railDrag = false; });
  railTrack.addEventListener('lostpointercapture', function () { railDrag = false; });
  railTrack.addEventListener('keydown', function (e) {
    var d = { ArrowUp: -.01, ArrowLeft: -.01, ArrowDown: .01, ArrowRight: .01, PageUp: -.06, PageDown: .06 }[e.key];
    if (d) { goto(clamp(scrollP() + d)); e.preventDefault(); }
    if (e.key === 'Home') { goto(0); e.preventDefault(); }
    if (e.key === 'End') { goto(1); e.preventDefault(); }
  });

  $$('.dv button').forEach(function (b) { b.addEventListener('click', function () { setDrive(driveScn, b.dataset.m); dirty = true; }); });
  $$('.dvs button').forEach(function (b) { b.addEventListener('click', function () { setDrive(b.dataset.sc, 'brain'); dirty = true; }); });
  setDrive('wall', 'brain');
  $$('.mast button[data-p], .mast button[data-go]').forEach(function (b) {
    b.addEventListener('click', function () {
      if (b.dataset.go) $('#' + b.dataset.go).scrollIntoView({ behavior: reduceMq.matches ? 'auto' : 'smooth' });
      else goto(+b.dataset.p, true);
    });
  });

  /* ---------- 主循环 ---------- */
  var bootT = performance.now();
  var pNow = -1, dirty = true, tPulse = 0, last = performance.now(), v = new T.Vector3(), v2 = new T.Vector3(), lastP = -1;
  var col = new T.Color();
  function place(ui, wx, wy, wz, dx, dy, alpha) {
    if (ui.a === alpha && alpha === 0) return;
    ui.a = alpha;
    if (alpha <= .001) {
      ui.el.style.opacity = 0; ui.path.style.opacity = 0; ui.dot.style.opacity = 0; return;
    }
    v.set(wx, wy, wz).project(camera);
    var x = (v.x * .5 + .5) * W, y = (-v.y * .5 + .5) * H;
    var w = ui.w || (ui.w = ui.el.offsetWidth), h = ui.h || (ui.h = ui.el.offsetHeight);
    var lx = x + dx, ly = y + dy;
    var left = dx >= 0 ? lx + 6 : lx - w - 6;
    left = clamp(left, 8, W - w - 8);
    ui.el.style.transform = 'translate(' + left.toFixed(1) + 'px,' + (ly - h / 2).toFixed(1) + 'px)';
    ui.el.style.opacity = alpha;
    ui.path.setAttribute('d', 'M' + x.toFixed(1) + ' ' + y.toFixed(1) + 'L' + lx.toFixed(1) + ' ' + ly.toFixed(1));
    ui.path.style.opacity = alpha; ui.dot.style.opacity = alpha;
    ui.dot.setAttribute('cx', x.toFixed(1)); ui.dot.setAttribute('cy', y.toFixed(1));
  }

  // 标签放在 colX 外侧的空白处，折线加箭头指回 (wx,wy,wz)
  function placeCol(ui, wx, wy, wz, side, colX, yPx, alpha) {
    if (alpha <= .001) {
      if (ui.a !== 0) { ui.a = 0; ui.el.style.opacity = 0; ui.path.style.opacity = 0; ui.dot.style.opacity = 0; ui.el.style.pointerEvents = 'none'; }
      return;
    }
    ui.a = alpha;
    v.set(wx, wy, wz).project(camera);
    var x = (v.x * .5 + .5) * W, y = (-v.y * .5 + .5) * H;
    var w = ui.w || (ui.w = ui.el.offsetWidth), h = ui.h || (ui.h = ui.el.offsetHeight);
    var left = clamp(side < 0 ? colX - w : colX, 8, W - w - 8);
    ui.el.style.transform = 'translate(' + left.toFixed(1) + 'px,' + (yPx - h / 2).toFixed(1) + 'px)';
    ui.el.style.opacity = alpha;
    ui.el.style.pointerEvents = alpha > .5 && ui.el.classList.contains('rg') ? 'auto' : 'none';
    var ax = side < 0 ? left + w + 6 : left - 6, bx = ax - side * 18;
    var dx = x - bx, dy = y - yPx, len = Math.max(1, Math.hypot(dx, dy)), ux = dx / len, uy = dy / len;
    ui.path.setAttribute('d', 'M' + ax.toFixed(1) + ' ' + yPx.toFixed(1) + 'L' + bx.toFixed(1) + ' ' + yPx.toFixed(1) + 'L' + x.toFixed(1) + ' ' + y.toFixed(1) +
      'M' + (x - ux * 7 - uy * 3.4).toFixed(1) + ' ' + (y - uy * 7 + ux * 3.4).toFixed(1) + 'L' + x.toFixed(1) + ' ' + y.toFixed(1) + 'L' + (x - ux * 7 + uy * 3.4).toFixed(1) + ' ' + (y - uy * 7 - ux * 3.4).toFixed(1));
    ui.path.style.stroke = ui.color; ui.path.style.opacity = alpha * .85; ui.dot.style.opacity = 0;
  }

  function frame(now) {
    requestAnimationFrame(frame);
    var dt = clamp((now - last) / 1000, 0, .05); last = now;
    var reduced = reduceMq.matches;
    var target = scrollP();
    var prev = pNow;
    if (pNow < 0 || reduced) pNow = target;
    else { pNow += (target - pNow) * (1 - Math.exp(-dt * 7)); if (Math.abs(target - pNow) < 1e-5) pNow = target; }
    var p = pNow, moved = p !== prev;

    // 拖动偏移：跟手；滚动时逐渐回到分镜构图
    var scrollDelta = Math.abs(p - lastP); lastP = p;
    if (!drag && scrollDelta > 1e-5) { var dec = Math.exp(-scrollDelta * 22); offAzT *= dec; offElT *= dec; }
    var ek = reduced ? 1 : 1 - Math.exp(-dt * 12);
    var dAz = offAzT - offAz, dEl = offElT - offEl;
    offAz += dAz * ek; offEl += dEl * ek;
    var offMoving = Math.abs(dAz) > .01 || Math.abs(dEl) > .01;

    var heroIdle = !reduced && p < .07;
    var brainPhase = (p > .6 && p < .975) || (p > .45 && p < .516);
    if (!reduced && brainPhase) tPulse += dt;
    var animating = !reduced && window.scrollY < trackLen + H * .7;
    if (!moved && !offMoving && !animating && !dirty) return;
    dirty = false;

    var s = sample(p);
    renderer.toneMappingExposure = 1.05 * (reduced ? 1 : .05 + .95 * smooth((now - bootT) / 2200));
    var idle = heroIdle ? Math.sin(now * .00022) * 2.2 : 0;
    var frontSwing = currentEp === 'front' ? -123 * range(p, .868, .888) * (1 - range(p, .942, .968)) : 0; // 看到走来的人的正面
    var az = (s.az + frontSwing + idle + offAz) * Math.PI / 180, el = clamp(s.el + offEl, -18, 62) * Math.PI / 180;
    var R = s.r * (narrow ? clamp(1.05 / camera.aspect, 1.15, 2.1) : 1); // 竖屏按宽度取景
    camera.position.set(s.tx + R * Math.cos(el) * Math.sin(az), s.ty + R * Math.sin(el), s.tz + R * Math.cos(el) * Math.cos(az));
    camera.lookAt(s.tx, s.ty, s.tz);
    if (narrow) camera.setViewOffset(W, H, 0, H * .13, W, H); else camera.clearViewOffset();
    camera.updateMatrixWorld();

    var physK = reduced ? 0 : 1 - range(s.ex, .05, .4);
    if (!reduced) stepPhysics(dt, now, physK);
    setPose(s.a, physK); setExplode(s.ex);
    physCmdV = 0; physCmdW = 0;
    if (lidarHead && !reduced) lidarHead.rotation.y += dt * 9;

    // 聚焦：其余部件压暗（不用透明，避免排序问题）
    var f = null, fv = 0;
    for (var i = 0; i < FOCUS.length; i++) {
      var w = range(p, FOCUS[i].from - .012, FOCUS[i].from + .012) * (1 - range(p, FOCUS[i].to - .012, FOCUS[i].to + .012));
      if (w > fv) { fv = w; f = FOCUS[i]; }
    }
    for (var id in parts) {
      var pt = parts[id], d = f && !f.on.some(function (x) { return id.indexOf(x) === 0; }) ? f.dim * fv : 0;
      if (Math.abs(d - pt.dim) > .002) {
        pt.dim = d;
        for (var m = 0; m < pt.mats.length; m++) {
          var mm = pt.mats[m];
          mm.m.color.copy(mm.c).multiplyScalar(1 - d);
          mm.m.envMapIntensity = 1 - d * .9;
          mm.m.emissiveIntensity = mm.e * (1 - d * .75);
        }
        for (m = 0; m < pt.edges.length; m++) pt.edges[m].opacity = .34 * (1 - d);
      }
    }

    // 决策回放：人走近 -> 记录里的窗口 -> 由记录的 v、w 换算机身动作（当时底盘锁定，实际未动）
    var rw = range(p, .876, .89) * (1 - range(p, .94, .955));
    var mapW = range(p, .755, .77) * (1 - range(p, .858, .872));
    if (mapPick && Math.abs(p - mapPickP) > .012) mapPick = null;
    if (p > .75 && p < .87) setAct(mapPick || MAP_ORDER[Math.min(3, Math.floor(clamp((p - .757) / .106) * 4))]);
    var act = MAP[mapAct];
    var ep = D.replay.episodes[currentEp], rows = ep.rows;
    var t0 = rows[0][0], span = rows[rows.length - 1][0] - t0 + .2, total = PREROLL + span + HOLD_END;
    if (reduced) rt = clamp((p - .885) / (.94 - .885)) * total;
    else if (rw > .02) { rt += dt; if (rt > total) rt = 0; } else rt = 0;
    var Tr = rt - PREROLL, inRecord = p >= .885 && Tr >= 0;
    var rIdx = 0;
    if (p < .885) rIdx = peakIdx(rows);
    else for (var ri = 0; ri < rows.length; ri++) if (rows[ri][0] - t0 <= Tr) rIdx = ri;
    var row = rows[rIdx];
    if (rw > .5 && inRecord) {
      chTarget.set(clamp(row[1] / 150), clamp(row[2] / 150), row[3] + row[4] > 0 && row[1] + row[2] < 60 ? .9 : .12, clamp(row[8] / 40));
      kTarget.set(.35 + clamp(row[1] + row[2], 0, 300) / 460, .35 + clamp(row[1] + row[2], 0, 300) / 460, clamp((row[3] + row[4]) / 240));
    } else if (rw > .5) { chTarget.set(0, 0, .5, 0); kTarget.set(.3, .3, .9); }
    else if (mapW > .5) { chTarget.fromArray(act.ch); kTarget.fromArray(act.k); }
    else { chTarget.fromArray(SCN[currentScn].ch); kTarget.fromArray(SCN[currentScn].k); }
    updateReplayUi(ep, rIdx, row, rw, p, inRecord);
    // 记录指令的积分（构建时算好；输入过期的窗口按 0）；循环末尾回到起点
    var yaw = 0, mvx = 0, mvz = 0;
    if (rw > .001 && inRecord) {
      var rn = rows[Math.min(rows.length - 1, rIdx + 1)], ra = row, gapT = Math.max(.01, rn[0] - ra[0]), fT = clamp((Tr + t0 - ra[0]) / gapT);
      var backHome = 1 - smooth((rt - (total - .9)) / .9);
      yaw = lerp(ra[13], rn[13], fT) * backHome; mvx = lerp(ra[14], rn[14], fT) * backHome; mvz = lerp(ra[15], rn[15], fT) * backHome;
    }
    robot.rotation.y = yaw * rw;
    wedges.rotation.y = yaw * rw; intent.rotation.y = yaw * rw;
    // 地面网格、起点残影和轨迹线都固定在世界里，机器人留在画面中心，靠它们看出位移
    worldG.visible = rw > .01;
    worldG.position.set(-mvx * rw, 0, -mvz * rw);
    gridMat.opacity = .34 * rw; startMat.opacity = .85 * rw;
    trailGeo.attributes.position.setXYZ(1, mvx * rw, .014, mvz * rw); trailGeo.attributes.position.needsUpdate = true;
    trailMat.opacity = .95 * rw;
    // 决定瞬间的脉冲环
    var sinceEscape = Tr - (ep.first_escape_t - t0);
    var pu = rw > .5 && sinceEscape > 0 && sinceEscape < 1.1 ? sinceEscape / 1.1 : -1;
    pulse.visible = pu >= 0;
    if (pu >= 0) { var ps = .5 + pu * 2.3; pulse.scale.set(ps, ps, 1); pulseMat.opacity = (1 - pu) * .85; }
    var movedM = Math.hypot(mvx, mvz), turnDeg = Math.abs(yaw) * 180 / Math.PI;
    if (rw > .01) {
      var moveKey = inRecord ? row[11].toFixed(2) + '|' + row[12].toFixed(2) + '|' + Math.round(movedM * 20) + '|' + Math.round(turnDeg / 2) : '-';
      if (moveKey !== moveUi) {
        moveUi = moveKey;
        decS.textContent = inRecord ? 'v ' + row[11].toFixed(2) + '  w ' + row[12].toFixed(2) + Z('  command integral ', '  指令积分 ') + movedM.toFixed(2) + ' m ' + Math.round(turnDeg) + '°' : '';
      }
    }
    if (rw > .5 && inRecord) { physCmdV = row[11]; physCmdW = row[12]; }
    if (mapW > .5) { physCmdV = act.v; physCmdW = act.w; } // 示意：只驱动轮腿动画，车不移动
    // 人：路径和走法都是示意（记录没有人的坐标）。全程在画面内走来，在记录开始后约 1 s 到位并面向机器人
    var path = PATHS[currentEp];
    var uWalk = clamp(rt / (PREROLL + 1));
    // 匀速走，最后 14% 减速停下（位置与速度在衔接点连续）
    var uEase = uWalk < .86 ? uWalk / .93 : 1 - Math.pow(1 - uWalk, 2) / (2 * .14 * .93);
    uEase = clamp(uEase);
    var pathLen = Math.hypot(path[2] - path[0], path[3] - path[1]);
    var walkAmp = clamp((1 - uWalk) / .1);
    walkPose(uEase * pathLen * Math.PI * 2 / 1.42, walkAmp);
    var px = lerp(path[0], path[2], uEase) - mvx, pz = lerp(path[1], path[3], uEase) - mvz;
    person.visible = rw > .01;
    person.position.set(px, 0, pz);
    var dirx = (path[2] - path[0]) / pathLen, dirz = (path[3] - path[1]) / pathLen;
    person.lookAt(lerp(-0 + 0, px + dirx, walkAmp), 0, lerp(0, pz + dirz, walkAmp));
    var endFade = 1 - smooth((rt - (total - .5)) / .5), startFade = smooth(rt / .5);
    personMat.opacity = .9 * rw * (reduced ? 1 : endFade * startFade);
    intent.visible = rw > .01;
    var tag = inRecord ? row[16] : 'hold';
    arrowF.visible = rw > .01 && tag === 'forward'; arrowB.visible = rw > .01 && tag === 'back';
    arcL.visible = rw > .01 && tag === 'left'; arcR.visible = rw > .01 && tag === 'right';
    [arrowF, arrowB, arcL, arcR].forEach(function (a) { a.material.opacity = rw * .95; });

    // 地面与 LiDAR 章节
    var legsW = range(p, .225, .25) * (1 - range(p, .325, .345));
    footRing.material.opacity = legsW * .55; turnMark.material.opacity = legsW;
    var mw = range(p, .35, .372) * (1 - range(p, .498, .516));
    mapPts.visible = mw > .001; mapMat.uniforms.uA.value = mw;
    mapMat.uniforms.uReveal.value = lerp(0, 62, range(p, .355, .415));
    pathLine.visible = mw > .01; pathLine.material.opacity = .85 * range(p, .405, .42) * (1 - range(p, .445, .458));
    stageFloor.forEach(function (o) { o.visible = mw < .7; });
    mapMat.uniforms.uFloor.value = 1 - .92 * range(p, .446, .464);
    siteMark.material.opacity = range(p, .39, .405) * (1 - range(p, .445, .458));
    var lw = range(p, .452, .466) * (1 - range(p, .498, .516));
    // 逼近片段：机器人留在画面中心，云图反向移动
    var driveTotal = DRIVE.dur / DRIVE_SPEED + DRIVE_HOLD;
    if (reduced) driveT = clamp((p - .46) / .04) * driveTotal;
    else if (lw > .02) {
      driveT += dt;
      if (driveT > driveTotal) {
        if (driveMode === 'brain') setDrive(driveScn, 'blind');
        else setDrive(SC_ORDER[(SC_ORDER.indexOf(driveScn) + 1) % SC_ORDER.length], 'brain');
      }
    } else { driveT = 0; if (driveMode !== 'brain' || driveScn !== 'wall') setDrive('wall', 'brain'); }
    var dSec = Math.min(DRIVE.dur, driveT * DRIVE_SPEED), dk = 0;
    while (dk < DRIVE.n - 2 && DRIVE.steps[dk + 1][3] <= dSec) dk++;
    var sa0 = DRIVE.steps[dk], sa1 = DRIVE.steps[dk + 1], dF = clamp((dSec - sa0[3]) / Math.max(.01, sa1[3] - sa0[3]));
    if (lw > .02 && driveT * DRIVE_SPEED < DRIVE.dur) {
      var dtRec = Math.max(.05, sa1[3] - sa0[3]), ddx = sa1[0] - sa0[0], ddz = sa1[1] - sa0[1];
      var fwdD = ddx * Math.sin(sa0[2]) + ddz * Math.cos(sa0[2]);
      var dh = wrapPi(sa1[2] - sa0[2]);
      physCmdV = fwdD / dtRec * DRIVE_SPEED; physCmdW = dh / dtRec * DRIVE_SPEED;
    }
    var mwOn = lw > .001;
    var dpx = mwOn ? lerp(sa0[0], sa1[0], dF) : 0, dpz = mwOn ? lerp(sa0[1], sa1[1], dF) : 0, dph = mwOn ? lerp(sa0[2], sa1[2], dF) : 0;
    mapPts.matrix.makeRotationY(-dph).multiply(mapShift.makeTranslation(-dpx, 0, -dpz));
    mapPts.matrixWorldNeedsUpdate = true;
    pathLine.matrix.copy(mapPts.matrix); pathLine.matrixWorldNeedsUpdate = true;
    blindLine.matrix.copy(mapPts.matrix); blindLine.matrixWorldNeedsUpdate = true;
    blindDot.userData.holder.matrix.copy(mapPts.matrix); blindDot.userData.holder.matrixWorldNeedsUpdate = true;
    brainPath.matrix.copy(mapPts.matrix); brainPath.matrixWorldNeedsUpdate = true;
    var blindA = range(p, .46, .47) * (1 - range(p, .498, .516));
    blindLine.material.opacity = .6 * blindA; blindDot.material.opacity = .85 * blindA;
    blindLine.visible = blindDot.visible = blindA > .01;
    brainPath.material.opacity = .85 * blindA; brainPath.visible = blindA > .01;
    rays.visible = hits.visible = lw > .02;
    rays.material.opacity = .9 * lw; hits.material.opacity = .95 * lw;
    var freeL = 6, freeR = 6;
    for (var si2 = 0; si2 < 24; si2++) {
      var rr = lerp(DRIVE.r(dk, si2), DRIVE.r(dk + 1, si2), dF);
      var ctr = ((si2 + .5) * 15 - 180) * Math.PI / 180;
      if (Math.abs(ctr) <= Math.PI / 6 + 1e-6) { if (ctr > 0) freeL = Math.min(freeL, rr); else freeR = Math.min(freeR, rr); }
      driveTheta[si2] = rr >= 5.99 ? 0 : 2 * Math.atan(.3 / (2 * rr));
      if (lw > .02) {
        var ex0 = Math.sin(ctr) * rr, ez0 = Math.cos(ctr) * rr, lit = clamp((driveTheta[si2] - .1) / .3);
        var seen = rr < 5.99;
        rayPos[si2 * 6] = 0; rayPos[si2 * 6 + 1] = LIDAR_Y + .03; rayPos[si2 * 6 + 2] = LIDAR_Z;
        var nearRay = seen && lit > .02;
        rayPos[si2 * 6 + 3] = nearRay ? ex0 : 0; rayPos[si2 * 6 + 4] = nearRay ? .55 : LIDAR_Y + .03; rayPos[si2 * 6 + 5] = nearRay ? ez0 : LIDAR_Z;
        col.setHex(COLORS.LC4).multiplyScalar(.2 + lit * 1.1);
        if (!seen) col.setRGB(0, 0, 0); else if (lit < .02) col.setRGB(.1, .105, .11);
        rayCol[si2 * 6] = col.r * .4; rayCol[si2 * 6 + 1] = col.g * .4; rayCol[si2 * 6 + 2] = col.b * .4;
        rayCol[si2 * 6 + 3] = col.r; rayCol[si2 * 6 + 4] = col.g; rayCol[si2 * 6 + 5] = col.b;
        hitPos[si2 * 3] = ex0; hitPos[si2 * 3 + 1] = nearRay ? .55 : -9; hitPos[si2 * 3 + 2] = ez0;
        hitCol[si2 * 3] = seen ? Math.max(col.r, .5) : 0; hitCol[si2 * 3 + 1] = seen ? Math.max(col.g, .32) : 0; hitCol[si2 * 3 + 2] = seen ? Math.max(col.b, .28) : 0;
      }
    }
    rayGeo.attributes.position.needsUpdate = rayGeo.attributes.color.needsUpdate = true;
    hitGeo.attributes.position.needsUpdate = hitGeo.attributes.color.needsUpdate = true;
    var dRec = DRIVE.rec[dk], freeAhead = Math.min(freeL, freeR);
    var decA = Math.max(rw, lw);
    decisionEl.style.opacity = decA; decisionEl.style.visibility = decA > .002 ? 'visible' : 'hidden';
    if (lw > .02) {
      var isStopped = Math.abs(dRec[7]) < .01;
      if (driveT * DRIVE_SPEED < DRIVE.dur) stuckS = isStopped ? stuckS + dt * DRIVE_SPEED : 0;
      var driveKey = driveMode + '|' + driveScn + '|' + dk + '|' + Math.round(stuckS);
      if (driveKey !== driveUi) {
        driveUi = driveKey; moveUi = ''; uiKey = '';
        if (driveMode === 'blind') {
          decB.textContent = isStopped ? Z('Stopped', '被保护拦停') : Z('Straight ahead', '恒速直行');
          decS.textContent = isStopped ? Z('by the safety guard, stuck ', '已卡住 ') + Math.round(stuckS) + ' s' : Z('clearance ', '离障 ') + dRec[3].toFixed(2) + ' m';
        } else {
          decB.textContent = STATE_ZH[dRec[2]] || (isStopped ? Z('Hold', '停住') : dRec[2]);
          decS.textContent = Z('clearance ', '离障 ') + dRec[3].toFixed(2) + ' m  LC9 ' + dRec[0] + '／' + dRec[1] + ' Hz' + (isStopped ? Z('  stopped ', '  已停 ') + Math.round(stuckS) + ' s' : '');
        }
      }
      if (driveMode === 'blind' && DRIVE.stopT) { // 被拦下瞬间的脉冲环
        var stopAge = driveT * DRIVE_SPEED - DRIVE.stopT;
        var span2 = 1.1 * DRIVE_SPEED;
        if (stopAge > 0 && stopAge < span2) { var sp = stopAge / span2; pulse.visible = true; pulse.scale.set(.5 + sp * 2.3, .5 + sp * 2.3, 1); pulseMat.opacity = (1 - sp) * .9; }
      }
      // 记录里的物体（有人挡路的场景）
      var obj = dRec[8];
      if (obj && !(rw > .01)) {
        var objNext = (DRIVE.rec[dk + 1] && DRIVE.rec[dk + 1][8]) || obj;
        var ox0 = lerp(obj[0], objNext[0], dF), oz0 = lerp(obj[1], objNext[1], dF);
        v2.set(ox0, 0, oz0).applyMatrix4(mapPts.matrix);
        person.visible = true; person.position.set(v2.x, 0, v2.z); person.lookAt(0, 0, 0);
        var oSpeed = Math.hypot(objNext[0] - obj[0], objNext[1] - obj[1]);
        objWalk += Math.max(0, oSpeed) * dt * DRIVE_SPEED / Math.max(.05, sa1[3] - sa0[3]);
        walkPose(objWalk * Math.PI * 2 / 1.42, clamp(oSpeed * 12));
        personMat.opacity = .9 * lw * (.25 + .75 * clamp((camera.position.distanceTo(person.position) - 3.5) / 2)); // 离镜头太近时变淡
      }
    }
    // 带脑时脑亮起，不带脑时脑熄灭
    dbw += ((driveMode === 'brain' ? lw : 0) - dbw) * (reduced ? 1 : 1 - Math.exp(-dt * 4));
    if (dbw < .004) dbw = 0;
    wedges.visible = lw > .01 || rw > .01;
    wedges.scale.setScalar(rw > .01 ? .84 : .72);
    if (rw > .01) {
      for (i = 0; i < SECTORS; i++) {
        var sa = (i + .5) * 15 - 180, isFront = Math.abs(sa) <= 30;
        col.setRGB(.022, .023, .025);
        if (isFront) col.setHex(COLORS.LC9).multiplyScalar(.05 + clamp((row[3] + row[4]) / 240) * .34);
        var side = !isFront && sa > 0 ? row[1] : !isFront ? row[2] : 0;
        if (side > 0) col.setHex(COLORS.LC4).multiplyScalar(.08 + clamp(side / 300) * .8);
        col.multiplyScalar(rw);
        wedges.setColorAt(i, col);
      }
      wedges.instanceColor.needsUpdate = true;
    } else if (wedges.visible) {
      for (i = 0; i < SECTORS; i++) {
        var cAng = (i + .5) * 15 - 180, inFront = Math.abs(cAng) <= 30;
        var lt = clamp((driveTheta[i] - .1) / .3);
        col.setRGB(.026, .027, .029);
        if (inFront) col.setHex(COLORS.LC9).multiplyScalar(.1 + clamp((freeAhead - .5) / 2) * .55);
        if (lt > .02 && !inFront) col.setHex(COLORS.LC4).multiplyScalar(.1 + lt * .9);
        if (lt > .02 && inFront && freeAhead < 2) col.setHex(COLORS.LC4).multiplyScalar(.1 + lt * .95);
        col.multiplyScalar(lw);
        wedges.setColorAt(i, col);
      }
      wedges.instanceColor.needsUpdate = true;
    }

    // 脑
    var brainW = range(p, .595, .635) * (1 - range(p, .945, .97));
    brain.visible = brainW > .002 || dbw > .004;
    // 脑区一章把脑放大，给颜色和标签留出空间；.69 前回到原尺寸，信号流的端点依赖原尺寸
    var regZoom = range(p, .62, .642) * (1 - range(p, .668, .688));
    brain.scale.setScalar(BRAIN_SCALE * (1 + .3 * regZoom)); brain.position.y = BRAIN_POS.y - .08 * regZoom;
    brainUni.uForm.value = dbw > brainW ? 1 : range(p, .6, .63);
    var regLate = range(p, .67, .69);
    brainUni.uRegion.value = Math.max(range(p, .618, .636) * (1 - regLate), .2 * regLate * (1 - range(p, .865, .88)));
    brainUni.uA.value = Math.max(brainW, dbw * .9);
    hiUni.uHi.value = Math.max(range(p, .67, .695) * brainW, dbw);
    hiUni.uDn.value = Math.max(range(p, .735, .76) * brainW, dbw);
    pulseUni.uFlow.value = dbw > .02 ? 1.08 : lerp(.0, 1.08, range(p, .69, .79)) * (brainW > .02 ? 1 : 0);
    if (dbw > .02) { // 输入取自当次记录
      chTarget.set(clamp(dRec[5] * 8), clamp(dRec[6] * 8), .9, 0);
      kTarget.set(.3 + clamp(dRec[5] * 8) * .7, .3 + clamp(dRec[6] * 8) * .7, clamp((dRec[0] + dRec[1]) / 240));
    }
    pulseUni.uT.value = reduced ? .37 : tPulse;
    var ease = reduced ? 1 : 1 - Math.exp(-dt * 5);
    var uc = pulseUni.uCh.value, uk = hiUni.uK.value;
    var lagging = Math.abs(uc.x - chTarget.x) + Math.abs(uc.y - chTarget.y) + Math.abs(uc.z - chTarget.z) + Math.abs(uc.w - chTarget.w) > .005;
    uc.lerp(chTarget, ease); uk.lerp(kTarget, ease);
    dTarget.set(lerp(1, act.d[0], mapW), lerp(1, act.d[1], mapW), lerp(1, act.d[2], mapW), lerp(1, act.d[3], mapW));
    hiUni.uD.value.lerp(dTarget, ease); hiUni.uDo.value = 1 - .85 * mapW;
    if (lagging) dirty = true;

    // 机身与脑之间的信号（示意）
    var flowOff = 1 - range(p, .945, .965);
    var flowT = reduced ? 0 : tPulse * .42;
    var cs = pulseUni.uCh.value;
    upL.m.color.setHex(cs.z > .5 ? COLORS.LC9 : COLORS.LC4); upR.m.color.copy(upL.m.color);
    var upW = Math.max(range(p, .69, .715), dbw);
    upL.update(upW * flowOff * Math.max(cs.x, cs.z), flowT);
    upR.update(upW * flowOff * Math.max(cs.y, cs.z), flowT);
    downS.update(Math.max(range(p, .755, .78), dbw) * flowOff * (rw > .5 ? clamp(.15 + Math.max(row[5], row[6]) / 120) : 1), flowT);

    // 地面反射：先画镜像机器人，再叠地面与其它内容（场地云图段不做）
    var bgTex = scene.background;
    if (mw < .05) {
      var others = scene.children.filter(function (o) { return o !== robot && !o.isLight; });
      var was = others.map(function (o) { return o.visible; });
      others.forEach(function (o) { o.visible = false; });
      robot.scale.y = -1; robot.updateMatrixWorld(true);
      renderer.shadowMap.autoUpdate = false;
      renderer.autoClear = true;
      renderer.render(scene, camera);
      robot.scale.y = 1; robot.updateMatrixWorld(true);
      others.forEach(function (o, ix) { o.visible = was[ix]; });
      renderer.shadowMap.autoUpdate = true;
      scene.background = null; renderer.autoClear = false;
      renderer.clearDepth();
    }
    renderer.render(scene, camera);
    scene.background = bgTex; renderer.autoClear = true;

    // 文案
    for (i = 0; i < cards.length; i++) {
      var c = cards[i], rampIn = .012;
      // one-sided ramps: out by `to`, in from `from`, so two captions never overlap
      var o = range(p, c.from, c.from + 2 * rampIn) * (1 - range(p, c.to - 2 * rampIn, c.to));
      if (o !== c.shown) {
        c.shown = o;
        c.el.style.opacity = o;
        c.el.style.visibility = o > .002 ? 'visible' : 'hidden';
        c.el.classList.toggle('live', o > .5);
        if (!reduced) {
          c.el.style.setProperty('--ty', ((1 - o) * (p < c.from + 2 * rampIn ? 26 : -26)).toFixed(1) + 'px');
        }
      }
    }

    // 数字随滚动跳到记录值；每帧更新，停在哪里都不会卡在半途
    if (!reduced) {
      for (i = 0; i < cards.length; i++) {
        var cn = cards[i];
        if (!cn.nums.length || cn.shown <= .002) continue;
        var rise = smooth(clamp((p - cn.from + .012) / .03));
        for (var ni = 0; ni < cn.nums.length; ni++) {
          var txt = fmtNum(cn.nums[ni], cn.nums[ni].v * (1 - Math.pow(1 - rise, 3)));
          if (cn.nums[ni].el.textContent !== txt) cn.nums[ni].el.textContent = txt;
        }
      }
    }

    // 标注
    var showAny = !narrow;
    var viewFade = 1 - range(Math.abs(offAz) + Math.abs(offEl), 8, 26);
    for (id in parts) {
      var q = parts[id]; if (!q.ui) continue;
      var alpha = 0;
      if (showAny) {
        for (i = 0; i < LABELS.sets.length; i++) {
          var se = LABELS.sets[i];
          if (se.ids.indexOf(id) >= 0) alpha = Math.max(alpha, range(p, se.from, se.from + .012) * (1 - range(p, se.to - .008, se.to)));
        }
      }
      if (alpha > 0) {
        v2.copy(q.anchor).applyMatrix4(q.inner.matrix).add(q.outer.position);
        var dir = LABEL_DIR[id];
        place(q.ui, v2.x, v2.y, v2.z, dir[0], dir[1], alpha * viewFade);
      } else place(q.ui, 0, 0, 0, 0, 0, 0);
    }
    brain.updateMatrixWorld();
    // 脑两侧的标签列：列位置由脑的屏幕范围决定，文字不压在脑上
    v2.set(1.06, 0, 0).applyMatrix4(brain.matrixWorld).project(camera); var edgeA = (v2.x * .5 + .5) * W;
    v2.set(-1.06, 0, 0).applyMatrix4(brain.matrixWorld).project(camera); var edgeB = (v2.x * .5 + .5) * W;
    var colL = Math.min(edgeA, edgeB) - 26, colR = Math.max(edgeA, edgeB) + 26;
    v2.copy(brain.position).project(camera); var brainCy = (-v2.y * .5 + .5) * H;
    var slotGap = clamp(H * .092, 50, 80);
    function slotY(ix, n) { return Math.max(70, brainCy + (ix - (n - 1) / 2) * slotGap); }
    var regA = (narrow ? 0 : 1) * range(p, .628, .64) * (1 - range(p, .664, .674)) * viewFade;
    if (regA < .5 && brainUni.uFocus.value >= 0) brainUni.uFocus.value = -1;
    [-1, 1].forEach(function (c) {
      rgByCol[c].forEach(function (r, ix) {
        v2.copy(r.pos).applyMatrix4(brain.matrixWorld);
        placeCol(r.ui, v2.x, v2.y, v2.z, c, c < 0 ? colL : colR, slotY(ix, rgByCol[c].length), regA);
      });
    });
    var mapA = (narrow ? 0 : 1) * range(p, .757, .772) * (1 - range(p, .855, .866)) * viewFade;
    var repA = (narrow ? 0 : 1) * range(p, .885, .9) * (1 - range(p, .935, .95)) * viewFade;
    dnLabels.forEach(function (d) {
      var useMap = p < .87, lay = useMap ? d.map : d.rep, c = lay[0];
      v2.copy(c < 0 ? d.posL : d.posR).applyMatrix4(brain.matrixWorld);
      var hit = act.on.indexOf(d.t) >= 0;
      placeCol(d.ui, v2.x, v2.y, v2.z, c, c < 0 ? colL : colR, slotY(lay[1], useMap ? 4 : 2), useMap ? mapA * (hit ? 1 : .3) : repA);
    });
    inLabels.forEach(function (d) {
      v2.copy(d.pos).applyMatrix4(brain.matrixWorld);
      placeCol(d.ui, v2.x, v2.y, v2.z, -1, colL, slotY(d.slot, 3), mapA * (act.on.indexOf(d.t) >= 0 ? 1 : .3));
    });
    var pA = (narrow ? 0 : 1) * Math.max(rw, lw > .02 && dRec[8] ? lw : 0) * viewFade;
    v2.set(person.position.x, 1.72, person.position.z).project(camera);
    var headOn = Math.abs(v2.x) < .86 && Math.abs(v2.y) < .94 ? 1 : 0;
    place(personLabel, person.position.x, 1.72, person.position.z, currentEp === 'right' ? -46 : 46, -22, pA * headOn * personMat.opacity / .9);
    v2.copy(blindDot.position).applyMatrix4(blindDot.userData.holder.matrix);
    place(blindLabel, v2.x, v2.y, v2.z, 26, -22, (narrow ? 0 : 1) * blindLine.material.opacity / .6 * viewFade * (driveMode === 'brain' ? 1 : 0));
    place(noBrainLabel, 0, BRAIN_POS.y, BRAIN_POS.z, -22, 0, (narrow ? 0 : 1) * lw * (driveMode === 'blind' ? 1 : 0) * (1 - dbw) * viewFade);
    var upA = (narrow ? 0 : 1) * range(p, .695, .715) * flowOff;
    upR.curve.getPoint(.45, v2); place(upLabel, v2.x, v2.y, v2.z, -92, 12, upA * viewFade);
    var downA = (narrow ? 0 : 1) * range(p, .765, .785) * flowOff;
    downS.curve.getPoint(.62, v2); place(downLabel, v2.x, v2.y, v2.z, 112, 8, downA * viewFade);

    // 进度 UI
    railFill.style.height = (p * 100).toFixed(2) + '%';
    railThumb.style.top = (p * 100).toFixed(2) + '%';
    railTrack.setAttribute('aria-valuenow', Math.round(p * 100));
    lastEx = Math.round(s.ex * 100);

    // 结果段落滚入后不再显示固定层
    var past = window.scrollY > trackLen + H * .55;
    var rail = $('#rail'); rail.style.visibility = past ? 'hidden' : 'visible';
    $('.mast').style.visibility = past ? 'hidden' : 'visible';
  }

  window.addEventListener('resize', resize);
  window.addEventListener('scroll', function () { dirty = true; }, { passive: true });
  reduceMq.addEventListener('change', function () { dirty = true; });
  setScn('single');
  resize();
  var deep = /[#&]p=([0-9.]+)/.exec(location.hash);
  if (deep) goto(clamp(+deep[1]));
  window.addEventListener('hashchange', function () {
    var m = /[#&]p=([0-9.]+)/.exec(location.hash);
    if (m) { goto(clamp(+m[1])); dirty = true; }
  });
  requestAnimationFrame(frame);

  // 只读调试入口：验证用
  window.__xt = {
    p: function () { return pNow; },
    explode: function () { return lastEx; },
    offset: function (id) { return parts[id].outer.position.toArray(); },
    drag: function () { return [offAz, offEl]; },
    info: function () { return renderer.info.render; },
    jump: function (p) { goto(p); pNow = p; lastP = p; dirty = true; }
  };
})();
