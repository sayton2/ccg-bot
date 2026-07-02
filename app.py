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
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
import difflib

app = Flask(__name__)

@app.route('/')
def home():
    return "Многопользовательский бот активен", 200

# ==================== НАСТРОЙКИ (ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ) ====================
VK_TOKEN = os.environ.get("VK_TOKEN", "vk1.a.T5Pbv3wIbB4GMeo7K35-pOAe4VRe084e6Yk8F4d6VgpA37bFPnGMUkAiPx2pql3QHudrZD8H9yHMPkWQqIm9DPqh6Ogccw5DUV-eQDxZD0--ASEzF1lP9yPcBZuVJPewneTsmYCM_dOp5aBVycYSl2hxkOrnRWa6Ew7VijQTXr2vJG0pLJ77yuz_DwPn1hSnpilKv2PixLWo0e-WfTmCoA")
GROUP_ID = int(os.environ.get("GROUP_ID", 202318207))
# =====================================================================================

RULES = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'j', 'к': 'k', 'л': 'l', 'м': 'm',
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
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        res = requests.get("https://ep-ccg.ru", headers=headers, timeout=10)
        if res.status_code == 200:
            links = re.findall(r'href__="([^"]+\.webp)"', res.text, re.IGNORECASE)
            found = list(set([l.split('/')[-1] for l in links]))
            if found:
                with INDEX_LOCK:
                    SITE_FILES_INDEX = found
                    LAST_INDEX_UPDATE = time.time()
                print(f"Индекс обновлен! Карт: {len(SITE_FILES_INDEX)}", flush=True)
    except:
        pass

def get_smart_filename(target_filename):
    if not SITE_FILES_INDEX:
        return target_filename
    matches = difflib.get_close_matches(target_filename, SITE_FILES_INDEX, n=1, cutoff=0.75)
    return matches[0] if matches else target_filename

def fetch_photo(path, full_filename, headers):
    photo_url = urljoin("https://ep-ccg.ru", f"{path.strip('/')}/{full_filename}")
    try:
        res = requests.get(photo_url, headers=headers, timeout=4)
        if res.status_code == 200:
            return res.content, photo_url
    except:
        pass
    return None, photo_url

def run_vk_bot():
    update_site_files_index()
    while True:
        try:
            vk_session = vk_api.VkApi(token=VK_TOKEN, api_version='5.199')
            bot_longpoll = VkBotLongPoll(vk_session, group_id=GROUP_ID)
            print("Бот успешно запущен и слушает ВК...", flush=True)

            while True:
                try:
                    events = bot_longpoll.check()
                    for event in events:
                        if event.type == VkBotEventType.MESSAGE_NEW:
                            message_obj = event.obj.message
                            raw_text = message_obj.get('text', '').strip()
                            peer_id = message_obj.get('peer_id')

                            # ЧИСТКА ОТ УПОМИНАНИЙ (для работы в беседах других сообществ)
                            text = re.sub(r'\[club\d+\|@?[^\]]+\]\s*', '', raw_text).strip()
                            text_lower = text.lower()

                            chosen_command = None
                            for command in ["!бго", "!бк"]:
                                if text_lower.startswith(command + " "):
                                    chosen_command = command
                                    break
                            if not chosen_command:
                                continue

                            card_name_ru = text[len(chosen_command) + 1:].strip().lower()
                            if not card_name_ru:
                                continue

                            cache_key = f"{chosen_command}_{card_name_ru}"
                            game_title = "Берсерк Герои" if chosen_command == "!бго" else "Берсерк Классика"
                            response_msg = f"🃏 [{game_title}] Карта: {card_name_ru.capitalize()}\n\nБаза карт: ep-ccg.ru"

                            if cache_key in ATTACHMENT_CACHE:
                                vk_session.method('messages.send', {
                                    'peer_id': peer_id,
                                    'message': response_msg,
                                    'attachment': ATTACHMENT_CACHE[cache_key],
                                    'random_id': 0
                                })
                                continue

                            cleaned_text = card_name_ru.replace(" ", "-").replace("_", "-")
                            card_name_lat = "".join(RULES.get(char, char) for char in cleaned_text)
                            prefix = "bgo-" if chosen_command == "!бго" else "bk-"
                            ideal_filename = prefix + card_name_lat + ".webp"
                            full_filename = get_smart_filename(ideal_filename)

                            possible_paths = [
                                "wp-content/uploads/2026/07/",
                                "wp-content/uploads/2026/06/",
                                "wp-content/uploads/2026/05/",
                                "wp-content/uploads/",
                                "2026/07/",
                                "2026/06/",
                                "2026/05/",
                                "wp-content/uploads/2024/05/",
                                "wp-content/uploads/2024/06/",
                            ]

                            photo_content = None
                            last_tried_url = ""
                            headers = {'User-Agent': 'Mozilla/5.0'}

                            with ThreadPoolExecutor(max_workers=len(possible_paths)) as executor:
                                futures = [executor.submit(fetch_photo, path, full_filename, headers) for path in possible_paths]
                                for future in as_completed(futures):
                                    content, tried_url = future.result()
                                    if content:
                                        photo_content = content
                                        last_tried_url = tried_url
                                        break

                            if photo_content:
                                try:
                                    img = Image.open(io.BytesIO(photo_content)).convert("RGBA")
                                    canvas_size = 800
                                    white_bg = Image.new("RGBA", (canvas_size, canvas_size), (255, 255, 255, 255))
                                    scale = canvas_size / img.height
                                    card_width = int(img.width * scale)
                                    img = img.resize((card_width, canvas_size), Image.Resampling.BILINEAR)
                                    white_bg.paste(img, ((canvas_size - card_width) // 2, 0), img)
                                    output = io.BytesIO()
                                    white_bg.convert("RGB").save(output, format="JPEG", quality=90)

                                    up_srv = vk_session.method('photos.getMessagesUploadServer', {'peer_id': peer_id})
                                    upload_url = up_srv['response']['upload_url'] if 'response' in up_srv else up_srv['upload_url']
                                    upload_resp = requests.post(upload_url, files={'photo': ('card.jpg', output.getvalue(), 'image/jpeg')}).json()
                                    save_resp = vk_session.method('photos.saveMessagesPhoto', {
                                        'photo': upload_resp['photo'],
                                        'server': upload_resp['server'],
                                        'hash': upload_resp['hash']
                                    })

                                    actual_data = save_resp['response'] if 'response' in save_resp else save_resp
                                    attachment = f"photo{actual_data[0]['owner_id']}_{actual_data[0]['id']}"
                                    ATTACHMENT_CACHE[cache_key] = attachment

                                    vk_session.method('messages.send', {
                                        'peer_id': peer_id,
                                        'message': response_msg,
                                        'attachment': attachment,
                                        'random_id': 0
                                    })
                                except Exception as e:
                                    vk_session.method('messages.send', {
                                        'peer_id': peer_id,
                                        'message': f"❌ Ошибка ВК: {e}",
                                        'random_id': 0
                                    })
                            else:
                                vk_session.method('messages.send', {
                                    'peer_id': peer_id,
                                    'message': f"❌ Карта не найдена!\nФайл: {full_filename}",
                                    'random_id': 0
                                })
                except Exception:
                    time.sleep(1)
                time.sleep(0.1)
        except Exception:
            time.sleep(5)

if __name__ == '__main__':
    bot_thread = threading.Thread(target=run_vk_bot)
    bot_thread.daemon = True
    bot_thread.start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
    




