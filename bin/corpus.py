#!/usr/bin/env python3
"""Emit a corpus manifest: what this consumer enumerated, and how.

"State your corpus and how you enumerated it" is easy to write into a pattern and impossible to
check, which makes it advice rather than a rule. Two consumers publishing different rankings of
the same period currently have no way to find out whether they disagree about the *scoring* or
about *what they were looking at* — and those need completely different conversations.

This closes that. For every source the collector enumerates, the manifest publishes:

  * the exact method, as a runnable command — so the enumeration can be repeated;
  * the count;
  * a digest over the sorted item identifiers.

The digest is the part that does the work. Two consumers compare digests: equal means they saw
the same items and any disagreement is about weights; different means they were never looking at
the same corpus, and comparing their conclusions was meaningless. Identifiers are published in
full here too, so a mismatch can be diffed rather than merely detected — but the digest alone is
enough to know whether that diff is worth doing.

It exists because of a specific failure: our collector requested one page of results and never
paged, saw about a tenth of the ecosystem, and produced an entirely plausible ranking. Nothing
about the output looked wrong. A published digest would not have fixed the bug, but it would have
let anyone else notice it without reading our code.

    ./bin/corpus.py           # writes data/corpus.json
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "corpus.json"

# How each source was enumerated, as something a reader can run. Kept beside the identifier
# extractor so the description and the thing described cannot drift apart unnoticed.
SOURCES = {
    "pulls": {
        "description": "Every pull request against the upstream repo, all states.",
        # What the enumeration covered, not what it requested. This said `--limit 300`, and that
        # was both the literal command and a false description of the corpus: the repository had
        # 407 closed pull requests, the call returned exactly 300 of them successfully, and the
        # manifest published the number it asked for as though it were the number it got.
        "method": "gh pr list --repo flop-labs/technocore-chat --state {merged,open,closed}, "
                  "paged to exhaustion; a listing that comes back at exactly its row cap is "
                  "refused rather than published, so a count here is the whole set or there is "
                  "no manifest at all. See bin/fetch.py:gh_list.",
        "identity": lambda row: f"pr#{row['number']}",
    },
    "issues": {
        "description": "Every issue against the upstream repo, all states.",
        "method": "gh issue list --repo flop-labs/technocore-chat --state all, paged to "
                  "exhaustion; see the note on pulls above.",
        "identity": lambda row: f"issue#{row['number']}",
    },
    "artifacts": {
        "description": "Public repositories that reference Technocore, after the README check. "
                       "Search is paginated to exhaustion; see collect.py:search_all.",
        "method": "search/repositories over 4 queries, all pages, then a per-repo reference check",
        "identity": lambda row: row["repo"],
    },
    "proofs": {
        "description": "Contribution proofs found by code search, plus a direct probe of every "
                       "discovered artifact repository for a root contribution-proof.json.",
        "method": "search/code 'technocore-contribution-proof-v1', all pages, unioned with a "
                  "direct fetch per artifact repo",
        "identity": lambda row: f"{row['repo']}/{row['path']}",
    },
}


def digest(identifiers: list[str]) -> str:
    """sha256 over the sorted, newline-joined identifiers.

    Sorted so two consumers that enumerated in different orders still agree; newline-joined with a
    trailing newline so the encoding is unambiguous and reproducible from the published list.
    """
    body = "\n".join(sorted(identifiers)) + "\n"
    return "sha256:" + hashlib.sha256(body.encode()).hexdigest()


def main() -> int:
    sources = {}
    for name, spec in SOURCES.items():
        path = RAW / f"{name}.json"
        if not path.exists():
            continue
        rows = json.loads(path.read_text())
        identifiers = sorted({spec["identity"](row) for row in rows})
        sources[name] = {
            "description": spec["description"],
            "method": spec["method"],
            "count": len(identifiers),
            "digest": digest(identifiers),
            "identifiers": identifiers,
        }

    # What this run could not fetch, published beside what it did. A consumer comparing digests
    # needs to know whether a difference is two people enumerating different worlds or one of
    # them having been rate-limited mid-enumeration, and until now the manifest could not say.
    # An empty list here is a claim: every question we asked got an answer.
    try:
        incidents = json.loads((RAW / "incidents.json").read_text())
    except (OSError, ValueError):
        incidents = {"count": None, "fetches_that_did_not_answer": [],
                     "note": "this collection predates incident recording"}

    manifest = {
        "schema": "corpus-manifest-v1",
        "consumer": "https://github.com/stupeterwilliams-ui/technocore-contributor-index",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "how_to_compare": (
            "Enumerate the same sources yourself, take sha256 of your sorted identifiers joined "
            "by newlines with a trailing newline, and compare digests. Equal digests mean any "
            "disagreement between our rankings is about weights. Different digests mean we were "
            "not looking at the same corpus, and comparing the rankings tells you nothing until "
            "that is resolved. The full identifier lists are published so a mismatch can be "
            "diffed rather than only detected."
        ),
        "fetch_incidents": incidents,
        # Committed, unlike data/raw, so `git log -p data/corpus.json` is the durable record of
        # whether the evidence-cache sweep is draining or stuck without anyone reconstructing it.
        "evidence_cache_backlog": incidents.get("evidence_cache_backlog"),
        "known_incompleteness": [
            "GitHub code search does not index every repository and lags; proof discovery is "
            "best-effort even with the direct per-repo probe layered on top.",
            "GitHub search does not return some items that demonstrably exist — it will not "
            "surface an issue carrying this consumer's own comments — so any search-derived "
            "corpus should be treated as a lower bound.",
            "Repository search is not stable near its 1000-result cap: consecutive runs of the "
            "identical query return slightly different tails. The collector therefore re-probes "
            "every repository the enumeration has previously returned, directly, and drops one "
            "only when that probe answers 404. Anything else it cannot reach is listed under "
            "fetch_incidents and the run is not published at all.",
        ],
        "sources": sources,
    }
    OUT.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}")
    for name, source in sources.items():
        print(f"  {name:10} {source['count']:>5} items  {source['digest'][:23]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
