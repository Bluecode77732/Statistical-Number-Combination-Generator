import unittest
from unittest import mock

import numpy as np

import backtest
import models
from excel_loader import LottoDraw
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

    # 목적: 세 방식(첫 화면, 재산출 규칙, 무작위)이 모두 회차마다 예측을 남기고 요약이 회차 수와 맞는지 확인한다.
    # 이유: 2026-11-20부터 두 선택 방식을 함께 잰다. 예측 목록에 실제 번호가 섞이면 안 된다.
    # 방법: 160회 가짜 데이터로 101~160회를 시험하고 개수, 요약 순서, 분포 합, 후보 모양을 본다.
    def test_counts_and_separation(self):
        r = backtest.run_backtest(self.draws, start_round=101)
        self.assertTrue(r["ran"])
        self.assertEqual((r["start_round"], r["end_round"], r["rounds"]), (101, 160, 60))
        self.assertEqual(len(r["actuals"]), 60)
        self.assertEqual(len(r["predictions"]), 180)  # 방식 3개 × 60회
        self.assertEqual([s["key"] for s in r["summaries"]], ["logistic", "mixed", "random"])
        for s in r["summaries"]:
            self.assertEqual(sum(s["distribution"]), 60)
            self.assertLessEqual(s["ci_low"], s["mean"])
        for p in r["predictions"]:
            self.assertEqual(len(set(p["candidates"])), 10)
            self.assertEqual(p["candidates"], sorted(p["candidates"]))
            self.assertNotIn("numbers", p)  # 예측 목록에 실제 번호가 섞이지 않음

    # 목적: 저장된 예측과 실제 목록만으로 방식별 일치 분포와 직전 회차 포함 평균을 다시 계산할 수 있는지 확인한다.
    # 이유: 화면과 backtest.xlsx의 값이 저장된 목록과 어긋나면 측정을 믿을 수 없다(핵심 규칙 8).
    # 방법: 세 방식마다 일치 개수 분포와 "직전 회차 당첨번호 중 후보에 든 개수"의 평균을 직접 센다.
    def test_matches_are_recomputable_from_saved_lists(self):
        r = backtest.run_backtest(self.draws, start_round=101)
        actual = {a["round"]: set(a["numbers"]) for a in r["actuals"]}
        prev = {d.round_no + 1: set(d.numbers) for d in self.draws}
        for key in ("logistic", "mixed", "random"):
            preds = [p for p in r["predictions"] if p["model"] == key]
            hits = [len(actual[p["round"]] & set(p["candidates"])) for p in preds]
            summary = next(s for s in r["summaries"] if s["key"] == key)
            self.assertEqual([hits.count(m) for m in range(7)], summary["distribution"])
            prev_mean = sum(len(prev[p["round"]] & set(p["candidates"])) for p in preds) / len(preds)
            self.assertAlmostEqual(summary["prev_overlap_mean"], round(prev_mean, 4))

    # 목적: 두 선택 방식 모두 회차 t 예측이 t 이후 데이터에 영향받지 않는지 확인한다(워크포워드, 핵심 규칙 9).
    # 이유: 재산출 규칙은 최근 5회·50회 출현을 세므로, 범위를 잘못 자르면 미래 회차가 섞일 수 있다.
    # 방법: 140회부터의 당첨번호를 모두 바꾼 데이터로 다시 돌려, 101~140회의 예측이 세 방식 모두 같은지 본다.
    #       140회 예측은 139회까지만 쓰므로 같아야 하고, 141회부터는 달라질 수 있다.
    def test_predictions_ignore_later_rounds(self):
        changed = [d if d.round_no < 140 else LottoDraw(d.round_no, [40, 41, 42, 43, 44, 45], 1, d.draw_date)
                   for d in self.draws]
        a = backtest.run_backtest(self.draws, start_round=101)
        b = backtest.run_backtest(changed, start_round=101)
        keep = [p for p in a["predictions"] if p["round"] <= 140]
        self.assertEqual(keep, [p for p in b["predictions"] if p["round"] <= 140])
        self.assertEqual({p["model"] for p in keep}, {"logistic", "mixed", "random"})

    # 목적: 이전 회차가 50회보다 적은 회차는 재산출 규칙을 재지 않는지 확인한다.
    # 이유: 최근 50회 출현 횟수를 셀 수 없는 회차를 섞으면 정의와 다른 방식을 재게 된다.
    # 방법: 80회 데이터로 30회부터 시험하면 재산출 규칙은 51~80회(30회)만 잰다.
    def test_mixed_needs_50_prior_rounds(self):
        r = backtest.run_backtest(make_draws(80, seed=2), start_round=30)
        mixed = next(s for s in r["summaries"] if s["key"] == "mixed")
        self.assertEqual(mixed["rounds"], 30)
        self.assertEqual(min(p["round"] for p in r["predictions"] if p["model"] == "mixed"), 51)

    # 목적: 고정 SEED 덕분에 다시 돌려도 같은 예측이 나오는지 확인한다.
    # 이유: 재산출 규칙의 무작위 자리도 백테스트에서는 고정 SEED여야 화면의 측정값이 실행마다 바뀌지 않는다.
    # 방법: 같은 데이터로 두 번 돌려 예측 목록과 요약을 비교한다.
    def test_reruns_match(self):
        a = backtest.run_backtest(self.draws, start_round=101)
        b = backtest.run_backtest(self.draws, start_round=101)
        self.assertEqual(a["predictions"], b["predictions"])
        self.assertEqual(a["summaries"], b["summaries"])

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
