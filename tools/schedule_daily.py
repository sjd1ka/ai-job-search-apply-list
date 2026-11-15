"""Register (or remove) the daily /scrape run at the time chosen in job_search_config.json.

Usage:
  python tools/schedule_daily.py            # create or update the scheduled run from "schedule"
  python tools/schedule_daily.py --remove   # delete it
  python tools/schedule_daily.py --dry-run  # print what would be registered

Windows: a Task Scheduler task opens a PowerShell window in this repo and starts
`claude --chrome "/scrape"` (Chrome lets /scrape read sites without a CLI). It runs only while you
are logged in; a missed time (PC asleep or off) is skipped, not caught up.
macOS / Linux: prints a crontab line using headless `claude -p "/scrape"`; add it with `crontab -e`.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import user_config  # noqa: E402

TASK = "AI Job Search Daily Scrape"
CRON_DAYS = {"SUN": 0, "MON": 1, "TUE": 2, "WED": 3, "THU": 4, "FRI": 5, "SAT": 6}


def windows_cmd(s: dict) -> list:
    repo = str(user_config.ROOT)
    action = f"powershell -NoExit -Command \"Set-Location '{repo}'; claude --chrome '/scrape'\""
    return ["schtasks", "/Create", "/F", "/TN", TASK, "/SC", "WEEKLY", "/D", ",".join(s["days"]),
            "/ST", s["time"], "/TR", action]


def cron_line(s: dict) -> str:
    hh, mm = s["time"].split(":")
    days = ",".join(str(CRON_DAYS[d]) for d in s["days"])
    return f'{int(mm)} {int(hh)} * * {days} cd "{user_config.ROOT}" && claude -p "/scrape" >> job_scraper/scheduled_run.log 2>&1'


def main() -> int:
    s = user_config.load()["schedule"]
    if "--selftest" in sys.argv:
        t = {"time": "07:05", "days": ["MON", "FRI"]}
        assert cron_line(t).startswith("5 7 * * 1,5 ") and "/scrape" in windows_cmd(t)[-1]
        return print("selftest ok")
    if sys.platform != "win32":
        print("Add this line with `crontab -e`:\n" + cron_line(s))
        return 0
    if "--remove" in sys.argv:
        return subprocess.run(["schtasks", "/Delete", "/F", "/TN", TASK]).returncode
    if not s.get("enabled"):
        print('schedule.enabled is false in job_search_config.json; nothing registered.')
        return 0
    cmd = windows_cmd(s)
    if "--dry-run" in sys.argv:
        print(subprocess.list2cmdline(cmd))
        return 0
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    sys.exit(main())
