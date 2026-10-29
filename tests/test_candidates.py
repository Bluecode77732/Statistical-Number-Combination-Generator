import unittest
from unittest import mock

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

    def test_one_set_only(self):
        c = candidates.next_candidates(make_draws(200))
        self.assertIsInstance(c["numbers"][0], int)  # 조합 여러 개가 아니라 숫자 한 세트

    def test_fallback_when_too_few_rounds(self):
        c = candidates.next_candidates(make_draws(10))
        self.assertEqual(c["method"], "random")
        self.assertIn("최소", c["fallback_reason"])
        self.check_shape(c["numbers"])

    def test_fallback_when_model_fails(self):
        with mock.patch.object(models.LogisticModel, "fit", side_effect=models.ModelError("발산")):
            c = candidates.next_candidates(make_draws(200))
        self.assertEqual(c["method"], "random")
        self.assertIn("발산", c["fallback_reason"])
        self.check_shape(c["numbers"])


if __name__ == "__main__":
    unittest.main()
