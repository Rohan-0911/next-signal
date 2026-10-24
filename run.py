"""Usage:
  python run.py "<company name>"            run the agent, write out/<company>_<timestamp>.html + .json
  python run.py --replay "<company name>"   re-render the most recent saved run (demo safety net)

A failed or refused run never overwrites the latest good report: out/<company>.html is only
replaced when the new run produced an actual finding.
"""
import json
import pathlib
import socket
import sys
import time

OUT = pathlib.Path("out")


def preflight() -> bool:
    ok = True
    for host, fatal in (("generativelanguage.googleapis.com", True), ("www.screener.in", False)):
        try:
            socket.getaddrinfo(host, 443)
        except OSError:
            print(f"[preflight] cannot resolve {host}" + (" - LLM unreachable" if fatal else " - numeric spine unavailable"))
            ok = ok and not fatal
    return ok


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    company = " ".join(args) or input("Company: ")
    slug = company.replace(" ", "_")
    OUT.mkdir(exist_ok=True)
    from nextsignal.report.render import render

    if "--replay" in sys.argv:
        from nextsignal.models import finding_from_dict
        saved = sorted(OUT.glob(f"{slug}_*.json"))
        if not saved:
            sys.exit(f"No saved run for {company}")
        f = finding_from_dict(json.loads(saved[-1].read_text(encoding="utf-8")))
        path = OUT / f"{slug}_replay.html"
        path.write_text(render(f), encoding="utf-8")
        print(f"Replayed {saved[-1].name} -> {path}")
        return

    if not preflight():
        sys.exit("Network problem: fix your connection (try a phone hotspot) and rerun. Nothing was written.")
    from nextsignal.agent.pipeline import run
    try:
        finding = run(company)
    except Exception as e:
        sys.exit(f"Run failed: {str(e)[:300]}\nNothing was written; previous reports are untouched.")

    stamp = time.strftime("%Y%m%d_%H%M%S")
    html = render(finding)
    (OUT / f"{slug}_{stamp}.html").write_text(html, encoding="utf-8")
    (OUT / f"{slug}_{stamp}.json").write_text(json.dumps(finding.to_dict(), default=str, indent=1), encoding="utf-8")
    refused = finding.discovery.startswith("No discovery reported")
    latest = OUT / f"{slug}.html"
    if not refused or not latest.exists():
        latest.write_text(html, encoding="utf-8")
    print(f"Wrote out/{slug}_{stamp}.html | strength: {finding.strength}" + (" | REFUSED (kept previous report)" if refused and latest.exists() else ""))


if __name__ == "__main__":
    main()
