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

# ==================== НАСТРОЙКИ ====================
# Если вы используете Render, добавьте переменные в Environment Variables в панели управления
VK_TOKEN = os.environ.get("VK_TOKEN", "vk1.a.BALD32iIlxqRFAkhbeNf_ov9m4nXt-Kw9VY3A_JHaIDm5AbgfCumitU_Wkwr3j2FJCEcAKS7DZTuPm_5cmbuHEtNdFIGCwf5ObrPf1agvu6nYefQ7kdKwEIaZT63A5cmC9lf8kiASrIqcC8GjCfclXX517KPSL8wEbXDGvnw-BEFIIU09vJx1v_XQn8T4rlVnmtfuQaa75uSq_J6IVbM3A")
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

def update_site_files_index():
    global SITE_FILES_INDEX, LAST_INDEX_UPDATE
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get("https://ep-ccg.ru", headers=headers, timeout=10)
        if res.status_code == 200:
            links = re.findall(r'href="([^"]+\.webp)"', res.text, re.IGNORECASE)
            found = [l.split('/')[-1] for l in links]
            if found:
                with INDEX_LOCK:
                    SITE_FILES_INDEX = list(set(found))
                    LAST_INDEX_UPDATE = time.time()
                print(f"[INDEX] Обновлен! Карт в индексе: {len(SITE_FILES_INDEX)}", flush=True)
    except Exception as e:
        print(f"[INDEX] Ошибка обновления: {e}", flush=True)

def get_smart_filename(target_filename):
    if not SITE_FILES_INDEX: return target_filename
    matches = difflib.get_close_matches(target_filename, SITE_FILES_INDEX, n=1, cutoff=0.8)
    return matches[0] if matches else target_filename

def get_image_url_from_search(card_name):
    search_url = f"https://ep-ccg.ru/?s={quote(card_name)}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        print(f"[SEARCH] Ищу через сайт: {card_name}", flush=True)
        res = requests.get(search_url, headers=headers, timeout=7)
        if res.status_code == 200:
            page_match = re.search(r'href="(https://ep-ccg\.ru/cards/[^"]+)"', res.text)
            if not page_match:
                page_match = re.search(r'href="(https://ep-ccg\.ru/[^"]+)"', res.text)
            if page_match:
                page_url = page_match.group(1)
                res_page = requests.get(page_url, headers=headers, timeout=7)
                img_match = re.search(r'property="og:image" content="([^"]+\.webp)"', res_page.text)
                if not img_match:
                    img_match = re.search(r'src="([^"]+\.webp)"', res_page.text)
                if img_match:
                    return img_match.group(1)
    except Exception as e:
        print(f"[SEARCH] Ошибка: {e}", flush=True)
    return None

def fetch_photo(path, filename, headers):
    photo_url = urljoin("https://ep-ccg.ru", f"{path.strip('/')}/{quote(filename)}")
    try:
        res = requests.get(photo_url, headers=headers, timeout=5)
        if res.status_code == 200:
            return res.content, photo_url
    except: pass
    return None, photo_url

def run_vk_bot():
    update_site_files_index()
    while True:
        try:
            print("[VK] Попытка подключения к LongPoll...", flush=True)
            vk_session = vk_api.VkApi(token=VK_TOKEN, api_version='5.199')
            bot_longpoll = VkBotLongPoll(vk_session, group_id=GROUP_ID)
            print("[VK] Бот успешно подключен!", flush=True)
            
            for event in bot_longpoll.listen():
                if event.type == VkBotEventType.MESSAGE_NEW:
                    msg = event.obj.message
                    text = msg.get('text', '').strip()
                    peer_id = msg.get('peer_id')
                    text_lower = text.lower()

                    cmd = None
                    for c in ["!бго", "!бк"]:
                        if text_lower.startswith(c + " "):
                            cmd = c
                            break
                    if not cmd: continue

                    card_name = text[len(cmd)+1:].strip()
                    if not card_name: continue
                    
                    print(f"[BOT] Запрос от {peer_id}: {card_name}", flush=True)
                    cache_key = f"{cmd}_{card_name.lower()}"

                    if cache_key in ATTACHMENT_CACHE:
                        vk_session.method('messages.send', {
                            'peer_id': peer_id, 'attachment': ATTACHMENT_CACHE[cache_key],
                            'message': f"🃏 Карта: {card_name.capitalize()} (кэш ⚡)\nБаза: ep-ccg.ru", 'random_id': 0
                        })
                        continue

                    photo_content, final_url = None, ""
                    headers = {'User-Agent': 'Mozilla/5.0'}

                    # 1. Поиск по сайту
                    found_url = get_image_url_from_search(card_name)
                    if found_url:
                        res = requests.get(found_url, headers=headers, timeout=5)
                        if res.status_code == 200:
                            photo_content, final_url = res.content, found_url

                    # 2. Прямой перебор
                    if not photo_content:
                        prefix = "bgo-" if cmd == "!бго" else "bk-"
                        clean = card_name.lower().replace(" ", "-")
                        names = [
                            f"{prefix}{clean}.webp", # Кириллица
                            f"{prefix}{''.join(RULES.get(c,c) for c in clean)}.webp", # Латиница
                            f"{clean}.webp"
                        ]
                        paths = ["wp-content/uploads/2024/05/", "wp-content/uploads/2024/06/", "wp-content/uploads/"]
                        for name in names:
                            smart_name = get_smart_filename(name)
                            with ThreadPoolExecutor(max_workers=5) as ex:
                                futures = [ex.submit(fetch_photo, p, smart_name, headers) for p in paths]
                                for f in as_completed(futures):
                                    cnt, url = f.result()
                                    if cnt:
                                        photo_content, final_url = cnt, url
                                        break
                            if photo_content: break

                    if photo_content:
                        try:
                            img = Image.open(io.BytesIO(photo_content)).convert("RGBA")
                            canvas = Image.new("RGBA", (800, 800), (255, 255, 255, 255))
                            scale = 800 / img.height
                            img = img.resize((int(img.width * scale), 800), Image.Resampling.BILINEAR)
                            canvas.paste(img, ((800 - img.width)//2, 0), img)
                            out = io.BytesIO()
                            canvas.convert("RGB").save(out, format="JPEG", quality=90)
                            
                            up_srv = vk_session.method('photos.getMessagesUploadServer', {'peer_id': peer_id})
                            up_res = requests.post(up_srv['upload_url'], files={'photo': ('c.jpg', out.getvalue(), 'image/jpeg')}).json()
                            sv_res = vk_session.method('photos.saveMessagesPhoto', {
                                'photo': up_res['photo'], 'server': up_res['server'], 'hash': up_res['hash']
                            })
                            
                            att = f"photo{sv_res[0]['owner_id']}_{sv_res[0]['id']}"
                            ATTACHMENT_CACHE[cache_key] = att
                            vk_session.method('messages.send', {'peer_id': peer_id, 'attachment': att, 'message': f"🃏 Карта: {card_name.capitalize()}", 'random_id': 0})
                            print(f"[OK] Отправлено: {card_name}", flush=True)
                        except Exception as e:
                            print(f"[ERR] Ошибка ВК: {e}", flush=True)
                    else:
                        vk_session.method('messages.send', {'peer_id': peer_id, 'message': f"❌ Карта не найдена!\nПроверен адрес: {final_url}", 'random_id': 0})
        except Exception as e:
            print(f"[CRITICAL] Перезагрузка через 5с: {e}", flush=True)
            time.sleep(5)

if __name__ == '__main__':
    # Запускаем бота в отдельном потоке
    bot_thread = threading.Thread(target=run_vk_bot, daemon=True)
    bot_thread.start()
    
    # Запускаем Flask (Render использует PORT из переменных окружения)
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
































