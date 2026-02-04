import asyncio
import logging
import threading
import os
import math
import re
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import (
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton,
    BufferedInputFile
)
from aiogram.filters import Command

# Import core modules
import config
import utils
from core.browser import browser_thread_target
# --- FIX: Added credential_watchdog to imports ---
from core.websocket import websocket_loop, credential_watchdog 
from core import api
from core.scanner import TerminationScanner
import core.database as db

# Logging Setup
logging.basicConfig(level=logging.INFO)
bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# ===================== SETTINGS =====================
PAGE_SIZE = 20

# ===================== DATA HELPERS =====================

def get_service_from_name(name):
    match = re.match(r"([a-zA-Z\s]+)", name)
    if match:
        return match.group(1).strip()
    return "Other"

async def build_tree_data():
    countries = {}
    categories = {}
    
    if not utils.numbers_data:
        return {}, {}

    for rng, items in utils.numbers_data.items():
        if not items: continue
        
        first_num = items[0].get('number', '')
        c_name, flag = utils.CountryManager.get_country_info(first_num)
        c_key = f"{flag} {c_name}"
        
        if c_key not in countries: countries[c_key] = []
        countries[c_key].append(rng)
        
        svc = get_service_from_name(rng)
        if svc not in categories: categories[svc] = []
        categories[svc].append(rng)
        
    return countries, categories

# ===================== KEYBOARDS =====================

def get_main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📤 Export Numbers"), KeyboardButton(text="🔎 Choose Range")],
            [KeyboardButton(text="➕ Add Range"), KeyboardButton(text="🗑 Remove Range")],
            [KeyboardButton(text="📊 Status"), KeyboardButton(text="📜 History")]
        ],
        resize_keyboard=True,
        persistent=True
    )

def get_cancel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_action")]
    ])

def get_tree_root_kb(mode):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🌍 By Country", callback_data=f"tree:{mode}:ctry_list"),
            InlineKeyboardButton(text="📱 By Category", callback_data=f"tree:{mode}:cat_list")
        ],
        [
            InlineKeyboardButton(text="📁 By Range Name", callback_data=f"tree:{mode}:rng_list"),
            InlineKeyboardButton(text="🌐 All Numbers", callback_data=f"tree:{mode}:all")
        ],
        [InlineKeyboardButton(text="❌ Close", callback_data="cancel_action")]
    ])

def get_pagination_kb(prefix: str, current_page: int, total_pages: int):
    buttons = []
    if current_page > 1:
        buttons.append(InlineKeyboardButton(text="⬅️", callback_data=f"{prefix}:{current_page-1}"))
    buttons.append(InlineKeyboardButton(text=f"{current_page}/{total_pages}", callback_data="noop"))
    if current_page < total_pages:
        buttons.append(InlineKeyboardButton(text="➡️", callback_data=f"{prefix}:{current_page+1}"))
    return buttons

# ===================== COMMAND HANDLERS =====================

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 <b>Welcome to IVASMS Bot!</b>\n"
        "Manage your numbers with the menu below.",
        reply_markup=get_main_menu(),
        parse_mode="HTML"
    )

@dp.message(Command("menu"))
async def cmd_menu(message: types.Message):
    await message.answer("📂 <b>Main Menu</b>", reply_markup=get_main_menu(), parse_mode="HTML")

# ===================== TREE NAVIGATION =====================

@dp.message(F.text == "📤 Export Numbers")
async def handle_export_root(message: types.Message):
    await launch_tree_mode(message, "exp", "📤 <b>Export Menu</b>")

@dp.message(F.text == "🔎 Choose Range")
async def handle_view_root(message: types.Message):
    await launch_tree_mode(message, "view", "🔎 <b>Choose Range</b>")

@dp.message(F.text == "🗑 Remove Range")
async def handle_remove_root(message: types.Message):
    await launch_tree_mode(message, "rm", "🗑 <b>Remove Menu</b>")

async def launch_tree_mode(message: types.Message, mode: str, title: str):
    status_msg = await message.answer("🔄 Refreshing data...")
    await api.fetch_numbers()
    
    if not utils.numbers_data:
        await status_msg.edit_text("⚠️ No numbers found.")
        return
        
    await status_msg.edit_text(
        f"{title}\nSelect grouping method:", 
        reply_markup=get_tree_root_kb(mode), 
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("tree:"))
async def tree_navigation(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    mode = parts[1]   
    action = parts[2] 
    value = parts[3] if len(parts) > 3 else None

    if action == "ctry_list":
        countries, _ = await build_tree_data()
        if not countries:
            await callback.answer("No data found.", show_alert=True)
            return
        
        kb = []
        for ctry_key in sorted(countries.keys()):
            ranges = countries[ctry_key]
            count = sum(len(utils.numbers_data[r]) for r in ranges)
            kb.append([InlineKeyboardButton(text=f"{ctry_key} ({count})", callback_data=f"tree:{mode}:sel_ctry:{ctry_key}")])
        
        kb.append([InlineKeyboardButton(text="🔙 Back", callback_data=f"tree_back:{mode}")])
        await callback.message.edit_text(f"🌍 <b>Select Country ({mode.upper()})</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

    elif action == "cat_list":
        _, categories = await build_tree_data()
        if not categories:
            await callback.answer("No data found.", show_alert=True)
            return

        kb = []
        for cat_name in sorted(categories.keys()):
            ranges = categories[cat_name]
            count = sum(len(utils.numbers_data[r]) for r in ranges)
            kb.append([InlineKeyboardButton(text=f"📱 {cat_name} ({count})", callback_data=f"tree:{mode}:sel_cat:{cat_name}")])
        
        kb.append([InlineKeyboardButton(text="🔙 Back", callback_data=f"tree_back:{mode}")])
        await callback.message.edit_text(f"📱 <b>Select Category ({mode.upper()})</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

    elif action == "rng_list":
        ranges = sorted(utils.numbers_data.keys())
        kb = []
        for r in ranges[:50]:
            count = len(utils.numbers_data[r])
            if mode == "exp": cb = f"do_exp:range:{r}"
            elif mode == "rm": cb = f"ask_rm:range:{r}"
            else: cb = f"view_rng:{r}:1"
            kb.append([InlineKeyboardButton(text=f"📁 {r} ({count})", callback_data=cb)])
        
        kb.append([InlineKeyboardButton(text="🔙 Back", callback_data=f"tree_back:{mode}")])
        await callback.message.edit_text(f"📁 <b>Select Range ({mode.upper()})</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

    elif action == "sel_ctry":
        countries, _ = await build_tree_data()
        target_ranges = countries.get(value, [])
        if mode == "exp":
            await execute_export(callback, "Country", value, target_ranges)
        elif mode == "rm":
            await ask_bulk_remove(callback, "Country", value, target_ranges)
        else:
            await show_ranges_sublist(callback, f"🌍 {value}", target_ranges, mode, "ctry_list")

    elif action == "sel_cat":
        _, categories = await build_tree_data()
        target_ranges = categories.get(value, [])
        if mode == "exp":
            await execute_export(callback, "Category", value, target_ranges)
        elif mode == "rm":
            await ask_bulk_remove(callback, "Category", value, target_ranges)
        else:
            await show_ranges_sublist(callback, f"📱 {value}", target_ranges, mode, "cat_list")

    elif action == "all":
        all_ranges = list(utils.numbers_data.keys())
        if mode == "exp":
            await execute_export(callback, "All", "Everything", all_ranges)
        elif mode == "rm":
            await ask_bulk_remove(callback, "Global", "ALL NUMBERS", all_ranges)
        else:
            await tree_navigation(callback, types.CallbackQuery(id=callback.id, data=f"tree:{mode}:rng_list", message=callback.message, from_user=callback.from_user))

@dp.callback_query(F.data.startswith("tree_back:"))
async def tree_back(callback: types.CallbackQuery):
    mode = callback.data.split(":")[1]
    title_map = {"exp": "📤 Export Menu", "view": "🔎 Choose Range", "rm": "🗑 Remove Menu"}
    await callback.message.edit_text(
        f"<b>{title_map.get(mode, 'Menu')}</b>",
        reply_markup=get_tree_root_kb(mode),
        parse_mode="HTML"
    )

async def show_ranges_sublist(callback, title, ranges, mode, back_action):
    kb = []
    for r in sorted(ranges):
        count = len(utils.numbers_data[r])
        if mode == 'exp': cb = f"do_exp:range:{r}"
        elif mode == 'rm': cb = f"ask_rm:range:{r}"
        else: cb = f"view_rng:{r}:1"
        kb.append([InlineKeyboardButton(text=f"📁 {r} ({count})", callback_data=cb)])
    
    kb.append([InlineKeyboardButton(text="🔙 Back", callback_data=f"tree:{mode}:{back_action}")])
    await callback.message.edit_text(f"<b>{title}</b>\nSelect a range:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

# ===================== EXECUTORS =====================

@dp.callback_query(F.data.startswith("do_exp:"))
async def handle_specific_export(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    val = parts[2]
    await execute_export(callback, "Range", val, [val])

async def execute_export(callback, type_label, name_label, ranges_list):
    await callback.message.edit_text("⏳ Generating file...")
    lines = []
    total = 0
    lines.append(f"Export: {type_label} - {name_label}")
    lines.append("Number | Range | ID")
    lines.append("-" * 40)
    
    for r in ranges_list:
        if r in utils.numbers_data:
            for item in utils.numbers_data[r]:
                num = item.get('number', 'Unknown')
                if not num.startswith("+"): num = f"+{num}"
                tid = item.get('id', '-')
                lines.append(f"{num} | {r} | {tid}")
                total += 1
            
    content = "\n".join(lines)
    fname = f"export_{type_label}_{name_label[:10]}.txt".replace(" ", "_")
    f = BufferedInputFile(content.encode('utf-8'), filename=fname)
    await callback.message.answer_document(document=f, caption=f"✅ <b>Export Complete</b>\nTotal: {total} numbers", parse_mode="HTML")
    await callback.message.delete()

async def ask_bulk_remove(callback, type_label, name_label, ranges_list):
    count = 0
    for r in ranges_list:
        if r in utils.numbers_data:
            count += len(utils.numbers_data[r])
            
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ YES, DELETE ALL", callback_data=f"exec_rm:{type_label}:{name_label}")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_action")]
    ])
    utils.temp_remove_list = ranges_list
    await callback.message.edit_text(f"⚠️ <b>BULK DELETE WARNING</b> ⚠️\n\nTarget: <b>{name_label}</b> ({type_label})\nTotal: {count}\nAre you sure?", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("ask_rm:range:"))
async def ask_single_remove(callback: types.CallbackQuery):
    range_name = callback.data.split(":")[2]
    count = len(utils.numbers_data.get(range_name, []))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Confirm Delete", callback_data=f"exec_rm:Range:{range_name}")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_action")]
    ])
    utils.temp_remove_list = [range_name]
    await callback.message.edit_text(f"⚠️ Delete Range <b>{range_name}</b>?\nContains {count} numbers.", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("exec_rm:"))
async def execute_remove_action(callback: types.CallbackQuery):
    if not hasattr(utils, 'temp_remove_list') or not utils.temp_remove_list:
        await callback.answer("Session expired. Try again.")
        return

    ranges_to_del = utils.temp_remove_list
    total_deleted = 0
    await callback.message.edit_text("⏳ Deleting numbers...")
    
    for rng in ranges_to_del:
        if rng in utils.numbers_data:
            ok, msg = await api.remove_range(rng)
            if ok: total_deleted += 1
                
    await callback.message.edit_text(f"✅ <b>Deleted {total_deleted} Ranges.</b>", parse_mode="HTML")
    utils.temp_remove_list = []

@dp.callback_query(F.data.startswith("view_rng:"))
async def view_range_numbers(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    range_name = parts[1]
    page = int(parts[2])
    
    if not hasattr(utils, "numbers_data") or range_name not in utils.numbers_data:
        await callback.answer("Range not found.")
        return

    items = utils.numbers_data[range_name]
    total_items = len(items)
    total_pages = math.ceil(total_items / PAGE_SIZE)
    if total_pages == 0: total_pages = 1
    
    start_idx = (page - 1) * PAGE_SIZE
    end_idx = start_idx + PAGE_SIZE
    current_items = items[start_idx:end_idx]
    
    text = f"📂 <b>Range:</b> {range_name} (Page {page}/{total_pages})\nTotal: {total_items} numbers\n\n"
    for item in current_items:
        num = item['number']
        if not num.startswith("+"): num = f"+{num}"
        text += f"• <code>{num}</code>\n"
        
    nav_btns = get_pagination_kb(f"view_rng:{range_name}", page, total_pages)
    back_row = [InlineKeyboardButton(text="🔙 Back to Menu", callback_data="tree_back:view")]
    kb = InlineKeyboardMarkup(inline_keyboard=[nav_btns, back_row])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "noop")
async def noop_handler(c): await c.answer()

# ===================== ADD NUMBER =====================

@dp.message(F.text == "➕ Add Range")
async def ask_add_range_category(message: types.Message):
    categories = await db.db.get_categories()
    static_cats = ["WhatsApp", "Facebook", "Telegram", "TikTok", "Google", "Instagram"]
    final_cats = []
    for c in static_cats:
        if c in categories: final_cats.append(c)
    for c in categories:
        if c not in final_cats and c != "Other": final_cats.append(c)
    
    kb_rows = []
    kb_rows.append([InlineKeyboardButton(text="🔥 Top 10 Hot Ranges", callback_data="add_cat:top10")])
    current_row = []
    for cat in final_cats:
        current_row.append(InlineKeyboardButton(text=f"{cat}", callback_data=f"add_cat:{cat}"))
        if len(current_row) == 2:
            kb_rows.append(current_row)
            current_row = []
    if current_row: kb_rows.append(current_row)
    kb_rows.append([InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_action")])
    await message.answer("➕ <b>Add Range: Select Category</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows), parse_mode="HTML")

@dp.callback_query(F.data.startswith("add_cat:"))
async def add_number_show_ranges(callback: types.CallbackQuery):
    cat = callback.data.split(":")[1]
    if cat == "top10":
        items = await db.db.get_top_10()
        title = "🔥 <b>Top 10 Hot Ranges</b>"
    else:
        items = await db.db.get_ranges_by_category(cat)
        title = f"📱 <b>{cat} Ranges</b>"
    
    if not items:
        await callback.answer("No active ranges.", show_alert=True)
        return

    kb_rows = []
    for item in items:
        btn_text = f"{item['termination_name']} (Act: {item.get('hit_count', 1)})"
        term_id = item['termination_id']
        kb_rows.append([InlineKeyboardButton(text=btn_text, callback_data=f"do_add:{term_id}")])
    kb_rows.append([InlineKeyboardButton(text="🔙 Back", callback_data="back_to_cats")])
    await callback.message.edit_text(f"{title}\nClick to <b>ADD Range</b>:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows), parse_mode="HTML")

@dp.callback_query(F.data == "back_to_cats")
async def back_to_add_cats(callback: types.CallbackQuery):
    await callback.message.delete()
    await ask_add_range_category(callback.message)

@dp.callback_query(F.data.startswith("do_add:"))
async def execute_add_range(callback: types.CallbackQuery):
    term_id = callback.data.split(":")[1]
    await callback.message.edit_text(f"⏳ <b>Adding Range ID {term_id}...</b>", parse_mode="HTML")
    ok, msg = await api.add_number(term_id)
    if ok: await callback.message.edit_text(f"✅ <b>Range Added:</b> {msg}", parse_mode="HTML")
    else: await callback.message.edit_text(f"❌ <b>Failed:</b> {msg}", parse_mode="HTML")

@dp.callback_query(F.data == "cancel_action")
async def cancel_handler(c):
    utils.add_number_pending.pop(c.message.chat.id, None)
    await c.message.delete()

# ===================== HISTORY & TEXT =====================

@dp.message(F.text)
async def handle_text(message: types.Message):
    if utils.add_number_pending.get(message.chat.id):
        term_id = message.text.strip()
        if not term_id.isdigit():
            await message.answer("⚠️ Digits only.")
            return
        status_msg = await message.answer(f"⏳ Adding Range <b>{term_id}</b>...", parse_mode="HTML")
        ok, msg = await api.add_number(term_id)
        utils.add_number_pending.pop(message.chat.id, None)
        if ok: await status_msg.edit_text(f"✅ {msg}", parse_mode="HTML")
        else: await status_msg.edit_text(f"❌ {msg}", parse_mode="HTML")
        return

    if message.text == "📊 Status":
        connected = "✅ YES" if utils.current_livesms_token else "❌ NO"
        msg = f"📊 <b>Bot Status</b>\n• WebSocket: {connected}\n• OTPs Received: {utils.otp_stats['total']}"
        await message.answer(msg, parse_mode="HTML")
    
    elif message.text == "📜 History":
        if not utils.otp_history:
            await message.answer("📜 No OTPs yet.")
        else:
            txt = "📜 <b>Recent OTPs:</b>\n\n"
            for otp in utils.otp_history[-10:]:
                code = otp.get('otp_code', '-')
                sender = otp.get('originator', 'Unknown')
                recipient = otp.get('recipient', 'Unknown')
                txt += f"• <code>{code}</code>\n   To: <b>{recipient}</b> | From: {sender}\n\n"
            await message.answer(txt, parse_mode="HTML")

# ===================== STARTUP =====================

async def main():
    await db.db.init_db()
    t = threading.Thread(target=browser_thread_target, daemon=True)
    t.start()
    asyncio.create_task(websocket_loop())
    # --- FIX: credential_watchdog is now imported correctly ---
    asyncio.create_task(credential_watchdog())
    scanner = TerminationScanner()
    asyncio.create_task(scanner.start())

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    if not hasattr(utils, "add_number_pending"): utils.add_number_pending = {}
    asyncio.run(main())
