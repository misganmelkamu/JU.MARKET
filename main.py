"""
Telegram sales bot for digital goods (Premium, Stars, files, etc.) with
manual "bank transfer, admin confirms" payments.

Flow
----
Customer:
  /start -> Shop -> pick category -> pick product -> Buy -> choose quantity
  -> bot shows bank details + a unique order reference
  -> customer sends a screenshot/proof of payment as a photo
  -> order goes to "awaiting_confirmation" and admins are notified
  -> admin taps Approve/Reject
  -> on Approve: if the product has a file attached it's sent automatically,
     otherwise the admin is reminded to deliver it manually (e.g. gift a
     Telegram Premium code) and the customer is notified their order is paid.

Admin (only user IDs in config.ADMIN_IDS):
  /addproduct   - guided flow to add a new product
  /products     - list all products (with hide/show)
  /orders       - list orders awaiting confirmation
  /stats        - quick shop stats
"""
import logging

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

import config
import database as db

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---- conversation states ----
BUY_QTY = 1
BUY_PROOF = 2
ADD_CATEGORY, ADD_NAME, ADD_DESC, ADD_PRICE, ADD_STOCK, ADD_FILE = range(10, 16)
EDIT_FIELD, EDIT_VALUE = range(20, 22)


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍 Shop", callback_data="menu:shop")],
        [InlineKeyboardButton("📦 My Orders", callback_data="menu:myorders")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="menu:help")],
    ])


# ----------------------------------------------------------------------
# Basic navigation
# ----------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.upsert_user(user.id, user.username or "", user.first_name or "")
    text = (
        f"Welcome, {user.first_name}! 👋\n\n"
        "This is an automated shop. Browse products, place an order, and "
        "send your payment proof — an admin will confirm it shortly."
    )
    await update.message.reply_text(text, reply_markup=main_menu_kb())


async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "menu:shop":
        await show_categories(query)
    elif data == "menu:myorders":
        await show_my_orders(query)
    elif data == "menu:help":
        await query.edit_message_text(
            "How it works:\n"
            "1. Shop → pick a product → Buy\n"
            "2. Enter quantity\n"
            "3. Send payment via the bank details shown\n"
            "4. Send a screenshot of the payment as proof\n"
            "5. Wait for admin confirmation — you'll be notified here.\n\n"
            "Use /start to return to the main menu any time.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Back", callback_data="menu:back")]]
            ),
        )
    elif data == "menu:back":
        await query.edit_message_text(
            "Main menu:", reply_markup=main_menu_kb()
        )


async def show_categories(query):
    categories = db.list_categories()
    if not categories:
        await query.edit_message_text(
            "No products available yet — check back soon!",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Back", callback_data="menu:back")]]
            ),
        )
        return
    kb = [[InlineKeyboardButton(c, callback_data=f"cat:{c}")] for c in categories]
    kb.append([InlineKeyboardButton("⬅️ Back", callback_data="menu:back")])
    await query.edit_message_text("Choose a category:", reply_markup=InlineKeyboardMarkup(kb))


async def show_category_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.split(":", 1)[1]
    products = db.list_products(category=category)
    if not products:
        await query.edit_message_text("No products in this category right now.")
        return
    kb = []
    for p in products:
        label = f"{p['name']} — {p['price']:.2f} {config.CURRENCY}"
        kb.append([InlineKeyboardButton(label, callback_data=f"prod:{p['id']}")])
    kb.append([InlineKeyboardButton("⬅️ Back", callback_data="menu:shop")])
    await query.edit_message_text(f"📂 {category}", reply_markup=InlineKeyboardMarkup(kb))


async def show_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    product_id = int(query.data.split(":", 1)[1])
    p = db.get_product(product_id)
    if not p or not p["active"]:
        await query.edit_message_text("This product is no longer available.")
        return
    stock_line = "" if p["stock"] is None else f"\nStock: {p['stock']}"
    text = (
        f"🛒 {p['name']}\n"
        f"{p['description'] or ''}\n\n"
        f"Price: {p['price']:.2f} {config.CURRENCY}{stock_line}"
    )
    kb = [
        [InlineKeyboardButton("✅ Buy", callback_data=f"buy:{p['id']}")],
        [InlineKeyboardButton("⬅️ Back", callback_data=f"cat:{p['category']}")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))


async def show_my_orders(query):
    orders = db.list_orders_for_user(query.from_user.id)
    if not orders:
        await query.edit_message_text(
            "You have no orders yet.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Back", callback_data="menu:back")]]
            ),
        )
        return
    lines = ["📦 Your orders:\n"]
    status_label = {
        "awaiting_proof": "⏳ awaiting your payment proof",
        "awaiting_confirmation": "🔎 pending admin confirmation",
        "paid": "✅ paid & confirmed",
        "rejected": "❌ rejected",
    }
    for o in orders:
        lines.append(
            f"{o['reference']} — {o['product_name']} x{o['quantity']} "
            f"({o['total']:.2f} {config.CURRENCY}) — "
            f"{status_label.get(o['status'], o['status'])}"
        )
    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Back", callback_data="menu:back")]]
        ),
    )


# ----------------------------------------------------------------------
# Buy flow (ConversationHandler)
# ----------------------------------------------------------------------

async def buy_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    product_id = int(query.data.split(":", 1)[1])
    p = db.get_product(product_id)
    if not p or not p["active"]:
        await query.edit_message_text("This product is no longer available.")
        return ConversationHandler.END
    if p["stock"] is not None and p["stock"] <= 0:
        await query.edit_message_text("Sorry, this product is out of stock.")
        return ConversationHandler.END

    context.user_data["buy_product_id"] = product_id
    await query.edit_message_text(
        f"How many units of \"{p['name']}\" would you like? Reply with a number.\n"
        "Send /cancel to abort."
    )
    return BUY_QTY


async def buy_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit() or int(text) <= 0:
        await update.message.reply_text("Please send a positive whole number, or /cancel.")
        return BUY_QTY

    qty = int(text)
    p = db.get_product(context.user_data["buy_product_id"])
    if not p or not p["active"]:
        await update.message.reply_text("This product is no longer available.")
        return ConversationHandler.END
    if p["stock"] is not None and qty > p["stock"]:
        await update.message.reply_text(
            f"Only {p['stock']} left in stock. Enter a smaller quantity or /cancel."
        )
        return BUY_QTY

    user = update.effective_user
    order_id, ref = db.create_order(user.id, user.username or "", p, qty)
    context.user_data["buy_order_id"] = order_id

    total = p["price"] * qty
    await update.message.reply_text(
        f"Order created: {ref}\n"
        f"{p['name']} x{qty} = {total:.2f} {config.CURRENCY}\n\n"
        f"Please pay using:\n{config.BANK_DETAILS}\n\n"
        f"⚠️ Include the reference {ref} in your transfer if possible.\n\n"
        "Once paid, send a screenshot of the payment here as your proof.\n"
        "Send /cancel to abort this order.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return BUY_PROOF


async def buy_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text(
            "Please send the payment proof as a photo, or /cancel."
        )
        return BUY_PROOF

    order_id = context.user_data.get("buy_order_id")
    order = db.get_order(order_id)
    if not order:
        await update.message.reply_text("Something went wrong finding your order. /start to try again.")
        return ConversationHandler.END

    file_id = update.message.photo[-1].file_id
    db.attach_proof(order_id, file_id)

    await update.message.reply_text(
        f"Thanks! Your proof for order {order['reference']} was submitted. "
        "You'll be notified here once an admin confirms it."
    )

    # notify all admins
    caption = (
        f"🆕 Payment proof received\n"
        f"Order: {order['reference']}\n"
        f"Product: {order['product_name']} x{order['quantity']}\n"
        f"Total: {order['total']:.2f} {config.CURRENCY}\n"
        f"Customer: @{update.effective_user.username or update.effective_user.id}"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"adm_appr:{order_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"adm_rej:{order_id}"),
    ]])
    for admin_id in config.ADMIN_IDS:
        try:
            await context.bot.send_photo(
                admin_id, photo=file_id, caption=caption, reply_markup=kb
            )
        except Exception:
            logger.exception("Failed to notify admin %s", admin_id)

    context.user_data.clear()
    return ConversationHandler.END


async def buy_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    order_id = context.user_data.get("buy_order_id")
    if order_id:
        db.set_order_status(order_id, "rejected", admin_note="cancelled by customer")
    context.user_data.clear()
    await update.message.reply_text("Order cancelled. Use /start to browse again.")
    return ConversationHandler.END


# ----------------------------------------------------------------------
# Admin: approve / reject
# ----------------------------------------------------------------------

async def admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Admins only.", show_alert=True)
        return
    await query.answer()

    action, order_id = query.data.split(":")
    order_id = int(order_id)
    order = db.get_order(order_id)
    if not order:
        await query.edit_message_caption("Order not found (may have been removed).")
        return

    if action == "adm_appr":
        db.set_order_status(order_id, "paid")
        product = db.get_product(order["product_id"])
        if product and product["stock"] is not None:
            db.decrement_stock(order["product_id"], order["quantity"])

        delivery_note = ""
        if product and product["file_path"]:
            try:
                await context.bot.send_document(
                    order["user_id"], document=open(product["file_path"], "rb"),
                    caption=f"Here's your order {order['reference']} — thanks!"
                )
                delivery_note = " File delivered automatically."
            except Exception:
                logger.exception("Failed to deliver file for order %s", order_id)
                delivery_note = " (File delivery failed — send it manually.)"
        else:
            try:
                await context.bot.send_message(
                    order["user_id"],
                    f"✅ Payment confirmed for order {order['reference']}. "
                    "Your item will be delivered to you here shortly."
                )
            except Exception:
                logger.exception("Failed to notify customer for order %s", order_id)

        await query.edit_message_caption(
            (query.message.caption or "") + f"\n\n✅ APPROVED by admin.{delivery_note}"
        )

    elif action == "adm_rej":
        db.set_order_status(order_id, "rejected", admin_note="rejected by admin")
        try:
            await context.bot.send_message(
                order["user_id"],
                f"❌ Your payment proof for order {order['reference']} could not be "
                "verified. Please contact support or try again."
            )
        except Exception:
            logger.exception("Failed to notify customer for order %s", order_id)
        await query.edit_message_caption(
            (query.message.caption or "") + "\n\n❌ REJECTED by admin."
        )


# ----------------------------------------------------------------------
# Admin: add product (ConversationHandler)
# ----------------------------------------------------------------------

async def addproduct_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Admins only.")
        return ConversationHandler.END
    context.user_data["new_product"] = {}
    await update.message.reply_text(
        "Let's add a product. Send /cancel at any time to abort.\n\n"
        "1) Category name (e.g. 'Telegram Premium'):"
    )
    return ADD_CATEGORY


async def addproduct_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_product"]["category"] = update.message.text.strip()
    await update.message.reply_text("2) Product name:")
    return ADD_NAME


async def addproduct_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_product"]["name"] = update.message.text.strip()
    await update.message.reply_text("3) Short description:")
    return ADD_DESC


async def addproduct_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_product"]["description"] = update.message.text.strip()
    await update.message.reply_text(f"4) Price in {config.CURRENCY} (e.g. 4.99):")
    return ADD_PRICE


async def addproduct_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Please send a number, e.g. 4.99")
        return ADD_PRICE
    context.user_data["new_product"]["price"] = price
    await update.message.reply_text(
        "5) Stock quantity (send a number), or send 'unlimited':"
    )
    return ADD_STOCK


async def addproduct_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    stock = None if text == "unlimited" else None
    if text != "unlimited":
        if not text.isdigit():
            await update.message.reply_text("Send a whole number, or 'unlimited'.")
            return ADD_STOCK
        stock = int(text)
    context.user_data["new_product"]["stock"] = stock
    await update.message.reply_text(
        "6) If this product auto-delivers a file, upload it now. "
        "Otherwise send /skip (you'll deliver it manually after approving orders)."
    )
    return ADD_FILE


async def addproduct_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    np = context.user_data["new_product"]
    file_path = None
    if update.message.document:
        file = await update.message.document.get_file()
        file_path = f"files/{update.message.document.file_unique_id}_{update.message.document.file_name}"
        import os
        os.makedirs("files", exist_ok=True)
        await file.download_to_drive(file_path)

    product_id = db.add_product(
        np["category"], np["name"], np["description"], np["price"],
        np["stock"], file_path,
    )
    await update.message.reply_text(
        f"✅ Product #{product_id} '{np['name']}' added to category '{np['category']}'."
    )
    context.user_data.clear()
    return ConversationHandler.END


async def addproduct_skip_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    np = context.user_data["new_product"]
    product_id = db.add_product(
        np["category"], np["name"], np["description"], np["price"],
        np["stock"], None,
    )
    await update.message.reply_text(
        f"✅ Product #{product_id} '{np['name']}' added to category '{np['category']}'."
    )
    context.user_data.clear()
    return ConversationHandler.END


async def editproduct_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Admins only.")
        return ConversationHandler.END
    products = db.list_products(active_only=False)
    if not products:
        await update.message.reply_text("No products yet. Use /addproduct first.")
        return ConversationHandler.END
    kb = [
        [InlineKeyboardButton(f"#{p['id']} {p['name']}", callback_data=f"edit_pick:{p['id']}")]
        for p in products
    ]
    await update.message.reply_text("Which product do you want to edit?", reply_markup=InlineKeyboardMarkup(kb))
    return EDIT_FIELD


async def editproduct_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    product_id = int(query.data.split(":", 1)[1])
    p = db.get_product(product_id)
    if not p:
        await query.edit_message_text("Product not found.")
        return ConversationHandler.END
    context.user_data["edit_product_id"] = product_id
    stock = "unlimited" if p["stock"] is None else p["stock"]
    kb = [
        [InlineKeyboardButton(f"Name ({p['name']})", callback_data="edit_field:name")],
        [InlineKeyboardButton(f"Description", callback_data="edit_field:description")],
        [InlineKeyboardButton(f"Price ({p['price']:.2f})", callback_data="edit_field:price")],
        [InlineKeyboardButton(f"Stock ({stock})", callback_data="edit_field:stock")],
        [InlineKeyboardButton(
            "Deactivate" if p["active"] else "Activate", callback_data="edit_field:toggle_active"
        )],
    ]
    await query.edit_message_text(
        f"Editing #{p['id']} {p['name']}. What do you want to change?",
        reply_markup=InlineKeyboardMarkup(kb),
    )
    return EDIT_FIELD


async def editproduct_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    field = query.data.split(":", 1)[1]
    product_id = context.user_data["edit_product_id"]

    if field == "toggle_active":
        p = db.get_product(product_id)
        db.set_product_active(product_id, not p["active"])
        await query.edit_message_text(
            f"Product #{product_id} is now {'active' if not p['active'] else 'inactive'}."
        )
        context.user_data.clear()
        return ConversationHandler.END

    context.user_data["edit_field"] = field
    prompts = {
        "name": "Send the new name:",
        "description": "Send the new description:",
        "price": f"Send the new price in {config.CURRENCY} (e.g. 4.99):",
        "stock": "Send the new stock quantity (a number), or 'unlimited':",
    }
    await query.edit_message_text(prompts[field] + "\nSend /cancel to abort.")
    return EDIT_VALUE


async def editproduct_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    field = context.user_data["edit_field"]
    product_id = context.user_data["edit_product_id"]
    text = update.message.text.strip()

    if field == "price":
        try:
            value = float(text)
        except ValueError:
            await update.message.reply_text("Please send a number, e.g. 4.99")
            return EDIT_VALUE
    elif field == "stock":
        if text.lower() == "unlimited":
            value = None
        elif text.isdigit():
            value = int(text)
        else:
            await update.message.reply_text("Send a whole number, or 'unlimited'.")
            return EDIT_VALUE
    else:
        value = text

    db.update_product_field(product_id, field, value)
    await update.message.reply_text(f"✅ Updated. Product #{product_id} {field} = {value}")
    context.user_data.clear()
    return ConversationHandler.END


async def generic_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


# ----------------------------------------------------------------------
# Admin: read-only commands
# ----------------------------------------------------------------------

async def admin_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    products = db.list_products(active_only=False)
    if not products:
        await update.message.reply_text("No products yet. Use /addproduct.")
        return
    lines = []
    for p in products:
        flag = "🟢" if p["active"] else "🔴"
        stock = "∞" if p["stock"] is None else p["stock"]
        lines.append(
            f"{flag} #{p['id']} [{p['category']}] {p['name']} — "
            f"{p['price']:.2f} {config.CURRENCY} (stock: {stock})"
        )
    await update.message.reply_text("\n".join(lines))


async def admin_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    orders = db.list_pending_orders()
    if not orders:
        await update.message.reply_text("No orders awaiting confirmation.")
        return
    lines = [
        f"{o['reference']} — {o['product_name']} x{o['quantity']} "
        f"({o['total']:.2f} {config.CURRENCY}) — @{o['username'] or o['user_id']}"
        for o in orders
    ]
    await update.message.reply_text("Pending confirmation:\n" + "\n".join(lines))


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    s = db.stats()
    await update.message.reply_text(
        f"👥 Users: {s['users']}\n"
        f"🧾 Total orders: {s['total_orders']}\n"
        f"⏳ Pending confirmation: {s['pending_orders']}\n"
        f"✅ Paid orders: {s['paid_orders']}\n"
        f"💰 Revenue (confirmed): {s['revenue']:.2f} {config.CURRENCY}"
    )


# ----------------------------------------------------------------------
# Wiring
# ----------------------------------------------------------------------

def main():
    db.init_db()
    app = Application.builder().token(config.BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("products", admin_products))
    app.add_handler(CommandHandler("orders", admin_orders))
    app.add_handler(CommandHandler("stats", admin_stats))

    app.add_handler(CallbackQueryHandler(menu_router, pattern=r"^menu:"))
    app.add_handler(CallbackQueryHandler(show_category_products, pattern=r"^cat:"))
    app.add_handler(CallbackQueryHandler(show_product, pattern=r"^prod:"))
    app.add_handler(CallbackQueryHandler(admin_decision, pattern=r"^adm_(appr|rej):"))

    buy_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(buy_start, pattern=r"^buy:")],
        states={
            BUY_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, buy_qty)],
            BUY_PROOF: [MessageHandler(filters.PHOTO, buy_proof)],
        },
        fallbacks=[CommandHandler("cancel", buy_cancel)],
        name="buy_conversation",
    )
    app.add_handler(buy_conv)

    addproduct_conv = ConversationHandler(
        entry_points=[CommandHandler("addproduct", addproduct_start)],
        states={
            ADD_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, addproduct_category)],
            ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, addproduct_name)],
            ADD_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, addproduct_desc)],
            ADD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, addproduct_price)],
            ADD_STOCK: [MessageHandler(filters.TEXT & ~filters.COMMAND, addproduct_stock)],
            ADD_FILE: [
                MessageHandler(filters.Document.ALL, addproduct_file),
                CommandHandler("skip", addproduct_skip_file),
            ],
        },
        fallbacks=[CommandHandler("cancel", generic_cancel)],
        name="addproduct_conversation",
    )
    app.add_handler(addproduct_conv)

    editproduct_conv = ConversationHandler(
        entry_points=[CommandHandler("editproduct", editproduct_start)],
        states={
            EDIT_FIELD: [
                CallbackQueryHandler(editproduct_pick, pattern=r"^edit_pick:"),
                CallbackQueryHandler(editproduct_field, pattern=r"^edit_field:"),
            ],
            EDIT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, editproduct_value)],
        },
        fallbacks=[CommandHandler("cancel", generic_cancel)],
        name="editproduct_conversation",
    )
    app.add_handler(editproduct_conv)

    logger.info("Bot starting (polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
