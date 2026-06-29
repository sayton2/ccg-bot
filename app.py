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
    return "Bot is alive", 200

# Настройки (токен и ID группы)
VK_TOKEN = os.environ.get("VK_TOKEN", "vk1.a.BALD32iIlxqRFAkhbeNf_ov9m4nXt-Kw9VY3A_JHaIDm5AbgfCumitU_Wkwr3j2FJCEcAKS7DZTuPm_5cmbuHEtNdFIGCwf5ObrPf1agvu6nYefQ7kdKwEIaZT63A5cmC9lf8kiASrIqcC8GjCfclXX517KPSL8wEbXDGvnw-BEFIIU09vJx1v_XQn8T4rlVnmtfuQaa75uSq_J6IVbM3A")
GROUP_ID = int(os.environ.get("GROUP_ID", 202318207))

RULES = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'c', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
    'ы': 'y', 'э': 'e', 'ю': 'yu', 'я': 'ya', 'ь': '', 'ъ': ''
}

def get_image_url(card_name, cmd):
    headers = {'User-Agent': 'Mozilla/5.0'}
    print(f"[BOT] Ищу карту: {card_name}", flush=True)
    
    # 1. Поиск через сайт (самый надежный способ)
    try:
        res = requests.get(f"https://ep-ccg.ru/?s={quote(card_name)}", headers=headers, timeout=10)
        if res.status_code == 200:
            match = re.search(r'href="(https://ep-ccg\.ru/(cards/|)[^"]+)"', res.text)
            if match:
                print(f"[BOT] Нашел страницу карты: {match.group(1)}", flush=True)
                res_p = requests.get(match.group(1), headers=headers, timeout=10)
                img = re.search(r'src="([^"]+\.webp)"', res_p.text)
                if img:
                    print(f"[BOT] Нашел прямую ссылку: {img.group(1)}", flush=True)
                    return img.group(1)
    except Exception as e:
        print(f"[BOT] Ошибка поиска на сайте: {e}", flush=True)

    # 2. Прямые ссылки (если поиск не сработал)
    prefix = "bgo-" if cmd == "!бго" else "bk-"
    clean = card_name.lower().replace(" ", "-")
    names = [f"{prefix}{clean}.webp", f"{prefix}{''.join(RULES.get(c,c) for c in clean)}.webp", f"{clean}.webp"]
    paths = ["wp-content/uploads/2024/05/", "wp-content/uploads/2024/06/", "wp-content/uploads/"]
    
    for n in names:
        for p in paths:
            url = urljoin("https://ep-ccg.ru", f"{p}{quote(n)}")
            try:
                if requests.head(url, timeout=3).status_code == 200: return url
            except: pass
    return None

def run_bot():
    while True:
        try:
            print("[BOT] Подключение к ВК...", flush=True)
            vk_session = vk_api.VkApi(token=VK_TOKEN)
            vk = vk_session.get_api()
            longpoll = VkBotLongPoll(vk_session, GROUP_ID)
            print("[BOT] Готов к работе! Слушаю сообщения...", flush=True)
            
            for event in longpoll.listen():
                if event.type == VkBotEventType.MESSAGE_NEW:
                    msg = event.obj.message
                    text = msg.get('text', '')
                    peer_id = msg.get('peer_id')
                    
                    if not text: continue
                    print(f"[BOT] Новое сообщение: {text} от {peer_id}", flush=True)
                    
                    cmd = None
                    if text.lower().startswith("!бго "): cmd = "!бго"
                    elif text.lower().startswith("!бк "): cmd = "!бк"
                    if not cmd: continue
                    
                    name = text[len(cmd):].strip()
                    url = get_image_url(name, cmd)
                    
                    if url:
                        try:
                            # Обработка изображения
                            resp = requests.get(url, timeout=15)
                            img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
                            canvas = Image.new("RGBA", (800, 800), (255, 255, 255, 255))
                            scale = 800 / img.height
                            img = img.resize((int(img.width * scale), 800), Image.Resampling.BILINEAR)
                            canvas.paste(img, ((800 - img.width)//2, 0), img)
                            
                            out = io.BytesIO()
                            canvas.convert("RGB").save(out, format="JPEG", quality=90)
                            
                            # Загрузка в ВК
                            srv = vk.photos.getMessagesUploadServer(peer_id=peer_id)
                            up = requests.post(srv['upload_url'], files={'photo': ('c.jpg', out.getvalue(), 'image/jpeg')}).json()
                            sv = vk.photos.saveMessagesPhoto(photo=up['photo'], server=up['server'], hash=up['hash'])
                            att = f"photo{sv[0]['owner_id']}_{sv[0]['id']}"
                            
                            vk.messages.send(peer_id=peer_id, attachment=att, message=f"🃏 {name.capitalize()}\nБаза: ep-ccg.ru", random_id=0)
                            print(f"[BOT] Успешно отправлено: {name}", flush=True)
                        except Exception as e:
                            print(f"[BOT] Ошибка при отправке картинки: {e}", flush=True)
                            vk.messages.send(peer_id=peer_id, message=f"❌ Ошибка ВК: {e}", random_id=0)
                    else:
                        vk.messages.send(peer_id=peer_id, message=f"❌ Карта '{name}' не найдена на сайте.", random_id=0)
                        print(f"[BOT] Карта не найдена в поиске", flush=True)
        except Exception as e:
            print(f"[BOT] Критическая ошибка: {e}. Перезапуск через 10с...", flush=True)
            time.sleep(10)

if __name__ == '__main__':
    # Запускаем бота в фоновом потоке
    threading.Thread(target=run_bot, daemon=True).start()
    # Запускаем Flask для Render
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)































