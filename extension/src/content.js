// 콘텐츠 스크립트: 게시물 카드에 배지를 붙이고, 오른쪽에 분석 패널을 띄운다.
(() => {
  const RI = window.RI;
  const TAG = '__REFERENCE_INSIGHT__';
  const ext = globalThis.browser && globalThis.browser.storage ? globalThis.browser : globalThis.chrome;

  const notes = new Map(); // id → 게시물 (지금 보고 있는 페이지에서 모은 것)
  let pageKey = location.pathname + location.search;
  let tiers = RI.DEFAULT_TIERS;
  let saved = {}; // id → 저장한 레퍼런스
  let sortKey = 'mult';
  let filterTier = 'all';
  let collapsed = false;

  // ── 데이터 모으기 ─────────────────────────────────────────
  function upsert(n, source) {
    const prev = notes.get(n.id) || {id: n.id, source};
    const merged = {...prev};
    for (const k of ['title', 'author', 'type', 'xsecToken']) if (n[k]) merged[k] = n[k];
    for (const k of ['likes', 'collects', 'comments', 'shares']) {
      const v = RI.parseCount(n[k]);
      // 페이지 데이터(api)가 화면 글자(dom)보다 정확하므로 덮어쓰지 않는다
      if (v != null && !(source === 'dom' && prev.source === 'api' && prev[k] != null)) merged[k] = v;
    }
    const t = typeof n.time === 'number' ? n.time : null;
    if (t) merged.time = t < 1e12 ? t * 1000 : t; // 초 단위면 밀리초로
    if (source === 'api') merged.source = 'api';
    notes.set(n.id, merged);
  }

  window.addEventListener('message', (e) => {
    if (e.source !== window || !e.data || e.data.source !== TAG || !Array.isArray(e.data.notes)) return;
    e.data.notes.forEach((n) => n && typeof n.id === 'string' && upsert(n, 'api'));
    schedule();
  });

  const NOTE_LINK = 'a[href*="/explore/"], a[href*="/search_result/"], a[href*="/discovery/item/"]';
  const idFromHref = (href) => {
    const m = String(href).match(/\/(?:explore|search_result|discovery\/item)\/([0-9a-zA-Z]+)/);
    return m ? m[1] : null;
  };
  const text = (root, sel) => {
    const el = root.querySelector(sel);
    return el ? el.textContent.trim() : '';
  };

  // 화면에 보이는 카드에서 id·제목·좋아요를 읽는다 (페이지 데이터가 없을 때의 대안)
  function scanCards() {
    const cards = [];
    document.querySelectorAll('section.note-item, .note-item').forEach((card) => {
      const link = card.querySelector(NOTE_LINK);
      const id = link && idFromHref(link.getAttribute('href'));
      if (!id) return;
      upsert(
        {
          id,
          title: text(card, '.title span, .title, .footer .title'),
          author: text(card, '.author .name, .author-wrapper .name, .name'),
          likes: text(card, '.like-wrapper .count, [class*="like"] .count, .count'),
        },
        'dom',
      );
      cards.push({card, id});
    });
    return cards;
  }

  // ── 배지 ─────────────────────────────────────────────────
  const TIER_COLOR = {viral: '#7c3aed', explosive: '#ea580c', strong: '#ca8a04', normal: '#2563eb', weak: '#6b7280'};

  function ensureStyle() {
    if (document.getElementById('ri-style')) return;
    const st = document.createElement('style');
    st.id = 'ri-style';
    st.textContent = `
      .ri-badge{position:absolute;top:6px;right:6px;z-index:5;display:flex;flex-direction:column;align-items:flex-end;gap:3px;
        font:600 11px/1.2 -apple-system,"Apple SD Gothic Neo","Malgun Gothic",sans-serif;pointer-events:auto}
      .ri-badge .ri-pill{color:#fff;border-radius:999px;padding:3px 7px;box-shadow:0 1px 4px rgba(0,0,0,.25)}
      .ri-badge .ri-chip{background:rgba(17,17,17,.78);color:#fff;border-radius:6px;padding:2px 6px}
      .ri-badge .ri-save{all:unset;cursor:pointer;background:rgba(255,255,255,.92);color:#111;border-radius:6px;padding:2px 6px}
      .ri-badge .ri-save.on{background:#FFC93C}`;
    document.head.appendChild(st);
  }

  function renderBadge(card, row) {
    if (getComputedStyle(card).position === 'static') card.style.position = 'relative';
    let b = card.querySelector(':scope > .ri-badge');
    if (!b) {
      b = document.createElement('div');
      b.className = 'ri-badge';
      card.appendChild(b);
    }
    b.replaceChildren();
    const pill = document.createElement('span');
    pill.className = 'ri-pill';
    pill.style.background = TIER_COLOR[row.tier.key];
    pill.textContent = `${row.tier.label} ${RI.formatMult(row.mult)}`;
    const chip = document.createElement('span');
    chip.className = 'ri-chip';
    const parts = [`❤ ${RI.formatCount(row.likes)}`];
    if (row.collects != null) parts.push(`★ ${RI.formatCount(row.collects)}`);
    if (row.comments != null) parts.push(`💬 ${RI.formatCount(row.comments)}`);
    chip.textContent = parts.join('  ');
    const save = document.createElement('button');
    save.className = 'ri-save' + (saved[row.id] ? ' on' : '');
    save.textContent = saved[row.id] ? '저장됨' : '레퍼런스 저장';
    save.title = '링크와 숫자만 내 브라우저에 저장합니다';
    save.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      toggleSave(row);
    });
    b.append(pill, chip, save);
    if (row.score != null) b.title = `반응 점수 ${row.score}/100`;
  }

  // ── 저장 (내 브라우저 storage 에만) ────────────────────────
  function noteUrl(row) {
    const q = row.xsecToken ? `?xsec_token=${encodeURIComponent(row.xsecToken)}` : '';
    return `https://www.xiaohongshu.com/explore/${row.id}${q}`;
  }

  async function toggleSave(row) {
    if (saved[row.id]) delete saved[row.id];
    else
      saved[row.id] = {
        id: row.id, title: row.title || '', author: row.author || '', url: noteUrl(row),
        likes: row.likes ?? null, collects: row.collects ?? null, comments: row.comments ?? null,
        mult: row.mult != null ? +row.mult.toFixed(2) : null, score: row.score, tier: row.tier.label,
        context: searchKeyword() || location.pathname, savedAt: new Date().toISOString(),
      };
    await ext.storage.local.set({ri_saved: saved});
    render();
  }

  // ── 패널 ─────────────────────────────────────────────────
  const host = document.createElement('div');
  host.id = 'ri-panel-host';
  const shadow = host.attachShadow({mode: 'open'});
  shadow.innerHTML = `
    <style>
      :host{all:initial}
      .p{position:fixed;top:72px;right:16px;z-index:2147483000;width:360px;max-height:calc(100vh - 96px);display:flex;flex-direction:column;
        background:#fff;color:#111;border-radius:14px;box-shadow:0 8px 30px rgba(0,0,0,.18);
        font:13px/1.45 -apple-system,"Apple SD Gothic Neo","Malgun Gothic",sans-serif;overflow:hidden}
      .p.c{width:auto}
      header{display:flex;align-items:center;gap:8px;padding:10px 12px;background:#050914;color:#fff}
      header b{color:#FFC93C}
      header .ctx{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;opacity:.85}
      button{font:inherit;cursor:pointer;border:0;border-radius:8px}
      header button{background:rgba(255,255,255,.12);color:#fff;padding:3px 8px}
      .body{overflow:auto;padding:10px 12px}
      .p.c .body{display:none}
      .stats{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:10px}
      .stat{background:#f4f5f7;border-radius:8px;padding:6px}
      .stat small{display:block;color:#6b7280;font-size:11px}
      .stat strong{font-size:15px}
      .chips{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px}
      .chips button{background:#f4f5f7;padding:3px 8px}
      .chips button.on{background:#050914;color:#fff}
      .bar{display:flex;gap:6px;align-items:center;margin-bottom:8px}
      .bar select{font:inherit;padding:3px;border-radius:6px;border:1px solid #ddd}
      .bar .sp{flex:1}
      .bar .csv{background:#FFC93C;color:#050914;padding:4px 10px;font-weight:700}
      ol{margin:0;padding:0;list-style:none}
      li{display:grid;grid-template-columns:1fr auto;gap:2px 8px;padding:6px 0;border-top:1px solid #eee}
      li a{color:#111;text-decoration:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      li a:hover{text-decoration:underline}
      li .m{font-weight:700;text-align:right}
      li .meta{color:#6b7280;font-size:11px}
      li .t{color:#fff;border-radius:999px;padding:0 6px;font-size:11px;justify-self:end}
      .empty{color:#6b7280;padding:12px 0}
      .note{color:#9ca3af;font-size:11px;margin-top:8px}
    </style>
    <div class="p">
      <header><b>레퍼런스 인사이트</b><span class="ctx"></span><button class="tg">접기</button></header>
      <div class="body">
        <div class="stats"></div>
        <div class="chips"></div>
        <div class="bar">
          <select class="sort">
            <option value="mult">성과배수순</option>
            <option value="score">반응점수순</option>
            <option value="likes">좋아요순</option>
            <option value="collects">저장순</option>
            <option value="comments">댓글순</option>
          </select>
          <span class="sp"></span>
          <button class="csv">CSV 내보내기</button>
        </div>
        <ol></ol>
        <div class="note">성과배수 = 좋아요 ÷ 이 목록의 좋아요 중앙값. 계산은 이 브라우저 안에서만 합니다.</div>
      </div>
    </div>`;
  const $ = (s) => shadow.querySelector(s);
  $('.tg').addEventListener('click', () => {
    collapsed = !collapsed;
    render();
  });
  $('.sort').addEventListener('change', (e) => {
    sortKey = e.target.value;
    render();
  });
  $('.csv').addEventListener('click', () => exportCSV());

  function searchKeyword() {
    const k = new URLSearchParams(location.search).get('keyword');
    if (!k) return '';
    try {
      return decodeURIComponent(k); // 따다처럼 %E4.. 로 깨져 보이지 않게
    } catch (_) {
      return k;
    }
  }

  function contextLabel() {
    const k = searchKeyword();
    if (k) return `검색: ${k}`;
    if (location.pathname.startsWith('/user/profile')) return '프로필';
    return '피드';
  }

  let lastAnalysis = null;

  function sortedRows(a) {
    const rows = a.rows.filter((r) => filterTier === 'all' || r.tier.key === filterTier);
    return rows.sort((x, y) => (y[sortKey] ?? -1) - (x[sortKey] ?? -1));
  }

  function renderPanel(a) {
    const p = $('.p');
    p.classList.toggle('c', collapsed);
    $('.tg').textContent = collapsed ? '펼치기' : '접기';
    $('.ctx').textContent = `· ${contextLabel()} · ${a.rows.length}개`;
    const stat = (label, value) => {
      const d = document.createElement('div');
      d.className = 'stat';
      const s = document.createElement('small');
      s.textContent = label;
      const b = document.createElement('strong');
      b.textContent = value;
      d.append(s, b);
      return d;
    };
    $('.stats').replaceChildren(
      stat('노트 수', a.rows.length + '개'),
      stat('중앙값 좋아요', RI.formatCount(a.median)),
      stat('평균 좋아요', RI.formatCount(a.average)),
      stat('최고 배수', RI.formatMult(a.maxMult)),
    );
    const chips = $('.chips');
    chips.replaceChildren();
    const mk = (key, label) => {
      const b = document.createElement('button');
      b.textContent = label;
      b.className = filterTier === key ? 'on' : '';
      b.addEventListener('click', () => {
        filterTier = key;
        render();
      });
      chips.appendChild(b);
    };
    mk('all', `전체 ${a.rows.length}`);
    a.tiers.forEach((t) => mk(t.key, `${t.label} ${a.counts[t.key]}`));
    const ol = $('ol');
    ol.replaceChildren();
    const rows = sortedRows(a).slice(0, 50);
    if (!rows.length) {
      const d = document.createElement('div');
      d.className = 'empty';
      d.textContent = '아직 모은 게시물이 없어요. 피드나 검색 결과를 스크롤해 보세요.';
      ol.appendChild(d);
    }
    rows.forEach((r, i) => {
      const li = document.createElement('li');
      const link = document.createElement('a');
      link.href = noteUrl(r);
      link.target = '_blank';
      link.rel = 'noopener';
      link.textContent = `${i + 1}. ${r.title || r.id}`;
      const m = document.createElement('span');
      m.className = 'm';
      m.textContent = RI.formatMult(r.mult);
      const meta = document.createElement('span');
      meta.className = 'meta';
      meta.textContent = `❤ ${RI.formatCount(r.likes)} · ★ ${RI.formatCount(r.collects)} · 💬 ${RI.formatCount(r.comments)}` +
        (r.score != null ? ` · 점수 ${r.score}` : '');
      const t = document.createElement('span');
      t.className = 't';
      t.style.background = TIER_COLOR[r.tier.key];
      t.textContent = r.tier.label;
      li.append(link, m, meta, t);
      ol.appendChild(li);
    });
  }

  function exportCSV() {
    if (!lastAnalysis) return;
    const headers = ['순위', '제목', '작성자', '좋아요', '저장', '댓글', '공유', '성과배수', '반응점수', '등급', '시간당좋아요', '링크', '맥락'];
    const ctx = contextLabel();
    const rows = sortedRows(lastAnalysis).map((r, i) => [
      i + 1, r.title, r.author, r.likes, r.collects, r.comments, r.shares,
      r.mult != null ? r.mult.toFixed(2) : '', r.score ?? '', r.tier.label,
      r.likesPerHour != null ? r.likesPerHour.toFixed(1) : '', noteUrl(r), ctx,
    ]);
    const blob = new Blob([RI.toCSV(headers, rows)], {type: 'text/csv;charset=utf-8'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `샤오홍슈_${(searchKeyword() || '피드').replace(/[\\/:*?"<>|]/g, '_')}_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  // ── 전체 갱신 ────────────────────────────────────────────
  function render() {
    const key = location.pathname + location.search;
    if (key !== pageKey) {
      // 다른 검색어·페이지로 넘어가면 새로 모은다 (SPA 이동 대응)
      pageKey = key;
      notes.clear();
      filterTier = 'all';
    }
    ensureStyle();
    if (!host.isConnected) document.documentElement.appendChild(host);
    const cards = scanCards();
    const a = RI.analyze([...notes.values()], tiers);
    lastAnalysis = a;
    const byId = new Map(a.rows.map((r) => [r.id, r]));
    cards.forEach(({card, id}) => byId.has(id) && renderBadge(card, byId.get(id)));
    renderPanel(a);
  }

  let timer = null;
  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(render, 300);
  }

  new MutationObserver((muts) => {
    // 우리 배지 때문에 생긴 변경은 무시 (무한 반복 방지)
    const ours = (m) =>
      (m.target.nodeType === 1 && m.target.closest('.ri-badge')) ||
      [...m.addedNodes, ...m.removedNodes].every((n) => n.nodeType === 1 && n.classList.contains('ri-badge'));
    if (muts.every(ours)) return;
    schedule();
  }).observe(document.body, {childList: true, subtree: true});

  // 페이지 쪽 스크립트에게 "준비됨"을 알려 이미 찾은 데이터를 다시 받는다
  window.postMessage({source: TAG, type: 'ready'}, location.origin);

  // 설정·저장 목록 불러오기 (팝업에서 바꾸면 바로 반영)
  ext.storage.local.get(['ri_saved', 'ri_tiers']).then((r) => {
    saved = r.ri_saved || {};
    if (Array.isArray(r.ri_tiers) && r.ri_tiers.length === 4) tiers = r.ri_tiers;
    render();
  });
  ext.storage.onChanged.addListener((changes, area) => {
    if (area !== 'local') return;
    if (changes.ri_saved) saved = changes.ri_saved.newValue || {};
    if (changes.ri_tiers) tiers = changes.ri_tiers.newValue || RI.DEFAULT_TIERS;
    schedule();
  });
})();
