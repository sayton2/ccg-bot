# -*- coding: utf-8 -*-
from flask import Flask, request, jsonify
import vk_api
import requests
import io
from PIL import Image
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)

# ==================== НАСТРОЙКИ ВКонтакте ====================
VK_TOKEN = "vk1.a.BALD32iIlxqRFAkhbeNf_ov9m4nXt-Kw9VY3A_JHaIDm5AbgfCumitU_Wkwr3j2FJCEcAKS7DZTuPm_5cmbuHEtNdFIGCwf5ObrPf1agvu6nYefQ7kdKwEIaZT63A5cmC9lf8kiASrIqcC8GjCfclXX517KPSL8wEbXDGvnw-BEFIIU09vJx1v_XQn8T4rlVnmtfuQaa75uSq_J6IVbM3A"
# Строка подтверждения сервера из настроек Callback API вашей группы ВК:
CONFIRMATION_CODE = "ЗАМЕНИТЕ_НА_ВАШ_КОД_ПОДТВЕРЖДЕНИЯ"
# =============================================================

vk_session = vk_api.VkApi(token=VK_TOKEN, api_version='5.199')

RULES = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
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

def process_card_request(chosen_command, card_name_ru, peer_id):
    try:
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
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

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
            img = Image.open(io.BytesIO(photo_content)).convert("RGBA")
            canvas_size = 1200
            white_bg = Image.new("RGBA", (canvas_size, canvas_size), (255, 255, 255, 255))
            
            card_height = canvas_size
            scale = card_height / img.height
            card_width = int(img.width * scale)
            img = img.resize((card_width, card_height), Image.Resampling.LANCZOS)
            
            x_offset = (canvas_size - card_width) // 2
            y_offset = (canvas_size - card_height) // 2
            
            white_bg.paste(img, (x_offset, y_offset), img)
            final_img = white_bg.convert("RGB")

            output = io.BytesIO()
            final_img.save(output, format="JPEG", quality=95, subsampling=0)
            jpeg_bytes = output.getvalue()

            server_resp = vk_session.method('photos.getMessagesUploadServer', {'peer_id': peer_id})
            upload_url = server_resp['upload_url']
            
            files = {'photo': ('card.jpg', jpeg_bytes, 'image/jpeg')}
            upload_resp = requests.post(upload_url, files=files).json()
            
            if 'photo' in upload_resp and upload_resp['photo'] and upload_resp['photo'] != '[]':
                save_resp = vk_session.method('photos.saveMessagesPhoto', {
                    'photo': upload_resp['photo'],
                    'server': int(upload_resp.get('server', 0)),
                    'hash': str(upload_resp.get('hash', ''))
                })
                
                if save_resp and len(save_resp) > 0:
                    photo_data = save_resp[0]
                    attachment = f"photo{photo_data['owner_id']}_{photo_data['id']}"
        
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
                err_text = f"❌ Карта не найдена!\nФайл '{full_filename}' отсутствует на ep-ccg.ru.\n\nАдрес:\n{last_tried_url}"
            else:
                err_text = f"❌ Ошибка ВК при сохранении картинки!\nТекст ошибки: {vk_error_msg}"
            
            vk_session.method('messages.send', {'peer_id': peer_id, 'message': err_text, 'random_id': 0})
    except Exception as e:
        print(f"Ошибка обработки: {e}")

# Главный эндпоинт, куда ВК будет мгновенно слать сообщения
@app.route('/', methods=['POST'])
def webhook():
    data = request.get_json()
    if not data or 'type' not in data:
        return "Bad Request", 400

    # 1. ВК проверяет ваш сервер
    if data['type'] == 'confirmation':
        return CONFIRMATION_CODE

    # 2. Пришло новое сообщение
    if data['type'] == 'message_new':
        message_obj = data['object']['message']
        text = message_obj.get('text', '').strip()
        peer_id = message_obj.get('peer_id')
        text_lower = text.lower()

        chosen_command = None
        for command in ["!бго", "!бк"]:
            if text_lower.startswith(command + " "):
                chosen_command = command
                break

        if chosen_command:
            card_name_ru = text[len(chosen_command) + 1:].strip().lower()
            if card_name_ru:
                # Запускаем обработку в отдельном потоке, чтобы сразу вернуть ВК "ok"
                threading.Thread(target=process_card_request, args=(chosen_command, card_name_ru, peer_id)).start()

        return "ok" # ВК требует строго этот ответ в течение 10 секунд

if __name__ == '__main__':
    import os
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

























