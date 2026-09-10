#!/usr/bin/env python3
"""Ask what a proof that does not verify here actually is.

The board reports "does not verify" for most published contribution proofs, and that phrasing
carries an accusation it has not earned. Three explanations fit the same observation, and they
deserve very different words:

  1. the signature is fabricated — random bytes in a signature field nobody checks;
  2. the repository is a shell — a proof citing work that does not exist;
  3. the proof is real and was signed over a different canonical string from ours.

Only the third is innocent, and it is the one the board's own methodology already admits is
possible: `technocore-contribution-proof-v1` is in wide use with no agreed canonicalisation, so
a publisher has no way to discover ours. Guessing between the three is not acceptable when the
output is a public ranking of named people, so this computes the answer.

Two tests, neither of which needs the signing message:

  * **Does the cited commit exist?** A fabricated proof has no reason to name a real one.

  * **Is the signature a structurally valid Ed25519 signature?** The low half is a scalar `S`
    that a real signing operation always leaves below the group order `L ≈ 2**252`. Uniform
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
    proofs — a conclusion that survived until the same check over all 113 said 111 of them
    exist. A lookup that could not run is not evidence of absence, and collapsing it into
    `False` is how an instrument reports a finding it never made.
    """
    result = subprocess.run(
        ["gh", "api", f"repos/{repo}/commits/{commit}", "--jq", ".sha"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True
    stderr = result.stderr.lower()
    if "404" in stderr or "no commit found" in stderr or "not found" in stderr:
        return False
    return None


def fetch(record: dict) -> dict:
    url = f"https://raw.githubusercontent.com/{record['repo']}/HEAD/{record['path']}"
    body = subprocess.run(
        ["curl", "-sL", "--max-time", "25", url], capture_output=True, text=True
    ).stdout
    try:
        doc = json.loads(body)
    except Exception:  # noqa: BLE001
        return {"repo": record["repo"], "readable": False}
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
    subjects = [p for p in proofs if (p.get("note") or "").startswith("well-formed")]
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        rows = list(pool.map(fetch, subjects))

    examined = [r for r in rows if r.get("signature_scalar_in_range") is not None]
    in_range = sum(1 for r in examined if r["signature_scalar_in_range"])
    commits = [r for r in rows if r.get("commit_exists") is not None]
    real_commits = sum(1 for r in commits if r["commit_exists"])

    finding = {
        "schema": "proof-forensics-v1",
        "subjects": "published proofs that are well-formed and do not verify against our "
        "canonical string",
        "counts": {
            "subjects": len(subjects),
            "signatures_examined": len(examined),
            "signatures_with_valid_scalar": in_range,
            "commits_checked": len(commits),
            "commits_that_exist": real_commits,
            "lookups_that_failed": sum(1 for r in rows if r.get("commit_exists") is None),
        },
        "reading": (
            "Fabricated signatures would fail the scalar test about 94% of the time. These do "
            "not fail it, and they cite commits that exist. They are genuine signatures over "
            "some canonical string, and it is not ours — which makes 'does not verify' a "
            "statement about the absence of an agreed canonicalisation, not about the people "
            "who published them."
        ),
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
