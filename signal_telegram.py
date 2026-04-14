"""SignalBot v2 - Ave proxy wallet integration with PNL, Copy Trading, and Alerts"""
import os, json, asyncio, sys, urllib.request, urllib.parse, base64, datetime, hmac, hashlib
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from dotenv import load_dotenv

AVENUE_SCRIPTS = "/home/workspace/ave-cloud-skill/scripts"
if os.path.exists("/workspace/ave-cloud-skill/scripts"):
    AVENUE_SCRIPTS = "/workspace/ave-cloud-skill/scripts"

load_dotenv("/workspace/.env")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
AVE_API_KEY = os.environ.get("AVE_API_KEY", "")
AVE_SECRET_KEY = os.environ.get("AVE_SECRET_KEY", "")
API_PLAN = os.environ.get("API_PLAN", "pro")
USERS_FILE = "/workspace/users.json"

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE) as f: return json.load(f)
    return {}

def save_users(u):
    with open(USERS_FILE, "w") as f: json.dump(u, f, indent=2)

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

async def cmd_start(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = u.message if u.message else u.callback_query.message
    keyboard = [
        [InlineKeyboardButton("📊 Portfolio PNL", callback_data="cmd|pnl"), InlineKeyboardButton("🔍 Scan Signals", callback_data="cmd|signal")],
        [InlineKeyboardButton("🐳 Top Wallets", callback_data="cmd|topwallets"), InlineKeyboardButton("💼 Deposit Address", callback_data="cmd|deposit")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await msg.reply_text(
        "🚀 *Avegram v2 - Smart Trading Bot*\n\n"
        "Welcome! Choose an action below or use commands:\n"
        "/register - Create proxy wallet\n"
        "/deposit - View address\n"
        "/balance - Check holdings\n"
        "/pnl - Portfolio PNL Analysis\n"
        "/quote SYM [AMT] - Get quote\n"
        "/signal - AI Signals\n"
        "/trade SYM AMT - Execute swap\n"
        "/topwallets - Smart money\n"
        "/track ADDRESS - Track wallet\n"
        "/copy ADDRESS AMT - Auto-copy trades\n"
        "/alert SYM PRICE - Set price alert\n\n"
        "Powered by Ave Cloud API",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def cmd_register(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = u.message if u.message else u.callback_query.message
    users = load_users()
    uid = str(u.effective_user.id)
    if uid in users and users[uid].get("assets_id"):
        w = users[uid]
        bsc_addr = next((a["address"] for a in w.get("address_list", []) if a["chain"] == "bsc"), "N/A")
        await msg.reply_text(f"Already registered\nBSC: `{bsc_addr}`", parse_mode="Markdown")
        return
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
                await msg.reply_text(f"Proxy wallet found and linked!\n\nBSC: `{bsc_addr}`", parse_mode="Markdown")
                return
        await msg.reply_text("No existing wallet found. Creating new one...")
    r = proxy_post("/v1/thirdParty/user/generateWallet", {"assetsName": "user_" + uid[-8:], "returnMnemonic": False})
    if r.get("status") not in (200, 0) or not r.get("data"):
        await msg.reply_text("Registration failed: " + str(r.get("msg", ""))); return
    d = r["data"]
    users[uid] = {"assets_id": d["assetsId"], "address_list": d.get("addressList", []), "username": u.effective_user.username, "chain": "bsc"}
    save_users(users)
    bsc_addr = next((a["address"] for a in d.get("addressList", []) if a["chain"] == "bsc"), "N/A")
    await msg.reply_text(f"Proxy wallet created!\n\nBSC: `{bsc_addr}`\n\nDeposit USDT BEP20 to this address, then /balance to check.", parse_mode="Markdown")

async def cmd_deposit(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = u.message if u.message else u.callback_query.message
    users = load_users(); uid = str(u.effective_user.id)
    if uid not in users or not users[uid].get("assets_id"):
        await msg.reply_text("Use /register first"); return
    addr = next((a["address"] for a in users[uid].get("address_list", []) if a["chain"] == "bsc"), "N/A")
    await msg.reply_text(f"Deposit Address (BSC BEP20)\n\n`{addr}`\n\nDeposit USDT to this address", parse_mode="Markdown")

async def cmd_pnl(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = u.message if u.message else u.callback_query.message
    users = load_users()
    uid = str(u.effective_user.id)
    if uid not in users or not users[uid].get("assets_id"):
        await msg.reply_text("Use /register first")
        return
    addr = next((a["address"] for a in users[uid].get("address_list", []) if a["chain"] == "bsc"), "N/A")
    if addr == "N/A":
        await msg.reply_text("No BSC address found")
        return

    sys.path.insert(0, AVENUE_SCRIPTS)
    from ave.http import api_get
    
    await msg.reply_text("Calculating PNL for your BSC wallet...")
    r = await api_get("/address/walletinfo/tokens", {"wallet_address": addr, "chain": "bsc", "sort": "balance_usd", "sort_dir": "desc", "pageSize": 20})
    d = r.json()
    
    lines = ["📊 *Portfolio PNL - BSC*\n"]
    total_bal = 0.0
    total_profit = 0.0
    
    if d.get("status") == 1 and d.get("data"):
        for t in d["data"]:
            bal = float(t.get("balance_usd", 0) or 0)
            if bal <= 0: continue
            profit_pct = float(t.get("profit_pct", 0))
            profit_usd = float(t.get("profit", 0))
            sym = t.get("symbol", "?")
            lines.append(f"{sym}: ${bal:.2f} | P/L: ${profit_usd:.2f} ({profit_pct:.1f}%)")
            total_bal += bal
            total_profit += profit_usd
        
        lines.append(f"\n*Total Balance:* ${total_bal:.2f}")
        lines.append(f"*Total PNL:* ${total_profit:.2f}")
    else:
        lines.append("No active holdings found.")
        
    await msg.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_balance(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = u.message if u.message else u.callback_query.message
    users = load_users(); uid = str(u.effective_user.id)
    if uid not in users or not users[uid].get("assets_id"):
        await msg.reply_text("Use /register first"); return
    await msg.reply_text("Fetching portfolio...")
    aid = users[uid]["assets_id"]
    r = proxy_get("/v1/thirdParty/tx/getSwapOrder", {"chain": "bsc", "assetsId": aid, "pageSize": "50", "pageNO": "0"})
    if r.get("status") not in (200, 0) or not r.get("data"):
        await msg.reply_text("No swap history."); return
    lines = ["Portfolio - BSC\n"]
    total_usd = 0.0; seen = {}
    for o in r["data"]:
        if o.get("status") != "confirmed": continue
        sym = o.get("outTokenSymbol", "?")
        if sym in seen: continue
        seen[sym] = True
        bal = float(o.get("outAmount", "0")) / 1e18
        price = float(o.get("txPriceUsd", "0"))
        usd = bal * price
        total_usd += usd
        lines.append(f"{sym}: {bal:.4f} (${usd:.2f})")
    if len(lines) == 1: await msg.reply_text("No confirmed swaps yet."); return
    lines.append(f"\nTotal: ${total_usd:.2f}")
    await msg.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_signal(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = u.message if u.message else u.callback_query.message
    await msg.reply_text("Scanning for signals (60%+ confidence)...")
    tokens = []; seen = set()
    try:
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
        await msg.reply_text("No tokens found to scan."); return
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
        await msg.reply_text("No signals above 60% confidence right now. Try again later.")
        return
    await msg.reply_text(f"🔔 {len(signals)} Signals Found (≥60% confidence)\n")
    for s in signals[:8]:
        d = "🟢 BUY" if s["chg"] < -3 else "🔴 SELL" if s["chg"] > 5 else "🟡 WATCH"
        text = f"{d} [{s['conf']}%] {s['sym']} | ${round(s['price'], 8)} | 24h:{round(s['chg'],1)}% | Liq:${s['liq']:,.0f}"
        
        keyboard = [
            [
                InlineKeyboardButton(f"Buy 10 USDT", callback_data=f"buy|{s['chain']}|{s['addr']}|10"),
                InlineKeyboardButton(f"Buy 50 USDT", callback_data=f"buy|{s['chain']}|{s['addr']}|50")
            ]
        ]
        await msg.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_trade(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    users = load_users(); uid = str(u.effective_user.id)
    if uid not in users or not users[uid].get("assets_id"): await u.message.reply_text("Use /register first"); return
    if not ctx.args or len(ctx.args) < 2: await u.message.reply_text("Usage: /trade SYMBOL AMOUNT"); return
    sym = ctx.args[0].upper(); amount = float(ctx.args[1])
    sys.path.insert(0, AVENUE_SCRIPTS); from ave.http import api_get
    sr = await api_get("/tokens", {"keyword": sym, "limit": 3, "chain": "bsc"})
    tok_data = sr.json().get("data", [])
    if not tok_data: await u.message.reply_text("Token " + sym + " not found"); return
    ta = tok_data[0].get("token", "").split("-")[0]
    aid = users[uid]["assets_id"]
    usdt = "0x55d398326f99059fF775485246999027B3197955"
    await u.message.reply_text(f"Getting quote for {amount} USDT to {sym}...")
    qr = proxy_post("/v1/thirdParty/tx/sendSwapOrder", {"chain": "bsc", "assetsId": aid, "inTokenAddress": usdt, "outTokenAddress": ta, "inAmount": str(int(amount * 1e6)), "swapType": "buy", "slippage": "500"})
    if qr.get("status") not in (200, 0):
        await u.message.reply_text("Swap failed: " + str(qr.get("msg", ""))); return
    oid = ""
    d = qr.get("data", {})
    if isinstance(d, dict): oid = d.get("id", "")
    elif isinstance(d, list) and d: oid = d[0].get("id", "") if isinstance(d[0], dict) else str(d[0])
    await u.message.reply_text(f"Swap submitted!\nOrder ID: {oid}\n\nCheck /balance after 30s.", parse_mode="Markdown")

async def cmd_topwallets(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = u.message if u.message else u.callback_query.message
    sys.path.insert(0, AVENUE_SCRIPTS); from ave.http import api_get
    chain = "bsc"
    if ctx.args and ctx.args[0].lower() in ("bsc", "eth", "base", "solana"): chain = ctx.args[0].lower()
    await msg.reply_text("Loading top wallets on " + chain.upper() + "...")
    r = await api_get("/address/smart_wallet/list", {"chain": chain, "sort": "profit_above_900_percent_num", "sort_dir": "desc", "profit_900_percent_num_min": 1, "profit_300_900_percent_num_min": 3})
    d = r.json()
    if d.get("status") != 1 or not d.get("data"): await msg.reply_text("No wallets found on " + chain.upper()); return
    
    await msg.reply_text(f"🏆 *Top Smart Money Wallets - {chain.upper()}*", parse_mode="Markdown")
    for i, w in enumerate(d["data"][:8], 1):
        addr = w.get("wallet_address", "")
        short_addr = addr[:10] + "..."
        text = f"{i}. `{short_addr}`\n900%+: {w.get('profit_above_900_percent_num', 0)} | 300-900%: {w.get('profit_300_900_percent_num', 0)}"
        keyboard = [[
            InlineKeyboardButton("Track", callback_data=f"track|{chain}|{addr}"),
            InlineKeyboardButton("Copy Trade (10U)", callback_data=f"copy|{addr}|10")
        ]]
        await msg.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def cmd_track(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    sys.path.insert(0, AVENUE_SCRIPTS); from ave.http import api_get
    if not ctx.args: await u.message.reply_text("Usage: /track ADDRESS [chain]"); return
    addr = ctx.args[0]; chain = "bsc"
    if len(ctx.args) > 1 and ctx.args[1].lower() in ("bsc", "eth", "solana"): chain = ctx.args[1].lower()
    await u.message.reply_text(f"Tracking {addr[:10]}... on {chain.upper()}")
    r = await api_get("/address/walletinfo/tokens", {"wallet_address": addr, "chain": chain, "sort": "balance_usd", "sort_dir": "desc", "pageSize": 8})
    d = r.json()
    lines = [f"Wallet: `{addr}` | {chain.upper()}\n"]
    if d.get("status") == 1 and d.get("data"):
        for t in d["data"][:6]:
            bal = float(t.get("balance_amount", 0) or 0)
            if bal <= 0: continue
            lines.append(f"{t.get('symbol', '?')}: {bal:.4f} | P/L: {t.get('profit_pct', 0):.1f}%")
    else: lines.append("No holdings found")
    await u.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_alert(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if len(ctx.args) < 2:
        await u.message.reply_text("Usage: /alert SYMBOL TARGET_PRICE\nExample: /alert BNB 600")
        return
    sym = ctx.args[0].upper()
    try:
        price = float(ctx.args[1])
    except ValueError:
        await u.message.reply_text("Invalid price.")
        return
        
    users = load_users()
    uid = str(u.effective_user.id)
    if uid not in users:
        await u.message.reply_text("Use /register first")
        return
        
    alerts = users[uid].get("alerts", [])
    alerts.append({"sym": sym, "target": price, "chain": "bsc"})
    users[uid]["alerts"] = alerts
    save_users(users)
    
    await u.message.reply_text(f"✅ Alert set! You will be notified when {sym} is near ${price}.")

async def cmd_copy(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if len(ctx.args) < 2:
        await u.message.reply_text("Usage: /copy ADDRESS AMOUNT\nExample: /copy 0x123... 10")
        return
    addr = ctx.args[0]
    try:
        amt = float(ctx.args[1])
    except ValueError:
        await u.message.reply_text("Invalid amount.")
        return
        
    users = load_users()
    uid = str(u.effective_user.id)
    if uid not in users or not users[uid].get("assets_id"):
        await u.message.reply_text("Use /register first")
        return
        
    users[uid]["copy_target"] = {"address": addr.lower(), "amount": amt, "last_tx": ""}
    save_users(users)
    
    await u.message.reply_text(f"✅ Copy trading activated!\nWatching: `{addr}`\nAmount: {amt} USDT per trade", parse_mode="Markdown")

async def cmd_quote(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await u.message.reply_text("Usage: /quote SYMBOL [AMOUNT]\nExample: /quote ASTER 10")
        return
    sym = ctx.args[0].upper()
    amount = float(ctx.args[1]) if len(ctx.args) > 1 else 10.0
    await u.message.reply_text(f"Getting quote for {amount} USDT → {sym}...")
    sys.path.insert(0, AVENUE_SCRIPTS)
    from ave.http import api_get
    sr = await api_get("/tokens", {"keyword": sym, "limit": 5, "chain": "bsc"})
    tok_data = sr.json().get("data", [])
    if not tok_data:
        await u.message.reply_text(f"Token '{sym}' not found on BSC.")
        return
    ta = tok_data[0].get("token", "").split("-")[0]
    tok_chain = tok_data[0].get("chain", "bsc")
    usdt_addr = "0x55d398326f99059fF775485246999027B3197955"
    in_amount_smallest = str(int(amount * 1e6))
    try:
        qr = proxy_post("/v1/thirdParty/chainWallet/getAmountOut", {
            "chain": tok_chain, "inAmount": in_amount_smallest, "inTokenAddress": usdt_addr,
            "outTokenAddress": ta, "swapType": "buy"
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
    token_amount = estimate_out / (10 ** decimals)
    price_usd = amount / token_amount if token_amount > 0 else 0
    lines = [
        f"💱 Quote: {amount} USDT → {sym}",
        f"Estimated out: {token_amount:,.6f}",
        f"Price: ${price_usd:,.6f}",
        f"Token: `{ta}`"
    ]
    await u.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def handle_callback(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = u.callback_query
    await query.answer()
    data = query.data.split("|")
    
    if data[0] == "cmd":
        cmd = data[1]
        if cmd == "pnl": await cmd_pnl(u, ctx)
        elif cmd == "signal": await cmd_signal(u, ctx)
        elif cmd == "topwallets": await cmd_topwallets(u, ctx)
        elif cmd == "deposit": await cmd_deposit(u, ctx)
        
    elif data[0] == "buy":
        chain = data[1]; ta = data[2]; amount = float(data[3])
        users = load_users()
        uid = str(query.from_user.id)
        if uid not in users or not users[uid].get("assets_id"):
            await query.message.reply_text("Use /register first")
            return
        aid = users[uid]["assets_id"]
        usdt = "0x55d398326f99059fF775485246999027B3197955"
        await query.message.reply_text(f"Executing quick buy for {amount} USDT...")
        qr = proxy_post("/v1/thirdParty/tx/sendSwapOrder", {
            "chain": "bsc", "assetsId": aid, "inTokenAddress": usdt, 
            "outTokenAddress": ta, "inAmount": str(int(amount * 1e6)), 
            "swapType": "buy", "slippage": "500"
        })
        if qr.get("status") not in (200, 0):
            await query.message.reply_text("Swap failed: " + str(qr.get("msg", "")))
            return
        oid = ""
        d = qr.get("data", {})
        if isinstance(d, dict): oid = d.get("id", "")
        elif isinstance(d, list) and d: oid = d[0].get("id", "") if isinstance(d[0], dict) else str(d[0])
        await query.message.reply_text(f"Swap submitted! Order ID: {oid}", parse_mode="Markdown")

    elif data[0] == "track":
        chain = data[1]; addr = data[2]
        sys.path.insert(0, AVENUE_SCRIPTS); from ave.http import api_get
        await query.message.reply_text(f"Tracking {addr[:10]}... on {chain.upper()}")
        r = await api_get("/address/walletinfo/tokens", {"wallet_address": addr, "chain": chain, "sort": "balance_usd", "sort_dir": "desc", "pageSize": 8})
        d = r.json()
        lines = [f"Wallet: `{addr}` | {chain.upper()}\n"]
        if d.get("status") == 1 and d.get("data"):
            for t in d["data"][:6]:
                bal = float(t.get("balance_amount", 0) or 0)
                if bal <= 0: continue
                lines.append(f"{t.get('symbol', '?')}: {bal:.4f} | P/L: {t.get('profit_pct', 0):.1f}%")
        else: lines.append("No holdings found")
        await query.message.reply_text("\n".join(lines), parse_mode="Markdown")

    elif data[0] == "copy":
        addr = data[1]; amt = float(data[2])
        users = load_users()
        uid = str(query.from_user.id)
        if uid not in users or not users[uid].get("assets_id"):
            await query.message.reply_text("Use /register first")
            return
        users[uid]["copy_target"] = {"address": addr.lower(), "amount": amt, "last_tx": ""}
        save_users(users)
        await query.message.reply_text(f"✅ Copy trading activated!\nWatching: `{addr}`\nAmount: {amt} USDT per trade", parse_mode="Markdown")


async def background_tasks(context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    if not users: return
    sys.path.insert(0, AVENUE_SCRIPTS)
    from ave.http import api_get
    
    # Poll Copy Trades
    for uid, data in users.items():
        ct = data.get("copy_target")
        if not ct: continue
        addr = ct["address"]; amt = ct["amount"]; last_tx = ct.get("last_tx", "")
        aid = data.get("assets_id")
        if not aid: continue
        try:
            r = await api_get("/address/tx", {"wallet_address": addr, "chain": "bsc", "limit": 5})
            d = r.json()
            if d.get("status") != 1 or not d.get("data"): continue
            latest_tx = d["data"][0]
            tx_hash = latest_tx.get("tx_hash")
            if tx_hash == last_tx: continue
            if not last_tx:
                users[uid]["copy_target"]["last_tx"] = tx_hash
                save_users(users); continue
            
            direction = latest_tx.get("direction")
            if direction == 1: # Buy
                token_address = latest_tx.get("token")
                token_sym = latest_tx.get("symbol", "Unknown")
                token_addr = token_address.split("-")[0] if "-" in token_address else token_address
                usdt = "0x55d398326f99059fF775485246999027B3197955"
                await context.bot.send_message(chat_id=uid, text=f"🚨 *Copy Trade Triggered!*\nTarget bought {token_sym}.\nExecuting buy for {amt} USDT...", parse_mode="Markdown")
                qr = proxy_post("/v1/thirdParty/tx/sendSwapOrder", {
                    "chain": "bsc", "assetsId": aid, "inTokenAddress": usdt, 
                    "outTokenAddress": token_addr, "inAmount": str(int(amt * 1e6)), 
                    "swapType": "buy", "slippage": "1000"
                })
                if qr.get("status") in (200, 0):
                    await context.bot.send_message(chat_id=uid, text=f"✅ Copy Trade Submitted for {token_sym}!")
                else:
                    await context.bot.send_message(chat_id=uid, text=f"❌ Copy Trade Failed: {qr.get('msg')}")
            
            users[uid]["copy_target"]["last_tx"] = tx_hash
            save_users(users)
        except Exception as e: pass

    # Poll Alerts
    symbols = set()
    for u, data in users.items():
        for alert in data.get("alerts", []):
            symbols.add(alert["sym"])
    if not symbols: return
    
    for sym in symbols:
        try:
            sr = await api_get("/tokens", {"keyword": sym, "limit": 1, "chain": "bsc"})
            tok_data = sr.json().get("data", [])
            if not tok_data: continue
            token_id = tok_data[0].get("token")
            pr = await api_get(f"/tokens/{token_id}")
            pd = pr.json().get("data", {}).get("token", {})
            curr_price = float(pd.get("current_price_usd") or 0)
            if curr_price == 0: continue
            
            for uid, data in users.items():
                alerts = data.get("alerts", [])
                new_alerts = []
                for alert in alerts:
                    if alert["sym"] == sym:
                        target = alert["target"]
                        if abs(curr_price - target) / target < 0.05: # 5% margin
                            await context.bot.send_message(chat_id=uid, text=f"🚨 *PRICE ALERT* 🚨\n\n{sym} has reached near your target of ${target}!\nCurrent Price: ${curr_price:.4f}", parse_mode="Markdown")
                        else:
                            new_alerts.append(alert)
                    else:
                        new_alerts.append(alert)
                if len(alerts) != len(new_alerts):
                    users[uid]["alerts"] = new_alerts
                    save_users(users)
        except Exception as e: pass

def main():
    if not BOT_TOKEN: print("ERROR: TELEGRAM_BOT_TOKEN not set"); return
    app = Application.builder().token(BOT_TOKEN).build()
    for cmd, fn in [
        ("start", cmd_start), ("register", cmd_register), ("deposit", cmd_deposit),
        ("balance", cmd_balance), ("pnl", cmd_pnl), ("quote", cmd_quote), 
        ("signal", cmd_signal), ("trade", cmd_trade), ("topwallets", cmd_topwallets), 
        ("track", cmd_track), ("copy", cmd_copy), ("alert", cmd_alert)
    ]:
        app.add_handler(CommandHandler(cmd, fn))
        
    app.add_handler(CallbackQueryHandler(handle_callback))
    
    # Background jobs every 60 seconds
    app.job_queue.run_repeating(background_tasks, interval=60, first=10)
    
    print("Avegram v2.1 running on proxy wallet mode with PNL & Copy Trading...")
    app.run_polling()

if __name__ == "__main__": main()
