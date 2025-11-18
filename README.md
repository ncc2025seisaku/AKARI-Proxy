# AKARI Proxy

## 概要

このリポジトリは Rust 製 `akari_udp_core`（ヘッダ/ペイロード/HMACエンコード・デコード）と、その pyo3 バインディング `akari_udp_py`、および Python 側のユーティリティを含んだモノレポ構成です。`uv` + Python 3.11 でビルドされることを前提に、ローカル/外部プロキシの UDP 処理を Rust に閉じ込めた構成です。

## 開発用環境を整える（他の開発者向け）

1. **uv で Python 3.11 を準備**

   ```powershell
   uv python install 3.11
   uv venv --python 3.11 .venv
   .\.venv\Scripts\activate.bat  # PowerShell なら Activate.ps1
   ```

2. **Python バインディングをビルド＆インストール**

   `uv add` でツール類を `.venv` に追加すると手順が簡潔です。

   ```powershell
   uv add pip setuptools
   pip install maturin
   cd crates/akari_udp_py
   python -m maturin develop
   cd ../../
   ```

   これで `.venv` 内の Python から `import akari_udp_py` ができるようになります。

3. **Python ラッパを使うために `py/` を読み込む**

   `py/akari` パッケージをモジュールとして使うには `PYTHONPATH` を通す必要があります。

   ```powershell
   $env:PYTHONPATH = "$PWD\py"
   ```

4. **ビルド済みバイナリをリンク**

   `akari_udp_py` が依存する Python DLL（例: `python311.dll`）を PATH に追加しておいてください。`uv run` を使えば自動的に入り、`cargo test` などの実行時にも問題ありません。

## テストを回す

```powershell
uv run --python 3.11 cargo test
```

`akari_udp_core` のユニットテストと `akari_udp_py` の pyo3 テストが両方実行されます。

## デバッグ用ツール

### `akari_udp_py` の `debug_dump_py`

Rust 側で `debug_dump(datagram, psk)` を呼ぶとヘッダ／ペイロード／HMAC を文字列整形。`akari_udp_py` から同じ結果を取得する `debug_dump_py` が提供されています。

### `python -m akari.debug_tool`

`py/akari/debug_tool.py` に簡易デバッグ CLI を用意しました。次のように叩くだけで、リクエスト・レスポンス・エラーの datagram を生成して `decode_packet_py` や `debug_dump_py` で確認できます。

```powershell
$env:PYTHONPATH = "$PWD\py"
uv run --python 3.11 python -m akari.debug_tool --pretty
```

主な引数:

- `--mode [req|resp|error]`: 生成するパケットの種類（`--datagram` があるときは読み込み）  
- `--psk` / `--hex`: PSK を文字列 or 16進で指定  
- `--url` / `--message-id` / `--timestamp`: サンプルリクエストのパラメータ  
- `--body`, `--status`, `--error-code`, `--message`: レスポンス／エラーパケットのメタデータ  
- `--datagram path`: 既存 datagram を読み込み  
- `--text`: Rust の `debug_dump` テキスト出力を表示（`--pretty` を無視）  
- `--pretty`: JSON を prettify（デフォルトは compact）  
- `--no-diff`: 入力値と復元 JSON の差分出力を抑制  
- `--no-hex`: バイト列の hexdump 出力を抑制

デバッグスクリプトから生成した JSON は `akari_udp_py.decode_packet_py` の結果をそのまま再現するので、ヘッダ・ペイロード・HMAC などを目で追うのが簡単になります。差分と hex ダンプを併用すれば、「生成前の構造」と「復元後の構造」のギャップを素早く見つけられます。

## Web プロキシ検索画面

`py/akari/web_proxy/static/index.html` はローカルプロキシの Web プロキシモードで表示されるトップページを想定した、検索用 UI です。フォームでは「URL をそのまま開く」か「検索クエリから Google 検索を開く」かを切り替えられ、検索モードを選ぶと `https://www.google.com/search?q=` にエンコード済みクエリを付加した URL を開きます。新しいタブまたは同タブで開くボタンを使えば即座にアクセスできます。

ローカルプロキシ設定パネルで `Host`/`Port` を入力すると `http_proxy`/`https_proxy` の文字列がリアルタイムに更新され、コピーしてブラウザや OS のプロキシ設定に貼り付けることができます。設定値はブラウザの `localStorage` に保存されるのでリロードしても維持されます。

ロゴ画像は `py/akari/web_proxy/static/logo.png` に収納します。正方形（例: 96×96px）の PNG/JPEG で置き換えるとページ上部のロゴに反映されます。

静的ファイルは Python の組み込み HTTP サーバーで配信できます。`.venv` をアクティベートし、`PYTHONPATH` に `py` を通した状態で例えば `uv run --python 3.11 python -m akari.web_proxy.server --host 127.0.0.1 --port 8000` を実行すると、`http://127.0.0.1:8000/` で検索画面が開きます。

## UDP デモスクリプト

ローカル／外部プロキシ相当の処理を `scripts/demo_udp.py` で手早く確認できます。外部プロキシ（`AkariUdpServer`）は着信 URL に応じて HTTP 正常応答またはエラー応答を生成し、ローカルプロキシ（`AkariUdpClient`）役が UDP 経由で受信しながらレスポンスボディとパケット列を表示します。PSK を `--psk`/`--hex` で切り替えたり、`--url` を複数回指定して順に送信したりでき、URL に `--error-keyword` 文字列が含まれるとエラー応答が返ってきます。

```powershell
set PYTHONPATH=%CD%\py
uv run --python 3.11 python scripts/demo_udp.py
```

ホストやポート、タイムアウトは `--host`/`--port`/`--timeout` でも指定できます。たとえば以下のように 2 件の URL を送信し、1 つ目を正常、2 つ目をエラーにする構成で挙動を確認することができます。

```powershell
uv run --python 3.11 python scripts/demo_udp.py --url https://example.com/ping --url https://example.com/error --error-keyword error
```

出力には `[server]` の受信ログや、`ResponseOutcome` の JSON、受信パケットの詳細が含まれ、問題なく送受信できているかを目で追えます。`--port 0` を指定すると OS が空いているポートを選ぶため、複数インスタンスを並行実行する際に便利です。

## 今後の連携

- `py/akari/udp_codec.py` の `akari-udp-dump` CLI は STDIN からバイナリを受け取って JSON または `debug_dump` テキストを出します（`--debug`/`--pretty` 付き）。パイプやファイルから直接使って確認できます。  
- `debug-log` Cargo フィーチャーを有効化して `RUST_LOG=debug` + `cargo test -- --nocapture` すれば encode/decode の内部ログも出力されます。  
- 追加の Python スクリプトやドキュメントが必要な場合は `py/akari` 以下に置いておいてください。
