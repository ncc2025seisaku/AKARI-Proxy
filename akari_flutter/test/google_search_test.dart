import 'package:akari_flutter/src/server/rewriter.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  const testConfig = ProxyRewriterConfig(
    proxyBase: 'http://127.0.0.1:8080/',
    useEncryption: false,
  );

  group('Google Search Redirects', () {
    const googleBase = 'https://www.google.com/';

    test('Absolute redirect', () {
      const location = 'https://www.google.co.jp/search?q=test';
      final result = rewriteLocationHeader(location, googleBase, testConfig);

      // Should be proxied
      expect(result, isNot(contains('https://www.google.co.jp')));
      expect(result, startsWith('http://127.0.0.1:8080/'));
      expect(result, contains(Uri.encodeComponent(location)));
    });

    test('Relative redirect', () {
      const location = '/search?q=test&hl=ja';
      final result = rewriteLocationHeader(location, googleBase, testConfig);

      // Should be resolved to absolute URL and then proxied
      final expectedTarget = 'https://www.google.com/search?q=test&hl=ja';
      expect(result, startsWith('http://127.0.0.1:8080/'));
      expect(result, contains(Uri.encodeComponent(expectedTarget)));
    });

    test('Protocol-relative redirect', () {
      const location = '//www.google.co.uk/search?q=test';
      final result = rewriteLocationHeader(location, googleBase, testConfig);

      // Should be resolved to https and then proxied
      final expectedTarget = 'https://www.google.co.uk/search?q=test';
      expect(result, startsWith('http://127.0.0.1:8080/'));
      expect(result, contains(Uri.encodeComponent(expectedTarget)));
    });

    test('Redirect loop prevention (already proxied)', () {
      // Simulate what might happen if the server redirects back to the proxy URL
      const location =
          'http://127.0.0.1:8080/https%3A%2F%2Fwww.google.com%2Fsearch%3Fq%3Dtest';
      final result = rewriteLocationHeader(location, googleBase, testConfig);

      // Should remain as is, not double-proxied
      expect(result, location);
      expect(result, isNot(contains(Uri.encodeComponent(location))));
    });
  });
}
