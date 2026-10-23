"""매물 수집 PC 실행기 — 윈도우 작업 스케줄러가 매주 목요일 09:00 KST 에 돌린다.

    python tools/listings_local.py --install   # 전용 클론을 만들고 작업 스케줄러에 등록(한 번). 64비트 Python + playwright 로 실행할 것
    python tools/listings_local.py             # 지금 한 번 돈다(전용 클론에서)

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
import hashlib
import os
import shutil
import subprocess
import sys

HOME = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'seoul-redev-listings')
CLONE = os.path.join(HOME, 'repo')
LOG_DIR = os.path.join(HOME, 'logs')
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


def run(cmd, cwd=CLONE, check=True):
    """출력은 로그 파일로. 실패면 CalledProcessError."""
    log('$ ' + ' '.join(cmd))
    r = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                       encoding='utf-8', errors='replace', creationflags=NO_WINDOW)
    if r.stdout.strip():
        log(r.stdout.rstrip())
    if check and r.returncode:
        raise subprocess.CalledProcessError(r.returncode, cmd)
    return r


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


def install():
    try:
        import playwright  # noqa: F401
    except ImportError:
        sys.exit(f'이 Python({sys.executable})에 playwright 가 없다 — 64비트 Python 에서 `python -m pip install requests playwright` · '
                 '`python -m playwright install chromium` 후 같은 Python 으로 --install 한다')
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


def collect():
    py = console_python()
    summary = os.path.join(LOG_DIR, f'{today}.summary.md')
    r = run([py, 'tools/collect_listings.py', '--summary', summary], check=False)
    if r.returncode:
        raise RuntimeError(f'collect_listings.py exit {r.returncode}')
    run([shutil.which('node') or 'node', 'site/build.mjs'])
    if not run(['git', 'status', '--porcelain', '--', *PATHS]).stdout.strip():
        log('매물 파일·회차 스냅샷 모두 변화 없음 — 커밋하지 않는다')
        return
    run(['git', 'add', '--', *PATHS])
    run(['git', 'commit', '-q', '-F', summary])
    if run(['git', 'push', '-q', 'origin', 'HEAD:main'], check=False).returncode:
        run(['git', 'pull', '-q', '--rebase', 'origin', 'main'])   # 매물 경로는 이 실행만 쓴다 — 충돌 없이 얹힌다
        run(['git', 'push', '-q', 'origin', 'HEAD:main'])
    log('push 완료 — Pages 는 pages.yml 이 regions/** 변경으로 배포한다')


def main():
    global _log
    if '--install' in sys.argv:
        return install()
    os.makedirs(LOG_DIR, exist_ok=True)
    _log = open(os.path.join(LOG_DIR, f'{today}.log'), 'a', encoding='utf-8')
    log(f'== 매물 수집 시작 ({sys.executable})')
    try:
        if '--no-update' not in sys.argv:
            me = os.path.abspath(__file__)
            before = hashlib.sha256(open(me, 'rb').read()).hexdigest()
            sync_clone(origin_url())
            if hashlib.sha256(open(me, 'rb').read()).hexdigest() != before:
                log('실행기가 바뀌었다 — 새 판으로 다시 띄운다')
                _log.close()
                sys.exit(subprocess.run([sys.executable, me, '--no-update'], cwd=CLONE, creationflags=NO_WINDOW).returncode)
        collect()
    except Exception as e:
        log(f'!! 실패: {e}')
        report_failure(str(e))
        sys.exit(1)
    log('== 끝')


if __name__ == '__main__':
    main()
