# Making it run by itself

`watch_calendar.py` checks your calendar for a departure in the next 24 hours
and writes the plan. Something has to run it once a day. That something is
already on your computer.

Pick your platform below. Each is a five minute job, done once.

> Run it by hand first, without `--apply`, and confirm it says something
> sensible. A scheduled task that fails silently is worse than no task, and
> the commonest cause is a path that is right in your terminal and wrong in
> the scheduler's environment.

```
python3 watch_calendar.py
```

Two things to know before scheduling. It reports without changing anything
unless you pass `--apply`. And it is safe to run repeatedly: it records a
marker on every plan it writes, so a second run on the same flight does
nothing rather than creating a duplicate.

---

## Windows: Task Scheduler

Create `run_watch.bat` in the repo folder:

```bat
@echo off
cd /d "%~dp0"
python watch_calendar.py --apply >> watch.log 2>&1
```

Then:

1. Press the Windows key, type **Task Scheduler**, open it.
2. **Create Basic Task**, name it "Travel departure plan".
3. Trigger: **Daily**, and pick a time you are usually awake and online.
   Early evening works well: a plan written at 6 pm is ready for a 5 am start
   the next morning.
4. Action: **Start a program**. Program: the full path to `run_watch.bat`.
5. Finish, then open the task's **Properties** and tick **Run task as soon as
   possible after a scheduled start is missed**, so a laptop that was closed
   at 6 pm still catches up.

**Done when:** right click the task, choose **Run**, and `watch.log` appears
in the repo folder with output in it.

> The commonest failure here is `python` not being found, because Task
> Scheduler does not always inherit your PATH. If `watch.log` shows that, put
> the full interpreter path in the batch file instead: run `where python` in
> PowerShell and paste what it prints.

---

## macOS: launchd

Create `~/Library/LaunchAgents/com.travelkit.watch.plist`, replacing both
paths with your own:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.travelkit.watch</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/Users/YOU/travel-departure-kit/watch_calendar.py</string>
    <string>--apply</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/Users/YOU/travel-departure-kit</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>18</integer>
    <key>Minute</key><integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>/tmp/travelkit.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/travelkit.log</string>
</dict>
</plist>
```

Load it:

```bash
launchctl load ~/Library/LaunchAgents/com.travelkit.watch.plist
```

**Done when:** `launchctl list | grep travelkit` shows the job, and after the
next scheduled run `/tmp/travelkit.log` has content.

> launchd will not run a job while the machine is asleep, but it does run it
> on wake if the time passed. A desktop is more reliable than a laptop here.

---

## Linux: cron

```bash
crontab -e
```

Add one line, with your own path:

```
0 18 * * * cd /home/you/travel-departure-kit && /usr/bin/python3 watch_calendar.py --apply >> watch.log 2>&1
```

**Done when:** `crontab -l` shows the line, and `watch.log` fills after the
next run.

> cron runs with a minimal environment and almost no PATH. Use absolute paths
> for the interpreter, and `cd` into the repo first so the config files are
> found.

---

## Home Assistant, if you happen to run it

Entirely optional, and not recommended over the above unless you already have
HA and want the plan to trigger something else in the house. HA cannot run
the Python itself unless the repo lives on the HA machine; more usually it
calls out to whichever computer has it, via a `shell_command` or an SSH
integration.

```yaml
shell_command:
  travel_plan: "cd /config/travel-departure-kit && python3 watch_calendar.py --apply"

automation:
  - alias: Write the departure plan
    trigger:
      - platform: time
        at: "18:00:00"
    action:
      - service: shell_command.travel_plan
```

The advantage is not scheduling, which cron does perfectly well. It is that a
departure becomes an event the rest of your house can react to.

---

## The one thing that will catch you out

The first run needs a browser, because Google's consent flow is interactive.
A scheduler has no browser. So run it by hand once with `--apply` before
scheduling anything, get through the consent screen, and let `token.json` be
written. After that the scheduled runs refresh the token by themselves.

If the token ever goes stale, the scheduled run fails quietly and your log
says so. This is the argument for keeping `watch.log` rather than discarding
the output.

---

## What the log contains

Every example on this page redirects output to a log — `watch.log` on Windows,
whatever path you chose in the launchd plist or the cron line on macOS and
Linux. That log accumulates the contents of each run, and those contents are
your trip: hotel addresses, flight numbers, confirmation codes, one entry per
day for as long as the job runs.

It is gitignored, so `git add -A` will not sweep it into a commit. That is a
safety net rather than a reason to relax. If you would rather it not live in
the repo at all, redirect it somewhere outside the checkout — any of the three
examples above takes a different path without further changes.
