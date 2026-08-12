/**
 * Q2 Crypto Replay Mock Server
 * ────────────────────────────
 * Exposes two endpoints:
 *
 *   POST /transaction
 *     → Creates a new transaction, returns X-Transaction-Id,
 *       X-Challenge-Token, and X-Server-Timestamp in response headers.
 *
 *   PUT /transaction/:id
 *     → Validates the X-Frugal-Mac HMAC-SHA512 header.
 *       Enforces nonce uniqueness (replay protection).
 *       Returns 200 on success, 409 on replay detected, 401 on bad MAC.
 *
 * Start:  node server.js
 * Listens: http://localhost:4001
 */

const express  = require('express');
const crypto   = require('crypto');
const { v4: uuidv4 } = require('uuid');

const app  = express();
const PORT = 4001;

// Capture raw body string for HMAC verification
app.use(express.json({
  verify: (req, res, buf) => { req.rawBody = buf.toString('utf-8'); }
}));


// ── In-memory stores ──────────────────────────────────────────────────────────
const transactions = new Map();   // id → { challengeToken, createdAt, amount, status }
const usedNonces   = new Set();   // Set<nonce_string> for replay detection

// ── HMAC-SHA512 signing secret (shared with client via X-Challenge-Token) ─────
const HMAC_SECRET = 'frugal-testing-hmac-secret-2026';
const SALT_SEQ    = 'FT-SALT-v1-DELTA-7';

// ── Helpers ───────────────────────────────────────────────────────────────────
function generateChallengeToken() {
  return crypto.randomBytes(32).toString('hex');
}

function computeExpectedMac(rawBody, timestamp, challengeToken) {
  /**
   * MAC = HMAC-SHA512(
   *   key  = challengeToken,
   *   data = rawBodyString + timestamp + SALT_SEQ
   * )
   * Using raw body string avoids JSON serialization mismatches
   * between different language runtimes (Python vs Node).
   */
  const data = rawBody + timestamp + SALT_SEQ;
  return crypto
    .createHmac('sha512', challengeToken)
    .update(data)
    .digest('hex');
}

// ── POST /transaction ─────────────────────────────────────────────────────────
app.post('/transaction', (req, res) => {
  const id             = uuidv4();
  const challengeToken = generateChallengeToken();
  const serverTs       = Date.now() * 1000; // microseconds

  transactions.set(id, {
    challengeToken,
    createdAt: Date.now(),
    amount:    req.body.amount || 0,
    status:    'pending',
  });

  console.log(`\n[POST /transaction] Created transaction ${id}`);
  console.log(`  Challenge token : ${challengeToken}`);
  console.log(`  Server timestamp: ${serverTs}`);

  res
    .status(201)
    .set({
      'X-Transaction-Id':   id,
      'X-Challenge-Token':  challengeToken,
      'X-Server-Timestamp': String(serverTs),
    })
    .json({
      message:   'Transaction created',
      id,
      status:    'pending',
      serverTs,
    });
});

// ── PUT /transaction/:id ──────────────────────────────────────────────────────
app.put('/transaction/:id', (req, res) => {
  const { id }      = req.params;
  const clientMac   = req.headers['x-frugal-mac'];
  const clientTs    = req.headers['x-timestamp'];
  const body        = req.body;

  console.log(`\n[PUT /transaction/${id}]`);
  console.log(`  X-Frugal-Mac : ${clientMac}`);
  console.log(`  X-Timestamp  : ${clientTs}`);

  // ── 1. Transaction existence check ─────────────────────────────────────────
  if (!transactions.has(id)) {
    return res.status(404).json({ error: 'Transaction not found' });
  }

  const txn = transactions.get(id);

  // ── 2. Presence check ──────────────────────────────────────────────────────
  if (!clientMac || !clientTs) {
    return res.status(400).json({ error: 'Missing X-Frugal-Mac or X-Timestamp header' });
  }

  // ── 3. Timestamp staleness check (±10 seconds allowed) ────────────────────
  const clientTsMs = Math.floor(Number(clientTs) / 1000); // back to ms
  const drift      = Math.abs(Date.now() - clientTsMs);
  if (drift > 10_000) {
    console.log(`  ❌ Timestamp drift too large: ${drift}ms`);
    return res.status(401).json({ error: 'Timestamp expired', drift_ms: drift });
  }

  // ── 4. HMAC validation ─────────────────────────────────────────────────────
  const rawBody     = req.rawBody || JSON.stringify(req.body);
  const expectedMac = computeExpectedMac(rawBody, clientTs, txn.challengeToken);
  const macValid    = crypto.timingSafeEqual(
    Buffer.from(clientMac,   'hex'),
    Buffer.from(expectedMac, 'hex'),
  );

  if (!macValid) {
    console.log(`  ❌ HMAC mismatch`);
    console.log(`     Expected: ${expectedMac}`);
    console.log(`     Got     : ${clientMac}`);
    return res.status(401).json({ error: 'Invalid X-Frugal-Mac signature' });
  }

  // ── 5. Replay detection via nonce ─────────────────────────────────────────
  const nonce = `${id}::${clientTs}::${clientMac}`;

  if (usedNonces.has(nonce)) {
    console.log(`  🔴 REPLAY DETECTED — nonce already seen: ${nonce.slice(0, 60)}...`);
    return res.status(409).json({
      error:  'Replay attack detected',
      code:   'REPLAY_ATTEMPT',
      nonce:  nonce.slice(0, 60) + '...',
      detail: 'This request has already been processed. Duplicate nonce rejected.',
    });
  }

  // ── 6. Commit & store nonce ────────────────────────────────────────────────
  usedNonces.add(nonce);
  txn.status = 'completed';
  txn.amount = body.amount ?? txn.amount;
  transactions.set(id, txn);

  console.log(`  ✅ Transaction ${id} committed successfully`);
  return res.status(200).json({
    message:  'Transaction updated successfully',
    id,
    status:   'completed',
    amount:   txn.amount,
  });
});

// ── Health check ──────────────────────────────────────────────────────────────
app.get('/health', (req, res) => res.json({ status: 'ok', port: PORT }));

app.listen(PORT, () => {
  console.log(`\n✅  Crypto Replay Mock Server running at http://localhost:${PORT}`);
  console.log(`    POST /transaction       — create transaction`);
  console.log(`    PUT  /transaction/:id   — update with HMAC auth (replay protected)\n`);
});
