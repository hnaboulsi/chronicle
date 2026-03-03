from database import SessionLocal
import agent_logic, main
db = SessionLocal()
import asyncio
print(asyncio.run(main.analytics_today(db)))
