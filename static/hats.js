// Cosmetic hats, unlocked by stats saved in a player's profile (see store.py HATS on the server, which
// decides what is unlocked; ids must match). Built from Three.js primitives; a hat sits on top of the
// character (y = 0 is the top of the character) and faces +Z like the characters do.
import * as THREE from 'three';

const std = (color, o = {}) => new THREE.MeshStandardMaterial({ color, roughness: 0.55, ...o });
function add(g, geo, mat, x = 0, y = 0, z = 0, rx = 0, ry = 0, rz = 0) {
  const m = new THREE.Mesh(geo, mat); m.position.set(x, y, z); m.rotation.set(rx, ry, rz); m.castShadow = true; g.add(m); return m;
}

export const HATS = [
  { id: 'party', name: 'Party hat' },
  { id: 'beanie', name: 'Beanie' },
  { id: 'flower', name: 'Flower' },
  { id: 'horns', name: 'Horns' },
  { id: 'tophat', name: 'Top hat' },
  { id: 'crown', name: 'Crown' },
  { id: 'halo', name: 'Halo' },
];

// height the hat adds above the character (name tags and health bars move up by this much)
export const HAT_HEIGHT = { party: 0.55, beanie: 0.25, flower: 0.3, horns: 0.35, tophat: 0.55, crown: 0.35, halo: 0.45 };

export function buildHat(id, color = '#ffd23f') {
  const g = new THREE.Group();
  if (id === 'party') {
    add(g, new THREE.ConeGeometry(0.22, 0.5, 18), std(color), 0, 0.22, 0, -0.12);
    for (let k = 0; k < 3; k++) add(g, new THREE.TorusGeometry(0.2 - k * 0.06, 0.018, 6, 20), std(0xffffff), 0, 0.06 + k * 0.13, 0.03 - k * 0.02, Math.PI / 2 - 0.12);
    add(g, new THREE.SphereGeometry(0.07, 10, 8), std(0xffffff), 0, 0.48, -0.06);
  } else if (id === 'beanie') {
    add(g, new THREE.SphereGeometry(0.32, 20, 12, 0, Math.PI * 2, 0, Math.PI / 2), std(color, { roughness: 0.9 }), 0, -0.05, 0);
    add(g, new THREE.CylinderGeometry(0.33, 0.34, 0.1, 20), std(0xf4f6f8, { roughness: 0.9 }), 0, -0.04, 0);
    add(g, new THREE.SphereGeometry(0.09, 10, 8), std(0xf4f6f8, { roughness: 1 }), 0, 0.28, 0);
  } else if (id === 'flower') {
    const petal = std(0xff8cc3), centre = std(0xffd23f);
    for (let k = 0; k < 6; k++) {
      const a = (k / 6) * Math.PI * 2;
      const p = add(g, new THREE.SphereGeometry(0.09, 10, 8), petal, Math.cos(a) * 0.11, 0.12, Math.sin(a) * 0.11);
      p.scale.set(1, 0.4, 1);
    }
    add(g, new THREE.SphereGeometry(0.07, 10, 8), centre, 0, 0.14, 0);
    add(g, new THREE.CylinderGeometry(0.015, 0.015, 0.12, 6), std(0x4fd67a), 0, 0.05, 0);
    g.position.x = 0.12; g.rotation.z = -0.3;
  } else if (id === 'horns') {
    const bone = std(0xf1e6cf, { roughness: 0.4 });
    for (const s of [-1, 1]) add(g, new THREE.ConeGeometry(0.08, 0.38, 12), bone, s * 0.2, 0.12, 0, 0, 0, -s * 0.45);
  } else if (id === 'tophat') {
    const black = std(0x15151a, { roughness: 0.35 });
    add(g, new THREE.CylinderGeometry(0.36, 0.36, 0.04, 24), black, 0, 0.0, 0);
    add(g, new THREE.CylinderGeometry(0.22, 0.24, 0.46, 24), black, 0, 0.24, 0);
    add(g, new THREE.CylinderGeometry(0.245, 0.245, 0.08, 24), std(color), 0, 0.06, 0);
  } else if (id === 'crown') {
    const gold = std(0xffc233, { metalness: 0.85, roughness: 0.25, emissive: 0x5a3a00, emissiveIntensity: 0.4 });
    add(g, new THREE.CylinderGeometry(0.27, 0.27, 0.14, 20, 1, true), gold, 0, 0.05, 0);
    for (let k = 0; k < 6; k++) {
      const a = (k / 6) * Math.PI * 2;
      add(g, new THREE.ConeGeometry(0.06, 0.18, 8), gold, Math.cos(a) * 0.25, 0.2, Math.sin(a) * 0.25);
      add(g, new THREE.SphereGeometry(0.035, 8, 6), std(k % 2 ? 0xff4d6d : 0x4fa3ff, { roughness: 0.2 }), Math.cos(a) * 0.27, 0.06, Math.sin(a) * 0.27);
    }
  } else if (id === 'halo') {
    const ring = add(g, new THREE.TorusGeometry(0.26, 0.04, 10, 32), new THREE.MeshStandardMaterial({
      color: 0xfff3b0, emissive: 0xffe066, emissiveIntensity: 1.4, roughness: 0.3 }), 0, 0.35, 0, Math.PI / 2);
    ring.castShadow = false;
    g.userData.tick = (t) => { ring.position.y = 0.35 + Math.sin(t * 2.2) * 0.04; };
  }
  return g;
}
