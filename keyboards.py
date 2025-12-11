from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def action_keyboard():
    """Клавиатура действий участника"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Выполнил задачу", callback_data="done")],
            [InlineKeyboardButton(text="🔥 Экстра бицепс", callback_data="bonus")],
            [InlineKeyboardButton(text="💤 Использую day off", callback_data="dayoff")],
        ]
    )
    return keyboard


def weekly_challenge_keyboard():
    """Клавиатура для выбора еженедельного задания"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🏋🏼‍♀️ Подтягивания (70x)", callback_data="weekly_pullups"
                )
            ],
            [InlineKeyboardButton(text="🚶 Шаги (50k)", callback_data="weekly_steps")],
        ]
    )
    return keyboard


def opponent_selection_keyboard(opponents):
    """Клавиатура для выбора соперника в дуэли"""
    buttons = []
    for user_id, name in opponents:
        buttons.append(
            [InlineKeyboardButton(text=name, callback_data=f"duel_opponent_{user_id}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def second_selection_keyboard(users):
    """Клавиатура для выбора секунданта в дуэли"""
    buttons = []
    for user_id, name in users:
        buttons.append(
            [InlineKeyboardButton(text=name, callback_data=f"duel_second_{user_id}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def duel_result_keyboard(duel_id, challenger_name, opponent_name):
    """Клавиатура для решения результата дуэли (только для секунданта)"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🏆 {challenger_name}",
                    callback_data=f"duel_result_{duel_id}_challenger",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"🏆 {opponent_name}",
                    callback_data=f"duel_result_{duel_id}_opponent",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🤝 Ничья", callback_data=f"duel_result_{duel_id}_draw"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Дуэль не состоялась",
                    callback_data=f"duel_result_{duel_id}_cancelled",
                )
            ],
        ]
    )
    return keyboard
