# AKARI Proxy アーキテクチャ設計図

本ドキュメントは、AKARI Proxy プロジェクトの実装向け設計図（アーキテクチャ概要＋API概要）を示す。

- 要件・プロトコル仕様の詳細: `docs/AKARI.md`
- 本書: ディレクトリ構成、コンポーネント構成、Rust/Python API 概要

---

## 1. リポジトリ構成

モノレポ構成とし、Rust コア実装と Python アプリケーション（ローカルプロキシ / 外部プロキシ）を1つのリポジトリで管理する。

```text
akari-proxy/
├─ README.md
├─ docs/
│   ├─ spec_akari_udp_v1.md       # 要件定義 & プロトコル仕様
│   └─ architecture.md            # 本ファイル
├─ conf/
│   ├─ local.toml                 # ローカルプロキシ用設定
│   └─ remote.toml                # 外部プロキシ用設定
├─ crates/
│   ├─ akari_udp_core/            # Rust コアライブラリ（プロトコル実装）
│   │   ├─ Cargo.toml
│   │   └─ src/
│   │       ├─ lib.rs
│   │       ├─ header.rs
│   │       ├─ packet.rs
│   │       ├─ encode.rs
│   │       ├─ decode.rs
│   │       ├─ hmac.rs
│   │       └─ error.rs
│   └─ akari_udp_py/              # pyo3 バインディング
│       ├─ Cargo.toml
│       └─ src/
│           └─ lib.rs
├─ py/
│   └─ akari/
│       ├─ __init__.py
│       ├─ config.py              # TOML ロード & 設定モデル
│       ├─ udp_codec.py           # Rust バインディングの薄ラッパ
│       ├─ udp_client.py          # UDP 送信/受信（ローカル→外部）
│       ├─ udp_server.py          # UDP サーバ（外部側）
│       ├─ local_proxy/
│       │   ├─ __init__.py
│       │   ├─ http_server.py     # HTTP サーバ（ブラウザ用）
│       │   ├─ router.py          # モード分岐 & フィルタリング
│       │   └─ main.py            # ローカルプロキシエントリポイント
│       └─ remote_proxy/
│           ├─ __init__.py
│           ├─ handler.py         # UDP req → HTTP/HTTPS 取得ロジック
│           ├─ http_client.py     # 外向き HTTP/HTTPS クライアント
│           ├─ healthcheck.py     # 簡易ヘルスチェック（任意）
│           └─ main.py            # 外部プロキシエントリポイント
├─ scripts/
│   ├─ run_local.py               # ローカルプロキシ起動
│   └─ run_remote.py              # 外部プロキシ起動
└─ tests/
    ├─ test_udp_core_rs/          # Rust コアのテスト
    └─ test_udp_py/               # Python 統合テスト
```

---

## 2. コンポーネント構成

### 2.1 全体構成

```text
ブラウザ
   ↓ HTTP
ローカルプロキシ（Python 3.11）
   ↓ UDP（AKARI-UDP v1, Rustライブラリ利用）
外部プロキシ（Python 3.11）
   ↓ HTTP/HTTPS
Webサイト
```

### 2.2 ローカルプロキシ（Python）

#### 役割

* ブラウザからの HTTP リクエスト受付
* 動作モード（reverse/web）に応じたルーティング
* URL 構築（Host ヘッダや検索ワードからの生成）
* コンテンツ種別判定（HTML/JS/CSS/IMG）
* コンテンツフィルタ（JS/CSS/IMG 許可/拒否）
* AKARI-UDP リクエスト生成・送信（Rust コア利用）
* レスポンスチャンクの受信・再構成・HTTP レスポンス生成

#### 主なモジュール

* `local_proxy/main.py`

  * ローカルプロキシのエントリポイント
  * 設定ファイルの読込 (`conf/local.toml`)
  * HTTPサーバの起動
* `local_proxy/http_server.py`

  * ブラウザ向け HTTP サーバ
  * 各リクエストを `router` にディスパッチ
* `local_proxy/router.py`

  * モードに応じたルーティング
  * URL の解釈・生成（reverse_mode / web_mode）
  * コンテンツ種別判定＆フィルタリング
  * 許可されたリクエストを `udp_client` へ委譲
* `udp_client.py`

  * UDP ソケットクライアント
  * AKARI-UDP パケット送信
  * 指定 `message_id` のレスポンスチャンクを集約
  * チャンク欠落時のタイムアウト処理

---

### 2.3 外部プロキシ（Python）

#### 役割

* ローカルプロキシからの AKARI-UDP リクエスト受信
* Rust コアを用いたパケット解釈（復号・HMAC検証）
* HTTP/HTTPS クライアントとして外部 Web サーバへアクセス
* レスポンス body をチャンク分割し AKARI-UDP レスポンスとして返送
* 失敗時には error パケットを返送
* 稼働状態の確認用ヘルスチェック（任意）

#### 主なモジュール

* `remote_proxy/main.py`

  * 外部プロキシのエントリポイント
  * 設定ファイルの読込 (`conf/remote.toml`)
  * UDP サーバ起動（`udp_server` 利用）
* `udp_server.py`

  * UDP ポートを listen
  * パケット受信 → `udp_codec.decode_packet` → `remote_proxy.handler` 呼び出し
  * handler からのレスポンス（複数パケット）を送信
* `remote_proxy/handler.py`

  * `ParsedPacket`（type=req）を受け取り、HTTP/HTTPS 取得を行う
  * 正常時: body をチャンク分割し、AKARI-UDP resp パケット列を生成
  * エラー時: AKARI-UDP error パケットを生成
* `remote_proxy/http_client.py`

  * 実際の HTTP/HTTPS リクエスト処理
  * タイムアウト、リダイレクト上限、最大レスポンスサイズなどの制御
* `remote_proxy/healthcheck.py`（任意）

  * 外部プロキシが生きているか確認する簡易 HTTP/UDP エンドポイント

---

### 2.4 Rust コアライブラリ（`crates/akari_udp_core`）

#### 役割

* AKARI-UDP v1 プロトコル仕様に基づく

  * ヘッダのエンコード／デコード
  * ペイロード（req/resp/error）のエンコード／デコード
  * HMAC-SHA256 による認証タグ生成・検証
* プロトコルのすべてのバイナリ処理を Rust に閉じ込める
* Python から pyo3 経由で利用される
* 将来的に iOS/Android からも利用可能なコアとして再利用する

---

## 3. データフロー概要

### 3.1 ブラウザ → ローカルプロキシ → 外部プロキシ → Web → ローカル → ブラウザ

#### 3.1.1 正常系（HTML取得）

1. ブラウザがローカルプロキシに HTTP GET を送信。
2. `http_server.py` で受信し、`router.py` に委譲。
3. `router.py` が:

   * モードに応じてターゲット URL を決定。
   * コンテンツ種別（拡張子など）を判定。
   * 設定で禁止されている種別なら即 204 を返却。
4. 許可されたリクエストについて:

   * `message_id` と `timestamp` を発番。
   * `udp_codec.encode_request(url, message_id, timestamp)` で AKARI-UDP req を生成。
   * `udp_client.send(datagram)` で外部プロキシに送信。
5. 外部プロキシ `udp_server` が datagram を受信。
6. `udp_codec.decode_packet(datagram)` で解析・HMAC検証。
7. `remote_proxy/handler.py` が type=req を受け取り、`http_client.fetch(url)` を呼び出す。
8. `http_client.fetch(url)` が HTTP/HTTPS で Web サーバにアクセスし、レスポンス `status_code`, `body` を返す。
9. `handler` が body を MTU に合わせてチャンク分割し:

   * 先頭チャンク: `encode_response_first_chunk`
   * 後続チャンク: `encode_response_chunk`
     を呼んで複数 datagram を生成。
10. `udp_server` がこれらの datagram をローカルプロキシへ送信。
11. ローカル側 `udp_client` が:

    * 同一 `message_id` の resp パケットを集約。
    * `seq_total` 分揃ったら body を結合。
12. 完成した body を HTTP レスポンスとしてブラウザへ返却。

#### 3.1.2 エラー系（Web 取得失敗 / タイムアウト）

* `http_client.fetch(url)` でエラー：

  * `handler` が `encode_error(...)` を用いて AKARI-UDP error パケットを生成。
  * ローカルで受信後、HTTP 502 / 504 などに変換してブラウザへ返却。
* UDPレベルでチャンク欠落：

  * ローカル側がタイムアウト（例: 2秒）で諦め、504 を返却。

---

## 4. Rust コア API 設計

### 4.1 型定義概要

```rust
pub enum MessageType {
    Req,
    Resp,
    Error,
}

pub struct Header {
    pub magic: [u8; 2],      // "AK"
    pub version: u8,         // 0x01
    pub r#type: MessageType,
    pub flags: u8,
    pub message_id: u64,
    pub seq: u16,
    pub seq_total: u16,
    pub payload_len: u16,
    pub timestamp: u32,
}

pub struct RequestPayload {
    pub method: u8,          // v1: 0 = GET
    pub url: String,
}

pub struct ResponseHead {
    pub status_code: u16,
    pub body_len: u32,
}

pub struct ResponseChunk {
    pub chunk: Vec<u8>,
    pub is_first: bool,
    pub head: Option<ResponseHead>,
}

pub struct ErrorPayload {
    pub error_code: u8,
    pub http_status: u16,
    pub message: String,
}

pub enum Payload {
    Req(RequestPayload),
    Resp(ResponseChunk),
    Error(ErrorPayload),
}

pub struct ParsedPacket {
    pub header: Header,
    pub payload: Payload,
}
```

### 4.2 エンコード API

```rust
pub fn encode_request(
    url: &str,
    message_id: u64,
    timestamp: u32,
    psk: &[u8],
) -> Result<Vec<u8>, AkariError>;

pub fn encode_response_first_chunk(
    status_code: u16,
    body_len: u32,
    body_chunk: &[u8],
    message_id: u64,
    seq_total: u16,
    timestamp: u32,
    psk: &[u8],
) -> Result<Vec<u8>, AkariError>;

pub fn encode_response_chunk(
    body_chunk: &[u8],
    message_id: u64,
    seq: u16,
    seq_total: u16,
    timestamp: u32,
    psk: &[u8],
) -> Result<Vec<u8>, AkariError>;

pub fn encode_error(
    error_code: u8,
    http_status: u16,
    message: &str,
    message_id: u64,
    timestamp: u32,
    psk: &[u8],
) -> Result<Vec<u8>, AkariError>;
```

### 4.3 デコード API

```rust
pub fn decode_packet(datagram: &[u8], psk: &[u8]) -> Result<ParsedPacket, AkariError>;
```

---

## 5. Python ラッパ API 設計（`udp_codec.py`）

### 5.1 型定義イメージ

```python
from typing import Literal, TypedDict

PacketType = Literal["req", "resp", "error"]

class Header(TypedDict):
    version: int
    type: PacketType
    message_id: int
    seq: int
    seq_total: int
    payload_len: int
    timestamp: int

class RequestPayload(TypedDict):
    url: str

class ResponsePayload(TypedDict):
    status_code: int | None   # seq=0 のときのみ値あり
    body_len: int | None      # seq=0 のときのみ値あり
    chunk: bytes

class ErrorPayload(TypedDict):
    error_code: int
    http_status: int
    message: str

class ParsedPacket(TypedDict):
    header: Header
    type: PacketType
    payload: RequestPayload | ResponsePayload | ErrorPayload
```

### 5.2 公開関数

```python
def encode_request(url: str, message_id: int, timestamp: int) -> bytes: ...
def encode_response_first_chunk(
    status_code: int,
    body_len: int,
    body_chunk: bytes,
    message_id: int,
    seq_total: int,
    timestamp: int,
) -> bytes: ...
def encode_response_chunk(
    body_chunk: bytes,
    message_id: int,
    seq: int,
    seq_total: int,
    timestamp: int,
) -> bytes: ...
def encode_error(
    error_code: int,
    http_status: int,
    message: str,
    message_id: int,
    timestamp: int,
) -> bytes: ...
def decode_packet(datagram: bytes) -> ParsedPacket: ...
```

内部では pyo3 によって公開される Rust 側の関数を呼び出す。

---

## 6. 外部プロキシ固有の設計ポイント

### 6.1 HTTP/HTTPS クライアント (`remote_proxy/http_client.py`)

* 使用ライブラリ例: `httpx` or `requests`
* 機能:

  * GET のみ対応（v1）
  * タイムアウト（例: 5秒）
  * リダイレクト上限（例: 3回）
  * 最大レスポンスサイズ（安全性のための上限バイト数）
* インタフェース例:

```python
class HttpResponse(TypedDict):
    status_code: int
    headers: dict[str, str]
    body: bytes

def fetch(url: str) -> HttpResponse: ...
```

### 6.2 handler の流れ（`remote_proxy/handler.py`）

```python
from akari.udp_codec import ParsedPacket, encode_response_first_chunk, encode_response_chunk, encode_error
from .http_client import fetch

MTU_PAYLOAD_SIZE = 1180  # 例: AKARI-UDP の payload_len 上限

def make_response_chunks(body: bytes, status_code: int, message_id: int, timestamp: int) -> list[bytes]:
    total_len = len(body)
    # 何チャンクに分けるか計算
    # 先頭チャンク: payload にヘッダ(8byte) + chunk
    # 後続チャンク: chunkのみ
    # ここでは「簡易分割」のみ設計レベルで記述（実装詳細はコード側で）

    # ...（チャンク分割ロジック）...
    # return [datagram1, datagram2, ...]

def handle_request(packet: ParsedPacket) -> list[bytes]:
    assert packet["type"] == "req"
    url = packet["payload"]["url"]
    msg_id = packet["header"]["message_id"]

    try:
        resp = fetch(url)
    except TimeoutError:
        ts = now_ts()
        return [encode_error(
            error_code=2,
            http_status=504,
            message="timeout",
            message_id=msg_id,
            timestamp=ts,
        )]
    except Exception as e:
        ts = now_ts()
        return [encode_error(
            error_code=1,
            http_status=502,
            message=str(e)[:200],
            message_id=msg_id,
            timestamp=ts,
        )]

    ts = now_ts()
    return make_response_chunks(resp["body"], resp["status_code"], msg_id, ts)
```

### 6.3 UDP サーバ (`udp_server.py`)

責務:

* 外部プロキシ側で UDP ポートを listen
* パケットを受信し `udp_codec.decode_packet` でパース
* type=req に対して `remote_proxy.handler.handle_request` を呼び出し、返ってきた datagram 群を送信

インタフェースイメージ:

```python
def serve_udp_forever(bind_addr: str, bind_port: int) -> None:
    # ソケット生成
    # recvfrom → decode_packet → handler → sendto のループ
    ...
```

---

## 7. 実装順序メモ

1. `akari_udp_core`（Rust）でヘッダ＋ペイロードエンコード/デコード＋HMAC を実装
2. `akari_udp_py`（pyo3）で Python バインディング生成
3. `udp_codec.py` ラッパ実装
4. `remote_proxy/http_client.py` & `remote_proxy/handler.py` 実装
5. `udp_server.py` 実装 → 外部プロキシ単体テスト（UDP経由でHTTP取得）
6. `local_proxy`（HTTPサーバ＋router＋udp_client）実装
7. ブラウザからの end-to-end 動作確認
