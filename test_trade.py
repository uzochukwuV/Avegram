import os
import sys
import json
import asyncio
from dotenv import load_dotenv

# Setup path and env
AVENUE_SCRIPTS = "/workspace/ave-cloud-skill/scripts"
sys.path.insert(0, AVENUE_SCRIPTS)
load_dotenv("/workspace/.env")

# Ensure required env vars are loaded
if not os.environ.get("AVE_API_KEY") or not os.environ.get("AVE_SECRET_KEY"):
    print("Error: AVE_API_KEY or AVE_SECRET_KEY not set in environment.")
    sys.exit(1)

# Import Ave modules after path is set
from ave.http import api_get
from signal_telegram import proxy_post, load_users

async def run_test_trade():
    users = load_users()
    uid = "7614171263"  # @visualise_crypto
    
    if uid not in users or not users[uid].get("assets_id"):
        print(f"Error: User {uid} not found in users.json or missing assets_id.")
        return
        
    aid = users[uid]["assets_id"]
    print(f"Loaded User {uid} with assets_id: {aid}")
    
    # Let's test with PEPE on BSC
    sym = "PEPE"
    amount = 5.0  # $5 USDT
    chain = "bsc"
    
    print(f"\nLooking up token {sym} on {chain.upper()}...")
    sr = await api_get("/tokens", {"keyword": sym, "limit": 3, "chain": chain})
    tok_data = sr.json().get("data", [])
    
    if not tok_data:
        print(f"Token {sym} not found on {chain}.")
        return
        
    ta = tok_data[0].get("token", "").split("-")[0]
    print(f"Found Token Address: {ta}")
    
    usdt = "0x55d398326f99059fF775485246999027B3197955"
    amount_wei = str(int(amount * 1e18)) # USDT has 18 decimals on BSC
    
    print(f"\nExecuting ${amount} Buy Order for {sym}...")
    payload = {
        "chain": chain, 
        "assetsId": aid, 
        "inTokenAddress": usdt, 
        "outTokenAddress": ta, 
        "inAmount": amount_wei, 
        "swapType": "buy", 
        "slippage": "1000"
    }
    
    try:
        qr = proxy_post("/v1/thirdParty/tx/sendSwapOrder", payload)
        
        if qr.get("status") not in (200, 0):
            print(f"❌ Buy failed: {qr.get('msg', '')}")
            print(json.dumps(qr, indent=2))
            return
            
        d = qr.get("data", {})
        oid = ""
        if isinstance(d, dict): oid = d.get("id", "")
        elif isinstance(d, list) and d: oid = d[0].get("id", "") if isinstance(d[0], dict) else str(d[0])
        
        print(f"\n✅ SUCCESS! Swap submitted.")
        print(f"Order ID: {oid}")
        print(json.dumps(qr, indent=2))
        
    except Exception as e:
        print(f"Exception during trade execution: {e}")

if __name__ == "__main__":
    asyncio.run(run_test_trade())