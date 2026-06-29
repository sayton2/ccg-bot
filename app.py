# -*- coding: utf-8 -*-
import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
import requests
import threading
from flask import Flask
import os
import io
import time
import re
from PIL import Image
from urllib.parse import urljoin, quote
from concurrent.futures import ThreadPoolExecutor, as_completed
import difflib

app = Flask(__name__)

@app.route('/')
def home():
    return "Многопользовательский бот активен", 200

VK_TOKEN = os.environ.get("VK_TOKEN", "ВАШ_ТОКЕН")
GROUP_ID = int(os.environ.get("GROUP_ID", 202318207))

RULES = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'c', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
    'ы': 'y', 'э': 'e', 'ю': 'yu', 'я': 'ya', 'ь': '', 'ъ': ''
}

ATTACHMENT_CACHE = {}
SITE_FILES_INDEX = []
LAST_INDEX_UPDATE = 0
INDEX_LOCK = threading.Lock()

def get_image_url_from_search(card_name):
    """Ищет страницу карты через поиск сайта и вытаскивает URL картинки"""
    search_url = f"https://ep-ccg.ru/?s={quote(card_name)}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        res = requests.get(search_url, headers=headers, timeout=7)
        if res.status_code == 200:
            # Ищем ссылку на пост/карту
            page_match = re.search(r'href="(https://ep-ccg\.ru/cards/[^"]+)"', res.text)
            if not page_match:
                page_match = re.search(r'href="(https://ep-ccg\.ru/[^"]+)"', res.text)
            
            if page_match:
                page_url = page_match.group(1)
                res_page = requests.get(page_url, headers=headers, timeout=7)
                # Ищем .webp картинку в контенте или в мета-тегах (og:image)
                img_match = re.search(r'property="og:image" content="([^"]+\.webp)"', res_page.text)
                if not img_match:
                    img_match = re.search(r'src="([^"]+\.webp)"', res_page.text)
                
                if img_match:
                    return img_match.group(1)
    except Exception as e:
        print(f"Ошибка поиска: {e}")
    return None

def fetch_photo(path, full_filename, headers):
    # Кодируем имя файла, если оно на кириллице
    encoded_filename = quote(full_filename)
    photo_url = urljoin("https://ep-ccg.ru", f"{path.strip('/')}/{encoded_filename}")
    try:
        res = requests.get(photo_url, headers=headers, timeout=4)
        if res.status_code == 200:
            return res.content, photo_url
    except Exception:
        pass
    return None, photo_url

def run_vk_bot():
    while True:
        try:
            vk_session = vk_api.VkApi(token=VK_TOKEN, api_version='5.199')
            bot_longpoll = VkBotLongPoll(vk_session, group_id=GROUP_ID)
            print("Бот запущен...", flush=True)
            
            while True:
                events = bot_longpoll.check()
                for event in events:
                    if event.type == VkBotEventType.MESSAGE_NEW:
                        message_obj = event.obj.message
                        text = message_obj.get('text', '').strip()
                        peer_id = message_obj.get('peer_id')
                        text_lower = text.lower()

                        chosen_command = None
                        for command in ["!бго", "!бк"]:
                            if text_lower.startswith(command + " "):
                                chosen_command = command
                                break
                        if not chosen_command: continue

                        card_name_ru = text[len(chosen_command) + 1:].strip().lower()
                        cache_key = f"{chosen_command}_{card_name_ru}"

                        if cache_key in ATTACHMENT_CACHE:
                            vk_session.method('messages.send', {
                                'peer_id': peer_id,
                                'message': f"🃏 Карта: {card_name_ru.capitalize()} (кэш ⚡)\nБаза: ep-ccg.ru",
                                'attachment': ATTACHMENT_CACHE[cache_key],
                                'random_id': 0
                            })
                            continue

                        photo_content = None
                        last_tried_url = ""
                        headers = {'User-Agent': 'Mozilla/5.0'}
                        
                        # 1. Сначала пробуем найти через поиск сайта (самый надежный способ)
                        found_url = get_image_url_from_search(card_name_ru)
                        if found_url:
                            res = requests.get(found_url, headers=headers, timeout=5)
                            if res.status_code == 200:
                                photo_content = res.content
                                last_tried_url = found_url

                        # 2. Если поиск не помог, пробуем прямой перебор (кириллица и латиница)
                        if not photo_content:
                            prefix = "bgo-" if chosen_command == "!бго" else "bk-"
                            cleaned = card_name_ru.replace(" ", "-")
                            
                            # Варианты имен файлов для проверки
                            names_to_try = [
                                f"{prefix}{cleaned}.webp",  # Кириллица (как у Целительницы)
                                f"{prefix}{''.join(RULES.get(c, c) for c in cleaned)}.webp", # Латиница
                                f"{cleaned}.webp" # Без префикса
                            ]
                            
                            possible_paths = ["wp-content/uploads/2024/05/", "wp-content/uploads/2024/06/", "wp-content/uploads/"]
                            
                            for name in names_to_try:
                                with ThreadPoolExecutor(max_workers=5) as executor:
                                    futures = [executor.submit(fetch_photo, p, name, headers) for p in possible_paths]
                                    for f in as_completed(futures):
                                        c, url = f.result()
                                        if c:
                                            photo_content, last_tried_url = c, url
                                            break
                                if photo_content: break

                        if photo_content:
                            try:
                                img = Image.open(io.BytesIO(photo_content)).convert("RGBA")
                                canvas = Image.new("RGBA", (800, 800), (255, 255, 255, 255))
                                scale = 800 / img.height
                                img = img.resize((int(img.width * scale), 800), Image.Resampling.BILINEAR)
                                canvas.paste(img, ((800 - img.width) // 2, 0), img)
                                output = io.BytesIO()
                                canvas.convert("RGB").save(output, format="JPEG", quality=90)
                                
                                upload_url = vk_session.method('photos.getMessagesUploadServer', {'peer_id': peer_id})['upload_url']
                                upload_resp = requests.post(upload_url, files={'photo': ('card.jpg', output.getvalue(), 'image/jpeg')}).json()
                                save_resp = vk_session.method('photos.saveMessagesPhoto', {
                                    'photo': upload_resp['photo'], 'server': upload_resp['server'], 'hash': upload_resp['hash']
                                })
                                attachment = f"photo{save_resp[0]['owner_id']}_{save_resp[0]['id']}"
                                ATTACHMENT_CACHE[cache_key] = attachment
                                
                                vk_session.method('messages.send', {'peer_id': peer_id, 'message': f"🃏 Карта: {card_name_ru.capitalize()}", 'attachment': attachment, 'random_id': 0})
                            except Exception as e:
                                vk_session.method('messages.send', {'peer_id': peer_id, 'message': f"❌ Ошибка: {e}", 'random_id': 0})
                        else:
                            vk_session.method('messages.send', {'peer_id': peer_id, 'message': f"❌ Карта не найдена!\nПроверен адрес: {last_tried_url}", 'random_id': 0})
        except Exception: time.sleep(5)

if __name__ == '__main__':
    threading.Thread(target=run_vk_bot, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
































