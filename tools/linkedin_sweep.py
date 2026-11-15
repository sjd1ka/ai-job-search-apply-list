"""Page through linkedin-search for one query and print only new, relevant, fresh results.

Usage:
  python tools/linkedin_sweep.py -q "business analyst"                 # location = first in config
  python tools/linkedin_sweep.py -q "data analyst" -l "Ontario, Canada" --companies "Acme,Globex"
  python tools/linkedin_sweep.py --selftest

Preferences come from job_search_config.json (see tools/user_config.py). Filtering happens here
so the agent only reads survivors (saves tokens):
  - drops results older than --days (config: monday_days_window on Monday, days_window otherwise)
  - drops titles with none of the config's title_keywords
  - drops jobs already in job_scraper/seen_jobs.json (matched by LinkedIn job id)
  - with --companies, keeps only those employers (case/punctuation-insensitive prefix match)
  - drops companies, locations and title words on .claude/skills/job-scraper/exclude.md
  - drops French-language titles when exclude_french_titles is true
Stops at a short page, after 2 consecutive pages with fewer than 3 relevant titles, or at --max-pages.
Prints a JSON array on stdout and a one-line summary on stderr.
"""
import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import user_config  # noqa: E402

CLI = ".agents/skills/linkedin-search/cli/src/cli.ts"
CFG = user_config.load()["search"]


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def relevant(title: str, keywords=None) -> bool:
    t = f" {title.lower()} "
    return any(k.lower() in t for k in (keywords or CFG["title_keywords"]))


def should_stop(page_len: int, weak_streak: int, page: int, max_pages: int) -> bool:
    return page_len < 10 or weak_streak >= 2 or page >= max_pages


def default_days() -> int:
    return CFG["monday_days_window"] if dt.date.today().weekday() == 0 else CFG["days_window"]  # Mon covers the weekend


def seen_ids() -> set:
    p = Path("job_scraper/seen_jobs.json")
    if not p.exists():
        return set()
    seen = json.loads(p.read_text(encoding="utf-8")).get("seen", {})
    return {m.group(1) for v in seen.values() if (m := re.search(r"(\d{8,})", v.get("url", "")))}


def excludes() -> tuple:
    p = Path(".claude/skills/job-scraper/exclude.md")
    if not p.exists():
        return [], [], []
    lists, current = {"companies": [], "locations": [], "title words": []}, None
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            current = line[3:].strip().lower()
        elif line.startswith("- ") and current in lists:
            v = line[2:].strip()
            lists[current].append(norm(v) if current == "locations" else " ".join(re.findall(r"\w+", v.lower())))
    return lists["companies"], lists["locations"], lists["title words"]


def excluded(job: dict, companies: list, locations: list, title_words: list = (), french=None) -> bool:
    if french is None:
        french = CFG.get("exclude_french_titles", False)
    c = " " + " ".join(re.findall(r"\w+", (job.get("company") or "").lower())) + " "
    loc = norm(job.get("location", ""))
    title = (job.get("title") or "").lower()
    words = re.findall(r"\w+", title)
    is_french = french and bool(re.search(r"[àâçéèêëîïôûùüÿœ]|\(e\)", title))
    return (is_french or any(" " + x + " " in c for x in companies) or any(x in loc for x in locations)
            or any(" " + w + " " in " " + " ".join(words) + " " for w in title_words))


def fetch(query: str, location: str, minutes: int, page: int) -> list:
    out = subprocess.run(["bun", "run", CLI, "search", "-q", query, "-l", location,
                          "--jobage-minutes", str(minutes), "--page", str(page), "--format", "json"],
                         capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        sys.exit(f"linkedin-search failed on page {page}: {out.stderr.strip()[:300]}")
    return json.loads(out.stdout).get("results", [])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-q", "--query")
    ap.add_argument("-l", "--location", default=CFG["locations"][0] if CFG["locations"] else None)
    ap.add_argument("--days", type=int, default=default_days())
    ap.add_argument("--max-pages", type=int, default=10)
    ap.add_argument("--companies", default="")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not (a.query and a.location):
        ap.error("-q is required, and -l unless job_search_config.json lists a location")

    cutoff = (dt.date.today() - dt.timedelta(days=a.days)).isoformat()
    companies = [norm(c) for c in a.companies.split(",") if c.strip()]
    known = seen_ids()
    ex_companies, ex_locations, ex_titles = excludes()
    kept, raw, weak, page = {}, 0, 0, 0
    while True:
        page += 1
        results = fetch(a.query, a.location, a.days * 1440, page)
        raw += len(results)
        rel = [r for r in results if relevant(r.get("title", ""))]
        weak = weak + 1 if len(rel) < 3 else 0
        for r in rel:
            if r.get("date") and r["date"] < cutoff:
                continue
            if companies and not any(norm(r.get("company", "")).startswith(c) for c in companies):
                continue
            if r["id"] in known or excluded(r, ex_companies, ex_locations, ex_titles):
                continue
            kept[r["id"]] = {k: r.get(k) for k in ("id", "title", "company", "location", "date", "url")}
        if should_stop(len(results), weak, page, a.max_pages):
            break
        time.sleep(2)  # ponytail: fixed polite delay; LinkedIn guest endpoint, keep volume low
    print(json.dumps(list(kept.values()), ensure_ascii=False, indent=1))
    print(f"pages={page} raw={raw} new_relevant={len(kept)}", file=sys.stderr)


def selftest() -> None:
    kw = ["analyst", "data"]
    assert relevant("Senior Business Systems Analyst", kw) and not relevant("Registered Nurse", kw)
    assert should_stop(7, 0, 1, 10)          # short page = last page
    assert should_stop(10, 2, 3, 10)         # two weak pages in a row
    assert should_stop(10, 0, 10, 10)        # page cap
    assert not should_stop(10, 1, 4, 10)
    assert norm("TD Bank, N.A.").startswith(norm("TD"))
    assert excluded({"company": "TCS Canada", "location": "Toronto"}, ["tcs"], [])
    assert excluded({"company": "Monitor Deloitte"}, ["deloitte"], [])
    assert not excluded({"company": "Eyesafe Inc"}, ["ey"], [])
    assert excluded({"company": "EY"}, ["ey"], [])
    assert excluded({"company": "Acme", "location": "Brampton, Ontario, Canada"}, [], [norm("Brampton")])
    assert not excluded({"company": "TD", "location": "Toronto, ON"}, ["tcs"], [norm("Brampton")])
    assert excluded({"title": "Sr. Business Analyst"}, [], [], ["sr"])
    assert excluded({"title": "Business Analyst (Senior)"}, [], [], ["senior"])
    assert not excluded({"title": "SRED Tax Analyst"}, [], [], ["sr"])
    assert excluded({"title": "Quality Assurance Analyst - Remote"}, [], [], ["quality assurance"])
    assert excluded({"title": "Analyste d'affaires principal(e)"}, [], [], [], french=True)
    assert not excluded({"title": "Analyste d'affaires principal(e)"}, [], [], [], french=False)
    assert not excluded({"title": "Data Quality Analyst"}, [], [], ["quality assurance", "qa"])
    print("selftest ok")


if __name__ == "__main__":
    main()
