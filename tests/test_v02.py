import copy
import csv
import io
import json
import pathlib
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from mac_traffic_ledger import ledger as l


def snapshot(n=1, up=100, down=200):
    return {
        "uploadTotal": n * up,
        "downloadTotal": n * down,
        "connections": [
            {
                "id": f"conn-{i:04d}",
                "upload": up,
                "download": down,
                "start": "2026-01-01",
                "metadata": {
                    "process": "Synthetic app",
                    "processPath": "/Applications/Example.app/run",
                    "host": "example.test",
                    "sourcePort": "1234",
                    "destinationPort": "443",
                    "network": "tcp",
                },
                "chains": ["Example node"],
                "rule": "DomainSuffix",
                "rulePayload": "example.test",
            }
            for i in range(n)
        ],
    }


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_data = l.DATA
        l.DATA = pathlib.Path(self.tmp.name)
        l.init()
        self.c = l.Collector(flush_interval=10)
        self.now = 1800000000

    def tearDown(self):
        self.c.close()
        l.DATA = self.old_data
        self.tmp.cleanup()

    def totals(self):
        with l.connect() as db:
            return tuple(
                db.execute(
                    "SELECT COALESCE(SUM(up),0),COALESCE(SUM(down),0) FROM samples"
                ).fetchone()
            )

    def query(self, **options):
        q = {"start": [str(self.now)], "end": [str(self.now + 3600)]}
        q.update({k: [str(v)] for k, v in options.items()})
        return l.query(q)

    def seed(self, n=1):
        self.c.ingest(snapshot(n, 0, 0), {}, self.now)
        self.c.ingest(snapshot(n), {}, self.now + 1)
        self.c.flush(self.now + 1)

    def test_buffer_visibility_and_close_flush(self):
        self.c.ingest(snapshot(), {}, self.now)
        self.c.ingest(snapshot(up=120, down=230), {}, self.now + 1)
        self.assertEqual(self.totals(), (0, 0))
        self.c.close()
        self.assertEqual(self.totals(), (20, 30))

    def test_ten_second_commit_and_connection_reuse(self):
        self.c.ingest(snapshot(up=0, down=0), {}, self.now)
        db = self.c.db
        commits = []
        db.set_trace_callback(
            lambda sql: commits.append(sql) if sql == "COMMIT" else None
        )
        for i in range(1, 61):
            self.c.ingest(snapshot(up=i, down=2 * i), {}, self.now + i)
        self.assertIs(self.c.db, db)
        self.assertEqual(len(commits), 6)
        self.assertEqual(self.totals(), (60, 120))

    def test_rollback_restores_delta_checkpoint(self):
        self.c.ingest(snapshot(up=0, down=0), {}, self.now)
        self.c.ingest(snapshot(up=10, down=20), {}, self.now + 1)
        bad = snapshot(up=15, down=30)
        bad["connections"].append({"id": "broken"})
        with self.assertRaises(KeyError):
            self.c.ingest(bad, {}, self.now + 2)
        self.c.ingest(snapshot(up=20, down=40), {}, self.now + 10)
        self.assertEqual(self.totals(), (20, 40))

    def test_write_threshold_forces_early_commit(self):
        self.c.ingest(snapshot(1800, 0, 0), {}, self.now)
        self.c.ingest(snapshot(1800, 1, 2), {}, self.now + 1)
        self.assertEqual(self.totals(), (1800, 3600))

    def test_overview_does_not_fetch_full_connections(self):
        self.seed(125)
        data = self.query()
        self.assertEqual(data["summary"]["connections"], 125)
        self.assertEqual(data["connections"], [])
        self.assertEqual(data["summary"]["up"], 12500)

    def test_pages_cover_all_connections_without_overlap(self):
        self.seed(125)
        pages = [self.query(view="connections", page=i) for i in range(3)]
        self.assertEqual([len(p["connections"]) for p in pages], [50, 50, 25])
        ids = [r["id"] for p in pages for r in p["connections"]]
        self.assertEqual(len(set(ids)), 125)
        self.assertEqual(pages[0]["count"], 125)
        self.assertNotIn("trend", pages[0])

    def test_long_range_trend_is_bounded_and_keeps_total(self):
        self.c.ingest(snapshot(up=0, down=0), {}, self.now)
        for i in range(1, 501):
            self.c.ingest(snapshot(up=i, down=2 * i), {}, self.now + i * 60)
        self.c.flush()
        data = l.query({"start": [str(self.now)], "end": [str(self.now + 501 * 60)]})
        self.assertLessEqual(len(data["trend"]), 121)
        self.assertEqual(sum(r["up"] for r in data["trend"]), 500)
        self.assertEqual(sum(r["down"] for r in data["trend"]), 1000)

    def test_invalid_filters(self):
        for q in [
            {"start": ["nan"]},
            {"start": ["inf"]},
            {"start": ["2"], "end": ["1"]},
            {"process": ["{}"]},
            {"process": ["[1,2]"]},
        ]:
            with self.assertRaises(ValueError):
                l.query(q)

    def test_static_assets_export_and_error_response(self):
        self.seed()
        server = l.ThreadingHTTPServer(("127.0.0.1", 0), l.Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            for path, kind in [
                ("/", "text/html"),
                ("/app.js", "text/javascript"),
                ("/style.css", "text/css"),
            ]:
                with urllib.request.urlopen(base + path) as response:
                    self.assertTrue(response.headers["Content-Type"].startswith(kind))
                    self.assertGreater(len(response.read()), 100)
            with urllib.request.urlopen(
                base
                + f"/api/export?start={self.now}&end={self.now + 100}&view=connections"
            ) as response:
                rows = list(
                    csv.DictReader(io.StringIO(response.read().decode("utf-8-sig")))
                )
                self.assertEqual(rows[0]["process"], "Synthetic app")
                self.assertEqual(rows[0]["up"], "100")
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(base + "/api/data?start=nan")
            self.assertEqual(error.exception.code, 400)
        finally:
            server.shutdown()
            thread.join()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
