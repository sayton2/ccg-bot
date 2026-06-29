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
import json
from PIL import Image
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
import difflib

app = Flask(__name__)

@app.route('/')
def home():
    return "Public Card Bot is running", 200

# ==================== НАСТРОЙКИ ТРАНСЛИТЕРАЦИИ ====================
RULES = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'j', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'cz', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
    'ы': 'y', 'э': 'e', 'ю': 'yu', 'я': 'ya', 'ь': '', 'ъ': ''
}

# Кэш вложений: { group_id: { "key": "photo_id" } }
MULTI_GROUP_CACHE = {}

# Глобальный индекс файлов сайта
SITE_FILES_INDEX = []
LAST_INDEX_UPDATE = 0
INDEX_LOCK = threading.Lock()

def update_site_files_index():
    global SITE_FILES_INDEX, LAST_INDEX_UPDATE
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get("https://ep-ccg.ru", headers=headers, timeout=10)
        if res.status_code == 200:
            links = re.findall(r'href="([^"]+\.webp)"', res.text, re.IGNORECASE)
            found = list(set([l.split('/')[-1] for l in links]))
            if found:
                with INDEX_LOCK:
                    SITE_FILES_INDEX = found
                    LAST_INDEX_UPDATE = time.time()
                print(f"[INDEX] Карт на сайте: {len(SITE_FILES_INDEX)}", flush=True)
    except: pass

def get_smart_filename(target_filename):
    if not SITE_FILES_INDEX: return target_filename
    matches = difflib.get_close_matches(target_filename, SITE_FILES_INDEX, n=1, cutoff=0.75)
    return matches[0] if matches else target_filename

def fetch_photo(path, full_filename, headers):
    photo_url = urljoin("https://ep-ccg.ru", f"{path.strip('/')}/{full_filename}")
    try:
        res = requests.get(photo_url, headers=headers, timeout=4)
        if res.status_code == 200: return res.content, photo_url
    except: pass
    return None, photo_url

def clean_message_text(text):
    """Удаляет упоминание бота из начала сообщения (для чатов)"""
    return re.sub(r'\[club\d+\|@?[^\]]+\]\s*', '', text).strip()

def start_bot_instance(token, group_id):
    """Запуск отдельного потока для каждой группы ВК"""
    global MULTI_GROUP_CACHE
    if group_id not in MULTI_GROUP_CACHE:
        MULTI_GROUP_CACHE[group_id] = {}
    cache = MULTI_GROUP_CACHE[group_id]

    while True:
        try:
            vk_session = vk_api.VkApi(token=token, api_version='5.199')
            lp = VkBotLongPoll(vk_session, group_id=group_id)
            print(f"[BOT {group_id}] Подключен!", flush=True)
            
            for event in lp.listen():
                if event.type == VkBotEventType.MESSAGE_NEW:
                    msg = event.obj.message
                    raw_text = msg.get('text', '')
                    peer_id = msg.get('peer_id')
                    
                    # Очищаем от упоминаний и переводим в нижний регистр
                    text = clean_message_text(raw_text)
                    text_lower = text.lower()

                    cmd = None
                    for c in ["!бго", "!бк"]:
                        if text_lower.startswith(c + " "):
                            cmd = c
                            break
                    if not cmd: continue

                    card_name_ru = text[len(cmd) + 1:].strip().lower()
                    if not card_name_ru: continue

                    cache_key = f"{cmd}_{card_name_ru}"

                    # --- ПРОВЕРКА КЭША (Текст теперь одинаковый для всех) ---
                    game_title = "Берсерк Герои" if cmd == "!бго" else "Берсерк Классика"
                    response_msg = f"🃏 [{game_title}] Карта: {card_name_ru.capitalize()}\n\nБаза карт: ep-ccg.ru"

                    if cache_key in cache:
                        vk_session.method('messages.send', {
                            'peer_id': peer_id, 'message': response_msg,
                            'attachment': cache[cache_key], 'random_id': 0
                        })
                        continue

                    # --- ПОИСК КАРТЫ ---
                    cleaned = card_name_ru.replace(" ", "-").replace("_", "-")
                    lat_name = "".join(RULES.get(c, c) for c in cleaned)
                    prefix = "bgo-" if cmd == "!бго" else "bk-"
                    full_filename = get_smart_filename(prefix + lat_name + ".webp")

                    paths = ["wp-content/uploads/2026/06/", "wp-content/uploads/2026/05/", "wp-content/uploads/", "wp-content/uploads/2024/05/", "wp-content/uploads/2024/06/"]
                    photo_content, headers = None, {'User-Agent': 'Mozilla/5.0'}

                    with ThreadPoolExecutor(max_workers=5) as ex:
                        futures = [ex.submit(fetch_photo, p, full_filename, headers) for p in paths]
                        for f in as_completed(futures):
                            cnt, url = f.result()
                            if cnt:
                                photo_content = cnt
                                break
                    
                    if photo_content:
                        try:
                            # Обработка картинки
                            img = Image.open(io.BytesIO(photo_content)).convert("RGBA")
                            canvas = Image.new("RGBA", (800, 800), (255, 255, 255, 255))
                            scale = 800 / img.height
                            img = img.resize((int(img.width * scale), 800), Image.Resampling.BILINEAR)
                            canvas.paste(img, ((800 - img.width) // 2, 0), img)
                            out = io.BytesIO()
                            canvas.convert("RGB").save(out, format="JPEG", quality=90)

                            # Загрузка в ВК
                            up_srv = vk_session.method('photos.getMessagesUploadServer', {'peer_id': peer_id})
                            up_res = requests.post(up_srv['upload_url'], files={'photo': ('c.jpg', out.getvalue(), 'image/jpeg')}).json()
                            sv_res = vk_session.method('photos.saveMessagesPhoto', {'photo': up_res['photo'], 'server': up_res['server'], 'hash': up_res['hash']})
                            
                            att = f"photo{sv_res[0]['owner_id']}_{sv_res[0]['id']}"
                            cache[cache_key] = att # Сохраняем в кэш группы
                            
                            vk_session.method('messages.send', {
                                'peer_id': peer_id, 'message': response_msg,
                                'attachment': att, 'random_id': 0
                            })
                        except Exception as e:
                            print(f"[ERR] {e}")
                    else:
                        vk_session.method('messages.send', {'peer_id': peer_id, 'message': f"❌ Карта не найдена!\nФайл: {full_filename}", 'random_id': 0})

        except Exception as e:
            print(f"[RESTART {group_id}] {e}")
            time.sleep(10)

if __name__ == '__main__':
    update_site_files_index()
    
    # 1. Загружаем основную группу из Env
    main_token = os.environ.get("VK_TOKEN")
    main_id = os.environ.get("GROUP_ID")
    
    configs = []
    if main_token and main_id:
        configs.append({"token": main_token, "group_id": int(main_id)})
    
    # 2. Поддержка дополнительных групп (через JSON в Env переменной EXTRA_BOTS)
    extra_bots_raw = os.environ.get("EXTRA_BOTS")
    if extra_bots_raw:
        try:
            configs.extend(json.loads(extra_bots_raw))
        except: print("Ошибка парсинга EXTRA_BOTS")

    for cfg in configs:
        threading.Thread(target=start_bot_instance, args=(cfg["token"], cfg["group_id"]), daemon=True).start()
    
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))































