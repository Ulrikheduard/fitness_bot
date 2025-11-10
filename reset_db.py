#!/usr/bin/env python3
"""
Скрипт для полной очистки базы данных
Использование: python reset_db.py
"""
import asyncio
import aiosqlite
from config import DB_PATH


async def reset_database():
    """Полностью очистить базу данных"""
    async with aiosqlite.connect(DB_PATH) as db:
        print("🗑️  Очистка базы данных...")

        # Удаляем все данные из таблиц
        await db.execute("DELETE FROM daily_tasks")
        print("✅ Удалены все задания")

        await db.execute("DELETE FROM users")
        print("✅ Удалены все пользователи")

        await db.commit()
        print("\n✅ База данных полностью очищена!")
        print("Бот готов к работе с новыми участниками.")


if __name__ == "__main__":
    print("⚠️  ВНИМАНИЕ: Этот скрипт удалит ВСЕ данные из базы!")
    response = input("Продолжить? (yes/no): ")

    if response.lower() in ["yes", "y", "да", "д"]:
        asyncio.run(reset_database())
    else:
        print("Отменено.")
