# 목적: 번호 구간(1–10, 11–20, …)별로 당첨번호가 어떻게 나뉘는지 집계한다.
# 사용처: analysis.run_all이 부른다.
# 근거: 요구된 분석 항목 3번. 다른 항목과 독립적으로 바꿀 수 있게 따로 둔다.

from __future__ import annotations

KEY = "sections"
TITLE = "번호 구간별 분포"
SECTIONS = [(1, 10), (11, 20), (21, 30), (31, 40), (41, 45)]
METHOD = (
    "1–10, 11–20, 21–30, 31–40, 41–45 다섯 구간으로 나눠, 구간별 전체 출현 수와 회차당 평균 개수를 셉니다. "
    "기대 평균은 구간 크기 × 6 / 45입니다(41–45 구간은 5개라 기대값이 절반입니다)."
)


# 목적: 구간별 출현 수, 회차당 평균, 기대값, 회차별 개수 분포를 계산한다.
# 이유: 구간 크기가 달라 단순 출현 수만으로는 비교할 수 없어 기대값을 함께 둔다.
# 방법: 회차마다 구간별 개수를 세어 합계와 0~6개 분포를 쌓는다.
def compute(draws) -> dict:
    total = len(draws)
    rows = []
    for lo, hi in SECTIONS:
        per_round = [sum(1 for n in d.numbers if lo <= n <= hi) for d in draws]
        dist = [per_round.count(k) for k in range(7)]
        size = hi - lo + 1
        rows.append({"section": f"{lo}–{hi}", "total": sum(per_round),
                     "mean_per_round": round(sum(per_round) / total, 3) if total else 0.0,
                     "expected_per_round": round(size * 6 / 45, 3),
                     "distribution": dist})
    return {"rows": rows}
