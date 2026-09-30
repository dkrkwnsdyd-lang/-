// 서비스 워커: 앱 화면(껍데기)만 저장해서 빠르게 열고, 데이터/영상은 항상 서버에서 받는다.
const VERSION = "v1";
const SHELL = `shell-${VERSION}`;
const ASSETS = ["/manifest.webmanifest", "/icons/icon-192.png", "/icons/icon-512.png", "/icons/apple-touch-icon.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== SHELL).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin) return;
  // API, 영상, 로그인은 절대 저장하지 않는다 (개인 데이터/크레딧 보호)
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/outputs/") || url.pathname.startsWith("/login")) return;

  if (url.pathname.startsWith("/icons/") || url.pathname === "/manifest.webmanifest") {
    e.respondWith(caches.match(req).then((hit) => hit || fetch(req)));
    return;
  }
  if (req.mode === "navigate") {   // 화면: 네트워크 우선, 오프라인이면 마지막으로 본 화면
    e.respondWith(
      fetch(req).then((res) => {
        if (res.ok && res.type === "basic") { const copy = res.clone(); caches.open(SHELL).then((c) => c.put("/", copy)); }
        return res;
      }).catch(() => caches.match("/").then((hit) => hit || new Response("오프라인입니다. 인터넷에 연결해 주세요.", { status: 503, headers: { "Content-Type": "text/plain; charset=utf-8" } })))
    );
  }
});
