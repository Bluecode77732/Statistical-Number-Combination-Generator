import unittest

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


if __name__ == "__main__":
    unittest.main()
