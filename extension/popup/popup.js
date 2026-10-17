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

$('#clear').onclick = async () => {
  if (!confirm('저장한 레퍼런스를 모두 지울까요?')) return;
  await ext.storage.local.set({ri_saved: {}});
  renderSaved({});
};

load();
