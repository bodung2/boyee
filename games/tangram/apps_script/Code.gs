// 칠교 놀이터 — 구글 Apps Script 웹앱
//
// 아이들은 로그인 없이 놀이하고, 기록은 선생님 구글 드라이브의 '칠교 놀이터 순위표' 시트에 자동으로 모인다.
// 붙여 넣는 파일 2개: 이 Code.gs + games/tangram/index.html(Apps Script에서 HTML 파일 이름을 'index'로).
// 배포: 배포 → 새 배포 → 유형 '웹 앱' → 실행: 나 / 액세스 권한: 모든 사용자.
//
// 시트 한 줄 = 아이 한 명. 아이를 지우려면 시트에서 그 줄을 지우면 된다.
// 이름(아이디)만 같으면 누구나 그 기록으로 이어서 할 수 있다(로그인이 없으므로 비밀번호도 없다).

const SHEET_NAME = '순위표';
const HEAD = ['이름', '깬 단계', '걸린 시간(초)', '단계별 기록', '코드로 받은 단계', '코드로 받은 시간(초)', '바뀐 때'];
const LEVEL_COUNT = 100;
const SALT = 'tangram-board-2026';           // index.html의 salt와 같아야 한다

function doGet() {
  return HtmlService.createHtmlOutputFromFile('index')
    .setTitle('칠교 놀이터')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

// ---------- 화면에서 부르는 함수 (google.script.run) ----------

/** 모두의 순위표 */
function board() {
  return readAll_().map(out_);
}

/** 한 사람 기록 (없으면 null) — 이름을 넣으면 이어서 하기 위해 */
function player(name) {
  name = cleanName_(name);
  const r = readAll_().find(x => x.name === name);
  return r ? out_(r) : null;
}

/** 단계별 최고 기록 저장. 이미 있는 기록과 합쳐 더 빠른 시간만 남긴다. */
function save(name, best) {
  name = cleanName_(name);
  best = cleanBest_(best);
  return withLock_(() => {
    const sh = sheet_(), rows = readAll_(sh);
    const r = rows.find(x => x.name === name) || { name: name, best: {}, base: { cleared: 0, total: 0 }, row: -1 };
    r.best = mergeBest_(r.best, best);
    write_(sh, r);
    return out_(r);
  });
}

/** 기록 코드([칠교:이름:깬 단계:시간 합:확인]) 여러 개를 받아 각자의 기록으로 넣는다 */
function importCodes(text) {
  const codes = parseCodes_(text);
  return withLock_(() => {
    const sh = sheet_(), rows = readAll_(sh);
    let up = 0, same = 0;
    for (const c of codes.recs) {
      let r = rows.find(x => x.name === c.name);
      if (!r) { r = { name: c.name, best: {}, base: { cleared: 0, total: 0 }, row: -1 }; rows.push(r); }
      const before = summary_(r);
      r.base = better_(r.base, { cleared: c.cleared, total: c.total });
      const after = summary_(r);
      if (after.cleared === before.cleared && after.total === before.total && r.row >= 0) { same++; continue; }
      write_(sh, r);
      up++;
    }
    return { ok: codes.ok, bad: codes.bad, up: up, same: same, rows: rows.map(out_) };
  });
}

// ---------- 시트 ----------

function sheet_() {
  const props = PropertiesService.getScriptProperties();
  let ss = null;
  const id = props.getProperty('SHEET_ID');
  if (id) { try { ss = SpreadsheetApp.openById(id); } catch (e) { ss = null; } }
  if (!ss) {
    ss = SpreadsheetApp.create('칠교 놀이터 순위표');
    props.setProperty('SHEET_ID', ss.getId());
  }
  let sh = ss.getSheetByName(SHEET_NAME);
  if (!sh) {
    sh = ss.getSheets()[0];
    sh.setName(SHEET_NAME);
    sh.getRange(1, 1, 1, HEAD.length).setValues([HEAD]);
    sh.setFrozenRows(1);
  }
  return sh;
}

function readAll_(sh) {
  sh = sh || sheet_();
  const values = sh.getDataRange().getValues();
  const rows = [];
  for (let i = 1; i < values.length; i++) {
    const v = values[i], name = String(v[0] || '').trim();
    if (!name) continue;
    let best = {};
    try { best = cleanBest_(JSON.parse(String(v[3] || '{}'))); } catch (e) { best = {}; }
    rows.push({ name: name, best: best, base: { cleared: Math.min(LEVEL_COUNT, num_(v[4])), total: num_(v[5]) }, row: i + 1 });
  }
  return rows;
}

function write_(sh, r) {
  const s = summary_(r);
  const line = [r.name, s.cleared, s.total, JSON.stringify(r.best), r.base.cleared || '', r.base.cleared ? r.base.total : '', new Date()];
  if (r.row > 0) sh.getRange(r.row, 1, 1, line.length).setValues([line]);
  else { sh.appendRow(line); r.row = sh.getLastRow(); }
}

function withLock_(fn) {
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try { return fn(); } finally { lock.releaseLock(); }
}

// ---------- 기록 계산 (index.html의 summary와 같은 규칙) ----------

function num_(v) { v = Number(v); return isFinite(v) && v >= 0 ? Math.floor(v) : 0; }

function better_(a, b) {
  if (!a) return b; if (!b) return a;
  return (b.cleared > a.cleared || (b.cleared === a.cleared && b.total < a.total)) ? b : a;
}

/** 단계별 기록과 코드로 받은 기록을 이어 붙여 '연속으로 깬 단계'와 그 시간 합 */
function summary_(r) {
  const best = r.best || {}, base = r.base || { cleared: 0, total: 0 };
  let c1 = 0, t1 = 0; while (best[c1 + 1] != null) { t1 += best[c1 + 1]; c1++; }
  let c2 = Math.min(LEVEL_COUNT, num_(base.cleared)), t2 = num_(base.total);
  while (c2 && best[c2 + 1] != null) { t2 += best[c2 + 1]; c2++; }
  return better_({ cleared: c1, total: t1 }, { cleared: c2, total: t2 });
}

function out_(r) {
  const s = summary_(r);
  return { name: r.name, best: r.best, base: { cleared: r.base.cleared, total: r.base.total }, cleared: s.cleared, total: s.total };
}

function mergeBest_(a, b) {
  const o = {};
  for (const k in a) o[k] = a[k];
  for (const k in b) if (o[k] == null || b[k] < o[k]) o[k] = b[k];
  return o;
}

function cleanName_(v) {
  const name = String(v == null ? '' : v).replace(/[:\[\]]/g, '').replace(/\s+/g, ' ').trim()
    .replace(/^[=+\-@]+/, '').trim().slice(0, 12);   // 시트에서 수식으로 읽히지 않게
  if (!name) throw new Error('이름이 비어 있어요');
  return name;
}

function cleanBest_(b) {
  const o = {};
  if (!b || typeof b !== 'object') return o;
  for (const k in b) {
    const n = Number(k), t = Number(b[k]);
    if (Number.isInteger(n) && n >= 1 && n <= LEVEL_COUNT && isFinite(t) && t >= 0 && t <= 36000) o[n] = Math.round(t);
  }
  return o;
}

// ---------- 기록 코드 ----------

function check4_(str) {
  let h = 0x811c9dc5;
  for (const ch of str) { h ^= ch.codePointAt(0); h = Math.imul(h, 16777619) >>> 0; }
  const A = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  let o = '';
  for (let i = 0; i < 4; i++) { o += A[h & 31]; h >>>= 5; }
  return o;
}

function parseCodes_(text) {
  const out = {}; let ok = 0, bad = 0;
  const re = /\[칠교:([^:\[\]]{1,12}):(\d{1,3}):(\d{1,7}):([A-Z0-9]{4})\]/g;
  let m;
  while ((m = re.exec(String(text || ''))) !== null) {
    const name = m[1].trim(), cleared = Number(m[2]), total = Number(m[3]);
    if (!name || cleared < 1 || cleared > LEVEL_COUNT || check4_(name + '|' + cleared + '|' + total + '|' + SALT) !== m[4]) { bad++; continue; }
    let clean;
    try { clean = cleanName_(name); } catch (e) { bad++; continue; }
    ok++;
    out[clean] = better_(out[clean], { name: clean, cleared: cleared, total: total });
  }
  const recs = Object.keys(out).map(k => out[k]);
  return { recs: recs, ok: ok, bad: bad };
}
