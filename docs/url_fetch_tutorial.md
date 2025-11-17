# URLレスポンス取得の超やさしい作り方

初心者が `docs/AKARI.md` / `docs/architecture.md` の要件をもとに  
「URLにアクセスしてレスポンスを取得する処理」を組み立てられるよう、
実装済みの `py/akari/remote_proxy/http_client.py` を噛み砕いて説明する。

---

## 1. どんな役割？

* AKARI-Proxy では外部プロキシが **HTTP/HTTPS クライアント** となり、  
  Web サイトにアクセスして得たデータを UDP でローカル端末へ返す。
* その一歩目が「URLを受け取ってレスポンスを取ってくる」処理。
* 仕様の根拠:
  * `docs/AKARI.md` 2章/3章 … 外部プロキシはウェブからHTML/CSS/JS/画像を取得する
  * `docs/architecture.md` 6.1節 … `remote_proxy/http_client.py` で GET/タイムアウト/サイズ上限を守る

---

## 2. ファイル構成と作業場所

```
py/
└─ akari/
   └─ remote_proxy/
      ├─ __init__.py
      └─ http_client.py   ← 今回の実装
docs/
└─ url_fetch_tutorial.md   ← この解説ファイル
```

`http_client.py` を触れば、外部プロキシで使う最小限のHTTPクライアントが手に入る。

---

## 3. コードを分解して理解する

1. **定数を決める**
   * `DEFAULT_TIMEOUT = 5.0` 秒 … 要件で推奨されている値。
   * `MAX_BODY_BYTES = 1_000_000` … 不正な巨大レスポンスを防ぐ安全装置。
2. **URLを正規化する (`_normalize_url`)**
   * 前後の空白を削除。
   * `http` / `https` 以外は `InvalidURLError`。
   * ホスト名が空（例: `http:///path`）もエラーにする。
3. **実際に取得する (`fetch`)**
   * `urllib.request.Request` で GET リクエストを作り、User-Agent を明示。
   * `urlopen(..., timeout=5.0)` でアクセス。
   * `body = resp.read(max_bytes + 1)` と1バイト余分に読み、上限を突破したら `BodyTooLargeError`。
   * 成功したら `{"status_code": ..., "headers": {...}, "body": b"..."}`
     という辞書（`TypedDict`）で返却。
4. **例外をわかりやすく変換**
   * `socket.timeout` は `TimeoutFetchError`（「5秒以内に返ってこなかったよ」）。
   * URLミスや `ftp://` などは `InvalidURLError`。
   * それ以外は `FetchError` にまとめて上位へ投げる。

---

## 4. 使ってみる（ローカル検証）

1. プロジェクトルートに `demo_fetch.py` を作成し、次のコードを貼り付ける。

    ```python
    from akari.remote_proxy.http_client import fetch, FetchError

    try:
        resp = fetch("https://example.com")
    except FetchError as err:
        print(f"失敗: {err}")
    else:
        print(resp["status_code"])
        print(resp["headers"].get("Content-Type"))
        print(len(resp["body"]), "bytes")
    ```

2. ターミナルで `python demo_fetch.py` を実行すると、HTTPレスポンスの基本情報が表示される。

### エラーをわざと出す例

**プロトコル違いを確認**

```python
from akari.remote_proxy.http_client import fetch, InvalidURLError

try:
    fetch("ftp://example.com")
except InvalidURLError as err:
    print("OK:", err)
```

**タイムアウトを確認**

```python
from akari.remote_proxy.http_client import fetch, TimeoutFetchError

try:
    fetch("https://10.255.255.1", timeout=1.0)
except TimeoutFetchError as err:
    print("OK:", err)
```

どちらも `python <ファイル名>.py` で実行すれば挙動を確かめられる。

---

## 5. 例外早見表

| 例外名               | いつ起きる？                                 | 上流での扱い案                                    |
|----------------------|----------------------------------------------|--------------------------------------------------|
| `InvalidURLError`    | URLが空、`http/https`以外、ホストなし        | 400 Bad Request 相当のエラーをAKARI-UDPで返す    |
| `BodyTooLargeError`  | サーバーが巨大なレスポンスを返した           | 部分取得を諦め、外部プロキシでエラー化           |
| `TimeoutFetchError`  | `timeout`秒以内にレスポンスが来なかった      | `docs/architecture.md` 6.2節の例のように504で返す |
| `FetchError`         | それ以外のHTTP/ネットワークの一般的な失敗    | 502 Bad Gateway などにまとめてしまってOK         |

---

## 6. 次のステップ

1. `remote_proxy/handler.py` を作り、`fetch()` の戻り値を AKARI-UDP のチャンクに変換する。
2. `udp_server.py` から `handler` を呼び出し、`docs/AKARI.md` 3章のフローどおりに通信させる。
3. 自動テストを作るなら `tests/test_udp_py/` に `fetch()` のモックを使った疎通テストを書く。

わからなくなったら:

* 仕様確認 → `docs/AKARI.md`
* 役割・インターフェース確認 → `docs/architecture.md` 6.1/6.2節
* 実装の雛形 → このファイルか `py/akari/remote_proxy/http_client.py`

これで「まずはURLにアクセスしてレスポンスを取得」するパーツが完成！  
残りのUDP連携はこのパーツの上に組み立てていけばOK。

---

## 7. Step1: `remote_proxy/handler.py`

* `AkariUdpServer` から渡された `IncomingRequest` を受け取り、`payload["url"]` を元に `fetch()` を実行。
* レスポンス body を MTU (1180 byte) で分割し、先頭チャンクは `encode_response_first_chunk_py()`、後続は `encode_response_chunk_py()` に渡す。
* エラーは例外種別ごとに AKARI-UDP の error packet へ変換。
  * `InvalidURLError` → error_code=10 / HTTP 400
  * `BodyTooLargeError` → error_code=11 / HTTP 502
  * `TimeoutFetchError` → error_code=20 / HTTP 504
  * その他の `FetchError` → error_code=30 / HTTP 502
  * 想定外 → error_code=255 / HTTP 500
* これで「URL取得ロジック → AKARI-UDP datagram」の橋渡しが完了する。

---

## 8. Step2: `remote_proxy/server.py`

1. `serve_remote_proxy()` が `AkariUdpServer` を生成し、ハンドラ `handle_request` を登録。
2. CLI から実行可能:

    ```powershell
    python -m akari.remote_proxy.server --host 0.0.0.0 --port 14500 --psk test-psk-0000-test
    ```

3. `--hex` で PSK を16進表現に切り替え、`--timeout` / `--buffer-size` / `--log-level` で運用設定を調整。
4. ローカルプロキシが送った datagram を受け取り、即座に HTTP 取得→レスポンス化して送り返す。

これで

```
ローカルHTTPクライアント →(AKARI-UDP)→ remote_proxy.server →(HTTP/HTTPS)→ Web
```

という通信路が一通り形になり、残るのはローカル側や統合テストのみ。
