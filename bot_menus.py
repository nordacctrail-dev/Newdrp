from collections import defaultdict
from utils import CountryManager

class MenuMixin:
    """
    Generates Inline Keyboards (The "Tree" Structure).
    Mixes into the main Bot class.
    """

    # ====================================================
    # 1. EXPORT MENU TREE
    # ====================================================
    async def show_main_export_menu(self, cid, mid, user_id, user_data, is_admin):
        """
        Shows options: Download All, By Country, or By Account.
        """
        visible_emails = await self.get_visible_emails(user_id)
        if not visible_emails:
            await self.bot.edit_msg(cid, mid, "❌ No authorized accounts.")
            return

        kb = []
        is_owner = (user_id == self.cfg.OWNER_ID)
        
        # Branch 1: Unified Options (Simple for everyone)
        kb.append([{"text": "📥 Download All (Combined)", "callback_data": "exp:combined"}])
        kb.append([{"text": "🌎 By Country", "callback_data": "exp:ctry_menu"}])
        kb.append([{"text": "🎯 By Range", "callback_data": "exp:usr_rng_menu"}])
        
        # Branch 2: Account Specific (Only if >1 account AND (Admin or Owner))
        # Regular users with >1 account usually just want the Combined view.
        if (is_admin or is_owner) and len(visible_emails) > 1:
            for e in sorted(visible_emails):
                alias = self.get_account_alias(e, visible_emails, user_id, is_admin)
                kb.append([{"text": f"📂 {alias}", "callback_data": f"exp:acc:{e}"}])

        kb.append([{"text": "🔙 Close", "callback_data": "menu_close"}])
        
        text = "<b>📤 Export Center</b>\nSelect download type:"
        if mid: await self.bot.edit_msg(cid, mid, text, {"inline_keyboard": kb})
        else: await self.bot.send_to_chat(cid, text, {"inline_keyboard": kb})

    # ====================================================
    # 2. VIEW/NAVIGATE MENU TREE
    # ====================================================
    async def show_choose_range_root(self, cid, mid, user_id, is_admin):
        """
        Root menu for 'Choose Number'.
        """
        kb = []
        visible_emails = await self.get_visible_emails(user_id)
        is_owner = (user_id == self.cfg.OWNER_ID)

        # Branch 1: Unified Views
        kb.append([{"text": "🌎 By Country", "callback_data": "nav:ctry_menu"}])
        kb.append([{"text": "🎯 Combined Ranges", "callback_data": "nav:agg_root"}])
        
        # Branch 2: Advanced Account Selection (Owner/Admin with >1 Account)
        if (is_admin or is_owner) and len(visible_emails) > 1:
            kb.append([{"text": "✅ Select Accounts", "callback_data": "nav:checkbox_mode"}])
            for e in sorted(visible_emails):
                alias = self.get_account_alias(e, visible_emails, user_id, is_admin)
                kb.append([{"text": f"📂 {alias}", "callback_data": f"nav:acc:{e}"}])

        kb.append([{"text": "🔙 Close", "callback_data": "menu_close"}])
        
        text = "<b>🔢 Choose Number</b>\nSelect viewing mode:"
        if mid: await self.bot.edit_msg(cid, mid, text, {"inline_keyboard": kb})
        else: await self.bot.send_to_chat(cid, text, {"inline_keyboard": kb})

    # ====================================================
    # 3. ADD NUMBER MENU (Admin Only)
    # ====================================================
    async def show_add_menu(self, cid, mid, user_id, is_admin=False):
        """
        Shows list of accounts to add numbers to.
        """
        visible_emails = await self.get_visible_emails(user_id)
        kb = []
        is_owner = (user_id == self.cfg.OWNER_ID)

        # Advanced Selection for multiple accounts
        kb.append([{"text": "✅ Select Multiple (Checkbox)", "callback_data": "add:checkbox_mode"}])
        
        # Individual Accounts
        for e in sorted(visible_emails):
            alias = self.get_account_alias(e, visible_emails, user_id, is_admin)
            kb.append([{"text": f"📂 {alias}", "callback_data": f"add:sel:{e}"}])
            
        kb.append([{"text": "🔙 Close", "callback_data": "menu_close"}])
        
        text = "<b>➕ Add Number</b>\nSelect target account:"
        if mid: await self.bot.edit_msg(cid, mid, text, {"inline_keyboard": kb})
        else: await self.bot.send_to_chat(cid, text, {"inline_keyboard": kb})

    # ====================================================
    # 4. REMOVE NUMBER MENU (Admin Only)
    # ====================================================
    async def show_remove_menu(self, cid, mid, user_id, is_admin=False):
        """
        Shows options to remove numbers.
        """
        visible_emails = await self.get_visible_emails(user_id)
        if not visible_emails:
            await self.bot.edit_msg(cid, mid, "❌ No authorized accounts.")
            return

        kb = []
        is_owner = (user_id == self.cfg.OWNER_ID)

        # Unified Actions
        kb.append([{"text": "🌎 By Country", "callback_data": "rm:ctry_menu"}])
        
        # Account Specific (If multiple)
        if (is_admin or is_owner) and len(visible_emails) > 1:
             for e in sorted(visible_emails):
                alias = self.get_account_alias(e, visible_emails, user_id, is_admin)
                kb.append([{"text": f"📂 {alias}", "callback_data": f"rm:acc_menu:{e}"}])

        kb.append([{"text": "🔙 Close", "callback_data": "menu_close"}])
        
        text = "<b>➖ Remove Numbers</b>\nSelect deletion method:"
        if mid: await self.bot.edit_msg(cid, mid, text, {"inline_keyboard": kb})
        else: await self.bot.send_to_chat(cid, text, {"inline_keyboard": kb})

    # ====================================================
    # 5. COUNTRY SELECTION (Reusable Leaf Node)
    # ====================================================
    async def show_country_selection(self, cid, mid, user_id, mode, is_admin=False):
        """
        Generates a list of countries based on the user's viewable numbers.
        Used by Export, View, and Remove menus.
        """
        perms = []
        if user_id != self.cfg.OWNER_ID:
            u = await self.db.get_user(user_id)
            perms = u.get("permissions", []) if u else []

        # Aggregate countries from all allowed workers
        countries = self.get_combined_countries(user_id, perms, is_admin)
        
        if not countries:
            await self.bot.edit_msg(cid, mid, "❌ No country data found.")
            return

        kb = []
        # Dynamic Callback generation based on mode
        for ctry in sorted(countries.keys()):
            count = len(countries[ctry])
            flag = CountryManager.get_flag_by_name(ctry)
            
            if mode == "exp": cb = f"exp:gen_ctry:{ctry}"
            elif mode == "rm": cb = f"rm:exec_ctry:{ctry}"
            else: cb = f"nav:view_ctry:{ctry}:0"
            
            kb.append([{"text": f"{flag} {ctry} ({count})", "callback_data": cb}])

        # Smart Back Button
        back_map = {"exp": "exp:main_menu", "rm": "rm:main_menu", "nav": "nav:main_root"}
        kb.append([{"text": "🔙 Back", "callback_data": back_map.get(mode, "menu_close")}])
        
        titles = {
            "exp": "<b>📤 Export by Country</b>",
            "rm": "<b>➖ Remove by Country</b>",
            "nav": "<b>🌎 View by Country</b>"
        }
        await self.bot.edit_msg(cid, mid, titles.get(mode, "Select:"), {"inline_keyboard": kb})

    # ====================================================
    # 6. HELPER: DATA AGGREGATION
    # ====================================================
    def get_combined_countries(self, user_id, permissions, is_admin):
        """
        Scans all workers assigned to this user and groups numbers by Country.
        """
        visible_emails = self.get_visible_emails_sync(user_id, permissions)
        combined = defaultdict(list)
        
        for email in visible_emails:
            w = self.workers.get(email)
            if w:
                for ctry, nums in w.countries.items():
                    combined[ctry].extend(nums)
        return dict(combined)

    def get_visible_emails_sync(self, user_id, permissions):
        """Synchronous version for internal helpers."""
        if user_id == self.cfg.OWNER_ID:
            return list(self.workers.keys())
        return [e for e in self.workers.keys() if e in permissions]
