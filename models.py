# 목적: 후보 숫자를 고르는 모델 두 가지(무작위 기준선, 로지스틱 회귀)와 그 입력 특징값을 만든다.
# 사용처: backtest.py가 회차마다, pipeline.py가 최종 후보를 낼 때 부른다.
# 근거: 백테스트와 최종 후보가 같은 특징값·같은 모델 코드를 써야 "선정 방식이 구현과 일치"한다는 요구를 지킬 수 있다.

from __future__ import annotations

import random
from dataclasses import dataclass

import numpy as np

from excel_loader import LottoDraw

NUMBERS = 45
PICK = 10
# 번호 재산출 규칙(2026-11-20 사용자 결정): 점수 상위 5 + 최근 5회 당첨번호 2 + 최근 50회 최다 출현 1 + 최소 출현 2
MIX_TOP = 5
RECENT_ROUNDS = 5
RECENT_PICK = 2
FREQ_ROUNDS = 50
HOT_PICK = 1
COLD_PICK = 2
MIX_LABELS = {
    "model": "모델 점수 상위",
    "recent": f"최근 {RECENT_ROUNDS}회 당첨번호",
    "hot": f"최근 {FREQ_ROUNDS}회 최다 출현 쪽",
    "cold": f"최근 {FREQ_ROUNDS}회 최소 출현 쪽",
    "fill": "보충(앞 묶음이 모자란 자리)",
}
WINDOWS = (5, 10, 30, 100)
FEATURE_NAMES = [
    "직전 5회 출현 비율",
    "직전 10회 출현 비율",
    "직전 30회 출현 비율",
    "직전 100회 출현 비율",
    "전체 누적 출현 비율",
    "마지막 출현 후 경과 회차(로그)",
    "직전 회차 출현 여부",
]


class ModelError(Exception):
    """학습이나 점수 계산이 수치적으로 실패했을 때 발생."""


# 목적: 모델 단계에서 난 오류를 화면에 보일 한국어 문장으로 바꾼다.
# 이유: ModelError가 아닌 오류에서도 무작위 대체와 그 이유를 보여야 한다(핵심 규칙 10, 감사 A-01).
#       시스템 오류문(영문)을 그대로 싣지 않는다(감사 A-16).
# 방법: ModelError면 그 문장을 쓰고, 그 밖의 오류는 종류 이름만 밝힌다.
def describe_model_error(exc: Exception) -> str:
    if isinstance(exc, ModelError):
        return str(exc)
    return f"예상하지 못한 계산 오류가 났습니다({type(exc).__name__})."


# 목적: 회차별·번호별 특징값과 정답을 한 번에 만든다.
# 이유: 백테스트는 회차마다 학습하므로 특징값을 매번 새로 세면 느리고, 계산 방식이 달라질 위험도 있다.
# 방법: X[i]는 draws[:i]만으로 만든 "i번째 회차(0부터) 예측용" 특징값이다. i = len(draws)는 다음 회차용이다.
#       누적 출현 수로 구간 비율을 구하고, 마지막 출현 위치를 순서대로 갱신한다. 미래 회차는 쓰지 않는다.
def build_features(draws: list[LottoDraw]) -> tuple[np.ndarray, np.ndarray]:
    n = len(draws)
    hits = np.zeros((n, NUMBERS), dtype=np.float64)
    for i, d in enumerate(draws):
        hits[i, [k - 1 for k in d.numbers]] = 1.0

    cum = np.zeros((n + 1, NUMBERS))
    cum[1:] = np.cumsum(hits, axis=0)

    X = np.zeros((n + 1, NUMBERS, len(FEATURE_NAMES)))
    last_seen = np.full(NUMBERS, -1)  # 마지막으로 나온 회차의 인덱스
    for i in range(1, n + 1):
        last_seen[hits[i - 1] == 1] = i - 1
        for j, w in enumerate(WINDOWS):
            lo = max(0, i - w)
            X[i, :, j] = (cum[i] - cum[lo]) / (i - lo)
        X[i, :, 4] = cum[i] / i
        gap = np.where(last_seen >= 0, i - last_seen, i + 1)
        X[i, :, 5] = np.log1p(gap)
        X[i, :, 6] = hits[i - 1]
    return X, hits


# 목적: 고를 수 있는 번호(0부터 센 위치)를 값 순서로 줄 세운다. 값이 같으면 무작위 순서로 둔다.
# 이유: 점수 상위, 최다 출현, 최소 출현을 모두 같은 규칙으로 고르기 위해서다. 값이 같을 때 번호가 작은 쪽이
#       항상 앞서면 그 자체가 근거 없는 편향이 된다.
# 방법: 값(내림차순이면 부호를 뒤집음)을 우선, 무작위 값을 다음 기준으로 lexsort한다. 난수는 대상 수만큼 쓴다.
def _ranked(values: np.ndarray, eligible, rng: np.random.Generator, descending: bool) -> list[int]:
    idx = np.array(sorted(eligible), dtype=int)
    key = -values[idx] if descending else values[idx]
    return [int(i) for i in idx[np.lexsort((rng.random(len(idx)), key))]]


# 목적: 점수 배열에서 상위 10개 번호를 골라 오름차순으로 돌려준다.
# 이유: 첫 화면 후보는 로지스틱 회귀 점수 상위 10개로 낸다(2026-11-20 사용자 결정, 2026-11-09 동점 처리 이전 방식 복원).
#       점수가 정확히 같은 번호는 실제 데이터에서 나오지 않지만, 나오면 번호순이 아니라 무작위로 가른다.
# 방법: 점수 내림차순으로 줄 세운 뒤(_ranked) 앞 10개를 정렬한다.
def top_candidates(scores: np.ndarray, rng: np.random.Generator, k: int = PICK) -> list[int]:
    return sorted(i + 1 for i in _ranked(scores, range(NUMBERS), rng, descending=True)[:k])


# 목적: 번호 재산출 규칙으로 후보 10개를 고르고, 묶음별로 무엇을 골랐는지 함께 돌려준다.
# 이유: 사용자가 정한 재산출 규칙(2026-11-20)이다. 첫 화면(점수 상위 10개)과 다른 한 세트를 보여 주되,
#       각 자리가 어떤 기준으로 들어왔는지 화면에 밝혀야 한다(핵심 규칙 7). 빈도는 이 10개 중 3자리에만 쓴다(규칙 6).
# 방법: hits_before는 예측할 회차 이전 회차들의 (회차, 45) 출현 행렬이라, 그 밖의 데이터는 쓰지 않는다(규칙 9).
#       고르는 순서는 a → b → c이고 앞에서 고른 번호는 뒤에서 빼서 겹치지 않는다.
#       a. 모델 점수 상위 5개(top_candidates와 같은 점수·같은 줄 세우기).
#       b. 최근 5회 당첨번호(보너스 제외)에 나온 번호 중 a에 없는 것에서 무작위 2개.
#       c. 최근 50회 출현 횟수로 남은 번호를 줄 세워, 많은 쪽 앞에서 1개, 그다음 적은 쪽 앞에서 2개.
#          "쪽"은 출현 횟수가 가장 많은(적은) 번호들이다. 같은 횟수끼리는 무작위 순서라, 그 횟수의 번호가 고를 수보다
#          많으면 그중 무작위로, 모자라면 모두 넣고 다음 횟수의 번호에서 무작위로 채운다.
#       b의 대상이 2개보다 적으면(실제 데이터에서는 일어나지 않음) 모자란 자리는 마지막에 남은 번호에서 무작위로 채운다.
def mixed_candidates(scores: np.ndarray, hits_before: np.ndarray, rng: np.random.Generator) -> dict:
    if len(hits_before) < FREQ_ROUNDS:
        raise ModelError(f"최근 {FREQ_ROUNDS}회 데이터가 없어 재산출 규칙을 쓸 수 없습니다.")
    chosen: list[int] = []
    groups: list[dict] = []

    # 목적: 한 묶음의 번호를 결과에 더한다.
    # 이유: 다섯 묶음이 같은 모양으로 담겨야 화면이 한 방식으로 그릴 수 있다.
    # 방법: 번호(0부터)를 1부터로 바꿔 오름차순으로 담고, 고른 목록에도 더한다.
    def add(key: str, picked: list[int], **extra) -> None:
        chosen.extend(picked)
        groups.append({"key": key, "label": MIX_LABELS[key], "numbers": sorted(i + 1 for i in picked), **extra})

    add("model", _ranked(scores, range(NUMBERS), rng, descending=True)[:MIX_TOP])

    recent = np.flatnonzero(hits_before[-RECENT_ROUNDS:].sum(axis=0) > 0)
    pool = [int(i) for i in recent if i not in chosen]
    take = min(RECENT_PICK, len(pool))
    add("recent", [int(i) for i in rng.choice(pool, take, replace=False)] if take else [], pool=len(pool))

    counts = hits_before[-FREQ_ROUNDS:].sum(axis=0)

    # 목적: 최근 50회 출현 횟수로 많은(적은) 쪽에서 k개를 고르고, 번호마다 횟수와 같은 횟수의 번호 수를 남긴다.
    # 이유: 화면이 "몇 번 나왔고, 같은 횟수 몇 개 중에서 무작위로 골랐는지"를 밝히게 하기 위해서다.
    # 방법: 아직 고르지 않은 번호를 _ranked로 줄 세워 앞 k개를 고른다. tied는 고르기 직전 남은 번호 중 같은 횟수의 수다.
    def by_count(key: str, k: int, descending: bool) -> None:
        eligible = [i for i in range(NUMBERS) if i not in chosen]
        picked = _ranked(counts, eligible, rng, descending)[:k]
        picks = [{"number": i + 1, "count": int(counts[i]),
                  "tied": sum(1 for j in eligible if counts[j] == counts[i])} for i in sorted(picked)]
        add(key, picked, picks=picks)

    by_count("hot", HOT_PICK, descending=True)
    by_count("cold", COLD_PICK, descending=False)

    if len(chosen) < PICK:
        rest = [i for i in range(NUMBERS) if i not in chosen]
        add("fill", [int(i) for i in rng.choice(rest, PICK - len(chosen), replace=False)])
    return {"numbers": sorted(i + 1 for i in chosen), "groups": groups}


# 목적: 무작위 기준선 후보 10개를 만든다.
# 이유: 모델 성능을 판단할 비교 대상이자, 모델이 실패했을 때의 대체 수단이다.
# 방법: 1~45에서 중복 없이 균등하게 10개를 뽑는다.
def random_candidates(rng: random.Random, k: int = PICK) -> list[int]:
    return sorted(rng.sample(range(1, NUMBERS + 1), k))


@dataclass
class LogisticModel:
    lam: float = 1.0          # L2 정규화 세기 (표준화된 특징 기준, 절편 제외)
    max_iter: int = 25
    tol: float = 1e-7

    def __post_init__(self) -> None:
        self.mu = None
        self.sd = None
        self.w = None

    # 목적: 특징값과 정답으로 로지스틱 회귀를 학습한다.
    # 이유: 각 번호가 다음 회차에 들어갈지를 특징값으로 설명하는 가장 단순하고 해석 가능한 모델이다.
    #       2026-11-20에 점수 상위 10개 선택으로 돌아가 동점 판단용 공분산 계산을 뺐다.
    # 방법: 학습 데이터의 평균·표준편차로만 표준화하고, L2 정규화를 건 뉴턴법으로 푼다.
    #       init(직전 가중치)을 주면 거기서 시작해 백테스트의 반복 학습을 빠르게 한다.
    #       뉴턴 단계의 방정식을 풀지 못하면 ModelError로 바꿔 무작위 대체로 이어지게 한다(감사 A-01).
    def fit(self, X: np.ndarray, y: np.ndarray, init: np.ndarray | None = None) -> "LogisticModel":
        if len(X) == 0 or y.min() == y.max():
            raise ModelError("학습할 데이터가 부족합니다.")
        self.mu = X.mean(axis=0)
        sd = X.std(axis=0)
        self.sd = np.where(sd > 0, sd, 1.0)
        A = np.hstack([np.ones((len(X), 1)), (X - self.mu) / self.sd])
        reg = np.full(A.shape[1], self.lam)
        reg[0] = 0.0
        w = np.zeros(A.shape[1]) if init is None else init.copy()
        for _ in range(self.max_iter):
            p = 1.0 / (1.0 + np.exp(-np.clip(A @ w, -30, 30)))
            grad = A.T @ (p - y) + reg * w
            hess = (A * (p * (1 - p))[:, None]).T @ A + np.diag(reg)
            try:
                step = np.linalg.solve(hess, grad)
            except np.linalg.LinAlgError as exc:
                raise ModelError("학습 중 방정식을 풀지 못했습니다.") from exc
            w = w - step
            if np.max(np.abs(step)) < self.tol:
                break
        if not np.all(np.isfinite(w)):
            raise ModelError("학습 결과가 수치적으로 발산했습니다.")
        self.w = w
        return self

    # 목적: 번호 45개의 모델 점수(0~1)를 계산한다.
    # 이유: 첫 화면 상위 10개와 재산출 규칙 a(상위 5개)의 기준이며 API에도 내보낸다. 실제 당첨 확률이 아니며,
    #       각 번호의 실제 확률은 모델과 무관하게 6/45다.
    # 방법: 학습 때의 표준화를 그대로 적용한 뒤 시그모이드를 씌운다.
    def scores(self, X: np.ndarray) -> np.ndarray:
        if self.w is None:
            raise ModelError("학습되지 않은 모델입니다.")
        A = np.hstack([np.ones((len(X), 1)), (X - self.mu) / self.sd])
        s = 1.0 / (1.0 + np.exp(-np.clip(A @ self.w, -30, 30)))
        if not np.all(np.isfinite(s)):
            raise ModelError("점수 계산 결과가 올바르지 않습니다.")
        return s

    # 목적: 학습된 가중치를 특징 이름과 함께 돌려준다.
    # 이유: 점수의 근거를 사용자가 직접 확인할 수 있어야 한다.
    # 방법: 표준화된 특징 기준 가중치라, 크기를 서로 비교할 수 있다. 양수면 그 특징이 클수록 점수가 오른다.
    def weights(self) -> list[dict]:
        if self.w is None:
            return []
        rows = [{"feature": "절편", "weight": round(float(self.w[0]), 4)}]
        rows += [{"feature": name, "weight": round(float(v), 4)} for name, v in zip(FEATURE_NAMES, self.w[1:])]
        return rows


# 목적: draws 전체로 학습할 때 쓰는 학습 행렬을 만든다.
# 이유: 백테스트와 최종 학습이 같은 범위 규칙(첫 회차 제외, end 직전까지)을 쓰게 한다.
# 방법: 1 ~ end−1번째 회차의 특징값과 정답을 (회차×45, 특징) 모양으로 편다. 0번째는 이전 기록이 없어 뺀다.
def training_rows(X: np.ndarray, hits: np.ndarray, end: int) -> tuple[np.ndarray, np.ndarray]:
    if end <= 1:
        return np.zeros((0, X.shape[2])), np.zeros(0)
    return X[1:end].reshape(-1, X.shape[2]), hits[1:end].reshape(-1)
