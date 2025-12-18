# AKARI Proxy プロトコル仕様 v3

本文は v3 を正とする。v3 は効率性と柔軟性の大幅な改善を目的として設計された。

---

## 1. システム概要

```
ブラウザ/WebView → ローカルHTTPプロキシ → (UDP AKARI-UDP v3) → リモートプロキシ → HTTP(S) オリジン
```

- 全リソースは `http://<local_proxy>/<元URL>` に書き換え
- ローカルでBrotli/gzip解凍、HTML/CSS/JS のURL書き換えを適用
- Flutter/Windows/Android/iOS に対応したクロスプラットフォーム設計

---

## 2. トランスポート

| 項目 | 値 |
|------|-----|
| プロトコル | UDP |
| MTU | 1200B（断片化回避） |
| パケット構成 | ヘッダ(12-18B) + Payload + HMAC/AEADタグ(16B)※ |
| タグ省略 | AGG_TAGモード時、最終パケットのみタグ付与 |

※暗号化モードまたは通常モードでは各パケットに16Bのタグ付与

---

## 3. メッセージ種別 (PacketType)

v3 ではレスポンスをヘッダとボディに分離し、再送を細粒度化。

| type | 名前 | 用途 |
|------|------|------|
| 0 | Req | HTTPリクエスト |
| 1 | RespHead | レスポンスヘッダ先頭（status, body_len, ヘッダブロック） |
| 2 | RespHeadCont | ヘッダ継続チャンク（大きなヘッダ用） |
| 3 | RespBody | レスポンスボディチャンク |
| 4 | NackHead | ヘッダパケット再送要求（ビットマップ） |
| 5 | NackBody | ボディパケット再送要求（ビットマップ） |
| 6 | Error | エラー通知 |

---

## 4. 共通ヘッダ (可変長, BE)

v3 ヘッダは効率のため動的サイズ。SHORT_ID フラグで message_id を 8B → 2B に削減可能。

### 4.1 基本構造

```
 0     1     2     3     4     5     6     7    ...
+-----+-----+-----+-----+-----+-----+-----+-----+
|  'A'   'K' | ver | type| flags| rsv | message_id (2B or 8B)
+-----+-----+-----+-----+-----+-----+-----------+
| seq (2B) | seq_total (2B) | payload_len (2B)  |
+----------+-----------+-----------------------+
```

### 4.2 フィールド詳細

| フィールド | サイズ | 説明 |
|-----------|--------|------|
| Magic | 2B | `"AK"` 固定 |
| ver | 1B | `0x03` (v3) |
| type | 1B | PacketType (0-6) |
| flags | 1B | 動作制御フラグ |
| reserved | 1B | 将来用 |
| message_id | 2B or 8B | SHORT_ID=1 で 2B |
| seq | 2B | パケット番号（Req時はtimestamp下位16bit転用） |
| seq_total | 2B | 総パケット数（RespHead時はbodyのseq_total） |
| payload_len | 2B | ペイロード長 |

### 4.3 フラグ定義

| bit | 名前 | 説明 |
|-----|------|------|
| 0x80 | E (ENCRYPT) | AEADモード有効 |
| 0x40 | A (AGG_TAG) | 集約タグモード（最終パケットのみタグ） |
| 0x20 | S (SHORT_ID) | message_id 16bit モード |
| 0x10 | L (SHORT_LEN) | body_len/hdr_len 24bit モード |

---

## 5. Payload 定義

### 5.1 Request (type=0)

```
+--------+----------+----------+------------------+----------------+
| method | url_len  | hdr_len  | url (UTF-8)      | header_block   |
| (1B)   | (2B)     | (2B)     | (url_len bytes)  | (hdr_len bytes)|
+--------+----------+----------+------------------+----------------+
```

- method: 0=GET, 1=HEAD, 2=POST
- seq/seq_total: timestamp の上位/下位16bit を転用

### 5.2 RespHead (type=1)

```
+-------------+-----------+----------+----------+----------------+
| status_code | body_len  |hdr_chunks| hdr_idx  | header_block   |
| (2B)        | (3B/4B)   | (1B)     | (1B)     | (可変)         |
+-------------+-----------+----------+----------+----------------+
```

- body_len: SHORT_LEN=1 で 3B (24bit)、=0 で 4B
- hdr_chunks: ヘッダ分割総数
- hdr_idx: このパケットのヘッダインデックス (0始まり)
- seq_total: ボディ側の総パケット数

### 5.3 RespHeadCont (type=2)

```
+----------+----------+----------------+
|hdr_chunks| hdr_idx  | header_block   |
| (1B)     | (1B)     | (可変)         |
+----------+----------+----------------+
```

大きなレスポンスヘッダの継続チャンク。

### 5.4 RespBody (type=3)

```
+--------------------+---------------+
| body_chunk         | [agg_tag]     |
| (payload_len bytes)| (16B, 最終のみ)|
+--------------------+---------------+
```

- AGG_TAG モードで最終パケット (seq == seq_total-1) のみ agg_tag を付与
- agg_tag なしの中間パケットはタグ検証をスキップ（受信完了後に一括検証）

### 5.5 NackHead / NackBody (type=4, 5)

```
+------------+---------------+
| bitmap_len | bitmap        |
| (1B)       | (bitmap_len B)|
+------------+---------------+
```

- bitmap: seq/hdr_idx 基準で bit=1 が欠落を示す

### 5.6 Error (type=6)

```
+------------+-------------+---------------------+
| error_code | http_status | message (UTF-8)     |
| (1B)       | (2B)        | (残り全部)          |
+------------+-------------+---------------------+
```

---

## 6. HTTPヘッダ圧縮

ヘッダブロックは静的テーブルによる名前ID圧縮を使用。

### 6.1 静的名テーブル (1B ID)

| ID | ヘッダ名 |
|----|----------|
| 1 | content-type |
| 2 | content-length |
| 3 | cache-control |
| 4 | etag |
| 5 | last-modified |
| 6 | date |
| 7 | server |
| 8 | content-encoding |
| 9 | accept-ranges |
| 10 | set-cookie |
| 11 | location |

### 6.2 エンコード形式

```
既知ヘッダ (ID != 0):  [id:1B][val_len:varint16][value]
未知ヘッダ (ID == 0):  [0:1B][name_len:1B][name][val_len:varint16][value]
```

---

## 7. 暗号化 / 認証

### 7.1 AEAD モード (E=1)

- アルゴリズム: XChaCha20-Poly1305
- 鍵: 256bit PSK (非32Bの場合 SHA-256 でハッシュ)
- Nonce 構成: `message_id(8B) | seq(2B) | flags[1:0](1B) | 0-padding(13B)`
- AAD: ヘッダ全体

### 7.2 HMAC モード (E=0, AGG_TAG=0)

- HMAC-SHA256 先頭16B
- 対象: ヘッダ + ペイロード

### 7.3 Aggregate Tag モード (E=0, AGG_TAG=1)

- ボディパケット: 中間パケットはタグなし
- 最終パケットのみ集約タグを付与
- オーバーヘッド削減: (パケット数-1) × 16B 節約

---

## 8. 信頼性と輻輳制御

- 送信ウィンドウ: 4〜8パケット
- 再送トリガ: RTT×2 経過で未ACK
- NACK ベース: ビットマップで欠落を通知
- ヘッダ/ボディ独立再送: NackHead / NackBody で細粒度制御
- 204/304/HEAD: ボディなし、RespHead のみで完了

---

## 9. ブラウザ/WebView 統合

### 9.1 URL 書き換え

- 全 URL を `http://<listen_host>:<listen_port>/<元URL>` に書き換え
- HTML: `href`, `src`, `action`, `poster` 等の属性
- CSS: `url()` 関数内
- JavaScript: `fetch`, `XMLHttpRequest` をインターセプト

### 9.2 レスポンス処理

- Content-Encoding (br/gzip) を解凍
- CSP, X-Frame-Options 等のセキュリティヘッダを除去
- Content-Type に応じたフィルタリング（JS/CSS/画像/その他）

### 9.3 Service Worker

JavaScript 環境での完全な fetch インターセプトを提供。

---

## 10. 実装ステータス

### 10.1 Rust Core (`akari_udp_core`)

| 機能 | 状態 |
|------|------|
| v3 ヘッダ encode/decode | ✅ 完了 |
| 全 PacketType 対応 | ✅ 完了 |
| AGG_TAG モード | ✅ 完了 |
| SHORT_ID / SHORT_LEN | ✅ 完了 |
| XChaCha20-Poly1305 AEAD | ✅ 完了 |
| HMAC 認証 | ✅ 完了 |
| AkariClient (高レベル API) | ✅ 完了 |

### 10.2 Flutter アプリ (`akari_flutter`)

| 機能 | 状態 |
|------|------|
| Rust FFI バインディング | ✅ 完了 |
| ローカル HTTP プロキシ | ✅ 完了 |
| WebView 統合 | ✅ 完了 |
| URL バー / ナビゲーション | ✅ 完了 |
| 設定 UI (暗号化/PSK/フィルタ) | ✅ 完了 |
| Windows ビルド | ✅ 完了 |
| Android / iOS | 🔄 準備中 |

### 10.3 Python プロキシ

| 機能 | 状態 |
|------|------|
| リモートプロキシ (v3) | ✅ 完了 |
| ローカルプロキシ (v3) | ✅ 完了 |
| Brotli 保持転送 | ✅ 完了 |

---

## 11. v2 からの主な変更点

| v2 | v3 |
|----|----|
| 固定24Bヘッダ | 可変長ヘッダ (12-18B) |
| resp/ack/nack 統合 | RespHead/RespBody/NackHead/NackBody 分離 |
| 全パケットタグ必須 | AGG_TAG で最終パケットのみ |
| message_id 8B 固定 | SHORT_ID で 2B 可能 |
| body_len 4B 固定 | SHORT_LEN で 3B 可能 |

---

## 12. 設定オプション

### 12.1 リモートプロキシ

```toml
# conf/remote.toml
[security]
require_encryption = true  # E=0 リクエストを拒否
allowed_psks = ["..."]     # 許可する PSK リスト
```

### 12.2 Flutter アプリ UI

- **暗号化トグル**: E フラグの有効/無効
- **PSK 入力**: 共有秘密鍵の設定
- **コンテンツフィルタ**: JS/CSS/画像/その他のオン/オフ

---

## 13. 今後の TODO

- [ ] Android/iOS ビルドの完成
- [ ] CSS 内 `url()` の完全対応
- [ ] JS 動的生成 URL の書き換え強化
- [ ] ロス率 10-20% 環境でのテスト
- [ ] PSK ローテーション機能
