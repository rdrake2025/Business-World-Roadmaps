"""Test suite for the AnswerRank platform.

Focus is on the logic that costs money or credibility when it breaks:
answer parsing, scoring, billing idempotency, outreach compliance gates and
prospect deduplication.

Run with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from answerrank.agents.bookkeeper import BookkeeperAgent
from answerrank.agents.fixer import FixerAgent, faq_pairs, faq_schema, localbusiness_schema
from answerrank.agents.outreach import OutreachAgent, first_touch
from answerrank.agents.scout import ScoutAgent
from answerrank.agents.auditor import AuditorAgent
from answerrank.audit import run_audit
from answerrank.config import Settings
from answerrank.engines.base import detect_sentiment, extract_businesses, name_matches, normalize
from answerrank.mailer import build_message
from answerrank.models import (
    Audit, Business, Client, LedgerEntry, OutreachMessage, ProbeResult, Prospect,
)
from answerrank.orchestrator import Orchestrator
from answerrank.scoring import (
    competitor_gap, generate_findings, grade, interpret, prominence_value,
    score_audit, share_of_voice,
)
from answerrank.store import Store

import json
import logging

SAMPLE_ANSWER = """Here are the top HVAC companies in Austin, TX:

1. **Cool Breeze Air Conditioning** - highly rated, 24/7 emergency service
2. **Lone Star Heating & Air** (4.8 stars)
3. **Apex HVAC Services** - family owned since 1998

All three are trusted and well-reviewed."""


def make_settings(tmpdir: str) -> Settings:
    s = Settings()
    s.demo_mode = True
    s.database_path = os.path.join(tmpdir, "test.db")
    s.output_dir = os.path.join(tmpdir, "out")
    os.makedirs(s.output_dir, exist_ok=True)
    return s


class TestAnswerParsing(unittest.TestCase):
    def test_extracts_businesses_in_order(self):
        names = extract_businesses(SAMPLE_ANSWER)
        self.assertEqual(names[0], "Cool Breeze Air Conditioning")
        self.assertEqual(len(names), 3)

    def test_strips_trailing_descriptions(self):
        self.assertNotIn("highly rated", extract_businesses(SAMPLE_ANSWER)[0])

    def test_exact_and_fuzzy_matching(self):
        self.assertTrue(name_matches("Apex HVAC", SAMPLE_ANSWER))
        self.assertTrue(name_matches("Cool Breeze AC", SAMPLE_ANSWER))

    def test_rejects_absent_business(self):
        self.assertFalse(name_matches("Ghost Plumbing Co", SAMPLE_ANSWER))

    def test_stopwords_do_not_cause_false_positives(self):
        # "The Services Company" is all stopwords; must not match everything.
        self.assertFalse(name_matches("The Services Company", SAMPLE_ANSWER))

    def test_normalize_handles_accents_and_punctuation(self):
        self.assertEqual(normalize("Café  Aküt, Inc."), "cafe akut inc")

    def test_sentiment(self):
        self.assertEqual(detect_sentiment(SAMPLE_ANSWER, "Apex HVAC"), "positive")
        self.assertEqual(detect_sentiment(SAMPLE_ANSWER, "Nobody Inc"), "absent")
        neg = "Avoid **Shady Roofing** — numerous complaints and poor reviews."
        self.assertEqual(detect_sentiment(neg, "Shady Roofing"), "negative")

    def test_empty_input_is_safe(self):
        self.assertEqual(extract_businesses(""), [])
        self.assertFalse(name_matches("Anything", ""))
        self.assertFalse(name_matches("", "some text"))


class TestScoring(unittest.TestCase):
    def test_prominence_decays_with_rank(self):
        vals = [prominence_value(i, 5) for i in (1, 2, 3, 4)]
        self.assertEqual(vals[0], 1.0)
        self.assertTrue(all(vals[i] > vals[i + 1] for i in range(len(vals) - 1)))
        self.assertEqual(prominence_value(None, 5), 0.0)

    def test_interpret_finds_position_and_competitors(self):
        got = interpret(SAMPLE_ANSWER, ["https://apexhvac.com"], "Apex HVAC", "apexhvac.com")
        self.assertTrue(got["mentioned"])
        self.assertEqual(got["position"], 3)
        self.assertTrue(got["cited"])
        self.assertIn("Cool Breeze Air Conditioning", got["competitors"])

    def test_citation_requires_domain_in_sources(self):
        got = interpret(SAMPLE_ANSWER, ["https://yelp.com"], "Apex HVAC", "apexhvac.com")
        self.assertFalse(got["cited"])

    def test_invisible_business_scores_zero(self):
        audit = Audit(business_id="b", business_name="Ghost Co", market="Austin, TX", vertical="hvac")
        audit.results = [
            ProbeResult(probe_id="p", engine="mock", prompt="q", answer_text=SAMPLE_ANSWER,
                        mentioned=False, cited=False, position=None, sentiment="absent")
            for _ in range(5)
        ]
        score_audit(audit)
        self.assertEqual(audit.score, 0.0)
        self.assertEqual(grade(audit.score), "F")

    def test_dominant_business_scores_high(self):
        audit = Audit(business_id="b", business_name="Apex", market="Austin, TX", vertical="hvac")
        audit.results = [
            ProbeResult(probe_id="p", engine="mock", prompt="q", answer_text="x",
                        mentioned=True, cited=True, position=1, sentiment="positive")
            for _ in range(5)
        ]
        score_audit(audit)
        self.assertEqual(audit.score, 100.0)
        self.assertEqual(grade(audit.score), "A")

    def test_score_bounded_and_errors_ignored(self):
        audit = Audit(business_id="b", business_name="X", market="M", vertical="hvac")
        audit.results = [
            ProbeResult(probe_id="p", engine="mock", prompt="q", answer_text="",
                        mentioned=False, cited=False, position=None, error="HTTP 500"),
            ProbeResult(probe_id="p", engine="mock", prompt="q", answer_text="x",
                        mentioned=True, cited=False, position=1, sentiment="neutral"),
        ]
        score_audit(audit)
        self.assertTrue(0.0 <= audit.score <= 100.0)
        # The errored probe must not drag presence down.
        self.assertEqual(audit.subscores["presence"], 100.0)

    def test_all_errors_yields_zero_not_crash(self):
        audit = Audit(business_id="b", business_name="X", market="M", vertical="hvac")
        audit.results = [ProbeResult(probe_id="p", engine="mock", prompt="q", answer_text="",
                                     mentioned=False, cited=False, position=None, error="boom")]
        score_audit(audit)
        self.assertEqual(audit.score, 0.0)
        self.assertIn("No answer engines responded", audit.findings[0])

    def test_share_of_voice_sums_to_100(self):
        audit = Audit(business_id="b", business_name="Apex", market="M", vertical="hvac")
        audit.results = [ProbeResult(probe_id="p", engine="mock", prompt="q", answer_text="x",
                                     mentioned=True, cited=False, position=1) for _ in range(3)]
        audit.competitors = {"Rival A": 5, "Rival B": 2}
        self.assertAlmostEqual(sum(share_of_voice(audit).values()), 100.0, places=0)

    def test_competitor_gap_positive_when_behind(self):
        audit = Audit(business_id="b", business_name="Apex", market="M", vertical="hvac")
        audit.results = [ProbeResult(probe_id="p", engine="mock", prompt="q", answer_text="x",
                                     mentioned=False, cited=False, position=None) for _ in range(10)]
        audit.competitors = {"Rival": 8}
        self.assertEqual(competitor_gap(audit), 80.0)

    def test_findings_are_plain_english(self):
        audit = Audit(business_id="b", business_name="Apex", market="Austin, TX", vertical="hvac")
        audit.results = [ProbeResult(probe_id="p", engine="mock", prompt="q", answer_text="x",
                                     mentioned=False, cited=False, position=None) for _ in range(4)]
        audit.competitors = {"Rival": 4}
        audit.subscores = {"presence": 0, "prominence": 0, "citation": 0, "sentiment": 0}
        findings = generate_findings(audit)
        self.assertTrue(any("not named in any" in f for f in findings))
        self.assertTrue(any("Rival" in f for f in findings))


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.tmp.name, "t.db"))

    def tearDown(self):
        self.tmp.cleanup()

    def _biz(self, n=1):
        return Business(name=f"Biz {n}", city="Austin", state="TX", vertical="hvac",
                        website=f"https://biz{n}.com", email=f"a@biz{n}.com")

    def test_prospect_dedup_by_domain(self):
        for _ in range(3):
            self.store.upsert_prospect(Prospect(business=self._biz()))
        self.assertEqual(sum(self.store.count_prospects_by_stage().values()), 1)

    def test_www_and_scheme_normalised_to_same_domain(self):
        a = Business(name="A", city="Austin", website="https://www.same.com")
        b = Business(name="A", city="Austin", website="http://same.com/contact")
        self.assertEqual(a.domain, b.domain)

    def test_pnl_math(self):
        self.store.add_ledger(LedgerEntry(kind="revenue", category="subscription", amount=1000))
        self.store.add_ledger(LedgerEntry(kind="cost", category="api", amount=250))
        pnl = self.store.pnl(30)
        self.assertEqual(pnl["profit"], 750.0)
        self.assertAlmostEqual(pnl["margin"], 0.75, places=3)

    def test_suppression(self):
        self.store.suppress("Owner@Example.COM ", "unsubscribed")
        self.assertTrue(self.store.is_suppressed("owner@example.com"))
        self.assertFalse(self.store.is_suppressed("other@example.com"))

    def test_mrr_excludes_churned(self):
        self.store.upsert_client(Client(business=self._biz(1), mrr=500, status="active"))
        self.store.upsert_client(Client(business=self._biz(2), mrr=900, status="churned"))
        self.assertEqual(self.store.mrr(), 500.0)


class TestBilling(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = make_settings(self.tmp.name)
        self.store = Store(self.settings.database_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_billing_is_idempotent(self):
        biz = Business(name="Client A", city="Austin", state="TX", website="https://a.com")
        self.store.upsert_client(Client(business=biz, plan="growth", mrr=997, status="active"))
        agent = BookkeeperAgent(self.store, self.settings)
        first = agent.run()
        second = agent.run()
        self.assertEqual(first.items_processed, 1)
        self.assertEqual(second.items_processed, 0)
        self.assertEqual(self.store.pnl(30)["revenue"], 997.0)

    def test_six_growth_clients_clear_the_target(self):
        for i in range(6):
            biz = Business(name=f"C{i}", city="Austin", state="TX", website=f"https://c{i}.com")
            self.store.upsert_client(Client(business=biz, plan="growth", mrr=997, status="active"))
        agent = BookkeeperAgent(self.store, self.settings)
        agent.run()
        self.assertGreaterEqual(agent.kpis()["profit"], self.settings.profit_target_monthly)

    def test_kpis_report_clients_needed(self):
        kpis = BookkeeperAgent(self.store, self.settings).kpis()
        self.assertGreater(kpis["clients_needed_at_growth"], 0)
        self.assertEqual(kpis["mrr"], 0.0)


class TestOutreachCompliance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = make_settings(self.tmp.name)
        self.store = Store(self.settings.database_path)
        self.agent = OutreachAgent(self.store, self.settings)

    def tearDown(self):
        self.tmp.cleanup()

    def test_preflight_blocks_without_physical_address(self):
        problems = self.agent.preflight()
        self.assertTrue(any("CAN-SPAM" in p for p in problems))

    def test_preflight_passes_once_configured(self):
        self.settings.physical_address = "123 Main St, Austin, TX 78701"
        self.assertEqual(OutreachAgent(self.store, self.settings).preflight(), [])

    def test_every_message_carries_unsubscribe_and_address(self):
        biz = Business(name="Apex HVAC", city="Austin", state="TX", vertical="hvac",
                       website="https://apex.com", email="o@apex.com")
        prospect = Prospect(business=biz, score=10.0, competitor_gap=60.0)
        _subject, body = first_touch(prospect, self.settings)
        self.assertIn("unsubscribe", body.lower())
        self.assertIn(self.settings.company_legal_name, body)

    def test_suppressed_prospects_are_never_drafted(self):
        biz = Business(name="Apex HVAC", city="Austin", state="TX", vertical="hvac",
                       website="https://apex.com", email="o@apex.com")
        self.store.upsert_prospect(Prospect(business=biz, stage="audited", score=5.0,
                                            competitor_gap=80.0))
        self.store.suppress("o@apex.com", "unsubscribed")
        self.agent.run()
        self.assertEqual(len(self.store.get_messages("drafted")), 0)

    def test_prospects_without_evidence_are_not_pitched(self):
        biz = Business(name="Strong Co", city="Austin", state="TX", vertical="hvac",
                       website="https://strong.com", email="o@strong.com")
        self.store.upsert_prospect(Prospect(business=biz, stage="audited", score=90.0,
                                            competitor_gap=0.0))
        self.agent.run()
        self.assertEqual(len(self.store.get_messages("drafted")), 0)

    def test_messages_are_drafted_not_sent(self):
        biz = Business(name="Apex HVAC", city="Austin", state="TX", vertical="hvac",
                       website="https://apex.com", email="o@apex.com")
        self.store.upsert_prospect(Prospect(business=biz, stage="audited", score=10.0,
                                            competitor_gap=70.0))
        self.agent.run()
        msgs = self.store.get_messages()
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].status, "drafted")

    def test_rfc8058_one_click_headers(self):
        msg = build_message("a@b.com", "Subject", "Body", self.settings)
        self.assertIn("List-Unsubscribe", msg)
        self.assertEqual(msg["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")


class TestDeliverables(unittest.TestCase):
    def setUp(self):
        self.biz = Business(name="Apex Heating & Air", city="Austin", state="TX",
                            vertical="hvac", website="https://apexhvac.com",
                            phone="+1-512-555-0199")

    def test_localbusiness_schema_is_valid_json_and_typed(self):
        doc = json.loads(localbusiness_schema(self.biz))
        self.assertEqual(doc["@type"], "HVACBusiness")
        self.assertEqual(doc["@context"], "https://schema.org")
        self.assertEqual(doc["address"]["addressLocality"], "Austin")

    def test_faq_schema_is_valid_faqpage(self):
        doc = json.loads(faq_schema(faq_pairs(self.biz, None)))
        self.assertEqual(doc["@type"], "FAQPage")
        self.assertTrue(all(q["@type"] == "Question" for q in doc["mainEntity"]))

    def test_faq_answers_mention_the_market(self):
        pairs = faq_pairs(self.biz, None)
        self.assertTrue(any("Austin" in a for _q, a in pairs))

    def test_verticals_map_to_real_schema_types(self):
        for vertical, expected in [("plumbing", "Plumber"), ("dental", "Dentist"),
                                   ("legal", "Attorney"), ("unknown_x", "LocalBusiness")]:
            biz = Business(name="X", city="Austin", vertical=vertical, website="https://x.com")
            self.assertEqual(json.loads(localbusiness_schema(biz))["@type"], expected)


class TestPipelineIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = make_settings(self.tmp.name)
        self.store = Store(self.settings.database_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_audit_runs_offline_and_scores(self):
        biz = Business(name="Apex HVAC", city="Austin", state="TX", vertical="hvac",
                       website="https://apexhvac.com")
        audit = run_audit(biz, self.settings, depth="teaser")
        self.assertEqual(len(audit.results), 4)
        self.assertTrue(0.0 <= audit.score <= 100.0)
        self.assertTrue(audit.findings)

    def test_scout_to_outreach_end_to_end(self):
        ScoutAgent(self.store, self.settings, target_per_run=6).run()
        AuditorAgent(self.store, self.settings).run()
        OutreachAgent(self.store, self.settings).run()
        stages = self.store.count_prospects_by_stage()
        self.assertGreater(stages.get("queued", 0), 0)
        self.assertGreater(len(self.store.get_messages("drafted")), 0)

    def test_agent_failure_does_not_stop_the_fleet(self):
        # The agent logs the traceback by design; silence it so test output
        # stays readable. We assert on the recorded run status instead.
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)

        class Exploding(ScoutAgent):
            name = "exploding"
            def execute(self):
                raise RuntimeError("boom")

        orch = Orchestrator(self.store, self.settings,
                            agents=[Exploding(self.store, self.settings),
                                    BookkeeperAgent(self.store, self.settings)])
        lines = orch.tick(force=True)
        self.assertEqual(len(lines), 2)
        self.assertTrue(any("ERR" in l for l in lines))
        runs = {r["agent"]: r["status"] for r in self.store.recent_runs(10)}
        self.assertEqual(runs["exploding"], "error")
        self.assertEqual(runs["bookkeeper"], "ok")

    def test_scheduler_does_not_rerun_before_interval(self):
        orch = Orchestrator(self.store, self.settings)
        self.assertGreater(len(orch.tick(force=True)), 0)
        self.assertEqual(len(orch.tick()), 0)

    def test_report_renders_with_required_sections(self):
        from answerrank.agents.reporter import render_report
        biz = Business(name="Apex HVAC", city="Austin", state="TX", vertical="hvac",
                       website="https://apexhvac.com")
        audit = run_audit(biz, self.settings, depth="teaser")
        deliverables = FixerAgent(self.store, self.settings).build_for(biz, audit)
        html = render_report(audit, self.settings, [audit], deliverables)
        for needle in ("Visibility Score", "Apex HVAC", "action plan", "Full test log"):
            self.assertIn(needle.lower(), html.lower())

    def test_report_escapes_html_in_business_name(self):
        from answerrank.agents.reporter import render_report
        biz = Business(name="<script>alert(1)</script> HVAC", city="Austin", state="TX",
                       vertical="hvac", website="https://x.com")
        audit = run_audit(biz, self.settings, depth="teaser")
        html = render_report(audit, self.settings, [audit], [])
        self.assertNotIn("<script>alert(1)</script>", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestBudget(unittest.TestCase):
    def setUp(self):
        from answerrank.budget import Personal
        self.me = Personal(monthly_income=2500.0, income_is_take_home=True, savings=0.0,
                           expenses={"rent": 250, "food": 350, "phone": 50,
                                     "transport": 200, "utilities": 120, "other": 200})

    def test_disposable_math(self):
        self.assertEqual(self.me.total_expenses, 1170.0)
        self.assertEqual(self.me.disposable, 1330.0)

    def test_gross_income_is_haircut(self):
        from answerrank.budget import Personal
        gross = Personal(monthly_income=2500.0, income_is_take_home=False)
        self.assertLess(gross.net_income, 2500.0)

    def test_runway_indefinite_when_surplus_covers_burn(self):
        from answerrank.budget import runway_months
        self.assertEqual(runway_months(0, 12.20, 1330.0), float("inf"))

    def test_runway_eats_savings_only_on_shortfall(self):
        from answerrank.budget import runway_months
        # $300 saved, $100/mo burn, $50/mo surplus -> $50 shortfall -> 6 months
        self.assertEqual(runway_months(300, 100, 50), 6.0)

    def test_runway_zero_when_broke_and_short(self):
        from answerrank.budget import runway_months
        self.assertEqual(runway_months(0, 100, 0), 0.0)

    def test_phase_zero_is_affordable(self):
        from answerrank.budget import phase_cost
        one_time, monthly = phase_cost("0_test")
        self.assertLess(one_time, 50)
        self.assertLess(monthly, 20)

    def test_phases_are_cumulative(self):
        from answerrank.budget import cumulative_monthly
        self.assertLess(cumulative_monthly("0_test"), cumulative_monthly("2_scaling"))

    def test_reinvestment_splits_sum_to_profit(self):
        from answerrank.budget import reinvestment_split
        for profit in (500, 1400, 3500, 6000):
            split = reinvestment_split(profit)
            split.pop("_note", None)
            self.assertAlmostEqual(sum(split.values()), profit, places=1)

    def test_tax_reserve_is_always_thirty_percent(self):
        from answerrank.budget import reinvestment_split
        for profit in (500, 1400, 3500, 6000):
            self.assertAlmostEqual(reinvestment_split(profit)["tax_reserve"],
                                   profit * 0.30, places=1)

    def test_early_profit_pays_nothing_out(self):
        from answerrank.budget import reinvestment_split
        self.assertEqual(reinvestment_split(500)["to_you"], 0.0)

    def test_zero_profit_splits_to_zero(self):
        from answerrank.budget import reinvestment_split
        split = reinvestment_split(0)
        self.assertEqual(sum(v for k, v in split.items() if not k.startswith("_")), 0.0)

    def test_quit_threshold_exceeds_job_income(self):
        from answerrank.budget import quit_threshold
        q = quit_threshold(2500)
        self.assertGreater(q["profit_to_match_pay"], 2500)
        self.assertGreater(q["safe_quit_profit"], q["profit_to_match_pay"])


class TestSchedule(unittest.TestCase):
    """The calendar has to import cleanly into a real phone, so these assert
    on RFC 5545 structure, not just that a file was produced."""

    def _cal(self, start):
        from answerrank.schedule import build_calendar
        return build_calendar(start)

    def test_is_wellformed_ics(self):
        import datetime
        ics = self._cal(datetime.date(2026, 9, 21))
        self.assertTrue(ics.startswith("BEGIN:VCALENDAR"))
        self.assertTrue(ics.rstrip().endswith("END:VCALENDAR"))
        self.assertEqual(ics.count("BEGIN:VEVENT"), ics.count("END:VEVENT"))

    def test_crlf_line_endings_only(self):
        import datetime
        ics = self._cal(datetime.date(2026, 9, 21))
        self.assertNotIn("\n", ics.replace("\r\n", ""))

    def test_no_line_exceeds_75_octets(self):
        import datetime
        ics = self._cal(datetime.date(2026, 9, 21))
        for line in ics.split("\r\n"):
            self.assertLessEqual(len(line.encode("utf-8")), 75, f"too long: {line[:40]}")

    def test_escapes_special_characters(self):
        from answerrank.schedule import _escape
        self.assertEqual(_escape("a,b;c\\d\ne"), "a\\,b\;c\\\\d\\ne")

    def test_launch_tasks_never_collide_or_reorder(self):
        import datetime
        from answerrank.schedule import launch_events
        for offset in range(7):  # every possible start weekday
            events = launch_events(datetime.date(2026, 9, 21) + datetime.timedelta(days=offset))
            starts = [e.start for e in events]
            self.assertEqual(starts, sorted(starts), "launch tasks out of order")
            self.assertEqual(len(starts), len(set(starts)), "launch tasks collide")

    def test_nothing_scheduled_on_the_rest_day(self):
        import datetime
        from answerrank.schedule import launch_events
        for offset in range(7):
            for e in launch_events(datetime.date(2026, 9, 21) + datetime.timedelta(days=offset)):
                self.assertNotEqual(e.start.weekday(), 6, f"{e.summary} lands on Sunday")

    def test_long_blocks_land_on_saturday(self):
        import datetime
        from answerrank.schedule import launch_events
        for e in launch_events(datetime.date(2026, 9, 21)):
            if e.minutes >= 90:
                self.assertEqual(e.start.weekday(), 5, f"{e.summary} needs a Saturday")

    def test_warmup_starts_after_dns_is_configured(self):
        import datetime
        from answerrank.schedule import launch_events, warmup_events
        for offset in range(7):
            start = datetime.date(2026, 9, 21) + datetime.timedelta(days=offset)
            events = launch_events(start)
            dns = next(e.start.date() for e in events if "DNS" in e.summary)
            send = next(e.start.date() for e in events if "FIRST SEND" in e.summary)
            warm = warmup_events(dns, send)[0]
            self.assertGreater(warm.start.date(), dns)

    def test_every_event_carries_instructions(self):
        import datetime
        from answerrank.schedule import launch_events, recurring_events
        for e in launch_events(datetime.date(2026, 9, 21)) + recurring_events(datetime.date(2026, 9, 21)):
            self.assertTrue(e.description.strip(), f"{e.summary} has no instructions")

    def test_recurring_only_mode_has_no_launch_tasks(self):
        import datetime
        from answerrank.schedule import build_calendar
        ics = build_calendar(datetime.date(2026, 9, 21), include_launch=False)
        self.assertNotIn("LAUNCH", ics)
        self.assertIn("Morning ops", ics)


class TestWebApp(unittest.TestCase):
    """The unsubscribe endpoint is a legal requirement, not a feature.
    These tests assert the behaviour CAN-SPAM and RFC 8058 actually demand."""

    def setUp(self):
        from web.app import Application
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = make_settings(self.tmp.name)
        self.store = Store(self.settings.database_path)
        self.app = Application(self.settings, self.store)
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, path, method="GET", form=None, qs=""):
        import io
        import urllib.parse
        from wsgiref.util import setup_testing_defaults
        env = {}
        setup_testing_defaults(env)
        env["PATH_INFO"], env["REQUEST_METHOD"], env["QUERY_STRING"] = path, method, qs
        if form is not None:
            body = urllib.parse.urlencode(form).encode()
            env["wsgi.input"] = io.BytesIO(body)
            env["CONTENT_LENGTH"] = str(len(body))
        captured = {}
        body = b"".join(self.app(env, lambda s, h: captured.update(status=s, headers=dict(h))))
        return captured["status"], captured.get("headers", {}), body

    def _seed(self, email="owner@apex.com", stage="contacted"):
        biz = Business(name="Apex HVAC", city="Austin", state="TX", vertical="hvac",
                       website="https://apex.com", email=email)
        p = Prospect(business=biz, stage=stage, score=10.0, competitor_gap=70.0)
        self.store.upsert_prospect(p)
        return p

    # ---- routing ----

    def test_all_public_routes_serve(self):
        for path in ("/", "/privacy", "/terms", "/unsubscribe", "/health"):
            status, _h, body = self.call(path)
            self.assertTrue(status.startswith("200"), f"{path} -> {status}")
            self.assertTrue(body)

    def test_unknown_path_is_404_not_500(self):
        status, _h, _b = self.call("/nope")
        self.assertTrue(status.startswith("404"))

    def test_security_headers_present(self):
        _s, headers, _b = self.call("/")
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(headers.get("X-Frame-Options"), "DENY")

    # ---- RFC 8058 one-click ----

    def test_one_click_post_suppresses_and_returns_200(self):
        self._seed()
        status, _h, body = self.call("/unsubscribe", "POST",
                                     {"List-Unsubscribe": "One-Click"}, qs="e=owner@apex.com")
        self.assertTrue(status.startswith("200"))
        self.assertIn(b"Unsubscribed", body)
        self.assertTrue(self.store.is_suppressed("owner@apex.com"))

    def test_one_click_without_address_still_returns_200(self):
        # A non-2xx here makes mail clients flag the sender.
        status, _h, _b = self.call("/unsubscribe", "POST", {"List-Unsubscribe": "One-Click"})
        self.assertTrue(status.startswith("200"))

    def test_unsubscribe_halts_queued_sequence(self):
        p = self._seed()
        self.store.save_message(OutreachMessage(prospect_id=p.id, subject="s", body="b",
                                                status="approved"))
        self.call("/unsubscribe", "POST", {"email": "owner@apex.com"})
        self.assertEqual(len(self.store.get_messages("approved")), 0)
        self.assertEqual(self.store.get_prospects(limit=5)[0].stage, "suppressed")

    def test_unsubscribe_is_case_insensitive(self):
        self.call("/unsubscribe", "POST", {"email": "  Owner@APEX.com "})
        self.assertTrue(self.store.is_suppressed("owner@apex.com"))

    def test_invalid_email_does_not_pollute_suppression_list(self):
        status, _h, _b = self.call("/unsubscribe", "POST", {"email": "not-an-email"})
        self.assertTrue(status.startswith("200"))
        self.assertFalse(self.store.is_suppressed("not-an-email"))

    def test_unsubscribe_is_idempotent(self):
        self._seed()
        for _ in range(3):
            status, _h, _b = self.call("/unsubscribe", "POST", {"email": "owner@apex.com"})
            self.assertTrue(status.startswith("200"))
        self.assertTrue(self.store.is_suppressed("owner@apex.com"))

    def test_get_prefills_address_from_query(self):
        _s, _h, body = self.call("/unsubscribe", qs="e=owner@apex.com")
        self.assertIn(b"owner@apex.com", body)

    # ---- lead capture ----

    def test_inbound_lead_is_captured_and_flagged(self):
        status, _h, _b = self.call("/audit-request", "POST", {
            "business": "Summit Plumbing", "city": "Tampa", "state": "FL",
            "vertical": "plumbing", "email": "info@summit.com",
            "website": "https://summitplumb.com"})
        self.assertTrue(status.startswith("200"))
        leads = [p for p in self.store.get_prospects(limit=50) if "INBOUND" in (p.notes or "")]
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0].business.name, "Summit Plumbing")

    def test_incomplete_lead_is_rejected(self):
        status, _h, _b = self.call("/audit-request", "POST",
                                   {"business": "", "city": "", "email": "bad"})
        self.assertTrue(status.startswith("400"))

    def test_lead_get_redirects(self):
        status, _h, _b = self.call("/audit-request", "GET")
        self.assertTrue(status.startswith("302"))

    def test_landing_escapes_injected_error_text(self):
        from web.app import render
        body = render("landing.html", error="<script>alert(1)</script>")
        self.assertNotIn(b"<script>alert(1)</script>", body)

    def test_unconfigured_address_not_rendered_publicly(self):
        _s, _h, body = self.call("/")
        self.assertNotIn(b"SET_YOUR_REGISTERED", body)


class TestDoctor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = make_settings(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_flags_missing_address_as_blocking(self):
        from answerrank.doctor import check_address
        c = check_address(self.settings)
        self.assertEqual(c.status, "FAIL")
        self.assertTrue(c.blocking)

    def test_accepts_real_address(self):
        from answerrank.doctor import check_address
        self.settings.physical_address = "123 Main St, Suite 100, Austin, TX 78701"
        self.assertEqual(check_address(self.settings).status, "PASS")

    def test_flags_placeholder_identity(self):
        from answerrank.doctor import check_identity
        self.assertEqual(check_identity(self.settings).status, "FAIL")

    def test_accepts_real_identity(self):
        from answerrank.doctor import check_identity
        self.settings.from_email = "hello@realdomain.com"
        self.settings.website = "https://realdomain.com"
        self.assertEqual(check_identity(self.settings).status, "PASS")

    def test_summarise_counts_blockers(self):
        from answerrank.doctor import run_all, summarise
        checks = run_all(self.settings)
        _p, _w, _f, blockers = summarise(checks)
        self.assertGreater(len(blockers), 0)
        self.assertTrue(all(c.blocking for c in blockers))

    def test_every_failing_check_offers_a_fix(self):
        from answerrank.doctor import run_all
        for c in run_all(self.settings):
            if c.status != "PASS":
                self.assertTrue(c.fix.strip(), f"{c.name} has no fix instruction")

    def test_python_and_dependencies_pass_here(self):
        from answerrank.doctor import check_dependencies, check_python
        self.assertEqual(check_python().status, "PASS")
        self.assertEqual(check_dependencies().status, "PASS")
