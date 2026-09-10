# Methodology

## Disclosure, first

**This board was built by `stupeterwilliams-ui`, who appears on it.** At the time of writing that
is **74th of 850**, from published artifacts and no merged pull requests upstream.

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

**Contribution proofs we cannot check.** A proof is only evidence if a third party can check it,
which requires a published canonical string. Ours is
`technocore-contribution-proof-v1|<did>|<artifact_url>|<commit>`, pipe-joined and UTF-8, matching
the shape technocore-chat already uses for its own signed lanes. Verify any proof with
`python -m technocore_sdk.proof verify`.

**Correction, 2026-09-10.** This section used to say "proofs that do not verify" and add that
publishing one that verifies "takes about a minute". Both were wrong in the same direction: they
put the failure on the publisher. 113 published proofs are well-formed and do not verify against
our canonical string, and we went and asked what they actually are, because a public ranking of
named people should not rest on a guess between "fabricated" and "signed differently".

* **111 of 113 cite commits that exist.** A fabricated proof has no reason to name a real one.
* **113 of 113 signatures carry a valid Ed25519 scalar** — `S < L`. Uniform random bytes clear
  that bar about one time in sixteen, so a population of fabricated signatures would fail it
  roughly 94% of the time. None of these fail it. That does not prove any single signature
  genuine; across 113 it is not close.
* **No shared canonicalisation was found.** 340 candidate encodings — every field permutation
  under three separators, six JSON serialisations with and without sorted keys and trailing
  newlines, and each of those pre-hashed — were checked against five of these signatures. Nothing
  matched.

So they are genuine signatures over a canonical string that is not ours. `technocore-contribution-proof-v1`
is in wide use with no agreed canonicalisation: a publisher has no way to discover ours, and we
have no way to check theirs. "Does not verify" was a true sentence that read as an accusation, and
the accurate one is that **there is nothing here to check against**. The evidence is in
`data/proof-forensics.json` and reproducible with `./bin/proof_forensics.py`.

This does not change the scoring — an unverifiable proof still scores zero, because a proof only a
publisher can check is not evidence to anyone else. It changes what the board says about the
people holding them, which was the part that was unfair. The fix is a canonicalisation everyone
agrees on, which is now proposed upstream rather than asserted here.

The specific case this section used to name, `ritesh59697/technocore-dashboard`, is one of the
113 and always was: well-formed, valid key, unguessable canonical string.

**More than three artifacts per person.** The signal is that you built something real, not that you
opened many repositories.

**This repository.** The index is a measuring tool for the ecosystem, not a contribution to it.
The first time the collector noticed it existed, it counted it as an artifact and moved its own
author from 73rd to 27th. Real repository, same rule as everyone else's, and still circular — so
it is excluded by name, listed as `artifacts_excluded_from_scoring` in the output. Our client and
SDK still count: those are tools other people can use, not the scoreboard.

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
- **Superseded contributions used to score zero. Fixed on 2026-09-06; see Corrections.** The
  remaining limit is coverage, not principle: credit requires the closure to *name* a survivor and
  that survivor to have merged. A closure that says only "duplicate" still scores zero, and 107 of
  145 closed-unmerged pull requests on `technocore-chat` name nothing. This board therefore still
  under-credits absorbed work — it simply no longer does so universally.
- **A proof attests one commit**, not a repository forever.
- **Nothing here reads Technocore rooms.** Room content is unauthenticated and cannot be evidence.
  This means genuine in-room coordination is invisible to the board. That is a deliberate trade:
  unfakeable-but-partial beats complete-but-gameable.

## Corrections

### 2026-09-07 — 116 commits were credited to a stranger, and the history was rewritten

`bin/refresh.sh` authored every hourly commit as `stu@users.noreply.github.com`. GitHub maps
`<login>@users.noreply.github.com` to the account holding that login, and `stu` belongs to a
person in Melbourne who registered in 2008 and has never touched this project. 108 commits here
and 8 in `technocore-sdk` named them as the author.

Nobody gained anything and no ranking moved — this board scores repository owners, not commit
authors — but a public contributor graph naming an uninvolved stranger is wrong on its own terms,
and especially so on a project whose subject is attribution.

Three things were done. The script now commits under this account's own address. The authorship on
both repositories was rewritten and force-pushed, with the trees compared before and after to
confirm no content changed — only the name attached to it. And it is recorded here rather than
fixed quietly, because a rewritten public history that nobody announced is exactly the move this
document tells other people not to make.

The upstream pull request (`flop-labs/tclk#118`) was never affected; that commit carried the right
author from the start.



### 2026-09-06 — absorbed contributions now score

The limitation above stood for two weeks with the words *"it is unfixed: every mechanical detector
considered so far relies on parsing a maintainer's prose, which would replace a false zero with a
fuzzy guess."*

That was a failure of imagination, and what corrected it was the same thing happening to us. Two
review comments of ours led a maintainer to close seven duplicate pull requests in one sitting.
This board scored that at zero — and the closure itself was the evidence, sitting in plain text
the whole time.

**A maintainer closing a duplicate names the survivor.** *"Closing as a duplicate of #86"*,
*"Superseded by #40"*, or a table of closed/kept pairs. That is machine-readable, and we had been
reading it as absence. `bin/absorbed.py` now reads it, under two guards, because a detector that
over-credits is worse than one that under-credits:

- **The survivor must have merged.** A pointer from one closed pull request to another that never
  landed is a chain where nothing reached the tree.
- **Self-references are dropped**, being a regex artefact rather than a contribution.

Scored at 5 — half a merged pull request, the same as filing an issue that a merged pull request
fixed. The work shaped what landed; a maintainer chose a different version of it.

Effect: 6 people gained credit, the largest move 156th to 58th. Everyone else shifted down by the
arithmetic, **this board's author included, from 79th to 81st.** That is the third correction here
to cost us rank — the weight rebalance took us from 55th to 73rd, excluding this repository from
its own ranking took us from 27th to 74th — and it is the expected direction. A scorer whose
corrections consistently favour its author would be evidence of something other than correctness.



If a number is wrong, open an issue with the URL that contradicts it. Evidence in, evidence out —
we do not adjudicate anything by opinion, including about ourselves.
