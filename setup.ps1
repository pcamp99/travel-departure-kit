# setup.ps1 - Travel Departure Kit, one command install for Windows.
#
# Replaces: delete the old folder, unzip, work out which nested folder is the
# real one, install dependencies, copy the profile, then remember the long
# test command. All of which went wrong at least once by hand.
#
# Run it with:
#     powershell -ExecutionPolicy Bypass -File "$HOME\Downloads\setup.ps1"

$ErrorActionPreference = "Stop"
$Target = "C:\travel-departure-kit"

function Say($msg)  { Write-Host "  $msg" -ForegroundColor Cyan }
function Good($msg) { Write-Host "  $msg" -ForegroundColor Green }
function Bad($msg)  { Write-Host "  $msg" -ForegroundColor Red }

Write-Host ""
Write-Host "Travel Departure Kit setup" -ForegroundColor White
Write-Host "==========================" -ForegroundColor White
Write-Host ""

# --- Find the newest matching zip -------------------------------------------
# Windows never overwrites a download, it appends (1), (2) and so on. That is
# how a stale copy got installed last time, so always take the newest.
$zip = Get-ChildItem "$HOME\Downloads\travel-departure-kit*.zip" -ErrorAction SilentlyContinue |
       Sort-Object LastWriteTime -Descending | Select-Object -First 1

if (-not $zip) {
    Bad "No travel-departure-kit zip found in $HOME\Downloads"
    Bad "Download it from the chat first, then run this again."
    exit 1
}

$others = @(Get-ChildItem "$HOME\Downloads\travel-departure-kit*.zip").Count
Say "Using: $($zip.Name)  [$($zip.LastWriteTime.ToString('MMM d, h:mm tt'))]"
if ($others -gt 1) {
    Say "($others copies in Downloads; taking the newest. Tidy the rest later.)"
}

# --- Step out of the target folder before deleting it ------------------------
# You cannot delete the directory you are standing in, which is exactly what
# happened last time.
Set-Location "C:\"

if (Test-Path $Target) {
    Say "Removing the previous install..."
    try {
        Remove-Item $Target -Recurse -Force
    } catch {
        Bad "Could not delete $Target - close any File Explorer windows"
        Bad "showing that folder, then run this again."
        exit 1
    }
}

# --- Extract, then flatten if the zip nested a folder ------------------------
$temp = Join-Path $env:TEMP "tdk-extract-$(Get-Random)"
Say "Extracting..."
Expand-Archive -Path $zip.FullName -DestinationPath $temp -Force

$root = Get-ChildItem $temp -Recurse -Filter "plan_departure.py" |
        Select-Object -First 1
if (-not $root) {
    Bad "That zip does not contain plan_departure.py. Wrong file?"
    Remove-Item $temp -Recurse -Force -ErrorAction SilentlyContinue
    exit 1
}

Move-Item $root.DirectoryName $Target
Remove-Item $temp -Recurse -Force -ErrorAction SilentlyContinue
Good "Installed to $Target"

Set-Location $Target

# --- Python ------------------------------------------------------------------
try {
    $pyver = (python --version 2>&1 | Out-String).Trim()
} catch {
    Bad "Python is not on PATH. Install from python.org and tick"
    Bad "'Add python.exe to PATH' on the first installer screen."
    exit 1
}
Say "$pyver"

# tzdata matters more than it looks: Windows ships no time zone database, and
# every calculation in this kit is time zone arithmetic.
Say "Installing dependencies..."
python -m pip install --quiet --disable-pip-version-check PyYAML tzdata
if ($LASTEXITCODE -ne 0) { Bad "pip install failed"; exit 1 }
Good "PyYAML and tzdata ready"

# --- Personal profile, never overwritten -------------------------------------
if (Test-Path "config\profile.yaml") {
    Say "Keeping your existing config\profile.yaml"
} else {
    Copy-Item "config\profile.example.yaml" "config\profile.yaml"
    Good "Created config\profile.yaml"
}

# --- Prove it works ----------------------------------------------------------
Write-Host ""
Write-Host "Running the San Diego test..." -ForegroundColor White
Write-Host ""

python plan_departure.py --airport SAN --depart 2026-10-17T07:00 `
  --from "1515 Hotel Cir S, San Diego, CA 92108" `
  --from-latlon 32.758335,-117.176866 `
  --drive auto --find-fuel

Write-Host ""
Write-Host "==========================" -ForegroundColor White
Write-Host "What good looks like:" -ForegroundColor White
Say "a timeline starting around 04:55 or 05:00"
Say "a fuel stop with real coordinates, not a bare brand name"
Say "reasons that read 'on the way' rather than '0 min off route'"
Say "'Binding constraint: the 23 minute shuttle transfer at SAN'"
Write-Host ""
Write-Host "Next, in this window, run:" -ForegroundColor White
Say "cd $Target"
Say "(this script ran in its own process, so your prompt did not move)"
Write-Host ""
