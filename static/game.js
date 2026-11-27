import * as THREE from 'three';
import { CHARACTERS, CHAR_BY_ID, buildCharacter } from './characters.js';
import { REALMS, REALM_BY_ID } from './realms.js';
import { BOSSES } from './bosses.js';

const $ = (id) => document.getElementById(id);
// ---------------------------------------------------------------- state
let W = 32, H = 32, T = 2, REACH = 3;
let ws = null, myId = null, worldBuilt = false;
let tiles = new Int8Array(0);            // -2 hidden, -1 exploded mine, 0..8 revealed count
const flags = new Map();                 // tile idx -> { pid, mesh }
const craters = new Map();               // tile idx -> group
const players = new Map();               // id -> { name, color, score, stun, av, tx, tz, tr, x, z, r, y, phase }
let roundState = 'playing', overEndsAt = 0;
let throwRange = 6, scatterRadius = 2, bootsSpeed = 1.6, maxHp = 100;
const items = new Map();                 // tile idx -> { kind, mesh }
const bombs = new Map();                 // bomb id -> { mesh, zone }
let radar = null;                        // { group, until }
let bootsUntil = 0, goldUntil = 0;       // local display of effect timers
let koUntil = 0;                         // local respawn countdown while knocked out
const bosses = new Map();                // boss id -> { kind, m (model), group, x, z, tx, tz, r, tr, hp, max, state, ... }
let gameMode = 'race', teamLives = null; // race | pvp | coop; co-op's shared lives

function renderModeRow() {
  const chip = $('modeChip');
  chip.textContent = { race: 'RACE', pvp: 'PVP', coop: 'CO-OP' }[gameMode] || 'RACE';
  chip.className = `chip ${gameMode}`;
  if (gameMode === 'coop') {
    const team = [...players.values()].reduce((s, p) => s + p.score, 0);
    const n = Math.max(0, teamLives ?? 0);
    $('teamInfo').replaceChildren(
      Object.assign(document.createElement('span'), { className: 'hearts', textContent: n <= 6 ? '♥'.repeat(n) || '♡' : `♥×${n}` }),
      ` team ${team}`);
  } else if (gameMode === 'pvp') $('teamInfo').textContent = 'swords hit players · KOs +20';
  else $('teamInfo').textContent = '';
}

const me = { x: 0, z: 0, y: 0.6, vy: 0, r: 0, kx: 0, kz: 0, stun: 0, phase: 0, fx: 0, hp: 100 };
const cam = { yaw: 0.6, pitch: 0.95, dist: 18, shake: 0 };
const keys = new Set();
const mouse = { x: 0, y: 0, has: false, drag: false, lastX: 0 };
let hover = null;                        // { x, y, inReach }

const tileCenter = (x, y) => [(x - W / 2 + 0.5) * T, (y - H / 2 + 0.5) * T];
const tileOf = (wx, wz) => [Math.floor(wx / T + W / 2), Math.floor(wz / T + H / 2)];
const inBoard = (x, y) => x >= 0 && y >= 0 && x < W && y < H;
const send = (m) => ws && ws.readyState === 1 && ws.send(JSON.stringify(m));

// phones and tablets get touch controls and a lighter renderer; ?touch=1 forces it for testing
const IS_TOUCH = new URLSearchParams(location.search).has('touch') || matchMedia('(pointer: coarse)').matches;
if (IS_TOUCH) document.body.classList.add('touch');

// ---------------------------------------------------------------- renderer / scene
const renderer = new THREE.WebGLRenderer({ antialias: !IS_TOUCH, powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(devicePixelRatio, IS_TOUCH ? 1.5 : 2));
renderer.setSize(innerWidth, innerHeight);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
$('view').appendChild(renderer.domElement);

const scene = new THREE.Scene();
const SKY = 0x8cc4ee;
scene.background = new THREE.Color(SKY);
scene.fog = new THREE.Fog(SKY, 70, 190);
const camera = new THREE.PerspectiveCamera(55, innerWidth / innerHeight, 0.1, 600);
camera.position.set(20, 25, 20);

const hemi = new THREE.HemisphereLight(0xe4f3ff, 0x5b4a30, 1.1);
scene.add(hemi);
const sun = new THREE.DirectionalLight(0xfff3dd, 2.2);
sun.position.set(30, 60, 18);
sun.castShadow = true;
sun.shadow.mapSize.set(IS_TOUCH ? 1024 : 2048, IS_TOUCH ? 1024 : 2048);
Object.assign(sun.shadow.camera, { left: -45, right: 45, top: 45, bottom: -45, near: 1, far: 160 });
sun.shadow.bias = -0.0005;
scene.add(sun);

addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});

// ---------------------------------------------------------------- textures
const NUM_COLORS = ['', '#1e6bff', '#1f9d3a', '#e5322d', '#26308f', '#8b1a1a', '#138a8a', '#222222', '#777777'];
function numberTexture(n) {
  const c = document.createElement('canvas'); c.width = c.height = 128;
  const g = c.getContext('2d');
  g.font = '900 104px system-ui, Segoe UI, sans-serif';
  g.textAlign = 'center'; g.textBaseline = 'middle';
  g.lineWidth = 14; g.strokeStyle = 'rgba(255,255,255,.85)'; g.lineJoin = 'round';
  g.strokeText(String(n), 64, 70);
  g.fillStyle = NUM_COLORS[n]; g.fillText(String(n), 64, 70);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = renderer.capabilities.getMaxAnisotropy();
  return t;
}

function textSprite(text, { color = '#fff', bg = 'rgba(10,18,30,.6)', dot = null, scale = 1, font = 700 } = {}) {
  const c = document.createElement('canvas'); c.width = 512; c.height = 128;
  const g = c.getContext('2d');
  g.font = `${font} 64px system-ui, Segoe UI, sans-serif`;
  const tw = Math.min(g.measureText(text).width, 440);
  const pad = dot ? 70 : 34, w = tw + pad + 30, x0 = (512 - w) / 2;
  if (bg) {
    g.fillStyle = bg; g.beginPath(); g.roundRect(x0, 16, w, 96, 48); g.fill();
  }
  if (dot) { g.fillStyle = dot; g.beginPath(); g.arc(x0 + 46, 64, 16, 0, Math.PI * 2); g.fill(); }
  g.fillStyle = color; g.textBaseline = 'middle';
  if (!bg) { g.lineWidth = 12; g.strokeStyle = 'rgba(0,0,0,.55)'; g.strokeText(text, x0 + pad, 68, 440); }
  g.fillText(text, x0 + pad, 68, 440);
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false }));
  s.scale.set(4 * scale, 1 * scale, 1);
  return s;
}

// ---------------------------------------------------------------- world
let coverMesh, slabMesh, numMeshes = [], minesShown, highlight, reachZone, blastZone, blinkMark, aimLine, shockRing, digMark;
const ZERO = new THREE.Matrix4().makeScale(0, 0, 0);
const M = new THREE.Matrix4();

let realm = REALM_BY_ID.meadow, worldGroup = null, worldKey = '';
const worldTicks = [];
let baseMesh, wallMesh;
const WALL_H = 2.2, ROCK_H = 1.4;          // dungeon walls next to floor, and solid rock further in

// half the width of the area the layout uses, in world units (scenery is placed outside it)
function layoutExtent(layoutStr) {
  let m = 0;
  for (let i = 0; i < layoutStr.length; i++) {
    if (layoutStr[i] !== '1') continue;
    const [wx, wz] = tileCenter(i % W, Math.floor(i / W));
    m = Math.max(m, Math.abs(wx), Math.abs(wz));
  }
  return m + T / 2;
}

// (Re)build everything that belongs to the realm: ground, board meshes, scenery, weather, lighting.
function buildWorld(realmId, extent) {
  realm = REALM_BY_ID[realmId] || REALMS[0];
  if (worldGroup) { scene.remove(worldGroup); disposeTree(worldGroup); }
  worldTicks.length = 0;
  worldGroup = new THREE.Group();
  scene.add(worldGroup);
  const add = (...o) => worldGroup.add(...o);
  worldBuilt = true;
  const bw = extent * 2, bh = extent * 2;

  scene.background = new THREE.Color(realm.sky);
  scene.fog = new THREE.Fog(realm.sky, realm.fog[0], realm.fog[1]);
  hemi.color.set(realm.hemi[0]); hemi.groundColor.set(realm.hemi[1]); hemi.intensity = realm.hemi[2];
  sun.color.set(realm.sun[0]); sun.intensity = realm.sun[1];
  $('realmName').textContent = realm.name;

  const grass = new THREE.Mesh(new THREE.PlaneGeometry(600, 600),
    new THREE.MeshStandardMaterial({ color: realm.ground, roughness: 1 }));
  grass.rotation.x = -Math.PI / 2; grass.position.y = -0.5; grass.receiveShadow = true;
  add(grass);

  // one base block per floor tile (its top shows through the gaps between tiles) and dungeon walls;
  // both are positioned by setLayout() because every round can bring a new layout
  const dirt = new THREE.MeshStandardMaterial({ color: realm.dirt, roughness: 1 });
  const seam = new THREE.MeshStandardMaterial({ color: realm.seam, roughness: 1 });
  baseMesh = new THREE.InstancedMesh(new THREE.BoxGeometry(T, 1, T), [dirt, dirt, seam, dirt, dirt, dirt], W * H);
  baseMesh.receiveShadow = true; baseMesh.frustumCulled = false; baseMesh.count = 0;
  const wallSide = new THREE.MeshStandardMaterial({ color: realm.wall[0], roughness: 0.9, flatShading: true });
  const wallTop = new THREE.MeshStandardMaterial({ color: realm.wall[1], roughness: 0.9,
    emissive: realm.id === 'neon' || realm.id === 'volcano' ? realm.wall[1] : 0x000000, emissiveIntensity: 0.35 });
  wallMesh = new THREE.InstancedMesh(new THREE.BoxGeometry(T, 1, T), [wallSide, wallSide, wallTop, wallSide, wallSide, wallSide], W * H);
  wallMesh.castShadow = wallMesh.receiveShadow = true; wallMesh.frustumCulled = false; wallMesh.count = 0;
  add(baseMesh, wallMesh);

  // revealed ground slabs
  slabMesh = new THREE.InstancedMesh(new THREE.BoxGeometry(T * 0.97, 0.2, T * 0.97),
    new THREE.MeshStandardMaterial({ roughness: 0.95 }), W * H);
  // Instance matrices change every reveal; Three caches the bounding sphere on first render,
  // which would cull these meshes once that stale sphere leaves the view.
  slabMesh.receiveShadow = true; slabMesh.frustumCulled = false;
  // unrevealed grassy covers
  const coverGeo = new THREE.BoxGeometry(T * 0.94, 0.6, T * 0.94);
  coverMesh = new THREE.InstancedMesh(coverGeo, new THREE.MeshStandardMaterial({ roughness: 0.8 }), W * H);
  coverMesh.castShadow = coverMesh.receiveShadow = true; coverMesh.frustumCulled = false;
  const ca = new THREE.Color(realm.cover[0]), cb = new THREE.Color(realm.cover[1]);
  const sa = new THREE.Color(realm.slab[0]), sb = new THREE.Color(realm.slab[1]);
  for (let i = 0; i < W * H; i++) {
    const odd = ((i % W) + Math.floor(i / W)) % 2;
    coverMesh.setColorAt(i, odd ? ca : cb);
    slabMesh.setColorAt(i, odd ? sa : sb);
  }
  add(slabMesh, coverMesh);

  const numGeo = new THREE.PlaneGeometry(T * 0.78, T * 0.78); numGeo.rotateX(-Math.PI / 2);
  for (let n = 1; n <= 8; n++) {
    const m = new THREE.InstancedMesh(numGeo, new THREE.MeshBasicMaterial({
      map: numberTexture(n), transparent: true, depthWrite: false }), W * H);
    m.count = 0; m.renderOrder = 1; m.frustumCulled = false;
    numMeshes[n] = m; add(m);
  }

  minesShown = new THREE.InstancedMesh(new THREE.SphereGeometry(0.4, 16, 12),
    new THREE.MeshStandardMaterial({ color: 0x1b1b22, metalness: 0.6, roughness: 0.35, emissive: 0x550000 }), W * H);
  minesShown.count = 0; minesShown.castShadow = true; minesShown.frustumCulled = false;
  add(minesShown);

  const hs = new THREE.Shape();
  const o = T * 0.5, inr = T * 0.4;
  hs.moveTo(-o, -o); hs.lineTo(o, -o); hs.lineTo(o, o); hs.lineTo(-o, o); hs.lineTo(-o, -o);
  const hole = new THREE.Path();
  hole.moveTo(-inr, -inr); hole.lineTo(-inr, inr); hole.lineTo(inr, inr); hole.lineTo(inr, -inr); hole.lineTo(-inr, -inr);
  hs.holes.push(hole);
  const hg = new THREE.ShapeGeometry(hs); hg.rotateX(-Math.PI / 2);
  highlight = new THREE.Mesh(hg, new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.9, depthWrite: false }));
  highlight.renderOrder = 2; highlight.visible = false;
  add(highlight);

  // the square of tiles the local player can currently reach, and the scatter-bomb aim square
  reachZone = squareOutline(REACH, 0xfff3a0, 0.8);
  blastZone = squareOutline(scatterRadius, 0xc77dff, 0.9);
  blinkMark = squareOutline(0, 0xa3e635, 0.9);
  digMark = squareOutline(0, 0xffd23f, 1);      // touch: the tile the Dig button will dig
  add(digMark);
  const lineMat = new THREE.MeshBasicMaterial({ color: 0x3ee6d6, transparent: true, opacity: 0.6, depthWrite: false });
  aimLine = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.04, 1), lineMat); aimLine.renderOrder = 2; aimLine.visible = false;
  shockRing = new THREE.Mesh(new THREE.RingGeometry(shockRadius * T - 0.12, shockRadius * T, 48),
    new THREE.MeshBasicMaterial({ color: 0xff6fb5, transparent: true, opacity: 0.6, depthWrite: false, side: THREE.DoubleSide }));
  shockRing.rotation.x = -Math.PI / 2; shockRing.renderOrder = 2; shockRing.visible = false;
  add(reachZone, blastZone, blinkMark, aimLine, shockRing);

  let seed = 7;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  realm.decor({ group: worldGroup, rnd, floor: -0.5, lim: Math.max(bw, bh) / 2 + 7, tick: (fn) => worldTicks.push(fn),
    quality: IS_TOUCH ? 0.5 : 1 });
}

function squareOutline(radius, color, opacity) {
  const span = (radius * 2 + 1) * T, ro = span / 2, ri = ro - 0.12;
  const zs = new THREE.Shape();
  zs.moveTo(-ro, -ro); zs.lineTo(ro, -ro); zs.lineTo(ro, ro); zs.lineTo(-ro, ro); zs.lineTo(-ro, -ro);
  const zh = new THREE.Path();
  zh.moveTo(-ri, -ri); zh.lineTo(-ri, ri); zh.lineTo(ri, ri); zh.lineTo(ri, -ri); zh.lineTo(-ri, -ri);
  zs.holes.push(zh);
  const zg = new THREE.ShapeGeometry(zs); zg.rotateX(-Math.PI / 2);
  const m = new THREE.Mesh(zg, new THREE.MeshBasicMaterial({ color, transparent: true, opacity, depthWrite: false }));
  m.renderOrder = 2; m.visible = false;
  return m;
}

// tile values: -3 wall / not part of the layout, -2 hidden, -1 exploded, 0..8 revealed count
let floor = new Uint8Array(0), layoutKind = 'field';
const isWall = (x, y) => !inBoard(x, y) || !floor[y * W + x];

function setLayout(layoutStr, kind) {
  layoutKind = kind || 'field';
  floor = new Uint8Array(W * H);
  for (let i = 0; i < W * H; i++) floor[i] = layoutStr ? +(layoutStr[i] === '1') : 1;
  let nb = 0, nw = 0, seed = 11;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  const c = new THREE.Color(), q = new THREE.Quaternion(), s = new THREE.Vector3(), p = new THREE.Vector3();
  for (let i = 0; i < W * H; i++) {
    const x = i % W, y = Math.floor(i / W), [wx, wz] = tileCenter(x, y);
    if (floor[i]) { baseMesh.setMatrixAt(nb++, M.makeTranslation(wx, -0.5, wz)); continue; }
    if (layoutKind !== 'dungeon') continue;
    // walls bordering the floor stand tall; the rock behind them is lower so the map stays readable
    let edge = false;
    for (let dy = -1; dy <= 1 && !edge; dy++) for (let dx = -1; dx <= 1; dx++) if (!isWall(x + dx, y + dy)) { edge = true; break; }
    const h = edge ? WALL_H + rnd() * 0.3 : ROCK_H;
    wallMesh.setMatrixAt(nw, M.compose(p.set(wx, -0.5 + h / 2, wz), q, s.set(1, h, 1)));
    wallMesh.setColorAt(nw++, c.setScalar(edge ? 0.88 + rnd() * 0.12 : 0.62 + rnd() * 0.1));
  }
  baseMesh.count = nb; wallMesh.count = nw;
  baseMesh.instanceMatrix.needsUpdate = wallMesh.instanceMatrix.needsUpdate = true;
  if (wallMesh.instanceColor) wallMesh.instanceColor.needsUpdate = true;
  minimap.dirty = true;
}

function refreshBoard() {
  const counts = new Array(9).fill(0);
  for (let i = 0; i < W * H; i++) {
    const [wx, wz] = tileCenter(i % W, Math.floor(i / W));
    const v = tiles[i];
    coverMesh.setMatrixAt(i, v === -2 ? M.makeTranslation(wx, 0.3, wz) : ZERO);
    slabMesh.setMatrixAt(i, v >= -1 ? M.makeTranslation(wx, 0, wz) : ZERO);
    if (v > 0) numMeshes[v].setMatrixAt(counts[v]++, M.makeTranslation(wx, 0.11, wz));
  }
  coverMesh.instanceMatrix.needsUpdate = slabMesh.instanceMatrix.needsUpdate = true;
  for (let n = 1; n <= 8; n++) { numMeshes[n].count = counts[n]; numMeshes[n].instanceMatrix.needsUpdate = true; }
  minimap.dirty = true;
}

function groundAt(wx, wz) {
  const [x, y] = tileOf(wx, wz);
  if (!inBoard(x, y)) return -0.5;
  const v = tiles[y * W + x];
  if (v === -3) return layoutKind === 'dungeon' ? WALL_H - 0.5 : -0.5;
  return v === -2 ? 0.6 : 0.1;
}

// dungeon walls are solid: test the four corners of the player's footprint
const PLAYER_R = 0.42;
function solidAt(wx, wz) {
  if (layoutKind !== 'dungeon') return false;
  for (const [ox, oz] of [[-PLAYER_R, -PLAYER_R], [PLAYER_R, -PLAYER_R], [-PLAYER_R, PLAYER_R], [PLAYER_R, PLAYER_R]]) {
    const [x, y] = tileOf(wx + ox, wz + oz);
    if (isWall(x, y)) return true;
  }
  return false;
}

// ---------------------------------------------------------------- flags & craters
function makeFlag(color) {
  const g = new THREE.Group();
  const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 1.6, 6), new THREE.MeshStandardMaterial({ color: 0xeeeeee }));
  pole.position.y = 0.8; pole.castShadow = true;
  const shape = new THREE.Shape(); shape.moveTo(0, 0); shape.lineTo(0.9, -0.28); shape.lineTo(0, -0.56);
  const cloth = new THREE.Mesh(new THREE.ShapeGeometry(shape),
    new THREE.MeshStandardMaterial({ color, side: THREE.DoubleSide, roughness: 0.6 }));
  cloth.position.y = 1.58; cloth.castShadow = true;
  const foot = new THREE.Mesh(new THREE.CylinderGeometry(0.25, 0.3, 0.1, 10), new THREE.MeshStandardMaterial({ color: 0x333333 }));
  foot.position.y = 0.05;
  g.add(pole, cloth, foot);
  g.userData.cloth = cloth;
  return g;
}

function setFlag(x, y, pid) {
  const i = y * W + x;
  const old = flags.get(i);
  if (old) { scene.remove(old.mesh); flags.delete(i); }
  if (!pid) return;
  const color = players.get(pid)?.color ?? '#ffffff';
  const mesh = makeFlag(color);
  const [wx, wz] = tileCenter(x, y);
  mesh.position.set(wx, 0.6, wz);
  mesh.userData.seed = i;
  mesh.userData.pop = 0;
  scene.add(mesh);
  flags.set(i, { pid, mesh });
}

function makeMine() {
  const g = new THREE.Group();
  const mat = new THREE.MeshStandardMaterial({ color: 0x1b1b22, metalness: 0.7, roughness: 0.3 });
  const ball = new THREE.Mesh(new THREE.SphereGeometry(0.38, 16, 12), mat);
  g.add(ball);
  const spikeGeo = new THREE.CylinderGeometry(0.04, 0.07, 0.95, 6);
  for (const [ax, az] of [[0, 0], [Math.PI / 2, 0], [0, Math.PI / 2]]) {
    const s = new THREE.Mesh(spikeGeo, mat); s.rotation.set(ax, 0, az); g.add(s);
  }
  const led = new THREE.Mesh(new THREE.SphereGeometry(0.09, 8, 6), new THREE.MeshBasicMaterial({ color: 0xff2a2a }));
  led.position.y = 0.4; g.add(led);
  g.userData.led = led;
  g.traverse((o) => { o.castShadow = true; });
  return g;
}

function addCrater(x, y) {
  const i = y * W + x;
  if (craters.has(i)) return;
  const [wx, wz] = tileCenter(x, y);
  const g = new THREE.Group();
  const scorch = new THREE.Mesh(new THREE.CircleGeometry(T * 0.47, 20),
    new THREE.MeshStandardMaterial({ color: 0x2a2018, roughness: 1 }));
  scorch.rotation.x = -Math.PI / 2; scorch.position.y = 0.105;
  const mine = makeMine(); mine.position.y = 0.45; mine.rotation.y = Math.random() * 3;
  g.add(scorch, mine);
  g.position.set(wx, 0, wz);
  g.userData.led = mine.userData.led;
  scene.add(g);
  craters.set(i, g);
}

function showAllMines(list) {
  let n = 0;
  for (const [x, y] of list) {
    if (tiles[y * W + x] === -1) continue;
    const [wx, wz] = tileCenter(x, y);
    minesShown.setMatrixAt(n++, M.makeTranslation(wx, 1.0, wz));
  }
  minesShown.count = n;
  minesShown.instanceMatrix.needsUpdate = true;
}

// ---------------------------------------------------------------- power-ups
const ITEM_INFO = {
  scatter: { name: 'Scatter bomb', color: 0xc77dff, css: '#c77dff' },
  shield: { name: 'Shield', color: 0x4fa3ff, css: '#4fa3ff' },
  radar: { name: 'Radar', color: 0x4fd67a, css: '#4fd67a' },
  boots: { name: 'Boots', color: 0xff9f43, css: '#ff9f43' },
  freeze: { name: 'Freeze ray', color: 0x3ee6d6, css: '#3ee6d6', hint: 'aim at a player, press G' },
  gold: { name: 'Gold rush', color: 0xffd23f, css: '#ffd23f' },
  shockwave: { name: 'Shockwave', color: 0xff6fb5, css: '#ff6fb5', hint: 'press G near rivals' },
  blink: { name: 'Blink', color: 0xa3e635, css: '#a3e635', hint: 'aim at a tile, press G' },
  apple: { name: 'Apple', color: 0xff4d4d, css: '#ff4d4d' },
  potion: { name: 'Health potion', color: 0xff6fb5, css: '#ff6fb5' },
};
ITEM_INFO.scatter.hint = 'aim at a tile, press G';
let HELD = ['', 'scatter', 'freeze', 'shockwave', 'blink'];   // replaced by cfg.held from the server
let freezeRange = 10, blinkRange = 8, shockRadius = 3;
const heldKind = (fx) => HELD[(fx || 0) >> 4] || '';

function makeScatterBomb() {
  const g = new THREE.Group();
  const body = new THREE.Mesh(new THREE.SphereGeometry(0.38, 16, 12),
    new THREE.MeshStandardMaterial({ color: 0x2a2233, metalness: 0.5, roughness: 0.35 }));
  const band = new THREE.Mesh(new THREE.TorusGeometry(0.38, 0.06, 6, 20), new THREE.MeshStandardMaterial({ color: 0xc77dff, emissive: 0x5a2a80 }));
  band.rotation.x = Math.PI / 2;
  const cap = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.12, 0.14, 8), new THREE.MeshStandardMaterial({ color: 0x888888, metalness: 0.7 }));
  cap.position.y = 0.4;
  const fuse = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.025, 0.22, 5), new THREE.MeshStandardMaterial({ color: 0xc8a060 }));
  fuse.position.set(0.05, 0.55, 0); fuse.rotation.z = -0.4;
  const spark = new THREE.Mesh(new THREE.SphereGeometry(0.08, 8, 6), new THREE.MeshBasicMaterial({ color: 0xffe14d }));
  spark.position.set(0.1, 0.66, 0);
  g.add(body, band, cap, fuse, spark);
  g.userData.spark = spark;
  g.traverse((o) => { o.castShadow = true; });
  return g;
}

function itemModel(kind) {
  const c = ITEM_INFO[kind].color;
  const glow = new THREE.MeshStandardMaterial({ color: c, emissive: c, emissiveIntensity: 0.6, roughness: 0.4 });
  const g = new THREE.Group();
  if (kind === 'scatter') g.add(makeScatterBomb());
  else if (kind === 'shield') {
    const s = new THREE.Mesh(new THREE.CylinderGeometry(0.45, 0.45, 0.1, 6), glow); s.rotation.x = Math.PI / 2;
    const boss = new THREE.Mesh(new THREE.SphereGeometry(0.14, 10, 8), new THREE.MeshStandardMaterial({ color: 0xffffff, metalness: 0.6 }));
    boss.position.z = 0.07; g.add(s, boss);
  } else if (kind === 'radar') {
    const dish = new THREE.Mesh(new THREE.SphereGeometry(0.42, 16, 8, 0, Math.PI * 2, 0, Math.PI / 3),
      new THREE.MeshStandardMaterial({ color: 0xdddddd, side: THREE.DoubleSide, metalness: 0.4 }));
    dish.rotation.x = Math.PI * 0.75;
    const ring = new THREE.Mesh(new THREE.TorusGeometry(0.36, 0.04, 6, 24), glow); ring.rotation.x = Math.PI * 0.75;
    const tip = new THREE.Mesh(new THREE.SphereGeometry(0.08, 8, 6), glow); tip.position.set(0, -0.1, 0.18);
    g.add(dish, ring, tip);
  } else if (kind === 'boots') {
    for (const sx of [-0.18, 0.18]) {
      const leg = new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.36, 0.22), glow); leg.position.set(sx, 0.1, -0.04);
      const toe = new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.14, 0.38), glow); toe.position.set(sx, -0.11, 0.04);
      const wing = new THREE.Mesh(new THREE.ConeGeometry(0.1, 0.34, 4), new THREE.MeshStandardMaterial({ color: 0xffffff }));
      wing.rotation.z = sx > 0 ? -1.2 : 1.2; wing.position.set(sx * 1.9, 0.18, -0.08);
      g.add(leg, toe, wing);
    }
  } else if (kind === 'freeze') {
    // a chunky ray gun with a crystal emitter
    const metal = new THREE.MeshStandardMaterial({ color: 0xd8e6f0, metalness: 0.6, roughness: 0.3 });
    const barrel = new THREE.Mesh(new THREE.CylinderGeometry(0.11, 0.15, 0.6, 10), metal); barrel.rotation.x = Math.PI / 2; barrel.position.z = 0.1;
    const coil = new THREE.Mesh(new THREE.TorusGeometry(0.15, 0.04, 6, 14), glow); coil.position.z = 0.05;
    const coil2 = coil.clone(); coil2.position.z = 0.22;
    const grip = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.32, 0.14), metal); grip.position.set(0, -0.2, -0.1); grip.rotation.x = 0.3;
    const gem = new THREE.Mesh(new THREE.OctahedronGeometry(0.12), glow); gem.position.z = 0.45;
    g.add(barrel, coil, coil2, grip, gem);
  } else if (kind === 'gold') {
    const gold = new THREE.MeshStandardMaterial({ color: 0xffd23f, emissive: 0x7a5200, metalness: 0.9, roughness: 0.25 });
    for (const [x, y, z] of [[0, -0.1, 0], [0.16, 0.0, 0.05], [-0.14, 0.06, -0.04], [0.02, 0.14, 0.08]]) {
      const coin = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.2, 0.05, 18), gold);
      coin.position.set(x, y, z); coin.rotation.set(Math.PI / 2 + x, 0, y * 3); g.add(coin);
    }
  } else if (kind === 'shockwave') {
    const core = new THREE.Mesh(new THREE.IcosahedronGeometry(0.2, 0), glow);
    g.add(core);
    for (let k = 0; k < 3; k++) {
      const ring = new THREE.Mesh(new THREE.TorusGeometry(0.28 + k * 0.08, 0.025, 6, 24), glow);
      ring.rotation.set(k * 1.05, k * 0.7, 0); g.add(ring);
    }
  } else if (kind === 'apple') {
    const apple = new THREE.Mesh(new THREE.SphereGeometry(0.34, 18, 14), new THREE.MeshStandardMaterial({ color: 0xe8243c, roughness: 0.35 }));
    apple.scale.y = 0.9;
    const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.03, 0.18, 6), new THREE.MeshStandardMaterial({ color: 0x6b4a2b }));
    stem.position.y = 0.36;
    const leaf = new THREE.Mesh(new THREE.SphereGeometry(0.11, 8, 6), new THREE.MeshStandardMaterial({ color: 0x4fd67a }));
    leaf.scale.set(1, 0.25, 0.5); leaf.position.set(0.1, 0.38, 0); leaf.rotation.z = -0.5;
    g.add(apple, stem, leaf);
  } else if (kind === 'potion') {
    const glass = new THREE.MeshStandardMaterial({ color: 0xe8f6ff, transparent: true, opacity: 0.35, roughness: 0.05 });
    const flask = new THREE.Mesh(new THREE.SphereGeometry(0.3, 18, 14), glass);
    const liquid = new THREE.Mesh(new THREE.SphereGeometry(0.24, 16, 12), glow); liquid.position.y = -0.03;
    const neck = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.1, 0.22, 10), glass); neck.position.y = 0.34;
    const cork = new THREE.Mesh(new THREE.CylinderGeometry(0.085, 0.075, 0.1, 10), new THREE.MeshStandardMaterial({ color: 0xa0784a }));
    cork.position.y = 0.48;
    g.add(liquid, flask, neck, cork);
  } else if (kind === 'blink') {
    const ring = new THREE.Mesh(new THREE.TorusGeometry(0.32, 0.06, 8, 28), glow);
    const inner = new THREE.Mesh(new THREE.CircleGeometry(0.28, 24),
      new THREE.MeshBasicMaterial({ color: 0x0b1522, side: THREE.DoubleSide }));
    const swirl = new THREE.Mesh(new THREE.TorusGeometry(0.15, 0.03, 6, 20, Math.PI * 1.4), glow);
    g.add(ring, inner, swirl);
  }
  return g;
}

function addItem(x, y, kind) {
  const i = y * W + x;
  removeItem(i);
  const info = ITEM_INFO[kind]; if (!info) return;
  const g = new THREE.Group();
  const ring = new THREE.Mesh(new THREE.RingGeometry(0.55, 0.8, 24),
    new THREE.MeshBasicMaterial({ color: info.color, transparent: true, opacity: 0.85, depthWrite: false }));
  ring.rotation.x = -Math.PI / 2; ring.position.y = 0.12;
  const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.55, 0.55, 2.4, 16, 1, true),
    new THREE.MeshBasicMaterial({ color: info.color, transparent: true, opacity: 0.12, depthWrite: false, side: THREE.DoubleSide }));
  beam.position.y = 1.3;
  const model = itemModel(kind); model.position.y = 1.0;
  g.add(ring, beam, model);
  const [wx, wz] = tileCenter(x, y);
  g.position.set(wx, tiles[i] === -2 ? 0.5 : 0, wz);   // boss loot can land on unrevealed tiles
  g.userData = { model, seed: i, pop: 0 };
  scene.add(g);
  items.set(i, { kind, mesh: g });
}

function removeItem(i) {
  const it = items.get(i);
  if (!it) return;
  scene.remove(it.mesh); disposeTree(it.mesh); items.delete(i);
}

function clearRadar() {
  if (!radar) return;
  scene.remove(radar.group); disposeTree(radar.group); radar = null;
}

function showRadar(list, dur) {
  clearRadar();
  const g = new THREE.Group();
  const mat = new THREE.MeshBasicMaterial({ color: 0xff3b3b, transparent: true, opacity: 0.75, depthWrite: false });
  const ringMat = new THREE.MeshBasicMaterial({ color: 0x4fd67a, transparent: true, opacity: 0.9, depthWrite: false, side: THREE.DoubleSide });
  for (const [x, y] of list) {
    const [wx, wz] = tileCenter(x, y);
    const m = new THREE.Mesh(new THREE.OctahedronGeometry(0.35), mat); m.position.set(wx, 1.4, wz);
    const r = new THREE.Mesh(new THREE.RingGeometry(0.6, 0.75, 4, 1, Math.PI / 4), ringMat);
    r.rotation.x = -Math.PI / 2; r.position.set(wx, 0.64, wz);
    m.userData.tile = r.userData.tile = y * W + x;
    g.add(m, r);
  }
  scene.add(g);
  radar = { group: g, until: performance.now() + dur * 1000, mat };
}

function blastArea(x, y, r) {
  const out = [];
  for (let yy = y - r; yy <= y + r; yy++) for (let xx = x - r; xx <= x + r; xx++) if (inBoard(xx, yy)) out.push(yy * W + xx);
  return out;
}

// ---------------------------------------------------------------- avatars
function makeAvatar(color, name, charId) {
  const c = buildCharacter(charId, color);
  const g = c.root;
  const stars = new THREE.Group();
  for (let k = 0; k < 3; k++) {
    const s = new THREE.Mesh(new THREE.OctahedronGeometry(0.12), new THREE.MeshBasicMaterial({ color: 0xffe14d }));
    const a = (k / 3) * Math.PI * 2; s.position.set(Math.cos(a) * 0.55, 0, Math.sin(a) * 0.55);
    stars.add(s);
  }
  stars.position.y = c.top + 0.15; stars.visible = false;
  const label = textSprite(name, { dot: color, scale: 0.8 });
  label.position.y = c.top + 0.8;
  const bubble = new THREE.Mesh(new THREE.SphereGeometry(1, 24, 16), new THREE.MeshStandardMaterial({
    color: 0x4fa3ff, emissive: 0x2a5aa0, transparent: true, opacity: 0.22, depthWrite: false, roughness: 0.1 }));
  bubble.scale.set(1.1, (c.top + 0.4) / 2 + 0.2, 1.1); bubble.position.y = (c.top + 0.4) / 2; bubble.visible = false;
  const held = new THREE.Group(); held.position.set(0, c.top + 0.45, 0);
  const ice = new THREE.Mesh(new THREE.BoxGeometry(1.5, c.top + 0.5, 1.5), new THREE.MeshStandardMaterial({
    color: 0xbff4ff, emissive: 0x1a6a80, transparent: true, opacity: 0.55, roughness: 0.05, metalness: 0.1 }));
  ice.position.y = (c.top + 0.5) / 2; ice.visible = false;
  const aura = new THREE.Mesh(new THREE.RingGeometry(0.7, 0.95, 28), new THREE.MeshBasicMaterial({
    color: 0xffd23f, transparent: true, opacity: 0.8, depthWrite: false, side: THREE.DoubleSide }));
  aura.rotation.x = -Math.PI / 2; aura.position.y = 0.05; aura.visible = false;
  const hpCanvas = document.createElement('canvas'); hpCanvas.width = 128; hpCanvas.height = 20;
  const hpTex = new THREE.CanvasTexture(hpCanvas); hpTex.colorSpace = THREE.SRGBColorSpace;
  const hpBar = new THREE.Sprite(new THREE.SpriteMaterial({ map: hpTex, transparent: true, depthWrite: false }));
  hpBar.scale.set(1.4, 0.22, 1); hpBar.position.y = c.top + 0.42;
  g.add(stars, label, bubble, held, ice, aura, hpBar);
  scene.add(g);
  const av = { group: g, upper: c.upper, feet: c.feet, tick: c.tick, stars, label, bubble, held, heldKind: '', ice, aura,
    hpBar, hpCanvas, top: c.top };
  drawHpBar(av, maxHp);
  return av;
}

function drawHpBar(av, hp) {
  if (!av?.hpCanvas) return;
  const g = av.hpCanvas.getContext('2d'), k = Math.max(0, Math.min(1, hp / maxHp));
  g.clearRect(0, 0, 128, 20);
  g.fillStyle = 'rgba(10,18,30,.75)'; g.beginPath(); g.roundRect(0, 0, 128, 20, 8); g.fill();
  g.fillStyle = k > 0.6 ? '#4fd67a' : k > 0.3 ? '#ffd23f' : '#ff5d5d';
  if (k > 0) { g.beginPath(); g.roundRect(3, 3, 122 * k, 14, 6); g.fill(); }
  av.hpBar.material.map.needsUpdate = true;
}

function animateAvatar(p, av, speed, dt, stunned) {
  p.phase += speed * dt * 1.6;
  const sw = speed > 0.3 ? Math.sin(p.phase) : 0;
  if (av.feet.length === 2) { av.feet[0].position.z = sw * 0.25; av.feet[1].position.z = -sw * 0.25; }
  av.upper.position.y = Math.abs(sw) * 0.06;
  av.tick?.(elapsed, speed);
  const fx = p.fx || 0, frozen = !!(fx & 8), ko = p.hp === 0;
  // knocked out: topple over until the respawn; a melee swing lunges forward briefly
  if (p.swing > 0) p.swing = Math.max(0, p.swing - dt);
  const lunge = p.swing > 0 ? Math.sin((p.swing / 0.3) * Math.PI) * 0.5 : 0;
  av.upper.rotation.x += ((ko ? -1.45 : lunge) - av.upper.rotation.x) * Math.min(1, dt * (p.swing > 0 ? 30 : 8));
  av.hpBar.visible = !ko;
  av.stars.visible = stunned && !frozen && !ko;
  if (stunned) av.stars.rotation.y += dt * 6;
  av.ice.visible = frozen;
  av.bubble.visible = !!(fx & 1);
  if (fx & 1) av.bubble.material.opacity = 0.18 + Math.sin(elapsed * 4) * 0.06;
  av.aura.visible = !!(fx & 4);
  if (fx & 4) { av.aura.rotation.z += dt * 2; av.aura.scale.setScalar(1 + Math.sin(elapsed * 6) * 0.08); }
  // the held item floats over the player's head
  const hk = heldKind(fx);
  if (hk !== av.heldKind) {
    for (const ch of [...av.held.children]) { av.held.remove(ch); disposeTree(ch); }
    if (hk) { const m = itemModel(hk); m.scale.setScalar(0.65); av.held.add(m); }
    av.heldKind = hk;
  }
  av.held.visible = !!hk && !stunned;
  if (hk) av.held.rotation.y += dt * 2;
  if ((fx & 4) && speed > 0.3 && Math.random() < dt * 12) {
    const gp = av.group.position;
    burst(new THREE.Vector3(gp.x, gp.y + 0.3, gp.z), { count: 3, colors: [0xffd23f, 0xfff1a0], speed: [1, 2.5], life: 0.6, size: 0.2, gravity: 6 });
  }
  if ((fx & 2) && speed > 0.3 && Math.random() < dt * 25) {
    const gp = av.group.position;
    burst(new THREE.Vector3(gp.x, gp.y + 0.15, gp.z), { count: 4, colors: [0xff9f43, 0xffd23f], speed: [0.5, 1.5], life: 0.45, size: 0.22, gravity: -2 });
  }
}

// ---------------------------------------------------------------- effects
const effects = [];

function burst(pos, { count = 80, colors = [0xffb347], speed = [4, 12], up = 1, life = 1.2, size = 0.35, gravity = 18 }) {
  const geo = new THREE.BufferGeometry();
  const P = new Float32Array(count * 3), C = new Float32Array(count * 3), V = [];
  const col = new THREE.Color();
  for (let i = 0; i < count; i++) {
    P.set([pos.x, pos.y, pos.z], i * 3);
    col.set(colors[(Math.random() * colors.length) | 0]); C.set([col.r, col.g, col.b], i * 3);
    const a = Math.random() * Math.PI * 2, e = Math.random() * up, sp = speed[0] + Math.random() * (speed[1] - speed[0]);
    V.push(Math.cos(a) * sp * (1 - e * 0.5), (0.4 + e) * sp, Math.sin(a) * sp * (1 - e * 0.5));
  }
  geo.setAttribute('position', new THREE.BufferAttribute(P, 3));
  geo.setAttribute('color', new THREE.BufferAttribute(C, 3));
  const mat = new THREE.PointsMaterial({ size, vertexColors: true, transparent: true, depthWrite: false });
  const pts = new THREE.Points(geo, mat);
  scene.add(pts);
  let t = 0;
  effects.push((dt) => {
    t += dt;
    for (let i = 0; i < count; i++) {
      V[i * 3 + 1] -= gravity * dt;
      P[i * 3] += V[i * 3] * dt; P[i * 3 + 1] += V[i * 3 + 1] * dt; P[i * 3 + 2] += V[i * 3 + 2] * dt;
      if (P[i * 3 + 1] < 0.1) { P[i * 3 + 1] = 0.1; V[i * 3] *= 0.6; V[i * 3 + 2] *= 0.6; V[i * 3 + 1] *= -0.3; }
    }
    geo.attributes.position.needsUpdate = true;
    mat.opacity = Math.max(0, 1 - t / life);
    if (t >= life) { scene.remove(pts); geo.dispose(); mat.dispose(); return false; }
    return true;
  });
}

function explosion(wx, wz) {
  const pos = new THREE.Vector3(wx, 0.6, wz);
  burst(pos, { count: 160, colors: [0xffd23f, 0xff7b29, 0xff3d1f, 0x555555, 0x333333], speed: [6, 16], life: 1.6, size: 0.45 });
  burst(pos, { count: 50, colors: [0x6cc04a, 0x7a5a3a], speed: [5, 11], life: 1.4, size: 0.3 });
  const ball = new THREE.Mesh(new THREE.SphereGeometry(1, 20, 14),
    new THREE.MeshBasicMaterial({ color: 0xffa040, transparent: true, depthWrite: false }));
  ball.position.copy(pos); scene.add(ball);
  const light = new THREE.PointLight(0xffa050, 400, 40, 1.6);
  light.position.set(wx, 3, wz); scene.add(light);
  let t = 0;
  effects.push((dt) => {
    t += dt;
    const k = t / 0.5;
    ball.scale.setScalar(0.5 + k * 4);
    ball.material.opacity = Math.max(0, 1 - k);
    light.intensity = Math.max(0, 400 * (1 - t / 0.7));
    if (t > 0.7) { scene.remove(ball, light); ball.geometry.dispose(); ball.material.dispose(); light.dispose(); return false; }
    return true;
  });
}

function floatText(text, color, wx, wy, wz) {
  const s = textSprite(text, { color, bg: null, scale: 0.9, font: 900 });
  s.position.set(wx, wy, wz); scene.add(s);
  let t = 0;
  effects.push((dt) => {
    t += dt;
    s.position.y += dt * 1.4;
    s.material.opacity = Math.min(1, 2.5 * (1.4 - t));
    if (t > 1.4) { scene.remove(s); s.material.map.dispose(); s.material.dispose(); return false; }
    return true;
  });
}

function playerPos(pid) {
  if (pid === myId) return [me.x, me.y, me.z];
  const p = players.get(pid);
  if (p) return [p.x, p.y, p.z];
  const b = bosses.get(pid);
  return b ? [b.x, b.y + b.m.top - 2.4, b.z] : null;
}

// ---------------------------------------------------------------- bosses
function makeBoss(id, kind) {
  const def = BOSSES[kind] || BOSSES.ogre;
  const m = def.build();
  const g = m.root;
  const label = textSprite(def.name, { dot: def.color, scale: 1.1, color: '#ffd2d2' });
  label.position.y = m.top + 1.2;
  const hpCanvas = document.createElement('canvas'); hpCanvas.width = 160; hpCanvas.height = 22;
  const hpTex = new THREE.CanvasTexture(hpCanvas); hpTex.colorSpace = THREE.SRGBColorSpace;
  const hpBar = new THREE.Sprite(new THREE.SpriteMaterial({ map: hpTex, transparent: true, depthWrite: false }));
  hpBar.scale.set(2.6, 0.36, 1); hpBar.position.y = m.top + 0.6;
  const ice = new THREE.Mesh(new THREE.BoxGeometry(3.2, m.top + 0.4, 3.2), new THREE.MeshStandardMaterial({
    color: 0xbff4ff, emissive: 0x1a6a80, transparent: true, opacity: 0.5, roughness: 0.05 }));
  ice.position.y = (m.top + 0.4) / 2; ice.visible = false;
  const stars = new THREE.Group();
  for (let k = 0; k < 4; k++) {
    const s = new THREE.Mesh(new THREE.OctahedronGeometry(0.2), new THREE.MeshBasicMaterial({ color: 0xffe14d }));
    const a = (k / 4) * Math.PI * 2; s.position.set(Math.cos(a) * 1.1, 0, Math.sin(a) * 1.1); stars.add(s);
  }
  stars.position.y = m.top + 0.2; stars.visible = false;
  g.add(label, hpBar, ice, stars);
  scene.add(g);
  const b = { id, kind, m, group: g, hpBar, hpCanvas, ice, stars, x: NaN, z: 0, y: 0, tx: 0, tz: 0, r: 0, tr: 0,
    hp: 1, max: 1, state: 0, hitFlash: 0, phase: Math.random() * 6 };
  bosses.set(id, b);
  return b;
}

function drawBossHp(b) {
  const g = b.hpCanvas.getContext('2d'), k = Math.max(0, b.hp / b.max);
  g.clearRect(0, 0, 160, 22);
  g.fillStyle = 'rgba(20,6,10,.8)'; g.beginPath(); g.roundRect(0, 0, 160, 22, 9); g.fill();
  g.fillStyle = '#e24d4d'; if (k > 0) { g.beginPath(); g.roundRect(3, 3, 154 * k, 16, 7); g.fill(); }
  b.hpBar.material.map.needsUpdate = true;
}

function removeBoss(id) {
  const b = bosses.get(id); if (!b) return;
  scene.remove(b.group); disposeTree(b.group); bosses.delete(id);
}

// a red warning disc that fills up during a boss's wind-up
function telegraph(x, z, r, dur) {
  const R = r * T;
  const ring = new THREE.Mesh(new THREE.RingGeometry(R - 0.15, R, 48),
    new THREE.MeshBasicMaterial({ color: 0xff3b3b, transparent: true, opacity: 0.9, depthWrite: false, side: THREE.DoubleSide }));
  const fill = new THREE.Mesh(new THREE.CircleGeometry(R, 48),
    new THREE.MeshBasicMaterial({ color: 0xff3b3b, transparent: true, opacity: 0.25, depthWrite: false, side: THREE.DoubleSide }));
  for (const m of [ring, fill]) { m.rotation.x = -Math.PI / 2; m.position.set(x, 0.7, z); m.renderOrder = 3; scene.add(m); }
  let t = 0;
  effects.push((dt) => {
    t += dt; const k = Math.min(1, t / dur);
    fill.scale.setScalar(Math.max(0.01, k));
    ring.material.opacity = 0.6 + Math.sin(t * 30) * 0.3;
    if (t > dur + 0.1) { scene.remove(ring, fill); disposeTree(ring); disposeTree(fill); return false; }
    return true;
  });
}

function updateBosses(dt) {
  const k = 1 - Math.exp(-10 * dt);
  for (const b of bosses.values()) {
    if (Number.isNaN(b.x)) continue;
    const ox = b.x, oz = b.z;
    b.x += (b.tx - b.x) * k; b.z += (b.tz - b.z) * k;
    b.r = lerpAngle(b.r, b.tr, k);
    const gnd = Math.max(groundAt(b.x, b.z), 0.1); b.y += (gnd - b.y) * Math.min(1, dt * 10);
    const sp = Math.hypot(b.x - ox, b.z - oz) / Math.max(dt, 1e-4);
    b.group.position.set(b.x, b.y, b.z);
    b.group.rotation.y = b.r;
    const frozen = b.state === 3, stunned = b.state === 4;
    if (!frozen) b.phase += dt;
    b.m.tick?.(b.phase, b.state, sp / 3);
    b.ice.visible = frozen;
    b.stars.visible = stunned; if (stunned) b.stars.rotation.y += dt * 5;
    if (b.hitFlash > 0) { b.hitFlash = Math.max(0, b.hitFlash - dt * 4); b.m.body.scale.setScalar(1 + b.hitFlash * 0.08); }
  }
}

// ---------------------------------------------------------------- melee
function swingFx(pid) {
  const pos = playerPos(pid); if (!pos) return;
  const p = pid === myId ? players.get(myId) : players.get(pid);
  if (p) p.swing = 0.3;
  const rot = pid === myId ? me.r : (p?.r ?? 0);
  const arc = new THREE.Mesh(new THREE.RingGeometry(1.2, 1.9, 24, 1, -0.9, 1.8),
    new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.8, depthWrite: false, side: THREE.DoubleSide }));
  arc.rotation.x = -Math.PI / 2; arc.rotation.z = rot - Math.PI / 2;
  arc.position.set(pos[0], pos[1] + 1.1, pos[2]); scene.add(arc);
  let t = 0;
  effects.push((dt) => {
    t += dt; arc.material.opacity = Math.max(0, 0.8 - t * 4); arc.rotation.z += dt * 6;
    if (t > 0.22) { scene.remove(arc); disposeTree(arc); return false; }
    return true;
  });
}

// ---------------------------------------------------------------- audio
let actx = null;
function audio() {
  if (!actx) { try { actx = new AudioContext(); } catch { actx = null; } }
  return actx;
}
function tone(freq, dur, { type = 'sine', vol = 0.15, slide = 0, delay = 0 } = {}) {
  const a = audio(); if (!a) return;
  const t0 = a.currentTime + delay;
  const o = a.createOscillator(), g = a.createGain();
  o.type = type; o.frequency.setValueAtTime(freq, t0);
  if (slide) o.frequency.exponentialRampToValueAtTime(Math.max(20, freq + slide), t0 + dur);
  g.gain.setValueAtTime(vol, t0); g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
  o.connect(g).connect(a.destination); o.start(t0); o.stop(t0 + dur + 0.02);
}
function noise(dur, vol, cutoff) {
  const a = audio(); if (!a) return;
  const buf = a.createBuffer(1, a.sampleRate * dur, a.sampleRate);
  const d = buf.getChannelData(0);
  for (let i = 0; i < d.length; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / d.length, 2);
  const src = a.createBufferSource(); src.buffer = buf;
  const f = a.createBiquadFilter(); f.type = 'lowpass'; f.frequency.value = cutoff;
  const g = a.createGain(); g.gain.value = vol;
  src.connect(f).connect(g).connect(a.destination); src.start();
}
const distVol = (wx, wz) => Math.max(0.12, 1 - Math.hypot(wx - me.x, wz - me.z) / 70);
const sfx = {
  dig: (n, v) => { tone(420 + Math.min(n, 30) * 18, 0.09, { type: 'triangle', vol: 0.12 * v, slide: -180 }); noise(0.06, 0.15 * v, 2500); },
  flag: (v) => { tone(880, 0.06, { type: 'square', vol: 0.05 * v }); tone(1320, 0.09, { type: 'square', vol: 0.05 * v, delay: 0.06 }); },
  unflag: (v) => tone(600, 0.08, { type: 'square', vol: 0.04 * v, slide: -250 }),
  boom: (v) => { noise(1.4, 0.9 * v, 700); tone(90, 0.9, { vol: 0.6 * v, slide: -60 }); },
  win: () => [523, 659, 784, 1047].forEach((f, i) => tone(f, 0.25, { type: 'triangle', vol: 0.12, delay: i * 0.12 })),
  pickup: (v) => [660, 880, 1320].forEach((f, i) => tone(f, 0.12, { type: 'triangle', vol: 0.1 * v, delay: i * 0.06 })),
  throw: (v) => { noise(0.25, 0.25 * v, 1800); tone(300, 0.3, { type: 'sine', vol: 0.08 * v, slide: 500 }); },
  tick: (v) => tone(1500, 0.04, { type: 'square', vol: 0.04 * v }),
  scatter: (v) => { noise(1.2, 0.8 * v, 1100); tone(160, 0.7, { vol: 0.4 * v, slide: -120 }); tone(70, 1.1, { type: 'triangle', vol: 0.3 * v, slide: 40, delay: 0.05 }); },
  roar: (v) => { noise(1.2, 0.35 * v, 500); tone(110, 1.0, { type: 'sawtooth', vol: 0.12 * v, slide: -50 }); tone(82, 1.1, { type: 'square', vol: 0.06 * v, slide: 30, delay: 0.1 }); },
  growl: (v) => tone(70, 0.6, { type: 'sawtooth', vol: 0.1 * v, slide: 40 }),
  smash: (v) => { noise(0.9, 0.8 * v, 600); tone(55, 0.7, { vol: 0.6 * v, slide: -30 }); },
  hit: (v) => { noise(0.08, 0.3 * v, 3000); tone(220, 0.08, { type: 'square', vol: 0.06 * v, slide: -100 }); },
  whoosh: () => noise(0.15, 0.12, 2500),
  bossDown: (v) => { noise(1.6, 0.8 * v, 900); [392, 523, 659, 784].forEach((f, i) => tone(f, 0.3, { type: 'triangle', vol: 0.12 * v, delay: 0.3 + i * 0.1 })); },
  heal: () => [523, 784, 1047].forEach((f, i) => tone(f, 0.18, { type: 'sine', vol: 0.1, delay: i * 0.07 })),
  ko: () => { tone(400, 0.6, { type: 'sawtooth', vol: 0.08, slide: -320 }); tone(200, 0.8, { type: 'triangle', vol: 0.1, slide: -150, delay: 0.15 }); },
  zap: (v) => { tone(2400, 0.35, { type: 'sawtooth', vol: 0.06 * v, slide: -2000 }); tone(1800, 0.3, { type: 'sine', vol: 0.08 * v, slide: 1200, delay: 0.02 }); },
  freeze: (v) => { noise(0.5, 0.25 * v, 5000); [2093, 2637, 3136].forEach((f, i) => tone(f, 0.18, { type: 'sine', vol: 0.05 * v, delay: 0.05 + i * 0.05 })); },
  shock: (v) => { tone(55, 0.8, { type: 'sine', vol: 0.5 * v, slide: 30 }); noise(0.6, 0.5 * v, 400); tone(220, 0.4, { type: 'square', vol: 0.05 * v, slide: -180 }); },
  blink: (v) => { tone(300, 0.18, { type: 'sine', vol: 0.12 * v, slide: 1500 }); tone(1800, 0.2, { type: 'sine', vol: 0.08 * v, slide: -1400, delay: 0.15 }); },
  shield: (v) => { tone(1200, 0.25, { type: 'sine', vol: 0.15 * v, slide: -600 }); tone(1800, 0.2, { type: 'sine', vol: 0.08 * v, delay: 0.05 }); },
};

// ---------------------------------------------------------------- HUD
function feed(...parts) {
  const d = document.createElement('div');
  for (const p of parts) {
    if (typeof p === 'string') d.append(p);
    else { const b = document.createElement('b'); b.textContent = p.text; b.style.color = p.color; d.append(b); }
  }
  const box = $('feed'); box.append(d);
  while (box.children.length > 6) box.firstChild.remove();
  setTimeout(() => d.remove(), 5100);
}
const who = (pid) => {
  const p = players.get(pid);
  return { text: pid === myId ? 'You' : (p?.name ?? 'Someone'), color: p?.color ?? '#fff' };
};

let lastBoardKey = '';
function renderScores() {
  const list = [...players.entries()].sort((a, b) => b[1].score - a[1].score);
  const key = list.map(([id, p]) => id + p.score + p.name).join('|');
  if (key === lastBoardKey) return;
  lastBoardKey = key;
  renderModeRow();
  const ol = $('scores'); ol.replaceChildren();
  for (const [id, p] of list) {
    const li = document.createElement('li'); if (id === myId) li.className = 'me';
    const sw = document.createElement('span'); sw.className = 'sw'; sw.style.background = p.color;
    const nm = document.createElement('span'); nm.className = 'nm'; nm.textContent = p.name;
    const sc = document.createElement('span'); sc.className = 'sc'; sc.textContent = p.score;
    li.append(sw, nm);
    if (p.bot) { const b = document.createElement('span'); b.className = 'bot'; b.textContent = 'BOT'; li.append(b); }
    li.append(sc); ol.append(li);
  }
}

function setCounters(m) {
  if (m.minesLeft !== undefined) $('minesLeft').textContent = m.minesLeft;
  if (m.safeLeft !== undefined) $('safeLeft').textContent = m.safeLeft;
}

function showResults(results, next, duration) {
  roundState = 'over';
  overEndsAt = performance.now() + next * 1000;
  const ol = $('resultsList'); ol.replaceChildren();
  results.forEach((r, i) => {
    const li = document.createElement('li'); if (r.id === myId) li.className = 'me';
    const sw = document.createElement('span'); sw.className = 'sw'; sw.style.background = r.color;
    const nm = document.createElement('span'); nm.className = 'nm'; nm.textContent = `${['🥇', '🥈', '🥉'][i] ?? `${i + 1}.`} ${r.name}`;
    const sc = document.createElement('span'); sc.className = 'sc'; sc.textContent = r.score;
    li.append(sw, nm);
    if (r.flagBonus) { const b = document.createElement('span'); b.className = 'bonus'; b.textContent = `+${r.flagBonus} flags`; li.append(b); }
    li.append(sc); ol.append(li);
  });
  $('resultsSub').textContent = duration ? `Cleared in ${Math.floor(duration / 60)}m ${duration % 60}s` : 'This round is over.';
  $('results').hidden = false;
}

// ---------------------------------------------------------------- networking
function connect(name, room) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => send({ t: 'join', name, room, char: picker.char, color: picker.color, realm: picker.realm, layout: picker.layout, mode: picker.mode });
  ws.onmessage = (e) => handle(JSON.parse(e.data));
  ws.onclose = () => {
    $('hud').hidden = true; $('results').hidden = true;
    const wasIn = !!myId;
    myId = null;
    if (joinError) {   // the server refused the join (e.g. room full): keep its message
      const msg = joinError; joinError = null;
      openPicker(false);
      const err = $('joinError'); err.textContent = msg; err.hidden = false;
      return;
    }
    openPicker(false);
    const err = $('joinError'); err.textContent = wasIn ? 'Connection lost. Press the button to rejoin.' : 'Could not connect to the server.'; err.hidden = false;
  };
}

function applySnapshot(s) {
  tiles.fill(-2);
  for (const { mesh } of flags.values()) scene.remove(mesh);
  flags.clear();
  for (const g of craters.values()) scene.remove(g);
  craters.clear();
  for (const i of [...items.keys()]) removeItem(i);
  for (const b of bombs.values()) { scene.remove(b.mesh, b.zone); disposeTree(b.mesh); disposeTree(b.zone); }
  bombs.clear();
  for (const id of [...bosses.keys()]) removeBoss(id);
  clearRadar();
  minesShown.count = 0;
  setLayout(s.layout, s.layoutKind);
  if (s.mode) gameMode = s.mode;
  teamLives = s.lives ?? null;
  renderModeRow();
  for (let i = 0; i < W * H; i++) if (!floor[i]) tiles[i] = -3;
  for (const [x, y, v] of s.tiles) {
    tiles[y * W + x] = v;
    if (v === -1) addCrater(x, y);
  }
  for (const [x, y, pid] of s.flags) setFlag(x, y, pid);
  for (const [x, y, k] of s.items || []) addItem(x, y, k);
  refreshBoard();
  setCounters(s);
  roundState = s.state;
  $('results').hidden = true;
  if (s.state === 'over') {
    showAllMines(s.mines);
    const res = [...players.entries()].map(([id, p]) => ({ id, ...p })).sort((a, b) => b.score - a.score);
    showResults(res, s.next, 0);
  }
}

let joinError = null;
function handle(m) {
  switch (m.t) {
    case 'error':
      joinError = m.message || 'The server refused to join that room.';
      ws.close();
      break;
    case 'welcome': {
      myId = m.id;
      ({ w: W, h: H, tile: T, reach: REACH } = m.cfg);
      throwRange = m.cfg.throwRange ?? throwRange; scatterRadius = m.cfg.scatterRadius ?? scatterRadius;
      bootsSpeed = m.cfg.bootsSpeed ?? bootsSpeed;
      freezeRange = m.cfg.freezeRange ?? freezeRange; blinkRange = m.cfg.blinkRange ?? blinkRange;
      shockRadius = m.cfg.shockRadius ?? shockRadius; if (m.cfg.held) HELD = m.cfg.held;
      maxHp = m.cfg.maxHp ?? maxHp;
      gameMode = m.cfg.mode || 'race';
      const key = `${m.cfg.realm}|${m.snapshot.layoutKind}|${W}x${H}`;
      if (!worldBuilt || worldKey !== key) {
        tiles = new Int8Array(W * H);
        buildWorld(m.cfg.realm, layoutExtent(m.snapshot.layout || ''));
        worldKey = key;
      }
      for (const p of players.values()) scene.remove(p.av.group);
      players.clear();
      [me.x, me.z] = m.spawn;
      $('roomName').textContent = m.room;
      $('join').hidden = true; $('hud').hidden = false;
      applySnapshot(m.snapshot);
      break;
    }
    case 'roster': {
      const ids = new Set();
      for (const r of m.players) {
        ids.add(r.id);
        const ex = players.get(r.id);
        if (!ex) {
          players.set(r.id, { name: r.name, color: r.color, char: r.char, bot: !!r.bot, score: 0, stun: 0, hp: maxHp, av: makeAvatar(r.color, r.name, r.char),
            x: NaN, z: 0, y: 0.6, r: 0, tx: 0, tz: 0, tr: 0, phase: 0 });
          if (r.id !== myId && myId) feed(who(r.id), ' joined');
        } else if (ex.char !== r.char || ex.color !== r.color || ex.name !== r.name) {
          // appearance changed: rebuild the avatar in place
          scene.remove(ex.av.group);
          Object.assign(ex, { name: r.name, color: r.color, char: r.char });
          ex.av = makeAvatar(r.color, r.name, r.char);
          drawHpBar(ex.av, ex.hp ?? maxHp);
          if (r.id === myId) { picker.color = r.color; }
        }
      }
      for (const [id, p] of players) if (!ids.has(id)) { feed(who(id), ' left'); scene.remove(p.av.group); players.delete(id); }
      // flags from the join snapshot can arrive before we know their owners' colors
      for (const f of flags.values()) {
        const owner = players.get(f.pid);
        if (owner) f.mesh.userData.cloth.material.color.set(owner.color);
      }
      renderScores();
      break;
    }
    case 'players':
      for (const [id, x, z, r, s, st, fx = 0, hp = maxHp] of m.p) {
        const p = players.get(id); if (!p) continue;
        p.score = s; p.stun = st; p.fx = fx;
        if (p.hp !== hp) { p.hp = hp; drawHpBar(p.av, hp); }
        if (id === myId) { me.stun = st; me.fx = fx; me.hp = hp; continue; }
        p.tx = x; p.tz = z; p.tr = r;
        if (Number.isNaN(p.x)) { p.x = x; p.z = z; p.r = r; }
      }
      {
        const seen = new Set();
        for (const [id, kind, x, z, r, hp, max, state] of m.b || []) {
          seen.add(id);
          const b = bosses.get(id) || makeBoss(id, kind);
          b.tx = x; b.tz = z; b.tr = r; b.state = state;
          if (Number.isNaN(b.x)) { b.x = x; b.z = z; b.r = r; b.y = groundAt(x, z); }
          if (b.hp !== hp || b.max !== max) { b.hp = hp; b.max = max; drawBossHp(b); }
        }
        for (const id of [...bosses.keys()]) if (!seen.has(id)) removeBoss(id);
      }
      renderScores();
      break;
    case 'bossSpawn':
      feed('⚠ ', { text: `A ${m.name}`, color: BOSSES[m.kind]?.color || '#ff5d5d' }, ' is prowling the dungeon!');
      sfx.roar(distVol(m.x, m.z));
      break;
    case 'bossAtk':
      telegraph(m.x, m.z, m.r, m.t0);
      sfx.growl(distVol(m.x, m.z));
      break;
    case 'bossSmash': {
      const R = m.r * T;
      const ring = new THREE.Mesh(new THREE.RingGeometry(0.5, 1, 48),
        new THREE.MeshBasicMaterial({ color: 0xffb070, transparent: true, depthWrite: false, side: THREE.DoubleSide }));
      ring.rotation.x = -Math.PI / 2; ring.position.set(m.x, 0.75, m.z); scene.add(ring);
      let t = 0;
      effects.push((dt) => {
        t += dt; const k = Math.min(1, t / 0.35); ring.scale.setScalar(0.5 + k * R); ring.material.opacity = 1 - k;
        if (t > 0.35) { scene.remove(ring); disposeTree(ring); return false; }
        return true;
      });
      burst(new THREE.Vector3(m.x, 0.7, m.z), { count: 120, colors: [0x8a6a4a, realm.cover[0], 0xffffff], speed: [6, 14], up: 0.4, life: 1.1, size: 0.4 });
      const v = distVol(m.x, m.z);
      sfx.smash(v); cam.shake = Math.max(cam.shake, v * 1.5);
      for (const pid of [...m.hit, ...m.shielded]) {
        const pp = playerPos(pid), sh = m.shielded.includes(pid);
        if (pp) floatText(sh ? 'SHIELDED' : `-${m.damage} HP`, sh ? '#7fc0ff' : '#ff8080', pp[0], pp[1] + 3.6, pp[2]);
        if (pid === myId) {
          let dx = me.x - m.x, dz = me.z - m.z; const d = Math.hypot(dx, dz) || 1;
          const kick = sh ? 8 : 18;
          me.kx = (dx / d) * kick; me.kz = (dz / d) * kick; me.vy = 9;
          if (!sh) me.stun = m.stun;
        }
      }
      break;
    }
    case 'bossHit': {
      const b = bosses.get(m.id);
      if (b) { b.hp = m.hp; drawBossHp(b); b.hitFlash = 1; }
      floatText(`-${m.dmg}`, '#ffd23f', m.x, (b ? b.m.top : 4) + 1.5, m.z);
      burst(new THREE.Vector3(m.x, 2.4, m.z), { count: 16, colors: [0xffd23f, 0xffffff], speed: [3, 7], life: 0.5, size: 0.3 });
      sfx.hit(distVol(m.x, m.z));
      break;
    }
    case 'bossDown': {
      const b = bosses.get(m.id);
      const top = b ? b.m.top : 4;
      removeBoss(m.id);
      explosion(m.x, m.z);
      burst(new THREE.Vector3(m.x, top / 2, m.z), { count: 200, colors: [0xffd23f, 0xff9f43, 0xffffff, 0xc77dff], speed: [5, 16], life: 1.8, size: 0.5 });
      floatText(`${m.name} defeated!`, '#ffd23f', m.x, top + 2, m.z);
      for (const [x, y, k] of m.loot || []) addItem(x, y, k);
      const v = distVol(m.x, m.z);
      sfx.bossDown(v); cam.shake = Math.max(cam.shake, v);
      const best = Object.entries(m.rewards || {}).sort((a, b2) => b2[1] - a[1]);
      if (m.killer) feed(who(m.killer), ' slew the ', { text: m.name, color: '#ffd23f' }, best.length ? ` (+${m.rewards[m.killer] ?? 0})` : '');
      break;
    }
    case 'swing':
      if (m.pid !== myId) swingFx(m.pid);
      break;
    case 'reveal': {
      let puffs = 0;
      for (const [x, y, v] of m.tiles) {
        const i = y * W + x;
        tiles[i] = v;
        if (flags.has(i)) setFlag(x, y, null);
        if (puffs++ < 40) {
          const [wx, wz] = tileCenter(x, y);
          burst(new THREE.Vector3(wx, 0.5, wz), { count: 10, colors: [0x76c853, 0x5a9a3a, 0xc9a66b], speed: [2, 5], life: 0.7, size: 0.25 });
        }
      }
      refreshBoard();
      setCounters(m);
      for (const [x, y, k] of m.items || []) addItem(x, y, k);
      const pos = playerPos(m.pid);
      if (pos) {
        floatText(`+${m.gain}`, '#7dff8a', pos[0], pos[1] + 3.4, pos[2]);
        sfx.dig(m.gain, m.pid === myId ? 1 : distVol(pos[0], pos[2]) * 0.6);
      }
      for (const [pid, amt] of Object.entries(m.penalties || {})) {
        const pp = playerPos(pid);
        if (pp) floatText(`${amt}`, '#ff8080', pp[0], pp[1] + 3.4, pp[2]);
        feed(who(m.pid), ' dug up ', who(pid), `'s wrong flag (${amt})`);
      }
      break;
    }
    case 'boom': {
      const i = m.y * W + m.x;
      tiles[i] = -1;
      if (flags.has(i)) setFlag(m.x, m.y, null);
      refreshBoard();
      addCrater(m.x, m.y);
      setCounters(m);
      const [wx, wz] = tileCenter(m.x, m.y);
      explosion(wx, wz);
      const v = distVol(wx, wz);
      sfx.boom(v);
      cam.shake = Math.max(cam.shake, v * 1.2);
      const pos = playerPos(m.pid);
      if (pos) floatText(m.shielded ? 'SHIELDED' : `${m.penalty}`, m.shielded ? '#7fc0ff' : '#ff5d5d', pos[0], pos[1] + 3.4, pos[2]);
      if (m.shielded) sfx.shield(v);
      if (m.damage && pos) floatText(`-${m.damage} HP`, '#ff9a9a', pos[0], pos[1] + 4.2, pos[2]);
      if (m.pid === myId) {
        let dx = me.x - wx, dz = me.z - wz; const d = Math.hypot(dx, dz) || 1;
        const kick = m.shielded ? 7 : 16;
        me.kx = (dx / d) * kick; me.kz = (dz / d) * kick; me.vy = m.shielded ? 5 : 10; me.stun = m.stun;
      }
      if (m.shielded) feed(who(m.pid), "'s shield absorbed a mine!");
      else if (m.flagOwner && m.flagOwner !== m.pid) feed(who(m.pid), ' dug ', who(m.flagOwner), "'s flag and hit a mine!");
      else feed(who(m.pid), m.pid === myId ? ' hit a mine! ' : ' hit a mine! ', `(${m.penalty})`);
      break;
    }
    case 'flag': {
      setFlag(m.x, m.y, m.pid);
      setCounters(m);
      const [wx, wz] = tileCenter(m.x, m.y);
      const v = distVol(wx, wz) * 0.8;
      m.pid ? sfx.flag(v) : sfx.unflag(v);
      break;
    }
    case 'pickup': {
      removeItem(m.y * W + m.x);
      const [wx, wz] = tileCenter(m.x, m.y);
      const info = ITEM_INFO[m.kind];
      burst(new THREE.Vector3(wx, 1, wz), { count: 40, colors: [info.color, 0xffffff], speed: [2, 6], life: 0.8, size: 0.25, gravity: 4 });
      sfx.pickup(m.pid === myId ? 1 : distVol(wx, wz) * 0.5);
      if (m.heal) {
        const pp = playerPos(m.pid);
        if (pp) floatText(`+${m.heal} HP`, '#7dff8a', pp[0], pp[1] + 3.8, pp[2]);
        burst(new THREE.Vector3(wx, 1, wz), { count: 30, colors: [0x4fd67a, 0xffffff], speed: [1, 3], life: 1, size: 0.3, gravity: -3 });
        if (m.pid === myId) sfx.heal();
      }
      if (m.pid === myId && m.kind === 'boots') bootsUntil = performance.now() + m.dur * 1000;
      if (m.pid === myId && m.kind === 'gold') goldUntil = performance.now() + m.dur * 1000;
      feed(who(m.pid), ' grabbed ', { text: info.name, color: info.css });
      break;
    }
    case 'radar':
      showRadar(m.mines, m.dur);
      break;
    case 'throw': {
      const from = playerPos(m.pid) || [0, 1, 0];
      const [tx, tz] = tileCenter(m.x, m.y);
      const mesh = makeScatterBomb(); scene.add(mesh);
      const zone = squareOutline(m.r, 0xff3b3b, 0.9); zone.visible = true;
      zone.position.set(tx, 0.66, tz); scene.add(zone);
      bombs.set(m.id, { mesh, zone });
      sfx.throw(distVol(tx, tz));
      const flight = 0.6, sx = from[0], sy = from[1] + 2, sz = from[2];
      let t = 0, lastTick = 0;
      effects.push((dt) => {
        if (!bombs.has(m.id)) return false;
        t += dt;
        const k = Math.min(1, t / flight);
        const gy = groundAt(tx, tz) + 0.4;
        mesh.position.set(sx + (tx - sx) * k, sy + (gy - sy) * k + Math.sin(k * Math.PI) * 5, sz + (tz - sz) * k);
        mesh.rotation.x += dt * (k < 1 ? 12 : 0);
        if (k >= 1) {
          mesh.scale.setScalar(1 + Math.max(0, Math.sin(t * 18)) * 0.15);
          if (t - lastTick > 0.25) { lastTick = t; sfx.tick(distVol(tx, tz)); }
        }
        mesh.userData.spark.visible = Math.sin(t * 30) > 0;
        zone.material.opacity = 0.5 + Math.sin(t * 14) * 0.4;
        return true;
      });
      feed(who(m.pid), ' threw a ', { text: 'Scatter bomb', color: ITEM_INFO.scatter.css }, '!');
      break;
    }
    case 'scatter': {
      const b = bombs.get(m.id);
      if (b) { scene.remove(b.mesh, b.zone); disposeTree(b.mesh); disposeTree(b.zone); bombs.delete(m.id); }
      for (const i of blastArea(m.x, m.y, m.r)) {
        const x = i % W, y = (i / W) | 0;
        if (flags.has(i)) setFlag(x, y, null);
        const c = craters.get(i); if (c) { scene.remove(c); craters.delete(i); }
        removeItem(i);
      }
      if (radar) for (const o of [...radar.group.children]) if (blastArea(m.x, m.y, m.r).includes(o.userData.tile)) radar.group.remove(o);
      for (const [x, y, v] of m.tiles) tiles[y * W + x] = v;
      refreshBoard();
      setCounters(m);
      const [wx, wz] = tileCenter(m.x, m.y);
      const pos = new THREE.Vector3(wx, 0.8, wz);
      burst(pos, { count: 180, colors: [0xc77dff, 0x8a3ffc, 0xffffff, 0x2a2233], speed: [6, 18], life: 1.6, size: 0.45 });
      burst(pos, { count: 90, colors: [realm.cover[0], realm.cover[1]], speed: [4, 10], life: 1.4, size: 0.4 });
      // the "new mines" fly out as dark specks (purely decorative: they don't show where the mines landed)
      burst(pos, { count: 24, colors: [0x15101a], speed: [8, 14], up: 2, life: 1.3, size: 0.6 });
      const ring = new THREE.Mesh(new THREE.RingGeometry(0.8, 1.2, 40),
        new THREE.MeshBasicMaterial({ color: 0xc77dff, transparent: true, depthWrite: false, side: THREE.DoubleSide }));
      ring.rotation.x = -Math.PI / 2; ring.position.set(wx, 0.7, wz); scene.add(ring);
      let t = 0;
      effects.push((dt) => {
        t += dt; ring.scale.setScalar(1 + t * 14); ring.material.opacity = Math.max(0, 1 - t / 0.6);
        if (t > 0.6) { scene.remove(ring); disposeTree(ring); return false; }
        return true;
      });
      const v = distVol(wx, wz);
      sfx.scatter(v);
      cam.shake = Math.max(cam.shake, v * 1.4);
      for (const pid of [...m.hit, ...m.shielded]) {
        const pp = playerPos(pid);
        if (pp) floatText(m.shielded.includes(pid) ? 'SHIELDED' : 'BURIED!', m.shielded.includes(pid) ? '#7fc0ff' : '#c77dff', pp[0], pp[1] + 3.4, pp[2]);
        if (pid === myId) {
          let dx = me.x - wx, dz = me.z - wz; const d = Math.hypot(dx, dz) || 1;
          const kick = m.hit.includes(pid) ? 18 : 8;
          me.kx = (dx / d) * kick; me.kz = (dz / d) * kick; me.vy = 9;
          if (m.hit.includes(pid)) me.stun = m.stun;
        }
      }
      feed(who(m.pid), "'s scatter bomb re-buried the ground and scattered ", { text: `${m.added} new mines`, color: '#c77dff' },
        m.hit.length ? ` (caught ${m.hit.length})` : '');
      break;
    }
    case 'zap': {
      // ice beam from the shooter to where it stopped
      const y0 = (playerPos(m.pid)?.[1] ?? 0.6) + 1.2;
      const a = new THREE.Vector3(m.from[0], y0, m.from[1]), b = new THREE.Vector3(m.to[0], y0, m.to[1]);
      const len = a.distanceTo(b) || 0.01;
      const beamMat = new THREE.MeshBasicMaterial({ color: 0x9ff8ff, transparent: true, opacity: 0.95, depthWrite: false });
      const coreMat = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, depthWrite: false });
      const beam = new THREE.Group();
      const outer = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.22, len, 10, 1, true), beamMat);
      const core = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.08, len, 8), coreMat);
      beam.add(outer, core);
      beam.position.copy(a).lerp(b, 0.5);
      beam.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), b.clone().sub(a).normalize());
      scene.add(beam);
      let t = 0;
      effects.push((dt) => {
        t += dt; const k = 1 - t / 0.45;
        beamMat.opacity = Math.max(0, k * 0.95); coreMat.opacity = Math.max(0, k);
        beam.scale.set(1 + t * 2, 1, 1 + t * 2);
        if (t > 0.45) { scene.remove(beam); disposeTree(beam); return false; }
        return true;
      });
      burst(b, { count: 50, colors: [0xbff4ff, 0xffffff, 0x3ee6d6], speed: [2, 7], life: 0.9, size: 0.3, gravity: 6 });
      const v = distVol(m.from[0], m.from[1]);
      sfx.zap(v);
      if (m.target) {
        const tp = playerPos(m.target);
        if (tp) floatText(m.shielded ? 'SHIELDED' : 'FROZEN!', m.shielded ? '#7fc0ff' : '#9ff8ff', tp[0], tp[1] + 3.4, tp[2]);
        if (!m.shielded) sfx.freeze(distVol(m.to[0], m.to[1]));
        if (m.target === myId && !m.shielded) { me.stun = m.dur; me.kx = me.kz = 0; }
        const tgt = m.boss ? { text: `the ${BOSSES[bosses.get(m.target)?.kind]?.name ?? 'boss'}`, color: '#ffd23f' } : who(m.target);
        feed(who(m.pid), m.shielded ? ' zapped ' : ' froze ', tgt, m.shielded ? ", but a shield blocked it" : ` solid (${m.dur}s)`);
      } else feed(who(m.pid), "'s freeze ray missed");
      break;
    }
    case 'shock': {
      const ring = new THREE.Mesh(new THREE.TorusGeometry(1, 0.12, 8, 48),
        new THREE.MeshBasicMaterial({ color: 0xff6fb5, transparent: true, depthWrite: false }));
      ring.rotation.x = Math.PI / 2; ring.position.set(m.x, 0.9, m.z); scene.add(ring);
      const dome = new THREE.Mesh(new THREE.SphereGeometry(1, 24, 12, 0, Math.PI * 2, 0, Math.PI / 2),
        new THREE.MeshBasicMaterial({ color: 0xff6fb5, transparent: true, opacity: 0.3, depthWrite: false, side: THREE.DoubleSide }));
      dome.position.set(m.x, 0.6, m.z); scene.add(dome);
      const R = m.r * T;
      let t = 0;
      effects.push((dt) => {
        t += dt; const k = Math.min(1, t / 0.4);
        ring.scale.setScalar(0.5 + k * R); dome.scale.setScalar(0.5 + k * R);
        ring.material.opacity = 1 - k; dome.material.opacity = 0.3 * (1 - k);
        if (t > 0.4) { scene.remove(ring, dome); disposeTree(ring); disposeTree(dome); return false; }
        return true;
      });
      burst(new THREE.Vector3(m.x, 0.7, m.z), { count: 90, colors: [0xff6fb5, 0xffffff, realm.cover[0]], speed: [8, 14], up: 0.2, life: 0.8, size: 0.3 });
      const v = distVol(m.x, m.z);
      sfx.shock(v);
      cam.shake = Math.max(cam.shake, v * 0.9);
      for (const pid of [...m.hit, ...m.shielded]) {
        const pp = playerPos(pid); const sh = m.shielded.includes(pid);
        if (pp) floatText(sh ? 'SHIELDED' : 'SHOCKED!', sh ? '#7fc0ff' : '#ff6fb5', pp[0], pp[1] + 3.4, pp[2]);
        if (pid === myId) {
          let dx = me.x - m.x, dz = me.z - m.z; const d = Math.hypot(dx, dz) || 1;
          const kick = sh ? 9 : 20;
          me.kx = (dx / d) * kick; me.kz = (dz / d) * kick; me.vy = 8;
          if (!sh) me.stun = m.stun;
        }
      }
      feed(who(m.pid), ' set off a ', { text: 'Shockwave', color: ITEM_INFO.shockwave.css }, m.hit.length ? ` and stunned ${m.hit.length}` : '');
      break;
    }
    case 'blink': {
      for (const [x, z] of [m.from, m.to]) {
        burst(new THREE.Vector3(x, 1, z), { count: 60, colors: [0xa3e635, 0xffffff, 0x4fd67a], speed: [2, 6], life: 0.7, size: 0.28, gravity: -2 });
      }
      sfx.blink(Math.max(distVol(m.from[0], m.from[1]), distVol(m.to[0], m.to[1])));
      if (m.pid === myId) { me.x = m.to[0]; me.z = m.to[1]; me.kx = me.kz = 0; }
      else {
        const p = players.get(m.pid);
        if (p) { p.x = p.tx = m.to[0]; p.z = p.tz = m.to[1]; }
      }
      break;
    }
    case 'ko': {
      const pp = playerPos(m.pid);
      if (pp) {
        floatText('KNOCKED OUT', '#ff5d5d', pp[0], pp[1] + 4.2, pp[2]);
        burst(new THREE.Vector3(pp[0], pp[1] + 1, pp[2]), { count: 60, colors: [0xffffff, 0xaaaaaa], speed: [1, 4], life: 1.2, size: 0.5, gravity: -1 });
      }
      if (m.pid === myId) { koUntil = performance.now() + m.respawn * 1000; sfx.ko(); }
      if (m.by) {
        feed(who(m.by), ' knocked out ', who(m.pid), ` (+${m.reward})`);
        const bp = playerPos(m.by); if (bp) floatText(`+${m.reward} KO`, '#ffd23f', bp[0], bp[1] + 3.8, bp[2]);
      } else feed(who(m.pid), ` got knocked out (${m.penalty})`);
      if (m.lives !== null && m.lives !== undefined) {
        teamLives = m.lives; renderModeRow();
        feed({ text: `Team lives: ${m.lives}`, color: '#ff6b8a' }, m.lives ? '' : '. Out of lives!');
      }
      break;
    }
    case 'hitPlayer': {
      const tp = playerPos(m.target);
      if (tp) {
        floatText(m.shielded ? 'SHIELDED' : `-${m.dmg} HP`, m.shielded ? '#7fc0ff' : '#ff8080', tp[0], tp[1] + 3.6, tp[2]);
        burst(new THREE.Vector3(tp[0], tp[1] + 1.2, tp[2]), { count: 14, colors: [0xffffff, 0xff8080], speed: [3, 6], life: 0.4, size: 0.25 });
        sfx.hit(distVol(tp[0], tp[2]));
      }
      if (m.target === myId && !m.shielded) {
        let dx = me.x - m.x, dz = me.z - m.z; const d = Math.hypot(dx, dz) || 1;
        me.kx = (dx / d) * 12; me.kz = (dz / d) * 12; me.vy = 5;
      }
      break;
    }
    case 'respawn': {
      const p = players.get(m.pid);
      if (p) { p.hp = m.hp; drawHpBar(p.av, m.hp); }
      if (m.pid === myId) { me.x = m.x; me.z = m.z; me.kx = me.kz = 0; me.y = 2; me.hp = m.hp; koUntil = 0; }
      else if (p) { p.x = p.tx = m.x; p.z = p.tz = m.z; }
      burst(new THREE.Vector3(m.x, 1, m.z), { count: 50, colors: [0xffffff, 0x9ff8ff], speed: [2, 5], life: 0.8, size: 0.3, gravity: -2 });
      break;
    }
    case 'over':
      for (const b of bombs.values()) { scene.remove(b.mesh, b.zone); disposeTree(b.mesh); disposeTree(b.zone); }
      bombs.clear(); clearRadar();
      showAllMines(m.mines);
      showResults(m.results, m.next, m.duration);
      $('resultsTitle').textContent = m.mode === 'coop'
        ? (m.failed ? 'Out of lives. The dungeon wins!' : `Dungeon cleared! Team score ${m.team}`)
        : m.mode === 'pvp' ? 'Battle over!' : 'Field cleared!';
      if (m.failed) $('resultsSub').textContent = 'Your team was knocked out too many times. A new dungeon awaits.';
      sfx.win();
      break;
    case 'round':
      for (const p of players.values()) { p.score = 0; p.hp = maxHp; }
      applySnapshot(m.snapshot);
      if (m.spawns?.[myId]) { [me.x, me.z] = m.spawns[myId]; me.kx = me.kz = 0; me.y = 1; }
      for (const [id, [x, z]] of Object.entries(m.spawns || {})) {
        const p = players.get(id);
        if (p && id !== myId) { p.x = p.tx = x; p.z = p.tz = z; }
      }
      feed('A new field has been laid. Go!');
      break;
  }
}

// ---------------------------------------------------------------- input
// ---------------------------------------------------------------- character picker
const COLORS = ['#ff5d5d', '#4fa3ff', '#ffd23f', '#4fd67a', '#c77dff', '#ff9f43',
  '#3ee6d6', '#ff6fb5', '#a3e635', '#f8fafc', '#94a3b8', '#fb7185']; // must match server.py
const picker = { char: 'miner', color: COLORS[1], realm: 'meadow', layout: 'dungeon', mode: 'race', edit: false };
const pv = { renderer: null, scene: new THREE.Scene(), camera: new THREE.PerspectiveCamera(32, 260 / 300, 0.1, 50),
  model: null, running: false, last: 0 };
const thumb = { renderer: null, scene: new THREE.Scene(), camera: new THREE.PerspectiveCamera(30, 1, 0.1, 50), imgs: {} };

function disposeTree(o) {
  o.traverse((m) => {
    m.geometry?.dispose();
    for (const mat of [].concat(m.material || [])) { mat.map?.dispose(); mat.dispose(); }
  });
}
function addStudioLights(scene) {
  scene.add(new THREE.HemisphereLight(0xe4f3ff, 0x40362a, 1.3));
  const d = new THREE.DirectionalLight(0xffffff, 2.2); d.position.set(3, 5, 4); scene.add(d);
}

function initPicker() {
  pv.renderer = new THREE.WebGLRenderer({ canvas: $('preview'), antialias: true, alpha: true });
  pv.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  pv.renderer.setSize(260, 300, false);
  pv.renderer.toneMapping = THREE.ACESFilmicToneMapping;
  addStudioLights(pv.scene);
  const ped = new THREE.Mesh(new THREE.CylinderGeometry(1.1, 1.2, 0.3, 32), new THREE.MeshStandardMaterial({ color: 0x6cc04a }));
  ped.position.y = -0.15; pv.scene.add(ped);
  pv.camera.position.set(0, 2.1, 6.4); pv.camera.lookAt(0, 1.3, 0);

  thumb.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  thumb.renderer.setSize(128, 128, false);
  thumb.renderer.toneMapping = THREE.ACESFilmicToneMapping;
  addStudioLights(thumb.scene);
  thumb.camera.position.set(0, 2.0, 6.6); thumb.camera.lookAt(0, 1.35, 0);

  for (const def of CHARACTERS) {
    const b = document.createElement('button'); b.type = 'button'; b.title = def.name; b.dataset.id = def.id;
    const img = document.createElement('img'); img.alt = def.name; thumb.imgs[def.id] = img;
    const name = document.createElement('span'); name.textContent = def.name;
    b.append(img, name);
    b.addEventListener('click', () => { picker.char = def.id; syncPicker(false); });
    $('chars').append(b);
  }
  for (const c of COLORS) {
    const b = document.createElement('button'); b.type = 'button'; b.dataset.color = c; b.style.background = c; b.title = c;
    b.addEventListener('click', () => { picker.color = c; syncPicker(true); });
    $('colors').append(b);
  }
  const realmOpts = [...REALMS, { id: 'random', name: 'Random', blurb: 'Surprise me.',
    swatch: 'conic-gradient(#5f9e47 0 10%, #d9a85f 0 20%, #eef4f8 0 30%, #ff6a1a 0 40%, #7d818d 0 50%, #ff8cc3 0 60%, #3d7a2c 0 70%, #4fc1bd 0 80%, #2c3326 0 90%, #ff3ad0 0)' }];
  for (const r of realmOpts) {
    const b = document.createElement('button'); b.type = 'button'; b.dataset.id = r.id; b.title = r.blurb;
    const sw = document.createElement('i'); sw.style.background = r.swatch;
    const nm = document.createElement('span'); nm.textContent = r.name;
    b.append(sw, nm);
    b.addEventListener('click', () => { picker.realm = r.id; syncPicker(false); });
    $('realms').append(b);
  }
  for (const b of $('layouts').children) b.addEventListener('click', () => { picker.layout = b.dataset.id; syncPicker(false); });
  for (const b of $('modes').children) b.addEventListener('click', () => { picker.mode = b.dataset.id; syncPicker(false); });
}

function renderThumbs() {
  for (const def of CHARACTERS) {
    const c = buildCharacter(def.id, picker.color);
    c.root.rotation.y = 0.45;
    thumb.scene.add(c.root);
    thumb.renderer.render(thumb.scene, thumb.camera);
    thumb.imgs[def.id].src = thumb.renderer.domElement.toDataURL();
    thumb.scene.remove(c.root);
    disposeTree(c.root);
  }
}

function syncPicker(colorChanged) {
  for (const b of $('chars').children) b.classList.toggle('sel', b.dataset.id === picker.char);
  for (const b of $('realms').children) b.classList.toggle('sel', b.dataset.id === picker.realm);
  for (const b of $('layouts').children) b.classList.toggle('sel', b.dataset.id === picker.layout);
  for (const b of $('modes').children) b.classList.toggle('sel', b.dataset.id === picker.mode);
  const taken = new Set(picker.edit ? [...players].filter(([id]) => id !== myId).map(([, p]) => p.color) : []);
  for (const b of $('colors').children) {
    b.classList.toggle('sel', b.dataset.color === picker.color);
    b.disabled = taken.has(b.dataset.color);
  }
  const def = CHAR_BY_ID[picker.char] || CHARACTERS[0];
  $('charName').textContent = def.name;
  $('charBlurb').textContent = def.blurb;
  const rot = pv.model ? pv.model.root.rotation.y : 0.4;
  if (pv.model) { pv.scene.remove(pv.model.root); disposeTree(pv.model.root); }
  pv.model = buildCharacter(def.id, picker.color);
  pv.model.root.rotation.y = rot;
  pv.scene.add(pv.model.root);
  if (colorChanged) renderThumbs();
}

function previewLoop(now) {
  if ($('join').hidden) { pv.running = false; return; }
  requestAnimationFrame(previewLoop);
  const dt = Math.min(0.05, (now - pv.last) / 1000); pv.last = now;
  if (pv.model) {
    pv.model.root.rotation.y += dt * 0.9;
    pv.model.tick?.(now / 1000, 0);
  }
  pv.renderer.render(pv.scene, pv.camera);
}

function openPicker(edit) {
  picker.edit = edit;
  $('roomField').hidden = edit; $('realmField').hidden = edit; $('rules').hidden = edit; $('cancelBtn').hidden = !edit;
  $('lobby').hidden = edit;
  setTimeout(refreshLobby, 0);
  $('joinBtn').textContent = edit ? 'Save' : 'Enter the field';
  if (edit) {
    const p = players.get(myId);
    if (p) { picker.char = p.char; picker.color = p.color; $('name').value = p.name; }
  }
  $('joinError').hidden = true;
  $('join').hidden = false;
  keys.clear();
  syncPicker(true);
  if (!pv.running) { pv.running = true; pv.last = performance.now(); requestAnimationFrame(previewLoop); }
}
function closePicker() {
  $('join').hidden = true;
  document.activeElement?.blur();
}

// ---------------------------------------------------------------- lobby (open rooms)
const lobby = { rooms: [], timer: 0 };
const MODE_NAMES = { race: 'Race', pvp: 'PvP', coop: 'Co-op' };
const LAYOUT_NAMES = { dungeon: 'Dungeon', field: 'Open field' };

async function refreshLobby() {
  clearTimeout(lobby.timer);
  if ($('join').hidden || picker.edit) return;
  try {
    const r = await fetch('/api/rooms', { cache: 'no-store' });
    lobby.rooms = (await r.json()).rooms || [];
  } catch { lobby.rooms = []; }
  renderLobby();
  lobby.timer = setTimeout(refreshLobby, 3000);
}

function renderLobby() {
  const list = $('roomList'), mk = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; };
  const n = lobby.rooms.length;
  $('lobbyCount').textContent = n ? `${n} room${n > 1 ? 's' : ''} · ${lobby.rooms.reduce((s, r) => s + r.humans, 0)} playing` : '';
  if (!n) { list.replaceChildren(mk('div', 'empty', 'No open rooms right now. Type a room name below to start one, and friends will see it here.')); updateRoomNote(); return; }
  list.replaceChildren(...lobby.rooms.map((r) => {
    const full = r.humans + r.bots >= r.max;
    const card = mk('div', `roomCard${full ? ' full' : ''}`);
    const top = mk('div', 'top');
    top.append(mk('span', 'nm', r.name), mk('span', 'cnt', `${r.humans}${r.bots ? ` + ${r.bots} bot${r.bots > 1 ? 's' : ''}` : ''} / ${r.max}`));
    const chips = mk('div', 'chips');
    chips.append(mk('span', r.mode, MODE_NAMES[r.mode] || r.mode), mk('span', '', LAYOUT_NAMES[r.layout] || r.layout),
      mk('span', '', REALM_BY_ID[r.realm]?.name || r.realm));
    if (r.bosses) chips.append(mk('span', 'boss', r.bosses > 1 ? `${r.bosses} bosses` : 'boss out'));
    if (r.lives !== null && r.lives !== undefined) chips.append(mk('span', 'coop', `♥ ${r.lives}`));
    const who = mk('div', 'who');
    for (const p of r.players) {
      const s = mk('span'); const dot = mk('i'); dot.style.background = p.color;
      s.append(dot, `${p.name}${p.bot ? ' (bot)' : ''}`); who.append(s);
    }
    const prog = mk('div', 'prog'); const bar = mk('b'); bar.style.width = `${Math.round(r.progress * 100)}%`; prog.append(bar);
    const foot = mk('div', 'foot');
    const status = r.state === 'over' ? 'Round over, next one starting' : r.progress ? `${Math.round(r.progress * 100)}% cleared · ${Math.floor(r.age / 60)}m in` : 'Round just started';
    const btn = mk('button', '', full ? 'Full' : 'Join'); btn.type = 'button'; btn.disabled = full;
    btn.addEventListener('click', () => { $('room').value = r.name; updateRoomNote(); $('joinForm').requestSubmit(); });
    foot.append(mk('span', '', status), btn);
    card.append(top, chips, who, prog, foot);
    return card;
  }));
  updateRoomNote();
}

// typing the name of an open room means you'll join it with ITS mode, map and realm
function updateRoomNote() {
  const name = ($('room').value.trim() || 'lobby').toLowerCase();
  const r = lobby.rooms.find((x) => x.name === name);
  $('roomNote').hidden = !r || picker.edit;
  $('realmField').classList.toggle('dim', !!r && !picker.edit);
  if (r) $('roomNote').textContent = `You'll join the open room “${r.name}”: ${MODE_NAMES[r.mode]} · ${LAYOUT_NAMES[r.layout]} · ${REALM_BY_ID[r.realm]?.name || r.realm}. The choices below only apply to new rooms.`;
}
$('room').addEventListener('input', updateRoomNote);

$('joinForm').addEventListener('submit', (e) => {
  e.preventDefault();
  audio();
  const name = $('name').value.trim() || 'Sweeper';
  const room = $('room').value.trim() || 'lobby';
  try { localStorage.setItem('mf3d', JSON.stringify({ name, room, char: picker.char, color: picker.color, realm: picker.realm, layout: picker.layout, mode: picker.mode })); } catch {}
  if (picker.edit) {
    send({ t: 'look', name, char: picker.char, color: picker.color });
    closePicker();
    return;
  }
  $('joinError').hidden = true;
  connect(name, room);
});
$('cancelBtn').addEventListener('click', closePicker);
$('lookBtn').addEventListener('click', (e) => { e.currentTarget.blur(); openPicker(true); });

initPicker();
try {
  const saved = JSON.parse(localStorage.getItem('mf3d') || '{}');
  if (saved.name) $('name').value = saved.name;
  if (CHAR_BY_ID[saved.char]) picker.char = saved.char;
  if (COLORS.includes(saved.color)) picker.color = saved.color;
  const okRealm = (r) => r === 'random' || REALM_BY_ID[r];
  if (okRealm(saved.realm)) picker.realm = saved.realm;
  const qs = new URLSearchParams(location.search);
  $('room').value = qs.get('room') || saved.room || '';
  if (qs.get('name')) $('name').value = qs.get('name');
  if (CHAR_BY_ID[qs.get('char')]) picker.char = qs.get('char');
  if (okRealm(qs.get('realm'))) picker.realm = qs.get('realm');
  const okLayout = (l) => l === 'dungeon' || l === 'field';
  if (okLayout(saved.layout)) picker.layout = saved.layout;
  if (okLayout(qs.get('layout'))) picker.layout = qs.get('layout');
  const okMode = (m) => ['race', 'pvp', 'coop'].includes(m);
  if (okMode(saved.mode)) picker.mode = saved.mode;
  if (okMode(qs.get('mode'))) picker.mode = qs.get('mode');
  if (qs.has('autojoin')) setTimeout(() => $('joinForm').requestSubmit(), 0);
} catch {}
openPicker(false);

const typing = () => document.activeElement?.tagName === 'INPUT';
addEventListener('keydown', (e) => {
  if (!$('join').hidden) { if (e.code === 'Escape' && picker.edit) closePicker(); return; }
  if (typing()) return;
  keys.add(e.code);
  if (e.code === 'Space') e.preventDefault();
  if (e.code === 'KeyF') act('flag');
  if (e.code === 'KeyG') useItem();
  if (e.code === 'KeyR') attack();
});
addEventListener('keyup', (e) => keys.delete(e.code));
addEventListener('blur', () => keys.clear());

const canvas = renderer.domElement;
canvas.addEventListener('contextmenu', (e) => e.preventDefault());
canvas.addEventListener('mousemove', (e) => {
  mouse.x = (e.clientX / innerWidth) * 2 - 1; mouse.y = -(e.clientY / innerHeight) * 2 + 1; mouse.has = true;
  if (mouse.drag) { cam.yaw -= (e.clientX - mouse.lastX) * 0.006; mouse.lastX = e.clientX; }
});
canvas.addEventListener('mousedown', (e) => {
  audio();
  if (e.button === 0) act('dig');
  else if (e.button === 2) act('flag');
  else if (e.button === 1) { e.preventDefault(); mouse.drag = true; mouse.lastX = e.clientX; }
});
addEventListener('mouseup', (e) => { if (e.button === 1) mouse.drag = false; });
canvas.addEventListener('wheel', (e) => {
  e.preventDefault();
  cam.dist = THREE.MathUtils.clamp(cam.dist * (1 + e.deltaY * 0.001), 7, 45);
}, { passive: false });

let lastTooFar = 0;
function act(kind, target = hover) {
  if (!$('join').hidden || !target || roundState !== 'playing' || me.stun > 0) return;
  if (!target.inReach) {
    if (performance.now() - lastTooFar > 1500) { lastTooFar = performance.now(); feed('Too far away. Walk next to that tile first.'); }
    return;
  }
  const i = target.y * W + target.x;
  if (kind === 'dig' && flags.get(i)?.pid === myId) return;
  if (kind === 'flag' && tiles[i] !== -2) return;
  send({ t: kind, x: target.x, y: target.y });
}

// The tile the touch Dig / Flag buttons act on: the tapped tile if it's in reach and still useful,
// else the hidden tile you're facing, else the hidden neighbour closest to your facing direction.
function digTarget(forFlag = false) {
  if (roundState !== 'playing' || me.stun > 0 || !floor.length) return null;
  const [px, py] = tileOf(me.x, me.z);
  const inReach = (x, y) => Math.max(Math.abs(px - x), Math.abs(py - y)) <= REACH;
  const useful = (x, y) => {
    if (isWall(x, y)) return false;
    const i = y * W + x, v = tiles[i], f = flags.get(i);
    if (forFlag) return v === -2 && (!f || f.pid === myId);
    return v === -2 && f?.pid !== myId;
  };
  if (touchAim && inReach(...touchAim) && (useful(...touchAim) || (!forFlag && tiles[touchAim[1] * W + touchAim[0]] > 0)))
    return { x: touchAim[0], y: touchAim[1], inReach: true };
  const fx = Math.sin(me.r), fz = Math.cos(me.r);     // facing direction (world x/z = tile x/y)
  let best = null;
  for (let dy = -REACH; dy <= REACH; dy++) for (let dx = -REACH; dx <= REACH; dx++) {
    const x = px + dx, y = py + dy;
    if (!useful(x, y)) continue;
    const d = Math.hypot(dx, dy);
    const score = d ? (dx * fx + dy * fz) / d : -0.5;   // own tile ranks after anything in front
    if (!best || score > best.score) best = { x, y, inReach: true, score };
  }
  return best;
}

// ---------------------------------------------------------------- touch controls
// Left: a virtual joystick. View: tap a tile next to you to dig it (or flag it in flag mode), hold to
// flag, tap a farther tile to aim power-ups at it; drag to turn the camera, pinch to zoom.
let touchAim = null, jumpReq = false;
const joy = { id: null, x: 0, y: 0, cx: 0, cy: 0 };
if (IS_TOUCH) {
  $('touch').hidden = false;
  setTimeout(() => $('touchHint').classList.add('gone'), 9000);
  const stick = $('stick'), knob = $('knob'), R = 50;
  const setKnob = () => { knob.style.transform = `translate(${joy.x * R}px, ${joy.y * R}px)`; };
  stick.addEventListener('pointerdown', (e) => {
    e.preventDefault(); audio();
    stick.setPointerCapture(e.pointerId);
    const r = stick.getBoundingClientRect();
    Object.assign(joy, { id: e.pointerId, cx: r.left + r.width / 2, cy: r.top + r.height / 2 });
  });
  stick.addEventListener('pointermove', (e) => {
    if (e.pointerId !== joy.id) return;
    let dx = (e.clientX - joy.cx) / R, dy = (e.clientY - joy.cy) / R;
    const l = Math.hypot(dx, dy); if (l > 1) { dx /= l; dy /= l; }
    joy.x = dx; joy.y = dy; setKnob();
  });
  const release = (e) => { if (e.pointerId === joy.id) { Object.assign(joy, { id: null, x: 0, y: 0 }); setKnob(); } };
  stick.addEventListener('pointerup', release); stick.addEventListener('pointercancel', release);

  const press = (id, fn) => $(id).addEventListener('pointerdown', (e) => { e.preventDefault(); e.stopPropagation(); audio(); fn(); });
  press('tAttack', () => attack());
  press('tUse', () => useItem());
  press('tJump', () => { jumpReq = true; });
  press('tFlag', () => { const t = digTarget(true); if (t) act('flag', t); else nag('Nothing to flag here. Walk next to a covered tile.'); });
  // Dig: digs the marked tile; hold it to keep digging as you walk
  let digTimer = 0;
  const digOnce = () => { const t = digTarget(); if (t) act('dig', t); else nag('Nothing to dig here. Walk next to a covered tile.'); };
  const dig = $('tDig');
  dig.addEventListener('pointerdown', (e) => {
    e.preventDefault(); e.stopPropagation(); audio();
    dig.setPointerCapture(e.pointerId);
    digOnce();
    clearInterval(digTimer); digTimer = setInterval(digOnce, 320);
  });
  for (const ev of ['pointerup', 'pointercancel', 'lostpointercapture']) dig.addEventListener(ev, () => clearInterval(digTimer));

  // the view: taps, long-press, one-finger drag to turn, two-finger pinch to zoom
  const touches = new Map();
  let longTimer = 0, gesture = null;
  const ndc = (x, y) => [(x / innerWidth) * 2 - 1, -(y / innerHeight) * 2 + 1];
  const aimAt = (x, y) => { const t = pickTile(...ndc(x, y)); touchAim = t && !isWall(t[0], t[1]) ? t : null; updateHover(); };
  canvas.addEventListener('touchstart', (e) => {
    e.preventDefault(); audio();
    for (const t of e.changedTouches) touches.set(t.identifier, { x0: t.clientX, y0: t.clientY, x: t.clientX, y: t.clientY, t0: performance.now(), moved: false });
    clearTimeout(longTimer);
    if (touches.size === 1) {
      const [t] = touches.values();
      longTimer = setTimeout(() => {   // hold = flag
        if (!t.moved && touches.size === 1) { aimAt(t.x, t.y); t.used = true; if (hover?.inReach) act('flag'); navigator.vibrate?.(25); }
      }, 450);
      gesture = null;
    } else if (touches.size === 2) {
      const [a, b] = touches.values();
      gesture = { d: Math.hypot(a.x - b.x, a.y - b.y), dist: cam.dist };
    }
  }, { passive: false });
  canvas.addEventListener('touchmove', (e) => {
    e.preventDefault();
    for (const t of e.changedTouches) {
      const s = touches.get(t.identifier); if (!s) continue;
      const dx = t.clientX - s.x;
      if (Math.hypot(t.clientX - s.x0, t.clientY - s.y0) > 12) s.moved = true;
      if (touches.size === 1 && s.moved) cam.yaw -= dx * 0.008;    // drag to turn the camera
      s.x = t.clientX; s.y = t.clientY;
    }
    if (touches.size === 2 && gesture) {
      const [a, b] = touches.values();
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      cam.dist = THREE.MathUtils.clamp(gesture.dist * gesture.d / Math.max(20, d), 7, 45);
    }
  }, { passive: false });
  const end = (e) => {
    e.preventDefault();
    for (const t of e.changedTouches) {
      const s = touches.get(t.identifier); touches.delete(t.identifier);
      if (!s || s.moved || s.used || gesture || performance.now() - s.t0 > 400) continue;
      // a tap: aim at the tile; dig/flag it if it's within reach
      aimAt(s.x, s.y);
      if (hover?.inReach) act('dig');
    }
    clearTimeout(longTimer);
    if (!touches.size) gesture = null;
  };
  canvas.addEventListener('touchend', end, { passive: false });
  canvas.addEventListener('touchcancel', end, { passive: false });
  // don't let the page itself scroll or zoom while playing
  document.addEventListener('gesturestart', (e) => e.preventDefault());
}

let lastSwing = 0;
function attack() {
  if (!$('join').hidden || roundState !== 'playing' || me.stun > 0 || performance.now() - lastSwing < 450) return;
  lastSwing = performance.now();
  swingFx(myId); sfx.whoosh();
  send({ t: 'attack' });
}

const useRange = (kind) => ({ scatter: throwRange, freeze: freezeRange, blink: blinkRange }[kind] ?? 0);
function inUseRange(kind, tx, ty) {
  const [px, py] = tileOf(me.x, me.z);
  return Math.max(Math.abs(px - tx), Math.abs(py - ty)) <= useRange(kind);
}
function nag(text) {
  if (performance.now() - lastTooFar > 1500) { lastTooFar = performance.now(); feed(text); }
}
function useItem() {
  if (!$('join').hidden || roundState !== 'playing' || me.stun > 0) return;
  const kind = heldKind(me.fx);
  if (!kind) return nag('You are not holding anything. Dig up power-ups and walk onto them!');
  if (kind === 'shockwave') return send({ t: 'use' });
  if (!hover) return nag(IS_TOUCH ? 'Tap a tile to aim first, then press Use.' : 'Point at a tile to aim.');
  if (!inUseRange(kind, hover.x, hover.y)) return nag(`Too far for the ${ITEM_INFO[kind].name} (max ${useRange(kind)} tiles).`);
  send({ t: 'use', x: hover.x, y: hover.y });
}

// ---------------------------------------------------------------- picking
const ray = new THREE.Raycaster();
const planeTop = new THREE.Plane(new THREE.Vector3(0, 1, 0), -0.6);
const planeLow = new THREE.Plane(new THREE.Vector3(0, 1, 0), -0.1);
const hit = new THREE.Vector3();

// the tile under a screen point (normalised device coords): covers first, then revealed slabs
function pickTile(nx, ny) {
  ray.setFromCamera(new THREE.Vector2(nx, ny), camera);
  let tx, ty;
  if (ray.ray.intersectPlane(planeTop, hit)) {
    [tx, ty] = tileOf(hit.x, hit.z);
    if (!inBoard(tx, ty) || tiles[ty * W + tx] !== -2) {
      if (ray.ray.intersectPlane(planeLow, hit)) [tx, ty] = tileOf(hit.x, hit.z);
    }
  }
  return tx === undefined ? null : [tx, ty];
}

function updateHover() {
  hover = null;
  if (!worldBuilt) return;
  // on touch the aim is a tile you tapped (it stays put while the camera moves); with a mouse it's
  // whatever is under the cursor
  const t = IS_TOUCH ? touchAim : (mouse.has ? pickTile(mouse.x, mouse.y) : null);
  if (!t || isWall(t[0], t[1])) { highlight.visible = false; return; }
  const [tx, ty] = t;
  const [px, py] = tileOf(me.x, me.z);
  const inReach = Math.max(Math.abs(px - tx), Math.abs(py - ty)) <= REACH && roundState === 'playing' && me.stun <= 0;
  hover = { x: tx, y: ty, inReach };
  const [wx, wz] = tileCenter(tx, ty);
  highlight.position.set(wx, tiles[ty * W + tx] === -2 ? 0.62 : 0.13, wz);
  highlight.material.color.set(inReach ? 0xffffff : 0xff5d5d);
  highlight.material.opacity = inReach ? 0.95 : 0.45;
  highlight.visible = true;
}

// ---------------------------------------------------------------- minimap
// a small top-down map: walls dark, hidden tiles in the realm's cover colour, revealed tiles light,
// craters red, items as dots, players as coloured dots (you with a white ring)
const minimap = { dirty: true, last: 0, base: null };
function drawMinimap(now) {
  const cv = $('minimap'); if (!cv || !floor.length) return;
  if (now - minimap.last < 200 && !minimap.dirty) return;
  minimap.last = now;
  const S = cv.width / W, g = cv.getContext('2d');
  if (minimap.dirty) {
    // board layer, redrawn only when tiles change
    const b = minimap.base || (minimap.base = document.createElement('canvas'));
    b.width = cv.width; b.height = cv.height;
    const bg = b.getContext('2d');
    bg.fillStyle = layoutKind === 'dungeon' ? '#141a24' : '#' + new THREE.Color(realm.ground).getHexString();
    bg.fillRect(0, 0, b.width, b.height);
    const hidden = '#' + new THREE.Color(realm.cover[0]).getHexString(), shown = '#' + new THREE.Color(realm.slab[0]).getHexString();
    for (let i = 0; i < W * H; i++) {
      const v = tiles[i]; if (v === -3) continue;
      bg.fillStyle = v === -2 ? hidden : v === -1 ? '#d23b3b' : shown;
      bg.fillRect((i % W) * S, Math.floor(i / W) * S, Math.ceil(S), Math.ceil(S));
    }
    minimap.dirty = false;
  }
  g.drawImage(minimap.base, 0, 0);
  for (const [i, it] of items) {
    g.fillStyle = ITEM_INFO[it.kind]?.css || '#fff';
    g.fillRect((i % W) * S + S * 0.2, Math.floor(i / W) * S + S * 0.2, S * 0.6, S * 0.6);
  }
  const dot = (wx, wz, color, ring) => {
    const x = (wx / T + W / 2) * S, y = (wz / T + H / 2) * S;
    g.fillStyle = color; g.beginPath(); g.arc(x, y, S * 1.1, 0, 7); g.fill();
    if (ring) { g.strokeStyle = '#fff'; g.lineWidth = 1.5; g.beginPath(); g.arc(x, y, S * 1.6, 0, 7); g.stroke(); }
  };
  for (const b of bosses.values()) {
    if (Number.isNaN(b.x)) continue;
    const x = (b.x / T + W / 2) * S, y = (b.z / T + H / 2) * S;
    g.fillStyle = '#ff3b3b'; g.beginPath(); g.arc(x, y, S * 2, 0, 7); g.fill();
    g.strokeStyle = '#1a0505'; g.lineWidth = 1.5; g.stroke();
  }
  for (const [id, p] of players) if (id !== myId && !Number.isNaN(p.x)) dot(p.x, p.z, p.color, false);
  const mineP = players.get(myId); if (mineP) dot(me.x, me.z, mineP.color, true);
}

// ---------------------------------------------------------------- main loop
function lerpAngle(a, b, t) {
  const d = ((((b - a + Math.PI) % (Math.PI * 2)) + Math.PI * 2) % (Math.PI * 2)) - Math.PI;
  return a + d * t;
}

let sendTimer = 0, last = performance.now(), elapsed = 0;
function frame(now) {
  requestAnimationFrame(frame);
  const dt = Math.min(0.05, (now - last) / 1000); last = now; elapsed += dt;
  if (!worldBuilt || !myId) { renderer.render(scene, camera); return; }

  // --- local movement
  if (keys.has('KeyQ')) cam.yaw += dt * 2.2;
  if (keys.has('KeyE')) cam.yaw -= dt * 2.2;
  const fx = -Math.sin(cam.yaw), fz = -Math.cos(cam.yaw), rx = Math.cos(cam.yaw), rz = -Math.sin(cam.yaw);
  let mf = 0, mr = 0;
  if (keys.has('KeyW') || keys.has('ArrowUp')) mf += 1;
  if (keys.has('KeyS') || keys.has('ArrowDown')) mf -= 1;
  if (keys.has('KeyD') || keys.has('ArrowRight')) mr += 1;
  if (keys.has('KeyA') || keys.has('ArrowLeft')) mr -= 1;
  const joyMag = Math.hypot(joy.x, joy.y);
  if (joyMag > 0.12) { mf = -joy.y; mr = joy.x; }      // the touch stick is analogue; full tilt sprints
  const stunned = me.stun > 0;
  if (stunned) me.stun = Math.max(0, me.stun - dt);
  let mx = fx * mf + rx * mr, mz = fz * mf + rz * mr;
  const len = Math.hypot(mx, mz);
  let speed = 0;
  if (len > 0 && !stunned) {
    const sprint = keys.has('ShiftLeft') || keys.has('ShiftRight') || joyMag > 0.95;
    speed = (sprint ? 11 : 7) * (me.fx & 2 ? bootsSpeed : 1) * (joyMag > 0.12 ? Math.min(1, joyMag * 1.25) : 1);
    mx /= len; mz /= len;
    me.r = lerpAngle(me.r, Math.atan2(mx, mz), 1 - Math.exp(-14 * dt));
  } else { mx = mz = 0; }
  // move one axis at a time so you slide along dungeon walls instead of sticking to them
  const nx = me.x + (mx * speed + me.kx) * dt, nz = me.z + (mz * speed + me.kz) * dt;
  if (!solidAt(nx, me.z)) me.x = nx; else me.kx = 0;
  if (!solidAt(me.x, nz)) me.z = nz; else me.kz = 0;
  const damp = Math.exp(-3.5 * dt); me.kx *= damp; me.kz *= damp;
  const lim = W * T / 2 + 5;
  me.x = THREE.MathUtils.clamp(me.x, -lim, lim); me.z = THREE.MathUtils.clamp(me.z, -lim, lim);

  const ground = groundAt(me.x, me.z);
  if ((keys.has('Space') || jumpReq) && !stunned && me.y <= ground + 0.01) me.vy = 8.5;
  jumpReq = false;
  me.vy -= 25 * realm.gravity * dt; me.y += me.vy * dt;
  if (me.y <= ground) { me.y = ground; me.vy = 0; }

  const mine = players.get(myId);
  if (mine) {
    mine.av.group.position.set(me.x, me.y, me.z);
    mine.av.group.rotation.y = stunned && !(me.fx & 8) && me.hp > 0 ? mine.av.group.rotation.y + dt * 10 : me.r;
    mine.hp = me.hp;
    animateAvatar(me, mine.av, speed, dt, stunned);
  }

  sendTimer += dt;
  if (sendTimer > 1 / 15) { sendTimer = 0; send({ t: 'move', x: +me.x.toFixed(2), z: +me.z.toFixed(2), r: +me.r.toFixed(2) }); }

  // --- remote players
  const k = 1 - Math.exp(-12 * dt);
  for (const [id, p] of players) {
    if (id === myId || Number.isNaN(p.x)) continue;
    const ox = p.x, oz = p.z;
    p.x += (p.tx - p.x) * k; p.z += (p.tz - p.z) * k;
    p.r = lerpAngle(p.r, p.tr, k);
    const g = groundAt(p.x, p.z); p.y += (g - p.y) * Math.min(1, dt * 20);
    const sp = Math.hypot(p.x - ox, p.z - oz) / Math.max(dt, 1e-4);
    p.av.group.position.set(p.x, p.y, p.z);
    p.av.group.rotation.y = p.stun > 0 && !(p.fx & 8) && p.hp > 0 ? p.av.group.rotation.y + dt * 10 : p.r;
    animateAvatar(p, p.av, sp, dt, p.stun > 0);
  }

  // --- world animation
  for (const [i, f] of flags) {
    f.mesh.userData.cloth.rotation.y = Math.sin(elapsed * 3 + i) * 0.35;
    if (f.mesh.userData.pop < 1) { f.mesh.userData.pop = Math.min(1, f.mesh.userData.pop + dt * 5); f.mesh.scale.setScalar(0.3 + 0.7 * f.mesh.userData.pop); }
  }
  const blink = Math.sin(elapsed * 6) > 0;
  for (const c of craters.values()) c.userData.led.visible = blink;
  for (const fn of worldTicks) fn(dt, elapsed, me);
  updateBosses(dt);
  for (const it of items.values()) {
    const u = it.mesh.userData;
    if (u.pop < 1) { u.pop = Math.min(1, u.pop + dt * 3); it.mesh.scale.setScalar(u.pop); }
    u.model.rotation.y += dt * 1.8;
    u.model.position.y = 1.0 + Math.sin(elapsed * 2.5 + u.seed) * 0.15;
  }
  if (radar) {
    const left = (radar.until - performance.now()) / 1000;
    if (left <= 0) clearRadar();
    else radar.mat.opacity = (left < 1.5 ? left / 1.5 : 1) * (0.55 + Math.sin(elapsed * 6) * 0.2);
  }
  for (let i = effects.length - 1; i >= 0; i--) if (!effects[i](dt)) effects.splice(i, 1);

  // --- camera
  const d = cam.dist;
  const target = new THREE.Vector3(me.x, me.y + 1.2, me.z);
  const want = new THREE.Vector3(
    me.x + Math.sin(cam.yaw) * Math.cos(cam.pitch) * d,
    me.y + Math.sin(cam.pitch) * d,
    me.z + Math.cos(cam.yaw) * Math.cos(cam.pitch) * d);
  camera.position.lerp(want, 1 - Math.exp(-8 * dt));
  if (cam.shake > 0) {
    camera.position.x += (Math.random() - 0.5) * cam.shake;
    camera.position.y += (Math.random() - 0.5) * cam.shake;
    cam.shake = Math.max(0, cam.shake - dt * 2.5);
  }
  camera.lookAt(target);
  sun.position.set(me.x + 30, 60, me.z + 18); sun.target.position.set(me.x, 0, me.z); sun.target.updateMatrixWorld();

  updateHover();
  const [ptx, pty] = tileOf(me.x, me.z);
  reachZone.visible = inBoard(ptx, pty) && roundState === 'playing';
  if (reachZone.visible) {
    const [zx, zz] = tileCenter(ptx, pty);
    reachZone.position.set(zx, 0.64, zz);
    reachZone.material.color.set(me.stun > 0 ? 0xff5d5d : 0xfff3a0);
  }
  // scatter-bomb aim: the 5x5 area it would re-bury, purple in range, red when too far
  const hk = roundState === 'playing' && me.stun <= 0 ? heldKind(me.fx) : '';
  const aimOk = hover && hk && inUseRange(hk, hover.x, hover.y);
  const pulse = 0.65 + Math.sin(elapsed * 8) * 0.25;
  blastZone.visible = hk === 'scatter' && !!hover;
  blinkMark.visible = hk === 'blink' && !!hover;
  for (const z of [blastZone, blinkMark]) {
    if (!z.visible) continue;
    const [bx, bz] = tileCenter(hover.x, hover.y);
    z.position.set(bx, (tiles[hover.y * W + hover.x] === -2 ? 0.67 : 0.17), bz);
    z.material.color.set(aimOk ? ITEM_INFO[hk].color : 0xff5d5d);
    z.material.opacity = aimOk ? pulse : 0.35;
  }
  aimLine.visible = hk === 'freeze' && !!hover;
  if (aimLine.visible) {
    // the beam runs the full range in the aimed direction
    const [hx, hz] = tileCenter(hover.x, hover.y);
    let dx = hx - me.x, dz = hz - me.z; const d = Math.hypot(dx, dz) || 1; dx /= d; dz /= d;
    const L = freezeRange * T;
    aimLine.scale.z = L;
    aimLine.position.set(me.x + dx * L / 2, me.y + 1.2, me.z + dz * L / 2);
    aimLine.rotation.set(0, Math.atan2(dx, dz), 0);
    aimLine.material.color.set(aimOk ? 0x3ee6d6 : 0xff5d5d);
    aimLine.material.opacity = aimOk ? 0.35 + pulse * 0.3 : 0.25;
  }
  // touch: always show which tile the Dig button will dig
  const dt2 = IS_TOUCH ? digTarget() : null;
  digMark.visible = !!dt2;
  if (dt2) {
    const [mx2, mz2] = tileCenter(dt2.x, dt2.y);
    digMark.position.set(mx2, tiles[dt2.y * W + dt2.x] === -2 ? 0.66 : 0.16, mz2);
    digMark.material.opacity = 0.7 + Math.sin(elapsed * 7) * 0.3;
    digMark.scale.setScalar(1 + Math.sin(elapsed * 7) * 0.04);
  }
  shockRing.visible = hk === 'shockwave';
  if (shockRing.visible) { shockRing.position.set(me.x, me.y + 0.08, me.z); shockRing.material.opacity = pulse * 0.8; }

  const secs = (until) => Math.max(0, Math.ceil((until - performance.now()) / 1000));
  const held = heldKind(me.fx);
  $('invHeld').hidden = !held;
  if (IS_TOUCH) {   // the Use button glows in the held item's colour
    $('tUse').classList.toggle('held', !!held);
    if (held) $('tUse').style.setProperty('--held', ITEM_INFO[held].css);
  }
  if (held) {
    $('invHeldDot').style.setProperty('--c', ITEM_INFO[held].css);
    $('invHeldName').textContent = ITEM_INFO[held].name;
    $('invHeldHint').textContent = ITEM_INFO[held].hint;
  }
  $('invShield').hidden = !(me.fx & 1);
  $('invBoots').hidden = !(me.fx & 2); $('bootsLeft').textContent = secs(bootsUntil);
  $('invGold').hidden = !(me.fx & 4); $('goldLeft').textContent = secs(goldUntil);
  $('invRadar').hidden = !radar; $('radarLeft').textContent = radar ? secs(radar.until) : 0;
  $('inventory').hidden = !(me.fx & 0xf7) && !radar;
  $('stun').hidden = !(me.stun > 0);
  const koLeft = Math.max(0, Math.ceil((koUntil - performance.now()) / 1000));
  $('stun').textContent = me.hp === 0 ? `KNOCKED OUT · back in ${koLeft}` : me.fx & 8 ? 'FROZEN' : 'STUNNED';
  $('stun').classList.toggle('ko', me.hp === 0);
  // your own health in the HUD
  const hk2 = Math.max(0, Math.min(1, me.hp / maxHp));
  $('hpFill').style.width = `${hk2 * 100}%`;
  $('hpFill').style.background = hk2 > 0.6 ? '#4fd67a' : hk2 > 0.3 ? '#ffd23f' : '#ff5d5d';
  $('hpText').textContent = `${me.hp} / ${maxHp}`;
  drawMinimap(now);
  $('stun').classList.toggle('frozen', !!(me.fx & 8));
  if (roundState === 'over') $('nextIn').textContent = Math.max(0, Math.ceil((overEndsAt - performance.now()) / 1000));

  renderer.render(scene, camera);
}
requestAnimationFrame(frame);
