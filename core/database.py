import motor.motor_asyncio
import asyncio
from datetime import datetime
import config
from utils import log

class Database:
    def __init__(self):
        self.client = motor.motor_asyncio.AsyncIOMotorClient(config.MONGO_URL)
        self.db = self.client[config.DB_NAME]  # Ensure DB_NAME is in config.py
        
        # Collections
        self.users = self.db["users"]          # Telegram Users & Permissions
        self.accounts = self.db["accounts"]    # Email Accounts (Workers)
        self.hot_numbers = self.db["hot_numbers"] # Scanner Results

    async def init_db(self):
        """Initialize indexes for performance."""
        try:
            # Users: Index by chat_id
            await self.users.create_index("chat_id", unique=True)
            
            # Accounts: Index by email
            await self.accounts.create_index("email", unique=True)
            
            # Hot Numbers: Index by termination_id and expire after 24h
            await self.hot_numbers.create_index("termination_id", unique=True)
            await self.hot_numbers.create_index("last_seen", expireAfterSeconds=86400)
            
            log("✅ MongoDB Connected & Indexes Set", "OK")
        except Exception as e:
            log(f"❌ MongoDB Init Error: {e}", "ERROR")

    # ===================== USER MANAGEMENT =====================

    async def get_user(self, chat_id: int):
        return await self.users.find_one({"chat_id": chat_id})

    async def get_all_users(self):
        cursor = self.users.find({})
        return await cursor.to_list(length=None)

    async def add_user(self, chat_id: int, name: str, is_admin: bool = False, thread_id: int = None):
        user = {
            "chat_id": chat_id,
            "name": name,
            "is_admin": is_admin,
            "permissions": [],
            "joined_at": datetime.utcnow()
        }
        if thread_id:
            user["thread_id"] = thread_id
            
        await self.users.update_one(
            {"chat_id": chat_id},
            {"$setOnInsert": user},
            upsert=True
        )

    async def update_identity(self, chat_id: int, first_name: str, username: str):
        """Updates display name/username on /start"""
        name = f"{first_name} (@{username})" if username else first_name
        await self.users.update_one(
            {"chat_id": chat_id},
            {"$set": {"name": name}}
        )

    async def remove_user(self, chat_id: int):
        await self.users.delete_one({"chat_id": chat_id})

    async def set_admin_status(self, chat_id: int, status: bool):
        await self.users.update_one(
            {"chat_id": chat_id},
            {"$set": {"is_admin": status}}
        )

    # ===================== PERMISSIONS SYSTEM =====================

    async def toggle_permission(self, chat_id: int, email: str):
        user = await self.get_user(chat_id)
        if not user: return
        
        perms = user.get("permissions", [])
        if email in perms:
            await self.users.update_one({"chat_id": chat_id}, {"$pull": {"permissions": email}})
        else:
            await self.users.update_one({"chat_id": chat_id}, {"$addToSet": {"permissions": email}})

    async def grant_all_emails(self, chat_id: int):
        # Fetch all known accounts
        accounts = await self.get_all_accounts()
        emails = [a["email"] for a in accounts]
        await self.users.update_one({"chat_id": chat_id}, {"$set": {"permissions": emails}})

    async def revoke_all_emails(self, chat_id: int):
        await self.users.update_one({"chat_id": chat_id}, {"$set": {"permissions": []}})

    # ===================== ACCOUNT MANAGEMENT =====================

    async def get_all_accounts(self):
        cursor = self.accounts.find({})
        return await cursor.to_list(length=None)

    async def add_account(self, email: str):
        await self.accounts.update_one(
            {"email": email},
            {"$set": {"email": email, "added_at": datetime.utcnow()}},
            upsert=True
        )

    async def remove_account(self, email: str):
        # 1. Remove account doc
        await self.accounts.delete_one({"email": email})
        # 2. Remove permission from all users
        await self.users.update_many({}, {"$pull": {"permissions": email}})

    # ===================== SCANNER / HOT NUMBERS =====================

    async def record_scanner_hit(self, term_id, name, service):
        """Upsert scanner hit."""
        if not term_id or not name: return
        try:
            await self.hot_numbers.update_one(
                {"termination_id": term_id},
                {
                    "$set": {
                        "termination_name": name,
                        "service": service,
                        "last_seen": datetime.utcnow()
                    },
                    "$inc": {"hit_count": 1}
                },
                upsert=True
            )
        except Exception as e:
            log(f"DB Write Error: {e}", "ERROR")

    async def get_top_10(self):
        cursor = self.hot_numbers.find().sort("hit_count", -1).limit(10)
        return await cursor.to_list(length=10)

    async def get_categories(self):
        return await self.hot_numbers.distinct("service")

    async def get_ranges_by_category(self, service):
        cursor = self.hot_numbers.find({"service": service}).sort("hit_count", -1).limit(20)
        return await cursor.to_list(length=20)

    async def get_services_by_names(self, names_list):
        """Map Range Name -> Service"""
        if not names_list: return {}
        cursor = self.hot_numbers.find(
            {"termination_name": {"$in": names_list}},
            {"termination_name": 1, "service": 1}
        )
        result = {}
        async for doc in cursor:
            result[doc["termination_name"]] = doc.get("service", "Unknown")
        return result

# Global Instance
db = Database()
