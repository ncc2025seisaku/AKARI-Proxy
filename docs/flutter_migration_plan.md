# Flutter + Rust ローカルプロキシ移行計画

## 目的
 Python 版ローカルプロキシを Flutter (Dart) 実装に置き換え、Rust の **v3 パケット処理のみ** を既存 `akari_udp_core` から再利用する（v1/v2 ロジックは不要で廃止）。Windows / Android / iOS で単一コードベースを動かす。

## 役割分担
- Rust: v3 パケットのエンコード・デコードと UDP 送受信のみを FFI 経由で提供。HTTP 処理や書き換えは行わない。
- Flutter(Dart): ローカル HTTP サーバ、URL/HTML/CSS/JS 書き換え、設定管理、UI（WebView またはネイティブ画面）を担当。

## アーキテクチャ概要
1. アプリ起動時に Dart がローカル HTTP サーバ（`shelf`）を 127.0.0.1 で起動。
2. クライアント（WebView / Flutter UI）→ ローカル HTTP → 書き換え・フィルタ → Rust FFI で UDP 送受信 → リモートプロキシ。
3. 応答は Dart でデコード・書き換えし、HTTP レスポンスとして返却。

## マイルストン
1) 設定・データモデル移植 (v3 前提で簡素化)  
2) Rust FFI 最小実装（encode/decode/send_udp）と Dart バインディング生成  
3) ローカル HTTP サーバ最小 PoC（/healthz, /proxy で 1 サイト通過）  
4) HTML/CSS/JS/Location 書き換えロジックの Dart 版移植  
5) WebView/ネイティブ UI 統合と基本操作 (URL入力・戻る・更新)  
6) 追加機能移植（コンテンツフィルタ、ログ表示、設定画面）  
7) 各プラットフォームビルド配布手順整備（Win/Android/iOS）

## タスク詳細
- 設定読み込み  
  - `local_proxy.config` 相当を Dart で再実装。TOML→モデル、必須項目: リモートホスト/ポート/PSK、v3 固有のフラグのみ。
- Rust FFI  
  - `flutter_rust_bridge` で `encode_v3`, `decode_v3`, `send_udp(host, port, payload, timeout_ms)` を公開。既存の **v3** ロジックのみ流用し、v1/v2 由来の処理は持ち込まない。API は非同期。
- Dart ローカルサーバ  
  - `shelf` + `shelf_router` で `/proxy` & `/api/proxy` (GET/POST 両対応) とパス直指定型プロキシ (`/{abs-url}`) を実装。HTTP のみ、127.0.0.1 バインド。`/healthz` でヘルスチェック。
- 書き換えロジック  
  - Python の `akari.web_proxy.router` を参照し、以下を Dart に移植。性能懸念時は Isolate 分離。
    - HTML: href/src/action/srcset/meta refresh をプロキシ URL に書き換え、サービスワーカー `sw-akari.js[?enc=1]` 登録＋ランタイム書き換えスクリプト挿入。
    - CSS: `url(...)` のプロキシ化。
    - JS: fetch()/import()/from/bare import の静的リテラルを書き換え。
    - Location ヘッダを書き換え、CSP 等のセキュリティヘッダと Transfer-Encoding を除去し Content-Length 再計算。
    - Content-Encoding (br/gzip/deflate) をデコードしてから書き換え、再圧縮はしない。
- UI  
  - 最低限: WebView で `http://127.0.0.1:<port>/` を表示。  
  - ランタイム書き換えで表示する URL パネル（JS）をそのまま活かすか、Flutter 側に置き換えるかを決める。  
  - 余裕があれば Flutter ネイティブ UI 版も並行検討。
- プラットフォーム対応  
  - Windows: Rust を cdylib(DLL) ビルドし、Flutter desktop から FFI 呼び出し。  
  - Android: `cargo-ndk` で `.so` を生成し、`jniLibs/` に配置。`networkSecurityConfig` で 127.0.0.1 の cleartext を許可。  
  - iOS: `xcframework` を生成し、Podfile でリンク。ATS は localhost HTTP を許可。

## 成果物
- 新規ドキュメント: 本ファイル + ビルド手順書（後続で `docs/flutter_rust_build.md` を追加予定）
- Rust: FFI ブリッジコードと最小テスト
- Dart: ローカル HTTP サーバ、書き換えロジック、動作確認用 UI

## Python 版から必ず移植する挙動（抜け防止）
- URL入力とクエリ処理: `entry` でフィルタスキップ、`enc/e` または `akari_enc=1` Cookie で暗号化指定を保持し、レスポンスで Set-Cookie 付与。外側クエリの汎用パラメータを元URLへマージ（entry/enc/e/_akari_ref は除外）。
- コンテンツフィルタ API: `/api/filter` GET/POST で JS/CSS/IMG/OTHER をトグル。レスポンスフィルタは Content-Type ベースで 204 + `X-AKARI-Filtered` を返す。
- エラーハンドリング: URL未指定/非HTTP=400、UDP送信失敗=502、タイムアウト=504、レスポンス欠落=502、フィルタ更新の型エラー=400(JSON)。
- UDP クライアント設定: df/agg_tag/payload_max/plpmtud/initial_request_retries/max_nack_rounds/first_seq_timeout/sock_timeout/timeout を FFI 経由で指定し、message_id の wrap 増分と送受信ログを保持。**v3専用**で動かし、レガシー v1/v2 パラメータは不要。
- 静的配信: `static/` からエントリ HTML とアセットを返却（Content-Type 推定＋text系は UTF-8 付与）。

## 非対象・廃止
- v1/v2 プロトコルのロジック・定数・設定項目は移植しない。Rust 側・Dart 側とも v3 固定で実装する。


## リスクと対策
- 書き換えロジック性能: 大きな HTML で遅延 → Isolate 化＋ストリーミング対応を検討。
- WebView 依存: デスクトップでは機能差がある → Flutter ネイティブ UI の代替ルートを保持。
- ビルド環境差異: `cargo-ndk` / Xcode / Windows toolchain のセットアップを README に明記し、CI で検証予定。

## 次のアクション
1. Rust FFI スケルトン追加 (`flutter_rust_bridge` 導入)。  
2. Dart で設定ローダと `/health` 付きローカル HTTP サーバの PoC 作成。  
3. `/proxy` 経由で 1 リクエスト通す動作確認。  
