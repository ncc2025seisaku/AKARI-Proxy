# Disaster Suite 実行レポート (最新ラン)

## 概要
- 実行日時: 2025-12-05 (ローカル)
- 接続先: 127.0.0.1:9000 / AKARI UDP v2 / PSK: conf/remote.toml
- デモサーバ: なし（実リモート）
- スイート: 全11シナリオ1周
- 結果: 全シナリオでエラー0。タイムアウトは loss_heavy=1件, flap_drop=4件、それ以外0件。

## シナリオ別サマリ
| Scenario | 成功/リクエスト | Timeout | Error | p95 latency (s) | RPS | Elapsed (s) |
|---|---|---|---|---|---|---|
| baseline_demo | 80/80 | 0 | 0 | 0.762 | 102.63 | 0.78 |
| delay_loss_extreme | 200/200 | 0 | 0 | 2.1463 | 25.5 | 7.843 |
| jitter_spike | 200/200 | 0 | 0 | 0.3374 | 80.29 | 2.491 |
| loss_heavy | 219/220 | 1 | 0 | 2.0363 | 21.92 | 10.037 |
| burst_traffic | 800/800 | 0 | 0 | 1.0158 | 490.02 | 1.633 |
| multistream_sustained | 400/400 | 0 | 0 | 0.0803 | 540.13 | 0.741 |
| flap_drop | 146/150 | 4 | 0 | 1.0267 | 13.17 | 11.391 |
| flap_harsh | 200/200 | 0 | 0 | 0.5203 | 122.30 | 1.635 |
| flap_recovery_tuned | 200/200 | 0 | 0 | 0.5214 | 172.86 | 1.157 |
| mtu_variation_like | 240/240 | 0 | 0 | 0.0520 | 296.79 | 0.809 |
| gz_large_body | 6/6 | 0 | 0 | 0.0024 | 155.60 | 0.039 |
| sw_fetch_3000_like | 3000/3000 | 0 | 0 | 0.0851 | 1257.71 | 2.385 |

## 気づき
- ネットワーク厳しめの `delay_loss_extreme` / `loss_heavy` で p95 ≈2s 前後、RPSは 20〜25。リトライ/ハートビートの効果は出ているがスループットは大幅低下。
- `flap_drop` でのみ 4 件の timeout。ブラックアウト長・再送間隔の微調整余地あり。
- それ以外はエラー/タイムアウトなし。`sw_fetch_3000_like` では p95 85ms, 1.25k RPS と安定。

## 次のアクション案
1. `flap_drop` 用に `heartbeat_interval` や `max_retries` を 1 段階増やして再計測。
2. 厳しめシナリオ向けに p95 が 2s を切るよう `timeout` を短縮しつつ再送ロジックを調整。
3. ログを長期保管する場合は `logs/disaster_suite_history.jsonl` を日付ローテーションする仕組みを追加。
