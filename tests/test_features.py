"""The vault and key, spike traps, the daily dungeon, profiles and hats, and the WebSocket protocol
(rate limit, resume, spectators, quick chat)."""
import asyncio
import time
import unittest

from aiohttp.test_utils import TestClient, TestServer

from helpers import S, store, FakeWS, at, player, field_room, vault_room


class Vault(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._cd = S.ACTION_COOLDOWN
        S.ACTION_COOLDOWN = 0

    def tearDown(self):
        S.ACTION_COOLDOWN = self._cd

    def front(self, r):
        d = r.doors[0]
        return next(t for t in r.nb(d % S.W, d // S.W) if S.idx(*t) not in r.vault)

    async def test_layout(self):
        r = vault_room()
        self.assertEqual(len(r.doors), 2)
        self.assertTrue(S.VAULT_MIN <= len(r.vault) <= S.VAULT_MAX)
        self.assertFalse(any(r.floor[d] for d in r.doors), "doors are walls while locked")
        self.assertFalse(set(r.spawn_tiles) & r.vault, "nobody spawns in the locked vault")
        # the vault is cut off from the rest in 8-way terms, so flood fill can't leak in
        outside = set(r.floor_tiles) - r.vault
        for v in r.vault:
            for nx, ny in S.neighbors(v % S.W, v // S.W):
                self.assertNotIn(S.idx(nx, ny), outside)
        self.assertEqual(len(r.snapshot()["doors"]), 2)

    async def test_key_chest_and_opening(self):
        r = vault_room()
        ws = FakeWS()
        a = player(r, ws=ws)
        fx, fy = self.front(r)
        start = next(t for t in r.bfs((fx, fy), max_depth=12) if max(abs(t[0] - fx), abs(t[1] - fy)) >= 4)
        at(a, *start)
        await r.dig(a, *start)
        # the first dig's flood fill may already have uncovered the key
        self.assertEqual(list(r.buried.values()).count("key") + list(r.items.values()).count("key"), 1)
        key = next(i for i, k in [*r.buried.items(), *r.items.items()] if k == "key")
        r.buried.pop(key, None)
        self.assertNotIn(key, r.vault)
        self.assertNotIn(key, r.mines)
        self.assertIn("chest", [r.buried.get(i) for i in r.vault])
        # can't dig into the vault from outside, even right next to its wall
        v = next(iter(r.vault))
        a.x, a.z = S.tile_center(v % S.W, v // S.W)   # standing inside counts as inside
        self.assertFalse(r.locked_out(a, v))
        at(a, fx, fy)
        self.assertTrue(r.locked_out(a, v))
        # pick up the key (lying on a revealed tile) and walk to the door
        r.items[key] = "key"
        at(a, key % S.W, key // S.W)
        await r.pickups(time.time())
        self.assertTrue(a.key)
        self.assertTrue(a.fx(time.time()) & S.KEY_BIT)
        safe0, s0 = r.safe_left, a.score
        at(a, fx, fy)
        await r.check_doors()
        self.assertTrue(r.vault_open)
        self.assertFalse(a.key)
        self.assertTrue(all(r.floor[d] and r.revealed[d] for d in r.doors))
        self.assertTrue(ws.of("door"))
        self.assertGreaterEqual(a.score - s0, S.VAULT_OPEN_REWARD + 2)
        self.assertEqual(r.safe_left, sum(1 for i in r.floor_tiles if not r.revealed[i] and i not in r.mines))
        self.assertLessEqual(r.safe_left, safe0)
        self.assertEqual(r.spawn_tiles, r.floor_tiles)
        # the chest
        c = next(i for i in r.vault if r.buried.get(i) == "chest" or r.items.get(i) == "chest")
        r.buried.pop(c, None); r.items[c] = "chest"
        at(a, c % S.W, c // S.W)
        s1 = a.score
        await r.pickups(time.time())
        self.assertEqual(a.score - s1, S.CHEST_POINTS)

    async def test_key_dropped_on_ko_and_rebured(self):
        r = vault_room()
        ws = FakeWS()
        a = player(r, ws=ws)
        r.place(a)
        await r.dig(a, *a.tile())
        key = next(i for i, k in [*r.buried.items(), *r.items.items()] if k == "key")
        r.buried.pop(key, None)
        r.items.pop(key, None)
        a.key = True
        r.hurt(a, 999, time.time())
        await r.flush_kos()
        self.assertFalse(a.key)
        self.assertEqual(ws.of("drop")[-1]["kind"], "key")
        self.assertEqual(list(r.items.values()).count("key"), 1)
        # a lost key (e.g. blown up by a scatter bomb) is buried again
        r.items = {i: k for i, k in r.items.items() if k != "key"}
        await r.check_doors()
        self.assertEqual(list(r.buried.values()).count("key") + list(r.items.values()).count("key"), 1)

    async def test_blink_cannot_enter_locked_vault(self):
        r = vault_room()
        a = player(r)
        fx, fy = self.front(r)
        at(a, fx, fy)
        r.mines, r.counts = set(), [0] * (S.W * S.H)
        v = min(r.vault, key=lambda i: max(abs(i % S.W - fx), abs(i // S.W - fy)))
        a.held = "blink"
        await r.use(a, v % S.W, v // S.W)
        self.assertEqual(a.held, "blink")


class DescentBase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._cd = S.ACTION_COOLDOWN
        S.ACTION_COOLDOWN = 0

    def tearDown(self):
        S.ACTION_COOLDOWN = self._cd

    async def clear_floor(self, r, p):
        if r.mines is None:
            await r.dig(p, *p.tile())
        if not r.vault_open:   # carry the key to the door
            d = r.doors[0]
            at(p, *next(t for t in r.nb(d % S.W, d // S.W) if S.idx(*t) not in r.vault))
            p.key = True
            await r.check_doors()
        for i in list(r.floor_tiles):
            if r.stairs is not None:
                break
            if not r.revealed[i] and i not in r.mines:
                at(p, i % S.W, i // S.W)
                await r.dig(p, i % S.W, i // S.W)


class Descent(DescentBase):
    async def test_floors_carry_over_and_get_harder(self):
        r = S.Room("deep", "meadow", "field", "descent")
        self.assertEqual((r.layout_kind, r.realm, r.depth), ("dungeon", S.DESCENT_REALMS[0], 1))
        self.assertTrue(r.coop, "descent plays by co-op rules")
        ws = FakeWS()
        p = player(r, ws=ws)
        r.place(p)
        lives0 = r.lives
        await self.clear_floor(r, p)
        self.assertEqual(r.state, "playing", "clearing a floor doesn't end the run")
        st = ws.of("stairs")[-1]
        self.assertEqual(r.lives, lives0 + S.DESCENT_LIFE_PER_FLOOR)
        self.assertEqual(r.boss_target_count(), 0, "no bosses while the stairs are open")
        score = p.score
        # stepping on the stairs takes everyone down after a short delay
        at(p, st["x"], st["y"])
        now = time.time()
        await r.check_stairs(now)
        self.assertEqual(ws.of("descending")[-1]["depth"], 2)
        await r.check_stairs(now + S.DESCEND_DELAY + 0.1)
        self.assertEqual((r.depth, r.realm, r.stairs), (2, S.DESCENT_REALMS[1], None))
        self.assertEqual(p.score, score, "scores carry over")
        self.assertEqual(r.lives, lives0 + S.DESCENT_LIFE_PER_FLOOR, "lives carry over")
        self.assertTrue(r.is_floor(*p.tile()))
        self.assertEqual(ws.of("round")[-1]["snapshot"]["depth"], 2)
        # deeper floors: denser mines and more bosses
        r.depth = 7
        r.new_round(next_floor=True)
        r.modifier = None                     # Swarm would add a boss
        self.assertAlmostEqual(r.n_mines / len(r.floor_tiles),
                               min(S.DESCENT_MAX_DENSITY, S.MINE_DENSITY * (1 + S.DESCENT_MINES_PER_FLOOR * 6)), places=2)
        self.assertEqual(r.boss_target_count(), 3)

    async def test_stairs_open_on_their_own(self):
        r = S.Room("deep", "meadow", "dungeon", "descent")
        ws = FakeWS()
        p = player(r, ws=ws)
        r.place(p)
        await self.clear_floor(r, p)
        r.place(p)
        while S.idx(*p.tile()) == r.stairs:   # stand somewhere other than the stairs
            r.place(p)
        await r.check_stairs(r.stairs_auto + 0.01)
        self.assertIsNone(ws.of("descending")[-1]["by"])

    async def test_run_ends_on_lives_and_is_recorded(self):
        r = S.Room("deep", "meadow", "dungeon", "descent")
        ws = FakeWS()
        p = player(r, "Delver", ws=ws)
        p.profile = S.profiles.get("cd" * 16, "Delver")
        r.depth = 6
        r.lives = 1
        r.hurt(p, 999, time.time())
        await r.flush_kos()
        over = ws.of("over")[-1]
        self.assertTrue(over["failed"])
        self.assertEqual(over["depth"], 6)
        self.assertEqual(S.descent_board.board()["all"][0]["depth"], 6)
        self.assertEqual(p.profile["deepest"], 6)
        self.assertIn("lantern", store.unlocked(p.profile))
        r.round_task.cancel()
        # a new run starts back at floor 1
        S_delay, S.NEXT_ROUND_DELAY = S.NEXT_ROUND_DELAY, 0
        try:
            await r.restart_later()
        finally:
            S.NEXT_ROUND_DELAY = S_delay
        self.assertEqual((r.depth, p.score), (1, 0))


class Shop(DescentBase):
    async def stairs_up(self, r, p):
        await self.clear_floor(r, p)
        self.assertIsNotNone(r.stairs)
        return p.ws.of("stairs")[-1]

    async def test_flags_pay_when_a_floor_is_cleared(self):
        r = S.Room("deep", "meadow", "dungeon", "descent")
        p = player(r)
        r.place(p)
        await r.dig(p, *p.tile())
        m = next(iter(r.mines))
        r.flags[m] = p.id
        st = await self.stairs_up(r, p)
        self.assertEqual(st["flags"], {p.id: S.FLAG_CORRECT})

    async def test_buying(self):
        r = S.Room("deep", "meadow", "dungeon", "descent")
        p = player(r)
        r.place(p)
        st = await self.stairs_up(r, p)
        self.assertEqual(len(st["shop"]), S.SHOP_OFFERS)
        r.shop = list(S.SHOP)                    # make every offer available for the test
        p.score = 1000
        for k in ("vitality", "shield", "boots", "radar", "life", "supply"):
            await r.buy(p, k)
        self.assertEqual(p.bought, set(S.SHOP))
        self.assertEqual(p.max_hp, S.MAX_HP + S.VITALITY_HP)
        self.assertIn(p.held, S.HELD)
        self.assertEqual(1000 - p.score, sum(r.price(k) for k in S.SHOP))
        # once each; and not with too few points
        score = p.score
        await r.buy(p, "vitality")
        self.assertEqual(p.score, score)
        q = player(r, "Poor", "#000")
        q.score = 0
        await r.buy(q, "shield")
        self.assertNotIn("shield", q.bought)
        # perks arrive on the next floor; vitality lasts the run
        await r.next_floor()
        self.assertTrue(p.shield)
        self.assertGreater(p.boots_until, time.time())
        self.assertEqual((p.hp, p.max_hp), (S.MAX_HP + S.VITALITY_HP,) * 2)
        self.assertEqual(p.perks, set())
        await r.dig(p, *p.tile())
        await r.perk_tick()
        self.assertTrue(p.ws.of("radar"))
        # no shopping without stairs, and a new run resets max health
        await r.buy(p, "vitality")
        self.assertEqual(p.max_hp, S.MAX_HP + S.VITALITY_HP)
        S_delay, S.NEXT_ROUND_DELAY = S.NEXT_ROUND_DELAY, 0
        try:
            await r.restart_later()
        finally:
            S.NEXT_ROUND_DELAY = S_delay
        self.assertEqual(p.max_hp, S.MAX_HP)

    async def test_prices_rise_with_depth(self):
        r = S.Room("deep", "meadow", "dungeon", "descent")
        a = r.price("life")
        r.depth = 5
        self.assertGreater(r.price("life"), a)


class Modifiers(unittest.IsolatedAsyncioTestCase):
    def room(self, mod):
        r = S.Room("mod", "meadow", "dungeon", "descent")
        r.depth = 2
        r.new_round(next_floor=True)
        r.modifier = mod
        return r

    def test_rolled_from_floor_two_and_never_repeats(self):
        r = S.Room("mod", "meadow", "dungeon", "descent")
        self.assertIsNone(r.modifier)
        last = None
        for d in range(2, 12):
            r.depth = d
            r.new_round(next_floor=True)
            self.assertIn(r.modifier, S.MODIFIERS)
            self.assertNotEqual(r.modifier, last)
            last = r.modifier
        self.assertEqual(r.snapshot()["modifier"]["id"], last)
        self.assertIsNone(S.Room("race", "meadow", "dungeon").modifier)

    async def test_rich_volatile_swarm_trove(self):
        r = self.room("rich")
        p = player(r)
        r.place(p)
        await r.dig(p, *p.tile())
        self.assertEqual(p.score, 2 * sum(r.revealed))
        r = self.room("volatile")
        p = player(r)
        r.place(p)
        await r.dig(p, *p.tile())
        m = next(iter(r.mines))
        at(p, m % S.W, m // S.W)
        p.last_action = 0
        await r.dig(p, m % S.W, m // S.W)
        self.assertEqual(p.hp, S.MAX_HP - S.VOLATILE_DAMAGE)
        r = self.room("swarm")
        player(r)
        self.assertEqual(r.boss_target_count(), 2)
        t = self.room("trove")
        t.generate(*divmod(t.floor_tiles[0], S.W)[::-1])
        plain = self.room("rich")
        plain.generate(*divmod(plain.floor_tiles[0], S.W)[::-1])
        # regular power-ups only: the vault's chest, loot and key are a fixed extra on maps that have one
        loose = lambda r: sum(1 for i, k in r.buried.items() if i not in r.vault and k != "key") / len(r.floor_tiles)
        self.assertGreater(loose(t), 1.6 * loose(plain))

    async def test_unstable_ground(self):
        r = self.room("unstable")
        ws = FakeWS()
        p = player(r, ws=ws)
        r.place(p)
        await r.dig(p, *p.tile())
        for i in r.floor_tiles:               # dig everything so there's ground to cave in
            if i not in r.mines:
                r.revealed[i] = 1
        r.safe_left = 0
        r.stairs = None
        before = sum(r.revealed)
        await r.crumble(time.time())
        c = ws.of("crumble")[-1]
        self.assertTrue(3 <= len(c["tiles"]) <= 9)
        self.assertEqual(sum(r.revealed), before - len(c["tiles"]))
        self.assertEqual(r.safe_left, len(c["tiles"]))
        self.assertGreater(max(abs(c["x"] - p.tile()[0]), abs(c["y"] - p.tile()[1])), S.UNSTABLE_RADIUS + 1)
        await r.crumble(time.time())          # not again before UNSTABLE_EVERY
        self.assertEqual(len(ws.of("crumble")), 1)


class Traps(unittest.IsolatedAsyncioTestCase):
    async def test_spikes(self):
        r = field_room()
        ws = FakeWS()
        a = player(r, ws=ws)
        at(a, 10, 10)
        await r.dig(a, 10, 10)
        self.assertEqual(len(r.traps), round(S.TRAP_DENSITY * len(r.floor_tiles)))
        self.assertFalse(set(r.traps) & r.mines)
        self.assertFalse(set(r.traps) & set(r.buried))
        i = S.idx(10, 10)
        r.traps = {i: 0.0}
        now = time.time()
        t_up = now - (now % S.SPIKE_CYCLE) + S.SPIKE_CYCLE + 0.1          # 0.1 s into an "up" phase
        t_down = t_up + S.SPIKE_UP + 0.3
        await r.spikes(t_down)
        self.assertEqual(a.hp, S.MAX_HP, "spikes down: no damage")
        await r.spikes(t_up)
        self.assertEqual(a.hp, S.MAX_HP - S.SPIKE_DAMAGE)
        await r.spikes(t_up + 0.2)
        self.assertEqual(a.hp, S.MAX_HP - S.SPIKE_DAMAGE, "grace period")
        a.shield = True
        await r.spikes(t_up + S.SPIKE_CYCLE)
        self.assertTrue(ws.of("spike")[-1]["shielded"])
        self.assertEqual(a.hp, S.MAX_HP - S.SPIKE_DAMAGE)
        # dug-up traps are announced; scatter bombs bury them again
        self.assertIn([10, 10, 0.0], r.snapshot()["traps"])
        await r.scatter(1, a.id, 10, 10)
        self.assertNotIn(i, r.traps)


class Daily(unittest.IsolatedAsyncioTestCase):
    async def test_same_dungeon_and_leaderboard(self):
        d = "2031-01-02"
        a, b = S.Room("x", daily=d), S.Room("y", daily=d)
        self.assertEqual(bytes(a.floor), bytes(b.floor))
        self.assertEqual((a.mode, a.layout_kind, a.realm), ("race", "dungeon", S.daily_realm(d)))
        a.generate(*divmod(a.floor_tiles[0], S.W)[::-1])
        b.generate(*divmod(b.floor_tiles[0], S.W)[::-1])
        self.assertEqual(a.mines, b.mines)
        self.assertEqual(a.buried, b.buried)
        self.assertEqual(a.doors, b.doors)
        # a finished round goes on the board (best per name)
        ws = FakeWS()
        p = player(a, "Dee", ws=ws)
        p.score = 50
        await a.end_round()
        a.round_task.cancel()
        board = S.daily_board.board(d)
        self.assertEqual(board["scores"][0]["name"], "Dee")
        S.daily_board.record(d, "dee", 20, 5000)      # same name, other case: one row per name
        S.daily_board.record(d, "Zed", 70, 300)
        board = S.daily_board.board(d)
        self.assertEqual([r["name"] for r in board["scores"]], ["Zed", "Dee"])
        self.assertEqual([r["name"].lower() for r in board["times"]], ["dee", "zed"], "fastest clear per name")
        self.assertLess(board["times"][0]["secs"], 300)

    def test_daily_room_name(self):
        self.assertTrue(S.daily_name().startswith(S.DAILY_PREFIX + time.strftime("%Y")))
        self.assertTrue(S.make_room(S.daily_name(), {}).daily)
        self.assertIsNone(S.make_room("daily-1999-01-01", {}).daily)


class Profiles(unittest.IsolatedAsyncioTestCase):
    def test_tokens_and_unlocks(self):
        P = S.profiles
        self.assertIsNone(P.get("nope"))
        self.assertIsNone(P.get("A" * 32))
        prof = P.get("0123456789abcdef" * 2, "Pat")
        self.assertEqual(store.unlocked(prof), [])
        self.assertEqual(P.bump(prof, rounds=3), ["party"])
        self.assertEqual(S.pick_hat(prof, "party"), "party")
        self.assertEqual(S.pick_hat(prof, "crown"), "", "locked hats are refused")
        P.bump(prof, best=40)
        P.bump(prof, best=10)
        self.assertEqual(prof["best"], 40)
        P.save()
        again = store.Profiles(P.path)
        self.assertEqual(again.peek("0123456789abcdef" * 2)["rounds"], 3)

    async def test_round_stats(self):
        r = field_room()
        a, b = player(r, "A"), player(r, "B", "#000")
        a.profile = S.profiles.get("aa" * 16, "A")
        a.score, b.score = 30, 10
        await r.end_round()
        r.round_task.cancel()
        self.assertEqual((a.profile["rounds"], a.profile["wins"]), (1, 1))
        self.assertTrue(any(m["t"] == "profile" for m in a.ws.msgs))


class Protocol(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = TestClient(TestServer(S.make_app(lab=False)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        S.rooms.clear()

    async def join(self, **kw):
        ws = await self.client.ws_connect("/ws")
        await ws.send_json({"t": "join", "name": "T", "room": "proto", "layout": "field", **kw})
        while True:
            m = await ws.receive_json(timeout=5)
            if m["t"] in ("welcome", "error"):
                return ws, m

    async def until(self, ws, t, timeout=3):
        end = time.time() + timeout
        while time.time() < end:
            m = await ws.receive_json(timeout=timeout)
            if m["t"] == t:
                return m
        raise AssertionError(f"no {t}")

    async def test_resume_keeps_place(self):
        ws, w = await self.join()
        room = S.rooms["proto"]
        room.players[w["id"]].score = 42
        await ws.close()
        await asyncio.sleep(0.2)
        self.assertIn(w["token"], room.away)
        ws2, w2 = await self.join(resume=w["token"])
        self.assertTrue(w2.get("resumed"))
        self.assertEqual(w2["id"], w["id"])
        self.assertEqual(room.players[w["id"]].score, 42)
        await ws2.close()

    async def test_bad_resume_token_joins_fresh(self):
        ws, w = await self.join(resume="not-a-token")
        self.assertEqual(w["t"], "welcome")
        self.assertFalse(w.get("resumed"))
        await ws.close()

    async def test_spectator_watches_but_cannot_act(self):
        ws, w = await self.join()
        sp, sw = await self.join(spectate=True)
        self.assertTrue(sw["spectator"])
        self.assertIsNone(sw["token"])
        room = S.rooms["proto"]
        self.assertEqual(len(room.spectators), 1)
        await sp.send_json({"t": "dig", "x": 20, "y": 20})
        await asyncio.sleep(0.2)
        self.assertIsNone(room.mines)
        await ws.send_json({"t": "emote", "id": "gg"})
        self.assertEqual((await self.until(sp, "emote"))["id"], "gg")
        nobody, err = await self.join(spectate=True, room="ghost-town")
        self.assertEqual(err["t"], "error")
        for s in (ws, sp, nobody):
            await s.close()

    async def test_chat_cooldown_and_validation(self):
        ws, w = await self.join()
        await ws.send_json({"t": "emote", "id": "<script>"})
        await ws.send_json({"t": "ping", "x": 3, "y": 4})
        await ws.send_json({"t": "ping", "x": 5, "y": 5})   # inside the cooldown: dropped
        m = await self.until(ws, "ping")
        self.assertEqual((m["x"], m["y"]), (3, 4))
        msgs, end = [], time.time() + 0.6     # player ticks keep coming, so collect for a fixed window
        while time.time() < end:
            try:
                msgs.append(await ws.receive_json(timeout=0.3))
            except asyncio.TimeoutError:
                break
        self.assertFalse([x for x in msgs if x["t"] in ("ping", "emote")])
        await ws.close()

    async def test_flood_and_oversized_messages_disconnect(self):
        ws = await self.client.ws_connect("/ws")
        for _ in range(S.RATE_BURST + S.RATE_KICK + 50):
            await ws.send_str('{"t":"look"}')
        msg = await ws.receive(timeout=5)
        self.assertEqual(ws.close_code, 1008, msg)
        big = await self.client.ws_connect("/ws")
        await big.send_str("x" * (S.MAX_MSG_BYTES + 10))
        await big.receive(timeout=5)
        self.assertEqual(big.close_code, 1009)

    async def test_daily_and_profile_endpoints(self):
        d = await (await self.client.get("/api/daily")).json()
        self.assertEqual(d["room"], S.daily_name())
        p = await (await self.client.get("/api/profile?token=bad")).json()
        self.assertEqual(p["unlocked"], [])
        self.assertEqual(len(p["hats"]), len(store.HATS))


if __name__ == "__main__":
    unittest.main()
