/**
 * Q1 Canvas Streaming Server
 * ─────────────────────────
 * Serves an HTML5 Canvas page and broadcasts live WebSocket grid-cell
 * color-update events.  Each packet carries JSON describing which cell
 * changes from its "gray loading state" to an active vivid color.
 *
 * Start:  node server.js
 * Serves: http://localhost:3001
 * WS:     ws://localhost:3001
 */

const express  = require('express');
const http     = require('http');
const WebSocket = require('ws');
const path     = require('path');
const fs       = require('fs');

const PORT = 3001;
const GRID_SIZE = 10;           // 10 × 10 grid
const BROADCAST_INTERVAL_MS = 800; // ~1.25 Hz – slow enough to observe clearly

const app    = express();
const server = http.createServer(app);
const wss    = new WebSocket.Server({ server });

// ── Serve the canvas HTML page ───────────────────────────────────────────────
app.get('/', (req, res) => {
  res.sendFile(path.join(__dirname, 'index.html'));
});

// ── Track grid state on the server side ──────────────────────────────────────
const VIVID_COLORS = [
  '#e74c3c', '#2ecc71', '#3498db', '#f39c12',
  '#9b59b6', '#1abc9c', '#e67e22', '#e91e63',
  '#00bcd4', '#8bc34a', '#ff5722', '#607d8b',
];

function randomVividColor() {
  return VIVID_COLORS[Math.floor(Math.random() * VIVID_COLORS.length)];
}

function randomCell() {
  return {
    row: Math.floor(Math.random() * GRID_SIZE),
    col: Math.floor(Math.random() * GRID_SIZE),
  };
}

// ── Broadcast loop ────────────────────────────────────────────────────────────
let tickCount = 0;

function broadcastTick() {
  tickCount++;

  // Pick 1–3 random cells to activate / change colour per tick
  const cellCount = Math.floor(Math.random() * 3) + 1;
  const updates   = [];

  for (let i = 0; i < cellCount; i++) {
    const { row, col } = randomCell();
    updates.push({
      row,
      col,
      color:     randomVividColor(),
      balance:   +(Math.random() * 10000).toFixed(2),
      tick:      tickCount,
      timestamp: Date.now(),
    });
  }

  const payload = JSON.stringify({ type: 'grid_update', updates });

  wss.clients.forEach((client) => {
    if (client.readyState === WebSocket.OPEN) {
      client.send(payload);
    }
  });
}

setInterval(broadcastTick, BROADCAST_INTERVAL_MS);

// ── WebSocket connection handler ──────────────────────────────────────────────
wss.on('connection', (ws, req) => {
  console.log(`[WS] Client connected from ${req.socket.remoteAddress}`);

  // Send initial "all gray" state so client knows the grid dimensions
  const initPayload = JSON.stringify({
    type:      'init',
    gridSize:  GRID_SIZE,
    cellSize:  50,
    message:   'Canvas grid initialised – all cells in gray loading state',
  });
  ws.send(initPayload);

  ws.on('message', (msg) => {
    // Echo back any client messages (allows the automation to write back
    // a corrupted payload and observe server behaviour)
    try {
      const data = JSON.parse(msg.toString());
      console.log('[WS] Received from client:', JSON.stringify(data));

      // Simulate a server-side boundary check on the balance field
      if (data.type === 'balance_update') {
        const { balance } = data;
        const parsed = parseFloat(balance);

        if (!isFinite(parsed) || isNaN(parsed)) {
          ws.send(JSON.stringify({
            type:    'error',
            code:    'INVALID_BALANCE',
            message: `Corrupted balance value rejected: "${balance}"`,
          }));
        } else if (String(balance).toLowerCase().includes('e') ||
                   !Number.isInteger(parsed * 100)) {
          // Scientific notation or sub-cent precision detected
          ws.send(JSON.stringify({
            type:    'exception_boundary',
            code:    'BOUNDARY_VIOLATION',
            message: `Structured exception: scientific/floating balance "${balance}" detected`,
            received: balance,
          }));
        } else {
          ws.send(JSON.stringify({
            type:    'balance_ack',
            balance: parsed,
            status:  'accepted',
          }));
        }
      }
    } catch (e) {
      ws.send(JSON.stringify({ type: 'error', message: 'Invalid JSON' }));
    }
  });

  ws.on('close', () => console.log('[WS] Client disconnected'));
  ws.on('error', (err) => console.error('[WS] Error:', err.message));
});

// Bind to 0.0.0.0 so the server accepts connections from all network interfaces
// (required when running behind a reverse proxy or in a cloud environment)
server.listen(PORT, '0.0.0.0', () => {
  console.log(`\n✅  Canvas Streaming Server running at http://0.0.0.0:${PORT}`);
  console.log(`✅  WebSocket endpoint:          ws://0.0.0.0:${PORT}\n`);
});
