@echo off
REM Windows Task Scheduler entry point. See SCHEDULING.md.
REM cd /d "%~dp0" makes the working directory this repo regardless of where
REM the scheduler invoked it from, which is what lets config/ be found.
REM watch.log holds trip details: addresses, flight numbers, confirmations.
REM It is gitignored. If you would rather it not sit in the repo at all,
REM change the redirect to a path outside it.
cd /d "%~dp0"
python watch_calendar.py --apply >> watch.log 2>&1
