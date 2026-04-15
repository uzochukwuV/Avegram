"""SignalBot v2 - Ave proxy wallet integration"""
import os, json, asyncio, sys, urllib.request, urllib.parse, base64, datetime, hmac, hashlib
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

AVENUE_SCRIPTS = "/home/workspace/ave-cloud-skill/scripts"
if not os.path.exists(AVENUE_SCRIPTS):
    AVENUE_SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ave-cloud-skill", "scripts")
sys.path.insert(0, AVENUE_SCRIPTS)

from avegram.config import BOT_TOKEN, AVE_API_KEY
from avegram.db import (
    db_init,
    load_users,
    save_users,
    load_trades,
    save_trades,
    load_copy_trades,
    save_copy_trades,
    db_log_error,
    db_insert_signal_history,
    db_upsert_token_meta,
)
from avegram.proxy import proxy_get, proxy_post, send_swap_order
from avegram.utils import clear_user_session_keys, get_bsc_address
from avegram.handlers.menu import show_main_menu, auto_link_wallet
from avegram.monitors.tpsl import monitor_tp_sl as monitor_tp_sl_impl
from avegram.monitors.copytrade import monitor_copy_trades as monitor_copy_trades_impl

async def handle_callback(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = u.callback_query
    await query.answer()
    data = query.data
    uid = u.effective_user.id

    if data == "cb_menu":
        users = load_users()
        if str(uid) in users and "state" in users[str(uid)]:
            users[str(uid)]["state"] = None
            clear_user_session_keys(users, str(uid), ["auto_trade", "copy_trade", "withdraw_address"])
            save_users(users)
        await show_main_menu(query.message, uid, edit=True, username=u.effective_user.username)
    elif data == "cb_register":
        await cmd_register(u, ctx, is_callback=True)
    elif data == "cb_balance":
        await cmd_balance(u, ctx, is_callback=True)
    elif data == "cb_signal":
        await cmd_signal(u, ctx, is_callback=True)
    elif data == "cb_topwallets":
        await cmd_topwallets(u, ctx, is_callback=True)
    elif data == "cb_help":
        await cmd_help(u, ctx, is_callback=True)
    elif data == "cb_deposit":
        await cmd_deposit(u, ctx, is_callback=True)
    elif data == "cb_withdraw":
        auto_link_wallet(str(uid), username=u.effective_user.username)
        users = load_users()
        uid_str = str(uid)
        users[uid_str]["state"] = "awaiting_withdraw_address"
        save_users(users)
        keyboard = [[InlineKeyboardButton("🔙 Cancel", callback_data="cb_menu")]]
        await query.message.edit_text("💸 *Withdraw Funds*\n\nPlease paste the destination BSC address:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    elif data == "cb_trade":
        auto_link_wallet(str(uid), username=u.effective_user.username)
        users = load_users()
        uid_str = str(uid)
        users[uid_str]["state"] = "awaiting_trade_input"
        save_users(users)
        keyboard = [[InlineKeyboardButton("🔙 Cancel", callback_data="cb_menu")]]
        await query.message.edit_text("💱 *Trade Token*\n\nPlease enter the SYMBOL and AMOUNT separated by space.\nExample: `PEPE 10` (to buy $10 worth of PEPE)", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    elif data == "cb_dismiss":
        await query.message.delete()
    elif data.startswith("retry_"):
        parts = data.split("_")
        if len(parts) >= 7:
            _, chain, aid, in_token, out_token, in_amount, swap_type = parts
            await query.message.edit_text("🔄 Retrying trade...", reply_markup=None)
            qr = send_swap_order(uid, chain, aid, in_token, out_token, in_amount, swap_type, slippage="1500", context={"source": "retry"})
            if qr.get("status") in (200, 0):
                oid = qr.get('data', {}).get('id', '')
                await query.message.edit_text(f"✅ **Retry Successful!**\nOrder ID: `{oid}`", parse_mode="Markdown")
            else:
                err_msg = qr.get('msg', 'Unknown Error')
                kb = [[InlineKeyboardButton("🔄 Retry Again", callback_data=data), InlineKeyboardButton("❌ Dismiss", callback_data="cb_dismiss")]]
                await query.message.edit_text(f"❌ **Retry Failed**\nReason: {err_msg}", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    elif data.startswith("copy_"):
        parts = data.split("_")
        if len(parts) >= 3:
            chain = parts[1]
            addr = parts[2]
            users = load_users()
            uid_str = str(uid)
            users[uid_str]["state"] = "awaiting_copy_pct"
            users[uid_str]["copy_trade"] = {"chain": chain, "addr": addr}
            save_users(users)
            keyboard = [[InlineKeyboardButton("🔙 Cancel", callback_data="cb_menu")]]
            await query.message.edit_text(f"👥 *Copy Trade Setup*\nTarget: `{addr}`\n\nEnter the **percentage** of your USDT balance to use per trade (e.g., 10 for 10%):", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    elif data.startswith("auto_"):
        parts = data.split("_")
        if len(parts) >= 5:
            chain = parts[1]
            addr_short = parts[2]
            sym = parts[3]
            price = parts[4]
            users = load_users()
            uid_str = str(uid)
            users[uid_str]["state"] = "awaiting_auto_trade_amount"
            users[uid_str]["auto_trade"] = {"chain": chain, "sym": sym, "price": price, "addr_short": addr_short}
            save_users(users)
            keyboard = [[InlineKeyboardButton("🔙 Cancel", callback_data="cb_menu")]]
            await query.message.edit_text(f"⚡ *Auto-Trade {sym}*\n\nEnter amount of USDT to invest:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def handle_text(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = str(u.effective_user.id)
    users = load_users()
    if uid not in users or "state" not in users[uid]:
        return
        
    state = users[uid]["state"]
    text = u.message.text.strip()
    kb = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")]]
    rm = InlineKeyboardMarkup(kb)
    
    if state == "awaiting_withdraw_address":
        users[uid]["withdraw_address"] = text
        users[uid]["state"] = "awaiting_withdraw_amount"
        save_users(users)
        await u.message.reply_text(f"Address `{text}` saved.\n\nNow enter the amount of USDT to withdraw:", reply_markup=rm, parse_mode="Markdown")
        
    elif state == "awaiting_withdraw_amount":
        users[uid]["state"] = None
        save_users(users)
        try:
            amount = float(text)
            # Placeholder for actual withdraw logic
            await u.message.reply_text(f"✅ Withdrawal of {amount} USDT to `{users[uid]['withdraw_address']}` initiated! (Mock)", reply_markup=rm, parse_mode="Markdown")
            users = load_users()
            clear_user_session_keys(users, uid, ["withdraw_address"])
            save_users(users)
        except ValueError:
            await u.message.reply_text("Invalid amount. Please try again from the menu.", reply_markup=rm)
            
    elif state == "awaiting_trade_input":
        users[uid]["state"] = None
        save_users(users)
        parts = text.split()
        if len(parts) != 2:
            await u.message.reply_text("Invalid format. Use SYMBOL AMOUNT (e.g. PEPE 10). Try again from the menu.", reply_markup=rm)
            return
        
        # We can simulate the context args to call cmd_trade
        class MockCtx:
            def __init__(self, args):
                self.args = args
        await cmd_trade(u, MockCtx(parts), is_callback=False)
        users = load_users()
        clear_user_session_keys(users, uid, ["auto_trade", "copy_trade"])
        save_users(users)

    elif state == "awaiting_auto_trade_amount":
        try:
            amount = float(text)
            users[uid]["auto_trade"]["amount"] = amount
            users[uid]["state"] = "awaiting_auto_trade_tp"
            save_users(users)
            # Ensure auto_trade context exists
            if "auto_trade" not in users[uid]:
                await u.message.reply_text("Auto-trade session expired. Please try again from the menu.", reply_markup=rm)
                return
            sym = users[uid]["auto_trade"]["sym"]
            await u.message.reply_text(f"Amount: ${amount}\n\nEnter Take-Profit % for {sym} (e.g. 50):", reply_markup=rm)
        except ValueError:
            await u.message.reply_text("Invalid amount. Please try again.", reply_markup=rm)

    elif state == "awaiting_auto_trade_tp":
        try:
            tp = float(text)
            users[uid]["auto_trade"]["tp_pct"] = tp
            users[uid]["state"] = "awaiting_auto_trade_sl"
            save_users(users)
            # Ensure auto_trade context exists
            if "auto_trade" not in users[uid]:
                await u.message.reply_text("Auto-trade session expired. Please try again from the menu.", reply_markup=rm)
                return
            sym = users[uid]["auto_trade"]["sym"]
            await u.message.reply_text(f"Take-Profit: +{tp}%\n\nEnter Stop-Loss % for {sym} (e.g. -20):", reply_markup=rm)
        except ValueError:
            await u.message.reply_text("Invalid percentage. Please try again.", reply_markup=rm)

    elif state == "awaiting_auto_trade_sl":
        try:
            sl = float(text)
            users[uid]["auto_trade"]["sl_pct"] = sl
            users[uid]["state"] = None
            save_users(users)
            
            # Ensure auto_trade context exists
            if "auto_trade" not in users[uid]:
                await u.message.reply_text("Auto-trade session expired. Please try again from the menu.", reply_markup=rm)
                return
                
            auto_cfg = users[uid]["auto_trade"]
            sym = auto_cfg["sym"]
            amount = auto_cfg["amount"]
            chain = auto_cfg["chain"]
            
            await u.message.reply_text(f"⏳ Setting up TP/SL for {sym}...\nExecuting initial buy of ${amount}...", reply_markup=rm)
            
            # Execute BUY order
            from ave.http import api_get
            sr = await api_get("/tokens", {"keyword": sym, "limit": 5, "chain": chain})
            tok_data = sr.json().get("data", [])
            if not tok_data:
                await u.message.reply_text(f"Token {sym} not found. Auto-trade cancelled.", reply_markup=rm)
                return
                
            ta = tok_data[0].get("token", "").split("-")[0]
            aid = users[uid]["assets_id"]
            usdt = "0x55d398326f99059fF775485246999027B3197955"
            
            qr = send_swap_order(uid, chain, aid, usdt, ta, int(amount * 1e18), "buy", slippage="1000", context={"source": "auto_trade"})
            
            if qr.get("status") not in (200, 0):
                err_msg = qr.get('msg', 'Unknown Error')
                kb = [[InlineKeyboardButton("🔄 Retry Buy", callback_data=f"retry_{chain}_{aid}_{usdt}_{ta}_{int(amount * 1e18)}_buy"), InlineKeyboardButton("❌ Dismiss", callback_data="cb_dismiss")]]
                await u.message.reply_text(f"❌ **Buy Failed**\nReason: {err_msg}\nTP/SL setup cancelled.", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
                return
                
            oid = ""
            d = qr.get("data", {})
            if isinstance(d, dict): oid = d.get("id", "")
            elif isinstance(d, list) and d: oid = d[0].get("id", "") if isinstance(d[0], dict) else str(d[0])
            
            # Save to trades.json
            trades = load_trades()
            if uid not in trades:
                trades[uid] = {}
                
            # Get actual current price for entry
            pr = await api_get(f"/tokens/{ta}-{chain}")
            entry_price = float(auto_cfg["price"])
            if pr.status_code == 200 and pr.json().get("data"):
                entry_price = float(pr.json()["data"].get("token", {}).get("current_price_usd", entry_price))
                
            trades[uid][ta] = {
                "chain": chain,
                "symbol": sym,
                "entry_price": entry_price,
                "invested_usdt": amount,
                "tp_pct": auto_cfg["tp_pct"],
                "sl_pct": auto_cfg["sl_pct"],
                "status": "active"
            }
            save_trades(trades)
            
            await u.message.reply_text(
                f"✅ **Buy submitted!** Order ID: `{oid}`\n\n"
                f"🛡️ **TP/SL Configured for {sym}:**\n"
                f"Entry: ${entry_price:.6f}\n"
                f"Take-Profit: +{auto_cfg['tp_pct']}%\n"
                f"Stop-Loss: {auto_cfg['sl_pct']}%\n\n"
                f"The bot will automatically sell if limits are hit.", 
                reply_markup=rm, parse_mode="Markdown"
            )
            users = load_users()
            clear_user_session_keys(users, uid, ["auto_trade"])
            save_users(users)
            
        except ValueError:
            await u.message.reply_text("Invalid percentage. Please try again.", reply_markup=rm)

    elif state == "awaiting_copy_pct":
        try:
            pct = float(text)
            if pct <= 0 or pct > 100: raise ValueError
            users[uid]["copy_trade"]["pct"] = pct
            users[uid]["state"] = "awaiting_copy_max"
            save_users(users)
            await u.message.reply_text(f"Allocation: {pct}%\n\nEnter the **maximum USDT** to spend per copied trade (e.g., 50):", reply_markup=rm, parse_mode="Markdown")
        except ValueError:
            await u.message.reply_text("Invalid percentage. Enter a number between 1 and 100.", reply_markup=rm)

    elif state == "awaiting_copy_max":
        try:
            max_usdt = float(text)
            if max_usdt <= 0: raise ValueError
            users[uid]["copy_trade"]["max_usdt"] = max_usdt
            users[uid]["state"] = None
            save_users(users)
            
            cfg = users[uid]["copy_trade"]
            chain = cfg["chain"]
            target_addr = cfg["addr"]
            
            copy_trades = load_copy_trades()
            if uid not in copy_trades: copy_trades[uid] = {}
            
            copy_trades[uid][target_addr] = {
                "chain": chain,
                "pct_allocation": cfg["pct"],
                "max_usdt_per_trade": max_usdt,
                "last_tx_hash": "", # Will be set on first poll
                "status": "active"
            }
            save_copy_trades(copy_trades)
            
            await u.message.reply_text(
                f"✅ **Copy Trade Active!**\n\n"
                f"Target: `{target_addr[:15]}...`\n"
                f"Allocation: {cfg['pct']}%\n"
                f"Max Per Trade: ${max_usdt}\n\n"
                f"The bot will automatically mirror new swaps.",
                reply_markup=rm, parse_mode="Markdown"
            )
            users = load_users()
            clear_user_session_keys(users, uid, ["copy_trade"])
            save_users(users)
        except ValueError:
            await u.message.reply_text("Invalid amount. Enter a positive number.", reply_markup=rm)

async def monitor_tp_sl(app: Application):
    return await monitor_tp_sl_impl(app)

async def monitor_copy_trades(app: Application):
    return await monitor_copy_trades_impl(app)

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
        if is_callback: await msg.edit_text(text, reply_markup=rm, parse_mode="Markdown")
        else: await msg.reply_text(text, reply_markup=rm, parse_mode="Markdown")
        return

    users = load_users()
    if not is_callback:
        await msg.reply_text("No existing wallet found. Creating new one...")
    
    # New user - create proxy wallet
    r = proxy_post("/v1/thirdParty/user/generateWallet", {"assetsName": "user_" + uid[-8:], "returnMnemonic": False})
    if r.get("status") not in (200, 0) or not r.get("data"):
        text = "Registration failed: " + str(r.get("msg", ""))
        if is_callback: await msg.edit_text(text, reply_markup=rm)
        else: await msg.reply_text(text, reply_markup=rm)
        return
    d = r["data"]
    users[uid] = {"assets_id": d["assetsId"], "address_list": d.get("addressList", []), "username": username, "chain": "bsc"}
    save_users(users)
    bsc_addr = next((a["address"] for a in d.get("addressList", []) if a["chain"] == "bsc"), "N/A")
    text = f"Proxy wallet created!\n\nBSC: `{bsc_addr}`\n\nDeposit USDT BEP20 to this address, then check Portfolio."
    if is_callback: await msg.edit_text(text, reply_markup=rm, parse_mode="Markdown")
    else: await msg.reply_text(text, reply_markup=rm, parse_mode="Markdown")

async def cmd_deposit(u, ctx, is_callback=False):
    uid = str(u.effective_user.id)
    auto_link_wallet(uid, username=u.effective_user.username)
    users = load_users()
    msg = u.callback_query.message if is_callback else u.message
    kb = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")]]
    rm = InlineKeyboardMarkup(kb)
    
    if uid not in users or not users[uid].get("assets_id"):
        text = "Use /register first"
        if is_callback: await msg.edit_text(text, reply_markup=rm)
        else: await msg.reply_text(text, reply_markup=rm)
        return
    addr = next((a["address"] for a in users[uid].get("address_list", []) if a["chain"] == "bsc"), "N/A")
    text = "Deposit Address (BSC BEP20)\n\n`" + addr + "`\n\nDeposit USDT to this address"
    if is_callback: await msg.edit_text(text, reply_markup=rm, parse_mode="Markdown")
    else: await msg.reply_text(text, reply_markup=rm, parse_mode="Markdown")

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
        if is_callback: await msg.edit_text(text, reply_markup=rm)
        else: await msg.reply_text(text, reply_markup=rm)
        return
        
    text_loading = "Fetching on-chain portfolio..."
    if is_callback: await msg.edit_text(text_loading)
    else: msg = await msg.reply_text(text_loading)
    
    aid = users[uid]["assets_id"]
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
    
    from ave.http import api_get
    trades = load_trades()
    user_trades = trades.get(uid, {})
    
    lines = ["📊 *On-Chain Portfolio - BSC*\n"]
    total_usd = 0.0
    
    for tok in r["data"]:
        bal = float(tok.get("balance_amount", 0) or 0)
        if bal <= 0: continue
        sym = tok.get("symbol", "?")
        tok_addr = tok.get("token", "")
        value = float(tok.get("balance_usd", 0) or 0)
        total_usd += value
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
    if is_callback: await msg.edit_text(text_loading)
    else: msg = await msg.reply_text(text_loading)
    
    tokens = []
    seen = set()
    # 1. Public signals (Ave-filtered, multi-chain)
    try:
        from ave.http import api_get
        for chain in ["bsc", "solana"]:
            url = f"https://data.ave-api.xyz/v2/signals/public/list?chain={chain}&pageSize=20&pageNO=1"
            req = urllib.request.Request(url, headers={"X-API-KEY": AVE_API_KEY})
            r = await asyncio.get_event_loop().run_in_executor(None, lambda u=url: urllib.request.urlopen(req, timeout=10))
            d = json.loads(r.read())
            for s in d.get("data", []):
                ta = s.get("token", ""); chain_tok = s.get("chain", chain)
                a = ta.split("-")[0] if "-" in ta else ta
                if a and a not in seen:
                    seen.add(a); tokens.append({"addr": a, "chain": chain_tok, "sym": s.get("symbol", "?"), "name": s.get("name", "")})
    except: pass
    # 2. Trending BSC tokens by keyword
    for kw in ["PEPE", "SHIB", "DOGE", "BNB", "CAKE", "WBNB", "BTCB", "ETH", "SOL", "XRP"]:
        try:
            url = f"https://data.ave-api.xyz/v2/tokens?keyword={kw}&limit=3&chain=bsc"
            req = urllib.request.Request(url, headers={"X-API-KEY": AVE_API_KEY})
            r = await asyncio.get_event_loop().run_in_executor(None, lambda u=url: urllib.request.urlopen(req, timeout=10))
            d = json.loads(r.read())
            for t in d.get("data", []):
                a = (t.get("token") or "").split("-")[0]
                if a and a not in seen: seen.add(a); tokens.append({"addr": a, "chain": "bsc", "sym": t.get("symbol", "?"), "name": t.get("name", "")})
        except: pass
    if not tokens:
        await msg.edit_text("No tokens found to scan.", reply_markup=rm)
        return
    signals = []
    for tok in tokens[:25]:
        try:
            ta = tok["addr"]; chain_tok = tok["chain"]; tid = f"{ta}-{chain_tok}"
            url1 = f"https://data.ave-api.xyz/v2/tokens/{tid}"
            url2 = f"https://data.ave-api.xyz/v2/contracts/{tid}"
            r1 = await asyncio.get_event_loop().run_in_executor(None, lambda u=url1: urllib.request.urlopen(urllib.request.Request(u, headers={"X-API-KEY": AVE_API_KEY}), timeout=10))
            d1 = json.loads(r1.read())
            r2 = await asyncio.get_event_loop().run_in_executor(None, lambda u=url2: urllib.request.urlopen(urllib.request.Request(u, headers={"X-API-KEY": AVE_API_KEY}), timeout=10))
            d2 = json.loads(r2.read())
            pd = d1.get("data", {}).get("token", {}); rd = d2.get("data", {})
            price = float(pd.get("current_price_usd") or 0)
            liq = float(pd.get("liquidity") or pd.get("tvl") or 0)
            vol = float(pd.get("tx_volume_u_24h") or 0)
            chg = float(pd.get("price_change_24h") or 0)
            if rd.get("is_honeypot") == 1 or price == 0: continue
            conf = 0
            if liq > 50000: conf += 30
            if vol > 10000: conf += 30
            if abs(chg) > 5: conf += 20
            if rd.get("risk_score", 50) < 30: conf += 20
            conf = min(100, conf)
            if conf >= 60:
                signals.append({"conf": conf, "sym": tok["sym"], "price": price, "chg": chg, "liq": liq, "vol": vol, "addr": ta, "chain": chain_tok})
        except: continue
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
        # Note: callback_data max len is 64 bytes. 
        # auto_trade_<chain>_<addr>_<sym>_<price>
        cb_data = f"auto_{s['chain']}_{s['addr'][:10]}_{s['sym']}_{round(s['price'],8)}"
        buttons.append([InlineKeyboardButton(f"⚡ Auto-Trade {s['sym']} (TP/SL)", callback_data=cb_data)])
        
    lines.append("\n`/trade <sym> <amt>` to execute manually")
    
    # Add back to menu button at the end
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
        if is_callback: await msg.edit_text(text, reply_markup=rm)
        else: await msg.reply_text(text, reply_markup=rm)
        return
        
    if not ctx.args or len(ctx.args) < 2:
        text = "Usage: `/trade SYMBOL AMOUNT`\n\nExample: `/trade ASTER 10`\n(Interactive trade UI coming soon)"
        if is_callback: await msg.edit_text(text, reply_markup=rm, parse_mode="Markdown")
        else: await msg.reply_text(text, reply_markup=rm, parse_mode="Markdown")
        return
        
    sym = ctx.args[0].upper()
    amount = float(ctx.args[1])
    from ave.http import api_get
    
    if is_callback: await msg.edit_text(f"Looking up {sym}...")
    else: msg = await msg.reply_text(f"Looking up {sym}...")
    
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
    if isinstance(d, dict): oid = d.get("id", "")
    elif isinstance(d, list) and d: oid = d[0].get("id", "") if isinstance(d[0], dict) else str(d[0])
    
    await msg.edit_text("✅ Swap submitted!\nOrder ID: `" + oid + "`\n\nCheck Portfolio after 30s for confirmation.", reply_markup=rm, parse_mode="Markdown")

async def cmd_topwallets(u, ctx, is_callback=False):
    msg = u.callback_query.message if is_callback else u.message
    kb = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")]]
    rm = InlineKeyboardMarkup(kb)
    from ave.http import api_get
    chain = "bsc"
    if ctx.args and ctx.args[0].lower() in ("bsc", "eth", "base", "solana"): chain = ctx.args[0].lower()
    
    text_loading = "Loading top wallets on " + chain.upper() + "..."
    if is_callback: await msg.edit_text(text_loading)
    else: msg = await msg.reply_text(text_loading)
    
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
    
    # Add a generic back button
    await msg.edit_text("\n".join(lines), reply_markup=rm, parse_mode="Markdown")

async def cmd_track(u, ctx, is_callback=False):
    msg = u.callback_query.message if is_callback else u.message
    kb = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")]]
    rm = InlineKeyboardMarkup(kb)
    from ave.http import api_get
    if not ctx.args:
        text = "Usage: `/track ADDRESS [chain]`"
        if is_callback: await msg.edit_text(text, reply_markup=rm, parse_mode="Markdown")
        else: await msg.reply_text(text, reply_markup=rm, parse_mode="Markdown")
        return
        
    addr = ctx.args[0]; chain = "bsc"
    if len(ctx.args) > 1 and ctx.args[1].lower() in ("bsc", "eth", "solana"): chain = ctx.args[1].lower()
    
    text_loading = "Tracking " + addr[:10] + "... on " + chain.upper()
    if is_callback: await msg.edit_text(text_loading)
    else: msg = await msg.reply_text(text_loading)
    
    r = await api_get("/address/walletinfo/tokens", {"wallet_address": addr, "chain": chain, "sort": "balance_usd", "sort_dir": "desc", "pageSize": 8})
    d = r.json()
    lines = ["Wallet: `" + addr[:20] + "...` | " + chain.upper() + "\n"]
    if d.get("status") == 1 and d.get("data"):
        for t in d["data"][:6]:
            bal = float(t.get("balance_amount", 0) or 0)
            if bal <= 0: continue
            lines.append(t.get("symbol", "?") + ": " + str(round(bal, 4)) + " | P/L: " + str(round(float(t.get("profit_pct", 0), 1))) + "%")
    else: lines.append("No holdings found")
    
    # Add Copy Trade button
    # copy_chain_address
    cb_data = f"copy_{chain}_{addr}"
    kb = [
        [InlineKeyboardButton(f"👥 Copy Trade {addr[:6]}...", callback_data=cb_data)],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")]
    ]
    rm = InlineKeyboardMarkup(kb)
    
    await msg.edit_text("\n".join(lines), reply_markup=rm, parse_mode="Markdown")

async def cmd_help(u, ctx, is_callback=False):
    msg = u.callback_query.message if is_callback else u.message
    kb = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")]]
    rm = InlineKeyboardMarkup(kb)
    text = (
        "Commands:\n"
        "register · deposit · balance · quote SYM [AMT]\n"
        "signal · trade SYM AMT · topwallets [chain]\n"
        "track ADDRESS · help\n\n"
        "ENV Status:\n"
        f"TELEGRAM_BOT_TOKEN: {'✅ set' if BOT_TOKEN else '❌ missing'}\n"
        f"AVE_API_KEY: {'✅ set' if AVE_API_KEY else '❌ missing'}\n"
        f"AVE_SECRET_KEY: {'✅ set' if AVE_SECRET_KEY else '❌ missing'}\n"
        f"API_PLAN: {API_PLAN or 'pro'}\n\n"
        "Powered by Ave Cloud API"
    )
    if is_callback: await msg.edit_text(text, reply_markup=rm)
    else: await msg.reply_text(text, reply_markup=rm)

async def cmd_quote(u, ctx):
    """Quote price for a token - shows estimated output for a given input amount"""
    if not ctx.args:
        await u.message.reply_text("Usage: /quote SYMBOL [AMOUNT]\nExample: /quote ASTER 10\nShows quote for converting 10 USDT to ASTER")
        return

    sym = ctx.args[0].upper()
    amount = float(ctx.args[1]) if len(ctx.args) > 1 else 10.0  # default 10 USDT

    await u.message.reply_text(f"Getting quote for {amount} USDT → {sym}...")

    # Find token address
    from ave.http import api_get

    sr = await api_get("/tokens", {"keyword": sym, "limit": 5, "chain": "bsc"})
    tok_data = sr.json().get("data", [])
    if not tok_data:
        # Try ETH chain
        sr = await api_get("/tokens", {"keyword": sym, "limit": 5, "chain": "eth"})
        tok_data = sr.json().get("data", [])

    if not tok_data:
        await u.message.reply_text(f"Token '{sym}' not found on BSC or ETH.")
        return

    # Find token with matching symbol
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

    # USDT address on BSC
    usdt_addr = "0x55d398326f99059fF775485246999027B3197955"
    # USDT on ETH
    usdt_addr_eth = "0xdAC17F958D2ee523a2206206994597C13D831ec7"

    in_token = usdt_addr_eth if tok_chain == "eth" else usdt_addr
    chain = tok_chain

    # Get quote - inAmount in smallest unit (USDT has 6 decimals for BSC-USDT, 6 for ETH too)
    in_amount_smallest = str(int(amount * 1e18))  # 18 decimals for BSC USDT

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
    decimals = d.get("decimals", 18)
    spender = d.get("spender", "N/A")

    # Convert to human readable
    # The API returns estimateOut in the token's display unit (not smallest unit like wei)
    # ASTER has 18 decimals on-chain, but the API returns already normalized values
    # Confirmed: 14472927 estimate for 10 USDT → 14.472927 ASTER @ $0.69 ≈ $10 ✓
    token_amount = estimate_out / (10 ** 6)  # normalize assuming 6dp display unit
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


def main():
    if not BOT_TOKEN: print("ERROR: TELEGRAM_BOT_TOKEN not set"); return
    try:
        db_init()
    except Exception as e:
        print("ERROR: Database init failed: " + str(e))
        return
    app = Application.builder().token(BOT_TOKEN).build()
    for cmd, fn in [
        ("start", cmd_start), ("register", cmd_register), ("deposit", cmd_deposit),
        ("balance", cmd_balance), ("quote", cmd_quote), ("signal", cmd_signal),
        ("trade", cmd_trade), ("topwallets", cmd_topwallets), ("track", cmd_track),
        ("help", cmd_help)
    ]:
        app.add_handler(CommandHandler(cmd, fn))
    
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # Start TP/SL background monitor
    import asyncio
    
    async def run_tasks():
        asyncio.create_task(monitor_tp_sl(app))
        asyncio.create_task(monitor_copy_trades(app))
    
    app.post_init = lambda a: run_tasks()
    
    print("Avegram v2 running on proxy wallet mode...")
    app.run_polling()

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("migrate", "--migrate"):
        db_init()
        print("db_init ok")
    else:
        main()
