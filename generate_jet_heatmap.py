#!/usr/bin/env python3
"""
Generates an animated "jet over contribution grid" SVG using a GitHub
user's REAL contribution calendar (last 34 weeks, same layout as
GitHub's own heatmap: 34 columns x 7 rows).

Env vars:
  GH_USERNAME  - GitHub login to fetch contributions for (optional, uses mock if omitted)
  GH_TOKEN     - token with access to GraphQL API (optional, uses mock if omitted)
  OUTPUT_PATH  - path to save generated SVG (default: dist/github-jet.svg)
"""

import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

USERNAME = os.getenv("GH_USERNAME")
TOKEN = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
OUTPUT = os.getenv("OUTPUT_PATH", "dist/github-jet.svg")

COLS = 34
ROWS = 7
CELL = 11
STEP = 14
GRID_X = 20
GRID_Y = 15
WIDTH = 513
HEIGHT = 170
JET_X_START = 35
JET_X_END = 478
LOOP_DUR = 20
MAX_TARGETS = 12
FLASH_COLOR = "#39d353"
BULLET_COLOR = "#7ee787"
BLAST_COLOR = "#56d364"
PAD_Y = 128

QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        weeks {
          contributionDays {
            date
            contributionCount
            color
          }
        }
      }
    }
  }
}
"""

def mock_weeks():
    colors = ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"]
    weeks = []
    for w in range(34):
        days = []
        for d in range(7):
            seed = (w * 7 + d) % 13
            count = 12 if seed == 0 else 4 if seed < 3 else 1 if seed < 7 else 0
            level = 0 if count == 0 else 1 if count < 2 else 2 if count < 5 else 3 if count < 10 else 4
            days.append({
                "date": f"2026-W{w:02d}-{d}",
                "contributionCount": count,
                "color": colors[level]
            })
        weeks.append({"contributionDays": days})
    return weeks

def fetch_weeks():
    if not USERNAME or not TOKEN:
        print("[INFO] GH_USERNAME or GH_TOKEN missing. Using mock data preview...")
        return mock_weeks()

    url = "https://api.github.com/graphql"
    payload = json.dumps({"query": QUERY, "variables": {"login": USERNAME}}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"bearer {TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "Python-GitHub-Jet-Heatmap",
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if "errors" in data:
                raise RuntimeError(json.dumps(data["errors"]))
            return data["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if hasattr(e, 'read') else "<no body>"
        try:
            parsed = json.loads(body)
            details = parsed.get("message", body)
        except Exception:
            details = body

        if e.code == 401:
            raise RuntimeError(
                f"GitHub API 401 Unauthorized ('Bad credentials'). Details: {details}.\n"
                f"Check that GH_PAT repository secret is set with a valid token or github.token has appropriate permissions."
            )
        raise RuntimeError(f"GitHub API error {e.code}: {details}")

def build_cells(weeks):
    recent = weeks[-COLS:]
    pad_count = COLS - len(recent)
    padded = [
        {
            "contributionDays": [
                {"contributionCount": 0, "color": "#161b22", "date": None}
                for _ in range(ROWS)
            ]
        }
        for _ in range(pad_count)
    ] + recent

    cells = []
    for col, week in enumerate(padded):
        for row, day in enumerate(week["contributionDays"]):
            cells.append({
                "col": col,
                "row": row,
                "x": GRID_X + col * STEP,
                "y": GRID_Y + row * STEP,
                "color": day.get("color") or "#161b22",
                "count": day.get("contributionCount", 0),
                "date": day.get("date"),
            })
    return cells

def pick_targets(cells):
    active = [c for c in cells if c["count"] > 0]
    sorted_active = sorted(active, key=lambda c: c["count"], reverse=True)
    targets = sorted_active[:MAX_TARGETS]
    return sorted(targets, key=lambda c: (c["col"], c["row"]))

def key_time_for_col(col, direction):
    span = 0.46
    t = 0.02 + (col / (COLS - 1)) * span
    return t if direction == "forward" else 1.0 - t

def fmt(n):
    return f"{n:.4f}".rstrip('0').rstrip('.') if '.' in f"{n:.4f}" else f"{n:.4f}"

def build_grid(cells, targets):
    target_keys = {f"{t['col']}-{t['row']}" for t in targets}
    svg_parts = []
    for c in cells:
        key = f"{c['col']}-{c['row']}"
        if key not in target_keys:
            svg_parts.append(
                f'<rect x="{c["x"]:.2f}" y="{c["y"]:.2f}" width="{CELL}" height="{CELL}" rx="2" ry="2" fill="{c["color"]}"/>\n'
            )
            continue

        t_fwd = key_time_for_col(c["col"], "forward")
        t_back = key_time_for_col(c["col"], "backward")
        t1, t2 = min(t_fwd, t_back), max(t_fwd, t_back)
        dur = 0.006

        rect_str = (
            f'<rect x="{c["x"]:.2f}" y="{c["y"]:.2f}" width="{CELL}" height="{CELL}" rx="2" ry="2" fill="{c["color"]}">'
            f'<animate attributeName="fill" dur="{LOOP_DUR}s" repeatCount="indefinite" '
            f'keyTimes="0;{fmt(t1)};{fmt(t1 + dur)};{fmt(t2)};{fmt(t2 + dur)};1" '
            f'values="{c["color"]};{c["color"]};{FLASH_COLOR};{c["color"]};{FLASH_COLOR};{c["color"]}"/>'
            f'</rect>\n'
        )
        svg_parts.append(rect_str)
    return "".join(svg_parts)

def build_bullets_and_blasts(targets):
    bullets = []
    blasts = []
    dur = 0.006

    for direction in ["forward", "backward"]:
        ordered = targets if direction == "forward" else list(reversed(targets))
        for c in ordered:
            t = key_time_for_col(c["col"], direction)
            rise = t - dur * 3
            arrive = t
            fade_end = t + dur
            cx = fmt(c["x"] + CELL / 2)
            target_y = fmt(c["y"] + CELL / 2)

            bullets.append(
                f'<circle cx="{cx}" cy="{PAD_Y}" r="2.4" fill="{BULLET_COLOR}">'
                f'<animate attributeName="cy" dur="{LOOP_DUR}s" repeatCount="indefinite" '
                f'keyTimes="0;{fmt(rise)};{fmt(arrive)};1" values="{PAD_Y};{PAD_Y};{target_y};{target_y}"/>'
                f'<animate attributeName="opacity" dur="{LOOP_DUR}s" repeatCount="indefinite" '
                f'keyTimes="0;{fmt(rise)};{fmt(arrive)};{fmt(fade_end)};1" values="0;1;1;0;0"/>'
                f'</circle>\n'
            )

            blasts.append(
                f'<circle cx="{cx}" cy="{target_y}" r="0" fill="none" stroke="{BLAST_COLOR}" stroke-width="1.6" opacity="0">'
                f'<animate attributeName="r" dur="{LOOP_DUR}s" repeatCount="indefinite" '
                f'keyTimes="0;{fmt(arrive)};{fmt(arrive + dur * 3)};1" values="0;1;9;9"/>'
                f'<animate attributeName="opacity" dur="{LOOP_DUR}s" repeatCount="indefinite" '
                f'keyTimes="0;{fmt(arrive)};{fmt(arrive + dur * 3)};1" values="0;1;1;0"/>'
                f'</circle>\n'
            )

    return "".join(bullets), "".join(blasts)

def build_stars():
    pts = [
        [8, 20, 1.2], [8, 60, 1.6], [8, 100, 2.0],
        [505, 25, 1.2], [505, 70, 1.6], [505, 110, 2.0],
        [30, 164, 1.2], [483, 164, 1.6],
    ]
    stars = [
        f'<circle cx="{x}" cy="{y}" r="1.1" fill="#8b949e"><animate attributeName="opacity" values="0.2;1;0.2" dur="{dur}s" repeatCount="indefinite"/></circle>'
        for x, y, dur in pts
    ]
    return "\n".join(stars)

def build_jet():
    return f"""<g id="jet">
  <g transform="translate(0,0)">
    <polygon points="0,-16 8,6 4,3 -4,3 -8,6" fill="#58a6ff" stroke="#1f6feb" stroke-width="1"/>
    <polygon points="-8,6 -14,12 -4,7" fill="#388bfd"/>
    <polygon points="8,6 14,12 4,7" fill="#388bfd"/>
    <circle cx="0" cy="-6" r="2.2" fill="#c9e6ff"/>
    <polygon points="-3,7 3,7 0,15" fill="#f0883e">
      <animate attributeName="opacity" values="0.5;1;0.6;1" dur="0.18s" repeatCount="indefinite"/>
    </polygon>
  </g>
  <animateTransform attributeName="transform" attributeType="XML" type="translate"
    dur="{LOOP_DUR}s" repeatCount="indefinite"
    keyTimes="0;0.5;1"
    values="{JET_X_START:.2f},140.00;{JET_X_END:.2f},140.00;{JET_X_START:.2f},140.00"/>
</g>"""

def build_svg(weeks):
    cells = build_cells(weeks)
    targets = pick_targets(cells)
    bullets, blasts = build_bullets_and_blasts(targets)

    return f"""<svg viewBox="0 0 {WIDTH} {HEIGHT}" xmlns="http://www.w3.org/2000/svg">
<rect x="0" y="0" width="{WIDTH}" height="{HEIGHT}" fill="#0d1117"/>
{build_stars()}
<g id="grid">
{build_grid(cells, targets)}</g>
<g id="bullets">
{bullets}</g>
<g id="blasts">
{blasts}</g>
{build_jet()}
</svg>"""

def main():
    if USERNAME:
        print(f"Fetching contributions for {USERNAME}...")
    weeks = fetch_weeks()
    svg = build_svg(weeks)
    out_path = Path(OUTPUT).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(svg, encoding="utf-8")
    print(f"Successfully wrote {out_path}")

if __name__ == "__main__":
    main()
