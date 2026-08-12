# ==============================================================================
#  Frugal Testing - Full Suite Runner
#  Run from:  c:\Users\vippa\OneDrive\Desktop\frugal_testing_A\
#  Usage:     .\run_all.ps1
# ==============================================================================

$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ROOT

Write-Host ""
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "  FRUGAL TESTING - Anti-AI Automation Suite" -ForegroundColor Cyan
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host ""

# --- 1. Start Q2 mock server (port 4001) --------------------------------------
Write-Host "[1/4] Starting Q2 Crypto-Replay Mock Server (port 4001)..." -ForegroundColor Yellow

$q2Dir = "$ROOT\Q2_crypto_replay\mock_server"
$q2ServerArgs = "-NoExit -Command Set-Location '$q2Dir'; node server.js"
Start-Process powershell -ArgumentList $q2ServerArgs
Start-Sleep -Seconds 3

try {
    $r = Invoke-WebRequest -Uri "http://localhost:4001/health" -UseBasicParsing -TimeoutSec 4
    Write-Host "    [OK] Q2 server healthy" -ForegroundColor Green
} catch {
    Write-Host "    [WARN] Q2 server check skipped - may still be starting" -ForegroundColor Yellow
}

# --- 2. Start Q1 canvas server (port 3001) ------------------------------------
Write-Host ""
Write-Host "[2/4] Starting Q1 Canvas Streaming Server (port 3001)..." -ForegroundColor Yellow

$q1ServerDir = "$ROOT\Q1_canvas_race\canvas_server"
$q1ServerArgs = "-NoExit -Command Set-Location '$q1ServerDir'; node server.js"
Start-Process powershell -ArgumentList $q1ServerArgs
Start-Sleep -Seconds 3

try {
    $r = Invoke-WebRequest -Uri "http://localhost:3001" -UseBasicParsing -TimeoutSec 4
    Write-Host "    [OK] Q1 canvas server responding" -ForegroundColor Green
} catch {
    Write-Host "    [WARN] Q1 canvas server check skipped - may still be starting" -ForegroundColor Yellow
}

# --- 3. Run Q2 test -----------------------------------------------------------
Write-Host ""
Write-Host "[3/4] Running Q2 - Cryptographic HMAC Replay Test..." -ForegroundColor Yellow
Write-Host "------------------------------------------------------" -ForegroundColor DarkGray

Set-Location "$ROOT\Q2_crypto_replay"
python automation\test_replay.py
$q2Exit = $LASTEXITCODE

Write-Host "------------------------------------------------------" -ForegroundColor DarkGray
if ($q2Exit -eq 0) {
    Write-Host "    [PASS] Q2 completed successfully" -ForegroundColor Green
} else {
    Write-Host "    [FAIL] Q2 exited with code $q2Exit" -ForegroundColor Red
}

# --- 4. Run Q1 test -----------------------------------------------------------
Write-Host ""
Write-Host "[4/4] Running Q1 - Canvas Race Interception Test (browser will open)..." -ForegroundColor Yellow
Write-Host "------------------------------------------------------" -ForegroundColor DarkGray

Set-Location "$ROOT\Q1_canvas_race"
python automation\test_canvas.py
$q1Exit = $LASTEXITCODE

Write-Host "------------------------------------------------------" -ForegroundColor DarkGray
if ($q1Exit -eq 0) {
    Write-Host "    [PASS] Q1 completed successfully" -ForegroundColor Green
} else {
    Write-Host "    [FAIL] Q1 exited with code $q1Exit" -ForegroundColor Red
}

# --- Summary ------------------------------------------------------------------
Set-Location $ROOT

Write-Host ""
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "  SUITE COMPLETE - RESULTS" -ForegroundColor Cyan
Write-Host "======================================================" -ForegroundColor Cyan

$q1Color = if ($q1Exit -eq 0) { "Green" } else { "Red" }
$q2Color = if ($q2Exit -eq 0) { "Green" } else { "Red" }
$q1Status = if ($q1Exit -eq 0) { "[PASS]" } else { "[FAIL]" }
$q2Status = if ($q2Exit -eq 0) { "[PASS]" } else { "[FAIL]" }

Write-Host "  Q1 Canvas Race    : $q1Status" -ForegroundColor $q1Color
Write-Host "  Q2 Crypto Replay  : $q2Status" -ForegroundColor $q2Color
Write-Host "  Q3 Shadow DOM     : [DOCUMENTED] -> Q3_shadow_dom/" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Screenshots saved in: Q1_canvas_race/" -ForegroundColor DarkGray
Write-Host "  Close server windows manually when done." -ForegroundColor DarkGray
Write-Host "======================================================" -ForegroundColor Cyan
