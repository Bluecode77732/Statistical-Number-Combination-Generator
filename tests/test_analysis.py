import unittest

import analysis
from analysis import consecutive, frequency, gaps, last_digit, odd_even, repeats, sections, structure, sums
from excel_loader import LottoDraw

# 손으로 계산할 수 있는 작은 데이터
D = [
    LottoDraw(1, [1, 2, 3, 10, 20, 45], 7),
    LottoDraw(2, [2, 3, 11, 21, 31, 41], 9),
    LottoDraw(3, [5, 15, 25, 35, 40, 44], 1),
]


class AnalysisTest(unittest.TestCase):
    # 목적: 빈도 항목의 출현 수, 보너스 수, 기대값, 회차 수를 손으로 센 값과 비교한다.
    # 이유: 화면이 기대값을 "전체 기간 합계"로 밝히려면 회차 수와 회차당 기대값이 결과에 있어야 한다(감사 A-02).
    # 방법: 3회차짜리 작은 데이터로 계산한다.
    def test_frequency(self):
        r = frequency.compute(D)
        rows = {x["number"]: x for x in r["rows"]}
        self.assertEqual(rows[2]["count"], 2)
        self.assertEqual(rows[4]["count"], 0)
        self.assertEqual(rows[7]["bonus_count"], 1)
        self.assertEqual(r["expected"], round(3 * 6 / 45, 2))
        self.assertEqual(r["rounds"], 3)                 # 기대값이 전체 기간 값임을 화면이 밝히는 데 쓴다 (A-02)
        self.assertEqual(r["per_round"], round(6 / 45, 4))

    def test_odd_even(self):
        rows = {x["odd"]: x["rounds"] for x in odd_even.compute(D)["rows"]}
        self.assertEqual(rows[3], 1)  # 1회: 1, 3, 45
        self.assertEqual(rows[5], 1)  # 2회: 3, 11, 21, 31, 41
        self.assertEqual(rows[4], 1)  # 3회: 5, 15, 25, 35
        self.assertEqual(sum(rows.values()), 3)

    def test_sections(self):
        rows = {x["section"]: x for x in sections.compute(D)["rows"]}
        self.assertEqual(rows["1–10"]["total"], 7)   # 1회 4개(1,2,3,10) + 2회 2개(2,3) + 3회 1개(5)
        self.assertEqual(rows["41–45"]["total"], 3)
        self.assertEqual(sum(r["total"] for r in rows.values()), 18)

    def test_consecutive(self):
        r = consecutive.compute(D)
        pairs = {x["pairs"]: x["rounds"] for x in r["distribution"]}
        self.assertEqual(pairs[2], 1)  # 1회: 1-2, 2-3
        self.assertEqual(pairs[1], 1)  # 2회: 2-3
        self.assertEqual(pairs[0], 1)
        self.assertEqual(r["with_consecutive"], 2)

    def test_sums(self):
        r = sums.compute(D)
        self.assertEqual(r["min"], 81)    # 1+2+3+10+20+45
        self.assertEqual(r["max"], 164)   # 5+15+25+35+40+44
        self.assertEqual(r["median"], 109)

    def test_gaps(self):
        dist = {x["gap"]: x["count"] for x in gaps.compute(D)["distribution"]}
        self.assertEqual(dist[1], 3)   # 1-2, 2-3, 2-3
        self.assertEqual(dist[25], 1)  # 20-45
        self.assertEqual(sum(dist.values()), 15)

    def test_last_digit(self):
        digits = {x["digit"]: x["count"] for x in last_digit.compute(D)["digits"]}
        self.assertEqual(digits[0], 3)  # 10, 20, 40
        self.assertEqual(digits[5], 5)  # 45, 5, 15, 25, 35
        self.assertEqual(sum(digits.values()), 18)

    def test_repeats(self):
        r = repeats.compute(D)
        self.assertEqual(r["pairs"], 2)
        overlaps = {x["overlap"]: x["rounds"] for x in r["distribution"]}
        self.assertEqual(overlaps[2], 1)  # 1→2회: 2, 3
        self.assertEqual(overlaps[0], 1)  # 2→3회
        self.assertEqual(r["mean"], 1.0)

    def test_structure(self):
        r = structure.compute(D)
        self.assertEqual(r["kinds"], 3)
        self.assertEqual(sum(x["rounds"] for x in r["top"]), 3)

    def test_run_all_isolates_failures(self):
        out = analysis.run_all(D)
        self.assertEqual(len(out), 9)
        self.assertTrue(all("result" in a for a in out))
        broken = analysis.run_all([LottoDraw(1, None)])  # 일부러 망가진 입력
        self.assertEqual(len(broken), 9)
        self.assertTrue(any("error" in a for a in broken))


if __name__ == "__main__":
    unittest.main()
