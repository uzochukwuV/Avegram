from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..db import load_users
from ..proxy import proxy_get, proxy_post
from ..utils import clear_user_session_keys

def auto_link_wallet(uid_str, username=None):
    users = load_users()
    if uid_str in users and users[uid_str].get("assets_id"):
        return True

    r = proxy_get("/v1/thirdParty/user/getUserByAssetsId")
    if r.get("status") in (200, 0) and r.get("data"):
        wallets = r["data"]
        if wallets:
            w = wallets[0]
            if uid_str not in users:
                users[uid_str] = {"chain": "bsc"}
            if username:
                users[uid_str]["username"] = username
            users[uid_str]["assets_id"] = w["assetsId"]
            users[uid_str]["address_list"] = w.get("addressList", [])
            from ..db import save_users
            save_users(users)
            return True

    return False

async def show_main_menu(message, uid, edit=False, username=None):
    auto_link_wallet(str(uid), username=username)
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

