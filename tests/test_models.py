import random
import unittest

import numpy as np

import models
from excel_loader import LottoDraw
from tests.helpers import make_draws


class FeatureLeakTest(unittest.TestCase):
    def test_features_for_round_t_ignore_rounds_from_t_on(self):
        draws = make_draws(150, seed=3)
        X, _ = models.build_features(draws)
        t = 120
        changed = draws[:t] + [LottoDraw(d.round_no, [40, 41, 42, 43, 44, 45], 1, d.draw_date) for d in draws[t:]]
        X2, _ = models.build_features(changed)
        np.testing.assert_array_equal(X[: t + 1], X2[: t + 1])  # X[t]까지는 draws[:t]만 사용
        self.assertFalse(np.array_equal(X[t + 1], X2[t + 1]))   # 그 뒤는 바뀌어야 정상

    def test_training_rows_end_before_target(self):
        draws = make_draws(50)
        X, hits = models.build_features(draws)
        Xtr, ytr = models.training_rows(X, hits, 30)
        self.assertEqual(len(Xtr), 29 * 45)  # 1~29번째 회차(0번째는 이전 기록 없음)
        np.testing.assert_array_equal(ytr, hits[1:30].reshape(-1))


class SelectionTest(unittest.TestCase):
    def test_top_candidates_shape(self):
        rng = np.random.default_rng(0)
        for _ in range(50):
            got = models.top_candidates(rng.random(45), rng)
            self.assertEqual(len(got), 10)
            self.assertEqual(len(set(got)), 10)
            self.assertTrue(all(1 <= n <= 45 for n in got))
            self.assertEqual(got, sorted(got))

    def test_ties_are_not_always_lowest_numbers(self):
        rng = np.random.default_rng(1)
        seen = {tuple(models.top_candidates(np.zeros(45), rng)) for _ in range(20)}
        self.assertGreater(len(seen), 1)

    def test_highest_scores_win(self):
        scores = np.zeros(45)
        scores[[0, 4, 9, 14, 19, 24, 29, 34, 39, 44]] = 1.0
        self.assertEqual(models.top_candidates(scores, np.random.default_rng(0)),
                         [1, 5, 10, 15, 20, 25, 30, 35, 40, 45])

    def test_random_candidates(self):
        got = models.random_candidates(random.Random(5))
        self.assertEqual(len(set(got)), 10)
        self.assertEqual(got, sorted(got))


class LogisticTest(unittest.TestCase):
    def test_learns_real_signal(self):
        rng = np.random.default_rng(0)
        X = rng.normal(size=(4000, 2))
        y = (rng.random(4000) < 1 / (1 + np.exp(-(2 * X[:, 0])))).astype(float)
        m = models.LogisticModel(lam=0.0).fit(X, y)
        self.assertGreater(m.w[1], 1.5)          # 진짜 신호는 큰 가중치
        self.assertLess(abs(m.w[2]), 0.3)        # 잡음은 0 근처
        s = m.scores(X[:10])
        self.assertTrue(np.all((s > 0) & (s < 1)))

    def test_single_class_raises(self):
        with self.assertRaises(models.ModelError):
            models.LogisticModel().fit(np.ones((10, 2)), np.zeros(10))

    def test_unfitted_scores_raise(self):
        with self.assertRaises(models.ModelError):
            models.LogisticModel().scores(np.ones((1, 7)))


if __name__ == "__main__":
    unittest.main()
