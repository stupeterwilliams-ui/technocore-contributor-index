#!/usr/bin/env python3
"""Refuse to overwrite a good collection with a worse one.

A collector that cannot reach GitHub produces a smaller, entirely well-formed set of facts, and
every program downstream of it treats that set as the truth. The ranking gets worse, the board
publishes it, and `room-sync.sh` derives the gated room's allow-list from it and removes people.
Two hours later the fetch succeeds and they come back. Observed, in the room alerts: dejagold123
ejected at rank 51, re-admitted at 50, ejected again at 52, inside about ninety minutes, without
having done or undone anything.

The gate is deliberately not "did the count go down". Counts are a bad proxy in both directions:
on 2026-09-15 at 22:53 UTC a run lost an entire search page to a connection reset and the artifact
count moved by *one*, from 1076 to 1075, while 65 candidate repositories vanished from the
enumeration and five people fell off the board. The same run collected zero absorbed contributions
instead of fifteen, costing five real people five points each.

What the gate asks instead is: **did anything disappear that this run cannot account for?**

An identifier that was in the last accepted collection and is not in this one is one of two
things. Either the collector looked and established that it is gone — the repository 404s, the
proof file 404s — which is a finding and is fine. Or it is missing because a fetch did not answer,
which is not a finding about the world at all. Only the second kind blocks the run.

That framing is what lets the thresholds be zero rather than invented. Measured over the 185
consecutive run-to-run comparisons published in this repository's own `data/corpus.json` history:

    issues      lost zero identifiers in 185 of 185 comparisons
    pulls       lost zero in 164 of 185; a pull request number cannot stop existing
    proofs      lost zero in 148 of 185, at most 3
    artifacts   lost zero in only 53 of 185, at most 11

Artifacts churn because GitHub search does not return the same set twice near its result cap, so
`collect.py` re-probes anything search dropped rather than believing it. After that re-probe, a
disappearance means the repository really is gone, and zero is the right tolerance for every
source. No magic number appears anywhere in this file, and that is on purpose: a tolerance picked
to make the numbers stable is a way of dropping evidence quietly, which is the thing being fixed.
"""

from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"


class Rejected(Exception):
    """This collection is not fit to replace the one on disk."""


def previous(name: str) -> list[dict] | None:
    """The last accepted collection. None means there has never been one. Anything else raises.

    These two used to be the same answer, and it disarmed the guard completely. A missing file is
    a first run and there is genuinely nothing to compare against. A file that will not parse is a
    different fact — something went wrong — and returning None for it made `disappeared()` return
    an empty set, which passes every check unconditionally. A guard against absence being read as
    fact must not itself be switchable off by an absence it cannot read.

    That state was reachable rather than theoretical: `write()` was a plain `write_text`, so a
    crash or a full disk mid-write left a truncated JSON file exactly here. It is an atomic
    replace now, so this should be unreachable — which is the reason to refuse rather than guess
    when it happens anyway.
    """
    path = RAW / f"{name}.json"
    if not path.exists():
        return None
    try:
        rows = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise Rejected(
            f"{name}: {path.relative_to(ROOT)} exists but cannot be read ({exc}). That is not the "
            f"same as there being no previous collection, and treating it as one would let this "
            f"run overwrite the board with no comparison made at all"
        ) from exc
    if not isinstance(rows, list):
        raise Rejected(
            f"{name}: {path.relative_to(ROOT)} parsed but is {type(rows).__name__}, not a list of "
            f"records, so nothing can be compared against it"
        )
    return rows


def disappeared(name: str, rows: list[dict], identity) -> set[str]:
    """Identifiers present in the last accepted collection and absent from this one."""
    before = previous(name)
    if before is None:
        return set()
    return {identity(r) for r in before} - {identity(r) for r in rows}


def check(name: str, rows: list[dict], identity, incidents,
          explained: set[str] | None = None, force: bool = False) -> None:
    """Raise Rejected unless this collection may overwrite the one on disk.

    `explained` is the set of identifiers this run positively established are gone — a repository
    that answered 404, a proof file that answered 404. Those are findings and do not block.
    Anything else that vanished did so for a reason this run cannot name, which is exactly the
    condition that ejected real people from a gated room.
    """
    explained = explained or set()
    lost = disappeared(name, rows, identity) - explained

    # An incident on its own does not reject the run, and getting that wrong the other way would
    # have been the worse bug. A repository that answers 403 every single hour — deleted owner,
    # blocked content, anything sticky — would make every run fail forever and freeze the board
    # permanently, which is a silent failure of a grander kind. So the rule is about loss, not
    # about noise: a fetch that failed for something we never had costs this run a little recall
    # and is retried in an hour, while a fetch that failed for something we *did* have is how
    # people get ejected from a room. Both are published in data/raw/incidents.json either way.
    if incidents:
        print(f"  ! {len(incidents)} fetch(es) did not answer; see data/raw/incidents.json")
    if not lost:
        return

    shown = ", ".join(sorted(lost)[:8])
    more = f", +{len(lost) - 8} more" if len(lost) > 8 else ""
    message = (f"{name}: {len(lost)} disappeared with no finding to explain it: {shown}{more}"
               + (f" ({len(incidents)} fetch(es) did not answer this run)" if incidents else ""))
    if force:
        print(f"  ! FORCED past the guard — {message}")
        return
    raise Rejected(message)


def explain(verdict: Rejected) -> str:
    return (
        f"REJECTED — {verdict}\n"
        "  The previous collection is still on disk and is still what the board publishes.\n"
        "  Nothing was scored, nothing was published, and nobody was removed from the room's\n"
        "  allow-list. This is the correct outcome for a run that could not see the evidence:\n"
        "  a ranking built from what a failed fetch returned is not a worse ranking, it is a\n"
        "  ranking of a different and smaller world.\n"
        "  Re-run when the API is answering. Pass --force to overwrite anyway."
    )
