# -*- coding: utf-8 -*-
import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
import requests
import threading
from flask import Flask
import os
import io
from PIL import Image

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
        print("Финальный бот успешно запущен в фоне и слушает ВК через BotLongPoll...")
        
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
                        img = Image.open(io.BytesIO(photo_content)).convert("RGB")
                        output = io.BytesIO()
                        img.save(output, format="JPEG", quality=95)
                        jpeg_bytes = output.getvalue()

                        server_resp = vk.messages.getMessagesUploadServer(peer_id=peer_id, v='5.199')
                        upload_url = server_resp['upload_url']
                        
                        files = {'photo': ('card.jpg', jpeg_bytes, 'image/jpeg')}
                        upload_resp = requests.post(upload_url, files=files).json()
                        
                        if 'photo' in upload_resp and upload_resp['photo'] and upload_resp['photo'] != '[]':
                            save_resp = vk.messages.saveMessagesPhoto(
                                photo=upload_resp['photo'],
                                server=int(upload_resp.get('server', 0)),
                                hash=str(upload_resp.get('hash', '')),
                                v='5.199'
                            )
                            
                            if save_resp and len(save_resp) > 0:
                                # Исправлено: строго берём первый элемент из ответа ВК
                                photo_data = save_resp[0]
                                attachment = f"photo{photo_data['owner_id']}_{photo_data['id']}"
                    except Exception as e:
                        print(f"Ошибка загрузки фото в ВК: {e}")
                        attachment = None

                game_title = "Берсерк Герои" if chosen_command == "!бго" else "Берсерк Классика"

                if attachment:
                    vk.messages.send(
                        peer_id=peer_id, 
                        message=f"🃏 [{game_title}] Карта: {card_name_ru.capitalize()}", 
                        attachment=attachment, 
                        random_id=0,
                        v='5.199'
                    )
                else:
                    vk.messages.send(
                        peer_id=peer_id, 
                        message=f"❌ Ошибка!\nНе удалось найти карту на сайте ep-ccg.ru или ВК отклонил сохранение картинки.\nПроверьте права вашего токена.", 
                        random_id=0,
                        v='5.199'
                    )
    except Exception as main_err:
        print(f"Критическая ошибка в работе LongPoll: {main_err}")

if __name__ == '__main__':
    bot_thread = threading.Thread(target=run_vk_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)













