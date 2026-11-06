"""매물 자동수집 — 재개발닷컴 구역 매물 → 러프 매력도 점수 → `regions/listings/NN_slug.md` 통째 쓰기.

PC 작업 스케줄러가 매주 목요일 09:00 KST에 tools/listings_local.py 로 실행한다 — 재개발닷컴이 GitHub 러너 IP 를 막아
2026-10-23 러너에서 PC 로 옮겼다(DECISIONS #19 7차). 손으로 돌릴 때도 같은 명령이다.
    python tools/collect_listings.py [--only sangdo16,jangwi15] [--dry-run] [--out DIR] [--summary FILE]
                                     [--min-price 6.0] [--max-price 8.0]   # 하한 이상 ~ 상한 이하
                                     [--history-dir data/listings]
                                     [--from-dir DIR]   # 사람이 브라우저로 저장한 목록 페이지로 — 재개발닷컴 요청 0건

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
- 요청은 전부 REQUEST_INTERVAL(8초) 간격으로 보낸다 — robots.txt `Crawl-delay: 1` 준수. 429(속도 규칙)로 쉬면 쉰 뒤 간격을 2배로(상한 INTERVAL_MAX).
  2026-10-23 PC 실행은 4초 간격에서 약 50건(3분 20초)마다 429 — 집계 창 4분 이상·문턱 약 50건으로 읽힌다. 10-16까지는 4초로 23분을 버텼다.
  재개발닷컴 WAF 가 한 실행의 약 190번째 요청부터 러너를 막아 1·2차 시도가 같은 자리에서 실패했다(2026-10-16, HTTP 405).
- 상세(필지면적·연면적)는 재개발닷컴 상세 페이지가 아니라 **브이월드 NED** 에서 받는다(2026-11-06~): 토지특성 `lndpclAr`,
  건축물 연령(건축물대장 표제부) `buldTotar` 합. 재개발닷컴 상세와 같은 값이다(장위동 262-14 대조 70㎡·346.78㎡·사용승인 1992-03-06).
  재개발닷컴이 11-05 부터 자동 클라이언트에 상세를 주지 않고(사람 브라우저에는 준다) 이어 CAPTCHA 로 막아, 재개발닷컴에는 목록만 보낸다.
  주소(「장위동 262-14」)는 구역별 법정동코드 표 ZONES `bjd` 로 PNU 가 된다(코드는 브이월드 지오코더 level4LC 로 확정).
  표에 없는 동이면 그 매물은 상세 누락으로 센다 — 표에 동을 더한다. 2026-11-06 캐시(재개발닷컴 상세) 33건 대조: 필지면적 33/33,
  연면적 28/33 일치·5건은 브이월드 건축물 연령이 빈다(2018년 이후 사용승인분 전부 + 오래된 건물 일부). 그런 매물은 연면적 없이
  (다세대는 지분 미상) 채점되고 요약에 건수가 남는다. 같은 동이 두 번 오는 응답은 건물 식별번호로 지운다.
  결과는 매물 id 별로 `data/listings/details.json` 에 캐시한다. 새 매물과 DETAIL_TTL_DAYS 지난 브이월드 값만 다시 받는다 —
  재개발닷컴에서 받아 둔 값은 다시 받을 길이 없으니 만료시키지 않는다.
- 재개발닷컴 요청은 실행당 JAEGEBAL_MAX_REQUESTS 건이 상한이다(브라우저 토큰 발급의 문서 요청 포함). 넘기 전에 멈춘다.
- `--from-dir DIR`: 사람이 브라우저로 열어 저장한 목록 페이지(`listings_local.py --install-manual` 의 북마클릿이 만든
  `jaegebal-<develop id>-YYYYMMDD-HHMM.txt`)를 읽는다 — 재개발닷컴 요청 0건. 저장본이 있는 구역만 갱신하고(부분 회차), 2바퀴째는 없다.
- 2026-10-23부터 재개발닷컴은 첫 요청부터 AWS WAF Challenge(202, 브라우저 JS 로 토큰 발급)를 건다 — 요청 수와 무관하다.
  Challenge 응답이면 먼저 헤드리스 Chromium(Playwright)으로 그 페이지를 열어 `aws-waf-token` 쿠키를 받고, 쿠키와 브라우저 UA 를
  requests 세션에 옮겨 같은 요청을 다시 보낸다(실행당 TOKEN_REFRESHES 회). 토큰이 Challenge 를 면제하는 시간은 약 5분이라
  (2026-10-29 실측: 09:00·09:05·09:10·09:15 마다 다시 Challenge) 8초 간격 약 45분 실행이면 9~10회 받는다.
  IP 차단(헤더 없는 403)은 브라우저로도 토큰이 안 나온다 — 그때 아래 쉼으로 넘어간다.
- CAPTCHA(405 또는 `x-amzn-waf-action: captcha`)는 쉬지 않고 그 자리에서 멈춘다(exit 1). 사람 확인을 요구하는 것이라 우회하지 않고,
  쉼으로도 안 풀린다 — 2026-10-30 은 PC IP 자체에 CAPTCHA 가 걸려(사람 브라우저도 같음) 쉼 3회 30분 동안 요청만 쌓았다.
  그래서 막혀 있는 동안의 주간 실행은 요청 몇 건으로 끝나는 확인이 되고, 풀린 주부터 그대로 수집한다.
- 차단(403·405·429 또는 `x-amzn-waf-action` 헤더)이 토큰으로 안 풀리면 그 자리에서 멈추고 BLOCK_WAIT 쉰 뒤 같은 요청부터 잇는다(실행당 BLOCK_PAUSES 회).
  그래도 막히면 더 보내지 않고 exit 1. 일시 오류(408·425·5xx·네트워크)는 요청마다 짧게 백오프 재시도하고,
  그래도 실패한 구역은 전 구역 한 바퀴 뒤 쿨다운하고 한 번 더 돈다.
- 조용히 틀리지 않는다: 재시도 후에도 목록 페이지가 200이 아니거나, 구역 상세 누락이 상한(10% 초과·3건 이상)이거나,
  전 구역 수집 합계(예산 필터 전) 0건이면 exit 1 → CI 실패, 커밋 없음. 상한 아래의 상세 누락 건수는 커밋 메시지 요약에 남긴다.
  상세 누락은 조회 오류 · 필지 자료 없음(PNU 가 틀렸다) · 법정동 미등록으로 나눠 세고, 종류마다 첫 사례를 로그에 한 줄 찍는다.
- 의존성: requests + playwright(chromium). playwright 가 없으면 토큰 단계만 건너뛴다.
  브이월드 키 `VWORLD_API_KEY`(환경변수 또는 저장소 `.env`)가 없으면 exit 1 — 상세 없이 채점하면 지분 두 축이 중간값으로 몰린다.
"""
import argparse
import datetime as dt
import glob
import io
import json
import os
import re
import sys
import time
from urllib.parse import urlparse

import requests

for _s in (sys.stdout, sys.stderr):   # Windows 콘솔(cp949)에서도 한글·— 출력이 죽지 않게. 줄 단위로 내보내야 CI 로그 시각이 실제 시각이다
    try:
        _s.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
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

# 구역 설정. basedate 는 레지스트리 확정값(없으면 None → 상세 캐시에 남은 재개발닷컴 right_basedate 를 채점에만 사용).
# bjd 는 매물 주소 동 이름 → 법정동코드 10자리(PNU 앞부분). 2026-11-06 브이월드 지오코더 level4LC 로 동마다 확정 —
# 저장된 응답에서 거꾸로 뽑으면 틀린다(장위15 상월곡동을 1129014200 으로 찌른 Q15 태스크가 5건 전부 빈 응답이었다. 맞는 값 1129013700).
# anchor 는 노트에 찍는 기준 앵커 문구(레지스트리 요약). 구역 파일의 사실이 바뀌면 여기도 맞춘다.
ZONES = [
    dict(name='dapsimni489', did='2153', title='답십리동 489', file='01_dapsimni489', bjd={'답십리동': '1123010500'}, basedate='2023-12-07', anchor='구역 내 2026 중개거래 중앙 5.90억(단독다가구 지문 복원 3건, A) · 실거래/개별주택가격 배율 2.70(9건, A) · 개별공시지가 중앙 396만원/㎡(378필지, A)'),
    dict(name='jayang655', did='4641', title='자양1동 655', file='02_jayang655', bjd={'자양동': '1121510500'}, basedate='2026-05-18', anchor='폴리곤 대조 구역 내 21건 중앙값 5.20억(2026, A) · 실거래/공시 배율 중앙 2.85(n=21, A)'),
    dict(name='cheonho338', did='1738', title='천호동 338', file='03_cheonho338', bjd={'천호동': '1174010900'}, basedate='2024-05-23', anchor='폴리곤 대조 구역 내 52건 중앙값 5.00억(2026, A) · 실거래/공시 배율 중앙 2.93(n=52, A)'),
    dict(name='jangwi15', did='2327', title='장위15', file='04_jangwi15', bjd={'장위동': '1129013800', '상월곡동': '1129013700'}, basedate=None, anchor='233-42 실거래 10.00억(2026-06, 대지권 61.32㎡, A)'),
    dict(name='sangdo16', did='3691', title='상도16', file='05_sangdo16', bjd={'상도동': '1159010200'}, basedate='2025-05-23', anchor='구역 내 실거래 중앙값 4.60억 · 대지권27㎡+ 중앙값 5.70억(A)'),
    dict(name='galhyeon510-1', did='4640', title='갈현동 510-1(갈현3)', file='06_galhyeon510-1', bjd={'갈현동': '1138010400'}, basedate='2026-07-01', anchor='폴리곤 대조 구역 내 78건 중앙값 2.51억(2026, A) · 실거래/공시 배율 중앙 1.92(n=69, A)'),
    dict(name='sutaek2', did='4074', title='수택2', file='07_sutaek2', bjd={'수택동': '4131010500'}, basedate='2023-07-14', anchor='폴리곤 대조 구역 내 149건 중앙값 4.35억(2026, A) · 고시 권리자 분양가 35평형 6.77억·보정률 1.65·비례율 108.13%(고시 제2023-94호, A)'),
    dict(name='daejo212', did='4577', title='대조동212(가칭)', file='08_daejo212', bjd={'대조동': '1138010600'}, basedate=None, anchor='폴리곤 대조 구역 내 52건 중앙값 3.23억(2026, A) · 권리산정기준일 미지정'),
    dict(name='guui2donga', did='4141', title='구의2동A구역(구의동 46)', file='09_guui2dong46', bjd={'구의동': '1121510300'}, basedate='2026-01-27', anchor='폴리곤 대조 구역 내 58건 중앙값 5.70억(2026, A) · 실거래/공시 배율 중앙 3.19(n=59, A) · 토허 대상'),
    dict(name='seokchon-gobun1', did='4916', title='석촌고분1구역(석촌동 232 일대)', file='10_seokchon-gobun1', bjd={'석촌동': '1171010500'}, basedate=None, anchor='폴리곤 대조 구역 내 80건 중앙값 4.23억(2026, A) · 실거래/공시 배율 중앙 2.19(n=80, A) · 권리산정기준일 미지정 · 민간 도심복합'),
    dict(name='seokchon-gobun2', did='4917', title='석촌고분2구역(석촌동 232 일대)', file='11_seokchon-gobun2', bjd={'석촌동': '1171010500'}, basedate=None, anchor='폴리곤 대조 구역 내 30건 중앙값 4.80억(2026, A) · 실거래/공시 배율 중앙 2.11(n=30, A) · 권리산정기준일 미지정 · 민간 도심복합'),
]

session = requests.Session()
session.headers.update({'User-Agent': UA, 'Accept-Language': 'ko-KR,ko;q=0.9'})

# 재개발닷컴은 CloudFront(AWS WAF) 뒤 Next.js 오리진이다. 한 IP 의 요청 수가 문턱을 넘으면 WAF 가 막는다 —
# 10-02~10-13 은 약 250번째 요청에서 403·429(수십 초~수 분), 2026-10-16 은 약 190번째 요청부터 405(AWS WAF CAPTCHA 의 응답 코드)였고
# 180초 쉬어도 풀리지 않아 1·2차 시도가 같은 자리에서 실패했다. 그래서 간격을 벌려 문턱 아래로 보내고, 막히면 멈춰서 오래 쉰다.
# 오리진 일시 오류(500 = 오리진 30초 타임아웃 등)는 짧게 다시 찌른다(2026-09-18·09-25 예약 실행이 1회 오류로 통째 실패했다).
REQUEST_INTERVAL = 8.0          # 초. 요청 시작 간 최소 간격 — 5분 37건(관측 문턱 약 50건의 75%), robots.txt Crawl-delay 1
INTERVAL_MAX = 32.0            # 초. 429 로 쉴 때마다 간격을 2배로 늘리는 상한
BLOCK = {403, 405, 429}         # WAF 차단. 202 + x-amzn-waf-action(Challenge)도 차단으로 본다
BLOCK_WAIT = 600                # 초. AWS WAF 속도 규칙의 가장 긴 집계 창(10분) 동안 아무것도 보내지 않는다
BLOCK_PAUSES = 3                # 실행당 차단 쉼 횟수. 다 쓰고도 막히면 더 보내지 않고 끝낸다
TOKEN_REFRESHES = 20            # 실행당 브라우저 토큰 발급 횟수. 쉼보다 먼저 쓴다. 토큰 면제 약 5분 × 실행 약 45분의 2배 —
                                # 3회였던 2026-10-29 는 15분 만에 소진하고 쉼 3회(30분)로도 Challenge 가 안 풀려 11구역째에서 멈췄다
TOKEN_WAIT = 30                 # 초. 브라우저가 Challenge 를 풀어 토큰 쿠키가 생기기를 기다리는 상한(실측 1초)
TRANSIENT = {408, 425, 500, 502, 503, 504}
LIST_BACKOFF = (15, 45, 90)     # 초. 목록 페이지 — 실패하면 구역 전체가 빠지므로 길게 기다린다
ZONE_RETRY_WAIT = 180           # 초. 재시도까지 실패한 구역을 전 구역 한 바퀴 뒤 다시 도는 쿨다운
JAEGEBAL_MAX_REQUESTS = 30      # 실행당 재개발닷컴 요청 상한(토큰 발급 문서 2건씩 포함). 정상 회차는 목록 11~15건 + 토큰 1~2회.
                                # 2026-11-05 는 상세까지 두 바퀴 약 410건을 보낸 뒤 CAPTCHA 가 걸렸다 — 그 규모를 다시 만들지 않는다
DETAIL_TTL_DAYS = 28            # 상세 캐시 수명. 지나면 다시 받는다(브이월드라 재개발닷컴 요청과 무관)
DETAIL_FAIL_RATIO, DETAIL_FAIL_MIN = 0.10, 3   # 구역 상세 누락이 10%를 넘고 3건 이상이면 그 구역은 실패 — 지분 두 축이 중간값으로 채점된 채 커밋되지 않게
NED_BASE = 'https://api.vworld.kr/ned/data/'
NED_RETRIES = 4                 # 브이월드 일시 오류(URL_TYPE·5xx·네트워크) 재시도 — 같은 PNU 10번에 2~3번 URL_TYPE 이 난다(vworld_probe 실측)
ADDR_RE = re.compile(r'^(\S+)\s+(산\s?)?(\d+)(?:-(\d+))?$')   # 「장위동 262-14」「갈현동 산12-3」 — 동 이름 + 지번


class CollectError(Exception):
    pass


class Blocked(Exception):
    """더 보내면 안 된다 — 차단 쉼 소진·CAPTCHA·요청 상한. 실행 전체를 멈춘다. RequestException 이 아니라서 중간에 삼켜지지 않는다."""


_last_sent = float('-inf')     # 마지막 요청 시각(monotonic)
_pauses = 0                    # 이번 실행에서 쓴 차단 쉼 횟수
_tokens = 0                    # 이번 실행에서 브라우저로 토큰을 받으려 한 횟수
_interval = REQUEST_INTERVAL   # 지금 요청 간격. 429 로 쉬면 늘어난다
_sent = 0                      # 이번 실행에서 재개발닷컴에 보낸 요청 수(토큰 발급 문서 포함)
_ned_calls = 0                 # 이번 실행의 브이월드 호출 수
_first_miss = {}               # 상세 누락 종류 → 첫 사례(로그 한 줄만)


def spend(n):
    """재개발닷컴 요청 n 건을 쓴다 — 상한을 넘기게 되면 보내기 전에 Blocked."""
    global _sent
    if _sent + n > JAEGEBAL_MAX_REQUESTS:
        raise Blocked(f'재개발닷컴 요청 상한 {JAEGEBAL_MAX_REQUESTS}건(이번 실행 {_sent}건) — 더 보내지 않는다')
    _sent += n


def send(url):
    """_interval 을 지켜 한 번 보낸다. 재시도까지 모든 요청이 여기를 지난다."""
    global _last_sent
    spend(1)
    wait = _last_sent + _interval - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_sent = time.monotonic()
    return session.get(url, timeout=40)


def waf(r):
    """차단 응답이면 로그용 진단 문자열, 아니면 None. 405 는 AWS WAF CAPTCHA, 202 + 헤더는 Challenge 다."""
    action = r.headers.get('x-amzn-waf-action')
    if r.status_code in BLOCK or action:
        return f'HTTP {r.status_code} waf={action or "-"} cache={r.headers.get("x-cache", "-")} server={r.headers.get("server", "-")}'
    return None


def browser_token(url):
    """헤드리스 Chromium 으로 url 을 열어 WAF Challenge 를 풀고 aws-waf-token 쿠키·브라우저 UA 를 session 에 옮긴다.
    토큰을 받았으면 True. playwright 가 없거나 토큰이 안 나오면(CAPTCHA·IP 차단) False."""
    global _last_sent
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('   playwright 없음 — 브라우저 토큰 단계를 건너뛴다', file=sys.stderr)
        return False
    spend(2)   # Challenge 페이지 + 풀린 뒤 재로드
    wait = _last_sent + _interval - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_sent = time.monotonic()
    def only_documents(route):
        # 재개발닷컴 쪽은 문서만 보낸다(Challenge 페이지 + 풀린 뒤 재로드 = 2건). Next.js 청크·이미지까지 받으면 수십 건이
        # 속도 규칙에 얹혀 429 가 났다(2026-10-23 PC 첫 실행). 챌린지 스크립트·토큰 발급은 *.token.awswaf.com 이라 막지 않는다
        host = urlparse(route.request.url).hostname or ''
        if host.endswith('jaegebal.com') and route.request.resource_type != 'document':
            return route.abort()
        return route.continue_()

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        try:
            ctx = b.new_context(locale='ko-KR')
            ctx.route('**/*', only_documents)
            pg = ctx.new_page()
            ua = pg.evaluate('navigator.userAgent')   # 이동 전에 읽는다 — Challenge 가 풀리면 페이지가 재로드돼 evaluate 가 깨진다
            pg.goto(url, wait_until='domcontentloaded', timeout=60000)
            for _ in range(TOKEN_WAIT):
                cookies = ctx.cookies()
                if any(c['name'] == 'aws-waf-token' for c in cookies):
                    break
                time.sleep(1)
            else:
                return False
        except Exception as e:
            print(f'   브라우저 토큰 실패 ({type(e).__name__}: {e})', file=sys.stderr)
            return False
        finally:
            b.close()
    for c in cookies:
        session.cookies.set(c['name'], c['value'], domain=c['domain'], path=c['path'])
    session.headers['User-Agent'] = ua   # 토큰은 발급받은 브라우저의 UA 와 짝이다
    _last_sent = time.monotonic()
    return True


def get(url, backoff):
    """차단이면 먼저 브라우저로 WAF 토큰을 받아 같은 요청을 다시(실행당 TOKEN_REFRESHES 회).
    그래도 막히면 BLOCK_WAIT 쉬고 같은 요청부터 다시(실행당 BLOCK_PAUSES 회, 넘으면 Blocked).
    일시 오류(TRANSIENT·네트워크)면 backoff 간격으로 재시도. 마지막 응답을 돌려주거나 마지막 예외를 올린다."""
    global _pauses, _tokens, _interval
    i = 0
    fresh = False   # 이 요청을 위해 방금 토큰을 받았나 — 받자마자 또 막히면 토큰으로 안 풀리는 차단이다
    while True:
        try:
            r = send(url)
        except requests.RequestException as e:
            if i == len(backoff):
                raise
            why = type(e).__name__
        else:
            blk = waf(r)
            if blk:
                # 토큰은 Challenge(202 + challenge)에만 받는다. 429·헤더 없는 403(속도·IP 규칙)은 토큰으로 안 풀리고 발급 요청만 더 쌓는다
                if r.headers.get('x-amzn-waf-action') == 'challenge' and not fresh and _tokens < TOKEN_REFRESHES:
                    _tokens += 1
                    print(f'   차단 ({blk}) — 브라우저로 WAF 토큰 받기 {_tokens}/{TOKEN_REFRESHES}: {url}', file=sys.stderr)
                    if browser_token(url):
                        fresh = True
                        continue
                    print('   토큰 안 나옴 — 쉼으로 넘어간다', file=sys.stderr)
                fresh = False
                if r.status_code == 405 or r.headers.get('x-amzn-waf-action') == 'captcha':
                    raise Blocked(f'{url} → {blk} — CAPTCHA(사람 확인 요구) — 쉬지 않고 멈춘다')
                if _pauses >= BLOCK_PAUSES:
                    raise Blocked(f'{url} → {blk} — 차단 쉼 {BLOCK_PAUSES}회 뒤에도 막힘')
                _pauses += 1
                print(f'   차단 {_pauses}/{BLOCK_PAUSES} ({blk}) — {BLOCK_WAIT}s 아무것도 보내지 않고 같은 요청부터 잇는다: {url}', file=sys.stderr)
                time.sleep(BLOCK_WAIT)
                if r.status_code == 429 and _interval < INTERVAL_MAX:
                    _interval = min(_interval * 2, INTERVAL_MAX)
                    print(f'   요청 간격 {_interval:.0f}s 로 늘린다', file=sys.stderr)
                continue
            if r.status_code not in TRANSIENT or i == len(backoff):
                return r
            why = f'HTTP {r.status_code}'
            ra = r.headers.get('Retry-After', '')
            if ra.isdigit():
                time.sleep(min(int(ra), 120))
        print(f'   재시도 {i + 1}/{len(backoff)} ({why}, {backoff[i]}s 대기): {url}', file=sys.stderr)
        time.sleep(backoff[i])
        i += 1


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


def parse_meta(u):
    """목록 1쪽의 구역 메타 — 매물 수 · 구역계 폴리곤 · 진행 단계."""
    m = re.search(r'"ask_count":(\d+)', u)
    am = re.search(r'"areas":(\[\[\[\[.*?\]\]\]\])', u)
    sm = re.search(r'"detail_stage":"([^"]*)"', u)
    return dict(ask_count=int(m.group(1)) if m else None, areas=json.loads(am.group(1)) if am else None,
                stage=sm.group(1) if sm else None)


def fetch_list(did):
    asks, meta = {}, {}
    for page in range(1, 8):
        url = f'https://jaegebal.com/develops/{did}/asks' + (f'?page={page}' if page > 1 else '')
        r = get(url, LIST_BACKOFF)
        if r.status_code != 200:
            raise CollectError(f'{url} → HTTP {r.status_code}')
        u = unesc(r.text)
        if page == 1:
            meta = parse_meta(u)
        got = extract_asks(u)
        new = [k for k in got if k not in asks]
        asks.update(got)
        if not new or (meta.get('ask_count') and len(asks) >= meta['ask_count']):
            break
    return asks, meta


def load_saved(did, from_dir):
    """사람이 브라우저로 저장한 목록 페이지 → (asks, meta, 파일명). 그 구역 저장본이 없으면 None. 네트워크 요청 0건.

    파일은 `listings_local.py --install-manual` 의 북마클릿이 만든다: 첫 줄 `<!-- fmt=scripts|next_f url=… saved=… -->` 뒤에
    페이지의 플라이트 스크립트 원문(scripts — HTTP 응답과 같은 이스케이프) 또는 이미 풀린 플라이트 문자열(next_f).
    같은 구역 저장본이 여럿이면 파일명(…-YYYYMMDD-HHMM)이 가장 늦은 것을 쓴다. 다른 구역 데이터가 든 파일(사이트 안 링크로
    옮겨 다니면 스크립트가 첫 페이지 것으로 남는다)과 매물 데이터가 없는 파일은 CollectError — 조용히 0건으로 쓰지 않는다."""
    fs = sorted(glob.glob(os.path.join(from_dir, f'jaegebal-{did}-*.txt')))
    if not fs:
        return None
    path = fs[-1]
    name = os.path.basename(path)
    t = io.open(path, encoding='utf-8').read()
    u = t if t.startswith('<!-- fmt=next_f') else unesc(t)
    ids = set(re.findall(r'"develop_id":(\d+),"develop_title"', u))
    if ids and did not in ids:
        raise CollectError(f'{name}: 다른 구역 데이터(develop {", ".join(sorted(ids))}) — 그 구역 페이지에서 새로고침(F5) 뒤 다시 저장')
    meta = parse_meta(u)
    asks = extract_asks(u)
    if not asks and meta['ask_count'] is None:
        raise CollectError(f'{name}: 매물 데이터 없음 — 페이지가 다 뜬 뒤 다시 저장')
    return asks, meta, name


# ---------------------------------------------------------------- 상세 (브이월드 NED)
ned = requests.Session()
# Referer 가 없으면 NED 는 INCORRECT_KEY 를 준다(vworld_probe.py docstring, 00 §6.9). 키는 main 이 params 에 싣는다
ned.headers.update({'User-Agent': 'seoul-redev-registry/collect_listings (+https://great-yob.github.io/seoul-redev-registry)',
                    'Referer': 'https://great-yob.github.io/seoul-redev-registry/'})
MISS_LABEL = dict(fail='조회 오류', empty='필지 자료 없음', nopnu='법정동 미등록')


def vworld_key():
    k = os.environ.get('VWORLD_API_KEY')
    if k:
        return k.strip()
    p = os.path.join(ROOT, '.env')
    if os.path.exists(p):
        for ln in io.open(p, encoding='utf-8'):
            name, _, val = ln.strip().partition('=')
            if name.strip() == 'VWORLD_API_KEY':
                return val.strip().strip('"').strip("'")
    return None


def ned_rows(op, root, pnu):
    """(rows, err). rows 가 [] 면 '자료 없음'(막힘 아님 — 빈 응답≠비대상, 00 §6.9), None 이면 err 가 사유."""
    global _ned_calls
    err = None
    for i in range(NED_RETRIES + 1):
        _ned_calls += 1
        try:
            r = ned.get(NED_BASE + op, params=dict(pnu=pnu, format='json', numOfRows=1000, pageNo=1), timeout=25)
            if r.status_code != 200:
                err = f'http:{r.status_code}'
            else:
                js = r.json()
                body = js.get(root) or js.get('response') or {}
                code = (body.get('resultCode') or '').strip()
                if not code or code in ('00', 'NORMAL_SERVICE'):
                    rows = body.get('field') or []
                    return ([rows] if isinstance(rows, dict) else rows), None
                err = f'api:{code}'
        except requests.RequestException as e:
            err = f'network:{type(e).__name__}'
        except ValueError:
            err = 'nonjson'
        if not (err.startswith(('network', 'http:5')) or err == 'api:URL_TYPE'):
            break
        time.sleep(0.5 * (i + 1))
    return None, err


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def pnu_for(Z, addr):
    """(PNU 19자리, 사유). 매물 주소 「장위동 262-14」 → 법정동코드(ZONES bjd) + 산(2)/일반(1) + 본번 4 + 부번 4."""
    m = ADDR_RE.match((addr or '').strip())
    if not m:
        return None, f'주소 형식 밖 {addr!r}'
    code = Z.get('bjd', {}).get(m.group(1))
    if not code:
        return None, f'ZONES bjd 에 없는 동 「{m.group(1)}」'
    return f'{code}{"2" if m.group(2) else "1"}{int(m.group(3)):04d}{int(m.group(4) or 0):04d}', None


def ned_detail(Z, addr):
    """(상세, 출처, 사유). 상세는 채점이 읽는 모양 {address:{land_area, location}, buildings:[{tot_area}], right_basedate} + pnu·src.
    출처: fetch 받음 · nopnu 주소→PNU 실패 · fail 조회 오류 · empty 토지특성 자료 없음(필지가 없다 = PNU 가 틀렸다).
    건축물 연령이 비면(2018년 이후 사용승인·나대지) buildings=[] 로 받는다 — 누락이 아니다. 좌표는 목록에 있어 None."""
    pnu, why = pnu_for(Z, addr)
    if not pnu:
        return None, 'nopnu', why
    land, err = ned_rows('getLandCharacteristics', 'landCharacteristicss', pnu)
    if land is None:
        return None, 'fail', f'토지특성 {err} (PNU {pnu})'
    if not land:
        return None, 'empty', f'토지특성 0행 (PNU {pnu})'
    bld, err = ned_rows('getBuildingAge', 'buildingAges', pnu)
    if bld is None:
        return None, 'fail', f'건축물 연령 {err} (PNU {pnu})'
    latest = max(land, key=lambda r: str(r.get('stdrYear') or ''))   # stdrYear 없이 부르면 2013~ 연도별로 온다
    # 같은 동이 두 번 오기도 한다(천호동 338-32 나동 — 식별번호 같음). 그대로 더하면 1979㎡, 지우면 재개발닷컴과 같은 1319.41㎡
    uniq = {b.get('buldIdntfcNo') or (b.get('buldDongNm'), b.get('buldTotar'), b.get('useConfmDe')): b for b in bld}
    return dict(address=dict(land_area=num(latest.get('lndpclAr')), location=None),
                buildings=[dict(tot_area=num(b.get('buldTotar'))) for b in uniq.values()],
                right_basedate=None, pnu=pnu, src='vworld'), 'fetch', None


# ---------------------------------------------------------------- 상세 캐시 (data/listings/details.json)
def load_cache(path):
    if not os.path.exists(path):
        return {}
    return json.load(io.open(path, encoding='utf-8'))


def save_cache(path, cache):
    """한 줄 = 매물 1건(id 순) — 회차 간 diff 가 새로 받은 매물·빠진 매물만 보이게 한다."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rows = [f'{json.dumps(k)}: {json.dumps(cache[k], ensure_ascii=False, sort_keys=True)}' for k in sorted(cache, key=int)]
    with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('{\n' + ',\n'.join(rows) + '\n}\n')


def detail_for(Z, aid, a, cache, today, memo):
    """캐시가 DETAIL_TTL_DAYS 안이면 그대로, 아니면 브이월드에서 받아 캐시에 넣는다. (상세 또는 None, 출처) 를 돌려준다.

    출처: cache 캐시 · fetch 새로 받음 · stale 다시 받기 실패라 지난 값 · fail·empty·nopnu 누락(ned_detail).
    memo 는 이번 실행의 주소별 결과 — 같은 필지의 여러 호(다세대)를 한 번만 부른다. 누락은 캐시하지 않는다(다음 회차에 다시).
    캐시에는 2026-11-05 까지 재개발닷컴 상세에서 받은 값(src 없음)이 있다. 다시 받을 길이 없고 필지·연면적은 바뀌지 않으므로
    만료시키지 않는다 — 브이월드 건축물 연령은 오래된 건물도 비어 있는 일이 있어(33건 대조 중 5건) 다시 받으면 오히려 값이 빈다.
    브이월드 값은 DETAIL_TTL_DAYS 마다 다시 받되, 새 응답에 건물이 비고 지난 값에 있으면 지난 건물 값을 남긴다.
    """
    key = str(aid)
    hit = cache.get(key)
    if hit and (hit.get('src') != 'vworld'
                or (dt.date.fromisoformat(today) - dt.date.fromisoformat(hit['fetched'])).days < DETAIL_TTL_DAYS):
        return hit, 'cache'
    addr = a.get('address')
    if addr not in memo:
        memo[addr] = ned_detail(Z, addr)
    d, src, why = memo[addr]
    if d:
        if hit and not d['buildings'] and hit.get('buildings'):
            d = dict(d, buildings=hit['buildings'])
        cache[key] = dict(d, fetched=today)
        return cache[key], 'fetch'
    if src not in _first_miss:
        _first_miss[src] = why
        print(f'   상세 누락 첫 사례({MISS_LABEL[src]}): {Z["title"]} {addr} — {why}', file=sys.stderr)
    if hit:   # 필지·연면적은 바뀌지 않는다 — 지난 값이 없는 것보다 낫다
        return hit, 'stale'
    return None, src


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


def render_md(Z, rows, n_registered, basedate, bsrc, has_poly, today, st, pmin, pmax, manual=False):
    L = ['## 매물 (참고 · D · 본표 편입 금지 · 예산 필터)', '']
    src = f'재개발닷컴 [{Z["title"]} 매물 페이지](https://jaegebal.com/develops/{Z["did"]}/asks) {"수동 저장" if manual else "자동 수집"} {today}'
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
    L.append(f'{src} — 등록 {n_registered}건, 중복 제거 {n_dedup}건, **예산 필터({band}) 통과 {st["n_inb"]}건 + 저가 예외 {st["n_exc"]}건 = 표 {len(rows)}건**({n_dedup - len(rows)}건 제외).{rng} **호가·매물이며 실거래가 아니다(D).** 점수는 구역 전체 {n_dedup}건 기준 상대 순위(100점, 채점 규칙 DECISIONS #19)이며 어떤 계산에도 쓰지 않는다. {budget}{exc} 기준 앵커: {Z["anchor"]}. 권리산정기준일 {bd}. {poly}. 대지지분(≈)은 필지면적 × 전용/총연면적 근사(필지면적·연면적은 토지특성·건축물대장, 브이월드).')
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


def history_records(Z, st, basedate, bsrc, has_poly, stage, n_registered, today, pmin, pmax, mode='auto'):
    """회차 스냅샷 레코드. `t` 로 종류를 구분한다 — 구역당 zone 1행 + 필터 전 전체 ask N행. mode 는 목록 출처(auto 자동수집 · manual 수동 저장본).

    md 는 예산 통과분만 싣지만 이력은 필터 전 전체를 남긴다. 예산 기준이 바뀌어도 과거 회차를 다시 계산할 수 있어야 한다.
    통과 0건인 구역도 zone 행은 남는다 — '수집했으나 0건'과 '수집 실패'를 구분하기 위해서다.
    """
    span = st['span']
    out = [dict(t='zone', date=today, zone=Z['name'], title=Z['title'], did=Z['did'], stage=stage,
                registered=n_registered, dedup=st['n_dedup'], in_budget=st['n_inb'], low_exc=st['n_exc'],
                kept=st['n_inb'] + st['n_exc'], cut=st['cut'],
                price_min=r_(span[0], 4) if span else None, price_max=r_(span[1], 4) if span else None,
                budget_min=pmin, budget_max=pmax,
                basedate=basedate, basedate_src=bsrc if basedate else None, poly=has_poly, mode=mode)]
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
    ap.add_argument('--from-dir', help='사람이 저장한 목록 페이지(jaegebal-<did>-*.txt) 디렉터리 — 재개발닷컴 요청 0건, 저장본 있는 구역만')
    args = ap.parse_args()
    pmin, pmax = args.min_price, args.max_price
    only = set(args.only.split(',')) if args.only else None
    manual = args.from_dir
    today = dt.datetime.now(KST).strftime('%Y-%m-%d')
    key = vworld_key()
    if not key:
        print('FAIL  VWORLD_API_KEY 없음(환경변수·.env) — 상세(필지면적·연면적)를 받을 수 없어 수집하지 않는다', file=sys.stderr)
        return 1
    ned.params = dict(key=key)
    if args.out:
        os.makedirs(args.out, exist_ok=True)
    cache_path = os.path.join(args.history_dir, 'details.json')
    cache = load_cache(cache_path)
    done, errors, detail_fail = {}, {}, {}   # 구역 index → 결과 / 오류 / 상세 누락 건수
    src_n = dict(cache=0, fetch=0, stale=0, fail=0, empty=0, nopnu=0)   # 상세 출처별 건수 — 끝난 구역만 센다
    nobldg, short = 0, []   # 건축물 연령 자료 없는 매물 수 · 저장본이 목록 일부만 담은 구역
    seen, blocked, memo = set(), None, {}   # 이번 회차 목록에 나온 매물 id · 차단으로 멈춘 사유 · 주소별 상세
    first = todo = [i for i, Z in enumerate(ZONES) if (not only or Z['name'] in only)
                    and (not manual or glob.glob(os.path.join(manual, f'jaegebal-{Z["did"]}-*.txt')))]
    if manual and not first:
        print(f'FAIL  저장본 없음 — {manual} 에 jaegebal-<develop id>-*.txt 가 하나도 없다', file=sys.stderr)
        return 1
    full = len(first) == len(ZONES)   # 전 구역 회차인가 — 아니면 스냅샷은 .partial, 캐시 정리도 하지 않는다
    for rnd in range(1 if manual else 2):   # 2바퀴째는 1바퀴에서 실패한 구역만, 쿨다운 뒤 다시 돈다. 저장본은 다시 읽어도 같아 1바퀴
        if rnd:
            todo = sorted(errors)
            if not todo:
                break
            print(f'.. {len(todo)}개 구역 수집 실패 — {ZONE_RETRY_WAIT}s 뒤 다시 시도', file=sys.stderr)
            time.sleep(ZONE_RETRY_WAIT)
        for i in todo:
            Z = ZONES[i]
            try:
                if manual:
                    asks, meta, fname = load_saved(Z['did'], manual)
                    print(f'   {Z["title"]}: 저장본 {fname}', file=sys.stderr)
                    if meta.get('ask_count') and len(asks) < meta['ask_count']:
                        short.append(f'{Z["title"]} {len(asks)}/{meta["ask_count"]}')
                else:
                    asks, meta = fetch_list(Z['did'])
                got = {aid: detail_for(Z, aid, a, cache, today, memo) for aid, a in asks.items()}
            except Blocked as e:
                blocked = errors[i] = f'{Z["title"]}: {e}'
                print(f'!! {blocked} — 더 보내지 않고 멈춘다', file=sys.stderr)
                break
            except (CollectError, requests.RequestException) as e:
                errors[i] = f'{Z["title"]}: {e}'
                print(f'!! {Z["title"]}: {e}', file=sys.stderr)
                continue
            n_src = dict.fromkeys(src_n, 0)
            zone_nobldg = 0
            for aid, a in asks.items():
                d, src = got[aid]
                n_src[src] += 1
                a['_detail'] = d or {}
                zone_nobldg += bool(d) and not d.get('buildings')
            nfail = n_src['fail'] + n_src['empty'] + n_src['nopnu']
            if nfail > DETAIL_FAIL_RATIO * len(asks) and nfail >= DETAIL_FAIL_MIN:
                errors[i] = (f'{Z["title"]}: 상세 {nfail}/{len(asks)}건 누락('
                             + ' · '.join(f'{MISS_LABEL[k]} {n_src[k]}' for k in MISS_LABEL if n_src[k])
                             + f') — 상한({DETAIL_FAIL_RATIO:.0%} 초과·{DETAIL_FAIL_MIN}건 이상)')
                print(f'!! {errors[i]}', file=sys.stderr)
                continue
            errors.pop(i, None)
            seen.update(str(aid) for aid in asks)
            for k, v in n_src.items():
                src_n[k] += v
            nobldg += zone_nobldg
            if nfail:
                detail_fail[i] = nfail
            rows, basedate, bsrc, has_poly, st = score_zone(Z, asks, meta, pmin, pmax)
            block = render_md(Z, rows, len(asks), basedate, bsrc, has_poly, today, st, pmin, pmax, manual=bool(manual))
            if args.out:
                open(os.path.join(args.out, f'md_{Z["name"]}.md'), 'w', encoding='utf-8').write(block)
            hist = history_records(Z, st, basedate, bsrc, has_poly, meta.get('stage'), len(asks), today, pmin, pmax,
                                   mode='manual' if manual else 'auto')
            prev = write_listing_file(os.path.join(ROOT, 'regions', 'listings', Z['file'] + '.md'), block, args.dry_run)
            top = ' · '.join(f'{r["addr"].split()[-1]}({r["score"]})' for r in rows[:3])
            done[i] = dict(title=Z['title'], prev=prev, now=len(rows), dedup=st['n_dedup'], exc=st['n_exc'], registered=len(asks), stage=meta.get('stage'), top=top, hist=hist)
            print(f'{Z["title"]:12s} {prev if prev is not None else "-":>3} → {len(rows):3d}건 (등록 {len(asks)}, 중복 제거 {st["n_dedup"]}, 예산 내 {st["n_inb"]}, 저가 예외 {st["n_exc"]}, 단계 {meta.get("stage")}) 상위 {top}'
                  + (f' · 상세 누락 {nfail}건' if nfail else '') + f' · 상세 새로 {n_src["fetch"]}·캐시 {n_src["cache"] + n_src["stale"]}')
        if blocked:
            break
    if full and not errors:   # 전 구역을 다 돈 회차만 — 목록에서 사라진 매물은 캐시에서도 뺀다
        cache = {k: v for k, v in cache.items() if k in seen}
    save_cache(cache_path, cache)
    untried = [ZONES[i]['title'] for i in first if i not in done and i not in errors]   # 차단으로 멈춰 손대지 못한 구역
    results = [done[i] for i in sorted(done)]   # 재시도로 순서가 섞여도 요약·스냅샷은 ZONES 순서
    history = [h for r in results for h in r['hist']]
    errors = [errors[i] for i in sorted(errors)]
    total = sum(r['now'] for r in results)
    total_dedup = sum(r['dedup'] for r in results)
    total_exc = sum(r['exc'] for r in results)
    lines = [f'auto-listings: 매물 절 갱신 {today}{" (수동 저장본)" if manual else ""} — {len(results)}구역 {total}건 (예산 필터 {pmin:.1f}~{pmax:.1f}억, 저가 예외 {total_exc}건)', '']
    for r in results:
        lines.append(f'- {r["title"]}: {r["prev"] if r["prev"] is not None else "—"} → {r["now"]}건 (중복 제거 {r["dedup"]}건 중 {r["dedup"] - r["now"]}건 범위 밖, 저가 예외 {r["exc"]}건) · 상위 {r["top"] or "없음"}')
    lines += [f'- 예산 필터: 호가 {pmin:.2f}억 이상 {pmax:.2f}억 이하 + 하한 미만 점수 예외 {total_exc}건 — 전 구역 {total_dedup}건 중 {total_dedup - total}건 제외',
              f'- 출처: 재개발닷컴 jaegebal.com/develops/{{id}}/asks ({today} ' + ('수동 저장 — 사람이 브라우저로 연 목록 페이지)' if manual else '자동수집)'),
              '- 등급: D (호가·매물, 계산 근거 아님)',
              '- 근거: ' + ('수동 저장본' if manual else '자동수집') + ' tools/collect_listings.py · 채점 DECISIONS #19 · 예산 필터 DECISIONS #19 4·5차 · 상세 출처 DECISIONS #19 8차',
              f'- 상세(필지면적·연면적): 브이월드 NED 새로 받음 {src_n["fetch"]}건 · 캐시 {src_n["cache"]}건' + (f' · 다시 받기 실패로 지난 값 {src_n["stale"]}건' if src_n['stale'] else '')
              + f' (호출 {_ned_calls}회, data/listings/details.json, {DETAIL_TTL_DAYS}일 지나면 다시 받음)',
              f'- 재개발닷컴 요청 {_sent}건' + (' — 수동 저장본 ' + f'{len(first)}구역' if manual else f' (상한 {JAEGEBAL_MAX_REQUESTS})')]
    if nobldg:   # 연면적이 없으면 다세대 지분이 비고 그 축은 중간값이 된다 — 조용히 넘기지 않는다
        lines.append(f'- 건축물 연령 자료 없음 {nobldg}건 — 브이월드 공백(2018년 이후 사용승인분 전부·오래된 건물 일부). 연면적 없이 채점(다세대는 지분 미상)')
    if short:
        lines.append('- 저장본 목록이 일부만(저장 건수/등록 건수): ' + ' · '.join(short) + ' — 2쪽 이상은 저장되지 않는다')
    if _tokens:
        lines.append(f'- 재개발닷컴 WAF 토큰 브라우저 발급 시도 {_tokens}회 (헤드리스 Chromium)')
    if _pauses:
        lines.append(f'- 재개발닷컴 차단 쉼 {_pauses}회(각 {BLOCK_WAIT}초, 요청 간격 {REQUEST_INTERVAL:.0f} → {_interval:.0f}초) — 차단 응답 상태·헤더는 실행 로그')
    if detail_fail:   # 상세가 빠진 매물은 대지·연면적(→ 지분·단가) 없이 채점되고, 권리산정기준일 추정에서도 빠진다 — 조용히 넘기지 않는다
        lines.append('- 상세 누락(' + ' · '.join(f'{MISS_LABEL[k]} {src_n[k]}' for k in MISS_LABEL if src_n[k]) + '): '
                     + ' · '.join(f'{ZONES[i]["title"]} {n}건' for i, n in sorted(detail_fail.items())))
    if errors:
        lines += ['', '수집 실패:'] + [f'- {e}' for e in errors]
    if untried:
        lines += ['', '차단으로 멈춰 수집하지 않음: ' + ' · '.join(untried)]
    summary = '\n'.join(lines) + '\n'
    if args.summary:
        open(args.summary, 'w', encoding='utf-8').write(summary)
    print('\n' + summary)
    if history:
        # 부분 스냅샷(구역 일부만 돌았거나 실패가 섞인 회차)은 .partial 로 떨어뜨린다 — gitignore 되어 이력에 섞이지 않는다
        partial = not full or bool(errors)
        os.makedirs(args.history_dir, exist_ok=True)
        hp = os.path.join(args.history_dir, f'{today}{".partial" if partial else ""}.jsonl')
        write_history(hp, history)
        print(f'history: {hp} — {len(history)}행 (zone {len(results)} + ask {len(history) - len(results)})'
              + ('  ** 부분 실행 — 커밋 대상 아님 **' if partial else ''))
    if errors:
        print(f'FAIL  {len(errors)}개 구역 수집 실패' + (f' · {len(untried)}개 구역 미수집(차단으로 중단)' if untried else '')
              + ' — 커밋하지 않는다', file=sys.stderr)
        return 1
    if results and total_dedup == 0:   # 필터 전 수집량으로 판정한다 — 예산 필터로 0건이 되는 것은 정상이다
        print('FAIL  전 구역 수집 0건 — 재개발닷컴 구조 변경 의심. 커밋하지 않는다', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
