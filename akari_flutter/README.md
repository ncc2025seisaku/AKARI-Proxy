# AKARI Flutter

AKARI-UDP を使用したセキュアなプロキシクライアントアプリケーションです。

Rust FFI (flutter_rust_bridge) を活用し、高速で安全なUDP通信を提供します。

## 機能

- 🌐 **WebViewブラウザ統合** - アプリ内ブラウザでウェブサイトを閲覧
- 🔒 **暗号化通信** - AKARI-UDP v3プロトコルによる安全な通信
- ⚙️ **設定UI** - リモートサーバー、PSK、コンテンツフィルターの設定
- 📊 **モニタリング** - 通信状況のリアルタイム表示
- 🖥️ **マルチプラットフォーム** - Windows / Android / iOS 対応

## 動作要件

- Flutter 3.10.4 以上
- Rust 1.70 以上（ビルド時）
- 各プラットフォームの開発環境:
  - **Windows**: Visual Studio 2022 with C++ workload
  - **Android**: Android SDK, NDK
  - **iOS**: Xcode 14+, CocoaPods

## ビルド方法

### 共通準備

```bash
# 依存関係のインストール
cd akari_flutter
flutter pub get
```

### Windows

```bash
flutter build windows --release
```

ビルド成果物: `build/windows/x64/runner/Release/`

### Android

```bash
flutter build apk --release
```

ビルド成果物: `build/app/outputs/flutter-apk/app-release.apk`

### iOS

```bash
flutter build ios --release --no-codesign
```

ビルド成果物: `build/ios/iphoneos/Runner.app`

## 開発

### デバッグ実行

```bash
# Windows
flutter run -d windows

# Android (エミュレーター or 実機)
flutter run -d android

# iOS (シミュレーター or 実機)
flutter run -d ios
```

### テスト

```bash
# ユニットテスト
flutter test

# 統合テスト
flutter test integration_test/
```

### Rustコードの再生成

flutter_rust_bridge を使用してRust FFIバインディングを更新：

```bash
flutter_rust_bridge_codegen generate
```

## ディレクトリ構成

```
akari_flutter/
├── lib/
│   ├── main.dart              # エントリーポイント
│   └── src/
│       ├── rust/              # flutter_rust_bridge 生成コード
│       ├── server/            # ローカルプロキシサーバー
│       │   ├── local_server.dart
│       │   ├── rewriter.dart
│       │   └── static/        # 静的アセット
│       └── services/          # 設定・サービス
├── rust/                      # Rust FFI ソース
├── android/                   # Android設定
├── ios/                       # iOS設定
└── windows/                   # Windows設定
```

## 設定項目

| 設定 | 説明 | デフォルト |
|------|------|-----------|
| リモートホスト | プロキシサーバーのアドレス | 127.0.0.1 |
| リモートポート | プロキシサーバーのポート | 9000 |
| PSK | 事前共有鍵 | - |
| 暗号化 | 通信の暗号化有効/無効 | ON |
| JavaScript | JSの読み込み許可 | ON |
| CSS | CSSの読み込み許可 | ON |
| 画像 | 画像の読み込み許可 | ON |

## ライセンス

MIT License
