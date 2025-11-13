import asyncio
from datetime import datetime, timedelta
from config import DAILY_HOUR, DAILY_MINUTE, EVENING_HOUR, EVENING_MINUTE
from keyboards import action_keyboard
from database import reset_monthly_day_off, process_weekly_bonuses, get_users_without_task_today

# Пример набора цитат
QUOTES = [
    "«Если жизнь - это вызов, то я перезвоню» 📞",
    "«Не знаешь, как поступить, поступи как знаешь» 🔥",
    "«Пиво,водка, турничок через часик я качок.» 🏃‍♂️",
    "«Купил фитнес браслет. Теперь знаю, что до пивного ларька 235 шагов»",
    "«Запомните одну фразу ,быстрые ноги-пизды не получат»",
    "«Если тебе где-то не рады в рваных носках, то и в целых туда идти не стоит.»",
    "«Никогда не сдавайтесь, идите к своей цели! А если будет сложно – сдавайтесь.»",
    "«Не важно как тебя зовут, главное, чтобы звали пить пиво!»",
]


async def daily_reminder(bot, chat_id):
    last_reset_month = 0
    last_sent_date = None
    last_weekly_check_day = None

    while True:
        now = datetime.now()
        today = now.date()

        # Проверяем, нужно ли сбросить day off (в первый день месяца)
        current_month_key = now.year * 100 + now.month
        if now.day == 1 and current_month_key != last_reset_month:
            try:
                await reset_monthly_day_off()
                print(
                    f"✅ Day Off сброшены для всех участников (месяц: {now.month}/{now.year})"
                )
                last_reset_month = current_month_key
            except Exception as e:
                print(f"Ошибка при сбросе Day Off: {e}")

        # Проверяем недельные бонусы в воскресенье (день недели 6)
        # Проверяем один раз в день в воскресенье после 10:00
        if (
            now.weekday() == 6
            and (now.hour > 10 or (now.hour == 10 and now.minute >= 0))
            and last_weekly_check_day != today
        ):
            try:
                awarded_count = await process_weekly_bonuses(bot, chat_id)
                if awarded_count > 0:
                    print(
                        f"✅ Начислены недельные бонусы: {awarded_count} участникам получили +5💪 бицепсов"
                    )
                last_weekly_check_day = today
            except Exception as e:
                print(f"Ошибка при обработке недельных бонусов: {e}")

        # Напоминание в установленное время
        target = now.replace(
            hour=DAILY_HOUR, minute=DAILY_MINUTE, second=0, microsecond=0
        )
        if now > target:
            target += timedelta(days=1)

        sleep_seconds = (target - now).total_seconds()
        await asyncio.sleep(sleep_seconds)

        # Проверяем, не отправляли ли уже напоминание сегодня
        current_date = datetime.now().date()
        if last_sent_date != current_date:
            quote = QUOTES[datetime.now().day % len(QUOTES)]
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"<b>🌞 Доброе утро, мужики!</b>\n\nЦитата дня:\n{quote}\n\nПора на тренировку 🥊\n\nОтметь выполнение задания и пришли видео с упражнениями!\n\nНажми на команду /task",
                    reply_markup=None,
                )
                last_sent_date = current_date
            except Exception as e:
                print("Ошибка при отправке сообщения:", e)


async def evening_reminder(bot, chat_id):
    """Отправляет вечернее напоминание в 22:00 о невыполненных заданиях"""
    last_sent_evening = None

    while True:
        now = datetime.now()
        today = now.date()

        # Вычисляем целевое время вечернего напоминания
        target = now.replace(
            hour=EVENING_HOUR, minute=EVENING_MINUTE, second=0, microsecond=0
        )
        if now > target:
            target += timedelta(days=1)

        sleep_seconds = (target - now).total_seconds()
        await asyncio.sleep(sleep_seconds)

        # Проверяем, не отправляли ли уже вечернее напоминание сегодня
        current_date = datetime.now().date()
        if last_sent_evening != current_date:
            try:
                # Получаем список участников без выполненного задания
                users_without_task = await get_users_without_task_today()

                # Если есть участники без выполненного задания, отправляем уведомление
                if users_without_task:
                    names_list = "\n".join(
                        [f"• {name}" for user_id, name in users_without_task]
                    )

                    message_text = (
                        f"<b>🚨 ALARM! Вечернее напоминание!</b>\n\n"
                        f"Сегодня следующие участники ещё не выполнили основное задание:\n\n"
                        f"{names_list}\n\n"
                        f"Пацаны, у вас ещё есть время! Упор лежа принимаем, задание выполняем!🏋🏼‍♀️"
                    )

                    await bot.send_message(chat_id=chat_id, text=message_text)
                    print(
                        f"✅ Вечернее напоминание отправлено. Участников без задания: {len(users_without_task)}"
                    )
                else:
                    print("✅ Все участники выполнили основное задание. Вечернее напоминание не отправлено.")

                last_sent_evening = current_date
            except Exception as e:
                print(f"Ошибка при отправке вечернего напоминания: {e}")


async def nightly_check(bot, chat_id):
    """Выполняет проверку в полночь и применяет день отдыха автоматически"""
    last_check_date = None

    while True:
        now = datetime.now()
        today = now.date()

        # Вычисляем целевое время проверки (00:01)
        target = now.replace(hour=0, minute=1, second=0, microsecond=0)
        if now > target:
            target += timedelta(days=1)

        sleep_seconds = (target - now).total_seconds()
        await asyncio.sleep(sleep_seconds)

        # Проверяем, не проводили ли уже проверку сегодня
        current_date = datetime.now().date()
        if last_check_date != current_date:
            try:
                from database import auto_apply_dayoff_for_incomplete_tasks

                result = await auto_apply_dayoff_for_incomplete_tasks()

                # Отправляем уведомления если что-то произошло
                if result["auto_dayoff_applied"]:
                    names_list = "\n".join(
                        [
                            f"• {item['name']} (осталось Day Off: {item['remaining']}/3)"
                            for item in result["auto_dayoff_applied"]
                        ]
                    )

                    message_text = (
                        f"⚠️ Автоматический Day off\n\n"
                        f"Cледующим участникам автоматически применён day off "
                        f"(они не выполнили задание вчера):\n\n"
                        f"{names_list}\n\n"
                        f"Сегодня им нужно выполнить задание, чтобы продолжить челлендж!"
                    )

                    await bot.send_message(chat_id=chat_id, text=message_text)
                    print(
                        f"✅ Автоматический day off применён для {len(result['auto_dayoff_applied'])} участников"
                    )

                if result["eliminated"]:
                    names_list = "\n".join([f"• {item['name']}" for item in result["eliminated"]])

                    message_text = (
                        f"❌ Участники выбыли из челленджа\n\n"
                        f"Использованы все 3 дня отдыха и не выполнено вчерашнее задание:\n\n"
                        f"{names_list}\n\n"
                        f"Увидимся в следующем месяце! 👋"
                    )

                    await bot.send_message(chat_id=chat_id, text=message_text)
                    print(
                        f"✅ Из челленджа исключены {len(result['eliminated'])} участников"
                    )

                if not result["auto_dayoff_applied"] and not result["eliminated"]:
                    print("✅ Все участники выполнили задание или использовали day off. Проверка завершена.")

                last_check_date = current_date
            except Exception as e:
                print(f"Ошибка при выполнении ночной проверки: {e}")