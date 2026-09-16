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
#   ./bin/refresh.sh                        # collect, score, build, publish if changed
#   ./bin/refresh.sh --dry                  # everything except signing, committing and pushing
#   ./bin/refresh.sh --recheck-negatives    # same, re-asking the whole cached-negative backlog
#
# Options are matched by name and may be given in any order. Anything unrecognised is refused.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE" || exit 1
export UV_CACHE_DIR="$HERE/.uvcache"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
# Options, by name rather than by position. `DRY="${1:-}"` was here, so the dry flag had to be the
# first argument and nothing else could ever be passed — there was no path for
# `--recheck-negatives` to reach the collector at all. Running the collector separately first and
# then refresh.sh is not the same thing: it collects twice, and the second collection is not the
# one that was checked. Two consecutive runs of this pipeline routinely differ, which is the whole
# reason the guard in bin/guard.py exists, so "verify one collection then publish another" gives up
# exactly the property that makes verifying worth doing.
#
# Unknown options are refused rather than ignored. A mistyped `--recheck-negative` that silently
# ran without the recheck would be this repository's signature failure in a new costume.
#
# A plain string, not an array: the shebang resolves to bash 3.2 on macOS, where expanding an empty
# array under `set -u` is an error. These are fixed literals with no spaces, so word splitting on
# expansion is what we want.
DRY=""
COLLECT_ARGS=""
for arg in "$@"; do
  case "$arg" in
    --dry) DRY="--dry" ;;
    --recheck-negatives|--force) COLLECT_ARGS="$COLLECT_ARGS $arg" ;;
    *) echo "refresh.sh: unknown option '$arg'" >&2
       echo "usage: refresh.sh [--dry] [--recheck-negatives] [--force]" >&2
       exit 2 ;;
  esac
done
LOG="$HERE/state/refresh.log"
mkdir -p "$HERE/state"

log() { echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] $*" >> "$LOG"; }

log "=== refresh started ==="

# A non-zero exit here now has two meanings and the log has to say which. Either the collector
# crashed, or it declined to overwrite the last good collection because this run could not see
# the evidence — a rate limit, a reset connection, a TLS failure. The second is a correct outcome
# rather than a fault: the previous ranking stands, nothing is published, and nobody is removed
# from the room's allow-list. What is not acceptable is it happening every hour unnoticed, so the
# incidents are copied into the log where the reason is visible.
# shellcheck disable=SC2086 -- deliberate word splitting; see the option parsing above.
if ! uv run ./bin/collect.py $COLLECT_ARGS >>"$LOG" 2>&1; then
  if [[ -f data/raw/incidents.json ]]; then
    log "COLLECT REJECTED — this run saw less than the last one; previous data kept, nothing published"
    python3 -c "
import json
d = json.load(open('data/raw/incidents.json'))
for row in d.get('fetches_that_did_not_answer', [])[:20]:
    print('    could not fetch:', row['what'], '::', row['detail'][:120])
" >>"$LOG" 2>&1
  else
    log "COLLECT FAILED"
  fi
  exit 1
fi

# Absorbed contributions. Its own step because it reads closure comments one pull request at a
# time; the disk cache means only newly-closed ones cost a call. A failure here is not fatal —
# the previous absorbed.json stays and the ranking is merely as stale as it was before.
if ! uv run ./bin/absorbed.py >>"$LOG" 2>&1; then
  log "ABSORBED FAILED (continuing with the previous absorbed.json)"
fi

if ! uv run ./bin/score.py >>"$LOG" 2>&1; then
  log "SCORE FAILED"
  exit 1
fi

if ! uv run ./bin/corpus.py >>"$LOG" 2>&1; then
  log "CORPUS FAILED"
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

# One line a run about the evidence-cache sweep, so a stalled backlog is visible in the log rather
# than only in a file somebody has to think to open.
# A quoted heredoc, not `python3 -c "..."`. The first version used double quotes and the f-string
# inside it closed the shell's string, so python received truncated source and raised a SyntaxError
# every run. There is no `set -e` here, so it logged a traceback and carried on publishing — which
# made the one line whose whole job is to make a stalled backlog visible the least visible thing in
# the run. Every other inline python in this file is already a quoted heredoc for this reason.
python3 - >>"$LOG" 2>&1 <<'PY'
import json
try:
    b = json.load(open("data/raw/incidents.json")).get("evidence_cache_backlog") or {}
except (OSError, ValueError):
    b = {}
if b.get("remaining_before"):
    due = "  STALENESS REVIEW DUE" if b.get("staleness_review_due") else ""
    print("    evidence-cache sweep: asked {}, {} left, {}{}".format(
        b["asked_this_run"], b["remaining"], b["state"], due))
PY

if [[ "$DRY" == "--dry" ]]; then
  log "dry run; not publishing"
  exit 0
fi

# Do not publish a document that asserts numbers nobody has accounted for. METHODOLOGY.md is the
# page a reader is invited to check the board against, and it carried "all 114 well-formed proofs
# verify" for four days while the board published 117 — in the section correcting a previous false
# claim about the same 112 people. See bin/check_prose.py for the three ways a number is allowed
# to be there.
if ! uv run ./bin/check_prose.py >>"$LOG" 2>&1; then
  log "NOT PUBLISHING — METHODOLOGY.md asserts numbers that are not accounted for; see above"
  exit 1
fi

# Do not publish output that the committed code cannot produce.
#
# METHODOLOGY.md says, in bold, "the two programs that produce it are in this repository... If you
# cannot reproduce these numbers independently, the ranking is worth nothing." That claim was false
# from 2026-09-12 to 2026-09-16. The proof-canonicalisation fix lived only in the working tree,
# `git add -A data/ docs/` commits results and never the programs, and so every hourly run
# published numbers that a fresh clone could not reproduce — a clone would still have reported that
# 112 named people's proofs do not verify. Nobody noticed for four days because nothing complained.
#
# This complains. It refuses rather than committing bin/ for you, deliberately: an unattended timer
# that commits source code commits whatever half-finished edit happens to be open at the time, and
# on 2026-09-16 at 01:08 UTC this timer began a run against a pipeline that was mid-rewrite. The
# safe asymmetry is that a stale board is recoverable in one commit and a published-but-
# unreproducible board is a broken promise that stands until someone checks.
# Only things a program actually reads. `targets.json` was in this list and nothing read it: a
# 114-entry proof snapshot from 2026-09-12, never tracked, superseded by data/raw/proofs.json. The
# gate was therefore blocking every publish until somebody committed a dead file, and committing it
# would have made a frozen one-off snapshot look like a pipeline input with this guard vouching for
# it. A gate that names things nothing reads teaches you to satisfy it rather than to believe it.
PIPELINE="$(git status --porcelain -- bin/ pyproject.toml uv.lock)"
if [[ -n "$PIPELINE" ]]; then
  log "NOT PUBLISHING — the pipeline differs from HEAD, so this output is not reproducible from"
  log "  committed code and METHODOLOGY.md's reproducibility claim would be false. Commit these:"
  while IFS= read -r line; do log "    $line"; done <<< "$PIPELINE"
  log "  data/ and docs/ have been rebuilt locally and left in place; nothing was signed or pushed."
  exit 1
fi

# Sign here and nowhere earlier. Signing straight after the build attested bytes that the
# no-change branch above then discarded with `git checkout -- docs/`, leaving a SIGNATURE.json
# describing a build that never shipped — which is how a wrong signature reached the site once.
# A signature belongs to the commit it travels in, so it is produced immediately before the add.
if ! uv run --project "$HOME/Projects/technocore-sdk" ./bin/sign_release.py >>"$LOG" 2>&1; then
  log "SIGN FAILED (publishing unsigned rather than stale)"
  rm -f docs/SIGNATURE.json
fi

git add -A data/ docs/ >/dev/null 2>&1
# Author explicitly, and with OUR noreply address. `stu@users.noreply.github.com` was here for
# 108 commits and it is not ours — GitHub maps `<login>@users.noreply.github.com` to the account
# with that login, and `stu` is a real person in Melbourne who registered in 2008 and has never
# touched this repository. Every hourly refresh was publicly credited to them.
git -c user.name="stupeterwilliams-ui" \
    -c user.email="257534982+stupeterwilliams-ui@users.noreply.github.com" \
    commit -q -m "data: refresh leaderboard ($RANKED ranked)" >>"$LOG" 2>&1

if # Verify the signature against what the commit actually holds, before pushing. The working tree
# is not the artifact — the commit is, and the two disagreed once already. A signature describing
# bytes nobody can fetch is worse than none: it invites a reader to conclude we tampered rather
# than that we mis-ordered two steps.
if [[ -f docs/SIGNATURE.json ]] && ! python3 ./bin/verify_release.py --from-commit >>"$LOG" 2>&1; then
  log "SIGNATURE/COMMIT MISMATCH — not pushing"
  exit 1
fi

git push -q origin main >>"$LOG" 2>&1; then
  log "PUBLISHED"
else
  log "PUSH FAILED"
  exit 1
fi
