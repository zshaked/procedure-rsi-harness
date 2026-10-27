"""Hardened confirmations environment (v2).

Differences from v1, each aimed at a reason v1 was too easy:
- Requests are raw emails (greetings, signatures, forwarded headers, varied phrasing). A
  span extractor tool returns raw mentions without normalization; parsing dates such as
  "end of last month" or quantities such as "12.5k" is the method's job.
- State is spread over many tools and the right figure needs composition:
  * holdings are raw ledger transactions per custody sub-account, in pre-split units;
    settled = sum over sub-accounts, split-adjusted, as of the effective date
  * pending = matched (not cancelled / unmatched) instructions settling after the as-of date
  * authorization is per (contact, account) entitlement with expiry, not a contact attribute
  * the as-of date rolls to the previous business day (or not) per policy; holidays exist
  * get_position_summary is a plausible distractor: primary sub-account only, unadjusted,
    and one business day stale
- A long tail of rules that fire rarely: legal hold, client opt-out of email confirmations,
  expired entitlements, future as-of dates, implicit account, pre-split stated quantities.
"""
from __future__ import annotations

import calendar
import datetime as dt
import random
import re
from dataclasses import dataclass, field, asdict
from typing import Any

OUTCOMES = ["CONFIRMED", "NOT_HELD", "ESCALATE", "REQUEST_INFO", "REQUEST_AUTHORIZATION"]
D0 = dt.date(2026, 1, 2)
HOLIDAYS = {"2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-07-03"}


def is_bday(d: dt.date) -> bool:
    return d.weekday() < 5 and d.isoformat() not in HOLIDAYS


def prev_bday(d: dt.date) -> dt.date:
    d -= dt.timedelta(days=1)
    while not is_bday(d):
        d -= dt.timedelta(days=1)
    return d


def roll_back(d: dt.date) -> dt.date:
    while not is_bday(d):
        d -= dt.timedelta(days=1)
    return d


# --------------------------------------------------------------------------- state

_FIRST = ["Northwind", "Bluegate", "Harbor", "Crescent", "Ironwood", "Silverline", "Meridian", "Oakridge",
          "Pinecrest", "Redstone", "Summit", "Tidewater", "Granite", "Lakeshore", "Westbrook", "Falcon",
          "Evergreen", "Cobalt", "Juniper", "Halcyon", "Ashford", "Brightwater", "Calloway", "Dunmore"]
_SECOND = ["Capital", "Partners", "Asset Management", "Pension Trust", "Advisors", "Holdings",
           "Investment Fund", "Endowment", "Global Equity", "Fixed Income"]
_EXT = ["gmail.com", "outlook.com", "proton.me", "yahoo.com"]


@dataclass
class World:
    accounts: dict            # id -> {id, name, short_name, sub_accounts[]}
    profiles: dict            # id -> {domains[], legal_hold:bool, no_email_confirm:bool}
    contacts: dict            # email -> {contact_id, email, name}
    entitlements: dict        # contact_id -> [{account_id, level, expires}]
    instruments: dict         # id -> {id, ticker, old_ticker, name}
    splits: dict              # instrument_id -> {date, ratio}
    ledger: dict              # (account_id, instrument_id) -> [{sub_account, date, qty}]  (pre-split units)
    instructions: dict        # (account_id, instrument_id) -> [{id, qty, settle_date, status}]

    # ---------------- ground-truth computations (used by the gold executor) ----------------
    def resolve_account(self, ref: str) -> list[str]:
        r = ref.strip().lower()
        hits = [a["id"] for a in self.accounts.values()
                if r == a["id"].lower() or r in (s.lower() for s in a["sub_accounts"])
                or r == a["name"].lower() or r == a["short_name"].lower()]
        if not hits:
            hits = [a["id"] for a in self.accounts.values() if a["name"].lower().startswith(r)]
        return sorted(set(hits))

    def resolve_instrument(self, ref: str) -> list[str]:
        r = ref.strip().lower()
        return sorted({i["id"] for i in self.instruments.values()
                       if r in (i["ticker"].lower(), (i["old_ticker"] or "").lower(), i["name"].lower(), i["id"].lower())})

    def settled(self, aid: str, iid: str, as_of: str) -> int:
        sp = self.splits.get(iid)
        tot = 0
        for tx in self.ledger.get((aid, iid), []):
            if tx["date"] <= as_of:
                q = tx["qty"]
                if sp and tx["date"] < sp["date"] <= as_of:
                    q *= sp["ratio"]
                tot += q
        return tot

    def settled_presplit(self, aid: str, iid: str, as_of: str) -> int | None:
        sp = self.splits.get(iid)
        if not sp or sp["date"] > as_of:
            return None
        return sum(tx["qty"] for tx in self.ledger.get((aid, iid), []) if tx["date"] < sp["date"]) + \
            sum(tx["qty"] for tx in self.ledger.get((aid, iid), []) if sp["date"] <= tx["date"] <= as_of) // sp["ratio"]

    def pending(self, aid: str, iid: str, as_of: str) -> tuple[int, str | None]:
        live = [x for x in self.instructions.get((aid, iid), []) if x["status"] == "matched" and x["settle_date"] > as_of]
        if not live:
            return 0, None
        return sum(x["qty"] for x in live), max(x["settle_date"] for x in live)

    def entitlement(self, contact_id: str, aid: str, on: str) -> int:
        for e in self.entitlements.get(contact_id, []):
            if e["account_id"] == aid and e["expires"] >= on:
                return e["level"]
        return 0

    def live_entitled_accounts(self, contact_id: str, on: str) -> list[str]:
        return sorted({e["account_id"] for e in self.entitlements.get(contact_id, []) if e["expires"] >= on})


def make_world(seed: int = 0, n_accounts: int = 260, n_instruments: int = 140) -> World:
    rng = random.Random(seed)
    accounts, profiles, used = {}, {}, set()
    while len(accounts) < n_accounts:
        base = f"{rng.choice(_FIRST)} {rng.choice(_SECOND)}"
        fam = rng.choice([1, 1, 1, 2, 3])
        for k in range(fam):
            name = base + ([" I", " II", " III"][k] if fam > 1 else "")
            if name in used:
                continue
            used.add(name)
            aid = f"ACC-{10000 + len(accounts)}"
            short = "".join(w[0] for w in name.split()[:-1] if w[0].isalpha()).upper() + (name.split()[-1] if fam > 1 else rng.choice(["F", "T", "P"]))
            subs = [f"SA-{rng.randrange(100000, 999999)}" for _ in range(rng.choice([1, 1, 2, 3]))]
            accounts[aid] = {"id": aid, "name": name, "short_name": short, "sub_accounts": subs}
            dom = base.split()[0].lower() + rng.choice(["cap", "am", "funds", "inv"]) + ".com"
            doms = [dom] + ([dom.replace(".com", "-ops.com")] if rng.random() < 0.3 else [])
            profiles[aid] = {"domains": doms, "legal_hold": rng.random() < 0.03, "no_email_confirm": rng.random() < 0.04}
            if len(accounts) >= n_accounts:
                break

    instruments, splits = {}, {}
    L = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for _ in range(n_instruments):
        tk = "".join(rng.choice(L) for _ in range(rng.choice([3, 4])))
        iid = f"US{rng.randrange(10**9, 10**10)}"
        old = "".join(rng.choice(L) for _ in range(4)) if rng.random() < 0.12 else None
        instruments[iid] = {"id": iid, "ticker": tk, "old_ticker": old, "name": f"{tk.title()} {rng.choice(['Inc', 'Corp', 'Holdings', 'Group'])}"}
        if rng.random() < 0.18:
            splits[iid] = {"date": (D0 + dt.timedelta(days=rng.randrange(20, 140))).isoformat(), "ratio": rng.choice([2, 3])}

    contacts, ents = {}, {}
    acc_list = list(accounts)
    for aid in acc_list:
        for j in range(rng.choice([1, 2, 2, 3])):
            cid = f"C{len(contacts):05d}"
            local = rng.choice(["ops", "treasury", "j.smith", "a.lee", "m.garcia", "k.chen", "p.patel", "custody", "r.okafor"])
            dom = profiles[aid]["domains"][-1 if rng.random() < 0.3 else 0] if rng.random() > 0.1 else rng.choice(_EXT)
            email = f"{local}{j}.{aid[-3:]}@{dom}".lower()
            contacts[email] = {"contact_id": cid, "email": email, "name": local.replace(".", " ").title()}
            exp = (D0 + dt.timedelta(days=rng.randrange(400, 900))).isoformat() if rng.random() > 0.05 else \
                (D0 + dt.timedelta(days=rng.randrange(10, 120))).isoformat()
            e = [{"account_id": aid, "level": rng.choices([1, 2, 3], weights=[0.1, 0.3, 0.6])[0], "expires": exp}]
            if rng.random() < 0.15:  # adviser entitled to other accounts too
                for other in rng.sample(acc_list, rng.choice([1, 2])):
                    e.append({"account_id": other, "level": rng.choice([2, 3]),
                              "expires": (D0 + dt.timedelta(days=rng.randrange(300, 900))).isoformat()})
            ents[cid] = e

    ledger, instr = {}, {}
    inst_ids = list(instruments)
    for aid, a in accounts.items():
        for iid in rng.sample(inst_ids, 9):
            txs = []
            for sa in a["sub_accounts"]:
                if rng.random() < 0.75 or sa == a["sub_accounts"][0]:
                    q0 = rng.choice([rng.randrange(100, 30_000), rng.randrange(30_000, 900_000)])
                    txs.append({"sub_account": sa, "date": "2025-12-15", "qty": q0})
                    for _ in range(rng.choice([0, 1, 2])):
                        d = (D0 + dt.timedelta(days=rng.randrange(0, 150))).isoformat()
                        txs.append({"sub_account": sa, "date": d, "qty": rng.randrange(-q0 // 2, q0 // 2 + 1)})
            if rng.random() < 0.06:  # closed out
                tot = sum(t["qty"] for t in txs)
                txs.append({"sub_account": a["sub_accounts"][0], "date": (D0 + dt.timedelta(days=rng.randrange(0, 120))).isoformat(),
                            "qty": -tot})
            ledger[(aid, iid)] = txs
            ins = []
            for _ in range(rng.choice([0, 0, 1, 2])):
                ins.append({"id": f"INS{rng.randrange(10**6, 10**7)}",
                            "qty": rng.choice([rng.randrange(10, 900), rng.randrange(900, 60_000)]),
                            "settle_date": (D0 + dt.timedelta(days=rng.randrange(5, 175))).isoformat(),
                            "status": rng.choices(["matched", "unmatched", "cancelled"], weights=[0.6, 0.2, 0.2])[0]})
            instr[(aid, iid)] = ins
    return World(accounts, profiles, contacts, ents, instruments, splits, ledger, instr)


# --------------------------------------------------------------------------- requests

@dataclass
class Intent:
    """What the sender means. The email is rendered from this; the gold executor reads it."""
    from_email: str
    sent: str
    account_ref: str | None
    instrument_ref: str | None
    as_of: str | None          # calendar date the sender means, after resolving relative phrases
    stated_qty: int | None


def _fmt_date(d: dt.date, sent: dt.date, rng: random.Random) -> str:
    # relative phrase only when it resolves exactly to d
    last_prev = dt.date(sent.year, sent.month, 1) - dt.timedelta(days=1)
    if d == last_prev and rng.random() < 0.6:
        return rng.choice(["end of last month", "month-end", "the last day of last month"])
    if d == sent - dt.timedelta(days=1) and rng.random() < 0.5:
        return "yesterday"
    return rng.choice([
        d.isoformat(), d.strftime("%B %-d, %Y"), d.strftime("%-m/%-d/%Y"), d.strftime("%d-%b-%Y"),
        d.strftime("close of business %-d %B %Y"), d.strftime("%a %-d %b %Y")])


def _fmt_qty(q: int, rng: random.Random) -> str:
    r = rng.random()
    if r < 0.15 and q >= 10_000 and q % 100 == 0:
        return f"{q / 1000:g}k"
    if r < 0.25 and q >= 1_000_000 and q % 10_000 == 0:
        return f"{q / 1_000_000:g}mm"
    if r < 0.45:
        return f"{q}"
    return f"{q:,}"


def render_email(it: Intent, w: World, rng: random.Random) -> dict:
    sent = dt.date.fromisoformat(it.sent)
    name = w.contacts[it.from_email]["name"] if it.from_email in w.contacts else "Client"
    acct = f"{rng.choice(['account', 'acct', 'a/c', 'our account', 'fund'])} {it.account_ref}" if it.account_ref else rng.choice(["our account", "our fund", "the fund"])
    inst = it.instrument_ref
    date = _fmt_date(dt.date.fromisoformat(it.as_of), sent, rng) if it.as_of else None
    body_core = rng.choice([
        "Could you please confirm the position in {inst} held in {acct}{date}?",
        "Please confirm holdings of {inst} for {acct}{date}.",
        "We'd be grateful if you could confirm our {inst} position ({acct}){date}.",
        "Requesting confirmation of {acct} holdings in {inst}{date} for our audit.",
        "Can you confirm what {acct} holds in {inst}{date}?",
    ])
    if inst is None:
        body_core = rng.choice(["Could you please confirm the positions held in {acct}{date}?",
                                "Please send confirmation of holdings for {acct}{date}."])
    datestr = ""
    if date:
        datestr = rng.choice([f" as of {date}", f" as at {date}", f" as of {date}", f", position date {date}"])
    body = body_core.format(inst=inst, acct=acct, date=datestr)
    if it.stated_qty is not None:
        body += " " + rng.choice(["Our records show {q} units.", "We have {q} shares on our books.",
                                  "For reference, our figure is {q}.", "We show {q}."]).format(q=_fmt_qty(it.stated_qty, rng))
    greet = rng.choice(["Hi team,", "Hello,", "Dear Custody Services,", "Good morning,", ""])
    sign = rng.choice([f"Thanks,\n{name}", f"Best regards,\n{name}\nOperations", f"Kind regards\n{name}", f"{name}"])
    disclaimer = rng.choice(["", "", "\n\nThis email and any attachments are confidential and intended solely for the addressee."])
    text = f"{greet}\n\n{body}\n\n{sign}{disclaimer}".strip()
    if rng.random() < 0.15:
        text = (f"---------- Forwarded message ---------\nFrom: {it.from_email}\nDate: {it.sent}\n\n" + text)
    subject = rng.choice(["Position confirmation", "Holding confirmation request", "Audit confirmation",
                          f"Confirmation - {it.instrument_ref or 'holdings'}", "RE: position check"])
    return {"from": it.from_email, "sent": it.sent, "subject": subject, "body": text}


def make_intents(w: World, n: int, seed: int) -> list[Intent]:
    rng = random.Random(seed)
    emails = list(w.contacts)
    out = []
    for t in range(n):
        email = rng.choice(emails)
        cid = w.contacts[email]["contact_id"]
        sent = D0 + dt.timedelta(days=25 + int(t * 130 / n) + rng.randrange(0, 4))
        while sent.weekday() >= 5:
            sent += dt.timedelta(days=1)
        own = [e["account_id"] for e in w.entitlements[cid]]
        aid = rng.choice(own) if rng.random() > 0.06 else rng.choice(list(w.accounts))
        a = w.accounts[aid]
        r = rng.random()
        fam_base = a["name"].rsplit(" ", 1)[0] if a["name"].split()[-1] in ("I", "II", "III") else None
        if r < 0.05:
            account_ref = None
        elif fam_base and r < 0.40:
            account_ref = fam_base
        elif r < 0.55:
            account_ref = a["name"]
        elif r < 0.68:
            account_ref = a["short_name"]
        elif r < 0.80:
            account_ref = rng.choice(a["sub_accounts"])
        else:
            account_ref = a["id"]
        held = [iid for (x, iid) in w.ledger if x == aid]
        iid = rng.choice(held) if rng.random() > 0.08 else rng.choice(list(w.instruments))
        ins = w.instruments[iid]
        instrument_ref = None if rng.random() < 0.06 else rng.choice(
            [ins["ticker"], ins["ticker"], ins["name"], ins["id"]] + ([ins["old_ticker"]] * 2 if ins["old_ticker"] else []))
        rr = rng.random()
        if rr < 0.12:
            as_of = None
        elif rr < 0.30:
            as_of = (dt.date(sent.year, sent.month, 1) - dt.timedelta(days=1)).isoformat()
        elif rr < 0.42:
            as_of = (sent - dt.timedelta(days=1)).isoformat()
        elif rr < 0.44:
            as_of = (sent + dt.timedelta(days=rng.randrange(2, 20))).isoformat()   # future (rare)
        else:
            as_of = (sent - dt.timedelta(days=rng.randrange(2, 50))).isoformat()
        stated = None
        if rng.random() < 0.45:
            ref_d = as_of or sent.isoformat()
            base = w.settled(aid, iid, ref_d)
            pend = w.pending(aid, iid, ref_d)[0]
            pre = w.settled_presplit(aid, iid, ref_d)
            choice = rng.random()
            if pre and choice < 0.35:
                stated = pre
            else:
                b = base + (pend if rng.random() < 0.4 else 0)
                f = rng.choice([1.0, 1.0, 1.0, 1.02, 1.04, 0.93, 1.08, 0.85, 1.5])
                stated = int(round(b * f)) if b else rng.randrange(100, 20_000)
        out.append(Intent(email, sent.isoformat(), account_ref, instrument_ref, as_of, stated))
    return out


# --------------------------------------------------------------------------- policy

@dataclass
class Policy2:
    name: str
    min_level: int
    domain_rule: bool
    order: str                 # auth_first | resolve_first
    implicit_account: bool     # no account named + exactly one live entitlement -> use it
    missing_asof: str          # assume_sent_date | request_info
    non_bday: str              # roll_back | request_info
    qty_basis: str             # settled | total
    tol: float
    accept_presplit: bool      # a stated quantity equal to the pre-split figure is not a mismatch
    pending_min: int
    big_escalate: int | None
    honor_opt_out: bool        # client opted out of email confirmations -> REQUEST_AUTHORIZATION

    def render(self) -> str:
        r = []
        r.append(f"- The sender must hold a live (unexpired) entitlement of level >= {self.min_level} to the account; otherwise REQUEST_AUTHORIZATION.")
        if self.domain_rule:
            r.append("- The sender's email domain must be one of the client's registered domains; otherwise REQUEST_AUTHORIZATION.")
        r.append("- " + ("Check the sender's domain and that they hold any live entitlement before resolving the account." if self.order == "auth_first"
                         else "Resolve the account before any authorization check."))
        r.append("- If the account reference matches zero or several accounts, REQUEST_INFO." +
                 (" If no account is named and the sender has exactly one live entitlement, use that account." if self.implicit_account
                  else " If no account is named, REQUEST_INFO."))
        if self.honor_opt_out:
            r.append("- If the client has opted out of email confirmations, REQUEST_AUTHORIZATION.")
        r.append("- If the instrument is missing or matches zero or several instruments (old tickers count), REQUEST_INFO.")
        r.append("- No as-of date: " + ("use the date the email was sent and say you assumed it." if self.missing_asof == "assume_sent_date" else "REQUEST_INFO."))
        r.append("- As-of date in the future: REQUEST_INFO.")
        r.append("- As-of date on a weekend or holiday: " + ("use the previous business day." if self.non_bday == "roll_back" else "REQUEST_INFO."))
        r.append("- Accounts under legal hold: ESCALATE.")
        r.append("- Settled = sum across all custody sub-accounts, adjusted for splits, as of the effective date. Zero settled: NOT_HELD.")
        r.append("- Pending = matched instructions (not cancelled or unmatched) settling after the as-of date; pending date is the latest such settlement date.")
        basis = "settled" if self.qty_basis == "settled" else "settled plus pending"
        r.append(f"- If a stated quantity differs from {basis} by more than {self.tol:.0%}, ESCALATE" +
                 (", unless it equals the pre-split settled figure." if self.accept_presplit else "."))
        if self.big_escalate:
            r.append(f"- Settled above {self.big_escalate:,}: ESCALATE.")
        r.append(f"- Otherwise CONFIRMED; report pending and its date only if pending exceeds {self.pending_min:,}.")
        return "\n".join(r)


def policies2() -> list[Policy2]:
    S = [
        (2, False, "resolve_first", True, "assume_sent_date", "roll_back", "settled", 0.10, True, 0, None, True),
        (3, True, "auth_first", False, "request_info", "request_info", "total", 0.05, False, 100, 1_000_000, False),
        (2, True, "resolve_first", False, "assume_sent_date", "roll_back", "total", 0.0, True, 1000, None, True),
        (3, False, "auth_first", True, "assume_sent_date", "request_info", "settled", 0.05, True, 1000, 1_000_000, True),
        (2, True, "auth_first", False, "request_info", "roll_back", "total", 0.10, False, 0, None, False),
    ]
    return [Policy2(f"Q{k}", *s) for k, s in enumerate(S)]


def execute2(it: Intent, w: World, P: Policy2) -> dict[str, Any]:
    def out(o, rule, **kw):
        d = {"outcome": o, "account_id": None, "instrument_id": None, "as_of": None, "as_of_assumed": False,
             "settled": None, "pending": None, "pending_date": None}
        d.update(kw)
        d["_rule"] = rule
        return d

    c = w.contacts.get(it.from_email)
    dom = it.from_email.split("@")[1]
    cid = c["contact_id"] if c else None
    live = w.live_entitled_accounts(cid, it.sent) if cid else []

    def pre_auth():
        if c is None or not live:
            return "no_entitlement"
        if P.domain_rule and not any(dom in w.profiles[a]["domains"] for a in live):
            return "domain"
        return None

    if P.order == "auth_first":
        r = pre_auth()
        if r:
            return out("REQUEST_AUTHORIZATION", r)
    if it.account_ref is None:
        if P.implicit_account and len(live) == 1:
            accts = live
        else:
            return out("REQUEST_INFO", "account_missing")
    else:
        accts = w.resolve_account(it.account_ref)
    if len(accts) != 1:
        return out("REQUEST_INFO", "account_unresolved")
    aid = accts[0]
    if c is None:
        return out("REQUEST_AUTHORIZATION", "no_entitlement")
    lvl = w.entitlement(cid, aid, it.sent)
    if lvl == 0:
        expired = any(e["account_id"] == aid for e in w.entitlements[cid])
        return out("REQUEST_AUTHORIZATION", "expired_entitlement" if expired else "not_entitled")
    if lvl < P.min_level:
        return out("REQUEST_AUTHORIZATION", "level")
    if P.domain_rule and dom not in w.profiles[aid]["domains"]:
        return out("REQUEST_AUTHORIZATION", "domain")
    if P.honor_opt_out and w.profiles[aid]["no_email_confirm"]:
        return out("REQUEST_AUTHORIZATION", "opt_out")
    if not it.instrument_ref:
        return out("REQUEST_INFO", "instrument_missing", account_id=aid)
    insts = w.resolve_instrument(it.instrument_ref)
    if len(insts) != 1:
        return out("REQUEST_INFO", "instrument_unresolved", account_id=aid)
    iid = insts[0]
    assumed = False
    as_of = it.as_of
    if as_of is None:
        if P.missing_asof == "request_info":
            return out("REQUEST_INFO", "asof_missing", account_id=aid, instrument_id=iid)
        as_of, assumed = it.sent, True
    if as_of > it.sent:
        return out("REQUEST_INFO", "asof_future", account_id=aid, instrument_id=iid)
    d = dt.date.fromisoformat(as_of)
    if not is_bday(d):
        if P.non_bday == "request_info":
            return out("REQUEST_INFO", "asof_non_bday", account_id=aid, instrument_id=iid)
        as_of = roll_back(d).isoformat()
    if w.profiles[aid]["legal_hold"]:
        return out("ESCALATE", "legal_hold", account_id=aid, instrument_id=iid)
    s = w.settled(aid, iid, as_of)
    if s <= 0:
        return out("NOT_HELD", "not_held", account_id=aid, instrument_id=iid, as_of=as_of, as_of_assumed=assumed)
    pend, pdate = w.pending(aid, iid, as_of)
    common = dict(account_id=aid, instrument_id=iid, as_of=as_of, as_of_assumed=assumed, settled=s)
    if it.stated_qty is not None:
        basis = s + (pend if P.qty_basis == "total" else 0)
        pre = w.settled_presplit(aid, iid, as_of)
        if P.accept_presplit and pre is not None and it.stated_qty == pre:
            pass
        elif abs(it.stated_qty - basis) / basis > P.tol + 1e-12:
            return out("ESCALATE", "qty_mismatch", **common)
    if P.big_escalate and s > P.big_escalate:
        return out("ESCALATE", "large_position", **common)
    if pend > P.pending_min:
        return out("CONFIRMED", "confirm_with_pending", pending=pend, pending_date=pdate, **common)
    return out("CONFIRMED", "confirm", **common)


RULE_REASONS2 = {
    "no_entitlement": "We don't have this sender set up for this client, so we need authorization first.",
    "not_entitled": "This person isn't entitled to that account; authorization needed.",
    "expired_entitlement": "Their entitlement on that account has lapsed; they need re-authorization.",
    "level": "Their entitlement isn't high enough for a confirmation.",
    "domain": "That sender address isn't one of the client's registered domains.",
    "opt_out": "This client doesn't take confirmations by email; it has to go through authorization.",
    "account_missing": "They didn't say which account, so we ask.",
    "account_unresolved": "We can't tell which account they mean, so we ask them to clarify.",
    "instrument_missing": "They didn't say which security; we need to ask.",
    "instrument_unresolved": "The security reference is unclear; we need to ask.",
    "asof_missing": "No as-of date, so we go back and ask for one.",
    "asof_future": "They've asked about a date that hasn't happened yet.",
    "asof_non_bday": "That date isn't a business day; we ask them which date they want.",
    "legal_hold": "That account is under a legal hold; anything on it goes to escalation.",
    "not_held": "The account doesn't hold that security as of that date.",
    "qty_mismatch": "Their number doesn't match ours closely enough; that goes to escalation.",
    "large_position": "Positions that size always go to escalation before we confirm.",
    "confirm_with_pending": "Fine to confirm, but the pending amount and its settlement date need to be in there.",
    "confirm": "Fine to confirm with the settled position.",
}
