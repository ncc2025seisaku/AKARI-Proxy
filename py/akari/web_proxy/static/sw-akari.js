// AKARI Web Proxy Service Worker
const proxyBase = self.location.origin + "/";

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
  const proxiedUrl = proxyBase + url;
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
