// 지표 계산 (콘텐츠 스크립트와 팝업이 함께 쓴다). 외부로 아무것도 보내지 않는다.
(function (global) {
  // "1.2万", "3.4w", "1.9천", "4.8만", "1,234", "10w+" → 숫자
  const UNITS = {'万': 1e4, '萬': 1e4, 'w': 1e4, 'W': 1e4, '만': 1e4, '천': 1e3, 'k': 1e3, 'K': 1e3, '亿': 1e8, '억': 1e8};

  function parseCount(v) {
    if (typeof v === 'number') return Number.isFinite(v) ? v : null;
    if (typeof v !== 'string') return null;
    const s = v.replace(/[,\s+]/g, '');
    const m = s.match(/^(\d+(?:\.\d+)?)([万萬wW만천kK亿억])?$/);
    if (!m) return null;
    return Math.round(parseFloat(m[1]) * (m[2] ? UNITS[m[2]] : 1));
  }

  function median(values) {
    const a = values.filter((x) => typeof x === 'number').sort((x, y) => x - y);
    if (!a.length) return null;
    const mid = Math.floor(a.length / 2);
    return a.length % 2 ? a[mid] : (a[mid - 1] + a[mid]) / 2;
  }

  const clamp01 = (x) => Math.max(0, Math.min(1, x));

  // 등급 경계: 배수 "또는" 점수 중 하나만 넘어도 그 등급 (높은 등급부터 검사)
  const DEFAULT_TIERS = [
    {key: 'viral', label: '폭발', mult: 10, score: 85},
    {key: 'explosive', label: '강력', mult: 5, score: 65},
    {key: 'strong', label: '우수', mult: 3, score: 45},
    {key: 'normal', label: '보통', mult: 1, score: 20},
  ];
  const WEAK = {key: 'weak', label: '약함'};

  // 반응 점수 0~100 (공개 공식)
  //  - 성과배수 60점: 20배면 만점 (로그 눈금)
  //  - 저장률 25점: 저장/좋아요 50%면 만점 (구매·재방문 의도)
  //  - 댓글률 15점: 댓글/좋아요 10%면 만점 (대화 유발)
  //  모르는 항목은 절반 점수로 친다. 빼고 환산하면 정보가 없는 글이 오히려 유리해지기 때문.
  const WEIGHTS = {mult: 60, save: 25, talk: 15};

  function score(n) {
    if (n.mult == null) return null;
    const part = (weight, ratio) => weight * (ratio == null ? 0.5 : clamp01(ratio));
    const known = n.likes > 0;
    return Math.round(
      part(WEIGHTS.mult, Math.log10(Math.max(n.mult, 1)) / Math.log10(20)) +
      part(WEIGHTS.save, known && n.collects != null ? n.collects / n.likes / 0.5 : null) +
      part(WEIGHTS.talk, known && n.comments != null ? n.comments / n.likes / 0.1 : null),
    );
  }

  function tierOf(mult, sc, tiers) {
    for (const t of tiers) {
      if ((mult != null && mult >= t.mult) || (sc != null && sc >= t.score)) return t;
    }
    return WEAK;
  }

  // notes: [{id, likes, collects?, comments?, shares?, time?}] → 지표를 붙인 사본과 요약
  function analyze(notes, tiers = DEFAULT_TIERS, now = Date.now()) {
    const likes = notes.map((n) => n.likes).filter((x) => x != null);
    const med = median(likes);
    const avg = likes.length ? likes.reduce((a, b) => a + b, 0) / likes.length : null;
    const rows = notes.map((n) => {
      const r = {...n};
      r.mult = med > 0 && n.likes != null ? n.likes / med : null; // 중앙값 대비 성과배수
      r.saveRate = n.likes > 0 && n.collects != null ? n.collects / n.likes : null;
      const hours = n.time ? Math.max((now - n.time) / 36e5, 1) : null;
      r.likesPerHour = hours && n.likes != null ? n.likes / hours : null; // 시간당 좋아요 (조회수가 없어 VPH 대신)
      r.score = score(r);
      r.tier = tierOf(r.mult, r.score, tiers);
      return r;
    });
    const counts = Object.fromEntries([...tiers, WEAK].map((t) => [t.key, 0]));
    rows.forEach((r) => counts[r.tier.key]++);
    const maxMult = rows.reduce((m, r) => (r.mult != null && r.mult > m ? r.mult : m), 0);
    return {rows, median: med, average: avg, maxMult: maxMult || null, counts, tiers: [...tiers, WEAK]};
  }

  function formatCount(n) {
    if (n == null) return '—';
    n = Math.round(n);
    if (n >= 1e8) return (n / 1e8).toFixed(1).replace(/\.0$/, '') + '억';
    if (n >= 1e4) return (n / 1e4).toFixed(1).replace(/\.0$/, '') + '만';
    return n.toLocaleString('ko-KR');
  }

  const formatMult = (m) => (m == null ? '—' : (m >= 100 ? Math.round(m) : m.toFixed(1)) + '배');

  // 엑셀에서 한글이 깨지지 않도록 BOM 을 붙인 CSV
  function toCSV(headers, rows) {
    const esc = (v) => {
      const s = v == null ? '' : String(v);
      return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    };
    return '﻿' + [headers.map(esc).join(','), ...rows.map((r) => r.map(esc).join(','))].join('\r\n');
  }

  global.RI = {parseCount, median, analyze, score, tierOf, DEFAULT_TIERS, WEIGHTS, formatCount, formatMult, toCSV};
})(typeof window !== 'undefined' ? window : globalThis);
