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
class InGameBot(unittest.IsolatedAsyncioTestCase):
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
