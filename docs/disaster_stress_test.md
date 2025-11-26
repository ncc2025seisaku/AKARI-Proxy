# 災害時を想定したストレステスト手順書

このドキュメントでは「障害時のようにパケット損失・遅延が増える状況」を模したストレステストのやり方を、手順だけ追えば誰でも再現できるようにまとめます。  
実施はローカルのみで完結させる方法（デモサーバー利用）と、実際のリモートプロキシに対して負荷をかける方法の2通りを記載しています。

---

## 0. 前提準備（最初の1回だけ）
1. ルートディレクトリで仮想環境を有効化  
   - `.\.venv\Scripts\activate.bat`
2. Python バインディングをビルド（まだなら）  
   - `cd crates/akari_udp_py`  
   - `python -m maturin develop`  
   - `cd ..\..\` で戻る

---

## 1. 最短で試す（デモサーバーを自前で立てる）
リモートプロキシを持っていなくても、同一プロセス内に簡易UDPサーバーを立てて即テストできます。

```powershell
# ルートで実行
python scripts/stress_test_udp.py --demo-server --requests 50 --concurrency 8 --loss-rate 0.2 --timeout 2.0
```

- `--demo-server` … 内蔵の簡易サーバーを起動し、`https://example.com/` を返す。
- `--requests 50` … 合計50リクエスト送る。
- `--concurrency 8` … 8スレッドで同時送信。
- `--loss-rate 0.2` … 受信したパケットを 20% の確率で捨てる（災害時の損失を模擬）。
- `--timeout 2.0` … 1リクエストの待ち時間上限（秒）。

実行が終わると JSON でサマリが出ます。`success/timeout/error`、平均・p95/p99レイテンシ、RPS が確認できます。

---

## 2. 実環境（リモートプロキシ）に対して叩く
1. 先にリモートプロキシを起動しておく（例: `scripts/run_remote_proxy.py`）。
2. 別ターミナルで下記を実行（PSKやポートは環境に合わせて変更）。

```powershell
python scripts/stress_test_udp.py `
  --host 203.0.113.10 `
  --port 14500 `
  --psk test-psk-0000-test `
  --requests 200 `
  --concurrency 16 `
  --loss-rate 0.1 `
  --timeout 3.0 `
  --url https://example.com/ `
  --url https://example.com/large
```

- `--url` は複数指定可能。列挙した URL を順番に回しながら送信します。
- `--hex` を付けると `--psk` を16進表記として解釈します。

---

## 3. オプション早見表
- `--requests` … 送るリクエスト総数（必須ではないが災害時シナリオでは多めに設定）。
- `--concurrency` … 同時スレッド数。上げるほど負荷が急峻になります。
- `--loss-rate` … 受信パケットをランダムに捨てる確率。0〜1。0なら損失なし。
- `--jitter` … 受信後にランダムスリープを入れる最大秒数。遅延揺らぎを付けたいときに使用。
- `--delay` … 各リクエスト終了後に固定スリープを入れる秒数。緩和したいときに使う。
- `--timeout` … 1リクエストの待ち時間上限（秒）。
- `--log-level DEBUG` … 詳細ログを出すときに。

---

## 4. 結果の見方
出力例:
```json
{
  "success": 45,
  "timeout": 3,
  "error": 2,
  "bytes_sent": 12345,
  "bytes_received": 23456,
  "latency_avg_sec": 0.1234,
  "latency_p95_sec": 0.2001,
  "latency_p99_sec": 0.2509,
  "elapsed_sec": 5.432,
  "rps": 9.2
}
```
- success / timeout / error … それぞれの件数。
- latency_* … 正常完了したリクエストの平均・p95・p99（秒）。
- bytes_* … 送受信バイト合計（UDPペイロード＋ヘッダ相当）。
- rps … 全体の平均リクエスト毎秒。

---

## 5. トラブル時のチェックポイント
- `success` が極端に少ない場合
  - PSK/ポートの誤りを確認。
  - `--timeout` を少し伸ばす。
  - 損失を強くし過ぎていないか (`--loss-rate` を下げる)。
- `timeout` が多い場合
  - リモートプロキシやネットワークの輻輳が疑われる。`--concurrency` を下げて再試行。
  - `--jitter` を小さくする。

以上で、誰でも同じ手順でストレステストを実行できます。
