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
TIE_Z = 1.96  # 두 번호의 점수 차이가 표준오차의 이 배수 이하면 동점으로 본다 (95% 기준, 백테스트 판정과 같은 값)
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


# 목적: 번호 45개의 점수(로짓)와 그 공분산으로 후보 10개를 고르고, 몇 개가 점수로 정해졌는지 함께 돌려준다.
# 이유: 가중치가 0에 가까워 번호 간 점수 차이가 오차보다 훨씬 작은데도 순위로만 자르면, 그 작은 차이 때문에
#       직전 회차 번호가 매번 4~6개 들어갔다(2026-11-09 측정). 오차 안의 차이는 순위의 근거로 쓰지 않는다.
# 방법: 점수 순위(같은 점수는 무작위로 가름)를 매긴 뒤, 상위 10개 중 11위보다 z × SE(차이) 넘게 높은 번호는 "확정",
#       11위 아래 중 10위보다 z × SE 넘게 낮은 번호는 "제외"로 둔다. 남은 자리는 나머지(동점 묶음)에서 균등 무작위로
#       채운다. 차이의 분산은 cov[i,i] + cov[j,j] − 2·cov[i,j]. z = 0이면 점수 상위 10개와 같다.
def select_candidates(logits: np.ndarray, cov: np.ndarray, rng: np.random.Generator,
                      z: float = TIE_Z, k: int = PICK) -> dict:
    order = np.lexsort((rng.random(NUMBERS), -logits))
    i_last, i_next = order[k - 1], order[k]
    var = np.diag(cov)

    # 목적: 번호 i의 점수가 번호 j보다 오차를 넘게 높은지 판단한다.
    # 이유: 확정·제외를 가르는 단 하나의 기준이라 한곳에 둔다.
    # 방법: 로짓 차이를 그 차이의 표준편차 × z와 비교한다. 같으면 높지 않은 것으로 본다.
    def clearly_above(i: int, j: int) -> bool:
        sd = np.sqrt(max(var[i] + var[j] - 2 * cov[i, j], 0.0))
        return logits[i] - logits[j] > z * sd

    firm = [int(i) for i in order[:k] if clearly_above(i, i_next)]
    out = {int(i) for i in order[k:] if clearly_above(i_last, i)}
    pool = [i for i in range(NUMBERS) if i not in firm and i not in out]
    fill = [int(i) for i in rng.choice(pool, k - len(firm), replace=False)]
    return {"numbers": sorted(i + 1 for i in firm + fill),
            "firm": sorted(i + 1 for i in firm), "tie_pool": len(pool)}


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
        self.cov = None

    # 목적: 특징값과 정답으로 로지스틱 회귀를 학습하고, 가중치의 공분산도 구해 둔다.
    # 이유: 각 번호가 다음 회차에 들어갈지를 특징값으로 설명하는 가장 단순하고 해석 가능한 모델이다.
    #       공분산은 번호 간 점수 차이가 오차보다 큰지 판단하는 데 쓴다(select_candidates).
    # 방법: 학습 데이터의 평균·표준편차로만 표준화하고, L2 정규화를 건 뉴턴법으로 푼다.
    #       init(직전 가중치)을 주면 거기서 시작해 백테스트의 반복 학습을 빠르게 한다.
    #       뉴턴 단계의 방정식을 풀지 못하면 ModelError로 바꿔 무작위 대체로 이어지게 한다(감사 A-01).
    #       공분산은 최종 가중치에서 다시 계산한 헤시안(정규화 포함)의 역행렬이다. 부트스트랩과 비교해 거의 같았다.
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
        p = 1.0 / (1.0 + np.exp(-np.clip(A @ w, -30, 30)))
        hess = (A * (p * (1 - p))[:, None]).T @ A + np.diag(reg)
        try:
            cov = np.linalg.inv(hess)
        except np.linalg.LinAlgError as exc:
            raise ModelError("가중치의 오차를 계산하지 못했습니다.") from exc
        if not np.all(np.isfinite(cov)):
            raise ModelError("가중치의 오차 계산 결과가 올바르지 않습니다.")
        self.w = w
        self.cov = cov
        return self

    # 목적: 번호들의 점수(로짓)와 그 공분산 행렬을 돌려준다.
    # 이유: 후보 선택이 점수 순위뿐 아니라 점수 차이의 오차까지 보게 하기 위해서다.
    # 방법: 학습 때의 표준화를 적용한 설계행렬 A로 로짓 A·w, 공분산 A·cov·Aᵀ를 계산한다.
    def logits_with_cov(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if self.w is None:
            raise ModelError("학습되지 않은 모델입니다.")
        A = np.hstack([np.ones((len(X), 1)), (X - self.mu) / self.sd])
        logits = A @ self.w
        cov = A @ self.cov @ A.T
        if not (np.all(np.isfinite(logits)) and np.all(np.isfinite(cov))):
            raise ModelError("점수 계산 결과가 올바르지 않습니다.")
        return logits, cov

    # 목적: 번호 45개의 모델 점수(0~1)를 계산한다.
    # 이유: API에 내보내는 점수다. 실제 당첨 확률이 아니며, 각 번호의 실제 확률은 모델과 무관하게 6/45다.
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
