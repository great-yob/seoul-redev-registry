"""매물 수집 PC 실행기 — 윈도우 작업 스케줄러가 매주 목요일 09:00 KST 에 돌린다.

    python tools/listings_local.py --install          # 전용 클론을 만들고 작업 스케줄러에 등록(한 번). 64비트 Python + playwright 로 실행할 것
    python tools/listings_local.py                    # 지금 한 번 돈다(전용 클론에서)
    python tools/listings_local.py --install-manual   # 수동 수집 준비(한 번): 북마클릿 설치 페이지 + 바탕화면 「매물 반영」 바로가기
    python tools/listings_local.py --manual           # 다운로드 폴더의 수동 저장본으로 반영(바로가기가 부른다)

수동 수집 (재개발닷컴이 자동 클라이언트를 막는 동안의 경로, 2026-11-06)
- 사람이 평소 브라우저로 구역 목록 페이지를 연다 — CAPTCHA 가 뜨면 사람이 푼다. 북마클릿 「매물 저장」을 누르면 그 페이지에
  이미 받아져 있는 매물 데이터(플라이트 스크립트)를 `jaegebal-<develop id>-YYYYMMDD-HHMM.txt` 로 내려받고 다음 구역 페이지로 간다.
  북마클릿은 추가 요청을 보내지 않는다 — 한 번 누를 때 사람이 보는 페이지 한 장이다. 마지막 구역이면 알림만 띄운다.
  매물 수(ask_count)보다 적게 담긴 구역은 다음 쪽(?page=N, `…-pN.txt`)을 먼저 연다 — 새 매물이 없으면 다음 구역으로.
  새 탭에서는 북마클릿이 돌지 않아, 첫 구역을 여는 일반 북마크 「매물 시작」을 함께 둔다.
- 바탕화면 「매물 반영」(= --manual)이 다운로드 폴더에서 MANUAL_MAX_AGE_DAYS 안의 저장본을 모아 collect_listings.py --from-dir 로
  반영하고(상세는 브이월드, 재개발닷컴 요청 0건) 자동 회차와 같은 경로로 커밋·push 한다. 결과는 알림창으로 보인다.
  성공하면 쓴 저장본을 다운로드 폴더에서 치우고 LOG_DIR/YYYY-MM-DD.manual/ 에 남긴다. 실패는 이슈를 열지 않는다(사람이 앞에 있다).
- 브이월드 키: 전용 클론에는 .env 가 없다. --install·--install-manual 이 세션 저장소 .env 의 VWORLD_API_KEY 한 줄을
  HOME/.env 로 옮기고, 실행기가 그 값을 수집기 환경변수로 넘긴다.

왜 PC 인가: 재개발닷컴(CloudFront + AWS WAF)이 2026-10-23부터 클라우드 IP(GitHub 러너)를 헤더 없는 403 으로 막는다 —
헤드리스 브라우저로도 토큰이 안 나왔다(run 39869465784). 가정용 IP 의 PC 는 Challenge(202)만 걸리고
collect_listings.py 의 브라우저 토큰 단계로 통과한다. 국토부 비교시세는 그대로 러너(listings.yml)가 돈다.

- 작업 디렉터리는 세션에서 쓰는 저장소가 아니라 전용 클론(CLONE)이다 — 세션의 브랜치·미커밋 변경과 섞이지 않는다.
  매번 origin/main 으로 맞춘 뒤 돌고, 이 파일이 바뀌었으면 새 판으로 다시 띄운다.
- collect_listings.py → node site/build.mjs(파서 규약 검사) → regions/listings·data/listings 만 커밋해 main 에 push.
  push 가 거부되면 rebase 후 1회 재시도. Pages 는 사용자 자격으로 push 한 regions/** 변경이라 pages.yml 이 스스로 돈다.
- 실패하면 GitHub 이슈를 연다(러너 시절 Actions 실패 메일 대신). 회차 로그는 LOG_DIR/YYYY-MM-DD.log.
- PC 가 꺼져 있어 놓친 실행은 다음에 켜질 때 곧바로 돈다(작업 설정 StartWhenAvailable).
"""
import datetime as dt
import glob
import hashlib
import html
import json
import os
import shutil
import subprocess
import sys
import time

HOME = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'seoul-redev-listings')
CLONE = os.path.join(HOME, 'repo')
LOG_DIR = os.path.join(HOME, 'logs')
KEY_FILE = os.path.join(HOME, '.env')          # 전용 클론 밖 — VWORLD_API_KEY 한 줄
MANUAL_HTML = os.path.join(HOME, 'manual.html')   # 북마클릿 설치 페이지
SHORTCUT = '매물 반영.lnk'
MANUAL_MAX_AGE_DAYS = 3                        # 이보다 오래된 저장본은 반영하지 않는다(지난주 것이 섞이지 않게)
TASK = 'seoul-redev-listings'
PATHS = ['regions/listings', 'data/listings']   # 이 실행이 커밋하는 경로. 다른 것은 건드리지 않는다
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)   # pythonw 로 돌 때 자식 콘솔 창이 뜨지 않게
KST = dt.timezone(dt.timedelta(hours=9))

today = dt.datetime.now(KST).strftime('%Y-%m-%d')
_log = None


def log(msg):
    line = f'{dt.datetime.now(KST):%H:%M:%S} {msg}'
    if _log:
        _log.write(line + '\n')
        _log.flush()
    if sys.stdout:   # pythonw 면 None
        print(line)


def run(cmd, cwd=CLONE, check=True, env=None):
    """출력은 줄마다 시각을 붙여 로그 파일로 흘린다(차단이 몇 분째에 왔는지 보이게). 실패면 CalledProcessError."""
    log('$ ' + ' '.join(c if len(c) < 120 else c[:60] + '…' for c in cmd))
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         encoding='utf-8', errors='replace', creationflags=NO_WINDOW,
                         env={**os.environ, 'PYTHONIOENCODING': 'utf-8', **(env or {})})
    out = []
    for line in p.stdout:
        out.append(line)
        log('  ' + line.rstrip())
    p.wait()
    if check and p.returncode:
        raise subprocess.CalledProcessError(p.returncode, cmd)
    return subprocess.CompletedProcess(cmd, p.returncode, ''.join(out))


def console_python():
    """작업은 pythonw 로 뜨지만 수집기는 python.exe 로 돌린다(같은 설치본 — playwright 가 깔린 쪽)."""
    p = os.path.join(os.path.dirname(sys.executable), 'python.exe')
    return p if os.path.exists(p) else sys.executable


def sync_clone(origin):
    if not os.path.isdir(os.path.join(CLONE, '.git')):
        os.makedirs(HOME, exist_ok=True)
        run(['git', 'clone', '-q', origin, CLONE], cwd=HOME)
    run(['git', 'fetch', '-q', 'origin', 'main'])
    run(['git', 'checkout', '-q', '-f', '-B', 'main', 'origin/main'])   # 전용 클론이다 — 지난 회차의 실패 잔여물을 버린다
    run(['git', 'clean', '-q', '-fd', '--', *PATHS])


def origin_url():
    """이 파일이 든 저장소(세션 저장소든 전용 클론이든)의 origin."""
    here = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    return subprocess.run(['git', 'remote', 'get-url', 'origin'], cwd=here, capture_output=True, text=True,
                          check=True, creationflags=NO_WINDOW).stdout.strip()


def read_key(path):
    """.env 형식 파일의 VWORLD_API_KEY 값. 없으면 None. 값은 출력하지 않는다."""
    if not os.path.exists(path):
        return None
    for ln in open(path, encoding='utf-8'):
        name, _, val = ln.strip().partition('=')
        if name.strip() == 'VWORLD_API_KEY' and val.strip():
            return val.strip().strip('"').strip("'")
    return None


def ensure_key():
    """전용 클론에는 .env 가 없다 — 세션 저장소 .env 의 브이월드 키를 HOME/.env 로 옮긴다(한 번)."""
    if read_key(KEY_FILE):
        return
    src = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '.env'))
    k = read_key(src)
    if not k:
        sys.exit(f'VWORLD_API_KEY 를 찾지 못했다 — {src} 또는 {KEY_FILE} 에 `VWORLD_API_KEY=…` 한 줄을 둔다')
    os.makedirs(HOME, exist_ok=True)
    with open(KEY_FILE, 'w', encoding='utf-8') as f:
        f.write(f'VWORLD_API_KEY={k}\n')
    print(f'브이월드 키 → {KEY_FILE}')


def key_env():
    k = read_key(KEY_FILE)
    return {'VWORLD_API_KEY': k} if k else {}


def install():
    try:
        import playwright  # noqa: F401
    except ImportError:
        sys.exit(f'이 Python({sys.executable})에 playwright 가 없다 — 64비트 Python 에서 `python -m pip install requests playwright` · '
                 '`python -m playwright install chromium` 후 같은 Python 으로 --install 한다')
    ensure_key()
    sync_clone(origin_url())
    pyw = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
    script = os.path.join(CLONE, 'tools', 'listings_local.py')
    ps = f"""
$a = New-ScheduledTaskAction -Execute '{pyw}' -Argument '"{script}"' -WorkingDirectory '{CLONE}'
$t = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Thursday -At 9am
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName '{TASK}' -Action $a -Trigger $t -Settings $s -Description '재개발닷컴 매물 수집 (seoul-redev-registry tools/listings_local.py)' -Force | Out-Null
(Get-ScheduledTask -TaskName '{TASK}' | Get-ScheduledTaskInfo).NextRunTime
"""
    r = subprocess.run(['powershell', '-NoProfile', '-Command', ps], capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr)
    print(f'등록: 작업 {TASK} · 매주 목 09:00 · 다음 실행 {r.stdout.strip()}\n클론 {CLONE}\n로그 {LOG_DIR}')


def report_failure(why):
    """GitHub 이슈로 알린다 — PC 실행은 Actions 실패 메일이 없다. 로그 끝부분을 싣는다(재개발닷컴 URL·구역명뿐이라 공개 저장소에 올려도 된다)."""
    gh = shutil.which('gh')
    if not gh:
        log('gh 없음 — 이슈를 열지 못했다')
        return
    _log.flush()
    tail = open(_log.name, encoding='utf-8', errors='replace').read().splitlines()[-40:]
    body = f'PC 작업 스케줄러 매물 수집({TASK})이 실패했다: {why}\n\n로그 끝 40줄 (`{_log.name}`):\n\n```\n' + '\n'.join(tail) + '\n```\n'
    run([gh, 'issue', 'create', '--title', f'매물 수집 실패 {today} (PC)', '--body', body], check=False)


def collect(manual_dir=None):
    """수집 → 빌드 검사 → 매물 경로만 커밋·push. (요약 파일, 커밋했나) 를 돌려준다. manual_dir 이면 저장본으로(재개발닷컴 요청 0건)."""
    py = console_python()
    summary = os.path.join(LOG_DIR, f'{today}.summary.md')
    cmd = [py, 'tools/collect_listings.py', '--summary', summary] + (['--from-dir', manual_dir] if manual_dir else [])
    r = run(cmd, check=False, env=key_env())
    if r.returncode:
        raise RuntimeError(f'collect_listings.py exit {r.returncode}')
    run([shutil.which('node') or 'node', 'site/build.mjs'])
    if not run(['git', 'status', '--porcelain', '--', *PATHS]).stdout.strip():
        log('매물 파일·회차 스냅샷 모두 변화 없음 — 커밋하지 않는다')
        return summary, False
    run(['git', 'add', '--', *PATHS])
    run(['git', 'commit', '-q', '-F', summary])
    if run(['git', 'push', '-q', 'origin', 'HEAD:main'], check=False).returncode:
        run(['git', 'pull', '-q', '--rebase', 'origin', 'main'])   # 매물 경로는 이 실행만 쓴다 — 충돌 없이 얹힌다
        run(['git', 'push', '-q', 'origin', 'HEAD:main'])
    log('push 완료 — Pages 는 pages.yml 이 regions/** 변경으로 배포한다')
    return summary, True


# ---------------------------------------------------------------- 수동 수집
def downloads_dir():
    """브라우저 기본 다운로드 폴더(사용자 셸 폴더 Downloads). 옮겨 두었으면 그 자리."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders') as k:
            return os.path.expandvars(winreg.QueryValueEx(k, '{374DE290-123F-4565-9164-39C4925E467B}')[0])
    except OSError:
        return os.path.join(os.path.expanduser('~'), 'Downloads')


def manual_files():
    cutoff = time.time() - MANUAL_MAX_AGE_DAYS * 86400
    return sorted(p for p in glob.glob(os.path.join(downloads_dir(), 'jaegebal-*.txt')) if os.path.getmtime(p) >= cutoff)


def notify(text, ok=True):
    """바로가기(pythonw)로 뜨면 콘솔이 없다 — 결과를 알림창으로 보인다."""
    log(('   알림: ' if ok else '   알림(실패): ') + text.replace('\n', ' / '))
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, '매물 반영', (0x40 if ok else 0x30) | 0x10000 | 0x40000)
    except Exception:
        pass


def run_manual():
    files = manual_files()
    if not files:
        raise RuntimeError(f'다운로드 폴더({downloads_dir()})에 최근 {MANUAL_MAX_AGE_DAYS}일 안의 저장본(jaegebal-*.txt)이 없다 — '
                           '북마크 「매물 저장」으로 먼저 저장한다')
    stage = os.path.join(LOG_DIR, f'{today}.manual')
    os.makedirs(stage, exist_ok=True)
    for p in files:
        shutil.copy2(p, stage)
    log(f'저장본 {len(files)}개 → {stage}')
    summary, pushed = collect(stage)
    for p in files:   # 반영이 끝난 것만 치운다 — 실패면 다운로드 폴더에 그대로 두어 다시 누를 수 있게
        try:
            os.remove(p)
        except OSError:
            pass
    lines = open(summary, encoding='utf-8').read().splitlines()
    zones = [ln[2:] for ln in lines if ln.startswith('- ') and ' → ' in ln and '건 (중복 제거' in ln]
    head = lines[0].split(' — ', 1)[-1] if lines else ''
    notify(('반영·push 완료' if pushed else '변화 없음(커밋 안 함)') + f' — {head}\n\n' + '\n'.join(zones)
           + '\n\n페이지는 1~2분 뒤 갱신됩니다.')


BOOKMARKLET = r"""
(()=>{const Z=__ZONES__,H='https://jaegebal.com/develops/',go=(i,n)=>{location.href=H+Z[i][0]+'/asks'+(n>1?'?page='+n:'')};
const m=location.href.match(/^https:\/\/jaegebal\.com\/develops\/(\d+)\/asks\/?(?:\?([^\x23]*))?(?:\x23.*)?$/);
if(!m){if(confirm('재개발닷컴 매물 저장을 시작합니다 — 1/'+Z.length+' '+Z[0][1]))go(0,1);return}
const i=Z.findIndex(z=>z[0]===m[1]);
if(i<0){alert('비교 구역 페이지가 아닙니다 — 다른 페이지에서 누르면 첫 구역부터 시작합니다');return}
const pg=+((/(?:^|&)page=(\d+)/.exec(m[2]||'')||[])[1]||1);
let f='scripts',t=[...document.scripts].map(s=>s.textContent).filter(x=>x.indexOf('self.__next_f')>=0).join('\n');
const has=x=>x.indexOf('develop_id')>=0||x.indexOf('ask_count')>=0;
if(!has(t)&&self.__next_f){f='next_f';t=self.__next_f.map(x=>typeof x[1]=='string'?x[1]:'').join('')}
const ids=[...new Set([...t.matchAll(/develop_id\\?":(\d+),\\?"develop_title/g)].map(x=>x[1]))];
if(!has(t)||(ids.length&&ids.indexOf(m[1])<0)){alert('이 페이지의 매물 데이터가 아직 없습니다 — 새로고침(F5) 뒤 다시 누르세요');return}
const mine=[...new Set([...t.matchAll(/\\?"id\\?":(\d+),\\?"code\\?":\\?"[^"\\]*\\?",\\?"develop_id\\?":(\d+),/g)].filter(x=>x[2]===m[1]).map(x=>x[1]))];
const cnt=+((/\\?"ask_count\\?":(\d+)/.exec(t)||[])[1]||0);
let seen=[];try{seen=pg>1?JSON.parse(sessionStorage.getItem('jgb'+m[1])||'[]'):[]}catch(e){}
const fresh=mine.filter(x=>seen.indexOf(x)<0);seen=seen.concat(fresh);try{sessionStorage.setItem('jgb'+m[1],JSON.stringify(seen))}catch(e){}
const nxt=()=>{if(pg<5&&fresh.length&&cnt>seen.length)go(i,pg+1);else if(i+1<Z.length)go(i+1,1);else alert('완료 '+Z.length+'/'+Z.length+' — 바탕화면 「매물 반영」을 더블클릭하세요')};
if(pg>1&&!fresh.length){nxt();return}
const d=new Date(),p=n=>String(n).padStart(2,'0'),s=''+d.getFullYear()+p(d.getMonth()+1)+p(d.getDate())+'-'+p(d.getHours())+p(d.getMinutes());
const a=document.createElement('a');
a.href=URL.createObjectURL(new Blob(['<!-- fmt='+f+' url='+location.href+' saved='+s+' -->\n'+t],{type:'text/plain;charset=utf-8'}));
a.download='jaegebal-'+m[1]+'-'+s+(pg>1?'-p'+pg:'')+'.txt';document.body.appendChild(a);a.click();a.remove();
setTimeout(nxt,800)})()
"""

PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>매물 수동 저장</title>
<style>
body{{font:16px/1.6 system-ui,-apple-system,"Malgun Gothic",sans-serif;max-width:640px;margin:32px auto;padding:0 16px;color:#1d1d1f;background:#fff}}
h1{{font-size:22px;margin:0 0 4px}} .sub{{color:#666;margin:0 0 24px}}
.bm{{display:inline-block;padding:10px 18px;border-radius:8px;background:#2f6fe4;color:#fff;font-weight:600;text-decoration:none;cursor:grab}}
ol{{padding-left:22px}} li{{margin:10px 0}} .note{{color:#666;font-size:14px;border-top:1px solid #ddd;margin-top:28px;padding-top:12px}}
code{{background:#f2f2f2;padding:1px 5px;border-radius:4px}}
</style></head><body>
<h1>매물 수동 저장</h1>
<p class="sub">재개발닷컴이 자동 수집을 막는 동안 쓰는 경로입니다. 일주일에 한 번, 약 2분.</p>
<p><a class="bm" href="{href}">매물 저장</a> <a class="bm" href="{start}">매물 시작</a> ← 두 버튼을 <b>북마크바로 끌어다 놓으세요</b> (북마크바가 안 보이면 <code>Ctrl+Shift+B</code>). 처음 한 번만.</p>
<ol>
<li>북마크 <b>「매물 시작」</b>을 누릅니다 → 첫 구역({first}) 매물 페이지가 열립니다. 새 탭에서는 「매물 저장」이 동작하지 않아 시작용 링크를 따로 둡니다.</li>
<li>페이지가 다 뜨면 <b>「매물 저장」</b>을 누릅니다 → 파일이 내려받아지고 다음으로 넘어갑니다. 매물이 2쪽 이상인 구역은 다음 쪽이 먼저 열립니다(그 쪽도 한 번 더 누름). 마지막 구역에서 「완료」 알림이 뜹니다.</li>
<li>바탕화면 <b>「매물 반영」</b>을 더블클릭합니다 → 반영·push 결과가 알림창으로 뜹니다. 페이지는 1~2분 뒤 갱신됩니다.</li>
</ol>
<p class="note">
· 사람 확인(CAPTCHA)이 뜨면 직접 풀고, 매물 목록이 보인 뒤 누르세요. 「데이터가 아직 없습니다」가 뜨면 새로고침(F5) 뒤 다시 누르면 됩니다.<br>
· 저장 파일은 브라우저 기본 다운로드 폴더에 <code>jaegebal-…txt</code>로 쌓입니다. 「다운로드 전 저장 위치 묻기」는 꺼 두세요.
최근 {max_age}일 안의 파일만 반영되고, 반영이 끝난 파일은 다운로드 폴더에서 치워집니다.<br>
· 중간에 그만둬도 됩니다 — 저장한 구역만 갱신됩니다. 북마크는 누를 때 보고 있는 페이지 한 장만 저장하고, 따로 요청을 보내지 않습니다.<br>
· PC 브라우저(크롬·엣지) 전용입니다. 구역이 바뀌면 <code>python tools/listings_local.py --install-manual</code>을 다시 돌려 북마크를 새로 끌어다 놓습니다.
</p>
</body></html>
"""


def bookmarklet(zones):
    """한 줄 javascript: URL. `#`·`%` 가 있으면 브라우저가 조각·퍼센트 인코딩으로 읽어 코드가 깨진다 — 코드에 두지 않는다."""
    js = BOOKMARKLET.replace('__ZONES__', json.dumps(zones, ensure_ascii=False))
    js = ''.join(ln.strip() for ln in js.strip().splitlines())
    assert '#' not in js and '%' not in js, '북마클릿에 # 또는 % — URL 로 읽히며 깨진다'
    return 'javascript:' + js


def install_manual():
    """북마클릿 설치 페이지(HOME/manual.html)와 바탕화면 「매물 반영」 바로가기를 만든다. 구역이 바뀌면 다시 돌린다."""
    ensure_key()
    sync_clone(origin_url())   # 바로가기는 전용 클론의 실행기를 가리킨다
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from collect_listings import ZONES
    zones = [[Z['did'], Z['title']] for Z in ZONES]
    os.makedirs(HOME, exist_ok=True)
    with open(MANUAL_HTML, 'w', encoding='utf-8') as f:
        f.write(PAGE.format(href=html.escape(bookmarklet(zones), quote=True), start=f'https://jaegebal.com/develops/{zones[0][0]}/asks',
                            first=zones[0][1], max_age=MANUAL_MAX_AGE_DAYS))
    pyw = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
    script = os.path.join(CLONE, 'tools', 'listings_local.py')
    ps = f"""
$d = [Environment]::GetFolderPath('Desktop')
$s = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d '{SHORTCUT}'))
$s.TargetPath = '{pyw}'
$s.Arguments = '"{script}" --manual'
$s.WorkingDirectory = '{CLONE}'
$s.Description = 'jaegebal manual listings -> seoul-redev-registry'
$s.Save()
"""
    r = subprocess.run(['powershell', '-NoProfile', '-Command', ps], capture_output=True, text=True, errors='replace')
    if r.returncode:
        sys.exit(r.stderr)
    print(f'바로가기: 바탕화면 「{SHORTCUT[:-4]}」 → {pyw} "{script}" --manual\n설치 페이지: {MANUAL_HTML}')
    os.startfile(MANUAL_HTML)


def main():
    global _log
    if '--install' in sys.argv:
        return install()
    if '--install-manual' in sys.argv:
        return install_manual()
    manual = '--manual' in sys.argv
    os.makedirs(LOG_DIR, exist_ok=True)
    _log = open(os.path.join(LOG_DIR, f'{today}.log'), 'a', encoding='utf-8')
    log(f'== 매물 수집 시작{" (수동 저장본)" if manual else ""} ({sys.executable})')
    try:
        if '--no-update' not in sys.argv:
            me = os.path.abspath(__file__)
            before = hashlib.sha256(open(me, 'rb').read()).hexdigest()
            sync_clone(origin_url())
            if hashlib.sha256(open(me, 'rb').read()).hexdigest() != before:
                log('실행기가 바뀌었다 — 새 판으로 다시 띄운다')
                _log.close()
                sys.exit(subprocess.run([sys.executable, me, '--no-update', *[a for a in sys.argv[1:] if a != '--no-update']],
                                        cwd=CLONE, creationflags=NO_WINDOW).returncode)
        if manual:
            run_manual()
        else:
            collect()
    except Exception as e:
        log(f'!! 실패: {e}')
        if manual:
            notify(f'반영 실패: {e}\n\n로그: {_log.name}', ok=False)
        else:
            report_failure(str(e))
        sys.exit(1)
    log('== 끝')


if __name__ == '__main__':
    main()
