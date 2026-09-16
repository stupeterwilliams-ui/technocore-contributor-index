#!/usr/bin/env python3
"""Turn the collected evidence into a ranking. No network access.

Run `collect.py` first. This program reads `data/raw/*.json` and writes `data/leaderboard.json`.
Given the same raw files it always produces the same output, so anyone can re-run it and compare
against ours line by line.

Every point awarded carries the URL that justifies it. If a number on the page cannot be traced to
something public and clickable, it does not belong on the page.
"""

from __future__ import annotations

import json
import pathlib
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "leaderboard.json"

# Published weights. Ranked by how expensive the signal is to fake: a merged PR needs a maintainer
# to agree with you, whereas anyone can create a repository.
# Weights must match the stated principle, or the principle is decoration. The first set did not:
# a full artifact scored 10 and the cap allowed three, so 30 points were available for creating
# three tidy repositories while two merged pull requests scored 20. That put 37 of the top 50 there
# with no upstream contribution at all, and "anyone can create a repository, a merged PR needs a
# maintainer to agree with you" was written directly above it. Opening three repos is not harder
# than landing two PRs.
#
# A full artifact is now 5, so one merged PR is worth roughly two solid artifacts and two merged
# PRs beat the artifact cap outright.
# `absorbed_into_merged_pr` is the fix for what METHODOLOGY.md called a known flaw with no
# mechanical detector. A contribution closed as a duplicate, with a merged pull request named as
# the survivor, reached the tree — a maintainer just kept someone else's version of it. Scoring
# that zero undercounts systematically, and in the direction of the people who arrive second on a
# crowded file. It is worth less than a merged pull request, because a maintainer chose otherwise,
# and the same as filing an issue that a merged PR fixed: the contribution shaped what landed.
WEIGHTS = {
    "merged_pr": 10,
    "issue_closed_by_merged_pr": 5,
    "absorbed_into_merged_pr": 5,
    "verified_proof": 8,
    "artifact_references_technocore": 2,
    "artifact_has_license": 1,
    "artifact_has_description": 1,
    "artifact_maintained_past_first_day": 1,
}

# What is deliberately worth nothing, and why. This lives in the output so it reaches the page.
NOT_SCORED = {
    "message volume in Technocore rooms":
        "Unauthenticated text anyone can write. A bot posting the same sentence fifty times would "
        "top a board that counted it.",
    "stars, followers, and social engagement":
        "Downstream of who happened to see something. A board that scores attention scores itself.",
    "contribution proofs that verify under no known canonicalisation":
        "This entry used to say we could not check anybody's proof, and that was wrong. Two "
        "canonicalisations are in use and both are now checked. The one almost everyone uses, "
        "did-starter-json-v1, is undocumented: it is defined by contribution_payload in "
        "technocore_agent.py of zunmax/technocore-did-starter, and it was found by reading that "
        "source and reported by @githubbjj on flop-labs/technocore-chat#828. Proofs that verify "
        "under either rule score in full, and the rule that matched is recorded next to each "
        "award. What still scores zero is a proof matching neither, because nobody can check it.",
    "more than three artifacts per person":
        "The signal is that you built something real, not that you opened many repositories. "
        "Without a cap the board rewards volume, which is the easiest way to game it.",
    "our own opinion of whether an artifact is good":
        "Not machine-checkable, and a subjective score on a board its own authors appear on is the "
        "part that would deserve to be attacked.",
}

SELF = "stupeterwilliams-ui"

# At most this many artifacts count per person. The signal is "you built something real", not "you
# created many repositories" — without a cap, whoever opens the most repos wins regardless of what
# is in them, and that is the single easiest way to game a board like this.
MAX_SCORED_ARTIFACTS = 3

# Signals whose specification this board's author wrote. They score for everyone else and score
# zero for us.
#
# `verified_proof` checks a proof against either canonicalisation in use. The forfeit was
# introduced when only ours existed here and we were one of two people satisfying it — a rule its
# own author wrote and then won on. That is no longer the situation: the rule 112 of 114 published
# proofs use is `did-starter-json-v1`, which we did not write, and our own proof still verifies
# only under the one we did write. So the conflict is unchanged for us specifically and the
# forfeit stays. Dropping it is the one change here that would raise this author's own score, and
# it is not made in the same commit that corrected the error — if it is made at all, it should be
# argued separately and in public.
SELF_AUTHORED_SIGNALS = {"verified_proof"}

# The instrument does not score itself. This repository is a measuring tool for the ecosystem, not
# a contribution to it, and counting it moved its own author from 73rd to 27th the first time the
# collector noticed it existed. That is circular however real the repository is, and it is the same
# reasoning as forfeiting a signal we wrote the specification for.
EXCLUDED_ARTIFACTS = {"stupeterwilliams-ui/technocore-contributor-index"}


def load(name: str):
    return json.loads((RAW / f"{name}.json").read_text())


def main() -> int:
    pulls, issues = load("pulls"), load("issues")
    proofs, artifacts, meta = load("proofs"), load("artifacts"), load("meta")
    maintainers = set(meta.get("maintainers_excluded_from_ranking", []))

    people: dict[str, dict] = {}

    def person(login: str) -> dict:
        if login not in people:
            people[login] = {
                "login": login,
                "score": 0,
                "is_maintainer": login in maintainers,
                "is_author_of_this_board": login == SELF,
                "counts": {"merged_prs": 0, "issues_credited": 0, "verified_proofs": 0,
                           "artifacts": 0, "absorbed": 0},
                "evidence": [],
            }
        return people[login]

    def award(login: str, key: str, label: str, url: str, did: str | None = None) -> None:
        entry = person(login)
        forfeited = login == SELF and key in SELF_AUTHORED_SIGNALS
        points = 0 if forfeited else WEIGHTS[key]
        entry["score"] += points
        item = {"signal": key, "points": points, "what": label, "url": url}
        if did:
            # The did:key the proof binds, carried on the award rather than left in data/raw.
            #
            # data/raw is gitignored, and proofs.json was the only place this mapping existed — so
            # the gated room's allow-list could not be computed from the repository at all. Two
            # things follow from putting it here. A reader can check "membership is mechanical,
            # nobody approves anyone" offline instead of making 170 HTTP requests to derive it,
            # which is the difference between a claim and a checkable claim. And room-sync.sh can
            # read committed state rather than a working copy, so the room follows what was
            # published rather than whatever file happened to be on disk when its timer fired.
            #
            # The did is public key material already published in a public contribution-proof.json,
            # and the URL beside it here is the file it came from.
            item["did"] = did
        if forfeited:
            item["forfeited"] = (
                "not scored: this board's author wrote the specification for this signal"
            )
        entry["evidence"].append(item)

    # 1. Merged pull requests upstream.
    issues_by_number = {i["number"]: i for i in issues}
    for pr in pulls:
        if not pr.get("author"):
            continue
        if pr["state"] == "merged":
            award(pr["author"], "merged_pr", f"merged PR #{pr['number']}: {pr['title']}", pr["url"])
            person(pr["author"])["counts"]["merged_prs"] += 1
            # 2. Credit whoever filed an issue that a merged PR closed.
            for number in pr.get("closes", []):
                issue = issues_by_number.get(number)
                if not issue or not issue.get("author"):
                    continue
                award(issue["author"], "issue_closed_by_merged_pr",
                      f"issue #{number} fixed by merged PR #{pr['number']}: {issue['title']}",
                      issue["url"])
                person(issue["author"])["counts"]["issues_credited"] += 1

    # 2b. Contributions absorbed into someone else's merged pull request. Scoped to the repo this
    # board enumerates: crediting a tclk closure here would award points from a corpus the
    # manifest does not claim to cover.
    try:
        absorbed = json.loads((RAW / "absorbed.json").read_text())
    except (OSError, ValueError):
        absorbed = []
    for row in absorbed:
        if row.get("repo") != "flop-labs/technocore-chat" or not row.get("author"):
            continue
        award(row["author"], "absorbed_into_merged_pr",
              f"PR #{row['number']} closed for merged #{row['survivor']}: {row['title']}",
              row["url"])
        person(row["author"])["counts"]["absorbed"] += 1

    # 3. Contribution proofs that actually verify, under whichever canonicalisation matched. The
    # rule name travels with the award: "verified" on its own is not something a reader can
    # reproduce, and which rule matched is the whole substance of what was checked.
    proofs_by_rule: dict[str, int] = {}
    for proof in proofs:
        if proof.get("verifies"):
            rule = proof.get("verifying_rule") or "unrecorded"
            proofs_by_rule[rule] = proofs_by_rule.get(rule, 0) + 1
            award(proof["owner"], "verified_proof",
                  f"contribution proof for {proof['repo']}, verified under {rule}", proof["url"],
                  did=proof.get("did"))
            person(proof["owner"])["counts"]["verified_proofs"] += 1

    # 4. Artifacts, scored on mechanical properties only, best few per person.
    def artifact_strength(a: dict) -> tuple:
        return (a.get("maintained_past_first_day", False), a.get("has_license", False),
                a.get("has_description", False), a.get("size_kb", 0))

    by_owner: dict[str, list[dict]] = {}
    for art in artifacts:
        if art.get("is_fork") or art.get("size_kb", 0) == 0:
            continue  # a fork is not a contribution, and an empty repo is not an artifact
        if art["repo"] in EXCLUDED_ARTIFACTS:
            continue  # the instrument does not score itself
        by_owner.setdefault(art["owner"], []).append(art)

    for owner, owned in by_owner.items():
        owned.sort(key=artifact_strength, reverse=True)
        if len(owned) > MAX_SCORED_ARTIFACTS:
            person(owner)["artifacts_beyond_cap"] = len(owned) - MAX_SCORED_ARTIFACTS
        for art in owned[:MAX_SCORED_ARTIFACTS]:
            award(owner, "artifact_references_technocore", f"public artifact {art['repo']}",
                  art["url"])
            person(owner)["counts"]["artifacts"] += 1
            if art.get("has_license"):
                award(owner, "artifact_has_license", f"{art['repo']} has a licence", art["url"])
            if art.get("has_description"):
                award(owner, "artifact_has_description", f"{art['repo']} has a description",
                      art["url"])
            if art.get("maintained_past_first_day"):
                award(owner, "artifact_maintained_past_first_day",
                      f"{art['repo']} had commits after its first day", art["url"])

    ranked = sorted(
        (p for p in people.values() if not p["is_maintainer"]),
        key=lambda p: (-p["score"], p["login"].lower()),
    )
    for index, entry in enumerate(ranked, 1):
        entry["rank"] = index

    # How close the Nth-place score is to moving.
    #
    # Consumers gate on it: the gated room at /r/d-contributor-index admits everyone scoring at or
    # above the score at position ROOM_TOP_N, tie-inclusive. Whether that membership is stable
    # between two collections taken minutes apart is therefore a question about this number, and
    # on 2026-09-16 the answer was measured by hand — three collections an hour apart produced
    # corpora of 954, 961 and 957 people and the identical allow-list, because what search drops
    # and re-finds are artifact repositories worth two to five points while the cut sat at 14.
    #
    # That is a property of one day's distribution, not a guarantee, and a margin nobody is
    # watching is a margin nobody will notice closing. So the board asserts it on every build
    # instead: if the cut ever lands where the churn can reach it, this says so without anybody
    # having to remember to check.
    def cutoff_margin(position: int) -> dict | None:
        if len(ranked) < position:
            return None
        cut = ranked[position - 1]["score"]
        above = sum(1 for e in ranked if e["score"] > cut)
        tied = sum(1 for e in ranked if e["score"] == cut)
        lower = next((s for s in sorted({e["score"] for e in ranked}, reverse=True) if s < cut),
                     None)
        return {
            "position": position,
            "score": cut,
            "people_above_it": above,
            "people_tied_at_it": tied,
            "admitted_tie_inclusive": above + tied,
            # To raise the cut, enough people must climb past it to fill the positions outright.
            "gains_needed_to_raise_it": position - above,
            # To lower it, enough of those at or above must fall that position N reaches the next
            # score down. This is the number to watch. It is tempting to read a widening cut as
            # harmless because, relative to one board, it only admits — but anything describing a
            # change in membership compares two boards, and moving either endpoint falsifies the
            # description. A cut that drops onto a large tie re-admits everyone who was about to be
            # removed, which makes an announcement of removals a fiction rather than an undercount.
            # One point lost anywhere in the top N does it, and one artifact legitimately answering
            # 404 is one point lost.
            "losses_needed_to_lower_it": above + tied - position + 1,
            "next_score_below": lower,
        }

    margins = {str(n): cutoff_margin(n) for n in (50,)}

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "collected_at": meta.get("collected_at"),
        "upstream_repo": meta.get("upstream_repo"),
        "weights": WEIGHTS,
        "not_scored": NOT_SCORED,
        "maintainers_listed_separately": sorted(
            p["login"] for p in people.values() if p["is_maintainer"]
        ),
        "self_authored_signals_forfeited": sorted(SELF_AUTHORED_SIGNALS),
        "artifacts_excluded_from_scoring": sorted(EXCLUDED_ARTIFACTS),
        "disclosure": (
            "This board was built by " + SELF + ", who appears on it. Every point traces to a "
            "public URL, the weights are above, and the programs that produce it are in the "
            "repository — re-run them and compare. Where a signal's specification was written by "
            "the author of this board (currently: verified contribution proofs), it scores for "
            "everyone else and scores zero for the author — and this author's own proof verifies "
            "only under the canonicalisation this author wrote, so the forfeit still applies. "
            "Proofs are checked against both canonicalisations in use, and each award records "
            "which one matched. If these numbers cannot be reproduced independently, the ranking "
            "is not worth anything."
        ),
        "cutoff_margins": margins,
        "totals": {
            "people_ranked": len(ranked),
            "merged_prs_counted": sum(p["counts"]["merged_prs"] for p in ranked),
            "artifacts_counted": sum(p["counts"]["artifacts"] for p in ranked),
            "verified_proofs": sum(p["counts"]["verified_proofs"] for p in ranked),
            "verified_proofs_by_canonicalisation": dict(sorted(proofs_by_rule.items())),
        },
        "leaderboard": ranked,
        "maintainers": [p for p in people.values() if p["is_maintainer"]],
    }
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")

    print(f"ranked {len(ranked)} people -> {OUT.relative_to(ROOT)}\n")
    print(f"  {'#':>2}  {'who':28} {'pts':>4}  {'PRs':>3} {'iss':>3} {'proof':>5} {'art':>3}")
    for entry in ranked[:15]:
        c = entry["counts"]
        flag = "  <- this board's author" if entry["is_author_of_this_board"] else ""
        print(f"  {entry['rank']:>2}  {entry['login']:28} {entry['score']:>4}  "
              f"{c['merged_prs']:>3} {c['issues_credited']:>3} {c['verified_proofs']:>5} "
              f"{c['artifacts']:>3}{flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
