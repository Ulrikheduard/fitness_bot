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
)
from keyboards import action_keyboard

# Роутер (подключается в main.py)
router = Router()

# Храним активные запросы на отправку видео
# Формат: {user_id: {"message_id": int, "type": "main"|"bonus"}}
video_prompts: dict[int, dict[str, object]] = {}


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
        "/leaderboard — посмотреть таблицу лидеров\n"
        "/task — получить кнопки для отметки задания\n\n"
        "Каждый день бот будет присылать напоминание с кнопками в 9:00 утра. "
        "Нажми 'Выполнил задачу' и пришли видео с упражнениями для получения бицепсов.\n"
        "После этого можно заработать 🔥 экстра бонус (+1💪), если пришлёшь дополнительное видео.",
        reply_markup=action_keyboard(),
    )


# --- Обработка видеофайлов ---
@router.message(F.video | F.document)
async def handle_video(message: Message):
    """Обработка видеофайлов от участников"""
    user_id = message.from_user.id
    user = await get_user(user_id)

    if not user:
        await message.answer("Сначала используй команду /start")
        return

    if not user["is_active"]:
        await message.answer("Ты выбыл из челленджа. Увидимся в следующем месяце!")
        return

    today = date.today().isoformat()
    task_status = await get_task_status(user_id, today)
    prompt_info = video_prompts.get(user_id)
    expected_type = prompt_info.get("type") if prompt_info else None

    if not prompt_info:
        await message.answer(
            "Сначала воспользуйся кнопками под заданием, чтобы получить запрос на видео."
        )
        return

    if task_status == "dayoff":
        await message.answer("Сегодня выбран Day Off. Видео не требуется.")
        await _delete_prompt_message(message.bot, message.chat.id, prompt_info)
        video_prompts.pop(user_id, None)
        return

    if expected_type == "main" and task_status == "done":
        await message.answer("Основное задание уже отмечено на сегодня! ✅")
        await _delete_prompt_message(message.bot, message.chat.id, prompt_info)
        video_prompts.pop(user_id, None)
        return

    if expected_type == "bonus":
        if task_status != "done":
            await message.answer(
                "Сначала выполни основное задание и пришли видео, затем получи бонус."
            )
            await _delete_prompt_message(message.bot, message.chat.id, prompt_info)
            video_prompts.pop(user_id, None)
            return
        if await is_bonus_awarded(user_id, today):
            await message.answer("Бонус за сегодня уже получен! 🔥")
            await _delete_prompt_message(message.bot, message.chat.id, prompt_info)
            video_prompts.pop(user_id, None)
            return

    if expected_type not in {"main", "bonus"}:
        await message.answer("Не удалось определить тип задания. Нажми кнопку ещё раз.")
        await _delete_prompt_message(message.bot, message.chat.id, prompt_info)
        video_prompts.pop(user_id, None)
        return

    # Получаем file_id видео
    video_file_id = None
    if message.video:
        video_file_id = message.video.file_id
    elif (
        message.document
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
            f"Красавчик, {message.from_user.first_name}! 👏\n"
            f"Видео получено и задание подтверждено. Лови +2💪 бицепса.\n"
            f"Твой рейтинг: {{score}} бицепсов."
        )
    else:  # bonus
        await mark_bonus_done(user_id, today, video_file_id)
        await update_score(user_id, 1)
        response_text = (
            f"🔥 {message.from_user.first_name}, ты машина! Экстра бонус засчитан! Лови +1💪 бицепс.\n"
            f"Твой рейтинг: {{score}} бицепсов."
        )

    await _delete_prompt_message(message.bot, message.chat.id, prompt_info)
    video_prompts.pop(user_id, None)

    updated_user = await get_user(user_id)
    await message.answer(response_text.format(score=updated_user["score"]))


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

    leaderboard_text = "🏆 Таблица лидеров:\n\n"
    for idx, (user_id, name, score, day_off_used, is_active) in enumerate(
        users[:10], 1
    ):
        status_emoji = "✅" if is_active else "❌"
        medal = (
            "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}."
        )
        leaderboard_text += f"{medal} {status_emoji} {name}: {score} бицепсов (Day Off: {day_off_used}/3)\n"

    await message.answer(leaderboard_text)


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
