// AKARI Web Proxy Service Worker
const selfUrl = new URL(self.location.href);
const encEnabled = selfUrl.searchParams.get("enc") === "1";
const proxyBase = self.location.origin + "/";

self.addEventListener("install", (event) => {
  // 新バージョンを即座に有効化
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  // 既存クライアントにも即時適用
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = req.url;

  // すでにプロキシ経由 or 非HTTP(S)は素通し
  if (url.startsWith(proxyBase) || !(url.startsWith("http://") || url.startsWith("https://"))) {
    return;
  }

  // 同一オリジン相対は素通し
  try {
    const reqUrl = new URL(url);
    if (reqUrl.origin === self.location.origin && !url.startsWith(proxyBase)) {
      return;
    }
  } catch (_e) {
    return;
  }

  // プロキシ経由に書き換え
  // クエリ付き URL をそのままパスに載せると outer query に食われるのでエンコードする
  let proxiedUrl = proxyBase + encodeURIComponent(url);
  if (encEnabled) proxiedUrl += proxiedUrl.includes("?") ? "&enc=1" : "?enc=1";
  const newRequest = new Request(proxiedUrl, {
    method: req.method,
    headers: req.headers,
    body: req.method === "GET" || req.method === "HEAD" ? undefined : req.clone().body,
    mode: "cors",
    credentials: "include",
    redirect: req.redirect,
    referrer: req.referrer,
    referrerPolicy: req.referrerPolicy,
    integrity: req.integrity,
    cache: req.cache,
  });

  event.respondWith(fetch(newRequest));
});
