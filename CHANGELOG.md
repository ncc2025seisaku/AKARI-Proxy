# Changelog

All notable changes to AKARI Proxy will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2025-12-19

### Added
- **Feature**: AKARI-UDP v3 protocol support
- **Feature**: Flutter app with WebView integration, URL bar, and Settings UI
- **Feature**: AkariClientPool for concurrent request processing (#7)
- **Feature**: Issue/PR automation workflows (Priority analysis, Cycle management)
- **Infrastructure**: CI/CD pipeline for Windows, Android, and iOS with automated releases (#15, #27)
- **Infrastructure**: Rust FFI bindings via flutter_rust_bridge
- **Core**: Local HTTP proxy server with HTML/CSS/JS URL rewriting and Brotli/gzip decompression
- **Testing**: Flutter integration tests (#9)
- **Documentation**: New sections for Flutter app in main README (#11) and logic flow diagrams
