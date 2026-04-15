# Postgres Persistence Design Spec

## 1. Overview
This specification migrates all bot state from local JSON files into Postgres. It replaces:
- `users.json` (user identity, proxy wallet link, conversational state)
- `trades.json` (TP/SL active positions)
- `copy_trades.json` (copy-trading configurations)

The bot runs in **Postgres-only** mode: if `DATABASE_URL` (or `POSTGRES_URL`) is missing, the bot should fail fast with a clear message.

## 2. Goals
- Make state durable across restarts and deploys (PythonAnywhere, VPS, etc.).
- Remove reliance on local filesystem writes.
- Keep minimal changes to the existing bot flows and data shapes.
- Avoid leaking secrets: database URLs are only provided via environment variables.

## 3. Non-Goals
- Introducing a heavy ORM layer.
- Historical trade analytics storage (beyond what we already pull from Ave).
- Multi-tenant database provisioning.

## 4. Library Choice
- Use `psycopg2-binary` for compatibility and simplest deployment.
- All DB operations are synchronous; for current bot scale this is acceptable.

## 5. Schema

### 5.1 users
Stores Telegram user identity, proxy wallet link, and conversational state.

- `telegram_id TEXT PRIMARY KEY`
- `username TEXT`
- `chain TEXT DEFAULT 'bsc'`
- `assets_id TEXT`
- `address_list JSONB` (Ave addressList payload)
- `state TEXT` (e.g. `awaiting_trade_input`)
- `session JSONB` (e.g. `{"auto_trade": {...}, "copy_trade": {...}, "withdraw_address": "..."}`)
- `created_at TIMESTAMPTZ DEFAULT now()`
- `updated_at TIMESTAMPTZ DEFAULT now()`

Indexes:
- `assets_id` index (optional)

### 5.2 trades (TP/SL)
Stores active TP/SL orders per user per token.

- `telegram_id TEXT`
- `token_address TEXT`
- `chain TEXT`
- `symbol TEXT`
- `entry_price NUMERIC`
- `invested_usdt NUMERIC`
- `tp_pct NUMERIC`
- `sl_pct NUMERIC`
- `status TEXT` (e.g. `active`)
- `created_at TIMESTAMPTZ DEFAULT now()`
- `updated_at TIMESTAMPTZ DEFAULT now()`

Primary key:
- `(telegram_id, token_address, chain)`

### 5.3 copy_trades
Stores which wallets a user is copying and the sizing rules.

- `telegram_id TEXT`
- `target_wallet TEXT`
- `chain TEXT`
- `pct_allocation NUMERIC`
- `max_usdt_per_trade NUMERIC`
- `last_tx_hash TEXT`
- `status TEXT` (e.g. `active`)
- `created_at TIMESTAMPTZ DEFAULT now()`
- `updated_at TIMESTAMPTZ DEFAULT now()`

Primary key:
- `(telegram_id, target_wallet, chain)`

## 6. Data Access Layer
Add a small DB module (in `signal_telegram.py` initially) that provides:
- `db_init()` to create tables if missing
- `db_get_user(telegram_id)`
- `db_upsert_user(...)`
- `db_set_user_state(telegram_id, state)`
- `db_set_user_session(telegram_id, session_patch)`
- `db_list_active_trades()`, `db_upsert_trade(...)`, `db_delete_trade(...)`
- `db_list_active_copy_trades()`, `db_upsert_copy_trade(...)`, `db_delete_copy_trade(...)`

## 7. Flow Mapping
- `load_users/save_users` become user table reads/writes.
- `load_trades/save_trades` become trades table reads/writes.
- `load_copy_trades/save_copy_trades` become copy_trades table reads/writes.

The rest of the bot logic remains the same, but uses DB helper calls.

## 8. Startup Behavior
- On startup, call `db_init()`.
- If `DATABASE_URL`/`POSTGRES_URL` missing: log and exit.

## 9. Migration Strategy (one-time)
Optional helper script:
- Read existing JSON files (if present) and insert rows into Postgres.
- After migration, JSON is no longer used.

## 10. Operational Notes
- Always set `sslmode=require` (already present in your Prisma URL).
- Use short connection timeouts and retry logic for transient DB failures.
- Never commit `.env` or any connection string to the repo.

