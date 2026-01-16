from motor.motor_asyncio import AsyncIOMotorClient

class TradeStateMongoManager:
    def __init__(self, uri="mongodb+srv://Mahdi:Mahdi12345%24@cluster0.bqcuqfl.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0", db_name="trading", collection_name="trade_state"):
        self.client = AsyncIOMotorClient(uri)
        self.collection = self.client[db_name][collection_name]

    async def load_state(self):
        doc = await self.collection.find_one({"_id": "state"})
        if doc:
            return {
                "last_positions": doc.get("last_positions", {}),
                "copied_trades": doc.get("copied_trades", {}),
                "client_positions": doc.get("client_positions", {}),
            }
        return {
            "last_positions": {},
            "copied_trades": {},
            "client_positions": {},
        }

    async def save_state(self, state: dict):
        
        await self.collection.replace_one(
            {"_id": "state"},
            {**state, "_id": "state"},
            upsert=True
        )


print("✅ Connected to MongoDB successfully")
