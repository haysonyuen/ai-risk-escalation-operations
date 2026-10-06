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
        self.p.wait_for_timeout(600)
        try:
            self.p.wait_for_selector('[data-testid="stStatusWidget"]', state="detached", timeout=30000)
        except Exception:
            pass
        self.p.wait_for_timeout(600)
        ex = self.p.query_selector_all('[data-testid="stException"]')
        if ex:
            raise RuntimeError("Streamlit exception: " + ex[0].inner_text()[:800])

    def shot(self, name: str):
        self.n += 1
        path = self.out / f"{self.n:02d}_{name}.png"
        self.p.screenshot(path=str(path))
        print("  screenshot", path.name)

    def scope(self, dialog: bool = False):
        return self.p.locator('[data-testid="stDialog"]').first if dialog else self.p

    def nav(self, name: str):
        self.p.locator('[data-testid="stSidebarNav"]').get_by_text(name, exact=True).click()
        self.idle()

    def _pick(self, box, option: str):
        inp = box.locator("input").first
        inp.click()
        inp.fill(option)
        self.p.wait_for_timeout(300)
        self.p.keyboard.press("Enter")
        self.idle()

    def select(self, label: str, option: str, dialog: bool = False):
        box = self.scope(dialog).locator('[data-testid="stSelectbox"]').filter(has=self.p.get_by_text(label, exact=True)).locator("visible=true").first
        self._pick(box, option)

    def select_option(self, label: str, option: str):
        """Pick by clicking the option whose text contains ``option``."""
        box = self.p.locator('[data-testid="stSelectbox"]').filter(has=self.p.get_by_text(label, exact=True)).locator("visible=true").first
        box.click()
        self.p.get_by_role("option").filter(has_text=option).first.click()
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
        self.idle()

    def fill(self, label: str, text: str, dialog: bool = False):
        self.scope(dialog).get_by_label(label, exact=True).locator("visible=true").first.fill(text)

    def fill_ph(self, placeholder: str, text: str):
        el = self.p.get_by_placeholder(placeholder).locator("visible=true").first
        el.fill(text)
        el.press("Tab")
        self.idle()

    def button(self, name: str, dialog: bool = False, exact: bool = True):
        self.scope(dialog).get_by_role("button", name=name, exact=exact).locator("visible=true").first.click()
        self.idle()

    def is_disabled(self, name: str, dialog: bool = False) -> bool:
        return self.scope(dialog).get_by_role("button", name=name, exact=True).locator("visible=true").first.is_disabled()

    def section(self, name: str):
        self.p.locator('[data-testid="stButtonGroup"]').get_by_text(name, exact=True).locator("visible=true").first.click()
        self.idle()

    def expand(self, starts_with: str):
        det = self.p.locator('[data-testid="stExpander"] details').filter(has=self.p.locator("summary", has_text=starts_with)).first
        if det.get_attribute("open") is None:
            det.locator("summary").first.click()
            self.idle()

    def actor(self, display_prefix: str):
        sb = self.p.locator('[data-testid="stSidebar"]')
        box = sb.locator('[data-testid="stSelectbox"]').filter(has=self.p.get_by_text("Working as", exact=True)).first
        box.click()
        self.p.get_by_role("option").filter(has_text=display_prefix).first.click()
        self.idle()

    def expect(self, text: str, timeout: int = 15000):
        self.p.get_by_text(text).first.wait_for(timeout=timeout)


def _steps(ui: UI) -> None:
    print("0. Queue")
    ui.shot("queue")

    print("0b. C7 automatic pause on a P0 child-safety case: a specialist must confirm or lift it")
    ui.p.goto(URL + "/case?id=INC-1002")
    ui.idle()
    ui.actor("Priya")
    ui.expect("Auto-paused (C7)")
    assert not ui.is_disabled("Confirm pause"), "A Safety specialist must be able to confirm the automatic pause"
    ui.p.get_by_text("Auto-paused (C7)").first.scroll_into_view_if_needed()
    ui.shot("auto_pause_awaiting_review")
    ui.fill_ph("Reason (lifting needs 20+ characters)", "Specialist verdict E1 confirmed; keep the session paused while Child Safety reviews.")
    ui.button("Confirm pause")
    ui.expect("confirmed by Priya")
    ui.actor("Alex")

    print("1. Intake of an ambiguous but potentially urgent incident (JSON import)")
    ui.nav("New report")
    ui.section("Import JSON")
    ui.button("Load the walkthrough example")
    ui.button("Import")
    ui.expect("Assistant may have shared our renewals file")
    ui.expect("Awaiting triage")  # phase chip + bar
    ui.expect("AI assessed · awaiting triage")  # stage detail line
    ui.shot("case_after_import")

    print("2. AI assessment with evidence and unknowns (offline fixture)")
    ui.expect("does not exist in this case")
    ui.p.get_by_text("Facts the AI extracted").first.scroll_into_view_if_needed()
    ui.shot("ai_assessment_facts")

    print("3. Human correction with a recorded reason")
    ui.select("Severity", "P0")
    ui.multiselect("Source evidence I reviewed (required)", ["E2", "E3", "E4"])
    ui.select("Override reason", "AI under-estimated severity")
    ui.fill("Rationale (required)", "E2 shows the renewals file set to anyone_with_link by the assistant; E4 access log pending. "
                                    "Treat as highly credible exposure until access is ruled out. E5 cited by the AI does not exist.")
    ui.button("Record override")
    ui.expect("P0 · confirmed")
    ui.expect("Stage 3 of 8: Triaged")
    ui.select("Owner", "Jordan")
    ui.button("Assign")
    ui.p.get_by_text("Severity & routing decision").first.scroll_into_view_if_needed()
    ui.shot("decision_recorded")

    print("4. Specialist routing and simulated containment approval")
    ui.expand("Containment")
    ui.button("＋ Propose containment")
    ui.button("Propose this")
    ui.expect("Proposed by AI")
    assert ui.is_disabled("Approve"), "Risk Ops must not be able to approve P0 containment"
    ui.p.get_by_text("Approval at").first.scroll_into_view_if_needed()
    ui.shot("containment_needs_incident_lead")
    ui.actor("Sam")
    ui.fill_ph("Decision reason (required)", "Narrow, reversible: stop public-link creation while access is checked.")
    ui.button("Approve")
    ui.expect("ACTIVE · simulated")
    ui.shot("containment_approved")

    print("5. Executive brief (draft, needs Legal/Privacy review)")
    ui.expand("Communications")
    ui.button("＋ New draft")
    ui.button("Executive incident brief")
    ui.button("Open draft")
    ui.expect("EXECUTIVE BRIEF")
    assert ui.is_disabled("Approve", dialog=True), "Incident Lead must not approve a draft flagged for Legal/Privacy"
    ui.shot("executive_brief_dialog")
    ui.p.keyboard.press("Escape")
    ui.idle()
    ui.actor("Jordan")
    ui.button("Open draft")
    ui.button("Approve", dialog=True)

    print("6. Human-approved closure")
    ui.actor("Sam")
    ui.button("Start investigation")
    ui.section("Activity")
    ui.fill("Add an investigation note", "Access log export received (synthetic): no external views. Link revoked by customer admin.")
    ui.button("Add note")
    ui.section("Evidence")
    ui.button("＋ Add evidence")
    ui.select("Source type", "telemetry", dialog=True)
    ui.fill("Source description", "Link access log export", dialog=True)
    ui.fill("Content", "views: 0 external; 2 internal (account team); link revoked", dialog=True)
    ui.button("Add evidence", dialog=True)
    ui.button("Move to response")
    ui.fill_ph("Reason to reverse", "Access log E5 shows no external access; restriction no longer needed.")
    ui.button("Reverse containment")
    ui.button("Close case…")
    ui.select("Closure category", "ux approval issue", dialog=True)
    ui.fill("Root cause", "Share dialog did not show link visibility; assistant defaulted to anyone_with_link.", dialog=True)
    ui.fill("User / customer impact", "File publicly linkable for about 2h; no external access recorded (E5).", dialog=True)
    ui.fill("Actions taken", "Public-link creation restricted (simulated) then reversed; executive brief approved by Legal/Privacy (not sent).", dialog=True)
    ui.fill("Remaining mitigation / follow-up", "Product/UX: show visibility in the approval dialog; default to internal-only.", dialog=True)
    ui.fill("Sign-off statement", "Reviewed E1-E5; severity kept P0 for the record; no external access found.", dialog=True)
    ui.button("Sign off and close", dialog=True)
    ui.expect("Reopen…")
    ui.expect("Closed · QA pending")
    ui.shot("case_closed")
    ui.section("Activity")
    ui.shot("activity_feed")

    print("7. Rule change followed by regression evaluation on the frozen held-out split")
    ui.nav("Rules & playbooks")
    ui.section("Change rules + regression check")
    ui.select("New active version", "rules-v2.1")
    ui.fill("Rationale", "Adopt dev-derived fixes (blocked-attempt refusal, appeal routing, agent external actions) pending regression check.")
    ui.button("Change active rule version")
    ui.button("Run regression check")
    ui.expect("No regression on the gated metrics", timeout=60000)
    ui.shot("regression_check")
    ui.nav("Dashboard")
    ui.expect("Tickets by status")
    ui.shot("dashboard")
    ui.expand("Breakdown by stage")
    ui.nav("Quality & evaluation")
    ui.expect("P0/P1 caught (recall)")
    ui.expect("Rules v2.1 · held-out set (36)")
    ui.shot("quality")
    print("8. Quality tabs: compare, run, overrides, glossary")
    ui.section("Compare versions")
    ui.expect("No regression on the gated metrics")
    ui.expect("Now passing")
    ui.shot("quality_compare")
    ui.section("Run evaluation")
    ui.button("Run evaluation")
    ui.expect("with safety controls v1.2, on the dev set", timeout=60000)  # lands on Results with the new run
    ui.section("Human overrides")
    ui.expect("human decisions")
    ui.section("About & glossary")
    ui.expect("Regression gate")


def main(out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        exe = "/opt/pw-browsers/chromium"
        b = pw.chromium.launch(executable_path=exe) if Path(exe).exists() else pw.chromium.launch()
        page = b.new_page(viewport={"width": 1440, "height": 1000})
        ui = UI(page, out)
        page.goto(URL)
        page.wait_for_selector("text=Incident queue", timeout=30000)
        ui.idle()
        try:
            _steps(ui)
        except Exception:
            page.screenshot(path=str(out / "FAILURE.png"))
            raise
        b.close()
    print("walkthrough completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/screenshots")))
