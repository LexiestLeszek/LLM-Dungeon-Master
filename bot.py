import logging
import sqlite3
import json
import os
import random
import re
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import pyttsx3
from together import Together

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация клиента Together AI
together_client = Together(api_key=os.environ.get("TOGETHER_API_KEY", "your_api_key_here"))

# Функция для вызова LLM как предоставлено
def ask_llm(prompt, system_prompt):
    response = together_client.chat.completions.create(
        model="deepseek-ai/DeepSeek-V3",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        temperature=1.1
    )
    return response.choices[0].message.content

# Системный промпт для Мастера Подземелий
DM_SYSTEM_PROMPT = """
Ты опытный и творческий Мастер Подземелий для игры Dungeons & Dragons. Твоя роль — создавать увлекательные приключения, рассказывать захватывающие истории и обеспечивать погружение в мир ролевой игры. Следуй этим рекомендациям:

1. ПОВЕСТВОВАНИЕ: Создавай яркие описания окружения, персонажей и событий. Формируй богатый, правдоподобный мир.
2. УПРАВЛЕНИЕ ПРАВИЛАМИ: Применяй правила D&D 5e честно и последовательно. Обрабатывай броски кубиков (например, "Бросаю d20..." или "{1d20+5}") и объясняй результаты.
3. ОТЫГРЫШ НИП: Наделяй каждого неигрового персонажа особой индивидуальностью, голосом и мотивацией.
4. ТЕМП: Уравновешивай бои, исследования и социальные взаимодействия. Поддерживай движение приключения вперед.
5. АДАПТИВНОСТЬ: Значимо реагируй на выбор игроков. Их решения должны влиять на мир.
6. БРОСКИ КУБИКОВ: Когда действия требуют элемента случайности, указывай, какие кубики бросать (например, "Брось d20 + твой модификатор Силы для этой проверки Атлетики").
7. УПРАВЛЕНИЕ БОЕМ: Отслеживай инициативу, характеристики монстров и ход боя. Представляй тактические ситуации, бросающие вызов игрокам.
8. ПОСЛЕДОВАТЕЛЬНОСТЬ ТОНА: Поддерживай установленный тон кампании (героический, мрачный, комедийный и т.д.).

Ты можешь бросать кубики, записывая выражения как {1d20} или {2d6+3}. Всегда используй этот формат для бросков кубиков.

Никогда не контролируй персонажей игроков и не принимай решения за них. Спрашивай игроков, что они хотят делать, и уважай их выбор.

Помни: Твоя цель — создавать веселые, запоминающиеся впечатления для игроков, а не "побеждать" их.
"""

# Настройка базы данных
def setup_database():
    """Создать схему базы данных SQLite, если она не существует"""
    conn = sqlite3.connect('dnd_bot.db')
    cursor = conn.cursor()
    
    # Создать таблицу для игровых сессий
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS game_sessions (
        session_id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_active BOOLEAN DEFAULT TRUE,
        campaign_name TEXT,
        campaign_type TEXT,
        setting_description TEXT,
        current_location TEXT,
        current_quest TEXT
    )
    ''')
    
    # Создать таблицу для персонажей
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS characters (
        character_id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER,
        player_id INTEGER,
        player_name TEXT,
        name TEXT,
        race TEXT,
        class TEXT,
        level INTEGER DEFAULT 1,
        hp INTEGER,
        max_hp INTEGER,
        armor_class INTEGER,
        strength INTEGER,
        dexterity INTEGER,
        constitution INTEGER,
        intelligence INTEGER,
        wisdom INTEGER,
        charisma INTEGER,
        inventory TEXT,
        FOREIGN KEY (session_id) REFERENCES game_sessions(session_id)
    )
    ''')
    
    # Создать таблицу для истории разговоров
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS conversation_history (
        message_id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        sender TEXT,
        content TEXT,
        FOREIGN KEY (session_id) REFERENCES game_sessions(session_id)
    )
    ''')
    
    conn.commit()
    conn.close()
    logger.info("Настройка базы данных завершена")

# Управление игровым контекстом
def get_session_context(session_id):
    """Получить состояние игры, персонажей и историю разговоров для сессии"""
    conn = sqlite3.connect('dnd_bot.db')
    cursor = conn.cursor()
    
    # Получить детали игровой сессии
    cursor.execute("""
    SELECT campaign_name, campaign_type, setting_description, current_location, current_quest
    FROM game_sessions 
    WHERE session_id = ?
    """, (session_id,))
    
    session_data = cursor.fetchone()
    if not session_data:
        conn.close()
        return "Активная сессия не найдена."
    
    campaign_name, campaign_type, setting_description, current_location, current_quest = session_data
    
    # Получить персонажей в этой сессии
    cursor.execute("""
    SELECT player_name, name, race, class, level, hp, max_hp, 
           strength, dexterity, constitution, intelligence, wisdom, charisma
    FROM characters 
    WHERE session_id = ?
    """, (session_id,))
    
    characters = cursor.fetchall()
    
    # Получить недавнюю историю разговоров (последние 10 сообщений)
    cursor.execute("""
    SELECT sender, content FROM conversation_history 
    WHERE session_id = ? 
    ORDER BY timestamp DESC LIMIT 10
    """, (session_id,))
    
    history = cursor.fetchall()
    history.reverse()  # Показать старые сообщения сначала
    
    conn.close()
    
    # Составить контекст
    context = "ДЕТАЛИ КАМПАНИИ:\n"
    context += f"Название: {campaign_name}\n"
    context += f"Тип: {campaign_type}\n"
    context += f"Текущая локация: {current_location}\n"
    context += f"Текущий квест: {current_quest}\n\n"
    
    context += "ПЕРСОНАЖИ:\n"
    for char in characters:
        player_name, name, race, char_class, level, hp, max_hp, str_val, dex, con, intel, wis, cha = char
        context += f"{name}: Уровень {level} {race} {char_class} (играет {player_name})\n"
        context += f"ХП: {hp}/{max_hp}, Характеристики: СИЛ {str_val}, ЛОВ {dex}, ВЫН {con}, ИНТ {intel}, МДР {wis}, ХАР {cha}\n\n"
    
    context += "НЕДАВНЯЯ ИСТОРИЯ:\n"
    for sender, content in history:
        context += f"{sender}: {content}\n"
    
    return context

def generate_dm_response(user_input, session_id, player_name):
    """Сгенерировать ответ Мастера Подземелий, используя LLM"""
    context = get_session_context(session_id)
    
    prompt = f"""
Текущий игровой контекст:
{context}

Действие игрока ({player_name}):
{user_input}

Ответь как Мастер Подземелий. Поддерживай ход игры, реагируй на действия игрока и продолжай развивать приключение.
"""
    
    # Используем предоставленную функцию ask_llm
    response = ask_llm(prompt, DM_SYSTEM_PROMPT)
    
    # Обработка бросков кубиков в ответе
    response = process_dice_rolls(response)
    
    # Сохранить это взаимодействие в истории
    conn = sqlite3.connect('dnd_bot.db')
    cursor = conn.cursor()
    
    cursor.execute("""
    INSERT INTO conversation_history (session_id, sender, content)
    VALUES (?, ?, ?)
    """, (session_id, player_name, user_input))
    
    cursor.execute("""
    INSERT INTO conversation_history (session_id, sender, content)
    VALUES (?, ?, ?)
    """, (session_id, "МП", response))
    
    conn.commit()
    conn.close()
    
    return response

def process_dice_rolls(text):
    """Обработать выражения бросков кубиков типа {1d20+5} в тексте и заменить результатами"""
    def roll_dice(match):
        dice_expr = match.group(1)
        
        # Разобрать выражение кубиков (например, "2d6+3")
        if '+' in dice_expr:
            dice_part, bonus_part = dice_expr.split('+')
            bonus = int(bonus_part)
        elif '-' in dice_expr:
            dice_part, penalty_part = dice_expr.split('-')
            bonus = -int(penalty_part)
        else:
            dice_part = dice_expr
            bonus = 0
            
        num_dice, sides = map(int, dice_part.split('d'))
        
        # Бросить кубики
        rolls = [random.randint(1, sides) for _ in range(num_dice)]
        total = sum(rolls) + bonus
        
        # Форматировать результат
        if len(rolls) > 1:
            return f"{{{dice_expr} → [" + ", ".join(str(r) for r in rolls) + f"] + {bonus} = {total}}}"
        else:
            return f"{{{dice_expr} → {rolls[0]}" + (f" + {bonus}" if bonus != 0 else "") + f" = {total}}}"
    
    # Найти все выражения с кубиками и заменить их
    pattern = r'\{([1-9]\d*d[1-9]\d*(?:[+-][1-9]\d*)?)\}'
    return re.sub(pattern, roll_dice, text)

# Функциональность преобразования текста в речь
def generate_speech(text, output_file="dm_response.mp3"):
    """Генерировать речь из текста и сохранять в файл"""
    try:
        # Удалить обозначения бросков кубиков для более чистой речи
        clean_text = re.sub(r'\{.*?\}', '', text)
        
        engine = pyttsx3.init()
        # Настроить параметры голоса для более драматичного голоса МП
        voice_id = None
        voices = engine.getProperty('voices')
        for voice in voices:
            if 'male' in voice.name.lower():
                voice_id = voice.id
                break
        
        if voice_id:
            engine.setProperty('voice', voice_id)
        
        # Немного замедленная скорость для драматического эффекта
        engine.setProperty('rate', 150)
        engine.save_to_file(clean_text, output_file)
        engine.runAndWait()
        return output_file
    except Exception as e:
        logger.error(f"Ошибка при генерации речи: {e}")
        return None

# Обработчики команд
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    await update.message.reply_text(
        "🎲 Добро пожаловать в бота-Мастера Подземелий D&D! 🎲\n\n"
        "Я буду вашим виртуальным Мастером Подземелий для приключений в мире Dungeons & Dragons.\n\n"
        "Команды:\n"
        "/start - Показать это приветственное сообщение\n"
        "/help - Показать все доступные команды\n"
        "/new_game - Начать новую кампанию D&D\n"
        "/join_game - Присоединиться к существующей кампании\n"
        "/create_character - Создать нового персонажа\n"
        "/show_character - Показать детали вашего персонажа\n"
        "/roll [кубики] - Бросить кубики (например, /roll 2d6+3)\n"
        "/speak - Включить/выключить голосовое повествование\n\n"
        "Пусть приключение начнется!"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    help_text = """
🎲 Бот-Мастер Подземелий D&D - Помощь 🎲

ИГРОВЫЕ КОМАНДЫ:
/new_game - Начать новую кампанию D&D
/join_game - Присоединиться к существующей кампании
/end_game - Завершить текущую кампанию

КОМАНДЫ ПЕРСОНАЖЕЙ:
/create_character - Создать нового персонажа
/show_character - Показать детали вашего персонажа
/level_up - Повысить уровень вашего персонажа

ИГРОВЫЕ МЕХАНИКИ:
/roll [кубики] - Бросить кубики (например, /roll 2d6+3)
/initiative - Бросить на инициативу в бою
/rest - Сделать короткий или долгий отдых
/speak - Включить/выключить голосовое повествование

ПРОЧЕЕ:
/settings - Настройки бота
/status - Показать статус текущей игры

Чтобы продолжить игру, просто напишите что делает ваш персонаж!
"""
    await update.message.reply_text(help_text)

async def new_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды для начала новой игры"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    
    conn = sqlite3.connect('dnd_bot.db')
    cursor = conn.cursor()
    
    # Проверить, существует ли уже активная игра
    cursor.execute("SELECT session_id FROM game_sessions WHERE chat_id = ? AND is_active = TRUE", (chat_id,))
    existing_session = cursor.fetchone()
    
    if existing_session:
        conn.close()
        await update.message.reply_text("В этом чате уже есть активная игра. Используйте /join_game, чтобы присоединиться, или /end_game, чтобы завершить текущую игру.")
        return
    
    # Запросить у LLM предложения для новой кампании
    campaign_prompt = """
    Создай новую кампанию D&D с тремя вариантами на выбор. Для каждого варианта предоставь:
    1. Название кампании
    2. Тип кампании (исследование, героика, хоррор и т.д.)
    3. Краткое описание сеттинга
    4. Начальную локацию
    5. Первый квест
    
    Формат ответа должен быть кратким и чётким, с ясным разделением между тремя вариантами.
    """
    
    campaign_options = ask_llm(campaign_prompt, "Ты помощник Мастера Подземелий, создающий варианты новых кампаний D&D.")
    
    # Сохранить варианты в контексте для дальнейшего использования
    context.user_data['campaign_options'] = campaign_options
    
    await update.message.reply_text(
        f"🏰 {user_name}, давайте создадим новую кампанию D&D! 🏰\n\n"
        "Вот несколько вариантов кампаний. Выберите один, написав его номер (1, 2 или 3):\n\n"
        f"{campaign_options}\n\n"
        "Или напишите /custom, чтобы создать свою собственную кампанию."
    )
    
    # Установить следующий шаг обработки
    context.user_data['expecting_campaign_choice'] = True
    
    conn.close()

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    text = update.message.text
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    chat_id = update.effective_chat.id
    
    # Проверить, ожидаем ли мы выбор кампании от пользователя
    if context.user_data.get('expecting_campaign_choice'):
        if text in ['1', '2', '3']:
            # Пользователь выбрал предварительно созданную кампанию
            campaign_options = context.user_data.get('campaign_options', '')
            
            # Разобрать ответ LLM для извлечения деталей кампании
            # Это упрощенный анализ, вы можете улучшить его для более надежного извлечения данных
            lines = campaign_options.split('\n')
            choice_idx = int(text)
            
            # Найти выбранную кампанию в тексте
            campaign_name = "Новая кампания"
            campaign_type = "Приключение"
            setting_desc = "Фэнтезийный мир"
            current_location = "Таверна"
            current_quest = "Начало приключения"
            
            try:
                # Поиск деталей выбранной кампании
                # Этот код предполагает определенный формат ответа LLM
                option_found = False
                for i, line in enumerate(lines):
                    if f"Вариант {choice_idx}:" in line or f"{choice_idx}." in line:
                        option_found = True
                        # Извлечь имя кампании из текущей строки
                        parts = line.split(":", 1)
                        if len(parts) > 1:
                            campaign_name = parts[1].strip()
                        
                        # Проверить следующие строки для других деталей
                        for j in range(i+1, min(i+10, len(lines))):
                            if "Тип:" in lines[j]:
                                campaign_type = lines[j].split(":", 1)[1].strip()
                            elif "Сеттинг:" in lines[j] or "Описание:" in lines[j]:
                                setting_desc = lines[j].split(":", 1)[1].strip()
                            elif "Локация:" in lines[j]:
                                current_location = lines[j].split(":", 1)[1].strip()
                            elif "Квест:" in lines[j]:
                                current_quest = lines[j].split(":", 1)[1].strip()
                            
                            # Переход к следующей опции или концу текста
                            if j+1 < len(lines) and ("Вариант" in lines[j+1] or "---" in lines[j+1]):
                                break
                        
                        break
            except Exception as e:
                logger.error(f"Ошибка при разборе ответа LLM: {e}")
            
            # Создать новую игровую сессию
            conn = sqlite3.connect('dnd_bot.db')
            cursor = conn.cursor()
            
            cursor.execute("""
            INSERT INTO game_sessions (chat_id, campaign_name, campaign_type, setting_description, current_location, current_quest)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (chat_id, campaign_name, campaign_type, setting_desc, current_location, current_quest))
            
            session_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            # Очистить флаг ожидания
            context.user_data.pop('expecting_campaign_choice', None)
            context.user_data.pop('campaign_options', None)
            
            # Сохранить session_id в данных чата для будущего использования
            context.chat_data['active_session_id'] = session_id
            
            await update.message.reply_text(
                f"🎉 Кампания \"{campaign_name}\" успешно создана! 🎉\n\n"
                f"Тип: {campaign_type}\n"
                f"Локация: {current_location}\n\n"
                f"Теперь каждый игрок должен создать персонажа с помощью команды /create_character.\n"
                "Когда все будут готовы, МП начнет приключение!"
            )
            
            # Получить вступительное слово от Мастера Подземелий
            intro_prompt = f"""
            Ты Мастер Подземелий для новой кампании D&D.
            
            Кампания: {campaign_name}
            Тип: {campaign_type}
            Сеттинг: {setting_desc}
            Начальная локация: {current_location}
            Начальный квест: {current_quest}
            
            Напиши захватывающее вступление к этой кампании, устанавливающее сцену и атмосферу. Не более 5-6 предложений.
            Обращайся к игрокам, приглашая их в этот мир. Не указывай им, что делать, а просто представь ситуацию.
            """
            
            intro_text = ask_llm(intro_prompt, DM_SYSTEM_PROMPT)
            
            # Сохранить вступление в историю
            conn = sqlite3.connect('dnd_bot.db')
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO conversation_history (session_id, sender, content)
            VALUES (?, ?, ?)
            """, (session_id, "МП", intro_text))
            conn.commit()
            conn.close()
            
            # Сгенерировать и отправить аудио
            speech_file = generate_speech(intro_text)
            if speech_file:
                with open(speech_file, 'rb') as audio:
                    await update.message.reply_voice(voice=audio, caption="🎭 Мастер Подземелий начинает историю...")
                os.remove(speech_file)  # Удалить временный файл
            
            await update.message.reply_text(intro_text)
            
            return
        else:
            # Неверный выбор
            await update.message.reply_text("Пожалуйста, выберите номер кампании (1, 2 или 3) или используйте /custom для создания собственной.")
            return
    
    # Если есть активная сессия, обработать как игровое взаимодействие
    session_id = context.chat_data.get('active_session_id')
    if session_id:
        # Проверить, есть ли у пользователя персонаж
        conn = sqlite3.connect('dnd_bot.db')
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM characters WHERE session_id = ? AND player_id = ?", (session_id, user_id))
        character = cursor.fetchone()
        conn.close()
        
        if not character:
            await update.message.reply_text(
                "У вас еще нет персонажа в этой кампании! Используйте команду /create_character, чтобы создать его."
            )
            return
        
        # Обработать игровое взаимодействие
        character_name = character[0]
        dm_response = generate_dm_response(text, session_id, f"{character_name} ({user_name})")
        
        # Сгенерировать и отправить аудио, если включено
        if context.chat_data.get('voice_enabled', True):
            speech_file = generate_speech(dm_response)
            if speech_file:
                with open(speech_file, 'rb') as audio:
                    await update.message.reply_voice(voice=audio)
                os.remove(speech_file)  # Удалить временный файл
        
        # Разделить ответ на части, если он слишком длинный
        if len(dm_response) > 4000:
            parts = [dm_response[i:i+4000] for i in range(0, len(dm_response), 4000)]
            for part in parts:
                await update.message.reply_text(part)
        else:
            await update.message.reply_text(dm_response)
    else:
        # Если нет активной сессии
        await update.message.reply_text(
            "Сейчас нет активной игры! Используйте /new_game, чтобы начать новую кампанию, или /join_game, чтобы присоединиться к существующей."
        )

async def create_character(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды для создания персонажа"""
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    chat_id = update.effective_chat.id
    
    # Проверить, есть ли активная сессия
    session_id = context.chat_data.get('active_session_id')
    if not session_id:
        await update.message.reply_text("Сначала нужно начать игру! Используйте /new_game, чтобы создать новую кампанию.")
        return
    
    # Проверить, есть ли уже персонаж
    conn = sqlite3.connect('dnd_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM characters WHERE session_id = ? AND player_id = ?", (session_id, user_id))
    existing_character = cursor.fetchone()
    conn.close()
    
    if existing_character:
        await update.message.reply_text(f"У вас уже есть персонаж {existing_character[0]} в этой кампании! Используйте /show_character, чтобы увидеть его.")
        return
    
    # Запросить у LLM предложения персонажей
    character_prompt = """
    Создай три варианта персонажей D&D 5e уровня 1 на выбор. Для каждого варианта предоставь:
    1. Имя
    2. Раса
    3. Класс
    4. Краткая предыстория (1-2 предложения)
    5. Ключевые характеристики (СИЛ, ЛОВ, ВЫН, ИНТ, МДР, ХАР)
    6. ХП и КД
    
    Формат ответа должен быть кратким и чётким, с ясным разделением между тремя вариантами.
    """
    
    character_options = ask_llm(character_prompt, "Ты помощник по созданию персонажей D&D.")
    
    # Сохранить варианты в контексте для дальнейшего использования
    context.user_data['character_options'] = character_options
    
    await update.message.reply_text(
        f"🧙‍♂️ {user_name}, давайте создадим вашего персонажа! 🧙‍♂️\n\n"
        "Вот несколько вариантов персонажей. Выберите один, написав его номер (1, 2 или 3):\n\n"
        f"{character_options}\n\n"
        "Или напишите /custom_char, чтобы создать своего собственного персонажа."
    )
    
    # Установить следующий шаг обработки
    context.user_data['expecting_character_choice'] = True

async def roll_dice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды для броска кубиков"""
    if not context.args:
        await update.message.reply_text("Укажите формат броска, например /roll 2d6+3")
        return
    
    dice_expr = context.args[0]
    
    # Проверить правильность формата выражения
    if not re.match(r'^[1-9]\d*d[1-9]\d*(?:[+-][1-9]\d*)?$', dice_expr):
        await update.message.reply_text("Неверный формат! Используйте формат вида 2d6+3")
        return
    
    # Использовать функцию process_dice_rolls
    roll_result = process_dice_rolls("{" + dice_expr + "}")
    
    # Удалить фигурные скобки для чистоты ответа
    roll_result = roll_result.strip("{}")
    
    await update.message.reply_text(f"🎲 {update.effective_user.first_name} бросает {dice_expr}:\n{roll_result}")

async def speak_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Включить/выключить голосовые ответы МП"""
    voice_enabled = context.chat_data.get('voice_enabled', True)
    voice_enabled = not voice_enabled
    context.chat_data['voice_enabled'] = voice_enabled
    
    status = "включено" if voice_enabled else "выключено"
    await update.message.reply_text(f"🔊 Голосовое повествование {status}.")

def main():
    """Основная функция для запуска бота"""
    # Настройка базы данных при старте
    setup_database()
    
    # Получить токен бота
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "your_token_here")
    
    # Создать приложение
    application = Application.builder().token(token).build()
    
    # Добавить обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("new_game", new_game))
    application.add_handler(CommandHandler("create_character", create_character))
    application.add_handler(CommandHandler("roll", roll_dice_command))
    application.add_handler(CommandHandler("speak", speak_toggle))
    
    # Обработчик для текстовых сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # Запустить бота
    application.run_polling()

if __name__ == '__main__':
    main()
