"""Render a Finding as a single self-contained HTML research note.
Every evidence row is a clickable link to its source; unverified quotes never appear."""
from __future__ import annotations
import html
import json
from ..models import Finding


def _render_numbers(numbers: dict) -> str:
    e = html.escape
    if not numbers:
        return "<p><i>No quantitative anomaly computed.</i></p>"
    rows = []
    for m, data in numbers.items():
        if isinstance(data, dict) and "periods" in data and "values" in data:
            periods = ", ".join(str(p) for p in data["periods"][-4:])
            vals = ", ".join(f"{v:g}" if isinstance(v, (int, float)) else str(v) for v in data["values"][-4:])
            slope = data.get("slope", 0.0)
            consistency = data.get("consistency", 0.0)
            rows.append(
                f"<tr><td><b>{e(m)}</b></td><td>{e(periods)}</td><td>{e(vals)}</td>"
                f"<td>{slope:.3f}</td><td>{consistency * 100:.1f}%</td></tr>"
            )
    if rows:
        table = (
            "<table><tr><th>Metric</th><th>Recent Periods</th><th>Values</th><th>Slope</th><th>Consistency</th></tr>"
            + "".join(rows) + "</table>"
        )
        extra = []
        if "price_vs_volume_split" in numbers:
            extra.append(f"<p><b>Price vs Volume Split:</b> {e(json.dumps(numbers['price_vs_volume_split']))}</p>")
        return table + "".join(extra)
    return f"<pre>{e(json.dumps(numbers, indent=2, default=str))}</pre>"


def render(f: Finding) -> str:
    e = html.escape
    ev_rows = "".join(
        f"<tr><td>{e(it.stance)}</td><td>{e(it.summary)}</td>"
        + "<td>" + "<br>".join(f'<a href="{e(p.url)}">{e(p.title or p.url)}</a><blockquote>{e(p.quote)}</blockquote>' for p in it.passages if p.verified)
        + "</td></tr>" for it in f.evidence)
    tl = "".join(f"<li><b>{e(a)}</b> — {e(b)}</li>" for a, b in f.timeline)
    why = "".join(f"<li>{e(w)}</li>" for w in f.why_it_matters)
    num_section = _render_numbers(f.numbers)
    return f"""<!doctype html><meta charset=utf-8><title>{e(f.company)} — discovery</title>
<style>body{{font:15px/1.5 system-ui;max-width:860px;margin:2rem auto;padding:0 1rem}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccc;padding:6px;vertical-align:top}}
blockquote{{margin:4px 0;color:#444;font-size:13px}}.tag{{padding:2px 8px;border-radius:8px;background:#eee}}</style>
<h1>{e(f.company)}</h1>
<h2>Discovery</h2><p>{e(f.discovery)}</p>
<h2>Why it matters</h2><ul>{why}</ul>
<h2>Timeline</h2><ul>{tl}</ul>
<h2>Evidence trail</h2><table><tr><th>Stance</th><th>Finding</th><th>Source &amp; verified quote</th></tr>{ev_rows}</table>
<h2>Numbers</h2>{num_section}
<h2>Strongest counterargument</h2><p>{e(f.counterargument)}</p>
<h2>Falsification condition</h2><p>{e(f.falsification)}</p>
<h2>Evidence strength: <span class=tag>{e(f.strength)}</span></h2><p>{e(f.strength_reasoning)}</p>
<p><small>Research output, not investment advice.</small></p>"""
