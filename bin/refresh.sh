#!/usr/bin/env bash
# refresh.sh — collect, score, rebuild the page, publish. Zero model calls.
#
# This is the whole product loop. If it needs a human or a model to run, the board is a snapshot
# someone maintains rather than a live thing, and a stale leaderboard is worse than none because
# it is confidently wrong in public.
#
# Safe to run on a timer: it only pushes when the numbers actually changed, so an hourly run on a
# quiet day produces no commit and no noise.
#
#   ./bin/refresh.sh          # collect, score, build, publish if changed
#   ./bin/refresh.sh --dry    # everything except the push
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE" || exit 1
export UV_CACHE_DIR="$HERE/.uvcache"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
DRY="${1:-}"
LOG="$HERE/state/refresh.log"
mkdir -p "$HERE/state"

log() { echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] $*" >> "$LOG"; }

log "=== refresh started ==="

if ! uv run ./bin/collect.py >>"$LOG" 2>&1; then
  log "COLLECT FAILED"
  exit 1
fi

if ! uv run ./bin/score.py >>"$LOG" 2>&1; then
  log "SCORE FAILED"
  exit 1
fi

if ! uv run ./bin/build_site.py >>"$LOG" 2>&1; then
  log "BUILD FAILED"
  exit 1
fi

# `generated_at` changes on every run, so it is not evidence that anything moved. Compare the
# ranking itself — otherwise a timer would commit an identical board every hour forever.
CHANGED="$(python3 - <<'PY'
import json, pathlib, subprocess
current = json.loads(pathlib.Path("data/leaderboard.json").read_text())
def shape(doc):
    return [(e["login"], e["score"], e["rank"]) for e in doc.get("leaderboard", [])]
previous = subprocess.run(["git", "show", "HEAD:data/leaderboard.json"],
                          capture_output=True, text=True, check=False)
if previous.returncode != 0:
    print("yes"); raise SystemExit(0)
try:
    print("yes" if shape(json.loads(previous.stdout)) != shape(current) else "no")
except ValueError:
    print("yes")
PY
)"

if [[ "$CHANGED" != "yes" ]]; then
  log "no ranking change; nothing published"
  git checkout -- data/leaderboard.json docs/ 2>/dev/null || true
  exit 0
fi

RANKED="$(python3 -c "import json;print(len(json.load(open('data/leaderboard.json'))['leaderboard']))")"
log "ranking changed: $RANKED people"

if [[ "$DRY" == "--dry" ]]; then
  log "dry run; not publishing"
  exit 0
fi

git add -A data/ docs/ >/dev/null 2>&1
git -c user.name="Stu" -c user.email="stu@users.noreply.github.com" \
    commit -q -m "data: refresh leaderboard ($RANKED ranked)" >>"$LOG" 2>&1

if git push -q origin main >>"$LOG" 2>&1; then
  log "PUBLISHED"
else
  log "PUSH FAILED"
  exit 1
fi
