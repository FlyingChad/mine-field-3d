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

    def test_dig_reward_once_per_safe_dig(self):
        E = self.E
        rw = {"reveal": 0.0, "dig": 5.0}
        env = E.MineEnv(1, 1, 8, 8, 10, steps=50, stun=3, rewards=rw, device="cpu")
        env.pos[0, 0] = torch.tensor([4, 4])
        r = env.step(torch.tensor([[E.DIG0 + 4]]))
        self.assertGreater(int(env.revealed.sum()), 1, "the first dig floods open several tiles")
        self.assertEqual(float(r[0, 0]), 5.0, "but pays the dig reward once")
        self.assertEqual(float(env.stats["digs"][0, 0]), 1.0)
        r = env.step(torch.tensor([[E.DIG0 + 4]]))      # the same tile again: nothing opens, nothing paid
        self.assertEqual(float(r[0, 0]), 0.0)
        y, x = (~env.revealed[0] & env.mines[0]).nonzero()[0].tolist()
        env.pos[0, 0] = torch.tensor([y, x])
        r = env.step(torch.tensor([[E.DIG0 + 4]]))      # a mine is not a safe dig
        self.assertEqual(float(r[0, 0]), E.DEFAULT_REWARDS["mine"])
        self.assertEqual(float(env.stats["digs"][0, 0]), 1.0)

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
class V4(unittest.TestCase):
    """Power-ups (powers=True, v4 models): held items, shields and the USE action."""

    def setUp(self):
        torch.manual_seed(0)

    def env(self, mode="pvp", agents=2, bosses=False):
        from ai.env import MineEnv, DIG0
        e = MineEnv(1, agents, 12, 12, 12, 300, 3, rich=True, mode=mode, bosses=bosses, powers=True,
                    rewards={"step": 0})
        e.pos[0, :] = torch.tensor([6, 6])
        e.step(torch.tensor([[DIG0 + 4] + [26] * (agents - 1)]))
        e.traps.zero_(); e.items.zero_()
        e.stun.zero_(); e.hp.fill_(100.0)        # (in PvP the opening "attack" may have hit someone)
        return e

    def test_shapes_and_upgrade(self):
        from ai.env import MineEnv, obs_dim, n_actions, N_CHANNELS_V3, N_GLOBAL_V4, USE
        from ai.policy import Spec, upgrade, USE_BIAS
        s4 = Spec(2, [16, 8], "tanh", 4)
        self.assertEqual((s4.in_dim, s4.out_dim), (25 * N_CHANNELS_V3 + N_GLOBAL_V4, 28))
        self.assertEqual((n_actions(4), USE), (28, 27))
        e = MineEnv(4, 2, 12, 12, 20, 100, 3, rich=True, mode="mixed", bosses=True, powers=True)
        self.assertEqual(tuple(e.observe(0, 2, 4).shape), (4, obs_dim(2, 4)))
        self.assertEqual(tuple(e.mask(0, 4).shape), (4, 28))
        for old_v in (2, 3):
            old = Spec(2, [16, 8], "tanh", old_v)
            w = old.init(1)[0] + torch.randn(old.n_params) * 0.3
            w4 = upgrade(old, w, s4)
            l_old = old.forward(w[None], e.observe(0, 2, old_v)[None])[0]
            l4 = s4.forward(w4[None], e.observe(0, 2, 4)[None])[0]     # nobody holds anything yet
            if old_v == 3:
                self.assertTrue(torch.allclose(l_old, l4[:, :27], atol=1e-5))
            self.assertTrue(torch.allclose(l4[:, 27], torch.full((4,), USE_BIAS)))

    def test_pickups_and_shield(self):
        from ai.env import DIG0
        e = self.env()
        y, x = (e.revealed[0] & ~e.mines[0]).nonzero()[0].tolist()
        e.pos[0, 0] = torch.tensor([y, x])
        e.items[0, y, x] = 5                       # freeze
        e.step(torch.tensor([[26, 26]]))
        self.assertEqual(int(e.held[0, 0]), 2)
        e.items[0, y, x] = 7                       # blink: hands are full
        e.step(torch.tensor([[26, 26]]))
        self.assertEqual((int(e.held[0, 0]), int(e.items[0, y, x])), (2, 7))
        e.items[0, y, x] = 3
        e.step(torch.tensor([[26, 26]]))
        self.assertTrue(bool(e.shield[0, 0]))
        # the shield soaks a mine: no penalty, no stun, no damage
        my, mx = (~e.revealed[0] & e.mines[0]).nonzero()[0].tolist()
        e.pos[0, 0] = torch.tensor([my, mx])
        s0, hp = e.score[0, 0].item(), e.hp[0, 0].item()
        e.step(torch.tensor([[DIG0 + 4, 26]]))
        self.assertEqual((e.score[0, 0].item(), e.hp[0, 0].item(), int(e.stun[0, 0])), (s0, hp, 0))
        self.assertFalse(bool(e.shield[0, 0]))

    def test_freeze_shockwave_and_coop(self):
        from ai.env import USE, RICH
        e = self.env("pvp")
        e.pos[0, 0] = torch.tensor([6, 6]); e.pos[0, 1] = torch.tensor([6, 9])
        self.assertFalse(bool(e.use_ok(0)[0]), "nothing held")
        e.held[0, 0] = 2
        self.assertTrue(bool(e.use_ok(0)[0]))
        e.step(torch.tensor([[USE, 26]]))
        self.assertEqual(int(e.held[0, 0]), 0)
        self.assertGreaterEqual(int(e.stun[0, 1]), RICH["freeze_steps"] - 1)
        e.stun.zero_()
        e.held[0, 0] = 3
        hp = e.hp[0, 1].item()
        e.step(torch.tensor([[USE, 26]]))
        self.assertEqual(hp - e.hp[0, 1].item(), RICH["shock_damage"])
        c = self.env("coop")
        c.pos[0, 0] = torch.tensor([6, 6]); c.pos[0, 1] = torch.tensor([6, 7])
        c.held[0, 0] = 2
        self.assertFalse(bool(c.use_ok(0)[0]), "no freezing teammates")
        c.held[0, 0] = 3
        hp = c.hp[0, 1].item()
        c.step(torch.tensor([[USE, 26]]))
        self.assertEqual(c.hp[0, 1].item(), hp, "the shockwave spares teammates")

    def test_freeze_and_shock_the_boss(self):
        from ai.env import USE, RICH
        e = self.env("coop", agents=1, bosses=True)
        e.boss_on[0] = True; e.boss_hp[0] = 300.0
        e.boss_pos[0] = torch.tensor([6, 9]); e.pos[0, 0] = torch.tensor([6, 6])
        e.held[0, 0] = 2
        e.step(torch.tensor([[USE]]))
        self.assertEqual(e.boss_hp[0].item(), 300 - RICH["freeze_boss"])
        self.assertGreater(int(e.boss_stun[0]), 0)
        pos = e.boss_pos[0].clone()
        e.step(torch.tensor([[26]]))
        self.assertTrue(torch.equal(e.boss_pos[0], pos), "a frozen boss stays put")

    def test_scatter_recovers_and_reseeds(self):
        import torch.nn.functional as F
        from ai.env import USE, RICH
        e = self.env("pvp")
        e.pos[0, 0] = torch.tensor([6, 6]); e.pos[0, 1] = torch.tensor([6, 9])
        e.revealed[0, 4:9, 7:12] = True
        e.held[0, 0] = 1
        e.step(torch.tensor([[USE, 26]]))
        area = e.revealed[0, 4:9, 7:12]
        self.assertFalse(bool(area.any()), "the blast re-covers a 5x5")
        self.assertEqual(int(e.mines[0, 4:9, 7:12].sum()), RICH["scatter_mines"])
        c = F.conv2d(e.mines.float()[:, None], torch.ones(1, 1, 3, 3), padding=1)[:, 0].long() - e.mines.long()
        self.assertTrue(torch.equal(c, e.counts))
        self.assertEqual(int(e.safe_total[0]), int((e.floor[0] & ~e.mines[0]).sum()))
        self.assertLess(e.hp[0, 1].item(), 100)

    def test_blink_goes_somewhere_worth_digging(self):
        from ai.env import USE
        e = self.env("race", agents=1)
        e.held[0, 0] = 4
        ok, by, bx = e._blink_spot(0)
        if not bool(ok[0]):
            self.skipTest("no spot on this board")
        e.step(torch.tensor([[USE]]))
        y, x = e.pos[0, 0].tolist()
        self.assertTrue(bool(e.revealed[0, y, x]))
        hidden = (~e.revealed[0] & e.floor[0])[max(0, y - 1):y + 2, max(0, x - 1):x + 2].sum()
        self.assertGreater(int(hidden), 2)


@unittest.skipIf(torch is None, "PyTorch not installed")
class LiveRewards(unittest.TestCase):
    def test_every_reward_is_live_and_reaches_the_next_env(self):
        from ai import evolve
        rewards = [k for k in evolve.FIELDS if k.startswith("reward_")]
        self.assertTrue(rewards)
        self.assertEqual([k for k in rewards if not evolve.FIELDS[k].get("live")], [])
        cfg = evolve.sanitize({"board_w": 8, "board_h": 8, "mines": 6, "episode_steps": 20})
        tweak = evolve.sanitize({**cfg, "reward_stairs": 77, "reward_mine": -42})
        for k, v in tweak.items():          # what _train's "tweak" does
            if evolve.FIELDS.get(k, {}).get("live"):
                cfg[k] = v
        env = evolve.make_env(cfg, 2, 2, torch.device("cpu"))
        self.assertEqual((env.rw["stairs"], env.rw["mine"]), (77.0, -42.0))


def E_window(t, pos, r):
    """(N,H,W) bool -> (N,(2r+1)^2) bool window around pos (N,2), outside = False (like encode's planes)."""
    p = torch.nn.functional.pad(t.float(), (r, r, r, r))
    K = 2 * r + 1
    return torch.stack([p[n, pos[n, 0]:pos[n, 0] + K, pos[n, 1]:pos[n, 1] + K].reshape(-1) for n in range(t.shape[0])]).bool()


@unittest.skipIf(torch is None, "PyTorch not installed")
class LogicHint(unittest.TestCase):
    def test_the_two_rules_chain(self):
        from ai.env import deduce
        #  covered:  ▢ ▢ ▢ ▢     the right 2 has two covered neighbours -> both mines; the next 2 then
        #  numbers:  1 2 2 2     has its two -> the second tile is safe; the 1 then needs the first.
        rev = torch.tensor([[[0, 0, 0, 0], [1, 1, 1, 1], [1, 1, 1, 1]]], dtype=torch.bool)
        cnt = torch.tensor([[[0, 0, 0, 0], [1, 2, 2, 2], [0, 0, 0, 0]]])
        safe, mine = deduce(rev, cnt, torch.zeros_like(rev))
        self.assertEqual(safe[0, 0].int().tolist(), [0, 1, 0, 0])
        self.assertEqual(mine[0, 0].int().tolist(), [1, 0, 1, 1])
        self.assertFalse(bool((safe | mine)[0, 1:].any()), "only covered tiles are marked")
        # a crater counts as a known mine: a 1 next to it frees its other neighbours
        rev2 = torch.tensor([[[1, 0, 0], [1, 1, 1]]], dtype=torch.bool)
        exp2 = torch.tensor([[[1, 0, 0], [0, 0, 0]]], dtype=torch.bool)
        cnt2 = torch.tensor([[[0, 0, 0], [1, 1, 0]]])
        safe2, mine2 = deduce(rev2, cnt2, exp2)
        self.assertEqual(safe2[0, 0].int().tolist(), [0, 1, 1])
        self.assertFalse(bool(mine2.any()), "the crater itself isn't a covered tile")

    def test_sound_on_real_boards_and_flags_ignored(self):
        from ai.env import MineEnv, DIG0, FLAG0
        torch.manual_seed(5)
        e = MineEnv(128, 2, 16, 16, 40, 200, 3, device="cpu", layout="dungeon", rich=True, mode="race", powers=True)
        found = 0
        for _ in range(60):
            acts = torch.stack([torch.multinomial(e.mask(a, 4).float() + 1e-6, 1).squeeze(1) for a in range(2)], 1)
            e.step(acts)
            safe, mine = e.logic()
            self.assertFalse(bool((safe & e.mines).any()), "a tile proven safe is never a mine")
            self.assertFalse(bool((mine & ~e.mines).any()), "a tile proven mined always is one")
            found += int(safe.sum() + mine.sum())
        self.assertGreater(found, 0)
        # a wrong flag changes nothing: the hint only reads numbers and craters
        before = [t.clone() for t in e.logic()]
        e._logic = None
        e.flag_owner[(~e.revealed) & ~e.mines] = 0
        self.assertTrue(all(torch.equal(x, y) for x, y in zip(before, e.logic())))

    def test_v5_shapes_upgrade_and_planes(self):
        from ai.env import MineEnv, obs_dim, n_channels, N_CHANNELS_V5, N_GLOBAL_V5, DIG0
        from ai.policy import Spec, upgrade
        s5 = Spec(2, [16, 8], "tanh", 5)
        self.assertEqual((s5.in_dim, s5.out_dim, n_channels(5)), (25 * N_CHANNELS_V5 + N_GLOBAL_V5, 28, 19))
        e = MineEnv(8, 2, 12, 12, 20, 100, 3, rich=True, mode="mixed", bosses=True, powers=True)
        e.step(torch.full((8, 2), DIG0 + 4))
        e.traps.zero_(); e.items.zero_()
        o5 = e.observe(0, 2, 5)
        self.assertEqual(tuple(o5.shape), (8, obs_dim(2, 5)))
        self.assertTrue(torch.equal(o5[:, :16 * 25], e.observe(0, 2, 4)[:, :16 * 25]), "v4's planes come first")
        safe, mine = e.logic()
        planes = o5[:, :19 * 25].view(8, 19, 25)
        # the window holds exactly the proven tiles around the agent
        win = lambda t: E_window(t, e.pos[:, 0], 2)
        self.assertTrue(torch.equal(planes[:, 16].bool(), win(safe)))
        self.assertTrue(torch.equal(planes[:, 17].bool(), win(mine)))
        for old_v in (2, 3, 4):
            old = Spec(2, [16, 8], "tanh", old_v)
            w = old.init(1)[0] + torch.randn(old.n_params) * 0.3
            w5 = upgrade(old, w, s5)
            self.assertEqual(w5.numel(), s5.n_params)
            if old_v == 4:
                l4 = old.forward(w[None], e.observe(0, 2, 4)[None])[0]
                l5 = s5.forward(w5[None], o5[None])[0]
                self.assertTrue(torch.allclose(l4, l5, atol=1e-5), "an upgraded v4 plays exactly as before")

    def test_in_game_v5_bot_sees_the_hint(self):
        from ai.bots import Brain
        from ai.policy import Spec
        from ai import env as E
        from helpers import S, field_room
        r = field_room("race", name="v5")
        r.generate(20, 20)
        bot = Brain.__new__(Brain)
        bot.name, bot.spec = "v5", Spec(3, [16], "tanh", 5)
        bot.w = bot.spec.init(1)
        # dig an opening the way the server does, then check what the brain would see
        for i in range(S.W * S.H):
            x, y = i % S.W, i // S.W
            if max(abs(x - 20), abs(y - 20)) <= 4 and i not in r.mines:
                r.revealed[i] = 1
        act = bot.decide(S.W, S.H, r.revealed, r.counts, [], {}, "me", (20, 20), [], r.floor,
                         {"hp": 1, "mode": "race", "held": "", "shield": False, "use_ok": False})
        self.assertIn(act[0], ("move", "dig", "flag", "attack", "use"))
        rev = torch.tensor(list(r.revealed), dtype=torch.bool).view(1, S.H, S.W)
        cnt = torch.tensor(r.counts).view(1, S.H, S.W)
        mines = torch.zeros(1, S.H * S.W, dtype=torch.bool)
        mines[0, list(r.mines)] = True
        safe, mine = E.deduce(rev, cnt, torch.zeros_like(rev), torch.tensor(list(r.floor), dtype=torch.bool).view(1, S.H, S.W))
        self.assertFalse(bool((safe & mines.view(1, S.H, S.W)).any()))
        self.assertFalse(bool((mine & ~mines.view(1, S.H, S.W)).any()))


@unittest.skipIf(torch is None, "PyTorch not installed")
class Curriculum(unittest.TestCase):
    def test_dig_practice_starts_part_dug_at_the_edge(self):
        from ai import env as E
        torch.manual_seed(3)
        for layout, mines in (("field", 30), ("dungeon", 50)):
            env = E.MineEnv(64, 2, 16, 16, mines, 50, 3, device="cpu", layout=layout, params={"dig_practice": 1.0})
            self.assertTrue(bool(env.generated.all()))
            self.assertFalse(bool((env.revealed & env.mines).any()), "no mine starts dug")
            self.assertTrue(bool(env.revealed.reshape(64, -1).any(1).all()))
            c = F.conv2d(env.mines.float()[:, None], torch.ones(1, 1, 3, 3), padding=1)[:, 0].long() - env.mines.long()
            self.assertTrue(torch.equal(c, env.counts))
            covered = env.floor & ~env.revealed
            edge = env.revealed & (F.max_pool2d(covered.float()[:, None], 3, 1, 1)[:, 0] > 0)
            for a in range(2):
                y, x = env.pos[:, a, 0], env.pos[:, a, 1]
                on = edge[torch.arange(64), y, x]
                self.assertTrue(bool(on.all()), f"{layout}: every agent starts next to something to dig")
                self.assertTrue(bool(env.mask(a)[:, E.DIG0:E.FLAG0].any(1).all()))
            r = env.step(torch.full((64, 2), E.DIG0 + 4))      # digging your own (dug) tile does nothing
            self.assertEqual(float(env.stats["mines_hit"].sum()), 0.0)
        off = E.MineEnv(16, 1, 16, 16, 30, 50, 3, device="cpu")
        self.assertFalse(bool(off.generated.any()), "without practice the first dig places the mines")

    def test_ease_in(self):
        from ai import evolve
        cfg = evolve.sanitize({"mines": 80, "reward_mine": -10, "curriculum_gens": 10,
                               "curriculum_mines": 0.5, "curriculum_mine_penalty": 0.2})
        first, f0 = evolve.stage(cfg, 0)
        mid, f5 = evolve.stage(cfg, 5)
        done, f10 = evolve.stage(cfg, 25)
        self.assertEqual((first["mines"], first["reward_mine"], f0), (40, -2.0, 0.0))
        self.assertEqual((mid["mines"], round(mid["reward_mine"], 6), f5), (60, -6.0, 0.5))
        self.assertEqual((done["mines"], done["reward_mine"], f10), (80, -10.0, 1.0))
        self.assertEqual(cfg["mines"], 80, "the run's own settings are untouched")
        self.assertEqual(evolve.stage(evolve.sanitize({}), 3)[1], None)


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

    async def test_v4_bot_uses_its_item(self):
        """A v4 bot (upgraded from v3, so it uses items whenever they'd hit) freezes a rival in PvP,
        and the built-in rule no longer fires for it."""
        from ai.bots import Brain
        from ai.policy import Spec, upgrade
        from helpers import S, player, at, field_room
        r = field_room("pvp", name="v4")
        h = player(r, "H")
        bot = S.BotPlayer(Brain.__new__(Brain), "bot", "#123", "robot", "insane", 0.05)
        s3, s4 = Spec(3, [16], "tanh", 3), Spec(3, [16], "tanh", 4)
        bot.brain.name, bot.brain.spec = "v4", s4
        bot.brain.w = upgrade(s3, s3.init(1)[0], s4)[None]
        r.players[bot.id] = bot
        at(bot, 20, 20); bot.tx, bot.tz = bot.x, bot.z
        at(h, 24, 20)
        r.generate(10, 10)
        bot.held, bot.throw_at = "freeze", 0
        t0 = 1e9
        for k in range(10):
            await r.update_bots(t0 + k * 0.1, 0.1)
            if not bot.held:
                break
        self.assertIsNone(bot.held, "the v4 bot used its freeze")
        self.assertGreater(h.frozen_until, 0)

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
