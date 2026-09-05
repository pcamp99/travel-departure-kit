# setup.ps1 - Travel Departure Kit, first run setup on Windows.
#
# Run this from inside a cloned repo:
#
#     git clone https://github.com/YOURNAME/travel-departure-kit.git
#     cd travel-departure-kit
#     powershell -ExecutionPolicy Bypass -File .\setup.ps1
#
# It works in place. It does not download anything, does not delete anything,
# and does not care where the repo lives. An earlier version hunted your
# Downloads folder for a zip and recreated a fixed directory, which is a fine
# way to install a snapshot and a terrible way to live alongside a git repo:
# it silently resurrects a second copy that then drifts from the checkout.
#
# What it is actually for is one Windows specific trap. Windows ships no IANA
# time zone database, and every calculation in this kit is time zone
# arithmetic, so a fresh clone fails on the first run with an error that
# blames your config file for a value that is correct. Installing the
# requirements fixes that, and people skip it because the dependency list
# looks trivial.

$ErrorActionPreference = "Stop"
$Repo = $PSScriptRoot

function Say($m)  { Write-Host "  $m" -ForegroundColor Cyan }
function Good($m) { Write-Host "  $m" -ForegroundColor Green }
function Bad($m)  { Write-Host "  $m" -ForegroundColor Red }

Write-Host ""
Write-Host "Travel Departure Kit - first run setup" -ForegroundColor White
Write-Host ""

if (-not (Test-Path (Join-Path $Repo "plan_departure.py"))) {
    Bad "This does not look like the repo. Run it from inside your clone:"
    Bad "    cd path\to\travel-departure-kit"
    Bad "    powershell -ExecutionPolicy Bypass -File .\setup.ps1"
    exit 1
}
Set-Location $Repo
Say "Repo: $Repo"

try {
    Say ((python --version 2>&1 | Out-String).Trim())
} catch {
    Bad "Python is not on PATH. Install from python.org and tick"
    Bad "'Add python.exe to PATH' on the first installer screen."
    exit 1
}

Say "Installing dependencies..."
python -m pip install --quiet --disable-pip-version-check -r requirements.txt
if ($LASTEXITCODE -ne 0) { Bad "pip install failed"; exit 1 }
if (Test-Path "requirements-dev.txt") {
    python -m pip install --quiet --disable-pip-version-check -r requirements-dev.txt
}
Good "Dependencies ready (including tzdata, which Windows needs)"

if (Test-Path "config\profile.yaml") {
    Say "Keeping your existing config\profile.yaml"
} else {
    Copy-Item "config\profile.example.yaml" "config\profile.yaml"
    Good "Created config\profile.yaml - edit it to match how you travel"
}

Write-Host ""
Say "Running the test suite..."
python -m pytest tests\ -q
if ($LASTEXITCODE -ne 0) {
    Bad "Tests failed. That is worth reporting as an issue."
    exit 1
}

Write-Host ""
Good "Ready. Try it:"
Write-Host ""
Write-Host '  python plan_departure.py --airport SAN --depart 2026-10-17T07:00 `' -ForegroundColor Gray
Write-Host '    --from "1515 Hotel Cir S, San Diego, CA 92108" `' -ForegroundColor Gray
Write-Host '    --from-latlon 32.758335,-117.176866 --drive auto --find-fuel' -ForegroundColor Gray
Write-Host ""
