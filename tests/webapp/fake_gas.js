/**
 * 구글 Apps Script 서비스의 작은 가짜(테스트용). webapp/Code.gs를 Node나 브라우저에서 그대로 돌려 본다.
 *  - 시트: 값 저장, '로 시작하면 글자로(따옴표는 빠짐), =GOOGLEFINANCE(...) 수식은 fake.gf 표로 계산
 *  - UrlFetchApp: 업비트·네이버 증권 주소를 fake.coins·fake.naver 표로 흉내(업비트는 없는 코인이 섞이면 404)
 *  - DriveApp: fake.files 이름 → 내용
 */
(function (root) {
  function make(opts) {
    opts = opts || {};
    const fake = {
      gf: opts.gf || {}, coins: opts.coins || {}, naver: opts.naver || {}, files: opts.files || {},
      props: {}, books: {}, triggers: [], fetched: [], now: opts.now || new Date('2026-11-08T07:00:00Z')
    };
    let seq = 0;

    function kst(d) { return new Date(d.getTime() + 9 * 3600e3); }
    const p2 = n => String(n).padStart(2, '0');
    const Utilities = {
      formatDate(d, tz, fmt) {
        const k = kst(d);
        const day = k.getUTCFullYear() + '-' + p2(k.getUTCMonth() + 1) + '-' + p2(k.getUTCDate());
        if (fmt === 'yyyy-MM-dd') return day;
        return day + 'T' + p2(k.getUTCHours()) + ':' + p2(k.getUTCMinutes()) + ':' + p2(k.getUTCSeconds()) + '+09:00';
      },
      getUuid() { return 'id-' + (++seq); },
      sleep() {}
    };

    // '로 시작해 저장한 칸은 글자 그대로(수식으로 계산하지 않음) — 실제 시트와 같다
    function Text(v) { this.v = v; }
    function evalCell(v) {
      if (v instanceof Text) return v.v;
      if (typeof v !== 'string' || v[0] !== '=') return v;
      // =IFERROR(GOOGLEFINANCE("KRX:005930","price"),IFERROR(GOOGLEFINANCE("KOSDAQ:005930","price"),""))
      const syms = [];
      v.replace(/GOOGLEFINANCE\("([^"]+)"/g, (m, s) => syms.push(s));
      for (const s of syms) if (s in fake.gf) return fake.gf[s];
      return '';
    }
    function Sheet(name) {
      this.name = name; this.data = [];
    }
    Sheet.prototype = {
      getDataRange() { const self = this; return { getValues() { return self.data.map(r => r.map(evalCell)); } }; },
      clearContents() { this.data = []; },
      setFrozenRows() {},
      getRange(r, c, nr, nc) {
        const self = this;
        nr = nr || 1; nc = nc || 1;
        return {
          setValues(vals) {
            if (vals.length !== nr || vals.some(row => row.length !== nc)) throw new Error('setValues 크기가 맞지 않음');
            vals.forEach((row, i) => row.forEach((v, j) => {
              while (self.data.length < r + i) self.data.push([]);
              const line = self.data[r + i - 1];
              line[c + j - 1] = typeof v === 'string' && v[0] === "'" ? new Text(v.slice(1)) : v;
            }));
          },
          getValues() {
            const out = [];
            for (let i = 0; i < nr; i++) {
              const row = [];
              for (let j = 0; j < nc; j++) row.push(evalCell(((self.data[r + i - 1] || [])[c + j - 1]) ?? ''));
              out.push(row);
            }
            return out;
          }
        };
      }
    };
    function Book(name) { this.id = 'book-' + (++seq); this.name = name; this.sheets = {}; this.tz = ''; }
    Book.prototype = {
      getId() { return this.id; }, getUrl() { return 'https://docs.google.com/spreadsheets/d/' + this.id; },
      setSpreadsheetTimeZone(tz) { this.tz = tz; },
      getSheetByName(n) { return this.sheets[n] || null; },
      insertSheet(n) { return (this.sheets[n] = new Sheet(n)); }
    };
    const SpreadsheetApp = {
      create(name) { const b = new Book(name); fake.books[b.id] = b; return b; },
      openById(id) { if (!fake.books[id]) throw new Error('없는 시트'); return fake.books[id]; },
      flush() {}
    };
    const PropertiesService = { getScriptProperties() {
      return { getProperty: k => (k in fake.props ? fake.props[k] : null), setProperty: (k, v) => { fake.props[k] = String(v); } };
    } };
    const LockService = { getScriptLock() { return { waitLock() {}, releaseLock() {} }; } };
    const DriveApp = { getFilesByName(n) {
      const list = n in fake.files ? [{ isTrashed: () => false, getLastUpdated: () => new Date(0),
        getBlob: () => ({ getDataAsString: () => fake.files[n] }) }] : [];
      let i = 0;
      return { hasNext: () => i < list.length, next: () => list[i++] };
    } };
    function resp(code, body) { return { getResponseCode: () => code, getContentText: () => JSON.stringify(body) }; }
    const UrlFetchApp = { fetch(url) {
      fake.fetched.push(url);
      let m = /api\.upbit\.com\/v1\/ticker\?markets=(.+)$/.exec(url);
      if (m) {
        const mk = m[1].split(',');
        if (mk.some(x => !(x.slice(4) in fake.coins))) return resp(404, { error: { name: 404 } });
        return resp(200, mk.map(x => ({ market: x, trade_price: fake.coins[x.slice(4)] })));
      }
      m = /m\.stock\.naver\.com\/api\/stock\/(\w+)\/basic/.exec(url);
      if (m) return m[1] in fake.naver ? resp(200, { closePrice: Number(fake.naver[m[1]]).toLocaleString('en-US') }) : resp(409, {});
      return resp(404, {});
    } };
    const ScriptApp = {
      getProjectTriggers() { return fake.triggers.map(t => ({ getHandlerFunction: () => t.fn })); },
      newTrigger(fn) {
        const t = { fn };
        const chain = { timeBased: () => chain, everyDays: d => (t.days = d, chain), atHour: h => (t.hour = h, chain),
          inTimezone: z => (t.tz = z, chain), create: () => { fake.triggers.push(t); return t; } };
        return chain;
      }
    };
    function Out(html) { this.html = html; this.title = ''; }
    Out.prototype = { setTitle(t) { this.title = t; return this; }, addMetaTag() { return this; } };
    const HtmlService = { createHtmlOutput: h => new Out(h) };
    fake.globals = { Utilities, SpreadsheetApp, PropertiesService, LockService, DriveApp, UrlFetchApp, ScriptApp, HtmlService };
    return fake;
  }
  if (typeof module !== 'undefined') module.exports = { make };
  else root.FakeGas = { make };
})(this);
