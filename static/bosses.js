// Boss monsters (kinds must match BOSS_KINDS in server.py). Built from Three.js primitives like the
// characters, about 2.5x their size. build() returns { root, body, top, tick(t, state, speed) } where
// state is 0 wander, 1 chase, 2 wind-up, 3 frozen, 4 stunned.
import * as THREE from 'three';

const std = (color, o = {}) => new THREE.MeshStandardMaterial({ color, roughness: 0.7, ...o });
const glow = (color, k = 1.5) => new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: k, roughness: 0.4 });
function add(parent, geo, mat, x = 0, y = 0, z = 0, rx = 0, ry = 0, rz = 0) {
  const m = new THREE.Mesh(geo, mat); m.position.set(x, y, z); m.rotation.set(rx, ry, rz); m.castShadow = true;
  parent.add(m); return m;
}
const sphere = (r, w = 18, h = 14) => new THREE.SphereGeometry(r, w, h);
const box = (w, h, d) => new THREE.BoxGeometry(w, h, d);
const cyl = (a, b, h, s = 12) => new THREE.CylinderGeometry(a, b, h, s);
const cone = (r, h, s = 10) => new THREE.ConeGeometry(r, h, s);

function ogre() {
  const root = new THREE.Group(), body = new THREE.Group(); root.add(body);
  const skin = std(0x7ea04a), dark = std(0x4a3a2a), cloth = std(0x6b4a2b, { roughness: 1 });
  add(body, sphere(1.3), skin, 0, 2.2, 0).scale.set(1.15, 1.05, 0.95);
  add(body, cyl(1.2, 1.1, 0.6, 16), cloth, 0, 1.4, 0);
  const head = new THREE.Group(); head.position.set(0, 3.55, 0.2); body.add(head);
  add(head, sphere(0.75), skin).scale.set(1.1, 0.95, 1);
  add(head, box(1.0, 0.18, 0.2), dark, 0, 0.35, 0.62, 0.15);            // heavy brow
  for (const s of [-1, 1]) {
    add(head, sphere(0.13, 10, 8), glow(0xffd23f, 1.2), s * 0.3, 0.15, 0.66);
    add(head, cone(0.09, 0.35, 6), std(0xf3ead7), s * 0.28, -0.42, 0.62, 0.3);   // tusks
    add(head, sphere(0.2, 10, 8), skin, s * 0.78, 0.1, 0).scale.set(0.5, 1, 0.8); // ears
  }
  const arms = [-1, 1].map((s) => {
    const a = new THREE.Group(); a.position.set(s * 1.45, 2.8, 0); body.add(a);
    add(a, cyl(0.35, 0.3, 1.6), skin, 0, -0.8, 0);
    add(a, sphere(0.42, 12, 10), skin, 0, -1.65, 0.05);
    return a;
  });
  // a big wooden club in the right hand
  const club = new THREE.Group(); club.position.set(0, -1.7, 0.2); arms[1].add(club);
  add(club, cyl(0.12, 0.16, 1.6, 8), dark, 0, 0.6, 0.4, 1.2);
  add(club, sphere(0.42, 10, 8), dark, 0, 1.1, 1.05).scale.set(1, 1.3, 1);
  const legs = [-1, 1].map((s) => add(root, cyl(0.42, 0.38, 1.3), skin, s * 0.6, 0.65, 0));
  return { root, body, top: 4.6, tick(t, state, speed) {
    const wind = state === 2;
    arms[1].rotation.x = wind ? -2.4 : Math.sin(t * 3) * 0.25 * Math.min(1, speed);
    arms[0].rotation.x = -Math.sin(t * 3) * 0.25 * Math.min(1, speed);
    legs.forEach((l, i) => { l.position.z = Math.sin(t * 5 + i * Math.PI) * 0.3 * Math.min(1, speed); });
    body.rotation.z = Math.sin(t * 2.5) * 0.04;
  } };
}

function wraith() {
  const root = new THREE.Group(), body = new THREE.Group(); root.add(body);
  const robe = new THREE.MeshStandardMaterial({ color: 0x2a2440, emissive: 0x3a1a66, emissiveIntensity: 0.5, roughness: 0.8,
    transparent: true, opacity: 0.92, side: THREE.DoubleSide });
  const pts = [];
  for (let k = 0; k <= 12; k++) pts.push(new THREE.Vector2(0.4 + (k / 12) * 1.0 + Math.sin(k) * 0.05, 3.4 - (k / 12) * 3.0));
  const geo = new THREE.LatheGeometry(pts, 24);
  const pos = geo.attributes.position;
  for (let i = 0; i < pos.count; i++) if (pos.getY(i) < 0.8) pos.setY(i, pos.getY(i) + Math.sin(Math.atan2(pos.getZ(i), pos.getX(i)) * 6) * 0.25);
  geo.computeVertexNormals();
  add(body, geo, robe);
  add(body, new THREE.SphereGeometry(0.65, 18, 12, 0, Math.PI * 2, 0, Math.PI * 0.62), robe, 0, 3.5, 0); // hood
  add(body, sphere(0.45), std(0x05030a), 0, 3.35, 0.18);
  const eyes = [-1, 1].map((s) => add(body, sphere(0.09, 10, 8), glow(0x5ff6ff, 2.5), s * 0.17, 3.42, 0.55));
  const hands = [-1, 1].map((s) => add(body, sphere(0.2, 10, 8), std(0xd8d0ff, { emissive: 0x5a3aa0, emissiveIntensity: 0.6 }), s * 1.1, 2.3, 0.4));
  // floating soul orbs
  const orbs = new THREE.Group(); body.add(orbs);
  for (let k = 0; k < 3; k++) add(orbs, sphere(0.14, 10, 8), glow(0x9b6bff, 2), Math.cos(k * 2.1) * 1.6, 2.6, Math.sin(k * 2.1) * 1.6);
  return { root, body, top: 4.2, tick(t, state) {
    body.position.y = 0.4 + Math.sin(t * 2) * 0.25;
    orbs.rotation.y = t * (state === 1 ? 3 : 1.2);
    const wind = state === 2;
    hands.forEach((h, i) => { h.position.y = wind ? 3.6 : 2.3 + Math.sin(t * 3 + i) * 0.15; });
    eyes.forEach((e) => { e.material.emissiveIntensity = wind ? 5 : 2.5 + Math.sin(t * 6) * 0.8; });
  } };
}

function golem() {
  const root = new THREE.Group(), body = new THREE.Group(); root.add(body);
  const rock = std(0x7d8590, { flatShading: true, roughness: 0.9 }), moss = std(0x4f7a3a, { flatShading: true });
  const core = glow(0xff8a2a, 1.8);
  add(body, new THREE.DodecahedronGeometry(1.4, 0), rock, 0, 2.4, 0).scale.set(1.2, 1, 0.9);
  add(body, new THREE.DodecahedronGeometry(0.5, 0), moss, 0.6, 3.3, -0.2);
  const heart = add(body, new THREE.OctahedronGeometry(0.35), core, 0, 2.5, 1.05);
  add(body, new THREE.DodecahedronGeometry(0.7, 0), rock, 0, 3.8, 0.2);
  const eyes = [-1, 1].map((s) => add(body, box(0.22, 0.08, 0.05), core, s * 0.25, 3.9, 0.82));
  const arms = [-1, 1].map((s) => {
    const a = new THREE.Group(); a.position.set(s * 1.7, 3.0, 0); body.add(a);
    add(a, new THREE.DodecahedronGeometry(0.55, 0), rock, 0, -0.5, 0);
    add(a, new THREE.DodecahedronGeometry(0.7, 0), rock, 0, -1.5, 0.1);
    return a;
  });
  const legs = [-1, 1].map((s) => add(root, new THREE.DodecahedronGeometry(0.6, 0), rock, s * 0.7, 0.6, 0));
  return { root, body, top: 4.6, tick(t, state, speed) {
    const wind = state === 2;
    arms.forEach((a) => { a.rotation.x = wind ? -2.6 : Math.sin(t * 2) * 0.15 * Math.min(1, speed); });
    legs.forEach((l, i) => { l.position.y = 0.6 + Math.max(0, Math.sin(t * 3.5 + i * Math.PI)) * 0.25 * Math.min(1, speed); });
    const k = wind ? 4 : 1.6 + Math.sin(t * 3) * 0.5;
    heart.material.emissiveIntensity = k; eyes.forEach((e) => { e.material.emissiveIntensity = k; });
    heart.rotation.y = t * 2;
  } };
}

export const BOSSES = {
  ogre: { name: 'Ogre', color: '#a3e635', build: ogre },
  wraith: { name: 'Wraith', color: '#c77dff', build: wraith },
  golem: { name: 'Golem', color: '#ff9f43', build: golem },
};
