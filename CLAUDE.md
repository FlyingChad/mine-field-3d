# Mine Field 3D

Real-time multiplayer competitive minesweeper in a 3D world. Players are avatars walking a shared minefield in the browser: either a dungeon of rooms and corridors (a new one every round) or an open 32×32 field. A Python server is authoritative over all game state.

## Run

- Windows: `start.bat` (creates `.venv` and installs `aiohttp` on first run), or `.venv\Scripts\python server.py --port 8080`
- Open http://localhost:8080. `?room=x&name=y&char=wizard&realm=moon&layout=dungeon&autojoin=1` skips the join screen, which is useful for testing.
- Node is **not** installed on this machine. Python 3.11 is. There is no JS build step: the client is plain ES modules, and Three.js 0.160.0 comes from the jsDelivr CDN through an importmap in `static/index.html`.

## Layout

- `server.py`: aiohttp app that serves `/`, `/static/*` and the `/ws` WebSocket. Game rules live in `Room`: layout, lazy mine generation that keeps the first dig safe, flood-fill, chording, flags, scoring, health, power-ups, round end and restart. Tunables are constants at the top (`W`, `H`, `MINE_DENSITY`, `REACH`, `STUN_SECONDS`, scoring, health, items, `TICK_HZ`).
- `layouts.py` (pure Python, shared by `server.py` and `ai/env.py`): which tiles of the W×H grid (48×48) are floor.
  - `field` is a `FIELD_SIZE`² square in the middle.
  - `dungeon` is rooms joined by L-shaped corridors (a spanning tree plus a few loops); the outer ring is always wall.
  - Rules on a layout:
    - walls are never mined, revealed, flagged or reachable;
    - `Room.nb()` gives floor-only neighbours (use it for flood fill, chording and blast rims);
    - `Room.is_floor()` guards every target tile;
    - mines = `MINE_DENSITY` × floor tiles, so use `room.n_mines` / `len(room.mines)`, never `MINES`;
    - players spawn with `Room.place()`.
  - Each dungeon round generates a new layout, and the `round` message carries `spawns`.
  - In dungeons the server ignores `move`s whose centre is inside a wall; the client collides with walls (`solidAt`).
- **Health** (`MAX_HP`, `*_DAMAGE`, `KO_PENALTY`, `RESPAWN_SECONDS`, `FOOD`):
  - mines, scatter blasts and shockwaves deal damage through `Room.hurt()`, which queues knockouts; call `flush_kos()` after broadcasting the event;
  - at 0 HP a player loses points, drops their held item and is stunned until `Room.respawns()` puts them back on a random floor tile at full HP;
  - food (`apple`, `potion`) is a power-up that is only picked up when hurt.
  - Health is game-layer only, not in `ai/env.py`. Hurt bots walk toward visible food (a heuristic in `update_bots`).
- **Bosses** (`server.py` `Boss`, `BOSS_*` and `ATTACK_*` constants; models in `static/bosses.js`):
  - Kinds: `ogre`, `wraith`, `golem`; ids must match `BOSS_KINDS` and `BOSSES`. Only dungeon layouts have bosses (1, or 2 with 4+ players).
  - Behaviour (`Room.update_bosses`, every tick): wander with BFS paths (`Room.bfs`, 8-way, never cutting wall corners), chase the nearest player in `aggro` range with line of sight, then a telegraphed wind-up (`bossAtk`) → `boss_smash` (damage via `hurt()`, shield absorbs).
  - Players hurt bosses with `attack` (melee, `ATTACK_*`) and power-ups (`BOSS_POWER_DAMAGE`; shockwaves and blasts stagger them, freeze freezes them).
  - `damage_boss` → `boss_down`: rewards, loot (items may sit on unrevealed tiles) and a respawn timer.
  - Bosses ride in the 15 Hz `players` message as `b` rows. Bot heuristics: swing at bosses in range, and treat bosses as targets in `bot_use`.
  - Not in `ai/env.py`.
- **Lobby:** `GET /api/rooms` (`lobby_summary()`) lists open rooms with public info only: name, mode, layout, realm, state, player names, colours and scores, progress, bosses and lives.
  - The join screen polls it every 3 s while open (`refreshLobby` / `renderLobby` in game.js). Join buttons fill the room field and submit.
  - Typing an open room's name shows `#roomNote` and dims the new-room settings, since those only apply when creating a room.
  - Rooms close when their last human leaves. Joining a room with `MAX_PLAYERS` players gets `error {message}`; the client closes the socket and shows the message.
- **Game modes** (`Room.mode`, `MODES`; chosen by the room's creator like realm and layout):
  - `race` is the original game.
  - `pvp`: `Room.attack` also hits players (`PVP_MELEE_*`), and `hurt(..., by=)` credits `KO_REWARD` to whoever caused the knockout.
  - `coop`:
    - `hits_players()` is False, so no power-up or melee hits teammates;
    - no scatter bombs are generated or dropped;
    - boss HP scales with the player count;
    - `room.lives` is a shared pool (`COOP_LIVES_BASE` + 1 per player). Every KO costs one, and at 0 `flush_kos()` ends the round with `failed=True`.
  - Any new damage source must pass `by=` to `hurt()` and respect `hits_players()`.
- **Touch / mobile** (game.js `IS_TOUCH`, `body.touch` CSS; `?touch=1` forces it on desktop):
  - Controls: a pointer-events joystick (analogue; full tilt sprints) and Dig / Flag / Attack / Use / Jump buttons.
  - Dig and Flag act on `digTarget()`, shown by the pulsing yellow `digMark`: the tapped tile if it's in reach, else the hidden tile in the facing direction (`me.r`), else the hidden neighbour closest to it. Holding Dig repeats every 320 ms.
  - View gestures: tap = aim at the tile (`touchAim`, for power-ups too) and dig it if it's in reach; long-press = flag; one-finger drag turns the camera; pinch zooms.
  - With touch, `updateHover()` reads `touchAim` instead of the mouse.
  - Phones render at pixel ratio ≤ 1.5 with a 1024 shadow map, and realms get `ctx.quality = 0.5`, which halves instanced props and weather.
  - Headless Chrome won't go below about 500 px wide, so test portrait at 520×1000 and landscape at 844×390.
- `static/game.js`: the whole client:
  - the Three.js scene and instanced tile meshes (`refreshBoard()` rebuilds them from `tiles`);
  - `setLayout()`, which positions the per-tile base blocks and dungeon walls;
  - avatars with health bars, movement with wall collision, and the camera;
  - mouse picking, effects and WebAudio sounds;
  - the HUD and minimap (`drawMinimap`);
  - the character, realm and map picker;
  - networking (`handle()`).
- `static/realms.js`: the worlds a room can take place in (`meadow`, `desert`, `tundra`, `volcano`, `moon`, `candy`, `jungle`, `reef`, `spooky`, `neon`). Each realm defines:
  - a palette: sky, fog, lights, ground, cover and slab colours, plus `wall` = [side, top] for dungeons;
  - a `gravity` multiplier for jumping;
  - `decor(ctx)`, which builds scenery and weather into `ctx.group` and registers per-frame callbacks with `ctx.tick(fn(dt, t, me))`.
  - Scenery helpers: `instanced()`, `around()`, `weather()`, `clouds()` and `starfield()`.
  - `buildWorld(realmId, extent)` in game.js tears down the old realm and builds the new one.
  - Ids must match `REALM_IDS` in `server.py`. Whoever creates a room picks its realm and layout; later joiners get the room's.
  - Keep covers, slabs and walls clearly different colours, so numbers and walls stay readable from the overhead camera.
  - Thin GL lines (GridHelper) don't render reliably, so draw floor grids as textures.
- **Power-ups** (`server.py`, the `ITEM_*`, `THROW_RANGE` and `SCATTER_*` constants): `ITEMS_PER_ROUND` items are buried under random safe tiles. Digging a tile exposes its item, and walking onto it picks it up (`Room.pickups`, run every tick).
  - `scatter` is held and thrown with G. After `SCATTER_FUSE` it re-covers a (2R+1)² area, wipes the flags, craters and items in it, and scatters `SCATTER_MINES` new mines there. The total mine count can therefore change, so use `len(room.mines)`, never `MINES`, once mines exist.
  - `shield` absorbs one mine or blast.
  - `radar` privately sends the nearby mines to its holder.
  - `boots` is a speed multiplier; movement is client-side for humans and server-side for bots.
  - `gold` multiplies reveal points by `GOLD_MULT` for `GOLD_SECONDS`.
  - Held items (`HELD`: `scatter`, `freeze`, `shockwave`, `blink`) take the player's single item slot and are used with G (`use {x, y}` → `Room.use`, which checks the range for each item).
  - `freeze` fires a beam `FREEZE_RANGE` tiles long. The first other player within `FREEZE_WIDTH` of the beam is frozen: stunned, plus `frozen_until` for the ice visual.
  - `shockwave` stuns everyone within `SHOCK_RADIUS`.
  - `blink` teleports the user; the server sets a short `move_lock` so stale client `move`s can't undo it.
  - A shield absorbs a mine, a blast, a freeze or a shockwave (`Room._absorb`).
  - Adding a power-up means four changes:
    - an `ITEM_WEIGHTS` entry, plus a `HELD` entry if it is held;
    - its effect in `Room.pickups` (instant) or `Room.use` (held);
    - a bot heuristic in `Room.bot_use`;
    - on the client, `ITEM_INFO`, `itemModel()` and a message handler in game.js, plus an fx bit if other players need to see its effect.
  - Power-ups are **not** simulated in `ai/env.py`. Bots pick them up by walking over them and use them through the heuristics in `Room.bot_use`.
- `static/characters.js`: 18 procedurally built characters, including dragon, mech, alien, viking, skeleton and bee. Each one is a `build(color)` that returns `{root, upper, feet, top, tick?}`. The player's colour is the character's accent.
- `static/index.html`, `static/style.css`: the join/picker panel, HUD and results overlay.

## AI opponents (neuroevolution) — `ai/`

- `ai/env.py` `MineEnv`: a vectorised PyTorch copy of the game rules on a tile grid. It runs N boards × A agents as tensors, on the GPU during training. There are 26 actions: 8 moves, 9 digs and 9 flags within reach. `encode()` and `action_mask()` are standalone functions shared with the in-game bots. **Any rule change in `server.py` must be mirrored here**, or bots will train on a different game from the one they play.
  - **Model versions.** v1 is classic minesweeper: 10 channels + 3 globals, 26 actions. v2 plays every mode:
    - 13 channels: v1's plus boss, danger (boss wind-up zone) and ally; out-of-bounds stays the last channel;
    - 13 globals: v1's 3, own HP, mode one-hot, and boss direction / distance / present / HP / winding-up;
    - 27 actions: the 27th is `ATTACK`.
    - `Spec.version` is stored with the model; old files load as v1. `obs_dim(r, version)` and `n_actions(version)` give the sizes.
    - `env.observe(a, r, version)` and `env.mask(a, version)` serve both, so v1 and v2 models can share a board.
  - `rich=True` (on whenever training v2) mirrors the game's newer layers in tile/step units (`RICH`):
    - health and KO/respawn;
    - a boss per board (`bosses=True`): delay, chase, wind-up, smash, cooldown;
    - attack: boss damage, or in PvP a rival;
    - modes per board (`mode` = race / pvp / coop / mixed): PvP KOs pay `pvp_ko`; co-op has no friendly fire, and `env.fitness()` gives every agent the team average.
    - Not simulated: power-ups, food, co-op shared lives, boss line of sight, boss HP scaling.
    - Change these in `RICH` alongside the server constants.
  - In the game, `server.update_bots` passes v2 brains an `extra` dict: HP, mode, allies, nearest boss with wind-up state, and attack_ok. The network's attack replaces the "swing at bosses" heuristic, which v1 bots still use.
  - `layout="dungeon"` samples boards from a cached bank of `layouts.dungeon()` maps (`self.floor`). In that mode `mines` is a density.
  - Reward shaping (training only, not game scoring): `step` (lab default −0.02) and `unflag` (lab default −0.5, charged when an agent removes its own flag) stop bots toggling a flag to pass turns. `stats["unflags"]` is charted in the Flags plot. Both lab fields are LIVE.
  - Walls block moves and digs, and appear in the observation's out-of-bounds channel.
  - In-game bots pass `room.floor` into `Brain.decide()` so they see walls the same way.
- `ai/policy.py` `Spec`: an MLP whose weights are a flat vector, so the whole population runs in one `baddbmm`. The input is a (2r+1)² × 10-channel window plus 3 global features (`obs_dim`).
- `ai/evolve.py`: the genetic algorithm (elites, tournament selection, optional uniform crossover, Gaussian mutation with σ decay). `SCHEMA` defines every hyperparameter, and the lab builds its form from it. To add a setting, add it to `SCHEMA` and read it from `cfg`. `train_process` runs in a spawned process. `run_match` runs head-to-head games.
- `ai/lab.py`: the `/lab` page and `/lab/ws` WebSocket. It starts and stops the trainer process over mp queues, streams generations, runs live watch games (CPU), matches, model and config management, and bot deployment through callbacks into `server.py`.
  - Each watch `frame` carries `net` (from `Lab._net`, built on `Spec.trace()`): bot 1's vision window, up to 40 hidden units per layer (chosen once by outgoing weight norm, so the picture stays stable), action probabilities, and the top signed contributions (activation × weight) between layers.
  - `netView` in lab.js animates it.
  - `lab.html#watch=demo` opens straight into watching saved models.
- `static/lab.html`, `static/lab.js`, `static/lab.css`: the lab UI, in plain JS. Charts are hand-built SVG using the dark categorical palette in a fixed order (`--s1..--s6` in lab.css).
- `ai/bots.py` `Brain`: turns a live `server.Room` into the training observation and returns an action. `server.BotPlayer` walks tile to tile and calls the same `Room.dig` and `Room.flag` as humans, so it follows the same reach, cooldown and stun rules.
- Starter models: `demo` (v1, classic) and `allmodes` (v2, trained on mixed modes in dungeons with bosses).
- Files: `models/*.pt` (dict: name, spec, flat weights, meta, loaded with `weights_only=True`), `configs/*.json` (saved lab configs), `runs/*.json` (generation history per run).
- PyTorch is the CUDA 12.8 build (the GPU is an RTX 5070 Ti, Blackwell). Install it with `pip install torch --index-url https://download.pytorch.org/whl/cu128`. Without torch the game still runs and the lab is disabled.
- In multi-agent boards, the acting order is shuffled per board every step. Acting first matters because the first dig of a board is guaranteed safe. A self-match should come out about 50/50, so use that as a fairness check.

## Conventions and invariants

- **The server is authoritative** for tiles, flags, scores, stun and reach. Clients send intents (`dig`, `flag`, `move`, `look`) and render what the server broadcasts. Never trust the client for game outcomes.
- **Reach:** players may only dig or flag their own tile and the 8 tiles around it (`REACH = 1`). The client checks by tile index. The server checks against the player's actual position plus a `REACH_SLACK` of 0.3 tiles for lag. Keep both sides consistent.
- **Coordinates:** tile `(x, y)` has its world centre at `((x - W/2 + 0.5) * TILE, (y - H/2 + 0.5) * TILE)` on the XZ plane, with `TILE = 2`. World z corresponds to tile y. Covers are 0.6 tall, revealed slabs sit at about 0.1, and the grass outside the board is at -0.5.
- **Tile values on the client:** `-3` wall / not in the layout, `-2` hidden, `-1` exploded mine, `0..8` revealed count.
- **Character ids** must match in three places: `CHARACTER_IDS` in `server.py`, `CHARACTERS` in `static/characters.js`, and the `COLORS` palette shared by `server.py` and `game.js`.
- Characters face +Z, stand on y = 0 and are built only from Three.js primitives (no external assets). New ones go in `characters.js` and in `CHARACTER_IDS`.
- Player-supplied strings (names, rooms) are rendered with `textContent` or canvas, never `innerHTML`.

## WebSocket protocol (JSON, field `t` is the type)

Roster entries for bots also carry `bot: true, model, difficulty`.
Client → server: `join {name, room, char, color, realm, layout, mode}`, `move {x, z, r}` (about 15 Hz), `dig {x, y}`, `flag {x, y}`, `attack`, `use {x, y}` (held item; `throw` is an old alias), `look {name, char, color}`.
Server → client:
- `error {message}` (join refused, e.g. room full)
- `welcome {id, room, cfg:{…, realm, throwRange, scatterRadius, bootsSpeed, freezeRange, blinkRange, shockRadius, held, maxHp}, spawn, snapshot}` (the snapshot includes `layout` (W*H string of 0/1), `layoutKind` and `items:[[x,y,kind]]`)
- `roster {players:[{id,name,color,char}]}`
- `players {p:[[id,x,z,rot,score,stunLeft,fx,hp]]}` (15 Hz tick; `fx` bits: 1 shield, 2 boots, 4 gold rush, 8 frozen; `fx >> 4` is the index of the held item in `cfg.held`)
- the `players` message also has `b:[[id,kind,x,z,rot,hp,maxHp,state]]` (state 0 wander, 1 chase, 2 wind-up, 3 frozen, 4 stunned)
- `bossSpawn {id, kind, name, x, z}`, `bossAtk {id, x, z, r, t0}` (wind-up telegraph), `bossSmash {id, x, z, r, hit, shielded, damage, stun}`, `bossHit {id, by, dmg, hp, x, z}`, `bossDown {id, name, killer, x, z, loot:[[x,y,kind]], rewards:{pid:pts}}`, `swing {pid}`
- `ko {pid, penalty, respawn, by, reward, lives}` (`by`/`reward` in PvP, `lives` in co-op), `respawn {pid, x, z, hp}`, `hitPlayer {pid, target, shielded, dmg, x, z}` (PvP melee)
- `cfg.mode` in `welcome`, and `mode`/`lives` in snapshots; `over` also carries `mode`, `failed` and `team` (the co-op total)
- `zap {pid, from:[x,z], to:[x,z], target|null, shielded, dur}`, `shock {pid, x, z, r, hit, shielded, stun}`, `blink {pid, from, to}`
- `reveal {pid, tiles:[[x,y,v]], gain, penalties, items:[[x,y,kind]], minesLeft, safeLeft}`
- `boom {pid, x, y, penalty, stun, damage, shielded, flagOwner, minesLeft}`
- `flag {x, y, pid|null, minesLeft}`
- `pickup {pid, x, y, kind, dur, heal?, hp?}`
- `radar {mines:[[x,y]], dur}` (sent only to the player who picked it up)
- `throw {id, pid, x, y, fuse, r}`
- `scatter {id, pid, x, y, r, added, tiles:[[x,y,v]], hit, shielded, stun, minesLeft, safeLeft}` (tiles set to `-2` are covered again; rim tiles carry their new counts)
- `over {results, mines, next, duration}`
- `round {snapshot, spawns:{pid:[x,z]}}`

## Testing

There is no test suite in the repo yet. What has worked so far:
- Drive `server.Room` directly from a Python script with a fake websocket (an object with an async `send_str`) to test rules, reach and the round lifecycle.
- Use `aiohttp` client scripts as bots for end-to-end protocol checks.
- For visual checks, use headless Chrome: `chrome.exe --headless=new --use-angle=swiftshader --enable-unsafe-swiftshader --screenshot=out.png --virtual-time-budget=6000 "http://localhost:8080/?name=T&autojoin=1"`. Add `--enable-logging=stderr` and grep for `Uncaught` to catch JS errors.
- Restart the server after editing `server.py`, `layouts.py` or anything in `ai/`. Static files are served fresh.
- Rule tests with fixed coordinates are easiest on a whole-grid field: set `server.FIELD_SIZE = 48` and use `Room(name, realm, "field")`. `python layouts.py 48 48` prints a sample dungeon.
- Headless Chrome uses a slow software renderer. With `--timeout` (real time), busy scenes may not have processed any messages yet. Prefer `--virtual-time-budget`, which waits for the page.
- For AI changes: rule-check `MineEnv` on small boards (first dig is safe, counts match a conv of the mines, flood fill is complete, mine = −10 plus stun, flags score at episode end). Then drive `/lab/ws` with an aiohttp script (`start` → wait for `status: stopped` → `match` / `addBot`). `lab.html#watch` opens straight into the live watch view.
