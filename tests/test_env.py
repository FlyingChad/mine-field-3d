"""The training simulator (ai/env.py) must match the game's rules. Runs on the CPU so it never competes
with a training run for the GPU. Skipped when PyTorch isn't installed."""
import unittest

import helpers  # noqa: F401  (puts the repo on sys.path)

try:
    import torch
    import torch.nn.functional as F
except ImportError:  # the game runs without torch; so do the other tests
    torch = None


@unittest.skipIf(torch is None, "PyTorch not installed")
class Classic(unittest.TestCase):
    def setUp(self):
        from ai import env as E
        self.E = E
        torch.manual_seed(0)

    def test_first_dig_counts_and_flood(self):
        E = self.E
        env = E.MineEnv(1, 1, 8, 8, 10, steps=50, stun=3, device="cpu")
        env.pos[0, 0] = torch.tensor([4, 4])
        r = env.step(torch.tensor([[E.DIG0 + 4]]))
        self.assertTrue(bool(env.generated[0]))
        self.assertFalse(bool(env.exploded.any()))
        self.assertEqual(int(env.mines.sum()), 10)
        self.assertFalse(bool(env.mines[0, 3:6, 3:6].any()), "the first dig's 3x3 is safe")
        self.assertEqual(float(r[0, 0]), float(env.revealed.sum()))
        c = F.conv2d(env.mines.float()[:, None], torch.ones(1, 1, 3, 3), padding=1)[:, 0].long() - env.mines.long()
        self.assertTrue(torch.equal(c, env.counts))
        z = env.revealed & (env.counts == 0)
        nb = F.max_pool2d(z.float()[:, None], 3, 1, 1)[:, 0] > 0
        self.assertFalse(bool((nb & ~env.revealed & ~env.mines).any()), "flood fill complete")

    def test_mine_penalty_stun_and_flags(self):
        E = self.E
        env = E.MineEnv(1, 1, 8, 8, 10, steps=50, stun=3, device="cpu")
        env.pos[0, 0] = torch.tensor([4, 4])
        env.step(torch.tensor([[E.DIG0 + 4]]))
        y, x = (~env.revealed[0] & env.mines[0]).nonzero()[0].tolist()
        env.pos[0, 0] = torch.tensor([y, x])
        rr = env.step(torch.tensor([[E.DIG0 + 4]]))
        self.assertEqual(float(rr[0, 0]), E.DEFAULT_REWARDS["mine"])
        self.assertEqual(int(env.stun[0, 0]), 3)
        env3 = E.MineEnv(1, 1, 8, 8, 10, steps=3, stun=3, device="cpu")
        env3.pos[0, 0] = torch.tensor([4, 4])
        env3.step(torch.tensor([[E.DIG0 + 4]]))
        s0 = env3.score.clone()
        hm = (~env3.revealed[0] & env3.mines[0]).nonzero()[0].tolist()
        env3.pos[0, 0] = torch.tensor(hm)
        env3.step(torch.tensor([[E.FLAG0 + 4]]))
        env3.step(torch.tensor([[0]]))
        self.assertTrue(bool(env3.done[0]))
        self.assertEqual(float(env3.score[0, 0] - s0[0, 0]), E.DEFAULT_REWARDS["flag_correct"])

    def test_dungeon_walls(self):
        E = self.E
        e = E.MineEnv(32, 2, 24, 24, 86, 200, 5, device="cpu", layout="dungeon")
        for _ in range(150):
            acts = torch.stack([torch.multinomial(e.mask(a).float() + 1e-6, 1).squeeze(1) for a in range(2)], 1)
            e.step(acts)
            on = e.floor.reshape(32, -1)[torch.arange(32)[:, None], e.pos[..., 0] * 24 + e.pos[..., 1]]
            self.assertTrue(bool(on.all()), "walls block moves")
        self.assertFalse(bool((e.mines & ~e.floor).any()))
        self.assertFalse(bool((e.revealed & ~e.floor).any()))


@unittest.skipIf(torch is None, "PyTorch not installed")
class AllModes(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(0)

    def test_shapes_and_versions(self):
        from ai.env import MineEnv, obs_dim, n_actions
        from ai.policy import Spec
        for v in (1, 2):
            s = Spec(3, [32], "tanh", v)
            self.assertEqual((s.in_dim, s.out_dim), (obs_dim(3, v), n_actions(v)))
        self.assertEqual(Spec.from_dict({"radius": 3, "hidden": [64]}).version, 1, "old models load as v1")
        e = MineEnv(8, 2, 12, 12, 20, 200, 5, rich=True, mode="race", bosses=True)
        self.assertEqual(tuple(e.observe(0, 3, 2).shape), (8, obs_dim(3, 2)))
        self.assertEqual(tuple(e.mask(0, 2).shape), (8, 27))
        self.assertEqual(tuple(e.mask(0, 1).shape), (8, 26))

    def test_pvp_and_coop(self):
        from ai.env import MineEnv, ATTACK, RICH, DEFAULT_REWARDS
        for mode in ("pvp", "coop"):
            e = MineEnv(1, 2, 12, 12, 10, 400, 2, rich=True, mode=mode)
            e.pos[0, 0] = torch.tensor([5, 5]); e.pos[0, 1] = torch.tensor([5, 6])
            e.hp[0, 1] = RICH["pvp_damage"]
            s0 = e.score[0, 0].item()
            e.step(torch.tensor([[ATTACK, ATTACK]]))
            if mode == "pvp":
                self.assertTrue(bool(e.ko[0, 1]))
                self.assertEqual(e.score[0, 0].item() - s0, DEFAULT_REWARDS["pvp_ko"])
            else:
                self.assertFalse(bool(e.ko.any()))
                e.score[0] = torch.tensor([10.0, 30.0])
                self.assertEqual(e.fitness()[0].tolist(), [20.0, 20.0])

    def test_unflag_penalty(self):
        from ai.env import MineEnv, DIG0, FLAG0
        e = MineEnv(1, 1, 8, 8, 10, 50, 3, device="cpu", rewards={"unflag": -0.5, "step": 0})
        e.pos[0, 0] = torch.tensor([4, 4])
        e.step(torch.tensor([[DIG0 + 4]]))
        y, x = (~e.revealed[0]).nonzero()[0].tolist()
        e.pos[0, 0] = torch.tensor([y, x])
        e.step(torch.tensor([[FLAG0 + 4]]))
        s0 = e.score[0, 0].item()
        e.step(torch.tensor([[FLAG0 + 4]]))     # take your own flag back off
        self.assertAlmostEqual(e.score[0, 0].item() - s0, -0.5)
        self.assertEqual(int(e.stats["unflags"].sum()), 1)


@unittest.skipIf(torch is None, "PyTorch not installed")
class V3(unittest.TestCase):
    """Traps, pickups and the descent stairs (extras=True, v3 models)."""

    def setUp(self):
        torch.manual_seed(0)

    def env(self, mode="race", agents=1, **kw):
        from ai.env import MineEnv, DIG0
        e = MineEnv(1, agents, 10, 10, 8, 300, 3, rich=True, mode=mode, extras=True,
                    rewards={"step": 0}, **kw)
        e.pos[0, :] = torch.tensor([5, 5])
        e.step(torch.tensor([[DIG0 + 4] * agents]))      # first dig: mines, traps and items get laid
        e.traps.zero_(); e.items.zero_()
        return e

    @staticmethod
    def safe_tile(e, revealed=True):
        cand = e.floor[0] & ~e.mines[0] & (e.revealed[0] if revealed else True)
        return cand.nonzero()[0].tolist()

    def test_shapes(self):
        from ai.env import MineEnv, obs_dim, n_actions, N_CHANNELS_V3, N_GLOBAL_V3
        from ai.policy import Spec
        s = Spec(3, [32], "tanh", 3)
        self.assertEqual((s.in_dim, s.out_dim), (49 * N_CHANNELS_V3 + N_GLOBAL_V3, n_actions(3)))
        self.assertEqual(Spec.from_dict(s.to_dict()).version, 3)
        e = MineEnv(4, 2, 12, 12, 20, 100, 3, rich=True, mode="mixed", bosses=True, extras=True)
        for v in (1, 2, 3):
            self.assertEqual(tuple(e.observe(0, 3, v).shape), (4, obs_dim(3, v)))
        self.assertEqual(tuple(e.mask(0, 3).shape), (4, 27))

    def test_v2_upgrade_plays_the_same(self):
        from ai.env import MineEnv, DIG0
        from ai.policy import Spec, upgrade
        v2, v3 = Spec(2, [24, 16], "tanh", 2), Spec(2, [24, 16], "tanh", 3)
        w2 = v2.init(1)[0] + torch.randn(v2.n_params) * 0.3
        w3 = upgrade(v2, w2, v3)
        self.assertEqual(w3.numel(), v3.n_params)
        for mode in ("race", "pvp", "coop", "descent"):
            e = MineEnv(16, 2, 12, 12, 20, 100, 3, rich=True, mode=mode, bosses=True, extras=True)
            e.step(torch.full((16, 2), DIG0 + 4))
            e.traps.zero_(); e.items.zero_()
            for _ in range(5):
                l2 = v2.forward(w2[None], e.observe(0, 2, 2)[None])[0]
                l3 = v3.forward(w3[None], e.observe(0, 2, 3)[None])[0]
                self.assertTrue(torch.allclose(l2, l3, atol=1e-5), mode)
                e.step(torch.randint(0, 26, (16, 2)))
                e.traps.zero_(); e.items.zero_()

    def test_spikes_hurt_when_up_with_grace(self):
        from ai.env import RICH
        e = self.env()
        y, x = self.safe_tile(e)
        e.pos[0, 0] = torch.tensor([y, x])
        e.traps[0, y, x] = True
        e.phase[0, y, x] = (-e.t) % RICH["spike_cycle"]          # up on this step
        obs = e.observe(0, 3, 3)
        self.assertTrue(bool(e.spikes_up()[0, y, x]), "the observation shows them up")
        hp = e.hp[0, 0].item()
        e.step(torch.tensor([[26]]))                            # attack with nothing in reach = stand still
        self.assertEqual(hp - e.hp[0, 0].item(), RICH["spike_damage"])
        self.assertEqual(int(e.stats["spikes"][0, 0]), 1)
        e.phase[0, y, x] = (-e.t) % RICH["spike_cycle"]
        e.step(torch.tensor([[26]]))
        self.assertEqual(int(e.stats["spikes"][0, 0]), 1, "grace between hits")
        self.assertIsNotNone(obs)

    def test_hidden_traps_are_harmless(self):
        e = self.env()
        y, x = self.safe_tile(e, revealed=False) if (~e.revealed[0] & ~e.mines[0]).any() else self.safe_tile(e)
        e.revealed[0, y, x] = False
        e.pos[0, 0] = torch.tensor([y, x])
        e.traps[0, y, x] = True
        e.phase[0, y, x] = (-e.t) % 6
        e.step(torch.tensor([[26]]))
        self.assertEqual(int(e.stats["spikes"][0, 0]), 0)

    def test_pickups_and_food(self):
        from ai.env import DEFAULT_REWARDS, RICH
        e = self.env()
        y, x = self.safe_tile(e)
        e.pos[0, 0] = torch.tensor([y, x])
        e.items[0, y, x] = 2                                   # food at full health stays put
        e.step(torch.tensor([[26]]))
        self.assertEqual(int(e.items[0, y, x]), 2)
        e.hp[0, 0] = 50
        s0 = e.score[0, 0].item()
        e.step(torch.tensor([[26]]))
        self.assertEqual(int(e.items[0, y, x]), 0)
        self.assertEqual(e.hp[0, 0].item(), 50 + RICH["food_heal"])
        self.assertEqual(e.score[0, 0].item() - s0, DEFAULT_REWARDS["item"])
        e.items[0, y, x] = 1                                   # power-ups are always taken
        e.step(torch.tensor([[26]]))
        self.assertEqual(int(e.stats["items"][0, 0]), 2)

    def clear(self, e):
        e.revealed[0] = e.floor[0] & ~e.mines[0]

    def test_descent_stairs(self):
        from ai.env import DEFAULT_REWARDS
        e = self.env("descent", agents=2)
        self.clear(e)
        s0 = e.score[0].clone()
        e.step(torch.tensor([[26, 26]]))
        self.assertTrue(bool(e.stairs_on[0]) and bool(e.cleared[0]))
        self.assertFalse(bool(e.done[0]), "a cleared descent floor waits for the stairs")
        self.assertEqual((e.score[0] - s0).tolist(), [DEFAULT_REWARDS["floor"]] * 2)
        _, ex = e.extra(0, 3)
        sy, sx = e.stairs_pos[0].tolist()
        self.assertTrue(bool(ex["goal"][0, sy, sx]) and bool(ex["goal_on"][0]))
        e.pos[0, 1] = torch.tensor([sy, sx])
        s1 = e.score[0].clone()
        e.step(torch.tensor([[26, 26]]))
        self.assertTrue(bool(e.done[0]))
        self.assertEqual((e.score[0] - s1).tolist(), [DEFAULT_REWARDS["stairs"]] * 2)

    def test_descent_practice(self):
        from ai.env import MineEnv, DIG0
        e = MineEnv(8, 1, 16, 16, 30, 100, 3, rich=True, mode="descent", extras=True,
                    params={"descent_practice": 1.0, "practice_radius": 3})
        e.pos[:, 0] = torch.tensor([8, 8])
        e.step(torch.full((8, 1), DIG0 + 4))
        hidden_safe = (~e.revealed & ~e.mines).reshape(8, -1).sum(1)
        self.assertTrue(bool((hidden_safe <= 49).all()), "only the area around the first dig is left")
        far = e.revealed.clone(); far[:, 5:12, 5:12] = True
        self.assertTrue(bool((far | e.mines).all()))

    def test_descent_auto_and_other_modes(self):
        from ai.env import RICH
        e = self.env("descent")
        self.clear(e)
        e.step(torch.tensor([[26]]))
        e.pos[0, 0] = torch.tensor([0, 0]) if (e.stairs_pos[0] != 0).any() else torch.tensor([9, 9])
        n = 0
        while not bool(e.done[0]):
            e.step(torch.tensor([[26]])); n += 1
        self.assertEqual(n, RICH["stairs_auto"] - 1)
        self.assertEqual(int(e.stats["stairs"].sum()), 0)
        e = self.env("coop")
        self.clear(e)
        e.step(torch.tensor([[26]]))
        self.assertTrue(bool(e.done[0]) and not bool(e.stairs_on[0]), "co-op still ends on the clear")


@unittest.skipIf(torch is None, "PyTorch not installed")
class InGameBot(unittest.IsolatedAsyncioTestCase):
    async def test_v3_bot_in_descent(self):
        """A v3 brain gets traps, pickups and the goal from a live descent room and acts on them."""
        from ai.bots import Brain
        from ai.policy import Spec
        from helpers import S, player
        r = S.Room("v3test", "meadow", "dungeon", "descent")
        h = player(r, "H")
        r.place(h)
        brain = Brain.__new__(Brain)
        brain.name, brain.spec = "v3", Spec(3, [16], "tanh", 3)
        brain.w = brain.spec.init(1)
        seen = {}
        orig = brain.decide

        def spy(*a, **kw):
            seen.update(kw.get("extra") or {})
            return orig(*a, **kw)
        brain.decide = spy
        bot = S.BotPlayer(brain, "bot", "#123", "robot", "insane", 0.05)
        r.place(bot)
        r.players[bot.id] = bot
        r.generate(*h.tile())
        t0 = 1e9
        for k in range(200):
            await r.update_bots(t0 + k * 0.07, 0.07)
            self.assertTrue(r.is_floor(*bot.tile()))
        self.assertEqual(seen.get("mode"), "descent")
        for key in ("traps", "items", "goal"):
            self.assertIn(key, seen)
        # a nearby goal is the network's job; a far one is walked by BFS
        r.bosses.clear()
        bot.held, bot.key, bot.stun_until, bot.ko_until, bot.hp = None, False, 0, 0, bot.max_hp
        bx, by = bot.tile()
        bot.x, bot.z = bot.tx, bot.tz = S.tile_center(bx, by)
        far = max(r.spawn_tiles, key=lambda i: max(abs(i % S.W - bx), abs(i // S.W - by)))
        r.stairs = far
        bot.next_think = 0
        await r.update_bots(t0 + 100, 0.07)
        path = r.bfs((bx, by), (far % S.W, far // S.W))
        self.assertEqual(S.tile_center(*path[0]), (bot.tx, bot.tz))

    async def test_bot_stays_on_floor_and_carries_the_key(self):
        from ai.bots import Brain
        from helpers import S, vault_room, player
        r = vault_room()
        h = player(r, "H")
        r.place(h)
        bot = S.BotPlayer(Brain("demo"), "bot", "#123", "robot", "insane", 0.05)
        r.place(bot)
        r.players[bot.id] = bot
        t0 = 1e9
        for k in range(250):
            await r.update_bots(t0 + k * 0.07, 0.07)
            self.assertTrue(r.is_floor(*bot.tile()), "bot walked into a wall or the locked door")
        # the key heuristic walks a bot to the door, which opens it
        if r.mines is None:
            r.generate(*h.tile())
        bot.key, bot.stun_until, bot.ko_until = True, 0, 0
        for k in range(600):
            now = t0 + 100 + k * 0.07
            await r.update_bots(now, 0.07)
            await r.check_doors()
            if r.vault_open:
                break
        self.assertTrue(r.vault_open, "the bot never reached the door")


if __name__ == "__main__":
    unittest.main()
