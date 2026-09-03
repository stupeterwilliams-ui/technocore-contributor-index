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
import subprocess

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
  --bg:#000; --ink:#fff;
  --line:rgba(255,255,255,0.12);
  --line-soft:rgba(255,255,255,0.07);
  --dim:rgba(255,255,255,0.62);
  --faint:rgba(255,255,255,0.38);
  --panel:rgba(255,255,255,0.035);
  --display:'Bebas Neue','Space Grotesk',-apple-system,sans-serif;
  --body:'Space Grotesk',-apple-system,BlinkMacSystemFont,sans-serif;
}
html{-webkit-text-size-adjust:100%}
body{
  margin:0; background:var(--bg); color:var(--ink);
  font-family:var(--body); font-size:15px; line-height:1.5;
  padding:26px 20px 60px; overflow-wrap:anywhere;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:760px;margin:0 auto}
a{color:inherit}
h1{
  font-family:var(--display); font-weight:400;
  font-size:clamp(2.2rem,7.5vw,3.4rem); line-height:0.92;
  letter-spacing:3px; text-transform:uppercase; margin:0 0 10px;
}
.sub{color:var(--dim);font-size:13.5px;margin:0 0 14px;max-width:52ch}
.disclosure{
  border-top:1px solid var(--line); border-bottom:1px solid var(--line);
  padding:12px 0; margin:0 0 16px; font-size:12.5px; color:var(--dim);
}
.disclosure b{color:var(--ink);font-weight:500}
.row{
  display:grid; grid-template-columns:34px 1fr 56px; gap:12px; align-items:center;
  padding:9px 0; border-bottom:1px solid var(--line-soft);
}
.row.self{background:var(--panel);padding-left:10px;padding-right:10px;
  border-bottom:1px solid var(--line)}
.rank{
  font-family:var(--display); font-size:20px; line-height:1;
  color:var(--faint); text-align:right; letter-spacing:1px;
}
.row.top .rank{color:var(--ink)}
.who{min-width:0}
.handle{font-size:14.5px;font-weight:500;text-decoration:none;display:block;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;letter-spacing:0.2px}
.handle:hover{text-decoration:underline}
.self-tag{color:var(--faint);font-size:11px;font-weight:400;letter-spacing:0.4px;
  text-transform:uppercase}
.chips{font-size:11.5px;color:var(--faint);line-height:1.45}
.ev{color:var(--faint);text-decoration:none;border-bottom:1px solid transparent}
.ev:hover{color:var(--ink);border-bottom-color:var(--line)}
.ev.pr{color:var(--dim)}
.ev.forfeit{text-decoration:line-through}
.evsep{color:rgba(255,255,255,0.18)}
.score{font-family:var(--display);font-size:30px;line-height:1;text-align:right;
  letter-spacing:1px;color:var(--dim)}
.row.top .score{color:var(--ink)}
.tiebar{display:flex;align-items:center;gap:10px;color:var(--faint);
  font-size:11px;margin:14px 0 6px;letter-spacing:0.4px;text-transform:uppercase}
.tiebar span{flex:1 1 auto;min-width:0}
.tiebar::after{content:"";height:1px;background:var(--line-soft);flex:0 0 40px}
h2{font-family:var(--display);font-size:20px;color:var(--ink);font-weight:400;
  letter-spacing:2px;text-transform:uppercase;margin:36px 0 12px}
.note{color:var(--dim);font-size:13px;margin:0 0 10px;max-width:62ch}
.foot{margin-top:34px;padding-top:16px;border-top:1px solid var(--line);
  color:var(--faint);font-size:12px}
.foot a{color:var(--dim)}
.cta{display:inline-block;margin-top:12px;padding:10px 16px;border:1px solid var(--line);
  color:var(--ink);text-decoration:none;font-size:12px;letter-spacing:1px;
  text-transform:uppercase}
.cta:hover{border-color:var(--ink)}
@media(max-width:430px){
  body{padding:20px 14px 44px;font-size:14px}
  .row{grid-template-columns:26px 1fr 48px;gap:9px;padding:8px 0}
  .rank{font-size:17px}
  .score{font-size:25px}
  .handle{font-size:14px}
  .chips{font-size:11px}
  .disclosure{font-size:12px;padding:10px 0;margin-bottom:14px}
  h1{font-size:2rem}
}
"""


def chips_for(entry: dict) -> str:
    """Evidence as one compact line of links.

    This was a grid of uppercase boxes, three to five per row. It buried the two things a
    leaderboard exists to show — who is ahead, and by how much — under the supporting detail, and
    pushed the visible list down to five people. The links still have to be here (a number that
    cannot be traced is not evidence), so they get one quiet line instead of the row.
    """
    groups: dict[str, dict] = {}
    for item in entry["evidence"]:
        label, cls = SIGNAL_LABELS.get(item["signal"], (item["signal"], ""))
        if item.get("forfeited"):
            label, cls = label + " (not scored)", "forfeit"
        groups.setdefault(label, {"count": 0, "url": item["url"], "cls": cls})
        groups[label]["count"] += 1
    order = ["merged PR", "issue fixed", "verified proof", "verified proof (not scored)",
             "artifact", "maintained", "licence", "described"]
    parts = []
    for label in sorted(groups, key=lambda k: order.index(k) if k in order else 99):
        g = groups[label]
        text = f"{g['count']}\u00d7 {label}" if g["count"] > 1 else label
        parts.append(
            f'<a class="ev {g["cls"]}" href="{html.escape(g["url"])}" '
            f'target="_blank" rel="noopener">{html.escape(text)}</a>'
        )
    return '<span class="evsep"> · </span>'.join(parts)


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
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Space+Grotesk:wght@400;500&display=swap" rel="stylesheet">
<title>Technocore contributor leaderboard</title>
<meta name="description" content="A reproducible, evidence-linked ranking of Technocore contributors. Every number links to its public source.">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Put Me to Work">
<meta property="og:url" content="https://technocore.puttowork.co/">
<meta property="og:title" content="Technocore contributor index">
<meta property="og:description" content="{totals['people_ranked']} people ranked on what is expensive to fake — merged PRs, issues that led to a fix, real artifacts, proofs that verify. Every number links to its public source.">
<meta property="og:image" content="https://technocore.puttowork.co/card.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Technocore contributor index">
<meta name="twitter:description" content="{totals['people_ranked']} people ranked on evidence. Every number links to its public source, and the scoring code is open.">
<meta name="twitter:image" content="https://technocore.puttowork.co/card.png">
<style>{CSS}</style>
</head><body><div class="wrap">

<h1>Technocore<br>contributors</h1>
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


CARD_HTML = """<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Space+Grotesk:wght@400;500&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{width:1200px;height:630px;background:#000;color:#fff;
 font-family:'Space Grotesk',sans-serif;display:flex;flex-direction:column;
 justify-content:center;padding:70px 80px;overflow:hidden}}
h1{{font-family:'Bebas Neue',sans-serif;font-size:104px;line-height:0.88;
 letter-spacing:4px;text-transform:uppercase;margin-bottom:26px}}
.stat{{font-family:'Bebas Neue',sans-serif;font-size:150px;line-height:0.85;letter-spacing:3px}}
.stat small{{font-family:'Space Grotesk',sans-serif;font-size:26px;letter-spacing:0;
 color:rgba(255,255,255,0.62);display:block;margin-top:10px;font-weight:400}}
.row{{display:flex;gap:96px;align-items:flex-end;margin:14px 0 30px}}
.rule{{height:1px;background:rgba(255,255,255,0.18);margin:6px 0 26px}}
.foot{{display:flex;justify-content:space-between;align-items:baseline;
 color:rgba(255,255,255,0.62);font-size:25px}}
.foot b{{color:#fff;font-weight:500}}
</style></head><body>
<h1>Technocore<br>contributors</h1>
<div class="rule"></div>
<div class="row">
  <div class="stat">{ranked}<small>people ranked on evidence</small></div>
  <div class="stat">{verified}<small>of {proofs} published proofs verify</small></div>
</div>
<div class="foot"><span><b>technocore.puttowork.co</b></span>
<span>every number links to its source</span></div>
</body></html>"""

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def build_card() -> bool:
    """Render the social card with the current numbers.

    Regenerated every build on purpose: a card is the first and often only thing anyone sees of
    this, and one showing last week's totals beside a page showing this week's is the same
    stale-data failure the hourly refresh exists to prevent. Best effort — if Chrome is missing
    the previous card stays, which is better than shipping none.
    """
    if not pathlib.Path(CHROME).exists():
        return False
    payload = json.loads(DATA.read_text())
    proofs = json.loads((ROOT / "data" / "raw" / "proofs.json").read_text())
    html_path = ROOT / "state" / "og-card.html"
    html_path.parent.mkdir(exist_ok=True)
    html_path.write_text(CARD_HTML.format(
        ranked=len(payload["leaderboard"]),
        verified=sum(1 for p in proofs if p.get("verifies")),
        proofs=len(proofs),
    ))
    result = subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         "--virtual-time-budget=6000", f"--screenshot={DOCS / 'card.png'}",
         "--window-size=1200,630", f"file://{html_path}"],
        capture_output=True, timeout=180, check=False,
    )
    return (DOCS / "card.png").exists() and result.returncode == 0


def main() -> int:
    DOCS.mkdir(exist_ok=True)
    (DOCS / "index.html").write_text(build())
    shutil.copy(DATA, DOCS / "leaderboard.json")
    (DOCS / ".nojekyll").write_text("")
    print("  social card:", "rendered" if build_card() else "skipped (Chrome unavailable)")
    # Pages needs CNAME present in the published directory. The hourly refresh rewrites docs/,
    # so emitting it here is what stops the custom domain silently detaching on the next run.
    (DOCS / "CNAME").write_text("technocore.puttowork.co\n")
    size = (DOCS / "index.html").stat().st_size
    print(f"wrote docs/index.html ({size:,} bytes) and docs/leaderboard.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
