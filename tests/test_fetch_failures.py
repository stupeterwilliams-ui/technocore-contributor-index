#!/usr/bin/env python3
"""A fetch that fails must not look like evidence that is absent.

Run with:

    uv run pytest tests/ -v

Every test here drives the real `bin/collect.py`, `bin/absorbed.py` and `bin/score.py` as
subprocesses against a fake `gh` and a fake `curl` placed ahead of the real ones on PATH. Nothing
is mocked inside Python, because the bug being fixed lives exactly at that boundary: it is about
what a non-zero exit code and a `000` status line were taken to mean.

The failure strings the fakes emit are copied from this repository's own `state/refresh.log` and
from a rate-limit reproduction run against the live API on 2026-09-16.

Each property has a paired mutation test. The mutation tests rewrite one line of the fix in a
throwaway copy of the source, re-run the same scenario, and assert that the bug comes back — so a
green suite means the assertions are actually load-bearing rather than passing for free. If a
mutation ever stops applying cleanly the test fails loudly rather than silently passing.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
FAKEBIN = REPO / "tests" / "fakebin"

README = "Technocore Tool\n\nPosts to technocore.chat using did:key.\n"

# One artifact repo per owner, one proof, one merged pull request. Small on purpose: every test
# below asks whether a single specific piece of evidence survived a single specific failure.
SCENARIO: dict = {
    "pulls": {"flop-labs/technocore-chat": {
        "merged": [{"number": 1, "author": {"login": "alice"}, "title": "fix",
                    "mergedAt": "2026-09-01T00:00:00Z", "createdAt": "2026-09-01T00:00:00Z",
                    "body": "", "url": "https://github.com/flop-labs/technocore-chat/pull/1"}],
        "open": [], "closed": []}},
    "issues": [],
    "search/repositories": {
        "technocore.chat in:readme,description": [[
            {"full_name": "alice/technocore-tool", "owner": {"login": "alice"},
             "html_url": "https://github.com/alice/technocore-tool", "description": "a tool",
             "created_at": "2026-01-01T00:00:00Z", "pushed_at": "2026-06-01T00:00:00Z",
             "license": {"key": "mit"}, "fork": False, "size": 100},
            {"full_name": "bob/technocore-thing", "owner": {"login": "bob"},
             "html_url": "https://github.com/bob/technocore-thing", "description": "a thing",
             "created_at": "2026-01-01T00:00:00Z", "pushed_at": "2026-06-01T00:00:00Z",
             "license": {"key": "mit"}, "fork": False, "size": 100},
        ]],
        "technocore in:name": [[]],
        "technocore-chat in:readme,description": [[]],
        "tclk in:name,readme,description": [[]],
    },
    "search/code": {"technocore-contribution-proof-v1": [[]]},
    "readmes": {"alice/technocore-tool": README, "bob/technocore-thing": README},
    "repos": {
        "alice/technocore-tool": {
            "full_name": "alice/technocore-tool", "owner": {"login": "alice"},
            "html_url": "https://github.com/alice/technocore-tool", "description": "a tool",
            "created_at": "2026-01-01T00:00:00Z", "pushed_at": "2026-06-01T00:00:00Z",
            "license": {"key": "mit"}, "fork": False, "size": 100},
        "bob/technocore-thing": {
            "full_name": "bob/technocore-thing", "owner": {"login": "bob"},
            "html_url": "https://github.com/bob/technocore-thing", "description": "a thing",
            "created_at": "2026-01-01T00:00:00Z", "pushed_at": "2026-06-01T00:00:00Z",
            "license": {"key": "mit"}, "fork": False, "size": 100},
    },
    "proofs": {"alice/technocore-tool/contribution-proof.json": {
        "did": "did:key:zAlice", "artifact_url": "https://github.com/alice/technocore-tool",
        "commit": "abc123", "signature": "AA=="}},
}

# Reverting the fix, one property at a time. Each is (file, find, replace); each removes exactly
# one of the guarantees under test and nothing else.
MUTATIONS = {
    # Property 1a: a curl fetch that did not answer is distinguishable from a 404. Reverting this
    # restores `if status.strip() != "200": continue` in everything but spelling.
    "curl_is_two_valued_again": (
        "fetch.py",
        '        if attempt < attempts:\n            time.sleep(2 ** attempt)\n    raise Unavailable(label, last)\n',
        '        if attempt < attempts:\n            time.sleep(0)\n    return MISSING\n',
    ),
    # Property 1b: the same for `gh`. Two mutations rather than one because the two fetch paths
    # fail differently — curl reports `000` in a status line, gh reports a string on stderr — and
    # a mutation that only reached one of them would leave half the suite unchecked.
    "gh_is_two_valued_again": (
        "fetch.py",
        ("        if not _retryable(last) or attempt == attempts:\n"
         "            raise Unavailable(label, last, retryable=_retryable(last))"),
        ("        if not _retryable(last) or attempt == attempts:\n"
         "            return MISSING"),
    ),
    # Property 1c: a listing that did not answer is not an empty listing. This used to be two
    # mutations, one per call site, because each site checked for itself. Both sites now go through
    # `gh_list` — which had to happen anyway, to supply the row cap and prove it was not hit — so
    # the defence lives in one place and so does the mutation. Fewer mutations here is the
    # consolidation working rather than coverage lost.
    "gh_list_accepts_an_empty_listing": (
        "fetch.py",
        ('    if rows is MISSING or rows is None:\n'
         '        raise Unavailable(what, "no listing returned")'),
        "    if rows is MISSING or rows is None:\n        rows = []",
    ),
    # Property 1e: a listing that returns exactly its row cap is not a complete listing.
    "a_full_listing_is_believed": (
        "fetch.py",
        ("    if len(rows) >= limit:\n"
         "        raise Unavailable("),
        ("    if False:\n"
         "        raise Unavailable("),
    ),
    # Property 2b: an unreadable previous collection is not treated as no previous collection.
    "unreadable_previous_is_treated_as_absent": (
        "guard.py",
        ("    path = RAW / f\"{name}.json\"\n"
         "    if not path.exists():\n"
         "        return None\n"
         "    try:\n"
         "        rows = json.loads(path.read_text())\n"
         "    except (OSError, ValueError) as exc:"),
        ("    path = RAW / f\"{name}.json\"\n"
         "    if not path.exists():\n"
         "        return None\n"
         "    try:\n"
         "        rows = json.loads(path.read_text())\n"
         "    except (OSError, ValueError):\n"
         "        return None\n"
         "    if False:\n"
         "        exc = None"),
    ),
    # Property 2: a run that lost evidence it cannot explain does not overwrite the last good one.
    "guard_is_disabled": (
        "guard.py",
        "    lost = disappeared(name, rows, identity) - explained",
        "    lost = set()",
    ),
}


def _stage(tmp_path: pathlib.Path, mutation: str | tuple[str, ...] | None = None) -> pathlib.Path:
    """A throwaway copy of the pipeline, optionally with some guarantees removed.

    Several properties here are held up by two independent mechanisms — the call site refusing an
    empty listing, and the fetch layer refusing to call a failure an answer — so breaking one
    changes nothing observable. That is the design working, and it means the honest mutation for
    those properties is a pair. Naming the pair is better than pretending a single-line mutation
    was sufficient.
    """
    root = tmp_path / "board"
    (root / "data" / "raw").mkdir(parents=True)
    # Never copy __pycache__. Python validates a .pyc against the source's mtime and size, and a
    # mutation that changes neither passes that check — so a staged copy carrying compiled bytecode
    # can run the code from before the mutation. It bit for real: a test that rewrote
    # `LIST_LIMIT = 40` to `LIST_LIMIT = 41` kept running 40, because the size is identical and
    # both writes landed inside the same second. Every mutation in this file was exposed to that,
    # silently, whenever the edit happened to preserve length.
    shutil.copytree(REPO / "bin", root / "bin",
                    ignore=shutil.ignore_patterns("__pycache__"))
    for name in (mutation,) if isinstance(mutation, str) else (mutation or ()):
        target, find, replace = MUTATIONS[name]
        path = root / "bin" / target
        source = path.read_text()
        assert find in source, (
            f"mutation {name!r} no longer applies to bin/{target}. The code it was written "
            f"against has changed, so this test is no longer checking anything — rewrite it."
        )
        path.write_text(source.replace(find, replace, 1))
    return root


def _run(root: pathlib.Path, program: str, scenario: dict, *args: str):
    scenario_file = root / "scenario.json"
    scenario_file.write_text(json.dumps(scenario))
    counter = root / "counter.json"
    counter.unlink(missing_ok=True)
    env = {**os.environ,
           "PATH": f"{FAKEBIN}:{os.environ['PATH']}",
           "FAKE_SCENARIO": str(scenario_file),
           "FAKE_COUNTER": str(counter),
           # No bytecode, for any run. Python validates a .pyc against the source's mtime and
           # size, and a mutation changing neither passes that check — so a second run in the same
           # staged copy can execute the code from before the mutation. Ignoring __pycache__ on
           # copy is not enough: the first subprocess writes its own. It bit for real, a rewrite of
           # `LIST_LIMIT = 40` to `LIST_LIMIT = 41` kept running 40 because the size is identical
           # and both writes landed inside the same second. Every mutation here was exposed to it
           # whenever the edit happened to preserve length.
           "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, str(root / "bin" / program), *args],
                          capture_output=True, text=True, env=env, timeout=300, check=False)


def _raw(root: pathlib.Path, name: str):
    return json.loads((root / "data" / "raw" / f"{name}.json").read_text())


def _proof_ids(root: pathlib.Path) -> set[str]:
    return {f"{p['repo']}/{p['path']}" for p in _raw(root, "proofs")}


def _cache(root: pathlib.Path) -> dict:
    path = root / "data" / "evidence-cache.json"
    return json.loads(path.read_text()) if path.exists() else {}


@pytest.fixture()
def clean(tmp_path):
    """A board with one good collection already on disk — the state every run starts from."""
    root = _stage(tmp_path)
    result = _run(root, "collect.py", SCENARIO)
    assert result.returncode == 0, result.stderr
    assert "alice/technocore-tool/contribution-proof.json" in _proof_ids(root)
    return root


def _failing(match: str, mode: str, times: int = 99, **extra) -> dict:
    return {**SCENARIO, "fail": [{"match": match, "mode": mode, "times": times, **extra}]}


# --- property 1: a failed fetch is not evidence of absence -------------------------------------

def test_a_rate_limited_proof_fetch_does_not_erase_the_proof(clean):
    """The line this is about: `if status.strip() != "200": continue`.

    A 429 took that branch and the proof — eight points, and the sole input to the gated room's
    allow-list — left the collection with nothing recorded anywhere.
    """
    before = _proof_ids(clean)
    result = _run(clean, "collect.py",
                  _failing("proof alice/technocore-tool/contribution-proof.json",
                           "status", status="429"))

    assert result.returncode == 1, "a run that could not fetch a proof must not be accepted"
    assert _proof_ids(clean) == before, "the previous collection must still be on disk untouched"
    incidents = json.loads((clean / "data" / "raw" / "incidents.json").read_text())
    assert incidents["collection_accepted"] is False
    assert any("alice/technocore-tool" in row["what"]
               for row in incidents["fetches_that_did_not_answer"]), incidents


def test_a_transport_failure_is_not_a_404(clean):
    """curl writes `000` when the transfer never happened. That is not the file being absent."""
    result = _run(clean, "collect.py",
                  _failing("proof alice/technocore-tool/contribution-proof.json", "transport"))
    assert result.returncode == 1
    assert "alice/technocore-tool/contribution-proof.json" in _proof_ids(clean)


def test_a_proof_that_really_is_absent_is_still_dropped_quietly(clean):
    """The fix must not make a genuine 404 into an incident, or nothing would ever publish.

    This is the check that the fix did not simply weaken the pipeline into never failing.
    """
    without = {**SCENARIO, "proofs": {}}
    result = _run(clean, "collect.py", without)
    assert result.returncode == 0, result.stderr
    assert _proof_ids(clean) == set(), "a 404 is a finding: nothing is published at that path"


def test_a_rate_limited_search_page_does_not_truncate_the_corpus(tmp_path):
    """A refused page used to be read as a short page, and a short page ends pagination.

    Reproduced against the live API on 2026-09-16: GitHub allows ten code-search requests a
    minute and this collector pages a code search and four repository searches.
    """
    root = _stage(tmp_path)
    two_pages = [SCENARIO["search/repositories"]["technocore.chat in:readme,description"][0]
                 + [{"full_name": f"filler{i}/technocore-x", "owner": {"login": f"filler{i}"},
                     "html_url": "https://github.com/x", "description": "", "created_at": "",
                     "pushed_at": "", "license": None, "fork": False, "size": 1}
                    for i in range(98)],
                 [{"full_name": "carol/technocore-late", "owner": {"login": "carol"},
                   "html_url": "https://github.com/carol/technocore-late",
                   "description": "technocore.chat client", "created_at": "2026-01-01T00:00:00Z",
                   "pushed_at": "2026-06-01T00:00:00Z", "license": {"key": "mit"},
                   "fork": False, "size": 50}]]
    scenario = {**SCENARIO,
                "search/repositories": {**SCENARIO["search/repositories"],
                                        "technocore.chat in:readme,description": two_pages},
                "readmes": {**SCENARIO["readmes"], "carol/technocore-late": README},
                # Fail page 2 twice; the retry inside gh_json should then succeed.
                "fail": [{"match": "search/repositories technocore.chat in:readme,description "
                                   "page=2", "mode": "ratelimit", "times": 2}]}
    result = _run(root, "collect.py", scenario)
    assert result.returncode == 0, result.stderr
    owners = {a["owner"] for a in _raw(root, "artifacts")}
    assert "carol" in owners, "page 2 was refused, retried, and must not have been skipped"


def test_a_failed_readme_fetch_is_never_written_to_the_cache(tmp_path):
    """The permanent ejection.

    AMCONSEIL/technocore-local-signer hit `x509: certificate signed by unknown authority` on
    2026-09-15 and the empty string went into data/evidence-cache.json, where it still is. Its
    README mentions technocore.chat and did:key. Nothing ever looked again.
    """
    root = _stage(tmp_path)
    _run(root, "collect.py", _failing("readme bob/technocore-thing", "tls"))
    cache = _cache(root)
    assert "bob/technocore-thing" not in cache, (
        "an unanswered README fetch became a cache entry. Nothing re-reads a negative, so that "
        f"is a permanent, silent ejection. Entry was: {cache.get('bob/technocore-thing')!r}")
    incidents = json.loads((root / "data" / "raw" / "incidents.json").read_text())
    assert any("bob/technocore-thing" in row["what"]
               for row in incidents["fetches_that_did_not_answer"]), incidents

    # On a first run there is nothing to have lost, so the run is allowed to stand one artifact
    # short and try again in an hour. The thing that must never happen is the failure becoming a
    # permanent verdict, and it does not: the cache has no entry, so the next run asks again.
    result = _run(root, "collect.py", SCENARIO)
    assert result.returncode == 0, result.stderr
    assert {a["repo"] for a in _raw(root, "artifacts")} == {"alice/technocore-tool",
                                                            "bob/technocore-thing"}


def test_the_cache_records_when_a_verdict_was_established(clean):
    """A verdict and the wreckage of a failed fetch were byte-identical in the old format.

    Both were `""`. There are 527 such entries on disk and no way to tell them apart, which is
    why clearing them takes a flag rather than a policy. The new shape cannot express a
    non-verdict at all: `_verdict` is the only writer and only a fetch that answered reaches it.
    """
    cache = _cache(clean)
    assert cache, "the run should have cached the verdicts it established"
    for repo, entry in cache.items():
        assert isinstance(entry, dict), f"{repo} was stored as a bare string"
        assert "why" in entry and entry.get("checked_at"), (
            f"{repo} has no record of when it was checked: {entry!r}")


def test_old_bare_string_cache_entries_are_still_read(tmp_path):
    """The 1717 entries already on disk must keep working, and positives must keep counting.

    A migration that silently dropped them would re-fetch every README on the next run and, worse,
    would drop the positive verdicts that the re-probe uses as its seed list.
    """
    root = _stage(tmp_path)
    (root / "data").mkdir(exist_ok=True)
    (root / "data" / "evidence-cache.json").write_text(json.dumps({
        "alice/technocore-tool": "README mentions technocore and 'technocore.chat'",
        "bob/technocore-thing": "",
    }))
    result = _run(root, "collect.py", {**SCENARIO, "readmes": {}})
    assert result.returncode == 0, result.stderr
    assert {a["repo"] for a in _raw(root, "artifacts")} == {"alice/technocore-tool"}, (
        "a positive verdict in the old format stopped counting")


def test_the_legacy_negative_backlog_drains_without_anyone_remembering(tmp_path):
    """527 empty entries are indistinguishable from wreckage, and one is known to be wreckage.

    `AMCONSEIL/technocore-local-signer` qualifies and was made invisible by a TLS error. The type
    change stops new wreckage; it does not clear the old, and a documented flag to clear it would
    not get run — which is the same shape as the rule that was written down in September and
    applied in exactly one place. So it drains by itself, and then stops.
    """
    root = _stage(tmp_path)
    (root / "data").mkdir(exist_ok=True)
    # bob is wreckage: stored as a bare "" by a fetch that never answered. It qualifies.
    (root / "data" / "evidence-cache.json").write_text(json.dumps({"bob/technocore-thing": ""}))
    # Search does not offer it either, so nothing but the backlog sweep can rescue it.
    without_bob = {**SCENARIO,
                   "search/repositories": {**SCENARIO["search/repositories"],
                                           "technocore.chat in:readme,description":
                                               [[SCENARIO["search/repositories"]
                                                 ["technocore.chat in:readme,description"][0][0]]]}}
    assert _run(root, "collect.py", without_bob).returncode == 0
    assert "bob/technocore-thing" in {a["repo"] for a in _raw(root, "artifacts")}, (
        "a repository buried by a failed fetch was never re-asked")

    entry = _cache(root)["bob/technocore-thing"]
    assert entry["why"] and entry["checked_at"], entry

    # And it terminates: now that it carries a verdict and a timestamp, it is not asked again.
    # Re-asking a timestamped verdict would be a staleness policy, which is deliberately not one.
    before = _cache(root)["bob/technocore-thing"]["checked_at"]
    assert _run(root, "collect.py", without_bob).returncode == 0
    assert _cache(root)["bob/technocore-thing"]["checked_at"] == before, (
        "the sweep re-asked an entry it had already established, so it never terminates")


def _backlog(root: pathlib.Path) -> dict:
    return json.loads((root / "data" / "raw" / "incidents.json").read_text())[
        "evidence_cache_backlog"]


def test_the_backlog_reports_cleared_when_it_empties(tmp_path):
    root = _stage(tmp_path)
    (root / "data").mkdir(exist_ok=True)
    (root / "data" / "evidence-cache.json").write_text(json.dumps({"bob/technocore-thing": ""}))
    assert _run(root, "collect.py", SCENARIO).returncode == 0
    state = _backlog(root)
    assert state["state"] == "cleared" and state["staleness_review_due"] is True, state


def test_a_permanently_failing_entry_reports_stuck_rather_than_waiting_forever(tmp_path):
    """The trigger has to fire on a tail that never drains.

    "Revisit once every entry carries `checked_at`" was the first version and it is unreachable by
    construction: a re-ask that fails is never cached, so an entry that fails permanently never
    acquires a timestamp and never leaves the backlog. A deferred decision conditioned on a state
    that cannot arrive is deferred forever — the same shape as a manual command nobody runs.
    """
    root = _stage(tmp_path)
    (root / "data").mkdir(exist_ok=True)
    (root / "data" / "evidence-cache.json").write_text(json.dumps({
        "bob/technocore-thing": "",          # resolves
        "zed/technocore-cursed": "",         # never will
    }))
    scenario = {**SCENARIO,
                "repos": {**SCENARIO["repos"],
                          "zed/technocore-cursed": {
                              "full_name": "zed/technocore-cursed", "owner": {"login": "zed"},
                              "html_url": "https://github.com/zed/technocore-cursed",
                              "description": "", "created_at": "", "pushed_at": "",
                              "license": None, "fork": False, "size": 1}},
                "fail": [{"match": "readme zed/technocore-cursed", "mode": "tls", "times": 99}]}
    assert _run(root, "collect.py", scenario).returncode == 0
    state = _backlog(root)
    assert state["state"] == "stuck" and state["staleness_review_due"] is True, state
    assert state["remaining"] == 1 and state["asked_this_run"] == 2, state
    # It keeps its old undated entry rather than being removed. Removing it looked tidier and was
    # a way of losing repositories: an entry that fails every time would be dropped on its first
    # re-ask and never looked at again, which is the original bug wearing the fix as a disguise.
    stuck_entry = _cache(root)["zed/technocore-cursed"]
    assert stuck_entry.get("checked_at") is None, (
        f"a fetch that never answered became a dated verdict: {stuck_entry!r}")

    # So it is still there to be retried, and still counted, on the run after this one.
    assert _run(root, "collect.py", scenario).returncode == 0
    assert _backlog(root)["asked_this_run"] == 1, "the stuck entry stopped being retried"


def test_a_backlog_larger_than_one_slice_reports_draining(tmp_path):
    """And must not claim a review is due while the sweep has not reached the end."""
    root = _stage(tmp_path)
    (root / "data").mkdir(exist_ok=True)
    # More than RECHECK_PER_RUN, all of which 404 on the direct probe and so leave quietly.
    (root / "data" / "evidence-cache.json").write_text(json.dumps(
        {"bob/technocore-thing": "", **{f"ghost{i}/gone": "" for i in range(200)}}))
    assert _run(root, "collect.py", SCENARIO).returncode == 0
    state = _backlog(root)
    assert state["state"] == "draining" and state["staleness_review_due"] is False, state
    assert state["remaining_before"] == 201 and state["asked_this_run"] == 150, state


@pytest.mark.parametrize(("content", "why"), [
    ('[{"number": 1, "author": {"login": "alice"}', "truncated mid-write"),
    ('{"leaderboard": []}', "parses but is not a list of records"),
    ('', "empty file"),
])
def test_an_unreadable_previous_collection_does_not_disarm_the_guard(clean, content, why):
    """A file that cannot be read is not the same fact as no file at all.

    Both used to return None, and `disappeared()` turns None into an empty set, which passes every
    check unconditionally. So the guard against absence-being-read-as-fact could itself be switched
    off by an absence it could not read — the same shape it exists to prevent, one level up.
    """
    (clean / "data" / "raw" / "pulls.json").write_text(content)
    result = _run(clean, "collect.py",
                  _failing("pr list flop-labs/technocore-chat merged", "ratelimit"))
    assert result.returncode == 1, f"the guard was disarmed by a file that is {why}"
    assert "cannot be read" in result.stderr or "not a list" in result.stderr \
        or "never answered" in result.stderr, result.stderr


def test_a_first_run_with_no_previous_collection_is_still_allowed(tmp_path):
    """The other half: a missing file really is a first run and must not be refused."""
    root = _stage(tmp_path)
    assert not (root / "data" / "raw" / "pulls.json").exists()
    assert _run(root, "collect.py", SCENARIO).returncode == 0


def test_raw_files_are_written_atomically(clean):
    """The truncated-file state above was reachable, which is why refusing is not enough.

    `write()` was a plain write_text, so a crash or a full disk part way through left exactly the
    file the guard could not read. A rename within a directory is atomic: the next run sees the
    old collection or the new one, never half of one.
    """
    source = (REPO / "bin" / "collect.py").read_text()
    assert "tmp.replace(path)" in source, "data/raw writes are not atomic"
    assert ".write_text(json.dumps(payload" not in source.replace("tmp.write_text", ""), (
        "something still writes a raw file in place")
    assert not list((clean / "data" / "raw").glob("*.tmp")), "a temp file was left behind"


def test_methodology_asserts_no_number_it_cannot_account_for():
    """The published document is checked the way the collection is: nothing passes unexplained.

    Not a sample of known claims — every number in the file. An enumerate-the-known checker is the
    instrument this repository keeps getting wrong: right about what it looked at, silent about
    what it did not. The way this drifts back is a new sentence with a new number in it.
    """
    result = subprocess.run([sys.executable, str(REPO / "bin" / "check_prose.py")],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(("edit", "what"), [
    ("append_a_new_claim", "a new sentence with a new number"),
    ("edit_a_frozen_section", "rewriting a record of what the board said on a day"),
])
def test_the_prose_check_actually_bites(tmp_path, edit, what):
    """Mutating the document must fail the check, or the check is decoration.

    The first version of this passed on `append_a_new_claim`: dated sections were frozen by span
    and the last one runs to the end of the file, so anything appended landed inside a frozen
    section and was accounted for by position. Sections are frozen by content digest now.
    """
    root = tmp_path / "board"
    shutil.copytree(REPO / "bin", root / "bin")
    shutil.copytree(REPO / "data", root / "data", ignore=shutil.ignore_patterns("raw"))
    doc = root / "METHODOLOGY.md"
    text = (REPO / "METHODOLOGY.md").read_text()
    if edit == "append_a_new_claim":
        text += "\nThe board currently tracks 412 contributors across the ecosystem.\n"
    else:
        old = "| 2026-09-15 21:46 | rank 11, 24 pts"
        assert old in text, "the frozen table this mutation edits has moved"
        text = text.replace(old, "| 2026-09-15 21:46 | rank 11, 25 pts")
    doc.write_text(text)
    result = subprocess.run([sys.executable, str(root / "bin" / "check_prose.py")],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 1, f"the check passed {what}: {result.stdout}"


def test_a_listing_that_fills_its_limit_is_refused_rather_than_believed(tmp_path):
    """The one shape three outcomes do not cover: the fetch answered a smaller question.

    `gh pr list --limit N` caps the result rather than paging past it, so a repository with more
    than N matching rows returns exactly N, successfully, with no error and no short page. Live on
    2026-09-17: 300 requested against 407 closed pull requests, the oldest in the window #216, and
    the window slid as new ones closed. `absorbed.py` asked the identical question, and absorbed
    contributions score five points each.
    """
    root = _stage(tmp_path)
    many = [{"number": n, "author": {"login": f"u{n}"}, "title": "t",
             "mergedAt": "2026-09-01T00:00:00Z", "createdAt": "2026-09-01T00:00:00Z",
             "body": "", "url": "u"} for n in range(1, 41)]
    scenario = {**SCENARIO,
                "pulls": {"flop-labs/technocore-chat": {"merged": many, "open": [], "closed": []}}}
    # Shrink the cap to the size of the fixture so the fixture fills it exactly.
    fetch = root / "bin" / "fetch.py"
    fetch.write_text(fetch.read_text().replace("LIST_LIMIT = 5000", "LIST_LIMIT = 40"))

    result = _run(root, "collect.py", scenario)
    assert result.returncode == 1, "a listing that filled its cap was published as complete"
    assert "exactly the 40-row limit" in result.stderr, result.stderr

    # One row short of the cap is proof of completeness, and must still pass.
    fetch.write_text(fetch.read_text().replace("LIST_LIMIT = 40", "LIST_LIMIT = 41"))
    assert _run(root, "collect.py", scenario).returncode == 0
    assert len(_raw(root, "pulls")) == 40


def test_a_failed_pull_request_listing_does_not_zero_everybody(clean):
    """`gh(...) or []` on the merged listing deletes ten points a head from everyone."""
    result = _run(clean, "collect.py",
                  _failing("pr list flop-labs/technocore-chat merged", "ratelimit"))
    assert result.returncode == 1
    assert len(_raw(clean, "pulls")) == 1, "the previous pull requests must survive"


def test_a_failed_closure_listing_does_not_zero_the_absorbed_awards(clean):
    """On 2026-09-15 at 22:53 UTC this reported 0 where every neighbouring run reported 15."""
    (clean / "data" / "raw" / "absorbed.json").write_text(json.dumps(
        [{"repo": "flop-labs/technocore-chat", "number": 495, "author": "Sertug17",
          "title": "fix", "url": "u", "survivor": 539, "survivor_url": "v"}]))
    scenario = {**SCENARIO, "fail": [{"match": "pr list flop-labs/technocore-chat closed",
                                      "mode": "ratelimit", "times": 99}]}
    result = _run(clean, "absorbed.py", scenario)
    assert result.returncode == 1
    assert len(_raw(clean, "absorbed")) == 1, "Sertug17's five points must still be there"


# --- property 2: a run that saw less does not publish, and does not eject anyone ---------------

def test_a_degraded_run_never_reaches_the_leaderboard(clean):
    """The whole point. score.py must not run, so the allow-list derived from it cannot move."""
    def ranking():
        # The same shape refresh.sh compares before deciding to publish. `generated_at` moves on
        # every run and is not evidence that anybody's standing changed.
        board = json.loads((clean / "data" / "leaderboard.json").read_text())
        return [(e["login"], e["score"], e["rank"]) for e in board["leaderboard"]]

    assert _run(clean, "score.py", SCENARIO).returncode == 0
    before = ranking()
    assert ("alice", 15, 1) in before

    assert _run(clean, "collect.py",
                _failing("proof alice/technocore-tool/contribution-proof.json", "transport")
                ).returncode == 1
    assert _run(clean, "score.py", SCENARIO).returncode == 0
    assert ranking() == before, (
        "a run that could not see the evidence published a different ranking")


def test_a_repository_that_really_404s_is_allowed_to_leave(clean):
    """The guard must not freeze the board forever the first time someone deletes a repo."""
    gone = {**SCENARIO,
            "search/repositories": {**SCENARIO["search/repositories"],
                                    "technocore.chat in:readme,description":
                                        [[SCENARIO["search/repositories"]
                                          ["technocore.chat in:readme,description"][0][0]]]},
            "repos": {k: v for k, v in SCENARIO["repos"].items() if k != "bob/technocore-thing"}}
    result = _run(clean, "collect.py", gone)
    assert result.returncode == 0, result.stderr
    assert {a["repo"] for a in _raw(clean, "artifacts")} == {"alice/technocore-tool"}


def test_search_dropping_a_repo_does_not_drop_it_from_the_board(clean):
    """Search is not stable near its result cap. A repo it forgot is re-probed, not deleted.

    Measured over 185 consecutive published runs: artifacts lost identifiers in 132 of them, up
    to 11 at a time, while pull request numbers — which cannot stop existing — lost none in 164.
    """
    forgot = {**SCENARIO,
              "search/repositories": {**SCENARIO["search/repositories"],
                                      "technocore.chat in:readme,description":
                                          [[SCENARIO["search/repositories"]
                                            ["technocore.chat in:readme,description"][0][0]]]}}
    result = _run(clean, "collect.py", forgot)
    assert result.returncode == 0, result.stderr
    assert {a["repo"] for a in _raw(clean, "artifacts")} == {"alice/technocore-tool",
                                                             "bob/technocore-thing"}


# --- mutation checks: disable the fix, confirm the bug returns ---------------------------------

def test_mutation_without_three_valued_fetch_the_proof_vanishes_silently(tmp_path):
    """With `Unavailable` collapsed back into `MISSING`, a 429 erases the proof and the run
    reports success — which is the behaviour the board shipped, and the reason this test exists."""
    root = _stage(tmp_path, mutation="curl_is_two_valued_again")
    assert _run(root, "collect.py", SCENARIO).returncode == 0
    assert "alice/technocore-tool/contribution-proof.json" in _proof_ids(root)

    result = _run(root, "collect.py",
                  _failing("proof alice/technocore-tool/contribution-proof.json",
                           "status", status="429"))
    assert result.returncode == 0, "the mutated pipeline reports a clean run"
    assert "alice/technocore-tool/contribution-proof.json" not in _proof_ids(root), (
        "the mutation did not reintroduce the bug, so the paired test proves nothing")


def test_mutation_without_three_valued_gh_a_failed_readme_is_cached_as_no_evidence(tmp_path):
    """With `gh` failures collapsed back into "not found", a TLS error becomes a verdict.

    This is the mutation that reproduces AMCONSEIL/technocore-local-signer exactly: the fetch
    fails, the empty string lands in the cache, and no later run ever asks again.
    """
    root = _stage(tmp_path, mutation="gh_is_two_valued_again")
    _run(root, "collect.py", _failing("readme bob/technocore-thing", "tls"))
    cache = _cache(root)
    assert "bob/technocore-thing" in cache and not cache["bob/technocore-thing"]["why"], (
        "the mutation did not reintroduce the bug, so the paired test proves nothing")


@pytest.mark.parametrize(("program", "source", "mutations"), [
    ("collect.py", "pulls", ("gh_list_accepts_an_empty_listing", "gh_is_two_valued_again",
                             "guard_is_disabled")),
    ("absorbed.py", "absorbed", ("gh_list_accepts_an_empty_listing", "gh_is_two_valued_again",
                                 "guard_is_disabled")),
])
def test_mutation_a_failed_listing_becomes_an_empty_one(tmp_path, program, source, mutations):
    """All three defences off: a refused listing is read as "nobody did any of this".

    It takes all three, and finding that out is the useful part of writing the mutation down.
    A refused pull request listing is caught by `gh_list` refusing to return an empty list, and if
    that goes by the fetch layer refusing to call a failure an answer, and if that goes by the
    guard refusing to overwrite a collection that lost everything. Removing any one or any two of them
    changes nothing observable. With all three gone, `absorbed.py` reproduces its 2026-09-15
    22:53 UTC behaviour exactly: 0 awards where the runs either side of it found 15.
    """
    root = _stage(tmp_path, mutation=mutations)
    seed = [{"repo": "flop-labs/technocore-chat", "number": 495, "author": "Sertug17",
             "title": "fix", "url": "u", "survivor": 539, "survivor_url": "v"}]
    if program == "absorbed.py":
        (root / "data" / "raw" / "absorbed.json").write_text(json.dumps(seed))
        match = "pr list flop-labs/technocore-chat closed"
    else:
        assert _run(root, "collect.py", SCENARIO).returncode == 0
        match = "pr list flop-labs/technocore-chat merged"

    result = _run(root, program, {**SCENARIO, "fail": [{"match": match, "mode": "ratelimit",
                                                        "times": 99}]})
    assert result.returncode == 0, "the mutated pipeline reports a clean run"
    assert _raw(root, source) == [], (
        "the mutation did not reintroduce the bug, so the paired test proves nothing")


def test_mutation_an_unreadable_collection_silently_disarms_the_guard(tmp_path):
    """With the two answers collapsed again, a truncated file lets anything through."""
    root = _stage(tmp_path, mutation="unreadable_previous_is_treated_as_absent")
    assert _run(root, "collect.py", SCENARIO).returncode == 0
    (root / "data" / "raw" / "pulls.json").write_text('[{"number": 1, "author"')
    result = _run(root, "collect.py",
                  _failing("pr list flop-labs/technocore-chat merged", "ratelimit"))
    assert result.returncode == 1, result.stderr
    assert "never answered" in result.stderr and "disappeared" not in result.stderr, (
        "the mutation did not reintroduce the bug: the guard still noticed the loss, when it "
        "should have compared against nothing and had nothing to say")


def test_mutation_without_the_guard_a_degraded_run_publishes(tmp_path):
    """With the guard neutered, the shrunken collection overwrites the good one on disk."""
    root = _stage(tmp_path, mutation="guard_is_disabled")
    assert _run(root, "collect.py", SCENARIO).returncode == 0
    before = _proof_ids(root)

    _run(root, "collect.py", _failing("proof alice/technocore-tool/contribution-proof.json",
                                      "transport"))
    assert _proof_ids(root) != before, (
        "the mutation did not reintroduce the bug, so the paired test proves nothing")
