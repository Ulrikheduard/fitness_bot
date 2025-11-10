from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def action_keyboard():
    """Клавиатура с двумя кнопками: Выполнил задачу и Использую day off"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Выполнил задачу", callback_data="done")],
            [InlineKeyboardButton(text="💤 Использую day off", callback_data="dayoff")],
        ]
    )
    return keyboard
