"""SignalBot v2 - Ave proxy wallet integration"""
import os, json, asyncio, sys
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

AVENUE_SCRIPTS = "/home/workspace/ave-cloud-skill/scripts"
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
AVE_API_KEY = os.environ.get("AVE_API_KEY", "")
AVE_SECRET_KEY = os.environ.get("AVE_SECRET_KEY", "")
API_PLAN = os.environ.get("API_PLAN", "pro")
USERS_FILE = "/home/workspace/Avegram/users.json"

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

async def cmd_start(u, ctx):
    await u.message.reply_text(
        "SignalBot v2 - Proxy Wallet Bot\n\n"
        "/register - Create your Ave proxy wallet\n"
        "/deposit - View deposit address\n"
        "/balance - Check portfolio\n"
        "/signal - Scan for signals\n"
        "/trade SYMBOL AMOUNT - Execute swap\n"
        "/topwallets - Smart money wallets\n"
        "/track ADDRESS - Track any wallet\n"
        "/help - Commands\n\n"
        "Powered by Ave Cloud API",
        parse_mode="Markdown"
    )

async def cmd_register(u, ctx):
    users = load_users()
    uid = str(u.effective_user.id)
    if uid in users and users[uid].get("assets_id"):
        w = users[uid]
        bsc_addr = next((a["address"] for a in w.get("address_list", []) if a["chain"] == "bsc"), "N/A")
        await u.message.reply_text("Already registered\nBSC: " + bsc_addr, parse_mode="Markdown")
        return
    r = proxy_post("/v1/thirdParty/user/generateWallet", {"assetsName": "user_" + uid, "returnMnemonic": False})
    if r.get("status") not in (200, 0) or not r.get("data"):
        await u.message.reply_text("Registration failed: " + str(r.get("msg", ""))); return
    d = r["data"][0]
    users[uid] = {"assets_id": d["assetsId"], "address_list": d.get("addressList", []), "username": u.effective_user.username, "chain": "bsc"}
    save_users(users)
    bsc_addr = next((a["address"] for a in d.get("addressList", []) if a["chain"] == "bsc"), "N/A")
    await u.message.reply_text(
        "Wallet created on Ave proxy!\n\nBSC: " + bsc_addr + "\n\nDeposit USDT BEP20 to the BSC address above, then use /balance",
        parse_mode="Markdown"
    )

async def cmd_deposit(u, ctx):
    users = load_users(); uid = str(u.effective_user.id)
    if uid not in users or not users[uid].get("assets_id"):
        await u.message.reply_text("Use /register first"); return
    addr = next((a["address"] for a in users[uid].get("address_list", []) if a["chain"] == "bsc"), "N/A")
    await u.message.reply_text(
        "Deposit Address (BSC BEP20)\n\n" + addr + "\n\nDeposit USDT to this address",
        parse_mode="Markdown"
    )

async def cmd_balance(u, ctx):
    users = load_users(); uid = str(u.effective_user.id)
    if uid not in users or not users[uid].get("assets_id"):
        await u.message.reply_text("Use /register first"); return
    await u.message.reply_text("Fetching portfolio...")
    aid = users[uid]["assets_id"]
    r = proxy_get("/v1/thirdParty/tx/getSwapOrder", {"chain": "bsc", "assetsId": aid, "pageSize": "50", "pageNO": "0"})
    if r.get("status") not in (200, 0) or not r.get("data"):
        await u.message.reply_text("No swap history. Deposit USDT to your BSC wallet address then try /balance again."); return
    lines = ["Portfolio - BSC\n"]
    total_usd = 0.0
    seen = {}
    for o in r["data"]:
        if o.get("status") != "confirmed": continue
        sym = o.get("outTokenSymbol", "?")
        if sym in seen: continue
        seen[sym] = True
        bal = float(o.get("outAmount", "0")) / 1e18
        price = float(o.get("txPriceUsd", "0"))
        usd = bal * price
        total_usd += usd
        lines.append(sym + ": " + str(round(bal, 4)) + " ($" + str(round(usd, 2)) + ")")
    if len(lines) == 1: await u.message.reply_text("No confirmed swaps yet."); return
    lines.append("\nTotal: $" + str(round(total_usd, 2)))
    await u.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_signal(u, ctx):
    sys.path.insert(0, AVENUE_SCRIPTS)
    from ave.http import api_get
    await u.message.reply_text("Scanning for signals...")
    seen = set(); tokens = []
    for tag in ["hot", "defi", "meme"]:
        try:
            pr = await api_get("/tokens/platform", {"tag": tag, "limit": 8, "chain": "bsc"})
            for t in pr.json().get("data", []):
                a = t.get("token", "").split("-")[0]
                if a and a not in seen: seen.add(a); t["token"] = a; tokens.append(t)
        except: pass
    if not tokens: await u.message.reply_text("No signals found."); return
    signals = []
    for tok in tokens[:20]:
        try:
            ta = tok.get("token", ""); tid = ta + "-bsc"
            pr = await api_get("/tokens/" + tid); rd = await api_get("/contracts/" + tid)
            pd = pr.json().get("data", {}).get("token", {}); rd2 = rd.json().get("data", {})
            price = float(pd.get("current_price_usd") or 0)
            liq = float(pd.get("liquidity") or pd.get("tvl") or 0)
            vol = float(pd.get("tx_volume_u_24h") or 0)
            chg = float(pd.get("price_change_24h") or 0)
            if rd2.get("is_honeypot") == 1 or price == 0: continue
            conf = 0
            if liq > 50000: conf += 30
            if vol > 10000: conf += 30
            if abs(chg) > 5: conf += 20
            if rd2.get("risk_score", 50) < 30: conf += 20
            conf = min(100, conf)
            if conf >= 60: signals.append({"conf": conf, "sym": tok.get("symbol", "?"), "price": price, "chg": chg, "liq": liq, "vol": vol, "addr": ta})
        except: continue
    signals.sort(key=lambda x: x["conf"], reverse=True)
    if not signals: await u.message.reply_text("No signals above 60% confidence right now."); return
    lines = [str(len(signals)) + " signals found (60%+ confidence)\n"]
    for s in signals[:8]:
        d = "BUY" if s["chg"] < -3 else "SELL" if s["chg"] > 5 else "WATCH"
        lines.append(d + " [" + str(s["conf"]) + "%] " + s["sym"] + " | $" + str(round(s["price"], 8)) + " | 24h:" + str(round(s["chg"], 1)) + "%")
    await u.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_trade(u, ctx):
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
    await u.message.reply_text("Getting quote for " + str(amount) + " USDT to " + sym + "...")
    qr = proxy_post("/v1/thirdParty/tx/sendSwapOrder", {"chain": "bsc", "assetsId": aid, "inTokenAddress": usdt, "outTokenAddress": ta, "inAmount": str(int(amount * 1e6)), "swapType": "buy", "slippage": "500"})
    if qr.get("status") not in (200, 0):
        await u.message.reply_text("Swap failed: " + str(qr.get("msg", ""))); return
    oid = ""
    d = qr.get("data", {})
    if isinstance(d, dict): oid = d.get("id", "")
    elif isinstance(d, list) and d: oid = d[0].get("id", "") if isinstance(d[0], dict) else str(d[0])
    await u.message.reply_text("Swap submitted!\nOrder ID: " + oid + "\n\nCheck /balance after 30s for confirmation.", parse_mode="Markdown")

async def cmd_topwallets(u, ctx):
    sys.path.insert(0, AVENUE_SCRIPTS); from ave.http import api_get
    chain = "bsc"
    if ctx.args and ctx.args[0].lower() in ("bsc", "eth", "base", "solana"): chain = ctx.args[0].lower()
    await u.message.reply_text("Loading top wallets on " + chain.upper() + "...")
    r = await api_get("/address/smart_wallet/list", {"chain": chain, "sort": "profit_above_900_percent_num", "sort_dir": "desc", "profit_900_percent_num_min": 1, "profit_300_900_percent_num_min": 3})
    d = r.json()
    if d.get("status") != 1 or not d.get("data"): await u.message.reply_text("No wallets found on " + chain.upper()); return
    lines = ["Top Smart Money Wallets - " + chain.upper() + "\n"]
    for i, w in enumerate(d["data"][:8], 1):
        addr = w.get("wallet_address", "")[:10] + "..."
        lines.append(str(i) + ". " + addr + " | 900%+: " + str(w.get("profit_above_900_percent_num", 0)) + " | 300-900%: " + str(w.get("profit_300_900_percent_num", 0)))
        lines.append("   /track " + w.get("wallet_address", ""))
    await u.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_track(u, ctx):
    sys.path.insert(0, AVENUE_SCRIPTS); from ave.http import api_get
    if not ctx.args: await u.message.reply_text("Usage: /track ADDRESS [chain]"); return
    addr = ctx.args[0]; chain = "bsc"
    if len(ctx.args) > 1 and ctx.args[1].lower() in ("bsc", "eth", "solana"): chain = ctx.args[1].lower()
    await u.message.reply_text("Tracking " + addr[:10] + "... on " + chain.upper())
    r = await api_get("/address/walletinfo/tokens", {"wallet_address": addr, "chain": chain, "sort": "balance_usd", "sort_dir": "desc", "pageSize": 8})
    d = r.json()
    lines = ["Wallet: " + addr[:20] + "... | " + chain.upper() + "\n"]
    if d.get("status") == 1 and d.get("data"):
        for t in d["data"][:6]:
            bal = float(t.get("balance_amount", 0) or 0)
            if bal <= 0: continue
            lines.append(t.get("symbol", "?") + ": " + str(round(bal, 4)) + " | P/L: " + str(round(float(t.get("profit_pct", 0), 1))) + "%")
    else: lines.append("No holdings found")
    await u.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_help(u, ctx): await u.message.reply_text("/register /deposit /balance /signal /trade SYM AMOUNT /topwallets [chain] /track ADDRESS /help", parse_mode="Markdown")

def main():
    if not BOT_TOKEN: print("ERROR: TELEGRAM_BOT_TOKEN not set"); return
    app = Application.builder().token(BOT_TOKEN).build()
    for cmd, fn in [("start", cmd_start), ("register", cmd_register), ("deposit", cmd_deposit), ("balance", cmd_balance), ("signal", cmd_signal), ("trade", cmd_trade), ("topwallets", cmd_topwallets), ("track", cmd_track), ("help", cmd_help)]:
        app.add_handler(CommandHandler(cmd, fn))
    print("Avegram v2 running on proxy wallet mode...")
    app.run_polling()

if __name__ == "__main__": main()
