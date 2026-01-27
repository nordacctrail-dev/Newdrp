from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
import state
import core.api as api

router = Router()

# --- KEYBOARDS ---
def get_main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 My Numbers", callback_data="menu_numbers"),
         InlineKeyboardButton(text="➕ Add Number", callback_data="menu_add")],
        [InlineKeyboardButton(text="🗑 Remove Range", callback_data="menu_remove"),
         InlineKeyboardButton(text="📊 Stats", callback_data="menu_stats")],
        [InlineKeyboardButton(text="🔄 Refresh", callback_data="menu_refresh")]
    ])

# --- HANDLERS ---

@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer("🤖 <b>IVASMS Bot Online</b>", reply_markup=get_main_menu())

@router.callback_query(F.data == "menu_refresh")
async def cb_refresh(callback: CallbackQuery):
    await callback.answer("Refreshing...")
    success, msg = await api.fetch_numbers()
    await callback.message.answer(msg)

@router.callback_query(F.data == "menu_stats")
async def cb_stats(callback: CallbackQuery):
    stats = state.otp_stats
    txt = (f"📊 <b>Session Stats</b>\n"
           f"Total OTPs: {stats['total']}\n"
           f"Active Ranges: {len(state.numbers_ids_by_group)}")
    await callback.message.answer(txt)
    await callback.answer()

@router.callback_query(F.data == "menu_numbers")
async def cb_numbers(callback: CallbackQuery):
    if not state.numbers_ids_by_group:
        await callback.message.answer("⚠️ No numbers fetched. Click Refresh first.")
        await callback.answer()
        return

    txt = "📋 <b>Active Ranges:</b>\n\n"
    for rng, ids in state.numbers_ids_by_group.items():
        txt += f"• <b>{rng}</b>: {len(ids)} numbers\n"
    
    await callback.message.answer(txt[:4000]) # Telegram limit
    await callback.answer()

@router.message(Command("add"))
async def cmd_add(message: Message):
    # Usage: /add 123456
    args = message.text.split()
    if len(args) < 2:
        await message.answer("⚠️ Usage: <code>/add 123456</code>")
        return
    
    term_id = args[1]
    msg = await message.answer(f"⏳ Adding {term_id}...")
    success, resp = await api.add_number(term_id)
    await msg.edit_text(resp)

@router.message(Command("remove"))
async def cmd_remove(message: Message):
    # Usage: /remove RANGE_NAME
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("⚠️ Usage: <code>/remove USA 1</code>")
        return
    
    rng = args[1]
    msg = await message.answer(f"⏳ Removing range {rng}...")
    success, resp = await api.remove_range(rng)
    await msg.edit_text(resp)
