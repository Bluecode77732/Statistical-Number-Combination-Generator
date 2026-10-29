# 목적: 정렬된 당첨번호 사이의 간격을 집계한다.
# 사용처: analysis.run_all이 부른다.
# 근거: 요구된 분석 항목 6번. 다른 항목과 독립적으로 바꿀 수 있게 따로 둔다.

from __future__ import annotations

import statistics

KEY = "gaps"
TITLE = "번호 사이 간격"
METHOD = (
    "회차마다 정렬한 6개 번호의 이웃 간격 5개(예: 3, 8, 14 → 5, 6)를 모두 모아 분포를 내고, "
    "회차별 가장 큰 간격의 평균도 계산합니다."
)


# 목적: 간격 크기별 출현 수와 회차별 최대 간격 통계를 계산한다.
# 이유: 번호가 몰려 나오는지 흩어져 나오는지를 수치로 보여 준다.
# 방법: 모든 회차의 이웃 간격을 모아 크기별로 세고, 회차마다 최대 간격을 따로 모은다.
def compute(draws) -> dict:
    counts: dict[int, int] = {}
    max_gaps = []
    for d in draws:
        s = sorted(d.numbers)
        gaps = [b - a for a, b in zip(s, s[1:])]
        for g in gaps:
            counts[g] = counts.get(g, 0) + 1
        max_gaps.append(max(gaps))
    all_gaps = [g for g, c in counts.items() for _ in range(c)]
    return {
        "mean_gap": round(statistics.mean(all_gaps), 2) if all_gaps else 0.0,
        "mean_max_gap": round(statistics.mean(max_gaps), 2) if max_gaps else 0.0,
        "distribution": [{"gap": g, "count": counts[g]} for g in sorted(counts)],
    }
