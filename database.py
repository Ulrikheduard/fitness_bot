import aiosqlite
from datetime import datetime, date
from config import DB_PATH


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # Таблица пользователей
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                name TEXT,
                score INTEGER DEFAULT 10,
                day_off_used INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                last_reset_month INTEGER DEFAULT 0
            )
        """
        )

        # Таблица ежедневных заданий
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                task_date TEXT NOT NULL,
                status TEXT NOT NULL,
                video_file_id TEXT,
                bonus_awarded INTEGER DEFAULT 0,
                bonus_video_file_id TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, task_date),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """
        )

        # Миграция: добавляем недостающие колонки к существующим таблицам
        try:
            # Проверяем наличие колонки day_off_used
            cursor = await db.execute("PRAGMA table_info(users)")
            columns = [row[1] for row in await cursor.fetchall()]

            if "day_off_used" not in columns:
                await db.execute(
                    "ALTER TABLE users ADD COLUMN day_off_used INTEGER DEFAULT 0"
                )
            if "is_active" not in columns:
                await db.execute(
                    "ALTER TABLE users ADD COLUMN is_active INTEGER DEFAULT 1"
                )
            if "last_reset_month" not in columns:
                await db.execute(
                    "ALTER TABLE users ADD COLUMN last_reset_month INTEGER DEFAULT 0"
                )

            # Обновляем существующие записи, устанавливая значения по умолчанию
            await db.execute(
                """
                UPDATE users 
                SET day_off_used = COALESCE(day_off_used, 0),
                    is_active = COALESCE(is_active, 1),
                    last_reset_month = COALESCE(last_reset_month, 0)
                WHERE day_off_used IS NULL OR is_active IS NULL OR last_reset_month IS NULL
            """
            )

        except Exception as e:
            print(f"Предупреждение при миграции базы данных: {e}")

        # Миграция: добавляем недостающие колонки к таблице daily_tasks
        try:
            # Проверяем наличие колонок в daily_tasks
            cursor = await db.execute("PRAGMA table_info(daily_tasks)")
            task_columns = [row[1] for row in await cursor.fetchall()]

            if "bonus_awarded" not in task_columns:
                await db.execute(
                    "ALTER TABLE daily_tasks ADD COLUMN bonus_awarded INTEGER DEFAULT 0"
                )
            if "bonus_video_file_id" not in task_columns:
                await db.execute(
                    "ALTER TABLE daily_tasks ADD COLUMN bonus_video_file_id TEXT"
                )

        except Exception as e:
            print(f"Предупреждение при миграции базы данных: {e}")

        await db.commit()


async def get_or_create_user(user_id, name):
    """Получить пользователя или создать нового"""
    async with aiosqlite.connect(DB_PATH) as db:
        # Получаем описание колонок перед fetchone
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        columns = [desc[0] for desc in cursor.description]
        user = await cursor.fetchone()

        if not user:
            await db.execute(
                "INSERT INTO users (user_id, name, score, day_off_used, is_active) VALUES (?, ?, 10, 0, 1)",
                (user_id, name),
            )
            await db.commit()
            return {
                "user_id": user_id,
                "name": name,
                "score": 10,
                "day_off_used": 0,
                "is_active": 1,
                "last_reset_month": 0,
            }

        # Преобразуем кортеж в словарь
        user_dict = dict(zip(columns, user))

        # Убеждаемся, что все необходимые ключи присутствуют (для совместимости со старыми записями)
        if "day_off_used" not in user_dict:
            user_dict["day_off_used"] = 0
        if "is_active" not in user_dict:
            user_dict["is_active"] = 1
        if "last_reset_month" not in user_dict:
            user_dict["last_reset_month"] = 0

        return user_dict


async def get_user(user_id):
    """Получить пользователя"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        columns = [desc[0] for desc in cursor.description]
        user = await cursor.fetchone()
        if not user:
            return None

        # Преобразуем кортеж в словарь
        user_dict = dict(zip(columns, user))

        # Убеждаемся, что все необходимые ключи присутствуют (для совместимости со старыми записями)
        if "day_off_used" not in user_dict:
            user_dict["day_off_used"] = 0
        if "is_active" not in user_dict:
            user_dict["is_active"] = 1
        if "last_reset_month" not in user_dict:
            user_dict["last_reset_month"] = 0

        return user_dict


async def update_score(user_id, delta):
    """Обновить счет пользователя"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET score = score + ? WHERE user_id = ?", (delta, user_id)
        )
        await db.commit()


async def get_day_off_count(user_id):
    """Получить количество использованных day off"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT day_off_used FROM users WHERE user_id = ?", (user_id,)
        )
        result = await cursor.fetchone()
        return result[0] if result else 0


async def use_day_off(user_id):
    """Использовать day off. Возвращает (success, remaining) или (False, None) если закончились"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT day_off_used FROM users WHERE user_id = ?", (user_id,)
        )
        result = await cursor.fetchone()
        used = result[0] if result else 0

        if used < 3:
            await db.execute(
                "UPDATE users SET day_off_used = day_off_used + 1 WHERE user_id = ?",
                (user_id,),
            )
            await db.commit()
            return (True, 3 - (used + 1))
        return (False, None)


async def mark_task_done(user_id, task_date, video_file_id=None):
    """Отметить задание как выполненное"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO daily_tasks (user_id, task_date, status, video_file_id)
            VALUES (?, ?, 'done', ?)
            ON CONFLICT(user_id, task_date) DO UPDATE SET
                status = 'done',
                video_file_id = excluded.video_file_id
        """,
            (user_id, task_date, video_file_id),
        )
        await db.commit()


async def mark_task_dayoff(user_id, task_date):
    """Отметить задание как day off"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO daily_tasks (user_id, task_date, status, video_file_id, bonus_awarded, bonus_video_file_id)
            VALUES (?, ?, 'dayoff', NULL, 0, NULL)
            ON CONFLICT(user_id, task_date) DO UPDATE SET
                status = 'dayoff',
                video_file_id = NULL,
                bonus_awarded = 0,
                bonus_video_file_id = NULL
        """,
            (user_id, task_date),
        )
        await db.commit()


async def get_task_status(user_id, task_date):
    """Получить статус задания на конкретную дату"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT status FROM daily_tasks WHERE user_id = ? AND task_date = ?",
            (user_id, task_date),
        )
        result = await cursor.fetchone()
        return result[0] if result else None


async def is_bonus_awarded(user_id, task_date):
    """Проверить, получал ли пользователь бонус за день"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT bonus_awarded FROM daily_tasks WHERE user_id = ? AND task_date = ?",
            (user_id, task_date),
        )
        result = await cursor.fetchone()
        return bool(result and result[0])


async def mark_bonus_done(user_id, task_date, video_file_id=None):
    """Отметить бонусное задание как выполненное"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO daily_tasks (user_id, task_date, status, bonus_awarded, bonus_video_file_id)
            VALUES (?, ?, 'done', 1, ?)
            ON CONFLICT(user_id, task_date) DO UPDATE SET
                bonus_awarded = 1,
                bonus_video_file_id = excluded.bonus_video_file_id
        """,
            (user_id, task_date, video_file_id),
        )
        await db.commit()


async def deactivate_user(user_id):
    """Деактивировать пользователя (выбыл из челленджа)"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_active = 0 WHERE user_id = ?", (user_id,))
        await db.commit()


async def reset_monthly_day_off():
    """Сбросить day off для всех активных пользователей в начале месяца"""
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.now()
        current_month = now.month
        current_year = now.year
        # Используем комбинацию года и месяца для более точного отслеживания
        reset_key = current_year * 100 + current_month
        await db.execute(
            """
            UPDATE users 
            SET day_off_used = 0, last_reset_month = ?
            WHERE is_active = 1 AND last_reset_month != ?
        """,
            (reset_key, reset_key),
        )
        await db.commit()


async def get_all_users():
    """Получить всех пользователей отсортированных по рейтингу"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT user_id, name, score, day_off_used, is_active FROM users ORDER BY score DESC"
        )
        return await cursor.fetchall()


async def get_user_stats(user_id, month=None, year=None):
    """Получить статистику пользователя за период"""
    async with aiosqlite.connect(DB_PATH) as db:
        if month and year:
            cursor = await db.execute(
                """
                SELECT COUNT(*) as total, 
                       SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) as done_count,
                       SUM(CASE WHEN status = 'dayoff' THEN 1 ELSE 0 END) as dayoff_count
                FROM daily_tasks 
                WHERE user_id = ? 
                AND strftime('%Y', task_date) = ? 
                AND strftime('%m', task_date) = ?
            """,
                (user_id, str(year), f"{month:02d}"),
            )
        else:
            cursor = await db.execute(
                """
                SELECT COUNT(*) as total, 
                       SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) as done_count,
                       SUM(CASE WHEN status = 'dayoff' THEN 1 ELSE 0 END) as dayoff_count
                FROM daily_tasks 
                WHERE user_id = ?
            """,
                (user_id,),
            )

        result = await cursor.fetchone()
        return {
            "total": result[0] or 0,
            "done": result[1] or 0,
            "dayoff": result[2] or 0,
        }


async def check_weekly_bonus(user_id, week_start_date):
    """Проверить, выполнил ли пользователь все задания за неделю без day off"""
    from datetime import datetime, timedelta

    async with aiosqlite.connect(DB_PATH) as db:
        # Генерируем список всех дат недели (7 дней)
        week_start = datetime.strptime(week_start_date, "%Y-%m-%d").date()
        week_dates = [week_start + timedelta(days=i) for i in range(7)]
        week_dates_str = [d.isoformat() for d in week_dates]

        # Получаем все задания за эту неделю
        cursor = await db.execute(
            """
            SELECT task_date, status 
            FROM daily_tasks 
            WHERE user_id = ? 
            AND task_date >= ? 
            AND task_date < date(?, '+7 days')
            ORDER BY task_date
        """,
            (user_id, week_start_date, week_start_date),
        )
        tasks = await cursor.fetchall()

        # Создаем словарь для быстрого поиска
        tasks_dict = {task_date: status for task_date, status in tasks}

        # Проверяем, что для каждого дня недели есть выполненное задание
        for date_str in week_dates_str:
            if date_str not in tasks_dict:
                # Нет записи за этот день - пропуск
                return False
            if tasks_dict[date_str] != "done":
                # Есть day off или другой статус - не подходит
                return False

        return True


async def award_weekly_bonus(user_id, week_start_date):
    """Начислить недельный бонус пользователю (5 очков за полную неделю)"""
    async with aiosqlite.connect(DB_PATH) as db:
        # Проверяем, не начислялся ли уже бонус за эту неделю
        cursor = await db.execute(
            """
            SELECT COUNT(*) FROM daily_tasks 
            WHERE user_id = ? 
            AND task_date = ? 
            AND status = 'weekly_bonus'
        """,
            (user_id, week_start_date),
        )
        already_awarded = (await cursor.fetchone())[0] > 0

        if already_awarded:
            return False

        # Проверяем выполнение недели
        if await check_weekly_bonus(user_id, week_start_date):
            # Начисляем 5 очков
            await update_score(user_id, 5)

            # Отмечаем, что бонус начислен (сохраняем в daily_tasks для отслеживания)
            await db.execute(
                """
                INSERT INTO daily_tasks (user_id, task_date, status)
                VALUES (?, ?, 'weekly_bonus')
            """,
                (user_id, week_start_date),
            )
            await db.commit()
            return True

        return False


async def process_weekly_bonuses(bot=None, chat_id=None):
    """Обработать недельные бонусы для всех активных пользователей"""
    from datetime import datetime, timedelta

    # Определяем начало прошедшей недели (понедельник)
    # Проверяем в воскресенье, значит неделя была с понедельника по воскресенье
    today = datetime.now().date()
    days_since_monday = today.weekday()  # 0 = понедельник, 6 = воскресенье
    week_start = today - timedelta(days=days_since_monday)
    week_start_str = week_start.isoformat()

    # Получаем всех активных пользователей
    users = await get_all_users()

    awarded_count = 0
    awarded_users = []

    for user_tuple in users:
        user_id = user_tuple[0]
        user_name = user_tuple[1]
        is_active = user_tuple[4] if len(user_tuple) > 4 else 1

        if is_active:
            if await award_weekly_bonus(user_id, week_start_str):
                awarded_count += 1
                awarded_users.append((user_id, user_name))

    # Отправляем уведомления пользователям, если передан bot
    if bot and chat_id and awarded_users:
        try:
            names_list = ", ".join(
                [name for _, name in awarded_users[:5]]
            )  # Первые 5 имен
            if len(awarded_users) > 5:
                names_list += f" и еще {len(awarded_users) - 5}"

            await bot.send_message(
                chat_id=chat_id,
                text=f"🎉 Недельный бонус!\n\n"
                f"Поздравляем участников, которые выполнили все задания на этой неделе без пропусков:\n"
                f"{names_list}\n\n"
                f"Каждый получил +5 💪 бицепсов за полную неделю! 🔥",
            )
        except Exception as e:
            print(f"Ошибка при отправке уведомления о недельном бонусе: {e}")

    return awarded_count


async def reset_all_data():
    """Полностью очистить все данные (пользователи и задания)"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM daily_tasks")
        await db.execute("DELETE FROM users")
        await db.commit()
        return True


async def reset_scores_only():
    """Сбросить только счета и статистику, сохранив пользователей"""
    async with aiosqlite.connect(DB_PATH) as db:
        # Сбрасываем счет всех пользователей на 10
        await db.execute("UPDATE users SET score = 10, day_off_used = 0, is_active = 1")
        # Удаляем все задания
        await db.execute("DELETE FROM daily_tasks")
        await db.commit()
        return True


async def get_users_count():
    """Получить количество пользователей в базе"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM users")
        result = await cursor.fetchone()
        return result[0] if result else 0


async def get_users_without_task_today():
    """Получить список активных пользователей, которые не выполнили основное задание на сегодня"""
    from datetime import date
    
    today = date.today().isoformat()
    
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT u.user_id, u.name
            FROM users u
            WHERE u.is_active = 1
            AND NOT EXISTS (
                SELECT 1 FROM daily_tasks dt
                WHERE dt.user_id = u.user_id
                AND dt.task_date = ?
                AND dt.status = 'done'
            )
            AND NOT EXISTS (
                SELECT 1 FROM daily_tasks dt
                WHERE dt.user_id = u.user_id
                AND dt.task_date = ?
                AND dt.status = 'dayoff'
            )
            ORDER BY u.name
        """,
            (today, today),
        )
        return await cursor.fetchall()


async def auto_apply_dayoff_for_incomplete_tasks():
    """
    Автоматически применяет day off для участников, которые не выполнили основное задание.
    Вызывается в полночь (00:01).
    Если day off закончились, участник выбывает из челленджа.
    """
    from datetime import date
    
    yesterday = (date.today() - __import__('datetime').timedelta(days=1)).isoformat()
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Получаем всех активных пользователей без выполненного задания вчера
        cursor = await db.execute(
            """
            SELECT u.user_id, u.name, u.day_off_used
            FROM users u
            WHERE u.is_active = 1
            AND NOT EXISTS (
                SELECT 1 FROM daily_tasks dt
                WHERE dt.user_id = u.user_id
                AND dt.task_date = ?
                AND dt.status = 'done'
            )
            AND NOT EXISTS (
                SELECT 1 FROM daily_tasks dt
                WHERE dt.user_id = u.user_id
                AND dt.task_date = ?
                AND dt.status = 'dayoff'
            )
            ORDER BY u.name
        """,
            (yesterday, yesterday),
        )
        users_without_task = await cursor.fetchall()
        
        result = {
            "auto_dayoff_applied": [],
            "eliminated": []
        }
        
        for user_id, name, day_off_used in users_without_task:
            if day_off_used < 3:
                # Применяем day off автоматически
                await db.execute(
                    "UPDATE users SET day_off_used = day_off_used + 1 WHERE user_id = ?",
                    (user_id,),
                )
                await db.execute(
                    """
                    INSERT INTO daily_tasks (user_id, task_date, status)
                    VALUES (?, ?, 'dayoff')
                    ON CONFLICT(user_id, task_date) DO UPDATE SET status = 'dayoff'
                """,
                    (user_id, yesterday),
                )
                result["auto_dayoff_applied"].append({
                    "user_id": user_id,
                    "name": name,
                    "remaining": 3 - (day_off_used + 1)
                })
            else:
                # Day off закончились - выбываем
                await db.execute(
                    "UPDATE users SET is_active = 0 WHERE user_id = ?",
                    (user_id,),
                )
                result["eliminated"].append({"user_id": user_id, "name": name})
        
        await db.commit()
        return result