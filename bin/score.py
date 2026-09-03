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
WEIGHTS = {
    "merged_pr": 10,
    "issue_closed_by_merged_pr": 5,
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
    "unverifiable contribution proofs":
        "A proof whose canonical string is not published can only be checked by its author, so it "
        "is not evidence to anyone else. Publishing one that verifies takes a minute.",
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
# `verified_proof` checks a proof against the canonical string published in technocore-sdk. That
# is a real signal — a proof nobody can verify is not evidence — but we wrote the canonicalisation,
# and at the time of writing we are the only ones who satisfy it. Counting it for ourselves moves
# us from 55th to 6th, which is a rule its own author wrote and then won on. No amount of
# disclosure makes that read honestly, so we simply do not take the points. Anyone else who
# publishes a verifying proof gets all 8, and it takes about a minute.
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
                           "artifacts": 0},
                "evidence": [],
            }
        return people[login]

    def award(login: str, key: str, label: str, url: str) -> None:
        entry = person(login)
        forfeited = login == SELF and key in SELF_AUTHORED_SIGNALS
        points = 0 if forfeited else WEIGHTS[key]
        entry["score"] += points
        item = {"signal": key, "points": points, "what": label, "url": url}
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

    # 3. Contribution proofs that actually verify.
    for proof in proofs:
        if proof.get("verifies"):
            award(proof["owner"], "verified_proof",
                  f"verified contribution proof for {proof['repo']}", proof["url"])
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
            "everyone else and scores zero for the author. Counting it would have moved us from "
            "55th to 6th on a rule we wrote ourselves. If these numbers cannot be reproduced "
            "independently, the ranking is not worth anything."
        ),
        "totals": {
            "people_ranked": len(ranked),
            "merged_prs_counted": sum(p["counts"]["merged_prs"] for p in ranked),
            "artifacts_counted": sum(p["counts"]["artifacts"] for p in ranked),
            "verified_proofs": sum(p["counts"]["verified_proofs"] for p in ranked),
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
