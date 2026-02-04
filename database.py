import aiosqlite
import json
import logging
from config import DB_NAME

class Database:
    def __init__(self):
        self.conn = None

    async def connect(self):
        """Establishes connection to the SQLite database."""
        self.conn = await aiosqlite.connect(DB_NAME)
        self.conn.row_factory = aiosqlite.Row
        await self.create_tables()

    async def create_tables(self):
        """Creates Users and Accounts tables."""
        # USERS TABLE: Stores Telegram User info and their permissions
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id INTEGER PRIMARY KEY,
                name TEXT,
                username TEXT,
                is_admin BOOLEAN DEFAULT 0,
                permissions TEXT DEFAULT '[]', -- List of emails this user can access
                allowed_dids TEXT DEFAULT '[]', -- (Optional) Specific numbers
                thread_id INTEGER
            )
        """)
        
        # ACCOUNTS TABLE: Stores IVASMS Login Credentials
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                email TEXT PRIMARY KEY,
                password TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await self.conn.commit()

    # ====================================================
    # 👤 USER METHODS
    # ====================================================
    async def get_user(self, chat_id):
        """Fetches a user profile."""
        async with self.conn.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                d = dict(row)
                # Convert JSON strings back to Python lists
                d['permissions'] = json.loads(d['permissions'])
                d['allowed_dids'] = json.loads(d['allowed_dids'])
                d['is_admin'] = bool(d['is_admin'])
                return d
            return None

    async def add_user(self, chat_id, name="Unknown"):
        """Adds a new Telegram user."""
        try:
            await self.conn.execute(
                "INSERT OR IGNORE INTO users (chat_id, name, is_admin) VALUES (?, ?, 0)",
                (chat_id, name)
            )
            await self.conn.commit()
        except Exception as e:
            logging.error(f"DB Add User Error: {e}")

    async def get_all_users(self):
        """Returns list of all users."""
        async with self.conn.execute("SELECT * FROM users") as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def remove_user(self, chat_id):
        """Deletes a user."""
        await self.conn.execute("DELETE FROM users WHERE chat_id=?", (chat_id,))
        await self.conn.commit()

    # ====================================================
    # 🔑 PERMISSION METHODS
    # ====================================================
    async def toggle_permission(self, chat_id, email):
        """Grants or Revokes access to a specific email."""
        user = await self.get_user(chat_id)
        if not user: return
        
        perms = user['permissions']
        if email in perms:
            perms.remove(email)
        else:
            perms.append(email)
            
        await self.conn.execute("UPDATE users SET permissions=? WHERE chat_id=?", (json.dumps(perms), chat_id))
        await self.conn.commit()

    async def set_admin_status(self, chat_id, status: bool):
        """Promotes or Demotes a user."""
        await self.conn.execute("UPDATE users SET is_admin=? WHERE chat_id=?", (status, chat_id))
        await self.conn.commit()

    # ====================================================
    # 📧 ACCOUNT METHODS (IVASMS)
    # ====================================================
    async def add_account(self, email, password):
        """Saves an IVASMS account."""
        await self.conn.execute("INSERT OR REPLACE INTO accounts (email, password) VALUES (?, ?)", (email, password))
        await self.conn.commit()

    async def get_all_accounts(self):
        """Fetches all saved IVASMS accounts."""
        async with self.conn.execute("SELECT * FROM accounts") as cursor:
            return [dict(r) for r in await cursor.fetchall()]

    async def remove_account(self, email):
        """Deletes an IVASMS account."""
        await self.conn.execute("DELETE FROM accounts WHERE email=?", (email,))
        await self.conn.commit()
