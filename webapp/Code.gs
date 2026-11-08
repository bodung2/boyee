/**
 * 인생 대시보드 웹앱 (구글 Apps Script, '나만' 접근으로 배포)
 *
 * 탭 1. 퀘스트 보드: 집 PC가 매시간 드라이브에 올리는 quest_board.html(보기 전용)
 * 탭 2. 내 자산: 금융·파이프라인(부가수입)·부동산·사람·저작물·직위·수상을 기록하는 곳. 화면에서 추가·수정·삭제한다.
 *        분류 목록은 화면(app.html)이 정한다. 이 코드는 분류 이름 형식만 검사하므로 분류를 더해도 다시 붙여 넣을 필요가 없다.
 *
 * - 자산 데이터는 이 구글 계정의 비공개 시트 '인생 자산 대시보드 (웹앱 데이터)'에만 저장된다(처음 열 때 자동 생성).
 *   GitHub(공개 저장소)에는 이 코드와 화면만 있고 데이터는 올라가지 않는다.
 * - 금융 자산 시세: 국내·미국 주식/ETF = 구글 파이낸스(약 20분 지연, 국내는 네이버 증권으로 보충), 코인 = 업비트 원화 시세.
 * - 매일 16시(한국 시간)에 총자산을 '기록' 시트에 남겨 추이 그래프를 그린다(구글 서버에서 돌아 PC가 꺼져 있어도 된다).
 * - 화면(life_dashboard_app.html)은 집 PC가 저장소의 webapp/app.html을 드라이브에 올린다. 화면만 바뀔 때는
 *   이 코드를 다시 붙여 넣을 필요가 없다. 이 코드가 바뀌면 API_VERSION이 올라가고 화면이 '새로 붙여 넣기'를 알린다.
 * 설치·갱신 방법: docs/QUEST_BOARD_WEBAPP.md
 */
const API_VERSION = 2;
const QUEST_FILE = 'quest_board.html';
const APP_FILE = 'life_dashboard_app.html';
const BOOK_NAME = '인생 자산 대시보드 (웹앱 데이터)';
const TZ = 'Asia/Seoul';
const SNAPSHOT_HOUR = 16;
const CATEGORY_RE = /^[a-z_]{2,30}$/;           // finance, pipeline, realestate, people, works, positions, awards …
const PRICED = ['kr', 'us', 'coin'];
const ITEM_HEAD = ['id', '분류', '이름', '날짜', '데이터', '수정시각'];
const PRICE_HEAD = ['키', '가격', '통화', '갱신'];
const HIST_HEAD = ['날짜', '순자산', '금융', '부동산', '대출', '상세'];

// ---------------------------------------------------------------- 화면

function doGet() {
  const app = latestFile_(APP_FILE);
  if (!app) {
    // 화면 파일이 아직 없으면(집 PC가 올리기 전) 예전처럼 퀘스트 보드만 보여 준다
    const quest = getQuestBoard();
    return HtmlService.createHtmlOutput(quest || notice_('아직 집 PC가 화면 파일을 올리지 않았습니다. ' +
      'PC에서 .venv\\Scripts\\python.exe -m quest_board --upload 를 한 번 실행해 주세요.'))
      .setTitle('퀘스트 보드').addMetaTag('viewport', 'width=device-width, initial-scale=1');
  }
  return HtmlService.createHtmlOutput(app.getBlob().getDataAsString('UTF-8'))
    .setTitle('인생 대시보드').addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

function notice_(text) {
  return '<p style="font-family:sans-serif;padding:16px;line-height:1.6">' + text + '</p>';
}

function latestFile_(name) {
  const files = DriveApp.getFilesByName(name);
  let latest = null;
  while (files.hasNext()) {
    const f = files.next();
    if (!f.isTrashed() && (!latest || f.getLastUpdated() > latest.getLastUpdated())) latest = f;
  }
  return latest;
}

function apiVersion() {
  return API_VERSION;
}

function getQuestBoard() {
  const f = latestFile_(QUEST_FILE);
  return f ? f.getBlob().getDataAsString('UTF-8') : '';
}

// ---------------------------------------------------------------- 시트

function book_() {
  const props = PropertiesService.getScriptProperties();
  const id = props.getProperty('BOOK_ID');
  if (id) {
    try { return SpreadsheetApp.openById(id); } catch (e) { /* 지웠으면 새로 만든다 */ }
  }
  const book = SpreadsheetApp.create(BOOK_NAME);
  book.setSpreadsheetTimeZone(TZ);
  props.setProperty('BOOK_ID', book.getId());
  return book;
}

function sheet_(name, head) {
  const book = book_();
  let sh = book.getSheetByName(name);
  if (!sh) {
    sh = book.insertSheet(name);
    sh.getRange(1, 1, 1, head.length).setValues([head]);
    sh.setFrozenRows(1);
  }
  return sh;
}

function rows_(sh) {
  const values = sh.getDataRange().getValues();
  return values.slice(1).filter(function (r) { return String(r[0]).trim() !== ''; });
}

function rewrite_(sh, head, rows) {
  sh.clearContents();
  const all = [head].concat(rows);
  sh.getRange(1, 1, all.length, head.length).setValues(all);
}

function today_() {
  return Utilities.formatDate(new Date(), TZ, 'yyyy-MM-dd');
}

function nowIso_() {
  return Utilities.formatDate(new Date(), TZ, "yyyy-MM-dd'T'HH:mm:ssXXX");
}

function dateStr_(v) {
  if (v instanceof Date) return Utilities.formatDate(v, TZ, 'yyyy-MM-dd');
  return String(v || '');
}

// ---------------------------------------------------------------- 항목

function readItems_() {
  return rows_(sheet_('항목', ITEM_HEAD)).map(function (r) {
    let f = {};
    try { f = JSON.parse(r[4] || '{}'); } catch (e) { f = {}; }
    return { id: String(r[0]), category: String(r[1]), name: String(r[2]), date: dateStr_(r[3]), f: f, updated: dateStr_(r[5]) };
  });
}

function writeItems_(items) {
  rewrite_(sheet_('항목', ITEM_HEAD), ITEM_HEAD, items.map(function (it) {
    // 날짜·이름이 숫자·날짜로 바뀌지 않게 앞에 '를 붙여 글자로 저장한다
    return [it.id, it.category, "'" + it.name, it.date ? "'" + it.date : '', JSON.stringify(it.f), "'" + it.updated];
  }));
}

function clean_(item) {
  if (!item || !CATEGORY_RE.test(String(item.category || ''))) throw new Error('분류가 올바르지 않습니다');
  const name = String(item.name || '').trim().slice(0, 200);
  if (!name) throw new Error('이름을 적어 주세요');
  const date = String(item.date || '').trim();
  if (date && !/^\d{4}-\d{2}-\d{2}$/.test(date)) throw new Error('날짜는 2024-03-01처럼 적어 주세요');
  const f = {};
  const src = item.f || {};
  Object.keys(src).slice(0, 40).forEach(function (k) {
    if (!/^[a-z_]{1,30}$/.test(k)) return;
    const v = src[k];
    if (typeof v === 'number' && isFinite(v)) f[k] = v;
    else if (typeof v === 'string') f[k] = v.slice(0, 2000);
  });
  return { id: String(item.id || ''), category: item.category, name: name, date: date, f: f };
}

function saveItem(item) {
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    const it = clean_(item);
    const items = readItems_();
    it.updated = nowIso_();
    const i = it.id ? items.findIndex(function (x) { return x.id === it.id; }) : -1;
    if (i >= 0) items[i] = it;
    else { it.id = Utilities.getUuid(); items.push(it); }
    writeItems_(items);
    return it.id;
  } finally {
    lock.releaseLock();
  }
}

function deleteItem(id) {
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    const items = readItems_();
    const left = items.filter(function (x) { return x.id !== String(id); });
    if (left.length === items.length) throw new Error('이미 지워진 항목입니다');
    writeItems_(left);
    return true;
  } finally {
    lock.releaseLock();
  }
}

// ---------------------------------------------------------------- 시세

function num_(v) {
  if (v === null || v === undefined || v === '') return NaN;
  const n = typeof v === 'number' ? v : Number(String(v).replace(/[,\s원$₩]/g, ''));
  return isFinite(n) ? n : NaN;
}

function priceKey_(it) {
  const f = it.f || {};
  const t = String(f.ticker || '').trim().toUpperCase();
  if (it.category !== 'finance' || !t || PRICED.indexOf(f.kind) < 0) return '';
  if (f.kind === 'kr') return 'KR:' + t.replace(/^A/, '');
  if (f.kind === 'us') return 'US:' + t;
  return 'COIN:' + t.replace(/^KRW-/, '');
}

function gfFormula_(key) {
  const code = key.split(':')[1];
  if (key.indexOf('KR:') === 0) {
    return '=IFERROR(GOOGLEFINANCE("KRX:' + code + '","price"),IFERROR(GOOGLEFINANCE("KOSDAQ:' + code + '","price"),""))';
  }
  if (key.indexOf('US:') === 0) return '=IFERROR(GOOGLEFINANCE("' + code + '","price"),"")';
  if (key === 'FX:USDKRW') return '=IFERROR(GOOGLEFINANCE("CURRENCY:USDKRW"),"")';
  return '';
}

function readPrices_() {
  const out = {};
  rows_(sheet_('시세', PRICE_HEAD)).forEach(function (r) {
    out[String(r[0])] = { v: Number(r[1]), cur: String(r[2]), at: dateStr_(r[3]) };
  });
  return out;
}

function fetchJson_(url) {
  const r = UrlFetchApp.fetch(url, { muteHttpExceptions: true, headers: { 'User-Agent': 'Mozilla/5.0' } });
  if (r.getResponseCode() !== 200) return null;
  return JSON.parse(r.getContentText());
}

function coinPrices_(symbols) {
  const out = {};
  if (!symbols.length) return out;
  const tickers = function (list) {
    try {
      (fetchJson_('https://api.upbit.com/v1/ticker?markets=' + list.map(function (s) { return 'KRW-' + s; }).join(',')) || [])
        .forEach(function (t) { out[t.market.slice(4)] = Number(t.trade_price); });
    } catch (e) { /* 아래에서 하나씩 */ }
  };
  tickers(symbols);
  // 없는 코인이 하나라도 섞이면 업비트가 전체를 거절하므로, 빠진 것은 하나씩 다시 묻는다
  symbols.filter(function (s) { return !(s in out); }).forEach(function (s) { tickers([s]); });
  return out;
}

function naverPrice_(code) {
  try {
    const j = fetchJson_('https://m.stock.naver.com/api/stock/' + code + '/basic');
    const v = j && num_(j.closePrice);
    return isFinite(v) ? v : NaN;
  } catch (e) {
    return NaN;
  }
}

function googleFinance_(keys) {
  const out = {};
  if (!keys.length) return out;
  const sh = sheet_('시세계산', ['키', '값']);
  sh.clearContents();
  sh.getRange(1, 1, keys.length, 2).setValues(keys.map(function (k) { return [k, gfFormula_(k)]; }));
  for (let attempt = 0; attempt < 6; attempt++) {
    SpreadsheetApp.flush();
    const vals = sh.getRange(1, 2, keys.length, 1).getValues();
    let pending = false;
    vals.forEach(function (row, i) {
      const v = row[0];
      if (typeof v === 'number' && isFinite(v) && v > 0) out[keys[i]] = v;
      else if (String(v).indexOf('Loading') >= 0) pending = true;
    });
    if (!pending) break;
    Utilities.sleep(1500);
  }
  return out;
}

/** 금융 자산의 시세를 새로 받아 '시세' 시트에 남기고 돌려준다. 못 받은 것은 지난 값을 그대로 둔다. */
function refreshPrices() {
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    const keys = {};
    readItems_().forEach(function (it) {
      const k = priceKey_(it);
      if (k) keys[k] = true;
      if (k && it.f.kind === 'us') keys['FX:USDKRW'] = true;
    });
    const all = Object.keys(keys);
    const got = googleFinance_(all.filter(function (k) { return k.indexOf('COIN:') !== 0; }));
    all.filter(function (k) { return k.indexOf('KR:') === 0 && !(k in got); }).forEach(function (k) {
      const v = naverPrice_(k.slice(3));
      if (isFinite(v) && v > 0) got[k] = v;
    });
    const coins = coinPrices_(all.filter(function (k) { return k.indexOf('COIN:') === 0; }).map(function (k) { return k.slice(5); }));
    Object.keys(coins).forEach(function (s) { got['COIN:' + s] = coins[s]; });

    const prices = readPrices_();
    const at = nowIso_();
    Object.keys(got).forEach(function (k) {
      prices[k] = { v: got[k], cur: k.indexOf('US:') === 0 ? 'USD' : 'KRW', at: at };
    });
    rewrite_(sheet_('시세', PRICE_HEAD), PRICE_HEAD, Object.keys(prices).sort().map(function (k) {
      return [k, prices[k].v, prices[k].cur, "'" + prices[k].at];      // 시트가 날짜로 바꿔 시·분을 잃지 않게
    }));
    PropertiesService.getScriptProperties().setProperty('PRICES_AT', at);
    return { ok: Object.keys(got).length, missing: all.filter(function (k) { return !(k in got); }), at: at };
  } finally {
    lock.releaseLock();
  }
}

// ---------------------------------------------------------------- 평가

/** 금융·부동산 항목의 원화 평가금액·원가·손익. 화면과 매일 기록이 같은 계산을 쓴다. */
function value_(it, prices) {
  const f = it.f || {};
  const v = {};
  if (it.category === 'finance') {
    const qty = num_(f.qty);
    const avg = num_(f.avg);
    const key = priceKey_(it);
    const fx = prices['FX:USDKRW'] ? prices['FX:USDKRW'].v : NaN;
    const rate = f.kind === 'us' ? fx : 1;
    if (PRICED.indexOf(f.kind) >= 0 && isFinite(qty) && qty > 0) {
      const p = key ? prices[key] : null;
      if (p && isFinite(p.v) && isFinite(rate)) {
        v.price = p.v; v.priceAt = p.at; v.value = qty * p.v * rate;
      } else if (isFinite(num_(f.amount))) {
        v.value = num_(f.amount); v.manual = true;
      } else if (isFinite(avg) && isFinite(rate)) {
        v.value = qty * avg * rate; v.stale = true;
      }
      if (isFinite(avg) && avg > 0 && isFinite(rate)) {
        v.cost = qty * avg * rate;
        if (isFinite(v.price)) v.gainPct = (v.price / avg - 1) * 100;      // 미국 주식은 달러 기준 수익률
      }
      if (f.kind === 'us') v.fx = rate;
    } else {
      if (isFinite(num_(f.amount))) v.value = num_(f.amount);
      if (isFinite(num_(f.cost))) v.cost = num_(f.cost);
    }
    if (isFinite(v.value) && isFinite(v.cost) && v.cost > 0) {
      v.gain = v.value - v.cost;
      if (!isFinite(v.gainPct)) v.gainPct = v.gain / v.cost * 100;
    }
  } else if (it.category === 'realestate') {
    const buy = num_(f.buy);
    const now = num_(f.price);
    v.value = isFinite(now) ? now : (isFinite(buy) ? buy : NaN);
    v.loan = isFinite(num_(f.loan)) ? num_(f.loan) : 0;
    if (isFinite(buy) && buy > 0 && isFinite(v.value)) { v.cost = buy; v.gain = v.value - buy; v.gainPct = v.gain / buy * 100; }
    if (isFinite(v.value)) v.net = v.value - v.loan;
  }
  Object.keys(v).forEach(function (k) { if (typeof v[k] === 'number' && !isFinite(v[k])) delete v[k]; });
  return v;
}

function totals_(items) {
  const t = { finance: 0, realestate: 0, loan: 0, net: 0, byKind: {} };
  items.forEach(function (it) {
    const v = it.v || {};
    if (it.category === 'finance' && isFinite(v.value)) {
      t.finance += v.value;
      const k = (it.f && it.f.kind) || 'etc';
      t.byKind[k] = (t.byKind[k] || 0) + v.value;
    }
    if (it.category === 'realestate' && isFinite(v.value)) { t.realestate += v.value; t.loan += v.loan || 0; }
  });
  t.net = t.finance + t.realestate - t.loan;
  return t;
}

function valued_() {
  const prices = readPrices_();
  const items = readItems_().map(function (it) { it.v = value_(it, prices); return it; });
  return { items: items, prices: prices, totals: totals_(items) };
}

// ---------------------------------------------------------------- 매일 기록

function readHistory_() {
  return rows_(sheet_('기록', HIST_HEAD)).map(function (r) {
    return { date: dateStr_(r[0]), net: Number(r[1]), finance: Number(r[2]), realestate: Number(r[3]), loan: Number(r[4]) };
  }).sort(function (a, b) { return a.date < b.date ? -1 : 1; });
}

/** 오늘 총자산을 '기록' 시트에 남긴다(같은 날 여러 번이면 마지막 값으로 덮어씀). 매일 16시 트리거가 부른다. */
function dailySnapshot() {
  try { refreshPrices(); } catch (e) { /* 시세를 못 받아도 지난 값으로 기록 */ }
  const d = valued_();
  const day = today_();
  const detail = {};
  d.items.forEach(function (it) { if (isFinite(it.v.value)) detail[it.id] = Math.round(it.v.value); });
  const sh = sheet_('기록', HIST_HEAD);
  // 날짜 칸은 항상 '를 붙여 글자로 다시 쓴다(시트가 날짜로 바꿔 두면 순서가 섞인다)
  const rows = rows_(sh).map(function (r) { return ["'" + dateStr_(r[0])].concat(r.slice(1)); })
    .filter(function (r) { return r[0] !== "'" + day; });
  rows.push(["'" + day, Math.round(d.totals.net), Math.round(d.totals.finance), Math.round(d.totals.realestate),
             Math.round(d.totals.loan), JSON.stringify(detail)]);
  rows.sort(function (a, b) { return String(a[0]) < String(b[0]) ? -1 : 1; });
  rewrite_(sh, HIST_HEAD, rows);
  return d.totals;
}

function ensureTrigger_() {
  const has = ScriptApp.getProjectTriggers().some(function (t) { return t.getHandlerFunction() === 'dailySnapshot'; });
  if (!has) {
    ScriptApp.newTrigger('dailySnapshot').timeBased().everyDays(1).atHour(SNAPSHOT_HOUR).inTimezone(TZ).create();
  }
}

// ---------------------------------------------------------------- 화면이 부르는 함수

/** 화면을 그릴 데이터 전부. 처음 부르면 데이터 시트와 매일 기록 트리거를 만든다. */
function getData() {
  ensureTrigger_();
  const d = valued_();
  const history = readHistory_();
  if (!history.length && d.items.length) {
    dailySnapshot();                    // 첫 기록이 없으면 오늘 값으로 하나 남긴다
    history.push.apply(history, readHistory_());
  }
  return {
    api: API_VERSION,
    today: today_(),
    items: d.items,
    totals: d.totals,
    history: history,
    pricesAt: PropertiesService.getScriptProperties().getProperty('PRICES_AT') || '',
    snapshotHour: SNAPSHOT_HOUR,
    sheetUrl: book_().getUrl()
  };
}
