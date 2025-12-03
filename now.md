# AKARI-Proxy いまどうなってるか（ざっくり完全版）

- **役割**: ブラウザの HTTP リクエストをローカル → UDP（AKARI-UDP） → リモート → HTTP(S) に中継するプロキシ一式。Rust でパケットを安全にエンコード/デコードし、Python でプロキシ本体と UI を提供。
- **流れ**: ブラウザ → `py/akari/web_proxy` の HTTP サーバ → `py/akari/udp_client` が AKARI-UDP Req を送信 → リモート側 `py/akari/remote_proxy` が受信して Web 取得 → AKARI-UDP Resp を返送 → ローカルが再構成してブラウザへ返す。

## 主要ディレクトリと役割
- `crates/akari_udp_core`: Rust コア。ヘッダ/ペイロードのエンコード・デコードと HMAC 検証を担当（24B ヘッダ + Payload + 16B HMAC）。`encode_*`/`decode_packet`/`debug_dump` を公開。
- `crates/akari_udp_py`: pyo3 バインディング。Rust 関数を Python から `encode_request_v2_py` などで呼べるようにする。
- `py/akari/udp_client.py`: ローカル側 UDP クライアント。Req を送信し、Resp チャンクを集約する。v2 では NACK ビットマップ送信、心拍再送、XOR パリティによる 1 チャンク欠損復元をサポート。
- `py/akari/udp_server.py`: リモート側で使う UDP サーバラッパー。受信 → ハンドラ呼び出し → 返却パケット送信。
- `py/akari/remote_proxy`: リモートプロキシ本体。  
  - `config.py`: `conf/remote.toml` からホスト/ポート/PSK/タイムアウト等を読み込む。PSK は文字列・hex・ファイル・環境変数いずれか一つで指定。  
  - `http_client.py`: urllib ベースの GET クライアント。最大 1MB、Accept-Encoding は br/gzip/deflate、タイムアウト/URL バリデーションあり。  
  - `handler.py`: Req を受けて HTTP 取得し、MTU 1180B を基準にチャンク化。先頭チャンクに status/body_len/header_block、以降はボディのみ。FEC パリティ（環境変数 `AKARI_FEC_PARITY=1`）、冗長送信回数（`AKARI_RESP_DUP_COUNT` など）、ヘッダ圧縮用 ID→名前マッピング、レスポンスキャッシュ（message_id 単位 5 秒）と HTTP キャッシュ (url 単位、Cache-Control/Set-Cookie を見て TTL 判断) を実装。NACK で欠損チャンクのみ再送。  
  - `server.py`/`main.py`: UDP サーバ起動エントリ。
- `py/akari/web_proxy`: ローカル HTTP UI。  
  - `config.py`: `conf/web_proxy.toml` を読み、UI 文言、リモート先、PSK（文字列 or hex）、リッスン先、コンテンツフィルタ設定を取得。  
  - `router.py`: `/` で静的 UI、`/proxy`/`/api/proxy` で URL を受けて UDP 経由取得、`/api/filter` でフィルタ設定の閲覧/更新、パス直書きアクセス (`/https://example.com/...`) にも対応。`mode` が `reverse` の場合はホスト名などからターゲットを組み立てる。  
  - `http_server.py`: ThreadingHTTPServer ラッパー。  
  - `static/`: ブラウザ UI (検索フォーム、ロゴ等)。
- `py/local_proxy`: コンテンツフィルタ共通部。拡張子から HTML/JS/CSS/IMG/OTHER を判定し、設定で拒否すると 204 + `X-AKARI-Filtered` を返す。
- その他:  
  - `scripts/run_web_proxy.py`: `conf/web_proxy.toml` を読んでローカル Web プロキシ起動。  
  - `scripts/run_remote_proxy.py` / `run_async_remote_proxy.py`: リモート UDP プロキシ起動。  
  - `scripts/demo_udp.py`: ローカル/リモートを模した UDP 疎通デモ（メッセージ ID、エラー応答などを確認）。  
  - `py/akari/debug_tool.py`: 生成/復号/hex dump をまとめて見る CLI。  
  - `docs/AKARI.md`, `docs/architecture.md`: プロトコル詳細と設計図。`docs/*loadtest*` は負荷試験計画/結果。

## AKARI-UDP プロトコル（v2 が基本、v1 互換あり）
- **ヘッダ**: 24B 固定。`magic="AK"`, `version=0x01/0x02`, `type` (req/resp/ack/nack/error), `flags`, `message_id`(u64), `seq`/`seq_total`(u16), `payload_len`(u16), `timestamp`(u32 big-endian)。
- **HMAC**: PSK で HMAC-SHA256 を計算し先頭 16B をタグとして末尾に付与。タグ不一致は即エラー。
- **Req**: v1 は GET 固定、URL 長 + URL 本文。v2 は `method(get/head/post)` + URL + 任意 header_block(長さ付き)。`flags` は v2 で利用。
- **Resp**: `seq=0` が先頭。`status_code`、`body_len`、v2 は `header_block` も含む。後続チャンクはボディのみ。`seq_total` で総チャンク数を明示。
- **Ack/Nack** (v2): 欠損検知を補助。Ack は first_lost_seq を 2B、Nack はビットマップで欠損チャンクを指示。
- **Error**: `error_code` + HTTP ステータス + メッセージ文字列。

## ローカル側の振る舞い（`py/akari/udp_client.py` など）
- リクエスト送信時に message_id/timestamp を付与。v2 使用時はデフォルトでヘッダなし GET。  
- 受信チャンクは `ResponseAccumulator` で message_id ごとに集約。`seq_total` を見て完了判定。FEC パリティチャンクがあれば 1 チャンク欠損まで XOR で復元。  
- 欠損があれば v2 では NACK を送信（最大 `_max_nack_rounds` 回、ビットマップで指定）。  
- タイムアウト付き待受、ハートビート/再送（`_heartbeat_interval`、`_max_retries` など）でリクエスト再投げも可能。  
- HTTP 返却前にヘッダブロックをデコードして `dict[str,str]` に復元。

## リモート側の振る舞い（`py/akari/remote_proxy/handler.py`）
- URL を検証し、`http_client.fetch` で外部取得。  
- エラー種別に応じて AKARI-UDP error を返す（invalid URL=400、body over limit=502、timeout=504、上流失敗=502、想定外=500）。  
- 正常時: ボディを MTU 基準で分割、先頭チャンクにヘッダブロックと総サイズを付与。環境変数で冗長送信回数（全チャンク/先頭チャンク個別）、FEC パリティ有無を制御。  
- `RESP_CACHE` に直近レスポンスを 5 秒保持し、NACK のビットマップに従って欠損チャンクのみ再送。  
- `HTTP_CACHE` で URL 単位の簡易キャッシュ（Cache-Control/Set-Cookie を考慮）。304 応答時はキャッシュを再利用して 200 を返す。

## Web プロキシ UI（`py/akari/web_proxy`）
- `/` で静的 UI（`static/index.html`）。URL を入力 → `/proxy` に POST → リダイレクトで結果をそのまま表示。  
- `/proxy`/`/api/proxy`: JSON でもフォームでも受け付け、AKARI-UDP で取得したレスポンスをそのままクライアントへストリーミング。  
- `/api/filter`: JS/CSS/IMG/OTHER の許可/拒否設定を取得/更新（`ContentFilter` を共有）。  
- `mode=reverse` の場合は受けた Host/パスからターゲット URL を組み立てる軽量リバプロとして動作。

## 設定と起動の目安
- Python 3.11 + `uv` 前提。`uv python install 3.11 && uv venv .venv` の後、`crates/akari_udp_py` で `maturin develop` を実行すると Python から `akari_udp_py` が使える。`PYTHONPATH` に `py` を通す。  
- リモートプロキシ: `uv run --python 3.11 python scripts/run_remote_proxy.py --config conf/remote.toml`（PSK は文字列/hex/ファイル/環境変数のどれか）。  
- Web プロキシ: `uv run --python 3.11 python scripts/run_web_proxy.py --config conf/web_proxy.toml`。ブラウザで `http://<listen_host>:<listen_port>/` を開く。  
- UDP デモ: `uv run --python 3.11 python scripts/demo_udp.py --url ...` でローカル/リモート双方を模擬。  
- デバッグ: `python -m akari.debug_tool --pretty` で datagram を生成/復号/HMAC 確認。Rust 側の `debug_dump` も同等のダンプを出す。

## テスト・ドキュメント
- Rust/py 統合テストは `uv run --python 3.11 cargo test` でまとめて実行（HMAC 検証、往復テスト含む）。  
- 設計・プロトコルの詳細は `docs/AKARI.md` と `docs/architecture.md`。負荷試験計画/報告は `docs/disaster_loadtest_plan.md` などにあり。

---
発表で迷ったら「Rust コアが UDP パケットを守り、Python 側がプロキシと UI を回す」こと、「v2 はヘッダブロック + NACK/FEC で堅牢化している」ことを押さえれば OK。
