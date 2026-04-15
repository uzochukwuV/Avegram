import asyncio
import datetime
import json
import urllib.request

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ave.http import api_get

from ..db import (
    load_users,
    save_users,
    load_trades,
    save_trades,
    load_copy_trades,
    save_copy_trades,
    db_insert_signal_history,
    db_log_error,
)
from ..proxy import proxy_get, proxy_post, send_swap_order
from ..utils import get_bsc_address, clear_user_session_keys
from .menu import show_main_menu, auto_link_wallet

async def cmd_start(u, ctx):
    await show_main_menu(u.message, u.effective_user.id, username=u.effective_user.username)

async def cmd_register(u, ctx, is_callback=False):
    uid = str(u.effective_user.id)
    username = u.effective_user.username
    msg = u.callback_query.message if is_callback else u.message
    kb = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")]]
    rm = InlineKeyboardMarkup(kb)

    if auto_link_wallet(uid, username=username):
        users = load_users()
        w = users[uid]
        bsc_addr = next((a["address"] for a in w.get("address_list", []) if a["chain"] == "bsc"), "N/A")
        text = f"✅ Proxy wallet linked and ready!\n\nBSC: `{bsc_addr}`\n\nThis wallet holds your funded USDT. Check Portfolio to see your holdings."
        if is_callback:
            await msg.edit_text(text, reply_markup=rm, parse_mode="Markdown")
        else:
            await msg.reply_text(text, reply_markup=rm, parse_mode="Markdown")
        return

    users = load_users()
    if not is_callback:
        await msg.reply_text("No existing wallet found. Creating new one...")

    r = proxy_post("/v1/thirdParty/user/generateWallet", {"assetsName": "user_" + uid[-8:], "returnMnemonic": False})
    if r.get("status") not in (200, 0) or not r.get("data"):
        text = "Registration failed: " + str(r.get("msg", ""))
        if is_callback:
            await msg.edit_text(text, reply_markup=rm)
        else:
            await msg.reply_text(text, reply_markup=rm)
        return
    d = r["data"]
    users[uid] = {"assets_id": d["assetsId"], "address_list": d.get("addressList", []), "username": username, "chain": "bsc"}
    save_users(users)
    bsc_addr = next((a["address"] for a in d.get("addressList", []) if a["chain"] == "bsc"), "N/A")
    text = f"Proxy wallet created!\n\nBSC: `{bsc_addr}`\n\nDeposit USDT BEP20 to this address, then check Portfolio."
    if is_callback:
        await msg.edit_text(text, reply_markup=rm, parse_mode="Markdown")
    else:
        await msg.reply_text(text, reply_markup=rm, parse_mode="Markdown")

async def cmd_deposit(u, ctx, is_callback=False):
    uid = str(u.effective_user.id)
    auto_link_wallet(uid, username=u.effective_user.username)
    users = load_users()
    msg = u.callback_query.message if is_callback else u.message
    kb = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")]]
    rm = InlineKeyboardMarkup(kb)

    if uid not in users or not users[uid].get("assets_id"):
        text = "Use /register first"
        if is_callback:
            await msg.edit_text(text, reply_markup=rm)
        else:
            await msg.reply_text(text, reply_markup=rm)
        return
    addr = next((a["address"] for a in users[uid].get("address_list", []) if a["chain"] == "bsc"), "N/A")
    text = "Deposit Address (BSC BEP20)\n\n`" + addr + "`\n\nDeposit USDT to this address"
    if is_callback:
        await msg.edit_text(text, reply_markup=rm, parse_mode="Markdown")
    else:
        await msg.reply_text(text, reply_markup=rm, parse_mode="Markdown")

async def cmd_balance(u, ctx, is_callback=False):
    uid = str(u.effective_user.id)
    auto_link_wallet(uid, username=u.effective_user.username)
    users = load_users()
    msg = u.callback_query.message if is_callback else u.message
    kb = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="cb_balance")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")]
    ]
    rm = InlineKeyboardMarkup(kb)

    if uid not in users or not users[uid].get("assets_id"):
        text = "Use /register first"
        if is_callback:
            await msg.edit_text(text, reply_markup=rm)
        else:
            await msg.reply_text(text, reply_markup=rm)
        return

    text_loading = "Fetching on-chain portfolio..."
    if is_callback:
        await msg.edit_text(text_loading)
    else:
        msg = await msg.reply_text(text_loading)

    addr_list = users[uid].get("address_list", [])
    bsc_addr = next((a["address"] for a in addr_list if a.get("chain") == "bsc" and a.get("address", "").startswith("0x")), None)
    if not bsc_addr and addr_list:
        bsc_addr = next((a["address"] for a in addr_list if a.get("address", "").startswith("0x")), None)
    if not bsc_addr:
        await msg.edit_text("No BSC wallet address found. Use /register to create one.", reply_markup=rm)
        return

    r = proxy_get("/address/walletinfo/tokens", {
        "wallet_address": bsc_addr,
        "chain": "bsc",
        "sort": "balance_usd",
        "sort_dir": "desc",
        "pageSize": "20"
    })
    if r.get("status") != 1 or not r.get("data"):
        await msg.edit_text("No on-chain holdings found for this wallet.", reply_markup=rm)
        return

    tokens = r["data"]
    total_usd = 0.0
    trades = load_trades()
    user_trades = trades.get(uid, {})

    lines = ["📊 *My Portfolio*\n"]
    for tok in tokens[:10]:
        sym = tok.get("symbol", "?")
        bal = float(tok.get("balance_amount", 0) or 0)
        value = float(tok.get("balance_usd", 0) or 0)
        total_usd += value
        tok_addr = (tok.get("token") or "").split("-")[0]

        unreal_pnl = float(tok.get("unrealized_profit", 0) or 0)
        pnl_pct = float(tok.get("total_profit_ratio", 0) or 0)
        pnl_sign = "🟢 +" if unreal_pnl >= 0 else "🔴 "

        lines.append(f"*{sym}*: {round(bal, 4)}")
        lines.append(f"  Val: ${value:.2f} | P/L: {pnl_sign}{abs(unreal_pnl):.2f} ({pnl_pct:+.1f}%)")

        if tok_addr in user_trades and user_trades[tok_addr].get("status") == "active":
            tk = user_trades[tok_addr]
            lines.append(f"  ⚡ TP: +{tk['tp_pct']}% | SL: {tk['sl_pct']}%")
        lines.append("")

    if total_usd == 0:
        await msg.edit_text("No holdings with balance > 0.", reply_markup=rm)
        return

    lines.append(f"💰 *Total Value*: ${total_usd:.2f}")
    await msg.edit_text("\n".join(lines), reply_markup=rm, parse_mode="Markdown")

async def cmd_signal(u, ctx, is_callback=False):
    msg = u.callback_query.message if is_callback else u.message
    kb = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")]]
    rm = InlineKeyboardMarkup(kb)

    text_loading = "Scanning for signals (60%+ confidence)..."
    if is_callback:
        await msg.edit_text(text_loading)
    else:
        msg = await msg.reply_text(text_loading)

    tokens = []
    seen = set()
    try:
        for chain in ["bsc", "solana"]:
            url = f"https://data.ave-api.xyz/v2/signals/public/list?chain={chain}&pageSize=20&pageNO=1"
            req = urllib.request.Request(url, headers={"X-API-KEY": ""})
            r = await asyncio.get_event_loop().run_in_executor(None, lambda u=url: urllib.request.urlopen(req, timeout=10))
            d = json.loads(r.read())
            for s in d.get("data", []):
                ta = s.get("token", "")
                chain_tok = s.get("chain", chain)
                a = ta.split("-")[0] if "-" in ta else ta
                if a and a not in seen:
                    seen.add(a)
                    tokens.append({"addr": a, "chain": chain_tok, "sym": s.get("symbol", "?"), "name": s.get("name", "")})
    except Exception:
        pass

    for kw in ["PEPE", "SHIB", "DOGE", "BNB", "CAKE", "WBNB", "BTCB", "ETH", "SOL", "XRP"]:
        try:
            url = f"https://data.ave-api.xyz/v2/tokens?keyword={kw}&limit=3&chain=bsc"
            req = urllib.request.Request(url, headers={"X-API-KEY": ""})
            r = await asyncio.get_event_loop().run_in_executor(None, lambda u=url: urllib.request.urlopen(req, timeout=10))
            d = json.loads(r.read())
            for t in d.get("data", []):
                a = (t.get("token") or "").split("-")[0]
                if a and a not in seen:
                    seen.add(a)
                    tokens.append({"addr": a, "chain": "bsc", "sym": t.get("symbol", "?"), "name": t.get("name", "")})
        except Exception:
            pass

    if not tokens:
        await msg.edit_text("No tokens found to scan.", reply_markup=rm)
        return

    signals = []
    for tok in tokens[:25]:
        try:
            ta = tok["addr"]
            chain_tok = tok["chain"]
            tid = f"{ta}-{chain_tok}"
            url1 = f"https://data.ave-api.xyz/v2/tokens/{tid}"
            url2 = f"https://data.ave-api.xyz/v2/contracts/{tid}"
            r1 = await asyncio.get_event_loop().run_in_executor(None, lambda u=url1: urllib.request.urlopen(urllib.request.Request(u, headers={"X-API-KEY": ""}), timeout=10))
            d1 = json.loads(r1.read())
            r2 = await asyncio.get_event_loop().run_in_executor(None, lambda u=url2: urllib.request.urlopen(urllib.request.Request(u, headers={"X-API-KEY": ""}), timeout=10))
            d2 = json.loads(r2.read())
            pd = d1.get("data", {}).get("token", {})
            rd = d2.get("data", {})
            price = float(pd.get("current_price_usd") or 0)
            liq = float(pd.get("liquidity") or pd.get("tvl") or 0)
            vol = float(pd.get("tx_volume_u_24h") or 0)
            chg = float(pd.get("price_change_24h") or 0)
            if rd.get("is_honeypot") == 1 or price == 0:
                continue
            conf = 0
            if liq > 50000:
                conf += 30
            if vol > 10000:
                conf += 30
            if abs(chg) > 5:
                conf += 20
            if rd.get("risk_score", 50) < 30:
                conf += 20
            conf = min(100, conf)
            if conf >= 60:
                signals.append({"conf": conf, "sym": tok["sym"], "price": price, "chg": chg, "liq": liq, "vol": vol, "addr": ta, "chain": chain_tok})
        except Exception:
            continue

    signals.sort(key=lambda x: x["conf"], reverse=True)
    if not signals:
        await msg.edit_text("No signals above 60% confidence right now. Try again later.", reply_markup=rm)
        return

    try:
        expiry_time = int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)).timestamp())
        rows = []
        for s in signals[:25]:
            if s["chg"] < -3:
                signal_type = "buy"
            elif s["chg"] > 5:
                signal_type = "sell"
            else:
                signal_type = "watch"
            rows.append((s["sym"], signal_type, float(s["conf"]), float(s["price"]), "active", None, expiry_time))
        db_insert_signal_history(rows)
    except Exception as e:
        db_log_error("signal_history_insert", e, telegram_id=u.effective_user.id if u and u.effective_user else None, context={"count": len(signals)})

    lines = [f"🔔 {len(signals)} Signals Found (≥60% confidence)\n"]
    buttons = []
    for s in signals[:8]:
        d = "🟢 BUY" if s["chg"] < -3 else "🔴 SELL" if s["chg"] > 5 else "🟡 WATCH"
        lines.append(f"{d} [{s['conf']}%] {s['sym']} | ${round(s['price'], 8)} | 24h:{round(s['chg'],1)}% | Liq:${s['liq']:,.0f}")
        cb_data = f"auto_{s['chain']}_{s['addr'][:10]}_{s['sym']}_{round(s['price'],8)}"
        buttons.append([InlineKeyboardButton(f"⚡ Auto-Trade {s['sym']} (TP/SL)", callback_data=cb_data)])

    lines.append("\n`/trade <sym> <amt>` to execute manually")
    buttons.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")])
    new_rm = InlineKeyboardMarkup(buttons)
    await msg.edit_text("\n".join(lines), reply_markup=new_rm, parse_mode="Markdown")

async def cmd_trade(u, ctx, is_callback=False):
    uid = str(u.effective_user.id)
    auto_link_wallet(uid, username=u.effective_user.username)
    users = load_users()
    msg = u.callback_query.message if is_callback else u.message
    kb = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")]]
    rm = InlineKeyboardMarkup(kb)

    if uid not in users or not users[uid].get("assets_id"):
        text = "Use /register first"
        if is_callback:
            await msg.edit_text(text, reply_markup=rm)
        else:
            await msg.reply_text(text, reply_markup=rm)
        return

    if not ctx.args or len(ctx.args) < 2:
        text = "Usage: `/trade SYMBOL AMOUNT`\n\nExample: `/trade ASTER 10`\n(Interactive trade UI coming soon)"
        if is_callback:
            await msg.edit_text(text, reply_markup=rm, parse_mode="Markdown")
        else:
            await msg.reply_text(text, reply_markup=rm, parse_mode="Markdown")
        return

    sym = ctx.args[0].upper()
    amount = float(ctx.args[1])

    if is_callback:
        await msg.edit_text(f"Looking up {sym}...")
    else:
        msg = await msg.reply_text(f"Looking up {sym}...")

    sr = await api_get("/tokens", {"keyword": sym, "limit": 3, "chain": "bsc"})
    tok_data = sr.json().get("data", [])
    if not tok_data:
        await msg.edit_text("Token " + sym + " not found", reply_markup=rm)
        return

    ta = tok_data[0].get("token", "").split("-")[0]
    aid = users[uid]["assets_id"]
    usdt = "0x55d398326f99059fF775485246999027B3197955"
    await msg.edit_text("Getting quote for " + str(amount) + " USDT to " + sym + "...")

    qr = send_swap_order(uid, "bsc", aid, usdt, ta, int(amount * 1e18), "buy", slippage="500", context={"source": "trade"})
    if qr.get("status") not in (200, 0):
        err_msg = qr.get('msg', 'Unknown Error')
        kb = [[InlineKeyboardButton("🔄 Retry Trade", callback_data=f"retry_bsc_{aid}_{usdt}_{ta}_{int(amount * 1e18)}_buy"), InlineKeyboardButton("❌ Dismiss", callback_data="cb_dismiss")]]
        await msg.edit_text(f"❌ **Swap Failed**\nReason: {err_msg}", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return

    oid = ""
    d = qr.get("data", {})
    if isinstance(d, dict):
        oid = d.get("id", "")
    elif isinstance(d, list) and d:
        oid = d[0].get("id", "") if isinstance(d[0], dict) else str(d[0])

    await msg.edit_text("✅ Swap submitted!\nOrder ID: `" + oid + "`\n\nCheck Portfolio after 30s for confirmation.", reply_markup=rm, parse_mode="Markdown")

async def cmd_topwallets(u, ctx, is_callback=False):
    msg = u.callback_query.message if is_callback else u.message
    kb = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")]]
    rm = InlineKeyboardMarkup(kb)
    chain = "bsc"
    if ctx.args and ctx.args[0].lower() in ("bsc", "eth", "base", "solana"):
        chain = ctx.args[0].lower()

    text_loading = "Loading top wallets on " + chain.upper() + "..."
    if is_callback:
        await msg.edit_text(text_loading)
    else:
        msg = await msg.reply_text(text_loading)

    r = await api_get("/address/smart_wallet/list", {"chain": chain, "sort": "profit_above_900_percent_num", "sort_dir": "desc", "profit_900_percent_num_min": 1, "profit_300_900_percent_num_min": 3})
    d = r.json()
    if d.get("status") != 1 or not d.get("data"):
        await msg.edit_text("No wallets found on " + chain.upper(), reply_markup=rm)
        return
    lines = ["Top Smart Money Wallets - " + chain.upper() + "\n"]
    for i, w in enumerate(d["data"][:8], 1):
        addr = w.get("wallet_address", "")
        addr_short = addr[:10] + "..."
        lines.append(str(i) + ". " + addr_short + " | 900%+: " + str(w.get("profit_above_900_percent_num", 0)) + " | 300-900%: " + str(w.get("profit_300_900_percent_num", 0)))
        lines.append("   `/track " + addr + "`")
    await msg.edit_text("\n".join(lines), reply_markup=rm, parse_mode="Markdown")

async def cmd_track(u, ctx, is_callback=False):
    msg = u.callback_query.message if is_callback else u.message
    kb = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")]]
    rm = InlineKeyboardMarkup(kb)
    if not ctx.args:
        text = "Usage: `/track ADDRESS [chain]`"
        if is_callback:
            await msg.edit_text(text, reply_markup=rm, parse_mode="Markdown")
        else:
            await msg.reply_text(text, reply_markup=rm, parse_mode="Markdown")
        return

    addr = ctx.args[0]
    chain = "bsc"
    if len(ctx.args) > 1 and ctx.args[1].lower() in ("bsc", "eth", "solana"):
        chain = ctx.args[1].lower()

    text_loading = "Tracking " + addr[:10] + "... on " + chain.upper()
    if is_callback:
        await msg.edit_text(text_loading)
    else:
        msg = await msg.reply_text(text_loading)

    r = await api_get("/address/walletinfo/tokens", {"wallet_address": addr, "chain": chain, "sort": "balance_usd", "sort_dir": "desc", "pageSize": 8})
    d = r.json()
    lines = ["Wallet: `" + addr[:20] + "...` | " + chain.upper() + "\n"]
    if d.get("status") == 1 and d.get("data"):
        for t in d["data"][:6]:
            bal = float(t.get("balance_amount", 0) or 0)
            if bal <= 0:
                continue
            lines.append(t.get("symbol", "?") + ": " + str(round(bal, 4)) + " | P/L: " + str(round(float(t.get("profit_pct", 0), 1))) + "%")
    else:
        lines.append("No holdings found")

    cb_data = f"copy_{chain}_{addr}"
    kb2 = [
        [InlineKeyboardButton(f"👥 Copy Trade {addr[:6]}...", callback_data=cb_data)],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")]
    ]
    await msg.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(kb2), parse_mode="Markdown")

async def cmd_help(u, ctx, is_callback=False):
    msg = u.callback_query.message if is_callback else u.message
    kb = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")]]
    rm = InlineKeyboardMarkup(kb)

    text = (
        "📚 *Help / Commands*\n\n"
        "/start · open dashboard\n"
        "/register · create/link proxy wallet\n"
        "/deposit · show USDT deposit address\n"
        "/balance · portfolio\n"
        "/signal · scan signals\n"
        "/trade SYMBOL AMOUNT · buy token with USDT\n"
        "/topwallets [chain]\n"
        "/track ADDRESS [chain]\n"
        "/quote SYMBOL AMOUNT\n"
    )
    if is_callback:
        await msg.edit_text(text, reply_markup=rm, parse_mode="Markdown")
    else:
        await msg.reply_text(text, reply_markup=rm, parse_mode="Markdown")

async def cmd_quote(u, ctx):
    if not ctx.args or len(ctx.args) < 2:
        await u.message.reply_text("Usage: /quote SYMBOL AMOUNT (amount in USDT)")
        return

    sym = ctx.args[0].upper()
    amount = float(ctx.args[1])

    sr = await api_get("/tokens", {"keyword": sym, "limit": 5, "chain": "bsc"})
    tok_data = sr.json().get("data", [])
    if not tok_data:
        sr = await api_get("/tokens", {"keyword": sym, "limit": 5, "chain": "eth"})
        tok_data = sr.json().get("data", [])

    if not tok_data:
        await u.message.reply_text(f"Token '{sym}' not found on BSC or ETH.")
        return

    ta = None
    tok_chain = "bsc"
    for t in tok_data:
        if t.get("symbol", "").upper() == sym.upper():
            ta = t.get("token", "").split("-")[0]
            tok_chain = t.get("chain", "bsc")
            break
    if not ta:
        ta = tok_data[0].get("token", "").split("-")[0]
        tok_chain = tok_data[0].get("chain", "bsc")

    usdt_addr = "0x55d398326f99059fF775485246999027B3197955"
    usdt_addr_eth = "0xdAC17F958D2ee523a2206206994597C13D831ec7"

    in_token = usdt_addr_eth if tok_chain == "eth" else usdt_addr
    chain = tok_chain

    in_amount_smallest = str(int(amount * 1e18))
    try:
        qr = proxy_post("/v1/thirdParty/chainWallet/getAmountOut", {
            "chain": chain,
            "inAmount": in_amount_smallest,
            "inTokenAddress": in_token,
            "outTokenAddress": ta,
        })
    except Exception as e:
        await u.message.reply_text(f"Quote request failed: {e}")
        return

    if qr.get("status") not in (200, 0) or not qr.get("data"):
        await u.message.reply_text(f"Quote failed: {qr.get('msg', 'Unknown error')}")
        return

    d = qr["data"]
    estimate_out = int(d.get("estimateOut", 0))
    spender = d.get("spender", "N/A")
    token_amount = estimate_out / (10 ** 6)
    price_usd = amount / token_amount if token_amount > 0 else 0

    lines = [
        f"💱 Quote: {amount} USDT → {sym}",
        f"Chain: {chain.upper()}",
        f"Estimated {sym} out: {token_amount:,.6f}",
        f"Price: ${price_usd:,.6f} per {sym}",
        f"Token: `{ta}`",
        f"Spender: `{spender[:20]}...`" if len(spender) > 20 else f"Spender: `{spender}`",
        "",
        f"Link: https://pro.ave.ai/token/{ta}-{chain}"
    ]
    await u.message.reply_text("\n".join(lines), parse_mode="Markdown")

