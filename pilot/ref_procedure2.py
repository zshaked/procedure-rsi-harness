"""Reference procedure for v2, using only the public tools and the email text.
Exists to prove the environment is solvable as specified: given the true policy parameters,
it must score 1.000. Usage: make_respond(policy) -> respond(request, tools)."""
from __future__ import annotations

import calendar
import datetime as dt
import re

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m} | {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}


def parse_date(body: str, sent: str) -> str | None:
    s = dt.date.fromisoformat(sent)
    b = body
    if re.search(r"end of last month|month-end|last day of last month", b):
        return (dt.date(s.year, s.month, 1) - dt.timedelta(days=1)).isoformat()
    m = re.search(r"(?:as of|as at|position date)\s+(.*?)(?:[.?]\s|[.?]$|\.\n|\?\n|$)", b)
    if not m:
        return None
    t = m.group(1).strip().rstrip(".?")
    if t.startswith("yesterday"):
        return (s - dt.timedelta(days=1)).isoformat()
    t = t.replace("close of business ", "")
    for pat in (r"(\d{4})-(\d{2})-(\d{2})",):
        mm = re.match(pat, t)
        if mm:
            return dt.date(int(mm[1]), int(mm[2]), int(mm[3])).isoformat()
    mm = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", t)
    if mm:
        return dt.date(int(mm[3]), int(mm[1]), int(mm[2])).isoformat()
    mm = re.match(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})", t)
    if mm:
        return dt.date(int(mm[3]), MONTHS[mm[2].lower()], int(mm[1])).isoformat()
    mm = re.match(r"([A-Za-z]+) (\d{1,2}), (\d{4})", t)
    if mm:
        return dt.date(int(mm[3]), MONTHS[mm[1].lower()], int(mm[2])).isoformat()
    mm = re.match(r"(?:[A-Za-z]{3} )?(\d{1,2}) ([A-Za-z]+) (\d{4})", t)
    if mm:
        return dt.date(int(mm[3]), MONTHS[mm[2].lower()], int(mm[1])).isoformat()
    return None


def parse_qty(body: str) -> int | None:
    m = re.search(r"(?:records show|We have|our figure is|We show)\s+([\d,\.]+)(k|mm)?", body)
    if not m:
        return None
    num = float(m[1].replace(",", "").rstrip("."))
    mult = {"k": 1000, "mm": 1_000_000}.get(m[2] or "", 1)
    return int(round(num * mult))


def make_respond(P):
    def respond(request, tools):
        def out(o, **kw):
            d = {"outcome": o, "account_id": None, "instrument_id": None, "as_of": None, "as_of_assumed": False,
                 "settled": None, "pending": None, "pending_date": None}
            d.update(kw)
            return d
        sent = request["sent"]
        email = request["from"]
        dom = email.split("@")[1]
        c = tools.get_contact(email)
        ents = tools.get_entitlements(c["contact_id"]) if c else []
        live = sorted({e["account_id"] for e in ents if e["expires"] >= sent})
        if P.order == "auth_first":
            if c is None or not live:
                return out("REQUEST_AUTHORIZATION")
            if P.domain_rule and not any(dom in tools.get_client_profile(a)["domains"] for a in live):
                return out("REQUEST_AUTHORIZATION")
        ref = request["mentions"]["account_text"]
        if ref is None:
            if P.implicit_account and len(live) == 1:
                accts = live
            else:
                return out("REQUEST_INFO")
        else:
            accts = [a["id"] for a in tools.search_accounts(ref)]
        if len(accts) != 1:
            return out("REQUEST_INFO")
        aid = accts[0]
        if c is None:
            return out("REQUEST_AUTHORIZATION")
        lvl = max([e["level"] for e in ents if e["account_id"] == aid and e["expires"] >= sent] or [0])
        if lvl == 0 or lvl < P.min_level:
            return out("REQUEST_AUTHORIZATION")
        prof = tools.get_client_profile(aid)
        if P.domain_rule and dom not in prof["domains"]:
            return out("REQUEST_AUTHORIZATION")
        if P.honor_opt_out and prof["no_email_confirm"]:
            return out("REQUEST_AUTHORIZATION")
        iref = request["mentions"]["instrument_text"]
        if not iref:
            return out("REQUEST_INFO", account_id=aid)
        insts = tools.search_instruments(iref)
        if len(insts) != 1:
            return out("REQUEST_INFO", account_id=aid)
        iid = insts[0]["id"]
        as_of = parse_date(request["body"], sent)
        assumed = False
        if as_of is None:
            if P.missing_asof == "request_info":
                return out("REQUEST_INFO", account_id=aid, instrument_id=iid)
            as_of, assumed = sent, True
        if as_of > sent:
            return out("REQUEST_INFO", account_id=aid, instrument_id=iid)
        cal = tools.get_calendar(as_of)
        if not cal["business_day"]:
            if P.non_bday == "request_info":
                return out("REQUEST_INFO", account_id=aid, instrument_id=iid)
            d = dt.date.fromisoformat(as_of)
            while not tools.get_calendar(d.isoformat())["business_day"]:
                d -= dt.timedelta(days=1)
            as_of = d.isoformat()
        if prof["legal_hold"]:
            return out("ESCALATE", account_id=aid, instrument_id=iid)
        splits = tools.get_corporate_actions(iid)
        sp = splits[0] if splits else None
        settled = 0
        pre_raw = 0
        for t in tools.get_ledger(aid, iid):
            if t["date"] <= as_of:
                q = t["qty"]
                if sp and t["date"] < sp["date"] <= as_of:
                    q *= sp["ratio"]
                settled += q
        if settled <= 0:
            return out("NOT_HELD", account_id=aid, instrument_id=iid, as_of=as_of, as_of_assumed=assumed)
        live_ins = [x for x in tools.get_instructions(aid, iid) if x["status"] == "matched" and x["settle_date"] > as_of]
        pend = sum(x["qty"] for x in live_ins)
        pdate = max((x["settle_date"] for x in live_ins), default=None)
        presplit = None
        if sp and sp["date"] <= as_of:
            led = tools.get_ledger(aid, iid)
            presplit = sum(t["qty"] for t in led if t["date"] < sp["date"]) + \
                sum(t["qty"] for t in led if sp["date"] <= t["date"] <= as_of) // sp["ratio"]
        common = dict(account_id=aid, instrument_id=iid, as_of=as_of, as_of_assumed=assumed, settled=settled)
        sq = parse_qty(request["body"])
        if sq is not None:
            basis = settled + (pend if P.qty_basis == "total" else 0)
            if not (P.accept_presplit and presplit is not None and sq == presplit) and abs(sq - basis) / basis > P.tol + 1e-12:
                return out("ESCALATE", **common)
        if P.big_escalate and settled > P.big_escalate:
            return out("ESCALATE", **common)
        if pend > P.pending_min:
            return out("CONFIRMED", pending=pend, pending_date=pdate, **common)
        return out("CONFIRMED", **common)
    return respond
