# data/ — 기계 축적본 (append-only)

원본과 축적을 분리한다. **판단은 md, 축적은 여기다.**

| | `regions/*.md` 의 `## 매물` 절 | `data/listings/*.jsonl` |
| :-- | :-- | :-- |
| 성격 | 사람이 읽는 **판단용 뷰** | 기계가 쌓는 **회차 스냅샷** |
| 범위 | 예산 필터 통과분 + 저가 예외만 | **필터 전 구역 전체**(중복 제거 후) |
| 수명 | 매주 통째 교체 — 지난 회차는 사라짐 | 회차당 1파일, 지우지 않음 |
| 쓰는 곳 | 페이지·엑셀·판단 | 시계열(호가 추이·매물 회전율·점수 변화) |

두 산출물 모두 `tools/collect_listings.py` 한 번의 실행에서 나온다. 사람이 손으로 고치지 않는다.

**등급은 D다.** 호가·매물이며 실거래가 아니다. 요약표·추정 블록의 어떤 계산에도 넣지 않는다(`00_PROJECT_BRIEF.md` §9, `DECISIONS.md` #19).

---

## `data/listings/YYYY-MM-DD.jsonl`

한 줄 = JSON 객체 1개. UTF-8 · LF · 키 정렬(회차 간 diff 가 실제 변화만 보이도록).
파일명의 날짜는 수집일(KST). 같은 날 다시 돌리면 그 파일만 덮어쓴다 — 회차는 중복되지 않는다.

`t` 로 종류를 구분한다. 구역당 **zone 1행 + ask N행**이며, 매물이 0건인 구역도 zone 행은 남는다 —
"수집했는데 0건"과 "수집 실패"는 다르고, 뒤엣것은 애초에 파일이 생기지 않는다.

### `t: "zone"` — 구역 회차 요약

| 키 | 뜻 |
| :-- | :-- |
| `zone` `title` `did` | 구역 slug · 이름 · 재개발닷컴 develop_id |
| `stage` | 재개발닷컴이 표기한 단계 (레지스트리 단계와 별개, 대조용) |
| `registered` `dedup` | 등록 건수 · 중복 제거 후 건수 |
| `in_budget` `low_exc` `kept` | 예산 통과 · 저가 예외 · md 표에 실린 합계 |
| `cut` | 저가 예외 기준선(= 예산 통과분 최고점). 통과 0건이면 `null` |
| `price_min` `price_max` | 필터 전 구역 호가 범위(억) |
| `budget_min` `budget_max` | 그 회차에 적용된 예산 필터(억) — **기준이 바뀌어도 과거를 재계산할 수 있게 회차마다 박아 둔다** |
| `basedate` `basedate_src` | 권리산정기준일과 출처(`레지스트리` / `재개발닷컴`) |
| `poly` | 구역계 폴리곤 대조 가능 여부 |

### `t: "ask"` — 매물 1건

| 키 | 뜻 |
| :-- | :-- |
| `id` `addr` `typ` | 재개발닷컴 매물 id(→ `jaegebal.com/asks/{id}`) · 주소 · 유형 |
| `price` | 호가(억) |
| `share` `unit` | 대지지분 근사(㎡) · 지분 단가(억/㎡) |
| `floor` `max_floor` `use_apr` `year` | 층 · 최고층 · 사용승인(YYYY-MM) · 연도 |
| `after_basedate` | 권리산정기준일 이후 — 현금청산 위험 |
| `inside` | 구역계 폴리곤 내부 여부 (`null` = 대조 불가) |
| `land` | 단독·토지·다가구 여부 (채점에서 층 축 만점) |
| `score` `rank` | 점수(100점, 구역 전체 상대 순위) · md 표 내 순위(`kept: false` 면 `null`) |
| `in_budget` `low_exc` `kept` | 예산 통과 여부 · 저가 예외로 실렸는지 · md 표에 실렸는지 |
| `anom` | 단가 이상치(단독 중앙값 40% 미만) — 공유지분·오기 의심 |
| `flags` | md 메모 열과 같은 문자열 배열 |
| `lng` `lat` | 매물 좌표 |

`kept: false` 행이 이 파일의 존재 이유다 — md 에는 없고 여기에만 있다.

### `*.partial.jsonl`

`--only` 로 일부 구역만 돌렸거나 수집 실패 구역이 섞인 회차. **회차 전체가 아니므로 이력이 아니다.**
`.gitignore` 되어 커밋되지 않는다. 로컬 확인용이며 지워도 된다.

---

## 읽기

```bash
# 특정 구역 호가 추이 (회차별 중앙값)
cat data/listings/*.jsonl | jq -r 'select(.t=="ask" and .zone=="sangdo16") | [.date, .price] | @tsv'

# 회차별 구역 요약
cat data/listings/*.jsonl | jq -r 'select(.t=="zone") | [.date, .zone, .dedup, .kept, .price_min, .price_max] | @tsv'
```

`.partial.jsonl` 은 위 글롭에 걸리지 않는다(`*.jsonl` 에는 걸리므로 시계열을 만들 땐 `[0-9]*-[0-9]*-[0-9]*.jsonl` 로 좁힌다).

## `data/vworld/` — 브이월드 응답 축적

`tools/vworld_probe.py` 가 쓴다. 사람이 손으로 고치지 않는다.

| 파일 | 성격 |
| :-- | :-- |
| `queue.json` | 태스크 큐. 미해결 항목(Q번호)별 대상 필지·진행 커서·주기·차단 상태 |
| `YYYY-MM-DD.jsonl` | 그 날 받은 응답 원본. 회차당 1파일, append-only |

### `queue.json`

`policy` 가 한 번 실행의 상한이다(`max_tasks_per_run`·`call_budget_per_run`). 태스크는 `cursor` 로 어디까지 받았는지 기억하므로
**며칠에 걸쳐 이어받는다** — 연속 에러 3회면 커서를 남기고 `blocked_until` 을 다음 날로 찍고 조용히 끝낸다(exit 0).

- `cadence` — `once`(끝나면 done) / `weekly` / `monthly`(끝나면 `cursor` 0 으로 되돌리고 `last_cycle` 기록 → 주기 도래 시 재조회)
- `source: listings` — `--build-queue` 가 `data/listings` 최신 스냅샷의 `inside: true` 지번으로 `parcels` 를 채운다. 지오코딩 호출 0회.
  새 지번은 **뒤에 붙인다** — 커서가 가리키는 위치가 밀리면 안 된다
- `params` — 요청에 그대로 실린다. 공시가격 계열은 `stdrYear` 를 반드시 지정한다(안 하면 20년치가 와서 잘린다)

### `YYYY-MM-DD.jsonl`

한 줄 = 필지 1개 조회 결과. `t` 가 종류(`landuse`·`aptprice`·`landprice`·`houseprice`)다.

| 키 | 뜻 |
| :-- | :-- |
| `t` `date` `q` `zone` | 종류 · 조회일(KST) · 미해결 질문 번호 · 구역 slug |
| `jibun` `pnu` | 지번 · PNU 19자리 |
| `n` `total` | 받은 행 수 · 응답의 `totalCount` |
| `trunc` | `n < total` 일 때만 붙는다 — **잘린 회차다. 그대로 집계하면 안 된다** |
| `rows` | 응답 행 원본(중복 키 `pnu`·`ldCode`·`ldCodeNm`·`mnnmSlno` 만 제거) |

**요약해서 쌓지 않는다.** "토허 몇 건"으로 줄이면 나중에 다른 질문(정비구역·용도지역·지구단위)을 물을 때 다시 찔러야 한다.
판정은 읽는 쪽에서 한다 — `python tools/vworld_probe.py --report [zone]` 이 회차별로 집계하고 **회차 간 변화를 짚어 준다**(감시 태스크의 존재 이유).

`n: 0` 은 **"해당 사항 없음"이 아니다.** 일부 PNU 가 빈 응답을 준다(`DECISIONS.md` #25). 판정에서 빼고, 빠졌다는 사실을 적는다.

---

## 왜 DB 가 아닌가

10구역 · 회차당 수백 행 규모에서 DB 가 풀어 줄 문제가 없다. 파일로 두면 비용 0, diff 리뷰 유지,
PR 절차 그대로다. 원본(md)과 축적(jsonl)이 갈라져 있으므로 **축적 쪽만 나중에 DB 로 갈아끼울 수 있다** —
지금 DB 로 가면 원본까지 끌려 들어간다. 전환 트리거는 축적 5,000행 초과 · 쓰기 주체 2개 이상 ·
조인/집계 요구 · 일 1회 이상 갱신 · 구역 30개 초과.
