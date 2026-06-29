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

# Метрика для проверки жизни потока
last_bot_activity = time.time()

@app.route('/')
def home():
    global last_bot_activity
    status = "OK" if time.time() - last_bot_activity < 300 else "STUCK?"
    print(f"[PING] Received. Bot status: {status}", flush=True)
    return f"Bot status: {status}", 200

# ==================== НАСТРОЙКИ ====================
VK_TOKEN = os.environ.get("VK_TOKEN", "ВАШ_ТОКЕН")

RULES = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'cz', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
    'ы': 'y', 'э': 'e', 'ю': 'yu', 'я': 'ya', 'ь': '', 'ъ': ''
}

ATTACHMENT_CACHE = {} 
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
                print(f"[INDEX] Обновлен! Карт: {len(SITE_FILES_INDEX)}", flush=True)
    except: pass

def get_smart_filename(target_filename):
    if not SITE_FILES_INDEX: return target_filename
    matches = difflib.get_close_matches(target_filename, SITE_FILES_INDEX, n=1, cutoff=0.75)
    return matches[0] if matches else target_filename

def clean_text(text):
    """Очищает текст от упоминаний бота [club...|@bot]"""
    return re.sub(r'\[club\d+\|@?[^\]]+\]\s*', '', text).strip()

def fetch_photo(path, filename, headers):
    url = urljoin("https://ep-ccg.ru", f"{path.strip('/')}/{quote(filename)}")
    try:
        res = requests.get(url, headers=headers, timeout=4)
        if res.status_code == 200: return res.content, url
    except: pass
    return None, url

def run_vk_bot():
    global last_bot_activity
    update_site_files_index()
    
    while True:
        try:
            vk_session = vk_api.VkApi(token=VK_TOKEN, api_version='5.199')
            vk = vk_session.get_api()
            
            # Автоматически узнаем ID группы, чтобы бот мог работать везде
            group_info = vk.groups.getById()[0]
            group_id = group_info['id']
            print(f"[VK] Бот '{group_info['name']}' запущен!", flush=True)
            
            longpoll = VkBotLongPoll(vk_session, group_id)
            
            for event in longpoll.listen():
                last_bot_activity = time.time() # Обновляем время активности
                
                if event.type == VkBotEventType.MESSAGE_NEW:
                    msg = event.obj.message
                    peer_id = msg.get('peer_id')
                    raw_text = msg.get('text', '')
                    
                    text = clean_text(raw_text)
                    text_lower = text.lower()

                    cmd = None
                    for c in ["!бго", "!бк"]:
                        if text_lower.startswith(c + " "):
                            cmd = c
                            break
                    if not cmd: continue

                    card_name = text[len(cmd) + 1:].strip()
                    if not card_name: continue
                    
                    print(f"[EVENT] Запрос от {peer_id}: {card_name}", flush=True)
                    
                    cache_key = f"{group_id}_{cmd}_{card_name.lower()}"
                    game_title = "Берсерк Герои" if cmd == "!бго" else "Берсерк Классика"
                    # Чистое сообщение без пометки о кэше
                    response_msg = f"🃏 [{game_title}] Карта: {card_name.capitalize()}\n\nБаза карт: ep-ccg.ru"

                    if cache_key in ATTACHMENT_CACHE:
                        vk.messages.send(peer_id=peer_id, message=response_msg, attachment=ATTACHMENT_CACHE[cache_key], random_id=0)
                        continue

                    # --- ПОИСК ---
                    prefix = "bgo-" if cmd == "!бго" else "bk-"
                    clean_name = card_name.lower().replace(" ", "-").replace("_", "-")
                    
                    # Генерируем имя файла с новой транслитерацией (cz)
                    ideal_name = f"{prefix}{''.join(RULES.get(c,c) for c in clean_name)}.webp"
                    full_filename = get_smart_filename(ideal_name)

                    paths = ["wp-content/uploads/2026/06/", "wp-content/uploads/2026/05/", "wp-content/uploads/", "wp-content/uploads/2024/05/", "wp-content/uploads/2024/06/"]
                    photo_content, headers = None, {'User-Agent': 'Mozilla/5.0'}

                    with ThreadPoolExecutor(max_workers=5) as ex:
                        futures = [ex.submit(fetch_photo, p, full_filename, headers) for p in paths]
                        for f in as_completed(futures):
                            cnt, url = f.result()
                            if cnt: photo_content = cnt; break
                    
                    if photo_content:
                        try:
                            # Обработка картинки
                            img = Image.open(io.BytesIO(photo_content)).convert("RGBA")
                            canvas = Image.new("RGBA", (800, 800), (255, 255, 255, 255))
                            scale = 800 / img.height
                            img = img.resize((int(img.width * scale), 800), Image.Resampling.BILINEAR)
                            canvas.paste(img, ((800 - img.width)//2, 0), img)
                            out = io.BytesIO()
                            canvas.convert("RGB").save(out, format="JPEG", quality=90)
                            
                            # Загрузка
                            up_url = vk.photos.getMessagesUploadServer(peer_id=peer_id)['upload_url']
                            up_res = requests.post(up_url, files={'photo': ('c.jpg', out.getvalue(), 'image/jpeg')}).json()
                            sv_res = vk.photos.saveMessagesPhoto(photo=up_res['photo'], server=up_res['server'], hash=up_res['hash'])
                            
                            att = f"photo{sv_res[0]['owner_id']}_{sv_res[0]['id']}"
                            ATTACHMENT_CACHE[cache_key] = att
                            vk.messages.send(peer_id=peer_id, message=response_msg, attachment=att, random_id=0)
                            print(f"[SUCCESS] Отправлено: {card_name}", flush=True)
                        except Exception as e:
                            print(f"[ERR] {e}", flush=True)
                    else:
                        vk.messages.send(peer_id=peer_id, message=f"❌ Карта '{card_name}' не найдена.", random_id=0)

        except Exception as e:
            print(f"[CRITICAL] {e}. Рестарт через 10с...", flush=True)
            time.sleep(10)

if __name__ == '__main__':
    threading.Thread(target=run_vk_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)































