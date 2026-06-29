# -*- coding: utf-8 -*-
import os
import io
import time
import re
import logging
import requests
import difflib
from flask import Flask
from PIL import Image
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
from vk_api import VkApi
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
import asyncio
import aiohttp
 
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
 
# ==================== НАСТРОЙКИ (ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ) ====================
VK_TOKEN = os.environ.get("VK_TOKEN")
GROUP_ID = int(os.environ.get("GROUP_ID", 202318207))
 
# Замена кириллицы на латиницу
RULES = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'j', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
    'ы': 'y', 'э': 'e', 'ю': 'yu', 'я': 'ya', 'ь': '', 'ъ': ''
}
 
# Глобальный кэш
ATTACHMENT_CACHE = {}
SITE_FILES_INDEX = []
LAST_INDEX_UPDATE = 0
 
async def fetch_with_session(url, session):
    async with session.get(url) as response:
        response.raise_for_status()
        return await response.text()
 
async def update_site_files_index():
    """Обновление индекса файлов с сайта."""
    global SITE_FILES_INDEX, LAST_INDEX_UPDATE
    headers = {'User-Agent': 'Mozilla/5.0'}
    target_urls = ["https://ep-ccg.ru"]
    
    found_files = []
    async with aiohttp.ClientSession() as session:
        for url in target_urls:
            try:
                html = await fetch_with_session(url, session)
                links = re.findall(r'href="([^"]+\.webp)"', html, re.IGNORECASE)
                found_files.extend(set(link.split('/')[-1] for link in links))
            except Exception as e:
                logging.error(f"Ошибка при обновлении индекса: {e}")
 
    if found_files:
        SITE_FILES_INDEX = found_files
        LAST_INDEX_UPDATE = time.time()
        logging.info(f"Индекс файлов обновлен! Доступно карт: {len(SITE_FILES_INDEX)}")
 
def get_smart_filename(target_filename):
    """Ищет похожий файл в индексе сайта."""
    global SITE_FILES_INDEX, LAST_INDEX_UPDATE
    
    if not SITE_FILES_INDEX or (time.time() - LAST_INDEX_UPDATE > 3600):
        asyncio.run(update_site_files_index())
        
    matches = difflib.get_close_matches(target_filename, SITE_FILES_INDEX, n=1, cutoff=0.75)
    return matches[0] if matches else target_filename
 
async def fetch_photo(path, full_filename):
    """Получение фото с сайта."""
    relative_url = f"{path.strip('/')}/{full_filename}"
    photo_url = urljoin("https://ep-ccg.ru", relative_url)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(photo_url) as response:
                response.raise_for_status()
                return await response.read(), photo_url
    except Exception as e:
        logging.error(f"Ошибка при получении фото: {e}")
    return None, photo_url
 
async def process_message(vk_session, message):
    text = message.get('text', '').strip()
    peer_id = message.get('peer_id')
    text_lower = text.lower()
 
    if not (text_lower.startswith("!бго ") or text_lower.startswith("!бк ")):
        return
 
    chosen_command = text_lower.split(" ")[0]
    card_name_ru = text[len(chosen_command) + 1:].strip().lower()
    if not card_name_ru:
        return
 
    cache_key = f"{chosen_command}_{card_name_ru}"
    
    if cache_key in ATTACHMENT_CACHE:
        await vk_session.method('messages.send', {
            'peer_id': peer_id,
            'message': f"🃏 Карта: {card_name_ru.capitalize()} (из кэша ⚡)\n\nБаза карт: ep-ccg.ru",
            'attachment': ATTACHMENT_CACHE[cache_key],
            'random_id': 0
        })
        return
 
    cleaned_text = card_name_ru.replace(" ", "-").replace("_", "-")
    card_name_lat = "".join(RULES.get(char, char) for char in cleaned_text)
    
    prefix = "bgo-" if chosen_command == "!бго" else "bk-"
    ideal_filename = f"{prefix}{card_name_lat}.webp"
    
    full_filename = get_smart_filename(ideal_filename)
 
    possible_paths = [
        "wp-content/uploads/",
        "wp-content/uploads/2026/06/",
        "wp-content/uploads/2026/05/",
        "2026/06/",
        "2026/05/",
        "wp-content/uploads/2024/05/",
        "wp-content/uploads/2024/06/"
    ]
    
    photo_content = None
    last_tried_url = ""
 
    tasks = [fetch_photo(path, full_filename) for path in possible_paths]
    results = await asyncio.gather(*tasks)
 
    for content, tried_url in results:
        last_tried_url = tried_url
        if content:
            photo_content = content
            break
 
    if photo_content:
        img = Image.open(io.BytesIO(photo_content)).convert("RGBA")
        # Обработка изображения
        # ... (аналогично вашему коду)
        
        attachment = None
        # Загрузка фото на ВК
        # ... (аналогично вашему коду)
 
        if attachment:
            ATTACHMENT_CACHE[cache_key] = attachment
            await vk_session.method('messages.send', {
                'peer_id': peer_id,
                'message': f"🃏 Карта: {card_name_ru.capitalize()}\n\nБаза карт: ep-ccg.ru",
                'attachment': attachment,
                'random_id': 0
            })
        else:
            err_text = f"❌ Ошибка при загрузке фото!\nПроверен адрес:\n{last_tried_url}"
            await vk_session.method('messages.send', {'peer_id': peer_id, 'message': err_text, 'random_id': 0})
 
async def run_vk_bot():
    vk_session = VkApi(token=VK_TOKEN)
    bot_longpoll = VkBotLongPoll(vk_session, group_id=GROUP_ID)
    
    while True:
        try:
            events = bot_longpoll.check()
            for event in events:
                if event.type == VkBotEventType.MESSAGE_NEW:
                    asyncio.create_task(process_message(vk_session, event.obj.message))
        except Exception as e:
            logging.error(f"Ошибка в основном цикле: {e}")
            await asyncio.sleep(5)
 
if __name__ == '__main__':
    asyncio.run(run_vk_bot())
































