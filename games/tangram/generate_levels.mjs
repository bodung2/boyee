// 칠교 놀이터 — 100단계 문제 만들기
//
//   node games/tangram/generate_levels.mjs
//
// 정해진 씨앗(seed)으로 늘 같은 100단계를 만들고, index.html의
// /*LEVELS_START*/ ... /*LEVELS_END*/ 사이를 새 문제로 바꾼다.
// 단계마다 조각끼리 겹치지 않는지, 구멍이 없는지, 조각 수가 칠교판 2벌을
// 넘지 않는지 확인하고, 하나라도 어기면 파일을 바꾸지 않고 멈춘다.
//
// 좌표 단위: 작은 삼각형의 짧은 변 = 1. 화면(SVG)처럼 y는 아래로 커진다.
// 조각 자리 = {t: 종류, k: 45° 회전 횟수, f: 뒤집기(평행사변형), x, y: 이동}

import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const HTML = join(HERE, 'index.html');

// ---- 조각 모양 (index.html의 SHAPES와 같아야 한다) ----
const SHAPES = {
  L: [[0, 0], [2, 0], [0, 2]],            // 큰 삼각형 (넓이 2)
  M: [[0, 0], [2, 0], [1, 1]],            // 중간 삼각형 (넓이 1)
  S: [[0, 0], [1, 0], [0, 1]],            // 작은 삼각형 (넓이 0.5)
  Q: [[0, 0], [1, 0], [1, 1], [0, 1]],    // 정사각형 (넓이 1)
  P: [[0, 0], [1, 0], [2, 1], [1, 1]],    // 평행사변형 (넓이 1)
};
const AREA = { L: 2, M: 1, S: 0.5, Q: 1, P: 1 };
const ONE_SET = ['L', 'L', 'M', 'S', 'S', 'Q', 'P'];
const R = Math.SQRT1_2;
const DIRS = [[1, 0], [R, R], [0, 1], [-R, R], [-1, 0], [-R, -R], [0, -1], [R, -R]];
const EPS = 1e-6;

function poly(s) {
  let pts = SHAPES[s.t].map(([a, b]) => [s.f ? -a : a, b]);
  if (s.f) pts.reverse();
  const [c, sn] = DIRS[s.k];
  return pts.map(([a, b]) => [a * c - b * sn + s.x, a * sn + b * c + s.y]);
}

// ---- 씨앗 난수 ----
function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const pick = (rnd, arr) => arr[Math.floor(rnd() * arr.length)];
function shuffle(rnd, arr) {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(rnd() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

// ---- 기하 ----
function overlaps(A, B) { // 볼록 다각형이 넓이를 가지고 겹치는가 (분리축)
  for (const P of [A, B]) {
    for (let i = 0; i < P.length; i++) {
      const [x1, y1] = P[i], [x2, y2] = P[(i + 1) % P.length];
      const nx = y1 - y2, ny = x2 - x1;
      let a0 = Infinity, a1 = -Infinity, b0 = Infinity, b1 = -Infinity;
      for (const [x, y] of A) { const d = x * nx + y * ny; a0 = Math.min(a0, d); a1 = Math.max(a1, d); }
      for (const [x, y] of B) { const d = x * nx + y * ny; b0 = Math.min(b0, d); b1 = Math.max(b1, d); }
      if (Math.min(a1, b1) - Math.max(a0, b0) < 1e-5) return false;
    }
  }
  return true;
}
function edges(P) { return P.map((p, i) => [p, P[(i + 1) % P.length]]); }
function contact(A, B) { // 맞닿은 변의 길이 합
  let sum = 0;
  for (const [a, b] of edges(A)) {
    const dx = b[0] - a[0], dy = b[1] - a[1], L = Math.hypot(dx, dy), ux = dx / L, uy = dy / L;
    for (const [c, d] of edges(B)) {
      const ex = d[0] - c[0], ey = d[1] - c[1], M = Math.hypot(ex, ey);
      if (Math.abs(ex / M + ux) > EPS || Math.abs(ey / M + uy) > EPS) continue; // 반대 방향만
      if (Math.abs((c[0] - a[0]) * uy - (c[1] - a[1]) * ux) > EPS) continue;     // 같은 직선
      const t1 = (c[0] - a[0]) * ux + (c[1] - a[1]) * uy, t2 = (d[0] - a[0]) * ux + (d[1] - a[1]) * uy;
      const lo = Math.max(0, Math.min(t1, t2)), hi = Math.min(L, Math.max(t1, t2));
      if (hi > lo + EPS) sum += hi - lo;
    }
  }
  return sum;
}
function bbox(polys) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const P of polys) for (const [x, y] of P) {
    x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y);
  }
  return { x0, y0, x1, y1, w: x1 - x0, h: y1 - y0 };
}
function inside(P, x, y) {
  for (let i = 0; i < P.length; i++) {
    const [x1, y1] = P[i], [x2, y2] = P[(i + 1) % P.length];
    if ((x2 - x1) * (y - y1) - (y2 - y1) * (x - x1) < -1e-9) return false;
  }
  return true;
}
// 래스터로 구멍(닫힌 빈 곳)과 겹침 확인
function rasterCheck(polys) {
  const st = 0.05, b = bbox(polys);
  const W = Math.ceil((b.w + 1) / st), H = Math.ceil((b.h + 1) / st);
  const grid = new Uint8Array(W * H);
  let over = 0, filled = 0;
  for (let j = 0; j < H; j++) for (let i = 0; i < W; i++) {
    const x = b.x0 - 0.5 + (i + 0.37) * st, y = b.y0 - 0.5 + (j + 0.41) * st;
    let n = 0;
    for (const P of polys) if (inside(P, x, y)) n++;
    if (n) { grid[j * W + i] = 1; filled++; }
    if (n > 1) over++;
  }
  // 바깥에서 4방향으로 물 채우기 — 닿지 않는 빈 칸이 있으면 구멍
  const seen = new Uint8Array(W * H), stack = [0];
  seen[0] = 1;
  while (stack.length) {
    const p = stack.pop(), i = p % W, j = (p / W) | 0;
    for (const [di, dj] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      const a = i + di, c = j + dj;
      if (a < 0 || c < 0 || a >= W || c >= H) continue;
      const q = c * W + a;
      if (seen[q] || grid[q]) continue;
      seen[q] = 1; stack.push(q);
    }
  }
  let holes = 0;
  for (let p = 0; p < W * H; p++) if (!grid[p] && !seen[p]) holes++;
  return { over, holes, area: filled * st * st };
}

// ---- 조각 하나씩 변을 맞대어 붙여 가며 모양 만들기 ----
function grow(rnd, types, rots, flips) {
  const slots = [];
  const polys = [];
  const first = { t: types[0], k: pick(rnd, rots), f: flips && types[0] === 'P' ? rnd() < 0.5 : false, x: 0, y: 0 };
  slots.push(first); polys.push(poly(first));
  for (const t of types.slice(1)) {
    const cands = [];
    for (const k of rots) for (const f of (t === 'P' && flips ? [false, true] : [false])) {
      const base = poly({ t, k, f, x: 0, y: 0 });
      for (const P of polys) for (const [a, b] of edges(P)) {
        const dx = b[0] - a[0], dy = b[1] - a[1], L = Math.hypot(dx, dy);
        for (const [c, d] of edges(base)) {
          const ex = d[0] - c[0], ey = d[1] - c[1], M = Math.hypot(ex, ey);
          if (Math.abs(ex / M + dx / L) > EPS || Math.abs(ey / M + dy / L) > EPS) continue;
          for (const [tx, ty] of [[b[0] - c[0], b[1] - c[1]], [a[0] - d[0], a[1] - d[1]]]) {
            const s = { t, k, f, x: tx, y: ty }, Q = poly(s);
            if (polys.some(Z => overlaps(Z, Q))) continue;
            cands.push({ s, Q });
          }
        }
      }
    }
    if (!cands.length) return null;
    const before = bbox(polys);
    for (const c of cands) {
      const touch = polys.reduce((acc, Z) => acc + contact(Z, c.Q), 0);
      const nb = bbox([...polys, c.Q]);
      const grow = nb.w * nb.h - before.w * before.h;
      const lopsided = Math.abs(nb.w - nb.h);
      c.score = touch * 1.6 - grow * 0.35 - lopsided * 0.25 + rnd() * 1.4;
    }
    cands.sort((p, q) => q.score - p.score);
    const best = cands[Math.floor(rnd() * Math.min(2, cands.length))];
    slots.push(best.s); polys.push(best.Q);
  }
  return slots;
}

// 다각형(꼭짓점 목록)에 꼭 맞는 조각 자리 {t,k,f,x,y}를 찾는다
function slotFor(t, P) {
  const key = Q => Q.map(([x, y]) => String(Math.round(x * 1e4)) + ',' + String(Math.round(y * 1e4))).sort().join(' ');
  const cx = P.reduce((s, p) => s + p[0], 0) / P.length, cy = P.reduce((s, p) => s + p[1], 0) / P.length;
  const want = key(P.map(([x, y]) => [x - cx, y - cy]));
  for (let k = 0; k < 8; k++) for (const f of [false, true]) {
    const B = poly({ t, k, f, x: 0, y: 0 });
    const bx = B.reduce((s, p) => s + p[0], 0) / B.length, by = B.reduce((s, p) => s + p[1], 0) / B.length;
    if (key(B.map(([x, y]) => [x - bx, y - by])) === want) return { t, k, f, x: cx - bx, y: cy - by };
  }
  throw new Error('맞는 조각 자리를 못 찾음: ' + t);
}

// 오른쪽 끝 세로 변을 기준으로 좌우 대칭 복사 (칠교판 2벌용)
function mirror(slots) {
  const polys = slots.map(poly), b = bbox(polys);
  let onEdge = 0;
  for (const P of polys) for (const [a, c] of edges(P)) {
    if (Math.abs(a[0] - b.x1) < EPS && Math.abs(c[0] - b.x1) < EPS) onEdge += Math.abs(c[1] - a[1]);
  }
  if (onEdge < 0.99) return null;
  const out = slots.slice();
  for (const s of slots) {
    const M = poly(s).map(([x, y]) => [2 * b.x1 - x, y]).reverse();
    out.push(slotFor(s.t, M));
  }
  return out;
}

// 이름 있는 모양: 칠교판 정사각형 (4×4 그림을 1/√2배로 줄인 꼴)
function classicSquare(ox = 0) {
  const s = Math.SQRT1_2;
  const raw = [
    ['L', [[0, 0], [4, 0], [2, 2]]], ['L', [[0, 0], [2, 2], [0, 4]]],
    ['M', [[2, 4], [4, 4], [4, 2]]], ['S', [[4, 0], [4, 2], [3, 1]]],
    ['Q', [[2, 2], [3, 1], [4, 2], [3, 3]]], ['S', [[1, 3], [2, 2], [3, 3]]],
    ['P', [[0, 4], [1, 3], [3, 3], [2, 4]]],
  ];
  return raw.map(([t, P]) => {
    let Q = P.map(([x, y]) => [x * s + ox, y * s]);
    // 꼭짓점 순서를 조각 정의와 같은 방향으로
    const area = Q.reduce((acc, p, i) => { const q = Q[(i + 1) % Q.length]; return acc + p[0] * q[1] - q[0] * p[1]; }, 0);
    if (area < 0) Q = Q.reverse();
    return slotFor(t, Q);
  });
}

// ---- 단계별 난이도 ----
function plan(n) {
  // pieces: 조각 수, rot: 돌리기 단위, hint: 조각 선 보이기, same: 처음부터 정답 방향
  if (n <= 8) return { pieces: n <= 4 ? 2 : 3, rot: 90, hint: 'all', same: true };
  if (n <= 20) return { pieces: n <= 14 ? 3 : 4, rot: 90, hint: 'all', same: false };
  if (n <= 35) return { pieces: n <= 27 ? 4 : 5, rot: 45, hint: 'all', same: false };
  if (n <= 50) return { pieces: n <= 42 ? 5 : n <= 46 ? 6 : 7, rot: 45, hint: 'some', same: false, flip: true };
  if (n <= 70) return { pieces: n <= 56 ? 7 : n <= 63 ? 8 : 9, rot: 45, hint: 'none', same: false, flip: true };
  if (n <= 90) return { pieces: n <= 76 ? 10 : n <= 83 ? 11 : 12, rot: 45, hint: 'none', same: false, flip: true };
  return { pieces: n <= 95 ? 13 : 14, rot: 45, hint: 'none', same: false, flip: true };
}

function chooseTypes(rnd, count) {
  if (count >= 7) {
    const extra = shuffle(rnd, ONE_SET).slice(0, count - 7);
    return [...ONE_SET, ...extra];
  }
  return shuffle(rnd, ONE_SET).slice(0, count);
}
function ordered(rnd, types) { // 큰 조각부터 붙여야 모양이 단단하다
  const rank = { L: 0, M: 1, Q: 1, P: 1, S: 2 };
  return shuffle(rnd, types).sort((a, b) => rank[a] - rank[b]);
}

const round = v => Math.round(v * 1e6) / 1e6;
function normalize(slots) {
  const b = bbox(slots.map(poly));
  return slots.map(s => ({ t: s.t, k: s.k, f: s.f ? 1 : 0, x: round(s.x - b.x0), y: round(s.y - b.y0) }));
}

function makeLevel(n) {
  const p = plan(n);
  if (n === 50) return { ...p, name: '칠교판 정사각형', slots: classicSquare() };
  if (n === 100) return { ...p, name: '정사각형 두 개', slots: [...classicSquare(0), ...classicSquare(2 * Math.SQRT2)] };
  const rnd = rng(9173 + n * 7919);
  const rots = p.rot === 90 ? [0, 2, 4, 6] : [0, 1, 2, 3, 4, 5, 6, 7];
  for (let tries = 0; tries < 400; tries++) {
    let slots;
    const useMirror = p.pieces >= 8 && p.pieces % 2 === 0 && rnd() < 0.45;
    if (useMirror) {
      const half = grow(rnd, ordered(rnd, chooseTypes(rnd, p.pieces / 2)), rots, p.flip);
      slots = half && mirror(half);
    } else {
      slots = grow(rnd, ordered(rnd, chooseTypes(rnd, p.pieces)), rots, p.flip);
    }
    if (!slots) continue;
    const polys = slots.map(poly);
    const chk = rasterCheck(polys);
    if (chk.holes > 0 || chk.over > 0) continue;
    const b = bbox(polys);
    if (Math.max(b.w, b.h) > 2.6 + p.pieces * 0.55) continue; // 너무 길쭉하면 다시
    if (p.pieces >= 3 && Math.max(b.w, b.h) / Math.max(0.1, Math.min(b.w, b.h)) > 3) continue;
    return { ...p, name: useMirror ? '대칭 모양' : '', slots };
  }
  throw new Error(n + '단계 모양을 만들지 못함');
}

// ---- 만들고 검사 ----
const levels = [];
for (let n = 1; n <= 100; n++) {
  const L = makeLevel(n);
  const slots = normalize(L.slots);
  const polys = slots.map(poly);
  const chk = rasterCheck(polys);
  const want = slots.reduce((s, x) => s + AREA[x.t], 0);
  const count = {};
  for (const s of slots) count[s.t] = (count[s.t] || 0) + 1;
  const okCount = (count.L || 0) <= 4 && (count.M || 0) <= 2 && (count.S || 0) <= 4 && (count.Q || 0) <= 2 && (count.P || 0) <= 2;
  if (chk.holes || chk.over || Math.abs(chk.area - want) > want * 0.03 || !okCount || slots.length !== L.pieces) {
    console.error(n, chk, want, count);
    throw new Error(n + '단계 검사 실패');
  }
  for (let i = 0; i < polys.length; i++) for (let j = i + 1; j < polys.length; j++) {
    if (overlaps(polys[i], polys[j])) throw new Error(n + '단계 조각 겹침');
  }
  levels.push({ n, name: L.name, rot: L.rot, hint: L.hint, same: L.same ? 1 : 0, s: slots.map(s => [s.t, s.k, s.f, s.x, s.y]) });
}

const json = JSON.stringify(levels);
const html = readFileSync(HTML, 'utf8');
const re = /\/\*LEVELS_START\*\/[\s\S]*?\/\*LEVELS_END\*\//;
if (!re.test(html)) throw new Error('index.html에 LEVELS 자리표시가 없음');
writeFileSync(HTML, html.replace(re, `/*LEVELS_START*/${json}/*LEVELS_END*/`));
const sizes = levels.map(l => l.s.length);
console.log(`100단계 저장 완료 — 조각 수 ${sizes[0]}개 → ${sizes[99]}개, ${json.length.toLocaleString()}바이트`);
