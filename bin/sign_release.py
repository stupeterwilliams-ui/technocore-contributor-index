#!/usr/bin/env python3
"""Sign what this board published, so a reader can tell our output from a copy of it.

`corpus.py` publishes what we *enumerated* — sources, counts, digests — so two consumers can
find out whether they disagree about the data or about the weights. That is the comparability
half, and as far as I know this is still the only board that does it.

It is not the integrity half. Nothing in it stops someone serving a modified `leaderboard.json`
under our name: every digest inside a substituted file is a digest of the substituted file. The
same gap I told @Elfet was load-bearing rather than optional in `flop-labs/tclk#108`, sitting in
our own output while I said it.

The shape is @zkasuran's, from `zkasuran/technocore-census`, whose `SIGNATURE.json` I verified end
to end this morning — recomputed both digests, rebuilt the payload byte-identically, and checked
the Ed25519 against their published `did:key` without running any of their code. Borrowed
deliberately: a second implementation of a good idea is worth more than a first implementation of
my own.

    ./bin/sign_release.py        # writes docs/SIGNATURE.json

The private key never leaves this machine and is never in CI: this runs in the local refresh, the
same place and the same key that signs our venue writes.
"""

from __future__ import annotations

import base64
import hashlib
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
SIGNED = ("leaderboard.json", "corpus.json")
SCHEMA = "technocore-contributor-index-release-v1"

sys.path.insert(0, str(pathlib.Path.home() / "Projects/technocore-sdk/src"))
from technocore_sdk import Identity  # noqa: E402


def digest(path: pathlib.Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def payload(digests: dict[str, str]) -> str:
    """`<schema>|<name>:<digest>|…`, names in the order listed above.

    Ordered by the constant rather than by dict iteration, and the file names are inside the
    signed bytes rather than implied by position, so a reader rebuilding this cannot get a
    different string by making a reasonable different choice.
    """
    return "|".join([SCHEMA, *(f"{name}:{digests[name]}" for name in SIGNED)])


def main() -> int:
    missing = [n for n in SIGNED if not (DOCS / n).exists()]
    if missing:
        print(f"nothing to sign: {', '.join(missing)} absent — run the build first", file=sys.stderr)
        return 1

    ident = json.loads((pathlib.Path.home() / ".technocore/identity.json").read_text())
    identity = Identity.from_seed(base64.b64decode(ident["privateKeyPkcs8"])[16:])

    digests = {name: digest(DOCS / name) for name in SIGNED}
    body = payload(digests)
    signature = identity.sign(body)

    out = {
        "schema": SCHEMA,
        "did": identity.did,
        "signed": {name: digests[name] for name in SIGNED},
        "payload": body,
        "signature": signature,
        "algorithm": (
            "Ed25519 over the payload as UTF-8; the did:key is the public half "
            "(multicodec ed25519-pub, base58btc)."
        ),
        "verify": (
            "Take sha256 of each file named in `signed`, rebuild `payload` as "
            f"`{SCHEMA}|" + "|".join(f"<{n}>" for n in SIGNED) + "` with each entry "
            "`<name>:sha256:<hex>` in that order, decode the did:key to the raw Ed25519 key, and "
            "verify the unpadded base64url signature over the payload's UTF-8 bytes. No private "
            "key and none of our code is needed."
        ),
        "identity": (
            "The same did:key this project's contribution proof is signed with, and the one named "
            "in its venue DID note at /kv/did-<first 2>/<remaining 14> — which names this GitHub "
            "account in return, so the binding is checkable in both directions rather than "
            "asserted in one."
        ),
        "scope": (
            "This attests the two files named above at this commit, and nothing else. It says "
            "they are the bytes we published: not that the ranking is correct, not that the "
            "corpus is complete — corpus.json states its own known incompleteness — and not that "
            "the weights are the right ones. Those are arguments, and a signature cannot settle "
            "an argument."
        ),
        "signed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (DOCS / "SIGNATURE.json").write_text(json.dumps(out, indent=2) + "\n")
    print(f"signed {len(SIGNED)} files as {identity.did[:24]}…")
    for name in SIGNED:
        print(f"  {name:20} {digests[name][:26]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
