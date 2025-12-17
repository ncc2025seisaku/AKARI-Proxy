// Unit tests for the URL rewriter logic.

import 'package:flutter_test/flutter_test.dart';
import 'package:akari_flutter/src/server/rewriter.dart';

void main() {
  const testConfig = ProxyRewriterConfig(
    proxyBase: 'http://127.0.0.1:8080/',
    useEncryption: false,
  );

  const encryptedConfig = ProxyRewriterConfig(
    proxyBase: 'http://127.0.0.1:8080/',
    useEncryption: true,
  );

  group('HTML rewriting', () {
    test('rewrites href attributes', () {
      const html = '<a href="https://example.com/page">Link</a>';
      final result = rewriteHtmlToProxy(html, 'https://base.com/', testConfig);
      
      expect(result, contains('http://127.0.0.1:8080/https%3A%2F%2Fexample.com%2Fpage'));
    });

    test('rewrites src attributes', () {
      const html = '<img src="https://example.com/image.png">';
      final result = rewriteHtmlToProxy(html, 'https://base.com/', testConfig);
      
      expect(result, contains('http://127.0.0.1:8080/https%3A%2F%2Fexample.com%2Fimage.png'));
    });

    test('resolves relative URLs', () {
      const html = '<a href="/page">Link</a>';
      final result = rewriteHtmlToProxy(html, 'https://example.com/', testConfig);
      
      expect(result, contains('http://127.0.0.1:8080/https%3A%2F%2Fexample.com%2Fpage'));
    });

    test('preserves data: URLs', () {
      const html = '<img src="data:image/png;base64,abc123">';
      final result = rewriteHtmlToProxy(html, 'https://base.com/', testConfig);
      
      expect(result, contains('data:image/png;base64,abc123'));
    });

    test('preserves javascript: URLs', () {
      const html = '<a href="javascript:void(0)">Click</a>';
      final result = rewriteHtmlToProxy(html, 'https://base.com/', testConfig);
      
      expect(result, contains('javascript:void(0)'));
    });

    test('rewrites srcset attributes', () {
      const html = '<img srcset="small.jpg 1x, large.jpg 2x">';
      final result = rewriteHtmlToProxy(html, 'https://example.com/', testConfig);
      
      expect(result, contains('http://127.0.0.1:8080/'));
      expect(result, contains('1x'));
      expect(result, contains('2x'));
    });

    test('injects service worker registration', () {
      const html = '<html><body></body></html>';
      final result = rewriteHtmlToProxy(html, 'https://example.com/', testConfig);
      
      expect(result, contains('serviceWorker'));
      expect(result, contains('/sw-akari.js'));
    });

    test('adds enc=1 to service worker path when encryption enabled', () {
      const html = '<html><body></body></html>';
      final result = rewriteHtmlToProxy(html, 'https://example.com/', encryptedConfig);
      
      expect(result, contains('/sw-akari.js?enc=1'));
    });
  });

  group('CSS rewriting', () {
    test('rewrites url() references', () {
      const css = 'background: url("https://example.com/bg.png");';
      final result = rewriteCssToProxy(css, 'https://base.com/', testConfig);
      
      expect(result, contains('http://127.0.0.1:8080/https%3A%2F%2Fexample.com%2Fbg.png'));
    });

    test('handles unquoted url()', () {
      const css = 'background: url(https://example.com/bg.png);';
      final result = rewriteCssToProxy(css, 'https://base.com/', testConfig);
      
      expect(result, contains('http://127.0.0.1:8080/https%3A%2F%2Fexample.com%2Fbg.png'));
    });

    test('resolves relative URLs in CSS', () {
      const css = 'background: url("../images/bg.png");';
      final result = rewriteCssToProxy(css, 'https://example.com/css/style.css', testConfig);
      
      expect(result, contains('http://127.0.0.1:8080/'));
    });
  });

  group('JavaScript rewriting', () {
    test('rewrites fetch() calls', () {
      const js = "fetch('https://api.example.com/data')";
      final result = rewriteJsToProxy(js, 'https://base.com/', testConfig);
      
      expect(result, contains('http://127.0.0.1:8080/https%3A%2F%2Fapi.example.com%2Fdata'));
    });

    test('rewrites dynamic import()', () {
      const js = "import('https://cdn.example.com/module.js')";
      final result = rewriteJsToProxy(js, 'https://base.com/', testConfig);
      
      expect(result, contains('http://127.0.0.1:8080/https%3A%2F%2Fcdn.example.com%2Fmodule.js'));
    });

    test('rewrites static import from', () {
      const js = "import { foo } from 'https://cdn.example.com/module.js';";
      final result = rewriteJsToProxy(js, 'https://base.com/', testConfig);
      
      expect(result, contains('http://127.0.0.1:8080/https%3A%2F%2Fcdn.example.com%2Fmodule.js'));
    });
  });

  group('Content type detection', () {
    test('detects HTML content type', () {
      expect(getRewriteContentType('text/html'), RewriteContentType.html);
      expect(getRewriteContentType('text/html; charset=utf-8'), RewriteContentType.html);
    });

    test('detects CSS content type', () {
      expect(getRewriteContentType('text/css'), RewriteContentType.css);
    });

    test('detects JavaScript content type', () {
      expect(getRewriteContentType('application/javascript'), RewriteContentType.javascript);
      expect(getRewriteContentType('text/javascript'), RewriteContentType.javascript);
    });

    test('returns none for other types', () {
      expect(getRewriteContentType('image/png'), RewriteContentType.none);
      expect(getRewriteContentType('application/json'), RewriteContentType.none);
    });
  });

  group('Security header stripping', () {
    test('removes CSP headers', () {
      final headers = <String, String>{
        'Content-Type': 'text/html',
        'Content-Security-Policy': "default-src 'self'",
        'X-Custom': 'value',
      };
      
      stripSecurityHeaders(headers);
      
      expect(headers.containsKey('Content-Security-Policy'), isFalse);
      expect(headers.containsKey('Content-Type'), isTrue);
      expect(headers.containsKey('X-Custom'), isTrue);
    });

    test('removes CSP report-only headers', () {
      final headers = <String, String>{
        'Content-Security-Policy-Report-Only': "default-src 'self'",
      };
      
      stripSecurityHeaders(headers);
      
      expect(headers.isEmpty, isTrue);
    });

    test('removes X-Frame-Options headers', () {
      final headers = <String, String>{
        'Content-Type': 'text/html',
        'X-Frame-Options': 'DENY',
      };
      
      stripSecurityHeaders(headers);
      
      expect(headers.containsKey('X-Frame-Options'), isFalse);
      expect(headers.containsKey('Content-Type'), isTrue);
    });

    test('removes all security headers', () {
      final headers = <String, String>{
        'Content-Type': 'text/html',
        'X-Frame-Options': 'DENY',
        'Content-Security-Policy': "default-src 'self'",
        'Strict-Transport-Security': 'max-age=31536000',
        'Cross-Origin-Opener-Policy': 'same-origin',
        'Cross-Origin-Embedder-Policy': 'require-corp',
        'Cross-Origin-Resource-Policy': 'same-origin',
        'X-XSS-Protection': '1; mode=block',
        'X-Content-Type-Options': 'nosniff',
        'Permissions-Policy': 'camera=()',
      };
      
      stripSecurityHeaders(headers);
      
      expect(headers.length, 1);
      expect(headers.containsKey('Content-Type'), isTrue);
    });
  });

  group('Location header rewriting', () {
    test('rewrites absolute URLs', () {
      final result = rewriteLocationHeader(
        'https://example.com/new-page',
        'https://example.com/old-page',
        testConfig,
      );
      
      expect(result, contains('http://127.0.0.1:8080/'));
    });

    test('adds enc=1 when encryption enabled', () {
      final result = rewriteLocationHeader(
        'https://example.com/new-page',
        'https://example.com/old-page',
        encryptedConfig,
      );
      
      expect(result, contains('?enc=1'));
    });
  });
}
