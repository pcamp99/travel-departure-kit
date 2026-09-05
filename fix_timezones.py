#!/usr/bin/env python3
"""Scan your calendar for events stamped with the wrong time zone.

Reports by default. Only rewrites with --apply, and only events whose creator
you have listed as a trusted local time source in your profile. Everything
else is reported for you to judge.

  python3 fix_timezones.py --days 120
  python3 fix_timezones.py --days 120 --apply
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

from departure_kit.profile import ConfigError, load_profile
from departure_kit.tzfix import scan


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--days", type=int, default=90, help="How far ahead to look")
    p.add_argument("--apply", action="store_true",
                   help="Actually rewrite the events marked FIX")
    p.add_argument("--calendar", default="primary")
    args = p.parse_args(argv)

    try:
        profile = load_profile()
    except ConfigError as exc:
        print(f"Config problem: {exc}", file=sys.stderr)
        return 2

    from departure_kit.gcal import list_events, service, set_event_zone

    svc = service()
    now = datetime.now(timezone.utc)
    events = list_events(svc, now, now + timedelta(days=args.days), args.calendar)

    findings = scan(
        events,
        home_zone=profile.home_timezone,
        trusted_creators=profile.trusted_creators,
        skip_patterns=profile.skip_patterns,
        overrides=profile.city_overrides,
    )

    if not findings:
        print(f"Checked {len(events)} events. Nothing looks wrong.")
        return 0

    fixable = [f for f in findings if f.action == "fix"]
    reportable = [f for f in findings if f.action == "report"]

    if reportable:
        print(f"\nFor you to judge ({len(reportable)}):")
        for f in reportable:
            print(f"  {f.summary}")
            print(f"    {f.location}")
            print(f"    {f.reason}")

    if fixable:
        print(f"\nSafe to correct ({len(fixable)}):")
        for f in fixable:
            print(f"  {f.describe()}")

    if not args.apply:
        if fixable:
            print("\nDry run. Re run with --apply to make these changes.")
        return 0

    if not fixable:
        print("\nNothing to apply.")
        return 0

    for f in fixable:
        start = f.corrected_start
        # Preserve the original duration rather than assuming an hour.
        original = next(e for e in events if e.get("id") == f.event_id)
        o_start = datetime.fromisoformat(original["start"]["dateTime"])
        o_end = datetime.fromisoformat(original["end"]["dateTime"])
        end = start + (o_end - o_start)
        set_event_zone(
            svc, f.event_id,
            start.strftime("%Y-%m-%dT%H:%M:%S"),
            end.strftime("%Y-%m-%dT%H:%M:%S"),
            f.location_zone, args.calendar,
        )
        print(f"  corrected: {f.summary}")

    print(f"\nCorrected {len(fixable)}. No invitations were sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
