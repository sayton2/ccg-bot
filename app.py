# -*- coding: utf-8 -*-
import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
import requests
import threading
from flask import Flask
import os
import io
from PIL import Image

app = Flask(__name__)
@app.route('/')
def home(): return "Бот active"

def start_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

threading.Thread(target=start_flask, daemon=True).start()

# ==================== НАСТРОЙКИ ВКонтакте ====================
# Вставьте сюда ваш действующий новый токен группы ВК
VK_TOKEN = "vk1.a.elAkiiYHRRLNnHIWb6xlvPiOVE1MVj7g4w4bt5BJXevd6WVs14JjvBcKe_oz0HN029Yqytq5T_P9fTMtWg49VTR0jIUKiCn02bxWsslqLsKasFncsKegwOt5SdIW9fR1YycrZi5-yqER1OeRWBnT50wNUWOojSRczFk37QVXtiVwLQ61o4P0lHmx9XIBQz3RcpehFipGGJREGcRVrp0gzw"
# =============================================================

RULES = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
    'ы': 'y', 'э': 'e', 'ю': 'yu', 'я': 'ya', 'ь': '', 'ъ': ''
}

vk_session = vk_api.VkApi(token=VK_TOKEN, api_version='5.131')
vk = vk_session.get_api()
longpoll = VkLongPoll(vk_session)

print("Бот-конвертер запущен на Render...")

for event in longpoll.listen():
    if event.type == VkEventType.MESSAGE_NEW and event.to_me:
        text = event.text.strip()
        peer_id = event.peer_id
        text_lower = text.lower()

        chosen_command = None
        for command in ["!бго", "!бк"]:
            if text_lower.startswith(command + " "):
                chosen_command = command
                break

        if chosen_command:
            card_name_ru = text[len(chosen_command) + 1:].strip().lower()
            if not card_name_ru:
                continue

            cleaned_text = card_name_ru.replace(" ", "-").replace("_", "-")
            card_name_lat = "".join(RULES.get(char, char) for char in cleaned_text)
            
            prefix = "bgo-" if chosen_command == "!бго" else "bk-"
            full_filename = prefix + card_name_lat + ".webp"

            possible_months = ["2026/06", "2026/05", "2026/04"]
            photo_content = None

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
                'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7'
            }

            for month in possible_months:
                photo_url = f"https://ep-ccg.ru{month}/{full_filename}"
                try:
                    res = requests.get(photo_url, headers=headers, timeout=5)
                    if res.status_code == 200:
                        photo_content = res.content
                        break
                except Exception:
                    continue

            attachment = None
            if photo_content:
                try:
                    # НА ЛЕТУ ПЕРЕКОДИРУЕМ ИЗ WEBP В ЧИСТЫЙ JPEG ДЛЯ ВК
                    img = Image.open(io.BytesIO(photo_content)).convert("RGB")
                    output = io.BytesIO()
                    img.save(output, format="JPEG", quality=95)
                    jpeg_content = output.getvalue()

                    upload_server = vk.messages.getMessagesUploadServer(peer_id=peer_id, v='5.131')
                    upload_url = upload_server['upload_url']
                    
                    # Отправляем ВК настоящий JPEG файл
                    files = {'photo': ('card.jpg', jpeg_content, 'image/jpeg')}
                    upload_resp = requests.post(upload_url, files=files).json()
                    
                    if 'photo' in upload_resp and upload_resp['photo']:
                        save_resp = vk.messages.saveMessagesPhoto(
                            photo=upload_resp['photo'],
                            server=upload_resp.get('server', 0),
                            hash=upload_resp.get('hash', ''),
                            v='5.131'
                        )
                        
                        if save_resp and len(save_resp) > 0:
    photo_data = save_resp[0]
    attachment = f"photo{photo_data['owner_id']}_{photo_data['id']}"

                except Exception:
                    attachment = None

            game_title = "Берсерк Герои" if chosen_command == "!бго" else "Берсерк Классика"

            if attachment:
                vk.messages.send(
                    peer_id=peer_id, 
                    message=f"🃏 [{game_title}] Карта: {card_name_ru.capitalize()}", 
                    attachment=attachment, 
                    random_id=0
                )
            else:
                vk.messages.send(
                    peer_id=peer_id, 
                    message=f"❌ Ошибка загрузки картинки ВКонтакте.\nБот успешно скачал файл с сайта, но ВК отклонил сохранение медиафайла.", 
                    random_id=0
                )






