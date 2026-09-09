// site/build.mjs — 레지스트리 마크다운 → _site/ 정적 페이지
//
// 원본: 10_REGION_REGISTRY.md(요약표·OPEN QUESTIONS), regions/*.md(구역 상세·추정·매물),
//       00_PROJECT_BRIEF.md(§4 규제 — 초기 현금 산식의 입력), 20·DECISIONS(문서 뷰 원문)
// 산출: _site/index.html(메인), _site/regions/NN.html(구역), _site/docs.html(문서 뷰), _site/data.json(검증용)
// 의존성: Node 내장 모듈만. npm install 없음.
// 규약이 깨지면 exit 1 — CI가 실패한다. 경고는 로그와 data.json에 남긴다.
// 파서가 기대는 md 규약은 site/README.md 참조.
//
// 독자는 사용자 부부 2명(실거주 전제 투자 진입). 화면에는 필수만, 부수는 접힘 안에 표·키값으로.

import { readFileSync, writeFileSync, mkdirSync, readdirSync, rmSync, existsSync } from 'node:fs';
import { execSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const OUT = path.join(ROOT, '_site');
const TPL = path.join(ROOT, 'site', 'templates');

const warnings = [];
const warn = (m) => { warnings.push(m); console.warn('WARN  ' + m); };
const fail = (m) => { console.error('FAIL  ' + m); process.exit(1); };
const read = (f) => readFileSync(path.join(ROOT, f), 'utf8').replace(/\r\n/g, '\n');
const esc = (s) => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const strip = (s) => String(s ?? '').replace(/\*\*/g, '').replace(/`/g, '').trim();
const cut = (s, n) => (s && s.length > n ? s.slice(0, n - 1) + '…' : s);

// ---------------------------------------------------------------- md 표
function splitCells(line) {
  return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((s) => s.trim());
}
function tableAt(lines, i, where) {
  const rows = [];
  while (i < lines.length && lines[i].trim().startsWith('|')) rows.push(lines[i++]);
  if (rows.length < 3) return null;
  const header = splitCells(rows[0]);
  const body = [];
  for (const r of rows.slice(2)) {
    const c = splitCells(r);
    if (c.length !== header.length) { warn(`${where}: 표 열 수 불일치(헤더 ${header.length}, 행 ${c.length}): ${r.slice(0, 40)}`); continue; }
    body.push(Object.fromEntries(header.map((h, k) => [h, c[k]])));
  }
  return { header, rows: body };
}
function tableAfter(lines, re, where) {
  const h = lines.findIndex((l) => re.test(l));
  if (h < 0) return null;
  for (let i = h + 1; i < lines.length; i++) {
    if (lines[i].trim().startsWith('|')) return tableAt(lines, i, where);
    if (/^#{1,3} /.test(lines[i])) return null;
  }
  return null;
}
function num(s) {
  const t = strip(s).replace(/억/g, '').replace(/,/g, '').replace(/−/g, '-').replace(/^\+/, '');
  return /^-?\d+(\.\d+)?$/.test(t) ? Number(t) : null;
}
// "3.50~3.80" → [3.5, 3.8], "10.00" → [10, 10], 그 밖엔 null
function rangeOf(s) {
  const t = strip(s).replace(/억/g, '').replace(/,/g, '');
  const m = t.match(/^(\d+(?:\.\d+)?)\s*~\s*(\d+(?:\.\d+)?)$/);
  if (m) return [Number(m[1]), Number(m[2])];
  const n = num(s);
  return n === null ? null : [n, n];
}
const fix2 = (n) => n.toFixed(2);
const signed = (n) => (n > 0 ? '+' : n < 0 ? '−' : '') + fix2(Math.abs(n));
// 요약표 셀을 화면용으로: 숫자면 소수 2자리, 레인지·문자열은 그대로
const fmtCell = (s, sign = false) => { const n = num(s); return n === null ? strip(s) : sign ? signed(n) : fix2(n); };
const fmtRange = ([a, b]) => (a === b ? fix2(a) : `${fix2(a)}~${fix2(b)}`);

// ---------------------------------------------------------------- 10_REGION_REGISTRY.md
const regText = read('10_REGION_REGISTRY.md');
const regLines = regText.split('\n');
const head = regText.match(/\*\*버전\*\* (v[\d.]+) \| \*\*갱신\*\* (\d{4}-\d{2}-\d{2}) \| \*\*구역 수\*\* (\d+)/);
if (!head) fail('10_REGION_REGISTRY.md 헤더(버전|갱신|구역 수)를 찾지 못했다');
const registry = { version: head[1], updated: head[2], count: Number(head[3]) };

const SUMMARY_COLS = ['#', '구역', '사업방식', '단계', '초기필요자금', '실거주매매가', '조합원분양가', '권리가액', '추가분담금', '최종투자금액', '비교시세(원안)', '비교시세(검증)', '안전마진(검증)', '토허(내국인 빌라)', '근거등급', '신뢰도'];
const summary = tableAfter(regLines, /^## 요약표/, '요약표');
if (!summary) fail('## 요약표 아래 표를 찾지 못했다');
for (const c of SUMMARY_COLS) if (!summary.header.includes(c)) fail(`요약표에 '${c}' 열이 없다. 현재 열: ${summary.header.join(' | ')}`);

const oq = tableAfter(regLines, /^## OPEN QUESTIONS/, 'OPEN QUESTIONS');
if (!oq) fail('## OPEN QUESTIONS 아래 표를 찾지 못했다');
for (const c of ['#', '구역', '확인할 것', '확인처', '상태']) if (!oq.header.includes(c)) fail(`OPEN QUESTIONS 표에 '${c}' 열이 없다`);
const questions = oq.rows.map((r) => ({
  id: strip(r['#']), region: strip(r['구역']), what: strip(r['확인할 것']), where: strip(r['확인처']),
  status: strip(r['상태']), resolved: /^해소/.test(strip(r['상태'])),
}));

// 근거등급 셀 — "원안(C)" · "추정중앙(C)·권리가액 자리표시자" · "레인지(C)" · "매매가·비교시세만(A, 구역계 근사)"
function parseBasis(cell) {
  const s = strip(cell);
  if (!s || s === '—') return null;
  const m = s.match(/^(.+?)\(([ABCD])(?:[,)]|\s)/);
  const label = (m ? m[1] : s.replace(/\(.*$/, '')).trim();
  const short = /원안/.test(label) ? '원안' : /추정중앙/.test(label) ? '추정 중앙' : /레인지/.test(label) ? '레인지' : /비교시세만/.test(label) ? '실거래만' : label;
  return { raw: s, label, short, grade: m ? m[2] : null, placeholder: /자리표시자/.test(s), approx: /근사/.test(s) };
}

// ---------------------------------------------------------------- regions/*.md
function parseRegion(file) {
  const text = read(file);
  const lines = text.split('\n');
  const m = lines[0].match(/^# (\d+)\. (.+)$/);
  if (!m) fail(`${file}: 첫 줄이 '# N. 이름' 형식이 아니다: ${lines[0]}`);
  const estIdx = lines.findIndex((l) => /^## 추정/.test(l));
  const listIdx = lines.findIndex((l) => /^## 매물/.test(l));
  const secEnd = (from) => { const nx = lines.findIndex((l, k) => k > from && /^## /.test(l)); return nx < 0 ? lines.length : nx; };
  const firstSec = [estIdx, listIdx].filter((k) => k >= 0).sort((a, b) => a - b)[0];
  const bodyLines = firstSec === undefined ? lines.slice(1) : lines.slice(1, firstSec);
  const estLines = estIdx < 0 ? [] : lines.slice(estIdx, secEnd(estIdx));
  const listLines = listIdx < 0 ? [] : lines.slice(listIdx, secEnd(listIdx));
  const fields = {};
  const order = [];
  let cur = null;
  for (const l of bodyLines) {
    const b = l.match(/^- \*\*(.+?)\*\*\s*:?\s*(.*)$/);
    if (b) {
      const label = b[1];
      const key = label.split(/ — | \(/)[0].trim();
      const tail = (label.match(/ — (.+?)(?: \(|$)/) || [])[1] || '';
      cur = { label, key, tail, value: b[2], sub: '', raw: [l] };
      if (!(key in fields)) { fields[key] = cur; order.push(key); }
    } else if (cur && /^\s+- /.test(l)) {
      cur.sub += ' ' + l.trim().replace(/^- /, '');
      cur.raw.push(l);
    }
  }
  const est = estIdx < 0 ? null : { heading: lines[estIdx], table: tableAfter(estLines, /^## 추정/, `${file} 추정`), text: estLines.join('\n') };
  const list = listIdx < 0 ? null : { heading: lines[listIdx], table: tableAfter(listLines, /^## 매물/, `${file} 매물`), note: listLines.slice(1).find((l) => l.trim() && !l.trim().startsWith('|')) || '', lines: listLines };
  return { no: Number(m[1]), file, headingTitle: m[2].trim(), fields, order, est, list, md: text, bullets: bodyLines.filter((l) => /^- /.test(l)).length, bodyMd: bodyLines.join('\n').trim(), estMd: estLines.join('\n').trim(), listMd: listLines.join('\n').trim() };
}
const regionFiles = readdirSync(path.join(ROOT, 'regions')).filter((f) => /^\d{2}_.+\.md$/.test(f)).sort();
if (regionFiles.length === 0) fail('regions/ 에 NN_slug.md 파일이 없다');
const regions = regionFiles.map((f) => parseRegion('regions/' + f));
if (regions.length !== summary.rows.length) fail(`구역 수 불일치: regions/ ${regions.length}개, 요약표 ${summary.rows.length}행`);
if (regions.length !== registry.count) warn(`헤더 구역 수 ${registry.count} ≠ regions/ ${regions.length}`);

const get = (r, key) => {
  const ks = Object.keys(r.fields);
  const k = ks.find((x) => x === key) || ks.find((x) => x.startsWith(key)) || ks.find((x) => x.includes(key));
  return k ? r.fields[k] : null;
};
function district(loc) {
  if (!loc) return null;
  const gu = loc.match(/([가-힣]{1,4}구)(?=\s|$|·|,)/);
  if (gu) return { name: gu[1], seoul: true };
  const si = loc.match(/([가-힣]{1,4}시)(?=\s|$|·|,|\.)/);
  if (si) return { name: (/경기/.test(loc) ? '경기 ' : '') + si[1], seoul: false };
  return null;
}
// 위치 불릿 → 네이버 지도 검색 주소. "성북구 장위동 233-42번지 일대" → "서울 성북구 장위동 233-42"
function mapAddress(loc, seoul) {
  if (!loc) return null;
  const s = strip(loc);
  const m = s.match(/([가-힣]{1,4}구 [가-힣0-9]{1,6}동 [\d-]+)/) || s.match(/([가-힣]{1,4}구 [가-힣0-9]{1,6}동)/) || s.match(/([가-힣]{1,4}시 [가-힣0-9]{1,6}동)/);
  if (!m) return null;
  return (seoul === false ? (/경기/.test(s) ? '경기 ' : '') : '서울 ') + m[1];
}
function households(f) {
  if (!f) return null;
  const s = strip(f.value + ' ' + f.sub);
  const m = s.match(/((?:약 )?[\d,]+(?:~[\d,]+)?세대)/);
  return m ? m[1] : (/미공개/.test(s) ? '미공개' : null);
}
// 불릿 하나의 등급 — "종합 X" 우선, 없으면 가장 앞에 나오는 "(X" · "(X," · "(X " · "…, 서울시 X)" 형태
function gradeOf(f) {
  if (!f) return null;
  const s = strip(f.value + ' ' + f.sub);
  const c = s.match(/종합 ([ABCD])/);
  if (c) return c[1];
  const cands = [s.match(/\(([ABCD])(?:[,)]|\s)/), s.match(/[\s,]([ABCD])\)/)].filter(Boolean);
  if (!cands.length) return null;
  return cands.sort((a, b) => a.index - b.index)[0][1];
}
function firstSentence(s, n = 60) {
  const t = strip(s).split(/(?<=[.다])\s|\. /)[0];
  return t.length > n ? t.slice(0, n - 2) + '…' : t;
}
function parseEst(r) {
  if (!r.est) return null;
  const t = r.est.table;
  if (!t) { warn(`${r.file}: ## 추정 아래 표가 없다`); return null; }
  if (t.header.includes('시나리오')) {
    const mcol = t.header.find((h) => h.startsWith('안전마진'));
    if (!mcol) { warn(`${r.file}: 시나리오 표에 안전마진 열이 없다`); return null; }
    const rows = t.rows.map((row) => ({ name: strip(row['시나리오']), margin: strip(row[mcol]), m: num(row[mcol]), cells: Object.fromEntries(Object.entries(row).map(([k, v]) => [k, strip(v)])) }));
    const nums = rows.filter((v) => v.m !== null);
    const lo = nums.reduce((a, b) => (b.m < a.m ? b : a));
    const hi = nums.reduce((a, b) => (b.m > a.m ? b : a));
    const base = (mcol.match(/\((.+?)\)/) || [])[1] || null;   // 예: "B안 16.6"
    return { kind: 'scenario', header: t.header, rows, range: `${lo.margin} ~ ${hi.margin}`, base };
  }
  if (t.header[0] === '항목') {
    const items = t.rows.map((row) => ({ name: strip(row['항목']), value: strip(row['값']), grade: strip(row['등급']), basis: strip(row['근거']) }));
    return { kind: 'items', header: t.header, items };
  }
  warn(`${r.file}: 추정 표 형식 미인식 (${t.header.join('|')})`);
  return null;
}
function initFund(r, est) {
  const m = (r.est?.text || '').match(/초기필요자금[^\n]*?\*\*(?:갭 )?([\d.]+(?:~[\d.]+)?)억/);
  if (m) return m[1];
  if (est?.kind === 'items') {
    const it = est.items.find((i) => /초기필요자금|갭/.test(i.name));
    if (it) return it.value.replace(/억$/, '');
  }
  return null;
}
// 추정 절 "**근거 사슬**" 아래 최상위 불릿의 첫 문장
function estChain(r) {
  if (!r.estMd) return [];
  const lines = r.estMd.split('\n');
  const k = lines.findIndex((l) => /근거 사슬/.test(l));
  if (k < 0) return [];
  const out = [];
  for (let i = k + 1; i < lines.length; i++) {
    const l = lines[i];
    if (/^\*\*주의/.test(l)) break;
    if (/^- /.test(l)) out.push(firstSentence(l.replace(/^- /, ''), 90));
  }
  return out;
}
// ## 매물 절 — 참고(D). 필수 열 물건·점수·링크. 노트 문단의 첫 링크는 출처, 첫 날짜는 수집일.
const mdLinks = (s) => [...String(s ?? '').matchAll(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g)].map((m) => ({ label: m[1], url: m[2] }));
function parseListings(r) {
  if (!r.list) return null;
  const t = r.list.table;
  const note = strip(r.list.note);
  const pick = (re) => (note.match(re) || [])[1] || null;
  const meta = {
    note: note.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '$1'), noteLinks: mdLinks(note), date: (note.match(/\d{4}-\d{2}-\d{2}/) || [])[0] || null,
    total: pick(/중복 제거 (\d+)건/) || pick(/등록 (\d+)건/), pass: pick(/통과 (\d+)건/), priceRange: pick(/필터 전 구역 호가 ([\d.]+~[\d.]+)억/),
    scoring: (r.list.lines.find((l) => /^채점/.test(l.trim())) || '').trim(),
  };
  if (!t) return { ...meta, count: 0, items: [] };   // 절만 있고 표가 없으면 "수집 0건" — 노트만 보여준다
  for (const c of ['물건', '점수', '링크']) if (!t.header.includes(c)) { warn(`${r.file}: 매물 표에 '${c}' 열이 없다`); return null; }
  const items = t.rows.map((row) => ({
    rank: num(row['순위']), name: strip(row['물건']), score: num(row['점수']), price: strip(row['호가']), type: strip(row['유형']), area: strip(row['면적']), floor: strip(row['층']), approved: strip(row['사용승인']), memo: strip(row['메모']), links: mdLinks(row['링크']),
  })).filter((it) => it.name);
  for (const it of items) if (it.score === null) warn(`${r.file}: 매물 '${it.name}' 점수가 숫자가 아니다`);
  return { ...meta, count: items.length, items };
}
// 비교단지 한 줄 — 이름 · 입주연도 · 표본 수
function compareInfo(r) {
  const f = get(r, '비교단지') || get(r, '비교시세');
  if (!f) return null;
  const v = strip(f.value), s = strip(f.value + ' ' + f.sub);
  if (/^\(/.test(v)) {   // 장위15처럼 값이 주석이고 채택 단지가 하위 불릿에 있는 경우 — 채택 문장 안에서만 읽는다
    const m = s.match(/채택 비교시세[^=]*=\s*(.+?)\s+중개거래 (\d+)건/);
    if (!m) return null;
    return { name: cut(m[1].replace(/^\d{4}-\d{2}~\d{2}\s*/, '').split('(')[0].trim(), 22), year: null, n: m[2] };
  }
  // "원안 'A' → 실제는 'B'(…)" 처럼 정정 이력이 있으면 마지막 화살표 뒤가 채택 단지
  const seg = v.split('→').pop().replace(/^\s*실제는\s*/, '').replace(/['"‘’]/g, '').trim();
  const name = seg.split(/[(/]/)[0].trim();
  const year = (s.match(/(\d{4})(?:-\d{2})? (?:입주|준공)/) || [])[1] || (seg.match(/\((\d{4})/) || [])[1] || null;
  const n = (s.match(/(\d+)건 (?:중앙값|평균)/) || s.match(/중개거래 (\d+)건/) || s.match(/실거래 (\d+)건/) || [])[1] || null;
  return name ? { name: cut(name, 22), year, n } : null;
}
// 예상 입주 불릿 — "2032~2035 (레인지 C) — 근거 …". 미산출·보류면 null
function moveIn(r) {
  const f = get(r, '예상 입주');
  if (!f) return null;
  const s = strip(f.value);
  if (/미산출|보류/.test(s)) return null;
  const m = s.match(/(\d{4})(?:~(\d{4}))?/);
  if (!m) return null;
  const g = (s.match(/\((?:레인지 )?([ABCD])/) || [])[1] || null;
  return { from: m[1], to: m[2] || null, grade: g, text: m[2] ? `${m[1]}~${m[2].slice(2)}` : m[1] };
}
function stageShort(stage, unverified) {
  const seg = strip(stage).split('→').pop().trim()
    .replace(/\((\d{4}-\d{2}(?:-\d{2})?)[^)]*\)/g, ' $1').replace(/\([^)]*\)/g, '').replace(/\s+/g, ' ').replace(/\s·/g, '·').trim();
  return unverified && !/미검증/.test(seg) ? seg + ' · 미검증' : seg;
}

// 단계 → 단계 맵 행. 사업방식별로 같은 키워드가 다른 위치를 뜻한다. 행 이름은 "다음 관문", 작은 글씨는 현재 상태.
const STAGES = [
  ['신청 · 접수', '후보지 신청 전'],
  ['후보지 · 대상지 선정', '선정 대기'],
  ['구역지정 · 관리계획 고시', '지정 · 고시 진행'],
  ['조합설립인가', '조합 설립 진행'],
  ['사업시행인가', '인가 준비 · 모아타운은 관리처분 포함'],
  ['관리처분인가', '인가 대기 · 모아타운 해당 없음'],
  ['착공', '관리처분 후 · 이주 · 철거'],
  ['공사 중', '착공 후 · 입주 대기'],
];
function stageRow(method, stage) {
  const s = strip(stage);
  const moa = /모아/.test(method);
  if (/착공/.test(s)) return 7;
  if (/관리처분/.test(s)) return 6;
  if (/사업시행인가/.test(s)) return /진행|준비|목표/.test(s) ? 4 : 5;
  if (/통합심의/.test(s)) return moa ? 2 : 4;
  if (/관리계획.*고시|정비구역 지정/.test(s)) return 3;
  if (/조합설립/.test(s)) return /징구|동의|준비|추진/.test(s) ? 3 : 4;
  if (/후보지 선정|대상지 선정/.test(s)) return 2;
  if (/추진위|접수|신청/.test(s)) return 0;
  return null;
}

// OPEN QUESTIONS ↔ 구역 매칭
const norm = (s) => strip(s).replace(/\(.*?\)/g, '').replace(/\s|구역|일대/g, '');
const alt = (s) => norm(s).replace(/동(?=\d)/, '');

// ---------------------------------------------------------------- 00_PROJECT_BRIEF.md §4 → 규제 알약 + 초기 현금 산식 입력
const brief = read('00_PROJECT_BRIEF.md');
const reg4 = tableAfter(brief.split('\n'), /^## 4\. 규제 전제/, '00 §4');
if (!reg4) fail('00_PROJECT_BRIEF.md ## 4. 규제 전제 표를 찾지 못했다');
const r4 = (key, quiet) => { const row = reg4.rows.find((x) => strip(x['항목']).startsWith(key)); if (!row && !quiet) warn(`00 §4에 '${key}' 행이 없다`); return row ? strip(row['내용']) : null; };
const ltvText = r4('LTV');
const LTV = (() => { const m = ltvText && (ltvText.match(/(\d+)%\(무주택\)/) || ltvText.match(/(\d+)%/)); return m ? Number(m[1]) / 100 : null; })();
const capText = r4('주담대 절대한도');
const CAPS = (() => {   // "15억 이하 6억 · 15억 초과 25억 이하 4억 · 25억 초과 2억" → [{upto:15,cap:6},{upto:25,cap:4},{upto:∞,cap:2}]
  if (!capText) return null;
  const out = [];
  for (const part of capText.split('·')) {
    let m;
    if ((m = part.match(/초과 (\d+)억 이하 (\d+)억/))) out.push({ upto: Number(m[1]), cap: Number(m[2]) });
    else if ((m = part.match(/(\d+)억 이하 (\d+)억/))) out.push({ upto: Number(m[1]), cap: Number(m[2]) });
    else if ((m = part.match(/(\d+)억 초과 (\d+)억/))) out.push({ upto: Infinity, cap: Number(m[2]) });
  }
  return out.length ? out.sort((a, b) => a.upto - b.upto) : null;
})();
if (!CAPS) warn('00 §4 주담대 절대한도 행을 구간으로 읽지 못했다');
// 취득 부대비용 — 00 §4 '취득세·중개보수' 행이 있을 때만 초기 현금에 더한다. 산식은 그 행과 같아야 한다(무주택 유상취득, 85㎡ 이하 농특세 면제).
const feeText = r4('취득세', true);
function feeRate(p) {
  const acq = p <= 6 ? 1 : p <= 9 ? p * 2 / 3 - 3 : 3;   // 취득세 %
  const edu = acq * 0.1;                                    // 지방교육세 = 취득세율의 10%
  const broker = p < 0.5 ? 0.6 : p < 2 ? 0.5 : p < 9 ? 0.4 : p < 12 ? 0.5 : p < 15 ? 0.6 : 0.7;   // 중개보수 상한요율
  return (acq + edu + broker) / 100;
}
const loanCap = (p) => { for (const b of CAPS) if (p <= b.upto) return b.cap; return CAPS[CAPS.length - 1].cap; };
function cashFor(p) {
  if (LTV === null || !CAPS) return null;
  const loan = Math.min(p * LTV, loanCap(p));
  const fee = feeText ? p * feeRate(p) : 0;
  return { p, loan, fee, cash: p - loan + fee };
}
function cashOf(priceCell) {
  const rg = rangeOf(priceCell);
  if (!rg) return null;
  const a = cashFor(rg[0]), b = cashFor(rg[1]);
  if (!a || !b) return null;
  return { lo: a, hi: b, text: fmtRange([a.cash, b.cash]), loanText: fmtRange([a.loan, b.loan]), feeText: fmtRange([a.fee, b.fee]) };
}

// ---------------------------------------------------------------- 카드 데이터
const byNo = new Map(regions.map((r) => [r.no, r]));
const cards = summary.rows.map((row) => {
  const no = num(row['#']);
  const r = byNo.get(no);
  if (!r) fail(`요약표 ${no}번에 대응하는 regions/${String(no).padStart(2, '0')}_*.md 가 없다`);
  const nameCell = strip(row['구역']);
  const name = nameCell.replace(/\(.*?\)/g, '').trim();
  const nameNote = (nameCell.match(/\((.+?)\)/) || [])[1] || null;
  const loc = get(r, '위치');
  const d = district(loc ? loc.value : '');
  if (!d) warn(`${r.file}: 위치 불릿에서 자치구(○○구/○○시)를 찾지 못했다`);
  const method = strip(row['사업방식']);
  const stage = strip(row['단계']);
  const stageIdx = stageRow(method, stage);
  if (stageIdx === null) warn(`${r.file}: 단계 미분류 — "${stage}"`);
  const est = parseEst(r);
  const keys = [norm(nameCell), alt(nameCell)];
  const qs = questions.filter((q) => q.region.split('·').some((t) => {
    const a = norm(t), b = alt(t);
    return [a, b].some((x) => x.length >= 3 && keys.some((k) => k === x || k.startsWith(x) || x.startsWith(k)));
  }));
  const toheo = strip(row['토허(내국인 빌라)']);
  const basis = parseBasis(row['근거등급']);
  if (!basis) warn(`${r.file}: 요약표 근거등급 셀이 비어 있다`);
  const marginNum = num(row['안전마진(검증)']);
  const invest = strip(row['최종투자금액']);
  const style = d && !d.seoul ? 'out' : marginNum === null ? 'est' : 'main';
  const risk = get(r, '최대 리스크') || get(r, '리스크');
  const riskShort = risk ? (risk.tail || firstSentence(risk.value, 40)) : null;
  const riskLine = risk ? (risk.tail ? `${risk.tail} · ${firstSentence(risk.value, 70)}` : firstSentence(risk.value, 80)) : null;
  let updated = registry.updated;
  try { updated = execSync(`git log -1 --format=%cs -- "${r.file}"`, { cwd: ROOT, encoding: 'utf8' }).trim() || updated; } catch { /* git 없음 */ }
  const areaSrc = strip((get(r, '면적')?.value || '') + ' ' + (loc?.value || ''));
  const area = (areaSrc.match(/[\d,.]+\s?만?㎡/) || [])[0] || null;
  const bd = get(r, '권리산정기준일');
  const baseDate = bd ? (strip(bd.value).match(/\d{4}-\d{2}-\d{2}/) || [])[0] || null : null;
  const baseDateGrade = bd ? (strip(bd.value).match(/\(([ABCD])[,)\s]/) || [])[1] || null : null;
  const st = get(r, '단계');
  const stageDocGrade = st ? (strip(st.value + ' ' + st.sub).match(/(?:^|[\s(])([ABCD])(?= —|\)|,)/) || [])[1] || null : null;
  const contractor = get(r, '시공사') ? cut(firstSentence(get(r, '시공사').value, 30), 24) : null;
  const price = {
    buy: strip(row['실거주매매가']), unit: strip(row['조합원분양가']), rights: strip(row['권리가액']), levy: strip(row['추가분담금']), init: strip(row['초기필요자금']),
    invest, compare: strip(row['비교시세(검증)']), margin: strip(row['안전마진(검증)']), marginNum,
    compareGrade: est?.kind === 'items' ? (est.items.find((i) => /비교시세/.test(i.name))?.grade || null) : gradeOf(get(r, '비교단지') || get(r, '비교시세')),
    gapFund: initFund(r, est) || (num(row['초기필요자금']) !== null && toheo === '비대상' ? strip(row['초기필요자금']) : null),   // 갭 기준 참고 — 추정 절 실측 갭 우선, 없으면 요약표(토허 비대상일 때만 갭 의미)
    cash: cashOf(row['실거주매매가']),
  };
  return {
    no, slug: r.file.replace(/^regions\//, '').replace(/\.md$/, ''), name, nameNote, district: d ? d.name : null, seoul: d ? d.seoul : null,
    mapAddr: mapAddress(loc ? loc.value : '', d ? d.seoul : null),
    method, moa: /모아/.test(method), stage, stageShort: stageShort(stage, /미검증/.test(stage)), stageIdx, unverified: /미검증/.test(stage), style,
    households: households(get(r, '세대수')), area, baseDate, baseDateGrade, stageDocGrade, contractor, moveIn: moveIn(r), compareInfo: compareInfo(r),
    price, est, chain: estChain(r), toheo, trust: strip(row['신뢰도']), basis,
    questions: qs.map((q) => q.id), openIds: qs.filter((q) => !q.resolved).map((q) => q.id), open: qs.filter((q) => !q.resolved).length,
    riskShort, riskLine, listings: parseListings(r), bullets: r.bullets, bytes: Buffer.byteLength(r.md, 'utf8'), updated,
  };
});
for (const q of questions) {
  if (q.region === '전구역') continue;
  if (!cards.some((c) => c.questions.includes(q.id))) warn(`OPEN QUESTIONS ${q.id}의 구역 '${q.region}'이 어느 구역과도 매칭되지 않았다`);
}

const toheoCount = cards.filter((c) => c.toheo === '대상').length;
const pills = [
  (() => { const v = r4('투기과열지구'); return v && { short: '투기과열 <b>' + (/서울 전역/.test(v) ? '서울 전역' : '지정') + '</b>', detail: v }; })(),
  (() => { const v = r4('토지거래허가구역'); return v && { short: `토허 · 빌라는 <b>${toheoCount}곳만</b>`, detail: v }; })(),
  (() => { const v = ltvText; return v && { short: 'LTV <b>' + (LTV !== null ? Math.round(LTV * 100) + '%' : '규제지역') + '</b>', detail: v }; })(),
  (() => { const v = capText; return v && { short: '한도 <b>' + (CAPS ? CAPS.map((b) => b.cap).join(' · ') + '억' : '구간별') + '</b>', detail: v }; })(),
  (() => { const v = feeText; return v && { short: '취득세 <b>무주택 1~3%</b>', detail: v }; })(),
  (() => { const v = r4('조합원 지위양도'); return v && { short: '지위양도 <b>관리처분 후 ×</b>', detail: v }; })(),
].filter(Boolean);

// ---------------------------------------------------------------- HTML 조각
const badge = (g, extra) => (g ? ` <i class="grade ${g.toLowerCase()}" title="${esc(extra || '')}">${g}</i>` : '');
const nn = (c) => String(c.no).padStart(2, '0');
const gradeCls = (g) => (g === 'A' || g === 'B' ? '' : 'c');   // C·D는 색을 주지 않는다
function tagsHtml(c) {
  const to = c.toheo === '비대상' ? '<span class="tag ok">토허 비대상</span>' : c.toheo === '대상' ? '<span class="tag warn">토허 허가 · 2년 실거주</span>' : `<span class="tag">토허 ${esc(c.toheo || '미확인')}</span>`;
  const b = c.basis ? `<span class="tag">${esc(c.basis.short)}${badge(c.basis.grade, c.basis.raw)}${c.basis.placeholder ? ' · 자리표시자' : ''}</span>` : '';
  const trust = /낮음/.test(c.trust) ? `<span class="tag warn">신뢰 ${esc(c.trust)}</span>` : '';
  return to + b + trust;
}
const seoulCount = cards.filter((c) => c.seoul !== false).length;
const openUnique = new Set(questions.filter((q) => !q.resolved).map((q) => q.id)).size;
const computed = cards.filter((c) => c.price.marginNum !== null);
const appraised = computed.filter((c) => c.basis && (c.basis.grade === 'A' || c.basis.grade === 'B')).length;
const lead = `서울 ${seoulCount} · 서울 외 ${cards.length - seoulCount} · 안전마진 산출 ${computed.length}곳 (감정평가 기반 ${appraised}) · 확인 중 ${openUnique}건`;

const chip = (c) => `<a class="chip ${c.style}" href="regions/${nn(c)}.html">${esc(c.name)}${c.unverified ? ' <small>△</small>' : ''}</a>`;
const stagemap = STAGES.map(([nm, sub], i) => {
  const here = cards.filter((c) => c.stageIdx === i);
  return `<div class="vrow${here.length ? '' : ' empty'}"><div class="st">${esc(nm)}<small>${i} · ${esc(sub)}</small></div><div class="ch">${here.map(chip).join('')}</div></div>`;
}).join('') + (cards.some((c) => c.stageIdx === null) ? `<div class="vrow warn"><div class="st">단계 미분류<small>키워드 표 갱신 필요</small></div><div class="ch">${cards.filter((c) => c.stageIdx === null).map(chip).join('')}</div></div>` : '');

const pillsHtml = pills.map((p) => `<details class="pill"><summary>${p.short}</summary><p>${esc(p.detail)}</p></details>`).join('');

function numSlot(label, value, opts = {}) {
  const cls = ['num', opts.rng ? 'rng' : '', opts.na ? 'na' : ''].filter(Boolean).join(' ');
  const vcls = opts.na ? '' : opts.grade !== undefined ? (gradeCls(opts.grade) || (opts.sign > 0 ? 'plus' : opts.sign < 0 ? 'minus' : '')) : '';
  return `<div class="${cls}"><span>${label}</span><b class="${vcls}">${esc(value)}${opts.badge || ''}</b></div>`;
}
// 카드 3칸: 초기 현금(실거주) / 최종투자 / 안전마진 + 근거등급
function card(c) {
  const p = c.price;
  const cash = p.cash ? numSlot('초기 현금 <small>실거주</small>', p.cash.text, { rng: /~/.test(p.cash.text) }) : numSlot('초기 현금', '—', { na: true });
  const inv = num(p.invest) !== null ? numSlot('최종투자', fmtCell(p.invest)) : /~/.test(p.invest) ? numSlot('최종투자', p.invest, { rng: true }) : numSlot('최종투자', '—', { na: true });
  const g = c.basis ? c.basis.grade : null;
  const mg = p.marginNum !== null ? numSlot('안전마진', signed(p.marginNum), { sign: p.marginNum, grade: g, badge: badge(g, c.basis?.raw) })
    : /~/.test(p.margin) ? numSlot('안전마진', p.margin, { rng: true, grade: g, badge: badge(g, c.basis?.raw) })
      : numSlot('안전마진', '산출 불가', { na: true });
  const sub = [c.district, c.method, c.households, c.nameNote, c.moveIn ? `입주 ${c.moveIn.text}${c.moveIn.grade ? ' ' + c.moveIn.grade : ''}` : null].filter(Boolean).map(esc).join(' · ');
  return `<a class="card ${c.style}" href="regions/${nn(c)}.html">
  <div class="nm">${esc(c.name)}</div>
  <div class="sub">${sub}</div>
  <div><span class="stg${c.unverified ? ' warn' : ''}">${esc(c.stageShort)}</span></div>
  <div class="nums">${cash}${inv}${mg}</div>
  <div class="tags">${tagsHtml(c)}</div>
</a>`;
}
// 그룹은 단계 구간. 순위표가 아니다 — 같은 그룹 안에서도 번호순.
const GROUPS = [
  ['early', '정비구역 지정 전', '구역계 · 기준일 확정 전 · 소멸 리스크', (c) => c.seoul !== false && c.stageIdx !== null && c.stageIdx <= 2],
  ['mid', '지정 후 · 사업시행인가 전', '분양가 · 권리가액은 감정평가 전', (c) => c.seoul !== false && c.stageIdx !== null && c.stageIdx >= 3 && c.stageIdx <= 4],
  ['late', '관리처분 이후', '입주권 성격 · 재인가 대기', (c) => c.seoul !== false && c.stageIdx !== null && c.stageIdx >= 5],
  ['unk', '단계 미분류', '', (c) => c.seoul !== false && c.stageIdx === null],
  ['out', '서울 외', '같은 표에 안 세움', (c) => c.seoul === false],
];
const groupsHtml = GROUPS.map(([g, title, sub, pred]) => {
  const cs = cards.filter(pred);
  if (!cs.length) return '';
  return `<section class="grp"><div class="grp-h"><b>${esc(title)} · ${cs.length}</b><span>${esc(sub)}</span></div><div class="cards">${cs.map(card).join('')}</div></section>`;
}).join('');

const built = new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 10);
const fill = (tpl, map) => tpl.replace(/\{\{(\w+)\}\}/g, (_, k) => (k in map ? map[k] : (warn(`템플릿 자리표시자 미정의: ${k}`), '')));

// ---------------------------------------------------------------- 문서 뷰
const REPO = 'great-yob/seoul-redev-registry';
const mdBlock = (id, md) => `<script type="text/markdown" id="md-${id}">${md.replace(/<\/script/gi, '<\\/script')}</script>`;
const docs = [
  { id: 'brief', label: '00 · 브리프', file: '00_PROJECT_BRIEF.md' },
  { id: 'registry', label: '10 · 요약표', file: '10_REGION_REGISTRY.md' },
  { id: 'regions', label: `구역 1~${cards.length}`, sections: cards.map((c) => ({ id: 'r' + String(c.no).padStart(2, '0'), file: `regions/${c.slug}.md` })) },
  { id: 'policy', label: '20 · 정책 · 출처', file: '20_POLICY_CHECKLIST_SOURCES.md' },
  { id: 'decisions', label: 'DECISIONS', file: 'DECISIONS.md' },
];
const tabsHtml = docs.map((d) => `<button data-id="${d.id}">${esc(d.label)}</button>`).join('');
const panelsHtml = docs.map((d) => {
  const link = (f) => `<a href="https://github.com/${REPO}/blob/main/${f}" target="_blank" rel="noopener">${esc(f)}</a>`;
  if (d.sections) {
    return `<div class="doc" id="panel-${d.id}"><div class="doc-meta">${d.sections.map((s) => link(s.file)).join(' · ')}</div>${d.sections.map((s) => `<section class="content" id="${s.id}" data-md="md-${s.id}"></section>`).join('')}</div>`;
  }
  return `<div class="doc" id="panel-${d.id}"><div class="doc-meta">${link(d.file)} (GitHub에서 보기)</div><div class="content" data-md="md-${d.id}"></div></div>`;
}).join('');
const mdBlocks = docs.flatMap((d) => (d.sections ? d.sections.map((s) => mdBlock(s.id, read(s.file))) : [mdBlock(d.id, read(d.file))])).join('\n');

// ---------------------------------------------------------------- 구역 페이지
// 스테퍼는 사업방식별 축. 모아타운(빈집법)은 관리처분인가가 따로 없고 사업시행계획인가에 포함된다.
const STEPS_RE = ['후보지 · 대상지 선정', '구역지정', '조합설립인가', '사업시행인가', '관리처분인가', '착공', '입주'];
const STEPS_MOA = ['대상지 선정', '관리계획 고시', '조합설립인가', '사업시행계획인가', '착공', '입주'];
const MOA_STEP = [1, 1, 2, 3, 4, 4, 5, 6];   // stageIdx → 모아타운 스텝(1-based)

function bar(price, levy, compare, scale) {
  if ([price, levy, compare].some((v) => v === null || v === undefined)) return '';
  const invest = price + levy, margin = compare - invest;
  const sc = scale || Math.max(invest, compare);
  const w = (v) => (100 * v / sc).toFixed(1) + '%';
  return `<div class="bar"><div class="seg p" style="width:${w(price)}"></div><div class="seg l" style="width:${w(levy)}"></div>${margin >= 0 ? `<div class="seg m" style="width:${w(margin)}"></div>` : `<div class="seg neg" style="left:${w(compare)};width:${w(-margin)}"></div>`}<div class="mark" style="left:${w(compare)}"></div></div>`;
}
const LEGEND = `<div class="legend"><span><i style="background:var(--bar-price)"></i>매매가</span><span><i style="background:var(--bar-levy)"></i>분담금</span><span><i style="background:var(--bar-plus)"></i>마진 +</span><span><i style="background:var(--bar-minus)"></i>마진 −</span><span><i style="background:var(--ink)"></i>비교시세</span></div>`;
const signCls = (n) => (n === null ? 'na' : n > 0 ? 'plus' : n < 0 ? 'minus' : '');

// 돈의 흐름 — 위: 초기 현금(실거주), 아래: 최종투자·안전마진. 등급 배지는 행마다.
function moneyHtml(c) {
  const p = c.price, g = c.basis ? c.basis.grade : null, gb = badge(g, c.basis?.raw);
  const row = (label, value, opt = {}) => `<span class="${opt.ref ? 'ref' : ''}${opt.big ? ' big' : ''}">${label}</span><b class="${opt.cls || ''}${opt.big ? ' big' : ''}">${value}</b>`;
  const rows = [];
  const buyRg = rangeOf(p.buy);
  if (buyRg) {
    rows.push(row(`실거주매매가${gb}`, fmtRange(buyRg)));
    if (p.cash) {
      rows.push(row(`− 주담대 한도 <small>LTV ${Math.round(LTV * 100)}% · 최대 ${loanCap(buyRg[1])}억</small>`, p.cash.loanText));
      if (feeText) rows.push(row('+ 취득세 · 중개보수 <small>무주택</small>', p.cash.feeText));
      rows.push(row(`= 초기 현금 <small>실거주${feeText ? '' : ' · 부대비용 미포함'}</small>`, p.cash.text, { cls: 'sum' }));
    }
  } else rows.push(row('실거주매매가', '미확보', { cls: 'na' }));
  if (p.gapFund) rows.push(row('갭 기준 초기자금 <small>참고 · 전세 낀 매수</small>', esc(p.gapFund), { ref: true }));
  const investNum = num(p.invest);
  if (investNum !== null) {
    rows.push(row(`+ 추가분담금 <small>분양가 ${esc(fmtCell(p.unit))}${gb} − 권리가액 ${esc(fmtCell(p.rights))}${gb}${c.basis?.placeholder ? ' 자리표시자' : ''}</small>`, fmtCell(p.levy)));
    rows.push(row('= 최종투자', fmtCell(p.invest), { cls: 'sum' }));
  } else if (/~/.test(p.invest)) rows.push(row(`최종투자${gb}`, esc(p.invest), { cls: 'sum' }));
  else rows.push(row('최종투자', '미확보', { cls: 'na' }));
  const ci = c.compareInfo;
  const ciText = ci ? ` <small>${esc([ci.name, ci.year, ci.n ? ci.n + '건' : null].filter(Boolean).join(' · '))}</small>` : '';
  if (num(p.compare) !== null) rows.push(row(`비교시세${badge(p.compareGrade)}${ciText}`, fmtCell(p.compare)));
  else rows.push(row('비교시세', '미확보', { cls: 'na' }));
  const rng = c.est?.kind === 'scenario' ? ` <small>레인지 ${esc(c.est.range)}</small>` : '';
  if (p.marginNum !== null) rows.push(row(`안전마진${gb}${rng}`, signed(p.marginNum), { big: true, cls: gradeCls(g) || signCls(p.marginNum) }));
  else if (/~/.test(p.margin)) rows.push(row(`안전마진${gb}`, esc(p.margin), { big: true, cls: 'c' }));
  else rows.push(row('안전마진', '산출 불가', { big: true, cls: 'na' }));
  const chart = investNum !== null && num(p.compare) !== null && buyRg && buyRg[0] === buyRg[1] ? bar(buyRg[0], num(p.levy), num(p.compare)) + LEGEND : '';
  const cav = [investNum !== null ? '분양가 · 권리가액은 감정평가 전 추정치.' : '조합원분양가 · 권리가액 미확보 — 안전마진 산출 불가.', p.cash ? 'DSR 미반영 · 대출은 매매가 기준 근사.' : null, c.est?.kind === 'scenario' ? '점추정 인용 금지.' : null].filter(Boolean).join(' ');
  return `<div class="rows">${rows.join('')}</div>${chart}<div class="cav">${cav}</div>`;
}

function kvTable(r, c) {
  const rows = r.order.map((key, k) => {
    const f = r.fields[key];
    const full = strip(f.value + ' ' + f.sub);
    const short = firstSentence(f.value, 84) || cut(full, 84);
    const more = full.length > short.length + 12 || f.raw.length > 1;
    const label = f.tail ? `${esc(f.key)} <small>${esc(f.tail)}</small>` : esc(f.key);
    return `<tr><th>${label}</th><td>${esc(short)}${more ? `<details class="more"><summary>더 보기</summary><div data-md="md-f${k}"></div></details>` : ''}</td><td class="g">${badge(gradeOf(f))}</td></tr>`;
  });
  const blocks = r.order.map((key, k) => { const f = r.fields[key]; return (strip(f.value + f.sub).length > firstSentence(f.value, 84).length + 12 || f.raw.length > 1) ? mdBlock(`f${k}`, f.raw.join('\n')) : ''; }).filter(Boolean);
  return { html: `<table class="kv">${rows.join('')}</table>`, blocks };
}
function estFold(c, r) {
  const e = c.est;
  if (!e) return null;
  let table = '';
  if (e.kind === 'scenario') {
    table = `<table class="tbl"><tr>${e.header.map((h) => `<th>${esc(h)}</th>`).join('')}</tr>${e.rows.map((v) => `<tr>${e.header.map((h) => `<td>${esc(v.cells[h])}</td>`).join('')}</tr>`).join('')}</table>`;
  } else {
    table = `<table class="tbl"><tr><th>항목</th><th>값</th><th>등급</th><th>근거</th></tr>${e.items.map((it) => `<tr><td>${esc(it.name)}</td><td>${esc(it.value)}</td><td>${badge(it.grade)}</td><td>${esc(cut(it.basis, 90))}</td></tr>`).join('')}</table>`;
  }
  const chain = c.chain.length ? `<ul class="chain">${c.chain.slice(0, 5).map((s) => `<li>${esc(s)}</li>`).join('')}</ul>` : '';
  const title = (r.est.heading.match(/ — (.+)$/) || [])[1] || '';
  return { html: `${title ? `<div class="cav" style="margin:0 0 8px">${esc(title)}</div>` : ''}${table}${chain}<details class="more"><summary>근거 사슬 전체</summary><div data-md="md-est"></div></details>`, block: mdBlock('est', r.estMd) };
}
function listFold(c) {
  const ls = c.listings;
  if (!ls || !ls.count) return null;
  const link = (it, re) => { const l = it.links.find((x) => re.test(x.label) && !/모바일/.test(x.label)); return l ? `<a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.label)}</a>` : ''; };
  const rows = ls.items.map((it) => `<tr><td>${it.rank ?? ''}</td><td>${esc(it.name)}</td><td>${it.score ?? '—'}</td><td>${esc(it.price)}</td><td>${esc(it.type)}</td><td>${esc(it.area)}</td><td>${esc(it.floor)}</td><td>${esc(it.memo && it.memo !== '—' ? it.memo : '')}</td><td>${link(it, /재개발/)} ${link(it, /네이버/)}</td></tr>`).join('');
  return `<div class="wide"><table class="tbl"><tr><th>#</th><th>물건</th><th>점수</th><th>호가</th><th>유형</th><th>면적</th><th>층</th><th>메모</th><th>링크</th></tr>${rows}</table></div>${ls.scoring ? `<div class="cav">${esc(ls.scoring)}</div>` : ''}`;
}

function regionPage(c, i) {
  const r = byNo.get(c.no);
  const facts = [c.district, c.method, c.households ? `<b>${esc(c.households)}</b>` : null, c.area ? esc(c.area) : null,
    c.baseDate ? `기준일 <b>${esc(c.baseDate)}</b>${badge(c.baseDateGrade)}` : null, c.contractor ? `시공사 <b>${esc(c.contractor)}</b>` : null,
    c.moveIn ? `입주 <b>${esc(c.moveIn.text)}</b>${badge(c.moveIn.grade)}` : null, c.nameNote ? esc(c.nameNote) : null,
    c.mapAddr ? `<a class="map" href="https://map.naver.com/p/search/${encodeURIComponent(c.mapAddr)}" target="_blank" rel="noopener">지도 ↗</a>` : null]
    .filter(Boolean).map((x) => `<span>${x}</span>`).join('');
  const steps = c.moa ? STEPS_MOA : STEPS_RE;
  const now = c.stageIdx === null ? null : c.moa ? MOA_STEP[c.stageIdx] : Math.max(c.stageIdx, 1);
  const stepper = steps.map((s, k) => {
    const n = k + 1; const cls = now === null ? '' : n < now ? 'done' : n === now ? 'now' : '';
    const nowNote = c.stageShort.length > 22 && c.stageShort.includes('·') ? c.stageShort.split('·').pop().trim() : c.stageShort;   // 스테퍼 주석은 마지막 토막만
    const note = n === now ? nowNote : (c.moa && s === '사업시행계획인가' ? '통합심의 · 관리처분 포함' : '');
    return `<li class="${cls}">${esc(s)}${note ? `<small>${esc(note)}</small>` : ''}</li>`;
  }).join('');
  const p = c.price;
  const entry = [p.cash ? `초기 현금 <b>${esc(p.cash.text)}억</b>` : '초기 현금 —', p.gapFund ? `갭 기준 ${esc(p.gapFund)}억 참고` : null,
    c.toheo === '비대상' ? '토허 비대상' : c.toheo === '대상' ? '토허 허가 · 2년 실거주' : '토허 미확인'].filter(Boolean).join(' · ');
  const openQs = questions.filter((q) => c.openIds.includes(q.id));
  const qLines = openQs.slice(0, 3).map((q) => `<span><b>${esc(q.id)}</b> ${esc(cut(q.what, 38))}</span>`).join('') + (openQs.length > 3 ? `<span>외 ${openQs.length - 3}건</span>` : '');
  const judge = `<div class="jr"><span class="k">진입 <small>실거주</small></span><div>${entry}</div></div>`
    + `<div class="jr"><span class="k">최대 리스크</span><div>${esc(c.riskLine || '—')}</div></div>`
    + `<div class="jr"><span class="k">확인 필요</span><div class="ql">${qLines || '없음'}</div></div>`;
  const box = (on, label, note) => `<div><div class="box ${on ? 'on' : 'half'}">${on ? '✓' : '△'}</div>${esc(label)}<span>${esc(note)}</span></div>`;
  const checks = box(!!c.baseDate, '권리산정기준일', c.baseDate ? c.baseDate + (c.baseDateGrade ? ' ' + c.baseDateGrade : '') : '고시일 확인')
    + box(c.toheo === '비대상' || c.toheo === '대상', '토지거래허가', c.toheo === '비대상' ? '비대상' : c.toheo === '대상' ? '대상 · 허가 · 2년 실거주' : '미확인')
    + box(false, '구역계 필지 편입', '매수 필지별 확인')
    + box(c.stageDocGrade === 'A', '사업단계 문서', c.stageDocGrade ? c.stageDocGrade + '등급' : '고시문 확인');
  const ls = c.listings;
  const listingsHtml = ls ? (() => {
    const top = ls.items.slice(0, 3);
    const src = ls.noteLinks[0];
    const line = [ls.date ? `수집 ${ls.date}` : null, ls.total ? `예산 통과 ${ls.count} / ${ls.total}건` : null, ls.priceRange ? `구역 호가 ${ls.priceRange}억` : null].filter(Boolean).join(' · ');
    const head = `<div class="sec"><span>매수 후보 · 호가 <i class="grade d">D</i></span><em>${src ? `<a href="${esc(src.url)}" target="_blank" rel="noopener">${esc(src.label)}</a> · ` : ''}${top.length ? `상위 ${top.length}` : '0건'}</em></div>`;
    if (!top.length) return head + `<div class="cav">${esc(line || cut(ls.note, 120))}</div>`;
    // 링크 셀에 '모바일' 링크가 있으면 따로 그리지 않고 네이버 링크의 data-m 으로 붙인다 — 페이지 스크립트가 모바일 UA에서 href 를 바꾼다
    const linkHtml = (links) => {
      const mob = links.find((l) => /모바일/.test(l.label));
      return links.filter((l) => l !== mob).map((l) => `<a href="${esc(l.url)}"${mob && /네이버/.test(l.label) ? ` data-m="${esc(mob.url)}"` : ''} target="_blank" rel="noopener">${esc(l.label)}</a>`).join('');
    };
    // 점수 게이지 — 반원 도넛. 중심 (32,32) 반지름 26 의 위쪽 반원이고, 호 길이 π×26 을 stroke-dasharray 로 잘라 점수만큼 채운다
    const ARC = 'M6 32A26 26 0 0 1 58 32', LEN = Math.PI * 26;
    const gauge = (s) => {
      const v = s === null || s === undefined ? null : Math.max(0, Math.min(100, s));
      return `<svg class="gg" viewBox="0 0 64 38" role="img" aria-label="매력도 점수 ${v ?? '미상'} / 100">`
        + `<path class="tr" d="${ARC}"/>`
        + (v === null ? '' : `<path class="vl" d="${ARC}" stroke-dasharray="${(LEN * v / 100).toFixed(2)} ${LEN.toFixed(2)}"/>`)
        + `<text x="32" y="32">${v ?? '—'}</text></svg>`;
    };
    const li = top.map((it) => `<li><span class="rk">${it.rank ?? ''}</span><div class="nm">${esc(it.name)}<small>${esc([it.price, it.type, it.floor && it.floor !== '—' ? (/층/.test(it.floor) ? it.floor : it.floor + '층') : ''].filter(Boolean).join(' · '))}</small></div><div class="sc">${gauge(it.score)}</div><div class="lk">${linkHtml(it.links)}</div></li>`).join('');
    return head + `<ol class="ls">${li}</ol><div class="cav">${esc(line)}</div>`;
  })() : '';
  const kv = kvTable(r, c);
  const ef = estFold(c, r);
  const lf = listFold(c);
  const qs = questions.filter((q) => c.questions.includes(q.id));
  const openList = qs.filter((q) => !q.resolved);
  const folds = [
    { title: `핵심 사실 · ${r.order.length}항목`, html: kv.html },
    ef ? { title: '추정 시나리오 · 근거', html: ef.html } : null,
    lf ? { title: `매물 전체 ${ls.count}건 · 점수 근거`, html: lf } : null,
    qs.length ? { title: `확인 중인 질문 ${openList.length}${qs.length - openList.length ? ` · 해소 ${qs.length - openList.length}` : ''}`, html: openList.length ? `<ul class="qlist">${openList.map((q) => `<li><b>${esc(q.id)}</b>${esc(q.what)}<small>${esc(q.where)} · ${esc(cut(q.status, 110))}</small></li>`).join('')}</ul>` : '<div class="cav">미해결 없음</div>' } : null,
  ].filter(Boolean);
  const foldsHtml = folds.map((f) => `<details class="fold"><summary>${esc(f.title)}</summary><div class="content">${f.html}</div></details>`).join('');
  const prev = cards[i - 1], next = cards[i + 1];
  return fill(readFileSync(path.join(TPL, 'region.html'), 'utf8'), {
    ...common, NAME: esc(c.name), SUB: esc([c.district, c.method, c.households].filter(Boolean).join(' · ')), NO: String(c.no), NO2: nn(c), SLUG: c.slug, UPDATED: c.updated, STYLE: c.style,
    FACTS: facts, TAGS: tagsHtml(c), STAGE: c.stageIdx === null ? `단계 미분류 · ${esc(c.stage)}` : '', STEPPER: stepper,
    MONEY: moneyHtml(c), JUDGE: judge, LISTINGS: listingsHtml, CHECKS: checks, FOLDS: foldsHtml,
    PREV: prev ? `<a href="${nn(prev)}.html">‹ ${prev.no} ${esc(prev.name)}</a>` : '<span></span>',
    NEXT: next ? `<a href="${nn(next)}.html">${next.no} ${esc(next.name)} ›</a>` : '<span></span>',
    MD_BLOCKS: [...kv.blocks, ef ? ef.block : ''].join('\n'),
  });
}

// ---------------------------------------------------------------- 쓰기
rmSync(OUT, { recursive: true, force: true });
mkdirSync(path.join(OUT, 'regions'), { recursive: true });
const common = { VERSION: registry.version, UPDATED: registry.updated, COUNT: String(cards.length), BUILT: built, REPO, WARNINGS: warnings.length ? `경고 ${warnings.length}건 (빌드 로그)` : '' };
writeFileSync(path.join(OUT, 'index.html'), fill(readFileSync(path.join(TPL, 'index.html'), 'utf8'), { ...common, LEAD: esc(lead), STAGEMAP: stagemap, PILLS: pillsHtml, GROUPS: groupsHtml }));
writeFileSync(path.join(OUT, 'docs.html'), fill(readFileSync(path.join(TPL, 'docs.html'), 'utf8'), { ...common, TABS: tabsHtml, PANELS: panelsHtml, MD_BLOCKS: mdBlocks }));
cards.forEach((c, i) => writeFileSync(path.join(OUT, 'regions', nn(c) + '.html'), regionPage(c, i)));
writeFileSync(path.join(OUT, 'data.json'), JSON.stringify({ registry, built, warnings, rules: { ltv: LTV, caps: CAPS, fee: !!feeText }, stages: STAGES.map((s) => s[0]), pills, cards, questions }, null, 2));
if (existsSync(path.join(ROOT, 'site', 'static'))) for (const f of readdirSync(path.join(ROOT, 'site', 'static'))) writeFileSync(path.join(OUT, f), readFileSync(path.join(ROOT, 'site', 'static', f)));

console.log(`ok  ${registry.version} · ${cards.length}개 구역 · ${GROUPS.map(([, t, , pred]) => `${t} ${cards.filter(pred).length}`).filter((s) => !/ 0$/.test(s)).join(' / ')} · 미해결 ${openUnique} · 경고 ${warnings.length}`);
