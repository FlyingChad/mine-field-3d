'use strict';
const $ = (id) => document.getElementById(id);
const el = (tag, props = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === 'class') e.className = v;
    else if (k === 'style') e.style.cssText = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null && v !== false) e.setAttribute(k, v === true ? '' : v);
  }
  for (const k of kids.flat()) if (k !== null && k !== undefined && k !== false) e.append(k);
  return e;
};
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const SERIES = ['--s1', '--s2', '--s3', '--s4', '--s5', '--s6'].map(css);
const fmt = (v, d = 1) => (v === null || v === undefined || Number.isNaN(v) ? '–' : Number(v).toFixed(d));

const S = {
  schema: [], defaults: {}, cfg: null, state: 'idle', info: {}, history: [], models: [], configs: [],
  runs: [], rooms: [], characters: [], difficulties: [], viewing: null, picked: new Set(),
};

// ------------------------------------------------------------------ socket
let ws;
function connect() {
  ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/lab/ws`);
  ws.onmessage = (e) => handle(JSON.parse(e.data));
  ws.onclose = () => { setStatus('disconnected'); setTimeout(connect, 2000); };
}
const send = (m) => ws && ws.readyState === 1 && ws.send(JSON.stringify(m));

function toast(text, err = false, detail = null) {
  const t = el('div', { class: 'toast' + (err ? ' err' : ''), onclick: () => t.remove() }, text);
  if (detail) t.append(el('pre', {}, detail));
  $('toasts').append(t);
  setTimeout(() => t.remove(), err ? 15000 : 4000);
}

function handle(m) {
  switch (m.t) {
    case 'hello':
      Object.assign(S, { schema: m.schema, defaults: m.defaults, state: m.state, info: m.info || {}, cfg: m.cfg,
        history: m.history || [], models: m.models, configs: m.configs, runs: m.runs, rooms: m.rooms,
        characters: m.characters, difficulties: m.difficulties });
      $('device').textContent = m.cuda ? `GPU: ${m.gpu}` : 'GPU not available, training on CPU';
      buildForm(); fillForm(S.cfg || S.defaults);
      renderAll();
      if (location.hash === '#watch' && S.history.length) startWatch('run');
      // lab.html#watch=modelA,modelB opens straight into watching saved models
      if (location.hash.startsWith('#watch=')) {
        S.picked = new Set(decodeURIComponent(location.hash.slice(7)).split(',').filter((n) => S.models.some((m) => m.name === n)));
        if (S.picked.size) { renderWatchModels(); startWatch('models'); }
      }
      break;
    case 'status':
      S.state = m.state; S.info = m.info || S.info; if (m.cfg) S.cfg = m.cfg;
      if (m.cfg && S.state !== 'stopped') fillForm(m.cfg);
      renderStatus();
      break;
    case 'reset':
      S.history = []; S.viewing = null; $('runSel').value = ''; renderProgress();
      break;
    case 'gen':
      S.history.push(m);
      if (!S.viewing) renderProgress();
      break;
    case 'models':
      S.models = m.models; renderModels(); if (m.toast) toast(m.toast);
      break;
    case 'configs':
      S.configs = m.configs; renderPresets(); if (m.toast) toast(m.toast);
      break;
    case 'rooms':
      S.rooms = m.rooms; renderRooms();
      break;
    case 'run':
      S.viewing = m; renderProgress();
      break;
    case 'frame':
      drawFrame(m);
      if (m.net) netView.update(m.net);
      break;
    case 'matchResult':
      renderMatch(m);
      break;
    case 'toast':
      toast(m.text);
      break;
    case 'error': {
      const lines = String(m.text).trim().split('\n');
      toast(lines[lines.length - 1], true, lines.length > 1 ? m.text : null);
      if (lines.length > 1) setStatus('error');
      break;
    }
  }
}

// ------------------------------------------------------------------ config form
function buildForm() {
  const f = $('cfgForm'); f.replaceChildren();
  for (const g of S.schema) {
    const fs = el('fieldset', {}, el('legend', {}, g.group));
    for (const d of g.fields) {
      let input;
      if (d.type === 'select') input = el('select', {}, d.options.map((o) => el('option', { value: o }, o)));
      else if (d.type === 'model') input = el('select', {});
      else if (d.type === 'bool') input = el('input', { type: 'checkbox' });
      else if (d.type === 'text') input = el('input', { type: 'text' });
      else input = el('input', { type: 'number', min: d.min, max: d.max, step: d.step || (d.type === 'int' ? 1 : 'any') });
      input.name = d.key; input.dataset.type = d.type; if (d.live) input.dataset.live = '1';
      const label = el('span', {}, d.label, d.live ? el('span', { class: 'live', title: 'Can be changed while training runs' }, 'LIVE') : null);
      const row = el('label', { class: 'field', title: d.help || '' }, label, input);
      if (d.help) row.append(el('div', { class: 'help' }, d.help));
      fs.append(row);
    }
    f.append(fs);
  }
  renderSeedOptions();
}
function renderSeedOptions() {
  const sel = $('cfgForm').elements.seed_model; if (!sel) return;
  const cur = sel.value;
  sel.replaceChildren(el('option', { value: '' }, '(new random population)'), ...S.models.map((m) => el('option', { value: m.name }, m.name)));
  sel.value = S.models.some((m) => m.name === cur) ? cur : '';
}
function readForm() {
  const out = {};
  for (const inp of $('cfgForm').elements) {
    if (!inp.name) continue;
    out[inp.name] = inp.type === 'checkbox' ? inp.checked : inp.value;
  }
  return out;
}
function fillForm(cfg) {
  for (const inp of $('cfgForm').elements) {
    if (!inp.name || !(inp.name in cfg)) continue;
    if (inp.type === 'checkbox') inp.checked = !!cfg[inp.name];
    else inp.value = cfg[inp.name];
  }
}

function renderPresets() {
  const sel = $('presetSel');
  sel.replaceChildren(el('option', { value: '' }, 'Saved configs…'), ...S.configs.map((c) => el('option', { value: c.name }, c.name)));
}
$('presetLoad').onclick = () => { const c = S.configs.find((c) => c.name === $('presetSel').value); if (c) { fillForm({ ...S.defaults, ...c.cfg }); toast(`Loaded config “${c.name}”`); } };
$('presetDel').onclick = () => { const n = $('presetSel').value; if (n && confirm(`Delete config “${n}”?`)) send({ t: 'deleteConfig', name: n }); };
$('presetSave').onclick = () => send({ t: 'saveConfig', name: $('presetName').value || 'config', cfg: readForm() });
$('resetCfg').onclick = () => fillForm(S.defaults);

// ------------------------------------------------------------------ run controls
$('btnStart').onclick = () => send({ t: 'start', cfg: readForm() });
$('btnPause').onclick = () => send({ t: S.state === 'paused' ? 'resume' : 'pause' });
$('btnStop').onclick = () => send({ t: 'stop' });
$('btnSave').onclick = () => { send({ t: 'save', name: $('snapName').value }); $('snapName').value = ''; };
$('btnTweak').onclick = () => {
  const cfg = readForm(), live = {};
  for (const inp of $('cfgForm').elements) if (inp.dataset.live) live[inp.name] = cfg[inp.name];
  send({ t: 'tweak', cfg: live }); toast('Live settings sent to the trainer');
};

function setStatus(state) {
  const p = $('status');
  p.className = 'pill ' + state;
  p.querySelector('span').textContent = { idle: 'Idle', starting: 'Starting…', running: 'Training', paused: 'Paused',
    stopped: 'Stopped', disconnected: 'Disconnected', error: 'Error' }[state] || state;
}
function renderStatus() {
  setStatus(S.state);
  const active = ['starting', 'running', 'paused'].includes(S.state);
  $('btnStart').disabled = active;
  $('btnPause').disabled = !active || S.state === 'starting';
  $('btnPause').textContent = S.state === 'paused' ? 'Resume' : 'Pause';
  $('btnStop').disabled = !active;
  $('btnSave').disabled = !active || !S.history.length;
  $('btnTweak').hidden = !active;
  for (const inp of $('cfgForm').elements) if (inp.name) inp.disabled = active && !inp.dataset.live;
  $('archInfo').textContent = S.info.arch ? `Network ${S.info.arch} · ${S.info.params.toLocaleString()} weights per bot · ${S.info.device}` : '';
}

// ------------------------------------------------------------------ progress tab
function niceTicks(lo, hi, n = 4) {
  if (lo === hi) { lo -= 1; hi += 1; }
  const span = hi - lo, step0 = span / n, mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((k) => k * mag).find((s) => span / s <= n) || 10 * mag;
  const t0 = Math.floor(lo / step) * step, out = [];
  for (let v = t0; v <= hi + step * 0.5; v += step) out.push(+v.toFixed(10));
  return out;
}
const tickFmt = (v) => Math.abs(v) >= 1000 ? (v / 1000).toFixed(1).replace(/\.0$/, '') + 'k' : String(+v.toFixed(2));

function lineChart(id, xs, series, legendId) {
  const host = $(id);
  host.replaceChildren();
  if (legendId) {
    $(legendId).replaceChildren(...series.map((s) => el('span', {}, el('i', { style: `background:${s.color}` }), s.name)));
  }
  if (xs.length < 2) { host.append(el('div', { class: 'empty' }, 'Waiting for at least two generations…')); return; }
  const W = host.clientWidth || 420, H = host.clientHeight || 220;
  const m = { l: 40, r: series.length > 1 ? 74 : 14, t: 8, b: 24 };
  // downsample long runs so the path stays light
  const step = Math.ceil(xs.length / 500);
  const idx = []; for (let i = 0; i < xs.length; i += step) idx.push(i); if (idx[idx.length - 1] !== xs.length - 1) idx.push(xs.length - 1);
  let lo = Infinity, hi = -Infinity;
  for (const s of series) for (const i of idx) { const v = s.values[i]; if (v < lo) lo = v; if (v > hi) hi = v; }
  if (lo > 0 && lo < (hi - lo) * 0.5) lo = 0;
  const ticks = niceTicks(lo, hi); lo = Math.min(lo, ticks[0]); hi = Math.max(hi, ticks[ticks.length - 1]);
  const x = (i) => m.l + (xs[i] - xs[0]) / (xs[xs.length - 1] - xs[0] || 1) * (W - m.l - m.r);
  const y = (v) => m.t + (1 - (v - lo) / (hi - lo || 1)) * (H - m.t - m.b);
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  const add = (tag, attrs, text) => { const n = document.createElementNS(NS, tag); for (const k in attrs) n.setAttribute(k, attrs[k]); if (text !== undefined) n.textContent = text; svg.append(n); return n; };
  const grid = css('--grid'), axis = css('--axis'), ink2 = css('--text-2');
  for (const t of ticks) {
    add('line', { x1: m.l, x2: W - m.r, y1: y(t), y2: y(t), stroke: t === 0 ? axis : grid, 'stroke-width': 1 });
    add('text', { x: m.l - 6, y: y(t) + 4, 'text-anchor': 'end', fill: ink2, 'font-size': 11, style: 'font-variant-numeric:tabular-nums' }, tickFmt(t));
  }
  add('line', { x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b, stroke: axis });
  for (const t of niceTicks(xs[0], xs[xs.length - 1], 5).filter((t) => t >= xs[0] && t <= xs[xs.length - 1] && Number.isInteger(t))) {
    const px = m.l + (t - xs[0]) / (xs[xs.length - 1] - xs[0]) * (W - m.l - m.r);
    add('text', { x: px, y: H - 6, 'text-anchor': 'middle', fill: ink2, 'font-size': 11 }, t);
  }
  for (const s of series) {
    add('path', { d: idx.map((i, k) => `${k ? 'L' : 'M'}${x(i).toFixed(1)},${y(s.values[i]).toFixed(1)}`).join(''),
      fill: 'none', stroke: s.color, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' });
  }
  // direct end labels (swatch in series colour, text in ink), nudged apart
  if (series.length > 1) {
    const last = xs.length - 1;
    const labs = series.map((s) => ({ s, y: y(s.values[last]) })).sort((a, b) => a.y - b.y);
    for (let i = 1; i < labs.length; i++) if (labs[i].y - labs[i - 1].y < 13) labs[i].y = labs[i - 1].y + 13;
    for (const l of labs) {
      add('circle', { cx: W - m.r + 8, cy: l.y, r: 4, fill: l.s.color });
      add('text', { x: W - m.r + 16, y: l.y + 4, fill: ink2, 'font-size': 11 }, l.s.name);
    }
  }
  // hover crosshair + tooltip
  const cross = add('line', { y1: m.t, y2: H - m.b, stroke: axis, 'stroke-width': 1, visibility: 'hidden' });
  const dots = series.map((s) => add('circle', { r: 4, fill: s.color, stroke: css('--surface'), 'stroke-width': 2, visibility: 'hidden' }));
  const hit = add('rect', { x: m.l, y: 0, width: W - m.l - m.r, height: H, fill: 'transparent' });
  const tip = $('tip');
  hit.addEventListener('mousemove', (e) => {
    const r = svg.getBoundingClientRect();
    const px = (e.clientX - r.left) * (W / r.width);
    const gx = xs[0] + (px - m.l) / (W - m.l - m.r) * (xs[xs.length - 1] - xs[0]);
    let i = 0, best = Infinity;
    for (let k = 0; k < xs.length; k++) { const d = Math.abs(xs[k] - gx); if (d < best) { best = d; i = k; } }
    cross.setAttribute('x1', x(i)); cross.setAttribute('x2', x(i)); cross.setAttribute('visibility', 'visible');
    series.forEach((s, k) => { dots[k].setAttribute('cx', x(i)); dots[k].setAttribute('cy', y(s.values[i])); dots[k].setAttribute('visibility', 'visible'); });
    tip.replaceChildren(el('b', {}, `Generation ${xs[i]}`),
      ...series.map((s) => el('div', { class: 'r' }, el('i', { style: `background:${s.color}` }), `${s.name}: ${fmt(s.values[i], 2)}`)));
    tip.hidden = false;
    tip.style.left = Math.min(e.clientX + 14, innerWidth - 200) + 'px';
    tip.style.top = e.clientY + 14 + 'px';
  });
  hit.addEventListener('mouseleave', () => { tip.hidden = true; cross.setAttribute('visibility', 'hidden'); dots.forEach((d) => d.setAttribute('visibility', 'hidden')); });
  host.append(svg);
}

function renderProgress() {
  const run = S.viewing;
  const h = run ? run.history : S.history;
  const cfg = run ? run.cfg : S.cfg;
  $('runLabel').textContent = cfg
    ? `${run ? 'Past run' : 'Run'} “${cfg.run_name}” · ${cfg.population} bots × ${cfg.episodes} boards · ${cfg.board_w}×${cfg.board_h}, ${cfg.mines} mines, ${cfg.episode_steps} steps`
    : 'No run yet. Configure on the left and press Start training.';
  const last = h[h.length - 1] || {};
  const tiles = [
    ['Generation', last.gen ?? '–'], ['Best fitness', fmt(last.best)], ['Elite mean', fmt(last.elite)],
    ['Population mean', fmt(last.mean)], ['Tiles / board', fmt(last.tiles)], ['Mines hit / board', fmt(last.mines_hit, 2)],
    ['Mutation σ', fmt(last.sigma, 4)], ['Seconds / gen', fmt(last.seconds, 2)],
  ];
  $('tiles').replaceChildren(...tiles.map(([k, v]) => el('div', { class: 'tile' }, el('div', { class: 'k' }, k), el('div', { class: 'v' }, String(v)))));
  const xs = h.map((g) => g.gen);
  lineChart('ch-fit', xs, [
    { name: 'Best', color: SERIES[0], values: h.map((g) => g.best) },
    { name: 'Elite mean', color: SERIES[1], values: h.map((g) => g.elite) },
    { name: 'Population', color: SERIES[2], values: h.map((g) => g.mean) },
  ], 'lg-fit');
  lineChart('ch-tiles', xs, [{ name: 'Tiles', color: SERIES[0], values: h.map((g) => g.tiles) }]);
  lineChart('ch-mines', xs, [{ name: 'Mines hit', color: SERIES[0], values: h.map((g) => g.mines_hit) }]);
  lineChart('ch-flags', xs, [
    { name: 'Correct', color: SERIES[0], values: h.map((g) => g.flags_correct) },
    { name: 'Wrong', color: SERIES[1], values: h.map((g) => g.flags_wrong) },
    ...(h.some((g) => g.unflags !== undefined)
      ? [{ name: 'Removed (toggles)', color: SERIES[2], values: h.map((g) => g.unflags ?? 0) }] : []),
  ], 'lg-flags');
  // v2 (all-modes) runs also report combat
  const v2 = h.some((g) => g.kos !== undefined);
  $('card-kos').hidden = $('card-boss').hidden = !v2;
  if (v2) {
    lineChart('ch-kos', xs, [
      { name: 'Got knocked out', color: SERIES[0], values: h.map((g) => g.kos ?? 0) },
      { name: 'KO’d a rival (PvP)', color: SERIES[1], values: h.map((g) => g.pvp_kos ?? 0) },
      ...(h.some((g) => g.spikes !== undefined)
        ? [{ name: 'Spiked (v3)', color: SERIES[2], values: h.map((g) => g.spikes ?? 0) },
           { name: 'Pickups (v3)', color: SERIES[3], values: h.map((g) => g.items ?? 0) }] : []),
    ], 'lg-kos');
    lineChart('ch-boss', xs, [{ name: 'Boss damage', color: SERIES[0], values: h.map((g) => g.boss_damage ?? 0) }]);
  }
  if ($('genTable').closest('details').open) renderGenTable(h);
  renderStatus();
}
function renderGenTable(h) {
  const cols = [['gen', 'Gen', 0], ['best', 'Best', 1], ['elite', 'Elite', 1], ['mean', 'Mean', 1], ['median', 'Median', 1],
    ['tiles', 'Tiles', 1], ['mines_hit', 'Mines hit', 2], ['flags_correct', 'Flags ✓', 2], ['flags_wrong', 'Flags ✗', 2],
    ['clear_rate', 'Cleared', 2], ['sigma', 'σ', 4], ['seconds', 'Sec', 2]];
  const rows = h.slice(-200).reverse();
  $('genTable').replaceChildren(el('table', {},
    el('thead', {}, el('tr', {}, cols.map(([, n]) => el('th', { class: 'num' }, n)))),
    el('tbody', {}, rows.map((g) => el('tr', {}, cols.map(([k, , d]) => el('td', { class: 'num' }, fmt(g[k], d))))))));
}
$('genTable').closest('details').addEventListener('toggle', () => renderGenTable(S.viewing ? S.viewing.history : S.history));
$('runSel').onchange = () => { const n = $('runSel').value; if (n) send({ t: 'loadRun', name: n }); else { S.viewing = null; renderProgress(); } };
addEventListener('resize', () => renderProgress());

// ------------------------------------------------------------------ tabs
for (const b of document.querySelectorAll('.tabs button')) {
  b.onclick = () => {
    for (const o of document.querySelectorAll('.tabs button')) o.classList.toggle('on', o === b);
    for (const s of document.querySelectorAll('.tab')) s.hidden = s.id !== 'tab-' + b.dataset.tab;
    if (b.dataset.tab === 'progress') renderProgress();
  };
}
function showTab(name) { document.querySelector(`.tabs button[data-tab="${name}"]`).click(); }

// ------------------------------------------------------------------ models tab
function renderModels() {
  for (const n of [...S.picked]) if (!S.models.some((m) => m.name === n)) S.picked.delete(n);
  const rows = S.models.map((m) => {
    const meta = m.meta || {};
    const cb = el('input', { type: 'checkbox', 'aria-label': `Select ${m.name}` });
    cb.checked = S.picked.has(m.name);
    cb.onchange = () => { cb.checked ? S.picked.add(m.name) : S.picked.delete(m.name); renderWatchModels(); };
    return el('tr', {},
      el('td', {}, cb),
      el('td', {}, el('b', {}, m.name)),
      el('td', {}, m.arch || m.error || ''),
      el('td', { class: 'num' }, m.params ? m.params.toLocaleString() : ''),
      el('td', { class: 'num' }, fmt(meta.fitness)),
      el('td', { class: 'num' }, meta.generation ?? ''),
      el('td', {}, meta.run || ''),
      el('td', {}, meta.saved ? new Date(meta.saved * 1000).toLocaleString() : ''),
      el('td', {}, el('div', { class: 'acts' },
        el('button', { onclick: () => { S.picked = new Set([m.name]); renderModels(); startWatch('models'); } }, 'Watch'),
        el('button', { title: 'Continue training from this model', onclick: () => {
          const f = $('cfgForm').elements; f.seed_model.value = m.name;
          const c = meta.cfg || {};
          for (const k of ['radius', 'hidden', 'activation']) if (k in c) f[k].value = c[k];
          toast(`“${m.name}” set as the starting population. Press Start training.`);
        } }, 'Train from'),
        el('button', { onclick: () => { const nn = prompt('New name', m.name); if (nn && nn !== m.name) send({ t: 'renameModel', name: m.name, new: nn }); } }, 'Rename'),
        el('button', { class: 'danger', onclick: () => { if (confirm(`Delete model “${m.name}”? This cannot be undone.`)) send({ t: 'deleteModel', name: m.name }); } }, 'Delete'))));
  });
  $('modelTable').replaceChildren(S.models.length ? el('table', {},
    el('thead', {}, el('tr', {}, ['', 'Name', 'Network', 'Weights', 'Fitness', 'Gen', 'Run', 'Saved', ''].map((h, i) => el('th', { class: [3, 4, 5].includes(i) ? 'num' : '' }, h)))),
    el('tbody', {}, rows)) : el('p', { class: 'muted' }, 'No saved models yet. Training saves one automatically every few generations, or press “Save best now”.'));
  renderSeedOptions();
  renderWatchModels();
  const bm = $('bModel'), cur = bm.value;
  bm.replaceChildren(...S.models.map((m) => el('option', { value: m.name }, m.name)));
  if (S.models.some((m) => m.name === cur)) bm.value = cur;
}

$('matchRun').onclick = () => {
  if (S.picked.size < 2) return toast('Tick 2 to 6 models in the list above first.', true);
  $('matchResult').replaceChildren(el('p', { class: 'muted' }, 'Running…'));
  send({ t: 'match', models: [...S.picked], games: +$('mG').value, board: matchBoard() });
};
$('matchWatch').onclick = () => {
  if (S.picked.size < 1) return toast('Tick at least one model first.', true);
  setBoardInputs(matchBoard());
  startWatch('models');
};
const matchBoard = () => ({ board_w: +$('mW').value, board_h: +$('mH').value, mines: +$('mM').value, episode_steps: +$('mS').value });

function renderMatch(r) {
  const res = [...r.results].sort((a, b) => b.win_rate - a.win_rate);
  const maxW = Math.max(...res.map((x) => x.win_rate), 0.0001);
  $('matchResult').replaceChildren(
    el('p', { class: 'muted small' }, `${r.games} games on ${r.board.board_w}×${r.board.board_h} with ${r.board.mines} mines and ${r.board.episode_steps} steps · ${r.seconds}s`),
    el('table', {}, el('thead', {}, el('tr', {}, ['#', 'Model', 'Win rate', 'Avg score', 'Tiles', 'Mines hit', 'Flags ✓', 'Flags ✗'].map((h, i) => el('th', { class: i > 1 ? 'num' : '' }, h)))),
      el('tbody', {}, res.map((x, i) => el('tr', {},
        el('td', {}, String(i + 1)), el('td', {}, el('b', {}, x.name)),
        el('td', { class: 'num' }, el('span', { class: 'bar', style: `width:${Math.round(80 * x.win_rate / maxW)}px` }), `${(x.win_rate * 100).toFixed(1)}%`),
        el('td', { class: 'num' }, fmt(x.score)), el('td', { class: 'num' }, fmt(x.tiles)), el('td', { class: 'num' }, fmt(x.mines_hit, 2)),
        el('td', { class: 'num' }, fmt(x.flags_correct, 2)), el('td', { class: 'num' }, fmt(x.flags_wrong, 2)))))));
}

// ------------------------------------------------------------------ watch tab
for (const r of document.querySelectorAll('input[name=wsrc]')) r.onchange = () => { $('watchModels').hidden = r.value !== 'models' || !r.checked; renderWatchModels(); };
function renderWatchModels() {
  const box = $('watchModels');
  box.hidden = document.querySelector('input[name=wsrc]:checked').value !== 'models';
  box.replaceChildren(...(S.models.length ? S.models.map((m) => {
    const cb = el('input', { type: 'checkbox' }); cb.checked = S.picked.has(m.name);
    cb.onchange = () => { cb.checked ? S.picked.add(m.name) : S.picked.delete(m.name); renderModels(); };
    return el('label', { class: 'inline' }, cb, m.name);
  }) : [el('span', { class: 'muted' }, 'No saved models yet.')]));
}
function setBoardInputs(b) {
  $('wW').value = b.board_w; $('wH').value = b.board_h; $('wM').value = b.mines; $('wS').value = b.episode_steps;
  if (b.layout) $('wL').value = b.layout;
  if (b.mode) $('wMode').value = b.mode;
  if (b.bosses !== undefined) $('wBoss').value = b.bosses ? '1' : '0';
}
function startWatch(source) {
  if (source) document.querySelector(`input[name=wsrc][value=${source}]`).checked = true;
  const src = document.querySelector('input[name=wsrc]:checked').value;
  if (src === 'models' && !S.picked.size) return toast('Tick at least one saved model to watch.', true);
  showTab('watch');
  send({ t: 'watch', source: src, models: [...S.picked].slice(0, 6), speed: +$('wSpeed').value,
    board: { board_w: +$('wW').value, board_h: +$('wH').value, mines: +$('wM').value, episode_steps: +$('wS').value, layout: $('wL').value,
      mode: $('wMode').value, bosses: $('wBoss').value === '1' } });
}
$('watchStart').onclick = () => startWatch();
$('watchStop').onclick = () => send({ t: 'stopWatch' });
$('wSpeed').oninput = () => { $('wSpeedLbl').textContent = $('wSpeed').value; send({ t: 'watchSpeed', speed: +$('wSpeed').value }); };

const NUM_COLORS = ['', '#1e6bff', '#1f9d3a', '#e5322d', '#26308f', '#8b1a1a', '#138a8a', '#222', '#777'];
const NEAR_ARROWS = ['↖', '↑', '↗', '←', '•', '→', '↙', '↓', '↘'];
const MOVE_ARROWS = ['↖', '↑', '↗', '←', '→', '↙', '↓', '↘'];
const NEAR = [[-1, -1], [-1, 0], [-1, 1], [0, -1], [0, 0], [0, 1], [1, -1], [1, 0], [1, 1]];
function actionName(a) {
  if (a === 26) return 'Attack';
  if (a < 8) return `Move ${MOVE_ARROWS[a]}`;
  if (a < 17) return a - 8 === 4 ? 'Dig own tile' : `Dig ${NEAR_ARROWS[a - 8]}`;
  return a - 17 === 4 ? 'Flag own tile' : `Flag ${NEAR_ARROWS[a - 17]}`;
}

// ---------------------------------------------------------------- live network view
// Draws bot 1's network: its vision window (input), hidden neurons and action probabilities, with the
// strongest signed contributions (activation × weight) as edges. Values ease toward each new step and
// pulses travel layer by layer along the strongest edges, so you can watch a decision form.
const netView = (() => {
  const cv = $('net'), tip = $('netTip');
  let target = null, shown = null, pulses = [], last = 0, running = false, layout = null, hoverNode = null;
  const CELL_COL = { o: '#1b2430', x: '#b8322f', f: '#e3cfa0', h: '#63b143', 0: '#e3cfa0', 1: '#e3cfa0', 2: '#e3cfa0', 3: '#e3cfa0', 4: '#e3cfa0' };
  const POS = css('--s2'), NEG = css('--s1'), ACC = css('--accent');
  const lerp = (a, b, t) => a + (b - a) * t;

  function rgba(hex, a) {
    const n = parseInt(hex.replace('#', ''), 16);
    return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`;
  }
  // diverging colour for an activation: blue (negative) - grey (0) - orange (positive)
  function nodeColor(v) {
    const k = Math.min(1, Math.abs(v));
    const base = [74, 85, 100], to = parseInt((v >= 0 ? POS : NEG).replace('#', ''), 16);
    const c = [to >> 16, (to >> 8) & 255, to & 255].map((t, i) => Math.round(base[i] + (t - base[i]) * k));
    return `rgb(${c[0]},${c[1]},${c[2]})`;
  }

  function computeLayout(net, w, h) {
    const nL = net.hidden.length + 2, pad = 18;
    const G = net.glob.length, per = G > 3 ? 4 : 3, gRows = Math.ceil(G / per);
    const grid = Math.min(h - 40 - gRows * 30, 160), cs = grid / net.k;
    const gx = pad, gy = Math.max(30, (h - grid - gRows * 30) / 2);
    const portX = gx + grid + 14;            // connections leave from here, never across the grid
    const colX = (i) => portX + 70 + (i - 1) * ((w - portX - 70 - 100 - pad) / Math.max(1, nL - 2));
    const input = [], ports = [];
    for (let c = 0; c < net.k * net.k; c++) {
      const y = gy + (Math.floor(c / net.k) + 0.5) * cs;
      input.push({ x: gx + (c % net.k + 0.5) * cs, y, r: cs * 0.35 });
      // one port per cell on the grid's right edge, fanned out a little so rows don't stack exactly
      ports.push({ x: portX + (c % net.k) * 2.2, y: y + ((c % net.k) - (net.k - 1) / 2) * (cs / net.k) * 0.8, r: 1.5 });
    }
    // global inputs in rows under the vision grid (3 for v1 models, 13 for v2 in rows of 4)
    for (let g = 0; g < G; g++) {
      const n = { x: gx + ((g % per) + 0.5) * (grid / per), y: gy + grid + 22 + Math.floor(g / per) * 30, r: 5 };
      input.push(n);
      ports.push({ x: portX + 2 + g * 1.5, y: n.y, r: 1.5 });   // globals connect from beside their row too
    }
    const hidden = net.hidden.map((vals, l) => vals.map((_, i) => ({
      x: colX(l + 1), y: pad + (i + 0.5) * ((h - pad * 2) / vals.length), r: Math.max(2.5, Math.min(6, (h - pad * 2) / vals.length * 0.38)) })));
    const ox = w - pad - 70, nOut = net.out.length, gaps = 0.6 * (nOut > 26 ? 3 : 2);
    const out = net.out.map((_, a) => ({ x: ox, y: pad + (a + 0.5 + (a >= 8) * 0.6 + (a >= 17) * 0.6 + (a >= 26) * 0.6) * ((h - pad * 2) / (nOut + gaps + 0.2)), r: 4.5 }));
    return { input, ports, hidden, out, grid: { gx, gy, cs, portX }, cols: [input, ...hidden, out], srcCols: [ports, ...hidden, out] };
  }

  function update(net) {
    cv.style.height = net.glob.length > 3 ? '440px' : '360px';   // v2 has more inputs to label
    const fresh = !target || target.glob.length !== net.glob.length || target.hidden.length !== net.hidden.length
      || target.hidden.some((h, i) => h.length !== net.hidden[i].length) || target.k !== net.k;
    target = net;
    if (fresh || !shown) shown = { hidden: net.hidden.map((h) => h.slice()), out: net.out.slice(), glob: net.glob.slice() };
    const w = cv.clientWidth, h = cv.clientHeight;
    if (fresh || !layout || layout.w !== w) { layout = computeLayout(net, w, h); layout.w = w; }
    // a pulse along each of the strongest edges, one layer after another
    const now = performance.now(), speed = +$('wSpeed').value || 8;
    const step = Math.min(260, 1000 / speed / (net.edges.length + 0.5));
    net.edges.forEach((list, li) => {
      const mx = Math.max(1e-6, ...list.map((e) => Math.abs(e[2])));
      list.slice(0, 14).forEach(([s, d, v]) => pulses.push({ li, s, d, v: v / mx, t0: now + li * step, dur: step * 1.1 }));
    });
    if (pulses.length > 600) pulses = pulses.slice(-600);
    if (!running) { running = true; requestAnimationFrame(draw); }
  }

  function draw(now) {
    if (!target || $('tab-watch').hidden) { running = false; return; }
    requestAnimationFrame(draw);
    const dt = Math.min(0.1, (now - (last || now)) / 1000); last = now;
    const dpr = devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight;
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); layout = computeLayout(target, w, h); layout.w = w; }
    const g = cv.getContext('2d');
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    const k = 1 - Math.exp(-dt * 10);
    shown.hidden.forEach((vals, l) => vals.forEach((v, i) => { vals[i] = lerp(v, target.hidden[l][i], k); }));
    shown.out.forEach((v, i) => { shown.out[i] = lerp(v, target.out[i], k); });

    // edges
    target.edges.forEach((list, li) => {
      const src = layout.srcCols[li], dst = layout.cols[li + 1];
      const mx = Math.max(1e-6, ...list.map((e) => Math.abs(e[2])));
      for (const [s, d, v] of list) {
        const a = src[s], b = dst[d]; if (!a || !b) continue;
        const m = Math.abs(v) / mx;
        g.strokeStyle = rgba(v >= 0 ? POS : NEG, 0.12 + m * 0.5);
        g.lineWidth = 0.5 + m * 2.2;
        g.beginPath(); g.moveTo(a.x, a.y); g.lineTo(b.x, b.y); g.stroke();
      }
    });
    // pulses
    pulses = pulses.filter((p) => now < p.t0 + p.dur);
    for (const p of pulses) {
      if (now < p.t0) continue;
      const a = layout.srcCols[p.li][p.s], b = layout.cols[p.li + 1][p.d]; if (!a || !b) continue;
      const t = (now - p.t0) / p.dur, x = lerp(a.x, b.x, t), y = lerp(a.y, b.y, t);
      g.fillStyle = rgba(p.v >= 0 ? POS : NEG, 0.95);
      g.beginPath(); g.arc(x, y, 1.5 + Math.abs(p.v) * 2.5, 0, 7); g.fill();
    }

    // input: the vision window, centre = the bot itself
    const { gx, gy, cs } = layout.grid;
    for (let c = 0; c < target.k * target.k; c++) {
      const ch = target.cells[c], x = gx + (c % target.k) * cs, y = gy + Math.floor(c / target.k) * cs;
      g.fillStyle = CELL_COL[ch] || '#333'; g.fillRect(x + 1, y + 1, cs - 2, cs - 2);
      if (ch >= '1' && ch <= '4') {
        g.fillStyle = NUM_COLORS[+ch]; g.font = `800 ${Math.floor(cs * 0.6)}px system-ui`; g.textAlign = 'center'; g.textBaseline = 'middle';
        g.fillText(ch, x + cs / 2, y + cs / 2 + 1);
      } else if (ch === 'f') {
        g.fillStyle = '#ff5d5d'; g.beginPath(); g.moveTo(x + cs * 0.35, y + cs * 0.2); g.lineTo(x + cs * 0.75, y + cs * 0.35); g.lineTo(x + cs * 0.35, y + cs * 0.5); g.fill();
      } else if (ch === 'x') {
        g.fillStyle = '#2b2b33'; g.beginPath(); g.arc(x + cs / 2, y + cs / 2, cs * 0.22, 0, 7); g.fill();
      }
      if (target.traps?.includes(c)) {   // v3: spike trap (filled when the spikes are up)
        g.strokeStyle = '#9aa7b8'; g.lineWidth = 1.5; g.strokeRect(x + cs * 0.22, y + cs * 0.22, cs * 0.56, cs * 0.56);
        if (target.spikes?.includes(c)) { g.fillStyle = 'rgba(220,60,61,.55)'; g.fillRect(x + cs * 0.22, y + cs * 0.22, cs * 0.56, cs * 0.56); }
      }
      if (target.items?.includes(c)) { g.fillStyle = '#ffd23f'; g.beginPath(); g.arc(x + cs / 2, y + cs / 2, cs * 0.16, 0, 7); g.fill(); }
      if (target.goal?.includes(c)) { g.strokeStyle = '#7ee0ff'; g.lineWidth = 2.5; g.strokeRect(x + 3, y + 3, cs - 6, cs - 6); }
      if (target.danger?.includes(c)) { g.fillStyle = 'rgba(220,60,61,.4)'; g.fillRect(x + 1, y + 1, cs - 2, cs - 2); }
      if (target.others.includes(c)) { g.strokeStyle = SERIES[1]; g.lineWidth = 2; g.strokeRect(x + 2, y + 2, cs - 4, cs - 4); }
      if (target.allies?.includes(c)) { g.strokeStyle = SERIES[2]; g.lineWidth = 2; g.strokeRect(x + 2, y + 2, cs - 4, cs - 4); }
      if (target.boss?.includes(c)) {
        g.fillStyle = '#5a1a1a'; g.beginPath(); g.arc(x + cs / 2, y + cs / 2, cs * 0.4, 0, 7); g.fill();
        g.fillStyle = '#fff'; g.font = `800 ${Math.floor(cs * 0.5)}px system-ui`; g.textAlign = 'center'; g.textBaseline = 'middle';
        g.fillText('B', x + cs / 2, y + cs / 2 + 1);
      }
    }
    const mid = Math.floor(target.k * target.k / 2);
    g.strokeStyle = ACC; g.lineWidth = 2; g.strokeRect(gx + (mid % target.k) * cs + 1, gy + Math.floor(mid / target.k) * cs + 1, cs - 2, cs - 2);
    g.fillStyle = css('--text-2'); g.font = '11px system-ui'; g.textAlign = 'left'; g.textBaseline = 'alphabetic';
    g.fillText('What it sees', gx, gy - 6);
    // the bus the vision cells connect through, and short leads from the global inputs
    g.strokeStyle = 'rgba(158,172,189,.35)'; g.lineWidth = 2;
    g.beginPath(); g.moveTo(layout.grid.portX - 5, gy); g.lineTo(layout.grid.portX - 5, gy + target.k * cs); g.stroke();
    g.lineWidth = 1;
    const KK = target.k * target.k;
    layout.input.slice(KK).forEach((n, i) => {
      const pt = layout.ports[KK + i];
      g.strokeStyle = 'rgba(158,172,189,.18)'; g.beginPath(); g.moveTo(n.x + 6, n.y); g.lineTo(pt.x, pt.y); g.stroke();
    });
    const GLOBAL_NAMES = target.version >= 3
      ? ['dir ↕', 'dir ↔', 'dist', 'HP', 'race', 'pvp', 'co-op', 'descent', 'boss ↕', 'boss ↔', 'boss d', 'boss?', 'boss HP', 'wind-up', 'goal ↕', 'goal ↔', 'goal d', 'goal?']
      : ['dir ↕', 'dir ↔', 'dist', 'HP', 'race', 'pvp', 'co-op', 'boss ↕', 'boss ↔', 'boss d', 'boss?', 'boss HP', 'wind-up'];
    const gl = layout.input.slice(-target.glob.length);
    g.font = '10px system-ui';
    target.glob.forEach((v, i) => {
      g.fillStyle = nodeColor(v); g.beginPath(); g.arc(gl[i].x, gl[i].y, 5, 0, 7); g.fill();
      g.fillStyle = css('--text-2'); g.textAlign = 'center'; g.fillText(GLOBAL_NAMES[i] || '', gl[i].x, gl[i].y + 15);
    });
    g.font = '11px system-ui';

    // hidden neurons
    shown.hidden.forEach((vals, l) => {
      const col = layout.hidden[l];
      vals.forEach((v, i) => {
        const n = col[i];
        if (Math.abs(v) > 0.6) { g.fillStyle = rgba(v >= 0 ? POS : NEG, 0.18); g.beginPath(); g.arc(n.x, n.y, n.r * 2.2, 0, 7); g.fill(); }
        g.fillStyle = nodeColor(v); g.beginPath(); g.arc(n.x, n.y, n.r, 0, 7); g.fill();
      });
      g.fillStyle = css('--text-2'); g.textAlign = 'center'; g.font = '11px system-ui';
      const total = target.sizes[l];
      g.fillText(`Hidden ${l + 1}${total > vals.length ? ` (${vals.length} of ${total})` : ''}`, col[0].x, 12);
    });

    // outputs: action probabilities
    const mxp = Math.max(1e-6, ...shown.out);
    shown.out.forEach((p, a) => {
      const n = layout.out[a];
      g.fillStyle = rgba(css('--s3'), 0.15 + 0.85 * (p / mxp)); g.beginPath(); g.arc(n.x, n.y, n.r, 0, 7); g.fill();
      if (a === target.action) { g.strokeStyle = ACC; g.lineWidth = 2; g.beginPath(); g.arc(n.x, n.y, n.r + 3, 0, 7); g.stroke(); }
      g.fillStyle = a === target.action ? css('--text') : css('--text-2');
      g.font = `${a === target.action ? 700 : 400} 10px system-ui`; g.textAlign = 'left'; g.textBaseline = 'middle';
      g.fillText(actionName(a), n.x + 9, n.y);
    });
    g.textBaseline = 'alphabetic';
    if (hoverNode) drawTip();
  }

  // hover a neuron or action to read its value
  cv.addEventListener('mousemove', (e) => {
    if (!layout || !target) return;
    const r = cv.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    hoverNode = null;
    layout.hidden.forEach((col, l) => col.forEach((n, i) => { if (Math.hypot(n.x - x, n.y - y) < Math.max(6, n.r + 3)) hoverNode = { kind: 'h', l, i }; }));
    layout.out.forEach((n, a) => { if (Math.hypot(n.x - x, n.y - y) < 8) hoverNode = { kind: 'o', a }; });
    tip.hidden = !hoverNode;
    if (hoverNode) { tip.style.left = `${e.clientX + 12}px`; tip.style.top = `${e.clientY + 12}px`; drawTip(); }
  });
  cv.addEventListener('mouseleave', () => { hoverNode = null; tip.hidden = true; });
  function drawTip() {
    if (hoverNode.kind === 'h') tip.textContent = `Hidden ${hoverNode.l + 1}, neuron ${hoverNode.i + 1}: ${shown.hidden[hoverNode.l][hoverNode.i].toFixed(3)}`;
    else tip.textContent = `${actionName(hoverNode.a)}: ${(shown.out[hoverNode.a] * 100).toFixed(1)}%`;
  }

  return { update };
})();

function drawFrame(f) {
  const cv = $('board'), ctx = cv.getContext('2d');
  const maxPx = Math.min(640, cv.parentElement.clientWidth || 560);
  const s = Math.max(8, Math.floor(maxPx / Math.max(f.w, f.h)));
  const dpr = devicePixelRatio || 1;
  if (cv.width !== f.w * s * dpr || cv.height !== f.h * s * dpr) {
    cv.width = f.w * s * dpr; cv.height = f.h * s * dpr;
    cv.style.width = f.w * s + 'px'; cv.style.height = f.h * s + 'px';
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  for (let i = 0; i < f.w * f.h; i++) {
    const x = (i % f.w) * s, y = Math.floor(i / f.w) * s, c = f.cells[i], odd = ((i % f.w) + Math.floor(i / f.w)) % 2;
    if (c === '#') { ctx.fillStyle = '#1b2430'; ctx.fillRect(x, y, s, s); continue; }   // dungeon wall
    if (c === '.' || c === 'm') ctx.fillStyle = odd ? '#6fbf4c' : '#63b143';
    else if (c === 'X') ctx.fillStyle = '#b8322f';
    else ctx.fillStyle = odd ? '#e3cfa0' : '#d8c291';
    ctx.fillRect(x, y, s, s);
    ctx.strokeStyle = 'rgba(0,0,0,.12)'; ctx.strokeRect(x + 0.5, y + 0.5, s - 1, s - 1);
    if (c === 'X' || c === 'm') {
      ctx.fillStyle = '#2b2b33'; ctx.beginPath(); ctx.arc(x + s / 2, y + s / 2, s * 0.25, 0, 7); ctx.fill();
    } else if (c > '0' && c <= '8') {
      ctx.font = `800 ${Math.floor(s * 0.62)}px system-ui, sans-serif`;
      ctx.fillStyle = NUM_COLORS[+c]; ctx.fillText(c, x + s / 2, y + s / 2 + 1);
    }
  }
  for (const [i, owner] of f.flags) {
    const x = (i % f.w) * s, y = Math.floor(i / f.w) * s;
    ctx.fillStyle = '#eee'; ctx.fillRect(x + s * 0.3, y + s * 0.2, Math.max(1.5, s * 0.07), s * 0.62);
    ctx.fillStyle = SERIES[owner % SERIES.length];
    ctx.beginPath(); ctx.moveTo(x + s * 0.34, y + s * 0.2); ctx.lineTo(x + s * 0.8, y + s * 0.36); ctx.lineTo(x + s * 0.34, y + s * 0.52); ctx.fill();
  }
  // v3: spike traps (red when up), pickups (gold; food green) and the stairs
  for (const [i, up] of f.traps || []) {
    const x = (i % f.w) * s, y = Math.floor(i / f.w) * s;
    ctx.strokeStyle = '#5b6573'; ctx.lineWidth = 1.5; ctx.strokeRect(x + s * 0.2, y + s * 0.2, s * 0.6, s * 0.6);
    if (up) { ctx.fillStyle = 'rgba(200,40,40,.7)'; ctx.fillRect(x + s * 0.2, y + s * 0.2, s * 0.6, s * 0.6); }
    ctx.lineWidth = 1;
  }
  for (const [i, kind] of f.items || []) {
    const x = (i % f.w) * s, y = Math.floor(i / f.w) * s;
    ctx.fillStyle = kind === 2 ? '#3fae5a' : '#f2b705';
    ctx.beginPath(); ctx.arc(x + s / 2, y + s / 2, s * 0.2, 0, 7); ctx.fill();
  }
  if (f.stairs !== null && f.stairs !== undefined) {
    const x = (f.stairs % f.w) * s, y = Math.floor(f.stairs / f.w) * s;
    ctx.fillStyle = '#2c3e57'; ctx.fillRect(x + 2, y + 2, s - 4, s - 4);
    ctx.fillStyle = '#7ee0ff';
    for (let k = 0; k < 3; k++) ctx.fillRect(x + s * 0.2 + k * s * 0.2, y + s * (0.3 + k * 0.17), s * 0.6 - k * s * 0.2, Math.max(1.5, s * 0.1));
  }
  // bot 1's preferences over its reach
  const a0 = f.agents[0];
  if (f.prefs && a0 && !f.done) {
    NEAR.forEach(([dy, dx], k) => {
      const ty = a0.y + dy, tx = a0.x + dx;
      if (ty < 0 || tx < 0 || ty >= f.h || tx >= f.w) return;
      const dig = f.prefs[8 + k], flag = f.prefs[17 + k];
      if (dig > 0.01) { ctx.fillStyle = `rgba(255,255,255,${Math.min(0.75, dig * 0.9)})`; ctx.fillRect(tx * s + 2, ty * s + 2, s - 4, s - 4); }
      if (flag > 0.01) { ctx.strokeStyle = `rgba(220,60,61,${Math.min(1, 0.3 + flag)})`; ctx.lineWidth = 1 + flag * 4; ctx.strokeRect(tx * s + 3, ty * s + 3, s - 6, s - 6); ctx.lineWidth = 1; }
    });
    ctx.strokeStyle = 'rgba(255,243,160,.9)'; ctx.lineWidth = 2;
    ctx.strokeRect((a0.x - 1) * s + 1, (a0.y - 1) * s + 1, 3 * s - 2, 3 * s - 2); ctx.lineWidth = 1;
  }
  // v2: the boss, its wind-up danger zone and its health
  if (f.boss) {
    const b = f.boss, bx = b.x * s, by = b.y * s;
    if (b.windup) { ctx.fillStyle = 'rgba(220,60,61,.35)'; ctx.fillRect((b.x - 1) * s, (b.y - 1) * s, 3 * s, 3 * s); }
    ctx.fillStyle = '#5a1a1a'; ctx.strokeStyle = b.windup ? '#ff5d5d' : '#ffb0b0'; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(bx + s / 2, by + s / 2, s * 0.46, 0, 7); ctx.fill(); ctx.stroke(); ctx.lineWidth = 1;
    ctx.fillStyle = '#fff'; ctx.font = `800 ${Math.floor(s * 0.45)}px system-ui, sans-serif`; ctx.fillText('B', bx + s / 2, by + s / 2 + 1);
    ctx.fillStyle = '#1b2430'; ctx.fillRect(bx - s * 0.2, by - s * 0.35, s * 1.4, Math.max(3, s * 0.14));
    ctx.fillStyle = '#e24d4d'; ctx.fillRect(bx - s * 0.2, by - s * 0.35, s * 1.4 * b.hp, Math.max(3, s * 0.14));
  }
  f.agents.forEach((a, k) => {
    const cx = a.x * s + s / 2, cy = a.y * s + s / 2;
    ctx.globalAlpha = a.ko ? 0.35 : 1;
    ctx.fillStyle = SERIES[k % SERIES.length];
    ctx.strokeStyle = '#fff'; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(cx, cy, s * 0.34, 0, 7); ctx.fill(); ctx.stroke(); ctx.lineWidth = 1;
    ctx.fillStyle = '#fff'; ctx.font = `800 ${Math.floor(s * 0.38)}px system-ui, sans-serif`; ctx.fillText(String(k + 1), cx, cy + 1);
    if (a.stun && !a.ko) { ctx.strokeStyle = '#fbb315'; ctx.setLineDash([3, 3]); ctx.beginPath(); ctx.arc(cx, cy, s * 0.48, 0, 7); ctx.stroke(); ctx.setLineDash([]); }
    if (a.hp !== null && a.hp !== undefined) {   // v2: a small health bar under the agent
      ctx.fillStyle = '#1b2430'; ctx.fillRect(cx - s * 0.4, cy + s * 0.38, s * 0.8, Math.max(2, s * 0.1));
      ctx.fillStyle = a.hp > 0.6 ? '#4fd67a' : a.hp > 0.3 ? '#ffd23f' : '#ff5d5d';
      ctx.fillRect(cx - s * 0.4, cy + s * 0.38, s * 0.8 * a.hp, Math.max(2, s * 0.1));
    }
    ctx.globalAlpha = 1;
  });
  const modeTxt = f.mode ? ` · ${{ race: 'Race', pvp: 'PvP', coop: 'Co-op', descent: 'Descent' }[f.mode]}` : '';
  $('watchInfo').textContent = `Episode ${f.episode} · step ${f.step}/${f.steps}${modeTxt}` + (f.done ? (f.cleared ? ' · board cleared!' : ' · time up') : f.stairs != null ? ' · stairs open' : '');
  $('watchAgents').replaceChildren(...f.agents.map((a, k) => el('div', { class: 'agent' },
    el('span', { class: 'dot', style: `background:${SERIES[k % SERIES.length]}` }),
    el('span', {}, `${k + 1}. ${a.label}`), el('span', { class: 'sc' }, fmt(a.score)),
    el('span', { class: 'meta' }, `${a.tiles} tiles · ${a.mines} mines hit` +
      (a.hp !== null && a.hp !== undefined ? ` · ${Math.round(a.hp * 100)} HP · ${a.kos} KOs · ${a.bossDmg} boss dmg` : '') +
      ` · last: ${actionName(a.act)}${a.ko ? ' · knocked out' : a.stun ? ' · stunned' : ''}`))));
  if (f.prefs) {
    const top = f.prefs.map((p, a) => [p, a]).filter(([p]) => p > 0.001).sort((x, y) => y[0] - x[0]).slice(0, 6);
    $('prefs').replaceChildren(...top.map(([p, a]) => el('div', { class: 'pref' },
      el('span', {}, actionName(a)), el('span', { class: 'track' }, el('span', { class: 'fill', style: `width:${(p * 100).toFixed(1)}%;display:block` })),
      el('span', { class: 'p' }, `${(p * 100).toFixed(0)}%`))));
  }
}

// ------------------------------------------------------------------ arena tab
function renderRooms() {
  $('roomList').replaceChildren(...S.rooms.map((r) => el('option', { value: r.name })));
  const box = $('rooms');
  if (!S.rooms.length) { box.replaceChildren(el('p', { class: 'muted' }, 'No active rooms. Open the game, or add a bot to create a room.')); return; }
  box.replaceChildren(...S.rooms.map((r) => el('div', { class: 'card room' },
    el('h3', {}, r.name, el('a', { href: `/?room=${encodeURIComponent(r.name)}`, target: '_blank', class: 'muted small' }, 'Join ↗')),
    el('div', { class: 'muted small' }, `${r.state === 'playing' ? `${r.safeLeft} safe tiles left` : 'Round over'} · ${r.players.length} players`),
    el('ul', {}, [...r.players].sort((a, b) => b.score - a.score).map((p) => el('li', {},
      el('span', { class: 'sw', style: `background:${p.color}` }), el('span', { class: 'nm' }, `${p.name} (${p.char})`),
      p.bot ? el('span', { class: 'tag', title: `model ${p.model}` }, `BOT · ${p.difficulty}`) : el('span', { class: 'tag' }, 'HUMAN'),
      el('b', {}, String(p.score)),
      p.bot ? el('button', { onclick: () => send({ t: 'removeBot', room: r.name, id: p.id }) }, 'Remove') : null))))));
}
$('bAdd').onclick = () => {
  if (!$('bModel').value) return toast('Save a model first. There is nothing to deploy yet.', true);
  send({ t: 'addBot', room: $('bRoom').value || 'lobby', model: $('bModel').value, difficulty: $('bDiff').value, char: $('bChar').value });
};

function renderAll() {
  renderPresets(); renderModels(); renderRooms(); renderProgress();
  $('bDiff').replaceChildren(...S.difficulties.map((d) => el('option', { value: d }, d)));
  $('bDiff').value = 'normal';
  $('bChar').replaceChildren(el('option', { value: '' }, 'Random'), ...S.characters.map((c) => el('option', { value: c }, c)));
  $('runSel').replaceChildren(el('option', { value: '' }, 'Current run'), ...S.runs.map((r) => el('option', { value: r }, `Past run: ${r}`)));
  if (S.cfg) setBoardInputs(S.cfg);
}

connect();
