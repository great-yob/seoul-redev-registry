"""브이월드 NED API 큐 프로버 — 하루 예산만큼 찌르고, 막히면 커서를 남기고 다음 날 이어받는다.

    python tools/vworld_probe.py                       # 오늘 몫(태스크 2개 · 호출 예산 내)만 실행
    python tools/vworld_probe.py --task q24-sutaek2-toheo   # 특정 태스크 강제
    python tools/vworld_probe.py --budget 40 --max-tasks 1
    python tools/vworld_probe.py --build-queue          # 큐의 parcels 를 최신 매물 스냅샷으로 채움/보강
    python tools/vworld_probe.py --status               # 큐 현황만 출력 (호출 0회)
    python tools/vworld_probe.py --report [zone]        # 축적분 집계 + 회차 간 변화 (호출 0회)

왜 큐인가
- 브이월드는 하루에 많이 찌르면 어딘가에서 막힌다. 한 세션에 다 끝내려 하면 절반쯤에서 끊기고,
  어디까지 받았는지가 사라진다. 태스크마다 `cursor` 를 남기면 다음 날 그 자리에서 이어받는다.
- 막힘은 **실패가 아니다.** 에러를 만나면 커서를 저장하고 `blocked_until` 을 다음 날로 찍고 exit 0.
  CI 를 빨갛게 만들지 않는다. 진짜 실패(키 파일 없음·큐 깨짐)만 exit 1.

인증 (2026-09-10 확인)
- `api.vworld.kr/ned/data/*` 는 **`Referer` 헤더가 없으면 `INCORRECT_KEY`** 를 준다. 쿼터가 아니라 헤더 문제다.
  값은 아무 URL 이나 먹는다(`http://localhost` 확인). `domain=` 쿼리 파라미터는 효과 없다.
  v3.2 세션이 "쿼터 소진"으로 기록한 중단이 이것으로 보인다 — 그 판단은 `DECISIONS.md` #26 에 정정해 두었다.

원본과 축적의 분리 (data/README.md 와 같은 원칙)
- 이 스크립트는 **md 를 고치지 않는다.** 응답을 `data/vworld/YYYY-MM-DD.jsonl` 에 그대로 쌓기만 한다.
  레지스트리 수치 반영은 사람이 델타 패치 승인 절차를 거쳐서 한다(`CLAUDE.md` 세션 종료 절차).
- 행은 응답 원본 필드를 유지한다. 판정(토허 몇 건인지 등)은 읽는 쪽에서 한다 — 여기서 요약해 버리면 원본이 사라진다.

의존성: requests. 키는 `.env` 의 `VWORLD_API_KEY`(또는 같은 이름의 환경변수).
"""
import argparse
import collections
import datetime as dt
import json
import os
import sys
import time

import requests

for _s in (sys.stdout, sys.stderr):   # Windows 콘솔(cp949)에서도 한글 출력이 죽지 않게
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
QUEUE = os.path.join(ROOT, 'data', 'vworld', 'queue.json')
OUTDIR = os.path.join(ROOT, 'data', 'vworld')
LISTINGS = os.path.join(ROOT, 'data', 'listings')
KST = dt.timezone(dt.timedelta(hours=9))

# 태스크 kind → NED 엔드포인트. 응답 루트 키가 엔드포인트마다 다르다.
KINDS = {
    'landuse':  ('getLandUseAttr', 'landUses'),                  # 토지이용계획 — 용도지역·지구, 토허 지정 건수·등록일
    'aptprice': ('getApartHousingPriceAttr', 'apartHousingPrices'),  # 공동주택가격
    'landprice': ('getIndvdLandPriceAttr', 'indvdLandPrices'),   # 개별공시지가
    'houseprice': ('getIndvdHousingPriceAttr', 'indvdHousingPrices'),  # 개별주택가격
}
BASE = 'https://api.vworld.kr/ned/data/'
# 행에서 떼는 키 — 레코드 상위에 이미 있어 중복이다. 나머지는 응답 원본 그대로 남긴다.
DROP = ('pnu', 'ldCode', 'ldCodeNm', 'mnnmSlno')

DEFAULT_POLICY = dict(max_tasks_per_run=2, call_budget_per_run=80, sleep_sec=0.8,
                      block_backoff_days=1, max_consecutive_errors=3)


class ProbeError(Exception):
    pass


def today():
    return dt.datetime.now(KST).date()


def load_key():
    k = os.environ.get('VWORLD_API_KEY')
    if k:
        return k.strip()
    p = os.path.join(ROOT, '.env')
    if not os.path.exists(p):
        raise ProbeError('VWORLD_API_KEY 없음 — 환경변수도 .env 도 못 찾았다')
    for ln in open(p, encoding='utf-8'):
        ln = ln.strip()
        if ln.startswith('#') or '=' not in ln:
            continue
        name, val = ln.split('=', 1)
        if name.strip() == 'VWORLD_API_KEY':
            return val.strip().strip('"').strip("'")
    raise ProbeError('.env 에 VWORLD_API_KEY 줄이 없다')


def pnu_of(dong_code, jibun):
    """지번 문자열('454', '454-16', '산12-3') → PNU 19자리."""
    j = jibun.strip().replace(' ', '')
    san = '2' if j.startswith('산') else '1'
    j = j.lstrip('산')
    bon, _, bu = j.partition('-')
    return f'{dong_code}{san}{int(bon):04d}{int(bu or 0):04d}'


# ---------------------------------------------------------------- 큐
def read_queue():
    if not os.path.exists(QUEUE):
        raise ProbeError(f'큐 파일이 없다: {QUEUE}')
    with open(QUEUE, encoding='utf-8') as f:
        q = json.load(f)
    q.setdefault('policy', {})
    for k, v in DEFAULT_POLICY.items():
        q['policy'].setdefault(k, v)
    return q


def write_queue(q):
    q['updated'] = today().isoformat()
    os.makedirs(os.path.dirname(QUEUE), exist_ok=True)
    with open(QUEUE, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(q, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.write('\n')


def latest_snapshot():
    if not os.path.isdir(LISTINGS):
        return None
    files = sorted(f for f in os.listdir(LISTINGS)
                   if f.endswith('.jsonl') and not f.endswith('.partial.jsonl'))
    return os.path.join(LISTINGS, files[-1]) if files else None


def parcels_from_listings(zone):
    """매물 스냅샷에서 구역계 폴리곤 내부(`inside: true`) 지번만 뽑는다 — 지오코딩 호출 0회."""
    path = latest_snapshot()
    if not path:
        return []
    seen = set()
    for ln in open(path, encoding='utf-8'):
        r = json.loads(ln)
        if r.get('t') != 'ask' or r.get('zone') != zone or not r.get('inside'):
            continue
        addr = (r.get('addr') or '').split()
        if len(addr) >= 2:
            seen.add(addr[-1])
    return sorted(seen, key=lambda s: [int(x) for x in s.replace('산', '').split('-') + ['0']][:2])


def build_queue(q, verbose=True):
    """`source: listings` 태스크의 parcels 를 최신 스냅샷으로 채운다.
    기존 항목의 순서는 건드리지 않고 새 지번만 뒤에 붙인다 — 커서가 가리키는 위치가 밀리면 안 된다."""
    for t in q['tasks']:
        if t.get('source') != 'listings':
            continue
        fresh = parcels_from_listings(t['zone'])
        have = t.get('parcels') or []
        added = [p for p in fresh if p not in have]
        if added or not have:
            t['parcels'] = have + added
            if verbose:
                print(f"  {t['id']}: parcels {len(have)} → {len(t['parcels'])} (+{len(added)})")
        elif verbose:
            print(f"  {t['id']}: parcels {len(have)} 변화 없음")
    return q


def due(t, d):
    """오늘 돌릴 태스크인가."""
    if t.get('status') == 'done' and t.get('cadence', 'once') == 'once':
        return False
    if t.get('blocked_until') and d.isoformat() < t['blocked_until']:
        return False
    cad = t.get('cadence', 'once')
    if cad == 'once':
        return True
    period = {'daily': 1, 'weekly': 7, 'monthly': 28}.get(cad)
    if period is None:
        return True
    if t.get('cursor', 0) > 0:      # 회차 도중에 끊긴 것은 주기와 무관하게 이어받는다
        return True
    last = t.get('last_cycle')
    return (not last) or (d - dt.date.fromisoformat(last)).days >= period


# ---------------------------------------------------------------- 호출
def make_session(key):
    s = requests.Session()
    # Referer 필수 (위 docstring). 값은 임의지만 저장소 페이지를 쓴다 — 로그에서 출처가 보이게.
    s.headers.update({'User-Agent': 'seoul-redev-registry/vworld_probe (+https://great-yob.github.io/seoul-redev-registry)',
                      'Referer': 'https://great-yob.github.io/seoul-redev-registry/'})
    # numOfRows 기본값 100 은 공시가격 계열에서 조용히 잘린다 — 한 필지가 20년치 × 호 수라 450행까지 나온다.
    # 1000 으로 올리고, 그래도 totalCount 에 못 미치면 레코드에 trunc 를 찍어 읽는 쪽이 알게 한다.
    s.params = dict(key=key, format='json', numOfRows=1000, pageNo=1)
    return s


def call(session, kind, pnu, extra=None):
    """(rows, total, err) — err 가 있으면 막힌 것으로 본다. rows 가 빈 리스트면 '데이터 없음'이고 막힘이 아니다.

    빈 응답을 '해당 사항 없음'으로 읽으면 안 된다(DECISIONS #25 한계). 그래서 err 와 [] 를 갈라 놓는다.
    extra 는 태스크의 `params`(예: 공시가격 계열의 `stdrYear`)를 그대로 실어 보낸다."""
    op, root = KINDS[kind]
    q = dict(pnu=pnu)
    q.update(extra or {})
    try:
        r = session.get(BASE + op, params=q, timeout=25)
    except requests.RequestException as e:
        return None, 0, f'network:{type(e).__name__}'
    if r.status_code != 200:
        return None, 0, f'http:{r.status_code}'
    try:
        js = r.json()
    except ValueError:
        return None, 0, 'nonjson:' + r.text[:60].replace('\n', ' ')
    body = js.get(root) or js.get('response') or {}
    code = (body.get('resultCode') or '').strip()
    if code and code not in ('00', 'NORMAL_SERVICE'):
        return None, 0, f'api:{code}'
    rows = body.get('field') or []
    if isinstance(rows, dict):
        rows = [rows]
    try:
        total = int(body.get('totalCount') or len(rows))
    except (TypeError, ValueError):
        total = len(rows)
    return [{k: v for k, v in row.items() if k not in DROP} for row in rows], total, None


# ---------------------------------------------------------------- 실행
def run(args):
    q = read_queue()
    if args.build_queue:
        print('큐 parcels 갱신:')
        build_queue(q)
        write_queue(q)
        return 0

    d = today()
    pol = q['policy']
    budget = args.budget if args.budget is not None else pol['call_budget_per_run']
    max_tasks = args.max_tasks if args.max_tasks is not None else pol['max_tasks_per_run']

    if args.report is not None:
        return report(args.report or None)

    if args.status:
        print(status_text(q, d))
        return 0

    if args.task:
        picked = [t for t in q['tasks'] if t['id'] in args.task.split(',')]
        missing = set(args.task.split(',')) - {t['id'] for t in picked}
        if missing:
            raise ProbeError(f'큐에 없는 태스크: {", ".join(sorted(missing))}')
    else:
        cand = [t for t in q['tasks'] if due(t, d)]
        cand.sort(key=lambda t: (t.get('priority', 9), t.get('last_run') or '', t['id']))
        picked = cand[:max_tasks]

    if not picked:
        print(f'오늘({d}) 돌릴 태스크 없음 — 전부 done 이거나 주기 미도래이거나 backoff 중이다')
        print(status_text(q, d))
        return 0

    key = load_key()
    session = make_session(key)
    records, lines = [], []
    calls = 0
    blocked = None

    for t in picked:
        parcels = t.get('parcels') or []
        if not parcels:
            print(f"[{t['id']}] parcels 비어 있음 — --build-queue 먼저 돌려라. 건너뜀")
            continue
        cur = t.get('cursor', 0)
        got = empty = trunc = 0
        errs = 0
        t['last_run'] = d.isoformat()
        print(f"[{t['id']}] {t['kind']} · {t['zone']} · {cur}/{len(parcels)} 부터 · 남은 예산 {budget - calls}")
        while cur < len(parcels) and calls < budget:
            jibun = parcels[cur]
            pnu = pnu_of(t['dong'], jibun)
            if args.dry_run:
                print(f'  (dry) {jibun} → {pnu}')
                cur += 1
                calls += 1
                continue
            rows, total, err = call(session, t['kind'], pnu, t.get('params'))
            calls += 1
            if err:
                errs += 1
                print(f'  ! {jibun} {err}')
                if errs >= pol['max_consecutive_errors']:
                    blocked = err
                    break
                time.sleep(pol['sleep_sec'] * 3)
                continue
            errs = 0
            rec = dict(t=t['kind'], date=d.isoformat(), q=t['q'], zone=t['zone'],
                       jibun=jibun, pnu=pnu, n=len(rows), total=total, rows=rows)
            if len(rows) < total:
                rec['trunc'] = True
                trunc += 1
                print(f'  ~ {jibun} 잘림 {len(rows)}/{total} — numOfRows 상한')
            records.append(rec)
            if rows:
                got += 1
            else:
                empty += 1
            cur += 1
            time.sleep(pol['sleep_sec'])
        t['cursor'] = cur
        run_log = dict(date=d.isoformat(), calls=got + empty, ok=got, empty=empty,
                       trunc=trunc or None, blocked=blocked or None)
        t.setdefault('runs', []).append(run_log)
        if cur >= len(parcels):
            if t.get('cadence', 'once') == 'once':
                t['status'] = 'done'
            else:
                t['status'] = 'watching'
                t['last_cycle'] = d.isoformat()
                t['cursor'] = 0
        else:
            t['status'] = 'partial'
        line = f"- {t['id']}: {got}건 수신 · {empty}건 빈응답 · 진행 {t['cursor'] or len(parcels)}/{len(parcels)}"
        if trunc:
            line += f' · **{trunc}건 잘림**'
        if blocked:
            t['blocked_until'] = (d + dt.timedelta(days=pol['block_backoff_days'])).isoformat()
            line += f" · **막힘({blocked})** → {t['blocked_until']} 이후 재시도"
        else:
            t.pop('blocked_until', None)
        lines.append(line)
        print('  ' + line[2:])
        if blocked:
            break
        if calls >= budget:
            print(f'  예산 {budget}회 소진 — 나머지는 다음 회차')
            break

    if records and not args.dry_run:
        os.makedirs(OUTDIR, exist_ok=True)
        path = os.path.join(OUTDIR, f'{d.isoformat()}.jsonl')
        with open(path, 'a', encoding='utf-8', newline='\n') as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n')
        print(f'\n{len(records)}행 → {os.path.relpath(path, ROOT)}')

    if not args.dry_run:
        write_queue(q)

    if args.summary:
        with open(args.summary, 'w', encoding='utf-8', newline='\n') as f:
            f.write(f'출처: 브이월드 NED API 회차 {d.isoformat()} ({calls}회 호출)\n\n')
            f.write('\n'.join(lines) + '\n')
            f.write('\n- 등급: A (원본 응답) · 레지스트리 반영은 사람 승인 후\n')

    print('\n' + status_text(q, d))
    return 0


# ---------------------------------------------------------------- 집계 (호출 0회)
# manageNo = 기관코드(7) + 시군구코드(5) + 고시·공고번호(8, YYYYNNNN) + 지역지구코드(6) + 일련번호(7).
# 2026-09-10 확인: 수택2 필지의 국토부 토허 manageNo 가 `20261105` 로, 레지스트리가 원문 PDF(A)로 이미
# 특정해 둔 **국토교통부공고 제2026-1105호**와 일치했다. 즉 지정 근거를 필지단위로 공고번호까지 특정할 수 있다.
# 단 `registDt` 는 지정일이 아니라 **데이터 등록일**이다 — 대조2 필지는 공고 2026-1105호가 등록일 2025-08-25 로
# 붙어 있다(재지정 시 공고번호만 갱신). 어느 지정인지는 등록일이 아니라 공고번호로 가른다(DECISIONS #25 정정).
ORG = {'1613000': '국토교통부', '6110000': '서울특별시', '3980000': '구리시',
       '1480000': '환경부', '1290000': '국방부'}
WATCH = ('토지거래계약', '정비구역', '소규모주택정비', '지구단위', '재정비', '개발행위허가제한')


def notice_of(mn):
    org, sgg, notice = mn[:7], mn[7:12], mn[12:20]
    label = ORG.get(org, f'기관{org}')
    if notice.isdigit() and notice[:4].startswith('20') and int(notice[4:]):
        return f'{label} 공고 제{notice[:4]}-{int(notice[4:])}호', sgg
    return f'{label} (공고번호 미상 {notice})', sgg


def load_all():
    out = []
    if not os.path.isdir(OUTDIR):
        return out
    for f in sorted(os.listdir(OUTDIR)):
        if not f.endswith('.jsonl'):
            continue
        for ln in open(os.path.join(OUTDIR, f), encoding='utf-8'):
            out.append(json.loads(ln))
    return out


def report(zone_filter=None):
    recs = [r for r in load_all() if r.get('t') == 'landuse']
    if zone_filter:
        recs = [r for r in recs if r['zone'] == zone_filter]
    if not recs:
        print('축적된 landuse 레코드가 없다')
        return 0
    zones = sorted({r['zone'] for r in recs})
    for z in zones:
        rs = [r for r in recs if r['zone'] == z]
        dates = sorted({r['date'] for r in rs})
        print(f"\n===== {z} · 회차 {', '.join(dates)} =====")
        snaps = {}
        for d in dates:
            cur = [r for r in rs if r['date'] == d]
            agg = {}
            for r in cur:
                for x in r['rows']:
                    if not any(k in x['prposAreaDstrcCodeNm'] for k in WATCH):
                        continue
                    label, _ = notice_of(x['manageNo'])
                    key = (x['prposAreaDstrcCodeNm'], label, x['cnflcAtNm'])
                    agg.setdefault(key, set()).add(r['jibun'])
            snaps[d] = (agg, len(cur))
        d = dates[-1]
        agg, n = snaps[d]
        print(f'  최신 회차 {d} · {n}필지 조회')
        for (nm, label, cn), js in sorted(agg.items()):
            print(f'    {nm} | {label} | {cn} | {len(js)}/{n}필지')
        toheo = {k: v for k, v in agg.items() if '토지거래계약' in k[0]}
        per = collections.Counter()
        for r in [x for x in rs if x['date'] == d]:
            per[sum(1 for y in r['rows'] if '토지거래계약' in y['prposAreaDstrcCodeNm'])] += 1
        print(f'    → 필지별 토허 건수 분포 {dict(sorted(per.items()))} · 지정 종류 {len(toheo)}')
        if len(dates) > 1:
            prev, _ = snaps[dates[-2]]
            added = {k: v for k, v in agg.items() if k not in prev}
            gone = {k: v for k, v in prev.items() if k not in agg}
            if added or gone:
                print(f'  변화 ({dates[-2]} → {d}) — 확인 필요')
                for k, v in added.items():
                    print(f'    + {k[0]} | {k[1]} | {k[2]} | {len(v)}필지')
                for k, v in gone.items():
                    print(f'    - {k[0]} | {k[1]} | {k[2]} | {len(v)}필지 (사라짐)')
            else:
                print(f'  변화 없음 ({dates[-2]} → {d})')
    return 0


def status_text(q, d):
    out = ['큐 현황 (id · kind · 진행 · 상태)']
    for t in sorted(q['tasks'], key=lambda t: (t.get('priority', 9), t['id'])):
        n = len(t.get('parcels') or [])
        mark = 'due' if due(t, d) else '-'
        bl = f" blocked_until={t['blocked_until']}" if t.get('blocked_until') else ''
        out.append(f"  [{mark:>3}] {t['id']:<28} {t['kind']:<10} {t.get('cursor', 0)}/{n:<4} "
                   f"{t.get('status', 'pending'):<8} p{t.get('priority', 9)} {t.get('cadence', 'once')}{bl}")
    return '\n'.join(out)


def main():
    ap = argparse.ArgumentParser(description='브이월드 NED API 큐 프로버')
    ap.add_argument('--budget', type=int, default=None, help='이번 실행 최대 호출 수')
    ap.add_argument('--max-tasks', type=int, default=None, help='이번 실행 최대 태스크 수')
    ap.add_argument('--task', help='태스크 id (쉼표 구분) 강제 실행')
    ap.add_argument('--build-queue', action='store_true', help='parcels 를 매물 스냅샷으로 채움')
    ap.add_argument('--status', action='store_true', help='큐 현황만 출력')
    ap.add_argument('--report', nargs='?', const='', help='축적분 집계·회차 비교 (구역 slug 로 좁힘)')
    ap.add_argument('--dry-run', action='store_true', help='PNU 만 만들고 호출하지 않음')
    ap.add_argument('--summary', help='회차 요약을 이 파일에 쓴다(커밋 메시지용)')
    args = ap.parse_args()
    try:
        return run(args)
    except ProbeError as e:
        print(f'실패: {e}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
