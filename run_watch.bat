@echo off
REM Windows Task Scheduler entry point. See SCHEDULING.md.
REM cd /d "%~dp0" makes the working directory this repo regardless of where
REM the scheduler invoked it from, which is what lets config/ be found.
cd /d "%~dp0"
python watch_calendar.py --apply >> watch.log 2>&1
