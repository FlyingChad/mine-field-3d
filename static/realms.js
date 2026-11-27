// Realms: the world the minefield sits in. Each is a palette + gravity + procedural scenery/weather.
// Ids must match REALM_IDS in server.py. Scenery is built from Three.js primitives only.
import * as THREE from 'three';

const Std = (color, extra = {}) => new THREE.MeshStandardMaterial({ color, roughness: 0.9, ...extra });
const Glow = (color, extra = {}) => new THREE.MeshBasicMaterial({ color, ...extra });

// ---------------------------------------------------------------- shared helpers
function around(ctx, n, minR, maxR, fn) {
  for (let i = 0; i < n; i++) {
    let x, z;
    do { x = (ctx.rnd() - 0.5) * maxR * 2; z = (ctx.rnd() - 0.5) * maxR * 2; }
    while (Math.abs(x) < minR && Math.abs(z) < minR);
    fn(x, z, i);
  }
}

// instanced scatter: parts = [{geo, mat, place(i, x, z, k, rnd) -> [y, sx, sy, sz, rotY]}]
function instanced(ctx, n, minR, maxR, parts, scale = [0.7, 1.6]) {
  n = Math.max(1, Math.round(n * (ctx.quality ?? 1)));   // fewer props on phones
  const meshes = parts.map((p) => {
    const m = new THREE.InstancedMesh(p.geo, p.mat, n);
    m.castShadow = p.shadow !== false; ctx.group.add(m); return m;
  });
  const q = new THREE.Quaternion(), s = new THREE.Vector3(), v = new THREE.Vector3(), M = new THREE.Matrix4();
  const up = new THREE.Vector3(0, 1, 0);
  around(ctx, n, minR, maxR, (x, z, i) => {
    const k = scale[0] + ctx.rnd() * (scale[1] - scale[0]);
    const rot = ctx.rnd() * 6.28;
    parts.forEach((p, j) => {
      const [y, sx, sy, sz, ox = 0, oz = 0, tilt = 0] = p.place(k, ctx.rnd);
      q.setFromAxisAngle(up, rot);
      if (tilt) q.multiply(new THREE.Quaternion().setFromEuler(new THREE.Euler(0, 0, tilt)));
      const c = Math.cos(rot), sn = Math.sin(rot);
      meshes[j].setMatrixAt(i, M.compose(v.set(x + ox * c + oz * sn, ctx.floor + y, z - ox * sn + oz * c), q, s.set(sx, sy, sz)));
    });
  });
  return meshes;
}

function clouds(ctx, { color = 0xffffff, opacity = 0.92, count = 14, height = 45 } = {}) {
  const mat = new THREE.MeshStandardMaterial({ color, roughness: 1, transparent: true, opacity });
  const list = [];
  for (let i = 0; i < count; i++) {
    const c = new THREE.Group();
    for (let j = 0; j < 4; j++) {
      const b = new THREE.Mesh(new THREE.SphereGeometry(3 + ctx.rnd() * 3, 12, 10), mat);
      b.position.set(j * 4 - 6, ctx.rnd() * 2, ctx.rnd() * 3); b.scale.y = 0.6;
      c.add(b);
    }
    c.position.set((ctx.rnd() - 0.5) * 300, height + ctx.rnd() * 20, (ctx.rnd() - 0.5) * 300);
    c.userData.speed = 1 + ctx.rnd() * 2;
    list.push(c); ctx.group.add(c);
  }
  ctx.tick((dt) => { for (const c of list) { c.position.x += c.userData.speed * dt; if (c.position.x > 160) c.position.x = -160; } });
}

// particles that live in a box around the local player
function weather(ctx, { count, color = 0xffffff, colors = null, size, opacity = 0.9, vel, sway = 0, additive = false, spanY = 30, baseY = -0.5 }) {
  const span = 90;
  count = Math.max(1, Math.round(count * (ctx.quality ?? 1)));
  const P = new Float32Array(count * 3), phase = new Float32Array(count);
  for (let i = 0; i < count; i++) {
    P[i * 3] = (Math.random() - 0.5) * span; P[i * 3 + 1] = baseY + Math.random() * spanY; P[i * 3 + 2] = (Math.random() - 0.5) * span;
    phase[i] = Math.random() * 6.28;
  }
  const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.BufferAttribute(P, 3));
  if (colors) {
    const C = new Float32Array(count * 3), c = new THREE.Color();
    for (let i = 0; i < count; i++) { c.set(colors[i % colors.length]); C.set([c.r, c.g, c.b], i * 3); }
    geo.setAttribute('color', new THREE.BufferAttribute(C, 3));
  }
  const mat = new THREE.PointsMaterial({ color: colors ? 0xffffff : color, vertexColors: !!colors, size, transparent: true, opacity, depthWrite: false,
    blending: additive ? THREE.AdditiveBlending : THREE.NormalBlending });
  const pts = new THREE.Points(geo, mat); pts.frustumCulled = false; ctx.group.add(pts);
  ctx.tick((dt, t, me) => {
    for (let i = 0; i < count; i++) {
      const j = i * 3;
      P[j] += (vel[0] + Math.sin(t * 1.3 + phase[i]) * sway) * dt;
      P[j + 1] += vel[1] * dt;
      P[j + 2] += (vel[2] + Math.cos(t * 1.1 + phase[i]) * sway) * dt;
      // wrap around the player
      if (P[j] - me.x > span / 2) P[j] -= span; else if (P[j] - me.x < -span / 2) P[j] += span;
      if (P[j + 2] - me.z > span / 2) P[j + 2] -= span; else if (P[j + 2] - me.z < -span / 2) P[j + 2] += span;
      if (P[j + 1] < baseY) P[j + 1] += spanY; else if (P[j + 1] > baseY + spanY) P[j + 1] -= spanY;
    }
    geo.attributes.position.needsUpdate = true;
  });
}

function pines(ctx, n, { trunk = 0x6b4a2b, leaf = 0x2f7d3b, snow = null } = {}) {
  const parts = [
    { geo: new THREE.CylinderGeometry(0.25, 0.35, 2, 6), mat: Std(trunk), place: (k) => [k, k, k, k] },
    { geo: new THREE.ConeGeometry(1.6, 3.6, 7), mat: Std(leaf, { flatShading: true }), place: (k) => [k * 3, k, k, k] },
    { geo: new THREE.ConeGeometry(1.6, 3.6, 7), mat: Std(leaf, { flatShading: true }), place: (k) => [k * 4.4, k * 0.72, k * 0.75, k * 0.72] },
  ];
  if (snow) parts.push({ geo: new THREE.ConeGeometry(1.0, 1.4, 7), mat: Std(snow, { flatShading: true }), place: (k) => [k * 5.5, k * 0.75, k * 0.8, k * 0.75] });
  instanced(ctx, n, ctx.lim, 110, parts);
}

function rocks(ctx, n, color, { maxR = 80, flat = 0.7 } = {}) {
  instanced(ctx, n, ctx.lim - 3, maxR, [
    { geo: new THREE.DodecahedronGeometry(0.8, 0), mat: Std(color, { flatShading: true }), place: (k) => [k * 0.3, k, k * flat, k] },
  ], [0.4, 1.6]);
}

// ---------------------------------------------------------------- realms
export const REALMS = [
  {
    id: 'meadow', name: 'Meadow', blurb: 'Rolling grass, pine woods and lazy clouds.',
    swatch: 'linear-gradient(#8cc4ee 0 45%, #5f9e47 45%)',
    sky: 0x8cc4ee, fog: [70, 190], hemi: [0xe4f3ff, 0x5b4a30, 1.1], sun: [0xfff3dd, 2.2],
    ground: 0x5f9e47, dirt: 0x7a5a3a, seam: 0x3f6a2c,
    cover: [0x76c853, 0x67b847], slab: [0xead6a8, 0xdcc596], gravity: 1,
    decor(ctx) {
      pines(ctx, 170);
      rocks(ctx, 60, 0x8a8f98);
      // flowers
      instanced(ctx, 260, ctx.lim - 4, 70, [
        { geo: new THREE.SphereGeometry(0.18, 6, 5), mat: Std(0xffe066), place: () => [0.15, 1, 1, 1], shadow: false },
      ], [0.6, 1.3]);
      instanced(ctx, 200, ctx.lim - 4, 70, [
        { geo: new THREE.SphereGeometry(0.18, 6, 5), mat: Std(0xff7fb0), place: () => [0.15, 1, 1, 1], shadow: false },
      ], [0.6, 1.3]);
      clouds(ctx);
    },
  },
  {
    id: 'desert', name: 'Dune Sea', blurb: 'Scorching sand, cacti and red mesas. Watch for blowing dust.',
    swatch: 'linear-gradient(#f6cf8f 0 45%, #d9a85f 45%)',
    sky: 0xf3d3a0, fog: [60, 170], hemi: [0xfff1d6, 0x8a5a2a, 1.15], sun: [0xffe2b0, 2.6],
    ground: 0xd9a85f, dirt: 0x9a6a3a, seam: 0x8a5d30,
    cover: [0xd08f45, 0xc4833b], slab: [0xf7ead0, 0xeedcba], gravity: 1,
    decor(ctx) {
      const cactus = Std(0x4c8a3c, { flatShading: true });
      instanced(ctx, 90, ctx.lim, 100, [
        { geo: new THREE.CylinderGeometry(0.4, 0.45, 4, 8), mat: cactus, place: (k) => [k * 2, k, k, k] },
        { geo: new THREE.CylinderGeometry(0.28, 0.28, 1.6, 8), mat: cactus, place: (k) => [k * 2.6, k, k, k, 0.75 * k, 0] },
        { geo: new THREE.CylinderGeometry(0.28, 0.28, 1.2, 8), mat: cactus, place: (k) => [k * 1.9, k, k, k, -0.75 * k, 0] },
        { geo: new THREE.CylinderGeometry(0.22, 0.22, 0.9, 6), mat: cactus, place: (k) => [k * 1.8, k * 0.9, k, k * 0.9, 0.45 * k, 0, Math.PI / 2] },
        { geo: new THREE.CylinderGeometry(0.22, 0.22, 0.9, 6), mat: cactus, place: (k) => [k * 1.3, k * 0.9, k, k * 0.9, -0.45 * k, 0, Math.PI / 2] },
      ]);
      // mesas: stacked flat-shaded slabs in red rock
      const mesaMat = [Std(0xb5562f, { flatShading: true }), Std(0xc9703f, { flatShading: true })];
      around(ctx, 16, ctx.lim + 25, 150, (x, z) => {
        const g = new THREE.Group(), w = 8 + ctx.rnd() * 14, h = 6 + ctx.rnd() * 10;
        for (let l = 0; l < 3; l++) {
          const m = new THREE.Mesh(new THREE.CylinderGeometry(w * (1 - l * 0.12), w * (1.05 - l * 0.12), h / 3, 7), mesaMat[l % 2]);
          m.position.y = h / 6 + l * h / 3; m.castShadow = true; g.add(m);
        }
        g.position.set(x, ctx.floor, z); g.rotation.y = ctx.rnd() * 6; ctx.group.add(g);
      });
      rocks(ctx, 50, 0xb07a4a);
      // bleached bones
      instanced(ctx, 25, ctx.lim - 3, 50, [
        { geo: new THREE.CapsuleGeometry(0.1, 1.2, 3, 6), mat: Std(0xf4efe2), place: (k) => [0.12, k, k, k, 0, 0, Math.PI / 2] },
      ]);
      weather(ctx, { count: 700, color: 0xe8c48a, size: 0.18, opacity: 0.55, vel: [6, 0, 1.5], sway: 1.5, spanY: 6 });
      clouds(ctx, { count: 5, opacity: 0.7 });
    },
  },
  {
    id: 'tundra', name: 'Frostbite Tundra', blurb: 'Snow-laden pines, ice crystals and steady snowfall.',
    swatch: 'linear-gradient(#cfe3f1 0 45%, #eef4f8 45%)',
    sky: 0xc9dceb, fog: [45, 150], hemi: [0xeaf4ff, 0x6a7f95, 1.25], sun: [0xe8f2ff, 1.9],
    ground: 0xeef4f8, dirt: 0x8796a6, seam: 0x93a8ba,
    cover: [0xf5f9fc, 0xe2ecf4], slab: [0x9fb4c6, 0x93a9bc], gravity: 1,
    decor(ctx) {
      pines(ctx, 190, { leaf: 0x2c5e4a, trunk: 0x4f3a2a, snow: 0xffffff });
      // ice crystal clusters
      const ice = new THREE.MeshStandardMaterial({ color: 0xaee3ff, roughness: 0.1, metalness: 0.1, transparent: true, opacity: 0.8, flatShading: true });
      instanced(ctx, 45, ctx.lim - 2, 70, [
        { geo: new THREE.OctahedronGeometry(0.8, 0), mat: ice, place: (k) => [k * 1.2, k * 0.6, k * 1.8, k * 0.6] },
        { geo: new THREE.OctahedronGeometry(0.6, 0), mat: ice, place: (k) => [k * 0.8, k * 0.5, k * 1.4, k * 0.5, k * 0.7, 0.3, 0.4] },
      ], [0.6, 1.5]);
      // snow drifts
      instanced(ctx, 70, ctx.lim - 3, 80, [
        { geo: new THREE.SphereGeometry(1, 10, 6), mat: Std(0xffffff), place: (k) => [0, k * 2.4, k * 0.5, k * 1.6], shadow: false },
      ]);
      weather(ctx, { count: 1600, color: 0xffffff, size: 0.28, vel: [0.6, -2.8, 0.2], sway: 0.8 });
      clouds(ctx, { color: 0xdfe6ee, count: 18, height: 40 });
    },
  },
  {
    id: 'volcano', name: 'Molten Caldera', blurb: 'Black basalt, lava rivers and rising embers under a red sky.',
    swatch: 'linear-gradient(#4a1f1a 0 45%, #2b2523 45% 70%, #ff6a1a 70% 76%, #2b2523 76%)',
    sky: 0x3b1a16, fog: [50, 160], hemi: [0xffb08a, 0x2a1010, 0.9], sun: [0xff9a6a, 1.6],
    ground: 0x2b2523, dirt: 0x1d1715, seam: 0x1a1412,
    cover: [0x5a4c47, 0x4e413c], slab: [0xa8998f, 0x9b8c82], gravity: 1,
    decor(ctx) {
      const lava = Glow(0xff6a1a);
      // lava pools and a river ring around the field
      around(ctx, 26, ctx.lim + 3, 75, (x, z) => {
        const r = 1.5 + ctx.rnd() * 4;
        const m = new THREE.Mesh(new THREE.CircleGeometry(r, 18), lava);
        m.rotation.x = -Math.PI / 2; m.position.set(x, ctx.floor + 0.02, z); m.scale.y = 0.6 + ctx.rnd() * 0.6;
        ctx.group.add(m);
      });
      const ring = new THREE.Mesh(new THREE.RingGeometry(ctx.lim + 6, ctx.lim + 9, 64), lava);
      ring.rotation.x = -Math.PI / 2; ring.position.y = ctx.floor + 0.02; ctx.group.add(ring);
      // obsidian spikes
      instanced(ctx, 110, ctx.lim + 10, 100, [
        { geo: new THREE.ConeGeometry(0.9, 4, 5), mat: Std(0x15101a, { roughness: 0.25, metalness: 0.4, flatShading: true }), place: (k, r) => [k * 2, k, k * (0.8 + r()), k, 0, 0, (r() - 0.5) * 0.5] },
      ], [0.5, 1.8]);
      rocks(ctx, 70, 0x3a3230);
      // volcanoes with glowing calderas on the horizon
      around(ctx, 5, ctx.lim + 50, 160, (x, z) => {
        const h = 25 + ctx.rnd() * 25, w = h * 0.9;
        const cone = new THREE.Mesh(new THREE.CylinderGeometry(w * 0.18, w, h, 12, 1, true), Std(0x2a201e, { flatShading: true }));
        cone.position.set(x, ctx.floor + h / 2, z); ctx.group.add(cone);
        const top = new THREE.Mesh(new THREE.CircleGeometry(w * 0.18, 12), Glow(0xff7a2a));
        top.rotation.x = -Math.PI / 2; top.position.set(x, ctx.floor + h - 0.3, z); ctx.group.add(top);
      });
      const glow = new THREE.PointLight(0xff5a1a, 60, 60, 1.5); glow.position.set(0, 6, 0); ctx.group.add(glow);
      ctx.tick((dt, t) => {
        lava.color.setHSL(0.025 + Math.sin(t * 1.7) * 0.01, 1, 0.42 + Math.sin(t * 2.3) * 0.04);
        glow.intensity = 55 + Math.sin(t * 3.1) * 12;
      });
      weather(ctx, { count: 700, color: 0xff8a2a, size: 0.22, vel: [0.4, 2.2, 0.2], sway: 0.6, additive: true, spanY: 25 });
      clouds(ctx, { color: 0x2a2224, opacity: 0.85, count: 16, height: 38 });
    },
  },
  {
    id: 'moon', name: 'Lunar Base', blurb: 'Grey regolith, glowing crystals, a blue planet overhead, and low gravity.',
    swatch: 'radial-gradient(circle at 70% 25%, #5aa0ff 0 10%, transparent 11%), linear-gradient(#05060f 0 45%, #7d818d 45%)',
    sky: 0x05060f, fog: [90, 260], hemi: [0xbfc8ff, 0x2a2c33, 0.8], sun: [0xffffff, 2.8],
    ground: 0x6f7380, dirt: 0x4a4d57, seam: 0x4f525c,
    cover: [0x9aa0ad, 0x8c929f], slab: [0xd8dbe3, 0xcdd1da], gravity: 0.42,
    decor(ctx) {
      // craters: raised rims
      around(ctx, 34, ctx.lim + 2, 90, (x, z) => {
        const r = 2 + ctx.rnd() * 6;
        const rim = new THREE.Mesh(new THREE.TorusGeometry(r, r * 0.18, 6, 24), Std(0x7d818d, { flatShading: true }));
        rim.rotation.x = -Math.PI / 2; rim.scale.z = 0.5; rim.position.set(x, ctx.floor + 0.05, z);
        rim.receiveShadow = true; ctx.group.add(rim);
        const pit = new THREE.Mesh(new THREE.CircleGeometry(r, 24), Std(0x5a5e69));
        pit.rotation.x = -Math.PI / 2; pit.position.set(x, ctx.floor + 0.01, z); ctx.group.add(pit);
      });
      rocks(ctx, 80, 0x8a8e99, { maxR: 100 });
      // glowing crystals
      for (const [col, n] of [[0x58f5ff, 30], [0xc77dff, 22]]) {
        instanced(ctx, n, ctx.lim - 1, 70, [
          { geo: new THREE.OctahedronGeometry(0.6, 0), mat: Glow(col), place: (k) => [k * 1.3, k * 0.5, k * 2, k * 0.5], shadow: false },
          { geo: new THREE.OctahedronGeometry(0.45, 0), mat: Glow(col), place: (k) => [k * 0.8, k * 0.4, k * 1.4, k * 0.4, k * 0.5, 0.2, 0.5], shadow: false },
        ], [0.6, 1.4]);
      }
      // a habitat dome and antenna
      const dome = new THREE.Mesh(new THREE.SphereGeometry(7, 24, 12, 0, Math.PI * 2, 0, Math.PI / 2),
        new THREE.MeshStandardMaterial({ color: 0xbfe6ff, roughness: 0.1, metalness: 0.2, transparent: true, opacity: 0.45 }));
      dome.position.set(-(ctx.lim + 18), ctx.floor, ctx.lim + 12); ctx.group.add(dome);
      const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.15, 0.2, 12, 6), Std(0xdddddd, { metalness: 0.6 }));
      mast.position.set(ctx.lim + 14, ctx.floor + 6, -(ctx.lim + 10)); ctx.group.add(mast);
      const beacon = new THREE.Mesh(new THREE.SphereGeometry(0.4, 10, 8), Glow(0xff3030));
      beacon.position.set(ctx.lim + 14, ctx.floor + 12.3, -(ctx.lim + 10)); ctx.group.add(beacon);
      // the planet in the sky, and stars
      const planet = new THREE.Mesh(new THREE.SphereGeometry(40, 32, 20),
        new THREE.MeshStandardMaterial({ color: 0x3d7dff, emissive: 0x0d2a66, roughness: 0.7 }));
      planet.material.fog = false; planet.position.set(-160, 120, -220); ctx.group.add(planet);
      const S = new Float32Array(1500 * 3);
      for (let i = 0; i < 1500; i++) {
        const u = Math.random() * 2 - 1, a = Math.random() * 6.28, r = 300, c = Math.sqrt(1 - u * u);
        S.set([Math.cos(a) * c * r, Math.abs(u) * r + 10, Math.sin(a) * c * r], i * 3);
      }
      const sg = new THREE.BufferGeometry(); sg.setAttribute('position', new THREE.BufferAttribute(S, 3));
      const stars = new THREE.Points(sg, new THREE.PointsMaterial({ color: 0xffffff, size: 1.4, sizeAttenuation: false, fog: false }));
      stars.frustumCulled = false; ctx.group.add(stars);
      ctx.tick((dt, t, me) => { stars.position.set(me.x, 0, me.z); beacon.visible = Math.sin(t * 4) > 0; planet.rotation.y += dt * 0.02; });
    },
  },
  {
    id: 'candy', name: 'Candyfloss Hills', blurb: 'Frosting fields, lollipops, candy canes, giant cupcakes and falling sprinkles.',
    swatch: 'linear-gradient(#ffd1ec 0 45%, #a8f0d0 45% 72%, #ff8cc3 72%)',
    sky: 0xffd1ec, fog: [70, 190], hemi: [0xfff0fa, 0xc58fb0, 1.2], sun: [0xfff4e8, 2.2],
    ground: 0xa8f0d0, dirt: 0x8a5232, seam: 0x6b3a1e,
    cover: [0xff9fcf, 0xff8cc3], slab: [0xfff6e6, 0xfbeacf], gravity: 1,
    decor(ctx) {
      const glossy = (c) => Std(c, { roughness: 0.3 });
      // lollipops: stick, candy disc and a white swirl on both faces
      for (const c of [0xff4f9a, 0x6fd0ff, 0xffd23f, 0x9b6bff, 0x5be08a]) {
        instanced(ctx, 14, ctx.lim + 1, 100, [
          { geo: new THREE.CylinderGeometry(0.12, 0.12, 4, 6), mat: Std(0xffffff), place: (k) => [k * 2, k, k, k] },
          { geo: new THREE.CylinderGeometry(1.3, 1.3, 0.35, 24).rotateX(Math.PI / 2), mat: glossy(c), place: (k) => [k * 4.9, k, k, k] },
          { geo: new THREE.TorusGeometry(0.85, 0.1, 6, 24), mat: glossy(0xffffff), place: (k) => [k * 4.9, k, k, k, 0, 0.19 * k] },
          { geo: new THREE.TorusGeometry(0.42, 0.09, 6, 20), mat: glossy(0xffffff), place: (k) => [k * 4.9, k, k, k, 0, -0.19 * k] },
        ]);
      }
      // candy canes: stacked red/white stripes with a hook
      const stripes = [];
      for (let s = 0; s < 6; s++) {
        stripes.push({ geo: new THREE.CylinderGeometry(0.2, 0.2, 0.6, 10), mat: glossy(s % 2 ? 0xffffff : 0xe8243c),
          place: (k) => [k * (0.3 + s * 0.6), k, k, k] });
      }
      stripes.push({ geo: new THREE.TorusGeometry(0.5, 0.2, 8, 14, Math.PI), mat: glossy(0xe8243c), place: (k) => [k * 3.6, k, k, k, -0.5 * k, 0] });
      instanced(ctx, 60, ctx.lim + 1, 90, stripes, [0.8, 1.6]);
      // gumdrops in every flavour
      for (const c of [0xff5d7a, 0xffb340, 0x7ee05a, 0x5ab8ff, 0xc77dff, 0xfff07a]) {
        instanced(ctx, 14, ctx.lim - 3, 60, [
          { geo: new THREE.SphereGeometry(0.6, 14, 8, 0, Math.PI * 2, 0, Math.PI / 2), mat: Std(c, { roughness: 1 }), place: (k) => [0, k, k * 1.3, k] },
        ], [0.6, 1.4]);
      }
      // giant cupcakes on the horizon
      const wrapper = [Std(0xff8cc3, { flatShading: true }), Std(0x9b6bff, { flatShading: true }), Std(0x6fd0ff, { flatShading: true })];
      const icing = [Std(0xfff6e6), Std(0xffc0e0), Std(0x8a5232)];
      around(ctx, 12, ctx.lim + 22, 150, (x, z, i) => {
        const g = new THREE.Group(), s = 6 + ctx.rnd() * 8;
        const cup = new THREE.Mesh(new THREE.CylinderGeometry(s, s * 0.78, s * 0.9, 16), wrapper[i % 3]);
        cup.position.y = s * 0.45;
        const top = new THREE.Mesh(new THREE.SphereGeometry(s * 1.08, 20, 12), icing[i % 3]);
        top.scale.y = 0.6; top.position.y = s * 0.95;
        const cherry = new THREE.Mesh(new THREE.SphereGeometry(s * 0.2, 12, 10), glossy(0xe8243c));
        cherry.position.y = s * 1.75;
        for (const m of [cup, top, cherry]) { m.castShadow = true; g.add(m); }
        g.position.set(x, ctx.floor, z); ctx.group.add(g);
      });
      // a chocolate river around the field, plus puddles
      const choc = Std(0x6b3a1e, { roughness: 0.25, metalness: 0.1 });
      const river = new THREE.Mesh(new THREE.RingGeometry(ctx.lim + 6, ctx.lim + 9, 64), choc);
      river.rotation.x = -Math.PI / 2; river.position.y = ctx.floor + 0.02; ctx.group.add(river);
      around(ctx, 14, ctx.lim + 12, 80, (x, z) => {
        const m = new THREE.Mesh(new THREE.CircleGeometry(1.5 + ctx.rnd() * 3, 18), choc);
        m.rotation.x = -Math.PI / 2; m.position.set(x, ctx.floor + 0.02, z); ctx.group.add(m);
      });
      clouds(ctx, { color: 0xffb3dd, count: 9 });
      clouds(ctx, { color: 0xb3e5ff, count: 7 });
      weather(ctx, { count: 900, colors: [0xff4f9a, 0x6fd0ff, 0xffd23f, 0x5be08a, 0xffffff, 0x9b6bff], size: 0.22,
        vel: [0.3, -1.6, 0.2], sway: 0.6 });
    },
  },
  {
    id: 'jungle', name: 'Lost Jungle', blurb: 'Steamy rainforest, mossy ruins, a forgotten pyramid and fireflies.',
    swatch: 'linear-gradient(#b8dcb0 0 45%, #3d7a2c 45% 72%, #9a957a 72%)',
    sky: 0xb8dcb0, fog: [35, 140], hemi: [0xe8ffe0, 0x3a4a20, 1.1], sun: [0xfff0c8, 2.0],
    ground: 0x3d7a2c, dirt: 0x5a3f28, seam: 0x2c5a20,
    cover: [0x5f9a3e, 0x558f36], slab: [0xd9c08e, 0xcbb282], gravity: 1,
    decor(ctx) {
      const leaf = Std(0x2e6b2a, { flatShading: true }), leaf2 = Std(0x3f8a32, { flatShading: true });
      instanced(ctx, 160, ctx.lim, 110, [
        { geo: new THREE.CylinderGeometry(0.3, 0.45, 7, 7), mat: Std(0x5b4330), place: (k) => [k * 3.5, k, k, k] },
        { geo: new THREE.SphereGeometry(2.6, 10, 7), mat: leaf, place: (k) => [k * 7.2, k * 1.2, k * 0.5, k * 1.2] },
        { geo: new THREE.SphereGeometry(2.2, 10, 7), mat: leaf2, place: (k) => [k * 6.2, k, k * 0.45, k, k * 1.6, 0.4] },
        { geo: new THREE.SphereGeometry(2.0, 10, 7), mat: leaf2, place: (k) => [k * 6.5, k, k * 0.45, k, -k * 1.4, -0.6] },
      ], [0.7, 1.4]);
      // ferns
      instanced(ctx, 240, ctx.lim - 4, 70, [
        { geo: new THREE.ConeGeometry(0.8, 1.3, 5), mat: Std(0x4a9a3a, { flatShading: true }), place: (k, r) => [k * 0.55, k, k * 0.8, k, 0, 0, (r() - 0.5) * 0.7], shadow: false },
      ], [0.6, 1.4]);
      // crumbling stone ruins: pillars (some broken, some fallen) and loose blocks
      const stone = Std(0x8a8f7a, { flatShading: true }), moss = Std(0x5f7a3a, { flatShading: true });
      around(ctx, 26, ctx.lim + 2, 60, (x, z) => {
        const h = 2 + ctx.rnd() * 5, fallen = ctx.rnd() < 0.3;
        const p = new THREE.Mesh(new THREE.CylinderGeometry(0.8, 0.9, h, 8), stone);
        const cap = new THREE.Mesh(new THREE.BoxGeometry(2, 0.5, 2), moss);
        if (fallen) {
          p.rotation.z = Math.PI / 2; p.position.set(x, ctx.floor + 0.8, z); p.rotation.y = ctx.rnd() * 6;
          cap.position.set(x + 1.5, ctx.floor + 0.25, z + 1); cap.rotation.y = ctx.rnd();
        } else {
          p.position.set(x, ctx.floor + h / 2, z); cap.position.set(x, ctx.floor + h + 0.25, z);
        }
        p.castShadow = cap.castShadow = true;
        ctx.group.add(p, cap);
      });
      // a step pyramid rising out of the canopy
      const px = ctx.lim + 55, pz = -(ctx.lim + 45);
      for (let l = 0; l < 6; l++) {
        const s = 34 - l * 5.5, m = new THREE.Mesh(new THREE.BoxGeometry(s, 4, s), l % 2 ? stone : Std(0x9a957a, { flatShading: true }));
        m.position.set(px, ctx.floor + 2 + l * 4, pz); m.castShadow = true; ctx.group.add(m);
      }
      const shrine = new THREE.Mesh(new THREE.BoxGeometry(5, 4, 5), Std(0x6b6650, { flatShading: true }));
      shrine.position.set(px, ctx.floor + 26, pz); ctx.group.add(shrine);
      rocks(ctx, 40, 0x7a7f6a);
      weather(ctx, { count: 420, color: 0xd8ff6a, size: 0.26, opacity: 0.85, vel: [0, 0.2, 0], sway: 1.2, additive: true, spanY: 6 });
      clouds(ctx, { color: 0xeef7ea, opacity: 0.7, count: 10, height: 40 });
    },
  },
  {
    id: 'reef', name: 'Coral Reef', blurb: 'Under the sea: swaying kelp, corals, schools of fish and floaty gravity.',
    swatch: 'linear-gradient(#0f5c7a 0 45%, #4fc1bd 45% 72%, #d9c99a 72%)',
    sky: 0x0f5c7a, fog: [35, 130], hemi: [0x9fe8ff, 0x1a3a40, 1.2], sun: [0xbff4ff, 1.8],
    ground: 0xd9c99a, dirt: 0xb09a6a, seam: 0x8f7b52,
    cover: [0x4fc1bd, 0x45b3b0], slab: [0xf3ead0, 0xe8dcbb], gravity: 0.55,
    decor(ctx) {
      // branching corals
      for (const c of [0xff7a5c, 0xff5fa8, 0xb07cff, 0xffc94a]) {
        const m = Std(c, { roughness: 0.7 });
        instanced(ctx, 22, ctx.lim, 85, [
          { geo: new THREE.CylinderGeometry(0.18, 0.3, 2, 6), mat: m, place: (k) => [k, k, k, k] },
          { geo: new THREE.CylinderGeometry(0.12, 0.2, 1.5, 6), mat: m, place: (k) => [k * 2, k, k, k, k * 0.45, 0, -0.6] },
          { geo: new THREE.CylinderGeometry(0.12, 0.2, 1.4, 6), mat: m, place: (k) => [k * 1.8, k, k, k, -k * 0.4, 0, 0.6] },
          { geo: new THREE.SphereGeometry(0.2, 6, 5), mat: m, place: (k) => [k * 2.1, k, k, k] },
        ], [0.7, 1.8]);
      }
      // brain corals, starfish, rocks
      instanced(ctx, 30, ctx.lim - 2, 70, [
        { geo: new THREE.SphereGeometry(1, 12, 8, 0, Math.PI * 2, 0, Math.PI / 2), mat: Std(0xe88aa0, { flatShading: true }), place: (k) => [0, k, k * 0.7, k] },
      ], [0.6, 1.6]);
      instanced(ctx, 30, ctx.lim - 3, 45, [
        { geo: new THREE.CylinderGeometry(0.5, 0.5, 0.1, 5), mat: Std(0xff8a3a), place: () => [0.05, 1, 1, 1], shadow: false },
      ], [0.6, 1.2]);
      rocks(ctx, 50, 0x7d8a8f);
      // kelp forests that sway with the current
      const kelpMat = Std(0x5a8a3a, { side: THREE.DoubleSide });
      const kelp = [];
      around(ctx, 26, ctx.lim + 1, 70, (x, z) => {
        for (let j = 0; j < 4; j++) {
          const h = 6 + ctx.rnd() * 10;
          const m = new THREE.Mesh(new THREE.BoxGeometry(0.35, h, 0.06).translate(0, h / 2, 0), kelpMat);
          m.position.set(x + (ctx.rnd() - 0.5) * 3, ctx.floor, z + (ctx.rnd() - 0.5) * 3);
          m.rotation.y = ctx.rnd() * 6; m.userData.phase = ctx.rnd() * 6;
          ctx.group.add(m); kelp.push(m);
        }
      });
      // schools of fish circling the reef
      const schools = [];
      for (const [c, R, y, speed] of [[0xffb020, 26, 4, 0.25], [0xff5f5f, 40, 7, -0.18], [0x5fd0ff, 55, 5, 0.14], [0xfff07a, 34, 10, -0.22], [0xb07cff, 70, 8, 0.1]]) {
        const school = new THREE.Group(), mat = Std(c, { roughness: 0.4 });
        const body = new THREE.SphereGeometry(0.35, 8, 6).scale(0.4, 0.6, 1);
        const tail = new THREE.ConeGeometry(0.25, 0.4, 4).rotateX(-Math.PI / 2);
        for (let f = 0; f < 10; f++) {
          const a = f * 0.09 + ctx.rnd() * 0.05, rr = R + (ctx.rnd() - 0.5) * 3;
          const fish = new THREE.Group();
          const b = new THREE.Mesh(body, mat), tl = new THREE.Mesh(tail, mat); tl.position.z = 0.45;
          fish.add(b, tl);
          fish.position.set(Math.cos(a) * rr, y + (ctx.rnd() - 0.5) * 2, -Math.sin(a) * rr);
          fish.rotation.y = speed > 0 ? a : a + Math.PI;
          school.add(fish);
        }
        school.userData.speed = speed; schools.push(school); ctx.group.add(school);
      }
      // shafts of light from the surface
      const shaftMat = new THREE.MeshBasicMaterial({ color: 0xdffcff, transparent: true, opacity: 0.06, depthWrite: false,
        blending: THREE.AdditiveBlending, side: THREE.DoubleSide });
      const shafts = [];
      for (let i = 0; i < 10; i++) {
        const s = new THREE.Mesh(new THREE.ConeGeometry(5 + ctx.rnd() * 4, 70, 16, 1, true), shaftMat);
        s.position.set((ctx.rnd() - 0.5) * 120, 30, (ctx.rnd() - 0.5) * 120);
        s.rotation.z = 0.25; s.userData.phase = ctx.rnd() * 6; shafts.push(s); ctx.group.add(s);
      }
      ctx.tick((dt, t) => {
        for (const k of kelp) { k.rotation.z = Math.sin(t * 0.9 + k.userData.phase) * 0.18; k.rotation.x = Math.cos(t * 0.7 + k.userData.phase) * 0.08; }
        for (const s of schools) s.rotation.y += s.userData.speed * dt;
        shaftMat.opacity = 0.05 + Math.sin(t * 0.6) * 0.02;
      });
      weather(ctx, { count: 600, color: 0xe0ffff, size: 0.25, opacity: 0.6, vel: [0, 2.2, 0], sway: 0.5, spanY: 25 });
    },
  },
  {
    id: 'spooky', name: 'Haunted Hollow', blurb: 'A moonlit graveyard of dead trees, tombstones, jack-o\'-lanterns and wisps.',
    swatch: 'radial-gradient(circle at 75% 22%, #f4f0d8 0 9%, transparent 10%), linear-gradient(#1d1733 0 45%, #2c3326 45% 72%, #ff7a1a 72% 78%, #2c3326 78%)',
    sky: 0x1d1733, fog: [30, 120], hemi: [0x8f86c8, 0x1a1a22, 0.75], sun: [0xb8c8ff, 1.3],
    ground: 0x2c3326, dirt: 0x231c18, seam: 0x1e231a,
    cover: [0x55634a, 0x4b5842], slab: [0xbdb6a6, 0xb0a998], gravity: 1,
    decor(ctx) {
      const bark = Std(0x2a221e, { flatShading: true });
      instanced(ctx, 90, ctx.lim, 110, [
        { geo: new THREE.CylinderGeometry(0.25, 0.45, 5, 6), mat: bark, place: (k) => [k * 2.5, k, k, k] },
        { geo: new THREE.CylinderGeometry(0.08, 0.16, 2.6, 5), mat: bark, place: (k) => [k * 4.2, k, k, k, k * 0.55, 0, -0.9] },
        { geo: new THREE.CylinderGeometry(0.07, 0.14, 2.2, 5), mat: bark, place: (k) => [k * 3.4, k, k, k, -k * 0.5, 0, 0.95] },
        { geo: new THREE.CylinderGeometry(0.05, 0.1, 1.6, 5), mat: bark, place: (k) => [k * 5.3, k, k, k, -k * 0.25, 0, 0.5] },
      ], [0.7, 1.6]);
      // tombstones with rounded tops
      const stone = Std(0x7a7a80, { flatShading: true });
      instanced(ctx, 60, ctx.lim - 2, 45, [
        { geo: new THREE.BoxGeometry(1, 1.4, 0.25), mat: stone, place: (k, r) => [k * 0.7, k, k, k, 0, 0, (r() - 0.5) * 0.25] },
        { geo: new THREE.CylinderGeometry(0.5, 0.5, 0.25, 14).rotateX(Math.PI / 2), mat: stone, place: (k) => [k * 1.4, k, k, k] },
      ], [0.7, 1.3]);
      // glowing jack-o'-lanterns
      const pumpkin = Std(0xff7a1a, { emissive: 0x7a2a00, roughness: 0.6 });
      instanced(ctx, 45, ctx.lim - 3, 50, [
        { geo: new THREE.SphereGeometry(0.7, 12, 8), mat: pumpkin, place: (k) => [k * 0.5, k, k * 0.75, k] },
        { geo: new THREE.CylinderGeometry(0.06, 0.09, 0.35, 5), mat: Std(0x3a6a20), place: (k) => [k * 1.1, k, k, k] },
      ], [0.6, 1.4]);
      const glows = [];
      for (const [x, z] of [[1, 1], [-1, 1], [1, -1], [-1, -1]]) {
        const l = new THREE.PointLight(0xff8a2a, 40, 30, 1.6);
        l.position.set(x * (ctx.lim + 1), 2, z * (ctx.lim + 1)); ctx.group.add(l); glows.push(l);
      }
      const moon = new THREE.Mesh(new THREE.SphereGeometry(18, 24, 16), Glow(0xf4f0d8, { fog: false }));
      moon.position.set(120, 110, -200); ctx.group.add(moon);
      starfield(ctx, 700, 0xc8c8ff);
      ctx.tick((dt, t) => { glows.forEach((l, i) => { l.intensity = 34 + Math.sin(t * 7 + i * 2) * 6 + Math.sin(t * 13 + i) * 4; }); });
      weather(ctx, { count: 160, colors: [0x7dffd0, 0xa0c8ff], size: 0.35, vel: [0.3, 0.25, 0], sway: 1.5, additive: true, spanY: 6 });
      clouds(ctx, { color: 0x3a3350, opacity: 0.8, count: 10, height: 42 });
    },
  },
  {
    id: 'neon', name: 'Neon Grid', blurb: 'A synthwave night: glowing grid, a striped sunset, wireframe pyramids and floating cubes.',
    swatch: 'radial-gradient(circle at 50% 45%, #ff4fa0 0 18%, transparent 19%), linear-gradient(#0b0322 0 45%, #ff3ad0 45% 47%, #090414 47%)',
    sky: 0x0b0322, fog: [70, 230], hemi: [0xb18cff, 0x10051f, 0.9], sun: [0xff9ae6, 1.6],
    ground: 0x090414, dirt: 0x150a2a, seam: 0x1a0b33,
    cover: [0x3a1f6e, 0x321a62], slab: [0xece6ff, 0xdcd3fb], gravity: 1,
    decor(ctx) {
      // glowing floor grid: a tiled canvas texture (thin GL lines vanish on many GPUs)
      const cv = document.createElement('canvas'); cv.width = cv.height = 128;
      const g2 = cv.getContext('2d');
      g2.strokeStyle = '#ff3ad0'; g2.lineWidth = 6; g2.shadowColor = '#ff3ad0'; g2.shadowBlur = 10;
      g2.strokeRect(0, 0, 128, 128);
      const tex = new THREE.CanvasTexture(cv);
      tex.wrapS = tex.wrapT = THREE.RepeatWrapping; tex.repeat.set(150, 150); tex.anisotropy = 8;
      tex.colorSpace = THREE.SRGBColorSpace;
      const grid = new THREE.Mesh(new THREE.PlaneGeometry(600, 600), new THREE.MeshBasicMaterial({
        map: tex, transparent: true, opacity: 0.8, depthWrite: false, blending: THREE.AdditiveBlending }));
      grid.rotation.x = -Math.PI / 2; grid.position.y = ctx.floor + 0.02;
      ctx.group.add(grid);
      const edge = (geo, color) => new THREE.LineSegments(new THREE.EdgesGeometry(geo), new THREE.LineBasicMaterial({ color }));
      const dark = Std(0x120826, { roughness: 0.4 });
      // the striped synthwave sun
      const sunGroup = new THREE.Group();
      const disc = new THREE.Mesh(new THREE.CircleGeometry(55, 48), Glow(0xff4fa0, { fog: false }));
      sunGroup.add(disc);
      for (let s = 0; s < 7; s++) {
        const bar = new THREE.Mesh(new THREE.PlaneGeometry(120, 1.5 + s * 0.9), Glow(0x0b0322, { fog: false }));
        bar.position.set(0, -6 - s * 7, 0.1); sunGroup.add(bar);
      }
      sunGroup.position.set(0, 30, -280); ctx.group.add(sunGroup);
      starfield(ctx, 900, 0xffffff);
      // wireframe pyramids on the horizon
      around(ctx, 9, ctx.lim + 30, 170, (x, z, i) => {
        const h = 14 + ctx.rnd() * 22, geo = new THREE.ConeGeometry(h * 0.8, h, 4);
        const solid = new THREE.Mesh(geo, dark), lines = edge(geo, i % 2 ? 0x3ef0ff : 0xff3ad0);
        for (const m of [solid, lines]) { m.position.set(x, ctx.floor + h / 2, z); m.rotation.y = ctx.rnd(); ctx.group.add(m); }
      });
      // neon pillars around the field
      around(ctx, 40, ctx.lim + 2, 70, (x, z, i) => {
        const h = 2 + ctx.rnd() * 7, geo = new THREE.BoxGeometry(0.7, h, 0.7);
        const solid = new THREE.Mesh(geo, dark), lines = edge(geo, [0xff3ad0, 0x3ef0ff, 0xffd23f][i % 3]);
        for (const m of [solid, lines]) { m.position.set(x, ctx.floor + h / 2, z); ctx.group.add(m); }
      });
      // floating, spinning cubes
      const cubes = [];
      around(ctx, 30, ctx.lim + 4, 80, (x, z, i) => {
        const s = 0.8 + ctx.rnd() * 1.8, c = edge(new THREE.BoxGeometry(s, s, s), [0x3ef0ff, 0xff3ad0, 0xa3e635][i % 3]);
        c.position.set(x, 4 + ctx.rnd() * 10, z); c.userData = { spin: 0.3 + ctx.rnd(), bob: ctx.rnd() * 6, y: c.position.y };
        cubes.push(c); ctx.group.add(c);
      });
      ctx.tick((dt, t) => {
        for (const c of cubes) { c.rotation.x += c.userData.spin * dt; c.rotation.y += c.userData.spin * 0.7 * dt; c.position.y = c.userData.y + Math.sin(t + c.userData.bob) * 0.6; }
        grid.material.opacity = 0.7 + Math.sin(t * 2) * 0.15;
      });
      weather(ctx, { count: 500, colors: [0xff3ad0, 0x3ef0ff], size: 0.18, vel: [0, 0.8, 0], sway: 0.4, additive: true, spanY: 20 });
    },
  },
];

function starfield(ctx, n, color) {
  const S = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    const u = Math.random() * 2 - 1, a = Math.random() * 6.28, r = 300, c = Math.sqrt(1 - u * u);
    S.set([Math.cos(a) * c * r, Math.abs(u) * r + 10, Math.sin(a) * c * r], i * 3);
  }
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(S, 3));
  const stars = new THREE.Points(g, new THREE.PointsMaterial({ color, size: 1.3, sizeAttenuation: false, fog: false }));
  stars.frustumCulled = false; ctx.group.add(stars);
  ctx.tick((dt, t, me) => stars.position.set(me.x, 0, me.z));
}

// dungeon walls per realm: [side colour, top colour]. Picked to contrast with the realm's
// cover colour, so walls never read as diggable tiles from the overhead camera.
const WALLS = {
  meadow: [0x7a7a6c, 0x9a9a8a],     // grey fieldstone
  desert: [0x7a4a2a, 0x8f5a34],     // dark mud brick
  tundra: [0x6f98b8, 0x8fb4d2],     // blue glacier ice
  volcano: [0x2a2220, 0x5a2a1a],    // basalt with a glowing crust
  moon: [0x4a4e5a, 0x5c606c],       // dark regolith blocks
  candy: [0x6b3a1e, 0x8a5232],      // chocolate wafer
  jungle: [0x7d8270, 0x8f9480],     // ruined temple stone
  reef: [0x4a6f78, 0xe88aa0],       // dark rock crusted with coral
  spooky: [0x3a3644, 0x4a4656],     // purple crypt stone
  neon: [0x150a2a, 0xff3ad0],       // dark panels with glowing tops
};
for (const r of REALMS) r.wall = WALLS[r.id] || [0x777777, 0x999999];

export const REALM_BY_ID = Object.fromEntries(REALMS.map((r) => [r.id, r]));
