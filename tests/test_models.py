import random
import unittest
from unittest import mock

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
    # 목적: 첫 화면 선택(점수 상위 10개)이 10개·중복 없음·1~45·오름차순이고, 점수 상위 10개 그대로인지 확인한다.
    # 이유: 2026-11-20에 동점 처리를 거두고 점수 상위 10개로 돌아갔다. 핵심 규칙 5의 모양도 지켜야 한다.
    # 방법: 서로 다른 무작위 점수로 50번 고르고, argsort로 직접 구한 상위 10개와 비교한다.
    def test_top_candidates_are_highest_scores(self):
        rng = np.random.default_rng(0)
        for _ in range(50):
            scores = rng.random(45)
            got = models.top_candidates(scores, rng)
            self.assertEqual(got, sorted(int(i) + 1 for i in np.argsort(-scores)[:10]))
            self.assertEqual(len(set(got)), 10)
            self.assertTrue(all(1 <= n <= 45 for n in got))

    # 목적: 점수가 서로 다르면 난수와 상관없이 같은 후보가 나오는지 확인한다.
    # 이유: 첫 화면은 "동점 무작위 없음"이 사용자 결정이다. 같은 데이터면 같은 후보여야 한다.
    # 방법: 같은 점수로 난수 씨앗만 바꿔 20번 고른다.
    def test_top_candidates_ignore_rng_without_exact_ties(self):
        scores = np.random.default_rng(7).random(45)
        seen = {tuple(models.top_candidates(scores, np.random.default_rng(s))) for s in range(20)}
        self.assertEqual(len(seen), 1)

    # 목적: 점수가 정확히 같은 번호끼리는 번호가 작은 쪽이 항상 이기지 않는지 확인한다.
    # 이유: 같은 점수를 번호순으로 가르면 그 자체가 근거 없는 편향이 된다.
    # 방법: 모든 점수가 같을 때 20번 고른 결과가 한 가지가 아니어야 한다.
    def test_exact_ties_are_not_always_lowest_numbers(self):
        rng = np.random.default_rng(1)
        seen = {tuple(models.top_candidates(np.zeros(45), rng)) for _ in range(20)}
        self.assertGreater(len(seen), 1)


# 목적: 테스트용 (회차, 45) 출현 행렬을 만든다.
# 이유: 재산출 규칙은 출현 행렬만 받으므로, 회차 데이터 없이도 규칙을 직접 시험할 수 있다.
# 방법: 회차마다 1~45 중 6개를 무작위로 골라 1로 표시한다.
def random_hits(rounds: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    hits = np.zeros((rounds, 45))
    for r in range(rounds):
        hits[r, rng.choice(45, 6, replace=False)] = 1.0
    return hits


class MixedSelectionTest(unittest.TestCase):
    # 목적: 재산출 규칙의 결과가 10개·중복 없음·1~45·오름차순이고, 묶음별 개수(5·2·1·2)와 겹침 없음을 지키는지 확인한다.
    # 이유: 사용자가 정한 규칙(2026-11-20)과 핵심 규칙 5의 모양이다.
    # 방법: 무작위 점수와 무작위 출현 행렬로 50번 고르고, 묶음의 합집합이 후보와 같은지 본다.
    def test_shape_and_group_sizes(self):
        rng = np.random.default_rng(10)
        for seed in range(50):
            got = models.mixed_candidates(rng.random(45), random_hits(80, seed), rng)
            nums = got["numbers"]
            self.assertEqual(len(nums), 10)
            self.assertEqual(len(set(nums)), 10)
            self.assertTrue(all(1 <= n <= 45 for n in nums))
            self.assertEqual(nums, sorted(nums))
            sizes = {g["key"]: len(g["numbers"]) for g in got["groups"]}
            self.assertEqual(sizes, {"model": 5, "recent": 2, "hot": 1, "cold": 2})
            union = [n for g in got["groups"] for n in g["numbers"]]
            self.assertEqual(sorted(union), nums)

    # 목적: a는 점수 상위 5개, b는 최근 5회 번호 중 a에 없는 것, c는 남은 번호 중 최근 50회 최다·최소 출현인지 확인한다.
    # 이유: 묶음마다 화면에 적은 정의와 실제 선택이 같아야 한다(핵심 규칙 7).
    # 방법: 무작위 데이터로 30번 고르고, 각 묶음을 정의대로 직접 계산한 값과 비교한다.
    def test_groups_follow_their_definitions(self):
        rng = np.random.default_rng(11)
        for seed in range(30):
            scores, hits = rng.random(45), random_hits(120, seed)
            got = {g["key"]: g for g in models.mixed_candidates(scores, hits, rng)["groups"]}
            top5 = sorted(int(i) + 1 for i in np.argsort(-scores)[:5])
            self.assertEqual(got["model"]["numbers"], top5)
            self.assertTrue(set(top5) <= set(models.top_candidates(scores, rng)))  # 첫 화면 10개와 같은 점수
            recent = {int(i) + 1 for i in np.flatnonzero(hits[-5:].sum(axis=0))}
            self.assertTrue(set(got["recent"]["numbers"]) <= recent - set(top5))
            self.assertEqual(got["recent"]["pool"], len(recent - set(top5)))
            counts = hits[-50:].sum(axis=0)
            taken = set(top5) | set(got["recent"]["numbers"])
            left = [n for n in range(1, 46) if n not in taken]
            hot = got["hot"]["numbers"][0]
            self.assertEqual(counts[hot - 1], max(counts[n - 1] for n in left))
            self.assertEqual(got["hot"]["picks"][0]["count"], int(counts[hot - 1]))
            left.remove(hot)
            low2 = sorted(counts[n - 1] for n in left)[:2]
            self.assertEqual(sorted(counts[n - 1] for n in got["cold"]["numbers"]), low2)

    # 목적: 같은 출현 횟수끼리는 무작위로 고르고, 같은 횟수의 번호 수(tied)를 올바르게 남기는지 확인한다.
    # 이유: "쪽"의 정의(같은 횟수는 무작위, 모자라면 다음 횟수)를 화면이 tied로 설명한다.
    # 방법: 최근 50회에서 5개 번호만 0번, 나머지는 여러 번 나오게 만들고 점수 상위 5개와 최근 5회를 그 밖에 둔다.
    #       최소 출현 2개는 늘 0번인 5개 중에서 나오고, 20번 고르면 여러 조합이 나와야 한다.
    def test_cold_ties_are_random_and_reported(self):
        hits = np.zeros((60, 45))
        for r in range(60):
            hits[r, [(r * 6 + j) % 35 for j in range(6)]] = 1.0  # 1~35번만 나옴
        hits[:, 35:40] = 1.0  # 36~40번은 모든 회차에 나옴(최다 쪽)
        scores = np.zeros(45)
        scores[:5] = 1.0  # 점수 상위 5개는 1~5번
        rng = np.random.default_rng(12)
        seen = set()
        for _ in range(20):
            got = {g["key"]: g for g in models.mixed_candidates(scores, hits, rng)["groups"]}
            self.assertTrue(set(got["cold"]["numbers"]) <= {41, 42, 43, 44, 45})
            self.assertTrue(all(p["count"] == 0 and p["tied"] == 5 for p in got["cold"]["picks"]))
            self.assertIn(got["hot"]["numbers"][0], {36, 37, 38, 39, 40})
            seen.add(tuple(got["cold"]["numbers"]))
        self.assertGreater(len(seen), 1)

    # 목적: 최근 5회 번호가 2개보다 적게 남아도 10개를 채우고, 모자란 자리를 보충 묶음으로 밝히는지 확인한다.
    # 이유: 후보 수가 모자랄 때 채우는 법을 정해 두었다(코드 주석·화면·문서). 실제 데이터에서는 일어나지 않는다.
    # 방법: 최근 5회가 모두 1~6번이고 점수 상위 5개가 1~5번이면 b의 대상은 6번 하나뿐이다.
    def test_shortage_is_filled_and_labelled(self):
        hits = random_hits(60, 3)
        hits[-5:] = 0.0
        hits[-5:, :6] = 1.0
        scores = np.zeros(45)
        scores[:5] = 1.0
        got = models.mixed_candidates(scores, hits, np.random.default_rng(13))
        groups = {g["key"]: g for g in got["groups"]}
        self.assertEqual(groups["recent"]["numbers"], [6])
        self.assertEqual(len(groups["fill"]["numbers"]), 1)
        self.assertEqual(len(set(got["numbers"])), 10)

    # 목적: 재산출 규칙이 최근 50회보다 오래된 회차를 쓰지 않는지 확인한다.
    # 이유: 정의가 "최근 5회", "최근 50회"라 그 밖의 기록이 결과를 바꾸면 화면 설명과 어긋난다.
    # 방법: 같은 난수 씨앗으로, 마지막 50회 앞의 기록만 바꾼 두 행렬에서 고른 결과가 같아야 한다.
    def test_uses_only_last_50_rounds(self):
        hits = random_hits(200, 4)
        changed = hits.copy()
        changed[:150] = random_hits(150, 99)
        scores = np.random.default_rng(5).random(45)
        a = models.mixed_candidates(scores, hits, np.random.default_rng(6))
        b = models.mixed_candidates(scores, changed, np.random.default_rng(6))
        self.assertEqual(a, b)

    # 목적: 이전 회차가 50회보다 적으면 재산출 규칙을 쓰지 않고 ModelError를 내는지 확인한다.
    # 이유: 최근 50회 출현 횟수를 셀 수 없으면 무작위 대체로 넘어가야 한다(핵심 규칙 10).
    # 방법: 49회 행렬로 부른다.
    def test_requires_50_rounds(self):
        with self.assertRaises(models.ModelError):
            models.mixed_candidates(np.zeros(45), random_hits(49, 1), np.random.default_rng(0))

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

    # 목적: 뉴턴 단계의 방정식을 풀지 못하면 LinAlgError 대신 ModelError가 나는지 확인한다.
    # 이유: ModelError만 무작위 대체로 이어지던 시절의 구멍(감사 A-01, E4)을 모델 쪽에서도 막는다.
    # 방법: np.linalg.solve가 LinAlgError를 내도록 바꿔 fit을 부른다. 화면용 문장도 한국어인지 본다.
    def test_linalg_error_becomes_model_error(self):
        rng = np.random.default_rng(6)
        X = rng.normal(size=(200, 2))
        y = (rng.random(200) < 0.3).astype(float)
        with mock.patch.object(models.np.linalg, "solve", side_effect=np.linalg.LinAlgError("singular")):
            with self.assertRaises(models.ModelError) as ctx:
                models.LogisticModel().fit(X, y)
        self.assertIn("방정식", models.describe_model_error(ctx.exception))
        self.assertIn("ZeroDivisionError", models.describe_model_error(ZeroDivisionError()))

    def test_single_class_raises(self):
        with self.assertRaises(models.ModelError):
            models.LogisticModel().fit(np.ones((10, 2)), np.zeros(10))

    def test_unfitted_scores_raise(self):
        with self.assertRaises(models.ModelError):
            models.LogisticModel().scores(np.ones((1, 7)))


if __name__ == "__main__":
    unittest.main()
