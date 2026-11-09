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
    # 목적: 후보 선택 결과가 10개·중복 없음·1~45·오름차순이고, 확정 번호가 후보 안에 있는지 확인한다.
    # 이유: 선택 방식을 순위 자르기에서 동점 묶음 방식으로 바꿔도 핵심 규칙 5의 모양은 그대로여야 한다.
    # 방법: 무작위 점수와 무작위 양의 정부호 공분산으로 50번 고른다.
    def test_select_candidates_shape(self):
        rng = np.random.default_rng(0)
        for _ in range(50):
            B = rng.normal(size=(45, 5)) * 0.05
            got = models.select_candidates(rng.normal(size=45) * 0.05, B @ B.T, rng)
            nums = got["numbers"]
            self.assertEqual(len(nums), 10)
            self.assertEqual(len(set(nums)), 10)
            self.assertTrue(all(1 <= n <= 45 for n in nums))
            self.assertEqual(nums, sorted(nums))
            self.assertTrue(set(got["firm"]) <= set(nums))
            self.assertGreaterEqual(got["tie_pool"], 10 - len(got["firm"]))

    # 목적: 같은 점수끼리는 번호가 작은 쪽이 항상 이기지 않는지 확인한다.
    # 이유: 동점을 번호순으로 가르면 그 자체가 근거 없는 편향이 된다.
    # 방법: 모든 점수가 0이고 오차도 0일 때 20번 고른 결과가 한 가지가 아니어야 한다.
    def test_ties_are_not_always_lowest_numbers(self):
        rng = np.random.default_rng(1)
        seen = {tuple(models.select_candidates(np.zeros(45), np.zeros((45, 45)), rng)["numbers"]) for _ in range(20)}
        self.assertGreater(len(seen), 1)

    # 목적: 오차가 없으면 점수 상위 10개가 그대로 뽑히는지 확인한다.
    # 이유: 오차를 넘는 차이는 선택에 반영되어야 한다(z = 0이면 예전 순위 방식과 같음).
    # 방법: 10개 번호만 점수 1, 나머지 0, 공분산 0으로 고른다.
    def test_highest_scores_win_without_uncertainty(self):
        logits = np.zeros(45)
        logits[[0, 4, 9, 14, 19, 24, 29, 34, 39, 44]] = 1.0
        got = models.select_candidates(logits, np.zeros((45, 45)), np.random.default_rng(0))
        self.assertEqual(got["numbers"], [1, 5, 10, 15, 20, 25, 30, 35, 40, 45])
        self.assertEqual(got["firm"], got["numbers"])
        self.assertEqual(got["tie_pool"], 0)

    # 목적: 오차보다 작은 점수 차이로는 특정 번호들이 쏠려 뽑히지 않는지 확인한다.
    # 이유: 2026-11-09 측정에서 직전 회차 번호 6개가 로짓 +0.04 정도 앞선다는 이유로 매번 4~6개 뽑혔다.
    # 방법: 6개에 +0.04, 표준오차 0.026(실측 수준)을 주고 300번 고른다. 6개의 평균 포함 수가 무작위 기대
    #       10 × 6 / 45 ≈ 1.33 근처(2 미만)이고 확정 번호가 없어야 한다.
    def test_differences_within_error_are_tied(self):
        rng = np.random.default_rng(2)
        logits = np.zeros(45)
        prev = [1, 7, 12, 20, 33, 41]
        logits[prev] = 0.04
        cov = np.eye(45) * 0.026 ** 2
        counts = []
        for _ in range(300):
            got = models.select_candidates(logits, cov, rng)
            self.assertEqual(got["firm"], [])
            counts.append(len({k + 1 for k in prev} & set(got["numbers"])))
        self.assertLess(sum(counts) / len(counts), 2.0)

    # 목적: 오차를 크게 넘는 점수 차이는 확정으로 항상 뽑히는지 확인한다.
    # 이유: 동점 처리가 실제 신호까지 지우면 모델을 쓸 이유가 없다.
    # 방법: 6개에 +1.0, 표준오차 0.026을 주면 6개 모두 확정이고 나머지 4자리만 무작위다.
    def test_differences_beyond_error_are_firm(self):
        logits = np.zeros(45)
        logits[[1, 7, 12, 20, 33, 41]] = 1.0
        got = models.select_candidates(logits, np.eye(45) * 0.026 ** 2, np.random.default_rng(3))
        self.assertEqual(got["firm"], [2, 8, 13, 21, 34, 42])
        self.assertEqual(got["tie_pool"], 39)

    # 목적: z = 0이면 오차가 있어도 점수 순위 상위 10개를 고르는지 확인한다.
    # 이유: 기준값 z가 실제로 동점 판단을 좌우하는지 보여 준다.
    # 방법: 서로 다른 점수 45개와 큰 공분산에서 z = 0으로 고르면 점수 상위 10개(36~45번)와 같아야 한다.
    def test_zero_z_is_plain_ranking(self):
        got = models.select_candidates(np.arange(45.0), np.eye(45) * 100.0, np.random.default_rng(4), z=0.0)
        self.assertEqual(got["numbers"], list(range(36, 46)))

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

    # 목적: 학습 뒤 가중치 공분산과 번호별 로짓·공분산이 올바른 모양과 성질을 갖는지 확인한다.
    # 이유: 동점 판단이 이 공분산에 기대므로, 대칭이 아니거나 음수 분산이 나오면 선택이 틀어진다.
    # 방법: 잡음 데이터로 학습하고 공분산의 대칭·양의 고윳값, 로짓의 시그모이드가 scores와 같은지 본다.
    def test_covariance_and_logits(self):
        rng = np.random.default_rng(5)
        X = rng.normal(size=(3000, 3))
        y = (rng.random(3000) < 0.13).astype(float)
        m = models.LogisticModel().fit(X, y)
        np.testing.assert_allclose(m.cov, m.cov.T)
        self.assertTrue(np.all(np.linalg.eigvalsh(m.cov) > 0))
        logits, cov = m.logits_with_cov(X[:45])
        self.assertEqual(logits.shape, (45,))
        self.assertEqual(cov.shape, (45, 45))
        np.testing.assert_allclose(1 / (1 + np.exp(-logits)), m.scores(X[:45]))

    def test_single_class_raises(self):
        with self.assertRaises(models.ModelError):
            models.LogisticModel().fit(np.ones((10, 2)), np.zeros(10))

    def test_unfitted_scores_raise(self):
        with self.assertRaises(models.ModelError):
            models.LogisticModel().scores(np.ones((1, 7)))


if __name__ == "__main__":
    unittest.main()
