# 목적: 직전 회차와 이번 회차 당첨번호가 몇 개 겹치는지 집계한다.
# 사용처: analysis.run_all이 부른다.
# 근거: 요구된 분석 항목 8번. 다른 항목과 독립적으로 바꿀 수 있게 따로 둔다.

from __future__ import annotations

KEY = "repeats"
TITLE = "이전 회차와의 중복"
METHOD = (
    "2회차부터, 직전 회차 당첨번호 6개 중 이번 회차에 다시 나온 개수(0~6)를 세어 집계합니다. "
    "무작위 추첨의 이론 평균은 6 × 6 / 45 = 0.8개입니다."
)


# 목적: 겹친 개수별 회차 수와 평균을 계산한다.
# 이유: "직전 번호가 또 나온다"는 인상을 이론값과 비교해 확인할 수 있게 한다.
# 방법: 회차순으로 이웃한 두 회차의 교집합 크기를 센다.
def compute(draws) -> dict:
    ordered = sorted(draws, key=lambda d: d.round_no)
    dist = [0] * 7
    overlaps = []
    for prev, cur in zip(ordered, ordered[1:]):
        k = len(set(prev.numbers) & set(cur.numbers))
        dist[k] += 1
        overlaps.append(k)
    return {
        "pairs": len(overlaps),
        "mean": round(sum(overlaps) / len(overlaps), 3) if overlaps else 0.0,
        "theory_mean": 0.8,
        "distribution": [{"overlap": k, "rounds": dist[k]} for k in range(7)],
    }
