"""Read the user's preferences from job_search_config.json (written by /setup).

Falls back to job_search_config.example.json so the tools still run before /setup.
The real file is gitignored: it holds the user's name, contact line and search choices.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "job_search_config.json"
EXAMPLE = ROOT / "job_search_config.example.json"


def load() -> dict:
    return json.loads((CONFIG if CONFIG.exists() else EXAMPLE).read_text(encoding="utf-8"))


if __name__ == "__main__":
    cfg = load()
    assert cfg["search"]["roles"] and cfg["candidate"]["name"]
    print(f"config ok ({'job_search_config.json' if CONFIG.exists() else 'example only, run /setup'})")
