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
  assert.throws(() => gas.saveItem({ category: 'nope', name: 'x' }), /분류/);
  assert.throws(() => gas.saveItem({ category: 'people', name: '  ' }), /이름/);
  assert.throws(() => gas.saveItem({ category: 'people', name: '첫째', date: '2020/1/1' }), /날짜/);
  assert.equal(gas.deleteItem(id), true);
  assert.equal(gas.getData().items.length, 0);
  assert.throws(() => gas.deleteItem(id), /이미 지워진/);
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

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log('ok   ' + name); } catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + (e.stack || e).split('\n').slice(0, 3).join('\n     ')); }
}
console.log(failed ? `${failed} failed` : `all ${tests.length} passed`);
process.exit(failed ? 1 : 0);
