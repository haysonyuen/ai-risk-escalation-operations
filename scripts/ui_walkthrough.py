"""Drive the five-minute demo walkthrough through the real UI in a headless browser.

Requires the app running on :8501 against a freshly seeded database:
  python -m riskops.cli seed
  streamlit run app/streamlit_app.py --server.headless true
  python scripts/ui_walkthrough.py docs/screenshots
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://localhost:8501"


class UI:
    def __init__(self, page, out: Path):
        self.p, self.out, self.n = page, out, 0

    def idle(self):
        self.p.wait_for_timeout(500)
        try:
            self.p.wait_for_selector('[data-testid="stStatusWidget"]', state="detached", timeout=30000)
        except Exception:
            pass
        self.p.wait_for_timeout(500)
        ex = self.p.query_selector_all('[data-testid="stException"]')
        if ex:
            raise RuntimeError("Streamlit exception: " + ex[0].inner_text()[:800])

    def shot(self, name: str, full: bool = True):
        self.n += 1
        path = self.out / f"{self.n:02d}_{name}.png"
        self.p.screenshot(path=str(path), full_page=full)
        print("  screenshot", path.name)

    def nav(self, name: str):
        self.p.locator('[data-testid="stSidebar"]').get_by_text(name, exact=True).click()
        self.idle()

    def select(self, label: str, option: str, scope=None):
        root = scope or self.p
        box = root.locator('[data-testid="stSelectbox"]').filter(has=self.p.get_by_text(label, exact=True)).locator("visible=true").first
        inp = box.locator("input").first
        inp.click()
        inp.fill(option)
        self.p.wait_for_timeout(300)
        self.p.keyboard.press("Enter")
        self.idle()

    def multiselect(self, label: str, options: list[str]):
        box = self.p.locator('[data-testid="stMultiSelect"]').filter(has=self.p.get_by_text(label, exact=True)).locator("visible=true").first
        inp = box.locator("input").first
        for o in options:
            inp.click()
            inp.fill(o)
            self.p.wait_for_timeout(300)
            self.p.keyboard.press("Enter")
            self.p.wait_for_timeout(300)
        self.p.keyboard.press("Escape")

    def fill(self, label: str, text: str, nth: int = 0):
        self.p.get_by_label(label, exact=True).locator("visible=true").nth(nth).fill(text)

    def button(self, name: str, nth: int = 0):
        self.p.get_by_role("button", name=name, exact=True).locator("visible=true").nth(nth).click()
        self.idle()

    def tab(self, name: str):
        self.p.locator('[data-testid="stButtonGroup"]').get_by_text(name, exact=True).locator("visible=true").first.click()
        self.idle()

    def actor(self, display_prefix: str):
        sb = self.p.locator('[data-testid="stSidebar"]')
        box = sb.locator('[data-testid="stSelectbox"]').filter(has=self.p.get_by_text("Acting as (simulated identity)", exact=True)).first
        box.click()
        self.p.get_by_role("option").filter(has_text=display_prefix).first.click()
        self.idle()

    def expect(self, text: str):
        self.p.get_by_text(text).first.wait_for(timeout=15000)


def main(out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        exe = "/opt/pw-browsers/chromium"
        b = pw.chromium.launch(executable_path=exe) if Path(exe).exists() else pw.chromium.launch()
        page = b.new_page(viewport={"width": 1440, "height": 1000})
        ui = UI(page, out)
        try:
            _steps(ui, page)
        except Exception:
            page.screenshot(path=str(out / "FAILURE.png"), full_page=True)
            raise
        b.close()
    print("walkthrough completed")
    return 0


def _steps(ui: "UI", page) -> None:
    if True:
        page.goto(URL)
        page.wait_for_selector("text=AI Risk & Escalation Ops", timeout=30000)
        ui.idle()

        print("0. Queue")
        ui.shot("queue")

        print("1. Intake of an ambiguous but potentially urgent incident (JSON import)")
        ui.nav("New intake")
        ui.tab("JSON import")
        ui.button("Load walkthrough example (data/demo/intake_example.json)")
        ui.button("Import")
        ui.expect("DEMO-2001 · Assistant may have shared")
        ui.shot("intake_imported_report")

        print("2. AI assessment with evidence and unknowns (offline fixture)")
        ui.tab("AI assessment")
        ui.expect("INVALID REF: E5")
        ui.shot("ai_assessment")

        print("3. Human correction with a recorded reason")
        ui.tab("Triage, routing & notes")
        ui.select("Severity", "P0")
        ui.multiselect("Source evidence I reviewed (required for P0/P1)", ["E2", "E3", "E4"])
        ui.select("Override reason (required if different from AI recommendation)", "AI under-estimated severity")
        ui.fill("Rationale", "E2 shows the customer renewals file set to anyone_with_link by the assistant; E4 access log is pending. "
                             "Treat as highly credible exposure of customer pricing until access is ruled out. E5 cited by the AI does not exist.")
        ui.button("Record decision")
        ui.expect("Decision recorded")
        ui.select("Owner", "jordan.legal")
        ui.fill("Reason (optional)", "Privacy lead owns possible customer-data exposure")
        ui.button("Assign owner")
        ui.expect("Owner assigned")
        ui.shot("human_override")

        print("4. Specialist routing and simulated containment approval")
        ui.tab("Containment (simulated)")
        ui.button("Propose")
        ui.expect("Proposed (source: AI)")
        ui.fill("Decision reason", "Narrow, reversible: stop public-link creation while access is checked.")
        ui.button("Approve (simulated)")
        ui.expect("Blocked by service-layer permission check")
        ui.shot("containment_blocked_for_analyst")
        ui.actor("Sam")
        ui.tab("Containment (simulated)")
        ui.fill("Decision reason", "Narrow, reversible: stop public-link creation while access is checked.")
        ui.button("Approve (simulated)")
        ui.expect("Approved — simulated containment active")
        ui.shot("containment_approved_by_lead")

        print("5. Executive brief (draft, needs Legal/Privacy review)")
        ui.tab("Communications (drafts)")
        ui.button("Draft: Executive incident brief")
        ui.expect("needs Legal/Privacy review")
        ui.shot("executive_brief")
        ui.button("Approve for (simulated) use")
        ui.expect("This draft requires review by")
        ui.actor("Jordan")
        ui.tab("Communications (drafts)")
        ui.button("Approve for (simulated) use")
        ui.expect("APPROVED")

        print("6. Human-approved closure")
        ui.actor("Sam")
        ui.tab("Triage, routing & notes")
        ui.select("Move to", "INVESTIGATING")
        ui.button("Apply transition")
        ui.fill("Note", "Access log export received (synthetic): no external views. Link revoked by customer admin.")
        ui.button("Add note")
        ui.tab("Report & evidence")
        ui.fill("Evidence ID (stable, unique)", "E5")
        ui.select("Source type", "telemetry")
        ui.fill("Source description", "Link access log export")
        ui.fill("Content (synthetic only)", "views: 0 external; 2 internal (account team); link revoked 2026-09-28")
        ui.button("Add evidence")
        ui.tab("Triage, routing & notes")
        ui.select("Move to", "RESPONSE")
        ui.button("Apply transition")
        ui.tab("Containment (simulated)")
        ui.fill("Reason to reverse", "Access log E5 shows no external access; restriction no longer needed.")
        ui.button("Reverse (simulated)")
        ui.tab("Closure & QA")
        ui.select("Closure category", "ux_approval_issue")
        ui.fill("Root cause", "Share dialog did not show link visibility; assistant defaulted to anyone_with_link.")
        ui.fill("User / customer impact", "Customer file publicly linkable for ~2h; no external access recorded (E5).")
        ui.multiselect("Evidence reviewed", ["E1", "E2", "E3", "E4", "E5"])
        ui.fill("Actions taken", "Public-link creation restricted (simulated) then reversed; executive brief approved by Legal/Privacy (not sent).")
        ui.fill("Remaining mitigation / follow-up", "Product/UX: show visibility in approval dialog; default to internal-only.")
        ui.p.get_by_text("Monitoring required", exact=True).click()
        ui.fill("Sign-off statement", "Reviewed E1-E5; severity kept P0 for the record; no external access found.")
        ui.button("Sign off and close")
        ui.expect("Closed with human sign-off")
        ui.shot("closed")
        ui.tab("Timeline & audit")
        ui.shot("audit_timeline")

        print("7. Rule change followed by regression evaluation")
        ui.nav("Rules & playbooks")
        ui.tab("Change rules + regression check")
        ui.select("New active version", "rules-v1.1")
        ui.fill("Rationale", "Adopt dev-derived fixes (refusal carve-out, P3 routing, low-confidence floor) pending regression check.")
        ui.button("Change active rule version")
        ui.expect("Active rules → rules-v1.1")
        ui.button("Run regression check")
        ui.expect("QUALITY ALERT")
        ui.shot("regression_alert_v11")
        ui.nav("Quality & evaluation")
        ui.shot("quality_page")
        ui.nav("Monitoring")
        ui.shot("monitoring")


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/screenshots")))
