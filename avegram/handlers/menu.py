from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..db import load_users, save_users
from ..proxy import list_wallets
from ..utils import clear_user_session_keys


async def auto_link_wallet(uid_str: str, username: str | None = None) -> bool:
    """
    Ensure a user has a proxy wallet linked in the DB.

    1. If user already has an assetsId stored → return True immediately.
    2. Otherwise query Ave for all wallets and find the one whose assetsName
       matches the pattern we use at registration: ``user_<last8 of uid>``.
    3. If found, upsert the user record and return True.
    4. If not found, return False (caller should prompt /register).
    """
    users = load_users()
    if uid_str in users and users[uid_str].get("assets_id"):
        return True

    try:
        r = await list_wallets()
        wallets = r.get("data") or []
        if not isinstance(wallets, list):
            wallets = []

        # Match by assetsName pattern
        name_pattern = "user_" + uid_str[-8:]
        match = next(
            (w for w in wallets if w.get("assetsName") == name_pattern),
            None,
        )
        # Fallback: single wallet API key (solo user)
        if match is None and len(wallets) == 1:
            match = wallets[0]

        if match:
            if uid_str not in users:
                users[uid_str] = {"chain": "bsc"}
            if username:
                users[uid_str]["username"] = username
            users[uid_str]["assets_id"] = match["assetsId"]
            users[uid_str]["address_list"] = match.get("addressList", [])
            save_users(users)
            return True
    except Exception:
        pass

    return False


async def show_main_menu(message, uid, edit: bool = False, username: str | None = None):
    await auto_link_wallet(str(uid), username=username)
    users = load_users()
    uid_str = str(uid)
    text = "🚀 *Avegram Dashboard*\n\nPowered by Ave Cloud API"

    if uid_str not in users or not users[uid_str].get("assets_id"):
        keyboard = [[InlineKeyboardButton("💳 Create Wallet", callback_data="cb_register")]]
    else:
        keyboard = [
            [InlineKeyboardButton("📊 Portfolio", callback_data="cb_balance"),
             InlineKeyboardButton("🔎 Analyse", callback_data="cb_analyse")],
            [InlineKeyboardButton("💱 Trade", callback_data="cb_trade"),
             InlineKeyboardButton("📡 Signals", callback_data="cb_signal")],
            [InlineKeyboardButton("⬇️ Deposit", callback_data="cb_deposit"),
             InlineKeyboardButton("⬆️ Withdraw", callback_data="cb_withdraw")],
            [InlineKeyboardButton("📋 Limit Orders", callback_data="cb_limit"),
             InlineKeyboardButton("🐋 Smart Money", callback_data="cb_topwallets")],
            [InlineKeyboardButton("❓ Help", callback_data="cb_help")],
        ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    if edit:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
