// 팝업: 저장한 레퍼런스 목록, CSV 내보내기, 등급 기준 설정
const ext = globalThis.browser && globalThis.browser.storage ? globalThis.browser : globalThis.chrome;
const RI = window.RI;
const $ = (s) => document.querySelector(s);

async function load() {
  const r = await ext.storage.local.get(['ri_saved', 'ri_tiers']);
  renderSaved(r.ri_saved || {});
  renderTiers(Array.isArray(r.ri_tiers) && r.ri_tiers.length === 4 ? r.ri_tiers : RI.DEFAULT_TIERS);
}

function renderSaved(saved) {
  const items = Object.values(saved).sort((a, b) => (b.savedAt || '').localeCompare(a.savedAt || ''));
  $('#count').textContent = items.length;
  const ol = $('#saved');
  ol.replaceChildren();
  if (!items.length) {
    const li = document.createElement('li');
    li.className = 'empty';
    li.textContent = '배지의 "레퍼런스 저장"을 누르면 여기에 모입니다.';
    ol.appendChild(li);
  }
  items.forEach((s) => {
    const li = document.createElement('li');
    const a = document.createElement('a');
    a.href = s.url;
    a.target = '_blank';
    a.textContent = s.title || s.id;
    const m = document.createElement('span');
    m.textContent = `${s.tier} ${RI.formatMult(s.mult)}`;
    li.append(a, m);
    ol.appendChild(li);
  });
  $('#export').onclick = () => exportSaved(items);
}

function exportSaved(items) {
  const headers = ['제목', '작성자', '좋아요', '저장', '댓글', '성과배수', '반응점수', '등급', '찾은 곳', '링크', '저장 시각'];
  const rows = items.map((s) => [s.title, s.author, s.likes, s.collects, s.comments, s.mult, s.score, s.tier, s.context, s.url, s.savedAt]);
  const blob = new Blob([RI.toCSV(headers, rows)], {type: 'text/csv;charset=utf-8'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `레퍼런스_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
}

function renderTiers(tiers) {
  const table = $('#tiers');
  table.replaceChildren();
  tiers.forEach((t, i) => {
    const input = (k, value, attrs) => {
      const inp = document.createElement('input');
      Object.assign(inp, {type: 'number', min: '0', value: String(value), ...attrs});
      inp.dataset.i = String(i);
      inp.dataset.k = k;
      return inp;
    };
    const td = (...nodes) => {
      const c = document.createElement('td');
      c.append(...nodes);
      return c;
    };
    const tr = document.createElement('tr');
    tr.append(
      td(t.label),
      td(input('mult', t.mult, {step: '0.5'}), ' 배 이상'),
      td('또는 ', input('score', t.score, {max: '100', step: '1'}), ' 점'),
    );
    table.appendChild(tr);
  });
  $('#saveTiers').onclick = async () => {
    const next = tiers.map((t) => ({...t}));
    table.querySelectorAll('input').forEach((inp) => {
      const v = parseFloat(inp.value);
      if (Number.isFinite(v)) next[+inp.dataset.i][inp.dataset.k] = v;
    });
    await ext.storage.local.set({ri_tiers: next});
    $('#saveTiers').textContent = '저장됨';
    setTimeout(() => ($('#saveTiers').textContent = '기준 저장'), 1200);
  };
  $('#resetTiers').onclick = async () => {
    await ext.storage.local.remove('ri_tiers');
    renderTiers(RI.DEFAULT_TIERS);
  };
}

// ── shortsmaker 연결: 저장한 레퍼런스(링크·숫자)를 내 shortsmaker 서버로 보낸다 ──
const DEFAULT_SERVER = 'http://127.0.0.1:8000';

function serverOrigin() {
  try {
    const u = new URL($('#serverUrl').value.trim() || DEFAULT_SERVER);
    return /^https?:$/.test(u.protocol) ? u.origin : null;
  } catch (_) {
    return null;
  }
}

function setStatus(msg, isErr = false) {
  const el = $('#sendStatus');
  el.textContent = msg;
  el.className = 'status' + (isErr ? ' err' : '');
}

async function loadServer() {
  const r = await ext.storage.local.get('ri_server');
  const s = r.ri_server || {};
  $('#serverUrl').value = s.url || DEFAULT_SERVER;
  $('#serverCode').value = s.code || '';
  updateTrendsLink();
}

function updateTrendsLink() {
  const o = serverOrigin();
  $('#openTrends').href = o ? o + '/trends' : '#';
}
$('#serverUrl').addEventListener('input', updateTrendsLink);

$('#send').onclick = () => {
  const origin = serverOrigin();
  if (!origin) return setStatus('서버 주소가 올바르지 않아요. 예: http://127.0.0.1:8000', true);
  // 권한 요청은 클릭 직후에 해야 한다 (파이어폭스는 await 뒤에 부르면 거절)
  ext.permissions.request({origins: [origin + '/*']}).then(
    (ok) => (ok ? sendSaved(origin) : setStatus('이 주소에 접속할 권한을 허용해야 보낼 수 있어요.', true)),
    (e) => setStatus('권한 요청 실패: ' + e.message, true),
  );
};

async function sendSaved(origin) {
  const code = $('#serverCode').value.trim();
  await ext.storage.local.set({ri_server: {url: origin, code}});
  const r = await ext.storage.local.get('ri_saved');
  const items = Object.values(r.ri_saved || {}).map((s) => ({...s, platform: 'xiaohongshu'}));
  if (!items.length) return setStatus('먼저 샤오홍슈에서 "레퍼런스 저장"을 눌러 주세요.', true);
  setStatus(`${items.length}개 보내는 중…`);
  let res;
  try {
    res = await fetch(origin + '/api/v2/trend-refs', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', ...(code ? {Authorization: 'Bearer ' + code} : {})},
      body: JSON.stringify({items}),
    });
  } catch (_) {
    return setStatus('shortsmaker에 연결할 수 없어요. PC에서 start.bat 이 켜져 있는지, 주소가 맞는지 확인해 주세요.', true);
  }
  if (res.status === 401) return setStatus('접속 암호가 필요하거나 틀렸어요. shortsmaker의 SHORTSMAKER_ACCESS_CODE 를 넣어 주세요.', true);
  if (res.status === 404) return setStatus('이 shortsmaker 버전에는 레퍼런스 받기 기능이 없어요. 최신 버전으로 업데이트해 주세요.', true);
  if (!res.ok) return setStatus(`보내기 실패 (${res.status})`, true);
  const j = await res.json();
  setStatus(`보냈어요: 새로 ${j.added}개, 갱신 ${j.updated}개` + (j.skipped ? `, 건너뜀 ${j.skipped}개` : '') + ` · shortsmaker에 총 ${j.total}개`);
}

$('#clear').onclick = async () => {
  if (!confirm('저장한 레퍼런스를 모두 지울까요?')) return;
  await ext.storage.local.set({ri_saved: {}});
  renderSaved({});
};

load();
loadServer();
