# CAPABILITY: process-level config — environment only. Everything a parent configures lives in the `settings`
#             table (settings.py) and is edited in the web UI. No secrets here, ever.
import os

VERSION = "1.0.0"
DB_PATH = os.environ.get("AUTOGUARD_DB", "/data/autoguard.db")
PORT = int(os.environ.get("PORT", "8095"))
UA = f"autoguard/{VERSION}"
