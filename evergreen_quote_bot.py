"""
Evergreen Home Cleaning — Quote Generator Bot
Generates ready-to-copy client messages with v3 pricing.

Requirements:
    pip install python-telegram-bot==20.7

Usage:
    1. Create a new bot via @BotFather → get TOKEN
    2. Set TOKEN below (or use environment variable)
    3. Run: python evergreen_quote_bot.py
"""

import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler
)

# ── CONFIG ──────────────────────────────────────────────────────────
TOKEN = os.environ.get("BOT_TOKEN", "8694900674:AAHScHpiW7f8L2Tr7RHpAJbDNmj5Rh5uDuo")

# ── CONVERSATION STATES ─────────────────────────────────────────────
SERVICE, BEDS, BATHS, ADDONS, RECURRING, LEAD_TYPE = range(6)

# ── V3 PRICING TABLES ───────────────────────────────────────────────
# Format: PRICES[service][(beds, baths)] = price
STANDARD = {
    (1,1):115,(1,2):135,
    (2,1):140,(2,2):160,(2,3):180,
    (3,1):170,(3,2):190,(3,3):210,(3,4):230,
    (4,1):220,(4,2):220,(4,3):240,(4,4):260,(4,5):280,
    (5,1):250,(5,2):250,(5,3):270,(5,4):290,(5,5):310,
    (6,1):290,(6,2):290,(6,3):290,(6,4):310,(6,5):330,
}

DEEP = {
    (1,1):165,(1,2):185,
    (2,1):185,(2,2):205,(2,3):230,
    (3,1):220,(3,2):245,(3,3):270,(3,4):295,
    (4,1):275,(4,2):275,(4,3):300,(4,4):325,(4,5):350,
    (5,1):305,(5,2):305,(5,3):330,(5,4):355,(5,5):380,
    (6,1):345,(6,2):345,(6,3):345,(6,4):370,(6,5):395,
}

MOVEOUT = {
    (1,1):199,(1,2):219,
    (2,1):219,(2,2):239,(2,3):259,
    (3,1):249,(3,2):269,(3,3):289,(3,4):309,
    (4,1):289,(4,2):289,(4,3):309,(4,4):329,(4,5):349,
    (5,1):329,(5,2):329,(5,3):349,(5,4):369,(5,5):389,
    (6,1):369,(6,2):369,(6,3):369,(6,4):389,(6,5):409,
}

AIRBNB = {
    (1,1):99,(1,2):115,
    (2,1):120,(2,2):135,(2,3):155,
    (3,1):145,(3,2):160,(3,3):175,(3,4):190,
    (4,1):185,(4,2):185,(4,3):200,(4,4):215,(4,5):230,
    (5,1):210,(5,2):210,(5,3):225,(5,4):240,(5,5):255,
    (6,1):240,(6,2):240,(6,3):240,(6,4):255,(6,5):270,
}

PRICES = {
    "standard": STANDARD,
    "deep": DEEP,
    "moveout": MOVEOUT,
    "airbnb": AIRBNB,
}

# ── ADD-ONS ──────────────────────────────────────────────────────────
ADDONS_LIST = [
    ("oven", "Oven Cleaning", 35),
    ("fridge", "Fridge Cleaning", 35),
    ("laundry", "Laundry (wash+fold)", 45),
    ("pet", "Pet Home", 15),
    ("basement", "Basement", 60),
    ("baseboards", "Baseboards", 25),
    ("cabinets", "Interior Cabinets", 45),
    ("win_1_5", "Windows 1–5", 15),
    ("win_6_10", "Windows 6–10", 30),
    ("win_11_15", "Windows 11–15", 45),
    ("win_16_20", "Windows 16–20", 60),
    ("win_21", "Windows 21+", 75),
]

# ── RECURRING DISCOUNTS (Standard only) ──────────────────────────────
RECURRING_DISCOUNTS = {
    "weekly": 0.15,
    "biweekly": 0.10,
    "monthly": 0.05,
    "onetime": 0.00,
}

# ── DISPLAY NAMES ────────────────────────────────────────────────────
SERVICE_NAMES = {
    "standard": "Standard Cleaning",
    "deep": "Deep Cleaning",
    "moveout": "Move-Out Cleaning",
    "airbnb": "Airbnb Turnover",
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

def get_base_price(service: str, beds: int, baths: int) -> int | None:
    table = PRICES.get(service)
    if not table:
        return None
    return table.get((beds, baths))


def get_available_addons(service: str) -> list:
    """Return add-ons available for this service (exclude included ones)."""
    excluded = set()
    if service == "deep":
        excluded.add("baseboards")  # included in deep
    elif service == "moveout":
        excluded.add("baseboards")  # included in move-out
        excluded.add("cabinets")    # included in move-out
    # Window add-ons: only show one group at a time — show all, user picks
    return [a for a in ADDONS_LIST if a[0] not in excluded]


def calc_total(base: int, selected_addons: list, service: str, recurring: str = "onetime") -> tuple:
    """Calculate total price. Returns (total, addon_total, discount_amount, discount_pct)."""
    addon_total = sum(price for key, name, price in ADDONS_LIST if key in selected_addons)
    subtotal = base + addon_total
    discount_pct = RECURRING_DISCOUNTS.get(recurring, 0)
    discount_amount = 0
    if service == "standard" and discount_pct > 0:
        discount_amount = round(subtotal * discount_pct)
        subtotal -= discount_amount
    return subtotal, addon_total, discount_amount, discount_pct


def size_label(beds: int, baths: int) -> str:
    return f"{beds}bd/{baths}ba"


# ═══════════════════════════════════════════════════════════════════
# MESSAGE TEMPLATES
# ═══════════════════════════════════════════════════════════════════

def build_standard_message(beds, baths, total, selected_addons, recurring):
    """Short template: price + 1 line."""
    size = size_label(beds, baths)
    addon_text = ""
    if selected_addons:
        names = [n for k, n, p in ADDONS_LIST if k in selected_addons]
        addon_text = f" (add-ons: {', '.join(names)})"

    recurring_text = ""
    if recurring == "weekly":
        recurring_text = "\n\n📅 Weekly schedule — 15% discount applied."
    elif recurring == "biweekly":
        recurring_text = "\n\n📅 Bi-weekly schedule — 10% discount applied."
    elif recurring == "monthly":
        recurring_text = "\n\n📅 Monthly schedule — 5% discount applied."

    msg = (
        f"Hi! A standard cleaning for a {size} is ${total}{addon_text}. "
        f"I'm the owner and personally handle every cleaning — "
        f"fully licensed and insured."
        f"{recurring_text}\n\n"
        f"What date works for you?\n\n"
        f"— Oleh"
    )
    return msg


def build_deep_message(beds, baths, total, selected_addons):
    """Detailed Deep Clean template with checklist."""
    size = size_label(beds, baths)
    addon_lines = ""
    if selected_addons:
        names = [f"  • {n} (+${p})" for k, n, p in ADDONS_LIST if k in selected_addons]
        addon_lines = "\n\nAdd-ons included:\n" + "\n".join(names)

    msg = (
        f"Hi! A deep cleaning for a {size} is ${total} "
        f"(price may vary slightly depending on condition).\n\n"
        f"I'm the owner of Evergreen Home Cleaning and personally handle "
        f"every appointment — no crews, just me. Fully licensed and insured.\n\n"
        f"Here's what's included:\n"
        f"✅ All rooms — dusting, vacuuming, mopping\n"
        f"✅ Kitchen — counters, sink, stovetop, backsplash, exterior appliances\n"
        f"✅ Bathrooms — scrub shower/tub, toilet, mirrors, floors\n"
        f"✅ Baseboards throughout (included)\n"
        f"✅ Cobweb removal, light switches, door handles"
        f"{addon_lines}\n\n"
        f"No rush — everything gets done right.\n\n"
        f"What date works for you?\n\n"
        f"— Oleh"
    )
    return msg


def build_moveout_message(beds, baths, total, selected_addons):
    """Detailed Move-Out template with checklist."""
    size = size_label(beds, baths)
    addon_lines = ""
    if selected_addons:
        names = [f"  • {n} (+${p})" for k, n, p in ADDONS_LIST if k in selected_addons]
        addon_lines = "\n\nAdd-ons included:\n" + "\n".join(names)

    msg = (
        f"Hi! A move-out cleaning for a {size} is ${total}.\n\n"
        f"I'm the owner of Evergreen Home Cleaning and handle every job "
        f"personally — fully licensed and insured.\n\n"
        f"Here's what's included:\n"
        f"✅ All rooms — dust, vacuum, mop\n"
        f"✅ Kitchen — counters, sink, stovetop, backsplash, exterior appliances\n"
        f"✅ Bathrooms — scrub shower/tub, toilet, mirrors, floors\n"
        f"✅ Baseboards throughout (included)\n"
        f"✅ Interior cabinets (included)\n"
        f"✅ Cobweb removal, light switches, door handles"
        f"{addon_lines}\n\n"
        f"When's your move-out date?\n\n"
        f"— Oleh"
    )
    return msg


def build_airbnb_message(beds, baths, total, selected_addons):
    """Short Airbnb template."""
    size = size_label(beds, baths)
    addon_text = ""
    if selected_addons:
        names = [n for k, n, p in ADDONS_LIST if k in selected_addons]
        addon_text = f" (add-ons: {', '.join(names)})"

    msg = (
        f"Hi! Airbnb turnover cleaning for a {size} is ${total}{addon_text}. "
        f"I handle every cleaning personally — fully insured.\n\n"
        f"What date works for you?\n\n"
        f"— Oleh"
    )
    return msg


def build_final_message(service, beds, baths, total, selected_addons, recurring="onetime"):
    """Route to the correct template."""
    if service == "standard":
        return build_standard_message(beds, baths, total, selected_addons, recurring)
    elif service == "deep":
        return build_deep_message(beds, baths, total, selected_addons)
    elif service == "moveout":
        return build_moveout_message(beds, baths, total, selected_addons)
    elif service == "airbnb":
        return build_airbnb_message(beds, baths, total, selected_addons)


# ═══════════════════════════════════════════════════════════════════
# BOT HANDLERS
# ═══════════════════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point — choose service type."""
    context.user_data.clear()
    keyboard = [
        [InlineKeyboardButton("🧹 Standard", callback_data="svc_standard"),
         InlineKeyboardButton("🧽 Deep Clean", callback_data="svc_deep")],
        [InlineKeyboardButton("📦 Move-Out", callback_data="svc_moveout"),
         InlineKeyboardButton("🏠 Airbnb", callback_data="svc_airbnb")],
    ]
    text = "👋 *Evergreen Quote Generator*\n\nВибери тип прибирання:"
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
    return SERVICE


async def service_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Service chosen → pick bedrooms."""
    query = update.callback_query
    await query.answer()
    service = query.data.replace("svc_", "")
    context.user_data["service"] = service
    context.user_data["selected_addons"] = []

    keyboard = [
        [InlineKeyboardButton(f"{i} bed", callback_data=f"bed_{i}") for i in range(1, 4)],
        [InlineKeyboardButton(f"{i} bed", callback_data=f"bed_{i}") for i in range(4, 7)],
    ]
    await query.edit_message_text(
        f"*{SERVICE_NAMES[service]}*\n\nСкільки спалень (bedrooms)?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return BEDS


async def beds_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Bedrooms chosen → pick bathrooms."""
    query = update.callback_query
    await query.answer()
    beds = int(query.data.replace("bed_", ""))
    context.user_data["beds"] = beds

    # Determine max baths for this bed count
    service = context.user_data["service"]
    table = PRICES[service]
    max_baths = max(b for (bd, b) in table.keys() if bd == beds)

    buttons = [InlineKeyboardButton(f"{i} bath", callback_data=f"bath_{i}")
               for i in range(1, max_baths + 1)]
    # Arrange in rows of 3
    keyboard = [buttons[i:i+3] for i in range(0, len(buttons), 3)]

    await query.edit_message_text(
        f"*{beds} bed* — скільки ванних (bathrooms)?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return BATHS


async def baths_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Bathrooms chosen → show base price, offer add-ons."""
    query = update.callback_query
    await query.answer()
    baths = int(query.data.replace("bath_", ""))
    context.user_data["baths"] = baths

    service = context.user_data["service"]
    beds = context.user_data["beds"]
    base = get_base_price(service, beds, baths)

    if base is None:
        await query.edit_message_text("❌ Ця комбінація не знайдена. Спробуй /quote")
        return ConversationHandler.END

    context.user_data["base_price"] = base

    # Build add-on keyboard
    available = get_available_addons(service)
    selected = context.user_data["selected_addons"]

    return await show_addons_menu(query, context, base, available, selected)


async def show_addons_menu(query, context, base, available, selected):
    """Display add-ons selection with toggle buttons."""
    service = context.user_data["service"]
    beds = context.user_data["beds"]
    baths = context.user_data["baths"]

    total, addon_total, _, _ = calc_total(base, selected, service)

    lines = [
        f"*{SERVICE_NAMES[service]}* — {size_label(beds, baths)}",
        f"💰 Базова ціна: ${base}",
    ]
    if addon_total > 0:
        lines.append(f"➕ Add-ons: +${addon_total}")
        lines.append(f"📊 Всього: ${total}")

    lines.append("\nВибери add-ons (натисни ще раз щоб зняти):")

    keyboard = []
    for key, name, price in available:
        check = "✅ " if key in selected else ""
        keyboard.append([InlineKeyboardButton(
            f"{check}{name} (+${price})", callback_data=f"addon_{key}"
        )])

    # Done button
    keyboard.append([InlineKeyboardButton("✅ Готово — згенерувати", callback_data="addons_done")])

    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return ADDONS


async def addon_toggled(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Toggle an add-on on/off."""
    query = update.callback_query
    await query.answer()
    key = query.data.replace("addon_", "")

    selected = context.user_data["selected_addons"]
    if key in selected:
        selected.remove(key)
    else:
        selected.append(key)

    service = context.user_data["service"]
    base = context.user_data["base_price"]
    available = get_available_addons(service)

    return await show_addons_menu(query, context, base, available, selected)


async def addons_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Add-ons finalized. If Standard → ask recurring. Otherwise → generate."""
    query = update.callback_query
    await query.answer()

    service = context.user_data["service"]

    if service == "standard":
        keyboard = [
            [InlineKeyboardButton("📅 Weekly (−15%)", callback_data="rec_weekly"),
             InlineKeyboardButton("📅 Bi-weekly (−10%)", callback_data="rec_biweekly")],
            [InlineKeyboardButton("📅 Monthly (−5%)", callback_data="rec_monthly"),
             InlineKeyboardButton("One-time", callback_data="rec_onetime")],
        ]
        await query.edit_message_text(
            "Recurring чи разове прибирання?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return RECURRING
    else:
        context.user_data["recurring"] = "onetime"
        return await generate_quote(query, context)


async def recurring_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Recurring type chosen → generate quote."""
    query = update.callback_query
    await query.answer()
    recurring = query.data.replace("rec_", "")
    context.user_data["recurring"] = recurring
    return await generate_quote(query, context)


async def generate_quote(query, context) -> int:
    """Build and send the final client message."""
    service = context.user_data["service"]
    beds = context.user_data["beds"]
    baths = context.user_data["baths"]
    base = context.user_data["base_price"]
    selected = context.user_data["selected_addons"]
    recurring = context.user_data.get("recurring", "onetime")

    total, addon_total, discount_amount, discount_pct = calc_total(
        base, selected, service, recurring
    )

    # Summary for you
    summary_lines = [
        f"📋 *КОТИРУВКА*",
        f"Тип: {SERVICE_NAMES[service]}",
        f"Розмір: {size_label(beds, baths)}",
        f"Базова ціна: ${base}",
    ]
    if addon_total > 0:
        addon_names = [f"{n} (${p})" for k, n, p in ADDONS_LIST if k in selected]
        summary_lines.append(f"Add-ons: {', '.join(addon_names)} = +${addon_total}")
    if discount_amount > 0:
        summary_lines.append(f"Знижка: −{int(discount_pct*100)}% = −${discount_amount}")
    summary_lines.append(f"💰 *ВСЬОГО: ${total}*")
    summary_lines.append("\n─────────────────────")
    summary_lines.append("📝 *Повідомлення для клієнта:*\n")

    # Client message
    client_msg = build_final_message(service, beds, baths, total, selected, recurring)

    full_text = "\n".join(summary_lines) + client_msg

    # "New quote" button
    keyboard = [[InlineKeyboardButton("🔄 Нова котирувка", callback_data="restart")]]

    await query.edit_message_text(
        full_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return ConversationHandler.END


async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Restart the flow."""
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    return await start(update, context)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the conversation."""
    await update.message.reply_text("Скасовано. Натисни /quote щоб почати знову.")
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════════
# QUICK QUOTE COMMAND: /q <service> <beds> <baths>
# ═══════════════════════════════════════════════════════════════════

async def quick_quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Fast quote without buttons.
    Usage: /q standard 3 2
           /q deep 2 1
           /q moveout 4 3
           /q airbnb 2 2
    """
    args = context.args
    if not args or len(args) < 3:
        await update.message.reply_text(
            "Використання: /q <тип> <beds> <baths>\n"
            "Приклад: `/q standard 3 2`\n"
            "Типи: standard, deep, moveout, airbnb",
            parse_mode="Markdown"
        )
        return

    service = args[0].lower()
    if service not in PRICES:
        await update.message.reply_text("❌ Невідомий тип. Використай: standard, deep, moveout, airbnb")
        return

    try:
        beds = int(args[1])
        baths = int(args[2])
    except ValueError:
        await update.message.reply_text("❌ beds і baths мають бути числами.")
        return

    base = get_base_price(service, beds, baths)
    if base is None:
        await update.message.reply_text(f"❌ Комбінація {beds}bd/{baths}ba не знайдена для {service}.")
        return

    total = base  # no add-ons in quick mode
    client_msg = build_final_message(service, beds, baths, total, [], "onetime")

    text = (
        f"📋 *{SERVICE_NAMES[service]}* — {size_label(beds, baths)} — ${total}\n"
        f"─────────────────────\n\n"
        f"{client_msg}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ═══════════════════════════════════════════════════════════════════
# PRICE LIST COMMAND: /prices
# ═══════════════════════════════════════════════════════════════════

async def show_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show full price list."""
    lines = ["📊 *EVERGREEN V3 PRICING*\n"]

    for svc_key, svc_name in SERVICE_NAMES.items():
        lines.append(f"\n*{svc_name}*")
        table = PRICES[svc_key]
        for (beds, baths), price in sorted(table.items()):
            lines.append(f"  {beds}bd/{baths}ba — ${price}")

    lines.append(f"\n*Add-ons:*")
    for key, name, price in ADDONS_LIST:
        lines.append(f"  {name} — ${price}")

    lines.append(f"\n*Recurring (Standard only):*")
    lines.append(f"  Weekly — 15% off")
    lines.append(f"  Bi-weekly — 10% off")
    lines.append(f"  Monthly — 5% off")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    app = Application.builder().token(TOKEN).build()

    # Conversation handler for interactive flow
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("quote", start),
        ],
        states={
            SERVICE: [CallbackQueryHandler(service_selected, pattern=r"^svc_")],
            BEDS: [CallbackQueryHandler(beds_selected, pattern=r"^bed_")],
            BATHS: [CallbackQueryHandler(baths_selected, pattern=r"^bath_")],
            ADDONS: [
                CallbackQueryHandler(addon_toggled, pattern=r"^addon_"),
                CallbackQueryHandler(addons_done, pattern=r"^addons_done$"),
            ],
            RECURRING: [CallbackQueryHandler(recurring_selected, pattern=r"^rec_")],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(restart, pattern=r"^restart$"),
        ],
    )

    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(restart, pattern=r"^restart$"))
    app.add_handler(CommandHandler("q", quick_quote))
    app.add_handler(CommandHandler("prices", show_prices))

    print("🟢 Evergreen Quote Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
