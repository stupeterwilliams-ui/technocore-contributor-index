#!/usr/bin/env python3
"""Find contributions that landed under someone else's pull request.

The board scores merged pull requests. In this ecosystem a great many real contributions do not
merge: two people fix the same bug within hours, a maintainer keeps one and closes the other with
an explicit note naming the survivor and what to salvage from the loser. The work landed. The
author scores nothing.

METHODOLOGY.md called this a known flaw with "no mechanical detector I trust", and left it. That
was wrong, and the thing that changed my mind was it happening to us: two comments of ours led to
seven pull requests being closed in one sitting, and this board scored that at zero.

The detector is the closure itself. A maintainer who closes a duplicate almost always *names the
survivor* in the closing comment — "duplicate of #86", "closing in favour of #40", or a table of
closed/kept pairs. That is machine-readable text we were reading as absence.

Two guards, because a detector that over-credits is worse than one that under-credits:

  * the survivor must have MERGED. A pointer from one closed pull request to another that also
    never landed is a chain where nothing reached the tree, and crediting it would award points
    for work that does not exist in the repository.
  * self-references are dropped. "#653 -> #653" is a regex artefact, not a contribution.

Measured when written, against the two upstream repositories: 38 of 145 closed-unmerged pull
requests on technocore-chat name a survivor, and 16 of 23 on tclk. Of the tclk set, 8 have a
survivor that merged.

    ./bin/absorbed.py            # writes data/raw/absorbed.json
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

import guard
from fetch import MISSING, Incidents, Unavailable, gh_json

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "raw" / "absorbed.json"
CACHE = ROOT / "data" / "absorbed-cache.json"
REPOS = ("flop-labs/technocore-chat", "flop-labs/tclk")

# Ordered by how explicit the statement is. The table row is last because it is the loosest.
PATTERNS = (
    re.compile(r"(?:duplicate|dupe)\s+of\s+#(\d+)", re.I),
    re.compile(r"clos(?:ing|ed)\s+in\s+favou?r\s+of\s+#(\d+)", re.I),
    re.compile(r"superse\w+\s+by\s+#(\d+)", re.I),
    re.compile(r"\bkeep(?:ing)?\s+#(\d+)", re.I),
    re.compile(r"\|\s*#(\d+)\s*\|\s*#(\d+)\s*\|"),
)


INCIDENTS = Incidents()


def gh(*args: str, what: str | None = None):
    """Parsed JSON, `MISSING` for a definite 404, or `Unavailable` raised.

    The version this replaces returned None for a timeout, a rate limit, a 404 and an empty body
    alike, and both callers below then wrote that None into a permanent on-disk cache as though
    it meant "no survivor was named here". On 2026-09-15 at 22:53 UTC the pull request listing
    failed and this program reported `0 absorbed contributions` where every neighbouring run
    reported 15 — five points each, silently deleted from fifteen people, one of whom
    (@Sertug17) fell from rank 6 to rank 16 and back again an hour later.
    """
    return gh_json(*args, what=what)


def survivor_named_in(body: str, closed_number: int) -> int | None:
    for rx in PATTERNS:
        m = rx.search(body or "")
        if not m:
            continue
        # A table row gives (closed, kept); every other pattern gives the survivor alone.
        n = int(m.group(2) if rx.groups == 2 else m.group(1))
        if n != closed_number:
            return n
    return None


def load_cache() -> dict:
    try:
        return json.loads(CACHE.read_text())
    except (OSError, ValueError):
        return {}


def main() -> int:
    try:
        return _run()
    except Unavailable as exc:
        # A listing we could not read is not a repository with nothing in it. Exit non-zero and
        # leave the previous absorbed.json alone; refresh.sh already treats that as non-fatal and
        # carries on with a ranking that is as stale as it was, rather than one that is wrong.
        INCIDENTS.record(exc)
        print(guard.explain(guard.Rejected(f"{exc.what} never answered")), file=sys.stderr)
        return 1


def _run() -> int:
    cache = load_cache()
    found, checked = [], 0

    for repo in REPOS:
        # No `or []`. An empty listing here does not mean nothing was absorbed, it means we did
        # not get to look, and the two differ by fifteen awards.
        prs = gh("pr", "list", "--repo", repo, "--state", "closed", "--limit", "300",
                 "--json", "number,title,author,mergedAt,url", what=f"closed prs {repo}")
        if prs is MISSING or prs is None:
            raise Unavailable(f"closed prs {repo}", "no listing returned")
        unmerged = [p for p in prs if not p.get("mergedAt") and p.get("author")]
        merged_numbers = {p["number"] for p in prs if p.get("mergedAt")}

        for pr in unmerged:
            key = f"{repo}#{pr['number']}"
            if key in cache:
                survivor = cache[key]
            else:
                checked += 1
                try:
                    comments = gh("api", f"repos/{repo}/issues/{pr['number']}/comments",
                                  "--jq", "[.[].body]", what=f"comments {key}")
                except Unavailable as exc:
                    # Not cached. A closure whose comments we could not read is a question we
                    # have not asked, and caching the non-answer means never asking again.
                    INCIDENTS.record(exc)
                    continue
                if comments is MISSING or comments is None:
                    comments = []
                survivor = None
                for body in comments:
                    survivor = survivor_named_in(body, pr["number"])
                    if survivor:
                        break
                cache[key] = survivor
            if not survivor or survivor not in merged_numbers:
                continue
            found.append({
                "repo": repo,
                "number": pr["number"],
                "author": pr["author"]["login"],
                "title": pr["title"],
                "url": pr["url"],
                "survivor": survivor,
                "survivor_url": f"https://github.com/{repo}/pull/{survivor}",
            })

    # Absorbed awards are five points each and land on people who arrived second on a crowded
    # file — exactly the cohort sitting on the rank-50 line that gates the room. The same guard
    # the collector uses applies here: an award that vanished with nothing to explain it means
    # this run saw less than the last one, and refresh.sh already knows to keep the previous
    # absorbed.json and carry on when this program exits non-zero.
    try:
        guard.check("absorbed", found, lambda r: f"{r['repo']}#{r['number']}", INCIDENTS,
                    force="--force" in sys.argv)
    except guard.Rejected as verdict:
        print(guard.explain(verdict), file=sys.stderr)
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(found, indent=2) + "\n")
    CACHE.write_text(json.dumps(cache, indent=2) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(found)} absorbed contributions "
          f"({checked} closures newly read, {len(cache)} cached)")
    for f in found[:12]:
        print(f"  {f['repo'].split('/')[-1]}#{f['number']:<4} @{f['author']:<20} -> merged #{f['survivor']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
