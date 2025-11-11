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
