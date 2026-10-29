# 목적: 회차별 당첨번호 6개 합계의 분포를 집계한다.
# 사용처: analysis.run_all이 부른다.
# 근거: 요구된 분석 항목 5번. 다른 항목과 독립적으로 바꿀 수 있게 따로 둔다.

from __future__ import annotations

import statistics

KEY = "sums"
TITLE = "당첨번호 합계 분포"
BIN = 20
METHOD = (
    "회차마다 당첨번호 6개를 더한 값의 최소·최대·평균·중앙값과 20 단위 구간 분포를 계산합니다. "
    "무작위 추첨의 이론 평균은 6 × 23 = 138, 이론 표준편차는 √(6 × 168.67 × 39/44) ≈ 29.95입니다."
)


# 목적: 합계 통계와 구간 분포를 계산한다.
# 이유: 실제 합계가 무작위 추첨의 이론값 근처인지 비교할 기준을 함께 보여 준다.
# 방법: 합계 목록에서 요약 통계를 내고, 20 단위로 묶어 회차 수를 센다.
def compute(draws) -> dict:
    sums = [sum(d.numbers) for d in draws]
    if not sums:
        return {"rounds": 0}
    bins: dict[int, int] = {}
    for s in sums:
        start = (s // BIN) * BIN
        bins[start] = bins.get(start, 0) + 1
    return {
        "rounds": len(sums),
        "min": min(sums), "max": max(sums),
        "mean": round(statistics.mean(sums), 2), "median": statistics.median(sums),
        "stdev": round(statistics.pstdev(sums), 2),
        "theory_mean": 138, "theory_stdev": 29.95,
        "bins": [{"range": f"{b}–{b + BIN - 1}", "rounds": bins[b]} for b in sorted(bins)],
    }
