#!/bin/sh
# 导出 mem0 记忆并推送到 git 仓库。
# 仓库地址、身份、令牌全部来自环境变量或文件，不写死在脚本里。
set -e
BASE="${MEM0_HOME:-$HOME/.dsh-mem0}"
PY="${MEM0_PYTHON:-$BASE/.venv/bin/python}"
TOKEN_FILE="${MEM0_TOKEN_FILE:-$BASE/secret/git-token}"
REMOTE="${MEM0_REMOTE:-}"

[ -n "$REMOTE" ] || { echo "MEM0_REMOTE 未设置（例如 git@github.com:you/memory.git）"; exit 1; }
[ -f "$TOKEN_FILE" ] || { echo "缺少令牌文件 $TOKEN_FILE"; exit 1; }

"$PY" "$BASE/export_mem.py" >> "$BASE/sync.log" 2>&1
cd "$BASE/repo"
T=$(cat "$TOKEN_FILE")
git remote set-url origin "$(printf '%s' "$REMOTE" | sed "s#https://#https://x-access-token:${T}@#")"
git add -A
if git diff --cached --quiet; then
  echo "$(date '+%F %T') 无变化" >> "$BASE/sync.log"
else
  git -c user.name="${GIT_NAME:-dsh-mem0}" -c user.email="${GIT_EMAIL:-dsh-mem0@users.noreply.github.com}" \
    commit -q -m "sync: $(date '+%F %T')" >> "$BASE/sync.log" 2>&1
  git push -q origin HEAD >> "$BASE/sync.log" 2>&1
  echo "$(date '+%F %T') 已推送" >> "$BASE/sync.log"
fi
