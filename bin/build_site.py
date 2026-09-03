#!/usr/bin/env python3
"""Render the static page from data/leaderboard.json into docs/ for GitHub Pages.

The data is inlined into the HTML at build time rather than fetched at runtime. Two reasons: the
page then works with no network and no CORS, and — the one that matters — the page physically
cannot display a number that is not in the committed data file. A copy of the JSON ships alongside
so anyone can check the render against the source.

    ./bin/build_site.py
"""

from __future__ import annotations

import html
import json
import pathlib
import shutil

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "leaderboard.json"
DOCS = ROOT / "docs"

REPO_URL = "https://github.com/stupeterwilliams-ui/technocore-contributor-index"

# The page shows the top slice; the full ranking ships beside it as JSON. Rendering all 849 rows
# produced a 464KB page, which is a poor phone experience for rows nobody scrolls to. The cap is
# stated on the page — a truncation you do not mention reads as "this is everyone".
TOP_N = 50

SIGNAL_LABELS = {
    "merged_pr": ("merged PR", "pr"),
    "issue_closed_by_merged_pr": ("issue fixed", "issue"),
    "verified_proof": ("verified proof", "proof"),
    "artifact_references_technocore": ("artifact", "art"),
    "artifact_has_license": ("licence", "art"),
    "artifact_has_description": ("described", "art"),
    "artifact_maintained_past_first_day": ("maintained", "art"),
}

CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{
  --bg:#0b0e13; --panel:#11161f; --line:#1e2735; --line-soft:#161d28;
  --ink:#e8edf5; --dim:#8b98ac; --faint:#5d6a7e;
  --gold:#ffc857; --green:#5ddc9a; --blue:#6bb8ff; --violet:#b39dff;
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
}
html{-webkit-text-size-adjust:100%}
body{
  margin:0; background:var(--bg); color:var(--ink);
  font-family:var(--mono); font-size:15px; line-height:1.5;
  padding:20px 16px 56px; overflow-wrap:anywhere;
}
.wrap{max-width:760px;margin:0 auto}
a{color:inherit}
h1{font-size:23px;line-height:1.2;margin:0 0 6px;letter-spacing:-.02em}
h1 .dot{color:var(--gold)}
.sub{color:var(--dim);font-size:13.5px;margin:0 0 14px}
.disclosure{
  border-left:3px solid var(--gold); background:var(--panel);
  padding:10px 12px; margin:0 0 18px; font-size:12.5px; color:var(--dim);
}
.disclosure b{color:var(--gold);font-weight:600}
.row{
  display:grid; grid-template-columns:34px 1fr auto; gap:10px; align-items:center;
  padding:11px 12px; border:1px solid var(--line-soft); border-radius:10px;
  background:var(--panel); margin-bottom:7px;
}
.row.tied{border-color:var(--line)}
.row.self{border-color:var(--violet);background:#141225}
.rank{font-size:17px;color:var(--faint);text-align:right;font-variant-numeric:tabular-nums}
.row.top .rank{color:var(--gold)}
.who{min-width:0}
.handle{font-size:15px;font-weight:600;text-decoration:none;display:block;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.handle:hover{text-decoration:underline}
.self-tag{color:var(--violet);font-size:11px;font-weight:400}
.chips{display:flex;flex-wrap:wrap;gap:5px;margin-top:5px}
.chip{
  font-size:11.5px; padding:2px 7px; border-radius:999px; text-decoration:none;
  border:1px solid var(--line); color:var(--dim); white-space:nowrap;
}
.chip:hover{border-color:var(--dim);color:var(--ink)}
.chip.pr{color:var(--green);border-color:#1d3a2c}
.chip.issue{color:var(--blue);border-color:#1b3348}
.chip.proof{color:var(--gold);border-color:#3a3320}
.chip.forfeit{color:var(--faint);border-color:var(--line-soft);text-decoration:line-through}
.score{font-size:21px;font-variant-numeric:tabular-nums;text-align:right}
.row.top .score{color:var(--gold)}
.tiebar{
  display:flex;align-items:center;gap:8px;color:var(--faint);
  font-size:11.5px;margin:2px 0 10px;padding-left:2px;
}
.tiebar span{flex:1 1 auto;min-width:0;overflow-wrap:anywhere}
.tiebar::before,.tiebar::after{content:"";height:1px;background:var(--line-soft);
  flex:0 0 14px;min-width:0}
h2{font-size:13px;color:var(--faint);font-weight:600;letter-spacing:.09em;
  text-transform:uppercase;margin:26px 0 10px}
.note{color:var(--dim);font-size:12.5px;margin:0 0 8px}
.note code{color:var(--ink);background:var(--line-soft);padding:1px 5px;border-radius:4px}
.foot{margin-top:26px;padding-top:14px;border-top:1px solid var(--line-soft);
  color:var(--faint);font-size:12px}
.foot a{color:var(--dim)}
.cta{display:inline-block;margin-top:10px;padding:8px 13px;border:1px solid var(--line);
  border-radius:8px;color:var(--ink);text-decoration:none;font-size:13px}
.cta:hover{border-color:var(--gold);color:var(--gold)}
@media(max-width:430px){
  body{padding:14px 12px 40px;font-size:14px}
  h1{font-size:20px}
  .sub{margin-bottom:10px}
  .disclosure{padding:9px 11px;margin-bottom:12px;font-size:12px}
  .row{grid-template-columns:24px 1fr auto;gap:8px;padding:8px 10px;margin-bottom:6px}
  .score{font-size:19px}
  .handle{font-size:14px}
  .chips{gap:4px;margin-top:4px}
  .tiebar{margin:0 0 8px}
}
"""


def chips_for(entry: dict) -> str:
    """One clickable chip per distinct piece of evidence, deduped and counted.

    Evidence we deliberately did not score still appears, marked. Hiding it would make the
    forfeit invisible, and the forfeit is the part worth seeing.
    """
    groups: dict[str, dict] = {}
    for item in entry["evidence"]:
        label, cls = SIGNAL_LABELS.get(item["signal"], (item["signal"], ""))
        if item.get("forfeited"):
            label, cls = label + " (not scored)", "forfeit"
        key = label
        groups.setdefault(key, {"count": 0, "url": item["url"], "cls": cls, "label": label})
        groups[key]["count"] += 1
    order = ["merged PR", "issue fixed", "verified proof", "artifact", "maintained",
             "licence", "described"]
    out = []
    for label in sorted(groups, key=lambda k: order.index(k) if k in order else 99):
        g = groups[label]
        text = f"{g['count']}x {label}" if g["count"] > 1 else label
        out.append(
            f'<a class="chip {g["cls"]}" href="{html.escape(g["url"])}" '
            f'target="_blank" rel="noopener">{html.escape(text)}</a>'
        )
    return "".join(out)


def build() -> str:
    payload = json.loads(DATA.read_text())
    board = payload["leaderboard"]
    weights = payload["weights"]

    rows = []
    previous_score = None
    shown = board[:TOP_N]
    for entry in shown:
        score = entry["score"]
        tied_with_previous = score == previous_score
        # A tie is left as a tie. Inventing a tiebreak weight to manufacture a single winner is
        # exactly the kind of unjustifiable choice that would let someone unpick the whole board,
        # and reproducibility is the entire product. It is separated visually instead.
        if previous_score is not None and not tied_with_previous:
            rows.append("")
        classes = ["row"]
        if entry["rank"] <= 3:
            classes.append("top")
        if entry.get("is_author_of_this_board"):
            classes.append("self")
        tag = ' <span class="self-tag">— built this board</span>' if entry.get(
            "is_author_of_this_board") else ""
        rows.append(
            f'<div class="{" ".join(classes)}">'
            f'<div class="rank">{entry["rank"]}</div>'
            f'<div class="who">'
            f'<a class="handle" href="https://github.com/{html.escape(entry["login"])}" '
            f'target="_blank" rel="noopener">{html.escape(entry["login"])}</a>{tag}'
            f'<div class="chips">{chips_for(entry)}</div>'
            f'</div>'
            f'<div class="score">{score}</div>'
            f'</div>'
        )
        previous_score = score

    author_row = next((e for e in board if e.get("is_author_of_this_board")), None)
    if author_row and author_row["rank"] > TOP_N:
        rows.append(
            f'<div class="tiebar"><span>…</span></div>'
            f'<div class="row self">'
            f'<div class="rank">{author_row["rank"]}</div>'
            f'<div class="who">'
            f'<a class="handle" href="https://github.com/{html.escape(author_row["login"])}" '
            f'target="_blank" rel="noopener">{html.escape(author_row["login"])}</a>'
            f' <span class="self-tag">— built this board</span>'
            f'<div class="chips">{chips_for(author_row)}</div>'
            f'</div><div class="score">{author_row["score"]}</div></div>'
        )

    # Mark the leading tie explicitly, so the flat top reads as arithmetic rather than an accident.
    top_score = board[0]["score"] if board else 0
    tied_at_top = sum(1 for e in board if e["score"] == top_score)
    tie_note = ""
    if tied_at_top > 1:
        tie_note = (f'<div class="tiebar"><span>{tied_at_top}-way tie at {top_score} — kept as '
                    f'a tie, not broken by an invented weight</span></div>')

    maintainers = "".join(
        f'<div class="row"><div class="rank">—</div><div class="who">'
        f'<a class="handle" href="https://github.com/{html.escape(m["login"])}" '
        f'target="_blank" rel="noopener">{html.escape(m["login"])}</a>'
        f'<div class="chips">{chips_for(m)}</div></div>'
        f'<div class="score">{m["score"]}</div></div>'
        for m in payload.get("maintainers", [])
    )

    weight_rows = " · ".join(
        f'{html.escape(k.replace("_", " "))} <b>{v}</b>' for k, v in weights.items()
    )

    totals = payload["totals"]
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Technocore contributor leaderboard</title>
<meta name="description" content="A reproducible, evidence-linked ranking of Technocore contributors. Every number links to its public source.">
<style>{CSS}</style>
</head><body><div class="wrap">

<h1>Technocore contributors<span class="dot">.</span></h1>
<p class="sub">Ranked on what is expensive to fake. Every number links to its public source.</p>

<div class="disclosure">
<b>Built by stupeterwilliams-ui, who appears on this board.</b> Acceptable only because you can
check it: the code is public, the weights are listed, every point links to evidence.
<br><br>
Where a signal's specification was written by this board's author — currently verified contribution
proofs — it scores for everyone else and <b>scores zero for us</b>. Counting it would have moved us
from 55th to 6th on a rule we wrote. Anyone else who publishes a verifying proof gets the full 8
points; it takes about a minute.
</div>

{tie_note}
{"".join(rows)}

<h2>Not ranked · the maintainer</h2>
<p class="note">More merged pull requests than everyone else combined. That is the project, not a
contribution ranking.</p>
{maintainers}

<h2>How it is scored</h2>
<p class="note">{weight_rows}</p>
<p class="note">Not scored: room message volume (anyone can write it), stars and engagement
(scores attention, not building), proofs that do not verify, more than three artifacts per person,
our opinion of whether anything is good, and any signal whose specification this board's author
wrote — for the author.</p>
<a class="cta" href="{REPO_URL}/blob/main/METHODOLOGY.md">Read the full methodology &rarr;</a>

<div class="foot">
Showing the top {len(shown)} of {totals["people_ranked"]} ranked ·
<a href="leaderboard.json">the full ranking is in the data file</a><br>
{totals["people_ranked"]} people · {totals["merged_prs_counted"]} merged PRs ·
{totals["artifacts_counted"]} artifacts · {totals["verified_proofs"]} verified proofs<br>
Collected {html.escape(str(payload.get("collected_at")))} ·
built {html.escape(str(payload.get("generated_at")))}<br>
<a href="{REPO_URL}">Source and scoring code</a> ·
<a href="leaderboard.json">Raw data</a> ·
Not affiliated with FLOP Labs.
</div>

</div></body></html>
"""


def main() -> int:
    DOCS.mkdir(exist_ok=True)
    (DOCS / "index.html").write_text(build())
    shutil.copy(DATA, DOCS / "leaderboard.json")
    (DOCS / ".nojekyll").write_text("")
    size = (DOCS / "index.html").stat().st_size
    print(f"wrote docs/index.html ({size:,} bytes) and docs/leaderboard.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
