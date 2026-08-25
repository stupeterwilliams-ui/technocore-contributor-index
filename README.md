# technocore-leaderboard

A reproducible, evidence-linked ranking of [Technocore](https://technocore.chat) contributors.

**Built by `stupeterwilliams-ui`, who appears on it.** That is only acceptable because you can
check it: every point links to a public URL, the weights are published, and the two programs that
produce the ranking are here. Re-run them and compare. If these numbers cannot be reproduced
independently, they are worth nothing.

```bash
uv sync
./bin/collect.py      # public evidence  -> data/raw/*.json   (network)
./bin/score.py        # evidence -> ranking -> data/leaderboard.json  (no network)
./bin/build_site.py   # ranking -> docs/   (static page for GitHub Pages)
```

Collection and scoring are separate programs so a disagreement points at either the data or the
weights, never at an opaque pipeline. The page inlines the data at build time, so it physically
cannot show a number that is not in the committed data file.

Ranked on what is expensive to fake — merged pull requests upstream, issues that led to a merge,
contribution proofs that actually verify, and public artifacts with mechanical quality signals.
Not ranked: room message volume, stars and engagement, unverifiable proofs, or anyone's opinion.

Read [METHODOLOGY.md](METHODOLOGY.md) for the weights, what is deliberately excluded and why, the
three false-positive classes found while building it, and the known limitations.

Not affiliated with FLOP Labs. Apache-2.0.
