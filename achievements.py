# Функции для работы с ачивками и уровнями
import aiosqlite
from datetime import datetime, date, timedelta
from config import DB_PATH
from database import get_current_week_year

LEVEL_NAMES = {
    1: "Стажер по полу",
    2: "Полуотжиматель",
    3: "Размявшийся тип",
    4: "Локтевой технарь",
    5: "Уверенный отжиматор",
    6: "Рабочая лошадка",
    7: "Мастер поверхностного контакта",
    8: "Гранд-мастер",
    9: "Легенда местного пола",
}

ACHIEVEMENTS = {
    "first_sweat": {
        "name": "Первый пот",
        "description": "Первое выполнение основного задания",
    },
    "early_bird": {
        "name": "Ранняя пташка",
        "description": "Выполнил основные задания до 9 утра 3 дня подряд",
    },
    "double_strike": {
        "name": "Двойной удар",
        "description": "Выполнил и основное и экстра задание 3 дня подряд",
    },
    "extra_human": {
        "name": "Экстра-человек",
        "description": "Выполнил экстра задание 7 дней подряд",
    },
    "full_set": {
        "name": "Полный комплект",
        "description": "7 дней подряд сделал основные и экстра задания, и выполнил 2 еженедельных задания",
    },
    "final_boss": {
        "name": "Финальный босс",
        "description": "Выполнил все основные задания + экстра задания 25 дней подряд",
    },
    "last_hero": {
        "name": "Последний герой",
        "description": "Выполнил основное задание в 23:59",
    },
    "special_invitation": {
        "name": "Особое приглашение",
        "description": "Выполнил задание после вечернего уведомления (22:00)",
    },
}


async def init_achievements():
    """Инициализировать ачивки в базе данных"""
    async with aiosqlite.connect(DB_PATH) as db:
        for code, data in ACHIEVEMENTS.items():
            await db.execute(
                """
                INSERT OR IGNORE INTO achievements (code, name, description)
                VALUES (?, ?, ?)
                """,
                (code, data["name"], data["description"]),
            )
        await db.commit()


async def get_user_achievements_count(user_id):
    """Получить количество ачивок пользователя"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM user_achievements WHERE user_id = ?",
            (user_id,),
        )
        result = await cursor.fetchone()
        return result[0] if result else 0


async def get_user_achievements(user_id):
    """Получить список ачивок пользователя"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT a.name, a.code
            FROM user_achievements ua
            JOIN achievements a ON ua.achievement_id = a.id
            WHERE ua.user_id = ?
            ORDER BY ua.earned_at ASC
            """,
            (user_id,),
        )
        return await cursor.fetchall()


async def get_user_level(user_id):
    """Получить уровень пользователя (на основе количества ачивок)"""
    achievements_count = await get_user_achievements_count(user_id)
    # Уровень = количество ачивок + 1 (0 ачивок = 1 уровень, 1 ачивка = 2 уровень и т.д.)
    level = min(achievements_count + 1, 9)  # Максимум 9 уровень
    return level


async def update_user_level(user_id):
    """Обновить уровень пользователя на основе количества ачивок"""
    level = await get_user_level(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET level = ? WHERE user_id = ?",
            (level, user_id),
        )
        await db.commit()
    return level


async def has_achievement(user_id, achievement_code):
    """Проверить, есть ли у пользователя ачивка"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT COUNT(*) FROM user_achievements ua
            JOIN achievements a ON ua.achievement_id = a.id
            WHERE ua.user_id = ? AND a.code = ?
            """,
            (user_id, achievement_code),
        )
        result = await cursor.fetchone()
        return (result[0] if result else 0) > 0


async def award_achievement(user_id, achievement_code):
    """Выдать ачивку пользователю"""
    if await has_achievement(user_id, achievement_code):
        return None  # Ачивка уже есть

    async with aiosqlite.connect(DB_PATH) as db:
        # Получаем ID ачивки
        cursor = await db.execute(
            "SELECT id FROM achievements WHERE code = ?",
            (achievement_code,),
        )
        achievement = await cursor.fetchone()
        if not achievement:
            return None

        achievement_id = achievement[0]

        # Выдаем ачивку
        await db.execute(
            """
            INSERT INTO user_achievements (user_id, achievement_id)
            VALUES (?, ?)
            """,
            (user_id, achievement_id),
        )
        await db.commit()

        # Обновляем уровень пользователя
        new_level = await update_user_level(user_id)

        # Получаем информацию об ачивке
        achievement_info = ACHIEVEMENTS.get(achievement_code)
        return {
            "code": achievement_code,
            "name": achievement_info["name"] if achievement_info else achievement_code,
            "new_level": new_level,
        }


async def check_early_bird_achievement(user_id):
    """Проверить ачивку 'Ранняя пташка' - выполнил основные задания до 9 утра 3 дня подряд"""
    async with aiosqlite.connect(DB_PATH) as db:
        # Проверяем последние 3 дня
        today = date.today()
        consecutive_days = 0

        for i in range(3):
            check_date = (today - timedelta(days=i)).isoformat()
            cursor = await db.execute(
                """
                SELECT created_at FROM daily_tasks
                WHERE user_id = ? AND task_date = ? AND status = 'done'
                """,
                (user_id, check_date),
            )
            task = await cursor.fetchone()
            if task:
                # Проверяем время выполнения (до 9:00)
                created_at = datetime.fromisoformat(task[0])
                if created_at.hour < 9:
                    consecutive_days += 1
                else:
                    break
            else:
                break

        if consecutive_days >= 3:
            return await award_achievement(user_id, "early_bird")
    return None


async def check_double_strike_achievement(user_id):
    """Проверить ачивку 'Двойной удар' - выполнил и основное и экстра задание 3 дня подряд"""
    async with aiosqlite.connect(DB_PATH) as db:
        today = date.today()
        consecutive_days = 0

        for i in range(3):
            check_date = (today - timedelta(days=i)).isoformat()
            cursor = await db.execute(
                """
                SELECT status, bonus_awarded FROM daily_tasks
                WHERE user_id = ? AND task_date = ?
                """,
                (user_id, check_date),
            )
            task = await cursor.fetchone()
            if task and task[0] == "done" and task[1] == 1:
                consecutive_days += 1
            else:
                break

        if consecutive_days >= 3:
            return await award_achievement(user_id, "double_strike")
    return None


async def check_extra_human_achievement(user_id):
    """Проверить ачивку 'Экстра-человек' - выполнил экстра задание 7 дней подряд"""
    async with aiosqlite.connect(DB_PATH) as db:
        today = date.today()
        consecutive_days = 0

        for i in range(7):
            check_date = (today - timedelta(days=i)).isoformat()
            cursor = await db.execute(
                """
                SELECT bonus_awarded FROM daily_tasks
                WHERE user_id = ? AND task_date = ?
                """,
                (user_id, check_date),
            )
            task = await cursor.fetchone()
            if task and task[0] == 1:
                consecutive_days += 1
            else:
                break

        if consecutive_days >= 7:
            return await award_achievement(user_id, "extra_human")
    return None


async def check_full_set_achievement(user_id):
    """Проверить ачивку 'Полный комплект' - 7 дней подряд сделал основные и экстра задания, и выполнил 2 еженедельных задания"""
    async with aiosqlite.connect(DB_PATH) as db:
        today = date.today()
        consecutive_days = 0

        # Проверяем 7 дней подряд
        for i in range(7):
            check_date = (today - timedelta(days=i)).isoformat()
            cursor = await db.execute(
                """
                SELECT status, bonus_awarded FROM daily_tasks
                WHERE user_id = ? AND task_date = ?
                """,
                (user_id, check_date),
            )
            task = await cursor.fetchone()
            if task and task[0] == "done" and task[1] == 1:
                consecutive_days += 1
            else:
                break

        if consecutive_days >= 7:
            # Проверяем еженедельные задания
            week_year = get_current_week_year()
            cursor = await db.execute(
                """
                SELECT pullups_done, steps_done FROM weekly_tasks
                WHERE user_id = ? AND week_year = ?
                """,
                (user_id, week_year),
            )
            weekly = await cursor.fetchone()
            if weekly and weekly[0] == 1 and weekly[1] == 1:
                return await award_achievement(user_id, "full_set")
    return None


async def check_final_boss_achievement(user_id):
    """Проверить ачивку 'Финальный босс' - выполнил все основные задания + экстра задания 25 дней подряд"""
    async with aiosqlite.connect(DB_PATH) as db:
        today = date.today()
        consecutive_days = 0

        for i in range(25):
            check_date = (today - timedelta(days=i)).isoformat()
            cursor = await db.execute(
                """
                SELECT status, bonus_awarded FROM daily_tasks
                WHERE user_id = ? AND task_date = ?
                """,
                (user_id, check_date),
            )
            task = await cursor.fetchone()
            if task and task[0] == "done" and task[1] == 1:
                consecutive_days += 1
            else:
                break

        if consecutive_days >= 25:
            return await award_achievement(user_id, "final_boss")
    return None
