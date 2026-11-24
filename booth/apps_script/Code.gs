/**
 * 캐릭터 공방(부스 활동) — 구글 Apps Script 서버.
 *
 *  아이 폰  ──(QR → 이 웹앱)──▶ 그림 사진·닉네임·스타일을 보냄 → 드라이브 '원본' 폴더 + 대기열 시트에 한 줄
 *  부스 노트북(python -m booth run) ──(doPost + 토큰)──▶ 대기열에서 하나 가져감 → ChatGPT로 변환 → 결과를 올림
 *  아이 폰은 5초마다 상태를 물어 '완성' 그림을 보여 준다. 큰 화면용 모아 보기: 웹앱 주소 뒤에 ?view=wall
 *
 * 처음 한 번: 편집기 위쪽 함수 목록에서 setupBooth를 골라 ▶실행 → 실행 로그의 토큰을 노트북 .env의 BOOTH_TOKEN에 적는다.
 * 원본 그림은 비공개, 결과 그림만 '링크가 있는 사람 보기'로 공유한다(패들렛·큰 화면이 그림을 불러와야 해서).
 */
const BOOTH_API = 4;
const BOOK_NAME = '캐릭터 공방 대기열 (부스)';
const FOLDER_NAME = '캐릭터 공방 (부스)';
const STALE_MIN = 12;                 // 노트북이 가져간 뒤 이만큼 소식이 없으면 다시 대기열로
const MAX_TRIES = 2;
const MAX_IMAGE_CHARS = 9 * 1024 * 1024;
// 스타일 키·이름은 index.html의 STYLES, booth/styles.py와 같아야 한다(테스트가 확인).
const STYLES = {
  felt: '양모펠트 인형', clay: '클레이 인형', anime2d: '2D 애니메이션', anim3d: '3D 애니메이션',
  plush: '봉제 인형', pixel: '픽셀아트 게임', watercolor: '수채화 그림책', sticker: '스티커'
};
const HEAD = ['id', '받은 시각', '닉네임', '스타일', '소개', '상태', '원본 파일', '결과 파일', '결과 주소',
  '패들렛', '인쇄', '안내', '가져간 시각', '시도'];
const C = {};
HEAD.forEach((h, i) => { C[h] = i; });
const S = { WAIT: '대기', WORK: '변환 중', DONE: '완성', FAIL: '오류' };

function doGet(e) {
  const t = HtmlService.createTemplateFromFile('index');
  t.view = (e && e.parameter && e.parameter.view === 'wall') ? 'wall' : 'kid';
  return t.evaluate().setTitle('캐릭터 공방')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1, viewport-fit=cover');
}

// ───────── 처음 한 번 ─────────
function setupBooth() {
  const p = PropertiesService.getScriptProperties();
  sheet_();
  folder_('원본');
  folder_('결과');
  let token = p.getProperty('BOOTH_TOKEN');
  if (!token) {
    token = Utilities.getUuid().replace(/-/g, '');
    setProp_('BOOTH_TOKEN', token);
  }
  const msg = '노트북 .env에 이 줄을 적으세요 →  BOOTH_TOKEN=' + token +
    '\n대기열 시트: ' + SpreadsheetApp.openById(p.getProperty('BOOK_ID')).getUrl();
  console.log(msg);
  return msg;
}

// ───────── 저장값 ─────────
// 저장값(Properties) 읽기·쓰기는 무료 구글 계정에서 하루 5만 번까지다. 집 PC와 아이 폰이 5초마다 부르므로
// 자주 읽는 값은 캐시(6시간)에서 읽고, 집 PC가 살아 있다는 표시는 캐시에만 둔다.
const CACHE_SEC = 21600;
function prop_(k) {
  const c = CacheService.getScriptCache();
  const v = c.get('p_' + k);
  if (v !== null) return v;
  const val = PropertiesService.getScriptProperties().getProperty(k) || '';
  c.put('p_' + k, val, CACHE_SEC);
  return val;
}
function setProp_(k, v) {
  PropertiesService.getScriptProperties().setProperty(k, v);
  CacheService.getScriptCache().put('p_' + k, v, CACHE_SEC);
}

function sheet_() {
  let book = null;
  const id = prop_('BOOK_ID');
  if (id) { try { book = SpreadsheetApp.openById(id); } catch (err) { book = null; } }
  if (!book) {
    book = SpreadsheetApp.create(BOOK_NAME);
    book.setSpreadsheetTimeZone('Asia/Seoul');
    setProp_('BOOK_ID', book.getId());
  }
  let sh = book.getSheetByName('대기열');
  if (!sh) {
    sh = book.insertSheet('대기열');
    sh.getRange(1, 1, 1, HEAD.length).setValues([HEAD]);
    sh.setFrozenRows(1);
  }
  return sh;
}

function folder_(name) {
  const key = 'FOLDER_' + name;
  const id = prop_(key);
  if (id) { try { return DriveApp.getFolderById(id); } catch (err) { /* 지워졌으면 새로 */ } }
  let root;
  const rid = prop_('FOLDER_ROOT');
  try { root = rid ? DriveApp.getFolderById(rid) : null; } catch (err) { root = null; }
  if (!root) { root = DriveApp.createFolder(FOLDER_NAME); setProp_('FOLDER_ROOT', root.getId()); }
  const f = root.createFolder(name);
  setProp_(key, f.getId());
  return f;
}

function rows_() {
  const sh = sheet_();
  const v = sh.getDataRange().getValues();
  return { sh: sh, rows: v.slice(1) };
}

function setRow_(sh, idx, row) {
  sh.getRange(idx + 2, 1, 1, HEAD.length).setValues([row.slice(0, HEAD.length)]);
}

function find_(rows, id) {
  for (let i = 0; i < rows.length; i++) if (String(rows[i][C.id]) === String(id)) return i;
  return -1;
}

function clean_(s, n) {
  return String(s == null ? '' : s).replace(/[\u0000-\u001f<>]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, n);
}

function time_(v) { return v instanceof Date ? v.getTime() : (v ? new Date(v).getTime() : 0); }

function ahead_(rows, idx) {
  let n = 0;
  for (let i = 0; i < idx; i++) { const s = rows[i][C['상태']]; if (s === S.WAIT || s === S.WORK) n++; }
  return n;
}

function lock_(fn) {
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try { return fn(); } finally { lock.releaseLock(); }
}

function blob_(dataUrl, name) {
  const m = /^data:(image\/(?:jpeg|png|webp));base64,(.+)$/.exec(String(dataUrl || ''));
  if (!m) throw new Error('사진을 다시 찍어 주세요');
  if (m[2].length > MAX_IMAGE_CHARS) throw new Error('사진이 너무 커요. 다시 찍어 주세요');
  return Utilities.newBlob(Utilities.base64Decode(m[2]), m[1], name);
}

// ───────── 아이 폰(google.script.run) ─────────
function submitDrawing(form) {
  form = form || {};
  const nickname = clean_(form.nickname, 12);
  const style = String(form.style || '');
  if (!nickname) throw new Error('닉네임을 적어 주세요');
  if (!STYLES[style]) throw new Error('스타일을 골라 주세요');
  const intro = clean_(form.intro, 60);
  const id = Utilities.formatDate(new Date(), 'Asia/Seoul', 'MMdd-HHmmss') + '-' +
    Utilities.getUuid().slice(0, 4);
  const file = folder_('원본').createFile(blob_(form.image, id + '_원본.jpg'));
  return lock_(() => {
    const r = rows_();
    const row = HEAD.map(() => '');
    row[C.id] = id; row[C['받은 시각']] = new Date(); row[C['닉네임']] = nickname;
    row[C['스타일']] = style; row[C['소개']] = intro; row[C['상태']] = S.WAIT;
    row[C['원본 파일']] = file.getId(); row[C['시도']] = 0;
    setRow_(r.sh, r.rows.length, row);
    r.rows.push(row);
    return { id: id, ahead: ahead_(r.rows, r.rows.length - 1) };
  });
}

function getStatus(id) {
  const r = rows_();
  const i = find_(r.rows, id);
  if (i < 0) return { status: 'missing' };
  const row = r.rows[i];
  const lastSeen = Number(CacheService.getScriptCache().get('WORKER_SEEN') || 0);
  return {
    status: row[C['상태']], ahead: ahead_(r.rows, i), nickname: row[C['닉네임']],
    style: row[C['스타일']], styleLabel: STYLES[row[C['스타일']]] || '',
    note: row[C['안내']], printed: row[C['인쇄']] === 'ok', padlet: row[C['패들렛']] === 'ok',
    hasResult: !!row[C['결과 파일']], resultUrl: row[C['결과 주소']] || '',
    padletUrl: prop_('PADLET_URL'),
    workerOnline: Date.now() - lastSeen < 3 * 60 * 1000
  };
}

/** 완성 그림을 data URL로(폰은 드라이브 공유 설정과 상관없이 볼 수 있게). */
function getResultImage(id) {
  const r = rows_();
  const i = find_(r.rows, id);
  if (i < 0 || !r.rows[i][C['결과 파일']]) return '';
  const b = DriveApp.getFileById(r.rows[i][C['결과 파일']]).getBlob();
  return 'data:' + b.getContentType() + ';base64,' + Utilities.base64Encode(b.getBytes());
}

/** 큰 화면 모아 보기: 최근 완성 그림 */
function getWall(limit) {
  const r = rows_();
  const out = [];
  for (let i = r.rows.length - 1; i >= 0 && out.length < (limit || 24); i--) {
    const row = r.rows[i];
    if (row[C['상태']] === S.DONE && row[C['결과 주소']]) {
      out.push({ id: row[C.id], nickname: row[C['닉네임']], styleLabel: STYLES[row[C['스타일']]] || '',
        intro: row[C['소개']], url: row[C['결과 주소']] });
    }
  }
  let waiting = 0;
  r.rows.forEach(row => { if (row[C['상태']] === S.WAIT || row[C['상태']] === S.WORK) waiting++; });
  return { items: out, waiting: waiting };
}

// ───────── 부스 노트북(doPost) ─────────
function doPost(e) {
  let res;
  try {
    const req = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    res = workerApi_(req);
  } catch (err) {
    res = { ok: false, error: String(err && err.message || err) };
  }
  return ContentService.createTextOutput(JSON.stringify(res)).setMimeType(ContentService.MimeType.JSON);
}

function workerApi_(req) {
  const token = prop_('BOOTH_TOKEN');
  if (!token || req.token !== token) return { ok: false, error: 'token' };
  CacheService.getScriptCache().put('WORKER_SEEN', String(Date.now()), 600);
  const fn = { ping: apiPing_, claim: apiClaim_, done: apiDone_, mark: apiMark_, fail: apiFail_ }[req.action];
  if (!fn) return { ok: false, error: 'unknown action' };
  return Object.assign({ ok: true }, fn(req));
}

/** 집 PC가 시작할 때: 아이가 직접 올릴 패들렛 보드 주소를 알려 준다(빈칸이면 버튼을 숨김). */
function apiPing_(req) {
  if (req && typeof req.padletUrl === 'string') {
    const u = req.padletUrl.trim();
    setProp_('PADLET_URL', /^https:\/\/[^\s"'<>]+$/.test(u) ? u : '');
  }
  const r = rows_();
  return { api: BOOTH_API, styles: STYLES, waiting: r.rows.filter(x => x[C['상태']] === S.WAIT).length };
}

/** 가져갈 그림의 줄 번호(대기 중이거나, 가져간 뒤 STALE_MIN 넘게 소식이 없는 것). 없으면 -1 */
function pick_(rows, now) {
  for (let i = 0; i < rows.length; i++) {
    const st = rows[i][C['상태']];
    if (st === S.WAIT) return i;
    if (st === S.WORK && now - time_(rows[i][C['가져간 시각']]) > STALE_MIN * 60 * 1000) return i;
  }
  return -1;
}

/** 집 PC가 몇 초마다 부른다. 대부분은 기다리는 그림이 없으니 잠그지 않고 먼저 보고,
 *  있을 때만 잠깐 잠가 '변환 중'으로 바꾼다. 잠금이 바쁘면 기다리지 않고 '없음'으로 답한다(다음 확인 때 다시). */
function apiClaim_(req) {
  if (pick_(rows_().rows, Date.now()) < 0) return { job: null };
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(5000)) return { job: null, busy: true };
  let row;
  try {
    const r = rows_();
    const now = Date.now();
    const i = pick_(r.rows, now);
    if (i < 0) return { job: null };
    row = r.rows[i];
    row[C['상태']] = S.WORK; row[C['가져간 시각']] = new Date(now);
    row[C['시도']] = Number(row[C['시도']] || 0) + 1;
    setRow_(r.sh, i, row);
  } finally {
    lock.releaseLock();
  }
  const b = DriveApp.getFileById(row[C['원본 파일']]).getBlob();       // 사진 읽기는 잠금 밖에서
  return { job: {
    id: row[C.id], nickname: row[C['닉네임']], style: row[C['스타일']],
    styleLabel: STYLES[row[C['스타일']]] || row[C['스타일']], intro: row[C['소개']], tries: row[C['시도']],
    mime: b.getContentType(), image: Utilities.base64Encode(b.getBytes())
  } };
}

function apiDone_(req) {
  const blob = blob_('data:image/jpeg;base64,' + req.image, req.id + '_결과.jpg');
  const file = folder_('결과').createFile(blob);
  let url = '';
  try {
    file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
    url = 'https://lh3.googleusercontent.com/d/' + file.getId();
  } catch (err) { /* 학교 계정 등 공유가 막혀 있으면 폰 화면만 보인다 */ }
  return lock_(() => {
    const r = rows_();
    const i = find_(r.rows, req.id);
    if (i < 0) throw new Error('없는 작업: ' + req.id);
    const row = r.rows[i];
    row[C['상태']] = S.DONE; row[C['결과 파일']] = file.getId(); row[C['결과 주소']] = url; row[C['안내']] = '';
    setRow_(r.sh, i, row);
    return { fileId: file.getId(), url: url };
  });
}

function apiMark_(req) {
  return lock_(() => {
    const r = rows_();
    const i = find_(r.rows, req.id);
    if (i < 0) throw new Error('없는 작업: ' + req.id);
    const row = r.rows[i];
    if (req.padlet) row[C['패들렛']] = clean_(req.padlet, 80);
    if (req.printed) row[C['인쇄']] = clean_(req.printed, 80);
    setRow_(r.sh, i, row);
    return {};
  });
}

/** 변환 실패. retry면 대기열로 되돌리고(시도 횟수 안에서), 아니면 '오류'와 아이에게 보일 안내를 남긴다. */
function apiFail_(req) {
  return lock_(() => {
    const r = rows_();
    const i = find_(r.rows, req.id);
    if (i < 0) throw new Error('없는 작업: ' + req.id);
    const row = r.rows[i];
    const again = req.retry && (req.force || Number(row[C['시도']] || 0) < MAX_TRIES);
    row[C['상태']] = again ? S.WAIT : S.FAIL;
    row[C['안내']] = clean_(req.note || '', 120);
    if (req.force) row[C['시도']] = 0;
    setRow_(r.sh, i, row);
    return { status: row[C['상태']] };
  });
}
