import logging
import asyncio
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from utils import ExportManager, CountryManager

class CallbackMixin:
    """
    Handles all Inline Button clicks.
    """

    # Tracks checkbox selections for multi-account actions
    selection_state = {} 

    async def handle_callback(self, u):
        try:
            # Safe extraction for aiogram v3 structure
            cb = u["callback_query"]
            msg = cb.get("message", {})
            cid = msg.get("chat", {}).get("id")
            mid = msg.get("message_id")
            data = cb.get("data")
            from_user = cb.get("from", {})
            user_id = from_user.get("id")
            
            if not cid or not data: return

            # --- AUTH CHECK ---
            is_owner = (user_id == self.cfg.OWNER_ID)
            user_data = await self.db.get_user(user_id)
            is_admin = is_owner or (user_data and user_data.get("is_admin", False))

            # ====================================================
            # 1. EXPORT ACTIONS
            # ====================================================
            if data == "exp:main_menu":
                await self.show_main_export_menu(cid, mid, user_id, user_data, is_admin)

            elif data == "exp:combined":
                await self.bot.edit_msg(cid, mid, "🔄 <i>Preparing file...</i>")
                visible_emails = await self.get_visible_emails(user_id)
                
                all_nums = []
                for e in visible_emails:
                    w = self.workers.get(e)
                    if w:
                        if not w.all_numbers: await w.sync_numbers()
                        all_nums.extend(w.all_numbers)
                
                if not all_nums:
                    await self.bot.edit_msg(cid, mid, "❌ No numbers found.")
                else:
                    path = ExportManager.generate(all_nums, "All_Numbers")
                    # FIX: Use FSInputFile for local files
                    await self.bot.send_file(cid, path, f"<b>📤 Export Ready</b>\nCount: {len(all_nums)}")
                    await self.bot.delete_msg(cid, mid)

            elif data == "exp:ctry_menu":
                await self.show_country_selection(cid, mid, user_id, "exp", is_admin)

            elif data.startswith("exp:gen_ctry:"):
                ctry = data.split(":", 2)[2]
                await self.bot.edit_msg(cid, mid, f"⏳ <i>Exporting {ctry}...</i>")
                
                perms = [] if is_owner else user_data.get("permissions", [])
                countries = self.get_combined_countries(user_id, perms, is_admin)
                nums = countries.get(ctry, [])
                
                if nums:
                    path = ExportManager.generate(nums, f"Export_{ctry}")
                    await self.bot.send_file(cid, path, f"<b>📤 {ctry} Export</b>\nCount: {len(nums)}")
                    await self.bot.delete_msg(cid, mid)
                else:
                    await self.bot.edit_msg(cid, mid, "❌ Empty.")

            # ====================================================
            # 2. VIEWING & NAVIGATION
            # ====================================================
            elif data == "nav:main_root":
                await self.show_choose_range_root(cid, mid, user_id, is_admin)

            elif data == "nav:ctry_menu":
                await self.show_country_selection(cid, mid, user_id, "nav", is_admin)
                
            elif data.startswith("nav:view_ctry:"):
                parts = data.split(":")
                ctry = parts[2]
                page = int(parts[3])
                
                perms = [] if is_owner else user_data.get("permissions", [])
                countries = self.get_combined_countries(user_id, perms, is_admin)
                nums = countries.get(ctry, [])
                
                total_p = (len(nums) + 19) // 20
                chunk = nums[page*20 : (page+1)*20]
                
                text = f"🌎 <b>{ctry}</b> (Page {page+1}/{total_p})\n" + "\n".join([f"• <code>{n}</code>" for n in chunk])
                
                nav_row = []
                if page > 0: 
                    nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"nav:view_ctry:{ctry}:{page-1}"))
                if page < total_p - 1: 
                    nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"nav:view_ctry:{ctry}:{page+1}"))
                
                rows = []
                if nav_row: rows.append(nav_row)
                rows.append([InlineKeyboardButton(text="🔙 Back", callback_data="nav:ctry_menu")])
                
                markup = InlineKeyboardMarkup(inline_keyboard=rows)
                await self.bot.edit_msg(cid, mid, text, reply_markup=markup)

            # ====================================================
            # 3. ADD NUMBER SETUP
            # ====================================================
            elif data.startswith("add:sel:"):
                email = data.split(":")[2]
                from bot_handlers import HandlerMixin
                HandlerMixin.user_states[user_id] = {
                    "action": "add_number",
                    "target": [email],
                    "step": "await_name" 
                }
                await self.bot.delete_msg(cid, mid)
                await self.bot.send_to_chat(cid, f"📝 <b>Adding to {email}</b>\n\n👇 Enter <b>Termination Name</b>:\n<i>(One per line)</i>\n\nType /cancel to abort.")

            # ====================================================
            # 4. ADMIN PANEL ACTIONS (Owner Only)
            # ====================================================
            elif data == "usr:main":
                users = await self.db.get_all_users()
                kb_rows = []
                for u in users:
                    if u['chat_id'] == self.cfg.OWNER_ID: continue
                    kb_rows.append([InlineKeyboardButton(text=f"👤 {u.get('name','User')} ({u['chat_id']})", callback_data=f"perm:sel_usr:{u['chat_id']}")])
                
                kb_rows.append([InlineKeyboardButton(text="➕ Add User by ID", callback_data="usr:add")])
                kb_rows.append([InlineKeyboardButton(text="🔙 Close", callback_data="menu_close")])
                
                markup = InlineKeyboardMarkup(inline_keyboard=kb_rows)
                await self.bot.edit_msg(cid, mid, "<b>👤 User Management</b>\nSelect user to edit:", reply_markup=markup)

            elif data == "usr:add":
                # Force Reply is a bit different, sending a standard msg with reply_markup
                await self.bot.api("sendMessage", {
                    "chat_id": cid, 
                    "text": "✏️ <b>Enter Telegram User ID:</b>", 
                    "reply_markup": {"force_reply": True}
                })

            elif data == "acc:main":
                accounts = await self.db.get_all_accounts()
                kb_rows = [[InlineKeyboardButton(text=f"🗑 {a['email']}", callback_data=f"acc:del:{a['email']}")] for a in accounts]
                kb_rows.append([InlineKeyboardButton(text="➕ Add Account", callback_data="acc:add")])
                kb_rows.append([InlineKeyboardButton(text="🔙 Close", callback_data="menu_close")])
                
                markup = InlineKeyboardMarkup(inline_keyboard=kb_rows)
                await self.bot.edit_msg(cid, mid, "<b>📧 Account Settings</b>\nClick to delete:", reply_markup=markup)

            elif data == "acc:add":
                await self.bot.api("sendMessage", {
                    "chat_id": cid, 
                    "text": "✏️ <b>Enter:</b> <code>email:password</code>", 
                    "parse_mode": "HTML", 
                    "reply_markup": {"force_reply": True}
                })

            elif data.startswith("acc:del:"):
                email = data.split(":")[2]
                await self.kill_worker(email)
                await self.db.remove_account(email)
                await self.bot.api("answerCallbackQuery", {"callback_query_id": cb["id"], "text": "✅ Deleted!"})
                # Refresh menu recursively
                new_u = u.copy()
                new_u["callback_query"]["data"] = "acc:main"
                await self.handle_callback(new_u)

            # ====================================================
            # 5. PERMISSION MANAGEMENT (Owner Only)
            # ====================================================
            elif data.startswith("perm:sel_usr:"):
                target_id = int(data.split(":")[2])
                user = await self.db.get_user(target_id)
                accounts = await self.db.get_all_accounts()
                
                kb_rows = []
                # Admin Toggle
                is_adm = user.get("is_admin", False)
                adm_text = "🔴 Make Admin" if not is_adm else "🟢 Is Admin (Demote)"
                kb_rows.append([InlineKeyboardButton(text=adm_text, callback_data=f"perm:toggle_admin:{target_id}")])
                
                # Account Toggles
                current_perms = user.get("permissions", [])
                for acc in accounts:
                    has_access = acc["email"] in current_perms
                    icon = "✅" if has_access else "❌"
                    kb_rows.append([InlineKeyboardButton(text=f"{icon} {acc['email']}", callback_data=f"perm:tgl:{target_id}:{acc['email']}")])
                
                kb_rows.append([InlineKeyboardButton(text="🔙 Back", callback_data="usr:main")])
                markup = InlineKeyboardMarkup(inline_keyboard=kb_rows)
                await self.bot.edit_msg(cid, mid, f"🔑 <b>Permissions: {target_id}</b>", reply_markup=markup)

            elif data.startswith("perm:tgl:"):
                parts = data.split(":")
                tid, email = int(parts[2]), parts[3]
                await self.db.toggle_permission(tid, email)
                
                new_u = u.copy()
                new_u["callback_query"]["data"] = f"perm:sel_usr:{tid}"
                await self.handle_callback(new_u)

            elif data.startswith("perm:toggle_admin:"):
                tid = int(data.split(":")[2])
                user = await self.db.get_user(tid)
                curr = user.get("is_admin", False)
                await self.db.set_admin_status(tid, not curr)
                
                new_u = u.copy()
                new_u["callback_query"]["data"] = f"perm:sel_usr:{tid}"
                await self.handle_callback(new_u)

            # Close Handler
            elif data == "menu_close":
                await self.bot.delete_msg(cid, mid)

            await self.bot.api("answerCallbackQuery", {"callback_query_id": cb["id"]})

        except Exception as e:
            logging.error(f"Callback Error: {e}", exc_info=True)
