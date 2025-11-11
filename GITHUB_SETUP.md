# Инструкция по выгрузке на GitHub

## ⚠️ ВАЖНО: Безопасность

Если `config.py` с токеном бота уже был закоммичен ранее, **ОБЯЗАТЕЛЬНО**:
1. Смени токен бота через [@BotFather](https://t.me/BotFather) в Telegram
2. Обнови токен в локальном `config.py`

## Шаги для выгрузки на GitHub

### 1. Создай репозиторий на GitHub

1. Зайди на [github.com](https://github.com)
2. Нажми "New repository" (или "Создать репозиторий")
3. Укажи имя репозитория (например: `telegram_fitness_bot`)
4. Выбери Public или Private
5. **НЕ** создавай README, .gitignore или лицензию (они уже есть)
6. Нажми "Create repository"

### 2. Подключи удаленный репозиторий

Если у тебя еще нет remote или нужно обновить URL:

```bash
# Проверь текущий remote
git remote -v

# Если нужно изменить URL (замени на свой):
git remote set-url origin https://github.com/ТВОЙ_ЮЗЕРНЕЙМ/telegram_fitness_bot.git

# Или если remote нет, добавь:
git remote add origin https://github.com/ТВОЙ_ЮЗЕРНЕЙМ/telegram_fitness_bot.git
```

### 3. Загрузи код на GitHub

```bash
# Отправь код на GitHub
git push -u origin main
```

Если возникнет ошибка про `main` vs `master`, используй:
```bash
git push -u origin main
# или
git branch -M main
git push -u origin main
```

### 4. Проверь результат

Зайди на страницу репозитория на GitHub и убедись, что:
- ✅ Все файлы загружены
- ✅ `config.py` НЕ виден (он в .gitignore)
- ✅ `ratings.db` НЕ виден
- ✅ `config.example.py` есть
- ✅ README.md отображается

## Дальнейшая работа

После первого пуша, для обновления кода:

```bash
git add .
git commit -m "Описание изменений"
git push
```

## Если нужно удалить config.py из истории GitHub

Если ты уже запушил `config.py` с токеном на GitHub:

1. **СРОЧНО смени токен бота** через @BotFather
2. Используй BFG Repo-Cleaner или git filter-branch для удаления из истории
3. Или создай новый репозиторий и загрузи код заново

