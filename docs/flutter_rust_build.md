# Flutter + Rust ビルド手順書

AKARI-Proxy Flutter アプリの各プラットフォーム向けビルド手順。

## 前提条件

- Flutter SDK 3.10.4+
- Rust 1.70+（`rustup` でインストール）
- `flutter_rust_bridge_codegen` CLI

## Windows ビルド

### 開発ビルド

```powershell
cd akari_flutter
flutter run -d windows
```

### リリースビルド

```powershell
cd akari_flutter
flutter build windows --release
```

成果物: `build/windows/x64/runner/Release/`

## Android ビルド

### 1. cargo-ndk インストール

```bash
cargo install cargo-ndk
rustup target add aarch64-linux-android armv7-linux-androideabi x86_64-linux-android i686-linux-android
```

### 2. NDK パス設定

`local.properties` に追加:
```
ndk.dir=C:\\Users\\<username>\\AppData\\Local\\Android\\Sdk\\ndk\\<version>
```

### 3. ビルド

```bash
cd akari_flutter
flutter build apk --release
```

### 4. cleartext HTTP 許可

`android/app/src/main/res/xml/network_security_config.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
    <domain-config cleartextTrafficPermitted="true">
        <domain includeSubdomains="false">127.0.0.1</domain>
    </domain-config>
</network-security-config>
```

`AndroidManifest.xml` に追加:
```xml
<application
    android:networkSecurityConfig="@xml/network_security_config"
    ...>
```

## iOS ビルド

### 1. Xcode セットアップ

Xcode 14+ が必要。

### 2. xcframework 生成

```bash
cd akari_flutter/rust
cargo build --release --target aarch64-apple-ios
cargo build --release --target x86_64-apple-ios
```

### 3. ATS 設定

`ios/Runner/Info.plist` に追加（localhost HTTP 許可）:
```xml
<key>NSAppTransportSecurity</key>
<dict>
    <key>NSAllowsLocalNetworking</key>
    <true/>
</dict>
```

### 4. ビルド

```bash
cd akari_flutter
flutter build ios --release
```

## flutter_rust_bridge 再生成

Rust API を変更した場合:

```bash
cd akari_flutter
flutter_rust_bridge_codegen generate
```

## トラブルシューティング

### Windows: DLL が見つからない

`rust/target/release/rust_lib_akari_flutter.dll` が `build/windows/` にコピーされているか確認。

### Android: ネイティブライブラリエラー

`cargo-ndk` が正しくインストールされているか、NDK パスが正しいか確認。

### iOS: ServiceWorker 制限

WKWebView では ServiceWorker に制限あり。ランタイム書き換えスクリプトで代替。
