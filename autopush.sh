#!/usr/bin/env bash
# Stop 훅 — 턴이 끝날 때 미커밋 변경을 자동 커밋·푸시한다.
# 실패해도 세션을 막지 않는다. 항상 exit 0.

set -uo pipefail

cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || exit 0
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

# 변경 없으면 조용히 종료 (Claude가 이미 규약대로 커밋한 정상 경로)
if [ -z "$(git status --porcelain)" ]; then
  # 커밋은 됐지만 아직 안 올라간 게 있으면 푸시만
  branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)" || exit 0
  if [ -n "$(git log "origin/${branch}..${branch}" --oneline 2>/dev/null)" ]; then
    git push -q origin "$branch" 2>/dev/null || true
  fi
  exit 0
fi

git add -A 2>/dev/null || exit 0

git commit -q -F - <<'MSG' 2>/dev/null || exit 0
auto: 미커밋 변경 자동 반영

Stop 훅이 저장했습니다. Claude가 커밋 규약대로 직접 커밋하지 않은
변경이라는 뜻이므로, 내용을 반드시 확인하십시오.

    git show --stat HEAD
    git diff HEAD~1
MSG

branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)" || exit 0
git push -q origin "$branch" 2>/dev/null || true

exit 0
