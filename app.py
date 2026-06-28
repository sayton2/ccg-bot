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
def home(): return "Бот работает"

def start_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

threading.Thread(target=start_flask, daemon=True).start()

# ==================== НАСТРОЙКИ ВКонтакте ====================
# Вставьте сюда ваш действующий токен группы ВК
VK_TOKEN = "vk1.a.X3AziWC5kugRJmL88Qdtx_SCoCdzl-UEC_0BqUrbBsh4cu0dHO5CZ4tv5ES3t_kYQKkixZjKh_6KFZZXeYcDNj24VfZpYzhunro5GZVVobpHweSsOU0pT0A96m1vKkiU67KaXhk-T3JEKmJSYD1qulypusVl9rmBzw0WTUw6ULuy6Vf0IlK4r6iLkbUB_66__x5OV1aTXOwydFqKQgJw_w"
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

print("Бот на чистых requests запущен на Render...")

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
                    # Конвертируем в JPEG в памяти
                    img = Image.open(io.BytesIO(photo_content)).convert("RGB")
                    output = io.BytesIO()
                    img.save(output, format="JPEG", quality=95)
                    jpeg_bytes = output.getvalue()

                    # 1. Получаем сервер загрузки через чистый API
                    server_resp = vk.messages.getMessagesUploadServer(peer_id=peer_id, v='5.131')
                    upload_url = server_resp['upload_url']
                    
                    # 2. Отправляем файл обычным POST-запросом через requests (без vk_api)
                    files = {'photo': ('card.jpg', jpeg_bytes, 'image/jpeg')}
                    upload_resp = requests.post(upload_url, files=files).json()
                    
                    # 3. Сохраняем фото в ВК
                    if 'photo' in upload_resp and upload_resp['photo'] and upload_resp['photo'] != '[]':
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
                    message=f"❌ Ошибка!\nБот успешно скачал карту с сайта ep-ccg.ru, но ВК отклонил сохранение файла.\nПроверьте, что в настройках группы ВК -> Работа с API -> Ключи доступа у вашего токена включена галочка 'Доступ к фотографиям сообщества'.", 
                    random_id=0
                )








