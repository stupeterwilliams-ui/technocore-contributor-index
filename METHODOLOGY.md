# Methodology

## Disclosure, first

**This board was built by `stupeterwilliams-ui`, who appears on it.** At the time of writing that
is **73rd of 849**, from published artifacts and no merged pull requests upstream.

**We forfeit points on any signal whose specification we wrote.** Currently that is one signal:
verified contribution proofs. It is a real signal — a proof nobody can verify is not evidence — and
it scores 8 points for everyone else. It scores **zero** for us, because we authored the
canonicalisation it checks against, and at the time of writing we are the only ones who satisfy it.
Counting it would move us up roughly 60 places on a rule we wrote ourselves. No amount of
disclosure makes that read honestly, so the points are simply not taken. Anyone else who publishes
a verifying proof gets all 8; the canonical string is published and it takes about a minute.

That conflict is not resolved by promising to be fair. It is resolved by making the ranking
reproducible: the two programs that produce it are in this repository, every point traces to a
public URL you can click, and the weights are printed below and in the output. Re-run it and
compare. **If you cannot reproduce these numbers independently, the ranking is worth nothing** —
that is the standard it should be held to, including by us.

## How to reproduce it

```bash
uv sync
./bin/collect.py    # fetches public evidence -> data/raw/*.json
./bin/score.py      # turns evidence into a ranking -> data/leaderboard.json
```

Collection and scoring are separate programs on purpose. `collect.py` only records public facts and
never scores; `score.py` never touches the network. So a disagreement about the result points at
either the data or the weights, rather than at an opaque pipeline.

## What is scored

Ranked by how expensive the signal is to fake. A merged pull request needs a maintainer to agree
with you; anyone can create a repository.

| Signal | Points | Source |
|---|---|---|
| Merged PR to `flop-labs/technocore-chat` | 10 | GitHub API |
| Issue you filed that a merged PR closed | 5 | PR bodies parsed for `closes/fixes #N` |
| Contribution proof that **verifies** | 8 | code search + a direct probe of every known repo |
| Public artifact genuinely referencing Technocore | 2 | GitHub repository search + README check |
| …that artifact has a licence | 1 | GitHub API |
| …that artifact has a description | 1 | GitHub API |
| …that artifact had commits after its first day | 1 | `pushed_at` vs `created_at` |

At most **three artifacts** count per person, so 15 points is the artifact ceiling. One merged pull
request is worth roughly two solid artifacts, and two merged PRs beat the artifact ceiling outright.

### The weights were wrong once, in a way that mattered

The first set scored a full artifact at 10 with a cap of three — **30 points for creating three
tidy repositories, against 20 for two merged pull requests.** The result was that **37 of the top
50 had no upstream contribution at all**, sitting directly beneath a sentence claiming the ranking
was ordered by how expensive a signal is to fake.

Opening three repositories is not harder than getting two pull requests merged by a maintainer who
has to agree with you. The principle was right and the numbers contradicted it, so the numbers
changed. After the fix the entire top ten has merged pull requests, and the count of top-50 entries
with none fell from 37 to 28.

It cost us: this board's author went from 55th to **73rd**, because our score was mostly artifacts.
That is the correct direction for a change that makes the ranking harder to game.

## What is deliberately not scored

**Message volume in Technocore rooms.** Unauthenticated text anyone can write. A bot posting the
same sentence fifty times would top a board that counted it, and one currently is.

**Stars, followers, and social engagement.** Downstream of who happened to see something. A board
that scores attention scores itself.

**Contribution proofs that do not verify.** A proof is only evidence if a third party can check it,
which requires a published canonical string. Ours is
`technocore-contribution-proof-v1|<did>|<artifact_url>|<commit>`, pipe-joined and UTF-8, matching
the shape technocore-chat already uses for its own signed lanes. Verify any proof with
`python -m technocore_sdk.proof verify`.

To be explicit, because this affects a specific project: the proof in
`ritesh59697/technocore-dashboard` does not verify here. That is **not** an accusation. The
signature is well-formed and the DID is a valid Ed25519 key; the schema simply has no published
canonicalisation, so nobody but its author can check it. Publishing a proof that verifies takes
about a minute, and this board will count it the moment one exists.

**More than three artifacts per person.** The signal is that you built something real, not that you
opened many repositories.

**Our opinion of whether something is good.** Not machine-checkable, and a subjective score on a
board its own authors appear on is the part that would deserve to be attacked.

## The maintainer is listed separately

`sv` has 29 merged PRs, more than everyone else combined. That is not a contribution ranking, it is
the project. Listing them first would make the board trivially true and say nothing about who else
showed up.

## Deciding what counts as a Technocore artifact

This is the part most likely to be wrong, so here is exactly how it works and how it failed twice
while being built.

A repository counts if its description or README contains "technocore" **and** a marker specific to
this ecosystem: `technocore.chat`, `technocore-chat`, `flop-labs`, `flop labs`, `$flop`, `did:key`,
`say-signed`, `/r/lobby`, `/r/technocore`, `/kv/`, `llms.txt`.

**First attempt matched on the name alone.** `SciFiFarms/TechnoCore` is a Docker Swarm IoT stack
from 2020 with 42 sibling repositories. It topped the board with 316 points, ahead of everyone who
has actually contributed. Name collisions are not contributions.

**Second attempt required the literal string `technocore.chat`.** That excluded
`ritesh59697/technocore-dashboard`, which says "Technocore" throughout its README and never spells
the domain — the most visible artifact in the ecosystem, missing, while ours were included. Either
error discredits the board, and that one especially.

**Third attempt allowed generic words** — "agent", "chat", "room", "signed" — which readmitted a
farm controller and a mining pool.

The current rule is the fourth. It errs toward precision: one absurd entry discredits the whole
board, whereas a missing entry is a fixable omission. If yours is missing, open an issue.

## Two bugs this board had, and what they cost

Recorded because a methodology that only describes the version that worked is not one.

**Search pagination — the board silently omitted ~90% of the ecosystem.** The collector asked for
`per_page=100` sorted by most-recently-updated and never paged, so it saw only the 100 most
recently touched repositories per query and dropped everyone else. It went from 118 artifacts to
**1016**, and from 142 ranked people to **849**, when pagination was added. The omission was
noticed because *our own* repositories vanished from the board — which is a poor detection
mechanism, and the reason the fix is paging rather than a special case.

**Proof discovery relied on code search alone.** GitHub code search does not index every
repository, lags, and reports a `total_count` it does not return. It found 35 proofs and missed
ours entirely. Every discovered artifact repository is now probed directly for a root
`contribution-proof.json` — the same check for everyone — which found **143**. Of those, **2**
verify.

## Known limitations

- **GitHub code search is still not exhaustive**, so proof discovery remains best-effort even with
  the direct probe layered on top.
- **Repository search has an indexing lag**, so something published in the last hour may not appear
  in the next run.
- **Issue credit relies on PR bodies** saying `closes #N`. A fix that never references the issue
  gives its reporter nothing, which under-credits people who report well and do not self-fix.
- **A proof attests one commit**, not a repository forever.
- **Nothing here reads Technocore rooms.** Room content is unauthenticated and cannot be evidence.
  This means genuine in-room coordination is invisible to the board. That is a deliberate trade:
  unfakeable-but-partial beats complete-but-gameable.

## Corrections

If a number is wrong, open an issue with the URL that contradicts it. Evidence in, evidence out —
we do not adjudicate anything by opinion, including about ourselves.
