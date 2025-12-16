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
  bool _isWebViewReady = false;
  String _currentUrl = '';

  @override
  void initState() {
    super.initState();
    _initWebView();
  }

  Future<void> _initWebView() async {
    try {
      await _webviewController.initialize();
      
      _webviewController.url.listen((url) {
        setState(() {
          _currentUrl = url;
        });
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

  @override
  void dispose() {
    _webviewController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0A0A0A),
      body: _isWebViewReady
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
    );
  }
}
