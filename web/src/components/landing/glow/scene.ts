import * as THREE from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";

// The glow hero's 3D world: a clay dollhouse at night, cut open at the front,
// with the six machines of the sample home in their rooms. A small warm light
// (the nightlight) travels a path room to room; each machine's status light and
// its room's lamp come on as it passes. Everything the page scrolls through is
// one View, which GlowLanding tweens with GSAP; this file only draws it.

export type View = {
  tx: number; ty: number; tz: number; // where the camera looks
  zoom: number;
  az: number; el: number; // camera angle around and above, in degrees
  ox: number; // focal point's offset from screen centre, as a share of the width (wide screens)
  oy: number; // the same, upward, as a share of the height (narrow screens)
  follow: number; // 0..1: how much the camera follows the light instead of (tx,ty,tz)
  trail: number; // 0..1: how far the light has travelled
  rings: number; // 0..1: the "checking" pulse around the light
  done: number; // 0..1: the Pi is fixed
  lit: number; // 0..1: every room warm
  orb: number; // 0..1: pulses flow along the whole wire
};

const BG = 0x11141f;
const CLAY = {
  ground: 0x232838,
  wall: 0x535a73,
  floor: 0x646b85,
  thing: 0x737a94,
  soft: 0x8a90a8,
};
const WARM = new THREE.Color(0xffc65a);
const OK = new THREE.Color(0x8fd6a8);
const WARN = new THREE.Color(0xf5a83a);
const OFF = new THREE.Color(0x232a40);

export function createScene(canvas: HTMLCanvasElement, opts: { calm: boolean }) {
  // Antialiasing happens in the post target (MSAA), so the canvas itself needs none.
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: "high-performance" });
  // Quality steps down on its own if frames run slow: pixel ratio first, then bloom.
  const LEVELS = [Math.min(window.devicePixelRatio, 1.5), Math.min(window.devicePixelRatio, 1.25), 1];
  let level = 0;
  renderer.setPixelRatio(LEVELS[0]);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  // Nothing that casts a shadow ever moves, so the shadow map is drawn once.
  renderer.shadowMap.autoUpdate = false;
  renderer.shadowMap.needsUpdate = true;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.setClearColor(BG, 1);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(BG);
  scene.fog = new THREE.Fog(BG, 62, 96); // hides where the ground ends

  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 300);

  // ---------- Light: moon, sky, and the warm ones that come on ----------
  scene.add(new THREE.HemisphereLight(0x8d97c2, 0x1a1c26, 1.25));
  const moon = new THREE.DirectionalLight(0xc4cdf2, 1.9);
  moon.position.set(14, 22, 12);
  moon.castShadow = true;
  moon.shadow.mapSize.set(2048, 2048);
  moon.shadow.camera.left = -18;
  moon.shadow.camera.right = 18;
  moon.shadow.camera.top = 18;
  moon.shadow.camera.bottom = -18;
  moon.shadow.bias = -0.0006;
  moon.shadow.radius = 4;
  scene.add(moon);

  // Matte clay: Lambert reads the same as a rough standard material at a fraction of the cost.
  const clay = (color: number) => new THREE.MeshLambertMaterial({ color });
  const mats = {
    ground: clay(CLAY.ground),
    wall: clay(CLAY.wall),
    floor: clay(CLAY.floor),
    thing: clay(CLAY.thing),
    soft: clay(CLAY.soft),
  };

  const geos: THREE.BufferGeometry[] = [];
  function box(w: number, h: number, d: number, x: number, y: number, z: number, mat = mats.thing, round = 0.06) {
    const g = round > 0 ? new RoundedBoxGeometry(w, h, d, 3, Math.min(round, w / 2, h / 2, d / 2)) : new THREE.BoxGeometry(w, h, d);
    geos.push(g);
    const m = new THREE.Mesh(g, mat);
    m.position.set(x, y + h / 2, z); // y is the bottom
    m.castShadow = true;
    m.receiveShadow = true;
    scene.add(m);
    return m;
  }
  function cyl(rt: number, rb: number, h: number, x: number, y: number, z: number, mat = mats.thing, seg = 24) {
    const g = new THREE.CylinderGeometry(rt, rb, h, seg);
    geos.push(g);
    const m = new THREE.Mesh(g, mat);
    m.position.set(x, y + h / 2, z);
    m.castShadow = true;
    m.receiveShadow = true;
    scene.add(m);
    return m;
  }

  // ---------- Ground ----------
  const groundGeo = new THREE.CircleGeometry(60, 64);
  geos.push(groundGeo);
  const ground = new THREE.Mesh(groundGeo, mats.ground);
  ground.rotation.x = -Math.PI / 2;
  ground.receiveShadow = true;
  scene.add(ground);

  // ---------- The house: x -6..6, z -3..3; floors at 0, 3 and 6 ----------
  box(12.6, 0.3, 6.6, 0, -0.3, 0, mats.floor, 0.08); // base
  box(12.6, 0.25, 6.3, 0, 2.75, -0.15, mats.floor, 0.05); // first floor
  box(12.6, 0.25, 6.3, 0, 5.75, -0.15, mats.floor, 0.05); // attic floor
  box(12.6, 5.75, 0.25, 0, 0, -3.18, mats.wall, 0.04); // back wall, two storeys
  box(0.25, 5.75, 6.3, -6.18, 0, -0.15, mats.wall, 0.04); // left wall
  box(0.2, 2.75, 5.6, -2.5, 0, -0.4, mats.wall, 0.03); // garage | hall
  box(0.2, 2.75, 5.6, 0.5, 0, -0.4, mats.wall, 0.03); // hall | living
  box(0.2, 2.75, 5.6, 0.5, 3, -0.4, mats.wall, 0.03); // study | kids
  // Doorways: a darker block in each partition reads as an opening.
  box(0.22, 1.9, 0.9, -2.5, 0, -0.8, mats.ground, 0.02);
  box(0.22, 1.9, 0.9, 0.5, 0, 0.6, mats.ground, 0.02);
  box(0.22, 1.9, 0.9, 0.5, 3, 0.2, mats.ground, 0.02);

  // Roof: only the back slope and the left gable, so the attic stays open.
  const roofGeo = new RoundedBoxGeometry(13.2, 0.28, 4.9, 2, 0.08);
  geos.push(roofGeo);
  const roof = new THREE.Mesh(roofGeo, mats.wall);
  roof.position.set(0, 7.6, -1.6);
  roof.rotation.x = -Math.PI / 4;
  roof.castShadow = roof.receiveShadow = true;
  scene.add(roof);
  const gable = new THREE.Shape();
  gable.moveTo(-3.25, 0);
  gable.lineTo(3.1, 0);
  gable.lineTo(0, 3.2);
  gable.closePath();
  const gableGeo = new THREE.ExtrudeGeometry(gable, { depth: 0.25, bevelEnabled: false });
  geos.push(gableGeo);
  const gableMesh = new THREE.Mesh(gableGeo, mats.wall);
  gableMesh.rotation.y = Math.PI / 2;
  gableMesh.position.set(-6.3, 6, 0);
  gableMesh.castShadow = gableMesh.receiveShadow = true;
  scene.add(gableMesh);
  box(0.8, 2.2, 0.8, 3.6, 7.6, -1.9, mats.wall, 0.05); // chimney

  // Windows on the back wall: moonlit panes.
  const paneMat = new THREE.MeshLambertMaterial({ color: 0x1d2440, emissive: 0x3b4d8f, emissiveIntensity: 0.35 });
  for (const [x, y, w] of [
    [-4.3, 0.9, 1.6], [-1, 1.1, 0.9], [3.2, 0.9, 2.2], [-3.6, 3.9, 1.8], [3.4, 3.9, 1.8],
  ] as const) {
    box(w, 1.2, 0.06, x, y, -3.03, paneMat, 0.02);
  }

  // ---------- Furniture, so each room reads as a room ----------
  // Garage: a car and a shelf
  box(1.5, 0.55, 2.4, -4.3, 0.2, 0.9, mats.soft, 0.25);
  box(1.3, 0.5, 1.3, -4.3, 0.7, 0.75, mats.soft, 0.22);
  for (const [x, z] of [[-5, 0.1], [-3.6, 0.1], [-5, 1.7], [-3.6, 1.7]] as const) {
    const w = cyl(0.26, 0.26, 0.2, x, 0.26, z, mats.ground, 18);
    w.rotation.z = Math.PI / 2;
    w.position.y = 0.26;
  }
  box(2.4, 0.08, 0.6, -4.5, 1.15, -2.7, mats.floor, 0.02);
  box(0.06, 1.2, 0.6, -5.65, 0, -2.7, mats.floor, 0.02);
  box(0.06, 1.2, 0.6, -3.35, 0, -2.7, mats.floor, 0.02);
  // Hall: console table, coat stand
  box(1.6, 0.9, 0.5, -1, 0, -2.7, mats.floor, 0.05);
  cyl(0.05, 0.05, 1.7, -2, 0, 1.6, mats.soft);
  // Living room: sofa, TV stand, TV, rug
  box(3, 0.5, 0.95, 3.2, 0, 1.4, mats.soft, 0.18);
  box(3, 0.6, 0.3, 3.2, 0.5, 1.75, mats.soft, 0.14);
  box(2.8, 0.55, 0.6, 3.2, 0, -2.6, mats.floor, 0.05);
  box(1.7, 1, 0.08, 3.7, 0.95, -2.75, mats.ground, 0.03);
  box(3.6, 0.03, 2.2, 3.2, 0.01, -0.3, mats.thing, 0);
  // Study: desk, monitor, shelf of books
  box(2.6, 0.85, 0.9, -3.4, 3, -2.5, mats.floor, 0.05);
  box(1.1, 0.7, 0.07, -2.8, 3.95, -2.7, mats.ground, 0.03);
  box(0.6, 2.2, 1.6, -5.6, 3, -0.3, mats.floor, 0.04);
  // Kids' room: bed, small desk, toy blocks
  box(1.7, 0.5, 2.6, 4.6, 3, 0.9, mats.soft, 0.16);
  box(1.4, 0.18, 0.7, 4.6, 3.5, -0.1, mats.thing, 0.08);
  box(1.6, 0.8, 0.8, 2.2, 3, -2.55, mats.floor, 0.05);
  box(0.35, 0.35, 0.35, 1.6, 3, 1.8, mats.thing, 0.06);
  box(0.3, 0.3, 0.3, 1.9, 3, 2.2, mats.soft, 0.06);
  // Attic: a low crate for the Pi, boxes
  box(1.3, 0.55, 0.9, 0, 6, -1.6, mats.floor, 0.05);
  box(0.9, 0.7, 0.8, -3.6, 6, -1.8, mats.thing, 0.05);
  box(0.7, 0.55, 0.6, -2.8, 6, -1.3, mats.soft, 0.05);

  // Outside: a path, trees, a low fence
  box(1.6, 0.04, 6, -4.3, 0, 6.3, mats.floor, 0);
  for (const [x, z, s] of [[-9.5, -1.5, 1.2], [9, -2.5, 1.5], [8.4, 3.5, 0.9], [-10.5, 4.5, 0.8]] as const) {
    cyl(0.12 * s, 0.16 * s, 1 * s, x, 0, z, mats.wall, 10);
    const crown = new THREE.Mesh(new THREE.ConeGeometry(0.95 * s, 2.4 * s, 7), mats.soft);
    geos.push(crown.geometry);
    crown.position.set(x, 2.1 * s, z);
    crown.castShadow = crown.receiveShadow = true;
    scene.add(crown);
  }
  for (let i = 0; i < 9; i++) box(0.12, 0.6, 0.12, 1.5 + i * 0.9, 0, 5, mats.wall, 0.03);
  box(7.4, 0.08, 0.06, 5.1, 0.45, 5, mats.wall, 0);

  // ---------- The machines, each with a status light and a lamp in its room ----------
  type Device = { led: THREE.Mesh; at: THREE.Vector3; lamp: THREE.PointLight; shade: THREE.MeshLambertMaterial; t: number };
  const ledGeo = new THREE.SphereGeometry(0.07, 16, 12);
  geos.push(ledGeo);
  function device(build: () => void, led: [number, number, number], lamp: [number, number, number]): Device {
    build();
    const mat = new THREE.MeshBasicMaterial({ color: OFF.clone(), toneMapped: false });
    const l = new THREE.Mesh(ledGeo, mat);
    l.position.set(...led);
    scene.add(l);
    // A small table lamp: its shade glows when the room is checked.
    const shade = new THREE.MeshLambertMaterial({ color: 0x4a4a52, emissive: WARM.clone(), emissiveIntensity: 0 });
    cyl(0.03, 0.03, 0.55, lamp[0], lamp[1], lamp[2], mats.wall, 8);
    const sh = cyl(0.14, 0.26, 0.3, lamp[0], lamp[1] + 0.5, lamp[2], shade, 20);
    sh.castShadow = false;
    const p = new THREE.PointLight(WARM, 0, 7, 1.6);
    p.position.set(lamp[0], lamp[1] + 0.9, lamp[2] + 0.4);
    scene.add(p);
    return { led: l, at: new THREE.Vector3(...led), lamp: p, shade, t: 0 };
  }

  const devices: Device[] = [
    // Camera recorder, garage shelf
    device(() => { box(0.9, 0.3, 0.5, -4.6, 1.23, -2.7, mats.soft, 0.05); box(0.3, 0.22, 0.35, -5.8, 2.2, -2.85, mats.soft, 0.08); }, [-4.25, 1.4, -2.44], [-3.9, 1.23, -2.75]),
    // Router, hall console
    device(() => {
      box(0.75, 0.14, 0.45, -1, 0.9, -2.7, mats.soft, 0.05);
      cyl(0.025, 0.025, 0.55, -1.28, 1.02, -2.85, mats.soft, 8);
      cyl(0.025, 0.025, 0.55, -0.72, 1.02, -2.85, mats.soft, 8);
    }, [-0.85, 1.0, -2.46], [-1.6, 0.9, -2.75]),
    // Mac Mini, under the TV
    device(() => box(0.8, 0.24, 0.8, 2.3, 0.55, -2.55, mats.soft, 0.1), [2.3, 0.68, -2.14], [4.4, 0.55, -2.6]),
    // Minecraft server, kids' desk
    device(() => box(0.5, 1.1, 0.75, 2.6, 3.8, -2.55, mats.soft, 0.05), [2.6, 4.7, -2.16], [1.7, 3.8, -2.6]),
    // NAS, study desk
    device(() => {
      box(0.55, 0.75, 0.7, -4.25, 3.85, -2.5, mats.soft, 0.05);
      for (let i = 0; i < 3; i++) box(0.4, 0.03, 0.02, -4.25, 4.0 + i * 0.18, -2.14, mats.ground, 0);
    }, [-4.05, 4.5, -2.14], [-2.2, 3.85, -2.6]),
    // Raspberry Pi, attic crate
    device(() => {
      box(0.7, 0.12, 0.5, 0, 6.55, -1.6, mats.soft, 0.03);
      box(0.18, 0.08, 0.18, -0.12, 6.67, -1.62, mats.ground, 0.02);
    }, [0.22, 6.72, -1.4], [-0.9, 6, -1.9]),
  ];

  // ---------- The wire: one cable routed through the house like real wiring ----------
  // It runs along each floor in front of the furniture, goes up to every machine and
  // back down, and climbs a corner to the next storey. The light travels along it.
  const F = [0.06, 3.06, 6.06]; // floor levels
  const RUN = -1.85; // where the cable runs along a floor
  const route: [number, number, number][] = [[-14, F[0], 4.2], [-5.6, F[0], 4.2], [-5.6, F[0], RUN]];
  const visit = (x: number, floor: number, top: number, z: number) =>
    route.push([x, floor, RUN], [x, floor, z], [x, top, z], [x, floor, z], [x, floor, RUN]);
  const climb = (x: number, from: number, to: number, runTo = RUN) =>
    route.push([x, from, RUN], [x, from, -2.9], [x, to, -2.9], [x, to, runTo]);
  visit(-4.25, F[0], 1.36, -2.36); // camera recorder
  visit(-0.85, F[0], 1.0, -2.4); // router
  visit(2.3, F[0], 0.66, -2.08); // Mac Mini
  climb(5.8, F[0], F[1]);
  visit(2.6, F[1], 4.66, -2.08); // Minecraft server
  visit(-4.05, F[1], 4.46, -2.0); // NAS
  climb(-5.9, F[1], F[2], -0.85);
  route.push([0.22, F[2], -0.85], [0.22, F[2], -1.12], [0.22, 6.68, -1.12]); // the Pi

  // Straight runs with small rounded bends, like a cable pressed into corners.
  const pts = route.map(([x, y, z]) => new THREE.Vector3(x, y, z));
  const wire = new THREE.CurvePath<THREE.Vector3>();
  let from = pts[0].clone();
  for (let i = 1; i < pts.length - 1; i++) {
    const [a, p, b] = [pts[i - 1], pts[i], pts[i + 1]];
    const r = Math.min(0.14, p.distanceTo(a) / 2, p.distanceTo(b) / 2);
    const into = p.clone().addScaledVector(a.clone().sub(p).normalize(), r);
    const out = p.clone().addScaledVector(b.clone().sub(p).normalize(), r);
    if (from.distanceTo(into) > 1e-4) wire.add(new THREE.LineCurve3(from, into));
    wire.add(new THREE.QuadraticBezierCurve3(into, p.clone(), out));
    from = out;
  }
  wire.add(new THREE.LineCurve3(from, pts[pts.length - 1]));

  const SEG = 2400;
  const RAD = 6;
  const cableGeo = new THREE.TubeGeometry(wire, SEG, 0.028, RAD, false);
  geos.push(cableGeo);
  const cable = new THREE.Mesh(cableGeo, clay(0x1c2131));
  cable.castShadow = true;
  scene.add(cable);
  const tubeGeo = new THREE.TubeGeometry(wire, SEG, 0.034, RAD, false);
  geos.push(tubeGeo);
  const tubeMat = new THREE.MeshBasicMaterial({ color: WARM.clone().multiplyScalar(0.95), toneMapped: false, transparent: true, opacity: 0.85 });
  const tube = new THREE.Mesh(tubeGeo, tubeMat);
  scene.add(tube);

  // Where along the wire each machine is: the closest sample to its light.
  const samples = wire.getSpacedPoints(1600);
  for (const d of devices) {
    let best = 0;
    let bestD = Infinity;
    samples.forEach((p, i) => {
      const dd = p.distanceToSquared(d.at);
      if (dd < bestD) { bestD = dd; best = i; }
    });
    d.t = best / 1600;
  }

  // The nightlight itself: a small bright bead on the wire
  const headGeo = new THREE.SphereGeometry(0.11, 24, 16);
  geos.push(headGeo);
  const head = new THREE.Mesh(headGeo, new THREE.MeshBasicMaterial({ color: new THREE.Color(0xfff1c4).multiplyScalar(1.4), toneMapped: false }));
  scene.add(head);
  const haloGeo = new THREE.SphereGeometry(0.22, 24, 16);
  geos.push(haloGeo);
  head.add(new THREE.Mesh(haloGeo, new THREE.MeshBasicMaterial({ color: WARM, transparent: true, opacity: 0.12, toneMapped: false, depthWrite: false })));
  const headLight = new THREE.PointLight(WARM, 3, 4, 1.6);
  head.add(headLight);

  // Once all is well, small pulses keep flowing along the wire.
  const pulseGeo = new THREE.SphereGeometry(0.06, 12, 8);
  geos.push(pulseGeo);
  const pulses = Array.from({ length: 7 }, () => {
    const m = new THREE.Mesh(pulseGeo, new THREE.MeshBasicMaterial({ color: WARM.clone().multiplyScalar(1.2), toneMapped: false }));
    scene.add(m);
    return m;
  });

  // ---------- "Checking" rings around the light ----------
  const ringGeo = new THREE.RingGeometry(0.95, 1, 64);
  geos.push(ringGeo);
  const rings = [0, 1, 2].map(() => {
    const m = new THREE.Mesh(ringGeo, new THREE.MeshBasicMaterial({ color: WARN, transparent: true, opacity: 0, toneMapped: false, depthWrite: false, side: THREE.DoubleSide }));
    m.rotation.x = -Math.PI / 2;
    scene.add(m);
    return m;
  });

  // ---------- A field of dots on the ground, rippling out from the house ----------
  const STEP = 0.62;
  const dots: THREE.Vector2[] = [];
  for (let x = -26; x <= 26; x += STEP) {
    for (let z = -26; z <= 26; z += STEP) {
      const inHouse = Math.abs(x) < 6.6 && Math.abs(z) < 3.6;
      if (!inHouse && x * x + z * z < 26 * 26) dots.push(new THREE.Vector2(x, z));
    }
  }
  // The ripple is computed on the GPU: each dot only knows where it sits.
  const disc = new THREE.CircleGeometry(0.075, 12);
  disc.rotateX(-Math.PI / 2);
  const dotGeo = new THREE.InstancedBufferGeometry();
  dotGeo.index = disc.index;
  dotGeo.setAttribute("position", disc.getAttribute("position"));
  dotGeo.setAttribute("aPos", new THREE.InstancedBufferAttribute(new Float32Array(dots.flatMap((d) => [d.x, d.y])), 2));
  dotGeo.instanceCount = dots.length;
  geos.push(disc, dotGeo);
  const dotUniforms = {
    uR: { value: 12 },
    uAmp: { value: 0.25 },
    uBase: { value: new THREE.Color(0x283152) },
    uWarm: { value: WARM.clone() },
  };
  const field = new THREE.Mesh(
    dotGeo,
    new THREE.ShaderMaterial({
      uniforms: dotUniforms,
      vertexShader: /* glsl */ `
        attribute vec2 aPos;
        uniform float uR;
        uniform float uAmp;
        varying float vWave;
        varying float vNear;
        void main() {
          float d = length(aPos);
          vWave = exp(-pow(d - uR, 2.0) / 3.0) * uAmp;
          vNear = max(0.0, 1.0 - d / 22.0);
          vec3 p = position * (0.55 + vNear * 0.45 + vWave * 0.5) + vec3(aPos.x, 0.0, aPos.y);
          gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
        }`,
      fragmentShader: /* glsl */ `
        uniform vec3 uBase;
        uniform vec3 uWarm;
        varying float vWave;
        varying float vNear;
        void main() {
          vec3 c = mix(uBase, uWarm, min(1.0, vWave * 0.6)) * (0.6 + vNear * 0.5 + vWave * 0.6);
          gl_FragColor = vec4(c, 1.0);
        }`,
    }),
  );
  field.frustumCulled = false;
  field.position.y = 0.02;
  scene.add(field);

  // ---------- Post: a soft bloom so the warm lights actually glow ----------
  const composer = new EffectComposer(
    renderer,
    new THREE.WebGLRenderTarget(1, 1, { type: THREE.HalfFloatType, samples: 4 }),
  );
  composer.addPass(new RenderPass(scene, camera));
  const bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.4, 0.4, 0.9);
  // The glow is soft anyway, so its blur runs at a quarter of the size.
  const bloomSize = bloom.setSize.bind(bloom);
  bloom.setSize = (w: number, h: number) => bloomSize(w / 2, h / 2);
  composer.addPass(bloom);
  composer.addPass(new OutputPass());

  // ---------- Sizing ----------
  let W = 1;
  let H = 1;
  function resize() {
    W = canvas.clientWidth || window.innerWidth;
    H = canvas.clientHeight || window.innerHeight;
    renderer.setSize(W, H, false);
    composer.setPixelRatio(renderer.getPixelRatio());
    composer.setSize(W, H);
  }
  function lower() {
    if (level >= LEVELS.length - 1) {
      bloom.enabled = false;
      return;
    }
    level++;
    renderer.setPixelRatio(LEVELS[level]);
    resize();
  }
  resize();
  const ro = new ResizeObserver(resize);
  ro.observe(canvas);

  // ---------- Drawing one frame of a View ----------
  const target = new THREE.Vector3();
  const headPos = new THREE.Vector3();
  const camHead = new THREE.Vector3(); // the light, smoothed, for the camera to follow
  const piColor = new THREE.Color();
  let last = -1;
  let slow = 0; // a running average of frame time, for stepping quality down
  let settle = 0; // frames to ignore after a step down
  const sm = (a: number, b: number, x: number) => {
    const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
    return t * t * (3 - 2 * t);
  };

  function draw(v: View, time: number) {
    const narrow = W < 820;
    const dt = last < 0 ? 0 : Math.min(0.1, time - last);
    last = time;
    if (dt > 0 && settle-- <= 0) {
      slow += (dt - slow) * 0.05;
      if (slow > 1 / 40) {
        lower();
        slow = 1 / 60;
        settle = 90;
      }
    }

    // The light and its trail
    const tr = Math.min(1, Math.max(0, v.trail));
    wire.getPointAt(Math.max(0.0001, tr), headPos);
    head.position.copy(headPos);
    if (dt === 0) camHead.copy(headPos);
    else camHead.lerp(headPos, 1 - Math.exp(-dt * 5));
    head.scale.setScalar(opts.calm ? 1 : 1 + Math.sin(time * 2.2) * 0.08);
    tube.geometry.setDrawRange(0, Math.round(tr * SEG) * RAD * 6);
    pulses.forEach((m, k) => {
      const u = opts.calm ? k / pulses.length : (time * 0.035 + k / pulses.length) % 1;
      wire.getPointAt(u, m.position);
      m.scale.setScalar(Math.max(v.orb, 0.0001));
    });

    piColor.copy(WARN).lerp(OK, v.done);
    // Machines: off until the light reaches them, then fine; the Pi needs a look until it's fixed.
    devices.forEach((d, i) => {
      const reached = sm(d.t - 0.02, d.t + 0.01, tr);
      const isPi = i === devices.length - 1;
      const state = isPi ? piColor : OK;
      const mat = d.led.material as THREE.MeshBasicMaterial;
      mat.color.copy(OFF).lerp(state, reached).multiplyScalar(1 + reached * 0.5);
      const pulse = isPi && !opts.calm ? 1 + (1 - v.done) * 0.35 * Math.sin(time * 4) : 1;
      d.led.scale.setScalar((1 + reached * 0.4) * pulse);
      const on = Math.max(reached, v.lit);
      d.lamp.intensity = on * 3.5;
      d.shade.emissiveIntensity = on * 0.9;
    });

    // Checking rings, expanding from the light
    rings.forEach((r, i) => {
      const ph = opts.calm ? 0.35 + i * 0.2 : ((time * 0.55 + i / 3) % 1);
      r.position.set(headPos.x, tr > 0.97 ? 6.57 : headPos.y, headPos.z);
      r.scale.setScalar(0.3 + ph * 1.6);
      const m = r.material as THREE.MeshBasicMaterial;
      m.color.copy(tr > 0.97 ? piColor : WARM);
      m.opacity = v.rings * (1 - ph) * 0.5;
    });

    // Dot field: a slow ripple, stronger once all is well
    const amp = 0.25 + v.lit * 0.75;
    const R = opts.calm ? 12 : (time * 5) % 34;
    dotUniforms.uAmp.value = amp;
    dotUniforms.uR.value = R;

    // Camera: orthographic, looking at (tx,ty,tz) or at the light
    target.set(v.tx, v.ty, v.tz).lerp(camHead, v.follow);
    const az = THREE.MathUtils.degToRad(v.az);
    const el = THREE.MathUtils.degToRad(v.el);
    camera.position.set(
      target.x + Math.cos(el) * Math.sin(az) * 60,
      target.y + Math.sin(el) * 60,
      target.z + Math.cos(el) * Math.cos(az) * 60,
    );
    camera.lookAt(target);
    const aspect = W / H;
    const half = Math.max(11, (narrow ? 8.5 : 0) / aspect) / v.zoom;
    const halfW = half * aspect;
    const ox = narrow ? 0 : v.ox;
    const oy = narrow ? v.oy : 0;
    camera.left = -halfW - ox * 2 * halfW;
    camera.right = halfW - ox * 2 * halfW;
    camera.top = half - oy * 2 * half;
    camera.bottom = -half - oy * 2 * half;
    camera.updateProjectionMatrix();

    composer.render();
  }

  // Build every shader now, so nothing stalls the first time it appears.
  resize();
  renderer.compile(scene, camera);

  return {
    draw,
    dispose() {
      ro.disconnect();
      geos.forEach((g) => g.dispose());
      scene.traverse((o) => {
        const m = (o as THREE.Mesh).material;
        if (m) (Array.isArray(m) ? m : [m]).forEach((x) => x.dispose());
      });
      composer.dispose();
      renderer.dispose();
    },
  };
}
