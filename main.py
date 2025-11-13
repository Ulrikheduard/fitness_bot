import asyncio
from aiogram import Bot, Dispatcher
from config import BOT_TOKEN
from database import init_db
from handlers import router
from scheduler import daily_reminder, evening_reminder, nightly_check

# ID чата для ежедневных напоминаний
CHAT_ID = -1003381403522  # <-- вставь ID вашего чата (через @userinfobot можно узнать)


async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    await init_db()
    print("✅ Бот запущен")

    # Запуск рассылки
    asyncio.create_task(daily_reminder(bot, CHAT_ID))
    asyncio.create_task(evening_reminder(bot, CHAT_ID))
    asyncio.create_task(nightly_check(bot, CHAT_ID))

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
