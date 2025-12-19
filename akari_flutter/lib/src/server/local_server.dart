/// Local HTTP proxy server for AKARI.
///
/// This server runs on localhost and handles HTTP requests by forwarding them
/// through the AKARI-UDP protocol via the Rust backend.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart' show rootBundle;
import 'package:shelf/shelf.dart';
import 'package:shelf/shelf_io.dart' as shelf_io;
import 'package:shelf_router/shelf_router.dart';

import '../rust/api/akari_client.dart';
import '../services/monitoring_service.dart';
import 'rewriter.dart';

/// Configuration for the local proxy server.
class ProxyServerConfig {
  final String host;
  final int port;
  final String remoteHost;
  final int remotePort;
  final List<int> psk;
  final bool useEncryption;

  const ProxyServerConfig({
    this.host = '127.0.0.1',
    this.port = 8080,
    required this.remoteHost,
    required this.remotePort,
    required this.psk,
    this.useEncryption = false,
  });
}

/// Local HTTP proxy server.
class LocalProxyServer {
  final ProxyServerConfig config;
  HttpServer? _server;
  final Router _router = Router();
  AkariClientPool? _clientPool;
  static const int _defaultPoolSize = 4;
  late final ProxyRewriterConfig _rewriterConfig;

  LocalProxyServer(this.config) {
    _rewriterConfig = ProxyRewriterConfig(
      proxyBase: 'http://${config.host}:${config.port}/',
      useEncryption: config.useEncryption,
    );
    _setupRoutes();
  }

  // Content filter state
  bool _enableJs = true;
  bool _enableCss = true;
  bool _enableImg = true;
  bool _enableOther = true;

  void _setupRoutes() {
    // Health check endpoint
    _router.get('/healthz', _handleHealthz);

    // Static files
    _router.get('/', _handleIndex);
    _router.get('/index.html', _handleIndex);
    _router.get('/logo.png', _handleStaticFile);
    _router.get('/favicon.ico', _handleStaticFile);
    _router.get('/sw-akari.js', _handleStaticFile);

    // Filter API
    _router.get('/api/filter', _handleFilterGet);
    _router.post('/api/filter', _handleFilterPost);

    // Proxy endpoints
    _router.get('/proxy', _handleProxy);
    _router.get('/api/proxy', _handleProxy);
    _router.post('/proxy', _handleProxyPost);
    _router.post('/api/proxy', _handleProxyPost);

    // Path-based proxy (catch-all for /{encoded-url})
    _router.get('/<url|.+>', _handlePathProxy);
  }

  /// Handle GET /api/filter - return current filter state
  Response _handleFilterGet(Request request) {
    return Response.ok(
      jsonEncode({
        'enable_js': _enableJs,
        'enable_css': _enableCss,
        'enable_img': _enableImg,
        'enable_other': _enableOther,
      }),
      headers: {'Content-Type': 'application/json; charset=utf-8'},
    );
  }

  /// Handle POST /api/filter - update filter state
  Future<Response> _handleFilterPost(Request request) async {
    try {
      final body = await request.readAsString();
      final data = jsonDecode(body) as Map<String, dynamic>;

      if (data.containsKey('enable_js')) {
        _enableJs = data['enable_js'] == true;
      }
      if (data.containsKey('enable_css')) {
        _enableCss = data['enable_css'] == true;
      }
      if (data.containsKey('enable_img')) {
        _enableImg = data['enable_img'] == true;
      }
      if (data.containsKey('enable_other')) {
        _enableOther = data['enable_other'] == true;
      }

      return Response.ok(
        jsonEncode({
          'enable_js': _enableJs,
          'enable_css': _enableCss,
          'enable_img': _enableImg,
          'enable_other': _enableOther,
        }),
        headers: {'Content-Type': 'application/json; charset=utf-8'},
      );
    } catch (e) {
      return Response(
        400,
        body: jsonEncode({'error': e.toString()}),
        headers: {'Content-Type': 'application/json; charset=utf-8'},
      );
    }
  }

  /// Serve index.html
  Future<Response> _handleIndex(Request request) async {
    return _serveStaticFile('index.html', 'text/html; charset=utf-8');
  }

  /// Serve static files
  Future<Response> _handleStaticFile(Request request) async {
    final path = request.url.path;
    final filename = path.startsWith('/') ? path.substring(1) : path;

    String contentType;
    if (filename.endsWith('.png')) {
      contentType = 'image/png';
    } else if (filename.endsWith('.ico')) {
      contentType = 'image/x-icon';
    } else if (filename.endsWith('.js')) {
      contentType = 'application/javascript; charset=utf-8';
    } else if (filename.endsWith('.html')) {
      contentType = 'text/html; charset=utf-8';
    } else if (filename.endsWith('.css')) {
      contentType = 'text/css; charset=utf-8';
    } else {
      contentType = 'application/octet-stream';
    }

    return _serveStaticFile(filename, contentType);
  }

  Future<Response> _serveStaticFile(String filename, String contentType) async {
    try {
      List<int> body;

      if (Platform.isWindows) {
        // Windows behavior: try to load from local file system
        // Get the directory where this script is located
        final scriptDir = Platform.script.resolve('.').toFilePath();
        // Navigate to lib/src/server/static from the build output
        final staticDir = Directory(
          '${scriptDir}data/flutter_assets/packages/akari_flutter/lib/src/server/static',
        );

        File? file;
        if (await staticDir.exists()) {
          file = File('${staticDir.path}/$filename');
        } else {
          // Development mode - use lib directory directly
          file = File('lib/src/server/static/$filename');
        }

        if (await file.exists()) {
          body = await file.readAsBytes();
        } else {
          return Response.notFound('File not found: $filename');
        }
      } else {
        // Mobile behavior: load from Flutter assets
        // The path in pubspec.yaml is 'lib/src/server/static/'
        final assetPath = 'lib/src/server/static/$filename';
        try {
          final data = await rootBundle.load(assetPath);
          body = data.buffer.asUint8List();
        } catch (e) {
          debugPrint('Asset not found: $assetPath ($e)');
          return Response.notFound('Asset not found: $filename');
        }
      }

      return Response.ok(
        body,
        headers: {
          'Content-Type': contentType,
          'Content-Length': body.length.toString(),
        },
      );
    } catch (e) {
      return Response.internalServerError(
        body: 'Error serving static file: $e',
      );
    }
  }

  /// Start the HTTP server.
  Future<void> start() async {
    // Initialize AkariClientPool for concurrent requests
    _clientPool = await AkariClientPool.newInstance(
      host: config.remoteHost,
      port: config.remotePort,
      psk: config.psk,
      poolSize: BigInt.from(_defaultPoolSize),
    );

    final handler = Pipeline()
        .addMiddleware(logRequests())
        .addMiddleware(_corsMiddleware())
        .addHandler(_router.call);

    _server = await shelf_io.serve(handler, config.host, config.port);
    print(
      'AKARI Local Proxy listening on http://${config.host}:${config.port}',
    );
  }

  /// Stop the HTTP server.
  Future<void> stop() async {
    await _server?.close(force: true);
    _server = null;
    _clientPool = null;
  }

  /// CORS middleware for browser compatibility.
  Middleware _corsMiddleware() {
    return (Handler innerHandler) {
      return (Request request) async {
        if (request.method == 'OPTIONS') {
          return Response.ok('', headers: _corsHeaders);
        }
        final response = await innerHandler(request);
        return response.change(headers: _corsHeaders);
      };
    };
  }

  static const _corsHeaders = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  };

  // ----------------------------- Route Handlers -----------------------------

  Response _handleHealthz(Request request) {
    return Response.ok('ok', headers: {'Content-Type': 'text/plain'});
  }

  Future<Response> _handleProxy(Request request) async {
    final url = request.url.queryParameters['url'];
    if (url == null || url.isEmpty) {
      return Response(
        400,
        body: 'url parameter required',
        headers: {'Content-Type': 'text/plain; charset=utf-8'},
      );
    }
    return await _proxyRequest(request, url);
  }

  Future<Response> _handleProxyPost(Request request) async {
    final contentType = request.headers['content-type'] ?? '';
    String? url;

    if (contentType.contains('application/json')) {
      try {
        final body = await request.readAsString();
        final json = jsonDecode(body) as Map<String, dynamic>;
        url = json['url'] as String?;
      } catch (_) {
        // Ignore JSON parse errors
      }
    } else if (contentType.contains('application/x-www-form-urlencoded')) {
      final body = await request.readAsString();
      final params = Uri.splitQueryString(body);
      url = params['url'];
    }

    url ??= request.url.queryParameters['url'];

    if (url == null || url.isEmpty) {
      return Response(
        400,
        body: 'url parameter required',
        headers: {'Content-Type': 'text/plain; charset=utf-8'},
      );
    }
    return await _proxyRequest(request, url);
  }

  Future<Response> _handlePathProxy(Request request) async {
    final encodedUrl = request.params['url'];
    if (encodedUrl == null || encodedUrl.isEmpty) {
      return Response.notFound('Not Found');
    }

    var url = Uri.decodeComponent(encodedUrl);
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      return Response.notFound('Not Found');
    }

    // Merge query parameters from the proxy URL into the target URL
    // This handles cases like Google redirects that add ?sei=xxx to the proxy URL
    final proxyQuery = request.url.queryParameters;
    if (proxyQuery.isNotEmpty) {
      // Filter out AKARI-specific params
      final targetParams = Map<String, String>.from(proxyQuery)
        ..remove('enc')
        ..remove('_akari_ref');

      if (targetParams.isNotEmpty) {
        final targetUri = Uri.parse(url);
        final mergedParams = Map<String, String>.from(targetUri.queryParameters)
          ..addAll(targetParams);
        url = targetUri.replace(queryParameters: mergedParams).toString();
      }
    }

    return await _proxyRequest(request, url);
  }

  Future<Response> _proxyRequest(Request request, String targetUrl) async {
    try {
      final pool = _clientPool;
      if (pool == null) {
        throw Exception('Client pool not initialized. Call start() first.');
      }

      // Collect headers to forward
      final forwardHeaders = <(String, String)>[];
      request.headers.forEach((key, value) {
        final lowerKey = key.toLowerCase();
        // Skip headers that wreak havoc or are managed by client/transport
        if (lowerKey == 'host' ||
            lowerKey == 'connection' ||
            lowerKey == 'upgrade' ||
            lowerKey == 'content-length' ||
            lowerKey == 'transfer-encoding' ||
            lowerKey == 'keep-alive') {
          return;
        }
        forwardHeaders.add((key, value));
      });

      // Send request via Rust AkariClientPool (automatically uses available client)
      final requestConfig = defaultRequestConfig();
      final akariResponse = await pool.sendRequest(
        url: targetUrl,
        headers: forwardHeaders,
        config: requestConfig,
      );

      // Build response headers
      final headers = <String, String>{
        'X-AKARI-Target': targetUrl,
        'X-AKARI-Status': 'rust-client',
        'X-AKARI-Bytes-Sent': akariResponse.stats.bytesSent.toString(),
        'X-AKARI-Bytes-Received': akariResponse.stats.bytesReceived.toString(),
      };

      // Copy headers from AKARI response
      for (final (name, value) in akariResponse.headers) {
        headers[name] = value;
      }

      // Strip security headers (CSP, etc.)
      stripSecurityHeaders(headers);

      // Remove Transfer-Encoding (we'll return fixed-length content)
      headers.remove('Transfer-Encoding');
      headers.remove('transfer-encoding');

      // Handle Location header redirect
      final location = headers['Location'] ?? headers['location'];
      if (location != null) {
        headers['Location'] = rewriteLocationHeader(
          location,
          targetUrl,
          _rewriterConfig,
        );
        headers.remove('location');
      }

      // Get body and decompress if needed
      var body = akariResponse.body.toList();
      final (decompressedBody, decompressed) = maybeDecompress(body, headers);
      body = decompressedBody;

      // Determine content type and rewrite if needed
      final contentType =
          headers['Content-Type'] ??
          headers['content-type'] ??
          'text/html; charset=utf-8';

      final rewriteType = getRewriteContentType(contentType);

      // Try to rewrite even if decompression failed (failsoft approach)
      // This handles cases where we get uncompressed content or when
      // the encoding is unsupported (like Brotli)
      if (rewriteType != RewriteContentType.none) {
        try {
          switch (rewriteType) {
            case RewriteContentType.html:
              final text = utf8.decode(body, allowMalformed: true);
              // Only rewrite if it looks like valid HTML (contains < character)
              if (text.contains('<')) {
                final rewritten = rewriteHtmlToProxy(
                  text,
                  targetUrl,
                  _rewriterConfig,
                );
                body = utf8.encode(rewritten);
              }
            case RewriteContentType.css:
              final text = utf8.decode(body, allowMalformed: true);
              final rewritten = rewriteCssToProxy(
                text,
                targetUrl,
                _rewriterConfig,
              );
              body = utf8.encode(rewritten);
            case RewriteContentType.javascript:
              final text = utf8.decode(body, allowMalformed: true);
              final rewritten = rewriteJsToProxy(
                text,
                targetUrl,
                _rewriterConfig,
              );
              body = utf8.encode(rewritten);
            case RewriteContentType.none:
              break;
          }
        } catch (_) {
          // If rewriting fails (e.g., binary data), keep original body
        }
      }

      // Update Content-Length
      headers['Content-Length'] = body.length.toString();

      // Set Content-Type if not present
      if (!headers.containsKey('Content-Type') &&
          !headers.containsKey('content-type')) {
        headers['Content-Type'] = 'text/html; charset=utf-8';
      }

      final response = Response(
        akariResponse.statusCode,
        body: body,
        headers: headers,
      );

      // Log to MonitoringService
      MonitoringService().addLog(
        ProxyLogEntry(
          timestamp: DateTime.now(),
          method: 'GET', // Path-based and standard proxy are mostly GET
          url: targetUrl,
          statusCode: akariResponse.statusCode,
          bytesSent: akariResponse.stats.bytesSent.toInt(),
          bytesReceived: akariResponse.stats.bytesReceived.toInt(),
        ),
      );

      return response;
    } catch (e) {
      // Log error
      MonitoringService().addLog(
        ProxyLogEntry(
          timestamp: DateTime.now(),
          method: 'GET',
          url: targetUrl,
          statusCode: 502,
          error: e.toString(),
        ),
      );

      return Response(
        502,
        body: 'Proxy error: $e',
        headers: {'Content-Type': 'text/plain; charset=utf-8'},
      );
    }
  }
}
