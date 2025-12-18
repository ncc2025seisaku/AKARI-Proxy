import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:tray_manager/tray_manager.dart';
import 'package:window_manager/window_manager.dart';
import 'package:webview_windows/webview_windows.dart' as ww;
import 'package:webview_flutter/webview_flutter.dart' as wf;
import 'package:akari_flutter/src/rust/frb_generated.dart';
import 'package:akari_flutter/src/server/local_server.dart';
import 'package:akari_flutter/src/server/monitoring_view.dart';
import 'package:akari_flutter/src/services/settings_service.dart';
import 'package:akari_flutter/src/services/system_proxy_service.dart';

/// Global settings service
final SettingsService _settingsService = SettingsService();

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  
  if (Platform.isWindows) {
    await windowManager.ensureInitialized();
    WindowOptions windowOptions = const WindowOptions(
      size: Size(1280, 800),
      center: true,
      backgroundColor: Colors.transparent,
      skipTaskbar: false,
      titleBarStyle: TitleBarStyle.normal,
      title: 'AKARI Proxy',
    );
    windowManager.waitUntilReadyToShow(windowOptions, () async {
      await windowManager.show();
      await windowManager.focus();
    });
  }

  await RustLib.init();
  await _settingsService.init();

  // Load saved settings
  final settings = await _settingsService.load();

  // Initialize and start ProxyManager
  _proxyManager = ProxyManager(settings);
  await _proxyManager!.start();

  runApp(AkariProxyApp(initialSettings: settings));
}

/// Global proxy manager instance
ProxyManager? _proxyManager;

/// Manages the local proxy server lifecycle and auto-restart.
class ProxyManager extends ChangeNotifier {
  AkariSettings _settings;
  LocalProxyServer? _server;
  bool _isRunning = false;
  bool _isAutoRestarting = false;
  Timer? _watchdogTimer;

  ProxyManager(this._settings);

  bool get isRunning => _isRunning;
  AkariSettings get settings => _settings;

  Future<void> start() async {
    if (_isRunning) return;
    
    await _startServer();
    if (_settings.useSystemProxy) {
      await WindowsSystemProxy.enable('127.0.0.1:8080');
    }
    _startWatchdog();
    _isRunning = true;
    notifyListeners();
  }

  Future<void> stop() async {
    _watchdogTimer?.cancel();
    if (_settings.useSystemProxy) {
      await WindowsSystemProxy.disable();
    }
    _isRunning = false;
    await _server?.stop();
    _server = null;
    notifyListeners();
  }

  Future<void> updateSettings(AkariSettings newSettings) async {
    final oldSettings = _settings;
    _settings = newSettings;
    
    if (_isRunning) {
      // If system proxy setting changed, apply it immediately
      if (oldSettings.useSystemProxy != newSettings.useSystemProxy) {
        if (newSettings.useSystemProxy) {
          await WindowsSystemProxy.enable('127.0.0.1:8080');
        } else {
          await WindowsSystemProxy.disable();
        }
      }
      
      // If core proxy settings changed, restart server
      if (oldSettings.remoteHost != newSettings.remoteHost ||
          oldSettings.remotePort != newSettings.remotePort ||
          oldSettings.psk != newSettings.psk ||
          oldSettings.useEncryption != newSettings.useEncryption) {
        await stop();
        await start();
      }
    }
  }

  Future<void> _startServer() async {
    _server = LocalProxyServer(
      ProxyServerConfig(
        host: '127.0.0.1',
        port: 8080,
        remoteHost: _settings.remoteHost,
        remotePort: _settings.remotePort,
        psk: _settings.psk,
        useEncryption: _settings.useEncryption,
      ),
    );
    
    try {
      await _server!.start();
    } catch (e) {
      debugPrint('Failed to start proxy server: $e');
      rethrow;
    }
  }

  void _startWatchdog() {
    _watchdogTimer?.cancel();
    _watchdogTimer = Timer.periodic(const Duration(seconds: 30), (timer) async {
      if (!_isRunning || _isAutoRestarting) return;
      
      try {
        // Simple health check
        final client = HttpClient();
        client.connectionTimeout = const Duration(seconds: 2);
        final request = await client.getUrl(Uri.parse('http://127.0.0.1:8080/healthz'));
        final response = await request.close();
        if (response.statusCode != 200) {
          throw Exception('Health check failed');
        }
        client.close();
      } catch (e) {
        debugPrint('Proxy server health check failed, restarting... ($e)');
        _handleRestart();
      }
    });
  }

  Future<void> _handleRestart() async {
    if (_isAutoRestarting) return;
    _isAutoRestarting = true;
    
    try {
      await _server?.stop();
      await _startServer();
      debugPrint('Proxy server successfully restarted by watchdog');
    } catch (e) {
      debugPrint('Watchdog failed to restart proxy server: $e');
    } finally {
      _isAutoRestarting = false;
    }
  }

  /// Sync filter settings to the proxy server
  Future<void> syncFilterSettings() async {
    try {
      final uri = Uri.parse('http://127.0.0.1:8080/api/filter');
      final client = HttpClient();
      final request = await client.postUrl(uri);
      request.headers.contentType = ContentType.json;
      request.write(jsonEncode({
        'enable_js': _settings.enableJs,
        'enable_css': _settings.enableCss,
        'enable_img': _settings.enableImg,
        'enable_other': _settings.enableOther
      }));
      await request.close();
      client.close();
    } catch (e) {
      debugPrint('Failed to sync filter settings: $e');
    }
  }
}

class AkariProxyApp extends StatelessWidget {
  final AkariSettings initialSettings;

  const AkariProxyApp({super.key, required this.initialSettings});

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
      home: ProxyHomePage(initialSettings: initialSettings),
    );
  }
}

class ProxyHomePage extends StatefulWidget {
  final AkariSettings initialSettings;

  const ProxyHomePage({super.key, required this.initialSettings});

  @override
  State<ProxyHomePage> createState() => _ProxyHomePageState();
}

class _ProxyHomePageState extends State<ProxyHomePage> {
  // Windows WebView
  final _windowsController = ww.WebviewController();
  // Android/iOS WebView
  late final wf.WebViewController _androidController;
  
  final _urlController = TextEditingController();
  bool _isWebViewReady = false;
  String _currentUrl = '';
  bool _isLoading = false;
  bool _settingsOpen = false;
  bool _monitoringOpen = false;

  // Settings state
  late AkariSettings _settings;
  late TextEditingController _remoteHostController;
  late TextEditingController _remotePortController;
  late TextEditingController _pskController;
  bool _isReconnecting = false;

  @override
  void initState() {
    super.initState();
    _settings = widget.initialSettings;
    _remoteHostController = TextEditingController(text: _settings.remoteHost);
    _remotePortController = TextEditingController(text: _settings.remotePort.toString());
    _pskController = TextEditingController(text: _settings.pskAsString);
    _initWebView();
    _initTray();
  }

  Future<void> _initTray() async {
    if (!Platform.isWindows) return;

    await trayManager.setIcon('lib/src/server/static/favicon.ico');
    
    List<MenuItem> items = [
      MenuItem(
        key: 'show_window',
        label: 'ウィンドウを表示',
      ),
      MenuItem.separator(),
      MenuItem(
        key: 'exit_app',
        label: '終了',
      ),
    ];
    await trayManager.setContextMenu(Menu(items: items));
    trayManager.addListener(TrayListenerImpl());
  }



  Future<void> _initWebView() async {
    try {
      if (Platform.isWindows) {
        await _initWindowsWebView();
      } else {
        await _initAndroidWebView();
      }
    } catch (e) {
      debugPrint('WebView initialization error: $e');
    }
  }

  Future<void> _initWindowsWebView() async {
    await _windowsController.initialize();
    
    _windowsController.url.listen((url) {
      _handleUrlChanged(url);
    });

    _windowsController.loadingState.listen((state) {
      final loading = state == ww.LoadingState.loading;
      if (_isLoading != loading) {
        setState(() => _isLoading = loading);
      }
    });

    await Future.delayed(const Duration(milliseconds: 500));
    await _windowsController.loadUrl('http://127.0.0.1:8080/');
    
    setState(() {
      _isWebViewReady = true;
    });
  }

  Future<void> _initAndroidWebView() async {
    _androidController = wf.WebViewController()
      ..setJavaScriptMode(wf.JavaScriptMode.unrestricted)
      ..setBackgroundColor(const Color(0x00000000))
      ..setNavigationDelegate(
        wf.NavigationDelegate(
          onProgress: (int progress) {
            // Update loading bar.
          },
          onPageStarted: (String url) {
            setState(() => _isLoading = true);
            _handleUrlChanged(url);
          },
          onPageFinished: (String url) {
            setState(() => _isLoading = false);
          },
          onWebResourceError: (wf.WebResourceError error) {},
          onNavigationRequest: (wf.NavigationRequest request) {
            final url = request.url;
            if (!url.startsWith('http://127.0.0.1:8080/') && 
                !url.startsWith('http://localhost:8080/') &&
                url.startsWith('http')) {
              debugPrint('Detected external navigation: $url');
              final proxyUrl = 'http://127.0.0.1:8080/${Uri.encodeComponent(url)}';
              _androidController.loadRequest(Uri.parse(proxyUrl));
              return wf.NavigationDecision.prevent;
            }
            return wf.NavigationDecision.navigate;
          },
        ),
      );

    await _androidController.loadRequest(Uri.parse('http://127.0.0.1:8080/'));
    
    setState(() {
      _isWebViewReady = true;
    });
  }

  void _handleUrlChanged(String url) {
    // Detect navigation away from localhost and redirect through proxy (for Windows listener)
    if (Platform.isWindows) {
      if (!url.startsWith('http://127.0.0.1:8080/') && 
          !url.startsWith('http://localhost:8080/') &&
          url.startsWith('http')) {
        debugPrint('Detected external navigation: $url');
        final proxyUrl = 'http://127.0.0.1:8080/${Uri.encodeComponent(url)}';
        _windowsController.loadUrl(proxyUrl);
        return;
      }
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
  }

  void _navigateToUrl() {
    final input = _urlController.text.trim();
    if (input.isEmpty) return;

    String url = input;
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      url = 'https://$url';
    }

    final proxyUrl = 'http://127.0.0.1:8080/${Uri.encodeComponent(url)}';
    if (Platform.isWindows) {
      _windowsController.loadUrl(proxyUrl);
    } else {
      _androidController.loadRequest(Uri.parse(proxyUrl));
    }
  }

  void _goBack() {
    if (Platform.isWindows) {
      _windowsController.goBack();
    } else {
      _androidController.goBack();
    }
  }

  void _goForward() {
    if (Platform.isWindows) {
      _windowsController.goForward();
    } else {
      _androidController.goForward();
    }
  }

  void _reload() {
    if (Platform.isWindows) {
      _windowsController.reload();
    } else {
      _androidController.reload();
    }
  }

  void _goHome() {
    final homeUrl = 'http://127.0.0.1:8080/';
    if (Platform.isWindows) {
      _windowsController.loadUrl(homeUrl);
    } else {
      _androidController.loadRequest(Uri.parse(homeUrl));
    }
    _urlController.clear();
  }

  void _toggleSettings() {
    setState(() {
      _settingsOpen = !_settingsOpen;
      if (_settingsOpen) _monitoringOpen = false;
    });
  }

  void _toggleMonitoring() {
    setState(() {
      _monitoringOpen = !_monitoringOpen;
      if (_monitoringOpen) _settingsOpen = false;
    });
  }

  Future<void> _saveAndReconnect() async {
    final host = _remoteHostController.text.trim();
    final port = int.tryParse(_remotePortController.text.trim()) ?? 9000;
    final pskString = _pskController.text.trim();

    if (host.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('リモートホストを入力してください')),
      );
      return;
    }

    if (pskString.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('PSKを入力してください')),
      );
      return;
    }

    setState(() {
      _isReconnecting = true;
    });

    try {
      // Update settings with all fields including PSK
      _settings = _settings.copyWith(
        remoteHost: host,
        remotePort: port,
        psk: AkariSettings.pskFromString(pskString),
      );

      // Save settings
      await _settingsService.save(_settings);

      // Update ProxyManager
      await _proxyManager?.updateSettings(_settings);

      // Sync filter settings
      await _proxyManager?.syncFilterSettings();

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('接続先を ${_settings.remoteHost}:${_settings.remotePort} に変更しました'),
            backgroundColor: Colors.green.shade700,
          ),
        );
        setState(() {
          _settingsOpen = false;
        });
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('接続エラー: $e'),
            backgroundColor: Colors.red.shade700,
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() {
          _isReconnecting = false;
        });
      }
    }
  }

  /// Sync filter settings to the local proxy server via API.
  Future<void> _syncFilterSettings() async {
    try {
      final uri = Uri.parse('http://127.0.0.1:8080/api/filter');
      final client = HttpClient();
      final request = await client.postUrl(uri);
      request.headers.contentType = ContentType.json;
      request.write('{"enable_js":${_settings.enableJs},"enable_css":${_settings.enableCss},"enable_img":${_settings.enableImg},"enable_other":${_settings.enableOther}}');
      await request.close();
      client.close();
    } catch (e) {
      debugPrint('Failed to sync filter settings: $e');
    }
  }

  /// Toggle a filter setting and save.
  void _toggleFilter(String key, bool value) {
    setState(() {
      switch (key) {
        case 'enableJs':
          _settings = _settings.copyWith(enableJs: value);
          break;
        case 'enableCss':
          _settings = _settings.copyWith(enableCss: value);
          break;
        case 'enableImg':
          _settings = _settings.copyWith(enableImg: value);
          break;
        case 'enableOther':
          _settings = _settings.copyWith(enableOther: value);
          break;
        case 'useEncryption':
          _settings = _settings.copyWith(useEncryption: value);
          break;
        case 'useSystemProxy':
          _settings = _settings.copyWith(useSystemProxy: value);
          break;
      }
    });

    _settingsService.save(_settings);
    
    // Update settings in ProxyManager as well
    _proxyManager?.updateSettings(_settings).then((_) {
      _proxyManager?.syncFilterSettings();
    });
  }

  @override
  void dispose() {
    _windowsController.dispose();
    _urlController.dispose();
    _remoteHostController.dispose();
    _remotePortController.dispose();
    _pskController.dispose();
    super.dispose();
  }

  Widget _buildMonitoringPanelContent() {
    return Container(
      decoration: BoxDecoration(
        color: const Color(0xFF1A1A1A),
        border: Border(
          right: BorderSide(
            color: Colors.white.withOpacity(0.1),
          ),
        ),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.5),
            blurRadius: 20,
            spreadRadius: 5,
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              border: Border(
                bottom: BorderSide(
                  color: Colors.white.withOpacity(0.1),
                ),
              ),
            ),
            child: Row(
              children: [
                const Icon(
                  Icons.analytics,
                  color: Color(0xFFF3C45C),
                  size: 24,
                ),
                const SizedBox(width: 12),
                const Text(
                  'モニタリング',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const Spacer(),
                IconButton(
                  icon: const Icon(Icons.close, size: 20),
                  color: Colors.white70,
                  onPressed: _toggleMonitoring,
                ),
              ],
            ),
          ),
          const Expanded(child: MonitoringView()),
        ],
      ),
    );
  }

  Widget _buildSettingsPanelContent() {
    return Container(
      decoration: BoxDecoration(
        color: const Color(0xFF1A1A1A),
        border: Border(
          left: BorderSide(
            color: Colors.white.withOpacity(0.1),
          ),
        ),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.5),
            blurRadius: 20,
            spreadRadius: 5,
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              border: Border(
                bottom: BorderSide(
                  color: Colors.white.withOpacity(0.1),
                ),
              ),
            ),
            child: Row(
              children: [
                const Icon(
                  Icons.settings,
                  color: Color(0xFFF3C45C),
                  size: 24,
                ),
                const SizedBox(width: 12),
                const Text(
                  'AKARI 設定',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const Spacer(),
                IconButton(
                  icon: const Icon(Icons.close, size: 20),
                  color: Colors.white70,
                  onPressed: _toggleSettings,
                ),
              ],
            ),
          ),
                  // Settings content
                  Expanded(
                    child: SingleChildScrollView(
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          // Remote Proxy Section
                          Text(
                            'リモートプロキシ',
                            style: TextStyle(
                              color: Colors.white.withOpacity(0.6),
                              fontSize: 12,
                              letterSpacing: 1.2,
                            ),
                          ),
                          const SizedBox(height: 12),
                          // Host input
                          _buildInputField(
                            controller: _remoteHostController,
                            label: 'ホスト / IP アドレス',
                            hint: '127.0.0.1',
                            icon: Icons.dns,
                          ),
                          const SizedBox(height: 12),
                          // Port input
                          _buildInputField(
                            controller: _remotePortController,
                            label: 'ポート',
                            hint: '9000',
                            icon: Icons.numbers,
                            keyboardType: TextInputType.number,
                          ),
                          const SizedBox(height: 12),
                          // PSK input
                          _buildInputField(
                            controller: _pskController,
                            label: 'PSK (事前共有鍵)',
                            hint: 'test-psk-0000-test',
                            icon: Icons.key,
                          ),
                          const SizedBox(height: 16),
                          // Connection status
                          Container(
                            padding: const EdgeInsets.all(12),
                            decoration: BoxDecoration(
                              color: Colors.black.withOpacity(0.3),
                              borderRadius: BorderRadius.circular(12),
                              border: Border.all(
                                color: Colors.white.withOpacity(0.1),
                              ),
                            ),
                            child: Row(
                              children: [
                                Container(
                                  width: 8,
                                  height: 8,
                                  decoration: BoxDecoration(
                                    shape: BoxShape.circle,
                                    color: _proxyManager?.isRunning == true
                                        ? Colors.green
                                        : Colors.red,
                                    boxShadow: [
                                      BoxShadow(
                                        color: (_proxyManager?.isRunning == true
                                                ? Colors.green
                                                : Colors.red)
                                            .withOpacity(0.5),
                                        blurRadius: 6,
                                        spreadRadius: 2,
                                      ),
                                    ],
                                  ),
                                ),
                                const SizedBox(width: 12),
                                Expanded(
                                  child: Text(
                                    '${_settings.remoteHost}:${_settings.remotePort}',
                                    style: const TextStyle(
                                      color: Colors.white70,
                                      fontSize: 13,
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),
                          const SizedBox(height: 16),
                          // Save button
                          SizedBox(
                            width: double.infinity,
                            child: ElevatedButton(
                              onPressed: _isReconnecting ? null : _saveAndReconnect,
                              style: ElevatedButton.styleFrom(
                                backgroundColor: const Color(0xFFF3C45C),
                                foregroundColor: const Color(0xFF0A0A0A),
                                padding: const EdgeInsets.symmetric(vertical: 14),
                                shape: RoundedRectangleBorder(
                                  borderRadius: BorderRadius.circular(12),
                                ),
                              ),
                              child: _isReconnecting
                                  ? const SizedBox(
                                      width: 20,
                                      height: 20,
                                      child: CircularProgressIndicator(
                                        strokeWidth: 2,
                                        color: Color(0xFF0A0A0A),
                                      ),
                                    )
                                  : const Text(
                                      '保存して再接続',
                                      style: TextStyle(
                                        fontWeight: FontWeight.bold,
                                        fontSize: 14,
                                      ),
                                    ),
                            ),
                          ),
                          const SizedBox(height: 28),
                          // Divider
                          Divider(color: Colors.white.withOpacity(0.1)),
                          const SizedBox(height: 20),
                          // Content Filter Section
                          Text(
                            'コンテンツフィルター',
                            style: TextStyle(
                              color: Colors.white.withOpacity(0.6),
                              fontSize: 12,
                              letterSpacing: 1.2,
                            ),
                          ),
                          const SizedBox(height: 16),
                          // Filter toggles
                          _buildToggleSwitch(
                            label: 'JavaScript',
                            description: 'script / module の読み込み',
                            value: _settings.enableJs,
                            onChanged: (v) => _toggleFilter('enableJs', v),
                          ),
                          const SizedBox(height: 8),
                          _buildToggleSwitch(
                            label: 'CSS',
                            description: 'スタイルシートの読み込み',
                            value: _settings.enableCss,
                            onChanged: (v) => _toggleFilter('enableCss', v),
                          ),
                          const SizedBox(height: 8),
                          _buildToggleSwitch(
                            label: '画像 (IMG)',
                            description: '画像リソースの取得',
                            value: _settings.enableImg,
                            onChanged: (v) => _toggleFilter('enableImg', v),
                          ),
                          const SizedBox(height: 8),
                          _buildToggleSwitch(
                            label: 'その他',
                            description: 'その他のリソース',
                            value: _settings.enableOther,
                            onChanged: (v) => _toggleFilter('enableOther', v),
                          ),
                          const SizedBox(height: 20),
                          // Divider
                          Divider(color: Colors.white.withOpacity(0.1)),
                          const SizedBox(height: 20),
                          // Encryption Section
                          Text(
                            'セキュリティ',
                            style: TextStyle(
                              color: Colors.white.withOpacity(0.6),
                              fontSize: 12,
                              letterSpacing: 1.2,
                            ),
                          ),
                          const SizedBox(height: 16),
                          _buildToggleSwitch(
                            label: '暗号化 (Encrypt)',
                            description: 'UDP ペイロードを暗号化',
                            value: _settings.useEncryption,
                            onChanged: (v) => _toggleFilter('useEncryption', v),
                            accentColor: const Color(0xFF4FC3F7),
                          ),
                          const SizedBox(height: 8),
                          if (Platform.isWindows)
                            _buildToggleSwitch(
                              label: 'システムプロキシ',
                              description: 'OS のプロキシ設定を自動更新',
                              value: _settings.useSystemProxy,
                              onChanged: (v) => _toggleFilter('useSystemProxy', v),
                              accentColor: const Color(0xFFA5D6A7),
                            ),
                        ],
                      ),
                    ),
                  ),
                ],
      ),
    );
  }

  Widget _buildInputField({
    required TextEditingController controller,
    required String label,
    required String hint,
    required IconData icon,
    TextInputType keyboardType = TextInputType.text,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: const TextStyle(
            color: Colors.white70,
            fontSize: 13,
          ),
        ),
        const SizedBox(height: 6),
        Container(
          decoration: BoxDecoration(
            color: Colors.black.withOpacity(0.3),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(
              color: Colors.white.withOpacity(0.15),
            ),
          ),
          child: TextField(
            controller: controller,
            keyboardType: keyboardType,
            style: const TextStyle(
              color: Colors.white,
              fontSize: 14,
            ),
            decoration: InputDecoration(
              hintText: hint,
              hintStyle: TextStyle(
                color: Colors.white.withOpacity(0.3),
              ),
              prefixIcon: Icon(
                icon,
                color: Colors.white.withOpacity(0.5),
                size: 20,
              ),
              border: InputBorder.none,
              contentPadding: const EdgeInsets.symmetric(
                horizontal: 12,
                vertical: 14,
              ),
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildToggleSwitch({
    required String label,
    required String description,
    required bool value,
    required ValueChanged<bool> onChanged,
    Color accentColor = const Color(0xFFF3C45C),
  }) {
    return InkWell(
      onTap: () => onChanged(!value),
      borderRadius: BorderRadius.circular(12),
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: Colors.black.withOpacity(0.2),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: value ? accentColor.withOpacity(0.3) : Colors.white.withOpacity(0.1),
          ),
        ),
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    label,
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 14,
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    description,
                    style: TextStyle(
                      color: Colors.white.withOpacity(0.5),
                      fontSize: 12,
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 12),
            Container(
              width: 48,
              height: 28,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(14),
                color: value ? accentColor : Colors.white.withOpacity(0.2),
              ),
              child: AnimatedAlign(
                duration: const Duration(milliseconds: 150),
                alignment: value ? Alignment.centerRight : Alignment.centerLeft,
                child: Container(
                  width: 24,
                  height: 24,
                  margin: const EdgeInsets.symmetric(horizontal: 2),
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: value ? const Color(0xFF0A0A0A) : const Color(0xFF0A0A0A),
                    boxShadow: [
                      BoxShadow(
                        color: Colors.black.withOpacity(0.3),
                        blurRadius: 4,
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0A0A0A),
      body: Stack(
        children: [
          // Main content
          Column(
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
                              contentPadding: const EdgeInsets.symmetric(horizontal: 16),
                            ),
                            onSubmitted: (url) {
                              if (url.isNotEmpty) {
                                _navigateToUrl();
                              }
                            },
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      // Monitoring toggle
                      IconButton(
                        icon: Icon(
                          Icons.analytics,
                          size: 20,
                          color: _monitoringOpen
                              ? const Color(0xFFF3C45C)
                              : Colors.white70,
                        ),
                        onPressed: _toggleMonitoring,
                        tooltip: 'モニタリング',
                      ),
                      const SizedBox(width: 8),
                      // Settings button
                      IconButton(
                        icon: Icon(
                          Icons.settings,
                          size: 20,
                          color: _settingsOpen
                              ? const Color(0xFFF3C45C)
                              : Colors.white70,
                        ),
                        onPressed: _toggleSettings,
                        tooltip: '設定',
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
                    ? (Platform.isWindows
                        ? ww.Webview(_windowsController)
                        : wf.WebViewWidget(controller: _androidController))
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
          
          // Overlay to close side panels when clicking outside
          if (_settingsOpen || _monitoringOpen)
            Positioned.fill(
              child: GestureDetector(
                onTap: () {
                  setState(() {
                    _settingsOpen = false;
                    _monitoringOpen = false;
                  });
                },
                behavior: HitTestBehavior.opaque,
                child: Container(
                  color: Colors.black.withOpacity(0.4), // Darker overlay
                ),
              ),
            ),

          // Monitoring panel (sliding from left)
          AnimatedPositioned(
            duration: const Duration(milliseconds: 250),
            curve: Curves.easeInOut,
            left: _monitoringOpen ? 0 : -350,
            top: 0,
            bottom: 0,
            width: 350,
            child: _buildMonitoringPanelContent(),
          ),

          // Settings panel (sliding from right)
          AnimatedPositioned(
            duration: const Duration(milliseconds: 250),
            curve: Curves.easeInOut,
            right: _settingsOpen ? 0 : -320,
            top: 0,
            bottom: 0,
            width: 320,
            child: _buildSettingsPanelContent(),
          ),
        ],
      ),
    );
  }
}

class TrayListenerImpl extends TrayListener {
  @override
  void onTrayIconMouseDown() {
    windowManager.show();
  }

  @override
  void onTrayMenuItemClick(MenuItem menuItem) {
    if (menuItem.key == 'show_window') {
      windowManager.show();
    } else if (menuItem.key == 'exit_app') {
      exit(0);
    }
  }
}
