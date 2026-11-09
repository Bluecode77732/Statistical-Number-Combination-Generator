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

    # 목적: 후보 결과에 확정 번호, 동점 묶음 크기, 직전 회차와의 겹침이 올바르게 담기는지 확인한다.
    # 이유: 화면이 이 값으로 선정 방식과 "직전 번호는 근거가 아님"을 설명한다.
    # 방법: 200회 가짜 데이터로 후보를 만들고, 겹침을 직접 다시 계산해 비교한다.
    def test_tie_and_previous_round_fields(self):
        draws = make_draws(200)
        c = candidates.next_candidates(draws)
        self.assertTrue(set(c["firm"]) <= set(c["numbers"]))
        self.assertGreaterEqual(c["tie_pool"], 10 - len(c["firm"]))
        self.assertEqual(c["tie_z"], models.TIE_Z)
        self.assertEqual(c["previous_round"], 200)
        self.assertEqual(c["previous_overlap"], sorted(set(draws[-1].numbers) & set(c["numbers"])))

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
