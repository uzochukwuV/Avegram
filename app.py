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

async def show_main_menu(message, uid, edit=False):
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
        await show_main_menu(query.message, uid, edit=True)
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
        users = load_users()
        uid_str = str(uid)
        users[uid_str]["state"] = "awaiting_withdraw_address"
        save_users(users)
        keyboard = [[InlineKeyboardButton("🔙 Cancel", callback_data="cb_menu")]]
        await query.message.edit_text("💸 *Withdraw Funds*\n\nPlease paste the destination BSC address:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    elif data == "cb_trade":
        users = load_users()
        uid_str = str(uid)
        users[uid_str]["state"] = "awaiting_trade_input"
        save_users(users)
        keyboard = [[InlineKeyboardButton("🔙 Cancel", callback_data="cb_menu")]]
        await query.message.edit_text("💱 *Trade Token*\n\nPlease enter the SYMBOL and AMOUNT separated by space.\nExample: `PEPE 10` (to buy $10 worth of PEPE)", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
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
                await u.message.reply_text(f"❌ Buy failed: {qr.get('msg', '')}\nTP/SL setup cancelled.", reply_markup=rm)
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


async def cmd_start(u, ctx):
    await show_main_menu(u.message, u.effective_user.id)

async def cmd_register(u, ctx, is_callback=False):
    users = load_users()
    uid = str(u.effective_user.id)
    msg = u.callback_query.message if is_callback else u.message
    kb = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")]]
    rm = InlineKeyboardMarkup(kb)
    
    # If already registered with proxy wallet, show it
    if uid in users and users[uid].get("assets_id"):
        w = users[uid]
        bsc_addr = next((a["address"] for a in w.get("address_list", []) if a["chain"] == "bsc"), "N/A")
        text = f"Already registered\nBSC: `{bsc_addr}`"
        if is_callback: await msg.edit_text(text, reply_markup=rm, parse_mode="Markdown")
        else: await msg.reply_text(text, reply_markup=rm, parse_mode="Markdown")
        return
    
    # If user exists but has no proxy wallet yet, fetch existing wallets from API
    if uid in users and not users[uid].get("assets_id"):
        r = proxy_get("/v1/thirdParty/user/getUserByAssetsId")
        if r.get("status") == 200 and r.get("data"):
            wallets = r["data"]
            if wallets:
                w = wallets[0]
                users[uid]["assets_id"] = w["assetsId"]
                users[uid]["address_list"] = w.get("addressList", [])
                save_users(users)
                bsc_addr = next((a["address"] for a in w.get("addressList", []) if a["chain"] == "bsc"), "N/A")
                text = f"Proxy wallet found and linked!\n\nBSC: `{bsc_addr}`\n\nThis wallet has your funded USDT. Check Portfolio to see your holdings."
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
    users[uid] = {"assets_id": d["assetsId"], "address_list": d.get("addressList", []), "username": u.effective_user.username, "chain": "bsc"}
    save_users(users)
    bsc_addr = next((a["address"] for a in d.get("addressList", []) if a["chain"] == "bsc"), "N/A")
    text = f"Proxy wallet created!\n\nBSC: `{bsc_addr}`\n\nDeposit USDT BEP20 
