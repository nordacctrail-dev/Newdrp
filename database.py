import motor.motor_asyncio
import logging
from datetime import datetime
from config import MONGO_URL, DB_NAME

class Database:
    def __init__(self):
        self.client = None
        self.db = None
        self.users = None
        self.accounts = None

    async def connect(self):
        """Establishes connection to MongoDB."""
        try:
            self.client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
            self.db = self.client[DB_NAME]
            self.users = self.db.users
            self.accounts = self.db.accounts
            logging.info("✅ Connected to MongoDB")
        except Exception as e:
            logging.error(f"❌ MongoDB Connection Failed: {e}")

    # ====================================================
    # 👤 USER METHODS
    # ====================================================
    async def get_user(self, chat_id):
        """Fetches a user profile."""
        doc = await self.users.find_one({"_id": chat_id})
        if doc:
            # Normalize data structure to match what the bot expects
            doc['chat_id'] = doc['_id'] # Ensure chat_id key exists
            doc['permissions'] = doc.get('permissions', [])
            doc['allowed_dids'] = doc.get('allowed_dids', [])
            return doc
        return None

    async def add_user(self, chat_id, name="Unknown", is_admin=False, thread_id=None):
        """Adds a new Telegram user (if not exists)."""
        try:
            await self.users.update_one(
                {"_id": chat_id},
                {"$setOnInsert": {
                    "name": name,
                    "is_admin": is_admin,
                    "permissions": [],
                    "allowed_dids": [],
                    "thread_id": thread_id,
                    "joined_at": datetime.now()
                }},
                upsert=True
            )
        except Exception as e:
            logging.error(f"DB Add User Error: {e}")

    async def update_identity(self, chat_id, name, username):
        """Updates name/username on interaction."""
        await self.users.update_one(
            {"_id": chat_id},
            {"$set": {"name": name, "username": username}}
        )

    async def get_all_users(self):
        """Returns list of all users."""
        cursor = self.users.find()
        users = await cursor.to_list(length=None)
        # Map _id back to chat_id for compatibility
        for u in users:
            u['chat_id'] = u['_id']
        return users

    async def remove_user(self, chat_id):
        """Deletes a user."""
        await self.users.delete_one({"_id": chat_id})

    # ====================================================
    # 🔑 PERMISSION METHODS
    # ====================================================
    async def toggle_permission(self, chat_id, email):
        """Grants or Revokes access to a specific email."""
        user = await self.get_user(chat_id)
        if not user: return
        
        perms = user.get('permissions', [])
        
        if email in perms:
            # Revoke (Pull)
            await self.users.update_one(
                {"_id": chat_id},
                {"$pull": {"permissions": email}}
            )
        else:
            # Grant (AddToSet)
            await self.users.update_one(
                {"_id": chat_id},
                {"$addToSet": {"permissions": email}}
            )

    async def set_admin_status(self, chat_id, status: bool):
        """Promotes or Demotes a user."""
        await self.users.update_one(
            {"_id": chat_id},
            {"$set": {"is_admin": status}}
        )

    async def grant_all_emails(self, chat_id):
        """Gives user access to ALL currently saved accounts."""
        # Fetch all emails first
        accts = await self.get_all_accounts()
        all_emails = [a['email'] for a in accts]
        
        await self.users.update_one(
            {"_id": chat_id},
            {"$set": {"permissions": all_emails}}
        )

    async def revoke_all_emails(self, chat_id):
        """Clears all permissions."""
        await self.users.update_one(
            {"_id": chat_id},
            {"$set": {"permissions": []}}
        )

    # ====================================================
    # 📧 ACCOUNT METHODS (IVASMS)
    # ====================================================
    async def add_account(self, email, password):
        """Saves an IVASMS account."""
        await self.accounts.update_one(
            {"_id": email},
            {"$set": {
                "email": email,
                "password": password,
                "updated_at": datetime.now()
            }},
            upsert=True
        )

    async def get_all_accounts(self):
        """Fetches all saved IVASMS accounts."""
        cursor = self.accounts.find()
        accounts = await cursor.to_list(length=None)
        # Ensure email key exists (though _id is email)
        for a in accounts:
            a['email'] = a['_id']
        return accounts

    async def remove_account(self, email):
        """Deletes an IVASMS account."""
        await self.accounts.delete_one({"_id": email})
