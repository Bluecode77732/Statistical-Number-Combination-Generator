# 목적: 테스트에서 쓸 가짜 당첨 데이터와, 공식 사이트처럼 응답하는 가짜 서버를 만든다.
# 사용처: tests 폴더의 테스트 파일들이 import한다.
# 근거: 테스트가 실제 공식 사이트에 접속하면 결과가 날마다 달라지고, 네트워크 오류 같은 상황을 재현할 수 없다.

from __future__ import annotations

import json
import random
import urllib.error
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

from excel_loader import LottoDraw


def make_draws(n: int, seed: int = 1) -> list[LottoDraw]:
    rng = random.Random(seed)
    out = []
    start = date(2002, 12, 7)
    for r in range(1, n + 1):
        picked = rng.sample(range(1, 46), 7)
        out.append(LottoDraw(round_no=r, numbers=sorted(picked[:6]), bonus=picked[6],
                             draw_date=(start + timedelta(weeks=r - 1)).isoformat()))
    return out


def to_item(d: LottoDraw) -> dict:
    item = {"ltEpsd": d.round_no, "bnsWnNo": d.bonus, "ltRflYmd": d.draw_date.replace("-", "")}
    for i, n in enumerate(d.numbers, start=1):
        item[f"tm{i}WnNo"] = n
    return item


class FakeServer:
    """공식 조회 주소의 center/latest 동작(실측)을 흉내 낸다."""

    def __init__(self, draws: list[LottoDraw]):
        self.draws = {d.round_no: d for d in draws}
        self.calls: list[str] = []
        self.fail_times = 0      # 앞에서부터 이 횟수만큼 네트워크 오류
        self.body_override = None  # 응답 본문을 통째로 바꿔 형식 오류를 흉내 낸다
        self.bad_rounds: dict[int, dict] = {}  # 특정 회차 응답을 망가뜨린다

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise urllib.error.URLError("fake network down")
        if self.body_override is not None:
            return self.body_override
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        rounds = sorted(self.draws)
        if q.get("srchDir") == "center" and "srchLtEpsd" in q:
            c = int(q["srchLtEpsd"])
            picked = [r for r in rounds if abs(r - c) <= 9][:10] if c in self.draws else []
            if c == 1:
                picked = [r for r in rounds if r <= 10]
        elif q.get("srchDir") == "latest" and "srchCursorLtEpsd" in q:
            cur = int(q["srchCursorLtEpsd"])
            picked = [r for r in rounds if r > cur][:10] if cur > 0 else []
        else:
            picked = []
        items = []
        for r in sorted(picked, reverse=True):
            item = to_item(self.draws[r])
            item.update(self.bad_rounds.get(r, {}))
            items.append(item)
        return json.dumps({"resultCode": None, "resultMessage": None, "data": {"list": items}}).encode("utf-8")


def no_sleep(_seconds: float) -> None:
    pass
