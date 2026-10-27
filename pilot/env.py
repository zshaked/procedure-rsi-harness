"""Synthetic position-confirmation environment with executable hidden policies.

Everything here is deterministic from a seed. The hidden policy is code: `execute_policy`
returns the required structured response and the rule that decided it. Grading compares a
method's structured response to that output; no LLM is involved in grading.
"""
from __future__ import annotations

import datetime as dt
import random
from dataclasses import dataclass, field, asdict
from typing import Any

OUTCOMES = ["CONFIRMED", "NOT_HELD", "ESCALATE", "REQUEST_INFO", "REQUEST_AUTHORIZATION"]

# --------------------------------------------------------------------------- state

_FIRST = ["Northwind", "Bluegate", "Harbor", "Crescent", "Ironwood", "Silverline", "Meridian",
          "Oakridge", "Pinecrest", "Redstone", "Summit", "Tidewater", "Granite", "Lakeshore",
          "Westbrook", "Falcon", "Evergreen", "Cobalt", "Juniper", "Halcyon"]
_SECOND = ["Capital", "Partners", "Asset Management", "Pension Trust", "Advisors", "Holdings",
           "Investment Fund", "Endowment", "Global Equity", "Fixed Income"]
_SUFFIX = ["", " I", " II", " III"]
_EXT_DOMAINS = ["gmail.com", "outlook.com", "proton.me"]


@dataclass
class Account:
    id: str
    name: str
    domain: str


@dataclass
class Contact:
    email: str
    account_id: str
    auth_level: int


@dataclass
class Instrument:
    id: str
    ticker: str
    name: str


@dataclass
class Position:
    account_id: str
    instrument_id: str
    trade_date: str      # quantity changes on this date
    qty_before: int
    qty_after: int
    pending: int
    pending_date: str | None

    def settled_as_of(self, as_of: str) -> int:
        return self.qty_after if as_of >= self.trade_date else self.qty_before


@dataclass
class State:
    accounts: dict[str, Account]
    contacts: dict[str, Contact]
    instruments: dict[str, Instrument]
    positions: dict[tuple[str, str], Position]

    # ---- tools (the closed vocabulary methods may use) ----
    def lookup_account(self, ref: str) -> list[dict]:
        ref_l = ref.lower().strip()
        if ref_l in (a.id.lower() for a in self.accounts.values()):
            return [asdict(self.accounts[ref.upper().strip()])]
        hits = [a for a in self.accounts.values() if ref_l == a.name.lower()]
        if not hits:
            hits = [a for a in self.accounts.values() if a.name.lower().startswith(ref_l)]
        return [asdict(a) for a in hits]

    def get_contact(self, email: str) -> dict | None:
        c = self.contacts.get(email.lower())
        return asdict(c) if c else None

    def resolve_instrument(self, ref: str) -> list[dict]:
        ref_l = ref.lower().strip()
        hits = [i for i in self.instruments.values()
                if ref_l in (i.ticker.lower(), i.name.lower(), i.id.lower())]
        return [asdict(i) for i in hits]

    def get_position(self, account_id: str, instrument_id: str, as_of: str) -> dict | None:
        p = self.positions.get((account_id, instrument_id))
        if p is None:
            return None
        pend = p.pending if (p.pending_date and p.pending_date > as_of) else 0
        return {"settled": p.settled_as_of(as_of), "pending": pend,
                "pending_date": p.pending_date if pend else None}


def make_state(seed: int = 0, n_accounts: int = 240, n_instruments: int = 120) -> State:
    rng = random.Random(seed)
    accounts: dict[str, Account] = {}
    used = set()
    while len(accounts) < n_accounts:
        base = f"{rng.choice(_FIRST)} {rng.choice(_SECOND)}"
        # create families of similarly named accounts (source of ambiguity)
        n_family = rng.choice([1, 1, 1, 2, 3])
        for k in range(n_family):
            name = base + (_SUFFIX[k + 1] if n_family > 1 else "")
            if name in used:
                continue
            used.add(name)
            aid = f"ACC-{10000 + len(accounts)}"
            domain = base.split()[0].lower() + rng.choice(["cap", "am", "funds", "inv"]) + ".com"
            accounts[aid] = Account(aid, name, domain)
            if len(accounts) >= n_accounts:
                break

    instruments: dict[str, Instrument] = {}
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for k in range(n_instruments):
        tick = "".join(rng.choice(letters) for _ in range(rng.choice([3, 4])))
        iid = f"ISIN{rng.randrange(10**9, 10**10)}"
        instruments[iid] = Instrument(iid, tick, f"{tick.title()} Corp {rng.choice(['Common', 'Class A', 'Ord'])}")

    contacts: dict[str, Contact] = {}
    for a in accounts.values():
        for j in range(rng.choice([1, 2, 3])):
            local = rng.choice(["ops", "treasury", "j.smith", "a.lee", "m.garcia", "k.chen", "p.patel", "custody"]) + str(j)
            domain = a.domain if rng.random() > 0.12 else rng.choice(_EXT_DOMAINS)
            email = f"{local}.{a.id[-3:]}@{domain}".lower()
            contacts[email] = Contact(email, a.id, rng.choices([1, 2, 3], weights=[0.08, 0.27, 0.65])[0])

    positions: dict[tuple[str, str], Position] = {}
    inst_ids = list(instruments)
    base_day = dt.date(2026, 1, 5)
    for a in accounts.values():
        for iid in rng.sample(inst_ids, 8):
            qb = rng.choice([rng.randrange(100, 20_000), rng.randrange(20_000, 2_500_000)])
            qa = max(0, qb + rng.choice([0, 0, rng.randrange(-qb // 2, qb // 2 + 1)]))
            if rng.random() < 0.08:
                qa = 0  # position closed out
            td = (base_day + dt.timedelta(days=rng.randrange(0, 150))).isoformat()
            pend, pdate = 0, None
            if rng.random() < 0.45:
                pend = rng.choice([rng.randrange(10, 100), rng.randrange(100, 1000), rng.randrange(1000, 50_000)])
                pdate = (base_day + dt.timedelta(days=rng.randrange(0, 170))).isoformat()
            positions[(a.id, iid)] = Position(a.id, iid, td, qb, qa, pend, pdate)
    return State(accounts, contacts, instruments, positions)


# --------------------------------------------------------------------------- requests

@dataclass
class Request:
    case_id: str
    t: int
    from_email: str
    request_date: str
    account_ref: str
    instrument_ref: str | None
    as_of: str | None
    stated_qty: int | None
    body: str = ""


def make_requests(state: State, n: int, seed: int, prefix: str) -> list[Request]:
    rng = random.Random(seed)
    contacts = list(state.contacts.values())
    reqs = []
    day0 = dt.date(2026, 1, 5)
    for t in range(n):
        c = rng.choice(contacts)
        # occasionally the contact asks about an account that is not theirs
        acc = state.accounts[c.account_id] if rng.random() > 0.07 else rng.choice(list(state.accounts.values()))
        held = [p for (aid, _), p in state.positions.items() if aid == acc.id]
        if rng.random() < 0.10:
            inst = rng.choice([i for i in state.instruments.values()
                               if (acc.id, i.id) not in state.positions])
        else:
            inst = state.instruments[rng.choice(held).instrument_id]
        req_date = (day0 + dt.timedelta(days=30 + int(t * 120 / n) + rng.randrange(0, 5))).isoformat()
        as_of = None if rng.random() < 0.15 else (
            dt.date.fromisoformat(req_date) - dt.timedelta(days=rng.randrange(0, 60))).isoformat()
        # account reference: id, exact name, or ambiguous family prefix
        r = rng.random()
        family_base = acc.name.rsplit(" ", 1)[0] if acc.name.split()[-1] in ("I", "II", "III") else None
        if family_base and r < 0.45:
            account_ref = family_base           # ambiguous when the family has >1 member
        elif r < 0.75:
            account_ref = acc.name
        else:
            account_ref = acc.id
        instrument_ref = None if rng.random() < 0.08 else rng.choice([inst.ticker, inst.name])
        stated = None
        if rng.random() < 0.45:
            pos = state.get_position(acc.id, inst.id, as_of or req_date)
            base = (pos["settled"] if pos else 0) + (pos["pending"] if pos and rng.random() < 0.5 else 0)
            factor = rng.choice([1.0, 1.0, 1.02, 1.04, 0.93, 1.08, 0.85, 1.5])
            stated = int(round(base * factor)) if base else rng.randrange(100, 10_000)
        reqs.append(Request(f"{prefix}{t:04d}", t, c.email, req_date, account_ref, instrument_ref, as_of, stated))
    for q in reqs:
        q.body = render_request(q)
    return reqs


def render_request(q: Request) -> str:
    parts = [f"Please confirm our holding for account {q.account_ref}"]
    if q.instrument_ref:
        parts.append(f" in {q.instrument_ref}")
    if q.as_of:
        parts.append(f" as of {q.as_of}")
    parts.append(".")
    if q.stated_qty is not None:
        parts.append(f" Our records show {q.stated_qty:,} units.")
    return "".join(parts) + " Thank you."


# --------------------------------------------------------------------------- policy

@dataclass
class Policy:
    name: str
    auth_min: int                  # contact auth level required
    external_rule: bool            # contact domain must match account domain
    order: str                     # "auth_first" | "resolve_first"
    missing_asof: str              # "assume_request_date" | "request_info"
    qty_basis: str                 # "settled" | "total"
    tol: float                     # relative tolerance before escalation
    pending_min: int               # report pending only if pending > pending_min
    big_escalate: int | None       # escalate confirmations above this settled quantity

    def render(self) -> str:
        """Plain-language policy document (for the gold agent / true-spec arm only)."""
        lines = [
            f"1. Only contacts with authorization level >= {self.auth_min} may receive confirmations; otherwise reply REQUEST_AUTHORIZATION.",
            "2. The contact must belong to the account asked about; otherwise REQUEST_AUTHORIZATION.",
        ]
        if self.external_rule:
            lines.append("3. Contacts whose email domain differs from the account's domain must be treated as unauthorized (REQUEST_AUTHORIZATION).")
        lines.append("4. If the account reference matches zero or several accounts, reply REQUEST_INFO." +
                     (" Check authorization (rules 1 and 3) before resolving the account." if self.order == "auth_first"
                      else " Resolve the account before checking authorization."))
        lines.append("5. If the instrument is missing or ambiguous, reply REQUEST_INFO.")
        lines.append("6. If no as-of date is given, " + ("use the request date and state that you assumed it." if self.missing_asof == "assume_request_date"
                                                       else "reply REQUEST_INFO."))
        lines.append("7. If the account holds no settled position in the instrument as of the date, reply NOT_HELD.")
        basis = "settled quantity" if self.qty_basis == "settled" else "settled plus pending quantity"
        lines.append(f"8. If the requester states a quantity and it differs from the {basis} by more than {self.tol:.0%}, reply ESCALATE.")
        if self.big_escalate:
            lines.append(f"9. Escalate (ESCALATE) any confirmation where the settled quantity exceeds {self.big_escalate:,}.")
        lines.append(f"10. Otherwise CONFIRMED with the settled quantity as of the date; report pending quantity and its expected settlement date only if pending exceeds {self.pending_min:,}.")
        return "\n".join(lines)


def sample_policies(seed: int = 7, n: int = 5) -> list[Policy]:
    """Five instances chosen so every parameter value appears at least once across the
    three development instances (P0-P2) and again in the held-out instances (P3-P4)."""
    specs = [
        (2, False, "resolve_first", "assume_request_date", "settled", 0.10, 0, None),
        (3, True, "auth_first", "request_info", "total", 0.05, 100, 1_000_000),
        (2, True, "resolve_first", "assume_request_date", "total", 0.0, 1000, None),
        (3, False, "auth_first", "assume_request_date", "settled", 0.05, 1000, 1_000_000),
        (2, True, "auth_first", "request_info", "total", 0.10, 0, None),
    ]
    return [Policy(f"P{k}", *sp) for k, sp in enumerate(specs[:n])]


def execute_policy(q: Request, s: State, P: Policy) -> dict[str, Any]:
    """The hidden procedure. Returns the required structured response plus the decisive rule."""
    def out(outcome, rule, **kw):
        d = {"outcome": outcome, "account_id": None, "instrument_id": None, "as_of": None,
             "as_of_assumed": False, "settled": None, "pending": None, "pending_date": None}
        d.update(kw)
        d["_rule"] = rule
        return d

    contact = s.get_contact(q.from_email)

    def auth_fail(account: dict | None) -> str | None:
        if contact is None or contact["auth_level"] < P.auth_min:
            return "auth_level"
        if P.external_rule and account is not None and q.from_email.split("@")[1] != account["domain"]:
            return "external_domain"
        if P.external_rule and account is None:
            own = s.accounts[contact["account_id"]]
            if q.from_email.split("@")[1] != own.domain:
                return "external_domain"
        return None

    if P.order == "auth_first":
        r = auth_fail(None)
        if r:
            return out("REQUEST_AUTHORIZATION", r)
    accts = s.lookup_account(q.account_ref)
    if len(accts) != 1:
        return out("REQUEST_INFO", "account_unresolved")
    acct = accts[0]
    r = auth_fail(acct)
    if r:
        return out("REQUEST_AUTHORIZATION", r)
    if contact["account_id"] != acct["id"]:
        return out("REQUEST_AUTHORIZATION", "not_own_account")
    if not q.instrument_ref:
        return out("REQUEST_INFO", "instrument_missing", account_id=acct["id"])
    insts = s.resolve_instrument(q.instrument_ref)
    if len(insts) != 1:
        return out("REQUEST_INFO", "instrument_unresolved", account_id=acct["id"])
    inst = insts[0]
    assumed = False
    as_of = q.as_of
    if as_of is None:
        if P.missing_asof == "request_info":
            return out("REQUEST_INFO", "asof_missing", account_id=acct["id"], instrument_id=inst["id"])
        as_of, assumed = q.request_date, True
    pos = s.get_position(acct["id"], inst["id"], as_of)
    if pos is None or pos["settled"] == 0:
        return out("NOT_HELD", "not_held", account_id=acct["id"], instrument_id=inst["id"],
                   as_of=as_of, as_of_assumed=assumed)
    common = dict(account_id=acct["id"], instrument_id=inst["id"], as_of=as_of, as_of_assumed=assumed,
                  settled=pos["settled"])
    if q.stated_qty is not None:
        basis = pos["settled"] + (pos["pending"] if P.qty_basis == "total" else 0)
        if basis == 0 or abs(q.stated_qty - basis) / basis > P.tol + 1e-12:
            return out("ESCALATE", "qty_mismatch", **common)
    if P.big_escalate and pos["settled"] > P.big_escalate:
        return out("ESCALATE", "large_position", **common)
    if pos["pending"] > P.pending_min:
        return out("CONFIRMED", "confirm_with_pending", pending=pos["pending"],
                   pending_date=pos["pending_date"], **common)
    return out("CONFIRMED", "confirm", **common)


# Operator-facing reasons: what an operator would say, deliberately without thresholds.
RULE_REASONS = {
    "auth_level": "This person isn't authorized to receive confirmations; we ask for authorization first.",
    "external_domain": "That sender isn't on the client's domain, so we treat them as unauthorized.",
    "not_own_account": "They're asking about an account that isn't theirs; needs authorization.",
    "account_unresolved": "We can't tell which account they mean, so we ask them to clarify.",
    "instrument_missing": "They didn't say which security; we need to ask.",
    "instrument_unresolved": "The security reference is unclear; we need to ask.",
    "asof_missing": "No as-of date, so we go back and ask for one.",
    "not_held": "The account doesn't hold that security as of that date.",
    "qty_mismatch": "Their number doesn't match ours closely enough; that goes to escalation.",
    "large_position": "Positions that size always go to escalation before we confirm.",
    "confirm_with_pending": "Fine to confirm, but the pending amount and its settlement date need to be in there.",
    "confirm": "Fine to confirm with the settled position.",
}
