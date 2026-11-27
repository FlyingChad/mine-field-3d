"""Descent extras: elite bosses, relics, the cursed and flooded floors, and the weekly descent."""
import time
import unittest

from helpers import S, FakeWS, at, player
from test_features import DescentBase


def descent_room(name="deep", **kw):
    return S.Room(name, "meadow", "dungeon", "descent", **kw)


class Elites(DescentBase):
    async def spawn(self, r):
        r.next_boss_at = 0
        await r.update_bosses(time.time(), 0.05)
        return next(iter(r.bosses.values()))

    async def test_every_fifth_floor_brings_one_elite(self):
        r = descent_room()
        ws = FakeWS()
        p = player(r, ws=ws)
        r.place(p)
        for depth, elite in ((4, False), (5, True), (10, True)):
            r.depth = depth
            r.new_round(next_floor=True)
            r.modifier = None
            b = await self.spawn(r)
            self.assertEqual(b.elite, elite, depth)
            self.assertEqual(ws.of("bossSpawn")[-1]["elite"], elite)
            self.assertEqual(r.snapshot()["elite"], elite)
            if elite:
                self.assertEqual(b.name, S.ELITE_NAMES[b.kind])
                self.assertEqual(b.row(time.time())[8], 1)
                r.bosses.clear()
                r.next_boss_at = 0
                await r.update_bosses(time.time(), 0.05)
                self.assertFalse(any(x.elite for x in r.bosses.values()), "only one elite per floor")

    async def test_quake_hits_a_wide_ring_and_pays_double(self):
        r = descent_room()
        r.depth = 5
        r.new_round(next_floor=True)
        r.modifier = None
        ws = FakeWS()
        p = player(r, ws=ws)
        r.place(p)
        b = await self.spawn(r)
        bx, by = 10, 10                       # a clear straight line: boss, then the player 3 tiles east
        for x in range(bx - 1, bx + 5):
            for y in range(by - 1, by + 2):
                r.floor[S.idx(x, y)] = 1
        b.x, b.z = S.tile_center(bx, by)
        at(p, bx + 3, by)
        now = time.time()
        b.cooldown_until = 0
        await r.update_bosses(now, 0.0)
        atk = ws.of("bossAtk")[-1]
        self.assertTrue(atk.get("quake"))
        self.assertEqual(atk["r"], S.ELITE_QUAKE_RADIUS)
        hp = p.hp
        await r.update_bosses(now + S.ELITE_QUAKE_WINDUP + 0.01, 0.0)
        sm = ws.of("bossSmash")[-1]
        self.assertTrue(sm["quake"])
        self.assertIn(p.id, sm["hit"])
        self.assertEqual(hp - p.hp, S.ELITE_QUAKE_DAMAGE)
        # killing it pays ELITE_REWARD x and drops more loot
        p.ko_until = 0
        await r.damage_boss(b, b.hp, p.id)
        down = ws.of("bossDown")[-1]
        self.assertTrue(down["elite"])
        self.assertEqual(down["rewards"][p.id], (b.max_hp // S.BOSS_DAMAGE_POINTS + S.BOSS_KILL_REWARD) * S.ELITE_REWARD)
        self.assertGreaterEqual(len(down["loot"]), 3)


class Relics(DescentBase):
    async def test_offer_pick_and_carry(self):
        r = descent_room()
        ws = FakeWS()
        p = player(r, ws=ws)
        r.place(p)
        await self.clear_floor(r, p)
        offer = ws.of("relics")[-1]["offer"]
        self.assertEqual(len(offer), S.RELIC_OFFERS)
        await r.pick_relic(p, "nope")
        self.assertEqual(p.relics, set())
        k = offer[0]["id"]
        await r.pick_relic(p, k)
        self.assertEqual(p.relics, {k})
        self.assertEqual(ws.of("relic")[-1]["id"], k)
        await r.pick_relic(p, offer[1]["id"])
        self.assertEqual(p.relics, {k}, "one relic per floor")
        await r.next_floor()
        self.assertEqual(p.relics, {k}, "relics last the run")
        self.assertEqual(p.relic_offer, [])

    async def test_bots_pick_at_once_and_offers_skip_owned(self):
        r = descent_room()
        p = player(r, ws=FakeWS())
        r.place(p)
        from types import SimpleNamespace
        bot = S.BotPlayer(SimpleNamespace(name="demo", version=1), "bot", "#123", "robot", "normal", 0.5)
        r.players[bot.id] = bot
        r.place(bot)
        p.relics = set(list(S.RELICS)[:-1])
        await self.clear_floor(r, p)
        self.assertEqual(len(bot.relics), 1)
        self.assertEqual(p.relic_offer, [list(S.RELICS)[-1]])

    def test_effects(self):
        r = descent_room()
        p = player(r, ws=FakeWS())
        now = time.time()
        p.relics = {"iron"}
        r.hurt(p, 40, now)
        self.assertEqual(p.hp, 100 - 30)
        p.relics = {"phoenix"}
        p.hp = 10
        self.assertFalse(r.hurt(p, 50, now))
        self.assertEqual((p.hp, p.ko_until), (1, 0))
        self.assertEqual(r.saves, [p.id])
        self.assertTrue(r.hurt(p, 50, now), "only once per floor")

    async def test_greed_brute_vampire_sapper_boots(self):
        r = descent_room()
        ws = FakeWS()
        p = player(r, ws=ws)
        r.place(p)
        x, y = p.tile()
        await r.dig(p, x, y)
        base = ws.of("reveal")[-1]["gain"]
        p.relics = {"greed"}
        cand = next(i for i in r.floor_tiles if not r.revealed[i] and i not in r.mines
                    and r.counts[i] > 0 and i not in r.vault)
        at(p, cand % S.W, cand // S.W)
        p.last_action = 0
        await r.dig(p, cand % S.W, cand // S.W)
        self.assertEqual(ws.of("reveal")[-1]["gain"], round(1 * S.GREED_MULT))
        self.assertGreater(base, 0)
        # sapper: half mine damage
        p.relics = {"sapper"}
        m = next(iter(r.mines))
        at(p, m % S.W, m // S.W)
        p.stun_until = p.last_action = 0
        hp = p.hp
        await r.dig(p, m % S.W, m // S.W)
        self.assertEqual(hp - p.hp, S.MINE_DAMAGE // 2)
        # brute + vampire on a boss
        r.next_boss_at = 0
        await r.update_bosses(time.time(), 0.05)
        b = next(iter(r.bosses.values()))
        p.x, p.z, p.stun_until, p.hp, p.relics = b.x, b.z + 1, 0, 50, {"brute", "vampire"}
        hp_b = b.hp
        await r.attack(p)
        self.assertEqual(hp_b - b.hp, round(S.ATTACK_DAMAGE * S.BRUTE_MULT))
        self.assertEqual(p.hp, 50 + S.VAMPIRE_HEAL)


class Floors(DescentBase):
    async def test_cursed_ground_refuses_flags(self):
        r = descent_room()
        p = player(r, ws=FakeWS())
        r.place(p)
        x, y = p.tile()
        await r.dig(p, x, y)
        t = next(i for i in r.floor_tiles if not r.revealed[i] and i not in r.vault)
        at(p, t % S.W, t // S.W)               # stand on a hidden tile: it's in reach
        r.modifier = "cursed"
        await r.flag(p, t % S.W, t // S.W)
        self.assertEqual(r.flags, {})
        r.modifier = None
        await r.flag(p, t % S.W, t // S.W)
        self.assertEqual(r.flags, {t: p.id})

    def test_flooded_is_sent_with_its_slowdown(self):
        r = descent_room()
        r.depth = 3
        r.new_round(next_floor=True)
        r.modifier = "flooded"
        self.assertEqual(r.snapshot()["modifier"]["slow"], S.FLOOD_SLOW)


class Weekly(DescentBase):
    def test_same_floors_for_every_team(self):
        week = "2026-W48"
        a, b = descent_room("w1", weekly=week), descent_room("w2", weekly=week)
        self.assertEqual(a.mode, "descent")
        self.assertEqual(a.floor, b.floor)
        a.generate(*divmod(a.spawn_tiles[0], S.W)[::-1])
        b.generate(*divmod(b.spawn_tiles[5], S.W)[::-1])
        self.assertEqual(a.buried, b.buried)
        self.assertEqual(a.traps, b.traps)
        for r in (a, b):
            r.depth = 4
            r.new_round(next_floor=True)
        self.assertEqual(a.floor, b.floor)
        self.assertEqual(a.modifier, b.modifier)
        c = descent_room("w3", weekly="2026-W49")
        self.assertNotEqual(a.floor, c.floor)

    def test_room_name_and_ladder(self):
        r = S.make_room(S.weekly_name(), {})
        self.assertEqual((r.weekly, r.mode), (S.this_week(), "descent"))
        import store, tempfile, pathlib
        d = store.Descents(pathlib.Path(tempfile.mkdtemp()) / "d.json")
        d.record([{"name": "A"}], 3, 50, 100, week="2026-W48")
        d.record([{"name": "B"}], 5, 10, 100, week="2026-W48")
        d.record([{"name": "C"}], 9, 10, 100)
        board = d.board(week="2026-W48")
        self.assertEqual([x["depth"] for x in board["weekly"]], [5, 3])
        self.assertEqual(board["all"][0]["depth"], 9)


if __name__ == "__main__":
    unittest.main()
