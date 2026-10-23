"""Synthetic benchmark; no Clash connection or user traffic required.

PYTHONPATH=src python benchmarks/collector.py [path/to/previous_ledger.py]
"""

import importlib.util
import json
import pathlib
import sys
import tempfile
import time
from contextlib import contextmanager
from mac_traffic_ledger import ledger


def snapshot(tick):
    return {
        "uploadTotal": 200 * tick * 100,
        "downloadTotal": 200 * tick * 200,
        "connections": [
            {
                "id": str(i),
                "start": "synthetic",
                "upload": tick * 100,
                "download": tick * 200,
                "metadata": {
                    "process": "Example",
                    "processPath": "/Applications/Example.app/run",
                    "host": "example.test",
                },
                "chains": ["Example node"],
                "rule": "MATCH",
            }
            for i in range(200)
        ],
    }


def measure(module, buffered):
    with tempfile.TemporaryDirectory() as folder:
        module.DATA = pathlib.Path(folder)
        module.init()
        commits = []
        original = module.connect

        @contextmanager
        def counted():
            with original() as db:
                db.set_trace_callback(
                    lambda sql: commits.append(sql) if sql == "COMMIT" else None
                )
                yield db

        module.connect = counted
        collector = (
            module.Collector(flush_interval=10) if buffered else module.Collector()
        )
        now = time.time()
        collector.ingest(snapshot(0), {}, now)
        commits.clear()
        if buffered:
            collector.db.set_trace_callback(
                lambda sql: commits.append(sql) if sql == "COMMIT" else None
            )
        start = time.perf_counter()
        cpu = time.process_time()
        for tick in range(1, 61):
            collector.ingest(snapshot(tick), {}, now + tick)
        elapsed = time.perf_counter() - start
        cpu = time.process_time() - cpu
        if buffered:
            collector.flush(now + 60)
        result = module.query({"start": [str(now)], "end": [str(now + 120)]})
        print(
            json.dumps(
                {
                    "version": "buffered" if buffered else "previous",
                    "snapshots": 60,
                    "connections": 200,
                    "commits": len(commits),
                    "wall_ms": round(elapsed * 1000, 2),
                    "cpu_ms": round(cpu * 1000, 2),
                    "overview_bytes": len(json.dumps(result).encode()),
                    "up": result["summary"]["up"],
                    "down": result["summary"]["down"],
                }
            )
        )
        if buffered:
            collector.close()
        module.connect = original


if len(sys.argv) > 1:
    spec = importlib.util.spec_from_file_location("previous", sys.argv[1])
    previous = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(previous)
    measure(previous, False)
measure(ledger, True)
