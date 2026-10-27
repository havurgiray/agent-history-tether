#!/usr/bin/env python3
"""The report of a check on a real machine (windows/tests/vm_check.sh,
linux/tests/vm_check.sh): one HTML page with each check, its result and its
screenshot, from OUT/results.jsonl and the suite lines in $SMOKE.

    vm_report.py OUT TITLE        (exit status 1 when a check failed)
"""
import html, json, os, sys
out, title = sys.argv[1], sys.argv[2]
rows = []
for line in os.environ.get("SMOKE", "").splitlines():
    parts = line.split(" ", 2)
    if len(parts) >= 2:
        rows.append({"check": parts[0] + " (suite)", "ok": parts[1] == "0",
                     "detail": parts[2] if len(parts) > 2 else "", "shot": None})
try:
    for line in open(os.path.join(out, "results.jsonl"), encoding="utf-8-sig"):
        line = line.strip()
        if line:
            r = json.loads(line)
            if r.get("check") != "done":
                rows.append(r)
except OSError:
    rows.append({"check": "the desktop checks", "ok": False,
                 "detail": "no results came back (was the user logged in and the screen unlocked?)", "shot": None})
mark = lambda ok: "✓" if ok is True else ("✗" if ok is False else "see")
page = [f"<!doctype html><meta charset=utf-8><title>{html.escape(title)}</title>",
        "<style>body{font:14px system-ui;margin:24px;max-width:1100px}td,th{padding:4px 8px;"
        "border-bottom:1px solid #ddd;text-align:left}img{max-width:100%;border:1px solid #ccc;margin:6px 0 18px}"
        ".bad{color:#c62828}.ok{color:#1f9d55}</style>",
        f"<h1>{html.escape(title)}</h1><table>"]
for r in rows:
    cls = "ok" if r.get("ok") is True else "bad" if r.get("ok") is False else ""
    page.append(f"<tr><td class={cls}>{mark(r.get('ok'))}</td><td>{html.escape(r['check'])}</td>"
                f"<td>{html.escape(str(r.get('detail') or ''))}</td></tr>")
page.append("</table>")
for r in rows:
    if r.get("shot"):
        page.append(f"<h3>{html.escape(r['check'])}</h3><img src='{html.escape(r['shot'])}'>")
open(os.path.join(out, "report.html"), "w", encoding="utf-8").write("\n".join(page))
for r in rows:
    print(f"   {mark(r.get('ok')):<3} {r['check']}" + (f" — {r['detail']}" if r.get("detail") and r.get("ok") is not True else ""))
bad = [r for r in rows if r.get("ok") is False]
print(f"\nreport: {os.path.join(out, 'report.html')}")
sys.exit(1 if bad else 0)