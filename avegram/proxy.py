"""Async proxy-wallet API calls via Ave Cloud skill HTTP client."""

from __future__ import annotations

import sys
import os

# Ensure the ave-cloud-skill module is on the path
_SKILL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ave-cloud-skill", "scripts")
if _SKILL_PATH not in sys.path:
    sys.path.insert(0, _SKILL_PATH)

os.environ.setdefault("AVE_IN_SERVER", "1")

from ave.http import trade_get, trade_post  # skill's authenticated async HTTP

from .db import db_insert_swap_order, db_log_error


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

async def proxy_get(path: str, params: dict | None = None) -> dict:
    """Authenticated GET to bot-api.ave.ai. Returns parsed JSON dict."""
    resp = await trade_get(path, params, proxy=True)
    try:
        return resp.json()
    except Exception:
        return {"status": resp.status_code, "msg": resp.text[:200]}


async def proxy_post(path: str, body: dict) -> dict:
    """Authenticated POST to bot-api.ave.ai. Returns parsed JSON dict."""
    resp = await trade_post(path, body, proxy=True)
    try:
        return resp.json()
    except Exception:
        return {"status": resp.status_code, "msg": resp.text[:200]}


# ---------------------------------------------------------------------------
# Wallet management
# ---------------------------------------------------------------------------

async def list_wallets(assets_ids: str | None = None) -> dict:
    """List proxy wallets. Pass comma-separated assetsIds to filter."""
    params = {}
    if assets_ids:
        params["assetsIds"] = assets_ids
    return await proxy_get("/v1/thirdParty/user/getUserByAssetsId", params or None)


async def create_wallet(name: str) -> dict:
    return await proxy_post("/v1/thirdParty/user/generateWallet", {"assetsName": name, "returnMnemonic": False})


# ---------------------------------------------------------------------------
# Trading
# ---------------------------------------------------------------------------

async def get_quote(chain: str, in_token: str, out_token: str, in_amount: str, swap_type: str) -> dict:
    """Get estimated swap output amount."""
    return await proxy_post("/v1/thirdParty/chainWallet/getAmountOut", {
        "chain": chain,
        "inAmount": in_amount,
        "inTokenAddress": in_token,
        "outTokenAddress": out_token,
        "swapType": swap_type,
    })


async def get_auto_slippage(chain: str, token_address: str) -> dict:
    """Get recommended slippage for a token."""
    return await proxy_post("/v1/thirdParty/chainWallet/getAutoSlippage", {
        "chain": chain,
        "tokenAddress": token_address,
        "useMev": False,
    })


async def send_swap_order(
    telegram_id,
    chain: str,
    assets_id: str,
    in_token: str,
    out_token: str,
    in_amount,
    swap_type: str,
    slippage: str = "1500",
    auto_slippage: bool = False,
    context: dict | None = None,
) -> dict:
    payload = {
        "chain": chain,
        "assetsId": assets_id,
        "inTokenAddress": in_token,
        "outTokenAddress": out_token,
        "inAmount": str(in_amount),
        "swapType": swap_type,
        "slippage": str(slippage),
        "useMev": False,
    }
    if auto_slippage:
        payload["autoSlippage"] = True
    try:
        resp = await proxy_post("/v1/thirdParty/tx/sendSwapOrder", payload)
    except Exception as e:
        db_log_error("sendSwapOrder_exception", e, telegram_id=telegram_id,
                     context={"payload": payload, "context": context or {}})
        raise
    db_insert_swap_order(telegram_id, chain, in_token, out_token, in_amount, swap_type, resp, context=context)
    if resp.get("status") not in (200, 0):
        db_log_error("sendSwapOrder_failed", resp.get("msg", "Unknown Error"),
                     telegram_id=telegram_id,
                     context={"payload": payload, "resp": resp, "context": context or {}})
    return resp


async def send_limit_order(
    telegram_id,
    chain: str,
    assets_id: str,
    in_token: str,
    out_token: str,
    in_amount,
    swap_type: str,
    limit_price: str,
    slippage: str = "500",
    expire_time: int | None = None,
    context: dict | None = None,
) -> dict:
    payload = {
        "chain": chain,
        "assetsId": assets_id,
        "inTokenAddress": in_token,
        "outTokenAddress": out_token,
        "inAmount": str(in_amount),
        "swapType": swap_type,
        "slippage": str(slippage),
        "limitPrice": str(limit_price),
        "useMev": False,
    }
    if expire_time:
        payload["expireTime"] = expire_time
    try:
        resp = await proxy_post("/v1/thirdParty/tx/sendLimitOrder", payload)
    except Exception as e:
        db_log_error("sendLimitOrder_exception", e, telegram_id=telegram_id,
                     context={"payload": payload, "context": context or {}})
        raise
    db_insert_swap_order(telegram_id, chain, in_token, out_token, in_amount, f"limit_{swap_type}", resp, context=context)
    return resp


async def cancel_limit_orders(chain: str, order_ids: list[str]) -> dict:
    return await proxy_post("/v1/thirdParty/tx/cancelLimitOrder", {"chain": chain, "ids": order_ids})


async def get_limit_orders(chain: str, assets_id: str, page_size: int = 20, page_no: int = 0, status: str | None = None) -> dict:
    params: dict = {"chain": chain, "assetsId": assets_id, "pageSize": page_size, "pageNo": page_no}
    if status:
        params["status"] = status
    return await proxy_get("/v1/thirdParty/tx/getLimitOrder", params)


async def get_swap_orders(chain: str, order_ids: str) -> dict:
    return await proxy_get("/v1/thirdParty/tx/getSwapOrder", {"chain": chain, "ids": order_ids})


# ---------------------------------------------------------------------------
# Transfer / withdraw
# ---------------------------------------------------------------------------

async def transfer_tokens(
    telegram_id,
    chain: str,
    assets_id: str,
    from_address: str,
    to_address: str,
    token_address: str,
    amount: str,
    context: dict | None = None,
) -> dict:
    payload = {
        "chain": chain,
        "assetsId": assets_id,
        "fromAddress": from_address,
        "toAddress": to_address,
        "tokenAddress": token_address,
        "amount": str(amount),
    }
    try:
        resp = await proxy_post("/v1/thirdParty/tx/transfer", payload)
    except Exception as e:
        db_log_error("transfer_exception", e, telegram_id=telegram_id, context={"payload": payload})
        raise
    if resp.get("status") not in (200, 0):
        db_log_error("transfer_failed", resp.get("msg", "Unknown"), telegram_id=telegram_id,
                     context={"payload": payload, "resp": resp})
    return resp


async def get_transfer_status(chain: str, transfer_ids: str) -> dict:
    return await proxy_get("/v1/thirdParty/tx/getTransfer", {"chain": chain, "ids": transfer_ids})
