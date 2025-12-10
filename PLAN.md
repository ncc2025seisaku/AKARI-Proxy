# AKARI-UDP v3 実装プラン（作業用）

## 0. ゴール
- v3プロトコル（集約タグ・ヘッダ分割対応・短縮ヘッダ・ヘッダ/ボディNACK）を実装し、ローカル↔リモート間で疎通確認できる状態にする。

## 1. コア実装（Rust akari_udp_core）
- [x] HeaderV3定義（short-id/short-len対応、type拡張）
- [ ] 新パケット型のencode/decode追加（resp-head/resp-head-cont/resp-body/nack-head/nack-body）
- [ ] 集約タグ用のAEAD処理（ブロック暗号化・復号）
- [ ] MTU対応（デフォルトペイロード上限1200B、DF/PLPMTUDオプション下準備）

## 2. Pythonバインディング（akari_udp_py）
- [ ] v3エンコード/デコード関数をPyにエクスポート
- [ ] 既存v2との互換ラッパー整備

## 3. リモート送信側
- [ ] レスポンス生成をv3パケットへ（ヘッダ分割、短ヘッダ、集約タグ）
- [ ] NACK-HEAD対応の再送処理

## 4. ローカル受信側（py/akari/udp_client.py）
- [ ] v3優先デコード、v2フォールバック
- [ ] ヘッダ/ボディ分離バッファ、NACK-HEAD/NACK-BODY、優先度付き再送
- [ ] タイムアウト/再リクエストポリシー（10秒、改善なし2連続で破棄、再リクエスト1回）

## 5. 設定・CLI
- [ ] conf/web_proxy.toml 等に v3/agg-tag/payload_max/DFオプションを追加
- [ ] scripts/compare_data_volume.py に v3 計測オプションを追加

## 6. テスト
- [ ] Rustユニット/プロパティテスト: encode/decode, 集約タグ, ヘッダ欠損NACK
- [ ] Python: udp_client 集約タグ、NACK-HEAD/BODY、v2フォールバック
- [ ] 回帰: v2互換疎通確認

## 7. ドキュメント
- [ ] README/設計docs に v3利用手順・MTU/DF/PLPMTUDの説明を追記

## 8. 動作確認
- [ ] ローカル↔リモートでv3疎通、データ量比較でオーバヘッド削減を確認
