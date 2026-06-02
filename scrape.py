"""Generate an iCalendar feed of EarlyON sessions at the Markham + Thornhill centres.

Source: https://www.missioninc.com/cso/york/en-ca/earlyon/calendar
API:    https://www.missioninc.com/OccmsApi/York/eoprogramschedevents
        (anonymous; no auth needed)

Output: docs/earlyon-markham-thornhill.ics
"""
from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

API = "https://www.missioninc.com/OccmsApi/York"
SOURCE_URL = "https://www.missioninc.com/cso/york/en-ca/earlyon/calendar"
OUT = Path(__file__).parent / "docs" / "earlyon-markham-thornhill.ics"

# How much of a window to publish, relative to "today" at script run time.
LOOKBACK_DAYS = 7
LOOKAHEAD_DAYS = 56  # 8 weeks


@dataclass(frozen=True)
class Centre:
    name: str
    hoid: str          # head-office code, e.g. "EARLY02"
    prov_id: str       # site code, e.g. "EARLY12"
    prov_id_num: int   # numeric site id (for lookups verification)
    address: str       # full street address for LOCATION

CENTRES: list[Centre] = [
    Centre(
        name="EarlyON Markham Centre",
        hoid="EARLY02",
        prov_id="EARLY12",
        prov_id_num=194,
        address="3990 14th Avenue, Markham, ON L3R 0B2",
    ),
    Centre(
        name="EarlyON Thornhill Centre",
        hoid="EARLY03",
        prov_id="EARLY22",
        prov_id_num=200,
        address="7755 Bayview Avenue, Thornhill, ON L3T 4P1",
    ),
]


def verify_centres_against_lookups(client: httpx.Client) -> None:
    """Fail loudly if Mission Inc renames/moves a centre."""
    r = client.get(f"{API}/eoprogramschedevents/lookups", timeout=60)
    r.raise_for_status()
    sites = {s["ProvID"]: s for s in r.json().get("Sites", [])}
    problems = []
    for c in CENTRES:
        s = sites.get(c.prov_id)
        if not s:
            problems.append(f"site {c.prov_id} ({c.name}) not in lookups")
            continue
        if s.get("ProvIDNum") != c.prov_id_num:
            problems.append(
                f"{c.prov_id}: ProvIDNum drifted "
                f"({s.get('ProvIDNum')} vs expected {c.prov_id_num})"
            )
        if s.get("HOID") != c.hoid:
            problems.append(
                f"{c.prov_id}: HOID drifted ({s.get('HOID')} vs expected {c.hoid})"
            )
        if c.name.lower() not in (s.get("Name") or "").lower():
            problems.append(
                f"{c.prov_id}: name '{s.get('Name')}' no longer matches '{c.name}'"
            )
    if problems:
        for p in problems:
            print(f"  ! {p}", file=sys.stderr)
        sys.exit(1)


def fetch_events(client: httpx.Client, start: date, end: date) -> list[dict]:
    """Fetch all events in [start, end] for every distinct HOID, filtered to our sites."""
    target_provids = {c.prov_id for c in CENTRES}
    hoids = sorted({c.hoid for c in CENTRES})
    events: list[dict] = []
    seen_ids: set[str] = set()
    for hoid in hoids:
        r = client.get(
            f"{API}/eoprogramschedevents",
            params={
                "Start": start.isoformat(),
                "End": end.isoformat(),
                "HOID": hoid,
            },
            timeout=60,
        )
        r.raise_for_status()
        for e in r.json():
            if e.get("ProvID") not in target_provids:
                continue
            if e["Id"] in seen_ids:
                continue
            seen_ids.add(e["Id"])
            events.append(e)
    return events


# ---------- ICS rendering (RFC 5545 by hand for full control) ----------

PRODID = "-//earlyon-cal//Markham+Thornhill//EN"

# America/Toronto VTIMEZONE block. Standard IANA → RFC 5545 transitions for
# US/Canada Eastern, valid since 2007. Many calendar clients accept TZID without
# a VTIMEZONE block, but including it is the safe move for Google Calendar.
VTIMEZONE = """BEGIN:VTIMEZONE
TZID:America/Toronto
X-LIC-LOCATION:America/Toronto
BEGIN:DAYLIGHT
TZOFFSETFROM:-0500
TZOFFSETTO:-0400
TZNAME:EDT
DTSTART:19700308T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:-0400
TZOFFSETTO:-0500
TZNAME:EST
DTSTART:19701101T020000
RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU
END:STANDARD
END:VTIMEZONE"""


def fold_line(line: str) -> str:
    """RFC 5545 line folding: 75 octets, continuation begins with a space."""
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line
    out_chunks: list[bytes] = []
    i = 0
    first = True
    while i < len(encoded):
        chunk_size = 75 if first else 74  # one octet reserved for leading space
        end = min(i + chunk_size, len(encoded))
        # don't split a UTF-8 multi-byte sequence
        while end < len(encoded) and (encoded[end] & 0xC0) == 0x80:
            end -= 1
        chunk = encoded[i:end]
        out_chunks.append(chunk if first else b" " + chunk)
        i = end
        first = False
    return b"\r\n".join(out_chunks).decode("utf-8")


def esc(s: str | None) -> str:
    if not s:
        return ""
    return (
        s.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
        .replace("\r", "")
    )


def fmt_local(iso_naive: str) -> str:
    """API gives naive local-time ISO ('2026-06-01T09:00:00'). Convert to ICS local form."""
    dt = datetime.fromisoformat(iso_naive)
    return dt.strftime("%Y%m%dT%H%M%S")


def fmt_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def uid_for(event: dict) -> str:
    base = f"{event['ProvID']}|{event['Id']}"
    h = hashlib.sha1(base.encode()).hexdigest()[:16]
    return f"{h}@earlyon-cal"


def vevent(event: dict, centre: Centre, now_utc: datetime) -> str:
    summary = (event.get("Summary1") or "").strip()
    desc_parts: list[str] = []
    if event.get("Description1"):
        desc_parts.append(event["Description1"].strip())
    if event.get("Comment"):
        desc_parts.append(event["Comment"].strip())
    tags = []
    if event.get("DropIn"):
        tags.append("Drop-in")
    if event.get("IsPreReg"):
        tags.append("Pre-registration required")
    if event.get("IsVirtual"):
        tags.append("Virtual")
    if event.get("Outdoor") and not event.get("Indoor"):
        tags.append("Outdoor")
    if tags:
        desc_parts.append(", ".join(tags))
    desc_parts.append(f"Centre: {centre.name}")
    desc_parts.append(f"Source: {SOURCE_URL}")
    description = "\n\n".join(desc_parts)

    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid_for(event)}",
        f"DTSTAMP:{fmt_utc(now_utc)}",
        f"DTSTART;TZID=America/Toronto:{fmt_local(event['Start'])}",
        f"DTEND;TZID=America/Toronto:{fmt_local(event['End'])}",
        f"SUMMARY:{esc(summary)}",
        f"LOCATION:{esc(centre.address)}",
        f"DESCRIPTION:{esc(description)}",
        f"URL:{SOURCE_URL}",
        "TRANSP:OPAQUE",
        "END:VEVENT",
    ]
    return "\r\n".join(fold_line(ln) for ln in lines)


def build_ics(events: list[dict]) -> str:
    now_utc = datetime.now(timezone.utc)
    centre_by_provid = {c.prov_id: c for c in CENTRES}
    events_sorted = sorted(events, key=lambda e: e["Start"])
    vevents = [vevent(e, centre_by_provid[e["ProvID"]], now_utc) for e in events_sorted]
    header = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:EarlyON — Markham + Thornhill",
        "X-WR-CALDESC:Drop-in & registered programs at EarlyON Markham Centre and EarlyON Thornhill Centre. Auto-refreshed daily.",
        "X-WR-TIMEZONE:America/Toronto",
        VTIMEZONE,
    ]
    body = "\r\n".join(header) + "\r\n" + "\r\n".join(vevents) + "\r\nEND:VCALENDAR\r\n"
    return body


def main() -> int:
    today = date.today()
    start = today - timedelta(days=LOOKBACK_DAYS)
    end = today + timedelta(days=LOOKAHEAD_DAYS)
    print(f"window: {start} → {end}")

    with httpx.Client(headers={"User-Agent": "earlyon-cal/1.0"}) as client:
        verify_centres_against_lookups(client)
        events = fetch_events(client, start, end)

    if not events:
        print("no events returned — refusing to overwrite output", file=sys.stderr)
        return 2

    counts: dict[str, int] = {}
    for e in events:
        counts[e["ProvID"]] = counts.get(e["ProvID"], 0) + 1
    for c in CENTRES:
        print(f"  {c.name}: {counts.get(c.prov_id, 0)} events")

    ics = build_ics(events)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(ics.encode("utf-8"))
    print(f"wrote {OUT} ({len(ics)} bytes, {len(events)} events)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
