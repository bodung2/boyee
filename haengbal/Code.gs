/**
 * 행발 기록 도우미 웹앱 (구글 Apps Script, '나만' 접근으로 배포)
 *
 * - 화면은 같은 프로젝트의 Index.html(= 저장소 haengbal/index.html 내용을 그대로 붙여 넣은 것).
 * - 기록은 이 구글 계정의 비공개 시트 '행발 기록 도우미 (데이터)'에만 저장된다(처음 열 때 자동 생성).
 *   저장소에는 이 코드와 화면만 있고 학생 기록은 올라가지 않는다.
 * - 화면은 클릭을 바로 반영하고, 바뀐 부분(학생 한 명·한 영역 단위)만 모아 뒤에서 saveUnits로 보낸다.
 *   그래서 시트 저장 속도(1초 안팎)가 클릭 반응을 느리게 하지 않는다.
 * - 시트 탭: 학년도 / 기록 / 추가문장 / 숨긴문장. A열 키, B열 원본(JSON)은 프로그램용, C열부터는 사람이 읽는 칸.
 *   시트를 직접 고치지 말고 화면에서 고친다(직접 고친 C열 이후 내용은 다음 저장 때 덮어써진다).
 * - 이 코드가 바뀌면 API_VERSION이 올라가고, 화면(NEED_API)이 '새로 붙여 넣기'를 알린다.
 * 설치·갱신 방법: haengbal/README.md
 */
const API_VERSION = 1;
const BOOK_NAME = '행발 기록 도우미 (데이터)';
const TABS = {
  Y: ['학년도', ['키', '원본', '학년도', '학생 수', '확정', '확정 시각']],
  R: ['기록', ['키', '원본', '학년도', '영역', '번호', '이름', '최종 문장', '수정 시각']],
  C: ['추가문장', ['키', '원본', '영역', '묶음', '문장']],
  H: ['숨긴문장', ['키', '원본', '영역', '문장']],
};

function doGet() {
  return HtmlService.createHtmlOutputFromFile('Index')
    .setTitle('행발 기록 도우미')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

function book_() {
  const props = PropertiesService.getScriptProperties();
  const id = props.getProperty('BOOK_ID');
  if (id) {
    try { return SpreadsheetApp.openById(id); } catch (e) { /* 지워졌으면 새로 만든다 */ }
  }
  const ss = SpreadsheetApp.create(BOOK_NAME);
  props.setProperty('BOOK_ID', ss.getId());
  return ss;
}

function tab_(ss, p) {
  const [name, head] = TABS[p];
  let sh = ss.getSheetByName(name);
  if (!sh) {
    sh = ss.insertSheet(name);
    sh.getRange(1, 1, 1, head.length).setValues([head]).setFontWeight('bold');
    sh.setFrozenRows(1);
    sh.getRange('A:Z').setNumberFormat('@');   // 문장이 숫자·수식으로 바뀌지 않게
    sh.hideColumns(1, 2);
    const first = ss.getSheetByName('Sheet1') || ss.getSheetByName('시트1');
    if (first && ss.getSheets().length > 1 && first.getLastRow() === 0) ss.deleteSheet(first);
  }
  return sh;
}

/** 화면이 처음 열릴 때: 모든 기록을 {키: 원본} 으로 돌려준다. */
function loadAll() {
  const ss = book_();
  const units = {};
  Object.keys(TABS).forEach(p => {
    const sh = tab_(ss, p);
    const n = sh.getLastRow();
    if (n < 2) return;
    sh.getRange(2, 1, n - 1, 2).getValues().forEach(([k, v]) => { if (k) units[k] = String(v); });
  });
  return { api: API_VERSION, units: units, url: ss.getUrl() };
}

/**
 * 바뀐 것만 저장한다. list = [{k: 키, v: 원본(JSON 문자열) 또는 null(지우기), c: [사람이 읽는 칸...]}]
 * 키의 첫 글자(Y/R/C/H)로 탭을 고른다. 같은 키가 있으면 그 줄을 고치고, 없으면 아래에 붙인다.
 */
function saveUnits(list) {
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    const ss = book_();
    const last = {};
    (list || []).forEach(u => { last[u.k] = u; });   // 같은 키가 두 번 오면 마지막 것만
    const groups = {};
    Object.keys(last).map(k => last[k]).forEach(u => {
      const p = String(u.k).charAt(0);
      if (!TABS[p]) throw new Error('알 수 없는 키: ' + u.k);
      (groups[p] = groups[p] || []).push(u);
    });
    Object.keys(groups).forEach(p => {
      const sh = tab_(ss, p);
      const width = TABS[p][1].length;
      const n = sh.getLastRow();
      const keys = n > 1 ? sh.getRange(2, 1, n - 1, 1).getValues().map(r => r[0]) : [];
      const at = {};
      keys.forEach((k, i) => { if (k) at[k] = i + 2; });
      const adds = [], dels = [];
      groups[p].forEach(u => {
        const row = at[u.k];
        if (u.v === null || u.v === undefined) {
          if (row) dels.push(row);
          return;
        }
        const vals = [u.k, u.v].concat(u.c || []);
        while (vals.length < width) vals.push('');
        vals.length = width;
        if (row) sh.getRange(row, 1, 1, width).setValues([vals]);
        else adds.push(vals);
      });
      if (adds.length) sh.getRange(sh.getLastRow() + 1, 1, adds.length, width).setValues(adds);
      dels.sort((a, b) => b - a).forEach(r => sh.deleteRow(r));
    });
    return { ok: true, api: API_VERSION, n: (list || []).length };
  } finally {
    lock.releaseLock();
  }
}
