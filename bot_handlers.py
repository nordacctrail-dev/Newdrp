import asyncio
import logging
import re
from utils import fmt_num, ExportManager

class HandlerMixin:
    """
    Handles all Telegram updates (Messages, Commands).
    Delegates Callbacks to CallbackMixin.
    """
    
    # State tracking for text inputs
    user_states = {}

    async def handle_update(self, u):
        try:
            # ====================================================
            # 1. CALLBACK QUERY DELEGATION
            # ====================================================
            if "callback_query" in u:
                await self.handle_callback(u)
                return

            # ====================================================
            # 2. MESSAGE HANDLER (Text & Commands)
            # ====================================================
            if "message" in u:
                msg = u["message"]
                cid = msg["chat"]["id"]
                
                # --- FIX: Safe Text Extraction ---
                # If msg["text"] is None (photo/sticker), default to ""
                raw_text = msg.get("text")
                txt = raw_text.strip() if raw_text else ""
                
                user = msg.get("from", {})
                user_id = user.get("id")
                first_name = user.get("first_name", "Unknown")
                username = user.get("username", "")
                reply_to = msg.get("reply_to_message")
                
                # Update Identity
                if txt == "/start":
                    await self.db.update_identity(user_id, first_name, username)

                # --- PERMISSIONS CHECK ---
                is_owner = (user_id == self.cfg.OWNER_ID)
                user_data = await self.db.get_user(user_id)
                
                is_admin = is_owner or (user_data and user_data.get("is_admin", False))
                is_authorized = is_owner or (user_data is not None)

                # Initialize Owner state if missing
                if is_owner and not user_data:
                    user_data = {"permissions": [], "allowed_dids": [], "is_admin": True}

                if not is_authorized and cid > 0:
                     await self.bot.send_to_chat(cid, "⛔ <b>Access Denied</b>\nContact the Administrator.")
                     return

                # ====================================================
                # 🖥️ HYBRID DASHBOARD (THE MAIN MENU)
                # ====================================================
                if txt == "/start" or txt == "/menu" or txt == "🔙 Back to Main Menu":
                    
                    kb = [
                        [{"text": "📋 All Numbers"}, {"text": "🔢 Choose Number"}]
                    ]
                    
                    if is_admin:
                        kb.append([{"text": "➕ Add Number"}, {"text": "➖ Remove Number"}])
                    
                    kb.append([{"text": "📂 Export"}, {"text": "📜 History"}])
                    
                    if is_owner:
                        kb.append([{"text": "🔐 Admin Panel"}])

                    await self.bot.send_to_chat(
                        cid, 
                        "👋 <b>IVASMS Dashboard</b>\nSelect an option below:", 
                        {"keyboard": kb, "resize_keyboard": True}
                    )
                    return

                # ====================================================
                # 🌲 ACTION ROUTING
                # ====================================================

                # --- 🟢 VIEWING ---
                elif txt == "📋 All Numbers":
                    ack = await self.bot.send_to_chat(cid, "🔄 <i>Fetching numbers...</i>")
                    mid = ack["result"]["message_id"]
                    
                    visible_emails = await self.get_visible_emails(user_id)
                    tasks = [self.workers[e].sync_numbers() for e in visible_emails if self.workers.get(e)]
                    if tasks: await asyncio.gather(*tasks)
                    
                    await self.render_global_numbers(cid, mid, 0, user_id, user_data, is_owner)

                elif txt == "🔢 Choose Number":
                    ack = await self.bot.send_to_chat(cid, "🔄 <i>Loading ranges...</i>")
                    mid = ack["result"]["message_id"]
                    
                    visible_emails = await self.get_visible_emails(user_id)
                    tasks = [self.workers[e].sync_numbers() for e in visible_emails if self.workers.get(e)]
                    if tasks: await asyncio.gather(*tasks)

                    await self.show_choose_range_root(cid, mid, user_id, is_admin)

                # --- 🟡 MANAGEMENT ---
                elif txt == "➕ Add Number":
                    if not is_admin: return 
                    visible_emails = await self.get_visible_emails(user_id)
                    
                    if not visible_emails:
                        await self.bot.send_to_chat(cid, "❌ No accounts assigned.")
                        return

                    if len(visible_emails) == 1:
                        email = visible_emails[0]
                        self.user_states[user_id] = {
                            "action": "add_number",
                            "target": [email],
                            "step": "await_name"
                        }
                        await self.bot.send_to_chat(cid, f"📝 <b>Adding to {email}</b>\n\n👇 Enter <b>Termination Name(s)</b>:\n<i>(One per line)</i>\n\nType /cancel to abort.")
                    else:
                        await self.show_add_menu(cid, None, user_id, is_admin)

                elif txt == "➖ Remove Number":
                    if not is_admin: return
                    await self.show_remove_menu(cid, None, user_id, is_admin)

                # --- 🔵 UTILITIES ---
                elif txt == "📂 Export":
                    await self.show_main_export_menu(cid, None, user_id, user_data, is_admin)

                elif txt == "📜 History":
                    visible_emails = await self.get_visible_emails(user_id)
                    history_text = "<b>📜 Recent OTP History</b>\n\n"
                    found_any = False

                    for email in visible_emails:
                        w = self.workers.get(email)
                        if w and hasattr(w, "otp_history") and w.otp_history:
                            alias = self.get_account_alias(email, visible_emails, user_id, is_admin)
                            for otp in w.otp_history[-5:]:
                                found_any = True
                                code = otp.get("otp_code", "---")
                                sender = otp.get("originator", "Service")
                                history_text += f"• <code>{code}</code> | {sender} ({alias})\n"
                            
                    if not found_any: history_text += "<i>No recent OTPs found.</i>"
                    await self.bot.send_to_chat(cid, history_text)

                # --- 🔴 SYSTEM ---
                elif txt == "🔐 Admin Panel":
                    if not is_owner: 
                        await self.bot.send_to_chat(cid, "⛔ <b>Owner Only.</b>")
                        return
                    
                    kb = {
                        "inline_keyboard": [
                            [{"text": "👤 User Settings", "callback_data": "usr:main"}, 
                             {"text": "📧 Account Settings", "callback_data": "acc:main"}], 
                            [{"text": "🔑 Assign Access", "callback_data": "perm:main"}]
                        ]
                    }
                    await self.bot.send_to_chat(cid, "<b>🔐 Owner Control Panel</b>\nManage your team and accounts:", kb)

                # ====================================================
                # 5. INPUT HANDLING (Forms)
                # ====================================================
                elif user_id in self.user_states:
                    await self.handle_state_input(cid, txt, user_id, user_data, is_owner)
                
                # --- Quick Setup Helpers ---
                # Check reply_to first to ensure it exists
                elif reply_to and "text" in reply_to:
                    reply_text = reply_to["text"]
                    
                    if "Enter Telegram User ID" in reply_text:
                        if not is_owner: return
                        try:
                            uid = int(txt)
                            await self.db.add_user(uid)
                            await self.bot.send_to_chat(cid, f"✅ User <code>{uid}</code> Added.")
                        except: await self.bot.send_to_chat(cid, "❌ Invalid ID.")

                    elif "Enter: email:password" in reply_text:
                        if not is_owner: return
                        if ":" in txt:
                            email, pwd = txt.split(":", 1)
                            await self.db.add_account(email.strip(), pwd.strip())
                            await self.spawn_worker(email.strip(), pwd.strip())
                            await self.bot.send_to_chat(cid, f"✅ Account <code>{email.strip()}</code> Started.")
                        else:
                            await self.bot.send_to_chat(cid, "❌ Use: <code>email:password</code>")

        except Exception as e:
            logging.error(f"Handler Error: {e}", exc_info=True)

    # Helper for the Add Number Input Flow
    async def handle_state_input(self, cid, txt, user_id, user_data, is_owner):
        if txt.lower() in ["/cancel", "cancel", "exit"]:
            del self.user_states[user_id]
            await self.bot.send_to_chat(cid, "❌ <b>Operation Cancelled.</b>")
            return

        state = self.user_states[user_id]
        
        if state.get("action") == "add_number":
            step = state.get("step")
            
            if step == "await_name":
                names = [x.strip() for x in txt.split('\n') if x.strip()]
                if not names:
                    await self.bot.send_to_chat(cid, "❌ Invalid input.")
                    return
                
                state["term_names"] = names
                state["step"] = "await_count"
                self.user_states[user_id] = state
                
                preview = "\n".join([f"• {n}" for n in names[:5]])
                await self.bot.send_to_chat(cid, f"📝 <b>Ranges:</b>\n{preview}\n\n🔢 <b>Enter Loop Count (1-50):</b>")
            
            elif step == "await_count":
                if not txt.isdigit():
                    await self.bot.send_to_chat(cid, "❌ Enter a number.")
                    return
                count = int(txt)
                if count > 50: count = 50
                
                targets = state.get("target", [])
                term_names = state.get("term_names", [])
                
                # Note: We need to define execute_add_process or call worker logic here
                # For this snippet, assuming worker.add_numbers is called directly or mapped
                asyncio.create_task(self.execute_add_process(cid, count, term_names, targets))
                del self.user_states[user_id]

    # Added helper to link back to worker logic
    async def execute_add_process(self, cid, count, term_names, targets):
        status_msg = await self.bot.send_to_chat(cid, "⏳ Starting...")
        msg_id = status_msg["result"]["message_id"]
        
        report = []
        for email in targets:
            w = self.workers.get(email)
            if not w:
                report.append(f"❌ {email}: Offline")
                continue
                
            # Define a progress callback for the worker
            async def progress(idx, total, txt):
                if idx % 5 == 0: # Update every 5 items to avoid spam
                    await self.bot.edit_msg(cid, msg_id, f"🔄 {email}: {idx}/{total}\n{txt}")

            # Loop Logic
            total_added = 0
            for i in range(count):
                res = await w.add_numbers(term_names, progress_callback=progress)
                total_added += res['success']
                await asyncio.sleep(1)
            
            report.append(f"✅ {email}: Added {total_added} numbers.")
            
        await self.bot.edit_msg(cid, msg_id, "\n".join(report))
