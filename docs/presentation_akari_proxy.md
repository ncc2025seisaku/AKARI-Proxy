# AKARI Proxy プレゼン原稿（ドラフト）

## 1. AKARI Proxy とは
- ブラウザからの HTTP/HTTPS アクセスを **UDP ベースの独自プロトコル AKARI-UDP v2** に載せ替えて転送する軽量プロキシ。
- ローカル側 `Web proxy`（UI 付き）が URL を受け取り、`AkariUdpClient` で UDP 送信 → リモート側が実際の HTTP/HTTPS を取得して応答を UDP で返す。
- 低オーバーヘッド: パケットは **24B 固定ヘッダ + 16B タグ** が最小構成。ハンドシェイク無しで即リクエストを送れる。
- 信頼性: 受信欠落を `ack`（first-lost）と `nack`（bitmap）で最小限再送し、必要なシーケンスだけリトライ。
- セキュリティ: E フラグ時は **XChaCha20-Poly1305** で暗号化＋認証、非暗号モードでも HMAC-SHA256 で改ざん検出。
- 圧縮: C フラグで zstd Lv1（将来 Brotli も選択予定）を有効化し、帯域をさらに節約可能。
- UI は `py/akari/web_proxy/static/index.html` をエントリに Service Worker（`sw-akari.js`）で全 fetch を `http://<listen_host>:<listen_port>/<URL>` へ巻き取り、HTML 内のリンクも `/sw-akari.js` 登録スニペットで自動書き換え。
- レスポンスはローカルで Content-Encoding をデコードし、CSP/TE をはずしてブラウザに返送（`WebRouter._raw_response`）。`X-AKARI-*` で message_id/送受信バイト数も可視化。

## 2. 目的・ゴール
- **通信フットプリント削減**: TCP/TLS ハンドシェイクを省き、最小 24B ヘッダ (+16B AEAD/HMAC タグ) で 1200B MTU 内に詰める設計。
- **疎通性向上**: UDP が許可され TCP/443 が制限される環境でも Web アクセスを確保。
- **ブラウジングの課題解消**: 企業プロキシやファイアウォールで発生する「TLS インスペクションによる遅延」「TCP ポート制限」「CSP/Service Worker による埋め込み失敗」「大型画像や JS の帯域圧迫」を、UDP トンネル＋コンテンツフィルタで緩和。
- **輻輳・ロスへの耐性**: モバイル回線やカフェ Wi‑Fi のように RTT/ロス率が揺れる場面で、ACK/NACK による部分再送と zstd 圧縮で帯域を圧縮し、タイムアウト短縮でキビキビした体感を狙う。
- **災害・非常時の復旧性**: インフラ断や一時的な TCP 規制下でも、UDP 経路が残っていれば最小限のデータ量で情報取得を継続しやすく、フィルタで重いコンテンツを落として必要情報（テキスト中心）だけを届ける運用が可能。
- **コンテンツ制御の簡素化**: JS/CSS/IMG/Other を API または UI トグルで瞬時に無効化し、安全なビューアとして使える。
- **導入容易性**: `scripts/run_web_proxy.py` と `conf/web_proxy.toml` だけでローカル UI を起動（Python 3.11 + uv）。Rust コアは pyo3 バインディング経由で自動利用。

## 3. 通常 HTTPS とのデータ量比較（概算）
| ケース | 内訳 | HTTPS (TCP+TLS) | AKARI-UDP v2 |
| --- | --- | --- | --- |
| 初回接続（TLS 1.3） | TCP 3-way + TLS 1.3 1-RTT + HTTP リクエスト/レスポンスヘッダ | ≈ 1.5–2.0 KB オーバーヘッド + 実データ | **1 枚の req データグラム**（24B ヘッダ + URL/オプション + 16B タグ）と **resp チャンク**のみ。ハンドシェイク 0。 |
| 10 KB HTML | ①TLS ハンドシェイク 1.5KB<br>②HTTP ヘッダ約 600B<br>③ボディ 10KB<br>合計 ≈ 12.1KB + ACK/再送 | ①なし<br>②seq=0 に status/hdr_block、24B ヘッダ + 16B タグ + ≈120B header block<br>③ボディは 1200B MTU に分割、各パケット 24B+16B オーバーヘッド<br>概算 合計 ≈ 10.8KB（ハンドシェイク分が削減） |
| 再送/欠落時 | TCP 再送 (倍増 RTO)、全 ACK 必須 | `ack` (first-lost) / `nack` (bitmap) で足りない seq だけ要求。 |
※数値は `docs/AKARI.md` の固定ヘッダ長と MTU 前提の試算。実測はネットワーク条件と圧縮/暗号化設定で変動。

## 4. デモ動画（構成案）
- シナリオ: `scripts/run_web_proxy.py --config conf/web_proxy.toml` で UI を起動 → ブラウザで `http://127.0.0.1:8080/` を開き、`https://example.com` を入力 → Service Worker が全リンクをプロキシ経由に書き換える様子を表示。
- オーバーレイで `X-AKARI-Bytes-Sent/Received` を開発者ツールから確認し、コンテンツフィルタ（JS/CSS/IMG/Other）を ON/OFF。204 No Content でブロックされる例も見せる。
- 収録ヒント: `scripts/demo_udp.py --url ... --error-keyword ...` を併用し、エラー応答と再送 (`nack`) ログをターミナルで同期表示するとプロトコルの特徴が伝わる。

- **プロトコル**: 24B 固定ヘッダ + AEAD XChaCha20-Poly1305 (E=1) または HMAC-SHA256 タグ 16B。ACK/NACK 付きの可変長チャンク転送。Content-Encoding (brotli/gzip/deflate) はローカルで解凍。C フラグで zstd 圧縮（レベル1）を選択可能。
- **コンテンツフィルタ**: `local_proxy.content_filter.ContentFilter` が URL の拡張子や Content-Type から `javascript/css/image/other` を分類。`/api/filter` GET/POST で状態取得・更新。
- **HTML 書き換え**: `WebRouter._rewrite_html_to_proxy` が href/src/srcset を絶対 URL に解決してプロキシ経由へ差し替え。末尾に Service Worker 登録スニペットを自動付与。
- **セキュリティヘッダ処理**: 透過表示のため CSP/TE を除去、Content-Type 未設定時は `text/html; charset=utf-8` を補完。
- **設定**: `conf/web_proxy.toml` で listen_host/port、PSK（平文 or hex）、タイムアウト、フィルタ既定値を指定。`mode` は web / reverse をサポート。
- **実装スタック**: Rust コア (`crates/akari_udp_core`)、Python バインディング (`akari_udp_py`), Python サーバ (`WebHttpServer` + `WebRouter`), フロントは純 HTML/CSS/JS + WebGL エフェクト。

## 6. 使い方（抜粋）
```powershell
# 事前: uv で venv 作成後、pyo3 バインディングを develop インストール
python scripts/run_web_proxy.py --config conf/web_proxy.toml
# ブラウザで http://127.0.0.1:8080/
```
- フィルタ API: `GET /api/filter` / `POST /api/filter {"enable_js":false,...}`。
- プロキシ API: `GET /{URL}` または `/api/proxy?url=...`。`entry=1` 付きリクエストはフィルタスキップ。

## 7. まとめメッセージ（スライド終盤用）
- 「TCP/TLS の儀式を省き、UDP で軽く・早く・制御しやすい Web アクセスを提供するのが AKARI Proxy。」
- 「Service Worker + HTML 書き換えでブラウザ側の設定はゼロ、PSK だけで安全にトンネルできる。」
- 「フィルタと可視化ヘッダで“運用しやすいプロキシ”を目指す。」
