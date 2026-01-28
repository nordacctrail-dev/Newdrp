import asyncio
import logging
import threading
import os
import math
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import (
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton
)
from aiogram.filters import Command

# Import core modules
import config
import state
from core.browser import browser_thread_target
from core.websocket import websocket_loop
from core import api

# Logging Setup
logging.basicConfig(level=logging.INFO)
bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# ===================== SETTINGS =====================
PAGE_SIZE = 20  # Updated to 20 items per page

# ===================== KEYBOARDS =====================

def get_main_menu():
    """Persistent Bottom Menu (Hybrid UI)"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 All Numbers"), KeyboardButton(text="🔎 Choose Range")],
            [KeyboardButton(text="➕ Add Number"), KeyboardButton(text="🗑 Remove Numbers")],
            [KeyboardButton(text="📊 Status"), KeyboardButton(text="📜 History")]
        ],
        resize_keyboard=True,
        persistent=True
    )

def get_cancel_kb():
    """Inline Cancel Button"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_action")]
    ])

def get_pagination_kb(prefix: str, current_page: int, total_pages: int, extra_data: str = ""):
    """
    Generates Previous/Next buttons for pagination.
    Data format: 'prefix:extra_data:page'
    """
    buttons = []
    
    # PREVIOUS BUTTON
    if current_page > 1:
        data_str = f"{prefix}:{extra_data}:{current_page-1}" if extra_data else f"{prefix}:{current_page-1}"
        buttons.append(InlineKeyboardButton(
            text="⬅️ Prev", 
            callback_data=data_str
        ))
    
    # INDICATOR
    buttons.append(InlineKeyboardButton(
        text=f"{current_page}/{total_pages}", 
        callback_data="noop"
    ))
    
    # NEXT BUTTON
    if current_page < total_pages:
        data_str = f"{prefix}:{extra_data}:{current_page+1}" if extra_data else f"{prefix}:{current_page+1}"
        buttons.append(InlineKeyboardButton(
            text="Next ➡️", 
            callback_data=data_str
        ))
    
    # Bottom row
    if prefix == "view_rng":
        back_btn = [InlineKeyboardButton(text="🔙 Back to Ranges", callback_data="back_to_ranges")]
        return InlineKeyboardMarkup(inline_keyboard=[buttons, back_btn])
    else:
        return InlineKeyboardMarkup(inline_keyboard=[buttons])

# ===================== COMMAND HANDLERS =====================

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "🤖 <b>IVASMS Bot Ready</b>\n"
        "Session monitored via Selenium.\n"
        "Use the menu below to manage numbers:",
        reply_markup=get_main_menu(),
        parse_mode="HTML"
    )

@dp.message(Command("menu"))
async def cmd_menu(message: types.Message):
    await message.answer("📂 <b>Main Menu</b>", reply_markup=get_main_menu(), parse_mode="HTML")

# ===================== ALL NUMBERS HANDLER (📋 All Numbers) =====================

async def show_all_numbers(message_or_call, page=1, edit=False):
    """Fetches and displays ALL numbers from ALL ranges in a single list."""
    if isinstance(message_or_call, types.Message):
        status_msg = await message_or_call.answer("🔄 Fetching all numbers...")
    else:
        status_msg = message_or_call.message

    if not edit: 
        ok, msg = await api.fetch_numbers()
        if not ok:
            text = f"⚠️ <b>Error:</b> {msg}"
            if edit: await status_msg.edit_text(text, parse_mode="HTML")
            else: await status_msg.edit_text(text, parse_mode="HTML")
            return

    if not hasattr(state, "numbers_data") or not state.numbers_data:
        text = "⚠️ No numbers found."
        if edit: await status_msg.edit_text(text, parse_mode="HTML")
        else: await status_msg.edit_text(text, parse_mode="HTML")
        return

    all_items = []
    for rng_name, items in state.numbers_data.items():
        for item in items:
            item_copy = item.copy()
            item_copy['range_name'] = rng_name
            all_items.append(item_copy)
            
    total_items = len(all_items)
    total_pages = math.ceil(total_items / PAGE_SIZE)
    if total_pages == 0: total_pages = 1
    
    if page > total_pages: page = total_pages
    
    start_idx = (page - 1) * PAGE_SIZE
    end_idx = start_idx + PAGE_SIZE
    
    current_items = all_items[start_idx:end_idx]
    
    text = f"📋 <b>All Numbers</b> (Page {page}/{total_pages})\n"
    text += f"Total: {total_items} numbers\n\n"
    
    for item in current_items:
        num = item['number']
        if not num.startswith("+"): num = f"+{num}"
        text += f"• <code>{num}</code> ({item['range_name']})\n"

    kb = get_pagination_kb("view_all", page, total_pages, extra_data="")

    if edit:
        await status_msg.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await status_msg.edit_text(text, reply_markup=kb, parse_mode="HTML")

@dp.message(F.text == "📋 All Numbers")
async def handle_all_numbers_btn(message: types.Message):
    await show_all_numbers(message, page=1, edit=False)

@dp.callback_query(F.data.startswith("view_all:"))
async def view_all_numbers(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    
    if len(parts) == 3:
        page = int(parts[2])
    else:
        page = int(parts[1])

    await show_all_numbers(callback, page=page, edit=True)
    await callback.answer()


# ===================== RANGES HANDLER (🔎 Choose Range) =====================

async def show_ranges(message_or_call, edit=False):
    if isinstance(message_or_call, types.Message):
        status_msg = await message_or_call.answer("🔄 Fetching numbers...")
    else:
        status_msg = message_or_call.message

    if not edit:
        ok, msg = await api.fetch_numbers()
        if not ok:
            text = f"⚠️ <b>Error:</b> {msg}\n\nIf it's Cloudflare, it will auto-solve in the browser."
            if edit: await status_msg.edit_text(text, parse_mode="HTML")
            else: await status_msg.edit_text(text, parse_mode="HTML")
            return

    if not hasattr(state, "numbers_data") or not state.numbers_data:
        text = "⚠️ No numbers found."
        if edit: await status_msg.edit_text(text, parse_mode="HTML")
        else: await status_msg.edit_text(text, parse_mode="HTML")
        return

    # --- MODIFIED: Single Column Layout ---
    buttons = []
    for rng in sorted(state.numbers_data.keys()):
        count = len(state.numbers_data[rng])
        btn_text = f"{rng} ({count})"
        # Directly append a list containing ONE button to make it a single column
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"view_rng:{rng}:1")])

    text = "🔎 <b>Select a Range</b> to view numbers:"
    if edit:
        await status_msg.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
    else:
        await status_msg.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")

@dp.message(F.text == "🔎 Choose Range")
async def handle_ranges_btn(message: types.Message):
    await show_ranges(message, edit=False)

@dp.callback_query(F.data == "back_to_ranges")
async def back_to_ranges(callback: types.CallbackQuery):
    await show_ranges(callback, edit=True)
    await callback.answer()

@dp.callback_query(F.data.startswith("view_rng:"))
async def view_range_numbers(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    range_name = parts[1]
    page = int(parts[2])
    
    if not hasattr(state, "numbers_data") or range_name not in state.numbers_data:
        await callback.answer("Range not found (refresh needed).")
        return

    items = state.numbers_data[range_name]
    total_items = len(items)
    total_pages = math.ceil(total_items / PAGE_SIZE)
    if total_pages == 0: total_pages = 1
    
    start_idx = (page - 1) * PAGE_SIZE
    end_idx = start_idx + PAGE_SIZE
    
    current_items = items[start_idx:end_idx]
    
    text = f"📂 <b>Range:</b> {range_name} (Page {page}/{total_pages})\n"
    text += f"Total: {total_items} numbers\n\n"
    
    for item in current_items:
        num = item['number']
        if not num.startswith("+"):
            num = f"+{num}"
        text += f"• <code>{num}</code>\n"
        
    kb = get_pagination_kb("view_rng", page, total_pages, range_name)
    
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "noop")
async def noop_handler(callback: types.CallbackQuery):
    await callback.answer(f"Page {callback.message.reply_markup.inline_keyboard[0][1].text}")

# ===================== ADD NUMBER HANDLERS =====================

@dp.message(F.text == "➕ Add Number")
async def ask_add_number(message: types.Message):
    state.add_number_pending[message.chat.id] = True
    await message.answer(
        "➕ <b>Send the Termination ID</b> to add (e.g. <code>980693</code>):",
        reply_markup=get_cancel_kb(),
        parse_mode="HTML"
    )

# ===================== REMOVE NUMBER HANDLERS =====================

@dp.message(F.text == "🗑 Remove Numbers")
async def ask_remove_range(message: types.Message):
    status_msg = await message.answer("🔄 Fetching ranges...")
    ok, msg = await api.fetch_numbers()
    
    if not ok:
        await status_msg.edit_text(f"⚠️ Error: {msg}")
        return

    if not hasattr(state, "numbers_data") or not state.numbers_data:
        await status_msg.edit_text("⚠️ No numbers to remove.")
        return

    buttons = []
    for rng in sorted(state.numbers_data.keys()):
        count = len(state.numbers_data[rng])
        buttons.append([InlineKeyboardButton(text=f"🗑 {rng} ({count})", callback_data=f"ask_rm:{rng}")])
    
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_action")])
    
    await status_msg.edit_text(
        "🗑 <b>Select a Range to WIPE</b> all numbers from:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("ask_rm:"))
async def confirm_remove(callback: types.CallbackQuery):
    range_name = callback.data.split(":")[1]
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ YES, DELETE ALL", callback_data=f"do_rm:{range_name}")],
        [InlineKeyboardButton(text="❌ No, Cancel", callback_data="cancel_action")]
    ])
    
    await callback.message.edit_text(
        f"⚠️ <b>CONFIRM DELETION</b> ⚠️\n\n"
        f"Are you sure you want to remove ALL numbers in range <b>{range_name}</b>?",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("do_rm:"))
async def execute_remove(callback: types.CallbackQuery):
    range_name = callback.data.split(":")[1]
    await callback.message.edit_text(f"⏳ Removing numbers from {range_name}...")
    
    ok, msg = await api.remove_range(range_name)
    
    if ok:
        await callback.message.edit_text(f"✅ <b>Success:</b> {msg}", parse_mode="HTML")
    else:
        await callback.message.edit_text(f"❌ <b>Failed:</b> {msg}", parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "cancel_action")
async def cancel_handler(callback: types.CallbackQuery):
    state.add_number_pending.pop(callback.message.chat.id, None)
    await callback.message.edit_text("❌ Action Cancelled.")
    await callback.answer("Cancelled")

# ===================== GENERIC TEXT HANDLER =====================

@dp.message(F.text)
async def handle_text(message: types.Message):
    if state.add_number_pending.get(message.chat.id):
        term_id = message.text.strip()
        
        if not term_id.isdigit():
            await message.answer("⚠️ Invalid ID. Please send numbers only (e.g. <code>123456</code>).", parse_mode="HTML")
            return
            
        status_msg = await message.answer(f"⏳ Adding <b>{term_id}</b>...", parse_mode="HTML")
        
        ok, msg = await api.add_number(term_id)
        state.add_number_pending.pop(message.chat.id, None)
        
        if ok:
            await status_msg.edit_text(f"✅ {msg}", parse_mode="HTML")
        else:
            await status_msg.edit_text(f"❌ {msg}", parse_mode="HTML")
        return

    if message.text == "📊 Status":
        connected = "✅ YES" if state.current_livesms_token else "❌ NO"
        ua_stat = "✅ Captured" if state.current_user_agent else "⚠️ Missing (Wait for browser)"
        
        msg = (
            f"📊 <b>Bot Status</b>\n"
            f"• WebSocket: {connected}\n"
            f"• Browser UA: {ua_stat}\n"
            f"• OTPs Received: {state.otp_stats['total']}\n"
        )
        await message.answer(msg, parse_mode="HTML")
        
    elif message.text == "📜 History":
        if not state.otp_history:
            await message.answer("📜 No OTPs yet.")
        else:
            txt = "📜 <b>Recent OTPs:</b>\n\n"
            for otp in state.otp_history[-5:]:
                code = otp.get('otp_code', '-')
                sender = otp.get('originator', 'Unknown')
                txt += f"• <code>{code}</code> from <code>{sender}</code>\n"
            await message.answer(txt, parse_mode="HTML")

# ===================== STARTUP =====================

async def main():
    t = threading.Thread(target=browser_thread_target, daemon=True)
    t.start()
    
    asyncio.create_task(websocket_loop())
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    if not hasattr(state, "add_number_pending"):
        state.add_number_pending = {}
        
    asyncio.run(main())
