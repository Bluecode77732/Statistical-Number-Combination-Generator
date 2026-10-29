import os
import tempfile
import unittest
from unittest import mock

import collector
import pipeline
from tests.helpers import FakeServer, make_draws, no_sleep


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"LOTTO_DATA_DIR": self.tmp.name})
        self.env.start()
        self.server = FakeServer(make_draws(130))
        self.patches = [
            mock.patch.object(collector, "default_http_get", self.server),
            mock.patch.object(collector.time, "sleep", no_sleep),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.env.stop()
        self.tmp.cleanup()

    def test_full_run_produces_every_section(self):
        p = pipeline.Pipeline()
        p.run()
        self.assertEqual(p.state, "done")
        r = p.result
        self.assertEqual(r["sync"]["status"], "created")
        self.assertEqual(len(r["analysis"]), 9)
        self.assertTrue(r["backtest"]["ran"])
        self.assertTrue(os.path.exists(r["backtest"]["saved_path"]))
        self.assertEqual(len(r["candidates"]["numbers"]), 10)
        self.assertTrue(all(s["state"] == "done" for s in p.status()["steps"]))

    def test_offline_first_run_stops_cleanly(self):
        self.server.fail_times = 99
        p = pipeline.Pipeline()
        p.run()
        self.assertEqual(p.state, "failed")
        self.assertNotIn("candidates", p.result)
        self.assertEqual(p.steps["candidates"]["state"], "skipped")

    def test_offline_later_run_uses_existing_data(self):
        pipeline.Pipeline().run()
        self.server.fail_times = 99
        p = pipeline.Pipeline()
        p.run()
        self.assertEqual(p.state, "done")
        self.assertEqual(p.steps["sync"]["state"], "warning")
        self.assertEqual(len(p.result["candidates"]["numbers"]), 10)


if __name__ == "__main__":
    unittest.main()
