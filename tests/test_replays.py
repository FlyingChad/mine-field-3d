"""Replays and run recaps (replays.py and the Room recording hooks)."""
import asyncio
import gzip
import json
import time
import unittest

from aiohttp.test_utils import TestClient, TestServer

from helpers import S, FakeWS, at, field_room, player

import replays


async def settle():
    """Let the executor finish writing the replay file."""
    for _ in range(100):
        await asyncio.sleep(0.02)
        if not S.replay_store.lock.locked() and S.replay_store.index and S.replay_store.path(S.replay_store.index[0]["id"]):
            return


def load(rid):
    return json.loads(gzip.decompress(S.replay_store.path(rid).read_bytes()))


class Recording(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._cd = S.ACTION_COOLDOWN
        S.ACTION_COOLDOWN = 0

    def tearDown(self):
        S.ACTION_COOLDOWN = self._cd

    async def play_a_round(self, r, p):
        await r.send_roster()                 # the first broadcast with a human starts the recording
        self.assertIsNotNone(r.rec)
        at(p, 20, 20)
        await r.dig(p, 20, 20)
        mine = next(iter(r.mines))
        at(p, mine % S.W, mine // S.W)
        await r.dig(p, mine % S.W, mine // S.W)
        await r.broadcast({"t": "players", "p": [[p.id, p.x, p.z, 0, p.score, 0, 0, p.hp, p.max_hp]], "b": []})
        r.rec.t0 -= replays.MIN_SECONDS + 5    # pretend the round took a while
        await r.end_round()
        if r.round_task:
            r.round_task.cancel()

    async def test_round_recap_and_replay_file(self):
        r = field_room(name="rec")
        ws = FakeWS()
        p = player(r, "Alice", "#ff5d5d", ws=ws)
        p.token, p.profile = "resume-secret-token", S.profiles.get("f" * 32, "Alice")
        r.place(p)
        await self.play_a_round(r, p)
        over = ws.of("over")[-1]
        rc, rid = over["recap"], over["replay"]
        self.assertTrue(rid and replays.ID_RE.match(rid))
        me = next(q for q in rc["players"] if q["id"] == p.id)
        self.assertEqual(me["name"], "Alice")
        self.assertGreater(me["tiles"], 0)
        self.assertEqual(me["mines"], 1)
        self.assertEqual(me["score"], over["results"][0]["score"], "the recap ends on the final scores")
        self.assertEqual(rc["series"]["scores"][p.id][-1], p.score)
        self.assertEqual(rc["moments"][0][1], "boom")
        self.assertEqual(len(rc["series"]["t"]), len(rc["series"]["scores"][p.id]))
        self.assertIsNone(r.rec, "the recording stops at the end of the round")

        await settle()
        data = load(rid)
        kinds = [e[1]["t"] for e in data["events"]]
        self.assertEqual(kinds[:2], ["welcome", "roster"])
        self.assertEqual(kinds[-1], "over")
        self.assertIn("reveal", kinds)
        self.assertIn("boom", kinds)
        w = data["events"][0][1]
        self.assertTrue(w["spectator"])
        self.assertIsNone(w["token"])
        times = [e[0] for e in data["events"]]
        self.assertEqual(times, sorted(times))
        raw = gzip.decompress(S.replay_store.path(rid).read_bytes()).decode()
        self.assertNotIn("resume-secret-token", raw, "resume tokens never go into a replay")
        self.assertNotIn("f" * 32, raw, "nor profile tokens")
        self.assertEqual(data["meta"]["room"], "rec")
        self.assertEqual(S.replay_store.list()[0]["id"], rid)

    async def test_short_rounds_and_bot_rooms_leave_no_replay(self):
        r = field_room(name="short")
        ws = FakeWS()
        p = player(r, ws=ws)
        r.place(p)
        await r.send_roster()
        await r.end_round()
        r.round_task.cancel()
        self.assertIsNone(ws.of("over")[-1]["replay"])
        self.assertIsNotNone(ws.of("over")[-1]["recap"], "a short round still gets a recap")
        b = field_room(name="bots")
        from types import SimpleNamespace
        bot = S.BotPlayer(SimpleNamespace(name="demo", version=1), "bot", "#fff", "robot", "normal", 0.5)
        b.players[bot.id] = bot
        await b.send_roster()
        self.assertIsNone(b.rec, "nobody to watch it later")

    async def test_new_round_starts_a_new_recording_and_closing_drops_it(self):
        r = field_room(name="again")
        p = player(r, ws=FakeWS())
        r.place(p)
        await r.send_roster()
        first = r.rec.id
        r.new_round()
        await r.send_roster()
        self.assertNotEqual(r.rec.id, first)
        await S.close_room(r)
        self.assertIsNone(r.rec)

    async def test_descent_run_is_one_recording(self):
        r = S.Room("deeprec", "meadow", "dungeon", "descent")
        p = player(r, ws=FakeWS())
        r.place(p)
        await r.send_roster()
        rid = r.rec.id
        r.depth += 1
        r.new_round(next_floor=True)
        await r.broadcast({"t": "round", "snapshot": r.snapshot(), "spawns": {}, "depth": r.depth})
        self.assertEqual(r.rec.id, rid, "every floor of a run goes in the same replay")
        self.assertEqual(r.rec.moments[-1][1], "floor")

    def test_recorder_limits(self):
        rec = replays.Recorder({"t": "welcome", "serverTime": 0}, {"t": "roster", "players": [{"id": "a", "name": "A", "color": "#fff"}]}, {})
        for k in range(10):
            rec.add({"t": "players", "p": [["a", 0, 0, 0, k, 0, 0, 100, 100]]})
        self.assertEqual(sum(1 for x in rec.parts if '"t":"players"' in x), 10 // replays.TICK_EVERY)
        rec.t0 -= replays.MAX_SECONDS + 1
        rec.add({"t": "boom", "pid": "a", "x": 1, "y": 1})
        self.assertTrue(rec.truncated)
        self.assertEqual(rec.stats["a"]["mines"], 1, "the recap keeps counting after the cap")


class Api(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = TestClient(TestServer(S.make_app(lab=False)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        S.rooms.clear()

    async def test_list_and_fetch(self):
        r = field_room(name="apiroom")
        p = player(r, ws=FakeWS())
        r.place(p)
        await r.send_roster()
        r.rec.t0 -= replays.MIN_SECONDS + 1
        rid = r.rec.id
        await r.end_round()
        r.round_task.cancel()
        await settle()
        lst = await (await self.client.get("/api/replays")).json()
        self.assertIn(rid, [x["id"] for x in lst["replays"]])
        resp = await self.client.get(f"/api/replay/{rid}")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["events"][0][1]["t"], "welcome")
        for bad in ("nope", "../index", "0" * 12):
            self.assertEqual((await self.client.get(f"/api/replay/{bad}")).status, 404)


class Store(unittest.TestCase):
    def test_keeps_only_the_newest(self):
        import tempfile
        st = replays.Replays(tempfile.mkdtemp())
        old = replays.MAX_REPLAYS
        replays.MAX_REPLAYS = 3
        try:
            ids = []
            for k in range(5):
                rec = replays.Recorder({"t": "welcome"}, {"t": "roster", "players": []}, {"room": f"r{k}"})
                rec.t0 -= replays.MIN_SECONDS + 1
                ids.append(st.save(rec, {}))
            self.assertEqual([e["id"] for e in st.list()], ids[::-1][:3])
            self.assertIsNone(st.path(ids[0]), "the oldest file was deleted")
            self.assertEqual([e["id"] for e in replays.Replays(st.dir).list()], ids[::-1][:3], "the index survives a restart")
        finally:
            replays.MAX_REPLAYS = old


if __name__ == "__main__":
    unittest.main()
