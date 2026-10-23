import unittest, tempfile, pathlib
from mac_traffic_ledger import ledger as l


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        l.DATA = pathlib.Path(self.temp.name)
        l.init()
        self.c = l.Collector()
        self.t = 1800000000

    def tearDown(self):
        self.c.close()
        self.temp.cleanup()

    def snap(self, up=100, down=200, ids=True, total=None):
        return {
            "uploadTotal": (total or (up, down))[0],
            "downloadTotal": (total or (up, down))[1],
            "connections": (
                [
                    {
                        "id": "a",
                        "upload": up,
                        "download": down,
                        "metadata": {
                            "network": "tcp",
                            "sourceIP": "198.18.0.1",
                            "sourcePort": "1234",
                            "destinationPort": "443",
                            "inboundIP": "198.18.0.5",
                            "host": "example.org",
                        },
                        "chains": ["node", "group"],
                        "rule": "MATCH",
                        "start": "test",
                    }
                ]
                if ids
                else []
            ),
        }

    def sums(self):
        with l.connect() as c:
            return tuple(
                c.execute(
                    "SELECT COALESCE(SUM(up),0),COALESCE(SUM(down),0) FROM samples"
                ).fetchone()
            )

    def test_initial_baseline_and_increment(self):
        self.c.ingest(self.snap(), {}, self.t)
        self.assertEqual(self.sums(), (0, 0))
        self.c.ingest(self.snap(130, 280), {}, self.t + 1)
        self.assertEqual(self.sums(), (30, 80))

    def test_restart_does_not_rebill(self):
        self.c.ingest(self.snap(), {}, self.t)
        self.c.ingest(self.snap(130, 280), {}, self.t + 1)
        c = l.Collector()
        c.ingest(self.snap(150, 300), {}, self.t + 2)
        c.ingest(self.snap(160, 310), {}, self.t + 3)
        self.assertEqual(self.sums(), (40, 90))

    def test_missing_then_returning_connection_no_double_count(self):
        self.c.ingest(self.snap(), {}, self.t)
        self.c.ingest(self.snap(130, 280), {}, self.t + 1)
        self.c.ingest(self.snap(130, 280, False), {}, self.t + 2)
        self.c.ingest(self.snap(140, 290), {}, self.t + 3)
        self.assertEqual(self.sums(), (40, 90))

    def test_counter_reset(self):
        self.c.ingest(self.snap(), {}, self.t)
        self.c.ingest(self.snap(5, 8), {}, self.t + 1)
        self.assertEqual(self.sums(), (5, 8))

    def test_new_connection_counts_from_zero(self):
        self.c.ingest(self.snap(0, 0, False), {}, self.t)
        self.c.ingest(self.snap(), {}, self.t + 1)
        self.assertEqual(self.sums(), (100, 200))

    def test_endpoint_collision_not_misattributed(self):
        m = self.snap()["connections"][0]["metadata"]
        owners = {("tcp", "198.18.0.1", "1234", "198.18.0.9", "443"): {(123, "wrong")}}
        self.assertEqual(l.identify(m, owners)[3], "unknown")

    def test_retention_keeps_daily(self):
        self.c.ingest(self.snap(), {}, self.t)
        self.c.ingest(self.snap(130, 280), {}, self.t + 1)
        self.c.ingest(self.snap(130, 280, False), {}, self.t + 31 * 86400)
        self.assertEqual(self.sums(), (0, 0))
        with l.connect() as c:
            self.assertEqual(
                tuple(c.execute("SELECT SUM(up),SUM(down) FROM daily").fetchone()),
                (30, 80),
            )

    def test_idle_connection_stays_active_and_closes(self):
        self.c.ingest(self.snap(), {}, self.t)
        self.c.ingest(self.snap(), {}, self.t + 1)
        with l.connect() as c:
            self.assertEqual(
                c.execute("SELECT active FROM connections").fetchone()[0], 1
            )
        self.c.ingest(self.snap(100, 200, False), {}, self.t + 2)
        with l.connect() as c:
            self.assertEqual(
                c.execute("SELECT active FROM connections").fetchone()[0], 0
            )
        self.assertEqual(len(self.c.known), 0)

    def test_db_connection_closed(self):
        with l.connect() as c:
            c.execute("SELECT 1")
        with self.assertRaises(l.sqlite3.ProgrammingError):
            c.execute("SELECT 1")

    def test_route_filter_and_minute_query(self):
        self.c.ingest(self.snap(), {}, self.t)
        self.c.ingest(self.snap(130, 280), {}, self.t + 1)
        q = {"start": [str(self.t)], "end": [str(self.t + 60)]}
        self.assertEqual(l.query(q)["summary"]["up"], 30)
        q["route"] = ["DIRECT"]
        self.assertEqual(l.query(q)["summary"]["up"], 0)


if __name__ == "__main__":
    unittest.main()
