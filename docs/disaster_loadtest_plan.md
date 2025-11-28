# AKARI-UDP v2 災害時チェックリスト対応ロードテスト手順書

このドキュメントは「AKARI-UDP v2 が満たすべき災害時要件チェックリスト」を実地で測るための
ロードテスト手順とツールの説明をまとめたものです。  
テストはすべて **自分が管理する環境（ローカル/自前VPS）内だけ** で行う前提です。

## 1. 目的とカバレッジ
- 高遅延/高ロス/ジッター/断続断の耐性
- バースト・多ストリーム時のスケジューラ/バッファ耐性
- 再送/NACK/順序逆転時の安定性
- 圧縮保持 → ローカル解凍の CPU/メモリ負荷観察（長時間ラン）

これらを以下のシナリオで確認します。シナリオは `loadtest/disaster_suite.py` に実装されています。

| key | 概要 | 主眼 (チェックリスト対応) |
| --- | --- | --- |
| baseline_demo | ローカルデモで疎通 sanity | 正常系の基準値取得 |
| delay_loss_extreme | 3s 遅延 + 20% ロス + 300ms ジッター | 遅延3000ms/ロス20%耐性 |
| jitter_spike | 350ms ジッター | ジッター300ms超で再送暴走しないか |
| loss_heavy | ロス25% | ロス大時のバックオフ・重複処理 |
| burst_traffic | 高並列・高PPS | バースト/多ストリーム耐性 |
| multistream_sustained | 中並列で長めの持続 | バッファ枯渇・リーク観察 |
| flap_drop | 断続ドロップ20% + 軽い待ち | 断続断後の復帰・再確立速度 |

## 2. 事前準備
1. Python 仮想環境を有効化。
2. Python バインディングを一度ビルド（未実施なら）:
   ```powershell
   cd crates/akari_udp_py
   python -m maturin develop
   cd ..\..
   ```
3. ローカル/テスト用のリモートプロキシ先を用意（外部本番には送らない）。

## 3. 実行方法
### 3.1 シナリオ一括実行（履歴追記あり）
```powershell
python loadtest/disaster_suite.py --demo-server --requests 200 --concurrency 16
```
- すべてのシナリオを順番に実行し、サマリを `logs/disaster_suite_history.jsonl` に **追記**。
- 詳細イベント（リクエスト単位）は `logs/disaster_suite_events.jsonl` に **追記**。
- 直近の集計を書き出す `logs/disaster_suite_summary.json` を上書き生成。

### 3.2 特定シナリオだけ
```powershell
python loadtest/disaster_suite.py --scenario delay_loss_extreme --scenario burst_traffic --demo-server
```

### 3.3 繰り返し回数を増やす
```powershell
python loadtest/disaster_suite.py --repeat 3 --demo-server
```

### 3.4 既存のリモートプロキシを使う
```powershell
python loadtest/disaster_suite.py `
  --host 203.0.113.10 `
  --port 14500 `
  --psk test-psk-0000-test `
  --protocol-version 2 `
  --url https://example.com/large `
  --repeat 2
```

### 3.5 イベントログを無効化
```powershell
python loadtest/disaster_suite.py --no-event-log --demo-server
```

## 4. 生成されるファイル
- `logs/disaster_suite_history.jsonl`  
  各シナリオ実行ごとのサマリが **追記** されます（時刻・シナリオ key・実行パラメータ・結果）。
- `logs/disaster_suite_events.jsonl`  
  `udp_load_runner` からのリクエスト単位イベントが **追記** されます（scenario key が付与されます）。
- `logs/disaster_suite_summary.json`  
  直近実行の全シナリオ結果をまとめた JSON（毎回上書き）。

## 5. 出力フィールド例
`disaster_suite.py` 実行時の JSONL 1 行例:
```json
{
  "timestamp": 1732610000.123,
  "iteration": 1,
  "scenario": "delay_loss_extreme",
  "runtime": {
    "host": "127.0.0.1",
    "port": 14500,
    "requests": 200,
    "concurrency": 16,
    "timeout": 6.0,
    "loss_rate": 0.2,
    "jitter": 0.3
  },
  "summary": {
    "success": 180,
    "timeout": 15,
    "error": 5,
    "latency_p95_sec": 1.9
  }
}
```

## 6. チェックリスト対応の読み方
- 高遅延＋ロス: `delay_loss_extreme` の成功/timeout割合と p95/p99 を確認。
- ジッター: `jitter_spike` で再送暴走や error 増を確認。
- バースト/多ストリーム: `burst_traffic` でエラー増加や RPS 低下を確認。
- 長時間稼働/バッファ: `multistream_sustained` のメモリ/CPUを別途観察（htop/pprof併用）。
- 断続断: `flap_drop` で timeout/再接続の安定性を確認。

## 7. 注意点
- `--demo-server` を付けると完全ローカルで安全に試せます。外部を叩く場合は必ずテスト用環境だけに限定してください。
- MTU変動や再順序入れ替えの厳密再現は OS の `tc/netem` が必要です（本スクリプトではロス/ジッターで近似）。
- ログはすべて追記型です。容量が増えたら適宜ローテーションしてください。

## 8. 参考
- 実行エントリ: `loadtest/disaster_suite.py`
- 基本ランナー: `loadtest/udp_load_runner.py`
- テスト結果: `logs/disaster_suite_history.jsonl`, `logs/disaster_suite_events.jsonl`, `logs/disaster_suite_summary.json`
