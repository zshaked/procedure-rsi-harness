"""Adapter: cases from a firm export. Documents the schema; nothing firm-specific here.

Expected input: one JSONL row per historical case, oldest first. Field names
are the contract; the export job maps the firm's own column names onto them.

    {
      "case_id":   "<stable id>",
      "t":         <int, time order within the mailbox>,
      "email":     {"sender": "...", "sent": "YYYY-MM-DD", "subject": "...", "body": "...",
                    "mentions": {"account_text": "...|null", "instrument_text": "...|null"}},
      "reply_text": "<the operator's outbound reply, verbatim>",
      "snapshot":  { ...recorded tool results as of the reply time, see RecordedSnapshot... }
    }

`snapshot` is the point-in-time view of the SOR at `t_reply`. E1 checks that it
is point-in-time rather than current-state; if that check fails, nothing
downstream is valid (DESIGN.md §11, E1). The recorded form is a dict of the
closed tool vocabulary's *answers*, captured when the case was exported:

    {
      "t_reply": "YYYY-MM-DD",
      "accounts":     {"<account_id>": {"id", "name", "short_name", "sub_accounts": [...]}, ...},
      "profiles":     {"<account_id>": {"domains": [...], "legal_hold": bool, "no_email_confirm": bool}},
      "contacts":     {"<email>": {"contact_id", "email", "name"}},
      "entitlements": {"<contact_id>": [{"account_id", "level", "expires": "YYYY-MM-DD"}]},
      "instruments":  {"<instrument_id>": {"id", "ticker", "old_ticker", "name"}},
      "positions":    {"<account_id>|<instrument_id>": {"<as_of>": {"settled": int, "pending": int, "pending_date": "..|null"}}},
      "business_days": {"YYYY-MM-DD": bool, ...}
    }

Only the entities the case touches need to be present. A method asked about an
entity the export did not record raises `MissingSnapshotData` rather than
guessing; the export job then widens what it captures. Positions are recorded
per as-of date because the firm SOR is not replayable the way the synthetic
World is — the export must capture the figures for the dates the reply could
be about (the as-of the reply states, and the email's sent date).
"""
from __future__ import annotations

import json
from pathlib import Path

from ..schema import Case, Email


class MissingSnapshotData(KeyError):
    pass


class RecordedSnapshot:
    def __init__(self, rec: dict):
        self._r = rec
        self.t_reply = rec["t_reply"]

    def _need(self, section: str, key: str):
        try:
            return self._r[section][key]
        except KeyError as e:
            raise MissingSnapshotData(f"snapshot has no {section}[{key!r}]") from e

    def resolve_account(self, ref: str) -> list[str]:
        r = ref.strip().lower()
        hits = [a["id"] for a in self._r.get("accounts", {}).values()
                if r == a["id"].lower() or r in (s.lower() for s in a.get("sub_accounts", []))
                or r == a["name"].lower() or r == a.get("short_name", "").lower()]
        if not hits:
            hits = [a["id"] for a in self._r.get("accounts", {}).values() if a["name"].lower().startswith(r)]
        return sorted(set(hits))

    def resolve_instrument(self, ref: str) -> list[str]:
        r = ref.strip().lower()
        return sorted({i["id"] for i in self._r.get("instruments", {}).values()
                       if r in (i["ticker"].lower(), (i.get("old_ticker") or "").lower(), i["name"].lower(), i["id"].lower())})

    def instrument(self, instrument_id: str) -> dict | None:
        return self._r.get("instruments", {}).get(instrument_id)

    def contact(self, email: str) -> dict | None:
        return self._r.get("contacts", {}).get(email)

    def live_entitled_accounts(self, contact_id: str, on: str) -> list[str]:
        return sorted({e["account_id"] for e in self._need("entitlements", contact_id) if e["expires"] >= on})

    def entitlement(self, contact_id: str, account_id: str, on: str) -> int:
        for e in self._need("entitlements", contact_id):
            if e["account_id"] == account_id and e["expires"] >= on:
                return e["level"]
        return 0

    def profile(self, account_id: str) -> dict:
        return self._need("profiles", account_id)

    def _pos(self, account_id: str, instrument_id: str, as_of: str) -> dict:
        key = f"{account_id}|{instrument_id}"
        by_date = self._need("positions", key)
        if as_of not in by_date:
            raise MissingSnapshotData(f"snapshot has no position for {key} as of {as_of}")
        return by_date[as_of]

    def settled(self, account_id: str, instrument_id: str, as_of: str) -> int:
        return int(self._pos(account_id, instrument_id, as_of)["settled"])

    def pending(self, account_id: str, instrument_id: str, as_of: str) -> tuple[int, str | None]:
        p = self._pos(account_id, instrument_id, as_of)
        return int(p.get("pending") or 0), p.get("pending_date")

    def is_business_day(self, date: str) -> bool:
        return bool(self._need("business_days", date))


def load_cases(path: str | Path) -> list[Case]:
    cases = []
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        e = row["email"]
        cases.append(Case(
            case_id=row["case_id"], t=int(row["t"]),
            email=Email(sender=e["sender"], sent=e["sent"], subject=e.get("subject", ""), body=e["body"],
                        mentions=e.get("mentions", {})),
            reply_text=row["reply_text"], snapshot=RecordedSnapshot(row["snapshot"]),
        ))
    return cases
