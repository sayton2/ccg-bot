# -*- coding: utf-8 -*-
import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
import requests
import threading
from flask import Flask
import os

# Крошечный веб-сервер, чтобы бесплатный Render не закрывал бота по ошибке порта
app = Flask(__name__)
@app.route('/')
def home(): return "Бот активен"

def start_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# Запускаем веб-сервер в отдельном потоке, освобождая память для ВК
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

vk_session = vk_api.VkApi(token=VK_TOKEN)
vk = vk_session.get_api()
longpoll = VkLongPoll(vk_session)

print("Бот успешно запущен на платформе Render и слушает чаты ВК...")

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
            full_filename = prefix + card_name_lat

            # Картинки тянутся СТРОГО С ВАШЕГО САЙТА ep-ccg.ru по прямой ссылке со слэшем!
            s = chr(47)
            domain = "https:__ep-ccg.ru".replace("__", s + s)
            path_folder = "img"

            photo_url = domain + s + path_folder + s + full_filename + ".webp"

            photo_content = None
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8'
                }
                res = requests.get(photo_url, headers=headers, timeout=5)
                if res.status_code == 200:
                    photo_content = res.content
            except Exception:
                pass

            attachment = None
            if photo_content:
                try:
                    upload_server = vk.messages.getMessagesUploadServer(peer_id=peer_id)
                    upload_url = upload_server['upload_url']
                    
                    files = {'photo': ('card.webp', photo_content, 'image/webp')}
                    upload_resp = requests.post(upload_url, files=files).json()
                    
                    if 'photo' in upload_resp and upload_resp['photo']:
                        save_resp = vk.messages.saveMessagesPhoto(
                            photo=upload_resp['photo'],
                            server=upload_resp.get('server', 0),
                            hash=upload_resp.get('hash', '')
                        )
                        attachment = f"photo{save_resp['owner_id']}_{save_resp['id']}"
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
                    message=f"❌ Ошибка!\nБот собрал ссылку: {photo_url}\nКартинка не найдена на сайте или ВК отклонил её загрузку.", 
                    random_id=0
                )

