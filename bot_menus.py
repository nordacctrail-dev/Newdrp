from collections import defaultdict
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
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
        visible_emails = await self.get_visible_emails(user_id)
        if not visible_emails:
            await self.bot.edit_msg(cid, mid, "❌ No authorized accounts.")
            return

        kb_rows = []
        is_owner = (user_id == self.cfg.OWNER_ID)
        
        # Branch 1: Unified Options
        kb_rows.append([InlineKeyboardButton(text="📥 Download All (Combined)", callback_data="exp:combined")])
        kb_rows.append([InlineKeyboardButton(text="🌎 By Country", callback_data="exp:ctry_menu")])
        kb_rows.append([InlineKeyboardButton(text="🎯 By Range", callback_data="exp:usr_rng_menu")])
        
        # Branch 2: Account Specific
        if (is_admin or is_owner) and len(visible_emails) > 1:
            for e in sorted(visible_emails):
                alias = self.get_account_alias(e, visible_emails, user_id, is_admin)
                kb_rows.append([InlineKeyboardButton(text=f"📂 {alias}", callback_data=f"exp:acc:{e}")])

        kb_rows.append([InlineKeyboardButton(text="🔙 Close", callback_data="menu_close")])
        
        markup = InlineKeyboardMarkup(inline_keyboard=kb_rows)
        text = "<b>📤 Export Center</b>\nSelect download type:"
        
        if mid: await self.bot.edit_msg(cid, mid, text, reply_markup=markup)
        else: await self.bot.send_to_chat(cid, text, reply_markup=markup)

    # ====================================================
    # 2. VIEW/NAVIGATE MENU TREE
    # ====================================================
    async def show_choose_range_root(self, cid, mid, user_id, is_admin):
        kb_rows = []
        visible_emails = await self.get_visible_emails(user_id)
        is_owner = (user_id == self.cfg.OWNER_ID)

        # Branch 1: Unified Views
        kb_rows.append([InlineKeyboardButton(text="🌎 By Country", callback_data="nav:ctry_menu")])
        kb_rows.append([InlineKeyboardButton(text="🎯 Combined Ranges", callback_data="nav:agg_root")])
        
        # Branch 2: Advanced Account Selection
        if (is_admin or is_owner) and len(visible_emails) > 1:
            kb_rows.append([InlineKeyboardButton(text="✅ Select Accounts", callback_data="nav:checkbox_mode")])
            for e in sorted(visible_emails):
                alias = self.get_account_alias(e, visible_emails, user_id, is_admin)
                kb_rows.append([InlineKeyboardButton(text=f"📂 {alias}", callback_data=f"nav:acc:{e}")])

        kb_rows.append([InlineKeyboardButton(text="🔙 Close", callback_data="menu_close")])
        
        markup = InlineKeyboardMarkup(inline_keyboard=kb_rows)
        text = "<b>🔢 Choose Number</b>\nSelect viewing mode:"
        
        if mid: await self.bot.edit_msg(cid, mid, text, reply_markup=markup)
        else: await self.bot.send_to_chat(cid, text, reply_markup=markup)

    # ====================================================
    # 3. ADD NUMBER MENU (Admin Only)
    # ====================================================
    async def show_add_menu(self, cid, mid, user_id, is_admin=False):
        visible_emails = await self.get_visible_emails(user_id)
        kb_rows = []
        is_owner = (user_id == self.cfg.OWNER_ID)

        # Advanced Selection
        kb_rows.append([InlineKeyboardButton(text="✅ Select Multiple (Checkbox)", callback_data="add:checkbox_mode")])
        
        # Individual Accounts
        for e in sorted(visible_emails):
            alias = self.get_account_alias(e, visible_emails, user_id, is_admin)
            kb_rows.append([InlineKeyboardButton(text=f"📂 {alias}", callback_data=f"add:sel:{e}")])
            
        kb_rows.append([InlineKeyboardButton(text="🔙 Close", callback_data="menu_close")])
        
        markup = InlineKeyboardMarkup(inline_keyboard=kb_rows)
        text = "<b>➕ Add Number</b>\nSelect target account:"
        
        if mid: await self.bot.edit_msg(cid, mid, text, reply_markup=markup)
        else: await self.bot.send_to_chat(cid, text, reply_markup=markup)

    # ====================================================
    # 4. REMOVE NUMBER MENU (Admin Only)
    # ====================================================
    async def show_remove_menu(self, cid, mid, user_id, is_admin=False):
        visible_emails = await self.get_visible_emails(user_id)
        if not visible_emails:
            await self.bot.edit_msg(cid, mid, "❌ No authorized accounts.")
            return

        kb_rows = []
        is_owner = (user_id == self.cfg.OWNER_ID)

        # Unified Actions
        kb_rows.append([InlineKeyboardButton(text="🌎 By Country", callback_data="rm:ctry_menu")])
        
        # Account Specific
        if (is_admin or is_owner) and len(visible_emails) > 1:
             for e in sorted(visible_emails):
                alias = self.get_account_alias(e, visible_emails, user_id, is_admin)
                kb_rows.append([InlineKeyboardButton(text=f"📂 {alias}", callback_data=f"rm:acc_menu:{e}")])

        kb_rows.append([InlineKeyboardButton(text="🔙 Close", callback_data="menu_close")])
        
        markup = InlineKeyboardMarkup(inline_keyboard=kb_rows)
        text = "<b>➖ Remove Numbers</b>\nSelect deletion method:"
        
        if mid: await self.bot.edit_msg(cid, mid, text, reply_markup=markup)
        else: await self.bot.send_to_chat(cid, text, reply_markup=markup)

    # ====================================================
    # 5. COUNTRY SELECTION (Reusable Leaf Node)
    # ====================================================
    async def show_country_selection(self, cid, mid, user_id, mode, is_admin=False):
        perms = []
        if user_id != self.cfg.OWNER_ID:
            u = await self.db.get_user(user_id)
            perms = u.get("permissions", []) if u else []

        countries = self.get_combined_countries(user_id, perms, is_admin)
        
        if not countries:
            await self.bot.edit_msg(cid, mid, "❌ No country data found.")
            return

        kb_rows = []
        for ctry in sorted(countries.keys()):
            count = len(countries[ctry])
            flag = CountryManager.get_flag_by_name(ctry)
            
            if mode == "exp": cb = f"exp:gen_ctry:{ctry}"
            elif mode == "rm": cb = f"rm:exec_ctry:{ctry}"
            else: cb = f"nav:view_ctry:{ctry}:0"
            
            kb_rows.append([InlineKeyboardButton(text=f"{flag} {ctry} ({count})", callback_data=cb)])

        back_map = {"exp": "exp:main_menu", "rm": "rm:main_menu", "nav": "nav:main_root"}
        kb_rows.append([InlineKeyboardButton(text="🔙 Back", callback_data=back_map.get(mode, "menu_close"))])
        
        titles = {
            "exp": "<b>📤 Export by Country</b>",
            "rm": "<b>➖ Remove by Country</b>",
            "nav": "<b>🌎 View by Country</b>"
        }
        
        markup = InlineKeyboardMarkup(inline_keyboard=kb_rows)
        await self.bot.edit_msg(cid, mid, titles.get(mode, "Select:"), reply_markup=markup)

    # ====================================================
    # 6. HELPER: DATA AGGREGATION
    # ====================================================
    def get_combined_countries(self, user_id, permissions, is_admin):
        visible_emails = self.get_visible_emails_sync(user_id, permissions)
        combined = defaultdict(list)
        
        for email in visible_emails:
            w = self.workers.get(email)
            if w:
                for ctry, nums in w.countries.items():
                    combined[ctry].extend(nums)
        return dict(combined)

    def get_visible_emails_sync(self, user_id, permissions):
        if user_id == self.cfg.OWNER_ID:
            return list(self.workers.keys())
        return [e for e in self.workers.keys() if e in permissions]
