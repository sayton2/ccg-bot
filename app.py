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

app = Flask(__name__)

@app.route('/')
def home():
    return "Бот работает!", 200

# Данные авторизации
VK_TOKEN = os.environ.get("VK_TOKEN", "vk1.a.BALD32iIlxqRFAkhbeNf_ov9m4nXt-Kw9VY3A_JHaIDm5AbgfCumitU_Wkwr3j2FJCEcAKS7DZTuPm_5cmbuHEtNdFIGCwf5ObrPf1agvu6nYefQ7kdKwEIaZT63A5cmC9lf8kiASrIqcC8GjCfclXX517KPSL8wEbXDGvnw-BEFIIU09vJx1v_XQn8T4rlVnmtfuQaa75uSq_J6IVbM3A")
GROUP_ID = int(os.environ.get("GROUP_ID", 202318207))

# Правила транслитерации (WP стиль: ц -> c)
RULES = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'c', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
    'ы': 'y', 'э': 'e', 'ю': 'yu', 'я': 'ya', 'ь': '', 'ъ': ''
}

def get_image_url(card_name, cmd):
    """Пытается найти карту всеми способами"""
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    # Способ 1: Внутренний поиск сайта (самый надежный для кириллицы и 'ц')
    try:
        search_res = requests.get(f"https://ep-ccg.ru/?s={quote(card_name)}", headers=headers, timeout=5)
        if search_res.status_code == 200:
            page_url = re.search(r'href="(https://ep-ccg\.ru/(cards/|)[^"]+)"', search_res.text)
            if page_url:
                res_p = requests.get(page_url.group(1), headers=headers, timeout=5)
                img = re.search(r'src="([^"]+\.webp)"', res_p.text)
                if img: return img.group(1)
    except: pass

    # Способ 2: Прямая ссылка (как было раньше)
    prefix = "bgo-" if cmd == "!бго" else "bk-"
    lat_name = "".join(RULES.get(c, c) for c in card_name.lower().replace(" ", "-"))
    
    paths = ["wp-content/uploads/2024/05/", "wp-content/uploads/2024/06/", "wp-content/uploads/"]
    for p in paths:
        url = urljoin("https://ep-ccg.ru", f"{p}{prefix}{lat_name}.webp")
        try:
            if requests.head(url, timeout=2).status_code == 200: return url
        except: pass
    return None

def run_bot():
    while True:
        try:
            vk = vk_api.VkApi(token=VK_TOKEN)
            lp = VkBotLongPoll(vk, GROUP_ID)
            print("Бот ВК запущен!", flush=True)
            
            for event in lp.listen():
                if event.type == VkBotEventType.MESSAGE_NEW:
                    msg = event.obj.message
                    text = msg.get('text', '').lower()
                    
                    cmd = None
                    if text.startswith("!бго "): cmd = "!бго"
                    elif text.startswith("!бк "): cmd = "!бк"
                    if not cmd: continue
                    
                    name = text[len(cmd):].strip()
                    url = get_image_url(name, cmd)
                    
                    if url:
                        # Скачиваем и обрабатываем
                        img_data = requests.get(url).content
                        img = Image.open(io.BytesIO(img_data)).convert("RGBA")
                        # (Ваш код обработки картинки пропущен для краткости, но он в финальной версии будет)
                        # Для примера просто отправим текст с ссылкой, если загрузка сложна
                        
                        # Код загрузки в ВК
                        upload = vk.method('photos.getMessagesUploadServer', {'peer_id': msg['peer_id']})
                        photo = requests.post(upload['upload_url'], files={'photo': ('c.jpg', img_data, 'image/jpeg')}).json()
                        save = vk.method('photos.saveMessagesPhoto', {'photo': photo['photo'], 'server': photo['server'], 'hash': photo['hash']})
                        att = f"photo{save[0]['owner_id']}_{save[0]['id']}"
                        
                        vk.method('messages.send', {'peer_id': msg['peer_id'], 'attachment': att, 'message': f"🃏 {name.capitalize()}", 'random_id': 0})
                    else:
                        vk.method('messages.send', {'peer_id': msg['peer_id'], 'message': f"❌ Карта '{name}' не найдена", 'random_id': 0})
        except Exception as e:
            print(f"Ошибка: {e}")
            time.sleep(5)

if __name__ == '__main__':
    threading.Thread(target=run_bot, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))































