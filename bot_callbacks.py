import logging
import asyncio
from utils import ExportManager, CountryManager

class CallbackMixin:
    """
    Handles all Inline Button clicks.
    """

    # Tracks checkbox selections for multi-account actions
    selection_state = {} 

    async def handle_callback(self, u):
        try:
            cb = u["callback_query"]
            cid = cb["message"]["chat"]["id"]
            data = cb["data"]
            mid = cb["message"]["message_id"]
            user_id = cb["from"]["id"]
            
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
                # Download ALL numbers available to this user
                await self.bot.edit_msg(cid, mid, "🔄 <i>Preparing file...</i>")
                visible_emails = await self.get_visible_emails(user_id)
                
                # Gather data from all workers
                all_nums = []
                for e in visible_emails:
                    w = self.workers.get(e)
                    if w:
                        # Ensure data is fresh
                        if not w.all_numbers: await w.sync_numbers()
                        all_nums.extend(w.all_numbers)
                
                if not all_nums:
                    await self.bot.edit_msg(cid, mid, "❌ No numbers found.")
                else:
                    path = ExportManager.generate(all_nums, "All_Numbers")
                    await self.bot.send_file(cid, path, f"<b>📤 Export Ready</b>\nCount: {len(all_nums)}")
                    await self.bot.delete_msg(cid, mid)

            elif data == "exp:ctry_menu":
                await self.show_country_selection(cid, mid, user_id, "exp", is_admin)

            elif data.startswith("exp:gen_ctry:"):
                ctry = data.split(":", 2)[2]
                await self.bot.edit_msg(cid, mid, f"⏳ <i>Exporting {ctry}...</i>")
                
                # Filter by country across all allowed accounts
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
                # Pagination for Country View
                parts = data.split(":")
                ctry = parts[2]
                page = int(parts[3])
                
                perms = [] if is_owner else user_data.get("permissions", [])
                countries = self.get_combined_countries(user_id, perms, is_admin)
                nums = countries.get(ctry, [])
                
                total_p = (len(nums) + 19) // 20
                chunk = nums[page*20 : (page+1)*20]
                
                text = f"🌎 <b>{ctry}</b> (Page {page+1}/{total_p})\n" + "\n".join([f"• <code>{n}</code>" for n in chunk])
                
                # Navigation Buttons
                btns = []
                nav_row = []
                if page > 0: nav_row.append({"text": "⬅️", "callback_data": f"nav:view_ctry:{ctry}:{page-1}"})
                if page < total_p - 1: nav_row.append({"text": "➡️", "callback_data": f"nav:view_ctry:{ctry}:{page+1}"})
                if nav_row: btns.append(nav_row)
                btns.append([{"text": "🔙 Back", "callback_data": "nav:ctry_menu"}])
                
                await self.bot.edit_msg(cid, mid, text, {"inline_keyboard": btns})

            # ====================================================
            # 3. ADD NUMBER SETUP (Select Account)
            # ====================================================
            elif data.startswith("add:sel:"):
                # User selected a specific account folder -> Start Input
                email = data.split(":")[2]
                from bot_handlers import HandlerMixin
                # Inject state into HandlerMixin
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
                # List users to manage
                users = await self.db.get_all_users()
                kb = []
                for u in users:
                    if u['chat_id'] == self.cfg.OWNER_ID: continue
                    kb.append([{"text": f"👤 {u.get('name','User')} ({u['chat_id']})", "callback_data": f"perm:sel_usr:{u['chat_id']}"}])
                
                kb.append([{"text": "➕ Add User by ID", "callback_data": "usr:add"}])
                kb.append([{"text": "🔙 Close", "callback_data": "menu_close"}])
                await self.bot.edit_msg(cid, mid, "<b>👤 User Management</b>\nSelect user to edit:", {"inline_keyboard": kb})

            elif data == "usr:add":
                await self.bot.api("sendMessage", {"chat_id": cid, "text": "✏️ <b>Enter Telegram User ID:</b>", "reply_markup": {"force_reply": True}})

            elif data == "acc:main":
                # List accounts to delete
                accounts = await self.db.get_all_accounts()
                kb = [[{"text": f"🗑 {a['email']}", "callback_data": f"acc:del:{a['email']}"}] for a in accounts]
                kb.append([{"text": "➕ Add Account", "callback_data": "acc:add"}])
                kb.append([{"text": "🔙 Close", "callback_data": "menu_close"}])
                await self.bot.edit_msg(cid, mid, "<b>📧 Account Settings</b>\nClick to delete:", {"inline_keyboard": kb})

            elif data == "acc:add":
                await self.bot.api("sendMessage", {"chat_id": cid, "text": "✏️ <b>Enter:</b> <code>email:password</code>", "parse_mode": "HTML", "reply_markup": {"force_reply": True}})

            elif data.startswith("acc:del:"):
                email = data.split(":")[2]
                await self.kill_worker(email)
                await self.db.remove_account(email)
                await self.bot.api("answerCallbackQuery", {"callback_query_id": cb["id"], "text": "✅ Deleted!"})
                # Refresh menu
                await self.handle_callback({**u, "callback_query": {**cb, "data": "acc:main"}})

            # ====================================================
            # 5. PERMISSION MANAGEMENT (Owner Only)
            # ====================================================
            elif data.startswith("perm:sel_usr:"):
                # Show permissions for a specific user
                target_id = int(data.split(":")[2])
                user = await self.db.get_user(target_id)
                accounts = await self.db.get_all_accounts()
                
                kb = []
                # Admin Toggle
                is_adm = user.get("is_admin", False)
                adm_text = "🔴 Make Admin" if not is_adm else "🟢 Is Admin (Demote)"
                kb.append([{"text": adm_text, "callback_data": f"perm:toggle_admin:{target_id}"}])
                
                # Account Toggles
                current_perms = user.get("permissions", [])
                for acc in accounts:
                    has_access = acc["email"] in current_perms
                    icon = "✅" if has_access else "❌"
                    kb.append([{"text": f"{icon} {acc['email']}", "callback_data": f"perm:tgl:{target_id}:{acc['email']}"}])
                
                kb.append([{"text": "🔙 Back", "callback_data": "usr:main"}])
                await self.bot.edit_msg(cid, mid, f"🔑 <b>Permissions: {target_id}</b>", {"inline_keyboard": kb})

            elif data.startswith("perm:tgl:"):
                parts = data.split(":")
                tid, email = int(parts[2]), parts[3]
                await self.db.toggle_permission(tid, email)
                # Refresh UI
                await self.handle_callback({**u, "callback_query": {**cb, "data": f"perm:sel_usr:{tid}"}})

            elif data.startswith("perm:toggle_admin:"):
                tid = int(data.split(":")[2])
                user = await self.db.get_user(tid)
                curr = user.get("is_admin", False)
                await self.db.set_admin_status(tid, not curr)
                # Refresh UI
                await self.handle_callback({**u, "callback_query": {**cb, "data": f"perm:sel_usr:{tid}"}})

            # Close Handler
            elif data == "menu_close":
                await self.bot.delete_msg(cid, mid)

            # Always answer the callback to stop the loading animation
            await self.bot.api("answerCallbackQuery", {"callback_query_id": cb["id"]})

        except Exception as e:
            logging.error(f"Callback Error: {e}", exc_info=True)
