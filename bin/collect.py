#!/usr/bin/env python3
"""Collect the raw evidence the leaderboard scores.

Collection and scoring are deliberately separate programs. This one only fetches and records
public facts, each with the URL a reader can click to check it; `score.py` turns that into
numbers without touching the network. That split is what makes the ranking reproducible: anyone
can re-run either half and compare, and a disagreement points at either the data or the weights
rather than at an opaque pipeline.

Everything here comes from the GitHub API. Nothing is scraped from Technocore rooms — room content
is unauthenticated text that anyone can write, so it cannot be evidence of anything.

    ./bin/collect.py                        # writes data/raw/*.json
    ./bin/collect.py --recheck-negatives    # re-ask the whole legacy-negative backlog at once
    ./bin/collect.py --force                # overwrite even if this run saw less than the last

A run that could not fetch something it needed writes nothing and exits non-zero, leaving the
previous collection in place. `data/raw/incidents.json` says what it could not reach. See
`bin/guard.py` for why that is the correct outcome rather than a nuisance.

Cached negatives left over from the pre-2026-09-16 format are re-asked automatically, a slice per
run, until none are left; `--recheck-negatives` does the whole backlog in one run instead.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
import time

import guard
from fetch import MISSING, Incidents, Unavailable, gh_json, http_get

# Imported at module scope on purpose: if the verifier is missing, this run must fail loudly
# rather than record every proof as "could not verify", which looks identical to a bad signature.
from technocore_sdk.proof import RULES, Proof

REPO = "flop-labs/technocore-chat"
ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"

# The maintainer's own merged PRs are not a contribution ranking, they are the project. Listing
# them first would make the board trivially true and say nothing about who else showed up.
MAINTAINERS = {"sv"}

CLOSES = re.compile(r"\b(?:closes|closed|close|fixes|fixed|fix|resolves|resolved)\s+#(\d+)\b", re.IGNORECASE)


# Every fetch this run could not complete. Carried to data/raw/incidents.json and consulted by
# the guard before anything is allowed to overwrite the last good collection.
INCIDENTS = Incidents()


def gh(*args: str, what: str | None = None) -> object:
    """One `gh` call: parsed JSON, `MISSING` for a definite 404, or `Unavailable` raised.

    It used to return None for all three. Callers wrote `gh(...) or []`, so a rate-limited 403
    became an empty list, an empty list became "this person has no merged pull requests", and the
    board published that. The return type is deliberately awkward now: there is no longer a way to
    write `or []` and have it mean anything, which is the point.
    """
    return gh_json(*args, what=what)


def write(name: str, payload: object) -> None:
    # Write to a sibling and rename. A plain write_text leaves a truncated file if the process
    # dies or the disk fills part way through, and a truncated data/raw/*.json is precisely the
    # state that used to disarm the guard on the next run — see `guard.previous`. A rename within
    # a directory is atomic, so the next run sees either the old collection or the new one.
    RAW.mkdir(parents=True, exist_ok=True)
    path = RAW / f"{name}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)
    size = len(payload) if isinstance(payload, list) else 1
    print(f"  wrote {path.relative_to(ROOT)} ({size} records)")


def collect_pulls() -> list[dict]:
    """Every PR ever opened against upstream, with its state and author."""
    print("pull requests")
    out = []
    for state in ("merged", "open", "closed"):
        # No `or []` here, and none below. A failed listing of merged pull requests is not a repo
        # with no merged pull requests; it is ten points a head silently deleted from everyone who
        # has ever landed one. Let it raise and let the run be rejected.
        rows = gh("pr", "list", "--repo", REPO, "--state", state, "--limit", "300",
                  "--json", "number,author,title,createdAt,mergedAt,closedAt,body,url",
                  what=f"pr list --state {state}")
        if rows is MISSING or rows is None:
            raise Unavailable(f"pr list --state {state}", "no listing returned")
        for row in rows:
            out.append({
                "number": row["number"],
                "author": (row.get("author") or {}).get("login"),
                "title": row.get("title", ""),
                "state": "merged" if row.get("mergedAt") else state,
                "createdAt": row.get("createdAt"),
                "mergedAt": row.get("mergedAt"),
                "url": row.get("url"),
                "closes": sorted({int(n) for n in CLOSES.findall(row.get("body") or "")}),
            })
    # A PR can appear under more than one state filter; keep one record per number.
    unique = {row["number"]: row for row in out}
    return sorted(unique.values(), key=lambda r: r["number"])


def collect_issues() -> list[dict]:
    print("issues")
    rows = gh("issue", "list", "--repo", REPO, "--state", "all", "--limit", "300",
              "--json", "number,author,title,state,stateReason,createdAt,url",
              what="issue list")
    if rows is MISSING or rows is None:
        raise Unavailable("issue list", "no listing returned")
    return [{
        "number": r["number"],
        "author": (r.get("author") or {}).get("login"),
        "title": r.get("title", ""),
        "state": r.get("state"),
        "stateReason": r.get("stateReason"),
        "createdAt": r.get("createdAt"),
        "url": r.get("url"),
    } for r in rows]


def collect_proofs(artifacts: list[dict]) -> tuple[list[dict], set[str]]:
    """Contribution proofs published anywhere on GitHub, fetched and verified.

    Two canonicalisations are in use and both are checked, so `verifying_rule` records which one
    each signature matched. A verification result without the rule that produced it is not
    reproducible by a reader, and this board spent weeks reporting one.

    The rule almost everyone uses — `did-starter-json-v1` — is specified nowhere. It is defined by
    `contribution_payload` in `technocore_agent.py` of `zunmax/technocore-did-starter`, and it was
    found by reading that source and reported by @githubbjj on flop-labs/technocore-chat#828. This
    collector previously checked only the string technocore-sdk published, found 2 matches out of
    114, and recorded the other 112 as not verifying. They verify. See METHODOLOGY.md.

    A proof that verifies under neither rule is recorded as not verifying rather than dropped —
    the board should be able to show that it looked and what it found.
    """
    print("contribution proofs")
    # Code search alone under-discovers badly: it reports a total_count it does not return, does
    # not index every repository, and lags. It missed our own proofs entirely, which is how the
    # gap was noticed. So every artifact repo already discovered is also probed directly for a
    # root contribution-proof.json — the same check for everyone, rather than a special case for
    # the repos we happen to know about.
    items = search_all("search/code", "technocore-contribution-proof-v1")
    known = {(i["repository"]["full_name"], i["path"]) for i in items}
    # This run's artifact list, not the one left on disk by the previous run. Reading the file
    # made proof discovery depend on whichever collection happened to be sitting there, so a bad
    # artifact run poisoned the next proof run too.
    for art in artifacts:
        if (art["repo"], "contribution-proof.json") not in known:
            items.append({"repository": {"full_name": art["repo"]},
                          "path": "contribution-proof.json"})

    out = []
    gone: set[str] = set()
    for item in items:
        repo = item["repository"]["full_name"]
        path = item["path"]
        raw_url = f"https://raw.githubusercontent.com/{repo}/HEAD/{path}"
        blob_url = f"https://github.com/{repo}/blob/HEAD/{path}"
        record = {
            "repo": repo,
            "path": path,
            "owner": repo.split("/")[0],
            "url": blob_url,
            "parsed": False,
            "verifies": False,
            "verifying_rule": None,
            "did": None,
            "artifact_url": None,
            "note": "",
        }
        if not path.endswith(".json"):
            record["note"] = "schema name appears in source code, not in a proof file"
            out.append(record)
            continue
        # The line this replaces was:
        #
        #     if status.strip() != "200": continue  # no proof published here; silence, not a finding
        #
        # A 403, a 429, a 5xx, a TLS failure and a timeout all took that branch, and all of them
        # were recorded as "no proof published here". A verified proof is worth eight points and
        # is the sole input to the gated room's allow-list, so one unlucky second at the wrong
        # moment removed a named person from a room. `http_get` answers MISSING only for a 404 —
        # the host saying the file is not there — and raises for everything else.
        try:
            fetched = http_get(raw_url, what=f"proof {repo}/{path}")
        except Unavailable as exc:
            INCIDENTS.record(exc)
            continue
        if fetched is MISSING:
            gone.add(f"{repo}/{path}")  # a real answer: nothing is published at this path
            continue
        _, body = fetched
        try:
            proof = json.loads(body)
        except json.JSONDecodeError:
            record["note"] = "could not parse the file as JSON"
            out.append(record)
            continue
        record["parsed"] = True
        record["did"] = proof.get("did")
        record["artifact_url"] = proof.get("artifact_url")
        record["commit"] = proof.get("commit")
        record["signature_present"] = bool(proof.get("signature"))
        # Recorded, not scored. A proof says "the holder of this key claims this artifact at this
        # commit" — it says nothing about who owns the repository the file happens to sit in, and
        # neither canonicalisation binds the two. Some published proofs sit in one person's
        # repository and claim someone else's artifact, and `score.py` credits the repository
        # owner. Whether that should still score is a scoring decision; what the collector owes
        # is the fact, so a reader can see it rather than infer it.
        record["artifact_url_is_this_repo"] = (
            (proof.get("artifact_url") or "").rstrip("/").lower()
            == f"https://github.com/{repo}".lower()
        )
        try:
            rule = Proof.from_dict(proof).verifying_rule()
            record["verifies"] = rule is not None
            record["verifying_rule"] = rule
            if not rule:
                record["note"] = (
                    "well-formed but does not verify under either known canonicalisation "
                    f"({', '.join(RULES)})"
                )
        except Exception as exc:  # noqa: BLE001 - any failure means "not verified"
            record["note"] = f"could not verify: {exc}"
        out.append(record)
    return out, gone


# Terms that only appear alongside *this* Technocore: the agent service, its API surface, or its
# vendor. "technocore" alone is not enough — SciFiFarms/TechnoCore is a Docker Swarm IoT stack with
# 42 sibling repos and would otherwise top the board without having touched this ecosystem. But
# requiring the literal string "technocore.chat" was too strict in the other direction: it excluded
# ritesh59697/technocore-dashboard, whose README says "Technocore" throughout and never spells the
# domain. Either error discredits the ranking, so the test is "technocore" AND an ecosystem marker.
# Only markers that occur in THIS ecosystem. The generic English words tried first — "agent",
# "chat", "room", "signed" — pulled in SciFiFarms/TechnoCore-Farmbot and frstrtr/c2pool, a farm
# controller and a mining pool. Precision matters more than recall here: one absurd entry
# discredits the whole board, whereas a missing entry is a fixable omission.
ECOSYSTEM_MARKERS = (
    "technocore.chat", "technocore-chat", "flop-labs", "flop labs", "$flop",
    "did:key", "say-signed", "/r/lobby", "/r/technocore", "/kv/", "llms.txt",
)


# A README fetch per candidate is ~1s of subprocess, and there are hundreds of candidates. Cached
# on disk so a scheduled refresh costs one call per *new* repository rather than a full sweep —
# which is what makes an hourly unattended run possible at all.
_EVIDENCE_CACHE = ROOT / "data" / "evidence-cache.json"

# The cache holds verdicts and nothing else. Three things it must never hold:
#
#   * the result of a fetch that did not answer. That is not a verdict, and writing one here is
#     permanent — nothing re-reads a negative. `AMCONSEIL/technocore-local-signer` has been
#     excluded from the board since a TLS error on 2026-09-15 for exactly this reason.
#   * an entry whose emptiness cannot be explained. The old format stored a verdict as a string
#     and "no evidence" as `""`, so a genuine negative and a lost fetch were byte-identical.
#     There are 527 empty entries and no way to tell which is which, which is why clearing them
#     needs a flag (`--recheck-negatives`) rather than a policy.
#   * a value this code cannot describe. `_verdict` is the only writer.
#
# The format is therefore `{"why": <str>, "checked_at": <iso8601>}`, where `why` is the evidence
# or the empty string, and an absent key means "never established" rather than "established as
# nothing". Old bare-string entries are still read, and read as verdicts, because that is what
# the positive ones certainly are; the ambiguous negatives are the ones the flag clears.
_MIGRATED_NOTE = "read from the pre-2026-09-16 bare-string cache format"


def _load_cache() -> dict:
    """The cache, normalised to the three-valued form regardless of what is on disk."""
    try:
        raw = json.loads(_EVIDENCE_CACHE.read_text())
    except (OSError, ValueError):
        return {}
    out = {}
    for repo, value in raw.items():
        if isinstance(value, dict):
            out[repo] = value
        else:
            out[repo] = {"why": value or "", "checked_at": None, "note": _MIGRATED_NOTE}
    return out


def _verdict(why: str) -> dict:
    """A verdict this run actually established. The only thing allowed into the cache."""
    return {"why": why, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def _why(entry: object) -> str:
    """The evidence string from a cache entry, whatever format it is in."""
    if isinstance(entry, dict):
        return entry.get("why") or ""
    return entry or ""


def _save_cache(cache: dict) -> None:
    _EVIDENCE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _EVIDENCE_CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, indent=0, sort_keys=True))
    tmp.replace(_EVIDENCE_CACHE)


def _reference_evidence(repo: str, description: str) -> str:
    """Why we believe this repository is about the agent service. Empty string means we do not."""
    def judge(text: str, where: str) -> str:
        low = text.lower()
        if "technocore" not in low and "flop-labs" not in low:
            return ""
        for marker in ECOSYSTEM_MARKERS:
            if marker in low:
                return f"{where} mentions technocore and '{marker}'"
        return ""

    verdict = judge(description, "description")
    if verdict:
        return verdict

    # NOT `--jq .content`: that emits a bare base64 string, which the JSON-parsing gh() helper
    # silently turned into None — so every README check quietly returned "no evidence" and the
    # artifact list was description-only. A silent no is the worst possible failure for a check
    # whose whole job is deciding who appears on a public ranking.
    #
    # `gh` raises Unavailable here rather than returning; the caller must not cache what comes
    # back from a fetch that did not happen. AMCONSEIL/technocore-local-signer is the standing
    # proof of why: its README fetch failed with `x509: certificate signed by unknown authority`
    # at 22:53 UTC on 2026-09-15, the empty string was written to data/evidence-cache.json, and it
    # has been excluded from the board ever since. Its README says "Technocore Local Signer" and
    # contains both `technocore.chat` and `did:key`. It qualifies.
    payload = gh("api", f"repos/{repo}/readme", what=f"readme {repo}")
    if payload is MISSING:
        return ""  # the repository answered: it has no README. A finding, and cacheable.
    if not isinstance(payload, dict) or not payload.get("content"):
        return ""
    import base64
    try:
        text = base64.b64decode(payload["content"]).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 - an unreadable README is simply no evidence
        return ""
    return judge(text, "README")


def search_all(endpoint: str, query: str, max_pages: int = 8) -> list[dict]:
    """Every page of a search, not just the first.

    The original took `per_page=100` with no pagination and `sort=updated`, so it saw only the 100
    most recently touched repositories per query and silently dropped everything older — including
    our own, which is how the omission was noticed. A ranking that quietly excludes contributors
    whose repo has not been pushed this week is worse than no ranking.
    """
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        result = gh("api", "-X", "GET", endpoint,
                    "-f", f"q={query}", "-f", "per_page=100", "-f", f"page={page}",
                    what=f"{endpoint} q={query!r} page={page}")
        # The old line was `items = (result or {}).get("items") or []`, and it is the single most
        # expensive line this collector has contained. `gh()` returned None on any failure, so a
        # rate-limited page became an empty page, an empty page is shorter than 100, and a page
        # shorter than 100 is how a paginator knows it has reached the end. A refusal was read as
        # "that is all of them". Reproduced 2026-09-16: GitHub allows 10 code-search requests a
        # minute and this collector pages a code search plus four repository searches; the seventh
        # consecutive call returns `API rate limit exceeded`. On 2026-09-15 at 22:53 UTC a
        # connection reset on page 5 of the `tclk` query cut the enumeration from 1560 candidates
        # to 1495 and nothing anywhere said so.
        if result is MISSING:
            raise Unavailable(f"{endpoint} q={query!r} page={page}", "search endpoint 404")
        items = (result or {}).get("items") or []
        out.extend(items)
        if len(items) < 100:
            break
    return out


# How many un-timestamped negatives to re-ask per run. Sized against the budget rather than
# guessed: a run spends roughly 30 search calls plus about 130 direct repository probes, the core
# limit is 5000 an hour, and each re-ask costs at most two calls. 150 drains the 527 legacy
# entries in four hourly runs and never puts a run within reach of the limit.
#
# The cap is not what makes this safe, though, and that is worth saying because it means the
# number is not load-bearing. A re-ask that fails is never cached, so it is simply asked again on
# the next run; the backlog drains monotonically whatever the cap is, and stops forever once it
# is empty. The cap only bounds how long any single run takes.
RECHECK_PER_RUN = 150

# What the sweep did this run, published so its progress is visible without reconstructing it.
#
# It also carries the trigger for the deferred staleness decision, and that trigger has to fire on
# a *stuck* backlog rather than wait one out. The first version of it was "revisit once every entry
# carries checked_at", which is unreachable by construction: a re-ask that fails is never cached,
# so an entry that fails permanently — a repository that 403s forever, a host whose certificate
# never validates — never acquires a timestamp and never leaves the backlog. A condition that may
# never be met is the same failure as a manual command nobody remembers to run.
#
# The predicate needs no history and no cross-run counter. After a run the backlog is in exactly
# one of three states:
#
#   draining   more entries remain than a single slice, so the sweep has not reached the end yet
#   cleared    nothing remains; every negative on record is now a dated verdict
#   stuck      fewer remain than a slice, which means every one of them was asked this run and
#              did not resolve — that is the permanently-failing tail, whatever its size
#
# `cleared` and `stuck` are both terminal and both fire the revisit. A one-off flap can show as
# `stuck` for a single run and then resolve, which is fine: the state is recomputed every run
# rather than latched, so it corrects itself and a reader sees the count rather than a verdict.
BACKLOG: dict = {}


def _legacy_negatives(cache: dict) -> list[str]:
    """Cached negatives with no record of when, or whether, they were ever established.

    These are the wreckage. Under the pre-2026-09-16 format a real verdict of "no evidence" and a
    fetch that never answered were both stored as `""`, so there is no way to tell them apart —
    and at least one of them, `AMCONSEIL/technocore-local-signer`, is a repository that plainly
    qualifies and was made invisible by a TLS error.

    Sorted by name, not by age. "Oldest first" is not available here: being un-timestamped is
    precisely their defect. A stable order is what is available, and it has the property that
    matters more anyway — two people running this get the same slice in the same order. Once this
    list is empty every entry carries `checked_at`, and that is the point at which a staleness
    policy for *positive* verdicts becomes a question anyone can reason about.
    """
    return sorted(repo for repo, entry in cache.items()
                  if not _why(entry) and not (isinstance(entry, dict) and entry.get("checked_at")))


def collect_artifacts(recheck_all: bool = False) -> tuple[list[dict], set[str]]:
    """Public repositories that genuinely reference Technocore, with mechanical signals only.

    No judgement about whether something "works": that is not machine-checkable, and a subjective
    score on a board we appear on is exactly the part someone would be right to attack. What is
    recorded instead is licence, description, and whether anyone came back after the first day —
    the last being the honest separator between a maintained tool and a generated one.
    """
    print("artifacts")
    candidates: dict[str, dict] = {}
    for query in ("technocore.chat in:readme,description",
                  "technocore in:name",
                  "technocore-chat in:readme,description",
                  "tclk in:name,readme,description"):
        for item in search_all("search/repositories", query):
            full = item["full_name"]
            if full in candidates or full.startswith("flop-labs/"):
                continue
            candidates[full] = item

    # Search is a lower bound and it is not stable. Every one of these four queries fills all
    # eight pages, GitHub caps a search at 1000 results, and relevance ordering near that cap
    # reshuffles between calls — so the tail of the enumeration flickers. Measured over the 185
    # consecutive runs published in data/corpus.json, artifacts lost identifiers in 132 of them,
    # up to 11 at a time, while pull requests lost none in 164. Repositories do not appear and
    # vanish hourly; the enumeration does.
    #
    # So anything the enumeration has ever returned is asked about directly, which is a definite
    # question with a definite answer. A 404 means the repository really is gone and that is a
    # finding the guard accepts. Anything else means we do not know, and not knowing must not
    # look like deletion. This is the same move `collect_proofs` already makes one level down,
    # for the same reason: code search under-discovers, so probe what you know about.
    #
    # The seed is every repository we have ever judged to qualify, not merely the ones in the last
    # collection. One run's memory is not enough: `chip1chapa/technocore-contribution-action` sits
    # in the evidence cache with a positive verdict — "README mentions technocore and
    # 'technocore.chat'" — and is absent from the board anyway, because it fell out of search
    # several runs ago and nothing has looked since. Its owner is on the board at 12 points and
    # rank 80 for one repository, having been at 24 and rank 11 for two.
    gone: set[str] = set()
    cache = _load_cache()
    probe_directly = {repo for repo, entry in cache.items() if _why(entry)}
    probe_directly |= {row["repo"] for row in (guard.previous("artifacts") or []) if row.get("repo")}

    # Clear a slice of the legacy negatives every run, automatically. This was very nearly shipped
    # as a documented flag, and a flag would not have been run — which is the same shape as the
    # rule "a lookup that could not run must return unknown" being written down in September and
    # applied in exactly one place. A backlog that needs somebody to remember it is a backlog.
    # It terminates: once these are re-asked they carry `checked_at` and are never re-asked again.
    backlog = _legacy_negatives(cache)
    slice_size = len(backlog) if recheck_all else RECHECK_PER_RUN
    recheck = set(backlog[:slice_size])
    probe_directly |= recheck           # search may well not offer these, so ask about them directly
    BACKLOG.update(remaining_before=len(backlog), asked_this_run=len(recheck))
    if backlog:
        print(f"  re-asking {len(recheck)} of {len(backlog)} cached negatives that carry no record "
              f"of when they were checked")

    for full in sorted(probe_directly):
        if full in candidates or full.startswith("flop-labs/"):
            continue
        item = gh("api", f"repos/{full}", what=f"repo {full}")
        if item is MISSING:
            gone.add(full)  # deleted or made private: a real answer
            if full in recheck:
                # And a real answer is a verdict, so it leaves the backlog properly rather than by
                # being forgotten: there is no repository here, so there is no evidence here.
                cache[full] = _verdict("")
            continue
        if isinstance(item, dict) and item.get("full_name"):
            candidates[item["full_name"]] = item
            if item["full_name"] != full:
                # A rename. GitHub answers for the old path and reports the new name, so the old
                # identifier really has stopped existing and the guard must be told, or one
                # rename would block every run from here on and only `--force` would clear it.
                gone.add(full)

    fresh = [k for k in candidates if k not in cache]
    print(f"  {len(candidates)} candidates ({len(fresh)} new, {len(candidates) - len(fresh)} cached)")
    seen: dict[str, dict] = {}
    for full, item in sorted(candidates.items()):
        description = (item.get("description") or "")
        if full in cache and full not in recheck:
            why = _why(cache[full])
        else:
            try:
                why = _reference_evidence(full, description)
            except Unavailable as exc:
                # Do not cache this. An unanswered README fetch is not a verdict, and there is now
                # no shape it could be written in: `_verdict` is the only writer and it is only
                # reachable from a fetch that answered. Under the old bare-string format this
                # stored `""`, which is permanent and silent, because nothing re-reads a negative.
                # That is what happened to AMCONSEIL/technocore-local-signer.
                #
                # A backlog entry being re-asked keeps its old undated entry when this happens,
                # rather than being removed. Removing it looked tidier and was a way of losing
                # repositories: an entry that fails every time would have been deleted on its
                # first re-ask and never looked at again, which is the original bug wearing the
                # fix as a disguise. Left in place, it is retried next run and stays countable.
                INCIDENTS.record(exc)
                continue
            cache[full] = _verdict(why)
            if len(cache) % 25 == 0:
                _save_cache(cache)
        if not why:
            continue
        created = item.get("created_at") or ""
        pushed = item.get("pushed_at") or ""
        maintained = False
        if created and pushed:
            fmt = "%Y-%m-%dT%H:%M:%SZ"
            try:
                maintained = (time.mktime(time.strptime(pushed, fmt))
                              - time.mktime(time.strptime(created, fmt))) > 86400
            except ValueError:
                maintained = False
        seen[full] = {
            "repo": full,
            "owner": item["owner"]["login"],
            "url": item["html_url"],
            "description": description[:160],
            "reference_evidence": why,
            "created_at": created,
            "pushed_at": pushed,
            "has_license": bool(item.get("license")),
            "has_description": bool(description),
            "is_fork": bool(item.get("fork")),
            "size_kb": item.get("size", 0),
            "maintained_past_first_day": maintained,
        }
    _save_cache(cache)
    print(f"  {len(seen)} genuinely reference Technocore"
          + (f"; {len(gone)} previously-seen repos answered 404 and are really gone" if gone else ""))
    return sorted(seen.values(), key=lambda r: r["repo"]), gone


# How each source is identified when the guard compares this run with the last accepted one.
# Same identifiers the published corpus manifest uses, so a reader checking our work and the
# guard protecting it are talking about the same things.
IDENTITY = {
    "pulls": lambda r: f"pr#{r['number']}",
    "issues": lambda r: f"issue#{r['number']}",
    "artifacts": lambda r: r["repo"],
    "proofs": lambda r: f"{r['repo']}/{r['path']}",
}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    unknown = [a for a in argv if a not in ("--force", "--recheck-negatives")]
    if unknown:
        # Ignoring an unrecognised flag means a mistyped `--recheck-negative` runs without the
        # recheck and says nothing, which is the same fault as every other one fixed tonight.
        print(f"collect.py: unknown option(s) {' '.join(unknown)}\n"
              f"usage: collect.py [--recheck-negatives] [--force]", file=sys.stderr)
        return 2
    force = "--force" in argv
    print(f"collecting at {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n")
    recheck_all = "--recheck-negatives" in argv

    # Collect everything first, write nothing yet. A partial overwrite is the worst of both
    # worlds: data/raw stops being one coherent collection, and score.py reads half of one run
    # and half of another while believing it is reading a snapshot.
    collected: dict[str, list[dict]] = {}
    explained: dict[str, set[str]] = {}
    try:
        collected["pulls"] = collect_pulls()
        collected["issues"] = collect_issues()
        collected["artifacts"], explained["artifacts"] = collect_artifacts(recheck_all)
        collected["proofs"], explained["proofs"] = collect_proofs(collected["artifacts"])

        # A proof identifier can also disappear because the repository holding it disappeared, and
        # that is already accounted for one level up.
        explained["proofs"] |= {f"{repo}/contribution-proof.json"
                                for repo in explained["artifacts"]}

        for name, rows in collected.items():
            guard.check(name, rows, IDENTITY[name], INCIDENTS,
                        explained=explained.get(name), force=force)
    except Unavailable as exc:
        INCIDENTS.record(exc)
        print(f"\ncollection abandoned: {exc}", file=sys.stderr)
        print(guard.explain(guard.Rejected(f"{exc.what} never answered")), file=sys.stderr)
        _write_incidents(accepted=False)
        return 1
    except guard.Rejected as verdict:
        # Raised by `guard.check`, and also by `guard.previous` when a collection is on disk but
        # unreadable — which reaches here from inside collect_artifacts, not only from the checks.
        print("\n" + guard.explain(verdict), file=sys.stderr)
        _write_incidents(accepted=False)
        return 1

    for name, rows in collected.items():
        write(name, rows)
    write("meta", {
        "collected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "upstream_repo": REPO,
        "maintainers_excluded_from_ranking": sorted(MAINTAINERS),
        "sources": [
            "GitHub API: pulls, issues, code search, repository search",
            "Contribution proofs fetched from raw.githubusercontent.com and verified locally",
        ],
        "proof_canonicalisations_checked": list(RULES),
        "fetches_that_did_not_answer": len(INCIDENTS),
        "not_used": [
            "Technocore room messages — unauthenticated text anyone can write, so not evidence",
            "Stars and social engagement — downstream of who saw what, not of what was built",
        ],
    })
    _write_incidents(accepted=True)
    print("\ndone")
    return 0


def _backlog_state() -> dict:
    """Where the legacy-negative sweep has got to, and whether the staleness decision is due."""
    remaining = len(_legacy_negatives(_load_cache()))
    asked = BACKLOG.get("asked_this_run", 0)
    if remaining == 0:
        state, due = "cleared", True
    elif asked >= BACKLOG.get("remaining_before", 0):
        # The whole backlog was asked and some of it is still here, so what is left is the tail
        # that does not resolve. Note this is not `remaining <= asked`: a run that asks 150 of 201
        # leaves 51 it never reached, which is progress, not a stall.
        state, due = "stuck", True
    else:
        state, due = "draining", False
    return {
        "remaining_before": BACKLOG.get("remaining_before", 0),
        "asked_this_run": asked,
        "remaining": remaining,
        "state": state,
        "staleness_review_due": due,
        "what_this_means": {
            "draining": "the sweep has not reached the end of the backlog yet; nothing to decide",
            "cleared": "every cached negative is now a dated verdict, so expiring positive "
                       "verdicts can finally be reasoned about — see METHODOLOGY, known "
                       "limitations",
            "stuck": "every remaining entry was re-asked this run and none resolved, so this is "
                     "the permanently-failing tail. It will not drain by waiting. Decide the "
                     "staleness policy on what is here rather than on a complete cache",
        }[state],
    }


def _write_incidents(accepted: bool) -> None:
    """Publish what this run could not fetch, whether or not the run was accepted.

    A run that answered every question and a run that could not reach the API produce raw files
    that look identical. This is the file that tells them apart, and it is written on the failure
    path too — a rejected run's incidents are the most useful ones there are.
    """
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "incidents.json").write_text(json.dumps({
        "collected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "collection_accepted": accepted,
        "evidence_cache_backlog": _backlog_state(),
        **INCIDENTS.summary(),
    }, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
