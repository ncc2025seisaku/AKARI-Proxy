import 'dart:io';

/// Manages Windows System Proxy settings via registry.
class WindowsSystemProxy {
  static const String _registryKey = r'HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings';

  /// Enable system proxy.
  static Future<void> enable(String proxyServer) async {
    if (!Platform.isWindows) return;

    try {
      // Set ProxyEnable to 1
      await Process.run('reg', ['add', _registryKey, '/v', 'ProxyEnable', '/t', 'REG_DWORD', '/d', '1', '/f']);
      // Set ProxyServer
      await Process.run('reg', ['add', _registryKey, '/v', 'ProxyServer', '/t', 'REG_SZ', '/d', proxyServer, '/f']);
      
      // Notify the system that settings have changed (optional but recommended)
      // This is usually done via Win32 API InternetSetOption, but for now we rely on the registry
    } catch (e) {
      print('Failed to enable system proxy: $e');
    }
  }

  /// Disable system proxy.
  static Future<void> disable() async {
    if (!Platform.isWindows) return;

    try {
      // Set ProxyEnable to 0
      await Process.run('reg', ['add', _registryKey, '/v', 'ProxyEnable', '/t', 'REG_DWORD', '/d', '0', '/f']);
    } catch (e) {
      print('Failed to disable system proxy: $e');
    }
  }

  /// Check if system proxy is enabled.
  static Future<bool> isEnabled() async {
    if (!Platform.isWindows) return false;

    try {
      final result = await Process.run('reg', ['query', _registryKey, '/v', 'ProxyEnable']);
      return result.stdout.toString().contains('0x1');
    } catch (_) {
      return false;
    }
  }
}
