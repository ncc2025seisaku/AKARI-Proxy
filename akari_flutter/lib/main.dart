import 'dart:io';

import 'package:flutter/material.dart';
import 'package:webview_windows/webview_windows.dart';
import 'package:akari_flutter/src/rust/frb_generated.dart';
import 'package:akari_flutter/src/server/local_server.dart';

/// Global proxy server instance
LocalProxyServer? _proxyServer;

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await RustLib.init();

  // Start the local proxy server
  _proxyServer = LocalProxyServer(
    const ProxyServerConfig(
      host: '127.0.0.1',
      port: 8080,
      remoteHost: '127.0.0.1',
      remotePort: 9000,
      psk: [116, 101, 115, 116, 45, 112, 115, 107, 45, 48, 48, 48, 48, 45, 116, 101, 115, 116], // "test-psk-0000-test" in UTF-8
    ),
  );
  await _proxyServer!.start();

  runApp(const AkariProxyApp());
}

class AkariProxyApp extends StatelessWidget {
  const AkariProxyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'AKARI Proxy',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFFF3C45C),
          brightness: Brightness.dark,
        ),
        useMaterial3: true,
      ),
      home: const ProxyHomePage(),
    );
  }
}

class ProxyHomePage extends StatefulWidget {
  const ProxyHomePage({super.key});

  @override
  State<ProxyHomePage> createState() => _ProxyHomePageState();
}

class _ProxyHomePageState extends State<ProxyHomePage> {
  final _webviewController = WebviewController();
  final _urlController = TextEditingController();
  bool _isWebViewReady = false;
  String _currentUrl = '';
  bool _isLoading = false;

  @override
  void initState() {
    super.initState();
    _initWebView();
  }

  Future<void> _initWebView() async {
    try {
      await _webviewController.initialize();
      
      _webviewController.url.listen((url) {
        // Detect navigation away from localhost and redirect through proxy
        if (!url.startsWith('http://127.0.0.1:8080/') && 
            !url.startsWith('http://localhost:8080/') &&
            url.startsWith('http')) {
          debugPrint('Detected external navigation: $url');
          final proxyUrl = 'http://127.0.0.1:8080/${Uri.encodeComponent(url)}';
          _webviewController.loadUrl(proxyUrl);
          return;
        }

        // Only update if URL actually changed
        if (_currentUrl == url) return;
        _currentUrl = url;

        // Update URL bar text
        if (url.startsWith('http://127.0.0.1:8080/') && 
            !url.contains('/proxy') && 
            !url.endsWith('/') &&
            !url.contains('.js') &&
            !url.contains('.png') &&
            !url.contains('.ico')) {
          try {
            final encodedPart = url.replaceFirst('http://127.0.0.1:8080/', '').split('?').first;
            final decoded = Uri.decodeComponent(encodedPart);
            if (decoded.startsWith('http')) {
              _urlController.text = decoded;
            }
          } catch (_) {}
        }
      });

      _webviewController.loadingState.listen((state) {
        final loading = state == LoadingState.loading;
        if (_isLoading != loading) {
          setState(() {
            _isLoading = loading;
          });
        }
      });

      // Wait a moment for the server to be ready
      await Future.delayed(const Duration(milliseconds: 500));
      
      await _webviewController.loadUrl('http://127.0.0.1:8080/');
      
      setState(() {
        _isWebViewReady = true;
      });
    } catch (e) {
      debugPrint('WebView initialization error: $e');
    }
  }

  void _navigateToUrl() {
    final input = _urlController.text.trim();
    if (input.isEmpty) return;

    String url = input;
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      url = 'https://$url';
    }

    final proxyUrl = 'http://127.0.0.1:8080/${Uri.encodeComponent(url)}';
    _webviewController.loadUrl(proxyUrl);
  }

  void _goBack() {
    _webviewController.goBack();
  }

  void _goForward() {
    _webviewController.goForward();
  }

  void _reload() {
    _webviewController.reload();
  }

  void _goHome() {
    _webviewController.loadUrl('http://127.0.0.1:8080/');
    _urlController.clear();
  }

  @override
  void dispose() {
    _webviewController.dispose();
    _urlController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0A0A0A),
      body: Column(
        children: [
          // URL Bar
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
            decoration: BoxDecoration(
              color: const Color(0xFF1A1A1A),
              border: Border(
                bottom: BorderSide(
                  color: Colors.white.withOpacity(0.1),
                ),
              ),
            ),
            child: SafeArea(
              bottom: false,
              child: Row(
                children: [
                  // Navigation buttons
                  IconButton(
                    icon: const Icon(Icons.arrow_back, size: 20),
                    color: Colors.white70,
                    onPressed: _goBack,
                    tooltip: '戻る',
                  ),
                  IconButton(
                    icon: const Icon(Icons.arrow_forward, size: 20),
                    color: Colors.white70,
                    onPressed: _goForward,
                    tooltip: '進む',
                  ),
                  IconButton(
                    icon: Icon(_isLoading ? Icons.close : Icons.refresh, size: 20),
                    color: Colors.white70,
                    onPressed: _reload,
                    tooltip: _isLoading ? '中止' : '再読み込み',
                  ),
                  IconButton(
                    icon: const Icon(Icons.home, size: 20),
                    color: Colors.white70,
                    onPressed: _goHome,
                    tooltip: 'ホーム',
                  ),
                  const SizedBox(width: 8),
                  // URL input field
                  Expanded(
                    child: Container(
                      height: 36,
                      decoration: BoxDecoration(
                        color: Colors.black.withOpacity(0.3),
                        borderRadius: BorderRadius.circular(18),
                        border: Border.all(
                          color: Colors.white.withOpacity(0.2),
                        ),
                      ),
                      child: TextField(
                        controller: _urlController,
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 14,
                        ),
                        decoration: InputDecoration(
                          hintText: 'URL を入力...',
                          hintStyle: TextStyle(
                            color: Colors.white.withOpacity(0.5),
                            fontSize: 14,
                          ),
                          border: InputBorder.none,
                          contentPadding: const EdgeInsets.symmetric(
                            horizontal: 16,
                            vertical: 8,
                          ),
                          isDense: true,
                        ),
                        onSubmitted: (_) => _navigateToUrl(),
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  // Go button
                  Container(
                    height: 36,
                    decoration: BoxDecoration(
                      gradient: const LinearGradient(
                        colors: [Color(0xFFFFD889), Color(0xFFBF8D29)],
                      ),
                      borderRadius: BorderRadius.circular(18),
                    ),
                    child: TextButton(
                      onPressed: _navigateToUrl,
                      style: TextButton.styleFrom(
                        padding: const EdgeInsets.symmetric(horizontal: 16),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(18),
                        ),
                      ),
                      child: const Text(
                        'GO',
                        style: TextStyle(
                          color: Color(0xFF0A0A0A),
                          fontWeight: FontWeight.bold,
                          fontSize: 13,
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
          // Loading indicator
          if (_isLoading)
            LinearProgressIndicator(
              backgroundColor: Colors.transparent,
              valueColor: const AlwaysStoppedAnimation<Color>(Color(0xFFF3C45C)),
              minHeight: 2,
            ),
          // WebView
          Expanded(
            child: _isWebViewReady
                ? Webview(_webviewController)
                : const Center(
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        CircularProgressIndicator(
                          color: Color(0xFFF3C45C),
                        ),
                        SizedBox(height: 16),
                        Text(
                          'AKARI Proxy を起動中...',
                          style: TextStyle(
                            color: Colors.white70,
                            fontSize: 16,
                          ),
                        ),
                      ],
                    ),
                  ),
          ),
        ],
      ),
    );
  }
}
