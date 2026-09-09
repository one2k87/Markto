// 마크토 서비스워커 — 아이폰 홈화면 설치(PWA)
// 캐시 이름 접두는 반드시 "markto-" : 같은 오리진(one2k87.github.io)에 네 앱이 살아
// 접두 없이 지우면 남의 앱 캐시를 날린다(픽토가 2026-09-09에 실측한 사고).
const CACHE = "markto-v1";

self.addEventListener("message", (e) => {
  if (e.data === "SKIP_WAITING") self.skipWaiting();
});

const ASSETS = [
  "./manifest.json",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
  "./icons/apple-touch-icon.png"
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k.startsWith("markto-") && k !== CACHE)
                      .map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  const isDoc = e.request.mode === "navigate" ||
                url.pathname.endsWith("/") || url.pathname.endsWith(".html");
  const isJson = url.pathname.endsWith(".json");

  // 화면(HTML)·데이터(JSON)는 네트워크 우선 → 새로 올린 버전·핀이 바로 보인다
  if (isDoc || isJson) {
    e.respondWith(
      fetch(e.request).then((r) => {
        const copy = r.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return r;
      }).catch(() => caches.match(e.request))
    );
    return;
  }
  e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request)));
});
