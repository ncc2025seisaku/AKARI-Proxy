# Flutter + Rust ローカルプロキシ移行計画

## 目的
Python 版ローカルプロキシを Flutter (Dart) 実装に置き換え、Rust の **v3 パケット処理および通信ロジック** を `akari_udp_core` に統合する（v1/v2 ロジックは不要で廃止）。Windows / Android / iOS で単一コードベースを動かす。

## 移行戦略: 2段階アプローチ

リスクを最小化するため、以下の2段階で移行を進める：

```
Phase 1: Rust 通信ロジック統合 + Python 検証
────────────────────────────────────────────
・既存の Python プロキシ環境で動作検証
・通信ロジック（再送/NACK/タイムアウト）を Rust に移植
・akari_udp_py 経由で Python から呼び出し、品質担保
                    ↓ 動作確認OK
Phase 2: Flutter 移行
────────────────────────────────────────────
・検証済み Rust ロジックを flutter_rust_bridge で公開
・Dart は薄い FFI ラッパー + HTTP サーバ・書き換えのみ
・通信部分は Phase 1 で検証済みなので安心
```

---

## Phase 1: Rust 通信ロジック統合（Python 検証）

### 役割分担（Phase 1）
- **Rust**: v3 パケットのエンコード・デコード **+ 再送制御・NACK送信・タイムアウト管理・チャンク管理** を含む高レベル API を提供
- **Python**: 既存の `AkariUdpClient` を Rust 呼び出しに差し替え、HTTP サーバ・書き換えはそのまま

### マイルストン（Phase 1）
1. Rust `AkariClient` 構造体の設計・実装
   - `send_http_request(url, method, body, config) -> HttpResponse`
   - 再送制御（NACK-HEAD, NACK-BODY）
   - タイムアウト・リトライ管理
   - チャンク受信・組み立て（`ResponseAccumulator` 相当）
   - 集約タグ検証
2. PyO3 バインディング更新（`akari_udp_py`）
   - `AkariClient` クラスを Python に公開
   - `RequestConfig` / `HttpResponse` / `TransferStats` を公開
3. Python `AkariUdpClient` を Rust 呼び出しに置き換え
   - 既存インターフェースを維持しつつ内部実装を Rust 呼び出しに変更
   - または `RustBackedClient` として新クラスを作成し切り替え
4. 既存テスト・動作確認
   - `compare_data_volume.py` でデータ量比較
   - Web プロキシ経由でのブラウジング確認
   - エラーケース（タイムアウト、ネットワーク断）の検証

### タスク詳細（Phase 1）

#### Rust 側追加（`akari_udp_core`）

```rust
// 新規構造体・API（イメージ）
pub struct RequestConfig {
    pub timeout_ms: u64,
    pub max_nack_rounds: Option<u32>,
    pub initial_request_retries: u32,
    pub sock_timeout_ms: u64,
    pub first_seq_timeout_ms: u64,
    pub df: bool,
    pub agg_tag: bool,
    pub payload_max: Option<u32>,
}

pub struct HttpResponse {
    pub status_code: u16,
    pub headers: Vec<(String, String)>,
    pub body: Vec<u8>,
    pub stats: TransferStats,
}

pub struct TransferStats {
    pub bytes_sent: u64,
    pub bytes_received: u64,
    pub nacks_sent: u32,
    pub request_retries: u32,
}

impl AkariClient {
    pub fn new(remote_host: &str, remote_port: u16, psk: &[u8]) -> Self;
    pub async fn send_request(&self, url: &str, method: &str, body: &[u8], config: &RequestConfig) -> Result<HttpResponse, AkariError>;
}
```

#### PyO3 公開（`akari_udp_py`）

- `AkariClient` を `#[pyclass]` でラップ
- `send_request` を `#[pyo3(signature = (...))]` で公開
- 非同期は `pyo3-asyncio` または同期ラッパーで対応

#### Python 側変更

- `akari/udp_client.py` の `AkariUdpClient` 内部を Rust 呼び出しに差し替え
- 既存の `ResponseOutcome` インターフェースは維持

### 成果物（Phase 1）
- `akari_udp_core/src/client.rs`: 高レベル通信クライアント
- `akari_udp_py/src/lib.rs`: PyO3 バインディング更新
- `py/akari/udp_client.py`: Rust バックエンド版に差し替え
- 動作確認レポート

---

## Phase 2: Flutter 移行

### 役割分担（Phase 2）
- **Rust**: Phase 1 で検証済みの通信ロジックを `flutter_rust_bridge` で公開
- **Flutter(Dart)**: ローカル HTTP サーバ、URL/HTML/CSS/JS 書き換え、設定管理、UI（WebView またはネイティブ画面）を担当

### アーキテクチャ概要
1. アプリ起動時に Dart がローカル HTTP サーバ（`shelf`）を 127.0.0.1 で起動
2. クライアント（WebView / Flutter UI）→ ローカル HTTP → 書き換え・フィルタ → Rust FFI で通信 → リモートプロキシ
3. 応答は Dart で書き換えし、HTTP レスポンスとして返却

### マイルストン（Phase 2）
5. `flutter_rust_bridge` でバインディング生成
   - Phase 1 の `AkariClient` / `HttpResponse` を Dart に公開
6. 設定・データモデル移植（v3 前提で簡素化）
7. ローカル HTTP サーバ最小 PoC（`/healthz`, `/proxy` で 1 サイト通過）
8. HTML/CSS/JS/Location 書き換えロジックの Dart 版移植
9. WebView/ネイティブ UI 統合と基本操作（URL入力・戻る・更新）
10. 追加機能移植（コンテンツフィルタ、ログ表示、設定画面）
11. 各プラットフォームビルド配布手順整備（Win/Android/iOS）

### タスク詳細（Phase 2）

#### 設定読み込み
- `local_proxy.config` 相当を Dart で再実装。TOML→モデル、必須項目: リモートホスト/ポート/PSK、v3 固有のフラグのみ

#### Rust FFI（flutter_rust_bridge）
- Phase 1 の `AkariClient` を公開
- API は非同期（Dart の `Future` にマップ）

#### Dart ローカルサーバ
- `shelf` + `shelf_router` で `/proxy` & `/api/proxy` (GET/POST 両対応) とパス直指定型プロキシ (`/{abs-url}`) を実装
- HTTP のみ、127.0.0.1 バインド。`/healthz` でヘルスチェック

#### 書き換えロジック
- Python の `akari.web_proxy.router` を参照し、以下を Dart に移植。性能懸念時は Isolate 分離
  - HTML: href/src/action/srcset/meta refresh をプロキシ URL に書き換え、サービスワーカー `sw-akari.js[?enc=1]` 登録＋ランタイム書き換えスクリプト挿入
  - CSS: `url(...)` のプロキシ化
  - JS: fetch()/import()/from/bare import の静的リテラルを書き換え
  - Location ヘッダを書き換え、CSP 等のセキュリティヘッダと Transfer-Encoding を除去し Content-Length 再計算
  - Content-Encoding (br/gzip/deflate) をデコードしてから書き換え、再圧縮はしない

#### UI
- 最低限: WebView で `http://127.0.0.1:<port>/` を表示
- ランタイム書き換えで表示する URL パネル（JS）をそのまま活かすか、Flutter 側に置き換えるかを決める
- 余裕があれば Flutter ネイティブ UI 版も並行検討

#### プラットフォーム対応
- Windows: Rust を cdylib(DLL) ビルドし、Flutter desktop から FFI 呼び出し
- Android: `cargo-ndk` で `.so` を生成し、`jniLibs/` に配置。`networkSecurityConfig` で 127.0.0.1 の cleartext を許可
- iOS: `xcframework` を生成し、Podfile でリンク。ATS は localhost HTTP を許可
  - ⚠️ ServiceWorker は WKWebView で制限あり。代替手段を検討

### 成果物（Phase 2）
- 新規ドキュメント: ビルド手順書（`docs/flutter_rust_build.md`）
- Rust: flutter_rust_bridge 用のバインディング
- Dart: ローカル HTTP サーバ、書き換えロジック、動作確認用 UI

---

## Python 版から必ず移植する挙動（抜け防止）

- **URL入力とクエリ処理**: `entry` でフィルタスキップ、`enc/e` または `akari_enc=1` Cookie で暗号化指定を保持し、レスポンスで Set-Cookie 付与。外側クエリの汎用パラメータを元URLへマージ（entry/enc/e/_akari_ref は除外）
- **コンテンツフィルタ API**: `/api/filter` GET/POST で JS/CSS/IMG/OTHER をトグル。レスポンスフィルタは Content-Type ベースで 204 + `X-AKARI-Filtered` を返す
- **エラーハンドリング**: URL未指定/非HTTP=400、UDP送信失敗=502、タイムアウト=504、レスポンス欠落=502、フィルタ更新の型エラー=400(JSON)
- **UDP クライアント設定**: df/agg_tag/payload_max/plpmtud/initial_request_retries/max_nack_rounds/first_seq_timeout/sock_timeout/timeout を FFI 経由で指定し、message_id の wrap 増分と送受信ログを保持。**v3専用**で動かし、レガシー v1/v2 パラメータは不要
- **静的配信**: `static/` からエントリ HTML とアセットを返却（Content-Type 推定＋text系は UTF-8 付与）

## 非対象・廃止
- v1/v2 プロトコルのロジック・定数・設定項目は移植しない。Rust 側・Dart 側とも v3 固定で実装する

---

## リスクと対策

| リスク | 対策 |
|--------|------|
| Rust 非同期と FFI の複雑さ | 同期ラッパーを用意し、必要に応じて非同期化 |
| 書き換えロジック性能 | 大きな HTML で遅延 → Isolate 化＋ストリーミング対応を検討 |
| WebView 依存 | デスクトップでは機能差がある → Flutter ネイティブ UI の代替ルートを保持 |
| iOS ServiceWorker 制限 | WKWebView では制限あり → ランタイム書き換えで代替 |
| ビルド環境差異 | `cargo-ndk` / Xcode / Windows toolchain のセットアップを README に明記し、CI で検証予定 |
| Rust パニック時の処理 | `flutter_rust_bridge` / PyO3 で例外に変換、Dart/Python 側で graceful に処理 |

---

## テスト計画

### Phase 1
- 単体テスト: Rust の `AkariClient` に対するモック UDP ソケットテスト
- 結合テスト: Python プロキシ経由での実リクエスト（`compare_data_volume.py`）
- エラーケース: タイムアウト、NACK 無限ループ防止、ネットワーク断

### Phase 2
- 単体テスト: Dart 書き換えロジックのテスト
- 結合テスト: Flutter アプリから実サイトへのプロキシアクセス
- プラットフォームテスト: Windows / Android / iOS での動作確認

---

## 次のアクション

### Phase 1（まず着手）
1. `akari_udp_core` に `AkariClient` 構造体のスケルトン追加
2. 既存の Python `AkariUdpClient._send_request_unlocked` ロジックを Rust に移植
3. PyO3 バインディング更新・Python 側差し替え
4. `compare_data_volume.py` で動作確認

### Phase 2（Phase 1 完了後）
5. `flutter_rust_bridge` 導入
6. Dart で設定ローダと `/healthz` 付きローカル HTTP サーバの PoC 作成
7. `/proxy` 経由で 1 リクエスト通す動作確認  
