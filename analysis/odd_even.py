# 목적: 회차별 홀수·짝수 구성을 집계한다.
# 사용처: analysis.run_all이 부른다.
# 근거: 요구된 분석 항목 2번. 다른 항목과 독립적으로 바꿀 수 있게 따로 둔다.

from __future__ import annotations

from math import comb

KEY = "odd_even"
TITLE = "홀수·짝수 구성"
METHOD = (
    "회차마다 당첨번호 6개 중 홀수 개수(0~6)를 세어 회차 수를 집계합니다. "
    "이론 비율은 1~45 중 홀수 23개·짝수 22개에서 6개를 뽑을 때의 확률 C(23,k)·C(22,6−k)/C(45,6)입니다."
)


# 목적: 홀수 개수별 회차 수와 이론 비율을 계산한다.
# 이유: 실제 분포가 무작위 추첨에서 기대되는 분포와 얼마나 비슷한지 비교할 수 있어야 한다.
# 방법: 회차별 홀수 개수를 세고, 초기하분포로 이론 비율을 구해 나란히 둔다.
def compute(draws) -> dict:
    counts = [0] * 7
    for d in draws:
        counts[sum(1 for n in d.numbers if n % 2)] += 1
    total = len(draws)
    rows = []
    for k in range(7):
        theory = comb(23, k) * comb(22, 6 - k) / comb(45, 6)
        rows.append({"odd": k, "even": 6 - k, "rounds": counts[k],
                     "ratio": round(counts[k] / total * 100, 1) if total else 0.0,
                     "theory_ratio": round(theory * 100, 1)})
    return {"rows": rows}
