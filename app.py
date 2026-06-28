# -*- coding: utf-8 -*-
import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
import requests
import threading
from flask import Flask
import os
import io
from PIL import Image
from urllib.parse import urljoin

app = Flask(__name__)

@app.route('/')
def home(): 
    return "Бот работает", 200

# ==================== НАСТРОЙКИ ВКонтакте ====================
VK_TOKEN = "vk1.a.BALD32iIlxqRFAkhbeNf_ov9m4nXt-Kw9VY3A_JHaIDm5AbgfCumitU_Wkwr3j2FJCEcAKS7DZTuPm_5cmbuHEtNdFIGCwf5ObrPf1agvu6nYefQ7kdKwEIaZT63A5cmC9lf8kiASrIqcC8GjCfclXX517KPSL8wEbXDGvnw-BEFIIU09vJx1v_XQn8T4rlVnmtfuQaa75uSq_J6IVbM3A"
GROUP_ID = 202318207 
# =============================================================

RULES = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
    'ы': 'y', 'э': 'e', 'ю': 'yu', 'я': 'ya', 'ь': '', 'ъ': ''
}

def run_vk_bot():
    try:
        vk_session = vk_api.VkApi(token=VK_TOKEN, api_version='5.199')
        vk = vk_session.get_api()
        
        bot_longpoll = VkBotLongPoll(vk_session, group_id=GROUP_ID)
        print("Финальный бот успешно запущен в фоне и слушает ВК...")
        
        for event in bot_longpoll.listen():
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

                if not chosen_command:
                    continue

                card_name_ru = text[len(chosen_command) + 1:].strip().lower()
                if not card_name_ru:
                    continue

                cleaned_text = card_name_ru.replace(" ", "-").replace("_", "-")
                card_name_lat = "".join(RULES.get(char, char) for char in cleaned_text)
                
                prefix = "bgo-" if chosen_command == "!бго" else "bk-"
                full_filename = prefix + card_name_lat + ".webp"

                possible_paths = [
                    "wp-content/uploads/",
                    "wp-content/uploads/2026/06/",
                    "wp-content/uploads/2026/05/",
                    "2026/06/",
                    "2026/05/",
                    "wp-content/uploads/2024/05/",
                    "wp-content/uploads/2024/06/"
                ]
                
                photo_content = None
                last_tried_url = ""

                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                }

                for path in possible_paths:
                    relative_url = f"{path.strip('/')}/{full_filename}"
                    photo_url = urljoin("https://ep-ccg.ru", relative_url)
                    last_tried_url = photo_url
                    
                    try:
                        res = requests.get(photo_url, headers=headers, timeout=2)
                        if res.status_code == 200:
                            photo_content = res.content
                            break
                    except Exception:
                        continue

                attachment = None
                vk_error_msg = ""
                
                if photo_content:
                    try:
                        img = Image.open(io.BytesIO(photo_content)).convert("RGB")
                        output = io.BytesIO()
                        img.save(output, format="JPEG", quality=95)
                        jpeg_bytes = output.getvalue()

                        # Вызываем метод получения сервера через универсальный vk_session.method
                        server_resp = vk_session.method('photos.getMessagesUploadServer', {'peer_id': peer_id})
                        upload_url = server_resp['upload_url']
                        
                        files = {'photo': ('card.jpg', jpeg_bytes, 'image/jpeg')}
                        upload_resp = requests.post(upload_url, files=files).json()
                        
                        # Сохраняем фото через чистый метод API photos.saveMessagesPhoto
                        if 'photo' in upload_resp and upload_resp['photo'] and upload_resp['photo'] != '[]':
                            save_resp = vk_session.method('photos.saveMessagesPhoto', {
                                'photo': upload_resp['photo'],
                                'server': int(upload_resp.get('server', 0)),
                                'hash': str(upload_resp.get('hash', ''))
                            })
                            
                            if save_resp and len(save_resp) > 0:
                                # Извлекаем параметры картинки из первого элемента ответа
                                photo_data = save_resp[0]
                                attachment = f"photo{photo_data['owner_id']}_{photo_data['id']}"
                    except Exception as e:
                        vk_error_msg = str(e)
                        attachment = None

                game_title = "Берсерк Герои" if chosen_command == "!бго" else "Берсерк Классика"

                if attachment:
                    vk_session.method('messages.send', {
                        'peer_id': peer_id,
                        'message': f"🃏 [{game_title}] Карта: {card_name_ru.capitalize()}",
                        'attachment': attachment,
                        'random_id': 0
                    })
                else:
                    if not photo_content:
                        err_text = f"❌ Карта не найдена на сайте!\nБот проверил все папки для файла '{full_filename}', включая свежие загрузки.\n\nПоследний проверенный адрес:\n{last_tried_url}"
                    else:
                        err_text = f"❌ Ошибка ВК при сохранении картинки!\nТекст ошибки: {vk_error_msg}\nУбедитесь, что у токена активны права на фото."
                    
                    vk_session.method('messages.send', {
                        'peer_id': peer_id,
                        'message': err_text,
                        'random_id': 0
                    })
    except Exception as main_err:
        print(f"Критическая ошибка в работе LongPoll: {main_err}")

if __name__ == '__main__':
    bot_thread = threading.Thread(target=run_vk_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)


















