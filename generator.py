"""
독립적인 랜덤 번호 생성기 (Independent Random Number Generator)

** 격리 원칙 (Isolation Principle) **
이 모듈은 분석 모듈(analyzer.py)이나 Excel 로더(excel_loader.py)를 절대
import하지 않는다. 이 모듈이 아는 것은 오직 "1부터 45까지의 정수" 뿐이며,
과거 당첨 번호, 출현 빈도, 분석 결과, 백테스트 결과, 점수, 가중치, 패턴 등
그 어떤 외부 데이터에도 접근하지 않는다.

이 파일이 사용하는 것은 표준 라이브러리 random 모듈 하나뿐이다.
"""

import random

LOTTO_MIN = 1
LOTTO_MAX = 45
PICK_COUNT = 6

# 분석 모듈과 완전히 독립된 난수 생성기 인스턴스.
# random.SystemRandom은 OS가 제공하는 난수 소스를 사용하며,
# 프로그램 내 다른 어떤 상태(과거 데이터, 분석 결과 등)와도 무관하다.
_rng = random.SystemRandom()


def generate_numbers() -> list[int]:
    """
    1~45 범위에서 중복 없이 정확히 6개의 번호를 무작위로 선택하여
    오름차순으로 정렬해 반환한다.

    - 외부 인자를 받지 않는다 (분석 결과를 전달할 방법 자체가 없다).
    - 호출할 때마다 정확히 하나의 조합만 생성한다.
    - 점수, 가중치, 순위 계산이 전혀 없다.
    """
    numbers = _rng.sample(range(LOTTO_MIN, LOTTO_MAX + 1), PICK_COUNT)
    numbers.sort()
    return numbers
