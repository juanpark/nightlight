import * as THREE from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

// The glow hero's 3D world: a clay dollhouse at night, cut open at the front,
// with the six machines of the sample home in their rooms. A small warm light
// (the nightlight) travels a path room to room; each machine's status light and
// its room's lamp come on as it passes. Everything the page scrolls through is
// one View, which GlowLanding tweens with GSAP; this file only draws it, and
// reports where the light, the Pi and its logs land on screen (a Probe).

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
  lift?: number; // focal point's offset upward, as a share of the height (every screen)
  logs?: number; // 0..1: the Pi's old logs have piled up beside it
  mark?: number; // 0..1: the dry run outlines the logs that would go
  town?: number; // 0..1: the shop, the office and the server room rise and are wired in, one by one
  fit?: number; // keep at least this much of the world's width on screen, in world units either side
};

// Where things land on screen this frame, in CSS pixels, for the page to pin
// its labels and connector lines to.
export type Probe = {
  head: { x: number; y: number };
  pi: { x: number; y: number };
  logs: { x: number; y: number };
  checked: number; // machines the light has reached
};

// Night clay: greys with a little of the page's navy in them, so the colour
// comes from the light (cool moon outside, star-yellow lamps inside) rather
// than from the paint.
const CLAY = {
  ground: 0x18203a,
  wall: 0x575e78,
  floor: 0x676b80,
  thing: 0x71758a,
  soft: 0x878a9c,
};
const COOL_PANE = new THREE.Color(0x2a3a6a);
const OFF = new THREE.Color(0x1e2a50);

export function createScene(canvas: HTMLCanvasElement, opts: { calm: boolean }) {
  // The colours come from the page's own tokens (Glow.module.css), so the
  // scene and the page can never drift apart.
  const css = getComputedStyle(canvas);
  const token = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback;
  const BG = new THREE.Color(token("--scene-ground", "#1b233c"));
  const WARM = new THREE.Color(token("--star", "#fdd83a"));
  const OK = new THREE.Color(token("--ok", "#8fd6a8"));
  const WARN = new THREE.Color(token("--warn", "#f5b84a"));
  const NIGHT_RGB = token("--night-rgb", "11 20 48").split(/\s+/).join(", ");
  const OK_RGB = token("--ok-rgb", "143 214 168").split(/\s+/).join(", ");
  const TEXT = token("--text", "#f4efe4");
  // Antialiasing happens in the post target (MSAA), so the canvas itself needs none.
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: "high-performance" });
  // Quality steps down on its own if frames run slow: pixel ratio first, then bloom.
  const LEVELS = [Math.min(window.devicePixelRatio, 1.5), Math.min(window.devicePixelRatio, 1.25), 1];
  let level = 0;
  renderer.setPixelRatio(LEVELS[0]);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  // Nothing that casts a shadow ever moves, so the shadow map is drawn once.
  renderer.shadowMap.autoUpdate = false;
  renderer.shadowMap.needsUpdate = true;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.15;
  renderer.setClearColor(BG, 1);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(BG);
  scene.fog = new THREE.Fog(BG, 62, 96); // hides where the ground ends

  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 300);

  // ---------- Light: moon, sky, and the warm ones that come on ----------
  // A dim studio environment gives the clay soft shading on every face; the sky
  // only tints it, and the moon is the one hard light, from the front left so
  // roof, walls and floors each read at their own value.
  const pmrem = new THREE.PMREMGenerator(renderer);
  const envTex = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environment = envTex;
  scene.environmentIntensity = 0.16;
  scene.add(new THREE.HemisphereLight(0x5f6d9e, 0x070b18, 0.55));
  const moon = new THREE.DirectionalLight(0xaebcea, 1.9);
  moon.position.set(-12, 24, 16);
  moon.castShadow = true;
  moon.shadow.mapSize.set(2048, 2048);
  moon.shadow.camera.left = -18;
  moon.shadow.camera.right = 18;
  moon.shadow.camera.top = 18;
  moon.shadow.camera.bottom = -18;
  moon.shadow.bias = -0.0004;
  moon.shadow.normalBias = 0.02;
  scene.add(moon);

  // Matte clay: rough, non-metal, lit by the environment as well as the lights.
  const clay = (color: number) => new THREE.MeshStandardMaterial({ color, roughness: 0.92, metalness: 0 });
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
  ground.position.y = -0.02; // just under the house base, which also tops out at 0 (avoids z-fighting)
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
  const paneMat = new THREE.MeshStandardMaterial({ color: 0x111a36, emissive: COOL_PANE.clone(), emissiveIntensity: 0.6, roughness: 0.3 });
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
  type Device = { led: THREE.Mesh; at: THREE.Vector3; lamp: THREE.PointLight; shade: THREE.MeshStandardMaterial; t: number; glow: number };
  const ledGeo = new THREE.SphereGeometry(0.07, 16, 12);
  geos.push(ledGeo);
  function device(build: () => void, led: [number, number, number], lamp: [number, number, number]): Device {
    build();
    const mat = new THREE.MeshBasicMaterial({ color: OFF.clone(), toneMapped: false });
    const l = new THREE.Mesh(ledGeo, mat);
    l.position.set(...led);
    scene.add(l);
    // A small table lamp: its shade glows when the room is checked.
    const shade = new THREE.MeshStandardMaterial({ color: 0x474b5e, emissive: WARM.clone(), emissiveIntensity: 0, roughness: 0.8 });
    cyl(0.03, 0.03, 0.55, lamp[0], lamp[1], lamp[2], mats.wall, 8);
    const sh = cyl(0.14, 0.26, 0.3, lamp[0], lamp[1] + 0.5, lamp[2], shade, 20);
    sh.castShadow = false;
    const p = new THREE.PointLight(WARM, 0, 9, 2);
    p.position.set(lamp[0], lamp[1] + 0.9, lamp[2] + 0.4);
    scene.add(p);
    return { led: l, at: new THREE.Vector3(...led), lamp: p, shade, t: 0, glow: 0 };
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

  // ---------- The Pi's old logs: a stack of thin slabs beside its crate ----------
  // They pile up as the light finds the problem, the dry run outlines the old
  // ones, and once the cleanup runs those slide away; the recent three stay.
  const LOGS = 10;
  const KEEP = 3;
  const LOG_AT = new THREE.Vector3(1.55, 6.06, -1.55);
  const LOG_GAP = 0.13;
  const slabGeo = new RoundedBoxGeometry(0.95, 0.08, 0.7, 2, 0.025);
  geos.push(slabGeo);
  const slabs = Array.from({ length: LOGS }, (_, k) => {
    const mat = new THREE.MeshStandardMaterial({
      color: 0x2a2416,
      emissive: WARN.clone(),
      emissiveIntensity: 0.5,
      roughness: 0.6,
      transparent: true,
      opacity: 0,
    });
    const m = new THREE.Mesh(slabGeo, mat);
    m.position.set(LOG_AT.x, LOG_AT.y + 0.04 + k * LOG_GAP, LOG_AT.z);
    m.visible = false;
    scene.add(m);
    return m;
  });
  // The dry run's outline: dashed, around the slabs that would be cleared.
  const markH = (LOGS - KEEP) * LOG_GAP + 0.06;
  const markEdges = new THREE.EdgesGeometry(new THREE.BoxGeometry(1.15, markH, 0.9));
  geos.push(markEdges);
  const markMat = new THREE.LineDashedMaterial({ color: WARN, dashSize: 0.09, gapSize: 0.07, transparent: true, opacity: 0, toneMapped: false });
  const markBox = new THREE.LineSegments(markEdges, markMat);
  markBox.computeLineDistances();
  markBox.position.set(LOG_AT.x, LOG_AT.y + KEEP * LOG_GAP + markH / 2 - 0.02, LOG_AT.z);
  scene.add(markBox);
  // A faint volume inside the outline, so the share that would go reads at a glance.
  const markFillGeo = new THREE.BoxGeometry(1.15, markH, 0.9);
  geos.push(markFillGeo);
  const markFillMat = new THREE.MeshBasicMaterial({ color: WARN, transparent: true, opacity: 0, depthWrite: false, toneMapped: false });
  markBox.add(new THREE.Mesh(markFillGeo, markFillMat));
  const logTop = new THREE.Vector3();

  // A soft warm fill on each storey, for when the whole house is lit.
  const fills = [1.6, 4.6, 7.2].map((y) => {
    const f = new THREE.PointLight(WARM, 0, 14, 2);
    f.position.set(0, y, 1.2);
    scene.add(f);
    return f;
  });

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
  function cablePath(route: [number, number, number][], bend = 0.14) {
    const pts = route.map(([x, y, z]) => new THREE.Vector3(x, y, z));
    const path = new THREE.CurvePath<THREE.Vector3>();
    let from = pts[0].clone();
    for (let i = 1; i < pts.length - 1; i++) {
      const [a, p, b] = [pts[i - 1], pts[i], pts[i + 1]];
      const r = Math.min(bend, p.distanceTo(a) / 2, p.distanceTo(b) / 2);
      const into = p.clone().addScaledVector(a.clone().sub(p).normalize(), r);
      const out = p.clone().addScaledVector(b.clone().sub(p).normalize(), r);
      if (from.distanceTo(into) > 1e-4) path.add(new THREE.LineCurve3(from, into));
      path.add(new THREE.QuadraticBezierCurve3(into, p.clone(), out));
      from = out;
    }
    path.add(new THREE.LineCurve3(from, pts[pts.length - 1]));
    return path;
  }
  const wire = cablePath(route);

  const SEG = 2400;
  const RAD = 6;
  const cableGeo = new THREE.TubeGeometry(wire, SEG, 0.028, RAD, false);
  geos.push(cableGeo);
  const cable = new THREE.Mesh(cableGeo, clay(0x1a2444));
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
  const head = new THREE.Mesh(headGeo, new THREE.MeshBasicMaterial({ color: WARM.clone().lerp(new THREE.Color(0xffffff), 0.65).multiplyScalar(1.4), toneMapped: false }));
  scene.add(head);
  const haloGeo = new THREE.SphereGeometry(0.22, 24, 16);
  geos.push(haloGeo);
  head.add(new THREE.Mesh(haloGeo, new THREE.MeshBasicMaterial({ color: WARM, transparent: true, opacity: 0.12, toneMapped: false, depthWrite: false })));
  const headLight = new THREE.PointLight(WARM, 7, 5, 2);
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

  // ---------- Beyond the house: a shop, an office and a server room ----------
  // Out of sight until the very end, when they rise from the ground one by one
  // and the light's wire runs out from the house to each. Same clay, same lamps.
  // They cast no shadows: the shadow map is drawn once, before they exist.
  type Place = {
    group: THREE.Group;
    panes: { mat: THREE.MeshStandardMaterial; at: number }[]; // each window lights at its own moment
    beacon: THREE.Mesh;
    tag: THREE.Mesh; // its name, above it
    cable: THREE.Mesh;
    segs: number;
    at: number; // 0..1: when, in the town's progress, it starts to rise
  };
  function placeBox(g: THREE.Group, w: number, h: number, d: number, x: number, y: number, z: number, mat: THREE.Material, round = 0.06) {
    const geo = round > 0 ? new RoundedBoxGeometry(w, h, d, 2, Math.min(round, w / 2, h / 2, d / 2)) : new THREE.BoxGeometry(w, h, d);
    geos.push(geo);
    const m = new THREE.Mesh(geo, mat);
    m.position.set(x, y + h / 2, z);
    m.receiveShadow = true;
    g.add(m);
    return m;
  }
  function pane(g: THREE.Group, w: number, h: number, x: number, y: number, z: number, at: number, list: Place["panes"]) {
    const mat = new THREE.MeshStandardMaterial({ color: 0x111a36, emissive: COOL_PANE.clone(), emissiveIntensity: 0.5, roughness: 0.3 });
    placeBox(g, w, h, 0.05, x, y, z, mat, 0.015);
    list.push({ mat, at });
  }
  // Tags: the page's own pill label (dark glass, a green dot, the place's name),
  // drawn into the world above each place and turned to face the same way as
  // its front, so the camera tilts it with the building. They fade in as each
  // place lights up; on a phone they are drawn larger so they stay readable.
  const font = getComputedStyle(canvas).getPropertyValue("--font-sans").trim() || "system-ui, sans-serif";
  const tags: { tex: THREE.CanvasTexture; paint: () => void; mesh: THREE.Mesh }[] = [];
  const TAG_H = 1.9; // world units
  function tagIn(parent: THREE.Object3D, text: string, x: number, y: number, z: number) {
    const cv = document.createElement("canvas");
    const H = 128;
    const ctx = cv.getContext("2d")!;
    const tex = new THREE.CanvasTexture(cv);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.anisotropy = renderer.capabilities.getMaxAnisotropy();
    const geo = new THREE.PlaneGeometry(1, 1);
    geos.push(geo);
    const mat = new THREE.MeshBasicMaterial({ map: tex, transparent: true, opacity: 0, toneMapped: false, depthWrite: false });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.set(x, y, z);
    mesh.renderOrder = 10;
    mesh.visible = false;
    parent.add(mesh);
    const paint = () => {
      const size = H * 0.36;
      ctx.font = `600 ${size}px ${font}`;
      const W = Math.ceil(ctx.measureText(text).width + H * 1.25);
      cv.width = W;
      cv.height = H;
      ctx.font = `600 ${size}px ${font}`;
      const r = H / 2 - 4;
      ctx.beginPath();
      ctx.roundRect(3, 3, W - 6, H - 6, r);
      ctx.fillStyle = `rgba(${NIGHT_RGB}, 0.82)`;
      ctx.fill();
      ctx.lineWidth = 3;
      ctx.strokeStyle = `rgba(${OK_RGB}, 0.55)`;
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(H * 0.48, H / 2, H * 0.085, 0, Math.PI * 2);
      ctx.fillStyle = `rgb(${OK_RGB})`;
      ctx.fill();
      ctx.fillStyle = TEXT;
      ctx.textBaseline = "middle";
      ctx.fillText(text, H * 0.72, H / 2 + 2);
      tex.needsUpdate = true;
      mesh.scale.set((TAG_H * W) / H, TAG_H, 1);
      mesh.userData.w = mesh.scale.x;
    };
    paint();
    tags.push({ tex, paint, mesh });
    return mesh;
  }
  // The page's font may still be loading; draw the tags again once it has.
  document.fonts?.ready.then(() => tags.forEach((t) => t.paint()));
  function showTag(m: THREE.Mesh, a: number, big: number) {
    m.visible = a > 0.002;
    (m.material as THREE.MeshBasicMaterial).opacity = a;
    m.scale.set(m.userData.w * big, TAG_H * big, 1);
  }

  const beaconGeo = new THREE.SphereGeometry(0.16, 16, 12);
  geos.push(beaconGeo);
  // A seeded shuffle, so the windows light in the same order on every visit.
  let seed = 7;
  const rand = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);

  const places: Place[] = [];
  // What the pointer can land on: an unseen box around each building, the house first.
  const hits: THREE.Mesh[] = [];
  const hitMat = new THREE.MeshBasicMaterial({ visible: false });
  function hitBox(parent: THREE.Object3D, [w, h, d]: [number, number, number], at = new THREE.Vector3()) {
    const geo = new THREE.BoxGeometry(w, h, d);
    geos.push(geo);
    const m = new THREE.Mesh(geo, hitMat);
    m.position.set(at.x, at.y + h / 2, at.z);
    parent.add(m);
    return m;
  }
  hits.push(hitBox(scene, [13, 10.5, 7]));
  function place(
    at: number,
    x: number,
    z: number,
    build: (g: THREE.Group, panes: Place["panes"]) => [number, number, number],
    cable: [number, number, number][],
    tag: [string, number, number, number], // text and where it floats, in the place's own space
    size: [number, number, number], // its bulk, for pointing at it
  ) {
    const group = new THREE.Group();
    group.position.set(x, 0, z);
    group.visible = false;
    scene.add(group);
    const panes: Place["panes"] = [];
    const [bx, by, bz] = build(group, panes);
    const tagMesh = tagIn(group, ...tag);
    const beacon = new THREE.Mesh(beaconGeo, new THREE.MeshBasicMaterial({ color: OFF.clone(), toneMapped: false }));
    beacon.position.set(bx, by, bz);
    group.add(beacon);
    const path = cablePath(cable, 0.3);
    const segs = Math.max(60, Math.round(path.getLength() * 12));
    const geo = new THREE.TubeGeometry(path, segs, 0.05, RAD, false);
    geos.push(geo);
    const mesh = new THREE.Mesh(geo, tubeMat);
    mesh.geometry.setDrawRange(0, 0);
    scene.add(mesh);
    places.push({ group, panes, beacon, tag: tagMesh, cable: mesh, segs, at });
    hits.push(hitBox(group, size));
  }

  // Sized against the house (12.6 wide, two storeys and an attic): a shop of one
  // tall storey, an office tower half again as high as the house's roof, and a
  // single-storey server room.

  // The shop, out to the left: two shop windows under an awning, a lit sign.
  place(0, -21, -2, (g, panes) => {
    placeBox(g, 9, 4.4, 6, 0, 0, 0, mats.wall, 0.06);
    placeBox(g, 9.4, 0.3, 6.4, 0, 4.4, 0, mats.floor, 0.06);
    const awning = placeBox(g, 9.2, 0.1, 1.7, 0, 2.95, 3.75, mats.soft, 0.03);
    awning.rotation.x = 0.3;
    pane(g, 2.8, 2, -2.9, 0.45, 3.02, 0.3, panes);
    pane(g, 2.2, 2, 0.1, 0.45, 3.02, 0.4, panes);
    placeBox(g, 1.4, 2.5, 0.06, 2.9, 0, 3.02, mats.ground, 0.02); // door
    pane(g, 6, 0.75, -0.5, 3.4, 3.04, 0.6, panes); // sign
    return [3.9, 5.1, 2.4];
  }, [[-6.6, 0.06, 4.2], [-21, 0.06, 4.2], [-21, 0.06, 1.05]], ["Your shop", 0, 6.9, 1.2], [9.4, 5, 7.6]);

  // The office, back to the right: seven floors of windows that light up a few at a time.
  place(0.22, 21, -9, (g, panes) => {
    placeBox(g, 9, 15, 7, 0, 0, 0, mats.wall, 0.06);
    placeBox(g, 9.4, 0.3, 7.4, 0, 15, 0, mats.floor, 0.06);
    placeBox(g, 3, 1.4, 2.2, -1.8, 15.3, -1.2, mats.soft, 0.06); // plant room on the roof
    pane(g, 4.2, 1.9, 0, 0.3, 3.52, 0.35, panes); // the lobby
    for (let f = 1; f < 7; f++) {
      for (let c = 0; c < 6; c++) pane(g, 1, 1.3, -3.5 + c * 1.4, 1.2 + f * 1.9, 3.52, 0.3 + rand() * 0.7, panes);
    }
    cylIn(g, 0.06, 0.06, 2, 2.8, 15.3, 1.5);
    return [2.8, 17.5, 1.5];
  }, [[6.6, 0.06, 4.6], [21, 0.06, 4.6], [21, 0.06, -5.45]], ["Your office", 0, 19.5, 1.2], [9.4, 17, 7.4]);

  // The server room, front right: cut open like the house, five racks of blinking lights.
  const rackLeds: { mat: THREE.MeshBasicMaterial; phase: number }[] = [];
  place(0.44, 16, 11, (g) => {
    placeBox(g, 8, 0.3, 5.5, 0, 0, 0, mats.floor, 0.06);
    placeBox(g, 8, 4.2, 0.25, 0, 0, -2.62, mats.wall, 0.04);
    placeBox(g, 0.25, 4.2, 5.5, -3.88, 0, 0, mats.wall, 0.04);
    placeBox(g, 0.25, 4.2, 5.5, 3.88, 0, 0, mats.wall, 0.04);
    placeBox(g, 8.4, 0.3, 5.8, 0, 4.2, -0.15, mats.floor, 0.06);
    const ledGeo2 = new THREE.BoxGeometry(0.16, 0.07, 0.02);
    geos.push(ledGeo2);
    for (let r = 0; r < 5; r++) {
      const x = -2.8 + r * 1.4;
      placeBox(g, 1, 3.2, 1.2, x, 0.3, -1.7, mats.ground, 0.05);
      for (let k = 0; k < 10; k++) {
        const mat = new THREE.MeshBasicMaterial({ color: OFF.clone(), toneMapped: false });
        const led = new THREE.Mesh(ledGeo2, mat);
        led.position.set(x + 0.28, 0.65 + k * 0.28, -1.08);
        g.add(led);
        rackLeds.push({ mat, phase: rand() * 6.28 });
      }
    }
    return [3.4, 5.9, -1.4];
  }, [[6.6, 0.06, 4.6], [10, 0.06, 4.6], [10, 0.06, 11], [11.95, 0.06, 11]], ["Your server room", 0, 6.9, 1.2], [8.4, 5, 5.8]);

  // A few trees to frame the street (the house has its own), growing in with the buildings.
  const grove: { g: THREE.Group; at: number }[] = [];
  for (const [x, z, sz, at] of [
    [-28.5, -1, 1.4, 0.05], [-14.5, -8.5, 1.1, 0.1], [4.5, -10, 1.4, 0.18],
    [28, 1.5, 1.3, 0.3], [24.5, 11, 1, 0.46], [-9, 11.5, 1.2, 0.12],
  ] as const) {
    const g = new THREE.Group();
    g.position.set(x, 0, z);
    g.visible = false;
    cylIn(g, 0.12 * sz, 0.16 * sz, sz, 0, 0, 0);
    const crown = new THREE.Mesh(new THREE.ConeGeometry(0.95 * sz, 2.4 * sz, 7), mats.soft);
    geos.push(crown.geometry);
    crown.position.y = 2.1 * sz;
    crown.receiveShadow = true;
    g.add(crown);
    scene.add(g);
    grove.push({ g, at });
  }

  function cylIn(g: THREE.Group, rt: number, rb: number, h: number, x: number, y: number, z: number) {
    const geo = new THREE.CylinderGeometry(rt, rb, h, 8);
    geos.push(geo);
    const m = new THREE.Mesh(geo, mats.wall);
    m.position.set(x, y + h / 2, z);
    g.add(m);
  }
  // Home's tag, above the roof.
  const homeTag = tagIn(scene, "Your home", 0, 11.6, 0.6);

  // ---------- A field of dots on the ground, rippling out from the house ----------
  const STEP = 0.62;
  const dots: THREE.Vector2[] = [];
  for (let x = -34; x <= 34; x += STEP) {
    for (let z = -34; z <= 34; z += STEP) {
      const inHouse = Math.abs(x) < 6.6 && Math.abs(z) < 3.6;
      if (!inHouse && x * x + z * z < 34 * 34) dots.push(new THREE.Vector2(x, z));
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
  const bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.5, 0.6, 0.88);
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
    const sideways = H < 520 && W > H; // a phone on its side
    const narrow = W < 820 || sideways; // phones, upright or on their side
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
      // A lamp warms up over half a second instead of switching on.
      const on = Math.max(reached, v.lit);
      d.glow += (on - d.glow) * (dt === 0 || opts.calm ? 1 : 1 - Math.exp(-dt * 4));
      d.lamp.intensity = d.glow * 13;
      d.shade.emissiveIntensity = d.glow * 1.2;
    });
    fills.forEach((f) => (f.intensity = v.lit * 9));

    // The logs: each slab drops in on its turn; the old ones slide off once cleared.
    const logs = v.logs ?? 0;
    const mark = v.mark ?? 0;
    let top = 0;
    slabs.forEach((m, k) => {
      const inn = sm(k / LOGS, (k + 1.6) / LOGS, logs);
      const old = k >= KEEP;
      // The old slabs go top first, so the stack sinks rather than vanishing at once.
      const out = old ? sm(((LOGS - 1 - k) / (LOGS - KEEP)) * 0.6, ((LOGS - 1 - k) / (LOGS - KEEP)) * 0.6 + 0.4, v.done) : 0;
      const a = inn * (1 - out);
      m.visible = a > 0.002;
      const mat = m.material as THREE.MeshStandardMaterial;
      mat.opacity = a * 0.92;
      mat.emissive.copy(WARN).lerp(OK, old ? 0 : v.done);
      // A slab that is marked for cleanup brightens with the dry run.
      mat.emissiveIntensity = 0.45 + (old ? mark * (1 - v.done) * 0.5 : 0);
      m.position.y = LOG_AT.y + 0.04 + k * LOG_GAP + (1 - inn) * 0.5 + out * 0.35;
      m.position.x = LOG_AT.x + out * 0.9;
      if (a > 0.5) top = k;
    });
    const marked = mark * (1 - v.done);
    markMat.opacity = marked * (opts.calm ? 1 : 0.8 + Math.sin(time * 3) * 0.2);
    markFillMat.opacity = marked * 0.1;
    markBox.visible = marked > 0.002;
    // The callout pins to the middle of the old logs while they are there, then to what is left.
    logTop.set(LOG_AT.x, LOG_AT.y + (v.done > 0.5 ? top * 0.5 : KEEP + (LOGS - KEEP) / 2) * LOG_GAP, LOG_AT.z);
    // Windows go from moonlit blue to lamplight as the house wakes up.
    const warmth = Math.max(v.lit, tr * 0.55);
    paneMat.emissive.copy(COOL_PANE).lerp(WARM, warmth);
    paneMat.emissiveIntensity = 0.6 + warmth * 0.5;

    // The town: each place rises, its cable runs out from the house, then it lights up.
    const town = v.town ?? 0;
    const big = narrow ? 1.8 : 1;
    // Tags stay hidden until a building is pointed at (or tapped), then fade in.
    const ease = dt === 0 || opts.calm ? 1 : 1 - Math.exp(-dt * 12);
    tagA.forEach((a, i) => (tagA[i] = a + ((hovered === i ? 1 : 0) - a) * ease));
    places.forEach((pl, k) => {
      const rise = sm(pl.at, pl.at + 0.22, town);
      const run = sm(pl.at + 0.1, pl.at + 0.34, town);
      const lit = sm(pl.at + 0.3, pl.at + 0.42, town);
      pl.group.visible = rise > 0.001;
      pl.group.scale.set(1, Math.max(0.001, 1 - Math.pow(1 - rise, 3)), 1);
      pl.cable.geometry.setDrawRange(0, Math.round(run * pl.segs) * RAD * 6);
      (pl.beacon.material as THREE.MeshBasicMaterial).color.copy(OFF).lerp(OK, lit).multiplyScalar(1 + lit * 0.6);
      pl.beacon.scale.setScalar(1 + lit * (opts.calm ? 0.2 : 0.2 + Math.sin(time * 2 + k) * 0.12));
      pl.panes.forEach((pn) => {
        const on = sm(pn.at - 0.1, pn.at + 0.05, lit);
        pn.mat.emissive.copy(COOL_PANE).lerp(WARM, on);
        // Star yellow is bright: lit windows stay just under a full glow so the street doesn't blur.
        pn.mat.emissiveIntensity = 0.5 + on * 0.45;
      });
      if (k === 2) {
        rackLeds.forEach((l) => {
          const blink = opts.calm ? 1 : 0.55 + 0.45 * Math.sin(time * 3.1 + l.phase);
          l.mat.color.copy(OFF).lerp(OK, lit * blink).multiplyScalar(1 + lit * 0.5);
        });
      }
      // A place has finished rising before it lights, so its tag is never squashed.
      showTag(pl.tag, lit * tagA[k + 1], big);
      if (hovered === k + 1) pl.beacon.scale.multiplyScalar(1.4);
      placeLit[k + 1] = lit;
    });
    placeLit[0] = sm(0.02, 0.12, town);
    showTag(homeTag, placeLit[0] * tagA[0], big);
    grove.forEach(({ g, at }) => {
      const rise = sm(at, at + 0.2, town);
      g.visible = rise > 0.001;
      g.scale.set(1, Math.max(0.001, 1 - Math.pow(1 - rise, 3)), 1);
    });
    // Further out, the fog lets go a little so the whole street reads.
    (scene.fog as THREE.Fog).near = 62 + town * 14;
    (scene.fog as THREE.Fog).far = 96 + town * 24;

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
    // A slow drift keeps the house alive when nobody is scrolling.
    const drift = opts.calm ? 0 : Math.sin(time * 0.13) * 1.4;
    const az = THREE.MathUtils.degToRad(v.az + drift);
    const el = THREE.MathUtils.degToRad(v.el + (opts.calm ? 0 : Math.sin(time * 0.09) * 0.6));
    camera.position.set(
      target.x + Math.cos(el) * Math.sin(az) * 60,
      target.y + Math.sin(el) * 60,
      target.z + Math.cos(el) * Math.cos(az) * 60,
    );
    camera.lookAt(target);
    const aspect = W / H;
    let half = Math.max(11, (narrow ? 8.5 : 0) / aspect) / v.zoom;
    if (v.fit) half = Math.max(half, v.fit / aspect);
    const halfW = half * aspect;
    // Upright phones keep the subject centred; on their side it moves to the right half,
    // since the words sit on the left.
    const ox = sideways ? 0.18 : narrow ? 0 : v.ox;
    const oy = (narrow ? v.oy : 0) + (v.lift ?? 0);
    camera.left = -halfW - ox * 2 * halfW;
    camera.right = halfW - ox * 2 * halfW;
    camera.top = half - oy * 2 * half;
    camera.bottom = -half - oy * 2 * half;
    camera.updateProjectionMatrix();

    composer.render();

    camera.updateMatrixWorld();
    // What the pointer is over, for the next frame's tags: only lit places, only at the end.
    hovered = -1;
    if (pointer && town > 0.5) {
      ray.setFromCamera(pointer, camera);
      const hit = ray.intersectObjects(hits, false)[0];
      const i = hit ? hits.indexOf(hit.object as THREE.Mesh) : -1;
      if (i >= 0 && placeLit[i] > 0.5) hovered = i;
    }
    toScreen(headPos, probe.head);
    toScreen(devices[devices.length - 1].at, probe.pi);
    toScreen(logTop, probe.logs);
    probe.checked = devices.filter((d) => tr >= d.t).length;
    return probe;
  }

  const probe: Probe = {
    head: { x: 0, y: 0 },
    pi: { x: 0, y: 0 },
    logs: { x: 0, y: 0 },
    checked: 0,
  };
  const ndc = new THREE.Vector3();
  const ray = new THREE.Raycaster();
  let pointer: THREE.Vector2 | null = null;
  let hovered = -1;
  const tagA = [0, 0, 0, 0];
  const placeLit = [0, 0, 0, 0];
  // The canvas fills the screen, so a pointer's page position is its place on the canvas.
  function point(x: number | null, y = 0) {
    if (x === null) pointer = null;
    else (pointer ??= new THREE.Vector2()).set((x / W) * 2 - 1, -(y / H) * 2 + 1);
  }
  function toScreen(p: THREE.Vector3, out: { x: number; y: number }) {
    ndc.copy(p).project(camera);
    out.x = ((ndc.x + 1) / 2) * W;
    out.y = ((1 - ndc.y) / 2) * H;
  }

  // Build every shader now, so nothing stalls the first time it appears.
  resize();
  renderer.compile(scene, camera);

  return {
    draw,
    point,
    dispose() {
      ro.disconnect();
      geos.forEach((g) => g.dispose());
      scene.traverse((o) => {
        const m = (o as THREE.Mesh).material;
        if (m) (Array.isArray(m) ? m : [m]).forEach((x) => x.dispose());
      });
      tags.forEach((t) => t.tex.dispose());
      composer.dispose();
      envTex.dispose();
      pmrem.dispose();
      renderer.dispose();
    },
  };
}
