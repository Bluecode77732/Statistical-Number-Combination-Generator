import http.client
import io
import unittest
import urllib.error

import collector
from tests.helpers import FakeServer, make_draws, no_sleep


class FetchAfterTest(unittest.TestCase):
    def test_full_fetch_from_zero_is_contiguous(self):
        server = FakeServer(make_draws(25))
        result = collector.fetch_after(0, http_get=server, sleep=no_sleep)
        self.assertEqual([d.round_no for d in result.draws], list(range(1, 26)))
        self.assertEqual(result.rejected, [])

    def test_only_rounds_after_cursor(self):
        server = FakeServer(make_draws(25))
        result = collector.fetch_after(20, http_get=server, sleep=no_sleep)
        self.assertEqual([d.round_no for d in result.draws], [21, 22, 23, 24, 25])

    def test_already_latest_returns_nothing(self):
        server = FakeServer(make_draws(25))
        result = collector.fetch_after(25, http_get=server, sleep=no_sleep)
        self.assertEqual(result.draws, [])

    def test_parsed_values_match_source(self):
        draws = make_draws(12)
        result = collector.fetch_after(0, http_get=FakeServer(draws), sleep=no_sleep)
        got = result.draws[4]
        self.assertEqual((got.numbers, got.bonus, got.draw_date), (draws[4].numbers, draws[4].bonus, draws[4].draw_date))

    def test_network_error_retries_then_raises(self):
        server = FakeServer(make_draws(5))
        server.fail_times = 99
        with self.assertRaises(collector.CollectError) as ctx:
            collector.fetch_after(0, http_get=server, sleep=no_sleep)
        self.assertEqual(ctx.exception.kind, "network")
        self.assertEqual(len(server.calls), collector.RETRIES + 1)

    def test_transient_network_error_recovers(self):
        server = FakeServer(make_draws(5))
        server.fail_times = 1
        result = collector.fetch_after(0, http_get=server, sleep=no_sleep)
        self.assertEqual(len(result.draws), 5)

    def test_html_response_is_format_error(self):
        server = FakeServer(make_draws(5))
        server.body_override = b"<html><head><title>The document has been moved.</title></head></html>"
        with self.assertRaises(collector.CollectError) as ctx:
            collector.fetch_after(0, http_get=server, sleep=no_sleep)
        self.assertEqual(ctx.exception.kind, "format")

    def test_missing_list_is_format_error(self):
        server = FakeServer(make_draws(5))
        server.body_override = b'{"data": {}}'
        with self.assertRaises(collector.CollectError):
            collector.fetch_after(0, http_get=server, sleep=no_sleep)

    def test_invalid_round_is_rejected_not_stored(self):
        draws = make_draws(15)
        server = FakeServer(draws)
        server.bad_rounds[7] = {"tm2WnNo": draws[6].numbers[0]}  # 번호 중복
        server.bad_rounds[9] = {"tm1WnNo": 46}                    # 범위 밖
        server.bad_rounds[11] = {"bnsWnNo": draws[10].numbers[0]}  # 보너스 중복
        result = collector.fetch_after(0, http_get=server, sleep=no_sleep)
        rounds = [d.round_no for d in result.draws]
        for bad in (7, 9, 11):
            self.assertNotIn(bad, rounds)
        self.assertEqual(sorted(r["round"] for r in result.rejected), [7, 9, 11])

    # 목적: 응답을 받다 중간에 끊긴 경우(IncompleteRead)도 네트워크 오류로 재시도하고, 끝내 실패하면 CollectError가 되는지 확인한다.
    # 이유: 이 예외는 OSError가 아니라 재시도 대상에서 빠져, 기존 데이터가 있어도 실행 전체가 처리되지 않은 오류로 멈췄다(감사 A-05).
    # 방법: 첫 요청만 끊기는 가짜 응답으로 복구를, 계속 끊기는 가짜 응답으로 재시도 횟수와 오류 종류를 본다.
    def test_incomplete_read_is_retried_and_reported_as_network_error(self):
        real = FakeServer(make_draws(5))
        calls = []

        # 목적: 첫 요청만 응답 도중 끊기고 그다음부터 정상으로 돌려주는 가짜 응답이다.
        # 이유: 일시적인 끊김이 재시도로 복구되는지 보려면 한 번만 실패해야 한다.
        # 방법: 호출 횟수를 세어 첫 호출에서만 IncompleteRead를 낸다.
        def flaky(url):
            calls.append(url)
            if len(calls) == 1:
                raise http.client.IncompleteRead(b"")
            return real(url)

        self.assertEqual(len(collector.fetch_after(0, http_get=flaky, sleep=no_sleep).draws), 5)

        broken_calls = []

        # 목적: 요청마다 응답 도중 끊기는 가짜 응답이다.
        # 이유: 재시도를 모두 쓴 뒤 CollectError가 되는지, 시도 횟수가 맞는지 보려면 계속 실패해야 한다.
        # 방법: 호출 기록을 남기고 항상 IncompleteRead를 낸다.
        def broken(url):
            broken_calls.append(url)
            raise http.client.IncompleteRead(b"")

        with self.assertRaises(collector.CollectError) as ctx:
            collector.fetch_after(0, http_get=broken, sleep=no_sleep)
        self.assertEqual(ctx.exception.kind, "network")
        self.assertEqual(len(broken_calls), collector.RETRIES + 1)

    # 목적: 사이트가 HTTP 403으로 거절하면 안내 문구에 번호가 있고 "인터넷 연결 확인"으로 잘못 안내하지 않는지 확인한다.
    # 이유: 접속 제한과 인터넷 끊김은 점검할 곳이 다른데 같은 문구로 안내했다(감사 A-13).
    # 방법: 항상 403을 내는 가짜 응답으로 받아 오류 종류와 문구를 본다.
    def test_http_403_is_named_in_the_message(self):
        # 목적: 요청마다 HTTP 403으로 거절하는 가짜 응답이다.
        # 이유: 접속 제한 때의 안내 문구를 확인하려면 사이트가 계속 거절해야 한다.
        # 방법: 받은 주소로 HTTPError(403)를 만들어 던진다.
        def forbidden(url):
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, io.BytesIO(b""))

        with self.assertRaises(collector.CollectError) as ctx:
            collector.fetch_after(0, http_get=forbidden, sleep=no_sleep)
        self.assertEqual(ctx.exception.kind, "network")
        self.assertIn("403", str(ctx.exception))
        self.assertNotIn("인터넷 연결", str(ctx.exception))

    # 목적: 형식은 맞지만 달력에 없는 추첨일을 받은 회차가 저장되지 않고 거부되는지 확인한다.
    # 이유: 8자리 숫자인지만 보면 20261399 같은 날짜가 전용 엑셀에 들어간다(감사 A-10).
    # 방법: 한 회차의 추첨일을 달력에 없는 값으로 바꿔 받고, 그 회차가 거부 목록에만 있는지 본다.
    def test_impossible_date_is_rejected(self):
        server = FakeServer(make_draws(15))
        server.bad_rounds[8] = {"ltRflYmd": "20261399"}
        result = collector.fetch_after(0, http_get=server, sleep=no_sleep)
        self.assertNotIn(8, [d.round_no for d in result.draws])
        self.assertEqual([r["round"] for r in result.rejected], [8])
        self.assertIn("날짜", result.rejected[0]["reason"])


if __name__ == "__main__":
    unittest.main()
