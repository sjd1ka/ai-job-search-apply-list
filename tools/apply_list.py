"""Write upload/apply_list.html: every job worth applying to, with apply and referral links.

Usage: python tools/apply_list.py
Reads job_scraper/seen_jobs.json directly (no agent tokens). Keeps jobs with status new or ranked
that pass the exclude list, are not in the tracker, and are not low quick-fit (unless ranked 70+, or
first seen today with an on-target title and no posting-based reason in gaps). Preferences (school,
title keywords, file names, talent-acquisition places) come from job_search_config.json.
Experience check (no agent tokens): LinkedIn postings are read once with the linkedin-search
`detail` command and cached in job_scraper/details_cache.json; the stated years are shown in the
Experience column for the candidate to judge (nothing is hidden for experience), and closed
postings are dropped.
Sort: rank score, then quick fit, then newest posting. The "Applied" ticks are saved in the
browser (localStorage), so they survive regenerating the file.
"""
import datetime as dt
import html
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote_plus

sys.path.insert(0, str(Path(__file__).resolve().parent))
import linkedin_sweep  # noqa: E402
import rank_state  # noqa: E402
import user_config  # noqa: E402

CFG = user_config.load()
SCHOOL = CFG["candidate"].get("school", "")
PREFIX = CFG["candidate"]["file_prefix"]
TA_PLACES = CFG.get("referral_search", {}).get("talent_acquisition_places", [])
FIT_ORDER = {"high": 0, "medium": 1, "low": 2}
ON_TARGET = re.compile("|".join(re.escape(k.strip()) for k in CFG["search"]["title_keywords"]), re.I)
CACHE = Path("job_scraper/details_cache.json")
LAWFUL = re.compile(r"work permit|authori[sz]ed|eligible to work|entitled to work|preference", re.I)
CITIZEN = re.compile(r"must be (a |an )?.{0,40}(citizens?|permanent residents?)\b|(citizens?|permanent residents?)\s+only\b|open (only )?to .{0,30}(citizens|permanent residents)", re.I)
SECRET = re.compile(r"\bsecret\b.{0,30}\b(clearance|level|status)\b|\bclearance\b.{0,40}\bsecret\b", re.I)
HELD = re.compile(r"\b(must|required to|need to)\s+(currently\s+)?(hold|have|possess)\b.{0,40}\b(clearance|reliability status)\b", re.I)
CLEARANCE = re.compile(r"\breliability (status|clearance|check)\b|\bsecurity (clearance|screening)\b", re.I)
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_NUM = r"(?:\d{1,2}|" + "|".join(WORDS) + r")(?:\s*\(\d{1,2}\))?"
# "3 years", "3+ years", "3-5 years", "3 - 5+ years", "Three (3) - Five (5) plus years'", "five-plus years"
YEARS = re.compile(r"\b(" + _NUM + r")\s*(?:\+|-?\s*plus)?\s*(?:(?:-|–|to)\s*" + _NUM + r"\s*(?:\+|plus)?\s*)?years?\b", re.I)
HISTORY = re.compile(r"\b(over|more than|nearly|almost|for|last|past)\s*$", re.I)  # "for over 35 years", "9 out of the last 10 years" = company history
EXPERIENCE = re.compile(r"experience|work", re.I)
EDUCATION = re.compile(r"university|degree|diploma|college|school|education|training", re.I)
PREFERRED = re.compile(r"prefer|asset|nice to have|bonus|ideally|desirable", re.I)
TAIL_PREFERRED = re.compile(r"^[^.;:•·]*?,\s*(?:is\s+|are\s+|would be\s+)?(?:an?\s+)?(?:strongly\s+)?(?:prefer|asset|nice to have|desirable)", re.I)
IN_ROLE = re.compile(r"^\s*(?:in|as)\s[^.;:]{0,70}?\b(?:role|position|capacity)s?\b", re.I)
AFTER_IS_EXPERIENCE = re.compile(r"^['’]?\s*(?:of\s+)?(?:\w+\s+){0,2}(?:experience|work)", re.I)


def min_years(text: str) -> tuple:
    """(required_years, preferred_years, quote) from a job description; None when not stated.

    LinkedIn descriptions arrive as one unbroken paragraph, so each "N years" match is judged
    on a small window around it, not on its sentence. With several requirements the highest
    one is returned, since that is the bar the posting sets.
    """
    text = text or ""
    req = pref = None
    quote = ""
    for m in YEARS.finditer(text):
        g = re.match(r"\d+|[a-z]+", m.group(1).lower()).group()
        n = int(g) if g.isdigit() else WORDS[g]
        before, after = text[max(0, m.start() - 45):m.start()], text[m.end():m.end() + 60]
        # "more than 3 years working experience" is a bar; "for over 10 years, we have" is company history
        if not 1 <= n <= 15 or (HISTORY.search(before) and not AFTER_IS_EXPERIENCE.search(after)):
            continue
        hit = EXPERIENCE.search(after) or IN_ROLE.search(after)  # "3+ years in a financial analyst or similar role"
        if hit and EDUCATION.search(after[:hit.start()]):
            hit = None  # "4 years of University training or equivalent experience"
        if not (hit or EXPERIENCE.search(before[-25:])):
            continue  # "3-year program", "per year", "years of service"
        # Same clause only: a "preferred" in the previous sentence, or ", ideally with X" after it, says nothing about the years
        lead = re.split(r"[.!?;:•·]", text[max(0, m.start() - 35):m.start()])[-1]
        trail = re.split(r"[.!?;:•·,]", after)[0]
        if PREFERRED.search(lead + " " + trail) or TAIL_PREFERRED.search(after):
            pref = n if pref is None else max(pref, n)
        elif req is None or n > req:
            req, quote = n, text[max(0, m.start() - 40):m.end() + 60].strip()
    return req, pref, quote


def clearance(text: str) -> tuple:
    """Eligibility Gate on a job description: ("hide", quote), ("flag", quote) or (None, "")."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?;])\s+|\n+", text or "")]
    for s in sentences:
        if (CITIZEN.search(s) and not LAWFUL.search(s)) or SECRET.search(s) or (HELD.search(s) and "obtain" not in s.lower()):
            return "hide", s
    for s in sentences:
        if CLEARANCE.search(s):
            return "flag", s
    return None, ""


def li_id(url: str):
    m = re.search(r"linkedin\.com/jobs/view/(?:.*-)?(\d{8,})", url or "")
    return m.group(1) if m else None


def details(items: list) -> dict:
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    for v in cache.values():  # re-judge stored descriptions so parser fixes apply to old jobs too
        if "desc" in v:
            v["req"], v["pref"], v["sentence"] = min_years(v["desc"])
    todo = [i for _, e in items if (i := li_id(e.get("url"))) and "desc" not in cache.get(i, {})]
    for n, jid in enumerate(todo):
        out = subprocess.run(["bun", "run", ".agents/skills/linkedin-search/cli/src/cli.ts", "detail", jid,
                              "--format", "json"], capture_output=True, text=True, encoding="utf-8")
        try:
            d = json.loads(out.stdout)
        except ValueError:
            continue  # ponytail: transient fetch failure, retried on the next run
        desc = d.get("description", "")
        req, pref, sent = min_years(desc)
        cache[jid] = {"req": req, "pref": pref, "sentence": sent, "active": d.get("isActive", True), "desc": desc}
        if n % 10 == 9:
            CACHE.write_text(json.dumps(cache, indent=1), encoding="utf-8")
        time.sleep(1)  # ponytail: polite fixed delay on LinkedIn's guest endpoint
    CACHE.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    return cache


def people(q: str) -> str:
    return f"https://www.linkedin.com/search/results/people/?keywords={quote_plus(q)}&origin=GLOBAL_SEARCH_HEADER"


def rows() -> list:
    doc, seen = rank_state.load_state(rank_state.STATE)
    applied = rank_state.tracker_pairs(rank_state.TRACKER)
    ex = linkedin_sweep.excludes()
    today = dt.date.today().isoformat()
    out = []
    for key, e in seen.items():
        # Shown on an earlier day = the candidate has seen it; retire it unless held for a referral.
        if e.get("shown_date", today) < today and not e.get("hold") and e.get("status") in ("new", "ranked"):
            e["status"], e["reviewed_date"] = "reviewed", today
        if e.get("status") not in ("new", "ranked"):
            continue
        if (rank_state.norm(e.get("company")), rank_state.norm(e.get("title"))) in applied:
            continue
        if linkedin_sweep.excluded(e, *ex):
            continue
        # A "low" set from the title alone (no gaps written from the posting) can't hide an on-target title:
        # it goes through the same posting checks below instead. Today's finds only: older unshown lows stay retired.
        if e.get("fit") == "low" and (e.get("rank_score") or 0) < 70 and (
                e.get("gaps") or not ON_TARGET.search(e.get("title") or "") or not (e.get("first_seen") or "").startswith(today)):
            continue
        out.append((key, e))
    cache = details(out)
    kept, hidden = [], []
    for key, e in out:
        d = cache.get(li_id(e.get("url")) or "", {})
        if d.get("active") is False:
            continue
        gate, quote = clearance(d.get("desc"))
        if gate == "hide":
            hidden.append((e, {**d, "sentence": quote}))
            continue
        years = (f"{d['req']} required" if d.get("req") else
                 f"{d['pref']}+ preferred" if d.get("pref") else
                 "not stated" if d else "check posting")
        kept.append((key, {**e, "_years": years, "_clear": quote if gate else ""}))
    for key, e in out:  # everything on today's page (incl. the hidden section) counts as seen today
        e.setdefault("shown_date", today)
    rank_state.save_state(rank_state.STATE, doc)
    out = kept
    out.sort(key=lambda kv: kv[1].get("posted_date") or "", reverse=True)  # newest first...
    out.sort(key=lambda kv: (-(kv[1].get("rank_score") or 0), FIT_ORDER.get(kv[1].get("fit"), 1)))  # ...within score/fit
    return out, hidden


def tailored(key: str, variant: str = "") -> str:
    found = sorted(Path("documents/applications").glob(f"????-??-??_{key}"))  # newest date last
    links = [(f, label) for f, label in ((f"{PREFIX}_Resume.pdf", "Tailored resume"), (f"{PREFIX}_Cover_Letter.pdf", "Cover letter"))
             if found and (found[-1] / f).exists()]
    out = "".join(f'<br><a href="../{html.escape((found[-1] / f).as_posix())}" target="_blank">{label}</a>' for f, label in links)
    if not links and variant and Path(f"cv/variants/resume_{variant}.pdf").exists():  # /tailor step 0: a variant covers it
        out = f'<br><a href="../cv/variants/resume_{variant}.pdf" target="_blank">Use {variant.upper()} resume (no tailoring needed)</a>'
    return out


def ta_links(company: str) -> str:
    return " · ".join(f'<a href="{people(company + " talent acquisition " + p)}" target="_blank">{html.escape(p)}</a>' for p in TA_PLACES)


def page(items: list, hidden: list = ()) -> str:
    trs = []
    for key, e in items:
        c, t = e.get("company") or "", e.get("title") or ""
        score = e.get("rank_score")
        trs.append(
            f'<tr data-key="{html.escape(key)}"><td><input type="checkbox" class="applied"></td><td><input type="checkbox" class="skipped"></td>'
            f'<td>{score if score is not None else ""}</td><td>{html.escape(e.get("fit") or "")}</td>'
            f'<td><a href="{html.escape(e.get("url") or "#")}" target="_blank">{html.escape(t)}</a>{tailored(key, e.get("resume_variant") or "")}</td>'
            f'<td>{html.escape(c)}{"<br><b>⏳ " + html.escape(e["hold"]) + "</b>" if e.get("hold") else ""}{"<br><b title=\"" + html.escape(e["_clear"]) + "\">🔒 Clearance</b>" if e.get("_clear") else ""}</td><td>{html.escape(e.get("posted_date") or "")}</td><td>{html.escape(e.get("_years", ""))}</td>'
            f'<td><a href="{people(c + " recruiter")}" target="_blank">Recruiter</a> · '
            + (f'<a href="{people(c + " " + SCHOOL)}" target="_blank">Alumni</a> · ' if SCHOOL else "") +
            f'<a href="{people(c + " " + t.split(",")[0])}" target="_blank">Same role</a></td>'
            f'<td>{ta_links(c)}</td></tr>')
    return f"""<!doctype html><meta charset="utf-8"><title>Apply list</title>
<style>body{{font:14px system-ui;margin:16px}}table{{border-collapse:collapse;width:100%}}
td,th{{border-bottom:1px solid #ddd;padding:6px;text-align:left;vertical-align:top}}
tr.applied{{opacity:.35}}tr.skipped{{opacity:.25;text-decoration:line-through}}a{{color:#0a58ca}}</style>
<h1>Apply list ({len(items)} jobs)</h1>
<p>Click the title to open the posting and apply. Upload the row's tailored resume if it has one, otherwise the variant matching the role
(see cv/variants/). Tick "Applied" when done, or "Not applying" if it doesn't fit; ticks are remembered in this browser. Then tell Claude
<code>/outcome &lt;company&gt;</code> if you want it tracked.</p>
<table><tr><th>Applied</th><th>Not applying</th><th>Rank</th><th>Fit</th><th>Job</th><th>Company</th><th>Posted</th><th>Experience</th><th>Referral search</th><th>Talent acquisition</th></tr>
{''.join(trs)}</table>
<details style="margin-top:24px"><summary>Hidden: {len(hidden)} jobs whose posting asks for citizenship/PR or a held or Secret clearance (check the quote; apply anyway if it was misread)</summary>
<ul>{''.join(f'<li><a href="{html.escape(e.get("url") or "#")}" target="_blank">{html.escape(e.get("title") or "")}</a> - {html.escape(e.get("company") or "")}: <i>{html.escape(d.get("sentence") or "")}</i></li>' for e, d in hidden)}</ul></details>
<script>
const table = document.querySelector('table');
const rows = [...document.querySelectorAll('tr[data-key]')];
// Order: untouched rows (ranked order), then Applied (dimmed), then Not applying (dimmed, struck through) at the very bottom.
const state = r => r.classList.contains('skipped') ? 2 : r.classList.contains('applied') ? 1 : 0;
const reorder = () => [0, 1, 2].forEach(n => rows.filter(r => state(r) === n).forEach(r => table.appendChild(r)));
for (const tr of rows) {{
  const boxes = {{applied: tr.querySelector('.applied'), skipped: tr.querySelector('.skipped')}};
  for (const [name, box] of Object.entries(boxes)) {{
    const k = name + ':' + tr.dataset.key;
    try {{ box.checked = localStorage.getItem(k) === '1'; }} catch (e) {{}}
    tr.classList.toggle(name, box.checked);
    box.onchange = () => {{
      if (box.checked) {{  // the two ticks are exclusive
        const other = name === 'applied' ? 'skipped' : 'applied';
        boxes[other].checked = false; tr.classList.remove(other);
        try {{ localStorage.setItem(other + ':' + tr.dataset.key, '0'); }} catch (e) {{}}
      }}
      try {{ localStorage.setItem(k, box.checked ? '1' : '0'); }} catch (e) {{}}
      tr.classList.toggle(name, box.checked); reorder();
    }};
  }}
}}
reorder();
</script>"""


def selftest() -> None:
    assert tailored("no-such-key") == "" and tailored("no-such-key", "no-such-variant") == ""
    assert min_years("Degree in Finance or a related field. 3+ years in a financial analyst, accounting, FP&A or similar role. Working")[0] == 3
    assert min_years("Named Best Workplace by Great Place to Work 9 out of the last 10 years and recognized for culture.")[0] is None
    assert min_years("More than 3 years working experience in a business systems analyst role.")[0] == 3
    assert min_years("3 to 5 years of experience in an analyst role, ideally with exposure to marketing data.")[0] == 3
    assert min_years("Master's degree or relevant certifications preferred. Experience: 6+ years of experience in Banking.")[0] == 6
    assert min_years("3 years of experience, preferred.")[0] is None
    assert min_years("3+ years of experience is an asset.")[1] == 3
    assert min_years("Ideally 3 years of experience in reporting.")[1] == 3
    assert min_years("Degree, preferably in Computer Science or equivalent relevant work experience More than 3 years working experience in a BSA role.")[0] == 3
    assert min_years("We have served clients for over 10 years, helping them work smarter.")[0] is None
    assert clearance("Must be a Canadian citizen.")[0] == "hide"
    assert clearance("Must be a Canadian citizen, permanent resident or hold a valid work permit.")[0] is None
    assert clearance("Preference will be given to Canadian citizens and permanent residents.")[0] is None
    assert clearance("Ability to obtain Secret clearance.")[0] == "hide"
    assert clearance("Must hold a valid security clearance.")[0] == "hide"
    assert clearance("Must have the ability to obtain a security clearance.")[0] == "flag"
    assert clearance("Reliability Status is required for this role.")[0] == "flag"
    assert clearance("Our secret sauce is our people. Must be legally authorized to work in Canada.")[0] is None
    assert min_years("Required Minimum 5 years of experience as a Scrum Master.")[0] == 5
    assert min_years("With more than 40 years of experience, we're the team behind Money Mart.")[0] is None
    assert min_years("3-5 years of experience in business analysis.")[0] == 3
    assert min_years("2+ years of experience preferred.")[1] == 2
    assert min_years("Minimum of five years experience.")[0] == 5
    assert min_years("Normally acquired through completion of 4 years of University training or equivalent experience.")[0] is None
    blob = ("We help people move forward. You have: A University degree, college diploma or equivalent experience "
            "3 years of experience as a Business Analyst or Business Systems Analyst Our benefits include $5,000 per year")
    assert min_years(blob)[0] == 3
    assert min_years("Minimum of 3 years’ work experience in roles related to Project Management")[0] == 3
    assert min_years("Three (3) - Five (5) plus years’ of experience in data analysis. "
                     "Two (2) or more years of experience in construction")[0] == 3
    assert min_years("helping Canadian investors for over 35 years. We offer a range of products")[0] is None
    assert min_years("Minimum College degree (3-year program). Post-secondary education or equivalent work experience")[0] is None
    assert min_years("10+ years of project, program or technology delivery experience")[0] == 10
    assert min_years("3 - 5+ years of relevant experience in business analysis")[0] == 3
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    items, hidden = rows()
    dest = Path("upload/apply_list.html")
    dest.parent.mkdir(exist_ok=True)
    dest.write_text(page(items, hidden), encoding="utf-8")
    print(f"Wrote {dest} ({len(items)} jobs)")
