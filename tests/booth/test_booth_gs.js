/* booth/apps_script/Code.gs를 작은 가짜 Apps Script 위에서 돌린다. 실행: node tests/booth/test_booth_gs.js (pytest가 부름) */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const CODE = fs.readFileSync(path.join(__dirname, '..', '..', 'booth', 'apps_script', 'Code.gs'), 'utf8');

function load(opts) {
  opts = opts || {};
  const fake = { props: {}, files: {}, sheets: [], now: Date.parse('2026-11-28T01:00:00Z'), shareFails: !!opts.shareFails };
  let seq = 0;
  function Sheet() { this.data = []; }
  Sheet.prototype = {
    getDataRange() { const s = this; return { getValues: () => s.data.map(r => r.slice()) }; },
    setFrozenRows() {},
    getRange(r, c, nr, nc) {
      const s = this;
      return { setValues(v) {
        assert.equal(v.length, nr); v.forEach(row => assert.equal(row.length, nc));
        v.forEach((row, i) => { while (s.data.length < r + i) s.data.push([]); row.forEach((x, j) => { s.data[r + i - 1][c + j - 1] = x; }); });
      } };
    }
  };
  function Book() { this.id = 'book-' + (++seq); this.sheets = {}; }
  Book.prototype = {
    getId() { return this.id; }, getUrl() { return 'https://sheet/' + this.id; }, setSpreadsheetTimeZone() {},
    getSheetByName(n) { return this.sheets[n] || null; },
    insertSheet(n) { const s = new Sheet(); fake.sheets.push(s); return (this.sheets[n] = s); }
  };
  const books = {};
  function Blob(bytes, type, name) { this.bytes = bytes; this.type = type; this.name = name; }
  Blob.prototype = { getBytes() { return this.bytes; }, getContentType() { return this.type; } };
  function File(blob) { this.id = 'file-' + (++seq); this.blob = blob; this.sharing = null; fake.files[this.id] = this; }
  File.prototype = {
    getId() { return this.id; }, getBlob() { return this.blob; },
    setSharing(a, p) { if (fake.shareFails) throw new Error('domain policy'); this.sharing = [a, p]; }
  };
  function Folder(name) { this.id = 'folder-' + (++seq); this.name = name; folders[this.id] = this; }
  Folder.prototype = {
    getId() { return this.id; }, createFolder(n) { return new Folder(n); }, createFile(b) { return new File(b); }
  };
  const folders = {};
  const globals = {
    PropertiesService: { getScriptProperties: () => ({
      getProperty: k => (k in fake.props ? fake.props[k] : null), setProperty: (k, v) => { fake.props[k] = String(v); } }) },
    SpreadsheetApp: {
      create() { const b = new Book(); books[b.id] = b; return b; },
      openById(id) { if (!books[id]) throw new Error('no book'); return books[id]; }
    },
    DriveApp: {
      Access: { ANYONE_WITH_LINK: 'anyone' }, Permission: { VIEW: 'view' },
      createFolder: n => new Folder(n),
      getFolderById(id) { if (!folders[id]) throw new Error('no folder'); return folders[id]; },
      getFileById(id) { if (!fake.files[id]) throw new Error('no file'); return fake.files[id]; }
    },
    Utilities: {
      getUuid: () => String(1000 + (++seq)) + 'abcd-0000-0000',
      formatDate: () => '1128-100000',
      newBlob: (b, t, n) => new Blob(b, t, n),
      base64Decode: s => Buffer.from(s, 'base64').toString('latin1'),
      base64Encode: b => Buffer.from(b, 'latin1').toString('base64')
    },
    LockService: { getScriptLock: () => ({ waitLock() {}, releaseLock() {} }) },
    ContentService: { MimeType: { JSON: 'json' }, createTextOutput: t => ({ text: t, setMimeType() { return this; } }) },
    console: { log() {} },
    Date: class extends Date { constructor(...a) { if (a.length) super(...a); else super(fake.now); } static now() { return fake.now; } }
  };
  const ctx = vm.createContext({ ...globals, JSON, Math, Number, String, Object, Array, Buffer });
  vm.runInContext(CODE, ctx);
  return { gas: ctx, fake };
}
const IMG = 'data:image/jpeg;base64,' + Buffer.from('JPEGDATA').toString('base64');
const post = (gas, body) => JSON.parse(gas.doPost({ postData: { contents: JSON.stringify(body) } }).text);
const tests = [];
const test = (n, f) => tests.push([n, f]);

test('setupBooth는 토큰·시트·폴더를 한 번만 만든다', () => {
  const { gas, fake } = load();
  const msg = gas.setupBooth();
  const token = fake.props.BOOTH_TOKEN;
  assert.ok(token && msg.includes('BOOTH_TOKEN=' + token));
  gas.setupBooth();
  assert.equal(fake.props.BOOTH_TOKEN, token);
  assert.equal(fake.sheets.length, 1);
});

test('토큰이 틀리면 노트북 요청을 거절한다', () => {
  const { gas } = load();
  gas.setupBooth();
  assert.deepEqual(post(gas, { token: 'x', action: 'ping' }), { ok: false, error: 'token' });
});

test('아이가 보낸 그림: 검증 → 대기 → 노트북이 가져가 완성 → 상태·결과 그림', () => {
  const { gas, fake } = load();
  gas.setupBooth();
  const T = fake.props.BOOTH_TOKEN;
  assert.throws(() => gas.submitDrawing({ nickname: '', style: 'felt', image: IMG }), /닉네임/);
  assert.throws(() => gas.submitDrawing({ nickname: '토끼', style: 'nope', image: IMG }), /스타일/);
  assert.throws(() => gas.submitDrawing({ nickname: '토끼', style: 'felt', image: 'data:text/html;base64,AA' }), /사진/);
  const a = gas.submitDrawing({ nickname: '  별빛<b>토끼</b>이름이아주아주길어요 ', style: 'felt', intro: '축구\n좋아함', image: IMG });
  const b = gas.submitDrawing({ nickname: '곰', style: 'pixel', image: IMG });
  assert.equal(a.ahead, 0); assert.equal(b.ahead, 1);
  let st = gas.getStatus(a.id);
  assert.equal(st.status, '대기'); assert.equal(st.nickname.length <= 12, true); assert.ok(!st.nickname.includes('<'));
  assert.equal(st.workerOnline, false);

  const c = post(gas, { token: T, action: 'claim', worker: 'pc-1' });
  assert.equal(c.job.id, a.id); assert.equal(c.job.styleLabel, '양모펠트 인형'); assert.equal(c.job.intro, '축구 좋아함');
  assert.equal(Buffer.from(c.job.image, 'base64').toString(), 'JPEGDATA');
  assert.equal(gas.getStatus(a.id).status, '변환 중');
  assert.equal(gas.getStatus(a.id).workerOnline, true);
  assert.equal(gas.getStatus(b.id).ahead, 1);
  const c2 = post(gas, { token: T, action: 'claim', worker: 'pc-2' });
  assert.equal(c2.job.id, b.id);
  assert.equal(post(gas, { token: T, action: 'claim' }).job, null);

  const d = post(gas, { token: T, action: 'done', id: a.id, image: Buffer.from('RESULT').toString('base64') });
  assert.ok(d.url.startsWith('https://lh3.googleusercontent.com/d/file-'));
  assert.deepEqual(fake.files[d.fileId].sharing, ['anyone', 'view']);
  post(gas, { token: T, action: 'mark', id: a.id, printed: 'ok', padlet: 'ok' });
  st = gas.getStatus(a.id);
  assert.equal(st.status, '완성'); assert.equal(st.printed, true); assert.equal(st.padlet, true);
  assert.equal(gas.getResultImage(a.id), 'data:image/jpeg;base64,' + Buffer.from('RESULT').toString('base64'));
  const wall = gas.getWall();
  assert.equal(wall.items.length, 1); assert.equal(wall.items[0].url, d.url); assert.equal(wall.waiting, 1);
});

test('원본 그림은 공유하지 않고, 공유가 막힌 계정이면 결과 주소 없이 완성만 표시한다', () => {
  const { gas, fake } = load({ shareFails: true });
  gas.setupBooth();
  const T = fake.props.BOOTH_TOKEN;
  const a = gas.submitDrawing({ nickname: '곰', style: 'clay', image: IMG });
  const job = post(gas, { token: T, action: 'claim' }).job;
  const orig = Object.values(fake.files)[0];
  assert.equal(orig.sharing, null);
  const d = post(gas, { token: T, action: 'done', id: job.id, image: 'UkVT' });
  assert.equal(d.url, '');
  assert.equal(gas.getStatus(a.id).status, '완성');
  assert.equal(gas.getWall().items.length, 0);
});

test('실패: 두 번까지 다시, 그 뒤엔 오류와 안내. 한도(force)는 횟수를 세지 않는다', () => {
  const { gas, fake } = load();
  gas.setupBooth();
  const T = fake.props.BOOTH_TOKEN;
  const a = gas.submitDrawing({ nickname: '곰', style: 'clay', image: IMG });
  post(gas, { token: T, action: 'claim' });
  assert.equal(post(gas, { token: T, action: 'fail', id: a.id, retry: true, force: true, note: '쉬는 중' }).status, '대기');
  assert.equal(post(gas, { token: T, action: 'claim' }).job.tries, 1);
  assert.equal(post(gas, { token: T, action: 'fail', id: a.id, retry: true, note: '다시' }).status, '대기');
  assert.equal(post(gas, { token: T, action: 'claim' }).job.tries, 2);
  assert.equal(post(gas, { token: T, action: 'fail', id: a.id, retry: true, note: '선생님께' }).status, '오류');
  const st = gas.getStatus(a.id);
  assert.equal(st.status, '오류'); assert.equal(st.note, '선생님께');
});

test('노트북이 가져간 뒤 12분 넘게 소식이 없으면 다시 가져갈 수 있다', () => {
  const { gas, fake } = load();
  gas.setupBooth();
  const T = fake.props.BOOTH_TOKEN;
  gas.submitDrawing({ nickname: '곰', style: 'clay', image: IMG });
  post(gas, { token: T, action: 'claim' });
  fake.now += 5 * 60e3;
  assert.equal(post(gas, { token: T, action: 'claim' }).job, null);
  fake.now += 8 * 60e3;
  assert.equal(post(gas, { token: T, action: 'claim' }).job.tries, 2);
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log('ok   ' + name); } catch (e) { failed++; console.log('FAIL ' + name + '\n' + (e.stack || e)); }
}
process.exit(failed ? 1 : 0);
