"""Induced procedure for the holding-confirmation desk.

Order of checks:
 1. Resolve account (mentions, falling back to ids in the body) and instrument.
 2. Sender verification: known contact, sender domain belongs to the client, and an
    unexpired entitlement of level >= 2 on the resolved account -> else REQUEST_AUTHORIZATION.
    If the account cannot be pinned down, a sender whose domain belongs to no candidate /
    entitled client is still REQUEST_AUTHORIZATION; otherwise REQUEST_INFO.
 3. Missing / ambiguous account, instrument or date -> REQUEST_INFO.
 4. Legal hold or no-email-confirm client -> ESCALATE.
 5. Figure = ledger across ALL sub-accounts up to the as-of date (rolled back to the previous
    business day when it is not one), split-adjusted.  Zero -> NOT_HELD.
 6. Client's own figure differs by more than 10% from settled (and from settled+pending) -> ESCALATE.
 7. CONFIRMED; matched instructions settling after the as-of date are reported as pending.
"""
import datetime as dt
import re

TOL = 0.10
FREE_MAIL = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com",
             "live.com", "msn.com", "protonmail.com", "proton.me", "gmx.com", "mail.com"}

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MON_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"


def _out(outcome, acc=None, ins=None, as_of=None, assumed=False, settled=None, pending=None, pdate=None):
    return {"outcome": outcome, "account_id": acc, "instrument_id": ins, "as_of": as_of,
            "as_of_assumed": bool(assumed) if as_of else False, "settled": settled,
            "pending": pending, "pending_date": pdate}


# ---------------------------------------------------------------- text cleaning
def _clean_body(body):
    lines = []
    for ln in (body or "").splitlines():
        s = ln.strip()
        if re.match(r"^-{2,}\s*(forwarded|original) message", s, re.I):
            continue
        if re.match(r"^(from|date|sent|to|cc|subject)\s*:", s, re.I):
            continue
        if re.search(r"confidential and intended solely", s, re.I):
            continue
        lines.append(ln)
    return "\n".join(lines)


# ---------------------------------------------------------------- dates
def _mk(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _month_end(y, m):
    nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
    return nxt - dt.timedelta(days=1)


def _infer_year(m, d, sent):
    c = _mk(sent.year, m, d)
    if c and c > sent:
        c = _mk(sent.year - 1, m, d)
    return c


def parse_date(text, sent):
    """Return (date|None, assumed: bool)."""
    t = text.lower()
    # ISO
    m = re.search(r"\b(20\d\d)-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        d = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            return d, False
    # numeric m/d/y (US) or d/m/y when unambiguous
    m = re.search(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})\b", t)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        d = _mk(y, a, b) if a <= 12 else _mk(y, b, a)
        if d:
            return d, False
    # 3 Jan 2026 / 27-Jan-2026 / 22 December 2025
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-]+(?:of\s+)?" + MON_RE + r"\.?,?[\s\-]+(\d{4})\b", t)
    if m:
        d = _mk(int(m.group(3)), MONTHS[m.group(2)[:3]], int(m.group(1)))
        if d:
            return d, False
    # January 27, 2026
    m = re.search(MON_RE + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", t)
    if m:
        d = _mk(int(m.group(3)), MONTHS[m.group(1)[:3]], int(m.group(2)))
        if d:
            return d, False
    # no year: "3 Jan", "Jan 3"
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-]+(?:of\s+)?" + MON_RE + r"\b(?!\s*\d)", t)
    if m:
        d = _infer_year(MONTHS[m.group(2)[:3]], int(m.group(1)), sent)
        if d:
            return d, True
    m = re.search(r"\b" + MON_RE + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b(?!\s*,?\s*\d{4})", t)
    if m and not re.search(r"(month|year)", m.group(0)):
        d = _infer_year(MONTHS[m.group(1)[:3]], int(m.group(2)), sent)
        if d:
            return d, True
    # relative
    if re.search(r"\byesterday\b", t):
        return sent - dt.timedelta(days=1), False
    if re.search(r"\b(today|this morning|now|current(ly)?|latest)\b", t) and re.search(
            r"(as of|as at|position date|date)\s+(today|now)|\btoday\b|\bcurrent(ly)?\b|\blatest\b", t):
        return sent, True
    if re.search(r"(year[\s\-]?end|end of (last |the )?year|end of 20\d\d|last day of last year)", t):
        m = re.search(r"end of (20\d\d)", t)
        y = int(m.group(1)) if m else sent.year - 1
        return dt.date(y, 12, 31), True
    m = re.search(r"(?:end of|month[\s\-]?end)\s*(?:of\s+)?" + MON_RE + r"(?:\s+(\d{4}))?", t) or \
        re.search(MON_RE + r"(?:\s+(\d{4}))?\s+month[\s\-]?end", t)
    if m:
        mo = MONTHS[m.group(1)[:3]]
        y = int(m.group(2)) if m.group(2) else sent.year
        if not m.group(2) and _month_end(y, mo) >= sent:
            y -= 1
        return _month_end(y, mo), True
    if re.search(r"(month[\s\-]?end|end of (last |the previous |previous |the )?month|last day of (last|the previous|previous) month|end-of-month|\beom\b)", t):
        first = sent.replace(day=1)
        return first - dt.timedelta(days=1), True
    if re.search(r"(last|previous|prior) (business|working) day|\bcob\b(?! \d)|close of business(?! \d)", t):
        return sent - dt.timedelta(days=1), True
    return None, False


# ---------------------------------------------------------------- quantities
def _num(s, suf):
    v = float(s.replace(",", ""))
    suf = (suf or "").lower()
    if suf in ("k", "thousand"):
        v *= 1e3
    elif suf in ("m", "mm", "mn", "mln", "million"):
        v *= 1e6
    elif suf in ("bn", "b", "billion"):
        v *= 1e9
    return int(round(v))


def parse_claim(text):
    t = text
    kw = (r"(records show|we show|our figure is|figure of|we have|we hold|our books show|"
          r"shows?|holding of|reconcil\w* to|position of|balance of|our position is|we expect)")
    for m in re.finditer(kw, t, re.I):
        seg = t[m.end(): m.end() + 40]
        q = re.match(r"\s*(?:is|of|:|approximately|approx\.?|about|around|~)?\s*"
                     r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(mm|mn|mln|million|thousand|bn|k|m|b)?\b",
                     seg, re.I)
        if q:
            return _num(q.group(1), q.group(2))
    m = re.search(r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(mm|mn|million|k|m)?\s*(units|shares)\b", t, re.I)
    if m:
        return _num(m.group(1), m.group(2))
    return None


# ---------------------------------------------------------------- resolution
def _resolve_account(text, tools):
    """Return list of candidate account ids."""
    if not text:
        return []
    q = text.strip().strip(".,;:()'\"")
    tries = [q]
    s = re.sub(r"^(our\s+)?(account|acct|a/c|fund|portfolio|client)\s+", "", q, flags=re.I).strip()
    tries.append(s)
    m = re.search(r"\b(ACC|SA)[\s\-_]?(\d{5,6})\b", q, re.I)
    if m:
        tries.insert(0, m.group(1).upper() + "-" + m.group(2))
    for t in tries:
        if not t:
            continue
        hits = tools.search_accounts(t)
        if hits:
            return [h["id"] for h in hits]
    return []


def _resolve_instrument(text, tools):
    if not text:
        return []
    q = text.strip().strip(".,;:()'\"")
    tries = [q]
    m = re.search(r"\b([A-Z]{2}[A-Z0-9]{9}\d)\b", q)
    if m:
        tries.insert(0, m.group(1))
    s = re.sub(r"^(isin|ticker|cusip|sedol)\s*:?\s*", "", q, flags=re.I)
    s = re.sub(r"\s+(shares|stock|equity|units|common|ordinary)$", "", s, flags=re.I).strip()
    tries.append(s)
    for t in tries:
        if not t:
            continue
        hits = tools.search_instruments(t)
        if hits:
            ids = sorted({h["id"] for h in hits})
            if len(ids) > 1:
                cur = [h["id"] for h in hits if h["ticker"].lower() == t.lower() or h["id"].lower() == t.lower()]
                if len(cur) == 1:
                    return cur
            return ids
    return []


def _domain(email):
    return (email or "").strip().lower().rsplit("@", 1)[-1]


def _domain_ok(dom, domains):
    for d in domains or []:
        d = d.lower()
        if dom == d or dom.endswith("." + d):
            return True
    return False


def _entitled(ents, acc, sent_iso):
    for e in ents:
        if e["account_id"] == acc and int(e["level"]) >= 2 and (not e.get("expires") or e["expires"] >= sent_iso):
            return True
    return False


# ---------------------------------------------------------------- figures
def _business_as_of(d, tools):
    iso = d.isoformat()
    cal = tools.get_calendar(iso)
    if cal["business_day"]:
        return iso, False
    return cal["previous_business_day"], True


def _settled(acc, ins, as_of, tools):
    splits = [c for c in tools.get_corporate_actions(ins) if c.get("type") == "split"]
    total = 0
    for t in tools.get_ledger(acc, ins):
        if t["date"] > as_of:
            continue
        q = t["qty"]
        for s in splits:
            if t["date"] < s["date"] <= as_of:
                q *= s["ratio"]
        total += q
    return total


def _pending(acc, ins, as_of, tools):
    items = [x for x in tools.get_instructions(acc, ins)
             if x["status"] == "matched" and x["settle_date"] > as_of]
    if not items:
        return None, None
    return sum(x["qty"] for x in items), max(x["settle_date"] for x in items)


def _close(claim, ref):
    if ref <= 0:
        return claim == ref
    return abs(claim - ref) <= TOL * ref


# ---------------------------------------------------------------- main
def respond(request, tools):
    sender = (request.get("from") or "").strip().lower()
    sent = dt.date.fromisoformat(str(request.get("sent"))[:10])
    sent_iso = sent.isoformat()
    body = _clean_body(request.get("body") or "")
    subject = request.get("subject") or ""
    mentions = request.get("mentions") or {}
    acc_text = mentions.get("account_text")
    ins_text = mentions.get("instrument_text")

    # fallbacks from body if the extractor missed something obvious
    if not acc_text:
        m = re.search(r"\b(ACC|SA)[\s\-]?\d{5,6}\b", body, re.I)
        acc_text = m.group(0) if m else None
    if not ins_text:
        m = re.search(r"\b[A-Z]{2}\d{10}\b", body + " " + subject)
        ins_text = m.group(0) if m else None

    accs = _resolve_account(acc_text, tools)
    inss = _resolve_instrument(ins_text, tools)

    contact = tools.get_contact(sender)
    ents = tools.get_entitlements(contact["contact_id"]) if contact else []
    dom = _domain(sender)

    # --- sender verification
    if len(accs) == 1:
        acc = accs[0]
        prof = tools.get_client_profile(acc) or {}
        if (not contact or dom in FREE_MAIL or not _domain_ok(dom, prof.get("domains"))
                or not _entitled(ents, acc, sent_iso)):
            return _out("REQUEST_AUTHORIZATION")
    else:
        acc = None
        prof = {}
        if not contact or dom in FREE_MAIL:
            return _out("REQUEST_AUTHORIZATION")
        cand = accs if accs else [e["account_id"] for e in ents]
        doms = []
        for a in cand:
            p = tools.get_client_profile(a) or {}
            doms += p.get("domains") or []
        if not _domain_ok(dom, doms):
            return _out("REQUEST_AUTHORIZATION")
        return _out("REQUEST_INFO")

    # --- completeness
    date, assumed = parse_date(body, sent)
    if date is None:
        date, assumed = parse_date(subject, sent)
    if len(inss) != 1 or date is None:
        return _out("REQUEST_INFO")
    ins = inss[0]

    # --- client restrictions
    if prof.get("legal_hold") or prof.get("no_email_confirm"):
        return _out("ESCALATE", acc, ins)

    # --- date handling
    if date >= sent:
        date = sent - dt.timedelta(days=1)
        assumed = True
    as_of, rolled = _business_as_of(date, tools)

    settled = _settled(acc, ins, as_of, tools)
    pending, pdate = _pending(acc, ins, as_of, tools)
    claim = parse_claim(body)

    if settled < 0:
        return _out("ESCALATE", acc, ins)
    if settled == 0:
        return _out("NOT_HELD", acc, ins, as_of, assumed, None, pending, pdate)
    if claim is not None and not (_close(claim, settled) or (pending and _close(claim, settled + pending))):
        return _out("ESCALATE", acc, ins)
    return _out("CONFIRMED", acc, ins, as_of, assumed, settled, pending, pdate)
