# Telegram Sales Bot (manual payment, digital goods)

A self-contained Telegram bot for selling digital goods (Premium codes,
Stars, downloadable files, etc.) with a manual "pay by bank transfer, admin
confirms" flow — similar in spirit to storefront bots like NovaPluset.

## What it does

- Customers browse a catalog (`Category → Product → Buy`)
- Bot creates an order with a unique reference and shows your bank details
- Customer sends a payment screenshot; the order goes to "pending confirmation"
- All admins get the screenshot with **Approve / Reject** buttons
- On approve: if the product has a file attached, it's sent automatically;
  otherwise you're reminded to deliver it manually (e.g. gift a Premium code)
- Customers can check `My Orders` any time; admins get `/orders` and `/stats`

Everything is stored in a local SQLite file (`shop.db`) — no external database needed.

## 1. Create the bot

1. Open Telegram, message **@BotFather**, send `/newbot`, follow the prompts.
2. Copy the token it gives you (looks like `123456789:AAExample...`).
3. Message **@userinfobot** to get your own numeric Telegram user ID — you'll be the admin.

## 2. Configure

```bash
cp .env.example .env
```

Edit `.env`:

```
BOT_TOKEN=your_botfather_token
ADMIN_IDS=your_numeric_id            # comma-separate for multiple admins
BANK_DETAILS="Bank: ...\nAccount: ...\nReference: use the order code"
CURRENCY=USD
```

## 3. Run it locally (to test)

```bash
pip install -r requirements.txt
python3 main.py
```

Open your bot in Telegram and send `/start`.

As the admin, add your first product:

```
/addproduct
```

and follow the prompts (category → name → description → price → stock →
optional file upload).

## 4. Hosting — you said "not sure", so here are three good options

### Option A: Railway.app (easiest, free tier available)
1. Push this folder to a GitHub repo (private is fine).
2. Go to railway.app → New Project → Deploy from GitHub repo.
3. In the project's **Variables** tab, add `BOT_TOKEN`, `ADMIN_IDS`,
   `BANK_DETAILS`, `CURRENCY` (same as your `.env`).
4. Railway auto-detects Python; set the **Start Command** to `python3 main.py`.
5. Deploy. Check the logs for "Bot starting (polling)..." — that means it's live.

Note: Railway's free tier sleeps/limits usage after a while — fine for
testing, upgrade to a small paid plan for a bot that must always be online.

### Option B: Render.com (Background Worker)
1. Push to GitHub, same as above.
2. New → Background Worker (not "Web Service" — this bot doesn't listen on
   a port, it polls Telegram).
3. Build command: `pip install -r requirements.txt`
   Start command: `python3 main.py`
4. Add the same environment variables in Render's dashboard.
5. Deploy.

### Option C: Your own VPS (most control, ~$4-6/mo)
Any small VPS (DigitalOcean, Hetzner, Contabo) works:

```bash
sudo apt update && sudo apt install -y python3-pip python3-venv
git clone <your-repo-url> salesbot && cd salesbot
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then edit it
```

Keep it running permanently with `systemd`:

```ini
# /etc/systemd/system/salesbot.service
[Unit]
Description=Telegram Sales Bot
After=network.target

[Service]
WorkingDirectory=/root/salesbot
ExecStart=/root/salesbot/venv/bin/python3 main.py
Restart=always
EnvironmentFile=/root/salesbot/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now salesbot
sudo journalctl -u salesbot -f   # view logs
```

**Recommendation:** start with Railway or Render to get it live in minutes;
move to a VPS later if you outgrow the free tier or want full control.

## Admin commands

| Command | Description |
|---|---|
| `/addproduct` | Guided flow to add a new product |
| `/products` | List all products (active and hidden) |
| `/orders` | List orders awaiting payment confirmation |
| `/stats` | Users, orders, revenue summary |

## Customizing

- **Products**: add via `/addproduct`, or edit `shop.db` directly with any
  SQLite browser (e.g. "DB Browser for SQLite").
- **Bank details / currency**: edit the `.env` file and restart the bot.
- **Auto-delivered files**: when adding a product, upload the file at the
  last step — it will be sent to the customer automatically the moment an
  admin taps Approve.
- **Telegram Stars / in-app payments instead of manual transfer**: this is a
  bigger change (uses Telegram's native invoice API) — happy to add it if
  you want to switch later.

## Important notes

- Only user IDs listed in `ADMIN_IDS` can approve/reject orders or manage
  products — keep that list accurate.
- This bot polls Telegram (`run_polling`) rather than using webhooks, which
  is simpler to deploy and is fine for most shop volumes.
- Back up `shop.db` periodically (it holds your products and order history).
