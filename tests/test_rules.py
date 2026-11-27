"""Core game rules: reach, digging, scoring, the round lifecycle, layouts, health, power-ups, bosses
and game modes. Drives server.Room directly with fake sockets."""
import asyncio
import time
import unittest

from helpers import S, FakeWS, at, player, field_room
import layouts


class Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._saved = (S.ACTION_COOLDOWN, S.NEXT_ROUND_DELAY)
        S.ACTION_COOLDOWN = 0

    def tearDown(self):
        S.ACTION_COOLDOWN, S.NEXT_ROUND_DELAY = self._saved


class Reach(Base):
    async def test_reach_and_lag_slack(self):
        r = field_room()
        p = player(r)
        r.generate(0, 0)
        cases = [((10.5, 10.5), (10, 10), True), ((10.5, 10.5), (11, 11), True),
                 ((10.5, 10.5), (12, 10), False), ((10.5, 10.5), (13, 13), False),
                 ((10.99, 10.5), (12, 10), True), ((10.6, 10.5), (12, 10), False),
                 ((11.1, 10.5), (12, 10), True)]
        for (fx, fy), (tx, ty), want in cases:
            p.x, p.z = (fx - S.W / 2) * S.TILE, (fy - S.H / 2) * S.TILE
            p.last_action = 0
            self.assertEqual(r.can_act(p, tx, ty), want, ((fx, fy), (tx, ty)))


class Round(Base):
    async def test_first_dig_safe_scoring_and_restart(self):
        S.NEXT_ROUND_DELAY = 0.05
        r = field_room()
        ws = FakeWS()
        p = player(r, ws=ws)
        r.traps = {}
        at(p, 5, 5)
        await r.dig(p, 5, 5)
        self.assertFalse(r.booms, "the first dig is always safe")
        r.traps = {}   # keep spikes out of this scoring test
        flagged = 0
        for m in list(r.mines)[:5]:
            at(p, m % S.W, m // S.W)
            await r.flag(p, m % S.W, m // S.W)
            flagged += 1
        for i in range(S.W * S.H):
            if r.state != "playing":
                break
            if not r.revealed[i] and i not in r.mines:
                at(p, i % S.W, i // S.W)
                await r.dig(p, i % S.W, i // S.W)
        self.assertEqual(r.state, "over")
        gained_items = 0   # chests aren't on fields; points are tiles + flag bonuses
        self.assertEqual(p.score, len(r.floor_tiles) - len(r.mines) + flagged * S.FLAG_CORRECT + gained_items)
        self.assertTrue(ws.of("over"))
        await asyncio.sleep(0.2)
        self.assertEqual((r.state, r.mines, p.score), ("playing", None, 0))
        self.assertTrue(ws.of("round"))

    async def test_counts_match_mines(self):
        r = field_room()
        r.generate(3, 3)
        for i in range(S.W * S.H):
            x, y = i % S.W, i // S.W
            self.assertEqual(r.counts[i], sum(1 for nx, ny in S.neighbors(x, y) if S.idx(nx, ny) in r.mines))


class Dungeon(Base):
    async def test_layout_mines_and_walls(self):
        r = S.Room("d", "spooky", "dungeon")
        self.assertTrue(600 < len(r.floor_tiles) < 1300)
        self.assertEqual(r.n_mines, round(S.MINE_DENSITY * len(r.floor_tiles)))
        snap = r.snapshot()
        self.assertEqual(snap["layout"].count("1"), len(r.floor_tiles))
        a = player(r)
        r.place(a)
        self.assertTrue(r.is_floor(*a.tile()))
        await r.dig(a, *a.tile())
        self.assertTrue(all(r.floor[m] for m in r.mines))
        self.assertFalse(any(r.revealed[i] and not r.floor[i] for i in range(S.W * S.H)))
        self.assertEqual(r.safe_left, sum(1 for i in r.floor_tiles if not r.revealed[i] and i not in r.mines))

    async def test_new_round_new_layout(self):
        S.NEXT_ROUND_DELAY = 0
        r = S.Room("d", "meadow", "dungeon")
        ws = FakeWS()
        a = player(r, ws=ws)
        r.place(a)
        old = bytes(r.floor)
        r.state = "over"
        await r.restart_later()
        self.assertIn(a.id, ws.of("round")[-1]["spawns"])
        self.assertTrue(r.is_floor(*a.tile()))
        self.assertNotEqual(bytes(r.floor), old)

    def test_layout_generator(self):
        for _ in range(5):
            f = layouts.dungeon(48, 48)
            self.assertTrue(layouts.connected(f, 48, 48))
            self.assertFalse(any(f[i] for i in range(48)), "outer ring is wall")


class Health(Base):
    async def test_ko_respawn_and_food(self):
        r = field_room()
        ws = FakeWS()
        a = player(r, ws=ws)
        at(a, 10, 10)
        await r.dig(a, 10, 10)
        score0 = a.score
        for m in list(r.mines)[:3]:
            at(a, m % S.W, m // S.W)
            a.stun_until = 0
            await r.dig(a, m % S.W, m // S.W)
        self.assertEqual(a.hp, 0)
        self.assertGreater(a.ko_until, time.time())
        self.assertEqual(a.score, score0 + 3 * S.MINE_PENALTY + S.KO_PENALTY)
        a.ko_until = time.time() - 0.01
        await r.respawns(time.time())
        self.assertEqual((a.hp, a.ko_until), (S.MAX_HP, 0))
        i = next(i for i in r.floor_tiles if r.revealed[i] and i not in r.booms)
        r.items[i] = "potion"
        at(a, i % S.W, i // S.W)
        a.stun_until = 0
        await r.pickups(time.time())
        self.assertIn(i, r.items, "full health ignores food")
        a.hp = 70
        await r.pickups(time.time())
        self.assertNotIn(i, r.items)
        self.assertEqual(a.hp, 100)


class Items(Base):
    async def test_pickups_shield_scatter(self):
        r = field_room()
        ws, ws2 = FakeWS(), FakeWS()
        a, b = player(r, "A", ws=ws), player(r, "B", "#000", ws=ws2)
        at(a, 10, 10); at(b, 12, 10)
        await r.dig(a, 10, 10)
        b.hp = 50
        for kind in ("shield", "boots", "radar", "scatter", "apple"):
            i = S.idx(12, 10)
            r.mines.discard(i); r.recount(); r.revealed[i] = 1
            r.items[i] = kind
            await r.pickups(time.time())
            self.assertNotIn(i, r.items, kind)
        self.assertEqual(b.hp, 75)
        self.assertTrue(b.shield and b.held == "scatter")
        self.assertTrue(ws2.of("radar"))
        # the shield soaks a mine
        m = next(iter(r.mines))
        at(b, m % S.W, m // S.W)
        s0 = b.score
        await r.dig(b, m % S.W, m // S.W)
        self.assertTrue(ws2.of("boom")[-1]["shielded"])
        self.assertEqual(b.score, s0)
        # scatter: out of range refused; in range re-buries 5x5 with fresh mines
        at(b, 5, 5)
        await r.use(b, 5 + S.THROW_RANGE + 2, 5)
        self.assertEqual(b.held, "scatter")
        at(a, 8, 8)
        await r.use(b, 8, 8)
        await asyncio.sleep(S.SCATTER_FUSE + 0.2)
        area = {S.idx(x, y) for x in range(6, 11) for y in range(6, 11)}
        self.assertEqual(len(area & r.mines), S.SCATTER_MINES)
        self.assertIn(a.id, ws.of("scatter")[-1]["hit"])
        self.assertEqual(r.safe_left, sum(1 for i in r.floor_tiles if not r.revealed[i] and i not in r.mines))

    async def test_freeze_shock_blink_gold(self):
        r = field_room()
        ws = FakeWS()
        a, b, c = player(r, "A", ws=ws), player(r, "B", "#000"), player(r, "C", "#111")
        at(a, 4, 20); await r.dig(a, 4, 20)
        a.gold_until = time.time() + 10
        i = next(i for i in range(S.W * S.H) if not r.revealed[i] and i not in r.mines and r.counts[i] > 0)
        at(a, i % S.W, i // S.W)
        s0 = a.score
        await r.dig(a, i % S.W, i // S.W)
        self.assertEqual(a.score - s0, 2, "gold rush doubles reveal points")
        at(a, 4, 20); at(b, 8, 20); at(c, 11, 20)
        a.held = "freeze"
        await r.use(a, 14, 20)
        self.assertEqual(ws.of("zap")[-1]["target"], b.id)
        self.assertGreater(b.frozen_until, time.time())
        self.assertEqual(c.frozen_until, 0)
        b.stun_until = b.frozen_until = 0
        a.held = "shockwave"; at(b, 6, 20); at(c, 20, 20)
        await r.use(a, -1, -1)
        self.assertEqual(ws.of("shock")[-1]["hit"], [b.id])
        a.held = "blink"
        await r.use(a, 4 + S.BLINK_RANGE + 2, 20)
        self.assertEqual(a.held, "blink")
        await r.use(a, 10, 24)
        self.assertEqual(a.tile(), (10, 24))


class Bosses(Base):
    async def test_boss_lifecycle(self):
        r = S.Room("boss", "volcano", "dungeon")
        ws = FakeWS()
        a = player(r, ws=ws)
        r.place(a)
        self.assertEqual(field_room().boss_target_count(), 0)
        now = time.time()
        await r.update_bosses(now, 0.07)
        self.assertFalse(r.bosses)
        r.next_boss_at = 0
        await r.update_bosses(now, 0.07)
        b = next(iter(r.bosses.values()))
        t = now
        for _ in range(200):
            t += 0.07
            await r.update_bosses(t, 0.07)
            self.assertTrue(r.is_floor(*b.tile()))
        a.x, a.z = b.x, b.z
        a.hp, a.stun_until, a.shield = S.MAX_HP, 0, False
        b.cooldown_until, b.state = 0, "chase"
        await r.update_bosses(t, 0.07)
        self.assertEqual(b.state, "windup")
        await r.update_bosses(t + S.BOSS_WINDUP + 0.01, 0.07)
        self.assertIn(a.id, ws.of("bossSmash")[-1]["hit"])
        self.assertEqual(a.hp, S.MAX_HP - b.damage)
        a.stun_until = a.last_attack = 0
        hp0 = b.hp
        await r.attack(a); await r.attack(a)
        self.assertEqual(b.hp, hp0 - S.ATTACK_DAMAGE, "attack cooldown")
        s0 = a.score
        dealt = b.dmg_by[a.id] + b.hp
        await r.damage_boss(b, 9999, a.id)
        down = ws.of("bossDown")[-1]
        self.assertEqual(down["killer"], a.id)
        self.assertEqual(a.score - s0, S.BOSS_KILL_REWARD + dealt // S.BOSS_DAMAGE_POINTS)
        self.assertTrue(any(k == "potion" for _, _, k in down["loot"]))


class Modes(Base):
    def pair(self, mode):
        r = field_room(mode)
        ws = FakeWS()
        a, b = player(r, "A", ws=ws), player(r, "B", "#000")
        at(a, 10, 10); at(b, 11, 10)
        r.mines, r.counts = set(), [0] * (S.W * S.H)
        return r, ws, a, b

    async def test_race_pvp_coop(self):
        r, ws, a, b = self.pair("race")
        await r.attack(a)
        self.assertEqual(b.hp, S.MAX_HP)
        r, ws, a, b = self.pair("pvp")
        await r.attack(a)
        self.assertEqual(b.hp, S.MAX_HP - S.PVP_MELEE_DAMAGE)
        b.hp, a.last_attack, s0 = 10, 0, a.score
        await r.attack(a)
        self.assertEqual(ws.of("ko")[-1]["by"], a.id)
        self.assertEqual(a.score, s0 + S.KO_REWARD)
        r, ws, a, b = self.pair("coop")
        await r.attack(a)
        a.held = "shockwave"; await r.use(a, -1, -1)
        a.held = "freeze"; await r.use(a, 12, 10)
        await r.scatter(1, a.id, 11, 10)
        self.assertEqual((b.hp, b.frozen_until), (S.MAX_HP, 0), "no friendly fire in co-op")

    async def test_coop_lives(self):
        r, ws, a, b = self.pair("coop")
        r.lives = 2
        now = time.time()
        r.hurt(a, 999, now); await r.flush_kos()
        self.assertEqual((r.lives, r.state), (1, "playing"))
        r.hurt(b, 999, now); await r.flush_kos()
        over = ws.of("over")[-1]
        self.assertTrue(over["failed"])
        if r.round_task:
            r.round_task.cancel()


if __name__ == "__main__":
    unittest.main()
