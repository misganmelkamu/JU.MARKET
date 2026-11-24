"""
Configuration for the sales bot.
All secrets come from environment variables (set them in a .env file locally,
or in your hosting provider's "Environment Variables" panel).
"""
import os
from dotenv import load_dotenv

load_dotenv()  # loads variables from a local .env file if present

# --- Required ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Comma-separated Telegram numeric user IDs of admins, e.g. "123456789,987654321"
ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}

# --- Payment instructions shown to the customer (manual bank transfer) ---
BANK_DETAILS = os.getenv(
    "BANK_DETAILS",
    "Bank: YOUR BANK NAME\n"
    "Account name: YOUR NAME\n"
    "Account number: 0000000000\n"
    "Reference: (use the order code the bot gives you)"
)

# Currency symbol/code used for display only
CURRENCY = os.getenv("CURRENCY", "USD")

DB_PATH = os.getenv("DB_PATH", "shop.db")

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN is not set. Create a .env file (see .env.example) "
        "or set the environment variable before running the bot."
    )

if not ADMIN_IDS:
    print(
        "WARNING: No ADMIN_IDS configured. Nobody will receive order "
        "notifications or be able to use /orders, /addproduct, etc. "
        "Set ADMIN_IDS in your .env file to your numeric Telegram user ID."
    )
