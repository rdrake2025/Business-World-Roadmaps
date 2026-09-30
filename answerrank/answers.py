"""Answers to what people actually ask, so a reply doesn't wait for you.

Prospects ask the same dozen questions: what it costs, whether there's a
contract, what happens each month, how long it takes, whether it's
guaranteed, whether their web person could do it. Clients ask a handful
more: how to cancel, where the invoice is, who gets the website login.

Each answer here was written once, carefully, from the sales playbook and
the service as it is actually delivered. None of them promises a ranking,
invents a number or commits you to work the service doesn't do. That is why
they can go out without you: they say only what is true of every client.

Anything that matches none of them is **not** answered with a guess. It is
held for you and you're emailed at once. An honest "I'll come back to you"
from a person beats a confident wrong answer from a template.

When you answer one of those yourself, you can save your answer under the
words that should trigger it. After that it's used like the ones here, but
only when none of these match, and never for a cancellation or a refund:
those always get the written answer above (evidence.py: saved_replies).
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Answer:
    key: str
    pattern: str
    text: str
    #: A client question the owner should also see (a cancellation, a
    #: refund, a change to their details). It is still answered at once.
    tell_owner: bool = False


PROSPECT: tuple[Answer, ...] = (
    Answer("price", r"how much|what (does|would) (it|this|that) cost|\bcost(s)?\b|"
                    r"\bpric(e|es|ing)\b|what do you charge|\bfees?\b|expensive|worth it",
           "It's {price}/month for {biz}, billed monthly, no contract, cancel any "
           "time. {payback} You'll see the same measurement every month, so it's "
           "never money spent on something you can't see: if the number doesn't "
           "move, cancel."),
    Answer("contract", r"contract|locked? in|commitment|minimum term|lawyer|"
                       r"sign (anything|up for a year)",
           "There's no contract. It's month to month, and you can cancel any time "
           "from the billing link in every email; nothing renews after that."),
    Answer("monthly", r"what (would|will|do) you (actually )?do|what('?s| is) included|"
                      r"what do (i|we) get|each month|every month|do differently",
           "Each month I re-run the same questions a customer asks on ChatGPT, "
           "Google's AI Overviews, Perplexity and Claude, and measure how often "
           "you're named. I write the fixes for your site (structured data, "
           "answer-ready service and FAQ content, listing corrections) as "
           "ready-to-paste files with plain steps for your website builder, and "
           "send a short report on what moved and what's next."),
    Answer("timeline", r"how long|how soon|how quickly|when (would|will|do|could) "
                       r"(we|i|you) see|see (a |any )?(difference|results|change)",
           "Honest answer: the engines pick up structured data when they next "
           "crawl, which is days to weeks, so month one is the baseline and most "
           "businesses see movement in month two or three. You get the same "
           "measurement every month, including the months it doesn't move."),
    Answer("guarantee", r"guarantee|promise|what if it (doesn'?t|does not) work|"
                        r"refund|money back",
           "Nobody can guarantee what an AI assistant says, and anyone who promises "
           "a ranking is guessing. What I do promise: the same measurement every "
           "month, and if you've put the fixes in and the number hasn't moved after "
           "30 days, I'll refund the month."),
    Answer("diy", r"(do|build|fix) (it|this|that) (my|our)sel(f|ves)|nephew|"
                  r"web(site)? (guy|person|designer|developer|company)|"
                  r"can'?t (he|she|they|i|we) just|in[- ]house",
           "Yes, honestly they could: it's public standards, and your report lists "
           "the fixes. What you'd be paying for is that it happens every month, "
           "gets checked, and someone watches the number. The report is yours to "
           "use either way."),
    Answer("later", r"wait (until|till)|later in the year|next (month|year|season|"
                    r"spring|summer|fall|winter)|slammed|swamped|circle back|"
                    r"not (right )?now,? but|after (the )?(season|summer|holidays)",
           "Of course. One thing worth knowing: what an assistant says in your busy "
           "season is built from what it indexed months before, so the quiet "
           "months are when this work lands. Reply whenever suits and I'll pick "
           "it up from here."),
    Answer("who", r"who (are|is) (you|this)|what is this|how did you (get|find)|"
                  r"where did you get|why (are you|did you) (email|contact)",
           "I run {brand}. I found {biz} in Google's local results, and your "
           "address on your website's contact page. I check how AI assistants "
           "answer for {trade} in {market}; that's the whole business. If you'd "
           "rather not hear from me, reply stop and that's the end of it."),
    Answer("free", r"(is|it'?s) (this|it|the report) (really |actually )?free|"
                   r"what'?s the catch|any catch",
           "The report is free, with no strings and no call attached. If you'd "
           "like me to do the work afterwards it's paid monthly, but you don't "
           "need to buy anything to keep the report."),
    Answer("how", r"how (does|do) (it|this|you) work|which (ai|engines|assistants)|"
                  r"what (is|are) ai (search|assistants?)|how do you (check|measure)",
           "I ask the questions a customer asks, like \"best {trade} in {city}\", "
           "on ChatGPT, Google's AI Overviews, Perplexity and Claude, several "
           "times each, and record who gets named. The fixes are what those "
           "engines read to decide: structured data on your site, answer-ready "
           "pages, and consistent listings."),
    Answer("access", r"log ?in|password|access to (our|my|the) (site|website|google)|"
                     r"\badmin\b|give you access",
           "You don't need to give me access to anything. Everything comes as "
           "files with plain steps for your website builder (WordPress, Wix, "
           "Squarespace and others), or you can forward them to whoever looks "
           "after your site."),
)

CLIENT: tuple[Answer, ...] = (
    Answer("cancel", r"\bcancel|stop (the )?(service|subscription|billing)|end (it|this|"
                     r"our|the)|terminate|don'?t want to continue",
           "Sorry to see you go. You can cancel any time here, and nothing renews "
           "after that: {portal} If something wasn't working, reply and tell me "
           "what; I'd rather fix it than lose you.", tell_owner=True),
    Answer("refund", r"refund|money back|charged twice|double charged|overcharged",
           "I've got this and I'll come back to you personally within a working "
           "day. Your billing history is here in the meantime: {portal}",
           tell_owner=True),
    Answer("billing", r"invoice|receipt|card|billing|\bcharge|payment method|"
                      r"update (my|our) (card|payment)",
           "Your invoices, receipts and card details are all here, any time: "
           "{portal}"),
    Answer("details", r"moved|new address|address (is|was) (old|wrong|out of date)|"
                      r"new (phone|number)|changed (our|the) (name|phone|address|number)|"
                      r"wrong (address|phone|number|hours)",
           "Thanks, noted. Update it on your Google Business Profile first, since "
           "that's the one the assistants trust most, and next month's files will "
           "use the new details.", tell_owner=True),
    Answer("access", r"log ?in|password|access|added you|add you|manager|"
                     r"who do (i|we) send",
           "Thanks, but there's no need to send any logins. Everything comes as "
           "files with plain steps for your website builder, or you can forward "
           "them to whoever looks after your site."),
    Answer("installed", r"installed|added (it|the code|the files|them)|put (it|them) "
                        r"(in|on|up)|it'?s (live|done|up)|all done|done that",
           "Thank you. Your site is checked every day; the next report will "
           "confirm it's live, or say exactly what's missing."),
    Answer("report", r"when (is|will) (my|the|our) (first )?report|haven'?t "
                     r"(got|had|received|seen)|where'?s (my|the|our) report",
           "Your first report goes out within a week of starting, then every "
           "month, by email. Each one shows the same measurement, so you can see "
           "exactly what moved."),
    Answer("thanks", r"^\W*(thanks|thank you|great|perfect|sounds good|looking "
                     r"forward|awesome|cheers)\b",
           "Thank you. Nothing else is needed from you right now; the next thing "
           "you'll get is your report."),
)


def _fill(text: str, values: dict[str, str]) -> str:
    return text.format(**values)


def _values(prospect, settings, client=None) -> dict[str, str]:
    from . import knowledge

    biz = prospect.business
    price = client.mrr if client is not None else settings.quote_for(biz.vertical)
    portal = (getattr(settings, "billing_portal_link", "") or "").strip()
    return {
        "price": f"${price:,.0f}",
        "biz": biz.name,
        "brand": settings.brand,
        "trade": knowledge.plural(knowledge.get(biz.vertical).label),
        "city": biz.city,
        "market": biz.market,
        "payback": knowledge.payback_line(biz.vertical, price),
        "portal": portal or "reply to this email and I'll sort it for you",
    }


def _match(bank: tuple[Answer, ...], text: str, limit: int) -> list[Answer]:
    low = (text or "").lower()
    return [a for a in bank if re.search(a.pattern, low)][:limit]


def saved_matches(store, text: str) -> list[dict]:
    """Answers you saved whose trigger words appear in what they wrote."""
    if store is None:
        return []
    low = (text or "").lower()
    out = []
    for a in store.saved_answers():
        triggers = [t.strip().lower() for t in (a.get("triggers") or "").split(",")
                    if len(t.strip()) >= 3]
        if any(re.search(r"\b" + re.escape(t) + r"\b", low) for t in triggers):
            out.append(a)
    return out[:1]


def _use_saved(store, text: str) -> list[str]:
    found = saved_matches(store, text)
    for a in found:
        store.note_answer_used(a["id"])
    return [a["text"] for a in found]


def for_prospect(text: str, prospect, settings, store=None) -> list[str]:
    """Answers to what a prospect asked, at most two. Empty means: a person."""
    values = _values(prospect, settings)
    found = [_fill(a.text, values) for a in _match(PROSPECT, text, 2)]
    return found or _use_saved(store, text)


def for_client(text: str, prospect, client, settings,
               store=None) -> tuple[list[str], bool]:
    """(answers, whether the owner should see it too). No answers: a person."""
    found = _match(CLIENT, text, 2)
    if not found:
        return _use_saved(store, text), False
    if any(a.key == "thanks" for a in found) and len(found) > 1:
        found = [a for a in found if a.key != "thanks"]
    values = _values(prospect, settings, client)
    if getattr(client, "status", "") == "churned" and any(a.key == "cancel" for a in found):
        return (["That's done: your subscription is cancelled and nothing more will be "
                 "charged. If you'd ever like the check again, just reply."], True)
    no_portal = not (getattr(settings, "billing_portal_link", "") or "").strip()
    tell = any(a.tell_owner or (no_portal and a.key == "billing") for a in found)
    return [_fill(a.text, values) for a in found], tell
