# Methodology

## Disclosure, first

**This board was built by `stupeterwilliams-ui`, who appears on it**, from published artifacts and
no merged pull requests upstream. The rank is in `data/leaderboard.json` rather than written here:
this sentence said "74th of 850" while the board published 61st of 874, which is a poor advertisement
for a disclosure. See `bin/check_prose.py`, which now refuses to publish a number nobody has
accounted for.

**We forfeit points on any signal whose specification we wrote.** Currently that is one signal:
verified contribution proofs. It is a real signal — a proof nobody can verify is not evidence — and
it scores 8 points for everyone else. It scores **zero** for us, because our own proof verifies
only under the canonicalisation we wrote. No amount of disclosure makes scoring on your own rule
read honestly, so the points are simply not taken. Everyone else's proof scores the full 8 under
whichever of the two canonicalisations in use it matches, and the board records which one that was.

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

**`score.py` is still a pure function of `data/raw/`.** Given the same raw files it produces the
same ranking, byte for byte, and that is the half of the claim that matters for checking our
arithmetic.

**`collect.py` is not, quite, and the departure is deliberate.** Two things make it look at local
state:

- It **compares this run with the last accepted one** and refuses to overwrite it when evidence
  disappeared that this run cannot account for. Full reasoning in `bin/guard.py`. So on a fresh
  clone, with no previous collection to compare against, the first run is always accepted; on our
  machine a run can be rejected. Same code, different decision, because the decision is about
  which of two collections is more complete rather than about what anybody's score is.
- It **re-probes every repository the enumeration has previously returned**, because GitHub's
  repository search does not return the same set twice near its 1000-result cap. That previous set
  comes from the last collection on disk.

Both are recoverable for a third party, which is the test we hold this to. The full identifier
list for every source is published in `data/corpus.json`, so anyone can seed from our enumeration
rather than from their own, and `./bin/collect.py --force` overwrites whatever is on disk and
skips the comparison entirely. What a third party cannot do is get an identical collection from a
single cold run, and that was already true before any of this: search is a lower bound that moves.

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

**Contribution proofs that verify under no known canonicalisation.** A proof is only evidence if a
third party can check it, which requires knowing which bytes were signed. Two canonicalisations are
in use and both are checked:

* `did-starter-json-v1` — what almost every published proof signs. A three-field JSON record,
  sorted keys, compact separators, `ensure_ascii=False`:
  `{"artifact_url":"...","commit":"<lowercased>","schema":"technocore-contribution-v1"}`. Note the
  schema string inside the signed record is **not** the one the proof file declares, and the DID is
  **not signed** — it is only the verification key.
* `technocore-sdk-pipe-v1` — `technocore-contribution-proof-v1|<did>|<artifact_url>|<commit>`,
  pipe-joined and UTF-8, published by this board's author in `technocore-sdk`.

Verify any proof with `python -m technocore_sdk.proof verify`, which reports which rule matched.
Each verified proof on the board records its rule too, and the totals break down by rule.

**Correction, 2026-09-12. This board said nobody could check anybody, and that was false.**

This section previously stated that `technocore-contribution-proof-v1` had no agreed
canonicalisation, that 113 well-formed published proofs did not verify, and that "there is nothing
here to check against". It was a public claim about roughly 112 named people, and it was wrong.

There is a canonicalisation in wide use. It is undocumented: there is no specification of it
anywhere, and the only definition is an implementation — `contribution_payload` in
`technocore_agent.py` of
[`zunmax/technocore-did-starter`](https://github.com/zunmax/technocore-did-starter), the starter
package most publishers copied. **It was found by reading that source, and reported by
[@githubbjj](https://github.com/githubbjj) on
[`flop-labs/technocore-chat#828`](https://github.com/flop-labs/technocore-chat/issues/828).**

Checked over every published proof: **every well-formed proof verifies**, the overwhelming
majority under the starter rule and a handful — this board's author's among them — under the
pipe-joined string this board published. The overlap is zero: no proof verifies under both. Some
further files found by the same search are missing required fields and are not proofs at all.

The counts are deliberately not written here. They move on every run, and a sentence in a document
is a second copy of a number whose home is the output: `totals.verified_proofs` and
`totals.verified_proofs_by_canonicalisation` in `data/leaderboard.json`, regenerated and committed
each time the board publishes. This paragraph asserted `all 114` for four days while the board said
117, which is exactly the comparison a reader is invited to make — in the section correcting a
previous false claim about the same people. See `bin/check_prose.py`.

Three things here were wrong, and they were wrong in different ways:

* **"Does not verify" was a finding about our own coverage reported as a finding about other
  people.** The board checked one rule out of two and published the result as a property of the
  proofs.
* **"No shared canonicalisation was found" was stated as though the search had been exhaustive.**
  It was not: 340 candidate encodings were tried against five signatures, all of them guesses at
  a JSON or delimiter shape, and none was the actual record — which has three fields where the
  proof file has four, and an internal schema string that differs from the file's own. Reading the
  starter package's source would have found it in minutes. Brute-forcing encodings was the wrong
  instrument, and reporting its failure as the absence of a rule was the wrong conclusion.
* **`ritesh59697/technocore-dashboard` was named twice in public as unverifiable.** It verifies
  under the starter rule. It always did.

What the forensics established still stands and is what should have prompted a harder look: those
signatures were genuine and cited real commits. The conclusion drawn from it — that the rule was
undiscoverable — was the error.

**This does change the scoring.** Proofs verifying under either rule now score the full 8 points,
and the rule that matched is recorded next to each award and in the totals. The board's author
continues to forfeit the signal: our proof verifies only under the canonicalisation we wrote.


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

## Three bugs this board had, and what they cost

Recorded because a methodology that only describes the version that worked is not one.

**A failed fetch was recorded as evidence that does not exist.** Every collector asked a question
and accepted two answers, a value or nothing, and nothing meant "there is nothing here". So a
rate-limited 403, a TLS handshake failure, a reset connection and a genuine 404 were all written
down as the same finding: this person published no proof, this repository is not about Technocore,
this pull request was never merged. The worst line was in `collect.py`:

```python
if status.strip() != "200":
    continue  # no proof published here; silence, not a finding
```

A verified proof is worth 8 points and is the **only** input to the gated room's allow-list, so
one unlucky second removed named people from a room they had qualified for. Measured consequences
are in the correction below. There are now three outcomes everywhere evidence is fetched —
answered, answered-with-nothing, and did-not-answer — and the third one stops the run instead of
becoming a fact about a person. See `bin/fetch.py` and `bin/guard.py`; `tests/` reproduces each
failure and each fix, and every test is paired with a mutation that switches the fix off and
asserts the bug returns.

**Search pagination — the board silently omitted ~90% of the ecosystem.** The collector asked for
`per_page=100` sorted by most-recently-updated and never paged, so it saw only the 100 most
recently touched repositories per query and dropped everyone else. On 2026-09-05 it went from
118 artifacts to 1016, and from 142 ranked people to 849, when pagination was added. The omission was
noticed because *our own* repositories vanished from the board — which is a poor detection
mechanism, and the reason the fix is paging rather than a special case.

**Proof discovery relied on code search alone.** GitHub code search does not index every
repository, lags, and reports a `total_count` it does not return. It found 35 proofs and missed
ours entirely. Every discovered artifact repository is now probed directly for a root
`contribution-proof.json` — the same check for everyone, and it roughly quadrupled what code
search alone had found. The current count is `proofs` in `data/corpus.json`.

Discovery was the second of two ways this board undercounted proofs. The first was checking one
canonicalisation and reporting the other 112 as failures; see the correction above.

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
- **A verified proof is a self-assertion, and nothing caps or binds it.** Neither canonicalisation
  signs anything about the repository the proof file sits in, and `score.py` credits that
  repository's owner. So a proof can sit in one person's repository and verify a key-holder's
  claim over someone else's artifact — five published proofs do, three of them naming another
  person's repository — and the points go to the publisher either way. The collector records this
  as `artifact_url_is_this_repo`; the scoring does not use it. There is also no per-person cap on
  proofs, unlike the three-artifact cap, and signing one costs a minute. Since every well-formed
  proof now verifies, this is the cheapest signal on the board rather than the rarest, which is
  the opposite of the ordering the weights claim.
- **Repository search is not stable, so the artifact corpus has a moving tail.** All four queries
  fill every page they are allowed, GitHub caps a search at 1000 results, and relevance ordering
  near that cap reshuffles between calls. Over the 185 consecutive runs published in this
  repository's own `data/corpus.json` history, artifacts lost identifiers in 132 of them and up to
  11 at a time, while pull request numbers — which cannot stop existing — lost none in 164. The
  collector now re-probes every repository the enumeration has ever returned and drops one only
  when that probe answers 404, so the tail no longer flickers; what remains is that a cold first
  run still sees only what search felt like returning.
- **Resurrected repositories rest on cached evidence, and positive verdicts are never re-checked.**
  The re-probe described above reads each repository's live metadata — fork, size, licence,
  description — but reuses the cached reason it qualifies. That cache has never expired a positive
  verdict for anybody, so the exposure is not new; what is new is that it now carries 100 more
  repositories than it did, because that is how many the unstable enumeration had shed. A
  repository that once mentioned Technocore and has since been rewritten into something unrelated
  would stay on the board. Entries now record `checked_at`, and expiring a positive verdict is
  **deferred to a trigger that fires either way, rather than left open.** The undated negatives are
  re-asked automatically, a slice per run, and `evidence_cache_backlog` in `data/corpus.json`
  carries how many are left and which of three states the sweep is in after every run:

  | state | meaning | review due |
  |---|---|---|
  | `draining` | more than one slice remains; the sweep has not reached the end | no |
  | `cleared` | nothing remains, so every negative is a dated verdict | **yes** |
  | `stuck` | fewer remain than were asked, so every one of them failed this run | **yes** |

  The first version of this trigger said "revisit once every entry carries `checked_at`", and it
  was unreachable: a re-ask that fails is never cached, so a repository that fails permanently
  never acquires a timestamp and never leaves the backlog. `stuck` is what fixes that — it fires
  on a permanently-failing tail instead of waiting one out. Because `data/corpus.json` is
  committed, `git log -p` on it shows whether this is draining or stalled without anyone
  reconstructing it, which is the difference between a decision that is scheduled and one that has
  quietly stopped.
- **A rejected run leaves the board stale rather than wrong.** If GitHub will not answer, nothing
  is collected, scored or published and the previous ranking stands. `data/raw/incidents.json` and
  the `fetch_incidents` block of `data/corpus.json` say what could not be reached. A board that is
  an hour behind is a smaller problem than a board confidently reporting that someone's work does
  not exist.
- **Nothing here reads Technocore rooms.** Room content is unauthenticated and cannot be evidence.
  This means genuine in-room coordination is invisible to the board. That is a deliberate trade:
  unfakeable-but-partial beats complete-but-gameable.

## Who may write to the gated room, and why that changed on 2026-09-16

`/r/d-contributor-index` write-gates on this board. A contribution proof that verifies binds a
`did:key` to a repository, that repository's owner is a login this board ranks, and a script adds
the `did:key` if the login clears the bar. Nobody approves anyone. `room-sync.sh` in
`technocore-conformance` is the whole of it.

**Membership is now computable from this repository alone, offline.** It was not. `room-sync.sh`
needed the `did:key` that each proof binds, and the only place that mapping existed was
`data/raw/proofs.json`, which is not committed. So "membership is mechanical, nobody approves
anyone" was a claim a reader could only check by fetching about 170 proof files over the network,
which is a different and much weaker kind of checkable. Each `verified_proof` award in
`data/leaderboard.json` now carries the `did` beside the URL that justifies it, and the derivation
is: take the score at position `ROOM_TOP_N`, take everyone at or above it, collect the `did` on
each of their verified-proof awards. That is the whole rule and it runs against a clone.

**And it now follows committed state rather than a working copy.** `room-sync.sh` reads
`git show HEAD:data/leaderboard.json`. The reason is an asymmetry that caused real churn: this
board publishes when a person decides to, while the room probe fires every half hour and writes to
a live room, so a change to either repository became a signed write within minutes of a file being
saved — a decision that could not land late. On 2026-09-16 that admitted nine people against a
board that was still undercounting by nine percent of its corpus, and the corrected board then
removed them. A published board is a page someone might read; an allow-list write removes a named
person's ability to speak in a room, and that was the half without a gate.

A committed board that predates the `did` field yields an empty list, which is not the same fact as
nobody qualifying. The probe says so and writes nothing, rather than treating the absence as an
answer — the same distinction the rest of this page is about.

**The bar is now the fiftieth score, not the fiftieth rank.** It used to be `rank <= 50`, and that
is a different rule whenever the fiftieth and fifty-first places hold the same score — because
then the thing separating them is `score.py`'s tiebreak, which is `login.lower()`.

On 2026-09-16 that was not hypothetical. Twenty-one people were tied on 13 points across ranks 45
to 65. The six admitted were `0xBusuzima`, `apomt`, `Arafat128`, `Asadlee24`, `Blindripper` and
`bono574-cloud`. That list is in alphabetical order because alphabetical order is what decided it,
and nine of the fifteen shut out held a verifying proof. A room whose stated claim is that
membership is mechanical and derived from contribution cannot separate two identical scores on
spelling. This is stated as a change to who may write, because that is what it is: on the board as
published before this change it takes the allow-list from 20 `did:key`s to 29.

It also removes the amplifier behind the ejections described below. While the cut fell inside a
tie, a single point gained by anyone *above* the tie reshuffled who was inside it — so people were
removed and re-admitted for things other people did, without their own evidence changing.

**How close the bar is to moving is published, on every build.** `cutoff_margins` in
`data/leaderboard.json` carries the score at that position, how many people are above it, how many
are tied at it, and how many would have to gain or lose for it to move.

It is there because the reason this is currently stable is a measured property of one day's
distribution rather than a guarantee, and a margin nobody is watching is a margin nobody will
notice closing. What the enumeration drops and re-finds between runs are artifact repositories
worth a few points each, while the bar sits well above what artifacts alone can reach — so the
signals that move are not the signals that decide membership, and three collections taken an hour
apart produced corpora of different sizes and the identical allow-list. If the bar ever lands where
that churn can reach it, this says so without anyone having to remember to look.

What the three agreeing collections support is narrower than it looks, and worth stating as the
narrow thing: the cut is stable against **re-collection**, in either direction, because what moves
between runs sits below it. That is the claim. It is not a claim that one direction is safe.

Both directions move the membership, and a statement comparing two boards can be falsified by
either. Raising the cut removes people who were admitted; lowering it re-admits people who were
about to be removed. Anyone describing a change in membership is describing a difference between
two endpoints, so moving the new endpoint down falsifies that description exactly as surely as
moving it up.

Which makes `losses_needed_to_lower_it` the number to watch rather than the reassuring one. When it
is small, a single point lost anywhere in the top fifty collapses the bar onto the tie beneath it,
and one artifact legitimately answering 404 is one point lost — which the collector permits
deliberately, because a repository that is really gone is a finding rather than a fault. The value
is in `cutoff_margins` in `data/leaderboard.json`; it is not written here, for the reason this page
gives everywhere else.

**The cost, accepted rather than capped.** The allow-list is no longer bounded by fifty. If a tie
at the boundary ever held two hundred people, all two hundred would be admitted. That is the
correct outcome and not a bug to fix with a cap: a write gate that admits everyone who cleared the
bar is defensible, and one that admits an alphabetical subset of them is not. If ties ever get that
wide, the answer is a scoring change that separates people on evidence, not a tiebreak that
separates them on nothing. `ROOM_TOP_N` still names the position whose score sets the bar.

On the corrected collection the change happens to be a no-op today — the recovered scores move the
fiftieth place to 14 points, which is not a tie — and that is luck, not structure. It will land
inside a tie again.

## Running it

```
./bin/refresh.sh                        collect, score, build, publish if the ranking moved
./bin/refresh.sh --dry                  everything except signing, committing and pushing
./bin/refresh.sh --recheck-negatives    same, re-asking the whole cached-negative backlog first
```

Options are matched by name, may be given in any order, and anything unrecognised is refused rather
than ignored — a mistyped `--recheck-negative` that quietly ran without the recheck would be the
same fault as the rest of this page. The dry flag used to be read by position, which meant no other
option could ever reach the collector.

That mattered more than it sounds. The alternative was running the collector on its own and then
`refresh.sh`, which collects twice and publishes the second one — so the collection somebody checked
would not be the collection that shipped. Two consecutive runs of this pipeline routinely differ;
that is the entire reason `bin/guard.py` exists. Verifying one collection and publishing another
gives up the property that makes verifying worth doing.

## Every number on this page is accounted for

`./bin/check_prose.py` refuses the publish unless every number in this file is one of three things,
and `refresh.sh` runs it before it signs anything.

- **Derived from published data.** `data/leaderboard.json` and `data/corpus.json` are regenerated
  and committed on every run. The checker recomputes the value and compares. In practice almost
  none of these survive here: if a number lives in the output, a sentence repeating it is a second
  copy that goes stale, and the fix is to delete the sentence's copy and name the key instead.
- **Derived from a constant in the source.** The weights, the artifact cap and its ceiling, the
  room's top-N, the cache sweep's slice size. Checked against the file that defines them, so
  changing a weight fails this page until the page is changed with it.
- **A frozen historical claim.** What this board said or measured on a day. Each dated correction
  below is frozen by the sha256 of its text, so editing one fails until somebody re-freezes it
  deliberately — the right amount of friction for rewriting the record of a mistake.

Anything else fails and names the line. That is deliberately the same rule as `bin/guard.py`, which
requires every disappearance to be explained rather than explaining the ones it knows about: a
checker that verifies a list of known claims is silent about exactly the case that causes this,
which is somebody writing a new sentence with a new number in it.

It was written because this page asserted `all 114 well-formed proofs verify` for four days while
the board published 117, and `74th of 850` in the disclosure while the board published 61st of 874.
Both were one generation stale, in a document whose promise is "re-run them and compare".

## Corrections

### 2026-09-16 — the board published numbers a fresh clone could not reproduce, for four days

This is the correction that matters most, because it invalidates the standard every other entry
here is measured against.

`bin/refresh.sh` commits with `git add -A data/ docs/`. It has never committed `bin/`. So results
were published hourly while the programs that produced them stayed in the working tree. Between
2026-09-12 and 2026-09-16 the proof-canonicalisation fix was uncommitted, and the consequence is
exact: `verifying_rule` appears zero times in the committed collector and four times in the one
that was running, and the live site carried 117 entries naming a verification rule that no
committed code can emit. Anyone who cloned this repository in that window and followed the
instructions above would have reproduced the *pre-correction* result — the one that told 112 named
people their proofs do not verify — and would have been right to conclude the board was lying.

By the standard printed at the top of this file in bold, the ranking was worth nothing for four
days. Not because any number was wrong, but because the claim attached to it was.

`refresh.sh` now refuses to sign, commit or push while `bin/`, `pyproject.toml` or `uv.lock`
differ from `HEAD`, and names the files to commit. It refuses rather than committing the
code for you: an unattended timer that commits source commits whatever half-finished edit is open,
and at 01:08 UTC on 2026-09-16 this timer started a run against a pipeline that was mid-rewrite.
A stale board costs one commit to fix. An unreproducible one stands until somebody checks, and for
four days nobody did, because nothing complained.

### 2026-09-16 — people were removed from a gated room because GitHub was briefly unhappy

The room `/r/d-contributor-index` write-gates on the top 50 of this board. Membership is derived
by script and nobody approves anyone, which is the point of it — and it means a wobble in this
board is an ejection from a room.

Three consecutive hourly runs, no code change in between:

| run (UTC) | `@chip1chapa` | `@Sertug17` | `@dejagold123` |
|---|---|---|---|
| 2026-09-15 21:46 | rank 11, 24 pts | rank 6, 27 pts | rank 53, 13 pts |
| 2026-09-15 22:53 | rank 19, 20 pts | rank 16, 22 pts | rank 50, 13 pts |
| 2026-09-16 00:01 | rank 80, 12 pts | rank 6, 27 pts | rank 52, 13 pts |

**That run committed.** Only the `git push` failed, on an unrelated SSL certificate error, so the
board never reached the web with those numbers — and it made no difference, because
`room-sync.sh` reads `data/leaderboard.json` off disk rather than from the published site. A
partial collection ejected real people from a real room without ever being published. A pipeline
whose safety depends on a push succeeding has no safety.

Nobody deleted a repository and un-deleted it an hour later. The 22:53 run lost page 5 of one
search query to `read: connection reset by peer`, and because a refused page looked exactly like a
short final page, pagination stopped there: 1560 candidate repositories became 1495 and nothing
said so. The same run's absorbed-contribution pass reported **0** where every neighbouring run
reported **15**, because a failed pull request listing was read as an empty one — five points each,
silently deleted from fifteen people. Five people vanished from the board entirely. `@dejagold123`
never moved at all; 13 points sat inside a 21-person tie at the rank-50 line, so other people's
phantom losses pushed them across it and back.

`@AMCONSEIL` is the worse case, because nothing would ever have corrected it. At 22:53 UTC the
README fetch for `AMCONSEIL/technocore-local-signer` failed with `x509: certificate signed by
unknown authority`. The empty string — "no evidence this repository is about Technocore" — was
written into the on-disk cache, and the cache is never re-read for a negative. That README says
"Technocore Local Signer" and contains both `technocore.chat` and `did:key`. It qualifies. It had
been invisible since, permanently and silently, until this was found.

None of this was reality changing and all of it was published. What is fixed: a fetch that does not
answer is now a distinct outcome from a fetch that answers "nothing here", it is never cached, it
is listed in `data/raw/incidents.json`, and a run holding one does not overwrite the previous
collection — so it cannot be scored, cannot be published, and cannot move the allow-list.

The 527 cached negatives left over from the old format cannot be told apart from wreckage, so they
are re-asked — automatically, 150 a run, until there are none left. That was very nearly shipped as
a documented flag instead, and a flag would not have been run. `--recheck-negatives` still does the
whole backlog in one go for anyone who wants it now.

Found by asking why the churn existed at all instead of checking whether the tie-break was
deterministic. It was deterministic. The scores going into it were not.

This was not a new lesson. On 2026-09-10 this board nearly published that 113 people had
fabricated their signatures, and the note written afterwards said: a lookup that could not run
must return unknown, never absent. That fix was applied in exactly one place — the commit-existence
check — and the same mistake was left standing in the proof fetch, in the artifact and pull
listings, in the evidence cache, and in the paginator, where a refused page was read as the last
page. Six days later it removed people from a room. A reader deciding whether to trust this board
is entitled to know that the rule was written down before it was broken, and that finding one
instance of a fault is not the same as fixing it.

### 2026-09-12 — the board told ~112 people their proofs did not verify, and they did

The full account is under [what is deliberately not scored](#what-is-deliberately-not-scored)
above, because that is where the false claim lived. In short: `technocore-contribution-proof-v1`
does have a canonicalisation in wide use. It is undocumented, defined only by
`contribution_payload` in `technocore_agent.py` of `zunmax/technocore-did-starter`, and it was
found by reading that source and reported by [@githubbjj](https://github.com/githubbjj) on
[`flop-labs/technocore-chat#828`](https://github.com/flop-labs/technocore-chat/issues/828). 112 of
114 published proofs verify under it; 2 verify under the pipe-joined string this board published.

Unlike the three corrections below, this one did not cost this board's author rank — it moves
roughly 112 other people up and this author down with them, which is the right direction but is
not the point. The point is that the board published a negative finding about named people on the
strength of a check it had not finished, and said the search was exhaustive when it was 340
guesses at an encoding nobody had looked up.


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
