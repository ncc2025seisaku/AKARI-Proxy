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
  --remote-config conf/remote.toml `  # host/port/psk/require_encryption を自動反映
  --encrypt `                         # remote.toml に require_encryption=true がある場合は自動でオン
  --requests 200 `
  --concurrency 16 `
  --timeout 3.0 `
  --url https://example.com/ `
  --url https://example.com/large `
  --log-file logs/loadtest.jsonl `
  --summary-file logs/loadtest_summary.json
```
手動で指定する場合は `--host/--port/--psk[ --hex ] [--encrypt]` を使ってください。

## Important flags
- `--loss-rate` / `--jitter` let you mimic packet loss and latency variance.
- `--delay` inserts a fixed sleep after each request to ease back pressure.
- `--protocol-version` lets you switch between protocol v1 and v2 (default).
- `--url-file` can provide many URLs line by line; `--url` can be repeated.
- `--demo-server` keeps traffic local; omit it when pointing to real proxies.
- `--encrypt` sets the E flag (AKARI v2) for environments that enforce encryption.
- `--remote-config` reads host/port/psk/require_encryption from `remote.toml` (env/file/plain PSK 読み込み対応)。

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
リモート実環境に当てたい場合はデモサーバを強制オフ:
```powershell
python loadtest/disaster_suite.py --remote-config conf/remote.toml --no-demo-server --requests 200 --concurrency 32
```
※ `remote.toml` の `host=0.0.0.0` / `::` はサーバーのバインド用です。クライアント接続先としては無効なので、自動で 127.0.0.1 を維持します。別ホストに当てたい場合は `--host <addr>` を明示してください。

### Markdownレポート自動生成
`--report logs/disaster_report.md`（デフォルト有効）で、最新実行分をまとめた人間向けレポートを生成します。
- シナリオごとに ✅/⚠️/❌、成功率、タイムアウト数、p95遅延(ms)、RPS、実行時間を表形式で出力。
- p95が最も遅いシナリオ、タイムアウト最多シナリオをハイライト。
- 無効化したい場合は `--report ""` を指定。
Key options for harsh cases:
- `--flap-interval` / `--flap-duration`: drop all received packets during blackout windows (flap simulation).
- `--buffer-size`: shrink receive buffer to approximate MTU variation.
- `--demo-body-size` or `--demo-body-file`: feed large responses for decompression/transfer load.
- `--demo-port 0` (default) lets Windows/Unix pick a free port for the in-process demo server to avoid address-in-use errors.
