#!/usr/bin/env python3
"""
Swarthmore College Events -> Google Calendar (.ics) Scraper
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from html import unescape
from textwrap import dedent
import requests
import pytz

GRAPHQL_URL = "https://dash.swarthmore.edu/graphql"
GRAPHQL_QUERY = dedent("""\
    query onLoad($currentOnly: Boolean, $days: Int) {
      result: swatcentralfeed(currentOnly: $currentOnly, days: $days) {
        id
        subscribeKey
        data {
          title
          id
          url
          eventactionurl
          description
          startdate
          enddate
          allday
          eventtype
          formatteddate
          location
          organization
          __typename
        }
        __typename
      }
    }
""")
EASTERN = pytz.timezone("America/New_York")
CALENDAR_NAME = "Swarthmore College Events"
CALENDAR_DESCRIPTION = "Community calendar of events at Swarthmore College, sourced from The Dash (dash.swarthmore.edu)."

def fetch_events(days=30):
    payload = {"query": GRAPHQL_QUERY, "operationName": "onLoad", "variables": {"currentOnly": True, "days": days}}
    headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "SwarthmoreCommunityCalendar/1.0"}
    resp = requests.post(GRAPHQL_URL, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    events = data.get("data", {}).get("result", {}).get("data", [])
    if not events:
        print("Warning: No events returned from the API.", file=sys.stderr)
    return events

def parse_datetime(dt_string):
    if not dt_string:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(dt_string, fmt)
            if dt.tzinfo is None:
                dt = EASTERN.localize(dt)
            return dt
        except ValueError:
            continue
    print(f"Warning: Could not parse datetime: {dt_string!r}", file=sys.stderr)
    return None

def format_ics_datetime(dt):
    utc_dt = dt.astimezone(timezone.utc)
    return utc_dt.strftime("%Y%m%dT%H%M%SZ")

def format_ics_date(dt):
    return dt.strftime("%Y%m%d")

def escape_ics_text(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = text.replace("\\", "\\\\")
    text = text.replace(";", "\\;")
    text = text.replace(",", "\\,")
    text = text.replace("\n", "\\n")
    return text

def fold_line(line):
    if len(line.encode("utf-8")) <= 75:
        return line
    result = []
    current = ""
    for char in line:
        test = current + char
        if len(test.encode("utf-8")) > 75:
            result.append(current)
            current = " " + char
        else:
            current = test
    if current:
        result.append(current)
    return "\r\n".join(result)

def generate_uid(event):
    event_id = str(event.get("id", ""))
    hash_val = hashlib.md5(event_id.encode()).hexdigest()[:16]
    return f"{hash_val}@swarthmore-dash-calendar"

def event_to_vevent(event):
    title = escape_ics_text(event.get("title", "Untitled Event"))
    description_parts = []
    if event.get("organization"):
        description_parts.append(f"Organized by: {event['organization']}")
    if event.get("eventtype"):
        description_parts.append(f"Category: {event['eventtype']}")
    if event.get("description"):
        description_parts.append(event["description"])
    if event.get("url"):
        description_parts.append(f"Details: {event['url']}")
    description = escape_ics_text("\\n".join(description_parts))
    location = escape_ics_text(event.get("location", ""))
    url = event.get("url") or event.get("eventactionurl") or ""
    uid = generate_uid(event)
    is_allday = event.get("allday", False)
    start_dt = parse_datetime(event.get("startdate"))
    end_dt = parse_datetime(event.get("enddate"))
    if not start_dt:
        return ""
    lines = ["BEGIN:VEVENT", fold_line(f"UID:{uid}"), fold_line(f"DTSTAMP:{format_ics_datetime(datetime.now(timezone.utc))}")]
    if is_allday:
        lines.append(fold_line(f"DTSTART;VALUE=DATE:{format_ics_date(start_dt)}"))
        if end_dt:
            end_exclusive = end_dt + timedelta(days=1)
            lines.append(fold_line(f"DTEND;VALUE=DATE:{format_ics_date(end_exclusive)}"))
    else:
        lines.append(fold_line(f"DTSTART:{format_ics_datetime(start_dt)}"))
        if end_dt:
            lines.append(fold_line(f"DTEND:{format_ics_datetime(end_dt)}"))
    lines.append(fold_line(f"SUMMARY:{title}"))
    if description:
        lines.append(fold_line(f"DESCRIPTION:{description}"))
    if location:
        lines.append(fold_line(f"LOCATION:{location}"))
    if url:
        lines.append(fold_line(f"URL:{url}"))
    if event.get("eventtype"):
        lines.append(fold_line(f"CATEGORIES:{escape_ics_text(event['eventtype'])}"))
    lines.append("END:VEVENT")
    return "\r\n".join(lines)

def generate_ics(events):
    vevents = [event_to_vevent(e) for e in events if event_to_vevent(e)]
    calendar_lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Swarthmore Community//Dash Events Scraper//EN",
        f"X-WR-CALNAME:{CALENDAR_NAME}", fold_line(f"X-WR-CALDESC:{CALENDAR_DESCRIPTION}"),
        "X-WR-TIMEZONE:America/New_York", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        "BEGIN:VTIMEZONE", "TZID:America/New_York",
        "BEGIN:DAYLIGHT", "TZOFFSETFROM:-0500", "TZOFFSETTO:-0400", "TZNAME:EDT",
        "DTSTART:19700308T020000", "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU", "END:DAYLIGHT",
        "BEGIN:STANDARD", "TZOFFSETFROM:-0400", "TZOFFSETTO:-0500", "TZNAME:EST",
        "DTSTART:19701101T020000", "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU", "END:STANDARD",
        "END:VTIMEZONE",
    ]
    calendar_lines.extend(vevents)
    calendar_lines.append("END:VCALENDAR")
    return "\r\n".join(calendar_lines)

def main():
    parser = argparse.ArgumentParser(description="Scrape Swarthmore Dash events and generate an .ics calendar file.")
    parser.add_argument("--days", type=int, default=30, help="Number of days of events to fetch (default: 30)")
    parser.add_argument("--output", type=str, default="swarthmore_events.ics", help="Output .ics file path")
    parser.add_argument("--json", action="store_true", help="Also save raw JSON data")
    args = parser.parse_args()
    print(f"Fetching Swarthmore events (next {args.days} days)...")
    events = fetch_events(days=args.days)
    print(f"Found {len(events)} events")
    if args.json:
        json_path = args.output.replace(".ics", ".json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(events, f, indent=2, ensure_ascii=False)
        print(f"Raw JSON saved to: {json_path}")
    ics_content = generate_ics(events)
    with open(args.output, "w", encoding="utf-8", newline="") as f:
        f.write(ics_content)
    print(f"Calendar saved to: {args.output}")
    allday = sum(1 for e in events if e.get("allday"))
    timed = len(events) - allday
    print(f"\nSummary: {allday} all-day events, {timed} timed events")
    print("\nSample events:")
    for event in events[:5]:
        title = event.get("title", "?")
        date = event.get("formatteddate", "?")
        loc = event.get("location", "")
        loc_str = f" @ {loc}" if loc else ""
        print(f"  - {title} -- {date}{loc_str}")

if __name__ == "__main__":
    main()
