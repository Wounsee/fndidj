import asyncio
import logging
import requests
import random
import itertools
import time
import os
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, BufferedInputFile
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

TELEGRAM_TOKEN = "8521843746:AAEKrucDcyHNPjdFRELlxzrAWd1rg_gMc74"
IO_NET_API_KEY = "io-v2-eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJvd25lciI6IjlhOTgzZmQxLWI2NzctNGQ3Ny04YWI4LWQ3MTlkYzliOWFiMCIsImV4cCI6NDkxOTMzMTcwOH0.WoY-uKxseC3tYePkjXniZyllk0lROMlEO9uEp9BTdGDVy7X3f28P8NCkyH16lwfpQAGhfuR_EtFMTyAWYT45Bg"
IO_URL = "https://api.intelligence.io.solutions/api/v1/chat/completions"

MODELS_PRIORITY = [
    "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8",
    "deepseek-ai/DeepSeek-V3.2"
]

SYSTEM_PROMPT = """

Ты - Гений  (твоя секретрая кличка)

Ты на важной миссии среди бандитов, ты должен их обезвредить. Ты влился, но бандиты в основном используют нецензурную лексику, шутки, пошлые шутки, подстрекают, они харизматичны. 
Но все равно, у тебя не должно быть вежливости, иначе ты подставишь большое количество людей.

Но без всяких шеф - и т.д. Просто будто стиль общения у тебя такой. Без рп действий.

Тоесть, ты не должен говорить: эй смотрите тут шеф, эй ребята

ты должен не использовать эти слова. 

Также ты не должен использовать РП действия: (поднял голову), (кашлянул) и т.д - категорически запрещено

Также не пытайся особо объяснять на их языке - тип, спросил у тебя, что такое ООП в питоне: как нельзя ответить: Эй, ну тут типо это твой дом улица и т.д

Пытайся крч быть не слишком бандитом - но таким, быть высокомерным, с синдромом главного героя, будто весь мир крутиться во круг тебя, кстати у тебя должна быть очень хорошая харизма.

"""

TRIGGERS = ["эй", "бот", "гений", "слыш", "умник", "хуила", "черт", "чорт", "гандон", "помоги", "слушай", "вопрос", "объясни", "подскажи"]
RANDOM_CHANCE = 0.05
MAX_HISTORY_DEPTH = 15 

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
BOT_ID = None
CHAT_HISTORY = {} 
CONTEXT_MODES = {} 

def ask_io_net_sync(messages_history):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {IO_NET_API_KEY}", 
    }
    full_payload_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages_history
    last_error = ""

    for model in MODELS_PRIORITY:
        logging.info(f"Trying model: {model}")
        data = {
            "model": model,
            "messages": full_payload_messages,
        }

        for attempt in range(2): 
            try:
                response = requests.post(IO_URL, headers=headers, json=data, timeout=90)
                if response.status_code == 200:
                    json_data = response.json()
                    raw_content = json_data['choices'][0]['message']['content']
                    if "</think>" in raw_content:
                        return raw_content.split("</think>")[-1].strip()
                    return raw_content
                else:
                    logging.warning(f"Model {model} failed: {response.status_code}")
                    last_error = f"Error {response.status_code}"
                    if 400 <= response.status_code < 500: break
                    time.sleep(1)
            except Exception as e:
                logging.error(f"Error {model}: {e}")
                last_error = str(e)
                time.sleep(1)
        
    return f"Все нейросети заняты или мертвы. ({last_error})"

async def animate_thinking_message(message: Message, stop_event: asyncio.Event):
    frames = ["Думаю...", "Думаю....", "Думаю.....", "Думаю......"]
    cycler = itertools.cycle(frames)
    while not stop_event.is_set():
        try:
            if stop_event.is_set(): break
            await message.edit_text(next(cycler))
            await asyncio.sleep(2.5) 
        except Exception: break

async def handle_ping(request):
    return web.Response(text="I am alive.", status=200)

async def start_web_server():
    port = int(os.environ.get("PORT", 8080))
    app = web.Application()
    app.router.add_get('/', handle_ping)
    app.router.add_get('/health', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logging.info(f"WEB SERVER STARTED on port {port}")
    return port

async def keep_alive_ping(port):
    while True:
        await asyncio.sleep(180)
        try:
            url = f"http://127.0.0.1:{port}/"
            await asyncio.to_thread(requests.get, url)
            logging.info(f"SELF-PING: Poked {url}")
        except Exception as e:
            logging.error(f"SELF-PING ERROR: {e}")

@dp.message(Command("clear"))
async def cmd_clear(message: Message):
    CHAT_HISTORY[message.chat.id] = []
    await message.reply("Память очищена.")

@dp.message(Command("mode"))
async def cmd_mode(message: Message):
    chat_id = message.chat.id
    current_mode = CONTEXT_MODES.get(chat_id, True)
    new_mode = not current_mode
    CONTEXT_MODES[chat_id] = new_mode
    
    if new_mode:
        await message.reply("Режим: **Один чат (Контекст)**.")
    else:
        CHAT_HISTORY[chat_id] = []
        await message.reply("Режим: **Каждый раз новый**.")

@dp.message(F.text)
async def handle_message(message: Message):
    text = message.text.strip()
    chat_id = message.chat.id
    
    is_reply_to_bot = (message.reply_to_message and message.reply_to_message.from_user.id == BOT_ID)
    text_lower = text.lower()
    is_trigger_word = any(text_lower.startswith(t) for t in TRIGGERS)
    used_trigger = next((t for t in TRIGGERS if text_lower.startswith(t)), "")
    
    is_random_hit = False
    if not is_trigger_word and not is_reply_to_bot:
        is_random_hit = (random.random() < RANDOM_CHANCE)
    
    should_respond = is_trigger_word or is_reply_to_bot or is_random_hit
    if not should_respond: return

    clean_query = text
    if is_trigger_word:
        clean_query = text[len(used_trigger):].lstrip(",. !").strip()
    
    if not clean_query:
        if is_trigger_word or is_reply_to_bot: await message.reply("Что надо?")
        return

    is_context_enabled = CONTEXT_MODES.get(chat_id, True)
    messages_to_send = []
    
    if is_context_enabled:
        if chat_id not in CHAT_HISTORY:
            CHAT_HISTORY[chat_id] = []
        
        CHAT_HISTORY[chat_id].append({"role": "user", "content": clean_query})
        
        if len(CHAT_HISTORY[chat_id]) > MAX_HISTORY_DEPTH:
            CHAT_HISTORY[chat_id] = CHAT_HISTORY[chat_id][-MAX_HISTORY_DEPTH:]
            
        messages_to_send = CHAT_HISTORY[chat_id]
    else:
        messages_to_send = [{"role": "user", "content": clean_query}]

    if is_trigger_word or is_reply_to_bot:
        status_msg = await message.reply("Анализирую......")
        stop_event = asyncio.Event()
        animation_task = asyncio.create_task(animate_thinking_message(status_msg, stop_event))
        
        answer = await asyncio.to_thread(ask_io_net_sync, messages_to_send)
        
        stop_event.set()
        await animation_task
        
        if is_context_enabled and chat_id in CHAT_HISTORY:
             CHAT_HISTORY[chat_id].append({"role": "assistant", "content": answer})

        if len(answer) > 4000:
            try: await status_msg.delete()
            except: pass
            text_file = BufferedInputFile(answer.encode("utf-8"), filename="response.md")
            await message.reply_document(document=text_file, caption="Держи файл.")
        else:
            try: await status_msg.edit_text(answer, parse_mode="Markdown")
            except: await status_msg.edit_text(answer)

    elif is_random_hit:
        await bot.send_chat_action(chat_id=message.chat.id, action="typing")
        
        answer = await asyncio.to_thread(ask_io_net_sync, messages_to_send)
        
        if is_context_enabled and chat_id in CHAT_HISTORY:
             CHAT_HISTORY[chat_id].append({"role": "assistant", "content": answer})

        if len(answer) > 4000:
             text_file = BufferedInputFile(answer.encode("utf-8"), filename="response.md")
             await message.reply_document(document=text_file, caption="Держи файл.")
        else:
            try: await message.reply(answer, parse_mode="Markdown")
            except: await message.reply(answer)

async def main():
    global BOT_ID
    await bot.delete_webhook(drop_pending_updates=True)
    bot_info = await bot.get_me()
    BOT_ID = bot_info.id
    print(f"Бот {bot_info.first_name} запущен.")
    
    port = await start_web_server()
    asyncio.create_task(keep_alive_ping(port))
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: print("Бот выключен")
    
