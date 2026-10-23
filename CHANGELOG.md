# Changelog

## 0.2.0

- Warm neutral dashboard with system/light/dark themes and local fonts.
- Separate overview, connection detail and daily ledger views; process drilldown retains all connection metadata.
- Lazy connection pagination (50 per page), current-page CSV export, bounded trend aggregation and consistent read snapshots.
- Reused SQLite writer with 10-second / 5,000-row-change transaction commits, graceful flush and rollback of delta state on write failure.
- Explicit disclosure of pending-write loss on forced termination and delayed display of committed statistics.
- Background browser refresh timers stop while hidden; overview refreshes every ten seconds, other views refresh on demand.
- Nineteen backend regression tests and a reproducible synthetic collector benchmark.
- Existing database schema and daily history remain compatible.

## 0.1.0

- Per-process upload/download accounting from a local Mihomo Unix socket.
- macOS socket endpoint attribution with executable paths and PID detail.
- Local dashboard with process drilldown, host rankings, date and route filters, CSV export.
- Thirty-day connection detail and persistent daily process summaries.
- macOS launch agent installation and removal without deleting historical data.
- Bounded attribution cache, conditional process scans, idle-write throttling and offline backoff.
- Ten regression tests covering counter accounting, route filters, retention and resource cleanup.
