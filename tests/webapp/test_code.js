/* webapp/Code.gs를 가짜 Apps Script 위에서 돌려 보는 테스트. 실행: node tests/webapp/test_code.js (pytest가 부름) */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { make } = require('./fake_gas.js');

const CODE = fs.readFileSync(path.join(__dirname, '..', '..', 'webapp', 'Code.gs'), 'utf8');

function load(opts) {
  const fake = make(opts);
  const ctx = vm.createContext({ ...fake.globals, console, JSON, Math, Date, Number, String, Object, Array, isFinite });
  vm.runInContext(CODE, ctx);
  return { gas: ctx, fake };
}
const near = (a, b, msg) => assert.ok(Math.abs(a - b) < 1e-6 * Math.max(1, Math.abs(b)), `${msg}: ${a} != ${b}`);
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test('처음 열면 비공개 시트와 매일 16시 기록 트리거를 만든다', () => {
  const { gas, fake } = load();
  const d = gas.getData();
  assert.equal(d.items.length, 0);
  assert.equal(d.api, gas.apiVersion());
  assert.equal(fake.triggers.length, 1);
  assert.deepEqual([fake.triggers[0].fn, fake.triggers[0].hour, fake.triggers[0].tz], ['dailySnapshot', 16, 'Asia/Seoul']);
  const book = Object.values(fake.books)[0];
  assert.equal(book.name, '인생 자산 대시보드 (웹앱 데이터)');
  assert.equal(book.tz, 'Asia/Seoul');
  gas.getData();
  assert.equal(fake.triggers.length, 1, '트리거는 한 번만');
  assert.equal(Object.keys(fake.books).length, 1, '시트도 한 번만');
});

test('국내·미국·코인 시세로 평가하고 현금·부동산과 합쳐 순자산을 낸다', () => {
  const { gas } = load({ gf: { 'KRX:005930': 75000, 'AAPL': 200, 'CURRENCY:USDKRW': 1400 }, coins: { BTC: 100000000 } });
  gas.saveItem({ category: 'finance', name: '삼성전자', f: { kind: 'kr', ticker: '005930', qty: 10, avg: 70000 } });
  gas.saveItem({ category: 'finance', name: '애플', f: { kind: 'us', ticker: 'aapl', qty: 2, avg: 150 } });
  gas.saveItem({ category: 'finance', name: '비트코인', f: { kind: 'coin', ticker: 'btc', qty: 0.1, avg: 80000000 } });
  gas.saveItem({ category: 'finance', name: '비상금', f: { kind: 'cash', amount: 5000000 } });
  gas.saveItem({ category: 'realestate', name: '우리 집', date: '2020-05-01', f: { buy: 500000000, price: 600000000, loan: 200000000 } });
  const r = gas.refreshPrices();
  assert.equal(r.missing.length, 0);
  const d = gas.getData();
  const by = Object.fromEntries(d.items.map(i => [i.name, i.v]));
  near(by['삼성전자'].value, 750000, '국내');
  near(by['삼성전자'].gainPct, (75000 / 70000 - 1) * 100, '국내 수익률');
  near(by['애플'].value, 2 * 200 * 1400, '미국(원화 환산)');
  near(by['애플'].gainPct, (200 / 150 - 1) * 100, '미국은 달러 기준 수익률');
  near(by['비트코인'].value, 10000000, '코인');
  near(by['비상금'].value, 5000000, '현금');
  near(by['우리 집'].net, 400000000, '부동산 순');
  near(d.totals.finance, 750000 + 560000 + 10000000 + 5000000, '금융 합');
  near(d.totals.net, d.totals.finance + 600000000 - 200000000, '순자산');
  assert.equal(d.history.length, 1, '첫 기록을 바로 남긴다');
  near(d.history[0].net, Math.round(d.totals.net), '기록 값');
});

test('구글 파이낸스에 없는 국내 종목은 네이버 증권, 없는 코인이 섞여도 나머지 코인은 받는다', () => {
  const { gas, fake } = load({ naver: { '0091C0': 10500 }, coins: { ETH: 5000000 } });
  gas.saveItem({ category: 'finance', name: '어떤 ETF', f: { kind: 'kr', ticker: 'A0091C0', qty: 3 } });
  gas.saveItem({ category: 'finance', name: '이더리움', f: { kind: 'coin', ticker: 'ETH', qty: 1 } });
  gas.saveItem({ category: 'finance', name: '없는코인', f: { kind: 'coin', ticker: 'NOPE', qty: 1, avg: 1000 } });
  const r = gas.refreshPrices();
  assert.deepEqual(r.missing, ['COIN:NOPE']);
  const by = Object.fromEntries(gas.getData().items.map(i => [i.name, i.v]));
  near(by['어떤 ETF'].value, 31500, '네이버 보충');
  near(by['이더리움'].value, 5000000, '업비트 하나씩 다시');
  assert.equal(by['없는코인'].stale, true, '시세 없으면 평단가로');
  near(by['없는코인'].value, 1000, '평단가 계산');
  assert.ok(fake.fetched.some(u => u.includes('markets=KRW-ETH') && !u.includes(',')), '하나씩 다시 물음');
});

test('시세를 못 받아도 지난 값을 지우지 않는다', () => {
  const { gas, fake } = load({ gf: { 'KRX:005930': 75000 } });
  gas.saveItem({ category: 'finance', name: '삼성전자', f: { kind: 'kr', ticker: '005930', qty: 1 } });
  gas.refreshPrices();
  delete fake.gf['KRX:005930'];
  const r = gas.refreshPrices();
  assert.deepEqual(r.missing, ['KR:005930']);
  near(gas.getData().items[0].v.value, 75000, '지난 값 유지');
});

test('수정·삭제와 입력 검사, 수식처럼 보이는 이름도 글자로 저장', () => {
  const { gas } = load();
  const id = gas.saveItem({ category: 'awards', name: '=SUM(1,2)', date: '2023-12-01', f: { kind: 'honor', org: '교육청', evil: { x: 1 }, 'Bad-Key': 'x' } });
  let it = gas.getData().items[0];
  assert.equal(it.name, '=SUM(1,2)');
  assert.equal(it.date, '2023-12-01');
  assert.deepEqual(it.f, { kind: 'honor', org: '교육청' }, '객체·이상한 키는 버린다');
  gas.saveItem({ id, category: 'awards', name: '교육감 표창', date: '2023-12-01', f: { kind: 'honor' } });
  it = gas.getData().items;
  assert.equal(it.length, 1);
  assert.equal(it[0].name, '교육감 표창');
  assert.throws(() => gas.saveItem({ category: 'Bad-Cat', name: 'x' }), /분류/);
  assert.throws(() => gas.saveItem({ category: '', name: 'x' }), /분류/);
  assert.throws(() => gas.saveItem({ category: 'people', name: '  ' }), /이름/);
  assert.throws(() => gas.saveItem({ category: 'people', name: '첫째', date: '2020/1/1' }), /날짜/);
  assert.equal(gas.deleteItem(id), true);
  assert.equal(gas.getData().items.length, 0);
  assert.throws(() => gas.deleteItem(id), /이미 지워진/);
});

test('새 분류(파이프라인)와 모든 분류의 링크는 화면만 바꿔도 저장된다', () => {
  const { gas } = load();
  gas.saveItem({ category: 'pipeline', name: '블로그 광고', date: '2025-01-01',
                 f: { kind: 'ads', status: 'on', monthly: 320000, link: 'https://example.com/a' } });
  gas.saveItem({ category: 'people', name: '가족 A', f: { relation: '배우자', link: 'https://example.com/p' } });
  const d = gas.getData();
  const p = d.items.find(i => i.category === 'pipeline');
  assert.deepEqual(p.f, { kind: 'ads', status: 'on', monthly: 320000, link: 'https://example.com/a' });
  assert.equal(d.items.find(i => i.category === 'people').f.link, 'https://example.com/p');
  assert.equal(d.totals.net, 0, '파이프라인 월수입은 순자산에 더하지 않는다');
});

test('같은 날 기록은 덮어쓰고 날짜순으로 쌓는다', () => {
  const { gas, fake } = load();
  gas.saveItem({ category: 'finance', name: '현금', f: { kind: 'cash', amount: 100 } });
  gas.dailySnapshot();
  const book = Object.values(fake.books)[0];
  book.sheets['기록'].data.splice(1, 0, ['2026-11-01', 50, 50, 0, 0, '{}']);
  gas.saveItem({ category: 'finance', name: '현금2', f: { kind: 'cash', amount: 30 } });
  gas.dailySnapshot();
  const h = gas.getData().history;
  assert.deepEqual(h.map(x => x.net), [50, 130]);
  assert.equal(h[0].date, '2026-11-01');
});

test('시트가 날짜처럼 생긴 글자를 날짜로 바꿔도 기록 순서와 시세 시각(시·분)이 유지된다', () => {
  const { gas, fake } = load({ gf: { 'KRX:005930': 75000 } });
  gas.saveItem({ category: 'finance', name: '삼성전자', f: { kind: 'kr', ticker: '005930', qty: 1 } });
  gas.dailySnapshot();
  const book = Object.values(fake.books)[0];
  const hist = book.sheets['기록'];
  hist.data.push(['2026-10-01', 10, 10, 0, 0, '{}']);          // 예전 줄(시트가 날짜로 바꿔 둔 상태처럼)
  hist.getRange(hist.data.length, 1, 1, 1).setValues([['2026-10-01']]);
  gas.dailySnapshot();
  const firstCol = hist.getDataRange().getValues().slice(1).map(r => (r[0] instanceof Date ? 'DATE' : String(r[0])));
  assert.ok(!firstCol.includes('DATE'), '날짜 칸은 글자로 남아야 함: ' + firstCol);
  assert.deepEqual(firstCol, firstCol.slice().sort(), '시트 안에서도 날짜순');
  const at = book.sheets['시세'].getDataRange().getValues()[1][3];
  assert.ok(typeof at === 'string' && /T\d{2}:\d{2}/.test(at), '시세 시각에 시·분이 남아야 함: ' + at);
});

test('화면 파일이 있으면 그것을, 없으면 퀘스트 보드를 보여 준다', () => {
  let { gas } = load({ files: { 'quest_board.html': '<p>보드</p>', 'life_dashboard_app.html': '<p>앱</p>' } });
  assert.equal(gas.doGet().html, '<p>앱</p>');
  assert.equal(gas.getQuestBoard(), '<p>보드</p>');
  ({ gas } = load({ files: { 'quest_board.html': '<p>보드</p>' } }));
  assert.equal(gas.doGet().html, '<p>보드</p>');
  ({ gas } = load());
  assert.match(gas.doGet().html, /아직 집 PC가 화면 파일을/);
});

test('베이스캠프 주소 점검: 열림·로그인 필요·닫힘·접속 실패·잘못된 주소', () => {
  const { gas } = load({ sites: { 'https://a.example/': 200, 'https://b.example/': 403, 'https://c.example/': 500, 'https://d.example/': 'fail' } });
  const r = gas.checkLinks(['https://a.example/', 'https://b.example/', 'https://c.example/', 'https://d.example/', 'javascript:alert(1)']);
  assert.deepEqual(r.map(x => x.state), ['ok', 'login', 'down', 'down', 'down']);
  assert.deepEqual(r.map(x => x.code), [200, 403, 500, 0, 0]);
  assert.equal(gas.checkLinks(Array(50).fill('https://a.example/')).length, 40, '한 번에 최대 40개');
});

test('스케줄 보드: 처음엔 빈 판, 저장하면 판이 오르고 같은 폴더에 남는다', () => {
  const { gas, fake } = load();
  const r0 = gas.loadBoard();
  assert.deepEqual([r0.json, r0.rev], ['', 0]);
  const j = JSON.stringify({ canvases: [{ id: 'c1', cards: [{ id: 'a' }], done: [] }] });
  const s1 = gas.saveBoard(j, 0);
  assert.deepEqual([s1.ok, s1.rev], [true, 1]);
  const r1 = gas.loadBoard();
  assert.equal(r1.json, j); assert.equal(r1.rev, 1);
  assert.equal(fake.folders['스케줄보드_데이터'].files.filter(f => f.name === 'board.json').length, 1);
});

test('스케줄 보드: 다른 기기가 먼저 저장했으면(판이 다름) 덮어쓰지 않고 충돌로 알린다', () => {
  const { gas } = load();
  const a = JSON.stringify({ canvases: [{ id: 'c1', cards: [{ id: 'a' }], done: [] }] });
  gas.saveBoard(a, 0);                                    // 기기 A → 판 1
  const b = JSON.stringify({ canvases: [{ id: 'c1', cards: [{ id: 'b' }], done: [] }] });
  const r = gas.saveBoard(b, 0);                          // 기기 B는 판 0을 보고 있었다
  assert.equal(r.conflict, true); assert.equal(r.json, a); assert.equal(r.rev, 1);
  assert.equal(gas.loadBoard().json, a, '덮어쓰지 않음');
});

test('스케줄 보드: 예전 단독 앱이 파일을 고치면 충돌로 알린다', () => {
  const { gas, fake } = load();
  gas.saveBoard(JSON.stringify({ canvases: [{ id: 'c1', cards: [{ id: 'a' }] }] }), 0);
  const f = fake.folders['스케줄보드_데이터'].files.find(x => x.name === 'board.json');
  f.content = JSON.stringify({ canvases: [{ id: 'c1', cards: [{ id: 'old' }] }] }); fake.touch(f);
  const r = gas.saveBoard(JSON.stringify({ canvases: [{ id: 'c1', cards: [{ id: 'a' }, { id: 'n' }] }] }), 1);
  assert.equal(r.conflict, true); assert.ok(r.rev > 1);
  assert.equal(gas.saveBoard(JSON.stringify({ canvases: [{ id: 'c1', cards: [{ id: 'merged' }] }] }), r.rev).ok, true, '합친 뒤 새 판으로는 저장됨');
});

test('스케줄 보드: 카드가 있던 판을 빈 판으로 덮어쓰지 않고, 깨진 내용은 거절, 백업을 남긴다', () => {
  const { gas, fake } = load();
  const full = JSON.stringify({ canvases: [{ id: 'c1', cards: [{ id: 'a' }, { id: 'b' }], done: [{ id: 'c' }] }] });
  gas.saveBoard(full, 0);
  const empty = JSON.stringify({ canvases: [{ id: 'c1', cards: [], done: [] }] });
  const r = gas.saveBoard(empty, 1);
  assert.equal(r.refused, true); assert.equal(gas.loadBoard().json, full);
  assert.equal(gas.saveBoard(empty, 1, true).ok, true, '직접 모두 지운 경우(force)는 저장');
  assert.throws(() => gas.saveBoard('{깨짐', 2));
  const bak = fake.folders['스케줄보드_데이터'].files.find(x => x.name === 'board.backup.json');
  assert.ok(bak, '백업 파일'); assert.equal(bak.content, full);
});

test('스케줄 보드: 첨부는 비공개로 올리고, 예전 앱이 공개해 둔 첨부도 비공개로 되돌린다', () => {
  const { gas, fake } = load();
  const folder = fake.globals.DriveApp.createFolder('스케줄보드_데이터');
  const old = folder.createFile('예전첨부.pdf', 'x', 'application/pdf'); old.sharing = 'ANYONE_WITH_LINK';
  gas.loadBoard();
  assert.equal(old.sharing, 'PRIVATE');
  const up = gas.uploadBoardFile(Buffer.from('hello').toString('base64'), '메모.txt', 'text/plain');
  assert.equal(up.name, '메모.txt'); assert.match(up.url, /drive\.google\.com/);
  const f = folder.files.find(x => x.name === '메모.txt');
  assert.equal(f.sharing, 'PRIVATE'); assert.equal(f.content, 'hello');
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log('ok   ' + name); } catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + (e.stack || e).split('\n').slice(0, 3).join('\n     ')); }
}
console.log(failed ? `${failed} failed` : `all ${tests.length} passed`);
process.exit(failed ? 1 : 0);
