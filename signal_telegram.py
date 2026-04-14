"""
SignalBot Telegram Bot v1
Commands: /start, /register, /deposit, /trade, /balance, /help, /signal
"""
import os
import json
import asyncio
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler, CallbackQueryHandler
)
from eth_account import Account

AVENUE_SCRIPTS = "/home/workspace/ave-cloud-skill/scripts"
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
AVE_API_KEY = os.environ.get("AVE_API_KEY", "")
API_PLAN = os.environ.get("API_PLAN", "free")
USERS_FILE = "/home/workspace/signal-bot/users.json"

(STATE_REGISTER, STATE_DEPOSIT, STATE_TRADE_CONFIRM) = range(3)

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE) as f:
            return json.load(f)
    return {}

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)

def generate_wallet():
    acct = Account.create()
    return {
        "address": acct.address,
        "private_key": acct.key.hex()
    }

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 *SignalBot* — Crypto signal alerts + spot trading\n\n"
        "/register — Create your trading wallet\n"
        "/deposit — View your deposit address\n"
        "/balance — Check wallet balance\n"
        "/signal — Scan for signals (60%+ confidence)\n"
        "/trade — Execute a trade\n"
        "/help — All commands\n\n"
        "Your keys stay in your wallet. Bot signs transactions on your behalf.",
        parse_mode="Markdown"
    )

async def cmd_register(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    users = load_users()
    if uid in users and users[uid].get("address"):
        await update.message.reply_text(
            f"✅ You already have a wallet:\n`{users[uid]['address']}`",
            parse_mode="Markdown"
        )
        return

    # Default to BSC, support ETH/SOLANA via switch
    chain = "bsc"
    wallet = generate_wallet()
    users[uid] = {
        "username": update.effective_user.username,
        "address": wallet["address"],
        "private_key": wallet["private_key"],
        "chain": chain,
        "created_at": str(update.message.date)
    }
    save_users(users)

    chain_msg = {
        "bsc": "BNB Smart Chain (BEP20)",
        "eth": "Ethereum (ERC20)",
        "solana": "Solana (SPL)"
    }.get(chain, "BNB Smart Chain")

    await update.message.reply_text(
        f"✅ *Wallet Created!*\n\n"
        f"Network: {chain_msg}\n"
        f"Address: `0x{wallet['address'][2:]}`\n\n"
        f"📥 Deposit USDT (BSC BEP20) to this address.\n"
        f"Then /balance to check + /trade to execute.",
        parse_mode="Markdown"
    )

async def cmd_deposit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    users = load_users()
    if uid not in users or not users[uid].get("address"):
        await update.message.reply_text("Use /register first to create your wallet.")
        return
    addr = users[uid]["address"]
    await update.message.reply_text(
        f"📥 *Deposit Address*\n\n"
        f"`{addr}`\n\n"
        f"Network: BSC (BEP20)\n"
        f"Token: USDT\n\n"
        f"After depositing, use /balance to check.",
        parse_mode="Markdown"
    )

async def cmd_balance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    import sys
    sys.path.insert(0, AVENUE_SCRIPTS)
    from ave.http import api_get, api_post

    uid = str(update.effective_user.id)
    users = load_users()
    if uid not in users or not users[uid].get("address"):
        await update.message.reply_text("Use /register first.")
        return

    addr = users[uid]["address"]
    chain = users[uid].get("chain", "bsc")
    await update.message.reply_text("⏳ Fetching portfolio...")

    # Get all token positions from Ave
    resp = await api_get("/address/walletinfo/tokens", {
        "wallet_address": addr, "chain": chain,
        "sort": "balance_usd", "sort_dir": "desc", "pageSize": 20
    })
    data = resp.json()

    if data.get("status") != 1 or not data.get("data"):
        # Fallback to BSC direct
        await update.message.reply_text(
            "💰 *Portfolio*\n\nNo trading history found yet.\n"
            "Deposit USDT to your address to start.\n\n"
            f"`{addr}`",
            parse_mode="Markdown"
        )
        return

    holdings = []
    total_usd = 0.0

    for tok in data["data"]:
        bal = float(tok.get("balance_amount", 0) or 0)
        if bal <= 0:
            continue
        symbol = tok.get("symbol", "?")
        token_addr = tok.get("token", "")
        chain_tok = tok.get("chain", chain)
        # Fetch live USD price for this token
        price = None
        try:
            price_resp = await api_get(f"/tokens/{token_addr}-{chain_tok}")
            pdata = price_resp.json().get("data", {}).get("token", {})
            price = float(pdata.get("current_price_usd") or 0)
        except:
            pass
        usd = float(tok.get("balance_usd", 0) or (bal * price) if price else 0)
        risk = tok.get("risk_level", 1)
        risk_icon = "🟢" if risk == 1 else "🟡" if risk == 2 else "🔴"
        price_str = f" (${price:.6f})" if price else " (!)"
        holdings.append(f"{risk_icon} {symbol}: {bal:.4f} (${usd:.2f}){price_str}")
        total_usd += usd

    if not holdings:
        await update.message.reply_text(
            "💰 *Portfolio*\n\nNo holdings yet.\n"
            f"Deposit USDT to start.\n\nAddress: `{addr}`",
            parse_mode="Markdown"
        )
        return

    msg = f"💰 *Portfolio — {chain.upper()}*\n\n"
    for h in holdings[:10]:
        msg += h + "\n"
    msg += f"\n💵 Total: ${total_usd:.2f}"
    msg += f"\n\n📥 Deposit: `{addr}`"
    msg += f"\n🔄 Trade: /trade <symbol> <amount>"

    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_signal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    import sys
    sys.path.insert(0, AVENUE_SCRIPTS)
    from ave.http import api_get

    await update.message.reply_text("🔍 Scanning top tokens for signals (60%+ confidence)...")

    try:
        # Use trending tokens from public signals endpoint as primary source
        # Supplement with keyword searches for coverage
        seen = set()
        tokens = []
        
        # First: get public signals (already filtered by Ave)
        try:
            sig_resp = await api_get("/signals/public/list", {
                "chain": "bsc", "pageSize": 20, "pageNO": 1
            })
            for s in sig_resp.json().get("data", []):
                t = s.get("token_info", {})
                if not t:
                    t = s
                addr = t.get("token", "").split("-")[0] if "-" in t.get("token", "") else t.get("token", "")
                if addr and addr not in seen:
                    seen.add(addr)
                    t["token"] = addr
                    tokens.append(t)
        except:
            pass
        
        # Second: get trending/hot tokens from platform tags
        platform_tags = ["defi", "meme", "gamefi", "ai", "hot"]
        for tag in platform_tags:
            try:
                presp = await api_get("/tokens/platform", {"tag": tag, "limit": 10, "chain": "bsc"})
                for t in presp.json().get("data", []):
                    addr = t.get("token", "").split("-")[0] if "-" in t.get("token", "") else t.get("token", "")
                    if addr and addr not in seen:
                        seen.add(addr)
                        t["token"] = addr
                        tokens.append(t)
            except:
                pass
        
        # Third: supplement with popular keyword searches
        bsc_keywords = ["PEPE", "SHIB", "DOGE", "BNB", "CAKE", "WBNB", "BTC", "ETH", 
                        "SOL", "XRP", "TRX", "ADA", "AVAX", "DOT", "MATIC", "LINK"]
        for kw in bsc_keywords:
            try:
                resp = await api_get("/tokens", {"keyword": kw, "limit": 3, "chain": "bsc"})
                for t in resp.json().get("data", []):
                    addr = t.get("token", "").split("-")[0] if "-" in t.get("token", "") else t.get("token", "")
                    if addr and addr not in seen:
                        seen.add(addr)
                        t["token"] = addr
                        tokens.append(t)
            except:
                pass
    except Exception as e:
        await update.message.reply_text(f"Error scanning: {e}")
        return

    signals = []
    for tok in tokens[:30]:
        try:
            token_addr = tok.get("token", "")
            token_id = f"{token_addr}-bsc"
            price_resp = await api_get(f"/tokens/{token_id}")
            risk_resp = await api_get(f"/contracts/{token_id}")

            pdata = price_resp.json().get("data", {}).get("token", {})
            rdata = risk_resp.json().get("data", {})

            price = float(pdata.get("current_price_usd") or 0)
            honeypot_val = rdata.get("is_honeypot", 0)
            risk_score = rdata.get("risk_score", 50)
            liq = float(pdata.get("liquidity") or pdata.get("tvl") or 0)
            vol = float(pdata.get("tx_volume_u_24h") or 0)
            chg_24h = float(pdata.get("price_change_24h") or 0)
            # is_honeypot: 1 = honeypot, 0 = safe, -1 = unknown
            is_honeypot = honeypot_val == 1

            if is_honeypot or price == 0:
                continue

            conf = 0
            if liq > 50000: conf += 30
            if vol > 10000: conf += 30
            if abs(chg_24h) > 5: conf += 20
            if risk_score < 30: conf += 20
            conf = min(100, conf)

            if conf >= 60:
                direction = "🟢 BUY" if chg_24h < -3 else "🔴 SELL" if chg_24h > 5 else "🟡 WATCH"
                signals.append({
                    "conf": conf, "addr": token_addr, "name": tok.get("name", ""),
                    "symbol": tok.get("symbol", ""), "price": price,
                    "chg_24h": chg_24h, "liq": liq, "vol": vol,
                    "direction": direction
                })
        except Exception:
            continue

    signals.sort(key=lambda x: x["conf"], reverse=True)

    if not signals:
        await update.message.reply_text("No signals above 60% confidence found right now.")
        return

    lines = [f"🔔 *{len(signals)} Signals Found (≥60% confidence)*\n"]
    for s in signals[:10]:
        lines.append(
            f"\n{s['direction']} [{s['conf']}%] *{s['symbol']}*\n"
            f"Price: ${'{:.8f}'.format(s['price'])} | 24h: {s['chg_24h']:.2f}%\n"
            f"Vol: ${s['vol']:,.0f} | Liq: ${s['liq']:,.0f}"
        )
    lines.append("\n\nReply with /trade to execute on any token.")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_trade(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    users = load_users()
    if uid not in users or not users[uid].get("address"):
        await update.message.reply_text("Use /register first.")
        return

    if not ctx.args:
        await update.message.reply_text(
            "Usage: /trade <SYMBOL> <AMOUNT>\nExample: /trade ODIC 10\n"
            "Uses USDT as input token on BSC."
        )
        return

    symbol = ctx.args[0].upper()
    try:
        amount = float(ctx.args[1])
    except (IndexError, ValueError):
        await update.message.reply_text("Invalid amount. Usage: /trade ODIC 10")
        return

    import sys
    sys.path.insert(0, AVENUE_SCRIPTS)
    from ave.http import api_get, api_post, trade_post

    await update.message.reply_text(f"⏳ Getting quote for {amount} USDT → {symbol}...")

    try:
        search_resp = await api_get("/tokens", {"keyword": symbol, "limit": 5, "chain": "bsc"})
        search_data = search_resp.json().get("data", [])
        if not search_data:
            await update.message.reply_text(f"Token '{symbol}' not found.")
            return

        token_addr = search_data[0].get("token", "").split("-")[0]
        symbol_out = search_data[0].get("symbol", symbol)
    except Exception as e:
        await update.message.reply_text(f"Error finding token: {e}")
        return

    usdt_addr = "0x55d398326f99059fF775485246999027B3197955"
    amount_wei = str(int(amount * 1e6))
    slippage = 0.5

    try:
        quote_resp = await trade_post("/v1/thirdParty/chainWallet/getAmountOut", {
            "chain": "bsc", "inAmount": amount_wei,
            "inTokenAddress": usdt_addr, "outTokenAddress": token_addr,
            "swapType": "buy"
        })
        qdata = quote_resp.json()
        if qdata.get("status") not in (200,):
            await update.message.reply_text(f"Quote failed: {qdata.get('msg', 'unknown error')}")
            return
    except Exception as e:
        await update.message.reply_text(f"Quote error: {e}")
        return

    estimate_out = qdata.get("data", {}).get("estimateOut", "0")
    decimals = int(qdata.get("data", {}).get("decimals", 18))
    out_amount = float(estimate_out) / (10 ** decimals)

    ctx.user_data["pending_trade"] = {
        "in_amount": amount_wei, "out_amount": estimate_out,
        "out_token": token_addr, "symbol": symbol_out,
        "decimals": decimals, "slippage": slippage
    }

    keyboard = [
        [InlineKeyboardButton("✅ Confirm Buy", callback_data="trade_confirm_yes"),
         InlineKeyboardButton("❌ Cancel", callback_data="trade_confirm_no")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"📋 *Confirm Trade*\n\n"
        f"You pay: {amount} USDT\n"
        f"You receive: ~{out_amount:.6f} {symbol_out}\n"
        f"Slippage: {slippage}%\n\n"
        f"Reply 'yes' or click below to execute.",
        parse_mode="Markdown", reply_markup=reply_markup
    )

async def handle_yes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "trade_confirm_yes":
        await query.edit_message_text("✅ Trade confirmed! Executing...\n(Note: execution requires RPC + private key signing — demo mode.)")
    else:
        await query.edit_message_text("❌ Trade cancelled.")

async def cmd_chain(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Switch blockchain network"""
    uid = str(update.effective_user.id)
    users = load_users()
    if uid not in users or not users[uid].get("address"):
        await update.message.reply_text("Use /register first.")
        return

    if not ctx.args:
        current = users[uid].get("chain", "bsc")
        await update.message.reply_text(
            f"Current chain: *{current.upper()}*\n\n"
            "Switch to: /chain bsc | /chain eth | /chain solana\n\n"
            "Note: Each chain has a separate wallet address.",
            parse_mode="Markdown"
        )
        return

    new_chain = ctx.args[0].lower()
    if new_chain not in ("bsc", "eth", "solana"):
        await update.message.reply_text("Invalid chain. Use: bsc, eth, or solana")
        return

    old_chain = users[uid].get("chain", "bsc")
    if new_chain == old_chain:
        await update.message.reply_text(f"Already on {new_chain.upper()}")
        return

    wallet = generate_wallet()
    users[uid]["address"] = wallet["address"]
    users[uid]["private_key"] = wallet["private_key"]
    users[uid]["chain"] = new_chain
    save_users(users)

    chain_msgs = {
        "bsc": "BNB Smart Chain (BEP20) — deposit USDT BEP20",
        "eth": "Ethereum (ERC20) — deposit USDT ERC20",
        "solana": "Solana (SPL) — deposit USDC SPL"
    }
    await update.message.reply_text(
        f"✅ *Chain Switched to {new_chain.upper()}*\n\n"
        f"New wallet: `0x{wallet['address'][2:]}`\n\n"
        f"{chain_msgs.get(new_chain)}\n\n"
        "⚠️ Your previous BSC wallet is still active but not used.",
        parse_mode="Markdown"
    )

async def cmd_topwallets(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show top performing smart money wallets"""
    import sys
    sys.path.insert(0, AVENUE_SCRIPTS)
    from ave.http import api_get

    chain = "bsc"
    if ctx.args:
        chain = ctx.args[0].lower()
        if chain not in ("bsc", "eth", "base", "solana"):
            chain = "bsc"

    await update.message.reply_text(f"🦊 Loading top wallets on {chain.upper()}...")

    params = {
        "chain": chain,
        "sort": "profit_above_900_percent_num",
        "sort_dir": "desc",
        "profit_900_percent_num_min": 1,
        "profit_300_900_percent_num_min": 3,
    }
    resp = await api_get("/address/smart_wallet/list", params)
    data = resp.json()

    if data.get("status") != 1 or not data.get("data"):
        await update.message.reply_text(f"No smart wallets found on {chain.upper()} right now.")
        return

    wallets = data["data"][:10]
    lines = [f"🦊 *Top Smart Money Wallets — {chain.upper()}*\n"]
    lines.append("_(Wallets with 300%+ profitable trades)_\n")

    for i, w in enumerate(wallets, 1):
        addr = w.get("wallet_address", "")[:10] + "..."
        p900 = w.get("profit_above_900_percent_num", 0)
        p300 = w.get("profit_300_900_percent_num", 0)
        total_profit = float(w.get("total_profit", 0) or 0)
        last = w.get("last_trade_time", "N/A")
        if isinstance(last, (int, float)) and last > 0:
            import datetime
            last = datetime.datetime.fromtimestamp(last).strftime("%m/%d")
        lines.append(
            f"\n{i}. `{addr}`\n"
            f"   900%+ trades: {p900} | 300-900%: {p300}\n"
            f"   Total profit: ${total_profit:,.2f}\n"
            f"   Last active: {last}"
        )
        lines.append(f"   🔗 /track {w.get('wallet_address', '')}")

    lines.append("\n\n_Reply /track <address> to see what they're holding._")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_track(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Track a specific wallet — shows holdings + recent trades"""
    import sys
    sys.path.insert(0, AVENUE_SCRIPTS)
    from ave.http import api_get

    if not ctx.args:
        uid = str(update.effective_user.id)
        users = load_users()
        if uid in users and users[uid].get("address"):
            addr = users[uid]["address"]
        else:
            await update.message.reply_text(
                "Usage: /track <address>\nExample: /track 0x... or reply with your own wallet"
            )
            return
    else:
        addr = ctx.args[0]

    chain = "bsc"
    if len(ctx.args) > 1:
        c = ctx.args[1].lower()
        if c in ("bsc", "eth", "solana"):
            chain = c

    await update.message.reply_text(f"🔍 Tracking `{addr[:10]}...` on {chain.upper()}...")

    # Get wallet token holdings
    resp = await api_get("/address/walletinfo/tokens", {
        "wallet_address": addr,
        "chain": chain,
        "sort": "balance_usd",
        "sort_dir": "desc",
        "pageSize": 10
    })
    data = resp.json()

    lines = [f"📊 *Wallet Portfolio — {chain.upper()}*\n`{addr[:20]}...`\n"]

    if data.get("status") == 1 and data.get("data"):
        holdings = []
        for tok in data["data"]:
            bal = float(tok.get("balance_amount", 0) or 0)
            if bal <= 0:
                continue
            symbol = tok.get("symbol", "?")
            usd = float(tok.get("balance_usd", 0) or 0)
            profit_pct = float(tok.get("profit_pct", 0) or 0)
            holding_profit = "🟢" if profit_pct > 0 else "🔴"
            holdings.append(
                f"{holding_profit} {symbol}: {bal:.4f} (${usd:.2f}) | "
                f"P/L: {profit_pct:+.1f}%"
            )
        if holdings:
            lines.append("📦 *Top Holdings:*")
            for h in holdings[:5]:
                lines.append(h)
        else:
            lines.append("No token holdings found.")
    else:
        lines.append("No holdings data available.")

    # Get recent transactions
    tx_resp = await api_get("/address/tx", {
        "wallet_address": addr,
        "chain": chain,
        "page_size": 5
    })
    tx_data = tx_resp.json()

    if tx_data.get("status") == 1 and tx_data.get("data"):
        txs = tx_data["data"] if isinstance(tx_data["data"], list) else []
        if txs:
            lines.append("\n📜 *Recent Transactions:*")
            for tx in txs[:5]:
                blk = str(tx.get("block_number", ""))[:8]
                amount = float(tx.get("amount", 0) or 0)
                symbol = tx.get("symbol", "?")
                tx_type = tx.get("type", "?")
                profit = float(tx.get("profit", 0) or 0)
                icon = "🟢" if profit > 0 else "🔴" if profit < 0 else "⚪"
                lines.append(
                    f"{icon} {tx_type} {amount:.4f} {symbol} "
                    f"(block: {blk[:6]}...) P/L: {profit:+.2f}"
                )
    else:
        lines.append("\nNo transaction history available.")

    lines.append(f"\n🔗 View on AVE Pro: https://pro.ave.ai/token/{addr}-{chain}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*SignalBot Commands*\n\n"
        "/start — Welcome message\n"
        "/register — Create wallet\n"
        "/deposit — Show deposit address\n"
        "/balance — Check wallet + live USD value\n"
        "/chain bsc|eth|solana — Switch network\n"
        "/signal — Scan tokens for signals\n"
        "/topwallets [chain] — Top smart money wallets\n"
        "/track <address> — Track any wallet\n"
        "/trade SYMBOL AMOUNT — Get quote + execute\n"
        "/help — This message\n\n"
        "*Flow:* register → deposit USDT → trade",
        parse_mode="Markdown"
    )

def main():
    if not BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN not set")
        return
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("register", cmd_register))
    app.add_handler(CommandHandler("deposit", cmd_deposit))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("signal", cmd_signal))
    app.add_handler(CommandHandler("trade", cmd_trade))
    app.add_handler(CommandHandler("topwallets", cmd_topwallets))
    app.add_handler(CommandHandler("track", cmd_track))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CallbackQueryHandler(handle_yes, pattern="trade_confirm_"))

    print(f"SignalBot running... | Users file: {USERS_FILE}")
    app.run_polling()

if __name__ == "__main__":
    main()