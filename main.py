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

# Constants
PAGE_SIZE = 10  # Number of items per page

# ===================== KEYBOARDS =====================

def get_main_menu():
    """Persistent Bottom Menu (Hybrid UI)"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Numbers"), KeyboardButton(text="🔎 Choose Range")],
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
    """Generates Previous/Next buttons"""
    buttons = []
    if current_page > 1:
        buttons.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"{prefix}:{current_page-1}:{extra_data}"))
    
    buttons.append(InlineKeyboardButton(text=f"{current_page}/{total_pages}", callback_data="noop"))
    
    if current_page < total_pages:
        buttons.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"{prefix}:{current_page+1}:{extra_data}"))
    
    return InlineKeyboardMarkup(inline_keyboard=[buttons, [InlineKeyboardButton(text="🔙 Back", callback_data="back_to_ranges")]])

# ===================== COMMAND HANDLERS =====================

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "🤖 **IVASMS Bot Ready**\n"
        "Session monitored via Selenium.\n"
        "Use the menu below to manage numbers:",
        reply_markup=get_main_menu(),
        parse_mode="Markdown"
    )

@dp.message(Command("menu"))
async def cmd_menu(message: types.Message):
    await message.answer("📂 **Main Menu**", reply_markup=get_main_menu(), parse_mode="Markdown")

# ===================== NUMBERS & RANGES HANDLERS =====================

async def show_ranges(message_or_call, edit=False):
    """Fetches numbers and displays Ranges as Inline Buttons."""
    if isinstance(message_or_call, types.Message):
        status_msg = await message_or_call.answer("🔄 Fetching numbers...")
    else:
        status_msg = message_or_call.message

    # 1. Fetch Numbers
    ok, msg = await api.fetch_numbers()
    
    if not ok:
        text = f"⚠️ **Error:** {msg}\n\nIf it's Cloudflare, it will auto-solve in the browser."
        if edit: await status_msg.edit_text(text, parse_mode="Markdown")
        else: await status_msg.edit_text(text, parse_mode="Markdown")
        return

    # 2. Check Data
    if not state.numbers_ids_by_group:
        await status_msg.edit_text("⚠️ No numbers found.", parse_mode="Markdown")
        return

    # 3. Build Inline Buttons for Ranges
    buttons = []
    row = []
    for rng in sorted(state.numbers_ids_by_group.keys()):
        count = len(state.numbers_ids_by_group[rng])
        btn_text = f"{rng} ({count})"
        row.append(InlineKeyboardButton(text=btn_text, callback_data=f"view_rng:{rng}:1"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row: buttons.append(row)

    # 4. Send/Edit Message
    text = "🔎 **Select a Range** to view numbers:"
    if edit:
        await status_msg.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")
    else:
        await status_msg.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")

@dp.message(F.text.in_({"📋 Numbers", "🔎 Choose Range"}))
async def handle_numbers_btn(message: types.Message):
    await show_ranges(message, edit=False)

@dp.callback_query(F.data == "back_to_ranges")
async def back_to_ranges(callback: types.CallbackQuery):
    await show_ranges(callback, edit=True)
    await callback.answer()

@dp.callback_query(F.data.startswith("view_rng:"))
async def view_range_numbers(callback: types.CallbackQuery):
    _, range_name, page_str = callback.data.split(":")
    page = int(page_str)
    
    if range_name not in state.numbers_ids_by_group:
        await callback.answer("Range not found (refresh needed).")
        return

    # Pagination Logic
    ids = state.numbers_ids_by_group[range_name]
    total_items = len(ids)
    total_pages = math.ceil(total_items / PAGE_SIZE)
    start_idx = (page - 1) * PAGE_SIZE
    end_idx = start_idx + PAGE_SIZE
    
    current_items = ids[start_idx:end_idx]
    
    # Render List
    text = f"📂 **Range:** {range_name} (Page {page}/{total_pages})\n\n"
    for num_id in current_items:
        # Note: API might only give IDs initially. If we fix API, we can show phone numbers here.
        text += f"• `{num_id}`\n"
        
    kb = get_pagination_kb("view_rng", page, total_pages, range_name)
    
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "noop")
async def noop_handler(callback: types.CallbackQuery):
    await callback.answer("Current Page")

# ===================== ADD NUMBER HANDLERS =====================

@dp.message(F.text == "➕ Add Number")
async def ask_add_number(message: types.Message):
    state.add_number_pending[message.chat.id] = True
    await message.answer(
        "➕ **Send the Termination ID** to add (e.g. `980693`):",
        reply_markup=get_cancel_kb(),
        parse_mode="Markdown"
    )

# ===================== REMOVE NUMBER HANDLERS =====================

@dp.message(F.text == "🗑 Remove Numbers")
async def ask_remove_range(message: types.Message):
    status_msg = await message.answer("🔄 Fetching ranges...")
    ok, msg = await api.fetch_numbers()
    
    if not ok:
        await status_msg.edit_text(f"⚠️ Error: {msg}")
        return

    if not state.numbers_ids_by_group:
        await status_msg.edit_text("⚠️ No numbers to remove.")
        return

    # Build Buttons
    buttons = []
    for rng in sorted(state.numbers_ids_by_group.keys()):
        count = len(state.numbers_ids_by_group[rng])
        buttons.append([InlineKeyboardButton(text=f"🗑 {rng} ({count})", callback_data=f"ask_rm:{rng}")])
    
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_action")])
    
    await status_msg.edit_text(
        "🗑 **Select a Range to WIPE** all numbers from:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("ask_rm:"))
async def confirm_remove(callback: types.CallbackQuery):
    range_name = callback.data.split(":")[1]
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ YES, DELETE", callback_data=f"do_rm:{range_name}")],
        [InlineKeyboardButton(text="❌ No, Cancel", callback_data="cancel_action")]
    ])
    
    await callback.message.edit_text(
        f"⚠️ **CONFIRM DELETION** ⚠️\n\n"
        f"Are you sure you want to remove ALL numbers in range **{range_name}**?",
        reply_markup=kb,
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("do_rm:"))
async def execute_remove(callback: types.CallbackQuery):
    range_name = callback.data.split(":")[1]
    await callback.message.edit_text(f"⏳ Removing numbers from {range_name}...")
    
    ok, msg = await api.remove_range(range_name)
    
    if ok:
        await callback.message.edit_text(f"✅ **Success:** {msg}", parse_mode="Markdown")
    else:
        await callback.message.edit_text(f"❌ **Failed:** {msg}", parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "cancel_action")
async def cancel_handler(callback: types.CallbackQuery):
    state.add_number_pending.pop(callback.message.chat.id, None)
    await callback.message.edit_text("❌ Action Cancelled.")
    await callback.answer("Cancelled")

# ===================== GENERIC TEXT HANDLER =====================

@dp.message(F.text)
async def handle_text(message: types.Message):
    # Handle Add Number Input
    if state.add_number_pending.get(message.chat.id):
        term_id = message.text.strip()
        if not term_id.isdigit():
            await message.answer("⚠️ Invalid ID. Please send numbers only (e.g. `123456`).")
            return
            
        status_msg = await message.answer(f"⏳ Adding **{term_id}**...", parse_mode="Markdown")
        ok, msg = await api.add_number(term_id)
        state.add_number_pending.pop(message.chat.id, None)
        
        if ok:
            await status_msg.edit_text(f"✅ {msg}", parse_mode="Markdown")
        else:
            await status_msg.edit_text(f"❌ {msg}", parse_mode="Markdown")
        return

    # Handle Status/History
    if message.text == "📊 Status":
        connected = "✅ YES" if state.current_livesms_token else "❌ NO"
        ua_stat = "✅ Captured" if state.current_user_agent else "⚠️ Missing"
        msg = (
            f"📊 **Bot Status**\n"
            f"• WebSocket: {connected}\n"
            f"• Browser UA: {ua_stat}\n"
            f"• OTPs Received: {state.otp_stats['total']}"
        )
        await message.answer(msg, parse_mode="Markdown")
        
    elif message.text == "📜 History":
        if not state.otp_history:
            await message.answer("📜 No OTPs yet.")
        else:
            txt = "📜 **Recent OTPs:**\n\n"
            for otp in state.otp_history[-5:]:
                txt += f"• `{otp.get('otp_code')}` from `{otp.get('originator')}`\n"
            await message.answer(txt, parse_mode="Markdown")

# ===================== STARTUP =====================

async def main():
    # 1. Start Browser Thread (Background)
    t = threading.Thread(target=browser_thread_target, daemon=True)
    t.start()
    
    # 2. Start WebSocket Loop (Async Background)
    asyncio.create_task(websocket_loop())
    
    # 3. Start Bot Polling
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    # Ensure state exists (if running standalone for test)
    if not hasattr(state, "add_number_pending"):
        state.add_number_pending = {}
        
    asyncio.run(main())
