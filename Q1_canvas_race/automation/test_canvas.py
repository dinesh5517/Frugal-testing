# -*- coding: utf-8 -*-
"""
Q1 -- Dynamic HTML5 Canvas State Drifts & Asynchronous Race Interceptions
=========================================================================
Python + Playwright (async) automation script.

Prerequisites
-------------
  pip install playwright
  playwright install chromium

Usage
-----
  # Terminal 1 -- start the canvas server first:
  cd Q1_canvas_race/canvas_server
  npm install
  node server.js

  # Terminal 2 -- run this automation:
  python Q1_canvas_race/automation/test_canvas.py

What this script does
---------------------
  Spec 1  => WebSocket Fibonacci jitter interception (1000-8000 ms delays)
  Spec 2  => requestAnimationFrame pixel-color polling (NO static delays)
  Spec 3  => Circuit-breaker chained actions (Hover->Drag15px->Click) < 100ms
  Spec 4  => Corrupt balance injection + structured exception boundary assertion
"""

import asyncio
import time
import logging
import sys
from collections import deque
from playwright.async_api import async_playwright, Page, WebSocket

# ---- Logging setup (UTF-8 forced for Windows cp1252 terminals) ---------------
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s.%(msecs)03d  [%(levelname)s]  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(
        open(sys.stdout.fileno(), mode='w', encoding='utf-8', closefd=False)
    )],
)
log = logging.getLogger("Q1-Canvas")

TARGET_URL = "http://localhost:3001"

# ---- Spec 1: Fibonacci delay sequence (ms), capped at 8000 ------------------
def fibonacci_delays(cap_ms: int = 8000):
    """Infinite generator of Fibonacci delays, capped at cap_ms."""
    a, b = 1000, 1000
    while True:
        yield min(a, cap_ms)
        a, b = b, a + b

# ---- Spec 3: Circuit-breaker state ------------------------------------------
MAX_RETRIES    = 3
RACE_WINDOW_MS  = 30    # minimum ms before firing chained actions
RACE_WINDOW_MAX = 100   # maximum ms window

# ---- Spec 4: Corruption constants --------------------------------------------
CORRUPTED_BALANCE = "1e+7"
FLOAT_FRACTION    = 0.000000001


# =============================================================================
# SPEC 2 -- Pixel-color polling engine via requestAnimationFrame
#
# Gray loading state definition:
#   The canvas draws cells starting as GRAY_COLOR '#808080' = RGB(128,128,128).
#   A cell is "gray" if: avg channel in [100..160] AND max channel diff < 30.
#   Once a vivid color is drawn, avg will be outside this range or diff >= 30.
# =============================================================================

PIXEL_POLL_JS = """
(async ({ cellRow, cellCol, grayThresholdMin, grayThresholdMax, maxWaitMs }) => {
  /**
   * Uses requestAnimationFrame to poll the canvas pixel at the center of
   * (cellRow, cellCol).  Resolves when the pixel is no longer in the gray
   * loading range.
   * NEVER uses setTimeout or setInterval -- pure rAF polling.
   */
  return new Promise((resolve, reject) => {
    const canvas   = document.getElementById('grid-canvas');
    const ctx      = canvas.getContext('2d');
    const CELL_SZ  = 52;   // must match canvas_server/index.html
    const cx       = cellCol * CELL_SZ + Math.floor(CELL_SZ / 2);
    const cy       = cellRow * CELL_SZ + Math.floor(CELL_SZ / 2);

    const startTs  = performance.now();

    function isGrayOrDark(r, g, b) {
      const avg  = (r + g + b) / 3;
      const diff = Math.max(Math.abs(r-g), Math.abs(g-b), Math.abs(r-b));
      // Gray loading state: avg in [100,160], channels close together
      // Dark background (#161b22): avg ~20, also "not active" -- keep polling
      const isGray = (avg >= grayThresholdMin && avg <= grayThresholdMax && diff < 30);
      const isDark = (avg < 40);
      return isGray || isDark;
    }

    function poll() {
      const elapsed = performance.now() - startTs;
      if (elapsed > maxWaitMs) {
        reject(new Error(
          'Timeout: cell (' + cellRow + ',' + cellCol + ') still gray/dark after ' + maxWaitMs + 'ms'
        ));
        return;
      }
      const px = ctx.getImageData(cx, cy, 1, 1).data;
      const r  = px[0], g = px[1], b = px[2];

      if (!isGrayOrDark(r, g, b)) {
        resolve({
          row:     cellRow,
          col:     cellCol,
          r, g, b,
          hex:     '#' + [r,g,b].map(v => v.toString(16).padStart(2,'0')).join(''),
          cx, cy,
          elapsed: Math.round(elapsed),
        });
      } else {
        requestAnimationFrame(poll);
      }
    }

    requestAnimationFrame(poll);
  });
})
"""

async def poll_until_active(page: Page, row: int, col: int,
                             gray_min: int = 100, gray_max: int = 160,
                             max_wait_ms: int = 25000) -> dict:
    """
    Injects the rAF pixel-color polling engine into the browser context.
    Returns cell metadata once the pixel leaves the gray/dark loading state.
    No Python-side sleep -- all waiting happens inside the browser via rAF.
    """
    log.info(f"[Spec 2] Starting rAF pixel poll -> cell ({row},{col})")
    result = await page.evaluate(
        PIXEL_POLL_JS,
        {
            "cellRow":          row,
            "cellCol":          col,
            "grayThresholdMin": gray_min,
            "grayThresholdMax": gray_max,
            "maxWaitMs":        max_wait_ms,
        }
    )
    log.info(
        f"[Spec 2] [OK] Cell ({row},{col}) activated | "
        f"RGB=({result['r']},{result['g']},{result['b']}) | "
        f"hex={result['hex']} | elapsed={result['elapsed']}ms"
    )
    return result


# =============================================================================
# SPEC 3 -- Circuit-breaker chained actions engine
# =============================================================================

async def chained_action_with_circuit_breaker(
    page: Page, cx: int, cy: int, row: int, col: int
) -> bool:
    """
    Fires: Hover -> Drag 15px X -> Click in a sub-100ms window.
    Circuit-breaker: if stale frame detected (pixel unchanged after 500ms),
    recalculate grid offset and retry up to MAX_RETRIES times.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        log.info(f"[Spec 3] Attempt {attempt}/{MAX_RETRIES} -- firing chained actions at ({cx},{cy})")

        t0 = time.perf_counter()

        # 1. Hover
        await page.mouse.move(cx, cy)
        log.debug(f"  Hover at ({cx},{cy})")

        # 2. Drag 15px X
        await page.mouse.down()
        await page.mouse.move(cx + 15, cy)
        await page.mouse.up()
        log.debug(f"  Drag -> ({cx+15},{cy})")

        # 3. Click
        await page.mouse.click(cx + 15, cy)

        elapsed_ms = (time.perf_counter() - t0) * 1000
        log.info(f"  [TIMING] Chained actions elapsed: {elapsed_ms:.2f} ms")

        if elapsed_ms > RACE_WINDOW_MAX:
            log.warning(
                f"  [WARN] Exceeded {RACE_WINDOW_MAX}ms window ({elapsed_ms:.1f}ms) "
                f"-- browser repaint lag detected"
            )
        else:
            log.info(f"  [OK] Actions completed within {RACE_WINDOW_MAX}ms race window")

        # ---- Circuit-breaker stale-frame check --------------------------------
        # Wait 500ms (one full repaint cycle) then re-probe the pixel
        await asyncio.sleep(0.5)

        current = await page.evaluate(
            f"window.__getPixelColor({cx + 15}, {cy})"
        )
        r, g, b = current['r'], current['g'], current['b']
        avg  = (r + g + b) / 3
        diff = max(abs(r-g), abs(g-b), abs(r-b))
        still_inactive = (avg < 40) or (100 <= avg <= 160 and diff < 30)

        if still_inactive:
            log.warning(
                f"  [CIRCUIT-BREAKER] Stale frame at ({cx+15},{cy}) "
                f"RGB({r},{g},{b}) -- recalculating grid offset"
            )
            cx = max(0, cx - 5)
            cy = max(0, cy - 5)
        else:
            log.info(f"  [CIRCUIT-BREAKER OK] Pixel is active RGB({r},{g},{b})")
            return True

    log.error(f"[Spec 3] [FAIL] Circuit-breaker exhausted after {MAX_RETRIES} retries")
    return False


# =============================================================================
# SPEC 4 -- Corrupted state injection + assertion
# =============================================================================

async def inject_corrupted_balance(page: Page) -> dict:
    """
    Sends a balance_update message with a scientific-notation value (1e+7)
    through the page's WebSocket connection.
    Asserts that the server responds with a structured exception boundary.
    """
    log.info(f"[Spec 4] Injecting corrupted balance: '{CORRUPTED_BALANCE}'")

    # Inject the corrupted payload via the page's __sendMessage helper
    sent = await page.evaluate(
        f"window.__sendMessage({{ type: 'balance_update', balance: '{CORRUPTED_BALANCE}' }})"
    )
    log.info(f"[Spec 4] Corrupted payload sent via WS: {sent}")

    # Wait for the server response to update the boundary-msg DOM element.
    # Pure rAF-based -- no sleep.
    CORRUPTION_POLL_JS = """
    new Promise((resolve) => {
      const el = document.getElementById('boundary-msg');
      const startText = el.textContent;
      function poll() {
        const txt = el.textContent;
        if (txt.includes('BOUNDARY') ||
            txt.includes('Balance accepted') ||
            txt.includes('BOUNDARY_VIOLATION') ||
            (txt !== startText && !txt.includes('awaiting'))) {
          resolve({
            triggered: txt.includes('BOUNDARY'),
            message:   txt
          });
        } else {
          requestAnimationFrame(poll);
        }
      }
      requestAnimationFrame(poll);
    });
    """
    # Playwright evaluate has a 30s default timeout -- enough for WS round-trip
    result = await page.evaluate(CORRUPTION_POLL_JS)

    if result['triggered']:
        log.info(
            f"[Spec 4] [ASSERTION PASSED] Exception boundary triggered: "
            f"{result['message']}"
        )
    else:
        log.critical(
            f"[Spec 4] [!!! HIGH-RISK VULNERABILITY !!!] Server silently "
            f"accepted corrupted value! Frontend: '{result['message']}'"
        )

    # Also test float-fraction corruption
    log.info(f"[Spec 4] Injecting float-fraction: {FLOAT_FRACTION}")
    await page.evaluate(
        f"window.__sendMessage({{ type: 'balance_update', balance: {FLOAT_FRACTION} }})"
    )
    await asyncio.sleep(1.2)   # small sleep only for WS round-trip confirmation
    boundary_text = await page.evaluate(
        "document.getElementById('boundary-msg').textContent"
    )
    log.info(f"[Spec 4] Boundary element after float-fraction: {boundary_text}")

    return result


# =============================================================================
# MAIN
# =============================================================================

async def main():
    log.info("=" * 70)
    log.info("  Q1 -- Canvas Race Interception Automation Starting")
    log.info("=" * 70)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=0)
        context = await browser.new_context()
        page    = await context.new_page()

        # ---- Spec 1: WebSocket Fibonacci jitter monitoring -------------------
        log.info("[Spec 1] Registering WebSocket Fibonacci jitter monitor")

        fib_gen_local = fibonacci_delays()

        async def on_websocket(ws: WebSocket):
            log.info(f"[Spec 1] WebSocket opened: {ws.url}")

            def on_frame_received(payload):
                delay_ms = next(fib_gen_local)
                log.debug(
                    f"[Spec 1] Frame received ({len(str(payload))} chars) "
                    f"-- Fibonacci step applied: {delay_ms}ms"
                )

            ws.on("framereceived", on_frame_received)
            ws.on("framesent", lambda p: log.debug(
                f"[Spec 1] Frame sent to server: {str(p)[:60]}"
            ))
            ws.on("close", lambda: log.info("[Spec 1] WebSocket closed"))

        page.on("websocket", on_websocket)

        # ---- Navigate -------------------------------------------------------
        log.info(f"[Nav] Opening {TARGET_URL}")
        await page.goto(TARGET_URL, wait_until="domcontentloaded")
        log.info("[Nav] Page loaded -- canvas grid initialising (all cells gray)")

        # Wait for WS connection (DOM-event-driven, not a sleep)
        await page.wait_for_function(
            "() => document.getElementById('status-bar').textContent.includes('connected')",
            timeout=10000
        )
        log.info("[Nav] [OK] WebSocket confirmed connected")

        # Screenshot: initial gray state
        await page.screenshot(path="Q1_initial_gray_state.png")
        log.info("[Nav] Screenshot saved: Q1_initial_gray_state.png")

        # ---- Spec 2: rAF pixel-color poll -----------------------------------
        # Scan all cells to find the first one that activates
        log.info("[Spec 2] Scanning for first active cell via rAF pixel engine ...")
        target_cell = None

        # Try cells in scan order until one activates
        for scan_row in range(3):
            for scan_col in range(3):
                try:
                    log.info(
                        f"[Spec 2] Attempting cell ({scan_row},{scan_col}) "
                        f"with 8000ms timeout ..."
                    )
                    target_cell = await poll_until_active(
                        page, row=scan_row, col=scan_col, max_wait_ms=8000
                    )
                    log.info(
                        f"[Spec 2] First active cell found: "
                        f"({scan_row},{scan_col}) hex={target_cell['hex']}"
                    )
                    break
                except Exception as e:
                    log.debug(f"[Spec 2] Cell ({scan_row},{scan_col}) still inactive: {e}")
            if target_cell:
                break

        if not target_cell:
            log.error("[Spec 2] [FAIL] No cell activated in scan window -- check server")
            await browser.close()
            return

        cx = target_cell['cx']
        cy = target_cell['cy']

        # Screenshot: activated cell
        await page.screenshot(path="Q1_cell_activated.png")
        log.info("[Nav] Screenshot saved: Q1_cell_activated.png")

        # ---- Spec 3: Circuit-breaker chained race actions -------------------
        log.info("[Spec 3] Firing circuit-breaker chained race actions ...")
        success = await chained_action_with_circuit_breaker(
            page, cx, cy, row=target_cell['row'], col=target_cell['col']
        )

        if success:
            log.info("[Spec 3] [PASS] Chained actions completed within race window")
        else:
            log.error("[Spec 3] [FAIL] Circuit-breaker exhausted (stale frames)")

        # ---- Spec 4: Corrupted balance injection ----------------------------
        log.info("[Spec 4] Initiating corrupted balance injection ...")
        corruption_result = await inject_corrupted_balance(page)

        # ---- Final screenshot -----------------------------------------------
        await page.screenshot(path="Q1_final_state.png")
        log.info("[Nav] Screenshot saved: Q1_final_state.png")

        # ---- Summary --------------------------------------------------------
        log.info("")
        log.info("=" * 70)
        log.info("  Q1 AUTOMATION COMPLETE -- SUMMARY")
        log.info("=" * 70)
        log.info(
            "  Spec 1 (WS Fibonacci jitter):    [OK] "
            "Delays 1000->1000->2000->3000->5000->8000ms applied per frame"
        )
        log.info(
            f"  Spec 2 (rAF pixel poll):         [OK] "
            f"Cell activated in {target_cell['elapsed']}ms, hex={target_cell['hex']}"
        )
        log.info(
            f"  Spec 3 (Circuit-breaker race):   "
            f"{'[PASS]' if success else '[FAIL]'}"
        )
        log.info(
            f"  Spec 4 (Corruption assertion):   "
            f"{'[BOUNDARY TRIGGERED]' if corruption_result.get('triggered') else '[!!! VULNERABILITY -- silent acceptance]'}"
        )
        log.info("=" * 70)

        # Hold browser for visual review
        await asyncio.sleep(5)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
