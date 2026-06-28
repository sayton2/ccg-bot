# -*- coding: utf-8 -*-
import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
import requests
import threading
from flask import Flask
import os
import io
import sys
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
VK_TOKEN = "vk1.a.BALD32iIlxqRFAkhbeNf_ov9m4nXt-Kw9VY3A_JHaIDm5AbgfCumitU_Wkwr3j2FJCEcAKS7DZTuPm_5cmbuHEtNdFIGCwf5ObrPf1agvu6nYefQ7kdKwEIaZT63A5cmC9lf8kiASrIqcC8GjCfclXX517KPSL8wEbXDGvnw-BEFIIU09vJx1v_XQn8T4rlVnmtfuQaa75uSq_J6IVbM3A"
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

print("Бот с логированием запущен на Render...", flush=True)

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
            print(f"Получена команда: {chosen_command} для карты: {card_name_ru}", flush=True)
            if not card_name_ru:
                continue

            cleaned_text = card_name_ru.replace(" ", "-").replace("_", "-")
            card_name_lat = "".join(RULES.get(char, char) for char in cleaned_text)
            
            prefix = "bgo-" if chosen_command == "!бго" else "bk-"
            full_filename = prefix + card_name_lat + ".webp"

            possible_months = ["2026/06", "2026/05", "2026/04"]
            photo_content = None

            for month in possible_months:
                photo_url = f"https://ep-ccg.ru{month}/{full_filename}"
                try:
                    res = requests.get(photo_url, timeout=5)
                    if res.status_code == 200:
                        photo_content = res.content
                        print(f"Успешно скачан файл с сайта: {photo_url}", flush=True)
                        break
                except Exception as e:
                    print(f"Ошибка скачивания с сайта: {str(e)}", flush=True)
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
                    print(f"Получен сервер загрузки ВК: {upload_url}", flush=True)
                    
                    # 2. Отправляем файл обычным POST-запросом через requests
                    files = {'photo': ('card.jpg', jpeg_bytes, 'image/jpeg')}
                    upload_resp = requests.post(upload_url, files=files).json()
                    print(f"Ответ сервера загрузки ВК: {upload_resp}", flush=True)
                    
                    # 3. Сохраняем фото в ВК, жестко вытаскивая сырые строковые параметры
                    if 'photo' in upload_resp and upload_resp['photo'] and upload_resp['photo'] != '[]':
                        save_resp = vk.messages.saveMessagesPhoto(
                            photo=upload_resp['photo'],
                            server=int(upload_resp.get('server', 0)),
                            hash=str(upload_resp.get('hash', '')),
                            v='5.131'
                        )
                        print(f"Ответ метода сохранения фото ВК: {save_resp}", flush=True)
                        
                        if save_resp:
    photo_data = save_resp if isinstance(save_resp, list) else save_resp
    attachment = f"photo{photo_data['owner_id']}_{photo_data['id']}"

                    else:
                        print("ВК вернул пустой блок 'photo' при загрузке бинарных данных.", flush=True)
                except Exception as e:
                    print(f"Критический сбой на этапе отправки в ВК: {str(e)}", flush=True)
                    attachment = None

            game_title = "Берсерк Герои" if chosen_command == "!бго" else "Берсерк Классика"

            try:
                if attachment:
                    vk.messages.send(
                        peer_id=peer_id, 
                        message=f"🃏 [{game_title}] Карта: {card_name_ru.capitalize()}", 
                        attachment=attachment, 
                        random_id=0
                    )
                    print("Сообщение с картой успешно отправлено пользователю!", flush=True)
                else:
                    vk.messages.send(
                        peer_id=peer_id, 
                        message=f"❌ Ошибка!\nБот успешно скачал карту с сайта ep-ccg.ru, но ВК отклонил сохранение файла.", 
                        random_id=0
                    )
                    print("Отправлено текстовое сообщение об ошибке.", flush=True)
            except Exception as e:
                print(f"Не удалось отправить даже текстовое сообщение в ВК: {str(e)}", flush=True)









