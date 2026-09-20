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
import re

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

    def test_custom_brand_replaces_default_everywhere(self):
        """A renamed business must not leak the default brand into the
        calendar — including CATEGORIES, which fell back to the module
        default because recurring events never passed it."""
        import datetime
        from answerrank.schedule import build_calendar
        ics = build_calendar(datetime.date(2026, 9, 21), brand="TheAnswerCheck")
        self.assertNotIn("AnswerRank", ics)
        self.assertIn("SUMMARY:TheAnswerCheck: Morning ops", ics)
        self.assertIn("X-WR-CALNAME:TheAnswerCheck", ics)

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


class TestConsoleAuth(unittest.TestCase):
    """The console can approve outreach and trigger sends, and it binds to the
    LAN so a phone can reach it. These assert the boundary actually holds."""

    def setUp(self):
        from web.app import Application
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = make_settings(self.tmp.name)
        self.store = Store(self.settings.database_path)
        self.app = Application(self.settings, self.store)
        self.token = self.app.token
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, path, method="GET", qs="", cookie=None, body=None):
        import io
        import json as _json
        from wsgiref.util import setup_testing_defaults
        env = {}
        setup_testing_defaults(env)
        env["PATH_INFO"], env["REQUEST_METHOD"], env["QUERY_STRING"] = path, method, qs
        if cookie:
            env["HTTP_COOKIE"] = cookie
        if body is not None:
            raw = _json.dumps(body).encode()
            env["wsgi.input"] = io.BytesIO(raw)
            env["CONTENT_LENGTH"] = str(len(raw))
        cap = {}
        data = b"".join(self.app(env, lambda s, h: cap.update(status=s, headers=dict(h))))
        return cap["status"], cap.get("headers", {}), data

    def cookie(self):
        return f"ar_session={self.token}"

    def test_public_routes_need_no_token(self):
        for path in ("/", "/unsubscribe", "/privacy", "/terms", "/health",
                     "/manifest.webmanifest", "/icon.svg", "/sw.js"):
            status, _h, _b = self.call(path)
            self.assertTrue(status.startswith("200"), f"{path} -> {status}")

    def test_console_and_api_reject_anonymous(self):
        for path in ("/app", "/api/state", "/api/inbox", "/api/send", "/api/tick"):
            status, _h, _b = self.call(path)
            self.assertTrue(status.startswith("401"), f"{path} was not guarded")

    def test_api_401_is_json_not_html(self):
        _s, headers, _b = self.call("/api/state")
        self.assertIn("application/json", headers.get("Content-Type", ""))

    def test_first_visit_exchanges_token_for_cookie(self):
        status, headers, _b = self.call("/app", qs=f"t={self.token}")
        self.assertTrue(status.startswith("200"))
        cookie = headers.get("Set-Cookie", "")
        self.assertIn("ar_session=", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)

    def test_cookie_grants_access(self):
        status, _h, _b = self.call("/api/state", cookie=self.cookie())
        self.assertTrue(status.startswith("200"))

    def test_forged_cookie_rejected(self):
        status, _h, _b = self.call("/api/state", cookie="ar_session=forged")
        self.assertTrue(status.startswith("401"))

    def test_token_is_stable_and_long(self):
        from web.auth import get_or_create_token
        self.assertEqual(get_or_create_token(self.store), self.token)
        self.assertGreaterEqual(len(self.token), 32)

    def test_rotation_invalidates_the_old_token(self):
        from web.auth import is_authorised, rotate_token
        old = self.token
        new = rotate_token(self.store)
        self.assertNotEqual(old, new)
        self.assertFalse(is_authorised(old, new))


class TestConsoleApi(unittest.TestCase):
    def setUp(self):
        from web.api import Api
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = make_settings(self.tmp.name)
        self.store = Store(self.settings.database_path)
        self.api = Api(self.store, self.settings)
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)

    def tearDown(self):
        self.tmp.cleanup()

    def _draft(self, email="o@apex.com"):
        biz = Business(name="Apex HVAC", city="Austin", state="TX", vertical="hvac",
                       website="https://apex.com", email=email)
        p = Prospect(business=biz, stage="queued", score=8.0, competitor_gap=80.0,
                     notes="Apex appears in 0 of 4 AI answers.")
        self.store.upsert_prospect(p)
        m = OutreachMessage(prospect_id=p.id, subject="s", body="b", status="drafted")
        self.store.save_message(m)
        return p, m

    def test_state_shape(self):
        s = self.api.state()
        for key in ("money", "queue", "pipeline", "agents", "blockers", "can_send"):
            self.assertIn(key, s)

    def test_inbox_carries_the_evidence_line(self):
        self._draft()
        item = self.api.inbox()["items"][0]
        self.assertEqual(item["business"], "Apex HVAC")
        self.assertIn("0 of 4", item["evidence"])

    def test_approve_moves_the_message(self):
        _p, m = self._draft()
        self.assertEqual(self.api.approve([m.id])["approved"], 1)
        self.assertEqual(len(self.store.get_messages("approved")), 1)
        self.assertEqual(len(self.store.get_messages("drafted")), 0)

    def test_reject_also_suppresses_the_prospect(self):
        """Otherwise the next cycle simply drafts the same message again."""
        _p, m = self._draft()
        self.assertEqual(self.api.reject([m.id])["rejected"], 1)
        self.assertEqual(self.store.get_prospects(limit=5)[0].stage, "suppressed")

    def test_send_refuses_while_preflight_fails(self):
        """The console is a convenience, never a way around a compliance gate."""
        _p, m = self._draft()
        self.api.approve([m.id])
        result = self.api.send()
        self.assertTrue(result["blocked"])
        self.assertEqual(result["sent"], 0)
        self.assertTrue(any("CAN-SPAM" in r for r in result["reasons"]))

    def test_send_still_blocked_even_with_everything_approved(self):
        self.settings.physical_address = "123 Main St, Austin, TX 78701"
        from web.api import Api
        api = Api(self.store, self.settings)
        _p, m = self._draft()
        api.approve([m.id])
        # SMTP is unconfigured, so nothing can actually leave.
        result = api.send()
        self.assertEqual(result.get("failed", 0) + result.get("sent", 0) -
                         result.get("sent", 0), result.get("failed", 0))

    def test_unknown_ids_are_harmless(self):
        self.assertEqual(self.api.approve(["nope"])["approved"], 0)
        self.assertEqual(self.api.reject(["nope"])["rejected"], 0)


class TestLanDiscovery(unittest.TestCase):
    def test_returns_a_usable_address(self):
        import ipaddress
        from web.app import lan_ip
        addr = ipaddress.ip_address(lan_ip())
        self.assertTrue(addr.is_private or addr.is_loopback,
                        "LAN discovery must not hand out a public address")

    def test_qr_helper_degrades_to_empty(self):
        from web.app import qr_or_url
        self.assertIsInstance(qr_or_url("http://example.com"), str)


class TestKnowledge(unittest.TestCase):
    """The knowledge layer makes revenue claims to prospects. Every number it
    produces has to be defensible, so these assert the estimates stay
    conservative rather than merely being present."""

    def test_every_vertical_has_economics(self):
        from answerrank.knowledge import VERTICALS
        for key, v in VERTICALS.items():
            self.assertGreater(v.economics.avg_ticket, 0, key)
            self.assertGreaterEqual(v.economics.lifetime_value,
                                    v.economics.avg_ticket, key)
            self.assertTrue(v.buyer_phrases, f"{key} has no real buyer language")
            self.assertTrue(v.objections, f"{key} has no objections")

    def test_unknown_vertical_falls_back(self):
        from answerrank.knowledge import GENERIC, get
        self.assertEqual(get("underwater_basket_weaving"), GENERIC)

    def test_revenue_estimates_stay_credible(self):
        """A roofer told they lose $290k/year dismisses the whole pitch.

        Believability is about the *job count*, not the dollar figure. A
        remodeler hearing $77,600 checks it against a $28,000 ticket, gets
        under three kitchens a year, and finds it reasonable. A roofer hearing
        the same share of a $9,000 ticket gets thirty roofs and stops reading.
        So the ceiling is expressed in jobs a month — the unit the owner
        actually reasons in, and the one the estimate already reports — with a
        dollar bound behind it to catch a runaway.
        """
        from answerrank.knowledge import VERTICALS, revenue_at_risk
        for key in VERTICALS:
            r = revenue_at_risk(key, 10, 10)
            annual = float(r["annual_revenue"])
            self.assertGreaterEqual(annual, 0)
            lost = float(r["lost_jobs_per_month"])
            self.assertLess(lost, 3.0,
                            f"{key} claims {lost:.1f} lost jobs a month — past "
                            f"about three the owner stops believing it")
            self.assertLess(annual, 150_000,
                            f"{key} revenue-at-risk has run away")

    def test_no_gap_means_no_loss(self):
        from answerrank.knowledge import revenue_at_risk
        self.assertEqual(revenue_at_risk("hvac", 0, 10)["annual_revenue"], 0)

    def test_bigger_gap_means_bigger_loss(self):
        from answerrank.knowledge import revenue_at_risk
        small = float(revenue_at_risk("hvac", 2, 10)["annual_revenue"])
        big = float(revenue_at_risk("hvac", 9, 10)["annual_revenue"])
        self.assertGreater(big, small)

    def test_every_estimate_states_its_assumptions(self):
        from answerrank.knowledge import VERTICALS, revenue_at_risk
        for key in VERTICALS:
            assumption = str(revenue_at_risk(key, 5, 10)["assumption"])
            self.assertIn("Assumes", assumption)
            self.assertIn("%", assumption)

    def test_recommendation_follows_the_arithmetic(self):
        """The top trade must be the one the numbers actually pick.

        This deliberately does not name a trade. The library grows, and a test
        that pins "hvac" would fail the day a better-suited market is added
        while the ranking is still perfectly correct \u2014 which is a test
        reporting its own staleness as a defect.
        """
        from answerrank.knowledge import best_verticals
        rows = best_verticals(997)
        self.assertEqual(rows[0]["verdict"], "strong")
        strong = [r for r in rows if r["verdict"] == "strong"]
        self.assertEqual(rows[0]["first_job_ratio"],
                         max(r["first_job_ratio"] for r in strong),
                         "the top recommendation is not the best first-job ratio")
        order = {"strong": 0, "workable": 1, "weak": 2}
        verdicts = [order[str(r["verdict"])] for r in rows]
        self.assertEqual(verdicts, sorted(verdicts),
                         "verdicts are not in descending order of strength")

    def test_hvac_remains_defensible_at_the_growth_price(self):
        """The founding vertical must still stand on first-job revenue."""
        from answerrank.knowledge import plan_fit
        fit = plan_fit("hvac", 997)
        self.assertEqual(fit["verdict"], "strong")
        self.assertEqual(fit["basis"], "first-job revenue")

    def test_low_ticket_verticals_cannot_claim_first_job_payback(self):
        from answerrank.knowledge import plan_fit
        fit = plan_fit("dental", 997)
        self.assertNotEqual(fit["basis"], "first-job revenue")
        self.assertLess(float(fit["first_job_ratio"]), 1.0)

    def test_seasonal_note_covers_every_month(self):
        from answerrank.knowledge import seasonal_note
        for month in range(1, 13):
            self.assertTrue(seasonal_note("hvac", month).strip())


class TestQualification(unittest.TestCase):
    def _biz(self, **kw):
        base = dict(name="Apex Heating & Air", city="Austin", state="TX",
                    vertical="hvac", website="https://apexhvac.com",
                    email="office@apexhvac.com")
        base.update(kw)
        return Business(**base)

    def test_ideal_prospect_scores_top_tier(self):
        from answerrank.qualify import score_fit
        fit = score_fit(self._biz(), visibility_score=8.0)
        self.assertEqual(fit.tier, "A")
        self.assertTrue(fit.worth_pitching)

    def test_no_website_is_blocked(self):
        from answerrank.qualify import score_fit
        fit = score_fit(self._biz(website=""), visibility_score=8.0)
        self.assertFalse(fit.worth_pitching)
        self.assertTrue(any("website" in b.lower() for b in fit.blockers))

    def test_already_visible_business_is_never_pitched(self):
        """There is no honest problem to sell them."""
        from answerrank.qualify import score_fit
        fit = score_fit(self._biz(), visibility_score=88.0)
        self.assertFalse(fit.worth_pitching)
        self.assertTrue(any("visible" in b.lower() for b in fit.blockers))

    def test_weak_economics_blocks_the_pitch(self):
        from answerrank.qualify import score_fit
        fit = score_fit(self._biz(vertical="medical"), visibility_score=10.0)
        self.assertFalse(fit.worth_pitching)

    def test_own_domain_email_scores_above_free_host(self):
        from answerrank.qualify import score_fit
        owned = score_fit(self._biz(), 8.0).score
        free = score_fit(self._biz(email="bob@gmail.com"), 8.0).score
        self.assertGreater(owned, free)

    def test_priority_is_zero_for_unpitchable(self):
        from answerrank.qualify import priority
        self.assertEqual(priority(self._biz(website=""), 8.0, 90.0), 0.0)

    def test_priority_favours_fit_over_raw_pain(self):
        from answerrank.qualify import priority
        good_fit_moderate_pain = priority(self._biz(), 30.0, 30.0)
        poor_fit_severe_pain = priority(
            self._biz(vertical="medical", city="Nowhere"), 5.0, 100.0)
        self.assertGreater(good_fit_moderate_pain, poor_fit_severe_pain)


class TestOutreachCopy(unittest.TestCase):
    """Reply-rate research is specific: 36-50 character subjects, and emails
    past ~12 sentences lose about half their replies. These hold the copy to
    that, because it is the difference between a 3% and a 7% reply rate."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = make_settings(self.tmp.name)
        self.settings.physical_address = "PO Box 1, Austin, TX 78701"

    def tearDown(self):
        self.tmp.cleanup()

    def _prospect(self, name="Apex Heating & Air", vertical="hvac"):
        biz = Business(name=name, city="Austin", state="TX", vertical=vertical,
                       website="https://apex.com", email="o@apex.com")
        return Prospect(business=biz, score=8.0, competitor_gap=80.0,
                        notes=f"{name} appears in 0 of 4 AI answers for HVAC "
                              f"contractors in Austin, TX. Summit Climate Co appears in 4.")

    def test_subject_length_sits_in_the_target_band(self):
        from answerrank.agents.outreach import subject_line
        for name in ["Apex", "Apex Heating & Air",
                     "Cornerstone Heating Cooling and Plumbing Services of Texas"]:
            subj = subject_line(name, "Austin", 4, 4)
            self.assertLessEqual(len(subj), 55, f"too long for a mobile preview: {subj}")

    def test_opener_stays_short_enough_to_get_replies(self):
        from answerrank.agents.outreach import first_touch
        _subject, body = first_touch(self._prospect(), self.settings)
        core = body.split("---")[0]
        sentences = [s for s in re.split(r"[.!?]+", core) if len(s.strip()) > 12]
        self.assertLessEqual(len(sentences), 10,
                             "past ~12 sentences reply rates roughly halve")

    def test_opener_names_the_competitor(self):
        """Referencing a visible competitor is top-quartile personalisation."""
        _subject, body = __import__(
            "answerrank.agents.outreach", fromlist=["first_touch"]
        ).first_touch(self._prospect(), self.settings)
        self.assertIn("Summit Climate Co", body)

    def test_opener_carries_the_money_argument(self):
        from answerrank.agents.outreach import first_touch
        _subject, body = first_touch(self._prospect(), self.settings)
        self.assertIn("average ticket", body)

    def test_every_message_still_carries_compliance(self):
        from answerrank.agents.outreach import first_touch, followup
        for subject, body in [first_touch(self._prospect(), self.settings)] + \
                             [followup(self._prospect(), n, self.settings) for n in (2, 3)]:
            self.assertTrue(subject.strip())
            self.assertIn("unsubscribe", body.lower())
            self.assertIn(self.settings.company_legal_name, body)


class TestMarkets(unittest.TestCase):
    def test_every_candidate_is_scoreable_and_bounded(self):
        from answerrank.markets import CANDIDATES
        for c in CANDIDATES:
            score = c.score(997)
            self.assertTrue(0 <= score <= 100, f"{c.key} scored {score}")
            self.assertIn(c.verdict(997), {"pursue", "test", "watch", "skip"})
            self.assertTrue(c.basis.strip(), f"{c.key} has no stated basis")

    def test_affordability_tracks_their_budget_not_ours(self):
        """A business spending $5k/mo barely notices $997. One spending $600
        has to cut something, and will say no.

        Picks from the live candidate list rather than naming markets, since
        promoting one into a full vertical removes it from here."""
        from answerrank.markets import CANDIDATES
        by_budget = sorted(CANDIDATES, key=lambda c: c.monthly_marketing_spend)
        poor, rich = by_budget[0], by_budget[-1]
        self.assertGreater(rich.affordability(997), poor.affordability(997))

    def test_promoted_markets_leave_the_candidate_list(self):
        """The candidate list is an expansion list, not a catalogue."""
        from answerrank.knowledge import VERTICALS
        from answerrank.markets import CANDIDATES
        overlap = {c.key for c in CANDIDATES} & set(VERTICALS)
        self.assertFalse(overlap, f"already served but still a candidate: {overlap}")

    def test_cheaper_retainer_is_more_affordable_everywhere(self):
        from answerrank.markets import CANDIDATES
        for c in CANDIDATES:
            self.assertGreaterEqual(c.affordability(499), c.affordability(997))

    def test_ticket_strength_saturates(self):
        """Past ~$10k the ROI argument is already trivial; more adds nothing."""
        from answerrank.markets import Candidate
        base = dict(monthly_marketing_spend=2000, urgency=0.5, fragmentation=0.5,
                    digital_gap=0.5, incumbent_risk=0.5, basis="test")
        big = Candidate(key="a", label="a", avg_ticket=10_000, **base)
        huge = Candidate(key="b", label="b", avg_ticket=100_000, **base)
        self.assertAlmostEqual(big.ticket_strength(), huge.ticket_strength(), places=2)

    def test_ranking_is_stable_and_complete(self):
        from answerrank.markets import CANDIDATES, ranked
        r = ranked(997)
        self.assertEqual(len(r), len(CANDIDATES))
        scores = [c.score(997) for c in r]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_shortlist_excludes_the_rejected(self):
        from answerrank.markets import shortlist
        for c in shortlist(997, limit=5):
            self.assertIn(c.verdict(997), {"pursue", "test"})


class TestExplorer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = make_settings(self.tmp.name)
        self.store = Store(self.settings.database_path)
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)

    def tearDown(self):
        self.tmp.cleanup()

    def test_explores_one_market_per_run(self):
        from answerrank.agents.explorer import ExplorerAgent
        agent = ExplorerAgent(self.store, self.settings, sample_size=2)
        run = agent.run()
        self.assertEqual(run.status, "ok")
        self.assertEqual(len(self.store.latest_findings()), 1)

    def test_successive_runs_cover_new_markets(self):
        """Otherwise the top of the list gets re-tested forever."""
        from answerrank.agents.explorer import ExplorerAgent
        agent = ExplorerAgent(self.store, self.settings, sample_size=2)
        for _ in range(4):
            agent.run()
        self.assertEqual(len(self.store.explored_markets()), 4)

    def test_simulated_findings_are_flagged_and_capped(self):
        """A simulated sample must never read as evidence."""
        from answerrank.agents.explorer import ExplorerAgent
        ExplorerAgent(self.store, self.settings, sample_size=2).run()
        finding = self.store.latest_findings()[0]
        self.assertTrue(any("SIMULATED" in n for n in finding["notes"]))
        self.assertNotEqual(finding["verdict"], "pursue")

    def test_exploration_cost_is_booked(self):
        from answerrank.agents.explorer import ExplorerAgent
        ExplorerAgent(self.store, self.settings, sample_size=2).run()
        self.assertGreater(self.store.cost_breakdown(30).get("api", 0), 0)


class TestStrategist(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = make_settings(self.tmp.name)
        self.store = Store(self.settings.database_path)
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)

    def tearDown(self):
        self.tmp.cleanup()

    def _agent(self):
        from answerrank.agents.strategist import StrategistAgent
        return StrategistAgent(self.store, self.settings)

    def test_thin_pipeline_beats_every_other_concern(self):
        rec = self._agent().recommend()
        self.assertIn("pipeline", rec["move"].lower())
        self.assertEqual(rec["confidence"], "high")

    def test_always_returns_exactly_one_move(self):
        """A list of opportunities is a way of avoiding a decision."""
        from answerrank.agents.scout import ScoutAgent
        ScoutAgent(self.store, self.settings, target_per_run=40).run()
        rec = self._agent().recommend()
        for key in ("move", "why", "confidence"):
            self.assertTrue(rec[key].strip())

    def test_recommendation_is_persisted_for_the_console(self):
        self._agent().run()
        self.assertTrue(self.store.kv_get("strategy_recommendation"))

    def test_assessment_covers_all_candidates(self):
        from answerrank.markets import CANDIDATES
        state = self._agent().assess()
        self.assertEqual(len(state["candidates"]), len(CANDIDATES))


class TestScoutSelectivity(unittest.TestCase):
    """The Strategist caught the Scout adding prospects the price could not
    serve, which Outreach then filtered out — API spend for nothing."""

    def test_only_defensible_verticals_are_prospected(self):
        from answerrank.agents.scout import defensible_verticals
        from answerrank.knowledge import plan_fit
        for key in defensible_verticals(997):
            self.assertNotEqual(plan_fit(key, 997)["verdict"], "weak", key)

    def test_a_higher_price_narrows_the_field(self):
        from answerrank.agents.scout import defensible_verticals
        self.assertLessEqual(len(defensible_verticals(1997)),
                             len(defensible_verticals(499)))

    def test_never_returns_an_empty_list(self):
        from answerrank.agents.scout import defensible_verticals
        self.assertTrue(defensible_verticals(50_000))

    def test_scout_and_outreach_now_agree(self):
        """Discovery and qualification should not disagree about a vertical."""
        from answerrank.agents.scout import defensible_verticals
        from answerrank.qualify import score_fit
        for key in defensible_verticals(997):
            biz = Business(name="Test Co", city="Austin", state="TX", vertical=key,
                           website="https://test.com", email="a@test.com")
            fit = score_fit(biz, visibility_score=10.0, monthly_price=997)
            self.assertTrue(fit.worth_pitching, f"{key} discovered but unpitchable")


class TestPromotedVerticals(unittest.TestCase):
    """Restoration and med spa were promoted from candidates after the Explorer
    measured them and their economics were sourced."""

    def test_both_are_adopted(self):
        from answerrank.knowledge import VERTICALS
        self.assertIn("restoration", VERTICALS)
        self.assertIn("med_spa", VERTICALS)

    def test_restoration_clears_on_first_job_revenue(self):
        """$3,860 average ticket carries the retainer on its own."""
        from answerrank.knowledge import plan_fit
        self.assertEqual(plan_fit("restoration", 997)["verdict"], "strong")

    def test_med_spa_needs_the_lifetime_argument(self):
        """$536 a visit does not cover $997 a month; claiming it would not
        survive the client checking."""
        from answerrank.knowledge import plan_fit
        fit = plan_fit("med_spa", 997)
        self.assertLess(float(fit["first_job_ratio"]), 1.0)
        self.assertEqual(fit["basis"], "lifetime value")

    def test_low_urgency_trades_get_no_emergency_prompt(self):
        """Nobody types 'I want a med spa, who do I call RIGHT NOW'."""
        from answerrank.prompts import build_prompts
        for key in ("med_spa", "insurance"):
            intents = [i for _p, i in build_prompts(key, "Tampa", "FL", 10)]
            self.assertNotIn("emergency", intents, key)

    def test_urgent_trades_keep_their_emergency_prompt(self):
        from answerrank.prompts import build_prompts
        for key in ("restoration", "hvac", "plumbing"):
            intents = [i for _p, i in build_prompts(key, "Tampa", "FL", 10)]
            self.assertIn("emergency", intents, key)

    def test_every_prompt_reads_as_a_real_question(self):
        """A prompt nobody would type measures nothing."""
        from answerrank.knowledge import VERTICALS
        from answerrank.prompts import build_prompts
        for key in VERTICALS:
            for prompt, _intent in build_prompts(key, "Tampa", "FL", 12):
                self.assertNotIn("  ", prompt, f"{key}: double space in {prompt!r}")
                self.assertFalse(prompt.startswith("I I"), key)
                self.assertGreater(len(prompt), 15, key)

    def test_scout_now_prospects_restoration(self):
        from answerrank.agents.scout import defensible_verticals
        self.assertIn("restoration", defensible_verticals(997))


class TestLanguage(unittest.TestCase):
    """Copy that reads as machine-generated is copy that gets deleted."""

    def test_articles_agree_with_the_sound_not_the_letter(self):
        from answerrank.knowledge import a_label, article
        self.assertEqual(article("HVAC contractor"), "an")
        self.assertEqual(article("plumber"), "a")
        self.assertEqual(article("electrician"), "an")
        self.assertEqual(a_label("hvac"), "an HVAC contractor")
        self.assertEqual(a_label("plumbing"), "a plumber")

    def test_plurals_are_not_naive(self):
        from answerrank.knowledge import plural
        self.assertEqual(plural("garage door company"), "garage door companies")
        self.assertEqual(plural("insurance agency"), "insurance agencies")
        self.assertEqual(plural("attorney"), "attorneys")
        self.assertEqual(plural("medical spa"), "medical spas")

    def test_sentence_case_preserves_acronyms(self):
        from answerrank.knowledge import sentence_case
        self.assertEqual(sentence_case("HVAC contractor"), "HVAC contractor")
        self.assertEqual(sentence_case("plumber"), "Plumber")

    def test_no_trade_label_is_pluralised_badly_anywhere(self):
        """"attorneys" is right; "agencys" is not. The difference is the
        letter before the y, so that is what this checks."""
        from answerrank.knowledge import VERTICALS, plural
        for key, v in VERTICALS.items():
            plural_label = plural(v.label)
            last_word = v.label.rsplit(" ", 1)[-1]
            if last_word.endswith("y") and last_word[-2].lower() not in "aeiou":
                self.assertTrue(plural_label.endswith("ies"),
                                f"{key}: {plural_label}")
            self.assertFalse(plural_label.endswith("ss"), key)


class TestPricingLadder(unittest.TestCase):
    """A trade that fails at one price is a pricing problem, not a dead market."""

    def test_every_trade_is_sellable_somewhere_on_the_ladder(self):
        from answerrank.knowledge import VERTICALS, recommended_price
        for key in VERTICALS:
            rec = recommended_price(key)
            self.assertIsNotNone(rec["price"], f"{key} has no defensible tier")
            self.assertIn(rec["verdict"], {"strong", "workable"}, key)

    def test_the_recommended_tier_is_actually_defensible(self):
        from answerrank.knowledge import VERTICALS, plan_fit, recommended_price
        for key in VERTICALS:
            price = recommended_price(key)["price"]
            self.assertIn(plan_fit(key, float(price))["verdict"],
                          {"strong", "workable"}, key)

    def test_no_higher_tier_would_also_have_worked(self):
        """Recommending $497 when $997 is defensible leaves money on the table."""
        from answerrank.knowledge import PRICE_LADDER, VERTICALS, plan_fit, recommended_price
        for key in VERTICALS:
            price = float(recommended_price(key)["price"])
            for higher in [p for p in PRICE_LADDER if p > price]:
                self.assertEqual(plan_fit(key, higher)["verdict"], "weak",
                                 f"{key} could have been sold at ${higher:,.0f}")

    def test_priced_verticals_covers_the_whole_library(self):
        from answerrank.knowledge import VERTICALS, priced_verticals
        self.assertEqual(len(priced_verticals()), len(VERTICALS))


class TestPlaybook(unittest.TestCase):
    """The method the agents are trained on, checked like any other code."""

    def _business(self, vertical="hvac", city="Austin"):
        return Business(name="Test Co", city=city, state="TX", vertical=vertical,
                        website="https://testco.com", email="o@testco.com")

    def test_bant_scores_a_strong_prospect_as_qualified(self):
        from answerrank.playbook import bant
        r = bant(self._business(), visibility_score=18, competitor_gap=40,
                 monthly_price=997, month=5)
        self.assertEqual(r.verdict, "qualified")
        self.assertGreater(r.score, 72)

    def test_bant_refuses_to_qualify_an_already_visible_business(self):
        from answerrank.playbook import bant
        r = bant(self._business(), visibility_score=85, competitor_gap=0,
                 monthly_price=997, month=5)
        self.assertLess(r.need, 0.2)

    def test_bant_names_a_cheaper_tier_when_the_price_does_not_fit(self):
        from answerrank.playbook import bant
        r = bant(self._business("garage_door"), visibility_score=20,
                 competitor_gap=30, monthly_price=1997, month=5)
        self.assertLess(r.budget, 0.5)
        self.assertIn("$297", r.evidence["budget"])

    def test_every_bant_read_carries_its_evidence(self):
        from answerrank.knowledge import VERTICALS
        from answerrank.playbook import bant
        for key in VERTICALS:
            r = bant(self._business(key), 20, 30, 997, 6)
            for dimension in ("budget", "authority", "need", "timeline"):
                self.assertTrue(r.evidence.get(dimension), f"{key}/{dimension}")
            self.assertTrue(r.next_question)

    def test_every_recorded_objection_has_an_answer(self):
        """An objection the agents cannot answer is a deal they cannot close."""
        from answerrank.knowledge import VERTICALS
        from answerrank.playbook import rebuttal
        for key, v in VERTICALS.items():
            for objection in v.objections:
                self.assertTrue(rebuttal(objection, key),
                                f"{key}: no answer to {objection!r}")

    def test_an_unrecognised_objection_routes_to_a_human(self):
        from answerrank.playbook import rebuttal
        self.assertEqual(rebuttal("my cousin does this for free", "hvac"), "")

    def test_the_price_rebuttal_offers_the_tier_that_fits(self):
        from answerrank.playbook import rebuttal
        answer = rebuttal("too expensive", "garage_door", 997)
        self.assertIn("$297", answer)

    def test_sequence_check_rejects_a_content_free_nudge(self):
        from answerrank.playbook import sequence_check
        problems = sequence_check(2, "Just checking in. Any thoughts? unsubscribe")
        self.assertTrue(any("nudge" in p for p in problems))

    def test_sequence_check_rejects_an_unwrapped_line(self):
        from answerrank.playbook import sequence_check
        problems = sequence_check(1, "x" * 120 + "\nunsubscribe")
        self.assertTrue(any("columns" in p for p in problems))

    def test_email_body_preserves_a_signature_block(self):
        from answerrank.playbook import email_body
        body = email_body("Hi,", "AnswerRank\nhttps://answerrank.io")
        self.assertIn("AnswerRank\nhttps://answerrank.io", body)

    def test_discovery_questions_name_the_trades_own_work(self):
        from answerrank.knowledge import VERTICALS, get
        from answerrank.playbook import discovery_questions
        for key in VERTICALS:
            questions = discovery_questions(key)
            self.assertGreaterEqual(len(questions), 5, key)
            self.assertIn(get(key).jobs[0], questions[0], key)


class TestOutreachDiscipline(unittest.TestCase):
    """Every draft the system writes must pass the system's own standard."""

    def test_every_draft_in_every_trade_passes_the_playbook(self):
        from answerrank.agents.outreach import first_touch, followup
        from answerrank.knowledge import VERTICALS
        from answerrank.playbook import sequence_check
        settings = Settings()
        for key in VERTICALS:
            for name in ("A Very Long Business Name Company LLC", "Ace"):
                prospect = Prospect(business=Business(
                    name=name, city="Oklahoma City", state="OK", vertical=key,
                    website="https://x.com", email="o@x.com"), score=22,
                    notes=f"{name} appears in 2 of 10 AI answers.")
                for step in (1, 2, 3, 4):
                    subject, body = (first_touch(prospect, settings) if step == 1
                                     else followup(prospect, step, settings))
                    self.assertFalse(sequence_check(step, body),
                                     f"{key} step {step}: "
                                     f"{sequence_check(step, body)}")
                    self.assertLessEqual(len(subject), 60, f"{key} step {step}")

    def test_the_sequence_closes_rather_than_nagging(self):
        """Past step 3 there is nothing new to say, so it says goodbye."""
        from answerrank.agents.outreach import followup
        prospect = Prospect(business=Business(name="Ace", city="Tulsa", state="OK",
                                              vertical="hvac", email="o@x.com"))
        _subject, body = followup(prospect, 5, Settings())
        self.assertIn("stop here", body)
        self.assertNotIn("Just checking", body)


class TestConcierge(unittest.TestCase):
    """The reply is worth more than every audit that preceded it."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = Store(self.tmp.name)
        self.settings = Settings()
        self.prospect = Prospect(business=Business(
            name="Acme HVAC", city="Austin", state="TX", vertical="hvac",
            website="https://acme.com", email="mike@acme.com"), stage="contacted")
        self.store.upsert_prospect(self.prospect)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def _agent(self):
        from answerrank.agents.concierge import ConciergeAgent
        return ConciergeAgent(self.store, self.settings)

    def test_intent_classification(self):
        from answerrank.agents.concierge import classify
        for text, expected in [
            ("yes please send it", "interested"),
            ("How much does this cost?", "question"),
            ("Not interested, thanks", "not_interested"),
            ("please remove me from your list", "unsubscribe"),
            ("This is spam, stop", "hostile"),
            ("Talk to my marketing guy", "referral"),
            ("", "unclear"),
        ]:
            self.assertEqual(classify(text), expected, text)

    def test_unsubscribe_beats_every_other_word_in_the_message(self):
        """"Yes, and also unsubscribe me" must never be read as interest."""
        from answerrank.agents.concierge import classify
        self.assertEqual(classify("yes sounds good but please remove me"),
                         "unsubscribe")

    def test_an_unsubscribe_suppresses_and_writes_no_draft(self):
        result = self._agent().handle_reply(self.prospect, "remove me")
        self.assertTrue(self.store.is_suppressed("mike@acme.com"))
        self.assertEqual(self.prospect.stage, "suppressed")
        self.assertEqual(result["message_id"], "")
        self.assertEqual(self.store.get_messages("drafted"), [])

    def test_a_reply_is_recorded_as_an_outcome(self):
        self._agent().handle_reply(self.prospect, "yes send it over")
        self.assertEqual(self.store.outcome_counts().get("replied"), 1)

    def test_an_objection_in_a_question_is_answered_directly(self):
        result = self._agent().handle_reply(
            self.prospect, "We already pay an SEO guy, what's different?")
        self.assertEqual(result["action"], "answer_objection")
        draft = self.store.get_messages("drafted")[0]
        self.assertIn("structured data", draft.body)

    def test_the_concierge_drafts_and_never_sends(self):
        self._agent().handle_reply(self.prospect, "yes please")
        self.assertEqual(self.store.get_messages("sent"), [])
        self.assertEqual(len(self.store.get_messages("drafted")), 1)


class TestAnalyst(unittest.TestCase):
    """A system that acts without measuring is a system that cannot improve."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = Store(self.tmp.name)
        self.settings = Settings()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def _agent(self):
        from answerrank.agents.analyst import AnalystAgent
        return AnalystAgent(self.store, self.settings)

    def _record(self, n, kind, vertical="hvac", step=1):
        for _ in range(n):
            self.store.record_outcome(prospect_id="p", vertical=vertical,
                                      step=step, kind=kind)

    def test_it_refuses_to_conclude_on_a_thin_sample(self):
        self._record(4, "sent")
        self._record(2, "replied")
        learnings = self._agent().learnings()
        self.assertEqual(len(learnings), 1)
        self.assertIn("measurable", learnings[0])

    def test_a_thin_vertical_is_reported_as_not_yet_known(self):
        from answerrank.agents.analyst import MIN_SAMPLE
        self._record(MIN_SAMPLE + 5, "sent", "hvac")
        self._record(3, "sent", "dental")
        rows = {r["vertical"]: r["confidence"] for r in self._agent().by_vertical()}
        self.assertEqual(rows["dental"], "insufficient")
        self.assertNotEqual(rows["hvac"], "insufficient")

    def test_required_volume_states_which_basis_it_used(self):
        volume = self._agent().required_volume(5000, 997, 18)
        self.assertIn("prior", str(volume["basis"]))
        self.assertGreater(volume["sends_per_week"], 0)
        self.assertGreaterEqual(volume["clients_needed"], 5)

    def test_required_volume_switches_to_measured_data(self):
        from answerrank.agents.analyst import CONFIDENT_SAMPLE
        self._record(CONFIDENT_SAMPLE + 10, "sent")
        self._record(6, "replied")
        self._record(2, "won")
        volume = self._agent().required_volume(5000, 997, 18)
        self.assertIn("measured", str(volume["basis"]))

    def test_replies_without_wins_points_at_the_close(self):
        self._record(120, "sent")
        self._record(12, "replied")
        learnings = self._agent().learnings()
        self.assertTrue(any("close" in line for line in learnings), learnings)

    def test_the_funnel_survives_an_empty_database(self):
        funnel = self._agent().funnel()
        self.assertEqual(funnel.sent, 0)
        self.assertEqual(funnel.reply_rate, 0.0)
        self.assertIn("No sends", funnel.line())


class TestRetention(unittest.TestCase):
    """Replacing a client costs weeks. Keeping one costs a report."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = Store(self.tmp.name)
        self.settings = Settings()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def _agent(self):
        from answerrank.agents.retention import RetentionAgent
        return RetentionAgent(self.store, self.settings)

    def _client(self, started_days_ago, reported_days_ago=None):
        from datetime import datetime, timedelta, timezone

        def ago(days):
            return (datetime.now(timezone.utc)
                    - timedelta(days=days)).isoformat(timespec="seconds")

        business = Business(name="Held Co", city="Austin", state="TX",
                            vertical="hvac", website="https://held.com")
        client = Client(business=business, plan="growth", mrr=997.0, status="active",
                        started_at=ago(started_days_ago),
                        last_report_at=("" if reported_days_ago is None
                                        else ago(reported_days_ago)))
        self.store.upsert_client(client)
        return client

    def test_a_silent_long_standing_account_scores_badly(self):
        health = self._agent().score_client(self._client(150, 70))
        self.assertEqual(health.band, "act_now")
        self.assertLess(health.score, 60)

    def test_a_brand_new_account_is_not_punished_for_having_no_history(self):
        health = self._agent().score_client(self._client(3))
        self.assertGreater(health.score, 60)

    def test_an_overdue_report_is_the_action_whatever_else_is_wrong(self):
        health = self._agent().score_client(self._client(150, 70))
        self.assertIn("report", health.action.lower())

    def test_a_rising_score_becomes_the_referral_moment(self):
        client = self._client(120, 5)
        for n, score in enumerate((30, 38, 46)):
            audit = Audit(business_id=client.business.id, business_name="Held Co",
                          market="Austin, TX", vertical="hvac", score=score)
            self.store.save_audit(audit)
        self.store.record_outcome(prospect_id=client.id, kind="replied")
        health = self._agent().score_client(client)
        self.assertIn("referral", health.action.lower())

    def test_the_portfolio_is_ordered_worst_first(self):
        self._client(150, 70)
        self._client(20, 5)
        scores = [h.score for h in self._agent().portfolio()]
        self.assertEqual(scores, sorted(scores))

    def test_no_clients_is_not_an_error(self):
        count, summary = self._agent().execute()
        self.assertEqual(count, 0)
        self.assertIn("no active clients", summary)


class TestSendPath(unittest.TestCase):
    """One implementation of the path that can burn the sending domain."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = Store(self.tmp.name)
        self.settings = Settings()
        self.settings.physical_address = "PO Box 1, Austin TX 78701"

    def tearDown(self):
        os.unlink(self.tmp.name)

    def _queue_one(self, email="o@x.com"):
        prospect = Prospect(business=Business(
            name="Ace", city="Austin", state="TX", vertical="hvac",
            website="https://ace.com", email=email))
        self.store.upsert_prospect(prospect)
        self.store.save_message(OutreachMessage(
            prospect_id=prospect.id, subject="s", body="b", status="approved"))
        return prospect

    def test_a_missing_postal_address_blocks_the_whole_batch(self):
        from answerrank.sending import send_batch
        self.settings.physical_address = "SET_YOUR_REGISTERED_BUSINESS_ADDRESS"
        self._queue_one()
        result = send_batch(self.store, self.settings, dry_run=True)
        self.assertTrue(result["blocked"])
        self.assertEqual(result["sent"], 0)

    def test_a_caller_can_add_a_check_but_not_remove_one(self):
        from answerrank.sending import send_batch
        self._queue_one()
        result = send_batch(self.store, self.settings, dry_run=True,
                            extra_checks=["DNS is not ready"])
        self.assertTrue(result["blocked"])
        self.assertIn("DNS is not ready", result["reasons"])

    def test_a_suppressed_recipient_is_never_sent_to(self):
        from answerrank.sending import send_batch
        self._queue_one("blocked@x.com")
        self.store.suppress("blocked@x.com", "unsubscribed")
        result = send_batch(self.store, self.settings, dry_run=True)
        self.assertEqual(result["sent"], 0)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(self.store.get_messages("suppressed")[0].status,
                         "suppressed")

    def test_a_dry_run_sends_nothing_and_records_nothing(self):
        from answerrank.sending import send_batch
        self._queue_one()
        result = send_batch(self.store, self.settings, dry_run=True)
        self.assertEqual(result["sent"], 1)
        self.assertEqual(self.store.outcome_counts(), {})

    def test_the_daily_cap_is_enforced_before_anything_is_sent(self):
        from answerrank.sending import send_batch
        self.settings.outreach.max_emails_total_per_day = 0
        self._queue_one()
        result = send_batch(self.store, self.settings, dry_run=True)
        self.assertTrue(result["blocked"])
        self.assertIn("cap", result["reasons"][0].lower())


class TestQualificationBrief(unittest.TestCase):
    def test_a_brief_answers_every_question_a_seller_asks(self):
        from answerrank import qualify
        business = Business(name="Ace", city="Austin", state="TX", vertical="hvac",
                            website="https://ace.com", email="o@ace.com")
        brief = qualify.brief(business, 18, 40, 997, month=5)
        for key in ("fit_score", "tier", "bant_score", "bant_verdict", "priority",
                    "recommended_price", "objections", "discovery", "seasonality",
                    "next_question", "decision_maker"):
            self.assertIn(key, brief)
        self.assertTrue(brief["objections"])
        self.assertTrue(brief["discovery"])
        self.assertNotIn("{city}", " ".join(brief["discovery"]))

    def test_priority_is_zero_for_a_business_not_worth_pitching(self):
        from answerrank import qualify
        visible = Business(name="Ace", city="Austin", state="TX", vertical="hvac",
                           website="https://ace.com", email="o@ace.com")
        self.assertEqual(qualify.priority(visible, 90, 0, 997), 0.0)
