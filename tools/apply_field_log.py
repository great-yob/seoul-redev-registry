"""임장 기록 이슈 → `data/field/*.jsonl` 원본 적재 + `regions/NN_*.md` 의 `## 임장 기록` 절 누적.

GitHub Actions(.github/workflows/field-log.yml)가 `field-log` 이슈가 열릴 때 실행한다. 로컬 확인도 같은 명령이다.
    python tools/apply_field_log.py --body-file 본문.txt [--issue 12] [--url URL] [--dry-run]
                                    [--summary FILE] [--comment FILE]

원칙
- 현장 관찰은 전부 **C~D등급**이다. 요약표·추정 블록의 어떤 계산에도 들어가지 않는다(`00_PROJECT_BRIEF.md` §6).
  이 스크립트는 `## 임장 기록` 절만 건드린다 — 요약표·본표·추정 절은 읽지도 않는다.
- 이슈 본문에는 **ID·체크·메모만** 실린다. 항목 문구는 여기서 `30_FIELD_CHECKLIST.md`(공통)와
  구역 파일 `## 임장` 절(특이사항)에서 ID로 복원한다. 한글은 URL 인코딩되면 글자당 9바이트라
  전문을 URL 에 실으면 이슈 프리필 한계를 넘긴다. ID 가 고정 키라서 가능한 방식이다(site/README.md 7번).
- **덮어쓰지 않는다.** 한 구역을 여러 번 간다(30 규칙 E4 평일 낮·밤, E5 비 온 다음날).
  회차 블록을 최신이 위로 쌓고, 회차는 이슈 번호로 유일해진다.
- **한 회차에 오는 것은 그때 바뀐 것뿐이다**(2026-09-17). 임장 페이지가 이미 커밋된 항목을 다시 싣지 않는다 —
  커밋된 체크·메모는 페이지가 `data/field/*.jsonl` 에서 바탕으로 깔기 때문이다. 그래서 회차 머리줄은
  `이번 회차 N항목 · 누적 체크 X / M` 으로 적는다. 회차 수만 세면 "얼마나 봤는지"를 알 수 없고,
  누적만 적으면 그 방문에서 무엇을 했는지가 사라진다.
- 원본(md)과 축적(jsonl)을 분리한다. `data/field/YYYY-MM-DD.jsonl` 은 같은 날 여러 구역·여러 회차를
  **이어붙인다**(append). `data/listings` 는 회차마다 덮어쓰지만 임장은 회차 자체가 사건이라 지우면 안 된다.
- 모르는 ID 는 버리지 않는다. 체크리스트가 개정돼 ID 가 빠졌어도 원문 그대로 남기고 경고한다.
- 조용히 틀리지 않는다: 구역 키·날짜·항목 중 하나라도 못 읽으면 exit 1 → Actions 가 이슈에 사유를 달고 열어 둔다.
- 의존성: 표준 라이브러리뿐.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

for _s in (sys.stdout, sys.stderr):   # Windows 콘솔(cp949)에서도 한글·— 출력이 죽지 않게
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
FIELD_FILE = '30_FIELD_CHECKLIST.md'
SECTION = '## 임장 기록'
MARKER = re.compile(r'<!--\s*field-log v1\s+key=([A-Za-z0-9_-]+)\s+date=(\d{4}-\d{2}-\d{2})\s*-->')
ITEM = re.compile(r'^([A-Z]{1,3}\d{1,3})\s+([x-])(?:\s+(.*))?$')
# `## 임장` 은 `## 임장 기록` 과 접두사가 같다. 기록 절이 체크 항목 표로 오인되면 안 된다.
VISIT_HEAD = re.compile(r'^## 임장(?! 기록)')


def die(msg):
    print('FAIL  ' + msg, file=sys.stderr)
    sys.exit(1)


def read(path):
    with open(path, 'rb') as f:
        return f.read().decode('utf-8')


def rel(path):
    """저장소 기준 경로. 커밋 메시지·댓글에 들어가므로 윈도우에서도 `/` 로 적는다."""
    return os.path.relpath(path, ROOT).replace('\\', '/')


# ---------------------------------------------------------------- md 표
def cells(line):
    return [c.strip() for c in line.strip().strip('|').split('|')]


def table_after(lines, start, stop=None):
    """start 다음의 첫 표를 `{ID: 확인}` 으로. 다음 `## ` 를 만나면 없는 것으로 친다."""
    out = {}
    i = start + 1
    end = stop if stop is not None else len(lines)
    while i < end and not lines[i].strip().startswith('|'):
        if lines[i].startswith('## '):
            return out
        i += 1
    if i >= end:
        return out
    head = cells(lines[i])
    try:
        ci, cw = head.index('ID'), head.index('확인')
    except ValueError:
        return out
    for row in lines[i + 2:end]:
        if not row.strip().startswith('|'):
            break
        c = cells(row)
        if len(c) == len(head) and c[ci]:
            out[c[ci]] = c[cw]
    return out


def load_common():
    """30_FIELD_CHECKLIST.md 의 `## A. 제목` 그룹별 첫 표. `## 임장 규칙` 은 체크 대상이 아니라 뺀다."""
    lines = read(os.path.join(ROOT, FIELD_FILE)).split('\n')
    groups = []
    for i, l in enumerate(lines):
        m = re.match(r'^## ([A-Z])\. (.+)$', l)
        if not m:
            continue
        nx = next((k for k in range(i + 1, len(lines)) if lines[k].startswith('## ')), len(lines))
        items = table_after(lines, i, nx)
        if items:
            groups.append((m[1], m[2].strip(), items))
    if not groups:
        die(f'{FIELD_FILE}: `## A. 제목` 그룹을 하나도 찾지 못했다')
    return groups


def region_path(key):
    d = os.path.join(ROOT, 'regions')
    for f in sorted(os.listdir(d)):
        if re.match(r'^\d{2}_' + re.escape(key) + r'\.md$', f):
            return os.path.join(d, f)
    die(f'regions/ 에 구역 키 `{key}` 에 해당하는 NN_{key}.md 가 없다')


def summary_name(no):
    """구역 이름은 `10_REGION_REGISTRY.md` 요약표의 `구역` 셀에서 읽는다 — 페이지가 쓰는 이름과 같아야 한다.
    구역 파일 첫 줄은 사업방식이 붙어 있어(`답십리동 489 모아타운`) 페이지 표기와 어긋난다."""
    lines = read(os.path.join(ROOT, '10_REGION_REGISTRY.md')).split('\n')
    i = next((k for k, l in enumerate(lines) if l.startswith('## 요약표')), None)
    if i is None:
        return None
    for row in lines[i:]:
        if not row.strip().startswith('|'):
            continue
        c = cells(row)
        if len(c) > 1 and c[0].strip() == str(no):
            return re.sub(r'\(.*?\)', '', c[1]).strip() or None
    return None


def load_region(path):
    """구역 파일의 번호·이름·`## 임장` 절 항목."""
    lines = read(path).split('\n')
    m = re.match(r'^# (\d+)\. (.+)$', lines[0])
    if not m:
        die(f'{rel(path)}: 첫 줄이 `# N. 이름` 형식이 아니다')
    no = int(m[1])
    name = summary_name(no) or re.sub(r'\s*\(.*\)$', '', m[2]).strip()
    vi = next((i for i, l in enumerate(lines) if VISIT_HEAD.match(l)), None)
    items = {} if vi is None else table_after(lines, vi)
    return no, name, items


# ---------------------------------------------------------------- 이슈 본문
def parse_body(text):
    text = text.replace('\r\n', '\n')
    m = MARKER.search(text)
    if not m:
        die('본문에서 `<!-- field-log v1 key=… date=… -->` 표시를 찾지 못했다 — 임장 페이지의 「제출」로 만든 이슈가 아니다')
    rows = []
    for line in text.split('\n'):
        line = line.strip()
        if line.startswith('<!--') or line.startswith('---'):
            continue
        it = ITEM.match(line)
        if it:
            rows.append((it[1], it[2] == 'x', (it[3] or '').strip()))
    if not rows:
        die('본문에 항목 줄(`A1 x 메모`)이 하나도 없다')
    seen = set()
    uniq = []
    for r in rows:   # 같은 ID 가 두 번 오면 뒤엣것이 이긴다(붙여넣기 사고 대비)
        if r[0] in seen:
            uniq = [x for x in uniq if x[0] != r[0]]
        seen.add(r[0])
        uniq.append(r)
    return m[1], m[2], uniq


# ---------------------------------------------------------------- 누적
def load_history(key):
    """`data/field/*.jsonl` 의 이 구역 항목 행을 회차순으로 병합 → `{ID: 체크여부}`.

    페이지(`site/build.mjs` loadFieldHistory)와 **같은 규칙**으로 읽는다 — 파일명(날짜) 오름차순,
    파일 안은 적재 순서, 같은 ID 를 다시 봤으면 나중 회차가 이긴다. 둘이 어긋나면 md 머리줄과 화면이 다른 수를 말한다.
    """
    d = os.path.join(ROOT, 'data', 'field')
    out = {}
    if not os.path.isdir(d):
        return out
    for f in sorted(x for x in os.listdir(d) if re.match(r'^\d{4}-\d{2}-\d{2}\.jsonl$', x)):
        for line in read(os.path.join(d, f)).split('\n'):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue   # 깨진 줄은 건너뛴다 — 누적 수 하나 때문에 회차 반영 전체를 막지 않는다
            if r.get('t') == 'item' and r.get('zone') == key and r.get('id'):
                out[r['id']] = bool(r.get('checked'))
    return out


def cumulative(key, rows, ids):
    """이번 회차까지의 누적 체크 수. 현재 체크리스트에 있는 ID 만 센다(개정으로 빠진 ID 는 분모를 넘는다)."""
    hist = load_history(key)
    for i, checked, _ in rows:
        hist[i] = checked
    return sum(1 for i in ids if hist.get(i))


# ---------------------------------------------------------------- md 블록
def render_block(name, date, rows, common, region_items, issue, url, warns, cum, total):
    """회차 블록 하나. 공통은 그룹 순서대로, 특이사항은 그 뒤, 모르는 ID 는 맨 끝에 원문 그대로.

    머리줄은 `이번 회차 N항목 · 누적 체크 X / M`. N 은 그 방문에서 바뀐 것이고 X 는 구역 전체 진척이다 —
    제출이 델타라서 N 만 적으면 몇 항목짜리 구역처럼 보인다. `누적 체크 X / M` 은 페이지가 읽는 형식이기도 하다.
    """
    done = sum(1 for _, c, _ in rows if c)
    src = f'[#{issue}]({url})' if issue and url else (f'#{issue}' if issue else '수동 입력')
    out = [f'**{date} · {name}** — 이번 회차 {len(rows)}항목 · 누적 체크 {cum} / {total} · {src}', '']
    by_id = {r[0]: r for r in rows}
    used = set()

    def lines_for(ids, texts):
        got = []
        for i in ids:
            if i not in by_id:
                continue
            used.add(i)
            _, checked, memo = by_id[i]
            got.append(f'- [{"x" if checked else " "}] {i} {texts[i]}' + (f' — {memo}' if memo else ''))
        return got

    for gid, gtitle, items in common:
        body = lines_for(items.keys(), items)
        if body:
            out += [f'**공통 {gid}. {gtitle}**', ''] + body + ['']
    body = lines_for(region_items.keys(), region_items)
    if body:
        out += [f'**특이사항 · {name}**', ''] + body + ['']
    rest = [r for r in rows if r[0] not in used]
    if rest:
        warns.append(f'체크리스트에 없는 ID {len(rest)}건 — 원문 그대로 남긴다: ' + ' · '.join(r[0] for r in rest))
        out += ['**미상 ID** — 체크리스트 개정으로 문구를 복원하지 못했다', '']
        out += [f'- [{"x" if c else " "}] {i}' + (f' — {m}' if m else '') for i, c, m in rest] + ['']
    out.append(f'출처: 현장 확인 ({date}) · 등급: C~D — 계산식에 넣지 않는다')
    return '\n'.join(out), done


def apply_section(path, block, dry_run):
    """`## 임장 기록` 절에 회차 블록을 **최신이 위로** 끼운다. 절이 없으면 파일 끝에 만든다.

    기록 절은 파일 **끝**에 둔다 — 절 순서가 고정돼 회차가 어디에 쌓이는지 매번 같다.
    (매물은 2026-09-22부터 `regions/listings/NN_slug.md` 로 갈라져 이 파일과 부딪히지 않는다.)
    """
    raw = read(path)
    nl = '\r\n' if '\r\n' in raw else '\n'
    lines = raw.split(nl)
    idx = next((i for i, l in enumerate(lines) if l.startswith(SECTION)), None)
    first = idx is None
    if first:
        while lines and not lines[-1].strip():
            lines.pop()
        new = lines + ['', SECTION, '', '현장 관찰·중개사 발언은 C~D등급이다. 요약표·추정 블록의 어떤 계산에도 넣지 않는다.',
                       '임장 페이지(`field.html`)의 「제출」이 이슈로 보내고 `field-log` 워크플로가 여기에 쌓는다 — 손으로 고치지 않는다.',
                       ''] + block.split('\n') + ['']
    else:
        at = idx + 1
        while at < len(lines) and not re.match(r'^\*\*\d{4}-\d{2}-\d{2} ', lines[at]) and not lines[at].startswith('## '):
            at += 1
        new = lines[:at] + block.split('\n') + [''] + lines[at:]
    text = nl.join(new)
    if not text.endswith(nl):
        text += nl
    if not dry_run:
        with open(path, 'wb') as f:
            f.write(text.encode('utf-8'))
    return first


# ---------------------------------------------------------------- 이력 (jsonl)
def write_history(key, no, name, date, rows, done, cum, total, issue, url, dry_run):
    """`data/field/YYYY-MM-DD.jsonl` — 회차 1행(visit) + 항목 N행(item). append-only.

    `checked` 는 **이 회차에서** 체크한 수, `cum` 은 이 회차까지의 누적이다. 회차 로그라서 둘 다 필요하다 —
    `checked` 만 두면 나중에 "그날 뭘 했나"를 못 읽고, `cum` 만 두면 회차가 사건이 아니라 스냅샷이 된다.
    """
    d = os.path.join(ROOT, 'data', 'field')
    path = os.path.join(d, f'{date}.jsonl')
    recs = [dict(t='visit', zone=key, no=no, title=name, date=date, issue=issue, url=url,
                 checked=done, cum=cum, total=total, reported=len(rows))]
    recs += [dict(t='item', zone=key, date=date, issue=issue, id=i, checked=bool(c), memo=m) for i, c, m in rows]
    if dry_run:
        return rel(path), len(recs)
    os.makedirs(d, exist_ok=True)
    with open(path, 'ab') as f:   # 같은 날 다른 구역·다른 회차가 이어붙는다. 덮어쓰지 않는다
        for r in recs:
            f.write((json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n').encode('utf-8'))
    return rel(path), len(recs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--body-file', required=True, help='이슈 본문 파일 (UTF-8)')
    ap.add_argument('--issue', type=int, default=0)
    ap.add_argument('--url', default='')
    ap.add_argument('--summary', help='커밋 메시지를 쓸 파일')
    ap.add_argument('--comment', help='이슈에 달 댓글을 쓸 파일')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    key, date, rows = parse_body(read(a.body_file))
    path = region_path(key)
    no, name, region_items = load_region(path)
    common = load_common()
    warns = []
    ids = [i for g in common for i in g[2]] + list(region_items)
    total = len(ids)
    cum = cumulative(key, rows, ids)   # 이번 회차를 얹은 누적 — 페이지가 세는 수와 같아야 한다
    block, done = render_block(name, date, rows, common, region_items, a.issue, a.url, warns, cum, total)
    first = apply_section(path, block, a.dry_run)
    hist, n_rec = write_history(key, no, name, date, rows, done, cum, total, a.issue, a.url, a.dry_run)

    relp = rel(path)
    print(f'ok  {name} {date} · 이번 회차 {len(rows)}항목(체크 {done}) · 누적 체크 {cum} / {total}'
          f' · {relp} {"절 신설" if first else "회차 추가"} · {hist} +{n_rec}행'
          + (f' · 경고 {len(warns)}건' if warns else ''))
    for w in warns:
        print('WARN  ' + w)

    if a.summary:
        msg = [f'auto-field: {name} 임장 기록 {date} — 이번 회차 {len(rows)}항목 · 누적 체크 {cum} / {total}', '',
               f'- 항목: {relp} `## 임장 기록` {"절 신설" if first else "회차 추가"} · {hist} +{n_rec}행',
               f'- 출처: 현장 확인 ({date}) · 이슈 {a.url or "#" + str(a.issue)}',
               '- 등급: C~D (현장 관찰 — 요약표·추정 블록 편입 금지)',
               '- 근거: 직접확인']
        msg += [f'- 경고: {w}' for w in warns]
        with open(a.summary, 'wb') as f:
            f.write(('\n'.join(msg) + '\n').encode('utf-8'))
    if a.comment:
        c = [f'기록했다 — **{name}** {date} · 이번 회차 {len(rows)}항목(체크 {done}) · 누적 체크 {cum} / {total}', '',
             f'- `{relp}` 의 `## 임장 기록` 절에 {"첫 회차를 만들었다" if first else "회차를 추가했다"}',
             f'- `{hist}` 에 {n_rec}행 적재(append-only)',
             '- 등급 C~D — 요약표·추정 블록의 계산에는 들어가지 않는다',
             '', '사진을 첨부했다면 이 이슈에 남는다. 페이지 반영은 Pages 배포 후 1~2분.']
        for w in warns:
            c += ['', '⚠️ ' + w]
        with open(a.comment, 'wb') as f:
            f.write(('\n'.join(c) + '\n').encode('utf-8'))


if __name__ == '__main__':
    main()
