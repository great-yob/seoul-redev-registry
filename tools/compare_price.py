"""규칙 비교시세 — 국토부 실거래 원본 → 구역별 신축 비교시세(59·74·84㎡) 기계 산출 → `data/compare/YYYY-MM-DD.jsonl`.

    python tools/compare_price.py [--only sangdo16,jangwi15] [--today 2026-10-04] [--dry-run] [--summary FILE]

규칙은 `00_PROJECT_BRIEF.md` §3 「규칙 비교시세」가 원본이다. 여기 상수(RULE · BANDS)는 그 절과 같아야 한다.
- 대상: 구역 중심 반경 RULE['radius_km'] 이내 · 준공 RULE['max_age']년 이내 아파트 + 분양권·입주권 전매(00 §6.6 — 입주 후 등기 전은 전매로 신고된다)
- 단지: 최근 fallback_months개월 거래(해제 제외·평형·거래유형 불문)가 RULE['min_liq']건 이상인 단지만 — 세대수 API 없이 나홀로·소형 단지를 거른다.
  구역은 수천 세대 단지가 되므로 소형 단지 시세는 비교 대상이 아니다(2026-10-04 첫 실행: 자양 59㎡ 중앙이 소형 단지 7~8억대에 끌려 8.25억)
- 채택: 해제 제외 · 중개거래만 · 동일 일자·층·면적·금액 1건 · 단지·평형별 중앙 대비 ±30% 이탈 제외 · 중앙값 (00 §6 국토부 실거래 원본 채택 규칙 1~5)
- 기간: 최근 RULE['months']개월. 표본이 RULE['min_n']건 미만이면 RULE['fallback_months']개월로 한 번만 넓히고 그 사실을 남긴다. 그래도 모자라면 값 없음
- 반경은 넓히지 않는다 — 규칙이 구역마다 달라지면 「같은 방법」이 아니게 된다

원칙
- **요약표 `비교시세(검증)`을 덮어쓰지 않는다.** 검증값은 사람이 고른 단지·입지 보정(상도16 B안)을 담고 있고, 이 값은 그 선택을
  같은 규칙으로 되짚는 교차 검산이다. 둘의 차이가 크면 그것이 신호다. 레지스트리 반영은 델타 패치 승인 절차를 거친다
- 등급: 원본은 국토부 실거래(A)이나 반경·연차·평형 구간이 규칙의 선택이라 **규칙값**으로 표기한다. 59·74㎡ 값은 평형별 분담금(00 §3 평형 환산비)의
  비교 기준으로 페이지가 쓴다
- 축적은 append-only, 회차당 1파일(같은 날 재실행은 그 파일만 덮어쓴다). 형식은 `data/README.md`
- 지오코딩은 `data/compare/geocode.json`에 캐시한다. 단지 좌표는 바뀌지 않으므로 다음 회차는 새 단지만 브이월드를 찌른다
- 키: `.env` 또는 환경변수 `MOLIT_API_KEY_DECODED`(국토부) · `VWORLD_API_KEY`(지오코딩). 국토부 키가 없으면 exit 2(건너뜀),
  브이월드 키가 없으면 캐시에 없는 단지를 빼고 돌며 그 수를 요약에 남긴다
- 조용히 틀리지 않는다: 국토부 호출이 재시도 후에도 실패한 (시군구, 월)이 하나라도 있으면 스냅샷을 `.partial.jsonl`로 떨어뜨리고 exit 1
"""
import argparse
import datetime as dt
import io
import json
import math
import os
import statistics
import sys
import time
import xml.etree.ElementTree as ET

import requests

for _s in (sys.stdout, sys.stderr):   # Windows 콘솔(cp949)에서도 한글이 죽지 않게
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
KST = dt.timezone(dt.timedelta(hours=9))
OUT_DIR = os.path.join(ROOT, 'data', 'compare')
GEO_CACHE = os.path.join(OUT_DIR, 'geocode.json')
REFERER = 'https://great-yob.github.io/seoul-redev-registry/'

# 00 §3 「규칙 비교시세」와 같아야 한다
RULE = dict(radius_km=1.5, max_age=10, months=6, fallback_months=12, min_n=5, outlier=0.30, min_liq=10)
BANDS = {'59': (57.0, 62.0), '74': (72.0, 78.0), '84': (82.0, 87.0)}   # 전용㎡, 하한 이상 ~ 상한 미만

LAWD = {
    '11200': '서울특별시 성동구', '11215': '서울특별시 광진구', '11230': '서울특별시 동대문구', '11290': '서울특별시 성북구',
    '11305': '서울특별시 강북구', '11350': '서울특별시 노원구', '11380': '서울특별시 은평구', '11590': '서울특별시 동작구',
    '11620': '서울특별시 관악구', '11710': '서울특별시 송파구', '11740': '서울특별시 강동구', '41310': '경기도 구리시',
}

# 구역 중심 = 재개발닷컴 구역 폴리곤 꼭짓점 평균(2026-10-04, tools/collect_listings.py 의 did 와 같은 폴리곤).
# lawd 는 반경 안에 들어올 수 있는 시군구 — **한강 건너편은 넣지 않는다**(자양655 → 청담 1.5km 같은 생활권 밖 표본을 막는다).
# 이름·file 은 collect_listings.ZONES 와 같다. 구역이 늘면 둘 다 고친다.
ZONES = [
    dict(name='dapsimni489', file='01_dapsimni489', title='답십리동 489', lng=127.053919, lat=37.568181, lawd=['11230', '11200']),
    dict(name='jayang655', file='02_jayang655', title='자양1동 655', lng=127.082146, lat=37.532650, lawd=['11215', '11200']),
    dict(name='cheonho338', file='03_cheonho338', title='천호동 338', lng=127.121495, lat=37.543212, lawd=['11740', '11710']),
    dict(name='jangwi15', file='04_jangwi15', title='장위15', lng=127.048196, lat=37.610394, lawd=['11290', '11230', '11305', '11350']),
    dict(name='sangdo16', file='05_sangdo16', title='상도16', lng=126.944633, lat=37.496057, lawd=['11590', '11620']),
    dict(name='galhyeon510-1', file='06_galhyeon510-1', title='갈현동 510-1(갈현3)', lng=126.912226, lat=37.617248, lawd=['11380']),
    dict(name='sutaek2', file='07_sutaek2', title='수택2', lng=127.144537, lat=37.593636, lawd=['41310']),
    dict(name='daejo212', file='08_daejo212', title='대조동212(가칭)', lng=126.919896, lat=37.615047, lawd=['11380']),
    dict(name='guui2donga', file='09_guui2dong46', title='구의2동A구역(구의동 46)', lng=127.093983, lat=37.550338, lawd=['11215']),
]

EP = {   # 아파트매매는 상세(Dev) 엔드포인트 — 기본 엔드포인트는 이 키로 403(SERVICE_KEY_IS_NOT_REGISTERED)이다(2026-10-04)
    'apt': 'https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev',
    'silv': 'https://apis.data.go.kr/1613000/RTMSDataSvcSilvTrade/getRTMSDataSvcSilvTrade',
}
BACKOFF = (3, 10, 30)


def load_keys():
    env = {}
    p = os.path.join(ROOT, '.env')
    if os.path.exists(p):
        for line in io.open(p, encoding='utf-8'):
            if '=' in line and not line.lstrip().startswith('#'):
                k, v = line.strip().split('=', 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return (os.environ.get('MOLIT_API_KEY_DECODED') or env.get('MOLIT_API_KEY_DECODED'),
            os.environ.get('VWORLD_API_KEY') or env.get('VWORLD_API_KEY'))


def months_back(today, n):
    """today 가 속한 달부터 거꾸로 n개월의 YYYYMM"""
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append(f'{y}{m:02d}')
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def fetch_month(key, kind, lawd, ymd):
    """한 (엔드포인트, 시군구, 월)의 전 건. 실패하면 None — 호출 쪽이 부분 회차로 처리한다."""
    items, page = [], 1
    while True:
        r = None
        for i in range(len(BACKOFF) + 1):
            try:
                r = requests.get(EP[kind], params=dict(serviceKey=key, LAWD_CD=lawd, DEAL_YMD=ymd, numOfRows=1000, pageNo=page), timeout=40)
                if r.status_code == 200 and b'<resultCode>000</resultCode>' in r.content:
                    break
            except requests.RequestException:
                pass
            if i == len(BACKOFF):
                print(f'!! {kind} {lawd} {ymd} p{page}: ' + (f'HTTP {r.status_code} {r.text[:120]!r}' if r is not None else '네트워크 오류'), file=sys.stderr)
                return None
            time.sleep(BACKOFF[i])
        root = ET.fromstring(r.content)
        got = [{c.tag: (c.text or '').strip() for c in it} for it in root.findall('.//item')]
        items += got
        total = int(root.findtext('.//totalCount') or 0)
        if len(items) >= total or not got:
            return items
        page += 1


def geocode(addr, vkey):
    for i in range(3):
        try:
            r = requests.get('https://api.vworld.kr/req/address', params=dict(service='address', request='getcoord', version='2.0', crs='epsg:4326', address=addr, format='json', type='parcel', key=vkey),
                             headers={'Referer': REFERER}, timeout=20)
            js = r.json()['response']
            if js.get('status') == 'OK':
                p = js['result']['point']
                return [round(float(p['x']), 6), round(float(p['y']), 6)]
            if js.get('status') == 'NOT_FOUND':
                return None
        except Exception:
            pass
        time.sleep(2 * (i + 1))
    return 'ERR'   # 일시 오류 — 캐시하지 않고 이번 회차만 뺀다


def km(lng1, lat1, lng2, lat2):
    p = math.pi / 180
    a = math.sin((lat2 - lat1) * p / 2) ** 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lng2 - lng1) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(a))


def norm_deal(kind, lawd, it):
    """두 엔드포인트를 한 형식으로. 채택 판정에 쓰는 필드만 남긴다."""
    try:
        amt = int(it.get('dealAmount', '').replace(',', '')) / 1e4   # 만원 → 억
        area = float(it.get('excluUseAr') or 0)
        date = f"{int(it['dealYear']):04d}-{int(it['dealMonth']):02d}-{int(it['dealDay']):02d}"
    except (ValueError, KeyError):
        return None
    jibun = (it.get('jibun') or '').strip()
    by = it.get('buildYear', '').strip()
    return dict(src=kind, lawd=lawd, umd=it.get('umdNm', '').strip(), jibun=jibun, apt=it.get('aptNm', '').strip(),
                seq=it.get('aptSeq', '').strip() or None, by=int(by) if by.isdigit() else None,
                own=it.get('ownershipGbn', '').strip() or None, date=date, amt=round(amt, 4), area=area,
                floor=it.get('floor', '').strip(), cancel=bool((it.get('cdealType') or '').strip()),
                gbn=(it.get('dealingGbn') or '').strip())


def band_of(area):
    for b, (lo, hi) in BANDS.items():
        if lo <= area < hi:
            return b
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', help='구역 name 쉼표 구분')
    ap.add_argument('--today', help='기준일 YYYY-MM-DD (기본: 오늘 KST)')
    ap.add_argument('--dry-run', action='store_true', help='스냅샷을 쓰지 않는다(지오코딩 캐시는 쓴다)')
    ap.add_argument('--summary', help='요약을 이 파일에 저장')
    ap.add_argument('--raw-cache', help='수집 원본을 이 파일에 저장·재사용(규칙 조정용)')
    args = ap.parse_args()
    mkey, vkey = load_keys()
    if not mkey:
        print('SKIP  MOLIT_API_KEY_DECODED 없음 — 규칙 비교시세를 건너뛴다', file=sys.stderr)
        return 2
    today = dt.date.fromisoformat(args.today) if args.today else dt.datetime.now(KST).date()
    only = set(args.only.split(',')) if args.only else None
    zones = [Z for Z in ZONES if not only or Z['name'] in only]
    span = max(RULE['months'], RULE['fallback_months'])
    yms = months_back(today, span)

    # 1) 수집 — 시군구×월×엔드포인트를 한 번씩만. --raw-cache 는 규칙 조정용(개발 전용, CI 는 쓰지 않는다)
    raw, failed = [], []
    if args.raw_cache and os.path.exists(args.raw_cache):
        raw = json.load(io.open(args.raw_cache, encoding='utf-8'))
    for lawd in ([] if raw else sorted({l for Z in zones for l in Z['lawd']})):
        for ym in yms:
            for kind in EP:
                got = fetch_month(mkey, kind, lawd, ym)
                if got is None:
                    failed.append(f'{kind} {lawd} {ym}')
                    continue
                raw += [d for d in (norm_deal(kind, lawd, it) for it in got) if d]
                time.sleep(0.15)
        print(f'.. {LAWD[lawd]} 수집 누계 {len(raw)}건', file=sys.stderr)
    if args.raw_cache and not os.path.exists(args.raw_cache) and not failed:
        json.dump(raw, io.open(args.raw_cache, 'w', encoding='utf-8'), ensure_ascii=False)

    # 2) 1차 필터 — 유동성 · 해제 · 중개거래 · 연차 · 평형 구간 (00 §6 1·2번)
    liq = {}
    for d in raw:
        if not d['cancel']:
            k = (d['lawd'], d['umd'], d['apt'])
            liq[k] = liq.get(k, 0) + 1
    min_by = today.year - RULE['max_age']
    cand, thin = [], set()
    for d in raw:
        d['band'] = band_of(d['area'])
        if d['cancel'] or d['gbn'] != '중개거래' or not d['band']:
            continue
        if liq[(d['lawd'], d['umd'], d['apt'])] < RULE['min_liq']:
            thin.add((d['lawd'], d['umd'], d['apt']))
            continue
        if d['src'] == 'apt' and (d['by'] is None or d['by'] < min_by):
            continue
        cand.append(d)
    # 중복 신고 1건 처리 (00 §6 3번)
    seen, deals = set(), []
    for d in cand:
        k = (d['lawd'], d['umd'], d['jibun'], d['apt'], d['date'], d['floor'], d['area'], d['amt'])
        if k not in seen:
            seen.add(k)
            deals.append(d)

    # 3) 지오코딩 (캐시)
    cache = json.load(io.open(GEO_CACHE, encoding='utf-8')) if os.path.exists(GEO_CACHE) else {}
    miss_key, geo_err = 0, 0
    for d in deals:
        d['addr'] = f"{LAWD[d['lawd']]} {d['umd']} {d['jibun']}".strip()
        if d['addr'] not in cache:
            if not vkey:
                miss_key += 1
                continue
            g = geocode(d['addr'], vkey)
            if g == 'ERR':
                geo_err += 1
                continue
            cache[d['addr']] = g
            time.sleep(0.1)
    os.makedirs(OUT_DIR, exist_ok=True)
    with io.open(GEO_CACHE, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(dict(sorted(cache.items())), f, ensure_ascii=False, indent=0, sort_keys=True)
        f.write('\n')

    # 4) 구역별 산출
    def ymd_to_date(s):
        return dt.date.fromisoformat(s)

    def start_of(months):   # 기준월 포함 months개월의 첫날
        ym = months_back(today, months)[-1]
        return dt.date(int(ym[:4]), int(ym[4:]), 1)

    records, lines = [], []
    for Z in zones:
        near = []
        for d in deals:
            if d['lawd'] not in Z['lawd']:
                continue
            g = cache.get(d['addr'])
            if not g:
                continue
            dist = km(Z['lng'], Z['lat'], g[0], g[1])
            if dist <= RULE['radius_km']:
                near.append(dict(d, dist=round(dist, 3)))
        zl = []
        for b in BANDS:
            pool = [d for d in near if d['band'] == b]
            res = None
            for months in (RULE['months'], RULE['fallback_months']):
                st = start_of(months)
                win = [d for d in pool if ymd_to_date(d['date']) >= st]
                # 이상치 — 단지·평형별 중앙 대비 ±30% (00 §6 4번). 단지 키는 단지명+법정동(전매는 aptSeq 가 없다)
                by_cx = {}
                for d in win:
                    by_cx.setdefault((d['apt'], d['umd']), []).append(d)
                kept, drop = [], []
                for cx, ds in by_cx.items():
                    med = statistics.median(x['amt'] for x in ds)
                    for x in ds:
                        (kept if abs(x['amt'] / med - 1) <= RULE['outlier'] else drop).append(x)
                if len(kept) >= RULE['min_n'] or months == RULE['fallback_months']:
                    res = dict(months=months, start=st.isoformat(), kept=kept, drop=drop)
                    break
            kept = res['kept']
            ok = len(kept) >= RULE['min_n']
            cxs = {}
            for x in kept:
                c = cxs.setdefault((x['apt'], x['umd']), dict(apt=x['apt'], umd=x['umd'], by=x['by'], dist=x['dist'], n=0, amts=[], src=set()))
                c['n'] += 1
                c['amts'].append(x['amt'])
                c['src'].add(x['src'])
                c['dist'] = min(c['dist'], x['dist'])
            complexes = sorted(({'apt': c['apt'], 'umd': c['umd'], 'by': c['by'], 'dist': c['dist'], 'n': c['n'], 'median': round(statistics.median(c['amts']), 2), 'src': sorted(c['src'])} for c in cxs.values()), key=lambda c: (-c['n'], c['dist']))
            rec = dict(t='zone', date=today.isoformat(), zone=Z['name'], file=Z['file'], title=Z['title'], band=b,
                       median=round(statistics.median(x['amt'] for x in kept), 2) if ok else None,
                       q1=round(statistics.quantiles([x['amt'] for x in kept], n=4)[0], 2) if len(kept) >= 4 else None,
                       q3=round(statistics.quantiles([x['amt'] for x in kept], n=4)[2], 2) if len(kept) >= 4 else None,
                       n=len(kept), dropped=len(res['drop']), months=res['months'], since=res['start'], widened=res['months'] != RULE['months'],
                       complexes=complexes, rule=dict(RULE, bands={k: list(v) for k, v in BANDS.items()}), center=[Z['lng'], Z['lat']], lawd=Z['lawd'])
            records.append(rec)
            for x in kept + res['drop']:
                records.append(dict(t='deal', date=today.isoformat(), zone=Z['name'], band=b, used=x in kept, src=x['src'], apt=x['apt'], umd=x['umd'], jibun=x['jibun'],
                                    by=x['by'], own=x['own'], deal=x['date'], amt=x['amt'], area=x['area'], floor=x['floor'], dist=x['dist']))
            top = ', '.join(f"{c['apt']} {c['median']:.2f}({c['n']})" for c in complexes[:3])
            zl.append(f"{b}㎡ " + (f"{rec['median']:.2f}억 n={rec['n']}{' · ' + str(res['months']) + '개월로 확장' if rec['widened'] else ''}" if ok else f"표본 부족 n={rec['n']}") + (f" [{top}]" if top else ''))
        line = f"- {Z['title']}: " + ' / '.join(zl)
        lines.append(line)
        print(line)

    summary = '\n'.join([f"규칙 비교시세 {today.isoformat()} — {len(zones)}구역 (반경 {RULE['radius_km']}km · 준공 {RULE['max_age']}년 이내 · 최근 {RULE['months']}개월, 표본 {RULE['min_n']}건 미만이면 {RULE['fallback_months']}개월)", ''] + lines
                        + [f"- 유동성 미달(12개월 {RULE['min_liq']}건 미만) 단지 {len(thin)}곳 제외"]
                        + ([f'- 지오코딩 키 없음으로 제외 {miss_key}건'] if miss_key else []) + ([f'- 지오코딩 일시 오류로 제외 {geo_err}건'] if geo_err else [])
                        + ([f'- 국토부 호출 실패 {len(failed)}건: ' + ', '.join(failed[:8])] if failed else [])) + '\n'
    if args.summary:
        io.open(args.summary, 'w', encoding='utf-8').write(summary)
    print('\n' + summary)
    if not args.dry_run:
        partial = bool(only) or bool(failed)
        hp = os.path.join(OUT_DIR, f"{today.isoformat()}{'.partial' if partial else ''}.jsonl")
        with io.open(hp, 'w', encoding='utf-8', newline='\n') as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + '\n')
        print(f'snapshot: {hp} — {len(records)}행' + ('  ** 부분 실행 — 커밋 대상 아님 **' if partial else ''))
    if failed:
        print(f'FAIL  국토부 호출 {len(failed)}건 실패 — 부분 회차', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
