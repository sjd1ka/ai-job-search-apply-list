"""Build a one-page tailored resume from a job's bullet spec.

Usage: python tools/tailor_resume.py documents/applications/<YYYY-MM-DD>_<job_key>/resume.json
Writes <file_prefix>_Resume.pdf next to the spec with xelatex and exits 1 unless it is exactly one page.
Name, contact line, education, employers, titles and dates come from job_search_config.json
("candidate" and "resume"), so a spec can only change skills and bullets.
Spec keys: skills (list of "Label: items"), one bullet list per job "key" in the config,
project_name, project; optional project2_name, project2.
A cover.json beside the spec (recipient, paragraphs) also builds <file_prefix>_Cover_Letter.pdf, one page.
Bullet text comes only from cv/facts.md; see .claude/commands/tailor.md.
A spec that breaks the house rules in lint() is refused, exit 1, nothing built.
"""
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import user_config  # noqa: E402

CFG = user_config.load()
WHO, RES = CFG["candidate"], CFG["resume"]
NAME = f"{WHO['file_prefix']}_Resume"
COVER = f"{WHO['file_prefix']}_Cover_Letter"
JOBS = [(j["key"], j["org"], j["location"], j["title"], j["dates"]) for j in RES["jobs"]]


def esc(s: str) -> str:
    return re.sub(r"([&%$#_{}])", r"\\\1", s)


def head(title: str, margins: str) -> str:
    return (r"""\documentclass[11pt,letterpaper]{article}
\usepackage[""" + margins + r"""]{geometry}
\usepackage{fontspec}
\usepackage{enumitem}
\setmainfont{""" + RES.get("font", "Times New Roman") + r"""}[RawFeature={-kern}]
\special{pdf: docinfo << /Title (""" + title + r""") /Author (""" + esc(WHO["name"]) + r""") >>}
\sloppy\hyphenpenalty=10000\pagestyle{empty}\setlength{\parindent}{0pt}\setlength{\parskip}{0pt}
\setlist[itemize]{leftmargin=14pt,itemsep=0pt,topsep=0pt,parsep=0pt,partopsep=0pt}
\newcommand{\sect}[1]{\vspace{5pt}{\bfseries #1}\par\vspace{1pt}\hrule\vspace{2pt}}
\newcommand{\entry}[4]{\textbf{#1}\hfill\textbf{#2}\par\textit{#3}\hfill\textit{#4}\par}
\begin{document}
\begin{center}{\fontsize{20}{24}\selectfont\bfseries """ + esc(WHO["name"]) + r"""}\\[1pt]""" + esc(WHO["contact_line"]) + r"""\end{center}
""")


def bullets(items: list) -> str:
    return r"\begin{itemize}" + "".join(r"\item " + esc(i) for i in items) + r"\end{itemize}"


def tex(spec: dict) -> str:
    out = [head(NAME, "left=0.6in,right=0.6in,top=0.5in,bottom=0.5in"), r"\vspace{-8pt}", r"\sect{EDUCATION}"]
    for e in RES["education"]:
        out.append(rf"\entry{{{esc(e['school'])}}}{{{esc(e['location'])}}}{{{esc(e['degree'])}}}{{{esc(e['dates'])}}}")
        if e.get("note"):
            out.append(bullets([e["note"]]))
    out.append(r"\sect{SKILLS}")
    for line in spec["skills"]:
        label, rest = line.split(":", 1)
        out.append(rf"\textbf{{{esc(label)}:}}{esc(rest)}\par")
    out.append(r"\sect{WORK EXPERIENCE}")
    for key, org, loc, title, dates in JOBS:
        out += [rf"\entry{{{esc(org)}}}{{{esc(loc)}}}{{{esc(title)}}}{{{esc(dates)}}}", bullets(spec[key]), r"\vspace{2pt}"]
    if spec.get("project"):
        out += [r"\sect{PROJECTS AND ACHIEVEMENTS}", rf"\textbf{{{esc(spec['project_name'])}}}\par", bullets(spec["project"])]
    if spec.get("project2"):  # optional second project
        out += [r"\vspace{2pt}", rf"\textbf{{{esc(spec['project2_name'])}}}\par", bullets(spec["project2"])]
    out.append(r"\end{document}")
    return "\n".join(out)


def letter(spec: dict) -> str:
    day = dt.date.today().strftime("%B %d, %Y").replace(" 0", " ")
    body = "".join(esc(p) + r"\par\vspace{9pt}" for p in spec["paragraphs"])
    return head(COVER, "margin=1in") + rf"""\vspace{{6pt}}
{day}\par\vspace{{12pt}}Dear {esc(spec['recipient'])},\par\vspace{{9pt}}
{body}Sincerely,\par\vspace{{4pt}}{esc(WHO['name'])}
\end{{document}}"""


SECTIONS = tuple(j[0] for j in JOBS) + ("project", "project2")
WEAK_OPENERS = ("Gathered", "Cleaned", "Reviewed", "Helped", "Supported", "Assisted", "Participated", "Worked", "Responsible")
BANNED = re.compile("|".join([r"\balso\b", r"\bhelped\b", r"\bassisted\b", r"\bresponsible for\b"]
                             + [re.escape(p) for p in RES.get("banned_phrases", [])]), re.I)
VARIANTS = {p.parent.name: json.loads(p.read_text(encoding="utf-8"))
            for p in (Path(__file__).resolve().parent.parent / "cv" / "variants").glob("*/resume.json")}


def lint(spec: dict) -> list:
    """House rules a spec can break; empty means clean. Judgement calls stay with the writer."""
    bad = [f"missing bullets for job '{k}' (keys come from job_search_config.json)" for k in SECTIONS[:-2] if not spec.get(k)]
    for sec in SECTIONS:
        for b in spec.get(sec) or []:
            if b.split()[0] in WEAK_OPENERS:
                bad.append(f"weak opener: {b}")
            if not b.endswith("."):
                bad.append(f"no full stop: {b}")
            if BANNED.search(b):
                bad.append(f"banned wording: {b}")
    for name, v in VARIANTS.items():  # a spec that only reorders a variant is not tailoring
        if all(sorted(spec.get(k) or []) == sorted(v.get(k) or []) for k in SECTIONS):
            bad.append(f"bullets are the {name} variant, only reordered: tailor them to this posting")
    return bad


def compile_pdf(source: str, name: str, out_dir: Path) -> int:
    xelatex = shutil.which("xelatex")
    if not xelatex:
        sys.exit("xelatex not found on PATH: install TeX Live or TinyTeX (see SETUP.md)")
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / f"{name}.tex").write_text(source, encoding="utf-8")
        run = subprocess.run([xelatex, "-interaction=nonstopmode", f"{name}.tex"], cwd=tmp, capture_output=True, text=True, errors="replace")
        pages = re.search(r"Output written on .*?\((\d+) pages?", run.stdout)
        if not pages:
            sys.exit(run.stdout[-1500:])
        shutil.copy(Path(tmp) / f"{name}.pdf", out_dir / f"{name}.pdf")
    return int(pages.group(1))


def selftest() -> None:
    assert esc("R&D 40% $2M") == r"R\&D 40\% \$2M"
    good = {k: ["Led a thing."] for k in SECTIONS[:-2]}
    assert lint(good) == []
    assert len(lint({**good, SECTIONS[0]: ["Gathered requirements, also helped on it"]})) == 3
    assert lint({}) and "Times New Roman" in tex({**good, "skills": ["Tools: SQL"]})
    print("selftest ok")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    if sys.argv[1] == "--selftest":
        sys.exit(selftest())
    spec_path = Path(sys.argv[1])
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    problems = lint(spec)
    if problems:
        print("\n".join(problems))
        sys.exit(1)
    n = compile_pdf(tex(spec), NAME, spec_path.parent)
    print(f"{n} page(s): {spec_path.parent / (NAME + '.pdf')}")
    cover = spec_path.with_name("cover.json")
    if cover.exists():
        m = compile_pdf(letter(json.loads(cover.read_text(encoding="utf-8"))), COVER, spec_path.parent)
        print(f"{m} page(s): {spec_path.parent / (COVER + '.pdf')}")
        n = max(n, m)
    sys.exit(0 if n == 1 else 1)
