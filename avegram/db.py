import json
import psycopg
from psycopg.rows import dict_row

from .config import DB_URL

_DB_CONN = None

def db_conn():
    global _DB_CONN
    if not DB_URL:
        raise RuntimeError("DATABASE_URL not set")
    if _DB_CONN is None or _DB_CONN.closed:
        _DB_CONN = psycopg.connect(DB_URL, connect_timeout=10)
        _DB_CONN.autocommit = False
    return _DB_CONN

def db_init():
    conn = db_conn()
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id TEXT PRIMARY KEY,
                username TEXT,
                chain TEXT DEFAULT 'bsc',
                assets_id TEXT,
                address_list JSONB,
                state TEXT,
                session JSONB,
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                telegram_id TEXT NOT NULL,
                token_address TEXT NOT NULL,
                chain TEXT NOT NULL,
                symbol TEXT,
                entry_price NUMERIC,
                invested_usdt NUMERIC,
                tp_pct NUMERIC,
                sl_pct NUMERIC,
                status TEXT,
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now(),
                PRIMARY KEY (telegram_id, token_address, chain)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS copy_trades (
                telegram_id TEXT NOT NULL,
                target_wallet TEXT NOT NULL,
                chain TEXT NOT NULL,
                pct_allocation NUMERIC,
                max_usdt_per_trade NUMERIC,
                last_tx_hash TEXT,
                status TEXT,
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now(),
                PRIMARY KEY (telegram_id, target_wallet, chain)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS signal_history (
                symbol TEXT,
                signal_type TEXT,
                confidence NUMERIC,
                entry_price NUMERIC,
                status TEXT,
                pnl_pct NUMERIC,
                created_at TIMESTAMPTZ DEFAULT now(),
                expiry_time BIGINT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS swap_orders (
                id BIGSERIAL PRIMARY KEY,
                telegram_id TEXT,
                order_id TEXT,
                chain TEXT,
                in_token TEXT,
                out_token TEXT,
                in_amount TEXT,
                swap_type TEXT,
                status TEXT,
                ave_status TEXT,
                ave_msg TEXT,
                context JSONB,
                raw_response JSONB,
                created_at TIMESTAMPTZ DEFAULT now()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_errors (
                id BIGSERIAL PRIMARY KEY,
                telegram_id TEXT,
                area TEXT,
                message TEXT,
                context JSONB,
                created_at TIMESTAMPTZ DEFAULT now()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS task_heartbeats (
                task_name TEXT PRIMARY KEY,
                last_ok_at TIMESTAMPTZ,
                last_error_at TIMESTAMPTZ,
                error_count BIGINT DEFAULT 0,
                last_error TEXT,
                updated_at TIMESTAMPTZ DEFAULT now()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS token_meta (
                chain TEXT NOT NULL,
                token_address TEXT NOT NULL,
                symbol TEXT,
                decimals INT,
                updated_at TIMESTAMPTZ DEFAULT now(),
                PRIMARY KEY (chain, token_address)
            )
        """)
        cur.execute("ALTER TABLE copy_trades ADD COLUMN IF NOT EXISTS last_tx_time BIGINT")
        cur.execute("ALTER TABLE copy_trades ADD COLUMN IF NOT EXISTS last_tx_block BIGINT")
    conn.commit()

_USER_RESERVED_KEYS = {"username", "chain", "assets_id", "address_list", "state"}

def load_users():
    conn = db_conn()
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT telegram_id, username, chain, assets_id, address_list, state, session FROM users")
        rows = cur.fetchall()
    users = {}
    for r in rows:
        uid = r["telegram_id"]
        d = {
            "username": r.get("username"),
            "chain": r.get("chain") or "bsc",
            "assets_id": r.get("assets_id"),
            "address_list": r.get("address_list") or [],
            "state": r.get("state"),
        }
        sess = r.get("session") or {}
        if isinstance(sess, dict):
            d.update(sess)
        users[uid] = d
    return users

def save_users(u):
    conn = db_conn()
    with conn.cursor() as cur:
        for uid, d in u.items():
            session = {k: v for k, v in d.items() if k not in _USER_RESERVED_KEYS}
            cur.execute(
                """
                INSERT INTO users (telegram_id, username, chain, assets_id, address_list, state, session, updated_at)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, now())
                ON CONFLICT (telegram_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    chain = EXCLUDED.chain,
                    assets_id = EXCLUDED.assets_id,
                    address_list = EXCLUDED.address_list,
                    state = EXCLUDED.state,
                    session = EXCLUDED.session,
                    updated_at = now()
                """,
                (
                    str(uid),
                    d.get("username"),
                    d.get("chain") or "bsc",
                    d.get("assets_id"),
                    json.dumps(d.get("address_list") or []),
                    d.get("state"),
                    json.dumps(session),
                ),
            )
    conn.commit()

def load_trades():
    conn = db_conn()
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT telegram_id, token_address, chain, symbol, entry_price, invested_usdt, tp_pct, sl_pct, status FROM trades")
        rows = cur.fetchall()
    trades = {}
    for r in rows:
        uid = r["telegram_id"]
        trades.setdefault(uid, {})
        trades[uid][r["token_address"]] = {
            "chain": r.get("chain"),
            "symbol": r.get("symbol"),
            "entry_price": float(r["entry_price"]) if r.get("entry_price") is not None else 0.0,
            "invested_usdt": float(r["invested_usdt"]) if r.get("invested_usdt") is not None else 0.0,
            "tp_pct": float(r["tp_pct"]) if r.get("tp_pct") is not None else 0.0,
            "sl_pct": float(r["sl_pct"]) if r.get("sl_pct") is not None else 0.0,
            "status": r.get("status") or "active",
        }
    return trades

def save_trades(t):
    conn = db_conn()
    with conn.cursor() as cur:
        for uid, items in t.items():
            cur.execute("SELECT token_address, chain FROM trades WHERE telegram_id = %s", (str(uid),))
            existing = {(r[0], r[1]) for r in cur.fetchall()}
            incoming = {(token_address, (d.get("chain") or "bsc")) for token_address, d in (items or {}).items()}
            for token_address, chain in existing - incoming:
                cur.execute(
                    "DELETE FROM trades WHERE telegram_id = %s AND token_address = %s AND chain = %s",
                    (str(uid), token_address, chain),
                )
            if not items:
                continue
            for token_address, d in items.items():
                cur.execute(
                    """
                    INSERT INTO trades (telegram_id, token_address, chain, symbol, entry_price, invested_usdt, tp_pct, sl_pct, status, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                    ON CONFLICT (telegram_id, token_address, chain) DO UPDATE SET
                        symbol = EXCLUDED.symbol,
                        entry_price = EXCLUDED.entry_price,
                        invested_usdt = EXCLUDED.invested_usdt,
                        tp_pct = EXCLUDED.tp_pct,
                        sl_pct = EXCLUDED.sl_pct,
                        status = EXCLUDED.status,
                        updated_at = now()
                    """,
                    (
                        str(uid),
                        token_address,
                        d.get("chain") or "bsc",
                        d.get("symbol"),
                        d.get("entry_price") or 0,
                        d.get("invested_usdt") or 0,
                        d.get("tp_pct") or 0,
                        d.get("sl_pct") or 0,
                        d.get("status") or "active",
                    ),
                )
    conn.commit()

def load_copy_trades():
    conn = db_conn()
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT telegram_id, target_wallet, chain, pct_allocation, max_usdt_per_trade, last_tx_hash, last_tx_time, last_tx_block, status FROM copy_trades")
        rows = cur.fetchall()
    copy_trades = {}
    for r in rows:
        uid = r["telegram_id"]
        copy_trades.setdefault(uid, {})
        copy_trades[uid][r["target_wallet"]] = {
            "chain": r.get("chain") or "bsc",
            "pct_allocation": float(r["pct_allocation"]) if r.get("pct_allocation") is not None else 0.0,
            "max_usdt_per_trade": float(r["max_usdt_per_trade"]) if r.get("max_usdt_per_trade") is not None else 0.0,
            "last_tx_hash": r.get("last_tx_hash") or "",
            "last_tx_time": int(r["last_tx_time"]) if r.get("last_tx_time") is not None else 0,
            "last_tx_block": int(r["last_tx_block"]) if r.get("last_tx_block") is not None else 0,
            "status": r.get("status") or "active",
        }
    return copy_trades

def save_copy_trades(t):
    conn = db_conn()
    with conn.cursor() as cur:
        for uid, items in t.items():
            cur.execute("SELECT target_wallet, chain FROM copy_trades WHERE telegram_id = %s", (str(uid),))
            existing = {(r[0], r[1]) for r in cur.fetchall()}
            incoming = {(target_wallet, (d.get("chain") or "bsc")) for target_wallet, d in (items or {}).items()}
            for target_wallet, chain in existing - incoming:
                cur.execute(
                    "DELETE FROM copy_trades WHERE telegram_id = %s AND target_wallet = %s AND chain = %s",
                    (str(uid), target_wallet, chain),
                )
            if not items:
                continue
            for target_wallet, d in items.items():
                cur.execute(
                    """
                    INSERT INTO copy_trades (telegram_id, target_wallet, chain, pct_allocation, max_usdt_per_trade, last_tx_hash, last_tx_time, last_tx_block, status, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                    ON CONFLICT (telegram_id, target_wallet, chain) DO UPDATE SET
                        pct_allocation = EXCLUDED.pct_allocation,
                        max_usdt_per_trade = EXCLUDED.max_usdt_per_trade,
                        last_tx_hash = EXCLUDED.last_tx_hash,
                        last_tx_time = EXCLUDED.last_tx_time,
                        last_tx_block = EXCLUDED.last_tx_block,
                        status = EXCLUDED.status,
                        updated_at = now()
                    """,
                    (
                        str(uid),
                        target_wallet,
                        d.get("chain") or "bsc",
                        d.get("pct_allocation") or 0,
                        d.get("max_usdt_per_trade") or 0,
                        d.get("last_tx_hash") or "",
                        d.get("last_tx_time") or 0,
                        d.get("last_tx_block") or 0,
                        d.get("status") or "active",
                    ),
                )
    conn.commit()

def db_log_error(area, message, telegram_id=None, context=None):
    try:
        conn = db_conn()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO bot_errors (telegram_id, area, message, context) VALUES (%s, %s, %s, %s::jsonb)",
                (str(telegram_id) if telegram_id is not None else None, area, str(message), json.dumps(context or {})),
            )
        conn.commit()
    except Exception:
        pass

def db_heartbeat_ok(task_name):
    conn = db_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO task_heartbeats (task_name, last_ok_at, updated_at)
            VALUES (%s, now(), now())
            ON CONFLICT (task_name) DO UPDATE SET
                last_ok_at = now(),
                updated_at = now()
            """,
            (task_name,),
        )
    conn.commit()

def db_heartbeat_error(task_name, err):
    conn = db_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO task_heartbeats (task_name, last_error_at, error_count, last_error, updated_at)
            VALUES (%s, now(), 1, %s, now())
            ON CONFLICT (task_name) DO UPDATE SET
                last_error_at = now(),
                error_count = task_heartbeats.error_count + 1,
                last_error = EXCLUDED.last_error,
                updated_at = now()
            """,
            (task_name, str(err)),
        )
    conn.commit()

def db_insert_signal_history(rows):
    conn = db_conn()
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO signal_history (symbol, signal_type, confidence, entry_price, status, pnl_pct, expiry_time) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            rows,
        )
    conn.commit()

def db_insert_swap_order(telegram_id, chain, in_token, out_token, in_amount, swap_type, resp, context=None):
    try:
        status = None
        ave_status = resp.get("status")
        ave_msg = resp.get("msg")
        data = resp.get("data", {})
        order_id = None
        if isinstance(data, dict):
            order_id = data.get("id") or data.get("orderId")
            status = data.get("status")
        conn = db_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO swap_orders (telegram_id, order_id, chain, in_token, out_token, in_amount, swap_type, status, ave_status, ave_msg, context, raw_response)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                """,
                (
                    str(telegram_id),
                    order_id,
                    chain,
                    in_token,
                    out_token,
                    str(in_amount),
                    swap_type,
                    status,
                    str(ave_status) if ave_status is not None else None,
                    str(ave_msg) if ave_msg is not None else None,
                    json.dumps(context or {}),
                    json.dumps(resp),
                ),
            )
        conn.commit()
    except Exception:
        pass

def db_upsert_token_meta(chain, token_address, symbol=None, decimals=None):
    try:
        conn = db_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO token_meta (chain, token_address, symbol, decimals, updated_at)
                VALUES (%s, %s, %s, %s, now())
                ON CONFLICT (chain, token_address) DO UPDATE SET
                    symbol = EXCLUDED.symbol,
                    decimals = EXCLUDED.decimals,
                    updated_at = now()
                """,
                (chain, token_address, symbol, int(decimals) if decimals is not None else None),
            )
        conn.commit()
    except Exception:
        pass

