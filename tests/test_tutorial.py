"""The tutorial room: a small private practice field with props on request."""
import time
import unittest

from helpers import S, FakeWS, at, player


class Tutorial(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._cd = S.ACTION_COOLDOWN
        S.ACTION_COOLDOWN = 0

    def tearDown(self):
        S.ACTION_COOLDOWN = self._cd
        S.rooms.clear()

    def room(self):
        r = S.make_room(S.TUTORIAL_PREFIX + "abc", {"mode": "pvp", "layout": "dungeon", "realm": "moon"})
        S.rooms[r.name] = r
        return r

    async def test_a_small_private_practice_field(self):
        r = self.room()
        self.assertTrue(r.tutorial)
        self.assertEqual((r.mode, r.layout_kind, r.realm), ("race", "field", "meadow"))
        self.assertEqual(len(r.floor_tiles), S.TUTORIAL_SIZE ** 2)
        self.assertEqual(r.n_mines, round(S.TUTORIAL_DENSITY * S.TUTORIAL_SIZE ** 2))
        p = player(r, ws=FakeWS())
        r.place(p)
        await r.send_roster()
        self.assertIsNone(r.rec, "tutorials aren't recorded")
        self.assertNotIn(r.name, [x["name"] for x in S.lobby_summary()], "and stay off the lobby")
        self.assertTrue(S.welcome_msg(r, p)["cfg"]["tutorial"])
        x, y = p.tile()
        await r.dig(p, x, y)
        self.assertEqual((r.buried, r.traps), ({}, {}), "no hidden surprises")

    async def test_props_on_request(self):
        r = self.room()
        ws = FakeWS()
        p = player(r, ws=ws)
        r.place(p)
        await r.tutorial_prop(p, "item")            # before the first dig: queued
        self.assertEqual(r.items, {})
        x, y = p.tile()
        await r.dig(p, x, y)
        drop = ws.of("drop")[-1]
        self.assertEqual(drop["kind"], "shockwave")
        self.assertTrue(r.revealed[S.idx(drop["x"], drop["y"])])
        await r.tutorial_prop(p, "item")
        self.assertEqual(len(ws.of("drop")), 1, "once per round")
        await r.tutorial_prop(p, "dummy")
        b = next(iter(r.bosses.values()))
        self.assertEqual((b.name, b.hp, b.damage), ("Training Golem", S.TUTORIAL_DUMMY_HP, 0))
        # it never moves or attacks, even with the player right next to it
        p.x, p.z = b.x, b.z + S.TILE
        x0, z0 = b.x, b.z
        for k in range(30):
            await r.update_bosses(time.time() + k * 0.1, 0.1)
        self.assertEqual((b.x, b.z, b.state), (x0, z0, "wander"))
        self.assertEqual(ws.of("bossAtk"), [])
        for _ in range(3):
            p.last_attack = 0
            await r.attack(p)
        self.assertEqual(ws.of("bossDown")[-1]["name"], "Training Golem")

    async def test_no_stats_and_other_rooms_ignore_it(self):
        r = self.room()
        p = player(r, ws=FakeWS())
        p.profile = S.profiles.get("e" * 32, "Rookie")
        r.place(p)
        x, y = p.tile()
        await r.dig(p, x, y)
        self.assertEqual(p.profile.get("tiles", 0), 0, "practice doesn't count")
        race = S.Room("plain", "meadow", "field", "race")
        q = player(race, ws=FakeWS())
        race.place(q)
        await race.dig(q, *q.tile())
        await race.tutorial_prop(q, "dummy")
        self.assertEqual(race.bosses, {})


if __name__ == "__main__":
    unittest.main()
