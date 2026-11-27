// Procedurally built player characters. Every character is made from Three.js primitives,
// faces +Z, stands on y = 0, and uses `color` (the player's colour) as its main accent so
// players stay easy to tell apart.
//
// build(color) returns { root, upper, feet, top, tick? }
//   root  - the Group placed in the world
//   upper - the part that bobs while walking
//   feet  - meshes swung while walking (may be empty)
//   top   - height of the top of the character (name tag and stun stars go above it)
//   tick(t, speed) - optional per-frame animation of special parts
import * as THREE from 'three';

const std = (color, o = {}) => new THREE.MeshStandardMaterial({ color, roughness: 0.6, ...o });
const basic = (color) => new THREE.MeshBasicMaterial({ color });
const glow = (color, intensity = 1) => new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: intensity, roughness: 0.4 });
const shade = (color, k) => new THREE.Color(color).multiplyScalar(k);
const mix = (a, b, t) => new THREE.Color(a).lerp(new THREE.Color(b), t);

const SKIN = 0xf2c9a0, BLACK = 0x15151a, GOLD = 0xffc233, WHITE = 0xf4f6f8;

function add(parent, geo, mat, x = 0, y = 0, z = 0, rx = 0, ry = 0, rz = 0) {
  const m = new THREE.Mesh(geo, mat);
  m.position.set(x, y, z); m.rotation.set(rx, ry, rz);
  parent.add(m);
  return m;
}
const sphere = (r, w = 18, h = 14) => new THREE.SphereGeometry(r, w, h);
const box = (w, h, d) => new THREE.BoxGeometry(w, h, d);
const cyl = (rt, rb, h, s = 16, open = false) => new THREE.CylinderGeometry(rt, rb, h, s, 1, open);
const cone = (r, h, s = 16) => new THREE.ConeGeometry(r, h, s);
const capsule = (r, l) => new THREE.CapsuleGeometry(r, l, 6, 16);

function rig() {
  const root = new THREE.Group(), upper = new THREE.Group();
  root.add(upper);
  return { root, upper };
}
function addFeet(root, color = 0x2b2b33, { spread = 0.2, w = 0.24, h = 0.18, d = 0.4, z = 0 } = {}) {
  const m = std(color);
  return [-spread, spread].map((x) => add(root, box(w, h, d), m, x, h / 2, z));
}
function addEyes(parent, y, z, { spread = 0.13, r = 0.05, color = 0x111111, white = false } = {}) {
  for (const s of [-1, 1]) {
    if (white) add(parent, sphere(r * 1.7, 12, 10), basic(0xffffff), s * spread, y, z - r * 0.4);
    add(parent, sphere(r, 10, 8), basic(color), s * spread, y, z + (white ? r * 0.75 : 0));
  }
}

// ------------------------------------------------------------------ characters

function miner(color) {
  const { root, upper } = rig();
  add(upper, capsule(0.42, 0.55), std(color), 0, 0.95, 0);
  for (const s of [-1, 1]) add(upper, box(0.08, 0.7, 0.05), std(shade(color, 0.55)), s * 0.18, 1.0, 0.4, -0.12);
  add(upper, sphere(0.36), std(SKIN, { roughness: 0.7 }), 0, 1.78, 0);
  const hatMat = std(0xffc233, { roughness: 0.35 });
  add(upper, new THREE.SphereGeometry(0.4, 18, 10, 0, Math.PI * 2, 0, Math.PI / 2), hatMat, 0, 1.86, 0);
  add(upper, cyl(0.5, 0.5, 0.05, 20), hatMat, 0, 1.87, 0);
  const lamp = add(upper, cyl(0.09, 0.09, 0.1, 12), glow(0xfff3b0, 1.5), 0, 2.02, 0.38, Math.PI / 2);
  addEyes(upper, 1.78, 0.33);
  // pickaxe slung on the back
  const pick = new THREE.Group(); pick.position.set(0, 1.0, -0.48); pick.rotation.z = 0.6; upper.add(pick);
  add(pick, cyl(0.035, 0.035, 1.2, 8), std(0x7a5230), 0, 0, 0);
  add(pick, new THREE.TorusGeometry(0.32, 0.04, 6, 12, Math.PI), std(0x9aa3ad, { metalness: 0.7, roughness: 0.3 }), 0, 0.45, 0);
  const feet = addFeet(root);
  return { root, upper, feet, top: 2.1, tick: (t) => { lamp.material.emissiveIntensity = 1.2 + Math.sin(t * 3) * 0.3; } };
}

function robot(color) {
  const { root, upper } = rig();
  const metal = std(0xb8c0cc, { metalness: 0.75, roughness: 0.3 });
  const dark = std(0x3a4150, { metalness: 0.5, roughness: 0.4 });
  for (const s of [-1, 1]) add(root, cyl(0.07, 0.07, 0.4, 8), dark, s * 0.2, 0.35, 0);
  add(upper, box(0.82, 0.75, 0.56), metal, 0, 0.88, 0);
  add(upper, box(0.5, 0.34, 0.04), glow(color, 0.35), 0, 0.92, 0.29);
  for (let k = 0; k < 3; k++) add(upper, sphere(0.035, 8, 6), basic([0xff4d4d, 0xffd23f, 0x4dff88][k]), -0.14 + k * 0.14, 0.68, 0.29);
  add(upper, cyl(0.1, 0.12, 0.16, 10), dark, 0, 1.33, 0);
  add(upper, box(0.64, 0.5, 0.52), metal, 0, 1.62, 0);
  const visor = add(upper, box(0.5, 0.14, 0.04), glow(0x5ff6ff, 1.4), 0, 1.66, 0.27);
  for (let k = 0; k < 3; k++) add(upper, box(0.3, 0.025, 0.02), dark, 0, 1.46 + k * 0.05, 0.265);
  for (const s of [-1, 1]) {
    add(upper, cyl(0.09, 0.09, 0.08, 12), dark, s * 0.35, 1.62, 0, 0, 0, Math.PI / 2);
    add(upper, cyl(0.08, 0.08, 0.55, 10), metal, s * 0.52, 0.85, 0);
    add(upper, sphere(0.11, 12, 10), dark, s * 0.52, 0.52, 0);
  }
  add(upper, cyl(0.02, 0.02, 0.35, 6), dark, 0, 2.02, 0);
  const tip = add(upper, sphere(0.075, 12, 10), glow(color, 1.5), 0, 2.22, 0);
  const feet = addFeet(root, 0x3a4150, { w: 0.3, h: 0.2, d: 0.46, spread: 0.2 });
  return { root, upper, feet, top: 2.3, tick: (t) => {
    tip.material.emissiveIntensity = Math.sin(t * 5) > 0 ? 2 : 0.3;
    visor.scale.x = Math.sin(t * 0.9) > 0.97 ? 0.2 : 1; // occasional "blink"
  } };
}

function knight(color) {
  const { root, upper } = rig();
  const steel = std(0xc9d1db, { metalness: 0.85, roughness: 0.25 });
  add(upper, capsule(0.42, 0.5), steel, 0, 0.95, 0);
  add(upper, box(0.6, 0.78, 0.06), std(color), 0, 0.92, 0.4);
  add(upper, new THREE.OctahedronGeometry(0.12), std(GOLD, { metalness: 0.8, roughness: 0.3 }), 0, 1.05, 0.45, 0, 0, 0).scale.set(1, 1.3, 0.4);
  add(upper, cyl(0.445, 0.445, 0.09, 20, true), std(0x5a3a1e), 0, 0.72, 0);
  for (const s of [-1, 1]) add(upper, new THREE.SphereGeometry(0.22, 14, 10, 0, Math.PI * 2, 0, Math.PI / 2), steel, s * 0.42, 1.3, 0);
  add(upper, cyl(0.37, 0.37, 0.5, 20), steel, 0, 1.78, 0);
  add(upper, new THREE.SphereGeometry(0.37, 20, 10, 0, Math.PI * 2, 0, Math.PI / 2), steel, 0, 2.03, 0);
  add(upper, box(0.42, 0.05, 0.05), basic(0x0a0a0a), 0, 1.84, 0.36);
  add(upper, box(0.05, 0.22, 0.05), basic(0x0a0a0a), 0, 1.7, 0.36);
  const plume = std(color, { roughness: 0.9 });
  [[2.48, 0.02, 0.15], [2.52, -0.14, 0.14], [2.47, -0.3, 0.13], [2.36, -0.43, 0.11], [2.22, -0.5, 0.09]]
    .forEach(([y, z, r]) => add(upper, sphere(r, 12, 10), plume, 0, y, z));
  // shield and sword
  add(upper, cyl(0.34, 0.34, 0.06, 24), std(color, { metalness: 0.3 }), 0.53, 0.95, 0.05, 0, 0, Math.PI / 2);
  add(upper, sphere(0.08, 10, 8), std(GOLD, { metalness: 0.8, roughness: 0.3 }), 0.57, 0.95, 0.05);
  add(upper, box(0.06, 0.85, 0.02), steel, -0.55, 0.55, 0.1);
  add(upper, box(0.28, 0.05, 0.07), std(GOLD, { metalness: 0.8 }), -0.55, 1.0, 0.1);
  add(upper, cyl(0.03, 0.03, 0.2, 8), std(0x5a3a1e), -0.55, 1.12, 0.1);
  const feet = addFeet(root, 0x7d8590);
  return { root, upper, feet, top: 2.55 };
}

function wizard(color) {
  const { root, upper } = rig();
  const robe = std(color, { roughness: 0.85 });
  add(upper, cone(0.6, 1.55, 24), robe, 0, 0.78, 0);
  add(upper, cyl(0.25, 0.32, 0.25, 16), robe, 0, 1.45, 0);
  add(upper, sphere(0.33), std(SKIN, { roughness: 0.7 }), 0, 1.7, 0);
  add(upper, cone(0.26, 0.6, 16), std(0xf0f0f0, { roughness: 1 }), 0, 1.38, 0.17, Math.PI + 0.25);
  add(upper, sphere(0.065, 10, 8), std(0xe8a882), 0, 1.66, 0.33);
  addEyes(upper, 1.76, 0.29, { spread: 0.12, r: 0.045 });
  const hatCol = shade(color, 0.55);
  add(upper, cyl(0.58, 0.58, 0.04, 24), std(hatCol), 0, 1.93, 0);
  const hat = new THREE.Group(); hat.position.set(0, 1.93, 0); upper.add(hat);
  add(hat, cone(0.34, 1.05, 20), std(hatCol), 0, 0.5, 0);
  hat.rotation.set(-0.12, 0, 0.14);
  const starMat = glow(GOLD, 0.8);
  [[0.1, 0.3, 0.27], [-0.14, 0.55, 0.17], [0.07, 0.78, 0.1]].forEach(([x, y, z]) => add(hat, new THREE.OctahedronGeometry(0.06), starMat, x, y, z));
  add(upper, cyl(0.04, 0.045, 2.1, 8), std(0x6b4a2b), 0.62, 1.05, 0.1);
  const orb = add(upper, sphere(0.14, 16, 12), glow(mix(color, 0xffffff, 0.5), 1.6), 0.62, 2.18, 0.1);
  const feet = addFeet(root, 0x3a2a1a, { w: 0.18, h: 0.12, d: 0.3, z: 0.25, spread: 0.16 });
  return { root, upper, feet, top: 2.95, tick: (t) => {
    const k = 1 + Math.sin(t * 4) * 0.12;
    orb.scale.setScalar(k);
    orb.material.emissiveIntensity = 1.2 + Math.sin(t * 4) * 0.6;
  } };
}

function astronaut(color) {
  const { root, upper } = rig();
  const suit = std(WHITE, { roughness: 0.5 });
  add(upper, capsule(0.45, 0.5), suit, 0, 0.95, 0);
  add(upper, box(0.62, 0.72, 0.3), suit, 0, 1.0, -0.42);
  add(upper, box(0.42, 0.3, 0.05), std(0x3a4150), 0, 1.02, 0.44);
  [[0xff4d4d, -0.12], [0x4dff88, 0], [color, 0.12]].forEach(([c, x]) => add(upper, sphere(0.04, 8, 6), glow(c, 1), x, 1.04, 0.47));
  add(upper, cyl(0.46, 0.46, 0.08, 24, true), std(color), 0, 0.7, 0);
  for (const s of [-1, 1]) {
    add(upper, capsule(0.12, 0.35), suit, s * 0.5, 0.92, 0, 0, 0, s * 0.18);
    add(upper, cyl(0.125, 0.125, 0.07, 14, true), std(color), s * 0.51, 0.98, 0, 0, 0, s * 0.18);
  }
  add(upper, sphere(0.46, 24, 18), suit, 0, 1.76, 0);
  const visor = new THREE.SphereGeometry(0.47, 24, 16, Math.PI / 2 - 0.75, 1.5, Math.PI / 2 - 0.5, 0.85);
  add(upper, visor, std(0xffb53d, { metalness: 1, roughness: 0.12 }), 0, 1.76, 0);
  add(upper, cyl(0.015, 0.015, 0.35, 6), std(0x9aa3ad), 0.3, 2.2, -0.1);
  add(upper, sphere(0.04, 8, 6), glow(color, 1.5), 0.3, 2.38, -0.1);
  const feet = addFeet(root, WHITE, { w: 0.3, h: 0.22, d: 0.45 });
  return { root, upper, feet, top: 2.4 };
}

function ninja(color) {
  const { root, upper } = rig();
  const cloth = std(0x23232b, { roughness: 0.9 });
  add(upper, capsule(0.42, 0.52), cloth, 0, 0.95, 0);
  add(upper, cyl(0.435, 0.435, 0.11, 20, true), std(color), 0, 0.74, 0);
  add(upper, sphere(0.36), cloth, 0, 1.76, 0);
  add(upper, new THREE.SphereGeometry(0.365, 24, 8, Math.PI / 2 - 0.75, 1.5, Math.PI / 2 - 0.22, 0.3), std(SKIN), 0, 1.76, 0);
  for (const s of [-1, 1]) {
    add(upper, sphere(0.045, 10, 8), basic(0x111111), s * 0.12, 1.75, 0.345);
    add(upper, box(0.13, 0.025, 0.02), basic(0x111111), s * 0.12, 1.83, 0.34, 0, 0, s * -0.3);
  }
  const band = std(color, { side: THREE.DoubleSide });
  add(upper, cyl(0.375, 0.375, 0.09, 24, true), band, 0, 1.92, 0);
  add(upper, sphere(0.07, 10, 8), band, 0, 1.92, -0.38);
  const tails = [-1, 1].map((s) => {
    const g = new THREE.Group(); g.position.set(s * 0.05, 1.92, -0.4); upper.add(g);
    add(g, box(0.07, 0.025, 0.5), band, 0, 0, -0.25);
    g.rotation.y = s * 0.25;
    return g;
  });
  const sword = new THREE.Group(); sword.position.set(0, 1.05, -0.46); sword.rotation.z = -0.7; upper.add(sword);
  add(sword, box(0.05, 1.0, 0.02), std(0xd5dbe3, { metalness: 0.9, roughness: 0.2 }), 0, 0.15, 0);
  add(sword, box(0.18, 0.04, 0.06), std(GOLD), 0, -0.36, 0);
  add(sword, box(0.06, 0.28, 0.06), std(color), 0, -0.52, 0);
  const feet = addFeet(root, 0x18181e);
  return { root, upper, feet, top: 2.15, tick: (t, speed) => {
    const amp = 0.15 + Math.min(speed, 11) * 0.03;
    tails.forEach((g, i) => { g.rotation.x = -0.35 + Math.sin(t * 9 + i) * amp; });
  } };
}

function cat(color) {
  const { root, upper } = rig();
  const fur = std(color, { roughness: 0.9 }), cream = std(0xfff1dc, { roughness: 0.9 }), pink = std(0xff9db5);
  add(upper, capsule(0.42, 0.45), fur, 0, 0.9, 0);
  add(upper, sphere(0.3), cream, 0, 0.9, 0.24).scale.set(1, 1.35, 0.6);
  const head = add(upper, sphere(0.4, 20, 16), fur, 0, 1.68, 0); head.scale.x = 1.12;
  add(upper, sphere(0.16), cream, 0, 1.58, 0.31).scale.set(1.3, 0.8, 0.7);
  add(upper, sphere(0.05, 8, 6), pink, 0, 1.64, 0.43);
  for (const s of [-1, 1]) {
    add(upper, cone(0.15, 0.32, 4), fur, s * 0.24, 2.05, 0, 0, Math.PI / 4, s * -0.3);
    add(upper, cone(0.08, 0.2, 4), pink, s * 0.235, 2.02, 0.05, 0, Math.PI / 4, s * -0.3);
    for (const k of [-1, 1]) add(upper, box(0.34, 0.012, 0.012), basic(0x333333), s * 0.32, 1.6 + k * 0.03, 0.36, 0, 0, s * k * 0.12);
  }
  addEyes(upper, 1.77, 0.34, { spread: 0.16, r: 0.065, color: 0x1f6f3a, white: true });
  const tail = new THREE.Group(); tail.position.set(0, 0.7, -0.38); upper.add(tail);
  const curve = new THREE.CatmullRomCurve3([[0, 0, 0], [0, 0.12, -0.28], [0, 0.48, -0.42], [0, 0.8, -0.3]].map((p) => new THREE.Vector3(...p)));
  add(tail, new THREE.TubeGeometry(curve, 20, 0.07, 8), fur);
  add(tail, sphere(0.075, 10, 8), fur, 0, 0.8, -0.3);
  const feet = addFeet(root, 0xfff1dc, { w: 0.22, h: 0.15, d: 0.34 });
  return { root, upper, feet, top: 2.3, tick: (t) => { tail.rotation.z = Math.sin(t * 3) * 0.45; } };
}

function dino(color) {
  const { root, upper } = rig();
  const skin = std(color, { roughness: 0.75 }), belly = std(mix(color, 0xfff6d5, 0.65), { roughness: 0.8 });
  add(upper, capsule(0.48, 0.5), skin, 0, 0.95, 0).scale.z = 1.1;
  add(upper, sphere(0.34), belly, 0, 0.9, 0.33).scale.set(1, 1.3, 0.5);
  const head = new THREE.Group(); head.position.set(0, 1.68, 0.08); upper.add(head);
  add(head, sphere(0.38, 20, 16), skin);
  add(head, sphere(0.3, 18, 14), skin, 0, -0.06, 0.3).scale.set(1, 0.75, 1.2);
  for (const s of [-1, 1]) {
    add(head, sphere(0.03, 6, 6), basic(0x222222), s * 0.08, 0.02, 0.63);
    add(head, cone(0.035, 0.08, 6), std(0xffffff), s * 0.14, -0.2, 0.5, Math.PI);
  }
  addEyes(head, 0.2, 0.22, { spread: 0.17, r: 0.06, white: true });
  const spike = std(mix(color, 0xffd23f, 0.7), { flatShading: true });
  [[2.08, -0.05], [1.8, -0.36], [1.45, -0.52], [1.1, -0.58], [0.78, -0.6]]
    .forEach(([y, z], i) => add(upper, cone(0.11 - i * 0.008, 0.26, 4), spike, 0, y, z, -0.9 - i * 0.12));
  const tail = new THREE.Group(); tail.position.set(0, 0.6, -0.5); upper.add(tail);
  add(tail, cone(0.28, 0.95, 16), skin, 0, -0.05, -0.4, -Math.PI / 2 - 0.25);
  for (const s of [-1, 1]) add(upper, capsule(0.07, 0.2), skin, s * 0.38, 1.12, 0.32, -1.1);
  const feet = addFeet(root, shade(color, 0.7), { w: 0.3, d: 0.45 });
  return { root, upper, feet, top: 2.25, tick: (t) => { tail.rotation.y = Math.sin(t * 2.5) * 0.35; } };
}

function pirate(color) {
  const { root, upper } = rig();
  add(upper, capsule(0.42, 0.55), std(color), 0, 0.95, 0);
  add(upper, box(0.24, 0.6, 0.05), std(0xf3efe6), 0, 1.02, 0.4);
  add(upper, cyl(0.435, 0.435, 0.1, 20, true), std(0x1d1a17), 0, 0.72, 0);
  add(upper, box(0.13, 0.11, 0.04), std(GOLD, { metalness: 0.8, roughness: 0.3 }), 0, 0.72, 0.44);
  add(upper, sphere(0.36), std(SKIN, { roughness: 0.7 }), 0, 1.75, 0);
  add(upper, sphere(0.3), std(0x5a3a1e, { roughness: 1 }), 0, 1.58, 0.12).scale.set(1, 0.8, 0.75);
  add(upper, sphere(0.045, 10, 8), basic(0x111111), -0.13, 1.8, 0.33);
  add(upper, cyl(0.08, 0.08, 0.03, 14), basic(0x111111), 0.13, 1.8, 0.33, Math.PI / 2);
  const strap = new THREE.Group(); strap.position.set(0, 1.78, 0); strap.rotation.z = 0.35; upper.add(strap);
  add(strap, new THREE.TorusGeometry(0.365, 0.014, 6, 32), basic(0x111111), 0, 0, 0, Math.PI / 2);
  const hatMat = std(0x1d1a17, { roughness: 0.8 });
  add(upper, cyl(0.6, 0.6, 0.18, 3), hatMat, 0, 2.03, 0);
  add(upper, cyl(0.3, 0.36, 0.3, 18), hatMat, 0, 2.2, 0);
  add(upper, cyl(0.62, 0.62, 0.03, 3), std(GOLD, { metalness: 0.6 }), 0, 2.13, 0);
  add(upper, sphere(0.07, 10, 8), std(0xf3efe6), 0, 2.2, 0.33);
  // parrot on the shoulder
  const parrot = new THREE.Group(); parrot.position.set(0.38, 1.42, 0); upper.add(parrot);
  add(parrot, sphere(0.13, 12, 10), std(0xe53935), 0, 0.12, 0).scale.y = 1.3;
  add(parrot, sphere(0.1, 12, 10), std(0xe53935), 0, 0.33, 0.04);
  add(parrot, cone(0.04, 0.1, 8), std(0xffc233), 0, 0.31, 0.15, Math.PI / 2);
  add(parrot, box(0.05, 0.18, 0.14), std(0x2e9d4f), 0.11, 0.13, 0);
  add(parrot, box(0.08, 0.22, 0.03), std(0x1e6bff), 0, -0.07, -0.11, 0.4);
  add(parrot, sphere(0.02, 6, 6), basic(0x111111), 0.06, 0.36, 0.1);
  const feet = addFeet(root, 0x1d1a17);
  return { root, upper, feet, top: 2.4, tick: (t) => { parrot.rotation.y = Math.sin(t * 1.7) * 0.5; parrot.position.y = 1.42 + Math.abs(Math.sin(t * 3.4)) * 0.03; } };
}

function ghost(color) {
  const { root, upper } = rig();
  const pts = [];
  for (let k = 0; k <= 10; k++) { const a = (k / 10) * (Math.PI / 2); pts.push(new THREE.Vector2(Math.sin(a) * 0.5 + 0.001, 1.6 + Math.cos(a) * 0.5)); }
  pts.push(new THREE.Vector2(0.53, 1.0), new THREE.Vector2(0.58, 0.3));
  const geo = new THREE.LatheGeometry(pts, 40);
  const pos = geo.attributes.position;
  for (let i = 0; i < pos.count; i++) {
    if (pos.getY(i) < 0.4) pos.setY(i, pos.getY(i) + Math.sin(Math.atan2(pos.getZ(i), pos.getX(i)) * 7) * 0.08);
  }
  geo.computeVertexNormals();
  const sheetCol = mix(0xffffff, color, 0.25);
  const sheet = new THREE.MeshStandardMaterial({ color: sheetCol, emissive: color, emissiveIntensity: 0.15, roughness: 0.5,
    transparent: true, opacity: 0.88, side: THREE.DoubleSide });
  add(upper, geo, sheet);
  for (const s of [-1, 1]) {
    add(upper, sphere(0.075, 12, 10), basic(0x14141c), s * 0.16, 1.72, 0.45).scale.set(1, 1.45, 0.5);
    add(upper, sphere(0.15, 12, 10), sheet, s * 0.55, 1.15, 0.05);
  }
  add(upper, sphere(0.07, 12, 10), basic(0x14141c), 0, 1.46, 0.5).scale.set(1.2, 0.85, 0.5);
  return { root, upper, feet: [], top: 2.45, tick: (t) => {
    upper.position.y = 0.25 + Math.sin(t * 2.4) * 0.12;
    upper.rotation.z = Math.sin(t * 1.7) * 0.06;
  } };
}

function mushroom(color) {
  const { root, upper } = rig();
  const stem = std(0xf3ead7, { roughness: 0.85 });
  add(upper, cyl(0.32, 0.42, 1.1, 20), stem, 0, 0.72, 0);
  addEyes(upper, 1.0, 0.34, { spread: 0.13, r: 0.055 });
  for (const s of [-1, 1]) add(upper, sphere(0.07, 10, 8), std(0xff9db5), s * 0.21, 0.9, 0.31).scale.set(1, 0.6, 0.4);
  add(upper, new THREE.TorusGeometry(0.06, 0.018, 6, 12, Math.PI), basic(0x3a2a1a), 0, 0.88, 0.36, 0, 0, Math.PI);
  add(upper, cyl(0.72, 0.6, 0.06, 28), std(0xe6d8bd), 0, 1.3, 0);
  const cap = add(upper, new THREE.SphereGeometry(0.78, 28, 14, 0, Math.PI * 2, 0, Math.PI / 2), std(color, { roughness: 0.45 }), 0, 1.3, 0);
  cap.scale.y = 0.78;
  const spot = std(0xffffff, { roughness: 0.6 });
  [[0, 0.2], [1.2, 0.55], [2.5, 0.6], [3.8, 0.5], [5.1, 0.6], [0.6, 0.95], [2.0, 1.05], [3.4, 0.95], [4.7, 1.0], [5.8, 1.05]]
    .forEach(([phi, theta]) => {
      const r = 0.78;
      const s = add(upper, sphere(0.1 + (theta < 0.3 ? 0.05 : 0), 10, 8), spot,
        Math.sin(theta) * Math.cos(phi) * r, 1.3 + Math.cos(theta) * r * 0.78, Math.sin(theta) * Math.sin(phi) * r);
      s.scale.set(1, 0.45, 1);
      s.lookAt(s.position.clone().multiplyScalar(2).setY(s.position.y * 2 - 1.3));
    });
  const feet = addFeet(root, 0x8a6a4a, { w: 0.22, h: 0.14, d: 0.32 });
  return { root, upper, feet, top: 2.0 };
}

function penguin(color) {
  const { root, upper } = rig();
  const black = std(0x1f2430, { roughness: 0.6 }), white = std(0xffffff, { roughness: 0.7 }), orange = std(0xffa726);
  add(upper, capsule(0.46, 0.55), black, 0, 0.95, 0);
  add(upper, sphere(0.38), white, 0, 0.9, 0.2).scale.set(1, 1.45, 0.62);
  add(upper, sphere(0.36), black, 0, 1.72, 0);
  add(upper, sphere(0.28), white, 0, 1.7, 0.16).scale.set(1.05, 0.85, 0.6);
  add(upper, cone(0.08, 0.22, 10), orange, 0, 1.64, 0.43, Math.PI / 2);
  addEyes(upper, 1.78, 0.32, { spread: 0.12, r: 0.045 });
  add(upper, new THREE.TorusGeometry(0.33, 0.085, 10, 24), std(color, { roughness: 0.9 }), 0, 1.42, 0, Math.PI / 2);
  add(upper, box(0.15, 0.42, 0.06), std(color, { roughness: 0.9 }), 0.2, 1.2, 0.33, 0, 0, 0.2);
  for (const s of [-1, 1]) add(upper, capsule(0.08, 0.42), black, s * 0.49, 1.0, 0, 0, 0, s * 0.3);
  const feet = addFeet(root, 0xffa726, { w: 0.26, h: 0.08, d: 0.42, z: 0.1 });
  return { root, upper, feet, top: 2.2, tick: (t, speed) => { upper.rotation.z = speed > 0.3 ? Math.sin(t * 10) * 0.08 : 0; } };
}

function dragon(color) {
  const { root, upper } = rig();
  const scale = std(color, { roughness: 0.55 }), belly = std(mix(color, 0xffe6a0, 0.6), { roughness: 0.7 });
  const horn = std(0xf3ead7, { roughness: 0.5 }), wingMat = std(shade(color, 0.7), { side: THREE.DoubleSide, roughness: 0.6 });
  add(upper, capsule(0.45, 0.5), scale, 0, 0.95, -0.02).scale.z = 1.15;
  add(upper, sphere(0.3), belly, 0, 0.9, 0.3).scale.set(1, 1.35, 0.5);
  for (let k = 0; k < 4; k++) add(upper, box(0.36 - k * 0.03, 0.025, 0.05), std(shade(color, 0.85)), 0, 0.62 + k * 0.18, 0.44 - Math.abs(k - 1.5) * 0.02);
  const head = new THREE.Group(); head.position.set(0, 1.72, 0.05); upper.add(head);
  add(head, sphere(0.34, 20, 16), scale);
  add(head, box(0.36, 0.24, 0.42), scale, 0, -0.08, 0.32);
  add(head, box(0.32, 0.08, 0.36), belly, 0, -0.2, 0.32);
  for (const s of [-1, 1]) {
    add(head, cone(0.07, 0.4, 8), horn, s * 0.18, 0.32, -0.12, -0.6, 0, s * -0.35);
    add(head, sphere(0.025, 6, 6), basic(0x222222), s * 0.08, -0.02, 0.54);
    add(head, sphere(0.085, 12, 10), basic(0xffe14d), s * 0.17, 0.08, 0.24);
    add(head, sphere(0.04, 8, 6), basic(0x111111), s * 0.18, 0.08, 0.31).scale.y = 1.6;
  }
  // wings: membranes on bony arms, flapped in tick()
  const wings = [-1, 1].map((s) => {
    const w = new THREE.Group(); w.position.set(s * 0.3, 1.35, -0.32); upper.add(w);
    const shape = new THREE.Shape();
    shape.moveTo(0, 0); shape.lineTo(s * 1.0, 0.55); shape.lineTo(s * 1.05, 0.05); shape.lineTo(s * 0.75, -0.25);
    shape.lineTo(s * 0.45, -0.1); shape.lineTo(s * 0.25, -0.35); shape.lineTo(0, -0.2);
    add(w, new THREE.ShapeGeometry(shape), wingMat, 0, 0, 0, 0, s * -0.35, 0);
    add(w, cyl(0.03, 0.03, 1.15, 6), horn, s * 0.5, 0.28, 0, 0, s * -0.35, s * -1.07);
    return w;
  });
  const tail = new THREE.Group(); tail.position.set(0, 0.55, -0.45); upper.add(tail);
  const curve = new THREE.CatmullRomCurve3([[0, 0, 0], [0, -0.15, -0.4], [0.15, -0.25, -0.8], [0.3, -0.2, -1.1]].map((p) => new THREE.Vector3(...p)));
  add(tail, new THREE.TubeGeometry(curve, 20, 0.12, 8), scale);
  add(tail, cone(0.14, 0.3, 4), horn, 0.34, -0.2, -1.25, -Math.PI / 2);
  [[1.45, -0.42], [1.15, -0.5], [0.85, -0.5]].forEach(([y, z]) => add(upper, cone(0.08, 0.2, 4), horn, 0, y, z, -1.1));
  const feet = addFeet(root, shade(color, 0.6), { w: 0.3, d: 0.46 });
  return { root, upper, feet, top: 2.35, tick: (t, speed) => {
    const flap = Math.sin(t * (speed > 0.3 ? 9 : 3)) * (speed > 0.3 ? 0.55 : 0.2);
    wings[0].rotation.y = flap; wings[1].rotation.y = -flap;
    tail.rotation.y = Math.sin(t * 2.2) * 0.3;
  } };
}

function mech(color) {
  const { root, upper } = rig();
  const plate = std(0x5a6270, { metalness: 0.7, roughness: 0.35 }), paint = std(color, { metalness: 0.4, roughness: 0.35 });
  const dark = std(0x23272f, { metalness: 0.5, roughness: 0.5 });
  for (const s of [-1, 1]) {
    add(root, box(0.26, 0.5, 0.3), plate, s * 0.3, 0.5, 0);
    add(root, cyl(0.12, 0.12, 0.3, 10), dark, s * 0.3, 0.82, 0, 0, 0, Math.PI / 2);
  }
  add(upper, box(1.05, 0.8, 0.72), paint, 0, 1.25, 0);
  add(upper, box(0.9, 0.18, 0.74), dark, 0, 0.82, 0);
  const cockpit = add(upper, new THREE.SphereGeometry(0.32, 20, 12, 0, Math.PI * 2, 0, Math.PI / 2),
    new THREE.MeshStandardMaterial({ color: 0x9ff8ff, emissive: 0x1aa0c0, emissiveIntensity: 0.8, transparent: true, opacity: 0.8, roughness: 0.05 }), 0, 1.65, 0.1);
  add(upper, box(0.55, 0.22, 0.05), glow(0xffd23f, 0.8), 0, 1.3, 0.37);
  const lights = [];
  for (const s of [-1, 1]) {
    add(upper, box(0.36, 0.36, 0.5), plate, s * 0.72, 1.45, 0);
    add(upper, cyl(0.08, 0.08, 0.7, 10), dark, s * 0.72, 1.62, 0.25, Math.PI / 2);     // shoulder cannon
    lights.push(add(upper, sphere(0.05, 8, 6), glow(0xff3b3b, 2), s * 0.72, 1.62, 0.62));
    add(upper, box(0.2, 0.6, 0.24), plate, s * 0.72, 0.95, 0);
    add(upper, box(0.26, 0.2, 0.3), paint, s * 0.72, 0.6, 0.02);
  }
  add(upper, cyl(0.02, 0.02, 0.45, 6), dark, 0.3, 1.9, -0.2);
  const tip = add(upper, sphere(0.05, 8, 6), glow(color, 1.5), 0.3, 2.14, -0.2);
  const feet = addFeet(root, 0x3a4150, { w: 0.36, h: 0.22, d: 0.55, spread: 0.3 });
  return { root, upper, feet, top: 2.25, tick: (t, speed) => {
    const on = Math.sin(t * 4) > 0;
    lights[0].visible = on; lights[1].visible = !on;
    tip.material.emissiveIntensity = 1 + Math.sin(t * 6) * 0.6;
    cockpit.material.emissiveIntensity = 0.6 + Math.sin(t * 1.3) * 0.2;
    upper.rotation.z = speed > 0.3 ? Math.sin(t * 8) * 0.04 : 0;
  } };
}

function alien(color) {
  const { root, upper } = rig();
  const skin = std(0x9be36b, { roughness: 0.5 }), suit = std(color, { metalness: 0.3, roughness: 0.4 });
  add(upper, capsule(0.32, 0.45), suit, 0, 0.82, 0);
  add(upper, cyl(0.38, 0.38, 0.06, 20), std(0xc9d1db, { metalness: 0.8, roughness: 0.25 }), 0, 0.62, 0);
  add(upper, cyl(0.1, 0.12, 0.2, 10), skin, 0, 1.28, 0);
  const head = add(upper, sphere(0.42, 24, 18), skin, 0, 1.68, 0); head.scale.set(1, 1.1, 0.95);
  for (const s of [-1, 1]) {
    const eye = add(upper, sphere(0.13, 16, 12), std(0x0b0b12, { roughness: 0.1, metalness: 0.4 }), s * 0.17, 1.66, 0.33);
    eye.scale.set(1, 1.5, 0.5); eye.rotation.z = s * -0.4;
    add(upper, sphere(0.025, 6, 6), basic(0xffffff), s * 0.14, 1.75, 0.39);
    add(upper, cyl(0.015, 0.015, 0.4, 6), skin, s * 0.16, 2.2, -0.02, 0, 0, s * -0.3);
    add(upper, capsule(0.07, 0.35), skin, s * 0.38, 0.85, 0.08, -0.3, 0, s * 0.25);
  }
  const tips = [-1, 1].map((s) => add(upper, sphere(0.06, 10, 8), glow(color, 1.6), s * 0.22, 2.4, -0.02));
  // ray gun
  add(upper, box(0.08, 0.1, 0.32), std(0xc9d1db, { metalness: 0.8 }), 0.42, 0.66, 0.28);
  add(upper, sphere(0.05, 8, 6), glow(0x5ff6ff, 1.5), 0.42, 0.68, 0.46);
  const feet = addFeet(root, 0x3a4150, { w: 0.2, h: 0.14, d: 0.34, spread: 0.16 });
  return { root, upper, feet, top: 2.45, tick: (t) => {
    tips.forEach((m, i) => { m.material.emissiveIntensity = 1 + Math.sin(t * 5 + i * 2) * 0.8; });
    upper.position.y = Math.sin(t * 2) * 0.03;
  } };
}

function viking(color) {
  const { root, upper } = rig();
  add(upper, capsule(0.46, 0.5), std(color, { roughness: 0.85 }), 0, 0.95, 0);
  add(upper, cyl(0.475, 0.475, 0.12, 20, true), std(0x5a3a1e), 0, 0.72, 0);
  add(upper, box(0.12, 0.1, 0.04), std(GOLD, { metalness: 0.8, roughness: 0.3 }), 0, 0.72, 0.47);
  add(upper, sphere(0.36), std(SKIN, { roughness: 0.7 }), 0, 1.75, 0);
  const beard = std(0xd2691e, { roughness: 1 });
  add(upper, sphere(0.3), beard, 0, 1.55, 0.18).scale.set(1.05, 1.15, 0.75);
  for (const s of [-1, 1]) add(upper, cone(0.07, 0.3, 8), beard, s * 0.1, 1.26, 0.3, Math.PI);
  add(upper, box(0.22, 0.05, 0.06), beard, 0, 1.66, 0.34);
  addEyes(upper, 1.82, 0.32, { spread: 0.12, r: 0.045 });
  const helm = std(0xa9b2bd, { metalness: 0.85, roughness: 0.25 });
  add(upper, new THREE.SphereGeometry(0.39, 20, 10, 0, Math.PI * 2, 0, Math.PI / 2), helm, 0, 1.86, 0);
  add(upper, cyl(0.4, 0.4, 0.08, 20), std(GOLD, { metalness: 0.7, roughness: 0.3 }), 0, 1.86, 0);
  add(upper, box(0.06, 0.24, 0.06), helm, 0, 1.78, 0.38);
  const hornMat = std(0xf3ead7, { roughness: 0.5 });
  for (const s of [-1, 1]) {
    const hc = new THREE.CatmullRomCurve3([[0, 0, 0], [s * 0.18, 0.08, 0], [s * 0.3, 0.3, 0], [s * 0.28, 0.5, 0.05]].map((p) => new THREE.Vector3(...p)));
    add(upper, new THREE.TubeGeometry(hc, 12, 0.055, 8), hornMat, s * 0.32, 2.0, 0);
  }
  // round shield and axe
  add(upper, cyl(0.38, 0.38, 0.06, 24), std(color, { roughness: 0.6 }), 0.55, 0.95, 0.05, 0, 0, Math.PI / 2);
  add(upper, new THREE.TorusGeometry(0.38, 0.03, 6, 24), std(0x9aa3ad, { metalness: 0.8 }), 0.59, 0.95, 0.05, 0, Math.PI / 2, 0);
  add(upper, sphere(0.09, 10, 8), std(GOLD, { metalness: 0.8, roughness: 0.3 }), 0.6, 0.95, 0.05);
  add(upper, cyl(0.03, 0.03, 0.9, 8), std(0x7a5230), -0.55, 0.75, 0.15);
  add(upper, box(0.04, 0.3, 0.28), std(0xc9d1db, { metalness: 0.85, roughness: 0.25 }), -0.55, 1.12, 0.3);
  const feet = addFeet(root, 0x5a3a1e);
  return { root, upper, feet, top: 2.55 };
}

function skeleton(color) {
  const { root, upper } = rig();
  const bone = std(0xf1ecdf, { roughness: 0.7 });
  add(upper, cyl(0.06, 0.06, 0.85, 8), bone, 0, 0.95, -0.05);
  for (let k = 0; k < 4; k++) add(upper, new THREE.TorusGeometry(0.28 - k * 0.025, 0.035, 6, 20), bone, 0, 1.25 - k * 0.14, 0, Math.PI / 2);
  add(upper, new THREE.TorusGeometry(0.3, 0.05, 6, 20), bone, 0, 0.62, 0, Math.PI / 2);
  for (const s of [-1, 1]) {
    add(upper, cyl(0.04, 0.035, 0.55, 8), bone, s * 0.36, 1.0, 0.02, 0, 0, s * 0.12);
    add(upper, sphere(0.06, 8, 6), bone, s * 0.4, 0.7, 0.03);
    add(root, cyl(0.045, 0.04, 0.55, 8), bone, s * 0.15, 0.32, 0);
  }
  const skull = add(upper, sphere(0.33, 20, 16), bone, 0, 1.68, 0); skull.scale.set(1, 1.05, 1.05);
  for (const s of [-1, 1]) add(upper, sphere(0.085, 12, 10), basic(0x15151a), s * 0.12, 1.72, 0.27).scale.set(1, 1.2, 0.5);
  const glowEyes = [-1, 1].map((s) => add(upper, sphere(0.03, 8, 6), glow(color, 2), s * 0.12, 1.72, 0.31));
  add(upper, cone(0.04, 0.08, 3), basic(0x15151a), 0, 1.6, 0.31, Math.PI);
  const jaw = add(upper, box(0.3, 0.09, 0.22), bone, 0, 1.44, 0.12);
  for (let k = -2; k <= 2; k++) add(jaw, box(0.035, 0.04, 0.02), basic(0x15151a), k * 0.055, 0.04, 0.11);
  // the player's colour as a bandana and scarf so skeletons stay distinguishable
  add(upper, new THREE.SphereGeometry(0.345, 20, 8, 0, Math.PI * 2, 0, Math.PI / 2.6), std(color, { roughness: 0.9 }), 0, 1.74, 0);
  add(upper, new THREE.TorusGeometry(0.17, 0.07, 8, 20), std(color, { roughness: 0.9 }), 0, 1.33, 0, Math.PI / 2);
  const feet = addFeet(root, 0xf1ecdf, { w: 0.16, h: 0.1, d: 0.32, spread: 0.15 });
  return { root, upper, feet, top: 2.15, tick: (t) => {
    jaw.position.y = 1.44 - Math.max(0, Math.sin(t * 9)) * 0.04;
    glowEyes.forEach((e) => { e.material.emissiveIntensity = 1.5 + Math.sin(t * 3) * 0.8; });
  } };
}

function bee(color) {
  const { root, upper } = rig();
  const yellow = std(0xffd23f, { roughness: 0.5 }), stripe = std(color, { roughness: 0.5 }), black = std(0x1d1d24, { roughness: 0.5 });
  const body = add(upper, sphere(0.5, 24, 18), yellow, 0, 1.0, 0); body.scale.set(1, 1.1, 1.15);
  for (const [y, r] of [[0.78, 0.43], [1.0, 0.52], [1.22, 0.45]]) add(upper, cyl(r, r, 0.1, 24, true), stripe, 0, y, 0);
  add(upper, cone(0.1, 0.3, 10), black, 0, 0.42, -0.25, Math.PI + 0.6);
  const head = add(upper, sphere(0.3, 20, 16), black, 0, 1.72, 0.08);
  for (const s of [-1, 1]) {
    add(upper, sphere(0.11, 12, 10), std(0x111111, { roughness: 0.1, metalness: 0.4 }), s * 0.15, 1.76, 0.28).scale.set(0.8, 1.1, 0.6);
    add(upper, sphere(0.03, 6, 6), basic(0xffffff), s * 0.13, 1.8, 0.34);
    add(upper, cyl(0.015, 0.015, 0.35, 6), black, s * 0.12, 2.08, 0.12, 0.4, 0, s * -0.4);
    add(upper, sphere(0.05, 8, 6), stripe, s * 0.2, 2.24, 0.2);
  }
  const wingMat = new THREE.MeshStandardMaterial({ color: 0xe8f6ff, transparent: true, opacity: 0.55, side: THREE.DoubleSide, roughness: 0.1 });
  const wings = [-1, 1].map((s) => {
    const w = new THREE.Group(); w.position.set(s * 0.2, 1.42, -0.2); upper.add(w);
    add(w, sphere(0.35, 14, 10), wingMat, s * 0.32, 0.1, 0).scale.set(1, 0.6, 0.08);
    return w;
  });
  const feet = addFeet(root, 0x1d1d24, { w: 0.14, h: 0.12, d: 0.24, spread: 0.18 });
  head.scale.set(1, 1, 1);
  return { root, upper, feet, top: 2.35, tick: (t) => {
    const f = Math.sin(t * 40) * 0.5;
    wings[0].rotation.y = 0.3 + f; wings[1].rotation.y = -0.3 - f;
    upper.position.y = 0.12 + Math.sin(t * 3) * 0.06;
  } };
}

export const CHARACTERS = [
  { id: 'miner', name: 'Miner', blurb: 'Hard hat, headlamp, nerves of steel.', build: miner },
  { id: 'robot', name: 'Robot', blurb: 'Beep boop. Mine detection not included.', build: robot },
  { id: 'knight', name: 'Knight', blurb: 'The armour will not help you here.', build: knight },
  { id: 'wizard', name: 'Wizard', blurb: 'Foresaw the mines. Forgot where.', build: wizard },
  { id: 'astronaut', name: 'Astronaut', blurb: 'One small step… carefully.', build: astronaut },
  { id: 'ninja', name: 'Ninja', blurb: 'Silent, swift, occasionally exploded.', build: ninja },
  { id: 'cat', name: 'Cat', blurb: 'Has nine lives. Will need them.', build: cat },
  { id: 'dino', name: 'Dino', blurb: 'Survived one extinction already.', build: dino },
  { id: 'pirate', name: 'Pirate', blurb: 'X marks the spot. So do mines.', build: pirate },
  { id: 'ghost', name: 'Ghost', blurb: 'Already blew up once. Back for more.', build: ghost },
  { id: 'mushroom', name: 'Mushroom', blurb: 'Fungi to be around.', build: mushroom },
  { id: 'penguin', name: 'Penguin', blurb: 'Waddles into danger with a scarf.', build: penguin },
  { id: 'dragon', name: 'Dragon', blurb: 'Hoards gold. Now hoarding safe tiles.', build: dragon },
  { id: 'mech', name: 'Mech', blurb: 'A walking tank with shoulder cannons and a bubble cockpit.', build: mech },
  { id: 'alien', name: 'Alien', blurb: 'Came in peace. Stayed for the minesweeping.', build: alien },
  { id: 'viking', name: 'Viking', blurb: 'Raids dungeons for a living.', build: viking },
  { id: 'skeleton', name: 'Skeleton', blurb: 'Has already been through the worst.', build: skeleton },
  { id: 'bee', name: 'Bee', blurb: 'Buzzes from tile to tile. Do not swat.', build: bee },
];
export const CHAR_BY_ID = Object.fromEntries(CHARACTERS.map((c) => [c.id, c]));

export function buildCharacter(id, color) {
  const def = CHAR_BY_ID[id] || CHARACTERS[0];
  const c = def.build(color);
  c.root.traverse((o) => { if (o.isMesh) o.castShadow = true; });
  return c;
}
