def get_bsc_address(user_row):
    addr_list = user_row.get("address_list", []) or []
    bsc_addr = next((a.get("address") for a in addr_list if a.get("chain") == "bsc" and (a.get("address") or "").startswith("0x")), None)
    if not bsc_addr and addr_list:
        bsc_addr = next((a.get("address") for a in addr_list if (a.get("address") or "").startswith("0x")), None)
    return bsc_addr

def clear_user_session_keys(users, uid, keys):
    u = users.get(uid)
    if not isinstance(u, dict):
        return
    for k in keys:
        if k in u:
            del u[k]

