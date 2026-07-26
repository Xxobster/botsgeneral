"""Print the non-passing entries of a checker JSON report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

path = Path(sys.argv[1] if len(sys.argv) > 1 else "out.json")
data = json.loads(path.read_text(encoding="utf-8"))

fixtures = data["fixtures"]
bad = [f for f in fixtures if f["status"] != "PASS"]
print(f"fixtures: {len(fixtures) - len(bad)}/{len(fixtures)} pass")
for f in bad:
    print(f"  {f['status']:<11} {f['fixture']}  [{', '.join(f['ids'])}]")
    for msg in f["failures"][:8]:
        print(f"        - {msg}")
    if f["detail"]:
        print(f"        - {f['detail'][:400]}")

rows = data["identifiers"]
unsat = [r for r in rows if r["required"] and r["problems"]]
print(f"\nidentifiers: {data['satisfied']}/{data['required']} satisfied")
for r in unsat:
    print(f"  {r['identifier']:<10} tests={r['test_status']:<13} fixtures={r['fixture_status']}")
    for p in r["problems"][:4]:
        print(f"        - {p}")
