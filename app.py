# -*- coding: utf-8 -*-
import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
import requests
import threading
from flask import Flask
import os
import io
import time
from PIL import Image
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)

@app.route('/')
def home(): 
    return "Многопользовательский бот активен", 200

# ==================== БЕЗОПАСНЫЕ НАСТРОЙКИ (ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ) ====================
VK_TOKEN = os.environ.get("VK_TOKEN", "vk1.a.BALD32iIlxqRFAkhbeNf_ov9m4nXt-Kw9VY3A_JHaIDm5AbgfCumitU_Wkwr3j2FJCEcAKS7DZTuPm_5cmbuHEtNdFIGCwf5ObrPf1agvu6nYefQ7kdKwEIaZT63A5cmC9lf8kiASrIqcC8GjCfclXX517KPSL8wEbXDGvnw-BEFIIU09vJx1v_XQn8T4rlVnmtfuQaa75uSq_J6IVbM3A")
GROUP_ID = int(os.environ.get("GROUP_ID", 202318207))
# =====================================================================================

RULES = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'j', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
    'ы': 'y', 'э': 'e', 'ю': 'yu', 'я': 'ya', 'ь': '', 'ъ': ''
}

def fetch_photo(path, full_filename, headers):
    relative_url = f"{path.strip('/')}/{full_filename}"
    photo_url = urljoin("https://ep-ccg.ru", relative_url)
    try:
        res = requests.get(photo_url, headers=headers, timeout=2)
        if res.status_code == 200:
            return res.content, photo_url
    except Exception:
        pass
    return None, photo_url

def run_vk_bot():
    while True:
        try:
            vk_session = vk_api.VkApi(token=VK_TOKEN, api_version='5.199')
            
            bot_longpoll = VkBotLongPoll(vk_session, group_id=GROUP_ID)
            print("Бот успешно запущен и слушает ВК...")
            
            while True:
                try:
                    events = bot_longpoll.check()
                    for event in events:
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
                            headers = {'User-Agent': 'Mozilla/5.0'}

                            with ThreadPoolExecutor(max_workers=len(possible_paths)) as executor:
                                futures = [executor.submit(fetch_photo, path, full_filename, headers) for path in possible_paths]
                                for future in as_completed(futures):
                                    content, tried_url = future.result()
                                    last_tried_url = tried_url
                                    if content:
                                        photo_content = content
                                        break

                            attachment = None
                            vk_error_msg = ""
                            
                            if photo_content:
                                try:
                                    img = Image.open(io.BytesIO(photo_content)).convert("RGBA")
                                    
                                    canvas_size = 800
                                    white_bg = Image.new("RGBA", (canvas_size, canvas_size), (255, 255, 255, 255))
                                    
                                    card_height = canvas_size
                                    scale = card_height / img.height
                                    card_width = int(img.width * scale)
                                    
                                    img = img.resize((card_width, card_height), Image.Resampling.BILINEAR)
                                    
                                    x_offset = (canvas_size - card_width) // 2
                                    y_offset = (canvas_size - card_height) // 2
                                    
                                    white_bg.paste(img, (x_offset, y_offset), img)
                                    final_img = white_bg.convert("RGB")

                                    output = io.BytesIO()
                                    final_img.save(output, format="JPEG", quality=90)
                                    jpeg_bytes = output.getvalue()

                                    server_resp = vk_session.method('photos.getMessagesUploadServer', {'peer_id': peer_id})
                                    upload_url = server_resp['response']['upload_url'] if 'response' in server_resp else server_resp['upload_url']
                                    
                                    files = {'photo': ('card.jpg', jpeg_bytes, 'image/jpeg')}
                                    upload_resp = requests.post(upload_url, files=files).json()
                                    
                                    if 'photo' in upload_resp and upload_resp['photo'] and upload_resp['photo'] != '[]':
                                        save_resp = vk_session.method('photos.saveMessagesPhoto', {
                                            'photo': upload_resp['photo'],
                                            'server': int(upload_resp.get('server', 0)),
                                            'hash': str(upload_resp.get('hash', ''))
                                        })
                                        
                                        actual_data = save_resp['response'] if 'response' in save_resp else save_resp
                                        if actual_data and len(actual_data) > 0:
                                            photo_data = actual_data
                                            attachment = f"photo{photo_data['owner_id']}_{photo_data['id']}"
                                except Exception as e:
                                    vk_error_msg = str(e)
                                    attachment = None

                            game_title = "Берсерк Герои" if chosen_command == "!бго" else "Берсерк Классика"

                            if attachment:
                                vk_session.method('messages.send', {
                                    'peer_id': peer_id,
                                    'message': f"🃏 [{game_title}] Карта: {card_name_ru.capitalize()}\n\nБаза карт: ep-ccg.ru",
                                    'attachment': attachment,
                                    'random_id': 0
                                })
                            else:
                                if not photo_content:
                                    err_text = f"❌ Карта не найдена на сайте!\nФайл '{full_filename}' отсутствует.\n\nПроверен адрес:\n{last_tried_url}"
                                else:
                                    err_text = f"❌ Ошибка ВК при сохранении картинки!\nТекст ошибки: {vk_error_msg}"
                                vk_session.method('messages.send', {'peer_id': peer_id, 'message': err_text, 'random_id': 0})
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




























