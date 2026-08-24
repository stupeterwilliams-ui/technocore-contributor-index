#!/usr/bin/env python3
"""Collect the raw evidence the leaderboard scores.

Collection and scoring are deliberately separate programs. This one only fetches and records
public facts, each with the URL a reader can click to check it; `score.py` turns that into
numbers without touching the network. That split is what makes the ranking reproducible: anyone
can re-run either half and compare, and a disagreement points at either the data or the weights
rather than at an opaque pipeline.

Everything here comes from the GitHub API. Nothing is scraped from Technocore rooms — room content
is unauthenticated text that anyone can write, so it cannot be evidence of anything.

    ./bin/collect.py            # writes data/raw/*.json
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import time

# Imported at module scope on purpose: if the verifier is missing, this run must fail loudly
# rather than record every proof as "could not verify", which looks identical to a bad signature.
from technocore_sdk.proof import Proof

REPO = "flop-labs/technocore-chat"
ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"

# The maintainer's own merged PRs are not a contribution ranking, they are the project. Listing
# them first would make the board trivially true and say nothing about who else showed up.
MAINTAINERS = {"sv"}

CLOSES = re.compile(r"\b(?:closes|closed|close|fixes|fixed|fix|resolves|resolved)\s+#(\d+)\b", re.IGNORECASE)


def gh(*args: str) -> object:
    """One `gh` call returning parsed JSON, or None when the call fails."""
    result = subprocess.run(["gh", *args], capture_output=True, text=True,
                            timeout=180, check=False)
    if result.returncode != 0:
        print(f"  ! gh {' '.join(args[:3])}...: {result.stderr.strip()[:160]}", file=sys.stderr)
        return None
    try:
        return json.loads(result.stdout) if result.stdout.strip() else None
    except json.JSONDecodeError:
        return None


def write(name: str, payload: object) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    path = RAW / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    size = len(payload) if isinstance(payload, list) else 1
    print(f"  wrote {path.relative_to(ROOT)} ({size} records)")


def collect_pulls() -> list[dict]:
    """Every PR ever opened against upstream, with its state and author."""
    print("pull requests")
    out = []
    for state in ("merged", "open", "closed"):
        rows = gh("pr", "list", "--repo", REPO, "--state", state, "--limit", "300",
                  "--json", "number,author,title,createdAt,mergedAt,closedAt,body,url") or []
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
              "--json", "number,author,title,state,stateReason,createdAt,url") or []
    return [{
        "number": r["number"],
        "author": (r.get("author") or {}).get("login"),
        "title": r.get("title", ""),
        "state": r.get("state"),
        "stateReason": r.get("stateReason"),
        "createdAt": r.get("createdAt"),
        "url": r.get("url"),
    } for r in rows]


def collect_proofs() -> list[dict]:
    """Contribution proofs published anywhere on GitHub, fetched and verified.

    A proof that does not verify is recorded as not verifying rather than dropped — the board
    should be able to show that it looked and what it found.
    """
    print("contribution proofs")
    search = gh("api", "-X", "GET", "search/code",
                "-f", "q=technocore-contribution-proof-v1", "-f", "per_page=100") or {}
    out = []
    for item in (search.get("items") or []):
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
            "did": None,
            "artifact_url": None,
            "note": "",
        }
        if not path.endswith(".json"):
            record["note"] = "schema name appears in source code, not in a proof file"
            out.append(record)
            continue
        fetched = subprocess.run(["curl", "-sL", "--max-time", "40", raw_url],
                                 capture_output=True, text=True, check=False)
        try:
            proof = json.loads(fetched.stdout)
        except json.JSONDecodeError:
            record["note"] = "could not parse the file as JSON"
            out.append(record)
            continue
        record["parsed"] = True
        record["did"] = proof.get("did")
        record["artifact_url"] = proof.get("artifact_url")
        record["commit"] = proof.get("commit")
        record["signature_present"] = bool(proof.get("signature"))
        try:
            record["verifies"] = Proof.from_dict(proof).verify()
            if not record["verifies"]:
                record["note"] = (
                    "well-formed but does not verify against the published canonical string "
                    "technocore-contribution-proof-v1|<did>|<artifact_url>|<commit>"
                )
        except Exception as exc:  # noqa: BLE001 - any failure means "not verified"
            record["note"] = f"could not verify: {exc}"
        out.append(record)
    return out


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
    payload = gh("api", f"repos/{repo}/readme")
    if not isinstance(payload, dict) or not payload.get("content"):
        return ""
    import base64
    try:
        text = base64.b64decode(payload["content"]).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 - an unreadable README is simply no evidence
        return ""
    return judge(text, "README")


def collect_artifacts() -> list[dict]:
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
                  "technocore-chat in:readme,description"):
        search = gh("api", "-X", "GET", "search/repositories",
                    "-f", f"q={query}", "-f", "per_page=100", "-f", "sort=updated") or {}
        for item in (search.get("items") or []):
            full = item["full_name"]
            if full in candidates or full.startswith("flop-labs/"):
                continue
            candidates[full] = item

    print(f"  {len(candidates)} candidates, checking each for a real reference")
    seen: dict[str, dict] = {}
    for full, item in sorted(candidates.items()):
        description = (item.get("description") or "")
        why = _reference_evidence(full, description)
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
    print(f"  {len(seen)} genuinely reference Technocore")
    return sorted(seen.values(), key=lambda r: r["repo"])


def main() -> int:
    print(f"collecting at {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n")
    write("pulls", collect_pulls())
    write("issues", collect_issues())
    write("proofs", collect_proofs())
    write("artifacts", collect_artifacts())
    write("meta", {
        "collected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "upstream_repo": REPO,
        "maintainers_excluded_from_ranking": sorted(MAINTAINERS),
        "sources": [
            "GitHub API: pulls, issues, code search, repository search",
            "Contribution proofs fetched from raw.githubusercontent.com and verified locally",
        ],
        "not_used": [
            "Technocore room messages — unauthenticated text anyone can write, so not evidence",
            "Stars and social engagement — downstream of who saw what, not of what was built",
        ],
    })
    print("\ndone")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
