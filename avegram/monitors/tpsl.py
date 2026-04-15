import asyncio

from ave.http import api_get

from ..db import load_trades, load_users, save_trades, db_log_error, db_heartbeat_ok, db_heartbeat_error, db_upsert_token_meta
from ..proxy import proxy_get, send_swap_order
from ..utils import get_bsc_address

async def monitor_tp_sl(app):
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
                    if t.get("status") != "active":
                        continue
                    chain = t.get("chain", "bsc")
                    sym = t.get("symbol", "?")
                    entry = float(t.get("entry_price", 0) or 0)
                    if entry == 0:
                        continue

                    pr = await api_get(f"/tokens/{ta}-{chain}")
                    if pr.status_code != 200 or not pr.json().get("data"):
                        continue
                    curr_price = float(pr.json()["data"].get("token", {}).get("current_price_usd", 0))
                    if curr_price == 0:
                        continue

                    tp_target = entry * (1 + (t["tp_pct"] / 100))
                    sl_target = entry * (1 + (t["sl_pct"] / 100))

                    hit_type = None
                    if curr_price >= tp_target:
                        hit_type = "Take-Profit"
                    elif curr_price <= sl_target:
                        hit_type = "Stop-Loss"

                    if hit_type:
                        bal = 0.0
                        decimals = 18
                        bsc_addr = get_bsc_address(users.get(uid, {}))
                        if bsc_addr:
                            tr = proxy_get("/address/walletinfo/tokens", {
                                "wallet_address": bsc_addr,
                                "chain": chain,
                                "sort": "balance_usd",
                                "sort_dir": "desc",
                                "pageSize": "200"
                            })
                            if tr.get("status") == 1 and tr.get("data"):
                                for tok in tr["data"]:
                                    tok_addr = (tok.get("token") or "").split("-")[0].lower()
                                    if tok_addr == ta.lower():
                                        bal = float(tok.get("balance_amount", 0) or 0)
                                        decimals = int(tok.get("decimals") or tok.get("token_decimals") or 18)
                                        db_upsert_token_meta(chain, ta, symbol=sym, decimals=decimals)
                                        break

                        if bal <= 0.0001:
                            del trades[uid][ta]
                            changed = True
                            continue

                        in_amount_smallest = str(int(bal * (10 ** decimals)))
                        qr = send_swap_order(uid, chain, aid, ta, usdt_addr, in_amount_smallest, "sell", slippage="1500", context={"source": "tpsl"})

                        if qr.get("status") in (200, 0):
                            pnl_pct = ((curr_price - entry) / entry) * 100
                            usd_out = bal * curr_price
                            msg = f"🚨 **{hit_type} Hit!**\n\nSold {round(bal, 4)} {sym} for ~${usd_out:.2f}\nPNL: {pnl_pct:+.2f}%\nPrice: ${curr_price:.6f}"
                            await app.bot.send_message(chat_id=uid, text=msg, parse_mode="Markdown")
                            del trades[uid][ta]
                            changed = True
                        else:
                            db_log_error("tpsl_sell_failed", qr.get("msg", "sell failed"), telegram_id=uid, context={"resp": qr, "token": ta, "symbol": sym, "chain": chain})

            if changed:
                save_trades(trades)
            db_heartbeat_ok("monitor_tp_sl")

        except Exception as e:
            db_log_error("tpsl_monitor_error", e)
            try:
                db_heartbeat_error("monitor_tp_sl", e)
            except Exception:
                pass

        await asyncio.sleep(30)

