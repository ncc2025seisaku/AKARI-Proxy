// Basic widget test for AKARI Proxy Flutter app
//
// NOTE: Full AkariProxyApp widget tests require WebView platform implementation
// which is not available in the unit test environment. These tests focus on
// testable components that don't require platform plugins.

import 'package:flutter_test/flutter_test.dart';
import 'package:akari_flutter/src/services/settings_service.dart';

void main() {
  group('AkariSettings', () {
    test('can be created with required parameters', () {
      final settings = AkariSettings(
        remoteHost: '127.0.0.1',
        remotePort: 9000,
        psk: [1, 2, 3, 4],
        useEncryption: false,
        enableJs: true,
        enableCss: true,
        enableImg: true,
        enableOther: true,
      );

      expect(settings.remoteHost, equals('127.0.0.1'));
      expect(settings.remotePort, equals(9000));
      expect(settings.psk, equals([1, 2, 3, 4]));
      expect(settings.useEncryption, isFalse);
      expect(settings.enableJs, isTrue);
    });

    test('copyWith creates new instance with updated values', () {
      final settings = AkariSettings(
        remoteHost: '127.0.0.1',
        remotePort: 9000,
        psk: [1, 2, 3, 4],
        useEncryption: false,
        enableJs: true,
        enableCss: true,
        enableImg: true,
        enableOther: true,
      );

      final updatedSettings = settings.copyWith(
        remoteHost: '192.168.1.1',
        remotePort: 8080,
      );

      expect(updatedSettings.remoteHost, equals('192.168.1.1'));
      expect(updatedSettings.remotePort, equals(8080));
      // Unchanged values should be preserved
      expect(updatedSettings.psk, equals([1, 2, 3, 4]));
      expect(updatedSettings.useEncryption, isFalse);
    });

    test('pskAsString converts PSK bytes to string', () {
      final settings = AkariSettings(
        remoteHost: '127.0.0.1',
        remotePort: 9000,
        psk: [116, 101, 115, 116], // "test" in ASCII
        useEncryption: false,
        enableJs: true,
        enableCss: true,
        enableImg: true,
        enableOther: true,
      );

      expect(settings.pskAsString, equals('test'));
    });

    test('pskFromString converts string to PSK bytes', () {
      final psk = AkariSettings.pskFromString('test');
      expect(psk, equals([116, 101, 115, 116]));
    });
  });
}
