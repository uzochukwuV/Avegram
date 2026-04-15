import base64
import datetime
import hashlib
import hmac
import json
import urllib.parse
import urllib.request

from .config import AVE_API_KEY, AVE_SECRET_KEY
from .db import db_insert_swap_order, db_log_error

def proxy_headers(method, path, body=None):
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    msg = ts + method.upper().strip() + path.strip()
    if body:
        msg += json.dumps(body, sort_keys=True, separators=(",", ":"))
    sig = base64.b64encode(hmac.new(AVE_SECRET_KEY.encode(), msg.encode(), hashlib.sha256).digest()).decode()
    return {"AVE-ACCESS-KEY": AVE_API_KEY, "AVE-ACCESS-TIMESTAMP": ts, "AVE-ACCESS-SIGN": sig, "Content-Type": "application/json"}

def proxy_get(path, params=None):
    url = "https://bot-api.ave.ai" + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=proxy_headers("GET", path))
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def proxy_post(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request("https://bot-api.ave.ai" + path, data=data, headers=proxy_headers("POST", path, body))
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def send_swap_order(telegram_id, chain, assets_id, in_token, out_token, in_amount, swap_type, slippage="1500", context=None):
    payload = {
        "chain": chain,
        "assetsId": assets_id,
        "inTokenAddress": in_token,
        "outTokenAddress": out_token,
        "inAmount": str(in_amount),
        "swapType": swap_type,
        "slippage": str(slippage),
    }
    try:
        resp = proxy_post("/v1/thirdParty/tx/sendSwapOrder", payload)
    except Exception as e:
        db_log_error("sendSwapOrder_exception", e, telegram_id=telegram_id, context={"payload": payload, "context": context or {}})
        raise
    db_insert_swap_order(telegram_id, chain, in_token, out_token, in_amount, swap_type, resp, context=context)
    if resp.get("status") not in (200, 0):
        db_log_error("sendSwapOrder_failed", resp.get("msg", "Unknown Error"), telegram_id=telegram_id, context={"payload": payload, "resp": resp, "context": context or {}})
    return resp

