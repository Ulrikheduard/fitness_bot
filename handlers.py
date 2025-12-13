from typing import Optional

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from datetime import date, datetime, timedelta
from config import ADMIN_IDS, CHAT_ID
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
    get_duels_count_this_week,
    get_available_opponents,
    create_duel,
    get_duel,
    get_pending_duel_for_opponent,
    update_duel_response,
    resolve_duel,
    get_expired_duels,
    get_all_active_users_except,
    get_user_ranking_position,
    get_max_extra_streak,
    get_weekly_tasks_count,
    DB_PATH,
)
import aiosqlite
from keyboards import action_keyboard
from keyboards import weekly_challenge_keyboard
from keyboards import (
    opponent_selection_keyboard,
    second_selection_keyboard,
    duel_result_keyboard,
)
from achievements import (
    award_achievement,
    check_early_bird_achievement,
    check_double_strike_achievement,
    check_extra_human_achievement,
    check_full_set_achievement,
    check_final_boss_achievement,
    get_user_level,
    get_user_achievements,
    LEVEL_NAMES,
    ACHIEVEMENTS,
)

# Роутер (подключается в main.py)
router = Router()

# Храним активные запросы на отправку видео
# Формат: {user_id: {"message_id": int, "type": "main"|"bonus"}}
video_prompts: dict[int, dict[str, object]] = {}
# Глобальный словарь для отслеживания контекста еженедельного челленджа
weekly_prompts: dict[int, dict[str, object]] = {}
# Глобальный словарь для отслеживания состояния дуэли
# Формат: {user_id: {"stage": "opponent"|"second"|"video", "opponent_id": int, "second_id": int, "message_id": int}}
duel_prompts: dict[int, dict[str, object]] = {}


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
        "/duel — вызвать соперника на дуэль (2 раза в неделю)\n"
        "/leaderboard — посмотреть таблицу лидеров\n\n"
        "<b>Основное задание:</b>\n"
        "Каждый день бот будет присылать напоминание с кнопками в 9:00 утра.  "
        "Нажми 'Выполнил задачу' и пришли видео с упражнениями для получения бицепсов.\n"
        "После этого можно заработать 🔥 экстра бонус (+1💪), если пришлёшь дополнительное видео.\n\n"
        "<b>Еженедельный челлендж:</b>\n"
        "Воспользуйся командой /weekly для участия в еженедельном челленже.  "
        "Выбери одно или оба задания и пришли подтверждение выполнения.  "
        "Каждое задание доступно только 1 раз в неделю (до 23:59 в воскресенье).  "
        "За каждое выполненное задание получи +5 баллов.\n\n"
        "<b>Дуэль:</b>\n"
        "Воспользуйся командой /duel для вызова соперника на дуэль.  "
        "Ты можешь вызвать на дуэль 2 раза в неделю.  "
        "Пришли видео с упражнением, соперник должен повторить его.  "
        "У соперника есть 24 часа на ответ.  "
        "Если соперник не успевает, ты получаешь +2 очка, он теряет -2.  "
        "Если ничья (решение секунданта), оба получают +1 очко.",
        parse_mode="HTML",
        reply_markup=action_keyboard(),
    )


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

    # ===== СНАЧАЛА ПРОВЕРЯЕМ ДУЭЛЬ =====
    duel_prompt_info = duel_prompts.get(user_id)
    if duel_prompt_info and duel_prompt_info.get("stage") == "video":
        # Это видео для создания дуэли
        opponent_id = duel_prompt_info.get("opponent_id")
        second_id = duel_prompt_info.get("second_id")

        if not opponent_id or not second_id:
            await message.answer("Ошибка: неверные данные дуэли")
            duel_prompts.pop(user_id, None)
            return

        # Получаем file_id видео/фото
        file_id = None
        if message.video:
            file_id = message.video.file_id
        elif message.photo:
            file_id = message.photo[-1].file_id
        elif (
            message.document
            and message.document.mime_type
            and "video" in message.document.mime_type
        ):
            file_id = message.document.file_id

        if not file_id:
            await message.answer("Пожалуйста, пришли видео или фото упражнений.")
            return

        # Вычисляем время истечения (24 часа от сейчас)
        expires_at = (datetime.now() + timedelta(hours=24)).isoformat()

        try:
            # Создаем дуэль (message_id будет обновлен после отправки сообщения в чат)
            duel_id = await create_duel(
                user_id,
                opponent_id,
                second_id,
                file_id,
                None,  # message_id будет обновлен после отправки сообщения в чат
                expires_at,
            )

            # Получаем информацию о пользователях
            challenger = await get_user(user_id)
            opponent = await get_user(opponent_id)
            second = await get_user(second_id)

            # Форматируем дату истечения
            expires_dt = datetime.fromisoformat(expires_at)
            expires_str = expires_dt.strftime("%d.%m.%Y в %H:%M")

            # Отправляем сообщение с условиями дуэли в общий чат
            try:
                duel_message = await message.bot.send_message(
                    chat_id=CHAT_ID,
                    text=(
                        f"⚔️ <b>ВЫЗОВ НА ДУЭЛЬ!</b>\n\n"
                        f"<b>{challenger['name']}</b> вызывает <b>{opponent['name']}</b> на дуэль!\n\n"
                        f"<b>Секундант:</b> {second['name']}\n\n"
                        f"<b>Условия:</b>\n"
                        f"• Соперник должен повторить упражнение из видео\n"
                        f"• Сделать как минимум такое же количество повторов\n"
                        f"• У соперника есть 24 часа для ответа, до <b>{expires_str}</b>\n\n"
                        f"{opponent['name']}, пришли видео с ответом в ответ на это сообщение!"
                    ),
                    parse_mode="HTML",
                )

                # Обновляем дуэль с message_id сообщения
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        "UPDATE duels SET challenge_message_id = ? WHERE id = ?",
                        (duel_message.message_id, duel_id),
                    )
                    await db.commit()
            except (TelegramForbiddenError, TelegramBadRequest) as e:
                await message.answer(
                    f"❌ Не удалось отправить вызов на дуэль в общий чат.",
                    parse_mode="HTML",
                )
                print(f"Ошибка при отправке вызова на дуэль в чат: {e}")
                duel_prompts.pop(user_id, None)
                return

            # Очищаем промпт
            duel_prompts.pop(user_id, None)

            # Удаляем сообщение с просьбой отправить видео, если оно есть
            await _delete_prompt_message(message.bot, message.chat.id, duel_prompt_info)

        except Exception as e:
            await message.answer(f"Ошибка при создании дуэли: {e}")
            duel_prompts.pop(user_id, None)

        return

    # Проверяем, есть ли активная дуэль, где пользователь является соперником
    pending_duel = await get_pending_duel_for_opponent(user_id)
    if pending_duel:
        # Это ответное видео от соперника
        # Получаем file_id видео/фото
        file_id = None
        if message.video:
            file_id = message.video.file_id
        elif message.photo:
            file_id = message.photo[-1].file_id
        elif (
            message.document
            and message.document.mime_type
            and "video" in message.document.mime_type
        ):
            file_id = message.document.file_id

        if not file_id:
            await message.answer("Пожалуйста, пришли видео или фото упражнений.")
            return

        # Обновляем дуэль с ответным видео
        response_message = await message.answer(
            "✅ Видео получено! Ожидаю решения секунданта...",
            parse_mode="HTML",
        )

        await update_duel_response(
            pending_duel["id"], file_id, response_message.message_id
        )

        # Отправляем сообщение секунданту с кнопками для решения результата в общий чат
        try:
            second_message = await message.bot.send_message(
                chat_id=CHAT_ID,
                text=(
                    f"⚔️ <b>ДУЭЛЬ ГОТОВА К РЕШЕНИЮ</b>\n\n"
                    f"Оба дуэлянта прислали свои видео!\n\n"
                    f"<b>Дуэлянты:</b>\n"
                    f"• {pending_duel['challenger_name']}\n"
                    f"• {pending_duel['opponent_name']}\n\n"
                    f"{pending_duel['second_name']}, определи результат дуэли:"
                ),
                reply_markup=duel_result_keyboard(
                    pending_duel["id"],
                    pending_duel["challenger_name"],
                    pending_duel["opponent_name"],
                ),
                parse_mode="HTML",
            )
        except (TelegramForbiddenError, TelegramBadRequest) as e:
            await message.answer(
                f"⚠️ Не удалось отправить сообщение в общий чат.",
                parse_mode="HTML",
            )
            print(f"Ошибка при отправке сообщения секунданту в чат: {e}")
            return

        # Уведомляем в общий чат о получении ответа
        try:
            await message.bot.send_message(
                chat_id=CHAT_ID,
                text=(
                    f"⚔️ <b>Соперник прислал ответ!</b>\n\n"
                    f"Секундант {pending_duel['second_name']} определяет результат дуэли..."
                ),
                parse_mode="HTML",
            )
        except (TelegramForbiddenError, TelegramBadRequest) as e:
            print(f"Ошибка при отправке уведомления в чат: {e}")

        return

    # ===== СНАЧАЛА ПРОВЕРЯЕМ ЕЖЕНЕДЕЛЬНЫЙ ЧЕЛЛЕНДЖ =====
    weekly_prompt_info = weekly_prompts.get(user_id)
    if weekly_prompt_info:
        task_type = weekly_prompt_info.get("type")
        completed_at = weekly_prompt_info.get("completed_at")
        is_processing = weekly_prompt_info.get("processing")

        # Если уже обрабатываем/закрыли задание — игнорируем дубли
        if is_processing:
            return

        # Если задание уже закрыто и мы всё ещё получаем видео — тихо игнорируем в течение 30 секунд
        if completed_at:
            if datetime.utcnow() - completed_at < timedelta(seconds=30):
                return
            # По истечении грейса очищаем контекст и идём дальше по логике основных заданий
            weekly_prompts.pop(user_id, None)

        elif task_type and task_type in ["pullups", "steps"]:
            # Ставим флаг обработки, чтобы параллельные сообщения не засчитались повторно
            weekly_prompts[user_id] = {
                **weekly_prompt_info,
                "processing": True,
            }

            # Проверяем, не выполнено ли уже это задание НА ЭТОЙ НЕДЕЛЕ
            if await is_weekly_task_completed(user_id, task_type):
                weekly_prompts[user_id] = {
                    **weekly_prompts[user_id],
                    "processing": False,
                    "completed_at": datetime.utcnow(),
                }
                # Молча пропускаем дополнительные видео - не отправляем ошибку
                return

            # Получаем file_id видео/фото
            file_id = None
            if message.video:
                file_id = message.video.file_id
            elif message.photo:
                file_id = message.photo[-1].file_id
            elif (
                message.document
                and message.document.mime_type
                and "video" in message.document.mime_type
            ):
                file_id = message.document.file_id

            if not file_id:
                await message.answer("Пожалуйста, пришли видео или фото упражнений.")
                return

            if not is_week_active():
                await message.answer(
                    "❌ Неделя закончилась! Попробуй на следующей неделе."
                )
                await _delete_prompt_message(
                    message.bot, message.chat.id, weekly_prompt_info
                )
                # Снимаем флаг обработки при ошибке
                weekly_prompts[user_id] = {
                    **weekly_prompts[user_id],
                    "processing": False,
                }
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
                f"🔥 Отлично, {message. from_user.first_name}!\n\n"
                f"<b>{task_emoji} {task_name}</b> выполнены на этой неделе!\n\n"
                f"Ты получил <b>+5💪</b> бицепсов\n"
                f"Твой рейтинг: <b>{new_score}💪</b> бицепсов\n\n"
                f"💡 Напоминаю: каждое из еженедельных заданий можно выполнить только 1 раз в неделю!"
            )

            # Проверяем статус обоих заданий
            status = await get_weekly_challenge_status(user_id)
            if status["pullups_done"] and status["steps_done"]:
                response_text += "\n\n🏅 Бро, я горжусь тобой! Ты выполнил оба задания на этой неделе!"

                # Проверяем "Полный комплект" - 7 дней подряд + 2 еженедельных
                achievement = await check_full_set_achievement(user_id)
                if achievement:
                    await message.bot.send_message(
                        chat_id=CHAT_ID,
                        text=f"🏆 <b>{message.from_user.first_name}</b> получил ачивку: <b>«{achievement['name']}»</b>!",
                        parse_mode="HTML",
                    )

            # Удаляем сообщение с просьбой отправить видео
            await _delete_prompt_message(
                message.bot, message.chat.id, weekly_prompt_info
            )

            # Сохраняем отметку, что задание закрыто, чтобы игнорировать дубли в течение грейса
            weekly_prompts[user_id] = {
                "type": task_type,
                "message_id": weekly_prompt_info.get("message_id"),
                "processing": False,
                "completed_at": datetime.utcnow(),
            }

            await message.answer(response_text, parse_mode="HTML")
            return  # Выходим, чтобы не обрабатывать как основное задание

    # ===== ПОТОМ ПРОВЕРЯЕМ ОСНОВНОЕ ЗАДАНИЕ И БОНУС =====
    today = date.today().isoformat()
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
            await message.answer(
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
        await message.answer(
            "Не удалось определить тип задания.  Нажми кнопку ещё раз."
        )
        await _delete_prompt_message(message.bot, message.chat.id, prompt_info)
        video_prompts.pop(user_id, None)
        return

    # Получаем file_id видео
    video_file_id = None
    if message.video:
        video_file_id = message.video.file_id
    elif message.photo:
        video_file_id = message.photo[-1].file_id
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
            f"Так держать, {message.from_user.first_name}! 👏\n"
            f"Видео получено и задание подтверждено.  Лови +2💪 бицепса.\n"
            f"Твой рейтинг: {{score}} бицепсов."
        )

        # Проверяем ачивки для основного задания
        current_time = datetime.now()

        # Проверяем "Первый пот" - первое выполнение основного задания
        achievement = await award_achievement(user_id, "first_sweat")
        if achievement:
            await message.bot.send_message(
                chat_id=CHAT_ID,
                text=f"🏆 <b>{message.from_user.first_name}</b> получил ачивку: <b>«{achievement['name']}»</b>!",
                parse_mode="HTML",
            )

        # Проверяем "Последний герой" - выполнил в 23:59
        if current_time.hour == 23 and current_time.minute == 59:
            achievement = await award_achievement(user_id, "last_hero")
            if achievement:
                await message.bot.send_message(
                    chat_id=CHAT_ID,
                    text=f"🏆 <b>{message.from_user.first_name}</b> получил ачивку: <b>«{achievement['name']}»</b>!",
                    parse_mode="HTML",
                )

        # Проверяем "Особое приглашение" - выполнил после 22:00
        if current_time.hour >= 22:
            achievement = await award_achievement(user_id, "special_invitation")
            if achievement:
                await message.bot.send_message(
                    chat_id=CHAT_ID,
                    text=f"🏆 <b>{message.from_user.first_name}</b> получил ачивку: <b>«{achievement['name']}»</b>!",
                    parse_mode="HTML",
                )

        # Проверяем "Ранняя пташка" - до 9 утра 3 дня подряд
        achievement = await check_early_bird_achievement(user_id)
        if achievement:
            await message.bot.send_message(
                chat_id=CHAT_ID,
                text=f"🏆 <b>{message.from_user.first_name}</b> получил ачивку: <b>«{achievement['name']}»</b>!",
                parse_mode="HTML",
            )

        # Проверяем "Двойной удар" - основное + экстра 3 дня подряд
        achievement = await check_double_strike_achievement(user_id)
        if achievement:
            await message.bot.send_message(
                chat_id=CHAT_ID,
                text=f"🏆 <b>{message.from_user.first_name}</b> получил ачивку: <b>«{achievement['name']}»</b>!",
                parse_mode="HTML",
            )

        # Проверяем "Финальный босс" - 25 дней подряд
        achievement = await check_final_boss_achievement(user_id)
        if achievement:
            await message.bot.send_message(
                chat_id=CHAT_ID,
                text=f"🏆 <b>{message.from_user.first_name}</b> получил ачивку: <b>«{achievement['name']}»</b>!",
                parse_mode="HTML",
            )
    else:  # bonus
        await mark_bonus_done(user_id, today, video_file_id)
        await update_score(user_id, 1)
        response_text = (
            f"🔥 {message.from_user.first_name}, ты легенда!  Экстра бонус засчитан!  Лови +1💪 бицепс.\n"
            f"Твой рейтинг: {{score}} бицепсов."
        )

        # Проверяем ачивки для экстра задания
        # Проверяем "Экстра-человек" - 7 дней подряд
        achievement = await check_extra_human_achievement(user_id)
        if achievement:
            await message.bot.send_message(
                chat_id=CHAT_ID,
                text=f"🏆 <b>{message.from_user.first_name}</b> получил ачивку: <b>«{achievement['name']}»</b>!",
                parse_mode="HTML",
            )

        # Проверяем "Двойной удар" - основное + экстра 3 дня подряд
        achievement = await check_double_strike_achievement(user_id)
        if achievement:
            await message.bot.send_message(
                chat_id=CHAT_ID,
                text=f"🏆 <b>{message.from_user.first_name}</b> получил ачивку: <b>«{achievement['name']}»</b>!",
                parse_mode="HTML",
            )

        # Проверяем "Полный комплект" - 7 дней подряд + 2 еженедельных
        achievement = await check_full_set_achievement(user_id)
        if achievement:
            await message.bot.send_message(
                chat_id=CHAT_ID,
                text=f"🏆 <b>{message.from_user.first_name}</b> получил ачивку: <b>«{achievement['name']}»</b>!",
                parse_mode="HTML",
            )

        # Проверяем "Финальный босс" - 25 дней подряд
        achievement = await check_final_boss_achievement(user_id)
        if achievement:
            await message.bot.send_message(
                chat_id=CHAT_ID,
                text=f"🏆 <b>{message.from_user.first_name}</b> получил ачивку: <b>«{achievement['name']}»</b>!",
                parse_mode="HTML",
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

    # Получаем все необходимые данные
    stats = await get_user_stats(user_id)
    level = await get_user_level(user_id)
    level_name = LEVEL_NAMES.get(level, f"Уровень {level}")
    ranking_position = await get_user_ranking_position(user_id)
    max_extra_streak = await get_max_extra_streak(user_id)
    weekly_tasks_count = await get_weekly_tasks_count(user_id)
    achievements = await get_user_achievements(user_id)
    achievements_count = len(achievements)
    total_achievements = len(ACHIEVEMENTS)

    # Получаем статистику дуэлей
    duels_won = user.get("duels_won", 0)
    duels_lost = user.get("duels_lost", 0)
    duels_draw = user.get("duels_draw", 0)
    total_duels = duels_won + duels_lost + duels_draw

    # Формируем список ачивок
    achievements_list = (
        "\n".join([f"{name}" for name, code in achievements])
        if achievements
        else "Пока нет ачивок"
    )

    rating_text = (
        f"🙎‍♂️{user['name']}\n\n"
        f"Level: {level} / {level_name}\n"
        f"Текущий счет: {user['score']} 💪\n"
        f"Место в рейтинге: {ranking_position}\n\n"
        f"☑️ Основные: {stats['done']}\n"
        f"⚡️ Экстра: {stats['bonus']}\n"
        f"📅 Еженедельные: {weekly_tasks_count}\n\n"
        f"🔥 Max экстра серия: {max_extra_streak} подряд\n\n"
        f"⚔️ Дуэли: {total_duels} / {duels_won}-{duels_lost}-{duels_draw} (В-П-Н)\n\n"
        f"🎖Ачивки ({achievements_count} из {total_achievements})\n"
        f"{achievements_list}"
    )

    await message.answer(rating_text)


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
    user_id = message.from_user.id
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


@router.callback_query(F.data.in_(["weekly_pullups", "weekly_steps"]))
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
    prompt_message = await callback.message.answer(
        f"{task_emoji} Отлично! Ты выбрал: <b>{task_name}</b>\n\n"
        f"Теперь пришли фото или видео с доказательством выполнения задания.\n"
        f"Можешь отправить несколько файлов подряд - я подожду 📸",
        parse_mode="HTML",
    )

    # Сохраняем контекст для последующей обработки видео
    weekly_prompts[user_id] = {
        "type": task_type,
        "message_id": prompt_message.message_id,
    }
    await callback.answer()


# === ОБРАБОТЧИКИ ДУЭЛЕЙ ===


@router.message(Command("duel"))
async def cmd_duel(message: Message):
    """Команда для начала дуэли"""
    user_id = message.from_user.id
    user = await get_user(user_id)

    if not user:
        await message.answer("Сначала используй команду /start")
        return

    if not user["is_active"]:
        await message.answer("Ты выбыл из челленджа. Увидимся в следующем месяце!")
        return

    if not is_week_active():
        await message.answer(
            "❌ Неделя закончилась! Дуэли доступны только до 23:59 в воскресенье."
        )
        return

    # Проверяем количество дуэлей на этой неделе
    duels_count = await get_duels_count_this_week(user_id)
    if duels_count >= 2:
        await message.answer(
            "❌ Ты уже использовал все 2 дуэли на этой неделе! Попробуй на следующей неделе."
        )
        return

    # Получаем список доступных соперников
    opponents = await get_available_opponents(user_id)
    if not opponents:
        await message.answer(
            "❌ Нет доступных соперников для дуэли. Все участники уже использовали свои 2 дуэли на этой неделе."
        )
        return

    # Используем всех доступных соперников (сообщения будут отправляться в общий чат)
    available_opponents = opponents

    # Удаляем предыдущий промпт дуэли, если был
    previous_prompt = duel_prompts.pop(user_id, None)
    if previous_prompt:
        await _delete_prompt_message(message.bot, message.chat.id, previous_prompt)

    # Отправляем сообщение с условиями и меню выбора соперника
    prompt_message = await message.answer(
        "⚔️ <b>ДУЭЛЬ</b>\n\n"
        "<b>Условия:</b>\n"
        "• Участник может вызвать на дуэль другого участника всего 2 раза за неделю\n"
        "• Вызывающий на дуэль должен прислать видео с упражнением, которое нужно повторить\n"
        "• Соперник должен сделать как минимум такое же количество повторов\n"
        "• У соперника есть 24 часа на выполнение задания\n"
        "• Если соперник не выполняет задание, победитель получает +2💪 бицепса, проигравший -2💪 бицепса\n"
        "• Если ничья, оба получают +1💪 бицепс (решение за секундантом)\n\n"
        "Выбери соперника:",
        reply_markup=opponent_selection_keyboard(available_opponents),
        parse_mode="HTML",
    )

    # Сохраняем состояние дуэли
    duel_prompts[user_id] = {
        "stage": "opponent",
        "message_id": prompt_message.message_id,
    }


@router.callback_query(F.data.startswith("duel_opponent_"))
async def duel_select_opponent(callback: CallbackQuery):
    """Обработка выбора соперника в дуэли"""
    user_id = callback.from_user.id
    opponent_id = int(callback.data.split("_")[-1])

    user = await get_user(user_id)
    if not user or not user["is_active"]:
        await callback.answer(
            "Ошибка: пользователь не найден или неактивен", show_alert=True
        )
        return

    if not is_week_active():
        await callback.answer("❌ Неделя закончилась!", show_alert=True)
        return

    # Проверяем, что это правильный этап
    prompt_info = duel_prompts.get(user_id)
    if not prompt_info or prompt_info.get("stage") != "opponent":
        await callback.answer("Ошибка: неверный этап дуэли", show_alert=True)
        return

    # Получаем список доступных секундантов (все активные пользователи кроме дуэлянтов)
    seconds = await get_all_active_users_except([user_id, opponent_id])
    if not seconds:
        await callback.answer("Нет доступных секундантов", show_alert=True)
        return

    # Обновляем состояние
    duel_prompts[user_id] = {
        "stage": "second",
        "opponent_id": opponent_id,
        "message_id": prompt_info.get("message_id"),
    }

    # Обновляем сообщение с меню выбора секунданта
    try:
        await callback.message.edit_text(
            "⚔️ <b>ДУЭЛЬ</b>\n\n"
            "<b>Условия:</b>\n"
            "• Участник может вызвать на дуэль другого участника всего 2 раза за неделю\n"
            "• Пришли видео с упражнением, которое нужно повторить\n"
            "• Соперник должен сделать как минимум такое же количество повторов\n"
            "• У соперника есть 24 часа на выполнение задания\n"
            "• Если соперник не выполняет задание, победитель получает +2💪 бицепса, проигравший -2💪 бицепса\n"
            "• Если ничья, оба получают +1💪 бицепс (решение за секундантом)\n\n"
            "Выбери секунданта:",
            reply_markup=second_selection_keyboard(seconds),
            parse_mode="HTML",
        )
    except Exception:
        pass

    await callback.answer()


@router.callback_query(F.data.startswith("duel_second_"))
async def duel_select_second(callback: CallbackQuery):
    """Обработка выбора секунданта в дуэли"""
    user_id = callback.from_user.id
    second_id = int(callback.data.split("_")[-1])

    user = await get_user(user_id)
    if not user or not user["is_active"]:
        await callback.answer(
            "Ошибка: пользователь не найден или неактивен", show_alert=True
        )
        return

    if not is_week_active():
        await callback.answer("❌ Неделя закончилась!", show_alert=True)
        return

    # Проверяем, что это правильный этап
    prompt_info = duel_prompts.get(user_id)
    if (
        not prompt_info
        or prompt_info.get("stage") != "second"
        or "opponent_id" not in prompt_info
    ):
        await callback.answer("Ошибка: неверный этап дуэли", show_alert=True)
        return

    opponent_id = prompt_info["opponent_id"]

    # Обновляем состояние
    duel_prompts[user_id] = {
        "stage": "video",
        "opponent_id": opponent_id,
        "second_id": second_id,
        "message_id": prompt_info.get("message_id"),
    }

    # Просим прислать видео
    try:
        await callback.message.edit_text(
            "⚔️ <b>ДУЭЛЬ</b>\n\n"
            "Отлично! Теперь пришли видео с упражнением, которое должен повторить твой соперник.\n"
            "Соперник должен сделать как минимум такое же количество повторов.",
            parse_mode="HTML",
        )
    except Exception:
        pass

    await callback.answer()


@router.callback_query(F.data.startswith("duel_result_"))
async def duel_resolve_result(callback: CallbackQuery):
    """Обработка решения результата дуэли (только для секунданта)"""
    user_id = callback.from_user.id
    parts = callback.data.split("_")
    duel_id = int(parts[2])
    result_type = parts[3]

    # Получаем информацию о дуэли
    duel = await get_duel(duel_id)
    if not duel:
        await callback.answer("Дуэль не найдена", show_alert=True)
        return

    # Проверяем, что это секундант
    if duel["second_id"] != user_id:
        await callback.answer(
            "Только секундант может определить результат дуэли!", show_alert=True
        )
        return

    # Проверяем, что дуэль ожидает результата
    if duel["status"] != "awaiting_result":
        await callback.answer(
            "Дуэль уже завершена или еще не готова к решению", show_alert=True
        )
        return

    # Определяем результат и победителя
    if result_type == "challenger":
        result = f"Победил {challenger}"
        winner_id = duel["challenger_id"]
        await update_score(duel["challenger_id"], 2)
        await update_score(duel["opponent_id"], -2)
    elif result_type == "opponent":
        result = f"Победил {opponent}"
        winner_id = duel["opponent_id"]
        await update_score(duel["challenger_id"], -2)
        await update_score(duel["opponent_id"], 2)
    elif result_type == "draw":
        result = "Ничья"
        winner_id = None
        await update_score(duel["challenger_id"], 1)
        await update_score(duel["opponent_id"], 1)
    elif result_type == "cancelled":
        result = "Отменена"
        winner_id = None
    else:
        await callback.answer("Неверный тип результата", show_alert=True)
        return

    # Завершаем дуэль
    result_message = await callback.message.edit_text(
        f"⚔️ <b>ДУЭЛЬ ЗАВЕРШЕНА</b>\n\n"
        f"Результат: {result in result_type}\n"
        f"Секундант: {duel['second_name']}\n\n"
        f"Дуэлянты:\n"
        f"• {duel['challenger_name']}\n"
        f"• {duel['opponent_name']}",
        parse_mode="HTML",
    )

    await resolve_duel(duel_id, result, winner_id, result_message.message_id)

    # Уведомляем участников дуэли в общий чат
    try:
        challenger = await get_user(duel["challenger_id"])
        opponent = await get_user(duel["opponent_id"])

        if result == "challenger_won":
            result_text = (
                f"🏆 <b>{duel['challenger_name']}</b> победил! Получено 2💪\n"
                f"💔 <b>{duel['opponent_name']}</b> проиграл. Потеряно 2💪"
            )
        elif result == "opponent_won":
            result_text = (
                f"🏆 <b>{duel['opponent_name']}</b> победил! Получено 2💪\n"
                f"💔 <b>{duel['challenger_name']}</b> проиграл. Потеряно 2💪"
            )
        elif result == "draw":
            result_text = (
                f"🤝 Ничья! Оба дуэлянта получили +1💪\n"
                f"• <b>{duel['challenger_name']}</b>: +1💪\n"
                f"• <b>{duel['opponent_name']}</b>: +1💪"
            )
        else:
            result_text = f"❌ Дуэль не состоялась"

        await callback.bot.send_message(
            chat_id=CHAT_ID,
            text=f"⚔️ <b>РЕЗУЛЬТАТ ДУЭЛИ</b>\n\n{result_text}",
            parse_mode="HTML",
        )
    except Exception as e:
        print(f"Ошибка при отправке уведомлений о дуэли: {e}")

    await callback.answer("Результат дуэли сохранен!")
