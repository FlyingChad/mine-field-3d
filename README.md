# Mine Field 3D

A multiplayer, real-time, competitive minesweeper in a 3D world. Each player is a character walking through one shared minefield. Everyone digs at once.

The minefield is either a **dungeon**, with rooms and corridors to explore and a new one generated every round, or the classic **open field** (32×32). The first player into a room chooses which.

## Run it

```
start.bat
```

Or run `.venv\Scripts\python server.py --port 8080` yourself. The first time, `start.bat` creates `.venv` and installs `aiohttp`.

Then open **http://localhost:8080**. Other people on your network can join at `http://<your-PC's-IP>:8080`. You may need to allow Python through Windows Firewall. To play over the internet, forward the port or use a tunnel such as ngrok or Cloudflare Tunnel.

The join screen has an **Open rooms** list showing every game in progress: its mode, map and realm, who's playing, how far the round has got, and whether a boss is out. Press **Join** to jump in with the character you've picked. To start your own room, type a new name and choose its mode, map and realm. It appears in everyone's list straight away. Rooms hold up to 12 players and close when the last person leaves.

Players who enter the same **room** name play on the same board. You can share a direct link like `http://host:8080/?room=friday`. Add `&name=Bob&autojoin=1` to skip the join screen.

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

How co-op works:

- **No friendly fire:** power-ups and swords never hurt teammates.
- **No scatter bombs:** they would only undo the team's work.
- **Tougher bosses:** boss health grows with the number of players.
- **Shared lives:** the team starts with 3 lives, plus 1 per player, shown as ♥ in the HUD. Every knockout costs one.
- **Winning and losing:** clear the dungeon to win. Run out of lives and the round is lost.

Add `?mode=pvp` or `?mode=coop` to a link to preselect a mode.

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

## Playing on a phone or tablet

Open the same address on your phone. It needs to be on the same network, or use a tunnel as described under "Run it". Touch controls appear automatically:

- **Left stick:** move. Push it all the way to sprint.
- **⛏ Dig** (the big yellow button): digs the tile marked with a **pulsing yellow square**, which is the covered tile you're facing. Hold it to keep digging as you walk.
- **⚑ Flag:** flags that same marked tile.
- **Tap:** a tile next to you digs it directly, and holding it flags it. Tapping a farther tile aims power-ups at it; then press **★ Use**.
- **⚔ Attack** and **⤒ Jump** buttons.
- **Drag** to turn the camera, **pinch** to zoom.

Phones use lighter graphics: lower resolution, softer shadows and less scenery. Landscape is the most comfortable way to hold the phone. Add `?touch=1` to the address to try the touch controls on a desktop.

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
   - **Model type 2** (the default) trains bots that play **every mode**. They see their own health, the boss and its wind-up danger zone, which players are teammates, and which mode they're in. They can **attack**.
   - *Game mode* **mixed** gives each training board a random mode (Race, PvP or Co-op), so one model learns all three.
   - In Co-op, every bot is scored on the team's average, so they learn to work together. In PvP, knocking out a rival pays.
   - *Bosses* adds a boss to every training board.
   - **Model type 1** is the classic minesweeper-only bot.
   - The starter **allmodes** model is a type 2 bot trained this way.
   - The Progress tab shows knockouts and boss damage for type 2 runs.
   - **Stopping time-wasting:** untrained bots like to toggle a flag on and off, a "safe" way to pass a turn. Two rewards discourage it:
     - *Per step* (−0.02 by default) makes every turn cost a little;
     - *Removing own flag* (−0.5) charges for taking your own flag back off.
     
     Both can be changed mid-run. The Flags chart shows "Removed (toggles)" so you can watch the habit fade. These only shape training; the game's scoring is unchanged. Each generation, every network plays several boards on the GPU. The best are kept and the rest are replaced by mutated copies of winners. Fields marked LIVE can be changed mid-run. You can save configs and continue training from a saved model.
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
   - Power-ups and food are still used by built-in rules for every bot.

Models are saved in `models/`, configs in `configs/` and run histories in `runs/`.

## Controls

WASD / arrows to move · Shift to sprint · Space to jump · Q/E or middle-drag to rotate the camera · mouse wheel to zoom
Left-click to dig · Right-click or F to flag · G to use a held power-up · R to attack

## Files

- `server.py`: the authoritative game server (aiohttp HTTP + WebSocket). It handles rooms, mine generation, scoring and reach checks. Tune `W`, `H`, `MINES`, `REACH`, etc. at the top.
- `static/game.js`: the Three.js client (rendering, movement, effects, sound). It loads Three.js from the jsDelivr CDN, so browsers need internet access.
- `static/index.html`, `static/style.css`: the page and HUD.

## License

[MIT](LICENSE)
