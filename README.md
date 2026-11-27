# Mine Field 3D

A multiplayer, real-time, competitive minesweeper in a 3D world. Each player is a character walking through one shared minefield. Everyone digs at once.

The minefield is either a **dungeon**, with rooms and corridors to explore and a new one generated every round, or the classic **open field** (32×32). The first player into a room chooses which.

## Run it

```
start.bat
```

Or run `.venv\Scripts\python server.py --port 8080` yourself. The first time, `start.bat` creates `.venv` and installs `aiohttp`.

Then open **http://localhost:8080**. Other people on your network can join at `http://<your-PC's-IP>:8080`. You may need to allow Python through Windows Firewall. To play over the internet, forward the port or use a tunnel such as ngrok or Cloudflare Tunnel.

**On a home server (Docker, e.g. Proxmox):** see [DOCKER.md](DOCKER.md). `./update.sh` pulls the latest code and rebuilds, and player data and models are kept. `--no-lab` (or `MF3D_LAB=0`) turns off the AI lab, which has no login.

### Playing over the internet

The server has some protection built in for when strangers can reach it:

- **Message limits:** each connection may send 40 messages per second on average. Floods are dropped, and a connection that keeps flooding is disconnected. Messages over 4 KB close the connection.
- **Trimmed text:** names and room names are cut to 16 and 24 characters. Chat is quick-chat only (fixed phrases), so there's no free text to moderate.
- **Reconnecting:** if your connection drops (a phone switching networks, a page reload), the game reconnects on its own. You keep your place, score, health and items for 45 seconds.
- **No CDN needed:** Three.js is bundled in `static/vendor/`, so the game also works without internet access.

There are no accounts or passwords. Anyone with the address can join, so only share it with people you'd invite.

The join screen has an **Open rooms** list showing every game in progress: its mode, map and realm, who's playing, how far the round has got, and whether a boss is out. Press **Join** to jump in with the character you've picked. To start your own room, type a new name and choose its mode, map and realm. It appears in everyone's list straight away. Rooms hold up to 12 players and close 45 seconds after the last person leaves, which leaves time for anyone who dropped to reconnect.

Players who enter the same **room** name play on the same board. You can share a direct link like `http://host:8080/?room=friday`. Add `&name=Bob&autojoin=1` to skip the join screen.

**Watching:** press **Watch** on any open room, even a full one, to spectate it. The camera follows one player; switch with ← → or Tab, or the ◀ ▶ buttons. A link like `http://host:8080/?room=friday&spectate=1` opens straight into watching.

## Replays and the run recap

When a round ends (or a Descent run is over), the results screen adds a **recap**:
- a chart of every player's score over the round, with the key moments marked along the bottom (hover for the scores at any point);
- a table of who did what: tiles dug, mines hit, knockouts, rivals knocked out, boss damage and kills, pickups, spike hits;
- the key moments: bosses beaten, the vault opened, the chest found, floors cleared, knockouts.

Every round with a person in it that lasts at least 10 seconds is also saved as a **replay**. A Descent run is one replay across all its floors.
- **Watch replay** on the results screen opens it in a new tab, and **Copy link** copies a link to share. Add `&t=90` to a link to start 90 seconds in.
- The join screen lists **Recent replays** with a Watch button.
- A replay plays like spectating: the camera follows one player (← → or Tab to switch). The bar at the bottom has play and pause (Space), a timeline you can drag, the key moments as dots you can click, and speeds from ½× to 8×.
- The server keeps the newest 60 replays in `data/replays/`. A replay holds only what any spectator could see: never resume or profile tokens, or radar sweeps.

## Daily dungeon

The top of the join screen shows **today's daily dungeon**. It has the same layout, mines, loot and realm for everyone all day; only the tiles right around your first dig can differ, because the first dig is always safe. It's always Race mode.

- **The board:** clear it to get on today's leaderboard of top scores and fastest clears, one entry per name.
- **Retries:** the same map comes back every round, so you can try to beat your time.
- **Saving:** leaderboards are kept for 14 days in `data/daily.json`.

## Rules

| Action | Points |
|---|---|
| Reveal a safe tile (flood-fill counts every tile) | +1 each |
| Flag a mine (paid when the round ends) | +3 each |
| Someone digs up your flag and it was safe | −3 |
| Dig a mine | −10 and stunned for 3 s, knocked back |

- You can only dig or flag the tile you're standing on and the 8 tiles around it. A yellow square on the ground shows that area.
- The first dig of each round is always safe.
- You can't dig your own flag. You *can* dig someone else's flag, at your own risk.
- Click a revealed number whose mines are all flagged to clear the tiles around it (chording).
- When every safe tile is revealed, the round ends. Final scores show for 12 s, then a new field is laid.

## Game modes

The first player into a room picks the mode, along with the map and realm:

| Mode | How it plays |
|---|---|
| **Race** | Everyone for themselves. Most points wins. |
| **PvP** | Race, but your sword (**R** / ⚔) also hits other players for 15. Knocking someone out earns you **+20**. |
| **Co-op** | One team against the dungeon. See below. |
| **Descent** | Co-op, floor after floor, as deep as you can go. See below. |

How co-op works:

- **No friendly fire:** power-ups and swords never hurt teammates.
- **No scatter bombs:** they would only undo the team's work.
- **Tougher bosses:** boss health grows with the number of players.
- **Shared lives:** the team starts with 3 lives, plus 1 per player, shown as ♥ in the HUD. Every knockout costs one.
- **Winning and losing:** clear the dungeon to win. Run out of lives and the round is lost.

Add `?mode=pvp`, `?mode=coop` or `?mode=descent` to a link to preselect a mode.

### Descent

Descent plays by the co-op rules (one team, shared lives, no friendly fire, no scatter bombs), but clearing the dungeon doesn't end the game. It opens a **staircase down**, marked by a purple beam and a pulsing square on the minimap. Step on it, or wait 30 seconds, and the whole team descends to the next floor.

Clearing a floor gives everyone **+10 × the floor number** and the team **+1 life**. Correct flags pay out (+3 each) when the floor is cleared.

**The stairs shop:** while the stairs are open, a shop shows 3 random offers. Each player buys with their own points, and can buy each offer once per floor. Prices rise 15% per floor.

| Offer | Base price | Effect |
|---|---|---|
| Vitality | 40 | +20 max health for the rest of the run |
| Shield | 25 | Start the next floor with a shield |
| Boots | 20 | Start the next floor with 20 s of boots |
| Radar | 30 | A radar sweep around where you land on the next floor |
| Spare life | 60 | +1 team life; one per floor for the whole team |
| Supply drop | 30 | A random held power-up, right away (hands must be empty) |

**Floor modifiers:** from floor 2 on, every floor rolls a twist, never the same one twice in a row. It's shown on the floor banner and under the mode in the top-left panel:

| Modifier | Effect |
|---|---|
| Darkness | Fog closes in and the lights go out; a lantern lights the ground around you |
| Unstable ground | Every 10 s a 3×3 patch of dug ground caves back in, away from players |
| Rich veins | Every tile you dig is worth double points |
| Swarm | One extra boss, but every boss has 60% health |
| Treasure trove | Twice as many power-ups are buried |
| Volatile | Mines hit for 50 damage instead of 35 |
| Cursed ground | Flags won't stay planted: no flags on this floor |
| Flooded | Knee-deep water slows everyone to 70% speed, monsters too |

**Relics:** when a floor is cleared, everyone is also offered 3 relics they don't have yet and may take one, free. Relics last the whole run:

| Relic | Effect |
|---|---|
| Iron Skin | Take 25% less damage |
| Prospector | +50% points for every tile you dig |
| Brute | Your sword hits bosses 50% harder |
| Bloodthirst | Heal 4 HP every time your sword hits a boss |
| Sapper's Luck | Mines deal half damage to you |
| Iron Boots | Spike traps can't hurt you |
| Scavenger | Start every floor holding a power-up |
| Phoenix Feather | Once per floor, a knockout leaves you on 1 HP instead |
| Cartographer | A radar sweep where you land on every floor |

The relics you hold show under the floor's twist in the top-left panel.

**Elite bosses:** every 5th floor, one boss is an **elite** (Ogre Warlord, Wraith Queen or Golem Colossus): bigger, with 2.5× the health and a harder smash. Besides its smash it winds up a **quake**, a wide red ring (3.5 tiles) that hits everyone inside for 25 and stuns them, so back off when it winds up. Beating it pays double rewards and drops extra loot.

Every floor down is harder:

- **New realm:** Meadow → Lost Jungle → Dune Sea → Frostbite Tundra → Coral Reef → Haunted Hollow → Molten Caldera → Candyfloss Hills → Neon Grid → Lunar Base, then round again.
- **More mines:** the density goes up 7% per floor, capped at 21% of floor tiles.
- **Tougher bosses:** they get 20% more health per floor, and an extra boss joins every 3 floors, up to 3 more.

What carries over between floors:

- **Kept:** scores, lives, held power-ups and shields.
- **Refilled:** health goes back to full.
- **Lost:** timed effects (boots, gold rush) and the vault key.

The run ends when the team runs out of lives. It's then recorded on the **Deepest descents** board on the join screen (`data/descents.json`), and a new run starts at floor 1. Reaching floor 5 unlocks the **Lantern** hat.

**The weekly descent:** press **Play the weekly descent** on the join screen (room `weekly-2026-W48` for that ISO week). Every team gets the same floors all week: the same layouts, mines, loot, traps and floor twists, floor after floor. Runs go on that week's ladder, next to the all-time board.

## Health

You have **100 HP**, shown in the top-left panel and as a bar over every player.

| Hit | Damage |
|---|---|
| Mine | 35 |
| Scatter bomb blast | 25 |
| Shockwave | 10 |

At 0 HP you're **knocked out**: −15 points, you drop your held power-up, and you respawn somewhere else after 5 s at full health. Heal by eating **Apples** (+25) and **Health potions** (+60). They are dug up like other power-ups and are only picked up when you're hurt.

## Bosses

Dungeons are home to boss monsters. One boss roams at a time, or two when four or more people are playing. They wander the corridors and chase anyone they can see.

| Boss | Character |
|---|---|
| **Ogre** | 300 HP, swings a club for 30 damage. |
| **Wraith** | 180 HP. Fast, floats, hits for 20. |
| **Golem** | 450 HP. Slow, hits for 40. |

- **Dodging:** when a boss winds up, a **red circle** fills on the ground. Get out before it fills.
- **Fighting back:** press **R** (or the ⚔ button on mobile) to swing for 12. Scatter bombs (60), shockwaves (40) and the freeze ray (20, and it freezes the boss) all hurt bosses, and blasts briefly stagger them.
- **Rewards:** the player who lands the killing blow gets **+40**. Everyone who helped gets +1 point per 10 damage dealt. The boss drops a health potion and two power-ups.
- **Respawning:** a new boss appears 40 s later.

## The vault and spike traps

**The vault:** most dungeons have a vault, a side room sealed by a locked door with a gold padlock floating over it. The door is also marked in gold on the minimap.

- **The key:** it's buried under a safe tile somewhere else in the dungeon. Dig it up and walk onto it. It floats beside you while you carry it.
- **Opening:** walk up to the door with the key. It opens for everyone and you get **+15**.
- **Inside:** a **treasure chest** worth **+30** and extra power-ups.
- **Losing it:** if you're knocked out (or disconnect) carrying the key, you drop it. A scatter bomb that blows the key up buries it again somewhere else.
- **No shortcuts:** you can't dig into the vault from outside or blink into it.

**Spike traps** are buried under some safe tiles. Once dug up they stay visible as red grates and stab up every few seconds; they rattle just before. Standing on one while the spikes are up deals **15 damage** and a short stun, and a shield absorbs it.

## Talking to your team

- **Quick chat:** **1**–**6** send a phrase that pops up over your head: Help!, Boss here!, Nice!, Follow me, GG, Oops.
- **Pings:** **V** pings the tile under your cursor with a beam of light in your colour, also shown on the minimap.
- **On a phone:** the 💬 button opens both. Ping uses the tile you tapped, or the one marked for digging.

## Stats and hats

Your browser keeps a private profile id, and the server saves your stats under it: rounds, wins, tiles revealed, correct flags, bosses slain, co-op clears and daily dungeons. Stats unlock **hats**, which you choose on the join screen or with **Change character**:

| Hat | Unlock |
|---|---|
| Party hat | Play 3 rounds |
| Beanie | Reveal 500 tiles |
| Flower | Finish a daily dungeon |
| Horns | Land the killing blow on a boss |
| Top hat | Flag 100 mines correctly |
| Crown | Win 3 rounds against other players (bots count) |
| Halo | Clear 2 co-op dungeons |
| Lantern | Reach floor 5 in a descent |

Locked hats show your progress. Profiles live in `data/profiles.json`. Clearing your browser's site data gives you a fresh profile.

## Playing on a phone or tablet

Open the same address on your phone. It needs to be on the same network, or use a tunnel as described under "Run it". Touch controls appear automatically:

- **Left stick:** move. Push it all the way to sprint.
- **⛏ Dig** (the big yellow button): digs the tile marked with a **pulsing yellow square**, which is the covered tile you're facing. Hold it to keep digging as you walk.
- **⚑ Flag:** flags that same marked tile.
- **Tap:** a tile next to you digs it directly, and holding it flags it. Tapping a farther tile aims power-ups at it; then press **★ Use**.
- **⚔ Attack** and **⤒ Jump** buttons.
- **Drag** to turn the camera, **pinch** to zoom.

Phones use lighter graphics: lower resolution, softer shadows and less scenery. Landscape is the most comfortable way to hold the phone. Add `?touch=1` to the address to try the touch controls on a desktop.

**Hiding the browser bar:**
- **Full screen:** pressing **Join** or **Watch** on a phone switches the game to full screen, which hides the address bar. If you swipe out of it, tap the **⛶** button at the top to go back.
- **Install as an app:** Chrome on Android can install the game, which then opens from its own home-screen icon, full screen. Use **Install as an app** on the join screen, or the browser menu's **Install app** / **Add to Home screen**. Chrome only allows this over **HTTPS** (for example through a tunnel or once the game is hosted). On a plain `http://192.168…` address the home-screen icon opens a normal browser tab, so use full screen there instead.

## Power-ups

Some safe tiles have a power-up buried under them. Dig one up and it appears on the ground. Whoever walks onto it first gets it.

**Held** power-ups float over your head until you use them with **G**. You can carry one at a time.

| Held power-up | What it does |
|---|---|
| **Scatter bomb** | Aim at a tile up to 6 away. A purple square shows the blast area. After a short fuse it covers a 5×5 area again, scatters 6 fresh mines into it, and knocks out anyone caught inside for 1.5 s. Use it to undo a rival's progress or to make more ground to dig. |
| **Freeze ray** | Aim toward a rival. An ice beam (10 tiles) freezes the first player it hits in a block of ice for 4 s. |
| **Shockwave** | Knocks back and stuns everyone within 3 tiles of you for 1.5 s. A pink ring shows the range. |
| **Blink** | Teleport to any tile up to 8 away. |

**Instant** power-ups work as soon as you pick them up:

| Instant power-up | What it does |
|---|---|
| **Shield** | Absorbs your next mine, blast, freeze or shockwave completely. |
| **Gold rush** | Double points for every tile you reveal for 12 s. |
| **Radar** | Shows you, and only you, the mines within 4 tiles for 8 s. |
| **Boots** | 60% faster movement for 10 s. |

## Realms

When you create a room, pick the realm it takes place in:

| Realm | Setting |
|---|---|
| Meadow | Grass, pines and clouds. |
| Dune Sea | Sand, cacti, mesas and blowing dust. |
| Frostbite Tundra | Snowy pines, ice crystals and snowfall. |
| Molten Caldera | Basalt, lava, volcanoes and embers. |
| Lunar Base | Craters, glowing crystals, a planet in the sky, and **low gravity**. |
| Candyfloss Hills | Frosting fields, lollipops, candy canes, gumdrops, giant cupcakes, a chocolate river and falling sprinkles. |
| Lost Jungle | Broadleaf trees, ferns, crumbling ruins, a step pyramid and fireflies. |
| Coral Reef | Underwater: swaying kelp, corals, circling fish, light shafts, bubbles and **floaty gravity**. |
| Haunted Hollow | A moonlit graveyard: dead trees, tombstones, flickering jack-o'-lanterns and wisps. |
| Neon Grid | Synthwave: a glowing grid floor, a striped sunset, wireframe pyramids and floating cubes. |

Choose **Random** to have one picked for you. Everyone who joins later plays in the room's realm. Use `?realm=moon` in a link to preselect one.

## Characters

Pick one of 18 characters and a colour on the join screen: Miner, Robot, Knight, Wizard, Astronaut, Ninja, Cat, Dino, Pirate, Ghost, Mushroom, Penguin, Dragon, Mech, Alien, Viking, Skeleton or Bee. Use **Change character** in the top-left panel to switch at any time. If someone in the room already has your colour, you get the first free one.

## AI opponents and the training lab

Open **http://localhost:8080/lab** to evolve neural-network opponents. This needs PyTorch; see `requirements-ai.txt`.

1. **Training:** set the hyperparameters on the left (board, map layout, network size, population, mutation, reward weights) and press **Start training**. Set *Map layout* to **dungeon** to train bots on rooms and corridors like the game's dungeons.
   - **Model type 4** (the default) adds **power-ups**. Pickups in training are now the real ones: shields soak a hit, food heals, and the held items (scatter, freeze, shockwave, blink) fill the bot's item slot. A type 4 bot sees what it's holding and has a **Use item** action. It learns *when* to use an item; *where* to aim is the game's built-in rule (the nearest rival or boss in range, everyone around you for the shockwave, and the dug-up spot with the most hidden ground for a blink).
     - **Warm start:** a type 3 (or type 2) model with the same vision radius and layers can seed a type 4 run. It starts out using items whenever they'd hit something, like the built-in rule, and evolution learns when holding on is better.
     - The Progress tab adds an "Items used" line.
   - **Model type 3** trains bots for the whole dungeon. On top of everything type 2 sees, they see **spike traps** (and whether the spikes are up), **pickups** and a **goal**: the stairs once a Descent floor is cleared, or the vault door while carrying the key. They learn **Descent** as a fourth mode.
     - On training boards, revealed traps hurt while their spikes are up, pickups pay a small reward (food heals, and is only taken when hurt), and a cleared Descent board opens stairs 2–4 tiles away that everyone is rewarded for reaching.
     - *Descent practice* (0.5 by default, LIVE) starts that share of Descent boards almost fully dug, so finishing a floor and finding the stairs comes up often enough to learn.
     - **Warm start:** pick a type 2 model with the same vision radius and layers (such as **allmodes**) in *Start from model*. The type 3 run keeps everything it knew and starts out blind to the new inputs, so it plays exactly like the old model until evolution finds a use for them.
   - **Model type 2** trains bots that play Race, PvP and Co-op. They see their own health, the boss and its wind-up danger zone, which players are teammates, and which mode they're in. They can **attack**.
   - *Game mode* **mixed** gives each training board a random mode (Race, PvP, Co-op, and Descent for types 3 and 4), so one model learns them all.
   - In Co-op, every bot is scored on the team's average, so they learn to work together. In PvP, knocking out a rival pays.
   - *Bosses* adds a boss to every training board.
   - **Model type 1** is the classic minesweeper-only bot.
   - The starter **allmodes** model is a type 2 bot trained this way.
   - The Progress tab shows knockouts and boss damage for type 2 and 3 runs, plus spike hits and pickups for type 3.
   - **Curriculum** (all LIVE): untrained bots tend to settle on wandering, because walking costs nothing and digging might hit a mine.
     - *Dig practice* starts that share of boards part-dug, with every bot standing at the edge of the dug area, so there's always something to dig next to it. Try 0.5 at first, and lower it as "Safe digs" climbs.
     - *Ease in over N generations* starts easy and gets harder. Mines start at *Mines at the start* (a share of the Mines setting) and the mine penalty at *Mine penalty at the start*, and both rise in a straight line to the values you set. Cheap mistakes early let bots find out that digging pays; rising costs then favour the bots that pick safe tiles. The Progress tab shows how far the ease-in has got. Fitness falls as the boards get harder, which is expected.
     - The **dig-trainer** config (game density, race, no bosses, one bot per board) is a good place to start.
   - **Rewarding careful digs:** *Per safe dig* (+1 by default) pays once for every dig that opens safe ground. *Per tile revealed* pays for every tile, so a lucky dig that floods a big empty area earns far more than a careful dig next to a number. Paying for safe digs as well makes every correct deduction count. The Tiles chart shows "Safe digs" alongside.
   - **Stopping time-wasting:** untrained bots like to toggle a flag on and off, a "safe" way to pass a turn. Two rewards discourage it:
     - *Per step* (−0.02 by default) makes every turn cost a little;
     - *Removing own flag* (−0.5) charges for taking your own flag back off.
     
     The Flags chart shows "Removed (toggles)" so you can watch the habit fade. These only shape training; the game's scoring is unchanged. Each generation, every network plays several boards on the GPU. The best are kept and the rest are replaced by mutated copies of winners. Fields marked LIVE can be changed mid-run, and that includes **every reward**: edit them and press *Apply live changes*, and the next generation is scored with the new values. Fitness is re-measured from scratch every generation, so nothing stale carries over, but the fitness chart will jump when the rewards change. You can save configs and continue training from a saved model.
2. **Progress:** live charts of fitness, tiles revealed, mines hit and flag accuracy, plus a table of every generation. You can also load past runs.
3. **Watch:** see the current best network, or up to 6 saved models, play live on a top-down board, on a field or a dungeon. The side panel shows what the network is weighing for its next move. **Brain activity** under the board animates bot 1's neural network as it plays:
   - **left:** the tiles it can see;
   - **middle:** its hidden neurons lighting up;
   - **right:** the probability of each action, with the chosen one ringed;
   - **connections:** the strongest connections are drawn, with pulses that follow the signal on every step.

   Hover a neuron to read its value. `lab.html#watch=demo` opens straight into this view.
4. **Models & matches:** rename, delete or continue training saved models, and pit 2–6 of them against each other over hundreds of games.
5. **Deploy bots:** add a model to any game room as a player with a character and a difficulty (how fast it acts). Bots follow exactly the same rules as people.
   - Type 2 bots read the room's mode, their health, nearby bosses and their teammates, and decide for themselves when to attack.
   - Type 3 bots also decide for themselves about traps, pickups and food, and walk to the stairs or the vault door when it is within 4 tiles; further away, a built-in path-finder takes them there.
   - Type 4 bots also decide when to use their held power-up (the game aims it for them).
   - Types 1 and 2 use built-in rules for food, traps, the key and the stairs. Types 1–3 use held power-ups by a built-in rule.

Models are saved in `models/`, configs in `configs/` and run histories in `runs/`.

## Tutorial and settings

**New here? Learn to play** on the join screen opens a private practice field: a small open square with a few mines, no traps and no monsters. A panel at the top walks you through nine steps, each finished by doing it:
1. move;
2. dig;
3. read the numbers;
4. flag a mine;
5. clear around a number;
6. pick up a power-up;
7. use it;
8. beat a training golem (it never fights back);
9. finish the field.

Practice rounds don't count towards your stats, aren't recorded as replays and don't show in the lobby. **Leave the tutorial** goes back to the join screen at any time.

**⚙ Settings** (on the join screen, and next to *Change character* in a game; `#settings` in the address opens them directly) are saved in this browser:
- **Volume**, and a **Screen shake** switch.
- **Camera turn speed**, for Q/E, middle-drag and touch drag.
- **Colour-blind friendly numbers:** 2 becomes orange and 3 magenta, so they no longer depend on telling green from red. It applies at once.
- **Show the controls help** at the bottom of the screen.
- **Graphics:** Auto (lighter on phones), High or Low. Low means a lower resolution, smaller shadows and less scenery. A reload applies it, and you rejoin your game.

## Controls

WASD / arrows to move · Shift to sprint · Space to jump · Q/E or middle-drag to rotate the camera · mouse wheel to zoom
Left-click to dig · Right-click or F to flag · G to use a held power-up · R to attack · 1–6 quick chat · V ping

## Files

- `server.py`: the authoritative game server (aiohttp HTTP + WebSocket). It handles rooms, mine generation, scoring and reach checks. Tune `W`, `H`, `MINE_DENSITY`, `REACH`, etc. at the top.
- `store.py`: saved player profiles (stats and hat unlocks) and the daily leaderboard, as JSON in `data/` (or `$MF3D_DATA`).
- `replays.py`: records rounds for replays and builds the run recap; saves replays in `data/replays/`.
- `static/game.js`: the Three.js client (rendering, movement, effects, sound). Three.js 0.160 is bundled in `static/vendor/`.
- `static/index.html`, `static/style.css`: the page and HUD.
- `tests/`: the test suite (below).

## Tests

```
.venv\Scripts\python -m unittest discover -s tests
```

The suite covers the game rules, the vault, traps, the daily dungeon, profiles, replays and the recap, the WebSocket protocol, and the AI simulator.

- **Protocol tests:** these run against an in-process server (rate limits, resume, spectators, chat).
- **AI simulator tests:** these run on the CPU, so they won't slow a training run, and they're skipped without PyTorch.
- **Speed:** the whole suite takes a few seconds.

## License

[MIT](LICENSE)
