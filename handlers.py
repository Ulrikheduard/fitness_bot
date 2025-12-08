from typing import Optional

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from datetime import date
from config import ADMIN_IDS
from database import (
    get_or_create_user,
    get_user,
    update_score,
    use_day_off,
    mark_task_done,
    mark_task_dayoff,
    get_task_status,
    deactivate_user,
    get_user_stats,
    get_all_users,
    reset_all_data,
    reset_scores_only,
    get_users_count,
    is_bonus_awarded,
    mark_bonus_done,
    get_weekly_challenge_status,
    mark_weekly_task_done,
    is_weekly_task_completed,
    is_week_active,
    get_current_week_year,
)
from keyboards import action_keyboard
from keyboards import weekly_challenge_keyboard

# Роутер (подключается в main.py)
router = Router()

# Храним активные запросы на отправку видео
# Формат: {user_id: {"message_id": int, "type": "main"|"bonus"}}
video_prompts: dict[int, dict[str, object]] = {}
# Глобальный словарь для отслеживания контекста еженедельного челленджа
weekly_prompts: dict[int, dict[str, object]] = {}


async def _delete_prompt_message(
    bot, chat_id: int, prompt_info: Optional[dict[str, object]]
):
    """Удалить сохранённое сообщение-просьбу, если она существует"""
    if not prompt_info:
        return
    message_id = prompt_info.get("message_id")
    if message_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            pass


# --- Команды /start и /help ---
@router.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    name = message.from_user.first_name or message.from_user.username or "Участник"
    user = await get_or_create_user(user_id, name)

    await message.answer(
        f"Привет, {name}! 👐\n\n"
        "Это твой фитнес бро, который будет следить за твоими достижениями! "
        "Каждый день отмечай выполнение задания и присылай видео с упражнениями.\n\n"
        "За каждый день выполнения ты будешь получать бонусные очки - бицепсы 💪.\n\n"
        "Тебе доступны кнопки:\n"
        "✅ Выполнил задачу — начисляется 2💪 бицепса (обязательно пришли видео, иначе не засчитается)\n"
        "🔥 Экстра бонус — дополнительный 1💪 бицепс (доступно после выполнения основного задания)\n"
        "💤 Использую day off — можно использовать 3 раза в месяц без штрафа\n\n"
        f"Твой стартовый рейтинг — {user['score']} 💪 бицепсов.\n"
        f"Осталось Day Off: {3 - user['day_off_used']} из 3.",
        reply_markup=action_keyboard(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "Команды:\n"
        "/start — начать/перезапустить\n"
        "/help — помощь\n"
        "/rating — посмотреть свой рейтинг\n"
        "/stats — посмотреть статистику\n"
        "/task — получить кнопки для отметки задания\n"
        "/weekly — еженедельный челлендж (70 подтягиваний или 50k шагов за неделю)\n"
        "/leaderboard — посмотреть таблицу лидеров\n\n"
        "<b>Основное задание:</b>\n"
        "Каждый день бот будет присылать напоминание с кнопками в 9:00 утра.  "
        "Нажми 'Выполнил задачу' и пришли видео с упражнениями для получения бицепсов.\n"
        "После этого можно заработать 🔥 экстра бонус (+1💪), если пришлёшь дополнительное видео.\n\n"
        "<b>Еженедельный челлендж:</b>\n"
        "Воспользуйся командой /weekly для участия в еженедельном челленже.  "
        "Выбери одно или оба задания и пришли подтверждение выполнения.  "
        "Каждое задание доступно только 1 раз в неделю (до 23:59 в воскресенье).  "
        "За каждое выполненное задание получи +5 баллов.",
        parse_mode="HTML",
        reply_markup=action_keyboard(),
    )


# --- Обработка видеофайлов ---
# --- Обработка видеофайлов и фото (для основного задания и еженедельного челленджа) ---
@router.message(F.video | F.document | F.photo)
async def handle_all_videos(message: Message):
    """Обработка видеофайлов и фото от участников (основное задание и еженедельный челлендж)"""
    user_id = message.from_user.id
    user = await get_user(user_id)

    if not user:
        await message.answer("Сначала используй команду /start")
        return

    if not user["is_active"]:
        await message.answer("Ты выбыл из челленджа. Увидимся в следующем месяце!")
        return

    # ===== СНАЧАЛА ПРОВЕРЯЕМ ЕЖЕНЕДЕЛЬНЫЙ ЧЕЛЛЕНДЖ =====
    weekly_prompt_info = weekly_prompts.get(user_id)
    if weekly_prompt_info:
        task_type = weekly_prompt_info. get("type")
        if task_type and task_type in ["pullups", "steps"]:
            # Получаем file_id видео/фото
            file_id = None
            if message.video:
                file_id = message.video.file_id
            elif message.photo:
                file_id = message.photo[-1].file_id
            elif (
                message.document
                and message.document.mime_type
                and "video" in message. document.mime_type
            ):
                file_id = message. document.file_id

            if not file_id:
                await message.answer("Пожалуйста, пришли видео или фото упражнений.")
                return

            if not is_week_active():
                await message.answer("❌ Неделя закончилась! Попробуй на следующей неделе.")
                await _delete_prompt_message(message.bot, message.chat.id, weekly_prompt_info)
                weekly_prompts. pop(user_id, None)
                return

            # Проверяем, не выполнено ли уже это задание
            if await is_weekly_task_completed(user_id, task_type):
                task_name = "Подтягивания" if task_type == "pullups" else "Шаги"
                await message.answer(f"✅ {task_name} уже выполнены на этой неделе!")
                await _delete_prompt_message(message. bot, message.chat.id, weekly_prompt_info)
                weekly_prompts.pop(user_id, None)
                return

            # Отмечаем задание как выполненное
            await mark_weekly_task_done(user_id, task_type, file_id)
            await update_score(user_id, 5)

            task_name = "Подтягивания" if task_type == "pullups" else "Шаги"
            task_emoji = "🏋🏼‍♀️" if task_type == "pullups" else "🚶"

            # Получаем обновленный счет пользователя
            updated_user = await get_user(user_id)
            new_score = updated_user["score"]

            response_text = (
                f"🔥 Отлично, {message. from_user.first_name}! {task_emoji}\n"
                f"<b>{task_name}</b> выполнены на этой неделе!\n\n"
                f"Ты получил <b>+5💪 бицепсов</b>\n"
                f"Твой рейтинг: <b>{new_score}</b> бицепсов.\n\n"
                f"💡 Напоминаю: каждое из еженедельных заданий можно выполнить только 1 раз в неделю!"
            )

            # Проверяем статус обоих заданий
            status = await get_weekly_challenge_status(user_id)
            if status["pullups_done"] and status["steps_done"]:
                response_text += "\n\n🏆 СУПЕР! Ты выполнил оба задания на этой неделе!"

            # Удаляем сообщение с просьбой отправить видео
            await _delete_prompt_message(message.bot, message.chat.id, weekly_prompt_info)
            weekly_prompts.pop(user_id, None)

            await message.answer(response_text, parse_mode="HTML")
            return  # Выходим, чтобы не обрабатывать как основное задание

    # ===== ПОТОМ ПРОВЕРЯЕМ ОСНОВНОЕ ЗАДАНИЕ И БОНУС =====
    today = date.today(). isoformat()
    task_status = await get_task_status(user_id, today)
    prompt_info = video_prompts.get(user_id)
    expected_type = prompt_info.get("type") if prompt_info else None

    if not prompt_info:
        # Проверяем, может ли это быть продолжением отправки видео для основного задания
        # Если сегодня уже отмечено основное задание как "done", то просто пропускаем
        if task_status == "done":
            # Молча пропускаем дополнительные видео после успешного выполнения основного задания
            return
        
        await message.answer(
            "Сначала воспользуйся кнопками под заданием, чтобы получить запрос на видео."
        )
        return

    if task_status == "dayoff":
        await message.answer("Сегодня выбран Day Off.  Видео не требуется.")
        await _delete_prompt_message(message.bot, message.chat.id, prompt_info)
        video_prompts.pop(user_id, None)
        return

    if expected_type == "main" and task_status == "done":
        await message.answer("Основное задание уже отмечено на сегодня!  ✅")
        await _delete_prompt_message(message.bot, message.chat.id, prompt_info)
        video_prompts.pop(user_id, None)
        return

    if expected_type == "bonus":
        if task_status != "done":
            await message. answer(
                "Сначала выполни основное задание и пришли видео, затем получи бонус."
            )
            await _delete_prompt_message(message.bot, message.chat.id, prompt_info)
            video_prompts.pop(user_id, None)
            return
        if await is_bonus_awarded(user_id, today):
            await message.answer("Бонус за сегодня уже получен!  🔥")
            await _delete_prompt_message(message.bot, message.chat.id, prompt_info)
            video_prompts.pop(user_id, None)
            return

    if expected_type not in {"main", "bonus"}:
        await message.answer("Не удалось определить тип задания.  Нажми кнопку ещё раз.")
        await _delete_prompt_message(message. bot, message.chat.id, prompt_info)
        video_prompts.pop(user_id, None)
        return

    # Получаем file_id видео
    video_file_id = None
    if message.video:
        video_file_id = message.video.file_id
    elif message.photo:
        video_file_id = message. photo[-1].file_id
    elif (
        message. document
        and message.document.mime_type
        and "video" in message.document.mime_type
    ):
        video_file_id = message.document.file_id

    if not video_file_id:
        await message.answer("Пожалуйста, пришли видеофайл с упражнениями.")
        return

    if expected_type == "main":
        await mark_task_done(user_id, today, video_file_id)
        await update_score(user_id, 2)
        response_text = (
            f"Так держать, {message.from_user.first_name}! 👏\n"
            f"Видео получено и задание подтверждено.  Лови +2💪 бицепса.\n"
            f"Твой рейтинг: {{score}} бицепсов."
        )
    else:  # bonus
        await mark_bonus_done(user_id, today, video_file_id)
        await update_score(user_id, 1)
        response_text = (
            f"🔥 {message.from_user.first_name}, ты легенда!  Экстра бонус засчитан!  Лови +1💪 бицепс.\n"
            f"Твой рейтинг: {{score}} бицепсов."
        )

    await _delete_prompt_message(message. bot, message.chat.id, prompt_info)
    video_prompts.pop(user_id, None)

    updated_user = await get_user(user_id)
    await message.answer(response_text. format(score=updated_user["score"]))



# --- Обработка нажатий кнопок ---
@router.callback_query(F.data == "done")
async def done_challenge(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = await get_user(user_id)

    if not user:
        await callback.answer("Сначала используй команду /start", show_alert=True)
        return

    if not user["is_active"]:
        await callback.answer("Ты выбыл из челленджа", show_alert=True)
        return

    today = date.today().isoformat()
    task_status = await get_task_status(user_id, today)

    # Проверяем, не отметил ли уже сегодня
    if task_status == "done":
        await callback.answer(
            "Ты уже отметил выполнение на сегодня! ✅", show_alert=True
        )
        return

    if task_status == "dayoff":
        await callback.answer("Ты использовал day off на сегодня", show_alert=True)
        return

    # Удаляем старый запрос (если был)
    previous_prompt = video_prompts.pop(user_id, None)
    await _delete_prompt_message(
        callback.bot, callback.message.chat.id, previous_prompt
    )

    # Удаляем старый запрос (если был)
    previous_prompt = video_prompts.pop(user_id, None)
    await _delete_prompt_message(
        callback.bot, callback.message.chat.id, previous_prompt
    )

    # Удаляем сообщение с кнопками
    try:
        await callback.message.delete()
    except Exception:
        pass

    # Просим прислать видео (баллы будут после видео)
    updated_user = await get_user(user_id)
    prompt_message = await callback.message.answer(
        f"Отлично, {callback.from_user.first_name}! 💪\n"
        f"Теперь пришли видео с упражнениями для подтверждения и получения бицепсов.\n"
        f"Твой текущий рейтинг: {updated_user['score']} бицепсов."
    )
    video_prompts[user_id] = {"message_id": prompt_message.message_id, "type": "main"}
    await callback.answer("Пришли видео для подтверждения ✅")


@router.callback_query(F.data == "dayoff")
async def use_dayoff(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = await get_user(user_id)

    if not user:
        await callback.answer("Сначала используй команду /start", show_alert=True)
        return

    if not user["is_active"]:
        await callback.answer("Ты выбыл из челленджа", show_alert=True)
        return

    today = date.today().isoformat()
    task_status = await get_task_status(user_id, today)

    # Проверяем, не отметил ли уже сегодня
    if task_status == "done":
        await callback.answer(
            "Ты уже отметил выполнение на сегодня! ✅", show_alert=True
        )
        return

    if task_status == "dayoff":
        await callback.answer("Ты уже использовал day off на сегодня", show_alert=True)
        return

    # Удаляем сообщение с кнопками
    try:
        await callback.message.delete()
    except Exception:
        pass

    # Пытаемся использовать day off
    success, remaining = await use_day_off(user_id)

    if success:
        await mark_task_dayoff(user_id, today)
        await callback.message.answer(
            f"Ты используешь Day Off 💤\n" f"Осталось: {remaining} из 3."
        )
        await callback.answer("Day Off использован")
    else:
        # Day off закончились - выбывает из челленджа
        await deactivate_user(user_id)
        await callback.message.answer(
            "❌ Ты использовал все 3 Day Off в этом месяце.\n"
            "К сожалению, ты выбываешь из челленджа. Увидимся в следующем месяце! 😔"
        )
        await callback.answer("Выбыл из челленджа", show_alert=True)


# --- Команда /rating ---
@router.message(Command("rating"))
async def show_rating(message: Message):
    user_id = message.from_user.id
    user = await get_user(user_id)

    if not user:
        await message.answer("Ты ещё не участвовал в челлендже. Используй /start")
        return

    stats = await get_user_stats(user_id)
    status_text = "✅ Активен" if user["is_active"] else "❌ Выбыл"

    await message.answer(
        f"🏆 Твой рейтинг: {user['score']} бицепсов\n"
        f"💤 Использовано Day Off: {user['day_off_used']} из 3\n"
        f"📊 Статистика:\n"
        f"   Выполнено заданий: {stats['done']}\n"
        f"   Экстра бонусы: {stats['bonus']}\n"
        f"   Использовано Day Off: {stats['dayoff']}\n"
        f"   Всего дней: {stats['total']}\n"
        f"Статус: {status_text}"
    )


# --- Команда /stats ---
@router.message(Command("stats"))
async def show_stats(message: Message):
    user_id = message.from_user.id
    user = await get_user(user_id)

    if not user:
        await message.answer("Ты ещё не участвовал в челлендже. Используй /start")
        return

    from datetime import datetime

    now = datetime.now()
    stats_month = await get_user_stats(user_id, now.month, now.year)

    await message.answer(
        f"📊 Статистика за текущий месяц:\n\n"
        f"✅ Выполнено заданий: {stats_month['done']}\n"
        f"🔥 Экстра бонусы: {stats_month['bonus']}\n"
        f"💤 Использовано Day Off: {stats_month['dayoff']}\n"
        f"📈 Всего дней: {stats_month['total']}\n\n"
        f"🏆 Текущий рейтинг: {user['score']} бицепсов\n"
        f"💤 Осталось Day Off: {3 - user['day_off_used']} из 3"
    )


# --- Команда /task ---
@router.message(Command("task"))
async def show_task_buttons(message: Message):
    """Получить кнопки для отметки задания в любое время"""
    user_id = message.from_user.id
    user = await get_user(user_id)

    if not user:
        await message.answer(
            "Сначала используй команду /start", reply_markup=action_keyboard()
        )
        return

    if not user["is_active"]:
        await message.answer("Ты выбыл из челленджа. Увидимся в следующем месяце!")
        return

    from datetime import date

    today = date.today().isoformat()
    from database import get_task_status

    task_status = await get_task_status(user_id, today)

    status_text = ""
    if task_status == "done":
        status_text = "\n✅ Ты уже отметил выполнение задания на сегодня!"
    elif task_status == "dayoff":
        status_text = "\n💤 Ты использовал day off на сегодня."

    await message.answer(
        f"📋 Отметка задания на сегодня\n\n"
        f"Выбери действие:\n"
        f"✅ Выполнил задачу — нажми кнопку и пришли видео\n"
        f"🔥 Экстра бонус — дополнительный +1💪 после основного задания\n"
        f"💤 Использую day off — использовать день отдыха\n\n"
        f"Осталось Day Off: {3 - user['day_off_used']} из 3.{status_text}",
        reply_markup=action_keyboard(),
    )


# --- Команда /leaderboard ---
@router.message(Command("leaderboard"))
async def show_leaderboard(message: Message):
    users = await get_all_users()

    if not users:
        await message.answer("Пока нет участников в рейтинге.")
        return

    leaderboard_text = "🏆 <b>Таблица лидеров:</b>\n\n"
    for idx, (user_id, name, score, day_off_used, is_active) in enumerate(
        users[:10], 1
    ):
        status_emoji = "✅" if is_active else "❌"
        medal = (
            "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}."
        )
        leaderboard_text += (
            f"{medal} {name}: {score} бицепсов\n<i>Day Off: {day_off_used}/3</i>\n"
        )

    await message.answer(leaderboard_text, parse_mode="HTML")


# --- Административные команды ---
def is_admin(user_id):
    """Проверить, является ли пользователь администратором"""
    return ADMIN_IDS and user_id in ADMIN_IDS


@router.message(Command("reset"))
async def cmd_reset(message: Message):
    """Сбросить все данные (только для администратора)"""
    user_id = message.from_user.id

    if not is_admin(user_id):
        await message.answer("❌ Эта команда доступна только администратору.")
        return

    # Проверяем, есть ли подтверждение
    command_parts = message.text.split()
    if len(command_parts) < 2 or command_parts[1] != "confirm":
        users_count = await get_users_count()
        await message.answer(
            f"⚠️ ВНИМАНИЕ! Эта команда удалит ВСЕ данные:\n"
            f"- Всех пользователей ({users_count})\n"
            f"- Все задания\n"
            f"- Всю статистику\n\n"
            f"Для подтверждения отправь: /reset confirm\n\n"
            f"Или используй /reset_scores для сброса только счетов (пользователи останутся)"
        )
        return

    try:
        await reset_all_data()
        await message.answer(
            "✅ Все данные успешно удалены!\n"
            "База данных очищена. Бот готов к работе с новыми участниками."
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка при сбросе данных: {e}")


@router.message(Command("reset_scores"))
async def cmd_reset_scores(message: Message):
    """Сбросить только счета, сохранив пользователей (только для администратора)"""
    user_id = message.from_user.id

    if not is_admin(user_id):
        await message.answer("❌ Эта команда доступна только администратору.")
        return

    # Проверяем, есть ли подтверждение
    command_parts = message.text.split()
    if len(command_parts) < 2 or command_parts[1] != "confirm":
        users_count = await get_users_count()
        await message.answer(
            f"⚠️ Эта команда сбросит:\n"
            f"- Все счета на 10 баллов\n"
            f"- Все Day Off на 0\n"
            f"- Все задания\n\n"
            f"Пользователи ({users_count}) останутся в базе.\n\n"
            f"Для подтверждения отправь: /reset_scores confirm"
        )
        return

    try:
        await reset_scores_only()
        users_count = await get_users_count()
        await message.answer(
            f"✅ Счета успешно сброшены!\n"
            f"Все {users_count} пользователей получили стартовый рейтинг 10 баллов.\n"
            f"Все задания удалены."
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка при сбросе счетов: {e}")


@router.callback_query(F.data == "bonus")
async def handle_bonus(callback: CallbackQuery):
    """Обработка бонусного задания"""
    user_id = callback.from_user.id
    user = await get_user(user_id)

    if not user:
        await callback.answer("Сначала используй команду /start", show_alert=True)
        return

    if not user["is_active"]:
        await callback.answer("Ты выбыл из челленджа", show_alert=True)
        return

    today = date.today().isoformat()
    task_status = await get_task_status(user_id, today)

    if task_status != "done":
        await callback.answer(
            "Сначала выполни основное задание и пришли видео, затем получи бонус.",
            show_alert=True,
        )
        return

    if await is_bonus_awarded(user_id, today):
        await callback.answer("Бонус за сегодня уже получен! 🔥", show_alert=True)
        return

    existing_prompt = video_prompts.get(user_id)
    if existing_prompt and existing_prompt.get("type") == "main":
        await callback.answer(
            "Сначала пришли видео по основному заданию, потом берись за бонус!",
            show_alert=True,
        )
        return

    # Удаляем предыдущие запросы
    previous_prompt = video_prompts.pop(user_id, None)
    await _delete_prompt_message(
        callback.bot, callback.message.chat.id, previous_prompt
    )

    # Удаляем сообщение с кнопками
    try:
        await callback.message.delete()
    except Exception:
        pass

    prompt_message = await callback.message.answer(
        f"🔥 Экстра бонус активирован, {callback.from_user.first_name}! \n"
        "Пришли видео подтверждение, чтобы получить ещё +1💪 бицепс."
    )
    video_prompts[user_id] = {"message_id": prompt_message.message_id, "type": "bonus"}
    await callback.answer("Пришли бонусное видео ✅")

# Обработчики еженедельного челленджа
@router.message(Command("weekly"))
async def weekly_challenge_command(message: Message):
    """Команда для запуска еженедельного челленджа"""
    user_id = message.from_user. id
    user = await get_user(user_id)

    if not user:
        await message.answer("Сначала используй команду /start")
        return

    if not user["is_active"]:
        await message.answer("Ты выбыл из челленджа.  Увидимся в следующем месяце!")
        return

    if not is_week_active():
        await message.answer(
            "❌ Неделя закончилась! Еженедельный челлендж доступен только до 23:59 в воскресенье."
        )
        return

    await message.answer(
        "🏅 <b>ЕЖЕНЕДЕЛЬНЫЕ БИЦЕПСЫ</b>\n\n"
        "Выбери одно или оба задания:\n\n"
        "<b>🏋🏼‍♀️ Подтягивания</b>: 70 повторений за неделю\n"
        "<b>🚶 Шаги</b>: 50 000 шагов за неделю\n\n"
        "За каждое выполненное задание ты получишь <b>+5💪 бицепсов</b>\n"
        "Каждое задание можно выполнить только <b>1 раз в неделю</b>!\n\n"
        "Выбери задание:",
        reply_markup=weekly_challenge_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data. in_(["weekly_pullups", "weekly_steps"]))
async def weekly_challenge_select(callback: CallbackQuery):
    """Обработка выбора типа еженедельного задания"""
    user_id = callback.from_user.id
    task_type = "pullups" if callback.data == "weekly_pullups" else "steps"

    user = await get_user(user_id)
    if not user:
        await callback.answer("Ошибка: пользователь не найден", show_alert=True)
        return

    if not user["is_active"]:
        await callback.answer("Ты выбыл из челленджа!", show_alert=True)
        return

    if not is_week_active():
        await callback.answer(
            "❌ Неделя закончилась! Попробуй на следующей неделе.", show_alert=True
        )
        return

    # Проверяем, выполнено ли уже это задание на этой неделе
    if await is_weekly_task_completed(user_id, task_type):
        task_name = "Подтягивания" if task_type == "pullups" else "Шаги"
        await callback.answer(
            f"✅ {task_name} уже выполнены на этой неделе!", show_alert=True
        )
        return

    # Удаляем старый запрос (если был)
    previous_prompt = weekly_prompts.pop(user_id, None)
    await _delete_prompt_message(
        callback.bot, callback.message.chat.id, previous_prompt
    )

    # Удаляем сообщение с кнопками
    try:
        await callback.message.delete()
    except Exception:
        pass

    task_name = "подтягивания (70x)" if task_type == "pullups" else "шаги (50k)"
    task_emoji = "🏋🏼‍♀️" if task_type == "pullups" else "🚶"

    # Просим прислать видео/фото
    prompt_message = await callback.message. answer(
        f"{task_emoji} Отлично! Ты выбрал: <b>{task_name}</b>\n\n"
        f"Теперь пришли фото или видео с доказательством выполнения задания.\n"
        f"Можешь отправить несколько файлов подряд - я подожду 📸",
        parse_mode="HTML"
    )

    # Сохраняем контекст для последующей обработки видео
    weekly_prompts[user_id] = {
        "type": task_type,
        "message_id": prompt_message.message_id,
    }
    await callback.answer()
