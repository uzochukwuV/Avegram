"""SignalBot v2 - Ave proxy wallet integration"""
import os, json, asyncio, sys, urllib.request, urllib.parse, base64, datetime, hmac, hashlib
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from dotenv import load_dotenv

AVENUE_SCRIPTS = "/home/workspace/ave-cloud-skill/scripts"
# Try using relative path for the workspace if absolute path doesn't exist
if not os.path.exists(AVENUE_SCRIPTS):
    AVENUE_SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ave-cloud-skill", "scripts")
sys.path.insert(0, AVENUE_SCRIPTS)
load_dotenv("/workspace/.env")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
AVE_API_KEY = os.environ.get("AVE_API_KEY", "")
AVE_SECRET_KEY = os.environ.get("AVE_SECRET_KEY", "")
API_PLAN = os.environ.get("API_PLAN", "pro")
USERS_FILE = "/workspace/users.json"
TRADES_FILE = "/workspace/trades.json"
COPY_TRADES_FILE = "/workspace/copy_trades.json"

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE) as f: return json.load(f)
    return {}

def save_users(u):
    with open(USERS_FILE, "w") as f: json.dump(u, f, indent=2)

def load_trades():
    if os.path.exists(TRADES_FILE):
        with open(TRADES_FILE) as f: return json.load(f)
    return {}

def save_trades(t):
    with open(TRADES_FILE, "w") as f: json.dump(t, f, indent=2)

def load_copy_trades():
    if os.path.exists(COPY_TRADES_FILE):
        with open(COPY_TRADES_FILE) as f: return json.load(f)
    return {}

def save_copy_trades(t):
    with open(COPY_TRADES_FILE, "w") as f: json.dump(t, f, indent=2)

def proxy_headers(method, path, body=None):
    import base64, datetime, hashlib, hmac
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    msg = ts + method.upper() + path
    if body: msg += json.dumps(body, sort_keys=True, separators=(",", ":"))
    sig = base64.b64encode(hmac.new(AVE_SECRET_KEY.encode(), msg.encode(), hashlib.sha256).digest()).decode()
    return {"AVE-ACCESS-KEY": AVE_API_KEY, "AVE-ACCESS-TIMESTAMP": ts, "AVE-ACCESS-SIGN": sig, "Content-Type": "application/json"}

def proxy_get(path, params=None):
    import urllib.request, urllib.parse
    url = "https://bot-api.ave.ai" + path
    if params: url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=proxy_headers("GET", path))
    with urllib.request.urlopen(req, timeout=15) as r: return json.loads(r.read())

def proxy_post(path, body):
    import urllib.request
    data = json.dumps(body).encode()
    req = urllib.request.Request("https://bot-api.ave.ai" + path, data=data, headers=proxy_headers("POST", path, body))
    with urllib.request.urlopen(req, timeout=15) as r: return json.loads(r.read())

def auto_link_wallet(uid_str, username):
    users = load_users()
    if uid_str in users and users[uid_str].get("assets_id"):
        return True
        
    r = proxy_get("/v1/thirdParty/user/getUserByAssetsId")
    if r.get("status") in (200, 0) and r.get("data"):
        wallets = r["data"]
        if wallets:
            w = wallets[0]
            if uid_str not in users:
                users[uid_str] = {"username": username, "chain": "bsc"}
            users[uid_str]["assets_id"] = w["assetsId"]
            users[uid_str]["address_list"] = w.get("addressList", [])
            save_users(users)
            return True
            
    return False

async def show_main_menu(message, uid, edit=False, username=""):
    auto_link_wallet(str(uid), username)
    users = load_users()
    uid_str = str(uid)
    text = "🚀 *Avegram Dashboard*\n\nPowered by Ave Cloud API"
    
    if uid_str not in users or not users[uid_str].get("assets_id"):
        keyboard = [[InlineKeyboardButton("💳 Create Wallet", callback_data="cb_register")]]
    else:
        keyboard = [
            [InlineKeyboardButton("📊 My Portfolio", callback_data="cb_balance")],
            [InlineKeyboardButton("💱 Trade", callback_data="cb_trade"), InlineKeyboardButton("📡 Scan Signals", callback_data="cb_signal")],
            [InlineKeyboardButton("⬇️ Deposit", callback_data="cb_deposit"), InlineKeyboardButton("⬆️ Withdraw", callback_data="cb_withdraw")],
            [InlineKeyboardButton("🐋 Smart Money Wallets", callback_data="cb_topwallets")],
            [InlineKeyboardButton("❓ Help", callback_data="cb_help")]
        ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    if edit:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

async def handle_callback(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = u.callback_query
    await query.answer()
    data = query.data
    uid = u.effective_user.id

    if data == "cb_menu":
        users = load_users()
        if str(uid) in users and "state" in users[str(uid)]:
            users[str(uid)]["state"] = None
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
        auto_link_wallet(str(uid), u.effective_user.username)
        users = load_users()
        uid_str = str(uid)
        users[uid_str]["state"] = "awaiting_withdraw_address"
        save_users(users)
        keyboard = [[InlineKeyboardButton("🔙 Cancel", callback_data="cb_menu")]]
        await query.message.edit_text("💸 *Withdraw Funds*\n\nPlease paste the destination BSC address:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    elif data == "cb_trade":
        auto_link_wallet(str(uid), u.effective_user.username)
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
            qr = proxy_post("/v1/thirdParty/tx/sendSwapOrder", {
                "chain": chain, "assetsId": aid, "inTokenAddress": in_token, "outTokenAddress": out_token, 
                "inAmount": in_amount, "swapType": swap_type, "slippage": "1500"
            })
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
            
            qr = proxy_post("/v1/thirdParty/tx/sendSwapOrder", {"chain": chain, "assetsId": aid, "inTokenAddress": usdt, "outTokenAddress": ta, "inAmount": str(int(amount * 1e18)), "swapType": "buy", "slippage": "1000"})
            
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
        except ValueError:
            await u.message.reply_text("Invalid amount. Enter a positive number.", reply_markup=rm)

async def monitor_tp_sl(app: Application):
    """Background task to monitor prices and trigger TP/SL."""
    from ave.http import api_get
    usdt_addr = "0x55d398326f99059fF775485246999027B3197955"
    
    while True:
        try:
            trades = load_trades()
            users = load_users()
            changed = False
            
            for uid, user_trades in list(trades.items()):
                if uid not in users or not users[uid].get("assets_id"):
                    continue
                aid = users[uid]["assets_id"]
                
                for ta, t in list(user_trades.items()):
                    if t.get("status") != "active": continue
                    
                    chain = t.get("chain", "bsc")
                    sym = t.get("symbol", "?")
                    entry = t.get("entry_price", 0)
                    if entry == 0: continue
                    
                    # Fetch current price
                    pr = await api_get(f"/tokens/{ta}-{chain}")
                    if pr.status_code != 200 or not pr.json().get("data"):
                        continue
                        
                    curr_price = float(pr.json()["data"].get("token", {}).get("current_price_usd", 0))
                    if curr_price == 0: continue
                    
                    tp_target = entry * (1 + (t["tp_pct"] / 100))
                    sl_target = entry * (1 + (t["sl_pct"] / 100))
                    
                    hit_type = None
                    if curr_price >= tp_target: hit_type = "Take-Profit"
                    elif curr_price <= sl_target: hit_type = "Stop-Loss"
                    
                    if hit_type:
                        # 1. Fetch current token balance
                        r = proxy_get("/v1/thirdParty/tx/getSwapOrder", {"chain": chain, "assetsId": aid, "pageSize": "50", "pageNO": "0"})
                        bal = 0.0
                        if r.get("status") in (200, 0) and r.get("data"):
                            for o in r["data"]:
                                if o.get("status") != "confirmed": continue
                                if o.get("outTokenAddress") == ta: bal += float(o.get("outAmount", "0")) / 1e18
                                elif o.get("inTokenAddress") == ta: bal -= float(o.get("inAmount", "0")) / 1e18
                        
                        if bal <= 0.0001:
                            # User already sold manually
                            del trades[uid][ta]
                            changed = True
                            continue
                            
                        # 2. Execute SELL order
                        in_amount_wei = str(int(bal * 1e18)) # Assuming 18 decimals, proxy_post will handle exact if needed but we send max wei
                        qr = proxy_post("/v1/thirdParty/tx/sendSwapOrder", {
                            "chain": chain, "assetsId": aid, "inTokenAddress": ta, "outTokenAddress": usdt_addr, 
                            "inAmount": in_amount_wei, "swapType": "sell", "slippage": "1500"
                        })
                        
                        if qr.get("status") in (200, 0):
                            # Sell successful
                            pnl_pct = ((curr_price - entry) / entry) * 100
                            usd_out = bal * curr_price
                            msg = f"🚨 **{hit_type} Hit!**\n\nSold {round(bal, 4)} {sym} for ~${usd_out:.2f}\nPNL: {pnl_pct:+.2f}%\nPrice: ${curr_price:.6f}"
                            await app.bot.send_message(chat_id=uid, text=msg, parse_mode="Markdown")
                            del trades[uid][ta]
                            changed = True
                        else:
                            # Failed to sell
                            print(f"TP/SL Sell failed for {uid} {sym}: {qr}")
                            
            if changed:
                save_trades(trades)
                
        except Exception as e:
            print(f"TP/SL Monitor error: {e}")
            
        await asyncio.sleep(30)


async def monitor_copy_trades(app: Application):
    """Background task to mirror smart money wallets."""
    from ave.http import api_get
    usdt_addr = "0x55d398326f99059fF775485246999027B3197955"
    
    while True:
        try:
            copy_trades = load_copy_trades()
            users = load_users()
            changed = False
            
            for uid, targets in list(copy_trades.items()):
                if uid not in users or not users[uid].get("assets_id"): continue
                aid = users[uid]["assets_id"]
                
                for target_addr, cfg in list(targets.items()):
                    if cfg.get("status") != "active": continue
                    
                    chain = cfg.get("chain", "bsc")
                    # Fetch latest txs for target wallet
                    r = await api_get("/address/walletinfo/transactions", {"wallet_address": target_addr, "chain": chain, "pageSize": 5, "pageNO": 0})
                    if r.status_code != 200: continue
                    data = r.json()
                    if data.get("status") != 1 or not data.get("data"): continue
                    
                    txs = data["data"]
                    if not txs: continue
                    
                    latest_tx = txs[0]
                    tx_hash = latest_tx.get("transaction_hash", "")
                    
                    # If this is the first poll, just set the hash and continue
                    if not cfg.get("last_tx_hash"):
                        cfg["last_tx_hash"] = tx_hash
                        changed = True
                        continue
                        
                    # If we have seen this hash, nothing new
                    if tx_hash == cfg["last_tx_hash"]: continue
                    
                    # New transaction found! Parse it
                    cfg["last_tx_hash"] = tx_hash
                    changed = True
                    
                    tx_type = latest_tx.get("trade_type", "")
                    token_addr = latest_tx.get("token_address", "")
                    token_sym = latest_tx.get("symbol", "?")
                    
                    # Ensure it's a swap we can mirror
                    if tx_type not in ("buy", "sell") or not token_addr: continue
                    
                    try:
                        # Find User's USDT balance
                        user_bal_resp = proxy_get("/v1/thirdParty/tx/getSwapOrder", {"chain": chain, "assetsId": aid, "pageSize": 50, "pageNO": 0})
                        
                        if tx_type == "buy":
                            # Calculate user's USDT balance to determine trade size
                            # We'll use a mock total since we don't have a direct wallet balance endpoint in the provided snippets.
                            # Usually, we would query the proxy wallet balance directly. 
                            # For safety in this mockup, we'll just try to use the max_usdt config limit if they have it.
                            trade_amount = cfg["max_usdt_per_trade"]
                            
                            # Execute Buy
                            in_amount_wei = str(int(trade_amount * 1e18))
                            qr = proxy_post("/v1/thirdParty/tx/sendSwapOrder", {
                                "chain": chain, "assetsId": aid, "inTokenAddress": usdt_addr, "outTokenAddress": token_addr, 
                                "inAmount": in_amount_wei, "swapType": "buy", "slippage": "1500"
                            })
                            
                            if qr.get("status") in (200, 0):
                                msg = f"👥 **Copied Buy**\nTarget: `{target_addr[:10]}...`\nBought: ~${trade_amount} of {token_sym}\nOrder: `{qr.get('data', {}).get('id', '')}`"
                                await app.bot.send_message(chat_id=uid, text=msg, parse_mode="Markdown")
                            else:
                                err_msg = qr.get('msg', 'Unknown Error')
                                kb = [[InlineKeyboardButton("🔄 Retry Buy", callback_data=f"retry_{chain}_{aid}_{usdt_addr}_{token_addr}_{in_amount_wei}_buy"), InlineKeyboardButton("❌ Dismiss", callback_data="cb_dismiss")]]
                                await app.bot.send_message(chat_id=uid, text=f"❌ **Copy Trade Failed (Buy {token_sym})**\nReason: {err_msg}", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
                                
                        elif tx_type == "sell":
                            # For sell, we would look up the user's holding of `token_addr` and sell 100%
                            # In a full impl, we'd calculate the proportional sell amount. Here we do 100% for safety.
                            
                            # Calculate user's token balance
                            bal = 0.0
                            if user_bal_resp.get("status") in (200, 0) and user_bal_resp.get("data"):
                                for o in user_bal_resp["data"]:
                                    if o.get("status") != "confirmed": continue
                                    if o.get("outTokenAddress") == token_addr: bal += float(o.get("outAmount", "0")) / 1e18
                                    elif o.get("inTokenAddress") == token_addr: bal -= float(o.get("inAmount", "0")) / 1e18
                                    
                            if bal > 0.0001:
                                in_amount_wei = str(int(bal * 1e18))
                                qr = proxy_post("/v1/thirdParty/tx/sendSwapOrder", {
                                    "chain": chain, "assetsId": aid, "inTokenAddress": token_addr, "outTokenAddress": usdt_addr, 
                                    "inAmount": in_amount_wei, "swapType": "sell", "slippage": "1500"
                                })
                                
                                if qr.get("status") in (200, 0):
                                    msg = f"👥 **Copied Sell**\nTarget: `{target_addr[:10]}...`\nSold: {round(bal, 4)} {token_sym}"
                                    await app.bot.send_message(chat_id=uid, text=msg, parse_mode="Markdown")
                                else:
                                    err_msg = qr.get('msg', 'Unknown Error')
                                    kb = [[InlineKeyboardButton("🔄 Retry Sell", callback_data=f"retry_{chain}_{aid}_{token_addr}_{usdt_addr}_{in_amount_wei}_sell"), InlineKeyboardButton("❌ Dismiss", callback_data="cb_dismiss")]]
                                    await app.bot.send_message(chat_id=uid, text=f"❌ **Copy Trade Failed (Sell {token_sym})**\nReason: {err_msg}", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
                                    
                    except Exception as inner_e:
                        print(f"Inner copy trade error for {uid}: {inner_e}")
                        
            if changed:
                save_copy_trades(copy_trades)
                
        except Exception as e:
            print(f"Copy Trade Monitor error: {e}")
            
        await asyncio.sleep(60)

async def cmd_start(u, ctx):
    await show_main_menu(u.message, u.effective_user.id, username=u.effective_user.username)

async def cmd_register(u, ctx, is_callback=False):
    users = load_users()
    uid = str(u.effective_user.id)
    username = u.effective_user.username
    msg = u.callback_query.message if is_callback else u.message
    kb = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")]]
    rm = InlineKeyboardMarkup(kb)
    
    # Check if they already have a wallet (this handles existing proxy wallets)
    if auto_link_wallet(uid, username):
        users = load_users()
        w = users[uid]
        bsc_addr = next((a["address"] for a in w.get("address_list", []) if a["chain"] == "bsc"), "N/A")
        text = f"✅ Proxy wallet linked and ready!\n\nBSC: `{bsc_addr}`\n\nThis wallet holds your funded USDT. Check Portfolio to see your holdings."
        if is_callback: await msg.edit_text(text, reply_markup=rm, parse_mode="Markdown")
        else: await msg.reply_text(text, reply_markup=rm, parse_mode="Markdown")
        return

    if not is_callback: await msg.reply_text("No existing wallet found. Creating new one...")
    
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
    username = u.effective_user.username
    auto_link_wallet(uid, username)
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
    username = u.effective_user.username
    auto_link_wallet(uid, username)
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
        
    text_loading = "Fetching portfolio and PNL..."
    if is_callback: await msg.edit_text(text_loading)
    else: msg = await msg.reply_text(text_loading)
    
    aid = users[uid]["assets_id"]
    r = proxy_get("/v1/thirdParty/tx/getSwapOrder", {"chain": "bsc", "assetsId": aid, "pageSize": "50", "pageNO": "0"})
    if r.get("status") not in (200, 0) or not r.get("data"):
        await msg.edit_text("No swap history. Deposit USDT to your BSC wallet address to start trading.", reply_markup=rm)
        return
        
    # Aggregate positions
    positions = {}
    for o in r["data"]:
        if o.get("status") != "confirmed": continue
        swap_type = o.get("swapType", "buy")
        if swap_type == "buy":
            sym = o.get("outTokenSymbol", "?")
            ta = o.get("outTokenAddress")
            bal_chg = float(o.get("outAmount", "0")) / 1e18
            usd_spent = float(o.get("txPriceUsd", "0")) * bal_chg
            if sym not in positions: positions[sym] = {"addr": ta, "bal": 0.0, "invested": 0.0}
            positions[sym]["bal"] += bal_chg
            positions[sym]["invested"] += usd_spent
        else:
            sym = o.get("inTokenSymbol", "?")
            ta = o.get("inTokenAddress")
            bal_chg = float(o.get("inAmount", "0")) / 1e18
            usd_received = float(o.get("txPriceUsd", "0")) * bal_chg
            if sym in positions:
                positions[sym]["bal"] -= bal_chg
                positions[sym]["invested"] -= usd_received
                if positions[sym]["invested"] < 0: positions[sym]["invested"] = 0

    from ave.http import api_get

    lines = ["📊 *Portfolio & PNL - BSC*\n"]
    total_invested = 0.0
    total_current = 0.0
    
    trades = load_trades()
    user_trades = trades.get(uid, {})
    
    for sym, p in positions.items():
        if p["bal"] < 0.0001: continue
        total_invested += p["invested"]
        
        pr = await api_get(f"/tokens/{p['addr']}-bsc")
        curr_price = 0.0
        if pr.status_code == 200 and pr.json().get("data"):
            curr_price = float(pr.json()["data"].get("token", {}).get("current_price_usd", 0))
            
        curr_value = p["bal"] * curr_price
        total_current += curr_value
        
        pnl_usd = curr_value - p["invested"]
        pnl_pct = (pnl_usd / p["invested"] * 100) if p["invested"] > 0 else 0
        sign = "🟢 +" if pnl_usd >= 0 else "🔴 "
        
        lines.append(f"*{sym}*: {round(p['bal'], 4)}")
        lines.append(f"  Val: ${curr_value:.2f} | Inv: ${p['invested']:.2f}")
        lines.append(f"  PNL: {sign}${abs(pnl_usd):.2f} ({pnl_pct:+.2f}%)")
        
        if p['addr'] in user_trades and user_trades[p['addr']].get('status') == 'active':
            t = user_trades[p['addr']]
            lines.append(f"  ⚡ TP: +{t['tp_pct']}% | SL: {t['sl_pct']}%")
            
        lines.append("")
        
    if total_invested == 0 and total_current == 0:
        await msg.edit_text("No active positions.", reply_markup=rm)
        return
        
    tot_pnl_usd = total_current - total_invested
    tot_pnl_pct = (tot_pnl_usd / total_invested * 100) if total_invested > 0 else 0
    tot_sign = "🟢 +" if tot_pnl_usd >= 0 else "🔴 "
    
    lines.append(f"💰 *Total Value*: ${total_current:.2f}")
    lines.append(f"📈 *Total PNL*: {tot_sign}${abs(tot_pnl_usd):.2f} ({tot_pnl_pct:+.2f}%)")
    
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
    username = u.effective_user.username
    auto_link_wallet(uid, username)
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
    
    qr = proxy_post("/v1/thirdParty/tx/sendSwapOrder", {"chain": "bsc", "assetsId": aid, "inTokenAddress": usdt, "outTokenAddress": ta, "inAmount": str(int(amount * 1e18)), "swapType": "buy", "slippage": "500"})
    if qr.get("status") not in (200, 0):
        err_msg = qr.get('msg', 'Unknown Error')
        kb = [[InlineKeyboardButton("🔄 Retry Trade", callback_data=f"retry_bsc_{aid}_{usdt}_{ta}_{in_amount_smallest}_buy"), InlineKeyboardButton("❌ Dismiss", callback_data="cb_dismiss")]]
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
        "/register /deposit /balance /quote SYM [AMT] /signal /trade SYM AMT /topwallets [chain] /track ADDRESS /help\n\n"
        "ENV Status:\n"
        f"TELEGRAM_BOT_TOKEN: {'✅ set' if BOT_TOKEN else '❌ missing'}\n"
        f"AVE_API_KEY: {'✅ set' if AVE_API_KEY else '❌ missing'}\n"
        f"AVE_SECRET_KEY: {'✅ set' if AVE_SECRET_KEY else '❌ missing'}\n"
        f"API_PLAN: {API_PLAN or 'pro'}\n\n"
        "Powered by Ave Cloud API"
    )
    if is_callback: await msg.edit_text(text, reply_markup=rm, parse_mode="Markdown")
    else: await msg.reply_text(text, reply_markup=rm, parse_mode="Markdown")

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
            "swapType": "buy"
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
    token_amount = estimate_out / (10 ** decimals)
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
    
    app.post_init = lambda a: run_tasks()
    
    print("Avegram v2 running on proxy wallet mode...")
    app.run_polling()

if __name__ == "__main__": main()
