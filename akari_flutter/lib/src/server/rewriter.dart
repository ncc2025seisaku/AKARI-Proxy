/// URL rewriting utilities for the AKARI local proxy.
///
/// This module provides functions to rewrite HTML, CSS, and JavaScript content
/// to route all URLs through the local proxy.
library;

import 'dart:io';

/// Proxy URL generator configuration.
class ProxyRewriterConfig {
  final String proxyBase;
  final bool useEncryption;

  const ProxyRewriterConfig({
    required this.proxyBase,
    this.useEncryption = false,
  });
}

/// Rewrite HTML content to route URLs through the proxy.
///
/// Handles:
/// - href, src, action attributes
/// - srcset attributes
/// - meta http-equiv="refresh" tags
/// - Injects service worker registration and runtime rewrite scripts
String rewriteHtmlToProxy(
  String html,
  String sourceUrl,
  ProxyRewriterConfig config,
) {
  var text = html;
  final baseUrl = sourceUrl;

  // Rewrite href/src/action attributes
  // Pattern: (href|src|action)="..." or '...'
  final attrPattern = RegExp(
    r'''(\b(?:href|src|action)\s*=\s*["'])([^"']+)''',
    caseSensitive: false,
  );
  text = text.replaceAllMapped(attrPattern, (m) {
    final prefix = m.group(1)!;
    final url = m.group(2)!;
    return '$prefix${_toProxyUrl(url, baseUrl, config)}';
  });

  // Rewrite srcset attributes
  final srcsetPattern = RegExp(
    r'''\bsrcset\s*=\s*["']([^"']+)["']''',
    caseSensitive: false,
  );
  text = text.replaceAllMapped(srcsetPattern, (m) {
    final srcset = m.group(1)!;
    final parts = <String>[];
    for (final entry in srcset.split(',')) {
      final trimmed = entry.trim();
      if (trimmed.isEmpty) continue;
      final tokens = trimmed.split(RegExp(r'\s+'));
      if (tokens.isEmpty) continue;
      final url = tokens[0];
      final rest = tokens.skip(1).join(' ');
      final rewritten = _toProxyUrl(url, baseUrl, config);
      parts.add('$rewritten${rest.isNotEmpty ? ' $rest' : ''}');
    }
    return 'srcset="${parts.join(', ')}"';
  });

  // Rewrite meta refresh tags
  final metaRefreshPattern = RegExp(
    r'''(<meta\s+[^>]*http-equiv\s*=\s*["']refresh["'][^>]*content\s*=\s*["'])([^"']+)''',
    caseSensitive: false,
  );
  text = text.replaceAllMapped(metaRefreshPattern, (m) {
    final prefix = m.group(1)!;
    final content = m.group(2)!;
    final parts = content.split(';');
    if (parts.length == 2) {
      final delay = parts[0].trim();
      final urlPart = parts[1].trim();
      if (urlPart.toLowerCase().startsWith('url=')) {
        final urlLiteral = urlPart.substring(4).trim();
        var proxied = _toProxyUrl(urlLiteral, baseUrl, config);
        final sep = proxied.contains('?') ? '&' : '?';
        proxied = '$proxied${sep}_akari_ref=1';
        return '$prefix$delay;url=$proxied';
      }
    }
    return m.group(0)!;
  });

  // Service worker registration and runtime rewrite scripts
  final swPath = config.useEncryption ? '/sw-akari.js?enc=1' : '/sw-akari.js';
  final registrationSnippet = '''
<script>(function(){
if('serviceWorker' in navigator){
navigator.serviceWorker.register('$swPath',{scope:'/'}).catch(()=>{});
}
})();</script>''';

  final runtimeRewriteSnippet = '''
<script>(function(){
const proxy=location.origin+'/';
const enc=/[?&]enc=1(?:&|\$)/.test(location.search)||document.cookie.includes('akari_enc=1');
let base=null;try{base=decodeURIComponent(location.pathname.slice(1));}catch(e){}
const invalid=/^(?:data:|javascript:|mailto:|#)/i;
function toProxy(u){
if(!u||invalid.test(u)||u.startsWith(proxy))return null;
if(u.startsWith('//'))u='https:'+u;
try{const abs=base?new URL(u,base).href:new URL(u).href;
let p=proxy+encodeURIComponent(abs);
if(enc&&p.indexOf('?')===-1)p+='?enc=1';
return p;}catch(e){return null;}
}
function rewrite(el,attr){const v=el.getAttribute(attr);const p=toProxy(v);if(p)el.setAttribute(attr,p);}
function scan(root){root.querySelectorAll('a[href],form[action],img[src],script[src],link[href],iframe[src]').forEach(el=>{rewrite(el,el.hasAttribute('href')?'href':'src');});}
function onClick(e){const a=e.target.closest&&e.target.closest('a[href]');if(!a)return;const p=toProxy(a.getAttribute('href'));if(p){e.preventDefault();location.assign(p);}}
function onSubmit(e){const f=e.target.closest&&e.target.closest('form[action]');if(!f)return;const p=toProxy(f.getAttribute('action'));if(p)f.action=p;}
scan(document);
document.addEventListener('click',onClick,true);
document.addEventListener('submit',onSubmit,true);
new MutationObserver(ms=>{ms.forEach(m=>m.addedNodes.forEach(n=>{if(n.nodeType===1)scan(n);}));}).observe(document.documentElement,{childList:true,subtree:true});
})();</script>''';

  text += registrationSnippet + runtimeRewriteSnippet;

  return text;
}

/// Rewrite CSS content to route url() references through the proxy.
String rewriteCssToProxy(
  String css,
  String sourceUrl,
  ProxyRewriterConfig config,
) {
  final baseUrl = sourceUrl;
  // Matches url("..."), url('...'), or url(...)
  final pattern = RegExp(
    r'''url\(\s*(['"]?)(.+?)\1\s*\)''',
    caseSensitive: false,
  );
  return css.replaceAllMapped(pattern, (m) {
    final quote = m.group(1) ?? '';
    final url = m.group(2) ?? '';
    if (url.isEmpty) return m.group(0)!;
    final rewritten = _toProxyUrl(url, baseUrl, config);
    return 'url($quote$rewritten$quote)';
  });
}

/// Rewrite JavaScript content to route fetch/import URLs through the proxy.
String rewriteJsToProxy(
  String js,
  String sourceUrl,
  ProxyRewriterConfig config,
) {
  var text = js;
  final baseUrl = sourceUrl;

  // fetch('...')
  final fetchPattern = RegExp(
    r'''(fetch\s*\(\s*)(['"])([^'"]+)(['"])''',
    caseSensitive: false,
  );
  text = text.replaceAllMapped(fetchPattern, (m) {
    return '${m.group(1)}${m.group(2)}${_toProxyUrl(m.group(3)!, baseUrl, config)}${m.group(4)}';
  });

  // Dynamic import('...')
  final dynImportPattern = RegExp(
    r'''(import\s*\(\s*)(['"])([^'"]+)(['"])(\s*\))''',
    caseSensitive: false,
  );
  text = text.replaceAllMapped(dynImportPattern, (m) {
    return '${m.group(1)}${m.group(2)}${_toProxyUrl(m.group(3)!, baseUrl, config)}${m.group(4)}${m.group(5)}';
  });

  // Static import ... from '...';
  final staticImportPattern = RegExp(
    r'''(from\s+)(['"])([^'"]+)(['"])''',
    caseSensitive: false,
  );
  text = text.replaceAllMapped(staticImportPattern, (m) {
    return '${m.group(1)}${m.group(2)}${_toProxyUrl(m.group(3)!, baseUrl, config)}${m.group(4)}';
  });

  // Bare import '...';
  final bareImportPattern = RegExp(
    r'''(^|\s)(import\s+)(['"])([^'"]+)(['"])''',
    caseSensitive: false,
  );
  text = text.replaceAllMapped(bareImportPattern, (m) {
    return '${m.group(1)}${m.group(2)}${m.group(3)}${_toProxyUrl(m.group(4)!, baseUrl, config)}${m.group(5)}';
  });

  return text;
}

/// Convert a URL to a proxied URL.
String _toProxyUrl(String url, String baseUrl, ProxyRewriterConfig config) {
  if (url.isEmpty) return url;
  
  // Skip data:, javascript:, mailto:, anchors
  if (RegExp(r'^(?:data:|javascript:|mailto:|#)', caseSensitive: false).hasMatch(url)) {
    return url;
  }
  
  // Already proxied
  if (url.startsWith(config.proxyBase)) {
    return url;
  }

  // Protocol-relative URL
  if (url.startsWith('//')) {
    url = 'https:$url';
  }

  // Resolve relative URLs
  if (!url.startsWith('http://') && !url.startsWith('https://')) {
    try {
      final base = Uri.parse(baseUrl);
      url = base.resolve(url).toString();
    } catch (_) {
      return url;
    }
  }

  // Encode and create proxy URL
  final encoded = Uri.encodeComponent(url);
  var proxied = '${config.proxyBase}$encoded';

  // Add encryption parameter if needed
  if (config.useEncryption && !proxied.contains('?')) {
    proxied = '$proxied?enc=1';
  }

  return proxied;
}

/// Rewrite Location header to route through proxy.
String rewriteLocationHeader(
  String location,
  String baseUrl,
  ProxyRewriterConfig config,
) {
  return _toProxyUrl(location, baseUrl, config);
}

/// Decompress response body if Content-Encoding is set.
/// Returns (decompressed body, success flag).
(List<int>, bool) maybeDecompress(List<int> body, Map<String, String> headers) {
  final encoding = headers['Content-Encoding']?.toLowerCase() ?? 
                   headers['content-encoding']?.toLowerCase() ?? '';
  
  if (encoding.isEmpty) {
    return (body, true);
  }

  try {
    List<int> decompressed;
    switch (encoding) {
      case 'gzip':
        decompressed = gzip.decode(body);
      case 'deflate':
        decompressed = zlib.decode(body);
      default:
        // Unknown encoding, return as-is
        return (body, false);
    }
    // Remove Content-Encoding header after decompression
    headers.remove('Content-Encoding');
    headers.remove('content-encoding');
    return (decompressed, true);
  } catch (_) {
    return (body, false);
  }
}

/// Strip security headers that may interfere with proxy operation.
void stripSecurityHeaders(Map<String, String> headers) {
  final keysToRemove = <String>[];
  for (final key in headers.keys) {
    final lk = key.toLowerCase();
    if (lk == 'content-security-policy' || 
        lk == 'content-security-policy-report-only') {
      keysToRemove.add(key);
    }
  }
  for (final key in keysToRemove) {
    headers.remove(key);
  }
}

/// Content types that should be rewritten.
enum RewriteContentType {
  html,
  css,
  javascript,
  none,
}

/// Determine if content should be rewritten based on Content-Type.
RewriteContentType getRewriteContentType(String contentType) {
  final ct = contentType.split(';').first.trim().toLowerCase();
  
  if (ct.startsWith('text/html')) {
    return RewriteContentType.html;
  }
  if (ct == 'text/css') {
    return RewriteContentType.css;
  }
  if (ct.contains('javascript') || 
      ct == 'application/javascript' || 
      ct == 'application/x-javascript') {
    return RewriteContentType.javascript;
  }
  return RewriteContentType.none;
}
