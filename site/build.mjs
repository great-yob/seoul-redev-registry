// site/build.mjs — 레지스트리 마크다운 → _site/ 정적 페이지
//
// 원본: 10_REGION_REGISTRY.md(요약표·OPEN QUESTIONS), regions/*.md(구역 상세·추정),
//       00_PROJECT_BRIEF.md(§4 규제), 20·DECISIONS(문서 뷰 원문)
// 산출: _site/index.html(메인), _site/docs.html(문서 뷰), _site/data.json(검증용)
// 의존성: Node 내장 모듈만. npm install 없음.
// 규약이 깨지면 exit 1 — CI가 실패한다. 경고는 로그와 data.json에 남긴다.
// 파서가 기대는 md 규약은 site/README.md 참조.

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

// ---------------------------------------------------------------- 10_REGION_REGISTRY.md
const regText = read('10_REGION_REGISTRY.md');
const regLines = regText.split('\n');
const head = regText.match(/\*\*버전\*\* (v[\d.]+) \| \*\*갱신\*\* (\d{4}-\d{2}-\d{2}) \| \*\*구역 수\*\* (\d+)/);
if (!head) fail('10_REGION_REGISTRY.md 헤더(버전|갱신|구역 수)를 찾지 못했다');
const registry = { version: head[1], updated: head[2], count: Number(head[3]) };

const SUMMARY_COLS = ['#', '구역', '사업방식', '단계', '초기필요자금', '실거주매매가', '조합원분양가', '권리가액', '추가분담금', '최종투자금액', '비교시세(원안)', '비교시세(검증)', '안전마진(검증)', '토허(내국인 빌라)', '신뢰도'];
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

// ---------------------------------------------------------------- regions/*.md
function parseRegion(file) {
  const text = read(file);
  const lines = text.split('\n');
  const m = lines[0].match(/^# (\d+)\. (.+)$/);
  if (!m) fail(`${file}: 첫 줄이 '# N. 이름' 형식이 아니다: ${lines[0]}`);
  const estIdx = lines.findIndex((l) => /^## 추정/.test(l));
  const bodyLines = estIdx < 0 ? lines.slice(1) : lines.slice(1, estIdx);
  const estLines = estIdx < 0 ? [] : lines.slice(estIdx);
  const fields = {};
  let cur = null;
  for (const l of bodyLines) {
    const b = l.match(/^- \*\*(.+?)\*\*\s*:?\s*(.*)$/);
    if (b) {
      const label = b[1];
      const key = label.split(/ — | \(/)[0].trim();
      const tail = (label.match(/ — (.+?)(?: \(|$)/) || [])[1] || '';
      cur = { label, key, tail, value: b[2], sub: '' };
      if (!(key in fields)) fields[key] = cur;
    } else if (cur && /^\s+- /.test(l)) {
      cur.sub += ' ' + l.trim().replace(/^- /, '');
    }
  }
  const est = estIdx < 0 ? null : { heading: lines[estIdx], table: tableAfter(estLines, /^## 추정/, `${file} 추정`), text: estLines.join('\n') };
  return { no: Number(m[1]), file, headingTitle: m[2].trim(), fields, est, md: text, bullets: bodyLines.filter((l) => /^- /.test(l)).length };
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
function households(f) {
  if (!f) return null;
  const s = strip(f.value + ' ' + f.sub);
  const m = s.match(/((?:약 )?[\d,]+(?:~[\d,]+)?세대)/);
  return m ? m[1] : (/미공개/.test(s) ? '미공개' : null);
}
function priceGrade(f) {
  if (!f) return null;
  const s = strip(f.value + ' ' + f.sub);
  const c = s.match(/종합 ([ABCD])/);
  if (c) return c[1];
  const p = s.match(/\(([ABCD])\)/);
  return p ? p[1] : null;
}
function firstSentence(s) {
  const t = strip(s).split(/(?<=[.다])\s|\. /)[0];
  return t.length > 60 ? t.slice(0, 58) + '…' : t;
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
    return { kind: 'items', items };
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
function trustTags(r, row) {
  const h = r.est?.heading || '';
  const found = [...h.matchAll(/(수치|사업단계) 신뢰도 (높음|중간|낮음)/g)];
  if (found.length) return found.map((f) => ({ text: `${f[1] === '수치' ? '수치' : '단계'} ${f[2]}`, cls: f[2] === '낮음' ? 'warn' : '' }));
  const t = strip(row['신뢰도']);
  return [{ text: '신뢰 ' + t, cls: /낮음/.test(t) ? 'warn' : '' }];
}

// 단계 → 단계 맵 행. 사업방식별로 같은 키워드가 다른 위치를 뜻한다.
const STAGES = [
  ['신청 · 접수', '후보지 신청 전'],
  ['후보지 · 대상지 선정', '선정 대기'],
  ['구역지정 · 관리계획 고시', '지정 · 고시 진행'],
  ['조합설립인가', '조합 설립 진행'],
  ['사업시행인가', '인가 준비'],
  ['관리처분인가', '인가 대기'],
  ['착공', '이주 · 철거'],
  ['입주', '착공 완료'],
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
  const invest = num(row['최종투자금액']);
  const group = d && !d.seoul ? 'out' : invest !== null ? 'main' : 'est';
  const risk = get(r, '최대 리스크');
  const riskShort = risk ? (risk.tail || firstSentence(risk.value)) : (get(r, '리스크') ? firstSentence(get(r, '리스크').value) : null);
  let updated = registry.updated;
  try { updated = execSync(`git log -1 --format=%cs -- "${r.file}"`, { cwd: ROOT, encoding: 'utf8' }).trim() || updated; } catch { /* git 없음 */ }
  return {
    no, slug: r.file.replace(/^regions\//, '').replace(/\.md$/, ''), name, nameNote, district: d ? d.name : null, seoul: d ? d.seoul : null,
    method, stage, stageIdx, unverified: /미검증/.test(stage), group,
    households: households(get(r, '세대수')),
    price: { invest: strip(row['최종투자금액']), compare: strip(row['비교시세(검증)']), margin: strip(row['안전마진(검증)']), marginNum: num(row['안전마진(검증)']), compareGrade: est?.kind === 'items' ? (est.items.find((i) => /비교시세/.test(i.name))?.grade || null) : priceGrade(get(r, '비교단지') || get(r, '비교시세')), initFund: initFund(r, est) },
    est, toheo, trust: strip(row['신뢰도']), trustTags: trustTags(r, row),
    questions: qs.map((q) => q.id), open: qs.filter((q) => !q.resolved).length,
    riskShort, bullets: r.bullets, bytes: Buffer.byteLength(r.md, 'utf8'), updated,
  };
});
for (const q of questions) {
  if (q.region === '전구역') continue;
  if (!cards.some((c) => c.questions.includes(q.id))) warn(`OPEN QUESTIONS ${q.id}의 구역 '${q.region}'이 어느 구역과도 매칭되지 않았다`);
}

// ---------------------------------------------------------------- 00_PROJECT_BRIEF.md §4
const brief = read('00_PROJECT_BRIEF.md');
const reg4 = tableAfter(brief.split('\n'), /^## 4\. 규제 전제/, '00 §4');
if (!reg4) fail('00_PROJECT_BRIEF.md ## 4. 규제 전제 표를 찾지 못했다');
const r4 = (key) => { const row = reg4.rows.find((x) => strip(x['항목']).startsWith(key)); if (!row) warn(`00 §4에 '${key}' 행이 없다`); return row ? strip(row['내용']) : null; };
const toheoCount = cards.filter((c) => c.toheo === '대상').length;
const pills = [
  (() => { const v = r4('투기과열지구'); return v && { short: '투기과열 <b>' + (/서울 전역/.test(v) ? '서울 전역' : '지정') + '</b>', detail: v }; })(),
  (() => { const v = r4('토지거래허가구역'); return v && { short: `토허 · 빌라는 <b>${toheoCount}곳만</b>`, detail: v }; })(),
  (() => { const v = r4('LTV'); const p = v && v.match(/(\d+)%/); return v && { short: 'LTV <b>' + (p ? p[1] + '%' : '규제지역') + '</b>', detail: v }; })(),
  (() => { const v = r4('주담대 절대한도'); const m = v ? [...v.matchAll(/(?:이하|초과) (\d+)억(?= ·|$)/g)].map((x) => x[1]) : []; return v && { short: '한도 <b>' + (m.length ? m.join(' · ') + '억' : '구간별') + '</b>', detail: v }; })(),
  (() => { const v = r4('조합원 지위양도'); return v && { short: '지위양도 <b>' + (/관리처분/.test(v) ? '관리처분 후 ×' : '제한') + '</b>', detail: v }; })(),
].filter(Boolean);

// ---------------------------------------------------------------- HTML 조각
const badge = (g) => (g ? ` <i class="grade ${g.toLowerCase()}">${g}</i>` : '');
const seoulCount = cards.filter((c) => c.seoul !== false).length;
const openUnique = new Set(questions.filter((q) => !q.resolved).map((q) => q.id)).size;
const kpis = [
  [cards.length, `구역 · 서울 ${seoulCount} · 외 ${cards.length - seoulCount}`],
  [cards.filter((c) => c.group === 'main').length, '안전마진 산출 가능'],
  [toheoCount, '토허 대상 · 실거주'],
  [openUnique, '미해결 질문'],
].map(([n, l]) => `<div class="kpi"><b>${n}</b><span>${esc(l)}</span></div>`).join('');

const chip = (c) => `<a class="chip ${c.group}" href="docs.html#r${String(c.no).padStart(2, '0')}">${esc(c.name)}${c.unverified ? ' <small>△</small>' : ''}</a>`;
const stagemap = STAGES.map(([nm, sub], i) => {
  const here = cards.filter((c) => c.stageIdx === i);
  return `<div class="vrow${here.length ? '' : ' empty'}"><div class="st">${esc(nm)}<small>${i} · ${esc(sub)}</small></div><div class="ch">${here.map(chip).join('')}</div></div>`;
}).join('') + (cards.some((c) => c.stageIdx === null) ? `<div class="vrow warn"><div class="st">단계 미분류<small>키워드 표 갱신 필요</small></div><div class="ch">${cards.filter((c) => c.stageIdx === null).map(chip).join('')}</div></div>` : '');

const pillsHtml = pills.map((p) => `<details class="pill"><summary>${p.short}</summary><p>${esc(p.detail)}</p></details>`).join('');

function numSlot(label, value, opts = {}) {
  const cls = ['num', opts.rng ? 'rng' : '', opts.na ? 'na' : ''].filter(Boolean).join(' ');
  const vcls = opts.sign === null || opts.sign === undefined ? '' : opts.sign > 0 ? 'plus' : opts.sign < 0 ? 'minus' : '';
  return `<div class="${cls}"><span>${label}</span><b class="${vcls}">${esc(value)}</b></div>`;
}
function card(c) {
  const p = c.price;
  let slots;
  if (c.group === 'main') {
    slots = numSlot('최종투자', p.invest) + numSlot('비교시세' + badge(p.compareGrade), p.compare) + numSlot('안전마진', p.margin, { sign: p.marginNum });
  } else if (c.group === 'est') {
    const rng = c.est?.kind === 'scenario' ? c.est.range : null;
    const cmp = num(p.compare) !== null ? p.compare : c.est?.base ? c.est.base : null;
    slots = (rng ? numSlot('마진 레인지' + (c.est.base ? ' · ' + esc(c.est.base.split(' ')[0]) : ''), rng, { rng: true }) : numSlot('안전마진', '산출 불가', { na: true }))
      + (cmp ? numSlot('비교시세' + badge(p.compareGrade), cmp, { rng: /~|안/.test(cmp) }) : numSlot('비교시세', '—', { na: true }))
      + (p.initFund ? numSlot('초기자금', p.initFund, { rng: /~/.test(p.initFund) }) : numSlot('초기자금', '—', { na: true }));
  } else {
    const v = (x) => (num(x) !== null ? x : /미확보|—/.test(x) ? '미확보' : x);
    slots = numSlot('최종투자', v(p.invest), { na: num(p.invest) === null }) + numSlot('비교시세', v(p.compare), { na: num(p.compare) === null }) + numSlot('안전마진', num(p.margin) !== null ? p.margin : '산출 불가', { na: num(p.margin) === null, sign: num(p.margin) });
  }
  const to = c.toheo === '비대상' ? '<span class="tag ok">토허 비대상</span>' : c.toheo === '대상' ? '<span class="tag bad">토허 대상 · 실거주</span>' : `<span class="tag">토허 ${esc(c.toheo || '미확인')}</span>`;
  const trust = c.trustTags.map((t) => `<span class="tag ${t.cls}">${esc(t.text)}</span>`).join('');
  const sub = [c.district, c.method, c.households, c.nameNote].filter(Boolean).map(esc).join(' · ');
  return `<a class="card ${c.group}" href="docs.html#r${String(c.no).padStart(2, '0')}">
  <div class="nm">${esc(c.name)}</div>
  <div class="sub">${sub}</div>
  <div><span class="stg${c.unverified ? ' warn' : ''}">${esc(c.stage)}</span></div>
  <div class="nums">${slots}</div>
  <div class="tags">${to}${trust}<span class="tag">미해결 ${c.open}</span></div>
</a>`;
}
const GROUPS = [
  ['main', '안전마진 산출', '분양가 · 권리가액은 감정평가 전'],
  ['est', '추정 블록', '레인지로만'],
  ['out', '서울 외', '같은 표에 안 세움'],
];
const groupsHtml = GROUPS.map(([g, title, sub]) => {
  const cs = cards.filter((c) => c.group === g);
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

// ---------------------------------------------------------------- 쓰기
rmSync(OUT, { recursive: true, force: true });
mkdirSync(OUT, { recursive: true });
const common = { VERSION: registry.version, UPDATED: registry.updated, COUNT: String(cards.length), BUILT: built, REPO, WARNINGS: warnings.length ? `경고 ${warnings.length}건 (빌드 로그)` : '' };
writeFileSync(path.join(OUT, 'index.html'), fill(readFileSync(path.join(TPL, 'index.html'), 'utf8'), { ...common, KPIS: kpis, STAGEMAP: stagemap, PILLS: pillsHtml, GROUPS: groupsHtml }));
writeFileSync(path.join(OUT, 'docs.html'), fill(readFileSync(path.join(TPL, 'docs.html'), 'utf8'), { ...common, TABS: tabsHtml, PANELS: panelsHtml, MD_BLOCKS: mdBlocks }));
writeFileSync(path.join(OUT, 'data.json'), JSON.stringify({ registry, built, warnings, stages: STAGES.map((s) => s[0]), pills, cards, questions }, null, 2));
if (existsSync(path.join(ROOT, 'site', 'static'))) for (const f of readdirSync(path.join(ROOT, 'site', 'static'))) writeFileSync(path.join(OUT, f), readFileSync(path.join(ROOT, 'site', 'static', f)));

console.log(`ok  ${registry.version} · ${cards.length}개 구역 · 카드 ${GROUPS.map(([g, t]) => `${t} ${cards.filter((c) => c.group === g).length}`).join(' / ')} · 미해결 ${openUnique} · 경고 ${warnings.length}`);
