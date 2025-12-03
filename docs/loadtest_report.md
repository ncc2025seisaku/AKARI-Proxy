# AKARI-Proxy 災害時想定ロードテストサマリ（発表用）

## 1. テスト概要
- 目的: フラップ（断続断 1.3s 周期/0.12s 断）とロス5%の厳しめ環境で、AKARI-Proxy（AKARI-UDP v2 経由）の耐性を確認。
- 実行: `disaster_suite.py --scenario flap_recovery_tuned --demo-server --requests 60 --concurrency 12 --dual-send --retry-jitter 0.2`
- デモサーバのみ使用（外部への実トラフィックなし）。

## 2. 主要オプションと環境変数
- `AKARI_RESP_DUP_COUNT=2`（全チャンク冗長送信2倍）
- `AKARI_HEAD_DUP_COUNT=4`（先頭チャンク冗長4倍）
- `AKARI_FEC_PARITY=1`（軽量FEC XOR パリティ有効）
- `AKARI_FEC_CHUNK_SIZE=256`（小分割）
- クライアント: デュアル送信 + 再送ジッター 0.2s

## 3. 結果サマリ（flap_recovery_tuned）
| 指標 | 値 |
| --- | --- |
| success | **367** |
| timeout | 33 |
| error / exceptions | 0 / 0 |
| latency p95 / p99 | 0.0103s / 0.0127s |
| RPS (全送信ベース) | 11.1 |
| bytes_sent / bytes_received | 26,000 / 22,387 |

※ フラップ条件: 1.3s 周期で 0.12s の完全断、ロス 5%。  
※ 既定より大幅に厳しい条件だが、冗長送信 + FEC + デュアル送信で成功率を大きく確保。

## 4. 一般的なブラウザ（Chrome/Edge 等）との違い
- **輸送層**: 一般ブラウザは TCP/TLS（HTTP/2,3）主体。AKARI-Proxy は UDP + 独自FEC/冗長送信で「黒帯」を避けやすい。
- **遅延耐性**: TCP は head-of-line blocking の影響が残る。AKARI は小分割・FEC・冗長送信により部分欠損を吸収。
- **断続断への強さ**: デュアル送信 + 先頭チャンク冗長 + FEC により、ブラックアウト窓を跨いでも復元しやすい。
- **可視化**: p95/p99 が 10〜13ms で安定（極端な断続断条件下）。一般ブラウザで同条件ならセッション切断・再接続の揺らぎが増えやすい。

## 5. 使い方メモ（再現・発表用）
1. 環境変数設定（PowerShell例）  
   ```powershell
   $env:AKARI_RESP_DUP_COUNT=2
   $env:AKARI_HEAD_DUP_COUNT=4
   $env:AKARI_FEC_PARITY=1
   $env:AKARI_FEC_CHUNK_SIZE=256
   ```
2. テスト実行  
   ```powershell
   .\.venv\Scripts\python.exe loadtest/disaster_suite.py `
     --demo-server --requests 60 --concurrency 12 `
     --scenario flap_recovery_tuned `
     --no-event-log --dual-send --retry-jitter 0.2
   ```
3. 結果参照  
   - `logs/disaster_suite_summary.json`（最新実行）
   - `logs/disaster_suite_history.jsonl`（履歴追記）

## 6. 補足
- テストは完全ローカル（demo-server）で外部への負荷なし。
- フラップ条件をさらに現実寄りに緩和（例: 0.1s/1.4s 周期）すると成功率はより上がる想定。
