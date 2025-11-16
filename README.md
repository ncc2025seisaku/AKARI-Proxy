# AKARI Proxy 要件定義書（v1.6）

---

## 1. プロジェクト概要

### 1.1 システム名

AKARI Proxy（AKARI-UDP Web Relay System）

### 1.2 背景

混雑回線・災害時など、TCP ベースの通常 Web 通信が不安定な環境でも
最低限の Web 情報取得を可能にすることを目的とし、
ローカルデバイスと外部プロキシ間を **UDP ベースの独自プロトコル（AKARI-UDP）** によって接続する。

### 1.3 目的

* ローカル端末上に HTTP プロキシ（ローカルプロキシ）を立て、ブラウザからの HTTP リクエストを受ける。
* ローカルプロキシから外部プロキシへ、独自 UDP プロトコルでリクエストを転送する。
* 外部プロキシが HTTP/HTTPS クライアントとして Web サイトから HTML/CSS/JS/画像等を取得し、UDP でローカルへ返却する。
* JS/CSS/画像の取得有無をローカル側設定で制御することで、通信量を削減し軽量な閲覧を可能にする。
* 将来的に、iOS / Android アプリからも同一プロトコルを利用できるよう、**独自プロトコル部分は Rust ライブラリとして実装**し、Python およびモバイルから共通利用可能な構成にする。

---

## 2. システム構成

### 2.1 全体構成

```text
ブラウザ
   ↓ HTTP
ローカルプロキシ（Pythonアプリ）
   ↓ UDP（AKARI-UDP Protocol v1, Rustライブラリ経由）
外部プロキシ（Pythonアプリ）
   ↓ HTTP/HTTPS
Webサイト
```

### 2.2 ローカルプロキシの役割

* HTTP リクエストの受付（ブラウザ → ローカル）
* URL の解析およびモード別ルーティング
* コンテンツ種別（HTML/JS/CSS/IMG）フィルタリング
* Rust 実装の AKARI-UDP ライブラリを利用した UDP パケット生成・送信
* レスポンスチャンクの受信・復元・HTTP レスポンス生成

### 2.3 外部プロキシの役割

* AKARI-UDP パケットの受信・検証（Rust ライブラリ）
* HTTP/HTTPS クライアントとして Web サーバにアクセス
* HTML/CSS/JS/画像などのレスポンス取得
* レスポンスボディのチャンク分割および AKARI-UDP パケット生成・送信

---

## 3. 動作モード

### 3.1 リバースプロキシモード

* ブラウザのプロキシ設定に `localhost:<port>` を指定し、通常のブラウジングと同様に利用するモード。
* Host ヘッダ等からターゲット URL を構築し、外部プロキシへ転送。

### 3.2 Web プロキシモード

* `http://localhost:<port>/` にアクセスすると、URL/検索ワードを入力可能なインデックス画面を表示。
* 入力された URL または検索ワードを元に、ターゲット URL を生成して外部プロキシへ転送。

---

## 4. HTTPS の扱い

### 4.1 ローカルプロキシ

* TLS/HTTPS の終端・復号は一切行わない。
* URL が `https://` であっても、文字列としてそのまま外部プロキシに転送する。

### 4.2 外部プロキシ

* HTTP/HTTPS クライアントとして動作し、`http://` および `https://` の両方に対応する。
* TLS 終端は外部プロキシ側で行い、取得したコンテンツ（HTML/CSS/JS/画像等）を AKARI-UDP メッセージとしてローカルに返却する。

### 4.3 方針の明文化

> 本バージョン（AKARI-UDP Protocol v1）では、TLS/HTTPS の終端は外部プロキシのみが行う。
> ローカルプロキシは HTTP のみを処理し、TLS/HTTPS を直接扱わない。

---

## 5. セキュリティ要件

### 5.1 改ざん防止（HMAC）

* HMAC-SHA256 の先頭 16 byte を認証タグとして使用。
* 対象範囲: ヘッダ（24 byte）＋ ペイロード全体。
* 鍵: 128bit 以上の事前共有鍵（Pre-Shared Key, PSK）。ローカル・外部双方で同一値を設定。

### 5.2 リプレイ対策（timestamp / nonce）

* ヘッダに u32 Unix Time（秒）を格納。
* 受信時に「現在時刻 ± 30 秒」などの許容範囲チェックを行う。
* `{message_id, timestamp}` の組を一定時間キャッシュし、同一組の再受信はリプレイとして破棄可能な構造とする（実装の詳細は設計段階で検討）。

### 5.3 その他

* magic `"AK"` によるプロトコル識別によって、異なるプロトコルからのパケットを排除する。
* HMAC 検証に失敗したパケットは、即座に破棄する。
* 不正 URL / スキームなどは error レスポンスとしてハンドリングする。

---

## 6. 非機能要件

### 6.1 性能

* 通常の HTML ページ取得で 1〜3 秒程度のレスポンスを目標とする。
* HTML のみモードでは、通常閲覧時と比べて通信量を 30〜70% 削減することを目標とする。

### 6.2 信頼性（ロス時挙動）

* AKARI-UDP v1 はプロトコルレベルで再送制御を行わない。
* 同一 `message_id` について、ヘッダの `seq_total` 分のチャンクが規定時間内（例: 2 秒）に揃わない場合、当該リクエストは失敗扱いとする。
* ローカルプロキシはブラウザに対して **504 Gateway Timeout** を返す。

### 6.3 運用性

* 設定ファイル（例: `config.toml`）により、以下を変更可能とする:

  * 動作モード（reverse / web）
  * ローカルプロキシ/外部プロキシのポート番号
  * 外部プロキシのアドレス
  * JS/CSS/画像のフィルタ設定
  * HMAC 用の事前共有鍵

### 6.4 拡張性

* UDP プロトコル部分を Rust ライブラリとして分離することで、将来的に iOS/Android アプリケーションからも直接利用可能な構造とする。
* 再送機構、圧縮、キャッシュ機構などは v2 以降で追加可能な設計とする。

---

## 7. コンテンツフィルタリング要件

ローカルプロキシ側で、コンテンツ種別ごとの制御を行う。

### 7.1 設定例

```toml
[content_filter]
enable_js  = false
enable_css = true
enable_img = false
```

### 7.2 挙動

* HTML 本体は常に許可。
* JS/CSS/IMG が無効 (`false`) の場合：

  * 該当拡張子（`.js`, `.css`, `.png`, `.jpg`, `.webp` 等）のリクエストに対して **HTTP 204 No Content** を返却し、UDP 送信は行わない。
* 許可されるリクエストのみ AKARI-UDP による送信対象とする。

---

## 8. AKARI-UDP Protocol v1 仕様

### 8.1 概要

* トランスポート: UDP
* 共通ヘッダ: 24 byte 固定
* ペイロード: 可変長（`payload_len` byte）
* 認証タグ: 末尾 16 byte の HMAC
* マルチバイト整数: 全て Big Endian（ネットワークバイトオーダー）

### 8.2 メッセージ種別（type）

* `0`: req（リクエスト）
* `1`: resp（レスポンス）
* `2`: error（エラー）

---

### 8.3 パケット全体構造

```text
+------------------------------+
| Header (24 byte)             |
+------------------------------+
| Payload (payload_len byte)   |
+------------------------------+
| HMAC (16 byte)               |
+------------------------------+
```

---

### 8.4 Header（24 byte）詳細

#### 8.4.1 フィールド一覧

| Offset | Size | Field       | 説明                            |
| ------ | ---- | ----------- | ----------------------------- |
| 0–1    | 2    | magic       | ASCII `"AK"` 固定               |
| 2      | 1    | version     | プロトコルバージョン（`0x01`）            |
| 3      | 1    | type        | メッセージ種別（0=req,1=resp,2=error） |
| 4      | 1    | flags       | 将来用フラグ（v1では 0 固定）             |
| 5      | 1    | reserved    | 予約（0 固定）                      |
| 6–13   | 8    | message_id  | u64（リクエスト識別子）                 |
| 14–15  | 2    | seq         | チャンク番号（u16, 0 起算）             |
| 16–17  | 2    | seq_total   | チャンク総数（u16）                   |
| 18–19  | 2    | payload_len | ペイロード長（byte 数, u16）           |
| 20–23  | 4    | timestamp   | Unix Time（秒, u32）             |

#### 8.4.2 32bit単位 ASCII 図（省略せず正式）

* Word0 (byte 0–3)

  ```text
  +------+------+------+------+ 
  | 'A'  | 'K'  |ver01 | type |
  +------+------+------+------+ 
  ```

* Word1 (byte 4–7)

  ```text
  +------+------+------+------+ 
  |flags |resv  |msgID7|msgID6|
  +------+------+------+------+ 
  ```

* Word2 (byte 8–11)

  ```text
  +------+------+------+------+ 
  |msgID5|msgID4|msgID3|msgID2|
  +------+------+------+------+ 
  ```

* Word3 (byte 12–15)

  ```text
  +------+------+------+------+ 
  |msgID1|msgID0|seq_H |seq_L |
  +------+------+------+------+ 
  ```

* Word4 (byte 16–19)

  ```text
  +------+------+------+------+ 
  |totlH |totlL |plenH |plenL |
  +------+------+------+------+ 
  ```

* Word5 (byte 20–23)

  ```text
  +------+------+------+------+ 
  |time3 |time2 |time1 |time0 |
  +------+------+------+------+ 
  ```

---

### 8.5 HMAC フィールド

* 位置: パケット末尾 16 byte
* アルゴリズム: HMAC-SHA256
* 計算対象: `Header (24 byte) + Payload (payload_len byte)`
* 認証タグ: HMAC-SHA256 の結果（32 byte）のうち先頭 16 byte

---

### 8.6 type=0: Request Payload（ローカル → 外部）

| Offset | Size    | Field     |                  |
| ------ | ------- | --------- | ---------------- |
| 0      | 1       | method    | 0 = GET（v1 固定）   |
| 1–2    | 2       | url_len   | URL のバイト長（u16）   |
| 3      | 1       | reserved  | 0 固定             |
| 4〜     | url_len | url_bytes | UTF-8 URL（クエリ含む） |

* 例: `https://example.com/search?q=akari&lang=ja`

---

### 8.7 type=1: Response Payload（外部 → ローカル）

#### 8.7.1 先頭チャンク（seq=0）

| Offset | Size | Field        |                 |
| ------ | ---- | ------------ | --------------- |
| 0–1    | 2    | status_code  |                 |
| 2–3    | 2    | reserved     |                 |
| 4–7    | 4    | body_len     | 全チャンク合計の body 長 |
| 8〜     | 可変   | body_chunk_0 |                 |

#### 8.7.2 後続チャンク（seq>=1）

| Offset | Size | Field      |
| ------ | ---- | ---------- |
| 0〜     | 可変   | body_chunk |

ローカルプロキシは同一 `message_id` について `seq=0..seq_total-1` を body_chunk 連結し、
`body_len` と一致するか確認後にブラウザへ返却する。

---

### 8.8 type=2: Error Payload

| Offset | Size    | Field            |
| ------ | ------- | ---------------- |
| 0      | 1       | error_code       |
| 1      | 1       | reserved         |
| 2–3    | 2       | http_status      |
| 4–5    | 2       | msg_len          |
| 6–7    | 2       | reserved2        |
| 8〜     | msg_len | msg_bytes（UTF-8） |

ローカルプロキシは内容に応じて 500 / 502 / 504 等をブラウザへ返却する。

---

### 8.9 ロス時挙動（明文化）

> AKARI-UDP Protocol v1 は再送制御を実装しない。
> 同一 message_id について seq_total 分のチャンクがタイムアウトまでに揃わない場合、ローカルプロキシは当該リクエストを失敗とみなし、ブラウザへ 504 Gateway Timeout を返す。

---

## 9. 技術スタック / 言語選定

### 9.1 実装言語

* ローカルプロキシ:

  * **Python 3.11**
* 外部プロキシ:

  * **Python 3.11**
* AKARI-UDP プロトコル（パケット生成・解釈）:

  * **Rust** でライブラリ実装

### 9.2 Rust ライブラリの役割

* ライブラリ名（例）: `akari_udp_core`
* 責務:

  * Header / Payload / HMAC のエンコード・デコード
  * チャンク分割・結合
  * HMAC 検証
* 提供インタフェース:

  * C-ABI もしくは pyo3 による Python バインディング
  * iOS / Android からも呼び出し可能な形（Swift/Kotlin との連携を想定）

### 9.3 Python 側からの利用方針

* Python 側には薄いラッパーモジュール（例: `akari_udp`）を実装し、

  * `encode_request(url, ...) -> bytes`
  * `decode_packet(datagram: bytes) -> ParsedPacket`
    などの高レベル API として Rust コアを呼び出す。
* ネットワークソケット処理（UDP送受信・HTTPサーバ）は Python 側で実装し、
  プロトコル処理のみ Rust に委譲する。

### 9.4 将来のモバイル展開

* iOS:

  * Rust ライブラリを static/dynamic library としてビルドし、Swift から呼び出し。
* Android:

  * Rust ライブラリを JNI 経由で Kotlin/Java から呼び出し。
* ローカルプロキシ相当の処理をアプリ内に実装することで、
  モバイルアプリ単体で AKARI-UDP を利用可能とする。

---

## 10. 開発フェーズ

1. AKARI-UDP Rust コアライブラリ実装（ヘッダ/HMAC/チャンク）
2. Python バインディング作成（`akari_udp`）
3. 外部プロキシ（Python + Rustコア）実装・HTTP/HTTPS動作確認
4. ローカルプロキシ（Python + Rustコア）実装・フィルタ機能実装
5. Windows 上のブラウザからの動作確認
6. （将来）iOS/Android への Rust コア組込み
