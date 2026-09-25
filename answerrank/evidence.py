"""The professional research the agents work from, with its sources.

Every rule in this system used to be a judgement written into a docstring.
Some were right; one was badly wrong (the month-one lever the method leaned
on hardest, schema markup, ranks 44th of the factors practitioners weigh for
AI visibility). So the rules that matter now cite the research they rest on,
here, and a test fails if a lever or a rule points at research that is not in
this file.

Research goes stale. AI search in particular changes quarterly, so every
entry carries the date it was checked and the date to check it again, and
the Researcher agent says so when one is overdue. An entry is removed or
updated when the source is; it is never quietly left to rot.

Each entry says what the source found, in its own numbers, and separately
what we do because of it. The two are kept apart so that a finding can be
checked against its source without having to agree with our reading of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Evidence:
    key: str
    source: str
    published: str          #: YYYY-MM
    url: str
    finding: str            #: what the source says, in its numbers
    so_we: str              #: what the agents do because of it
    used_by: tuple[str, ...]
    checked: str = "2026-09"   #: when we last read it (YYYY-MM)
    review_months: int = 6

    def due(self, today: date | None = None) -> bool:
        """Whether this is older than its shelf life."""
        today = today or date.today()
        y, m = (int(x) for x in self.checked.split("-"))
        months = (today.year - y) * 12 + today.month - m
        return months >= self.review_months

    def cite(self) -> str:
        return f"{self.source} ({self.published})"


LIBRARY: dict[str, Evidence] = {e.key: e for e in (
    # ---------------------------------------------------------- measurement
    Evidence(
        "ai_answers_vary",
        "SparkToro & Gumshoe, AI brand-recommendation consistency study",
        "2026-01",
        "https://sparktoro.com/blog/new-research-ais-are-highly-inconsistent-when-recommending-brands-or-products-marketers-should-take-care-when-tracking-ai-visibility/",
        "600 volunteers ran 12 prompts through ChatGPT, Claude and Google's AI "
        "2,961 times. Fewer than 1 in 100 runs returned the same list of brands, "
        "fewer than 1 in 1,000 in the same order. 'Visibility % across many "
        "prompts run multiple times' is a reasonable metric; 'ranking position "
        "in AI' is not.",
        "Audits report the share of answers a business is named in, over "
        "repeated runs, with a margin of error. Client audits ask each question "
        "three times. A before-and-after only counts as movement when it beats "
        "the noise. Nothing claims a 'rank' in an AI answer.",
        ("auditor", "reporter", "casestudy", "calls"), review_months=6),
    Evidence(
        "chatgpt_search_sources",
        "BrightLocal, Uncovering ChatGPT Search Sources",
        "2024-12",
        "https://www.brightlocal.com/research/uncovering-chatgpt-search-sources/",
        "800 local searches in ChatGPT: sources were business websites 58%, "
        "business mentions 27%, directories 15%. The leading directories were "
        "curated 'best of' sites: Three Best Rated (24% of directory sources) "
        "and Expertise (18%); Yelp, Facebook and Google Maps did not appear. "
        "Recommends optimising for Bing, which powers ChatGPT Search.",
        "The ChatGPT check searches the web the way ChatGPT does, rather than "
        "asking a model from memory. Bing Places is one of the listings every "
        "client gets. The citation agent checks the curated lists by name.",
        ("auditor", "fixer", "citations"), review_months=6),
    Evidence(
        "home_services_sources",
        "Cheers, AI search engine source differences (home services baseline)",
        "2026-09",
        "https://www.cheers.tech/geo-academy/ai-search-engine-source-differences",
        "Home services, 28 days to 2 Sept 2026: ChatGPT cited contractor "
        "websites 48.8% of the time and directories or review platforms 44.7%. "
        "Gemini cited contractor sites 80.7%, Perplexity 72.3%, Google AI "
        "Overviews/AI Mode 70.3%. No engine guarantees a given page is cited.",
        "For trades, a contractor's own site carries most engines, and "
        "directories carry nearly half of ChatGPT. Both are worked on: service "
        "pages for the first, listings and curated lists for the second.",
        ("fixer", "citations"), review_months=3),
    Evidence(
        "brand_managed_citations",
        "Yext, analysis of 6.8 million AI citations (as reported by Cheers)",
        "2025-10",
        "https://www.cheers.tech/geo-academy/ai-search-engine-source-differences",
        "86% of AI citations came from sources a business manages: its own "
        "website (44%) and its listings (42%).",
        "Most of what the engines quote is within a client's control, which is "
        "what the retainer sells: the website and the listings, kept right.",
        ("fixer", "citations"), review_months=6),

    # ---------------------------------------------------------- what moves it
    Evidence(
        "ai_visibility_factors",
        "Whitespark, 2026 Local Search Ranking Factors (AI search visibility)",
        "2026",
        "https://whitespark.ca/local-search-ranking-factors/",
        "Top AI visibility factors: 1) presence on expert-curated 'best of' "
        "lists, 2) a dedicated page for each service, 3) prominence on key "
        "industry-relevant domains, 4) quality and authority of unstructured "
        "citations, 5) authority of third-party sites where reviews are "
        "present. 'Website content marked up in schema' ranks #44.",
        "The delivery method is ordered by this: service pages in month one, "
        "curated lists in month two, industry domains and citations in month "
        "three, reviews on third-party sites in month four. Schema stays in "
        "month one because it is quick and cheap, and says honestly that it "
        "is not what moves AI answers.",
        ("fixer", "method", "citations"), review_months=12),
    Evidence(
        "local_pack_factors",
        "Whitespark, 2026 Local Search Ranking Factors (local pack)",
        "2026",
        "https://whitespark.ca/local-search-ranking-factors/",
        "Top local pack factors: primary Google Business Profile category, "
        "proximity to the searcher, keywords in the GBP business title, a "
        "physical address in the city searched, open at the time of search. "
        "Review recency ranks #11. GBP signals weigh 32% overall, reviews 20%.",
        "Getting the primary category exactly right is the first GBP task. "
        "Hours are kept accurate because being open when someone searches "
        "counts.",
        ("fixer", "method"), review_months=12),
    Evidence(
        "consumer_reviews_2026",
        "BrightLocal, Local Consumer Review Survey 2026",
        "2026",
        "https://www.brightlocal.com/research/local-consumer-review-survey/",
        "45% of consumers used AI tools such as ChatGPT to find local "
        "businesses in the past year (6% the year before). 74% prioritise "
        "reviews from the last three months; 32% want one from the last two "
        "weeks. 68% require at least 4 stars; 31% only use businesses rated "
        "4.5 or higher.",
        "Review work aims at a new review at least every two weeks, not a "
        "count. Retention watches for a client going quiet on reviews. The "
        "45% figure is what the sales script leans on.",
        ("fixer", "retention", "calls", "outreach"), review_months=12),

    # ---------------------------------------------------------- selling
    Evidence(
        "cold_email_2026",
        "Instantly, Cold Email Benchmark Report 2026",
        "2026",
        "https://instantly.ai/cold-email-benchmark-report-2026",
        "Average reply rate 3.43%; top quartile 5.5%+; elite 10.7%+. 58% of "
        "replies come from the first email. 4-7 touches is the sweet spot. "
        "Elite first emails average under 80 words. Wednesday has the highest "
        "reply rates. Keep bounces under 2%.",
        "The first email carries most of the weight and is kept under 80 "
        "words; the checker rejects a first touch over 100. The sequence is "
        "four touches. Bounces over 2% pause cold sending. The Analyst "
        "compares our reply rate against 3.4% and 5.5%.",
        ("outreach", "analyst", "sending"), review_months=12),
    Evidence(
        "cold_call_openers",
        "Gong Labs, cold call opening lines (300 million calls)",
        "2025",
        "https://www.gong.io/blog/cold-call-opening-lines",
        "Stating the reason for the call raises success 2.1x. 'Did I catch you "
        "at a bad time?' makes a meeting 40% less likely.",
        "The call script opens with who is calling and the reason, in one "
        "breath, and never asks if it's a bad time.",
        ("calls",), review_months=12),
    Evidence(
        "cold_call_stats",
        "Gong Labs, cold calling statistics",
        "2025",
        "https://www.gong.io/blog/cold-call-stats",
        "Successful cold calls average 5m50s, about twice as long as "
        "unsuccessful ones; reps talk about 55% of the time, in longer "
        "stretches (53s vs 25s). Wednesday and Thursday are the best days.",
        "The script's middle is a 40-second explanation, not a string of "
        "questions. The call list marks Wednesday and Thursday.",
        ("calls",), review_months=12),

    # ---------------------------------------------------------- rules
    Evidence(
        "gmail_sender_rules",
        "Google, Email sender guidelines",
        "2024-02",
        "https://support.google.com/a/answer/14229414?hl=en",
        "Senders of 5,000+ messages a day to Gmail need SPF, DKIM and DMARC "
        "(p=none at least, aligned), and one-click unsubscribe. Keep the "
        "user-reported spam rate below 0.1% and never let it reach 0.3%.",
        "The doctor blocks sending until SPF, DKIM and DMARC pass, whatever "
        "the volume. Every email has a one-click unsubscribe. The complaint "
        "ceiling is 0.1%.",
        ("sending", "doctor"), review_months=12),
    Evidence(
        "outlook_sender_rules",
        "Microsoft, Outlook requirements for high-volume senders",
        "2025-04",
        "https://techcommunity.microsoft.com/blog/microsoftdefenderforoffice365blog/strengthening-email-ecosystem-outlook%E2%80%99s-new-requirements-for-high%E2%80%90volume-senders/4399730",
        "From 5 May 2025, domains sending 5,000+ emails a day to Outlook.com, "
        "Hotmail and Live must pass SPF and DKIM and publish DMARC (p=none at "
        "least, aligned), or be filtered or rejected.",
        "Same bar as Gmail, applied from the first email.",
        ("sending", "doctor"), review_months=12),
    Evidence(
        "ftc_tsr_b2b",
        "FTC Telemarketing Sales Rule (2024 amendments); MarketingProfs on the B2B exemption",
        "2024-03",
        "https://www.ftc.gov/news-events/news/press-releases/2024/03/ftc-implements-new-protections-businesses-against-telemarketing-fraud-affirms-protections-against-ai",
        "Most business-to-business calls are exempt from the Do Not Call "
        "registry and much of the Rule. Since 2024, misrepresentations are "
        "prohibited on business calls too. The exemption does not cover "
        "turning a business's 'no need' into a pitch to the person who "
        "answered (MarketingProfs).",
        "Calls are dialled by hand to published business numbers; the script "
        "quotes only real audit results and never claims to be from an AI "
        "company; 'not interested' ends calls and email at once.",
        ("calls",), review_months=12),

    # ---------------------------------------------------------- the tools
    Evidence(
        "openai_web_search",
        "OpenAI, Web search tool and pricing",
        "2026",
        "https://developers.openai.com/api/docs/guides/tools-web-search",
        "The Responses API's web_search tool searches the live web, accepts an "
        "approximate user_location (city, region, country) and returns "
        "url_citation annotations. $10 per 1,000 calls for reasoning models "
        "(search content billed as tokens); $25 per 1,000 for others.",
        "The ChatGPT check uses web search from the business's own city, so "
        "it sees what a local customer sees, with the sources it used.",
        ("auditor",), review_months=6),
    Evidence(
        "anthropic_web_search",
        "Anthropic, Web search tool",
        "2026",
        "https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool",
        "The web_search tool (web_search_20250305) takes max_uses and an "
        "approximate user_location, returns cited sources, and costs $10 per "
        "1,000 searches plus the tokens the results add.",
        "The Claude check searches from the business's city, capped at two "
        "searches per question, and only runs in client audits where its "
        "cost is trivial next to the fee.",
        ("auditor",), review_months=6),
)}


def get(key: str) -> Evidence:
    return LIBRARY[key]


def cite(*keys: str) -> str:
    return "; ".join(LIBRARY[k].cite() for k in keys)


def for_agent(agent: str) -> list[Evidence]:
    return [e for e in LIBRARY.values() if agent in e.used_by]


def overdue(today: date | None = None) -> list[Evidence]:
    return [e for e in LIBRARY.values() if e.due(today)]


AGENT_NAMES = {
    "auditor": "Auditor", "reporter": "Reporter", "casestudy": "Case studies",
    "calls": "Call list", "fixer": "Fixer", "method": "Delivery method",
    "citations": "Citation agent", "retention": "Retention", "outreach": "Outreach",
    "analyst": "Analyst", "sending": "Sending", "doctor": "Doctor",
}


def as_markdown() -> str:
    """business/08_RESEARCH.md, generated so it cannot drift from the code."""
    lines = [
        "# The research the agents work from",
        "",
        "Generated from `answerrank/evidence.py` (`python run.py evidence`). Every",
        "rule an agent follows because of outside research cites one of these,",
        "and a test fails if it cites one that is not here. Each entry says what",
        "the source found, in its own numbers, and separately what we do because",
        "of it, so the finding can be checked without agreeing with our reading.",
        "",
        "Research goes stale, AI search especially. Each entry has a shelf life;",
        "when it runs out, the Researcher agent says so.",
        "",
    ]
    for e in LIBRARY.values():
        agents = ", ".join(AGENT_NAMES.get(a, a) for a in e.used_by)
        lines += [
            f"## {e.source}",
            "",
            f"*{e.published} · last read {e.checked} · re-check every "
            f"{e.review_months} months · used by {agents}*",
            "",
            f"**Found:** {e.finding}",
            "",
            f"**So we:** {e.so_we}",
            "",
            f"Source: <{e.url}>",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"
