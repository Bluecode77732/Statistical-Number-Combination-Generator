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


# 목적: 점수 배열에서 상위 10개 번호를 골라 오름차순으로 돌려준다.
# 이유: 점수가 같은 번호가 있을 때 번호가 작은 쪽이 항상 이기면 그 자체가 근거 없는 편향이 된다.
# 방법: 점수 내림차순을 우선으로, 동점은 무작위 값으로 가른 뒤 앞 10개를 정렬한다.
def top_candidates(scores: np.ndarray, rng: np.random.Generator, k: int = PICK) -> list[int]:
    order = np.lexsort((rng.random(NUMBERS), -scores))
    return sorted(int(i) + 1 for i in order[:k])


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
    # 방법: 학습 데이터의 평균·표준편차로만 표준화하고, L2 정규화를 건 뉴턴법으로 푼다.
    #       init(직전 가중치)을 주면 거기서 시작해 백테스트의 반복 학습을 빠르게 한다.
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
            step = np.linalg.solve(hess, grad)
            w = w - step
            if np.max(np.abs(step)) < self.tol:
                break
        if not np.all(np.isfinite(w)):
            raise ModelError("학습 결과가 수치적으로 발산했습니다.")
        self.w = w
        return self

    # 목적: 번호 45개의 모델 점수(0~1)를 계산한다.
    # 이유: 상위 10개 선택의 기준이다. 실제 당첨 확률이 아니며, 각 번호의 실제 확률은 모델과 무관하게 6/45다.
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
