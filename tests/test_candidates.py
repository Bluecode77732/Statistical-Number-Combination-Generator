import unittest
from unittest import mock

import numpy as np

import candidates
import models
from tests.helpers import make_draws


class CandidatesTest(unittest.TestCase):
    def check_shape(self, nums):
        self.assertEqual(len(nums), 10)
        self.assertEqual(len(set(nums)), 10)
        self.assertTrue(all(1 <= n <= 45 for n in nums))
        self.assertEqual(nums, sorted(nums))

    def test_logistic_candidates(self):
        c = candidates.next_candidates(make_draws(200))
        self.assertEqual(c["method"], "logistic")
        self.assertEqual(c["target_round"], 201)
        self.check_shape(c["numbers"])
        self.assertIsNone(c["fallback_reason"])
        self.assertEqual(len(c["weights"]), len(models.FEATURE_NAMES) + 1)

    # 목적: 첫 화면 후보가 점수 상위 10개이고, 직전 회차와의 겹침이 올바르게 담기는지 확인한다.
    # 이유: 2026-11-20 사용자 결정으로 점수 상위 10개로 돌아갔다. 화면은 겹침 개수로 "직전 번호는 근거가 아님"을 설명한다.
    # 방법: 200회 가짜 데이터로 후보를 만들고, 같은 학습의 반올림 전 점수 상위 10개와 겹침을 직접 다시 계산해 비교한다.
    def test_top10_and_previous_round_fields(self):
        draws = make_draws(200)
        c = candidates.next_candidates(draws)
        _, scores, _ = candidates._train(draws)
        self.assertEqual(c["numbers"], sorted(int(i) + 1 for i in np.argsort(-scores)[:10]))
        self.assertNotIn("groups", c)
        self.assertEqual(c["previous_round"], 200)
        self.assertEqual(c["previous_overlap"], sorted(set(draws[-1].numbers) & set(c["numbers"])))

    # 목적: 같은 데이터로 두 번 고른 첫 화면 후보가 같은지 확인한다.
    # 이유: 첫 화면은 동점 무작위가 없는 점수 상위 10개라, 같은 데이터면 같은 후보여야 한다(사용자 결정).
    # 방법: 같은 가짜 데이터로 next_candidates를 두 번 부른다.
    def test_top10_is_repeatable(self):
        draws = make_draws(200)
        self.assertEqual(candidates.next_candidates(draws)["numbers"], candidates.next_candidates(draws)["numbers"])

    # 목적: 재산출 후보가 재산출 규칙(점수 5 · 최근 5회 2 · 빈도 3)으로 나오고, 묶음과 회차 범위가 담기는지 확인한다.
    # 이유: 화면이 묶음별 번호와 "최근 5회(몇~몇 회)", "최근 50회(몇~몇 회)"를 밝힌다(핵심 규칙 7).
    # 방법: 200회 가짜 데이터로 재산출 후보를 만들고 방식, 모양, 묶음 개수, 회차 범위, a가 첫 화면 10개 안에 있는지 본다.
    def test_redraw_uses_mixed_rule(self):
        draws = make_draws(200)
        c = candidates.redraw_candidates(draws)
        self.assertEqual(c["method"], "mixed")
        self.check_shape(c["numbers"])
        self.assertEqual([len(g["numbers"]) for g in c["groups"]], [5, 2, 1, 2])
        self.assertEqual(c["recent_rounds"], [196, 200])
        self.assertEqual(c["freq_rounds"], [151, 200])
        self.assertEqual(c["previous_round"], 200)
        self.assertTrue(set(c["groups"][0]["numbers"]) <= set(candidates.next_candidates(draws)["numbers"]))
        recent = set().union(*[set(d.numbers) for d in draws[-5:]])
        self.assertTrue(set(c["groups"][1]["numbers"]) <= recent)

    # 목적: 데이터가 50회보다 적으면 재산출은 무작위로 대체하고, 첫 화면은 30회 이상이면 모델을 쓰는지 확인한다.
    # 이유: 재산출 규칙은 최근 50회 출현 횟수를 쓰므로 그보다 적으면 규칙 10대로 대체해야 한다.
    # 방법: 40회 가짜 데이터로 두 함수를 부른다.
    def test_redraw_fallback_when_under_50_rounds(self):
        draws = make_draws(40)
        c = candidates.redraw_candidates(draws)
        self.assertEqual(c["method"], "random")
        self.assertIn("최소 50회차", c["fallback_reason"])
        self.check_shape(c["numbers"])
        self.assertEqual(candidates.next_candidates(draws)["method"], "logistic")

    # 목적: 재산출 중 모델이 실패하면 무작위 10개와 이유를 내는지 확인한다.
    # 이유: 핵심 규칙 10은 재산출에도 적용된다.
    # 방법: fit이 LinAlgError를 내도록 바꿔 재산출한다.
    def test_redraw_fallback_when_model_fails(self):
        with mock.patch.object(models.LogisticModel, "fit", side_effect=np.linalg.LinAlgError("singular")):
            c = candidates.redraw_candidates(make_draws(200))
        self.assertEqual(c["method"], "random")
        self.assertIn("LinAlgError", c["fallback_reason"])
        self.check_shape(c["numbers"])

    def test_one_set_only(self):
        c = candidates.next_candidates(make_draws(200))
        self.assertIsInstance(c["numbers"][0], int)  # 조합 여러 개가 아니라 숫자 한 세트

    # 목적: 데이터가 적으면 무작위 대체 후보를 내고, 그때도 직전 회차 겹침을 붙이는지 확인한다.
    # 이유: 핵심 규칙 10의 대체 동작이며, 화면의 직전 번호 설명은 대체 후보에도 나온다.
    # 방법: 10회 가짜 데이터로 후보를 만든다.
    def test_fallback_when_too_few_rounds(self):
        c = candidates.next_candidates(make_draws(10))
        self.assertEqual(c["method"], "random")
        self.assertIn("최소", c["fallback_reason"])
        self.check_shape(c["numbers"])
        self.assertEqual(c["previous_round"], 10)  # 대체 후보에도 직전 회차 겹침을 붙인다

    # 목적: ModelError가 아닌 오류(재현 E4의 LinAlgError)에도 무작위 10개와 대체 이유를 내는지 확인한다.
    # 이유: 예전에는 예외가 그대로 퍼져 후보 없이 끝났다(감사 A-01, 핵심 규칙 10).
    # 방법: fit이 LinAlgError를 내도록 바꿔 후보를 만들고, 방식·이유·모양·직전 회차 겹침을 본다.
    def test_fallback_when_unexpected_error(self):
        with mock.patch.object(models.LogisticModel, "fit", side_effect=np.linalg.LinAlgError("singular")):
            c = candidates.next_candidates(make_draws(200))
        self.assertEqual(c["method"], "random")
        self.assertIn("LinAlgError", c["fallback_reason"])
        self.check_shape(c["numbers"])
        self.assertEqual(c["previous_round"], 200)

    def test_fallback_when_model_fails(self):
        with mock.patch.object(models.LogisticModel, "fit", side_effect=models.ModelError("발산")):
            c = candidates.next_candidates(make_draws(200))
        self.assertEqual(c["method"], "random")
        self.assertIn("발산", c["fallback_reason"])
        self.check_shape(c["numbers"])


if __name__ == "__main__":
    unittest.main()
