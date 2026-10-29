# 목적: 과거 회차의 조합 구조(홀수 개수, 고구간 개수, 구간 배치)가 어떻게 분포하는지 집계한다.
# 사용처: analysis.run_all이 부른다.
# 근거: 요구된 분석 항목 9번. 다른 항목과 독립적으로 바꿀 수 있게 따로 둔다.

from __future__ import annotations

KEY = "structure"
TITLE = "조합 구조 분포"
SECTIONS = [(1, 10), (11, 20), (21, 30), (31, 40), (41, 45)]
TOP = 15
METHOD = (
    "회차마다 (홀수 개수, 23~45 번호 개수, 다섯 구간별 개수)를 하나의 구조로 묶어 같은 구조의 회차 수를 셉니다. "
    "예: 홀3·고3·구간[1,2,1,1,1]. 많이 나온 상위 15개 구조와 전체 구조 종류 수를 보여 줍니다."
)


# 목적: 구조별 회차 수를 세어 상위 목록을 만든다.
# 이유: 특정 구조가 유난히 자주 나오는지, 대부분 흩어져 있는지를 한눈에 보여 준다.
# 방법: 회차를 구조 문자열로 바꿔 세고, 많은 순으로 정렬한다.
def compute(draws) -> dict:
    counts: dict[str, int] = {}
    for d in draws:
        odd = sum(1 for n in d.numbers if n % 2)
        high = sum(1 for n in d.numbers if n >= 23)
        sec = [sum(1 for n in d.numbers if lo <= n <= hi) for lo, hi in SECTIONS]
        key = f"홀{odd}·고{high}·구간[{','.join(str(c) for c in sec)}]"
        counts[key] = counts.get(key, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return {
        "kinds": len(counts),
        "rounds": len(draws),
        "top": [{"structure": k, "rounds": v} for k, v in ranked[:TOP]],
        "single_occurrence": sum(1 for v in counts.values() if v == 1),
    }
