#!/usr/bin/env python3
"""Check docs/SIGNATURE.json against the bytes it claims to describe.

Two modes, and the difference is the point:

  --from-commit   digests taken from `git show HEAD:docs/…`
  (default)       digests taken from the working tree

The working tree is not the artifact. A reader fetches what the commit published, and those two
disagreed once: the signer ran before the publish decision, the no-change branch restored `docs/`
from HEAD, and the surviving SIGNATURE.json described a build that never shipped. This is the
check that would have caught it, so it runs before every push.

It verifies the digests. It does not verify the Ed25519 signature, deliberately — that is the
reader's job and needs no key, and a self-check that re-runs our own signing code proves the code
is self-consistent rather than that the artifact is sound.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"


def from_commit(name: str) -> bytes:
    return subprocess.run(["git", "show", f"HEAD:docs/{name}"], cwd=ROOT,
                          capture_output=True, check=True).stdout


def main() -> int:
    use_commit = "--from-commit" in sys.argv
    raw = from_commit("SIGNATURE.json") if use_commit else (DOCS / "SIGNATURE.json").read_bytes()
    sig = json.loads(raw)

    problems = []
    for name, published in sig["signed"].items():
        blob = from_commit(name) if use_commit else (DOCS / name).read_bytes()
        actual = "sha256:" + hashlib.sha256(blob).hexdigest()
        if actual != published:
            problems.append(f"{name}: signature says {published[:22]}…, "
                            f"{'commit' if use_commit else 'tree'} holds {actual[:22]}…")

    rebuilt = "|".join([sig["schema"], *(f"{n}:{d}" for n, d in sig["signed"].items())])
    if rebuilt != sig["payload"]:
        problems.append("payload does not rebuild from the digests it lists")

    where = "commit" if use_commit else "working tree"
    if problems:
        print(f"SIGNATURE DOES NOT MATCH THE {where.upper()}: " + "; ".join(problems))
        return 1
    print(f"signature matches the {where}: " + ", ".join(sig["signed"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
