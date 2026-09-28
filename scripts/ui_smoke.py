"""Browser smoke test: visit every view, report Streamlit exceptions, save screenshots.

Usage (app must be running on :8501):
  python scripts/ui_smoke.py [out_dir]
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PAGES = ["Incident queue", "Incident workspace", "New intake", "Quality & evaluation", "Rules & playbooks", "Monitoring"]
URL = "http://localhost:8501"


def wait_idle(page):
    page.wait_for_timeout(600)
    try:
        page.wait_for_selector('[data-testid="stStatusWidget"]', state="detached", timeout=20000)
    except Exception:
        pass
    page.wait_for_timeout(400)


def exceptions(page) -> list[str]:
    return [e.inner_text()[:500] for e in page.query_selector_all('[data-testid="stException"]')]


def main(out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    problems = 0
    with sync_playwright() as p:
        exe = "/opt/pw-browsers/chromium"
        b = p.chromium.launch(executable_path=exe) if Path(exe).exists() else p.chromium.launch()
        page = b.new_page(viewport={"width": 1500, "height": 1000})
        page.goto(URL)
        page.wait_for_selector("text=AI Risk & Escalation Ops", timeout=30000)
        wait_idle(page)
        for name in PAGES:
            page.get_by_text(name, exact=True).first.click()
            wait_idle(page)
            ex = exceptions(page)
            problems += len(ex)
            print(f"{name}: {'OK' if not ex else 'EXCEPTION'}")
            for e in ex:
                print("   ", e.replace("\n", " | ")[:400])
            page.screenshot(path=str(out / f"{name.replace(' ', '_').replace('&', 'and')}.png"), full_page=True)
        # every workspace tab
        page.get_by_text("Incident workspace", exact=True).first.click()
        wait_idle(page)
        labels = [t.inner_text() for t in page.query_selector_all('[data-testid="stButtonGroup"] button')]
        for label in labels:
            tab = page.locator('[data-testid="stButtonGroup"]').get_by_text(label, exact=True).first
            tab.click()
            wait_idle(page)
            ex = exceptions(page)
            problems += len(ex)
            print(f"  workspace section {label!r}: {'OK' if not ex else 'EXCEPTION ' + ex[0][:300]}")
        b.close()
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("evaluation/screenshots")))
