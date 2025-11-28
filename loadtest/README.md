# AKARI UDP Load Test Kit

This folder holds a clean load-testing setup that stays separate from production code.  
It provides a single entry point `udp_load_runner.py` and optional demo server to avoid hitting real endpoints while rehearsing.

## Prerequisites (one-time)
1. Create/activate the project's virtualenv.
2. Build the Python bindings once (required for `akari_udp_py`):
   ```powershell
   cd crates/akari_udp_py
   python -m maturin develop
   cd ..\..
   ```

## Quick start (local dry-run)
```powershell
python loadtest/udp_load_runner.py --demo-server --requests 50 --concurrency 8 --timeout 2.5
```
- Spins up an in-process UDP responder and drives it with 50 requests.
- Prints a JSON summary and, if `--log-file` is set, emits JSON Lines per request.

## Running against a remote proxy
```powershell
python loadtest/udp_load_runner.py `
  --host 203.0.113.10 `
  --port 14500 `
  --psk test-psk-0000-test `
  --requests 200 `
  --concurrency 16 `
  --timeout 3.0 `
  --url https://example.com/ `
  --url https://example.com/large `
  --log-file logs/loadtest.jsonl `
  --summary-file logs/loadtest_summary.json
```

## Important flags
- `--loss-rate` / `--jitter` let you mimic packet loss and latency variance.
- `--delay` inserts a fixed sleep after each request to ease back pressure.
- `--protocol-version` lets you switch between protocol v1 and v2 (default).
- `--url-file` can provide many URLs line by line; `--url` can be repeated.
- `--demo-server` keeps traffic local; omit it when pointing to real proxies.

## Output
The script prints a summary JSON to stdout. Example:
```json
{
  "success": 45,
  "timeout": 3,
  "error": 2,
  "exceptions": 0,
  "bytes_sent": 12345,
  "bytes_received": 23456,
  "latency_avg_sec": 0.12,
  "latency_p95_sec": 0.2,
  "latency_p99_sec": 0.25,
  "elapsed_sec": 5.43,
  "rps": 9.2
}
```

## Safety note
- Default settings keep traffic on localhost; explicitly set host/port/PSK before touching any shared or production-like environment.
- This toolkit is non-production; no production files were altered or removed.

## Disaster checklist runner
Use `disaster_suite.py` to execute a predefined set of harsh-network scenarios derived from the AKARI-UDP v2 disaster checklist. Each run appends summaries to `logs/disaster_suite_history.jsonl` and optionally request-level events to `logs/disaster_suite_events.jsonl`.
```powershell
python loadtest/disaster_suite.py --demo-server --requests 200 --concurrency 16
```
