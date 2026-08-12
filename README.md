# Frugal-testing
🚀 Running the Frugal Testing Suite
✅ Run Everything at Once (Recommended)
powershell
cd c:\Users\vippa\OneDrive\Desktop\frugal_testing_A
.\run_all.ps1
Run Modules Individually
Q1 — Canvas Race Interception
Step 1: Start the canvas server (in a separate terminal)

powershell
cd c:\Users\vippa\OneDrive\Desktop\frugal_testing_A\Q1_canvas_race\canvas_server
node server.js
Step 2: Run the Playwright test

powershell
cd c:\Users\vippa\OneDrive\Desktop\frugal_testing_A\Q1_canvas_race
python automation\test_canvas.py
Q2 — Crypto HMAC Replay Protection
Step 1: Start the mock server (in a separate terminal)

powershell
cd c:\Users\vippa\OneDrive\Desktop\frugal_testing_A\Q2_crypto_replay\mock_server
node server.js
Step 2: Run the replay test

powershell
cd c:\Users\vippa\OneDrive\Desktop\frugal_testing_A\Q2_crypto_replay
python automation\test_replay.py
Q3 — Shadow DOM (Documentation only)
No runnable test — see Q3_shadow_dom/ for the written strategy.
Prerequisites (if not installed yet)
powershell
# Python deps for Q1
pip install -r Q1_canvas_race\requirements.txt
playwright install chromium
# Node deps for Q2 mock server
cd Q2_crypto_replay\mock_server && npm install
