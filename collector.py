# 목적: 동행복권 공식 사이트에서 로또 6/45 당첨 결과를 받아 검증된 회차 목록으로 돌려준다.
# 사용처: data_sync.py가 시작할 때 빠진 회차를 받으려고 호출한다. 테스트는 http_get을 가짜로 바꿔 끼운다.
# 근거: 예전 공식 조회 주소가 사이트 개편으로 막혀, 개편된 당첨결과 페이지가 쓰는 주소를 따로 다룰 곳이 필요했다.

from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from excel_loader import MAX_NUM, MIN_NUM, NUMBER_COUNT, LottoDraw

BASE_URL = "https://www.dhlottery.co.kr/lt645/selectPstLt645InfoNew.do"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) LottoAnalyzer",
    "Accept": "application/json",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.dhlottery.co.kr/lt645/result",
}
TIMEOUT_SECONDS = 20
RETRIES = 2              # 첫 시도 뒤 추가 시도 횟수
RETRY_WAIT_SECONDS = 2.0
REQUEST_INTERVAL_SECONDS = 0.4  # 공식 사이트에 부담을 주지 않도록 요청 사이에 둔다
MAX_PAGES = 500          # 응답이 끝나지 않는 이상 상황을 막는 상한 (현재 약 125쪽)

HttpGet = Callable[[str], bytes]


class CollectError(Exception):
    """네트워크 실패 또는 공식 사이트 응답 형식이 예상과 다를 때 발생."""

    def __init__(self, message: str, kind: str):
        super().__init__(message)
        self.kind = kind  # "network" | "format"


@dataclass
class FetchResult:
    draws: list[LottoDraw]
    rejected: list[dict]  # 받았지만 검증에 실패해 버린 회차 {"round": n, "reason": "..."}
    latest_seen: int = 0  # 응답에서 본 가장 큰 회차(불량 회차 포함). 응답이 비면 0


# 목적: 응답 항목에서 회차 번호만 꺼낸다.
# 이유: 검증에 실패한 회차도 번호가 읽히면 커서를 넘기고 공식 최신 회차를 아는 데 써야 한다(감사 A-06).
# 방법: ltEpsd가 1 이상의 정수로 읽히면 그 값을, 아니면 None을 돌려준다.
def _round_of(item) -> Optional[int]:
    try:
        n = int(item["ltEpsd"])
    except (KeyError, TypeError, ValueError):
        return None
    return n if n >= 1 else None


# 목적: 주어진 주소를 GET으로 요청해 응답 본문을 돌려준다.
# 이유: 실제 네트워크 호출을 한 곳에 모아 두어야 테스트에서 가짜로 바꿔 끼울 수 있다.
# 방법: 표준 라이브러리 urllib로 요청한다. 실패는 호출한 쪽이 재시도한다.
def default_http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as res:
        return res.read()


# 목적: 통신 실패의 원인에 맞는 안내 문구를 고른다.
# 이유: 사이트가 요청을 거절(403 등)했는데도 "인터넷 연결 확인"만 안내하면 사용자가 엉뚱한 곳을 점검한다(감사 A-13).
# 방법: HTTP 오류 번호가 있으면 번호를 밝히고 잠시 뒤 재실행을 권하며, 그 밖의 실패는 연결 확인을 안내한다.
def _network_message(exc: Optional[Exception]) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return (f"공식 사이트가 요청을 받아 주지 않았습니다(HTTP {exc.code}). "
                "잠시 뒤 다시 실행해 보세요. 계속되면 사이트가 바뀌었거나 접속이 제한되었을 수 있습니다.")
    return "공식 사이트에 연결하지 못했습니다. 인터넷 연결을 확인해 주세요."


# 목적: 응답 한 쪽(최대 10회차)을 받아 원본 목록으로 돌려준다.
# 이유: 일시적인 끊김은 다시 시도하면 되지만, 형식이 바뀐 응답은 다시 시도해도 소용없어 구분해야 한다.
# 방법: 네트워크 오류(응답 도중 끊김 포함)만 간격을 두고 재시도하고, JSON이 아니거나 data.list가 없으면 바로 형식 오류로 멈춘다.
#       화면에 보이는 메시지에는 영문 시스템 오류문을 싣지 않고, 원인에 맞는 다음 할 일을 적는다.
def _get_page(http_get: HttpGet, query: str, sleep: Callable[[float], None]) -> list[dict]:
    url = f"{BASE_URL}?{query}"
    last_error: Optional[Exception] = None
    for attempt in range(RETRIES + 1):
        try:
            body = http_get(url)
            break
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
            last_error = exc
            if attempt < RETRIES:
                sleep(RETRY_WAIT_SECONDS * (attempt + 1))
    else:
        raise CollectError(_network_message(last_error), "network") from last_error

    try:
        payload = json.loads(body.decode("utf-8"))
        items = payload["data"]["list"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise CollectError(
            "공식 사이트 응답 형식이 예상과 다릅니다. 사이트가 바뀌었을 수 있습니다.", "format"
        ) from exc
    if not isinstance(items, list):
        raise CollectError("공식 사이트 응답 형식이 예상과 다릅니다. 사이트가 바뀌었을 수 있습니다.", "format")
    return items


# 목적: 응답의 회차 하나를 검증해 LottoDraw로 바꾼다.
# 이유: 받은 값이 잘못됐을 때 그대로 저장하면 엑셀이 오염된다.
# 방법: 필드가 정수인지, 번호 6개가 1~45에서 서로 다른지, 보너스가 범위 안이고 겹치지 않는지,
#       추첨일이 8자리이면서 달력에 있는 날짜인지 본다.
def parse_item(item: dict) -> LottoDraw:
    try:
        round_no = int(item["ltEpsd"])
        numbers = [int(item[f"tm{i}WnNo"]) for i in range(1, NUMBER_COUNT + 1)]
        bonus = int(item["bnsWnNo"])
        ymd = str(item["ltRflYmd"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("필수 항목이 없거나 숫자가 아닙니다.") from exc

    if round_no < 1:
        raise ValueError("회차 번호가 올바르지 않습니다.")
    if any(not MIN_NUM <= n <= MAX_NUM for n in numbers) or len(set(numbers)) != NUMBER_COUNT:
        raise ValueError("당첨 번호가 범위를 벗어나거나 중복됩니다.")
    if not MIN_NUM <= bonus <= MAX_NUM or bonus in numbers:
        raise ValueError("보너스 번호가 올바르지 않습니다.")
    if len(ymd) != 8 or not ymd.isdigit():
        raise ValueError("추첨일 형식이 올바르지 않습니다.")
    try:
        datetime.strptime(ymd, "%Y%m%d")
    except ValueError as exc:
        raise ValueError("추첨일이 달력에 없는 날짜입니다.") from exc

    return LottoDraw(
        round_no=round_no,
        numbers=sorted(numbers),
        bonus=bonus,
        draw_date=f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}",
    )


# 목적: after_round 다음 회차부터 공식 사이트에 있는 마지막 회차까지 받는다.
# 이유: 실행할 때마다 빠진 회차만 받으려면, 이미 가진 마지막 회차 이후를 순서대로 가져와야 한다.
# 방법: latest 커서로 10개씩 앞으로 넘기다 빈 응답에서 멈춘다. 커서 0은 빈 응답이라 처음엔 center로 1~10회를 받는다.
#       응답에 실제로 있는 회차만 돌려주며, 확인되지 않은 회차를 만들어 넣지 않는다.
#       검증에 실패한 회차도 번호가 읽히면 커서를 그 뒤로 넘겨, 불량 쪽 하나 때문에 뒤 회차를 놓치지 않는다(감사 A-06).
#       응답에서 본 가장 큰 회차를 latest_seen으로 남겨, 호출한 쪽이 빈 응답과 공식에 없는 회차를 가려낼 수 있게 한다.
def fetch_after(
    after_round: int,
    http_get: Optional[HttpGet] = None,
    progress: Optional[Callable[[int], None]] = None,
    sleep: Optional[Callable[[float], None]] = None,
) -> FetchResult:
    http_get = http_get or default_http_get
    sleep = sleep or time.sleep
    collected: dict[int, LottoDraw] = {}
    rejected: list[dict] = []
    cursor = after_round
    latest_seen = 0

    for page in range(MAX_PAGES):
        if page > 0:
            sleep(REQUEST_INTERVAL_SECONDS)
        if cursor == 0:
            items = _get_page(http_get, "srchDir=center&srchLtEpsd=1", sleep)
        else:
            items = _get_page(http_get, f"srchDir=latest&srchCursorLtEpsd={cursor}", sleep)

        newest_in_page = cursor
        for item in items:
            seen = _round_of(item) if isinstance(item, dict) else None
            if seen is not None:
                latest_seen = max(latest_seen, seen)
                newest_in_page = max(newest_in_page, seen)
            try:
                draw = parse_item(item)
            except ValueError as exc:
                rejected.append({"round": item.get("ltEpsd") if isinstance(item, dict) else None,
                                 "reason": str(exc)})
                continue
            if draw.round_no > after_round:
                collected[draw.round_no] = draw

        if newest_in_page <= cursor:  # 더 나아가지 못했으면 끝
            break
        cursor = newest_in_page
        if progress is not None:
            progress(cursor)
    else:
        raise CollectError("공식 사이트 응답이 끝나지 않습니다. 사이트가 바뀌었을 수 있습니다.", "format")

    return FetchResult(draws=[collected[n] for n in sorted(collected)], rejected=rejected, latest_seen=latest_seen)
