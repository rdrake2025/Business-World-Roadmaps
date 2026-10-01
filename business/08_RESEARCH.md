# The research the agents work from

Generated from `answerrank/evidence.py` (`python run.py evidence`). Every
rule an agent follows because of outside research cites one of these,
and a test fails if it cites one that is not here. Each entry says what
the source found, in its own numbers, and separately what we do because
of it, so the finding can be checked without agreeing with our reading.

Research goes stale, AI search especially. Each entry has a shelf life;
when it runs out, the Researcher agent says so.

## SparkToro & Gumshoe, AI brand-recommendation consistency study

*2026-01 · last read 2026-09 · re-check every 6 months · used by Auditor, Reporter, Case studies, Call list*

**Found:** 600 volunteers ran 12 prompts through ChatGPT, Claude and Google's AI 2,961 times. Fewer than 1 in 100 runs returned the same list of brands, fewer than 1 in 1,000 in the same order. 'Visibility % across many prompts run multiple times' is a reasonable metric; 'ranking position in AI' is not.

**So we:** Audits report the share of answers a business is named in, over repeated runs, with a margin of error. Client audits ask each question three times. A before-and-after only counts as movement when it beats the noise. Nothing claims a 'rank' in an AI answer.

Source: <https://sparktoro.com/blog/new-research-ais-are-highly-inconsistent-when-recommending-brands-or-products-marketers-should-take-care-when-tracking-ai-visibility/>

## BrightLocal, Uncovering ChatGPT Search Sources

*2024-12 · last read 2026-09 · re-check every 6 months · used by Auditor, Fixer, Citation agent*

**Found:** 800 local searches in ChatGPT: sources were business websites 58%, business mentions 27%, directories 15%. The leading directories were curated 'best of' sites: Three Best Rated (24% of directory sources) and Expertise (18%); Yelp, Facebook and Google Maps did not appear. Recommends optimising for Bing, which powers ChatGPT Search.

**So we:** The ChatGPT check searches the web the way ChatGPT does, rather than asking a model from memory. Bing Places is one of the listings every client gets. The citation agent checks the curated lists by name.

Source: <https://www.brightlocal.com/research/uncovering-chatgpt-search-sources/>

## Cheers, AI search engine source differences (home services baseline)

*2026-09 · last read 2026-09 · re-check every 3 months · used by Fixer, Citation agent*

**Found:** Home services, 28 days to 2 Sept 2026: ChatGPT cited contractor websites 48.8% of the time and directories or review platforms 44.7%. Gemini cited contractor sites 80.7%, Perplexity 72.3%, Google AI Overviews/AI Mode 70.3%. No engine guarantees a given page is cited.

**So we:** For trades, a contractor's own site carries most engines, and directories carry nearly half of ChatGPT. Both are worked on: service pages for the first, listings and curated lists for the second.

Source: <https://www.cheers.tech/geo-academy/ai-search-engine-source-differences>

## Yext, analysis of 6.8 million AI citations (as reported by Cheers)

*2025-10 · last read 2026-09 · re-check every 6 months · used by Fixer, Citation agent*

**Found:** 86% of AI citations came from sources a business manages: its own website (44%) and its listings (42%).

**So we:** Most of what the engines quote is within a client's control, which is what the retainer sells: the website and the listings, kept right.

Source: <https://www.cheers.tech/geo-academy/ai-search-engine-source-differences>

## Whitespark, 2026 Local Search Ranking Factors (AI search visibility)

*2026 · last read 2026-09 · re-check every 12 months · used by Fixer, Delivery method, Citation agent*

**Found:** Top AI visibility factors: 1) presence on expert-curated 'best of' lists, 2) a dedicated page for each service, 3) prominence on key industry-relevant domains, 4) quality and authority of unstructured citations, 5) authority of third-party sites where reviews are present. 'Website content marked up in schema' ranks #44.

**So we:** The delivery method is ordered by this: service pages in month one, curated lists in month two, industry domains and citations in month three, reviews on third-party sites in month four. Schema stays in month one because it is quick and cheap, and says honestly that it is not what moves AI answers.

Source: <https://whitespark.ca/local-search-ranking-factors/>

## Whitespark, 2026 Local Search Ranking Factors (local pack)

*2026 · last read 2026-09 · re-check every 12 months · used by Fixer, Delivery method*

**Found:** Top local pack factors: primary Google Business Profile category, proximity to the searcher, keywords in the GBP business title, a physical address in the city searched, open at the time of search. Review recency ranks #11. GBP signals weigh 32% overall, reviews 20%.

**So we:** Getting the primary category exactly right is the first GBP task. Hours are kept accurate because being open when someone searches counts.

Source: <https://whitespark.ca/local-search-ranking-factors/>

## BrightLocal, Local Consumer Review Survey 2026

*2026 · last read 2026-09 · re-check every 12 months · used by Fixer, Retention, Call list, Outreach*

**Found:** 45% of consumers used AI tools such as ChatGPT to find local businesses in the past year (6% the year before). 74% prioritise reviews from the last three months; 32% want one from the last two weeks. 68% require at least 4 stars; 31% only use businesses rated 4.5 or higher.

**So we:** Review work aims at a new review at least every two weeks, not a count. Retention watches for a client going quiet on reviews. The 45% figure is what the sales script leans on.

Source: <https://www.brightlocal.com/research/local-consumer-review-survey/>

## Instantly, Cold Email Benchmark Report 2026

*2026 · last read 2026-09 · re-check every 12 months · used by Outreach, Analyst, Sending*

**Found:** Average reply rate 3.43%; top quartile 5.5%+; elite 10.7%+. 58% of replies come from the first email. 4-7 touches is the sweet spot. Elite first emails average under 80 words. Wednesday has the highest reply rates. Keep bounces under 2%.

**So we:** The first email carries most of the weight and is kept under 80 words; the checker rejects a first touch over 100. The sequence is four touches. Bounces over 2% pause cold sending. The Analyst compares our reply rate against 3.4% and 5.5%.

Source: <https://instantly.ai/cold-email-benchmark-report-2026>

## Gong Labs, cold call opening lines (300 million calls)

*2025 · last read 2026-09 · re-check every 12 months · used by Call list*

**Found:** Stating the reason for the call raises success 2.1x. 'Did I catch you at a bad time?' makes a meeting 40% less likely.

**So we:** The call script opens with who is calling and the reason, in one breath, and never asks if it's a bad time.

Source: <https://www.gong.io/blog/cold-call-opening-lines>

## Gong Labs, cold calling statistics

*2025 · last read 2026-09 · re-check every 12 months · used by Call list*

**Found:** Successful cold calls average 5m50s, about twice as long as unsuccessful ones; reps talk about 55% of the time, in longer stretches (53s vs 25s). Wednesday and Thursday are the best days.

**So we:** The script's middle is a 40-second explanation, not a string of questions. The call list marks Wednesday and Thursday.

Source: <https://www.gong.io/blog/cold-call-stats>

## Google, Email sender guidelines

*2024-02 · last read 2026-09 · re-check every 12 months · used by Sending, Doctor*

**Found:** Senders of 5,000+ messages a day to Gmail need SPF, DKIM and DMARC (p=none at least, aligned), and one-click unsubscribe. Keep the user-reported spam rate below 0.1% and never let it reach 0.3%.

**So we:** The doctor blocks sending until SPF, DKIM and DMARC pass, whatever the volume. Every email has a one-click unsubscribe. The complaint ceiling is 0.1%.

Source: <https://support.google.com/a/answer/14229414?hl=en>

## Microsoft, Outlook requirements for high-volume senders

*2025-04 · last read 2026-09 · re-check every 12 months · used by Sending, Doctor*

**Found:** From 5 May 2025, domains sending 5,000+ emails a day to Outlook.com, Hotmail and Live must pass SPF and DKIM and publish DMARC (p=none at least, aligned), or be filtered or rejected.

**So we:** Same bar as Gmail, applied from the first email.

Source: <https://techcommunity.microsoft.com/blog/microsoftdefenderforoffice365blog/strengthening-email-ecosystem-outlook%E2%80%99s-new-requirements-for-high%E2%80%90volume-senders/4399730>

## FTC Telemarketing Sales Rule (2024 amendments); MarketingProfs on the B2B exemption

*2024-03 · last read 2026-09 · re-check every 12 months · used by Call list*

**Found:** Most business-to-business calls are exempt from the Do Not Call registry and much of the Rule. Since 2024, misrepresentations are prohibited on business calls too. The exemption does not cover turning a business's 'no need' into a pitch to the person who answered (MarketingProfs).

**So we:** Calls are dialled by hand to published business numbers; the script quotes only real audit results and never claims to be from an AI company; 'not interested' ends calls and email at once.

Source: <https://www.ftc.gov/news-events/news/press-releases/2024/03/ftc-implements-new-protections-businesses-against-telemarketing-fraud-affirms-protections-against-ai>

## OpenAI, Web search tool and pricing

*2026 · last read 2026-09 · re-check every 6 months · used by Auditor*

**Found:** The Responses API's web_search tool searches the live web, accepts an approximate user_location (city, region, country) and returns url_citation annotations. $10 per 1,000 calls for reasoning models (search content billed as tokens); $25 per 1,000 for others.

**So we:** The ChatGPT check uses web search from the business's own city, so it sees what a local customer sees, with the sources it used.

Source: <https://developers.openai.com/api/docs/guides/tools-web-search>

## Anthropic, Web search tool

*2026 · last read 2026-09 · re-check every 6 months · used by Auditor*

**Found:** The web_search tool (web_search_20250305) takes max_uses and an approximate user_location, returns cited sources, and costs $10 per 1,000 searches plus the tokens the results add.

**So we:** The Claude check searches from the business's city, capped at two searches per question, and only runs in client audits where its cost is trivial next to the fee.

Source: <https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool>

## OpenAI, API pricing

*2026 · last read 2026-09 · re-check every 6 months · used by Auditor, costs*

**Found:** Web search on reasoning models such as gpt-5-mini costs $10 per 1,000 calls plus the search content tokens at the model's rates; gpt-5-mini is $0.25 per million input tokens and $2.00 per million output.

**So we:** A cold prospect's check costs about 6 cents (four questions at about 1.5 cents), so the daily number of checks is the budget dial: Lean runs 5 a day (about $9 a month), Standard 20 (about $36), Growth 40 (about $72). costs.py works every figure out from the prices.

Source: <https://developers.openai.com/api/docs/pricing>

## OpenAI Help Center, Setting up and managing prepaid API billing

*2026 · last read 2026-09 · re-check every 6 months · used by Auditor, costs*

**Found:** API use is paid from prepaid credit. The minimum purchase is $5 and the default offered is $10; auto recharge is optional with a $5 minimum; purchased credits expire after one year.

**So we:** Pilots can be measured before any monthly cost: with only an OpenAI key a full audit is about 45 cents, so three pilots measured three times each fit inside the $5 minimum. PILOTS.md says to change the $10 default to $5 and leave auto recharge off.

Source: <https://help.openai.com/en/articles/8264644-setting-up-and-managing-prepaid-api-billing>

## Google Cloud, Free Tier

*2026 · last read 2026-09 · re-check every 6 months · used by server*

**Found:** One e2-micro VM a month is free in us-west1, us-central1 or us-east1, with 30 GB of standard disk and 1 GB of outbound data. An e2-micro has 2 shared vCPUs and 1 GB of memory. Ubuntu images read cloud-init user-data from instance metadata, and Google's network pricing says the free tier doesn't charge for an in-use external IP address.

**So we:** The server guide offers it as the free option: the same setup file, pasted as the user-data metadata key, in one of those three regions. Oracle's free tier was halved without notice in June 2026, so it is not recommended.

Source: <https://cloud.google.com/free>

## Google Workspace, Pricing

*2026 · last read 2026-09 · re-check every 12 months · used by keys, selftest*

**Found:** Business Starter is $8.40 per user a month on the flexible plan and $7 on annual billing. App passwords still work for IMAP and SMTP with 2-Step Verification; plain passwords stopped working for Workspace on 14 March 2025.

**So we:** The mailbox is the one fixed cost that can't be avoided: the fleet sends over SMTP and reads replies over IMAP with an app password.

Source: <https://workspace.google.com/pricing>

## Serper, Pricing

*2026 · last read 2026-09 · re-check every 12 months · used by scout, costs*

**Found:** 2,500 free queries with no card, then $50 for 50,000 credits, about $1 per 1,000, with paid credits valid for six months.

**So we:** The finder costs nothing to start; one places search finds up to 10 businesses.

Source: <https://serper.dev>

## FTC, CAN-SPAM Act: A Compliance Guide for Business

*2009 · last read 2026-09 · re-check every 24 months · used by Sending, Doctor*

**Found:** Any opt-out mechanism must process requests for at least 30 days after the message is sent, and opt-outs must be honoured within 10 business days. The postal address may be a street address, a USPS PO Box or a private mailbox at a registered commercial mail receiving agency.

**So we:** No email is sent, by the fleet or from the phone, unless the unsubscribe link answers from the internet, and the server that answers it runs all the time.

Source: <https://www.ftc.gov/business-guidance/resources/can-spam-act-compliance-guide-business>

## Healthchecks.io, Pinging API and pricing

*2026 · last read 2026-09 · re-check every 12 months · used by guardian, server*

**Found:** A running process signals it is alive with a GET or HEAD to https://hc-ping.com/<uuid>; when the signals stop, Healthchecks emails you. The free Hobbyist plan monitors up to 20 checks, with email alerts included.

**So we:** The fleet pings your check every cycle. If the server dies, the Guardian dies with it and can't warn you; Healthchecks can.

Source: <https://healthchecks.io/docs/http_api/>

## SQLite, Online Backup API; Python sqlite3 Connection.backup

*2026 · last read 2026-09 · re-check every 24 months · used by backup*

**Found:** The online backup API copies a database that is in use into a consistent snapshot; copying the file directly can capture a half-written state.

**So we:** Backups use Connection.backup, never a file copy, and are compressed before they leave the server.

Source: <https://www.sqlite.org/c3ref/backup_finish.html>

## Google, Send attachments with your Gmail message

*2026 · last read 2026-09 · re-check every 12 months · used by backup*

**Found:** Gmail and standard Workspace plans send attachments up to 25 MB and receive up to 50 MB; attachments are base64-encoded, which adds about a third, so the largest file that fits is under about 18 MB.

**So we:** The weekly off-server backup is emailed to you when it's under 15 MB compressed; above that, the email says so and how to fetch it.

Source: <https://support.google.com/mail/answer/6584>

## Help-desk practice on saved replies (Zendesk, Intercom, HelpDesk)

*2026 · last read 2026-09 · re-check every 12 months · used by concierge*

**Found:** Saved replies suit simple, repetitive, informational questions and should not be used for sensitive cases such as cancellations or bad news. They need clear names, an owner, and regular review to stay accurate.

**So we:** Only answers you wrote yourself are saved for reuse, each under the words that trigger it, listed in one place to review or delete. Cancellations and refunds are never answered from a saved reply.

Source: <https://www.helpdesk.com/blog/canned-responses/>

## Customer health scoring practice (Gainsight, HubSpot, Planhat)

*2026 · last read 2026-09 · re-check every 12 months · used by Retention*

**Found:** The red band should be small enough to act on; scores built on weak signals give false confidence and false alarms. Thresholds should be tested against outcomes and adjusted.

**So we:** 'Act now' needs a concrete risk: a failing card, no report delivered, fixes still not live after three weeks, a falling score, or long silence with nothing moving. A quiet client whose report arrives on time is monitored, not flagged.

Source: <https://www.gainsight.com/blog/customer-health-scores/>
