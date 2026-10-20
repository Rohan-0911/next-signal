"""Usage: python run.py "<company name>"  ->  out/<company>.html"""
import pathlib
import sys
from nextsignal.agent.pipeline import run
from nextsignal.report.render import render

if __name__ == "__main__":
    company = " ".join(sys.argv[1:]) or input("Company: ")
    finding = run(company)
    out = pathlib.Path("out"); out.mkdir(exist_ok=True)
    path = out / (company.replace(" ", "_") + ".html")
    path.write_text(render(finding), encoding="utf-8", errors="ignore")
    print(f"Wrote {path}  |  strength: {finding.strength}")
