import unittest
from unittest import mock

import numpy as np

import backtest
import models
from tests.helpers import make_draws


class BacktestTest(unittest.TestCase):
    def setUp(self):
        self.draws = make_draws(160, seed=7)

    def test_walk_forward_uses_only_prior_rounds(self):
        seen = []
        real_fit = models.LogisticModel.fit

        def spy(self_model, X, y, init=None):
            seen.append(len(X))
            return real_fit(self_model, X, y, init)

        with mock.patch.object(models.LogisticModel, "fit", spy):
            result = backtest.run_backtest(self.draws, start_round=101)
        # 회차 t(1부터) 예측 시 학습 행은 (t-2)회차×45: 0번째 회차는 이전 기록이 없어 빠진다
        expected = [(r - 2) * 45 for r in range(101, 161)]
        self.assertEqual(seen[: len(expected)], expected)
        self.assertEqual(seen[len(expected)], 159 * 45)  # 마지막 1번은 과적합 확인용 전체 학습

    def test_counts_and_separation(self):
        r = backtest.run_backtest(self.draws, start_round=101)
        self.assertTrue(r["ran"])
        self.assertEqual((r["start_round"], r["end_round"], r["rounds"]), (101, 160, 60))
        self.assertEqual(len(r["actuals"]), 60)
        self.assertEqual(len(r["predictions"]), 120)  # 모델 2개 × 60회
        for s in r["summaries"]:
            self.assertEqual(sum(s["distribution"]), 60)
            self.assertLessEqual(s["ci_low"], s["mean"])
        for p in r["predictions"]:
            self.assertEqual(len(set(p["candidates"])), 10)
            self.assertNotIn("numbers", p)  # 예측 목록에 실제 번호가 섞이지 않음

    def test_matches_are_recomputable_from_saved_lists(self):
        r = backtest.run_backtest(self.draws, start_round=101)
        actual = {a["round"]: set(a["numbers"]) for a in r["actuals"]}
        for key in ("logistic", "random"):
            hits = [len(actual[p["round"]] & set(p["candidates"])) for p in r["predictions"] if p["model"] == key]
            summary = next(s for s in r["summaries"] if s["key"] == key)
            self.assertEqual([hits.count(m) for m in range(7)], summary["distribution"])

    # 목적: 무작위 이론값과 화면 설명에 쓰는 95% 기준값이 맞는지 확인한다.
    # 이유: 95% 범위와 판정의 정의를 화면에 적을 때 서버 값과 같아야 한다(감사 A-03).
    # 방법: 이론 평균·분포 합을 직접 계산하고, 백테스트 결과의 theory.z95가 Z95인지 본다.
    def test_theory_values(self):
        self.assertAlmostEqual(backtest.THEORY_MEAN, 10 * 6 / 45)
        r = backtest.run_backtest(self.draws, start_round=101)
        self.assertEqual(r["theory"]["z95"], backtest.Z95)  # 화면의 95% 범위·판정 설명에 쓴다 (A-03)
        self.assertAlmostEqual(sum(backtest.THEORY_PMF), 1.0)
        self.assertAlmostEqual(sum(m * p for m, p in enumerate(backtest.THEORY_PMF)), backtest.THEORY_MEAN)

    def test_not_enough_data(self):
        r = backtest.run_backtest(make_draws(50), start_round=101)
        self.assertFalse(r["ran"])

    # 목적: ModelError가 아닌 오류에도 백테스트가 멈추지 않고 기준선과 오류 기록을 남기는지 확인한다.
    # 이유: 예전에는 LinAlgError가 퍼져 백테스트 단계가 "진행 중"에 멈췄다(감사 A-01, E5).
    # 방법: fit이 LinAlgError를 내도록 바꿔 백테스트를 돌리고 요약과 model_errors를 본다.
    def test_unexpected_model_error_keeps_baseline(self):
        with mock.patch.object(models.LogisticModel, "fit", side_effect=np.linalg.LinAlgError("singular")):
            r = backtest.run_backtest(self.draws, start_round=101)
        self.assertTrue(r["ran"])
        self.assertEqual([s["key"] for s in r["summaries"]], ["random"])
        self.assertIn("LinAlgError", r["model_errors"][0])

    def test_model_failure_keeps_baseline(self):
        with mock.patch.object(models.LogisticModel, "fit", side_effect=models.ModelError("boom")):
            r = backtest.run_backtest(self.draws, start_round=101)
        self.assertEqual([s["key"] for s in r["summaries"]], ["random"])
        self.assertTrue(r["model_errors"])


if __name__ == "__main__":
    unittest.main()
