# Avegram — Project Documentation
**Crypto Signal Bot + Spot Trading on Telegram**
*Powered by Ave Cloud API | April 2026*

---

## 1. Product Overview

**Avegram** is a Telegram-native crypto platform that combines AI-driven signal generation, smart money tracking, and one-tap spot trading — all in one bot conversation. Users register via Telegram, get a proxy wallet automatically, and can trade, track wallets, and receive live signals without leaving the app.

**Core differentiating edge:** Ave Cloud API's signal data and proxy wallet infrastructure, enabling server-side trade execution without users exposing private keys.

---

## 2. AVE Skills & API Endpoints Used

Avegram is built on the **AVE Cloud Skill Suite**. The bot imports from a local skill module at `/home/workspace/ave-cloud-skill/scripts` and makes direct REST API calls to the Ave proxy infrastructure.

### 2.1 Data Skills (ave-data-rest)

Used for on-chain data lookups — no trading authority required.

| Endpoint / Method | Purpose |
|---|---|
| `GET /tokens?keyword=&chain=&limit=` | Token search by symbol/keyword |
| `GET /tokens/{token}-{chain}` | Token price, market cap, liquidity, 24h volume |
| `GET /contracts/{token}-{chain}` | Honeypot check, risk score, contract safety |
| `GET /address/walletinfo/tokens` | Read a wallet's token holdings on-chain (balance, P/L) |
| `GET /address/walletinfo/transactions` | Wallet's recent swap transactions |
| `GET /address/smart_wallet/list` | Top smart money wallets ranked by profit % |
| `GET /v2/signals/public/list` | Live filtered trading signals (confidence, type, chain) |

### 2.2 Trading Skills (ave-trade-proxy-wallet)

Used for executing trades via Ave's server-managed proxy wallet (no private key exposure).

| Endpoint / Method | Purpose |
|---|---|
| `POST /v1/thirdParty/user/generateWallet` | Create a new proxy wallet for a user |
| `POST /v1/thirdParty/chainWallet/getAmountOut` | Get a swap quote (price impact, estimated output) |
| `POST /v1/thirdParty/tx/sendSwapOrder` | Execute a buy or sell order |
| `GET /v1/thirdParty/tx/getSwapOrder` | Fetch user's swap history (used for on-chain balance derivation) |

### 2.3 Authentication

All Ave proxy API calls are signed with HMAC-SHA256:

```
Timestamp (UTC ISO) + Method + Path + JSON-body → Base64(HMAC-SHA256(AVE_SECRET_KEY, message))
Headers: AVE-ACCESS-KEY, AVE-ACCESS-TIMESTAMP, AVE-ACCESS-SIGN, Content-Type: application/json
```

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Telegram Users                       │
│         @visualise_crypto  & future users             │
└──────────────────────┬────────────────────────────────┘
                       │ Telegram Bot API (polling)
┌──────────────────────▼────────────────────────────────┐
│                    app.py                              │
│              (1,321 lines — main bot)                 │
│                                                          │
│  ┌─────────────────────────────────────────────────┐   │
│  │  Command Handlers                               │   │
│  │  /start  /register  /balance  /trade            │   │
│  │  /signal  /analyse  /topwallets  /track         │   │
│  │  /help  (inline + command)                      │   │
│  └─────────────────────────────────────────────────┘   │
│                                                          │
│  ┌─────────────────────────────────────────────────┐   │
│  │  Background Monitors (async, persistent loops)   │   │
│  │  monitor_tp_sl()        — every 30s             │   │
│  │  monitor_copy_trades()  — every 60s             │   │
│  │  monitor_signal_alerts() — every 120s → channel │   │
│  └─────────────────────────────────────────────────┘   │
└──────────────────────┬────────────────────────────────┘
                       │
         ┌─────────────┴──────────────┐
         ▼                            ▼
┌─────────────────────┐    ┌────────────────────────────┐
│  Local Data Files   │    │     Ave Cloud API           │
│  users.json         │    │     bot-api.ave.ai          │
│  trades.json        │    │     data.ave-api.xyz        │
│  copy_trades.json   │    │     (REST + WSS)           │
└─────────────────────┘    └────────────────────────────┘
```

---

## 4. Features Implemented

### 4.1 User Registration & Wallet Management
- `/register` — Creates a proxy wallet via Ave's `generateWallet` API. No private keys exposed — Ave holds them server-side.
- Proxy wallet supports BSC, ETH, Base, and Solana addresses per user.
- Auto-link on return: subsequent `/register` calls recognize existing wallets.

### 4.2 Portfolio & P&L Tracking
- `/balance` — Dual-mode: tries on-chain wallet read first (`/address/walletinfo/tokens`), falls back to swap history.
- Shows USDT, BNB, and all held token balances.
- Displays total portfolio value in USD.
- Active TP/SL configurations shown per token.

### 4.3 Signal Scanner
- `/signal` — Scans 25+ tokens (public Ave signals + trending BSC keywords).
- Scores tokens on: Liquidity (25%), Volume (20%), Price Momentum (25%), Contract Safety (20%), Holder Distribution (10%).
- Threshold: 60%+ confidence for display. BUY/SELL/WATCH verdict.
- Inline "⚡ Auto-Trade (TP/SL)" button per signal.

### 4.4 Token Analysis
- `/analyse <SYMBOL>` — Deep-dive for any token.
- Fetches live price, market cap, liquidity, 24h volume, holder count, risk/honeypot data.
- Weighted score with visual bar chart (0–100 per metric).
- BUY/HOLD/SELL verdict based on weighted aggregate.

### 4.5 Auto-Trade with TP/SL
- Interactive flow: user selects token → enters USDT amount → sets Take-Profit % → sets Stop-Loss %.
- Executes BUY immediately via Ave proxy wallet.
- `monitor_tp_sl()` polls every 30s — auto-executes SELL when TP or SL price is hit.
- Notifications sent to user via Telegram DM on trigger.

### 4.6 Smart Money Tracking
- `/topwallets [chain]` — Lists top wallets by 900%+ and 300–900% profitable trade count.
- `/track <ADDRESS> [chain]` — Reads a wallet's on-chain holdings with P/L % per token.
- Inline "👥 Copy Trade" button on tracked wallets.

### 4.7 Copy Trading
- Full copy-trade engine via `monitor_copy_trades()` (every 60s).
- Configuration: % of USDT balance per trade + max USDT per copied trade.
- Mirrors BUY and SELL from target smart wallet to user's proxy wallet.
- Retry/Dismiss buttons on failed copy-trade executions.

### 4.8 Signal Alerts Channel
- `monitor_signal_alerts()` — Background scanner (every 120s).
- Broadcasts ≥85% confidence BUY signals to `@AvegramAlerts` Telegram channel.
- Includes "⚡ Auto-Trade" and "📊 Analyse" inline buttons.
- Seen-signal deduplication prevents duplicate alerts.

### 4.9 Quote / Trade Execution
- `/trade <SYMBOL> <AMOUNT>` — Executes a buy order via Ave proxy wallet.
- `/quote <SYMBOL> [AMOUNT]` — Gets swap quote without executing (displayed price, estimated output).
- Retry button on failed swap with error reason from Ave API.

---

## 5. Bot Commands Reference

| Command | Description |
|---|---|
| `/start` | Welcome menu — creates wallet button if unregistered |
| `/register` | Create or link proxy wallet |
| `/deposit` | Show BSC deposit address + QR |
| `/balance` | On-chain portfolio with USD values |
| `/signal` | Scan tokens for signals (60%+ conf) |
| `/analyse <SYMBOL>` | Deep token analysis with scores |
| `/trade <SYMBOL> <AMT>` | Execute buy order |
| `/quote <SYMBOL> [AMT]` | Get swap quote without executing |
| `/topwallets [chain]` | Top smart money wallets |
| `/track <ADDRESS>` | Track a wallet's holdings |
| `/help` | Full command reference |

---

## 6. Data Files

| File | Schema |
|---|---|
| `users.json` | `{telegram_uid: {assets_id, address_list[], username, chain, state}}` |
| `trades.json` | `{uid: {token_addr: {chain, symbol, entry_price, invested_usdt, tp_pct, sl_pct, status}}}` |
| `copy_trades.json` | `{uid: {target_addr: {chain, pct_allocation, max_usdt_per_trade, last_tx_hash, status}}}` |

---

## 7. Background Monitor Summary

| Monitor | Interval | Broadcasts To |
|---|---|---|
| `monitor_tp_sl` | 30s | Per-user DM |
| `monitor_copy_trades` | 60s | Per-user DM |
| `monitor_signal_alerts` | 120s | `@AvegramAlerts` channel |

---

## 8. Technical Notes

- **Language:** Python 3.12
- **Framework:** python-telegram-bot v20 (async)
- **JSON Storage:** File-based (users.json, trades.json, copy_trades.json) — production should migrate to a database
- **API Plan:** Pro (unlocks proxy wallet trading, better rate limits)
- **Chains Supported:** BSC (primary), Solana, ETH, Base
- **Wallet Type:** Ave proxy wallet (server-managed, no private key exposure)
- **Security:** HMAC-SHA256 signed requests to Ave proxy API

---

## 9. Future Roadmap

- [ ] DCA/recurring buy bot
- [ ] Price alerts (alert when token drops X%)
- [ ] Profit sharing (top traders)
- [ ] Gamification: XP levels, trading streaks, challenge leaderboards
- [ ] Subscription tiers (Free vs Pro)
- [ ] Database migration (SQLite/PostgreSQL)
- [ ] Web dashboard

---

*Document generated: April 2026 | Avegram v2 | Powered by Ave Cloud API*
