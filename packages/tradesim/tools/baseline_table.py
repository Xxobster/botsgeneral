"""Turn several checker JSON reports into the markdown tables of the engine baseline.

Usage::

    python tools/baseline_table.py tradesim=base_tradesim.json xgb=base_xgb.json ...

Nothing here judges anything. It reads the reports the checker already wrote and lays
them out, so the baseline document cannot drift from the runs that produced it.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

FAMILIES = ("DATA", "CAUS", "EXEC", "FUND", "QTY", "METR", "VALD", "PORT")
ENTRY_BAR = ("EXEC-010", "EXEC-011", "EXEC-012", "EXEC-013", "EXEC-014", "EXEC-015", "EXEC-016")


def family(identifier: str) -> str:
    return identifier.split("-", 1)[0]


def load(pairs: list[str]) -> dict[str, dict]:
    out = {}
    for pair in pairs:
        label, _, path = pair.partition("=")
        out[label] = json.loads(Path(path).read_text(encoding="utf-8"))
    return out


def fixture_status_by_id(report: dict) -> dict[str, str]:
    """Worst status wins: one failing fixture is enough to fail the identifier."""
    order = {"PASS": 0, "UNSUPPORTED": 1, "FAIL": 2, "ERROR": 3}
    best: dict[str, str] = {}
    for f in report["fixtures"]:
        for i in f["ids"]:
            current = best.get(i)
            if current is None or order[f["status"]] > order[current]:
                best[i] = f["status"]
    return best


def main(argv: list[str]) -> int:
    reports = load(argv)
    if not reports:
        print(__doc__)
        return 2

    per_engine = {name: fixture_status_by_id(r) for name, r in reports.items()}
    all_ids = sorted({i for m in per_engine.values() for i in m})

    print("### Fixture outcome by family\n")
    header = "| family | " + " | ".join(per_engine) + " |"
    print(header)
    print("|" + "---|" * (len(per_engine) + 1))
    for fam in FAMILIES:
        cells = []
        for name, mapping in per_engine.items():
            counts = Counter(v for i, v in mapping.items() if family(i) == fam)
            total = sum(counts.values())
            if not total:
                cells.append("-")
                continue
            parts = [f"{counts['PASS']}/{total} pass"]
            if counts["UNSUPPORTED"]:
                parts.append(f"{counts['UNSUPPORTED']} unsupported")
            if counts["ERROR"]:
                parts.append(f"{counts['ERROR']} error")
            cells.append(", ".join(parts))
        print(f"| {fam} | " + " | ".join(cells) + " |")

    print("\n### The seven entry-bar identifiers\n")
    print("| identifier | " + " | ".join(per_engine) + " |")
    print("|" + "---|" * (len(per_engine) + 1))
    for i in ENTRY_BAR:
        cells = [per_engine[name].get(i, "NO FIXTURE") for name in per_engine]
        print(f"| {i} | " + " | ".join(cells) + " |")

    print("\n### Totals\n")
    print("| engine | fixtures passed | failed | unsupported | errored | bound identifiers |")
    print("|---|---|---|---|---|---|")
    for name, report in reports.items():
        counts = Counter(f["status"] for f in report["fixtures"])
        bound = sum(
            1 for r in report["identifiers"] if r["test_status"] not in ("NO_BINDING",)
        )
        print(
            f"| {name} | {counts['PASS']} | {counts['FAIL']} | {counts['UNSUPPORTED']} | "
            f"{counts['ERROR']} | {bound} |"
        )

    print("\n### Every identifier\n")
    print("| identifier | " + " | ".join(per_engine) + " |")
    print("|" + "---|" * (len(per_engine) + 1))
    for i in all_ids:
        cells = [per_engine[name].get(i, "-") for name in per_engine]
        print(f"| {i} | " + " | ".join(cells) + " |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
