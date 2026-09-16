#!/usr/bin/env python3
"""Ask what a proof that verifies under no known canonicalisation actually is.

**This program's original question has been answered, and the answer was not the one it assumed.**
It was written when the board checked exactly one canonicalisation — the pipe-joined string
technocore-sdk published — and reported the other 112 published proofs as "does not verify". It
concluded, correctly on the evidence it had, that those were genuine signatures over some other
canonical string. It then said that string could not be found. It could: it is
`did-starter-json-v1`, defined by `contribution_payload` in `technocore_agent.py` of
`zunmax/technocore-did-starter`, found by reading that source and reported by @githubbjj on
flop-labs/technocore-chat#828. 112 of 114 published proofs verify under it. The collector now
checks both rules, and those proofs score.

What survives is the instrument, pointed at what is left. A proof matching neither rule is still
one of three things, and they deserve very different words:

  1. the signature is fabricated — random bytes in a signature field nobody checks;
  2. the repository is a shell — a proof citing work that does not exist;
  3. the proof is real and signed under a third canonicalisation nobody here has found yet.

The third is the one this program got wrong before by assuming it was unfindable, so it is worth
saying plainly: a negative result here means "we did not find a rule that matches", never "this
person fabricated something".

Two tests, neither of which needs the signing message:

  * **Does the cited commit exist?** A fabricated proof has no reason to name a real one.

  * **Is the signature a structurally valid Ed25519 signature?** The low half is a scalar `S`
    that a real signing operation always leaves below the group order `L ~ 2**252`. Uniform
    random bytes land below `L` about one time in sixteen. So a population of fabricated
    signatures shows roughly 94% failures on this test and a population of genuine ones shows
    none — and it separates them without knowing what was signed. It cannot prove any single
    signature is genuine; across a hundred it is decisive.

    ./bin/proof_forensics.py        # writes data/proof-forensics.json
"""

from __future__ import annotations

import base64
import concurrent.futures
import json
import pathlib
import subprocess

from fetch import MISSING, Unavailable, http_get

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROOFS = ROOT / "data" / "raw" / "proofs.json"
OUT = ROOT / "data" / "proof-forensics.json"

# The order of the Ed25519 prime-order subgroup. Every signature a correct implementation emits
# has S < L; uniform random bytes do so with probability L / 2**256, about 6.25%.
L = 2**252 + 27742317777372353535851937790883648493


def scalar_in_range(signature: str) -> bool | None:
    """True if the signature's S is a valid scalar, None if it is not 64 decodable bytes."""
    try:
        raw = base64.b64decode(signature + "=" * (-len(signature) % 4), altchars=b"-_")
    except Exception:  # noqa: BLE001 - undecodable is its own answer, not a crash
        return None
    if len(raw) != 64:
        return None
    return int.from_bytes(raw[32:], "little") < L


def commit_exists(repo: str, commit: str) -> bool | None:
    """True/False from the API, None when the lookup itself failed.

    The three-way return is the point. An earlier version of this check ran four repositories
    through a shell loop, got a failed lookup for every one, and read that as four fabricated
    proofs — a conclusion that survived until the same check over the whole population said
    almost all of them exist. A lookup that could not run is not evidence of absence, and
    collapsing it into `False` is how an instrument reports a finding it never made.
    """
    result = subprocess.run(
        ["gh", "api", f"repos/{repo}/commits/{commit}", "--jq", ".sha"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return True
    stderr = result.stderr.lower()
    if "404" in stderr or "no commit found" in stderr or "not found" in stderr:
        return False
    return None


def fetch(record: dict) -> dict:
    """One proof, read and examined. `readable` is three-valued for the same reason
    `commit_exists` is: a fetch that did not happen is not a file that cannot be read.

    This function still conflated them after `commit_exists` had been fixed — an unreachable host
    and a corrupt file both came back as `readable: False`, and this program's published output is
    an argument about whether named people fabricated signatures. Getting that distinction wrong
    is precisely the error the docstring above describes, one layer down.
    """
    url = f"https://raw.githubusercontent.com/{record['repo']}/HEAD/{record['path']}"
    try:
        fetched = http_get(url, what=f"forensics {record['repo']}/{record['path']}")
    except Unavailable as exc:
        return {"repo": record["repo"], "readable": None, "note": exc.detail[:160]}
    if fetched is MISSING:
        return {"repo": record["repo"], "readable": False,
                "note": "the host answered: no file at this path"}
    _, body = fetched
    try:
        doc = json.loads(body)
    except Exception:  # noqa: BLE001
        return {"repo": record["repo"], "readable": False,
                "note": "fetched but not parseable as JSON"}
    commit = doc.get("commit")
    return {
        "repo": record["repo"],
        "readable": True,
        "did": doc.get("did"),
        "commit": commit,
        "commit_exists": commit_exists(record["repo"], commit) if commit else None,
        "signature_scalar_in_range": scalar_in_range(doc.get("signature") or ""),
    }


def main() -> int:
    proofs = json.loads(PROOFS.read_text())
    # Selected on the recorded fields, not on the wording of a note. The note text changed when
    # the second canonicalisation was added, and a subject filter that reads prose silently
    # selects nothing the moment someone rewrites a sentence.
    subjects = [p for p in proofs if p.get("parsed") and not p.get("verifies")]
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        rows = list(pool.map(fetch, subjects))

    examined = [r for r in rows if r.get("signature_scalar_in_range") is not None]
    in_range = sum(1 for r in examined if r["signature_scalar_in_range"])
    commits = [r for r in rows if r.get("commit_exists") is not None]
    real_commits = sum(1 for r in commits if r["commit_exists"])

    finding = {
        "schema": "proof-forensics-v1",
        "subjects": "published proofs that are well-formed and verify under neither known "
        "canonicalisation (technocore-sdk-pipe-v1, did-starter-json-v1)",
        "counts": {
            "subjects": len(subjects),
            "signatures_examined": len(examined),
            "signatures_with_valid_scalar": in_range,
            "commits_checked": len(commits),
            "commits_that_exist": real_commits,
            "lookups_that_failed": sum(1 for r in rows if r.get("commit_exists") is None),
            # Published so a reader can see how much of this finding rests on questions that
            # were actually answered. A subject whose proof could not be fetched is not a
            # subject that failed anything.
            "proofs_that_could_not_be_fetched": sum(1 for r in rows if r.get("readable") is None),
        },
        "reading": (
            "Fabricated signatures would fail the scalar test about 94% of the time. A subject "
            "that passes it and cites a commit that exists is a genuine signature over a "
            "canonicalisation this board has not found — which is a statement about what we "
            "know, not about the person who published it. That is not a hypothetical: this "
            "program's earlier run said exactly that about 112 proofs, and the rule they use was "
            "then found in zunmax/technocore-did-starter and reported by @githubbjj on "
            "flop-labs/technocore-chat#828. Those now verify and score. Whatever is left here "
            "should be read the same way — as an unfinished search."
        ),
        "canonicalisations_checked_before_this_ran": [
            "technocore-sdk-pipe-v1", "did-starter-json-v1",
        ],
        "rows": sorted(rows, key=lambda r: r["repo"]),
    }
    OUT.write_text(json.dumps(finding, indent=2) + "\n")
    counts = finding["counts"]
    print(f"wrote {OUT.relative_to(ROOT)}")
    print(f"  subjects                     {counts['subjects']}")
    print(f"  signatures with valid scalar {in_range}/{len(examined)}")
    print(f"  commits that exist           {real_commits}/{len(commits)}")
    print(f"  lookups that failed          {counts['lookups_that_failed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
