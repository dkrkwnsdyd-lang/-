// 가짜 샤오홍슈 검색 페이지에서 확장을 실제 Chromium 에 올려 확인한다.
// 사용: node extension/test/e2e.mjs <playwright 모듈 경로> <chromium 실행 파일> <스크린샷 폴더>
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const [, , pwPath, chromePath, outDir] = process.argv;
const {chromium} = await import(pwPath);
const here = path.dirname(fileURLToPath(import.meta.url));
const extDir = path.resolve(here, '..');

// 첫 화면 6개: 사용자 스크린샷의 실제 숫자 (초기 상태에 들어 있음)
const first = [
  ['n01', '29💰可折叠沙发', '家居君', '5400'],
  ['n02', '父母扭曲的教育观点，毁了男孩的童年', '育儿笔记', '5011', 3187, 152],
  ['n03', '这个男人太不讲厚道了', '电影夜奔', '2026', 1428, 12],
  ['n04', '韩系少女卧室💗被这盏落地灯甜晕', '卧室改造', '1900'],
  ['n05', '老公说，浴室门后被你整出个八百库🥰', '收纳达人', '1700'],
  ['n06', '苹果 HomeView 最实用的配件', '划水周', '1200'],
].map(([id, t, a, l, col, com]) => ({
  id, xsec_token: 'tok_' + id, model_type: 'note',
  note_card: {display_title: t, user: {nickname: a}, type: 'video',
    interact_info: {liked_count: l, ...(col != null ? {collected_count: String(col), comment_count: String(com)} : {})}},
}));
// 화면 글자로만 보이는 카드 (만·천 단위 표기 해석 확인)
const domOnly = [
  {id: 'd01', title: '谁家门厅拥有巨型猫咪猫墙🐱', author: '猫墙', likeText: '1.1万'},
  {id: 'd02', title: '18r的桌面铁皮柜我先拥有啦～', author: '桌面', likeText: '942'},
];
// 나중에 API 로 불러오는 14개 (저장·댓글 포함)
const likesMore = [83, 83, 60, 120, 45, 30, 95, 150, 70, 25, 300, 83, 55, 40];
const more = likesMore.map((l, i) => ({
  id: 'a' + String(i + 1).padStart(2, '0'), xsec_token: 'tok_a' + i, model_type: 'note',
  note_card: {display_title: `测试笔记 ${i + 1}`, user: {nickname: '用户' + i}, type: 'normal',
    time: Date.now() - (i + 2) * 3600e3,
    interact_info: {liked_count: String(l), collected_count: String(Math.round(l * (i % 3 === 0 ? 0.8 : 0.2))), comment_count: String(i)}},
}));

const html = fs.readFileSync(path.join(here, 'mock-search.html'), 'utf8')
  .replace('FIRST_NOTES_PLACEHOLDER', JSON.stringify(first))
  .replace('DOM_ONLY_PLACEHOLDER', JSON.stringify(domOnly));

const userDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ri-'));
const ctx = await chromium.launchPersistentContext(userDir, {
  executablePath: chromePath,
  headless: true,
  viewport: {width: 1400, height: 900},
  args: [`--disable-extensions-except=${extDir}`, `--load-extension=${extDir}`],
});
await ctx.route('https://www.xiaohongshu.com/**', async (route) => {
  const url = route.request().url();
  if (url.includes('/api/sns/web/v1/search/notes')) {
    return route.fulfill({contentType: 'application/json', body: JSON.stringify({code: 0, success: true, data: {items: more}})});
  }
  return route.fulfill({contentType: 'text/html; charset=utf-8', body: html});
});

const page = await ctx.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
await page.goto('https://www.xiaohongshu.com/search_result?keyword=%E4%B8%8E%E7%94%B5%E5%BD%B1%E5%A4%9C%E5%A5%94');
await page.waitForFunction(() => document.querySelectorAll('.ri-badge').length >= 22, null, {timeout: 15000});
await page.waitForTimeout(600);

const result = await page.evaluate(() => {
  const host = document.getElementById('ri-panel-host');
  const sh = host.shadowRoot;
  return {
    badges: document.querySelectorAll('.ri-badge').length,
    context: sh.querySelector('.ctx').textContent,
    stats: [...sh.querySelectorAll('.stat')].map((s) => s.innerText.replace(/\n/g, ': ')),
    chips: [...sh.querySelectorAll('.chips button')].map((b) => b.textContent),
    top: [...sh.querySelectorAll('li')].slice(0, 5).map((li) => li.innerText.replace(/\n/g, ' | ')),
    badgeOfN02: document.querySelector('a[href^="/search_result/n02"]').closest('section').querySelector('.ri-badge').innerText.replace(/\n/g, ' | '),
    badgeOfD01: document.querySelector('a[href^="/search_result/d01"]').closest('section').querySelector('.ri-badge').innerText.replace(/\n/g, ' | '),
  };
});
fs.mkdirSync(outDir, {recursive: true});
await page.screenshot({path: path.join(outDir, 'search.png')});

// 레퍼런스 저장 → 팝업에서 보이는지
await page.locator('a[href^="/search_result/n01"]').locator('xpath=..').locator('.ri-save').click();
await page.waitForTimeout(500);
const savedLabel = await page.locator('a[href^="/search_result/n01"]').locator('xpath=..').locator('.ri-save').innerText();

// 압축 해제 상태로 불러온 확장의 id 는 폴더 경로의 SHA-256 앞 32자리를 a~p 로 바꾼 값이다
const extId = crypto.createHash('sha256').update(extDir).digest('hex').slice(0, 32)
  .replace(/[0-9a-f]/g, (c) => String.fromCharCode(97 + parseInt(c, 16)));
let popup = null;
if (extId) {
  const pp = await ctx.newPage();
  await pp.setViewportSize({width: 360, height: 640});
  await pp.goto(`chrome-extension://${extId}/popup/popup.html`);
  await pp.waitForTimeout(500);
  popup = {count: await pp.locator('#count').innerText(), first: await pp.locator('#saved li').first().innerText()};
  // shortsmaker 서버 주소가 주어지면 팝업에서 보내기까지 확인
  const server = process.argv[5];
  if (server) {
    await pp.fill('#serverUrl', server);
    await pp.click('#send');
    await pp.waitForFunction(() => /보냈어요|실패|없어요|권한/.test(document.querySelector('#sendStatus').textContent), null, {timeout: 10000});
    popup.sendStatus = await pp.locator('#sendStatus').innerText();
    popup.serverRows = await (await fetch(server + '/api/v2/trend-refs')).json();
  }
  await pp.screenshot({path: path.join(outDir, 'popup.png'), fullPage: true});
}

console.log(JSON.stringify({result, savedLabel, extId, popup, errors}, null, 2));
await ctx.close();
