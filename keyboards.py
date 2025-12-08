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
            [InlineKeyboardButton(text="🏋🏼‍♀️ Подтягивания (70x)", callback_data="weekly_pullups")],
            [InlineKeyboardButton(text="🚶 Шаги (50k)", callback_data="weekly_steps")],
        ]
    )
    return keyboard