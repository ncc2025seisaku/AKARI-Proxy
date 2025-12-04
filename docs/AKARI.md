# AKARI Proxy プロトコル仕様 v2（v1互換付き）

本文は v2 を正とし、v1 は巻末の互換節に縮約する。

---

## 1. システム概要
ブラウザ → ローカルWebプロキシ → (UDP AKARI-UDP v2) → リモートプロキシ → HTTP(S) オリジン。  
全リソースは Service Worker で `http://<local_proxy>/https://...` に強制迂回。ネット経路は圧縮を保持し、ローカルで解凍・書き換え。

---

## 2. トランスポート
- UDP, MTU 1200B 前提（断片化回避）。  
- 1パケット = 24B固定ヘッダ + Payload + HMAC/AEADタグ16B。  
- タイムスタンプは秒精度（u32）。

---

## 3. メッセージ種別
| type | 意味 |
| --- | --- |
| 0 | req |
| 1 | resp |
| 2 | ack (first-lost) |
| 3 | nack (bitmap) |
| 4 | error |

---

## 4. 共通ヘッダ（24B, BE）
```
0                7 8               15 16              23
+----------------+-----------------+------------------+
| 'A''K' |ver|type|flags|rsv| message_id (8B)        |
+----------------+-----------------+------------------+
| message_id cont.| seq (u16) | seq_total (u16)      |
+-----------------------------------------------------+
| payload_len(u16)| timestamp(u32)                    |
+-----------------+-----------------------------------+
```
- ver: 0x02 (v2) / 0x01 (v1)
- flags(v2): `E`暗号, `H`ヘッダ圧縮ブロック, `C`本文圧縮, `F`終端
- tag: AEADタグ16B（E=1）または HMAC-SHA256 先頭16B（E=0）

---

## 5. Payload 定義（v2）
### 5.1 Request (type=0)
| ofs | size | field |
| --- | --- | --- |
|0|1|method (0=GET,1=HEAD,2=POST小)|
|1-2|2|url_len|
|3-4|2|opt_hdr_len|
|5-|url_bytes UTF-8|
|…|opt_headers (静的ID圧縮ブロック)|

### 5.2 Response (type=1)
- seq=0: `status(2) | hdr_block_len(2) | body_len(4) | hdr_block | body_chunk0`
- seq>=1: `body_chunk`
- `F=1` または `body_len` 到達で完了。

### 5.3 ACK (type=2)
`first_lost_seq(u16)` （全受信なら 0xFFFF）

### 5.4 NACK (type=3)
`bitmap_len(1) | bitmap...`（seq0基準 bit=1 が欠落）

### 5.5 Error (type=4)
`error_code(1) | http_status(2) | msg_len(2) | msg`

---

## 6. HTTPヘッダ圧縮（H=1）
静的名テーブル (1B ID):
`1:content-type, 2:content-length, 3:cache-control, 4:etag, 5:last-modified, 6:date, 7:server, 8:content-encoding, 9:accept-ranges, 10:set-cookie, 11:location`  
エンコード:
```
ID!=0: [id][val_len(varint16)][value]
ID==0: 0 [name_len(1)][name][val_len(varint16)][value]
```
ブラウザ返送時に展開、Content-Encodingはローカルで解凍後に除去する。

---

## 7. 圧縮/暗号
- C=1: 本文のみ zstd Lv1（既定オフ、Brotli二重圧縮を避けるため環境で選択）。  
- E=1: XChaCha20-Poly1305 (nonce = message_id(8)+seq(2)+flags下位2bit), 256bit PSK。

---

## 8. 輻輳と再送
- 送信ウィンドウ 4–8pkt。RTT×2 未ACKで再送、連続LOSSで半減(>=1)。  
- first-lost ACK で最初の欠落を通知／NACK でビットマップ通知。  
- 204/304/HEAD は seq=0 のみ + F=1 で終了。

---

## 9. ブラウザ統合
- Service Worker が全 fetch を `http://<listen_host>:<listen_port>/<元URL>` に書き換え、外部直アクセスを防止。  
- レスポンスはローカルで Content-Encoding を解凍し、CSP/TE を除去後、HTML内の絶対URLをプロキシ経由に再書き換え。

---

## 10. v1 互換（簡約）
- ver=0x01, type: req/resp/error のみ。ACK/NACKなし。  
- req payload: method=0 GET 固定, `url_len`/`reserved`/`url`。  
- resp seq=0: `status(2)|reserved(2)|body_len(4)|chunk0`、seq>=1: chunk。  
- ヘッダ圧縮・フラグなし。  
- 同ポート運用時は magic+ver 判定で振り分け、HMAC失敗で破棄。

---

## 11. 実装ステータス
- Rust core: v2 ヘッダ/ACK/NACK/ヘッダ圧縮/HMAC 実装済。AEAD/圧縮フラグは未配線。  
- Python binding: v1/v2 エンコード・デコード API 追加済。  
- Web proxy: SW 強制ルーティング・圧縮解凍・CSP除去・Content-Type ベースのフィルタ適用。  
- Remote proxy: v2 resp 送信（ヘッダブロック搭載）、Brotli圧縮を保持。

---

## 12. 今後のTODO
- AEAD (E) の実配線と鍵更新フレーム。  
- C フラグの実用条件（非Brotli時のみ）を自動判定。  
- CSS 内 url() / JS 動的生成までの書き換え強化。  
- テスト: MTU境界、ロス10–20%、Brotli + filter ON/OFF、v1/v2混在。

- `conf/remote.toml` の `require_encryption = true` で E フラグ無しリクエストを拒否できる。UI トグルから E を送信可能。
