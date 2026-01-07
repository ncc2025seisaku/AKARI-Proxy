# AKARI Proxy アーキテクチャ設計図

本ドキュメントは、AKARI Proxy プロジェクトの実装向け設計図（アーキテクチャ概要＋API概要）を示す。

- 要件・プロトコル仕様の詳細: `docs/AKARI.md`（v3仕様）
- 本書: ディレクトリ構成、コンポーネント構成、Rust/Dart/Python API 概要

---

## 1. リポジトリ構成

モノレポ構成とし、Rust コア実装、Flutter クライアント、Python リモートプロキシを1つのリポジトリで管理する。

```text
akari-proxy/
├─ README.md
├─ CHANGELOG.md
├─ docs/
│   ├─ AKARI.md                   # プロトコル仕様 v3
│   └─ architecture.md            # 本ファイル
├─ conf/
│   ├─ web_proxy.toml             # ローカルプロキシ用設定
│   └─ remote.toml                # リモートプロキシ用設定
├─ crates/
│   ├─ akari_udp_core/            # Rust コアライブラリ（v3 プロトコル実装）
│   │   ├─ Cargo.toml
│   │   └─ src/
│   │       ├─ lib.rs
│   │       ├─ types.rs           # PacketType, Header, Payload 型定義
│   │       ├─ encode.rs          # v3 エンコード
│   │       ├─ decode.rs          # v3 デコード
│   │       ├─ crypto.rs          # XChaCha20-Poly1305, HMAC
│   │       ├─ client.rs          # AkariClient 高レベル API
│   │       └─ error.rs
│   └─ akari_udp_py/              # pyo3 バインディング（リモートプロキシ用）
│       ├─ Cargo.toml
│       └─ src/lib.rs
├─ akari_flutter/                 # Flutter クライアントアプリ
│   ├─ lib/
│   │   ├─ main.dart              # エントリーポイント
│   │   └─ src/
│   │       ├─ rust/              # flutter_rust_bridge 生成コード
│   │       ├─ server/            # ローカルHTTPプロキシ（Dart）
│   │       │   ├─ local_server.dart
│   │       │   └─ rewriter.dart  # URL書き換え
│   │       └─ services/          # 設定・サービス
│   ├─ rust/                      # Rust FFI ソース
│   │   └─ src/
│   │       ├─ lib.rs
│   │       └─ api/               # flutter_rust_bridge API
│   ├─ android/
│   ├─ ios/
│   └─ windows/
├─ py/
│   └─ akari/
│       ├─ __init__.py
│       ├─ udp_codec.py           # Rust バインディングの薄ラッパ
│       ├─ remote_proxy/          # リモートプロキシ
│       │   ├─ handler.py
│       │   └─ http_client.py
│       └─ web_proxy/             # Python ローカルプロキシ（開発用）
├─ scripts/
│   ├─ run_remote_proxy.py        # リモートプロキシ起動
│   └─ run_web_proxy.py           # 開発用ローカルプロキシ起動
└─ tests/
```

---

## 2. コンポーネント構成

### 2.1 全体構成

```text
ブラウザ/WebView
   ↓ HTTP
ローカルプロキシ（Flutter/Dart または Python）
   ↓ UDP（AKARI-UDP v3, Rust コア利用）
リモートプロキシ（Python 3.11）
   ↓ HTTP/HTTPS
Webサイト
```

### 2.2 Flutter クライアント（メインクライアント）

#### 役割

* WebView でウェブサイトを表示
* Dart でローカル HTTP プロキシを実装
* Rust FFI (flutter_rust_bridge) でv3パケット処理を実行
* URL書き換え（HTML/CSS/JS）をDart側で処理

#### 主なモジュール

* `lib/main.dart`
  * アプリエントリーポイント
  * WebView + URL バー + 設定UIの統合
  
* `lib/src/server/local_server.dart`
  * Dart による HTTP プロキシサーバ
  * リクエスト受信 → Rust FFI → UDP 送受信 → レスポンス返却
  
* `lib/src/server/rewriter.dart`
  * HTML/CSS/JS の URL 書き換え処理
  * Brotli/gzip の解凍

* `rust/src/api/`
  * flutter_rust_bridge で公開する API
  * `AkariClient` の Dart バインディング

### 2.3 リモートプロキシ（Python）

#### 役割

* ローカルプロキシからの AKARI-UDP v3 リクエスト受信
* Rust コア (pyo3) を用いたパケット解釈
* HTTP/HTTPS クライアントとして外部 Web サーバへアクセス
* レスポンスを RespHead + RespBody に分割して返送

#### 主なモジュール

* `py/akari/remote_proxy/handler.py`
  * v3 パケットの処理
  * HTTP 取得 → RespHead/RespBody 生成
  
* `py/akari/remote_proxy/http_client.py`
  * 実際の HTTP/HTTPS リクエスト処理

### 2.4 Rust コアライブラリ（`crates/akari_udp_core`）

#### 役割

* AKARI-UDP v3 プロトコル仕様に基づく
  * 可変長ヘッダのエンコード／デコード
  * 6種類の PacketType 対応（Req, RespHead, RespHeadCont, RespBody, NackHead, NackBody, Error）
  * XChaCha20-Poly1305 AEAD 暗号化
  * HMAC-SHA256 認証
  * AGG_TAG モード（集約タグ）
* `AkariClient` 高レベル API で UDP 送受信を抽象化
* Flutter から flutter_rust_bridge 経由、Python から pyo3 経由で利用

---

## 3. データフロー概要

### 3.1 v3 プロトコルのフロー

#### 3.1.1 正常系（HTML取得）

1. WebView/ブラウザがローカルプロキシに HTTP GET を送信
2. ローカルプロキシ（Dart/Python）で受信
3. Rust `AkariClient.send_request()` で v3 Req パケットを生成・送信
4. リモートプロキシが Req を受信・デコード
5. `http_client.fetch(url)` で Web サーバにアクセス
6. レスポンスを以下に分割:
   * **RespHead** (type=1): status_code, body_len, HTTP ヘッダ
   * **RespBody** (type=3): ボディチャンク（複数パケット）
7. ローカルプロキシが RespHead + 全 RespBody を受信・結合
8. Brotli/gzip 解凍、URL 書き換えを適用
9. HTTP レスポンスとしてブラウザへ返却

#### 3.1.2 エラー系

* HTTP 取得失敗: Error パケット (type=6) を返送
* パケット欠落: NackHead/NackBody で再送要求

---

## 4. Rust コア API 設計 (v3)

### 4.1 型定義概要

```rust
pub enum PacketType {
    Req = 0,
    RespHead = 1,
    RespHeadCont = 2,
    RespBody = 3,
    NackHead = 4,
    NackBody = 5,
    Error = 6,
}

pub struct Header {
    pub magic: [u8; 2],        // "AK"
    pub version: u8,           // 0x03 (v3)
    pub packet_type: PacketType,
    pub flags: u8,             // E, A, S, L flags
    pub reserved: u8,
    pub message_id: u64,       // 8B or 2B (SHORT_ID)
    pub seq: u16,
    pub seq_total: u16,
    pub payload_len: u16,
}

pub struct RequestPayload {
    pub method: u8,            // 0=GET, 1=HEAD, 2=POST
    pub url: String,
    pub headers: Vec<(String, String)>,
}

pub struct RespHeadPayload {
    pub status_code: u16,
    pub body_len: u32,         // 3B or 4B (SHORT_LEN)
    pub hdr_chunks: u8,
    pub hdr_idx: u8,
    pub headers: Vec<(String, String)>,
}

pub struct RespBodyPayload {
    pub chunk: Vec<u8>,
    pub agg_tag: Option<[u8; 16]>,  // AGG_TAG モード時、最終のみ
}

pub struct ErrorPayload {
    pub error_code: u8,
    pub http_status: u16,
    pub message: String,
}
```

### 4.2 AkariClient 高レベル API

```rust
pub struct AkariClient {
    socket: UdpSocket,
    remote_addr: SocketAddr,
    psk: [u8; 32],
    encryption: bool,
}

impl AkariClient {
    pub fn new(remote_addr: SocketAddr, psk: &[u8], encryption: bool) -> Self;
    
    /// URL を取得し、完全なレスポンスを返す
    pub async fn fetch_url(&self, url: &str) -> Result<FetchResponse, AkariError>;
    
    /// リクエストパケットを送信
    pub fn send_request(&self, url: &str) -> Result<u64, AkariError>;
    
    /// レスポンスを受信・結合
    pub fn receive_response(&self, message_id: u64) -> Result<FetchResponse, AkariError>;
}

pub struct FetchResponse {
    pub status_code: u16,
    pub headers: Vec<(String, String)>,
    pub body: Vec<u8>,
}
```

---

## 5. Flutter (Dart) ローカルプロキシ設計

### 5.1 アーキテクチャ概要

```text
┌─────────────────────────────────────────────────────┐
│                   Flutter App                        │
├─────────────────────────────────────────────────────┤
│  WebView (InAppWebView)                              │
│    ↓ HTTP                                           │
│  LocalProxyServer (Dart HttpServer)                 │
│    ↓ FFI                                            │
│  AkariClient (Rust via flutter_rust_bridge)         │
│    ↓ UDP                                            │
└─────────────────────────────────────────────────────┘
```

### 5.2 主要クラス

#### LocalProxyServer

```dart
class LocalProxyServer {
  final int port;
  final AkariClient akariClient;
  HttpServer? _server;
  
  Future<void> start();
  Future<void> stop();
  
  Future<Response> _handleRequest(HttpRequest request);
}
```

#### Rewriter

```dart
class Rewriter {
  final String proxyBaseUrl;
  
  String rewriteHtml(String html, String baseUrl);
  String rewriteCss(String css, String baseUrl);
  String rewriteJs(String js);
}
```

---

## 6. リモートプロキシ設計（Python）

### 6.1 handler の流れ

```python
from akari_udp_py import decode_packet_py, encode_response_head, encode_response_body

def handle_v3_request(datagram: bytes, psk: bytes) -> list[bytes]:
    packet = decode_packet_py(datagram, psk)
    
    if packet["type"] != "req":
        return []
    
    url = packet["payload"]["url"]
    msg_id = packet["header"]["message_id"]
    
    try:
        resp = fetch(url)
    except Exception as e:
        return [encode_error(msg_id, str(e))]
    
    # RespHead + RespBody に分割して返す
    packets = []
    packets.append(encode_response_head(
        msg_id, resp.status_code, resp.headers, len(resp.body)
    ))
    for chunk in split_body(resp.body, MTU):
        packets.append(encode_response_body(msg_id, chunk))
    
    return packets
```

---

## 7. フラグとモード

### 7.1 フラグ定義

| bit | 名前 | 説明 |
|-----|------|------|
| 0x80 | E (ENCRYPT) | XChaCha20-Poly1305 AEAD 有効 |
| 0x40 | A (AGG_TAG) | 集約タグモード（最終パケットのみタグ） |
| 0x20 | S (SHORT_ID) | message_id 16bit モード |
| 0x10 | L (SHORT_LEN) | body_len/hdr_len 24bit モード |

### 7.2 Flutter UI での設定

* 暗号化トグル: E フラグの有効/無効
* PSK 入力: 共有秘密鍵の設定
* コンテンツフィルタ: JS/CSS/画像/その他

---

## 8. 実装ステータス

| コンポーネント | 状態 |
|----------------|------|
| Rust Core (v3) | ✅ 完了 |
| Flutter Windows | ✅ 完了 |
| Flutter Android | ✅ 完了 |
| Flutter iOS | ✅ 完了 |
| Python リモートプロキシ | ✅ 完了 |
| Python ローカルプロキシ（開発用） | ✅ 完了 |

---

## 9. 関連ドキュメント

* [AKARI.md](AKARI.md) - v3 プロトコル仕様
* [flutter_migration_plan.md](flutter_migration_plan.md) - Flutter 移行計画
* [README.md](../README.md) - プロジェクト概要
