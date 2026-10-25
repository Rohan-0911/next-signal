"""Run the agent on many companies and write out/eval.csv.  Usage: python scripts/batch.py"""
import csv, json, os, pathlib, subprocess, sys, time

COMPANIES = [
    "Hindustan Unilever", "ITC", "Nestle India", "Britannia Industries", "Dabur India",
    "Tata Consumer Products", "Marico", "Godrej Consumer Products", "Colgate Palmolive India",
    "Titan Company", "Trent", "Asian Paints",
]
OUT = pathlib.Path("out")
env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
rows = []
for name in COMPANIES:
    slug = name.replace(" ", "_")
    print(f"=== {name} ===", flush=True)
    t0 = time.time()
    p = subprocess.run([sys.executable, "run.py", name], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    tail = (p.stdout or "").strip().splitlines()[-3:]
    row = {"company": name, "seconds": round(time.time() - t0), "log": " | ".join(tail)[:200]}
    saved = [f for f in OUT.glob(f"{slug}_*.json") if f.stat().st_mtime >= t0]
    if saved:
        f = max(saved, key=lambda x: x.stat().st_mtime)
        d = json.loads(f.read_text(encoding="utf-8"))
        row.update(strength=d["strength"], discovery=d["discovery"][:160],
                   evidence_items=len(d.get("evidence", [])), file=f.name)
    else:
        row["strength"] = "NO NEW REPORT"
    rows.append(row)
    time.sleep(30)
keys = ["company", "strength", "discovery", "evidence_items", "seconds", "file", "log"]
with open(OUT / "eval.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
print("wrote out/eval.csv")