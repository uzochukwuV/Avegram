import os
from dotenv import load_dotenv

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# override=True allows a local .env to shadow already-set environment variables,
# which is useful for development (e.g. pointing at a local DB instead of the
# remote one that might be unreachable from this machine).
load_dotenv(os.path.join(ROOT_DIR, ".env"), override=True)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
AVE_API_KEY = os.environ.get("AVE_API_KEY", "")
AVE_SECRET_KEY = os.environ.get("AVE_SECRET_KEY", "")
API_PLAN = os.environ.get("API_PLAN", "pro")

DB_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or os.environ.get("PRISMA_DATABASE_URL") or ""

# Primary test wallet (used by API server for live tests)
PRIMARY_ASSETS_ID = os.environ.get("PRIMARY_ASSETS_ID", "")

# Ensure the skill's http client runs in async server mode
os.environ.setdefault("AVE_IN_SERVER", "1")

