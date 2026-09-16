#!/usr/bin/env python3
"""Every number in METHODOLOGY.md must be accounted for, or this refuses the publish.

    ./bin/check_prose.py

This is `bin/guard.py` pointed at prose, and deliberately the same shape. The guard does not
enumerate the disappearances it knows how to explain and pass the rest; it requires *every*
disappearance to be explained and refuses otherwise. A checker that enumerated the claims it knew
about would be the instrument this whole repository keeps getting wrong: correct about what it
looked at, silent about what it did not, and reporting "no problems" when it means "nothing to
say". The way this bug recurs is somebody writing a new sentence with a new number in it, which is
precisely the case an enumerate-the-known checker cannot see.

So: every number is unaccounted until something accounts for it, in one of three ways.

  LIVE     derived from published data — `data/leaderboard.json`, `data/corpus.json`. The checker
           recomputes the value and compares. These are the ones that drift, and the fix for a
           drifting number is usually to delete it from the prose rather than to register it: the
           output is its home and a sentence is a second copy.
  CODE     derived from a constant in the source — a weight, the artifact cap, the room's top-N.
           Checked against the source, not against a number somebody typed.
  FROZEN   a historical claim, registered with the date it describes. These must never move; the
           register is what says so, rather than the checker guessing from tense.

Anything else fails and names the line. Putting it in a bucket takes a minute and is the moment
somebody finds out whether the number is true.

METHODOLOGY.md asserted `all 114 well-formed proofs verify` for four days while the board published
117 — in the section correcting a previous false public claim about the same people, in a document
whose promise is "re-run them and compare".
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOC = ROOT / "METHODOLOGY.md"

# Numbers that are not claims about the world. Each is a rule rather than a register entry,
# because registering them one by one would bury the entries that matter in dates and issue refs.
NOT_A_CLAIM = (
    (re.compile(r"20\d\d-\d\d-\d\d"), "a date"),
    (re.compile(r"#\d+"), "an issue or pull request reference"),
    (re.compile(r"\bv\d+\b|-v\d+\b|\bv\d+\.\d+"), "a schema or version string"),
    (re.compile(r"\bhttps?://\S+"), "a URL"),
    (re.compile(r"`[^`]*`"), "inside code formatting, so it names a value rather than asserts one"),
    (re.compile(r"\bHTTP \d{3}\b|\b[45]\d\d\b(?= error| response)"), "an HTTP status"),
    (re.compile(r"\bper_page=\d+|\bpage=\d+"), "a query parameter"),
    (re.compile(r"\b\d{2}:\d{2}(:\d{2})?\b"), "a clock time"),
    (re.compile(r"\b\d+(st|nd|rd|th)\b"), "an ordinal position"),
    # Bare HTTP statuses. Narrow to the ones this pipeline actually names, so a real count that
    # happens to be 404 is still caught rather than waved through by a loose three-digit rule.
    (re.compile(r"\b(400|401|403|404|409|410|429|451|500|502|503|504|5xx)\b"), "an HTTP status"),
)

# Whole sections that are historical by construction. A correction entry is headed with the date it
# describes and records what this board said and did on that day; every number inside one is frozen
# by that heading. Registering them individually would mean about seventy entries that all say the
# same thing, and burying the handful that matter underneath them — so the register carries the
# rule instead, which is also the honest description of why they must not move.
#
# Frozen by content, not by position. The first version accounted for every number inside the span
# of a dated section, and the last section runs to the end of the file — so appending a sentence
# with a new number in it landed inside a frozen section and passed silently. That is the exact
# failure this checker exists to prevent, in the checker. Worse, span-freezing let anyone edit a
# correction and add a number to it, when "must never move" is the whole claim these sections make.
#
# So each dated section is registered with the sha256 of its text. Editing one fails until somebody
# updates the digest deliberately, which is the right amount of friction for rewriting a record of
# what this board got wrong, and appending anywhere changes the digest of whatever it lands in.
FROZEN_SECTIONS = re.compile(
    r"^#{2,3} (?P<heading>20\d\d-\d\d-\d\d[^\n]*)\n.*?(?=^#{2,3} |\Z)",
    re.MULTILINE | re.DOTALL)

# Keyed by the whole heading, not by the date: there are two corrections dated 2026-09-16 and a
# date-keyed dict silently kept one of them.
# heading -> sha256 of the section. Regenerate deliberately with:  ./bin/check_prose.py --freeze
FROZEN_DIGESTS = {
    "2026-09-16 — the board published numbers a fresh clone could not reproduce, for four days":
        "f162895430224abcf79431fe3245d1a32f18875af3b2cc10a41c355a103a3602",
    "2026-09-16 — people were removed from a gated room because GitHub was briefly unhappy":
        "ea80aa5f0d48a7593dddf9e3b1a783aa338c81a2466aec6ade8a71422eb48508",
    "2026-09-12 — the board told ~112 people their proofs did not verify, and they did":
        "e1215ded3835c3765ff9cb277060353e81eda82c9fa727bbb86c638150364265",
    "2026-09-07 — 116 commits were credited to a stranger, and the history was rewritten":
        "c9f2ee28b75858903f5c52cc71d7d187cbd20fe6a6c499e87ee746076e08f559",
    "2026-09-06 — absorbed contributions now score":
        "6eadacc5d23836dbe8128ac7149f9dd0b720d1fabe0decffd7ea8f88d60dacc7",
}

# No `:` in these guards. It was here to skip clock times and it exempted *any* number followed by
# a colon, so "currently 1:" sailed through — a live value that drifts, in the paragraph explaining
# why live values must not be written here. The clock-time rule in NOT_A_CLAIM does that job
# precisely. A character class does it approximately, and approximately is how things end up
# exempted that nobody chose to exempt.
NUMBER = re.compile(r"(?<![\w.#\-/])(\d[\d,]*\d|\d)(?![\w\-/])")


def _data() -> dict:
    """The published values a LIVE claim may be derived from."""
    out: dict[str, int] = {}
    try:
        board = json.loads((ROOT / "data" / "leaderboard.json").read_text())
        for key, value in board.get("totals", {}).items():
            if isinstance(value, int):
                out[f"leaderboard.totals.{key}"] = value
            elif isinstance(value, dict):
                for sub, count in value.items():
                    out[f"leaderboard.totals.{key}.{sub}"] = count
        for key, value in board.get("weights", {}).items():
            out[f"leaderboard.weights.{key}"] = value
    except (OSError, ValueError):
        pass
    try:
        corpus = json.loads((ROOT / "data" / "corpus.json").read_text())
        for name, source in corpus.get("sources", {}).items():
            out[f"corpus.{name}.count"] = source["count"]
    except (OSError, ValueError):
        pass
    try:
        board = json.loads((ROOT / "data" / "leaderboard.json").read_text())
        for position, margin in (board.get("cutoff_margins") or {}).items():
            for key, value in (margin or {}).items():
                if isinstance(value, int):
                    out[f"leaderboard.cutoff_margins.{position}.{key}"] = value
    except (OSError, ValueError):
        pass
    return out


def _code() -> dict:
    """Constants a CODE claim may be derived from, read from the source that defines them."""
    out: dict[str, int] = {}
    score = (ROOT / "bin" / "score.py").read_text()
    for name in ("MAX_SCORED_ARTIFACTS",):
        found = re.search(rf"^{name} = (\d+)", score, re.MULTILINE)
        if found:
            out[f"score.{name}"] = int(found.group(1))
    weights = re.search(r"^WEIGHTS = \{(.*?)^\}", score, re.MULTILINE | re.DOTALL)
    if weights:
        for key, value in re.findall(r'"(\w+)":\s*(\d+)', weights.group(1)):
            out[f"score.WEIGHTS.{key}"] = int(value)
    if "score.MAX_SCORED_ARTIFACTS" in out:
        # The ceiling is not written down anywhere; it is the cap times what one artifact can earn.
        # Deriving it here rather than registering the number means changing a weight moves the
        # prose check with it, instead of leaving a sentence that used to be true.
        per_artifact = sum(v for k, v in out.items() if k.startswith("score.WEIGHTS.artifact_"))
        out["score.ARTIFACT_CEILING"] = out["score.MAX_SCORED_ARTIFACTS"] * per_artifact
    collect = (ROOT / "bin" / "collect.py").read_text()
    found = re.search(r"^RECHECK_PER_RUN = (\d+)", collect, re.MULTILINE)
    if found:
        out["collect.RECHECK_PER_RUN"] = int(found.group(1))
    room = ROOT.parent / "technocore-conformance" / "probes" / "room-sync.sh"
    if room.exists():
        found = re.search(r'TOP_N="\$\{ROOM_TOP_N:-(\d+)\}"', room.read_text())
        if found:
            out["room-sync.ROOM_TOP_N"] = int(found.group(1))
    return out


# The register. Each entry is (bucket, source, pattern). The pattern must capture exactly the
# number it accounts for, and is matched against the whole document.
#
# FROZEN entries name the date they describe. They must never move: they record what this board
# said on a day, and rewriting them to match today's data would be falsifying the record of a
# correction rather than maintaining a number.
REGISTER: list[tuple[str, str, str]] = [
    # --- CODE: constants, checked against the source that defines them --------------------------
    ("CODE", "score.WEIGHTS.merged_pr", r"\| Merged PR to `flop-labs/technocore-chat` \| (\d+) \|"),
    ("CODE", "score.WEIGHTS.issue_closed_by_merged_pr",
     r"\| Issue you filed that a merged PR closed \| (\d+) \|"),
    ("CODE", "score.WEIGHTS.verified_proof",
     r"\| Contribution proof that \*\*verifies\*\* \| (\d+) \|"),
    ("CODE", "score.WEIGHTS.artifact_references_technocore",
     r"\| Public artifact genuinely referencing Technocore \| (\d+) \|"),
    ("CODE", "score.WEIGHTS.artifact_has_license", r"\| …that artifact has a licence \| (\d+) \|"),
    ("CODE", "score.WEIGHTS.artifact_has_description",
     r"\| …that artifact has a description \| (\d+) \|"),
    ("CODE", "score.WEIGHTS.artifact_maintained_past_first_day",
     r"\| …that artifact had commits after its first day \| (\d+) \|"),
    ("CODE", "score.MAX_SCORED_ARTIFACTS", r"At most \*\*(\w+) artifacts\*\* count per person"),
    ("CODE", "score.WEIGHTS.verified_proof",
     r"A verified proof is worth (\d+) points and is the \*\*only\*\* input"),
    ("CODE", "room-sync.ROOM_TOP_N", r"`ROOM_TOP_N` still names the position"),
    ("CODE", "score.WEIGHTS.verified_proof", r"it scores (\d+) points for everyone else"),
    ("CODE", "score.WEIGHTS.verified_proof", r"Everyone else's proof scores the full (\d+)"),
    ("CODE", "score.WEIGHTS.verified_proof",
     r"either rule now score the full (\d+) points"),
    ("CODE", "score.ARTIFACT_CEILING", r"so (\d+) points is the artifact ceiling"),
    ("CODE", "room-sync.ROOM_TOP_N", r"write-gates on the top (\d+) of this board"),
    ("CODE", "collect.RECHECK_PER_RUN", r"are re-asked — automatically, (\d+) a run"),


    # --- FROZEN: what this board said or measured on a day. These must never move. ---------------
    # Each accounts for every number in the passage it matches, because a paragraph describing one
    # past measurement is one claim, not six. The date is the day the measurement was made.
    ("FROZEN", "2026-09-08", (r"The first set scored a full artifact at 10 with a cap of three.*?"
                              r"fell from 37 to 28\.")),
    ("FROZEN", "2026-09-12", (r"canonicalisation, that 113 well-formed published proofs did not "
                              r"verify.*?and it was wrong\.")),
    ("FROZEN", "2026-09-16", (r"This paragraph asserted `all 114` for four days while the board "
                              r"said\n117,")),
    ("FROZEN", "2026-09-12", (r"It was not: 340 candidate encodings were tried against five "
                              r"signatures")),
    ("FROZEN", "2026-09-05", r"`sv` has 29 merged PRs, more than everyone else combined"),
    ("FROZEN", "2026-09-05", (r"from 2020 with 42 sibling repositories\. It topped the board with "
                              r"316 points")),
    ("FROZEN", "2026-09-05", r"\*\*Search pagination.*?when pagination was added\."),
    ("FROZEN", "2026-09-05", r"It found 35 proofs and missed\nours entirely"),
    ("FROZEN", "2026-09-12", r"canonicalisation and reporting the other 112 as failures"),
    ("FROZEN", "2026-09-06", (r"still scores zero, and 107 of\s+145 closed-unmerged pull "
                              r"requests")),
    ("FROZEN", "2026-09-16", r"GitHub caps a search at 1000 results.*?lost none in 164\."),
    ("FROZEN", "2026-09-16", r"what is new is that it now carries 100 more\n  repositories"),
    ("FROZEN", "2026-09-16", r"check by fetching about 170 proof files over the network"),
    ("FROZEN", "2026-09-16", r"Twenty-one people were tied on 13 points across ranks 45\nto 65\."),
    ("FROZEN", "2026-09-16", r"takes the allow-list from 20 `did:key`s to 29\."),
    ("FROZEN", "2026-09-16", r"the recovered scores move the\nfiftieth place to 14 points"),
    ("FROZEN", "2026-09-16", r"the live site carried 117 entries naming a verification rule"),
    ("FROZEN", "2026-09-16", r"the one that told 112 named\npeople their proofs do not verify"),
    ("FROZEN", "2026-09-05", r"omitted ~90% of the ecosystem"),
    ("FROZEN", "2026-09-16", (r'this sentence said "74th of 850" while the board published 61st '
                              r"of 874")),
    ("FROZEN", "2026-09-05", r"so it saw only the 100 most\srecently touched repositories"),
    ("FROZEN", "2026-09-05", (r"On 2026-09-05 it went from\s118 artifacts to 1016, and from 142 "
                              r"ranked people to 849")),
    ("FROZEN", "2026-09-16", (r"for four days while\nthe board published 117, and `74th of 850` "
                              r"in the disclosure while the board published 61st of 874")),
]

# Words that are numbers. The artifact cap is written "three" in the prose it belongs to.
WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
         "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def _fenced_spans(text: str) -> list[tuple[int, int]]:
    """Ranges inside ``` fences. Code samples quote real values and are not assertions."""
    spans, start = [], None
    for match in re.finditer(r"^```.*$", text, re.MULTILINE):
        if start is None:
            start = match.start()
        else:
            spans.append((start, match.end()))
            start = None
    if start is not None:
        spans.append((start, len(text)))
    return spans


def _freeze() -> int:
    """Rewrite FROZEN_DIGESTS from the file as it stands. Deliberate, never automatic."""
    text = DOC.read_text()
    body = ["FROZEN_DIGESTS = {"]
    for section in FROZEN_SECTIONS.finditer(text):
        digest = hashlib.sha256(section.group(0).encode()).hexdigest()
        body.append(f'    "{section.group("heading")}":\n        "{digest}",')
    body.append("}")
    me = pathlib.Path(__file__)
    source = me.read_text()
    replaced, count = re.subn(r"^FROZEN_DIGESTS = \{$.*?^\}$", "\n".join(body), source,
                              flags=re.DOTALL | re.MULTILINE)
    # A --freeze that quietly changes nothing would leave every section unregistered while
    # reporting success, which is this repository's signature failure. Refuse instead.
    if count != 1:
        print(f"could not rewrite FROZEN_DIGESTS: matched {count} times, expected 1",
              file=sys.stderr)
        return 1
    me.write_text(replaced)
    print(f"froze {len(body) - 2} dated sections")
    return 0


def main() -> int:
    if "--freeze" in sys.argv[1:]:
        return _freeze()
    text = DOC.read_text()
    accounted: set[tuple[int, int]] = set()
    problems: list[str] = []
    data, code = _data(), _code()

    frozen_sections = 0
    for section in FROZEN_SECTIONS.finditer(text):
        frozen_sections += 1
        heading = section.group("heading")
        digest = hashlib.sha256(section.group(0).encode()).hexdigest()
        if FROZEN_DIGESTS.get(heading) != digest:
            known = "registered" if heading in FROZEN_DIGESTS else "never registered"
            problems.append(
                f'the "{heading[:60]}" section is {known} and its text does not match the frozen '
                f"digest. These record what this board said on a day and must not move; if the "
                f"edit is deliberate, re-freeze with ./bin/check_prose.py --freeze")
            continue
        for number in NUMBER.finditer(text, *section.span()):
            accounted.add(number.span())

    for span in _fenced_spans(text):
        for found in NUMBER.finditer(text, *span):
            accounted.add(found.span())
    for pattern, _why in NOT_A_CLAIM:
        for found in pattern.finditer(text):
            for number in NUMBER.finditer(text, *found.span()):
                accounted.add(number.span())

    for bucket, source, pattern in REGISTER:
        matches = list(re.finditer(pattern, text, re.DOTALL))
        if not matches:
            problems.append(f"register entry no longer matches anything: {bucket} {source} "
                            f"-- the sentence it accounted for has changed or gone")
            continue
        for match in matches:
            if not match.groups():
                for number in NUMBER.finditer(text, *match.span()):
                    accounted.add(number.span())
                continue
            claimed = match.group(1).replace(",", "")
            claimed = WORDS.get(claimed.lower(), claimed)
            accounted.add(match.span(1))
            if bucket == "FROZEN":
                continue
            table = data if bucket == "LIVE" else code
            if source not in table:
                problems.append(f"{bucket} {source}: no such value to check against")
            elif str(table[source]) != str(claimed):
                line = text[:match.start()].count("\n") + 1
                problems.append(f"line {line}: prose says {claimed}, {source} is "
                                f"{table[source]} -- {match.group(0)[:70].strip()}")

    for number in NUMBER.finditer(text):
        if number.span() in accounted:
            continue
        line = text[:number.start()].count("\n") + 1
        context = text.splitlines()[line - 1].strip()
        problems.append(f"line {line}: {number.group(1)} is not accounted for -- {context[:90]}")

    if problems:
        print(f"{DOC.name}: {len(problems)} number(s) this file cannot vouch for\n",
              file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print("\n  Every number here must be derived from published data (LIVE), from a constant "
              "in\n  the source (CODE), or registered as a frozen historical claim with its date\n"
              "  (FROZEN). See the module docstring. A number nobody has accounted for is the way\n"
              "  this drifts back: the last one said 114 while the board published 117, for four\n"
              "  days, in the section correcting a false claim about the same people.",
              file=sys.stderr)
        return 1

    total = len(list(NUMBER.finditer(text)))
    print(f"{DOC.name}: {total} numbers, all accounted for "
          f"({len(REGISTER)} register entries, {frozen_sections} dated sections frozen by their "
          f"heading, {len(data)} live values, {len(code)} constants)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
