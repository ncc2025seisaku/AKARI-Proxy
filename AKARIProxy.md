# AKARI Proxy 超ざっくり解説（馬鹿でもわかる版）

「ブラウザ → ローカルWebプロキシ → UDP → リモートプロキシ → インターネット」をつなぐ簡易リバースプロキシ。HTTPはPython側、バイナリのAKARI-UDPはRust側で処理する。

```
ブラウザ --HTTP--> Web Proxy (py/akari/web_proxy)
              |            \
              |             `-- UDP クライアント (py/akari/udp_client)
              v
      リモートプロキシ (py/akari/remote_proxy, py/akari/udp_server)
              |
          HTTP/HTTPS
              |
          外部サイト
```

## 主な部品と役割
- `crates/akari_udp_core`: Rust実装のAKARI-UDPコア。ヘッダ組み立て、HMAC/AEAD、Req/Resp/Ack/Nack/Errorのエンコード・デコードを担当。
- `crates/akari_udp_py`: 上記をpyo3経由でPythonから呼べるようにしたバインディング。
- `py/akari/remote_proxy`: UDPで受け取ったリクエストをHTTPで取りに行き、AKARI-UDPレスポンスにして返すサーバ。
- `py/akari/web_proxy`: ブラウザ向けのHTTPサーバ(UI付き)。受け取ったURLをUDPでリモートプロキシへ投げ、結果をブラウザへ戻す。
- `conf/remote.toml`, `conf/web_proxy.toml`: PSKや待ち受けポートなどの設定。

## AKARI-UDPの超簡単仕様
- ヘッダ24B共通:
  - Magic "AK", `version` (1/2), `type` (req/resp/ack/nack/error), `flags` (0x80=暗号化Eフラグ, 0x40=ヘッダ付きなど), `message_id`, `seq`, `seq_total`, `payload_len`, `timestamp`
- 保護:
  - Eフラグなし: ヘッダ+ペイロードにPSKでHMAC-SHA256をかけ、先頭16Bをタグとして末尾に付ける。
  - Eフラグあり: XChaCha20-Poly1305(AEAD)で暗号化＋タグ。PSKは32Bでそのまま、違う長さならSHA-256で伸長。
- メッセージ種別:
  - `req`: URL(とv2ではHTTPヘッダブロック)を送る。v2は任意メソッド(get/head/post)とヘッダ長付き。
  - `resp`: 先頭チャンク(seq=0)に`status_code`・`body_len`・ヘッダブロック、続きはボディ断片。
  - `ack`/`nack`: 取りこぼし再送用。ackは「ここから欠けてるseq」を1つ示し、nackはビットマップで複数seqを要求。
  - `error`: エラーコード＋HTTPステータス＋短いメッセージ。

## 通信の流れ（正常系）
1. **ブラウザ→Web Proxy**: HTTPでURLを受け取る。必要ならコンテンツフィルタ(JS/CSS/画像など)をチェック。
2. **UDPリクエスト生成**: `akari_udp_core::encode_request_v2`で`message_id`と`timestamp`入りのreqパケットを作る。暗号化したいときはEフラグON。
3. **送信と受信待ち** (`py/akari/udp_client.py`): UDPでリモートプロキシへ送信し、同じ`message_id`のresp/errorを集める。タイムアウト/欠落監視をしながらループ。
4. **リモート側で受信** (`py/akari/udp_server.py` → `remote_proxy/handler.py`):
   - HMAC/AEADとバージョンを検証し、req以外はACK/NACKなどに応じて再送処理。
   - URLをHTTPで取得(`remote_proxy/http_client.py`)。タイムアウトや上限を超えたらerrorパケットに変換。
   - レスポンスボディをMTUに合わせて分割。v2ではHTTPヘッダを静的テーブル化してヘッダブロックに詰め、先頭チャンク(seq=0)に付与。
   - 作ったrespチャンク列をUDPで送り返す。直近のレスポンスは5秒間キャッシュしてNACK/ACKでの再送に使う。
5. **ローカルで組み立て** (`ResponseAccumulator`):
   - 受け取ったrespチャンクを`seq`順に溜める。`seq_total`分集まれば完成。
   - 欠けがあるときはv2では`encode_nack_v2_py`でビットマップ再送要求を送り、必要に応じて`ack`で「ここから足りない」を通知。
   - body完成後、HTTPヘッダをデコードし、ブラウザへそのまま返す（CSPなど一部ヘッダは外す／Locationはプロキシ経由に書き換え）。

## エラーとリトライのざっくり
- **HTTP取得エラー**: fetchでURL不正/タイムアウト/サイズ超過/上流失敗が起きたらerrorパケットにして返す。
- **UDP欠落**: タイムアウトまでに先頭チャンクが来ない場合はリクエストを再送。途中欠落はNACK/ACKで再送要求。リトライ回数は`AkariUdpClient`の設定依存。
- **サーバ側再送**: 直近5秒以内のレスポンスをキャッシュし、NACK/ACKで指定された`seq`だけ送り直す。
- **暗号化強制**: `conf/remote.toml`で`require_encryption=true`にするとEフラグなしreqは即400エラーで落とす。

## 知っておく数値の目安
- デフォルトで1datagram ≒ 1150B以下に抑制（MTU1200B想定、UDP+AKARIヘッダ+HMACタグを引いた残り）。
- UDP受信バッファはリモート側既定1MB (`conf/remote.toml`)、クライアント側も起動時にSO_RCVBUFを広げようとする。
- レスポンス再送キャッシュTTL: 5秒。

## どうやって使うか（最小手順）
1) リモートプロキシを起動: `scripts/run_remote_proxy.py --config conf/remote.toml`  
2) Web Proxy(UI付き)を起動: `scripts/run_web_proxy.py --config conf/web_proxy.toml`  
3) ブラウザで `http://<listen_host>:<listen_port>/` を開き、URLを入力して「OPEN」するだけ。  
   - `?enc=1` もしくはクッキー `akari_enc=1` で暗号化フラグをオンにできる。

これだけ覚えておけば「ブラウザ→HTTP→UDP→HTTP→ブラウザ」の往復と、欠落時の再送の仕組みがざっくり追える。
