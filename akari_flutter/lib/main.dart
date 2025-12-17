import 'dart:io';

import 'package:flutter/material.dart';
import 'package:webview_windows/webview_windows.dart';
import 'package:akari_flutter/src/rust/frb_generated.dart';
import 'package:akari_flutter/src/server/local_server.dart';
import 'package:akari_flutter/src/services/settings_service.dart';

/// Global proxy server instance
LocalProxyServer? _proxyServer;

/// Global settings service
final SettingsService _settingsService = SettingsService();

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await RustLib.init();
  await _settingsService.init();

  // Load saved settings
  final settings = _settingsService.load();

  // Start the local proxy server with saved settings
  _proxyServer = LocalProxyServer(
    ProxyServerConfig(
      host: '127.0.0.1',
      port: 8080,
      remoteHost: settings.remoteHost,
      remotePort: settings.remotePort,
      psk: settings.psk,
      useEncryption: settings.useEncryption,
    ),
  );
  await _proxyServer!.start();

  runApp(AkariProxyApp(initialSettings: settings));
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
  final _webviewController = WebviewController();
  final _urlController = TextEditingController();
  bool _isWebViewReady = false;
  String _currentUrl = '';
  bool _isLoading = false;
  bool _settingsOpen = false;

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

  void _toggleSettings() {
    setState(() {
      _settingsOpen = !_settingsOpen;
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

      // Restart proxy server with new settings
      await _proxyServer?.stop();
      _proxyServer = LocalProxyServer(
        ProxyServerConfig(
          host: '127.0.0.1',
          port: 8080,
          remoteHost: _settings.remoteHost,
          remotePort: _settings.remotePort,
          psk: _settings.psk,
          useEncryption: _settings.useEncryption,
        ),
      );
      await _proxyServer!.start();

      // Sync filter settings to proxy server
      await _syncFilterSettings();

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
      }
    });
    _settingsService.save(_settings);
    _syncFilterSettings();
  }

  @override
  void dispose() {
    _webviewController.dispose();
    _urlController.dispose();
    _remoteHostController.dispose();
    _remotePortController.dispose();
    _pskController.dispose();
    super.dispose();
  }

  Widget _buildSettingsPanel() {
    return AnimatedContainer(
      duration: const Duration(milliseconds: 250),
      curve: Curves.easeInOut,
      width: _settingsOpen ? 320 : 0,
      child: _settingsOpen
          ? Container(
              decoration: BoxDecoration(
                color: const Color(0xFF1A1A1A),
                border: Border(
                  left: BorderSide(
                    color: Colors.white.withOpacity(0.1),
                  ),
                ),
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
                                    color: _proxyServer != null
                                        ? Colors.green
                                        : Colors.red,
                                    boxShadow: [
                                      BoxShadow(
                                        color: (_proxyServer != null
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
                        ],
                      ),
                    ),
                  ),
                ],
              ),
            )
          : const SizedBox.shrink(),
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
      body: Row(
        children: [
          // Main content
          Expanded(
            child: Column(
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
          ),
          // Settings panel
          _buildSettingsPanel(),
        ],
      ),
    );
  }
}
