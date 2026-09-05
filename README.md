# Travel Departure Kit

Two small tools for people who fly a lot for work, rent a car at the other
end, and have to give it back at six in the morning.

It answers the question you are actually asking at 4 am: where do I stop for
fuel, and when do I have to leave?

```
$ python plan_departure.py --airport SAN --depart 2026-10-17T07:00 \
    --from "1515 Hotel Cir S, San Diego, CA 92108" \
    --from-latlon 32.758335,-117.176866 --drive auto --find-fuel

Departure plan, all times San Diego International local (PDT)

  04:55  Leave hotel
  04:59  Fuel stop
  05:17  Arrive SAN rental return
         3355 Admiral Boland Way, San Diego, CA 92101
  05:27  Keys handed over
  05:27  Board the shuttle to the terminal
         8 minute ride, up to 15 minutes waiting
  05:50  At the terminal
  05:55  Through security
  06:00  Airside, buffer starts
  07:00  Scheduled departure

Binding constraint: the 23 minute shuttle transfer at SAN, not security.

Fuel stop: ARCO, 3860 Old Town Ave
  on the way, confirmed open at that hour, large brand, quick in and
  out, 2 km from the return
```

The same person, same flight time, out of Charlotte instead: leave at 05:20,
not 04:55. Same traveller, same habits, different airport. That gap is the
rental car return, and no rule of thumb accounts for it.

**Two things it does that nothing else does.** It picks the actual station,
by name, on your route, open at that hour. And it carries per airport
knowledge of what the rental return really costs you, because at Phoenix,
San Diego, Houston and plenty of others the return is miles from the terminal
and you have to ride something to get back.

**`fix_timezones.py`** is the second tool. It finds calendar appointments
stamped with the wrong time zone, which is a quieter and more expensive
problem than it sounds.

**`watch_calendar.py`** is the one that makes it run by itself. It looks at
your calendar for a departure in the next day, finds where you are staying,
and writes the plan into your calendar as a reminder with the navigation links
in it. Point your operating system's scheduler at it once and you stop
thinking about any of this. See [SCHEDULING.md](SCHEDULING.md) for Windows
Task Scheduler, launchd and cron; no extra software, and Home Assistant is a
footnote rather than a requirement.

Writing the plan the day before rather than at booking time is deliberate. A
plan generated weeks ahead is computed from a calendar that will have changed
by the morning it matters.

No paid API, no account, no credit card. It runs on OpenStreetMap.

---

## The problems these solve

**Nobody tells you where to stop for fuel.** Corporate travel policy generally
forbids the prepaid fuel option, and for good reason: it is priced above pump
rate and is non refundable. So a business renter on full to full has to stop,
every single trip, usually before dawn, on roads they do not know. The cost is
not money, it is driving around looking for a station with a flight to catch.
No departure app solves this because they all model the fuel stop as a generic
buffer rather than a place.

This ranks on time and certainty, never on price: on the route, open at that
hour, big enough to get in and out of, close enough to the return that the
gauge still reads full. It returns **one** station and one fallback, because
two options at four in the morning is still a decision.

**Everyone assumes you leave from the hotel.** Sometimes you leave from your
last appointment. The obvious rule, early flight means hotel and afternoon
flight means appointment, is wrong in both directions: a 9 am flight with a
6 am breakfast meeting starts at the meeting, and a 4 pm flight whose last call
ended at 9 am starts at the hotel because you went back for your bag.

`--calendar-origin` looks at what you were doing immediately before you have to
leave, rather than at the clock. The genuinely ambiguous middle depends on
whether you checked out with the bag in the car, which no calendar records, so
it picks the safer option, tells you it picked, and names the other one.
Override with `--origin-from hotel` or `--origin-from appointment`.

`--drive auto` looks the drive time up from OSRM so the inferred origin changes
the arithmetic too, not just the links. `--drive 34` still works and stays the
documented fallback, because all three OpenStreetMap services here are run by
volunteers and any of them can be down on the morning you need it.

One case worth knowing about, because it looks like a bug and is not. If
leaving from your last appointment would mean departing before that appointment
ends, the tool says so rather than picking an origin. That is a schedule
conflict, not an ambiguity, and no amount of choosing between two origins fixes
it.

**Nobody budgets the rental return.** At Charlotte you park and walk. At
Phoenix, San Diego, Houston, Fort Lauderdale and plenty of others, the rental
return is miles from the terminal and you have to ride something. That
transfer routinely costs more than the entire security queue, and it does not
appear in any "arrive two hours early" rule of thumb.

The consequence is counterintuitive and worth stating plainly: if you have
PreCheck and CLEAR, your security speed does **not** set your departure time
at those airports. The transfer does. A rule that works at your home airport
quietly fails everywhere else. The tool makes each segment visible so you can
see which one is actually binding, and it tells you which one that is.

**Calendars lie about time zones.** Google Calendar stores an absolute instant
plus a zone label. Create an event on a device sitting in one zone for a place
in another, and the time you typed is interpreted in *your* zone. The event is
then permanently wrong. It does not fix itself when you travel: your phone
shows a different number, but the underlying moment never moves. A noon
appointment typed in Charlotte for a Phoenix office is 9 am Phoenix, forever,
and you find out in the parking lot.

---

## Prior art

**On prior art, honestly.** Several apps already tell you when to leave for a
flight, and some do it better than this: WhenToLeave and DepartTime both pull
live traffic and live TSA wait times, which this cannot. DepartTime even models
offsite rental depots and shuttles. If all you want is a leave time, use one of
those.

What they do not do is pick the station. That is the gap this fills, and it is
the part that actually costs a business traveller something.

---

## What it looks like

```
$ python3 plan_departure.py --airport SAN --depart 2026-10-17T07:00 \
    --from "1515 Hotel Cir S, San Diego, CA 92108" \
    --from-latlon 32.758335,-117.176866 --drive 11 --find-fuel

Departure plan, all times San Diego International local (PDT)

  04:55  Leave hotel
  04:59  Fuel stop
  05:17  Arrive SAN rental return
         3355 Admiral Boland Way, San Diego, CA 92101
  05:27  Keys handed over
  05:27  Board the shuttle to the terminal
         8 minute ride, up to 15 minutes waiting
  05:50  At the terminal
  05:55  Through security
  06:00  Airside, buffer starts
  07:00  Scheduled departure

Total elapsed: 125 minutes.
Binding constraint: the 23 minute shuttle transfer at SAN, not security.

Fuel stop: ARCO, 3860 Old Town Ave
  2 min off route, confirmed open at that hour, large brand, quick in and
  out, 2 km from the return
```

The same person, same flight time, out of Charlotte instead: leave at 05:20.
Ninety-five minutes rather than a hundred and twenty-five. Same traveller,
same habits, different airport.

---

## Setup

```bash
git clone https://github.com/YOURNAME/travel-departure-kit.git
cd travel-departure-kit
```

**Windows.** After cloning:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

On Windows, `pip install -r requirements.txt` is not optional even though the
kit has almost no dependencies: Windows ships no time zone database, and every
calculation here is time zone arithmetic. Skip it and you get a config error
naming a zone that is actually correct. `setup.ps1` installs the requirements,
creates your profile from the example, and runs the tests.

**macOS and Linux:**

```bash
pip install -r requirements.txt
cp config/profile.example.yaml config/profile.yaml
python -m pytest tests/ -q
```

Then edit `config/profile.yaml`. The two numbers that matter most are
`security_minutes` and `airside_buffer_minutes`. Be honest about the first and
generous with the second.

`plan_departure.py` works immediately. `fix_timezones.py` needs Google
Calendar access; see [SETUP-GOOGLE.md](SETUP-GOOGLE.md).

---

## The part no API knows

`airports.yaml` carries an `avoid_fuel` list per airport. OpenStreetMap knows
where the stations are; it does not know that the Shell on E Buckeye Road is
the last stop before the Phoenix rental return and prices accordingly, with a
thousand reviews saying so. That is human knowledge, it is identical for every
traveller, and it belongs in a shared file.

If a stop burns you, add a line. That is the whole contribution model.

## Adding your airports

`config/airports.yaml` ships with CLT, PHX, SAN, IAH, FLL, MSY and BWI. The
tool refuses to plan for an airport it does not know rather than guessing a
transfer time, because a guess produces a plan that looks right and is thirty
minutes wrong.

Adding one is a few lines. **A pull request with a new airport is the single
most useful thing you can contribute.** The transfer times are the hard part
to find and they are the same for everyone.

---

## The time zone corrector, and why it is careful

An event stamped Eastern with a Phoenix address has two possible histories.
Either a person typed the local time and the zone came from their device, or a
booking system wrote a correct absolute instant. The stored data is identical
in both cases and the right action is opposite. Guessing moves a real customer
appointment by hours.

So the tool does not guess. It resolves the location's zone, compares, and:

- If the event was created by an address you listed in
  `trusted_local_time_creators`, the intent is unambiguous and it can correct
  it automatically. That list is empty by default.
- Otherwise it reports and leaves it alone.
- If the location is in a state that spans two zones, it refuses to resolve it
  and tells you, rather than picking one.
- Video calls are skipped. A Teams call with an office in another state really
  is in your zone.

It is a dry run unless you pass `--apply`, and it never sends invitations when
it corrects something.

---

## Privacy

`config/profile.yaml`, `credentials.json` and `token.json` are gitignored.
Keep it that way. `token.json` in particular is a live credential for your
calendar.

Before you push anything: this repo is designed so that everything personal
lives in ignored files and everything shareable lives in tracked ones. If you
find yourself adding a hotel confirmation number or a home address to a
tracked file, that is the design telling you the value belongs in
`profile.yaml` instead.

---

## Tests

```bash
python3 -m pytest tests/ -q
```

75 tests, no network, no credentials. The fuel ranking is tested against a
recorded Overpass response in `tests/fixtures/`, so the selection logic is
covered offline. The three live HTTP calls, to Overpass for stations, Nominatim for geocoding
and OSRM for drive times, are what the suite does not exercise; that is what
your first real run verifies.

Routing by OSRM. Geocoding by Nominatim. Map data from OpenStreetMap
contributors, ODbL. All three are volunteer run: one query per trip is well
within their terms, a loop is not. They cover the timeline arithmetic, the
zone resolution refusals, and the link building. Two real bugs were caught by
this suite while it was being written: a sign error that treated the bag drop
counter as being past security, and a precedence bug that reported the wrong
binding constraint when a checked bag was involved.

---

## License

MIT. See [LICENSE](LICENSE). Use it, change it, ship it. The one thing worth
sending back is airport data: if you time a rental return the tool doesn't
know about yet, a line in `config/airports.yaml` helps everyone.
