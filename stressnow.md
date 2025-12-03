# 負荷テストまとめ（stressnow版）

- **目的**: AKARI-UDP プロキシの耐性/スループット/回復力を確認する専用ツール群。`loadtest/udp_load_runner.py` が単体ランナー、`loadtest/disaster_suite.py` が厳しめシナリオのバッチ実行。
- **通信モデル**: 送信は `AkariUdpClient` 派生の `LoadTestClient`、受信はリモート実サーバまたは `--demo-server` で起動するローカル `AkariUdpServer`。パケットロス/ジッター/フラップをテスター側で意図的に注入し、v2 の NACK や再送、FEC パリティ挙動を観察できる。

## エントリーポイントと設定ファイル
- 単発実行: `python loadtest/udp_load_runner.py [options]`
- シナリオ一括: `python loadtest/disaster_suite.py [options]`
- 設定ソース:
  - コマンドライン引数（主要）：`--host`, `--port`, `--psk`, `--protocol-version`, `--requests`, `--concurrency`, `--timeout`, `--loss-rate`, `--jitter`, `--flap-interval`, `--flap-duration`, `--max-nack-rounds`, `--buffer-size`, `--heartbeat-*`, `--max-retries`, `--delay`, `--dual-send`, `--url`/`--url-file`, `--log-file`, `--summary-file`, `--demo-*`。
  - シナリオ定義: `loadtest/disaster_suite.py` の `SCENARIOS` リストでキー/説明/上書き値を管理。`--scenario` で選択、`--repeat` で反復。
  - ログ出力パス: `--log-file`, `--summary-file`, `--suite-log`, `--suite-summary`, `--event-log` で指定（既定は `logs/` 配下）。

## 代表的な起動例
- **ローカル乾燥 run（デモサーバ付き）**  
  `python loadtest/udp_load_runner.py --demo-server --requests 50 --concurrency 8 --timeout 2.5`
- **実リモートに対して**  
  `python loadtest/udp_load_runner.py --host <remote> --port 14500 --psk <psk> --requests 200 --concurrency 16 --timeout 3.0 --url https://example.com/ --log-file logs/loadtest.jsonl --summary-file logs/loadtest_summary.json`
- **災害系シナリオ一括**  
  `python loadtest/disaster_suite.py --demo-server --requests 200 --concurrency 16`  
  シナリオキー例: `baseline_demo`, `delay_loss_extreme`, `flap_harsh`, `gz_large_body`, `sw_fetch_3000_like` など（`SCENARIOS` に一覧）。

## 測定・出力の意味
- `udp_load_runner` の標準出力/サマリ JSON:  
  - `success`: 完了しエラーなし  
  - `timeout`: タイムアウト判定（UDP待受経過 or エラーコード=TIMEOUT）  
  - `error`: それ以外の失敗（エラーパケット、例外など）  
  - `exceptions`: 例外件数（スレッド内で捕捉）  
  - `bytes_sent` / `bytes_received`: 総転送量  
  - `latency_avg_sec` / `p95` / `p99`: 完了リクエストの片道処理時間（送信→受信完了まで）  
  - `elapsed_sec`: 総経過時間、`rps`: リクエスト/秒（総リクエスト÷経過）  
- `--log-file` / `--event-log`: JSON Lines でリクエスト単位の詳細を保存（message_id、完了可否、タイムアウト、status_code、受信バイト、エラーペイロードなど）。`--log-context`（災害スイート経由）でシナリオ名も付与。
- `disaster_suite` の履歴:  
  - `logs/disaster_suite_history.jsonl`: シナリオごとの実行記録（開始時刻、iteration、runtime パラメータ、summary）。  
  - `logs/disaster_suite_summary.json`: 直近実行のまとめ（records 配列）。

## ネットワーク劣化・通信制御の扱い
- **ロス/ジッター/フラップ**: `LoadTestClient` が受信後にドロップ判定 (`--loss-rate`)、sleep によるジッター (`--jitter`)、周期的全ドロップ (`--flap-interval`/`--flap-duration`) を挿入。実パケットには影響せず、テスト側で意図的に欠損を作り出す。
- **NACK と再送**: v2 では欠損ビットマップを計算し、`--max-nack-rounds` 回まで NACK を送信。リモート側の `resp` キャッシュ（5 秒）から欠損チャンクのみ再送されるため、通信回復挙動を観察できる。
- **FEC パリティ**: リモート実装 (`akari.remote_proxy.handler`) が `AKARI_FEC_PARITY=1` でパリティチャンクを追加送信。ローカル側 `ResponseAccumulator` が 1 チャンク欠損まで XOR 復元を試行。負荷テストではこの挙動もログで確認可能。
- **ハートビート/リトライ**: `--heartbeat-*`, `--max-retries`, `--retry-jitter` で再送ポーリングを有効化し、沈黙時の再送を制御。災害系シナリオでフラップ復帰を検証する際に使用。
- **MTU/バッファ**: `--buffer-size` を絞ると MTU 変動やフラグメント風の挙動を模擬。チャンクの分割/再構成が崩れないかを確認。

## 結果の読み方（発表用ポイント）
- **成功率/タイムアウト率**: 回復不能なロスや上流遅延の影響を即時把握。NACK/FEC 設定の有効性を比較するときの基軸。
- **レイテンシ分布**: `p95/p99` が大きく跳ねるシナリオはジッターやフラップ耐性が課題。再送/ハートビート設定変更での改善度を強調。
- **転送バイト量**: 再送・冗長送信（ヘッド重複、FEC）によるオーバーヘッドを示す。帯域制約の議論材料。
- **シナリオ履歴**: `disaster_suite_history.jsonl` を連続実行で溜め、パラメータと結果の紐づけを保持。回帰比較やチューニングの根拠に使える。

## 付帯ツール/デモ
- `--demo-server`: 本番影響なしで完結テスト（固定ボディ or `--demo-body-size`/`--demo-body-file`）。  
- `--dual-send`: 同一 URL を message_id を変えて二重送信し、重複時の安定性を確認。  
- `--url-file`: 大量 URL を外部ファイルで供給。`--url` は複数指定可。  
- `logs/` ディレクトリは自動生成されるので事前作成不要。

---
発表の勘所: 「ロス/ジッター/フラップをテスト側で自在に注入し、NACK/FEC/再送の効き目を数値化できる」「シナリオは `disaster_suite.py` の `SCENARIOS` 一覧で管理し、履歴は JSONL で追跡可能」の2点を押さえると伝わりやすい。
