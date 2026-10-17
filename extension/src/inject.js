// 페이지 쪽(MAIN world)에서 실행: 샤오홍슈가 이미 받아 온 데이터에서 게시물 숫자만 골라
// 같은 탭의 콘텐츠 스크립트로 넘긴다. 요청을 새로 보내거나 외부로 전송하지 않는다.
(() => {
  const TAG = '__REFERENCE_INSIGHT__';
  const pick = (o, ...keys) => {
    for (const k of keys) if (o && o[k] != null) return o[k];
    return undefined;
  };

  // 객체 하나가 게시물이면 필요한 필드만 뽑는다 (snake_case/camelCase 둘 다 대응)
  function toNote(o, fallbackId) {
    const card = pick(o, 'note_card', 'noteCard') || o;
    const info = pick(card, 'interact_info', 'interactInfo');
    if (!info || typeof info !== 'object') return null;
    const id = pick(o, 'id', 'note_id', 'noteId') || pick(card, 'id', 'note_id', 'noteId') || fallbackId;
    if (!id || typeof id !== 'string') return null;
    const user = pick(card, 'user') || {};
    return {
      id,
      title: pick(card, 'display_title', 'displayTitle', 'title') || '',
      author: pick(user, 'nickname', 'nick_name', 'nickName') || '',
      type: pick(card, 'type') || '',
      likes: pick(info, 'liked_count', 'likedCount'),
      collects: pick(info, 'collected_count', 'collectedCount'),
      comments: pick(info, 'comment_count', 'commentCount'),
      shares: pick(info, 'share_count', 'shared_count', 'shareCount', 'sharedCount'),
      time: pick(card, 'time', 'publish_time', 'publishTime'),
      xsecToken: pick(o, 'xsec_token', 'xsecToken') || pick(card, 'xsec_token', 'xsecToken') || '',
    };
  }

  // 응답 JSON 이나 초기 상태를 훑어서 게시물을 찾는다 (순환 참조·과도한 크기 방지)
  function collect(root) {
    const out = [];
    const seen = new WeakSet();
    const stack = [[root, null]];
    let budget = 60000;
    while (stack.length && budget-- > 0) {
      const [v, parentId] = stack.pop();
      if (!v || typeof v !== 'object' || seen.has(v)) continue;
      seen.add(v);
      let note = null;
      try {
        note = toNote(v, parentId);
      } catch (_) {
        /* 읽을 수 없는 프록시 등은 건너뜀 */
      }
      if (note) out.push(note);
      const myId = (typeof v.id === 'string' && v.id) || (typeof v.noteId === 'string' && v.noteId) || parentId;
      let keys = [];
      try {
        keys = Object.keys(v);
      } catch (_) {
        continue;
      }
      for (const k of keys) {
        let child;
        try {
          child = v[k];
        } catch (_) {
          continue;
        }
        if (child && typeof child === 'object') stack.push([child, myId]);
      }
    }
    return out;
  }

  // 콘텐츠 스크립트가 늦게 켜져도 놓치지 않도록, 찾은 게시물을 기억해 뒀다가 다시 보낸다
  const cache = new Map();
  function send(notes) {
    notes.forEach((n) => cache.size < 5000 && cache.set(n.id, {...cache.get(n.id), ...n}));
    if (notes.length) window.postMessage({source: TAG, notes}, window.location.origin);
  }
  window.addEventListener('message', (e) => {
    if (e.source === window && e.data && e.data.source === TAG && e.data.type === 'ready') {
      readInitialState();
      send([...cache.values()]);
    }
  });

  const isApi = (url) => typeof url === 'string' && url.includes('/api/sns/');

  // fetch 응답 엿보기 (응답 사본을 읽을 뿐, 원래 동작은 그대로)
  const origFetch = window.fetch;
  window.fetch = async function (...args) {
    const res = await origFetch.apply(this, args);
    try {
      const url = typeof args[0] === 'string' ? args[0] : args[0] && args[0].url;
      if (isApi(url) && (res.headers.get('content-type') || '').includes('json')) {
        res.clone().json().then((j) => send(collect(j))).catch(() => {});
      }
    } catch (_) {
      /* 무시 */
    }
    return res;
  };

  // XHR 응답 엿보기
  const origOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.__riUrl = url;
    return origOpen.call(this, method, url, ...rest);
  };
  const origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function (...args) {
    if (isApi(String(this.__riUrl))) {
      this.addEventListener('load', () => {
        try {
          const body = this.responseType === 'json' ? this.response : JSON.parse(this.responseText);
          send(collect(body));
        } catch (_) {
          /* JSON 이 아니면 무시 */
        }
      });
    }
    return origSend.apply(this, args);
  };

  // 첫 화면 데이터(서버가 HTML 에 넣어 준 초기 상태)
  function readInitialState() {
    if (window.__INITIAL_STATE__) send(collect(window.__INITIAL_STATE__));
  }
  document.addEventListener('DOMContentLoaded', readInitialState);
  setTimeout(readInitialState, 2000);
})();
