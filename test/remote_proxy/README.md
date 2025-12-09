# Remote Proxy Test Helpers

`run_server.py` と `send_request.py` は AKARI リモートプロキシと簡易クライアントを起動するためのラッパースクリプトです。

## 使い方

1. `.venv` をアクティベートし、`PYTHONPATH` に `py` を含めておきます。
2. サーバ:
   ```powershell
   python test/remote_proxy/run_server.py --host 0.0.0.0 --port 14500 --psk test-psk-0000-test
   ```
3. クライアント:
   ```powershell
   python test/remote_proxy/send_request.py --host 127.0.0.1 --port 14500 --url https://example.com/ping
   ```

オプションや PSK の指定方法は各スクリプトの `--help` で確認できます。

## 追加のオプション

- `--output-file` / `-o` でレスポンスボディを保存するパスを指定できます（デフォルト：`response_body.bin`）。
- `--compare-http` を付けると同じ URL に対して直接 HTTP GET も行い、ヘッダー／ボディの受信バイト数を AKARI-UDP と比較します。
- `--http-timeout` で HTTP 側のタイムアウト秒を調整できます（デフォルト：10 秒）。
