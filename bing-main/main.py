# import asyncio
# from trade_manager import TradeManager

# async def main():
#     manager = TradeManager()
#     await manager.load_state()

#     try:
#         # ✅ הרצת סנכרון עסקאות
#         await manager.sync_trades()

#         # ✅ אם יש פונקציה נוספת שאתה רוצה להריץ ברקע:  
#         # asyncio.create_task(manager.refresh_leverage_cache())
#     except Exception as e:
#         print(f"❌ קרתה שגיאה במהלך הריצה: {e}")
#     finally:
#         await manager.close()  # סגירה מסודרת של session

# if __name__ == "__main__":
#     asyncio.run(main())
