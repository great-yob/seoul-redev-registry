"""매물 자동수집 — 재개발닷컴 구역 매물 → 러프 매력도 점수 → `regions/listings/NN_slug.md` 통째 쓰기.

GitHub Actions(.github/workflows/listings.yml)가 매주 금요일 04:00 KST에 실행한다. 로컬에서도 같은 명령으로 돈다.
    python tools/collect_listings.py [--only sangdo16,jangwi15] [--dry-run] [--out DIR] [--summary FILE]
                                     [--min-price 6.0] [--max-price 8.0]   # 하한 이상 ~ 상한 이하
                                     [--history-dir data/listings]

원칙 (DECISIONS #19)
- 호가·매물은 D등급. 점수는 구역 내 상대 순위(100점, 랭크 정규화)이며 어떤 계산에도 쓰지 않는다.
- 예산 필터: 호가 PRICE_MIN 이상 PRICE_MAX 이하만 표에 남긴다. 예외는 하나 — 하한 미만이라도 점수가 예산 통과분 최고점 이상이면 싣는다.
  점수는 필터 전 구역 전체 기준이라 예외 판정이 가능하다. 제외 건수·구역 호가 범위는 노트에 남긴다 — 조용히 빼지 않는다.
- 매물은 구역 파일과 **다른 파일**이다 — `regions/listings/NN_slug.md` 하나가 통째로 `## 매물` 절이고 이 스크립트가 덮어쓴다.
  구역 파일(`regions/NN_slug.md`)은 건드리지 않는다: 주 1회 자동 갱신이 구역 사실의 diff·갱신일을 덮지 않게 갈랐다(2026-09-22).
- 원본(md)과 축적(jsonl)을 분리한다. md 는 예산 통과분만 보여 주는 판단용 뷰이고, `data/listings/YYYY-MM-DD.jsonl` 은
  필터 전 전 구역 전체를 남기는 기계 축적본이다(append-only, 회차당 1파일). 형식은 `data/README.md`.
  `--only` 이거나 수집 실패 구역이 있으면 스냅샷이 부분이므로 `.partial.jsonl` 로 떨어뜨린다 — gitignore 되어 이력에 섞이지 않는다.
  `--dry-run` 은 md 만 건너뛴다(이력은 남긴다).
- 일시 오류(403·429·5xx·네트워크)는 요청마다 백오프 재시도하고, 그래도 목록이 실패한 구역은 전 구역 한 바퀴 뒤 쿨다운하고 한 번 더 돈다.
- 조용히 틀리지 않는다: 재시도 후에도 목록 페이지가 200이 아니거나 전 구역 수집 합계(예산 필터 전) 0건이면 exit 1 → CI 실패, 커밋 없음.
  재시도 후에도 빠진 상세 페이지 건수는 커밋 메시지 요약에 남긴다.
- 의존성: requests 뿐. .env 불필요.
"""
import argparse
import datetime as dt
import io
import json
import os
import re
import sys
import time

import requests

for _s in (sys.stdout, sys.stderr):   # Windows 콘솔(cp949)에서도 한글·— 출력이 죽지 않게
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36'
KST = dt.timezone(dt.timedelta(hours=9))
W = dict(unit=30, share=25, floor=15, date=15, entry=15)
LAND_TYPES = ('단독', '토지', '다가구')

# 예산 필터 (사용자 2026-09-08 결정, DECISIONS #19 4·5차) — 실거주 기준 초기투자금(대출 포함) 상한 8억.
# 하한은 2026-09-09 사용자 결정으로 6.0 → 5.0 (DECISIONS #19 6차) — 대조2처럼 구역 전체가 5억대 아래인 초기 구역이
# 통째로 0건이 되어 비교 자체가 불가능해졌기 때문이다.
# 호가 그대로 판정한다(취득세·중개비 별도, 빌라 약 4~5%). 양끝 포함이며, 하한 미만은 점수가 예산 통과분 최고점 이상일 때만 예외로 싣는다.
# 주 1회 자동 갱신도 이 값으로 돈다. CLI 인자로만 덮어쓴다.
PRICE_MIN, PRICE_MAX = 5.0, 8.0   # 억. PRICE_MIN 이상 ~ PRICE_MAX 이하(양끝 포함)

# 구역 설정. basedate 는 레지스트리 확정값(없으면 None → 재개발닷컴 상세의 right_basedate 를 채점에만 사용).
# anchor 는 노트에 찍는 기준 앵커 문구(레지스트리 요약). 구역 파일의 사실이 바뀌면 여기도 맞춘다.
ZONES = [
    dict(name='dapsimni489', did='2153', title='답십리동 489', file='01_dapsimni489', basedate='2023-12-07', anchor='구역 내 2026 중개거래 중앙 5.90억(단독다가구 지문 복원 3건, A) · 실거래/개별주택가격 배율 2.70(9건, A) · 개별공시지가 중앙 396만원/㎡(378필지, A)'),
    dict(name='jayang655', did='4641', title='자양1동 655', file='02_jayang655', basedate='2026-05-18', anchor='폴리곤 대조 구역 내 21건 중앙값 5.20억(2026, A) · 실거래/공시 배율 중앙 2.85(n=21, A)'),
    dict(name='cheonho338', did='1738', title='천호동 338', file='03_cheonho338', basedate='2024-05-23', anchor='폴리곤 대조 구역 내 52건 중앙값 5.00억(2026, A) · 실거래/공시 배율 중앙 2.93(n=52, A)'),
    dict(name='jangwi15', did='2327', title='장위15', file='04_jangwi15', basedate=None, anchor='233-42 실거래 10.00억(2026-06, 대지권 61.32㎡, A)'),
    dict(name='sangdo16', did='3691', title='상도16', file='05_sangdo16', basedate='2025-05-23', anchor='구역 내 실거래 중앙값 4.60억 · 대지권27㎡+ 중앙값 5.70억(A)'),
    dict(name='galhyeon510-1', did='4640', title='갈현동 510-1(갈현3)', file='06_galhyeon510-1', basedate='2026-07-01', anchor='폴리곤 대조 구역 내 78건 중앙값 2.51억(2026, A) · 실거래/공시 배율 중앙 1.92(n=69, A)'),
    dict(name='sutaek2', did='4074', title='수택2', file='07_sutaek2', basedate='2023-07-14', anchor='폴리곤 대조 구역 내 149건 중앙값 4.35억(2026, A) · 고시 권리자 분양가 35평형 6.77억·보정률 1.65·비례율 108.13%(고시 제2023-94호, A)'),
    dict(name='daejo212', did='4577', title='대조동212(가칭)', file='08_daejo212', basedate=None, anchor='폴리곤 대조 구역 내 52건 중앙값 3.23억(2026, A) · 권리산정기준일 미지정'),
    dict(name='guui2donga', did='4141', title='구의2동A구역(구의동 46)', file='09_guui2dong46', basedate='2026-01-27', anchor='폴리곤 대조 구역 내 58건 중앙값 5.70억(2026, A) · 실거래/공시 배율 중앙 3.19(n=59, A) · 토허 대상'),
]

session = requests.Session()
session.headers.update({'User-Agent': UA, 'Accept-Language': 'ko-KR,ko;q=0.9'})

# 재개발닷컴은 CloudFront 뒤 오리진이라 간헐적으로 500(오리진 30초 타임아웃)·403(WAF 일시 차단)을 낸다.
# 2026-09-18·09-25 예약 실행이 한 구역 목록 페이지의 1회 오류로 통째 실패했고, 수 분 뒤 재실행은 통과했다 → 일시 오류는 기다렸다 다시 찌른다.
TRANSIENT = {403, 408, 425, 429, 500, 502, 503, 504}
LIST_BACKOFF = (15, 45, 90)     # 초. 목록 페이지 — 실패하면 구역 전체가 빠지므로 길게 기다린다
DETAIL_BACKOFF = (5, 15)        # 초. 상세 페이지 — 건수가 많아 짧게
ZONE_RETRY_WAIT = 180           # 초. 목록 재시도까지 실패한 구역을 전 구역 한 바퀴 뒤 다시 도는 쿨다운


class CollectError(Exception):
    pass


def get(url, backoff):
    """일시 오류(TRANSIENT·네트워크)면 backoff 간격으로 재시도. 마지막 응답을 돌려주거나 마지막 예외를 올린다."""
    for i in range(len(backoff) + 1):
        try:
            r = session.get(url, timeout=40)
        except requests.RequestException as e:
            if i == len(backoff):
                raise
            why = type(e).__name__
        else:
            if r.status_code not in TRANSIENT or i == len(backoff):
                return r
            why = f'HTTP {r.status_code}'
            ra = r.headers.get('Retry-After', '')
            if ra.isdigit():
                time.sleep(min(int(ra), 120))
        print(f'   재시도 {i + 1}/{len(backoff)} ({why}, {backoff[i]}s 대기): {url}', file=sys.stderr)
        time.sleep(backoff[i])


# ---------------------------------------------------------------- 재개발닷컴 파싱 (Next.js 플라이트 JSON)
def unesc(t):
    return t.replace('\\"', '"').replace('\\\\', '\\')


def balanced_from(u, start):
    depth = 0
    for j in range(start, len(u)):
        if u[j] == '{':
            depth += 1
        elif u[j] == '}':
            depth -= 1
            if depth == 0:
                return u[start:j + 1]
    return None


def enclosing(u, anchor, pos=0):
    """anchor 문자열을 포함하는 가장 안쪽 미닫힘 객체"""
    p = u.find(anchor, pos)
    if p < 0:
        return None
    depth = 0
    i = p
    while i >= 0:
        ch = u[i]
        if ch == '}':
            depth += 1
        elif ch == '{':
            if depth == 0:
                break
            depth -= 1
        i -= 1
    return balanced_from(u, i)


def extract_asks(u):
    out = {}
    for m in re.finditer(r'"develop_id":(\d+),"develop_title"', u):
        obj = balanced_from(u, u.rfind('{', 0, m.start()))
        try:
            o = json.loads(obj)
            if 'price' in o and 'address' in o:
                out[o['id']] = o
        except Exception:
            pass
    return out


def fetch_list(did):
    asks, meta = {}, {}
    for page in range(1, 8):
        url = f'https://jaegebal.com/develops/{did}/asks' + (f'?page={page}' if page > 1 else '')
        r = get(url, LIST_BACKOFF)
        if r.status_code != 200:
            raise CollectError(f'{url} → HTTP {r.status_code}')
        u = unesc(r.text)
        if page == 1:
            m = re.search(r'"ask_count":(\d+)', u)
            meta['ask_count'] = int(m.group(1)) if m else None
            am = re.search(r'"areas":(\[\[\[\[.*?\]\]\]\])', u)
            meta['areas'] = json.loads(am.group(1)) if am else None
            sm = re.search(r'"detail_stage":"([^"]*)"', u)
            meta['stage'] = sm.group(1) if sm else None
        got = extract_asks(u)
        new = [k for k in got if k not in asks]
        asks.update(got)
        if not new or (meta.get('ask_count') and len(asks) >= meta['ask_count']):
            break
        time.sleep(0.6)
    return asks, meta


def fetch_detail(did, aid):
    """상세 JSON. 재시도 후에도 실패하면 None — 빈 상세({})와 구분해 호출 쪽이 건수를 센다."""
    try:
        r = get(f'https://jaegebal.com/develops/{did}/asks/{aid}', DETAIL_BACKOFF)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    obj = enclosing(unesc(r.text), '"agent_name"')
    try:
        return json.loads(obj) if obj else {}
    except Exception:
        return {}


# ---------------------------------------------------------------- 채점
def pip(pt, ring):
    x, y = pt
    inside = False
    for i in range(len(ring)):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % len(ring)]
        if (y1 > y) != (y2 > y):
            xin = (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1
            if x < xin:
                inside = not inside
    return inside


def rank_score(vals, w, lower_better):
    xs = [v for v in vals if v is not None]
    n = len(xs)
    if n <= 1:
        return [w if v is not None else w / 2 for v in vals]
    order = sorted(xs, reverse=not lower_better)
    return [w / 2 if v is None else w * (n - 1 - order.index(v)) / (n - 1) for v in vals]


def score_zone(Z, asks, meta, pmin, pmax):
    rings = [poly[0] for poly in (meta.get('areas') or [])]
    basedate, bsrc = Z['basedate'], '레지스트리'
    if not basedate:
        rb = [a['_detail'].get('right_basedate') for a in asks.values() if isinstance(a['_detail'].get('right_basedate'), str)]
        if rb:
            basedate, bsrc = sorted(rb)[0][:10], '재개발닷컴'
    uniq = {}
    for a in sorted(asks.values(), key=lambda x: x['id']):
        k = (a['address'], a.get('area2'), a['price'])
        if k in uniq:
            old = uniq[k]
            fl = a.get('floor') if a.get('floor') is not None else old.get('floor')
            uniq[k] = {**a, 'floor': fl, '_dups': old.get('_dups', 0) + 1}
        else:
            uniq[k] = dict(a)
    rows = []
    for a in uniq.values():
        d = a['_detail'] or {}
        ad = d.get('address') or {}
        blds = d.get('buildings') or []
        lot = ad.get('land_area')
        tot = sum((b.get('tot_area') or 0) for b in blds) or None
        typ = a.get('type_display') or '?'
        is_land = any(t in typ for t in LAND_TYPES)
        a2 = a.get('area2') or 0
        if is_land:
            share = lot
            note = f'대지 {lot:.1f}' if lot else '대지 미상'
            if tot:
                note += f' · 연면적 {tot:.1f}'
        else:
            share = (lot * a2 / tot) if (lot and tot and a2) else None
            note = (f'전용 {a2:.1f}' if a2 else '전용 미상') + (f' · 지분≈{share:.1f}' if share else ' · 지분 미상')
        unit = a['price'] / share if share else None
        floor, maxf = a.get('floor'), a.get('max_floor')
        apr = a.get('use_apr_day') or ''
        yr = int(apr[:4]) if apr[:4].isdigit() else None
        after = bool(a.get('is_after_right_basedate')) or (bool(basedate) and bool(apr) and apr[:10] > basedate)
        loc = a.get('location') or ad.get('location')
        inside = any(pip(loc, r) for r in rings) if (rings and isinstance(loc, list)) else None
        flags = []
        if not is_land:
            if floor is not None and floor <= 0:
                flags.append('반지하')
            elif floor is None:
                flags.append('층 미상')
        if after:
            flags.append('기준일 이후 — 현금청산 위험')
        elif yr and yr >= 2015:
            flags.append(f'{yr} 신축 · 지분 소형 가능성')
        if inside is False:
            flags.append('구역계 밖(폴리곤 대조)')
        if a.get('_dups'):
            flags.append(f'동일 매물 {a["_dups"] + 1}건 중복 등록')
        rows.append(dict(id=a['id'], addr=a['address'], typ=typ, price=a['price'] / 10000, share=share, share_note=note, unit=unit,
                         floor=floor, maxf=maxf, yr=yr, apr=apr[:7], after=after, inside=inside, flags=flags, loc=loc, is_land=is_land))
    lu = sorted(r['unit'] for r in rows if r['is_land'] and r['unit'])
    if len(lu) >= 3:
        med = lu[len(lu) // 2]
        for r in rows:
            if r['is_land'] and r['unit'] and r['unit'] < 0.4 * med:
                r['flags'].append(f'단가 이상치({r["unit"] / med * 100:.0f}% of 단독 중앙값) — 공유지분·오기 의심')
                r['anom'] = True
    n_dedup = len(rows)
    span = (min(r['price'] for r in rows), max(r['price'] for r in rows)) if rows else None
    # 점수는 구역 전체(중복 제거) 기준으로 매긴다 — 저가 예외를 판정하려면 예산 밖 매물에도 비교 가능한 점수가 있어야 한다
    su = rank_score([r['unit'] for r in rows], W['unit'], True)
    ss = rank_score([r['share'] for r in rows], W['share'], False)
    se = rank_score([r['price'] for r in rows], W['entry'], True)
    for i, r in enumerate(rows):
        if r['is_land']:
            f = W['floor']
        elif r['floor'] is None:
            f = W['floor'] * 0.55
        elif r['floor'] <= 0:
            f = 0
        elif r['floor'] == 1:
            f = W['floor'] * 0.6
        else:
            f = W['floor']
        if r['after']:
            d_ = 0
        elif r['yr'] and r['yr'] >= 2015:
            d_ = W['date'] / 3
        elif r['yr'] and r['yr'] >= 2005:
            d_ = W['date'] * 2 / 3
        else:
            d_ = W['date']
        pen = (0.7 if r['inside'] is False else 1.0) * (0.6 if r.get('anom') else 1.0)
        r['score'] = round((su[i] + ss[i] + f + d_ + se[i]) * pen)
    inb = [r for r in rows if pmin <= r['price'] <= pmax]          # 예산 통과 (상한 포함)
    cut = max((r['score'] for r in inb), default=None)             # 저가 예외 기준선 = 예산 내 최고점. 예산 통과 0건이면 예외도 없다
    keep = list(inb)
    for r in rows:
        if r['price'] < pmin and cut is not None and r['score'] >= cut:
            r['flags'].append(f'예산 하한 미만 — 점수 예외(예산 내 최고 {cut}점 이상)')
            r['low_exc'] = True
            keep.append(r)
    n_exc = len(keep) - len(inb)
    kept_ids = {id(r) for r in keep}
    for r in rows:
        r['in_budget'] = pmin <= r['price'] <= pmax
        r['kept'] = id(r) in kept_ids
    all_rows = rows                 # 이력용 — 필터 전 전체(중복 제거 후). md 는 keep 만 쓴다
    rows = keep
    rows.sort(key=lambda r: (-r['score'], r['price']))
    for i, r in enumerate(rows):
        r['rank'] = i + 1
    return rows, basedate, bsrc, bool(rings), dict(n_dedup=n_dedup, span=span, n_inb=len(inb), n_exc=n_exc, cut=cut, all=all_rows)


# ---------------------------------------------------------------- 링크 · md
ALPHA = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'


def b62(v):
    """네이버페이 부동산 center 인코딩 — round(v×1e7)+2e9 를 62진수로 (fin.land encodeCoordBase62)"""
    r = round(1e7 * v) + 2_000_000_000
    if r == 0:
        return '0'
    s = ''
    while r > 0:
        s = ALPHA[r % 62] + s
        r //= 62
    return s


def links(r):
    out = f'[재개발닷컴](https://jaegebal.com/asks/{r["id"]})'
    if isinstance(r['loc'], list):
        lng, lat = r['loc'][0], r['loc'][1]
        out += f' · [네이버부동산](https://new.land.naver.com/houses?ms={lat:.5f},{lng:.5f},18&a=VL:DDDGG:JWJT&e=RETAIL)'
        out += f' · [네이버 모바일](https://fin.land.naver.com/map?center={b62(lng)}-{b62(lat)}&zoom=17&realEstateTypes=C02-C03-A05-A06-A07&tradeTypes=A1)'
    return out


def render_md(Z, rows, n_registered, basedate, bsrc, has_poly, today, st, pmin, pmax):
    L = ['## 매물 (참고 · D · 본표 편입 금지 · 예산 필터)', '']
    src = f'재개발닷컴 [{Z["title"]} 매물 페이지](https://jaegebal.com/develops/{Z["did"]}/asks) 자동 수집 {today}'
    n_dedup, span = st['n_dedup'], st['span']
    band = f'호가 {pmin:.2f}억 이상 {pmax:.2f}억 이하'
    budget = f'예산 기준은 실거주 초기투자금(대출 포함) 상한 {pmax:.0f}억·이상 구간 {pmin:.0f}~{pmin + 1:.0f}억이며 호가 그대로 판정한다 — 취득세·중개비 별도(빌라 약 4~5%).'
    exc = f' 하한 미만은 **예산 내 최고점({st["cut"]}점) 이상일 때만** 예외로 싣는다 — 이번 회차 {st["n_exc"]}건.' if st['cut'] is not None else ''
    rng = f' 필터 전 구역 호가 {span[0]:.2f}~{span[1]:.2f}억.' if span else ''
    if not rows:
        if n_registered == 0:
            L.append(f'{src} — 등록 매물 0건. 호가 자료 없음. 기준 앵커: {Z["anchor"]}.')
        else:
            L.append(f'{src} — 등록 {n_registered}건, 중복 제거 {n_dedup}건, **예산 필터({band}) 통과 0건** — 표에 남길 매물이 없다.{rng} {budget} 기준 앵커: {Z["anchor"]}.')
        return '\n'.join(L) + '\n'
    bd = f'{basedate}({bsrc})' if basedate else '미확인'
    poly = '구역계 폴리곤(재개발닷컴) 대조 완료' + (' — 전 건 구역 내' if not any(r['inside'] is False for r in rows) else '') if has_poly else '구역계 폴리곤 없음 — 구역 내 여부 미대조'
    L.append(f'{src} — 등록 {n_registered}건, 중복 제거 {n_dedup}건, **예산 필터({band}) 통과 {st["n_inb"]}건 + 저가 예외 {st["n_exc"]}건 = 표 {len(rows)}건**({n_dedup - len(rows)}건 제외).{rng} **호가·매물이며 실거래가 아니다(D).** 점수는 구역 전체 {n_dedup}건 기준 상대 순위(100점, 채점 규칙 DECISIONS #19)이며 어떤 계산에도 쓰지 않는다. {budget}{exc} 기준 앵커: {Z["anchor"]}. 권리산정기준일 {bd}. {poly}. 대지지분(≈)은 필지면적 × 전용/총연면적 근사.')
    L += ['', '| 순위 | 물건 | 점수 | 호가 | 유형 | 면적 | 층 | 사용승인 | 메모 | 링크 |', '| --: | :-- | --: | --: | :-- | :-- | :-- | :-- | :-- | :-- |']
    for r in rows:
        if r['is_land']:
            fl = f'지상 {r["maxf"]}층' if r['maxf'] else '—'
        else:
            fl = f'{r["floor"]}/{r["maxf"]}' if r['floor'] is not None else f'?/{r["maxf"] or "?"}'
        memo = ' · '.join(r['flags']) or '—'
        L.append(f'| {r["rank"]} | {r["addr"]} | {r["score"]} | {r["price"]:.2f}억 | {r["typ"]} | {r["share_note"]} | {fl} | {r["apr"] or "—"} | {memo} | {links(r)} |')
    L += ['', f'채점(각 축 랭크 정규화): 지분 단가 {W["unit"]} · 지분 크기 {W["share"]} · 층/형태 {W["floor"]} · 권리산정기준일·신축 {W["date"]} · 진입 금액 {W["entry"]}. 단독·토지는 필지 전체가 지분이라 층 축 만점. 구역계 폴리곤(재개발닷컴) 밖이면 ×0.7, 단독 단가가 구역 단독 중앙값의 40% 미만이면 ×0.6(공유지분·오기 의심). 네이버 링크는 매물 좌표 지도(PC/모바일 URL 상이).']
    return '\n'.join(L) + '\n'


def write_listing_file(path, block, dry_run):
    """매물 사이드카(`regions/listings/NN_slug.md`)를 통째로 쓴다. 파일 전체가 `## 매물` 절 하나라 교체가 아니라 덮어쓰기다.

    구역 파일과 갈라 둔 이유는 갱신 주기다 — 구역 사실은 세션마다, 매물은 주 1회 자동이고 서로의 diff 를 덮는다.
    줄바꿈은 기존 파일을 따르고(없으면 저장소 관례대로 CRLF), 이전 회차의 '중복 제거 N건'을 돌려준다.
    """
    prev, nl = None, '\r\n'
    if os.path.exists(path):
        old = open(path, 'rb').read().decode('utf-8')
        nl = '\r\n' if '\r\n' in old else '\n'
        m = re.search(r'통과 (\d+)건|중복 제거 (\d+)건|등록 매물 (\d+)건', old)
        prev = int(next(g for g in m.groups() if g)) if m else None
    new = block.replace('\n', nl)
    if not new.endswith(nl):
        new += nl
    if not dry_run:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, 'wb').write(new.encode('utf-8'))
    return prev


# ---------------------------------------------------------------- 이력 (jsonl)
def r_(v, nd):
    return None if v is None else round(v, nd)


def history_records(Z, st, basedate, bsrc, has_poly, stage, n_registered, today, pmin, pmax):
    """회차 스냅샷 레코드. `t` 로 종류를 구분한다 — 구역당 zone 1행 + 필터 전 전체 ask N행.

    md 는 예산 통과분만 싣지만 이력은 필터 전 전체를 남긴다. 예산 기준이 바뀌어도 과거 회차를 다시 계산할 수 있어야 한다.
    통과 0건인 구역도 zone 행은 남는다 — '수집했으나 0건'과 '수집 실패'를 구분하기 위해서다.
    """
    span = st['span']
    out = [dict(t='zone', date=today, zone=Z['name'], title=Z['title'], did=Z['did'], stage=stage,
                registered=n_registered, dedup=st['n_dedup'], in_budget=st['n_inb'], low_exc=st['n_exc'],
                kept=st['n_inb'] + st['n_exc'], cut=st['cut'],
                price_min=r_(span[0], 4) if span else None, price_max=r_(span[1], 4) if span else None,
                budget_min=pmin, budget_max=pmax,
                basedate=basedate, basedate_src=bsrc if basedate else None, poly=has_poly)]
    for r in st['all']:
        loc = r['loc'] if isinstance(r['loc'], list) else None
        out.append(dict(t='ask', date=today, zone=Z['name'], id=r['id'], addr=r['addr'], typ=r['typ'],
                        price=r_(r['price'], 4), share=r_(r['share'], 2), unit=r_(r['unit'], 5),
                        floor=r['floor'], max_floor=r['maxf'], use_apr=r['apr'] or None, year=r['yr'],
                        after_basedate=r['after'], inside=r['inside'], land=r['is_land'],
                        score=r['score'], rank=r.get('rank'), in_budget=r['in_budget'], kept=r['kept'],
                        low_exc=bool(r.get('low_exc')), anom=bool(r.get('anom')), flags=r['flags'],
                        lng=r_(loc[0], 7) if loc else None, lat=r_(loc[1], 7) if loc else None))
    return out


def write_history(path, records):
    """회차당 1파일. 키 정렬·LF 고정 — 회차 간 diff 가 실제 변화만 보이게 한다."""
    with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + '\n')


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', help='구역 name 쉼표 구분')
    ap.add_argument('--dry-run', action='store_true', help='파일을 쓰지 않고 요약만')
    ap.add_argument('--out', help='생성한 md 블록을 이 디렉터리에 저장')
    ap.add_argument('--summary', help='커밋 메시지용 요약을 이 파일에 저장')
    ap.add_argument('--history-dir', default=os.path.join(ROOT, 'data', 'listings'), help='회차 스냅샷 jsonl 디렉터리. 기본 data/listings')
    ap.add_argument('--min-price', type=float, default=PRICE_MIN, help=f'예산 필터 하한(억, 이상). 기본 {PRICE_MIN}')
    ap.add_argument('--max-price', type=float, default=PRICE_MAX, help=f'예산 필터 상한(억, 이하). 기본 {PRICE_MAX}')
    args = ap.parse_args()
    pmin, pmax = args.min_price, args.max_price
    only = set(args.only.split(',')) if args.only else None
    today = dt.datetime.now(KST).strftime('%Y-%m-%d')
    if args.out:
        os.makedirs(args.out, exist_ok=True)
    done, errors, detail_fail = {}, {}, {}   # 구역 index → 결과 / 오류 / 상세 실패 건수
    todo = [i for i, Z in enumerate(ZONES) if not only or Z['name'] in only]
    for rnd in range(2):   # 2바퀴째는 1바퀴에서 목록 페이지가 실패한 구역만, 쿨다운 뒤 다시 돈다
        if rnd:
            todo = sorted(errors)
            if not todo:
                break
            print(f'.. {len(todo)}개 구역 목록 수집 실패 — {ZONE_RETRY_WAIT}s 뒤 다시 시도', file=sys.stderr)
            time.sleep(ZONE_RETRY_WAIT)
        for i in todo:
            Z = ZONES[i]
            try:
                asks, meta = fetch_list(Z['did'])
            except (CollectError, requests.RequestException) as e:
                errors[i] = f'{Z["title"]}: {e}'
                print(f'!! {Z["title"]}: {e}', file=sys.stderr)
                continue
            errors.pop(i, None)
            nfail = 0
            for aid, a in asks.items():
                d = fetch_detail(Z['did'], aid)
                nfail += d is None
                a['_detail'] = d or {}
                time.sleep(0.5)
            if nfail:
                detail_fail[i] = nfail
            rows, basedate, bsrc, has_poly, st = score_zone(Z, asks, meta, pmin, pmax)
            block = render_md(Z, rows, len(asks), basedate, bsrc, has_poly, today, st, pmin, pmax)
            if args.out:
                open(os.path.join(args.out, f'md_{Z["name"]}.md'), 'w', encoding='utf-8').write(block)
            hist = history_records(Z, st, basedate, bsrc, has_poly, meta.get('stage'), len(asks), today, pmin, pmax)
            prev = write_listing_file(os.path.join(ROOT, 'regions', 'listings', Z['file'] + '.md'), block, args.dry_run)
            top = ' · '.join(f'{r["addr"].split()[-1]}({r["score"]})' for r in rows[:3])
            done[i] = dict(title=Z['title'], prev=prev, now=len(rows), dedup=st['n_dedup'], exc=st['n_exc'], registered=len(asks), stage=meta.get('stage'), top=top, hist=hist)
            print(f'{Z["title"]:12s} {prev if prev is not None else "-":>3} → {len(rows):3d}건 (등록 {len(asks)}, 중복 제거 {st["n_dedup"]}, 예산 내 {st["n_inb"]}, 저가 예외 {st["n_exc"]}, 단계 {meta.get("stage")}) 상위 {top}'
                  + (f' · 상세 실패 {nfail}건' if nfail else ''))
            time.sleep(1)
    results = [done[i] for i in sorted(done)]   # 재시도로 순서가 섞여도 요약·스냅샷은 ZONES 순서
    history = [h for r in results for h in r['hist']]
    errors = [errors[i] for i in sorted(errors)]
    total = sum(r['now'] for r in results)
    total_dedup = sum(r['dedup'] for r in results)
    total_exc = sum(r['exc'] for r in results)
    lines = [f'auto-listings: 매물 절 갱신 {today} — {len(results)}구역 {total}건 (예산 필터 {pmin:.1f}~{pmax:.1f}억, 저가 예외 {total_exc}건)', '']
    for r in results:
        lines.append(f'- {r["title"]}: {r["prev"] if r["prev"] is not None else "—"} → {r["now"]}건 (중복 제거 {r["dedup"]}건 중 {r["dedup"] - r["now"]}건 범위 밖, 저가 예외 {r["exc"]}건) · 상위 {r["top"] or "없음"}')
    lines += [f'- 예산 필터: 호가 {pmin:.2f}억 이상 {pmax:.2f}억 이하 + 하한 미만 점수 예외 {total_exc}건 — 전 구역 {total_dedup}건 중 {total_dedup - total}건 제외',
              f'- 출처: 재개발닷컴 jaegebal.com/develops/{{id}}/asks ({today} 자동수집)', '- 등급: D (호가·매물, 계산 근거 아님)',
              '- 근거: 자동수집 tools/collect_listings.py · 채점 DECISIONS #19 · 예산 필터 DECISIONS #19 4·5차']
    if detail_fail:   # 상세가 빠진 매물은 대지·연면적(→ 지분·단가) 없이 채점되고, 권리산정기준일 추정에서도 빠진다 — 조용히 넘기지 않는다
        lines.append('- 상세 페이지 재시도 후 실패: ' + ' · '.join(f'{ZONES[i]["title"]} {n}건' for i, n in sorted(detail_fail.items())))
    if errors:
        lines += ['', '수집 실패:'] + [f'- {e}' for e in errors]
    summary = '\n'.join(lines) + '\n'
    if args.summary:
        open(args.summary, 'w', encoding='utf-8').write(summary)
    print('\n' + summary)
    if history:
        # 부분 스냅샷(구역 일부만 돌았거나 실패가 섞인 회차)은 .partial 로 떨어뜨린다 — gitignore 되어 이력에 섞이지 않는다
        partial = bool(only) or bool(errors)
        os.makedirs(args.history_dir, exist_ok=True)
        hp = os.path.join(args.history_dir, f'{today}{".partial" if partial else ""}.jsonl')
        write_history(hp, history)
        print(f'history: {hp} — {len(history)}행 (zone {len(results)} + ask {len(history) - len(results)})'
              + ('  ** 부분 실행 — 커밋 대상 아님 **' if partial else ''))
    if errors:
        print(f'FAIL  {len(errors)}개 구역 목록 페이지 수집 실패 — 커밋하지 않는다', file=sys.stderr)
        return 1
    if results and total_dedup == 0:   # 필터 전 수집량으로 판정한다 — 예산 필터로 0건이 되는 것은 정상이다
        print('FAIL  전 구역 수집 0건 — 재개발닷컴 구조 변경 의심. 커밋하지 않는다', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
