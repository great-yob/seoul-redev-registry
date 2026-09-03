#!/usr/bin/env bash
# SessionStart 훅 — 다른 기기에서 올린 커밋을 먼저 가져온다.
# 클라우드 세션은 새로 클론되므로 사실상 no-op. 터미널·데스크톱에서 의미가 있다.

set -uo pipefail

cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || exit 0
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

git pull --rebase --autostash -q 2>/dev/null || true

exit 0
