# Changelog

## 0.1.0

- Per-process upload/download accounting from a local Mihomo Unix socket.
- macOS socket endpoint attribution with executable paths and PID detail.
- Local dashboard with process drilldown, host rankings, date and route filters, CSV export.
- Thirty-day connection detail and persistent daily process summaries.
- macOS launch agent installation and removal without deleting historical data.
- Bounded attribution cache, conditional process scans, idle-write throttling and offline backoff.
- Ten regression tests covering counter accounting, route filters, retention and resource cleanup.
