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
from PIL import Image, ImageDraw, ImageFont
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
import difflib

app = Flask(__name__)

@app.route('/')
def home():
    return "Многопользовательский бот активен", 200

# ==================== НАСТРОЙКИ ====================
VK_TOKEN = os.environ.get("VK_TOKEN", "vk1.a.T5Pbv3wIbB4GMeo7K35-pOAe4VRe084e6Yk8F4d6VgpA37bFPnGMUkAiPx2pql3QHudrZD8H9yHMPkWQqIm9DPqh6Ogccw5DUV-eQDxZD0--ASEzF1lP9yPcBZuVJPewneTsmYCM_dOp5aBVycYSl2hxkOrnRWa6Ew7VijQTXr2vJG0pLJ77yuz_DwPn1hSnpilKv2PixLWo0e-WfTmCoA")
GROUP_ID = int(os.environ.get("GROUP_ID", 202318207))
# ====================================================

RULES = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'j', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'cz', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
    'ы': 'y', 'э': 'e', 'ю': 'yu', 'я': 'ya', 'ь': '', 'ъ': ''
}

# Цвета стихий
ELEMENT_COLORS = {
    'steppe':   (210, 170,  30),   # жёлтый
    'mountain': (70,  130, 200),   # синий
    'swamp':    (140, 180, 130),   # бледно-зелёный
    'forest':   (60,  150,  60),   # зелёный
    'dark':     (120,  60, 180),   # фиолетовый
    'neutral':  (160, 120,  60),   # бронзовый
}
DEFAULT_ELEMENT_COLOR = (160, 120, 60)

ATTACHMENT_CACHE = {}
SITE_FILES_INDEX = []
LAST_INDEX_UPDATE = 0
INDEX_LOCK = threading.Lock()

ELEMENT_CACHE = {}

# ==================== ИНДЕКС САЙТА ====================

def update_site_files_index():
    global SITE_FILES_INDEX, LAST_INDEX_UPDATE
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        res = requests.get("https://ep-ccg.ru", headers=headers, timeout=10)
        if res.status_code == 200:
            links = re.findall(r'href__="([^"]+\.webp)"', res.text, re.IGNORECASE)
            found = list(set([l.split('/')[-1] for l in links]))
            if found:
                with INDEX_LOCK:
                    SITE_FILES_INDEX = found
                    LAST_INDEX_UPDATE = time.time()
                print(f"Индекс обновлен! Карт: {len(SITE_FILES_INDEX)}", flush=True)
    except:
        pass

def get_smart_filename(target_filename):
    if not SITE_FILES_INDEX:
        return target_filename
    matches = difflib.get_close_matches(target_filename, SITE_FILES_INDEX, n=1, cutoff=0.75)
    return matches[0] if matches else target_filename

def to_lat(text):
    cleaned = text.replace(" ", "-").replace("_", "-")
    return "".join(RULES.get(c, c) for c in cleaned)

# ==================== СТИХИЯ КАРТЫ ====================

def get_card_element(card_name_ru):
    slug = to_lat(card_name_ru.strip().lower())
    if slug in ELEMENT_CACHE:
        return ELEMENT_CACHE[slug]
    try:
        url = f"https://ep-ccg.ru/wp-json/wp/v2/mmf_card?slug={slug}&_fields=class_list"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if data and isinstance(data, list):
                classes = data[0].get('class_list', [])
                for cls in classes:
                    m = re.match(r'mmf_element-(\w+)', cls)
                    if m:
                        element = m.group(1)
                        ELEMENT_CACHE[slug] = element
                        return element
    except:
        pass
    ELEMENT_CACHE[slug] = 'neutral'
    return 'neutral'

# ==================== ЗАГРУЗКА КАРТ ====================

POSSIBLE_PATHS = [
    "wp-content/uploads/2026/07/",
    "wp-content/uploads/2026/06/",
    "wp-content/uploads/2026/05/",
    "wp-content/uploads/",
    "2026/07/",
    "2026/06/",
    "2026/05/",
    "wp-content/uploads/2024/05/",
    "wp-content/uploads/2024/06/",
]

def fetch_photo(path, full_filename, headers):
    photo_url = urljoin("https://ep-ccg.ru", f"{path.strip('/')}/{full_filename}")
    try:
        res = requests.get(photo_url, headers=headers, timeout=4)
        if res.status_code == 200:
            return res.content, photo_url
    except:
        pass
    return None, photo_url

def download_card_image(card_name_ru, prefix="bgo-"):
    cleaned = card_name_ru.strip().lower()
    lat = to_lat(cleaned)
    ideal = prefix + lat + ".webp"
    filename = get_smart_filename(ideal)
    headers = {'User-Agent': 'Mozilla/5.0'}
    with ThreadPoolExecutor(max_workers=len(POSSIBLE_PATHS)) as executor:
        futures = [executor.submit(fetch_photo, path, filename, headers) for path in POSSIBLE_PATHS]
        for future in as_completed(futures):
            content, _ = future.result()
            if content:
                return content
    return None

# ==================== ШРИФТ ====================

def get_font(size):
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
    ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except:
                pass
    return ImageFont.load_default()

# ==================== СБОРКА ИЗОБРАЖЕНИЯ КОЛОДЫ ====================

CARD_W = 280
CARD_H = 48
COST_W = 36
COUNT_W = 40
PADDING = 3
HEADER_H = 80
BG_COLOR = (18, 22, 30)
HEADER_COLOR = (200, 150, 30)
SUBHEADER_COLOR = (100, 200, 80)

def build_deck_image(hero_name, total_cards, max_cards, cards):
    font_header = get_font(26)
    font_sub = get_font(16)
    font_card = get_font(17)
    font_cost = get_font(20)
    font_count = get_font(17)

    num_cards = len(cards)
    img_h = HEADER_H + num_cards * (CARD_H + PADDING) + PADDING
    img_w = CARD_W

    canvas = Image.new("RGB", (img_w, img_h), BG_COLOR)
    draw = ImageDraw.Draw(canvas)

    draw.text((12, 12), hero_name, font=font_header, fill=HEADER_COLOR)
    draw.text((12, 46), f"Карт: {total_cards} / {max_cards}", font=font_sub, fill=SUBHEADER_COLOR)

    y = HEADER_H
    for cost, name, count, img_bytes, element_key in cards:
        row_y = y
        element_color = ELEMENT_COLORS.get(element_key, DEFAULT_ELEMENT_COLOR)
        art_w = CARD_W - COST_W - COUNT_W

        if img_bytes:
            try:
                card_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                scale = CARD_H / card_img.height
                new_w = int(card_img.width * scale)
                card_img = card_img.resize((new_w, CARD_H), Image.Resampling.BILINEAR)
                start_x = max(0, (new_w - art_w) // 2)
                card_img = card_img.crop((start_x, 0, start_x + art_w, CARD_H))
                canvas.paste(card_img, (COST_W, row_y))
            except:
                draw.rectangle([COST_W, row_y, CARD_W - COUNT_W, row_y + CARD_H], fill=(40, 45, 55))
        else:
            draw.rectangle([COST_W, row_y, CARD_W - COUNT_W, row_y + CARD_H], fill=(40, 45, 55))

        overlay = Image.new("RGBA", (art_w, CARD_H), (0, 0, 0, 110))
        canvas.paste(Image.new("RGB", overlay.size, (20, 25, 35)), (COST_W, row_y), overlay)

        draw.rectangle([0, row_y, COST_W - 1, row_y + CARD_H], fill=element_color)
        cost_str = str(cost)
        bbox = draw.textbbox((0, 0), cost_str, font=font_cost)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(((COST_W - tw) // 2, row_y + (CARD_H - th) // 2 - 2), cost_str, font=font_cost, fill=(0, 0, 0))

        draw.text((COST_W + 6, row_y + (CARD_H - 17) // 2), name, font=font_card, fill=(255, 255, 255))

        draw.rectangle([CARD_W - COUNT_W, row_y, CARD_W, row_y + CARD_H], fill=element_color)
        count_str = f"{count}x"
        bbox2 = draw.textbbox((0, 0), count_str, font=font_count)
        tw2, th2 = bbox2[2] - bbox2[0], bbox2[3] - bbox2[1]
        draw.text((CARD_W - COUNT_W + (COUNT_W - tw2) // 2, row_y + (CARD_H - th2) // 2 - 1),
                  count_str, font=font_count, fill=(0, 0, 0))

        draw.rectangle([0, row_y + CARD_H, CARD_W, row_y + CARD_H + PADDING], fill=BG_COLOR)
        y += CARD_H + PADDING

    output = io.BytesIO()
    canvas.save(output, format="JPEG", quality=92)
    return output.getvalue()

# ==================== ПАРСИНГ КОЛОДЫ ====================

def parse_deck_text(text):
    hero_name = ""
    cards = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("###"):
            hero_name = line.lstrip("#").strip()
            continue
        m = re.match(r"#\s*(\d+)x\s*\((\d+)\)\s*(.+)", line)
        if m:
            count = int(m.group(1))
            cost = int(m.group(2))
            name = m.group(3).strip()
            cards.append((count, cost, name))
    return hero_name, cards

# ==================== ОСНОВНОЙ БОТ ====================

def run_vk_bot():
    update_site_files_index()
    while True:
        try:
            vk_session = vk_api.VkApi(token=VK_TOKEN, api_version='5.199')
            bot_longpoll = VkBotLongPoll(vk_session, group_id=GROUP_ID)
            print("Бот успешно запущен и слушает ВК...", flush=True)

            while True:
                try:
                    events = bot_longpoll.check()
                    for event in events:
                        if event.type == VkBotEventType.MESSAGE_NEW:
                            message_obj = event.obj.message
                            raw_text = message_obj.get('text', '').strip()
                            peer_id = message_obj.get('peer_id')

                            text = re.sub(r'\[club\d+\|@?[^\]]+\]\s*', '', raw_text).strip()
                            text_lower = text.lower()

                            # ==================== !deck ====================
                            if text_lower.startswith("!deck"):
                                deck_text = text[5:].strip()
                                if not deck_text:
                                    vk_session.method('messages.send', {
                                        'peer_id': peer_id,
                                        'message': "Использование: !deck [текст колоды из декбилдера]",
                                        'random_id': 0
                                    })
                                    continue

                                hero_name, cards = parse_deck_text(deck_text)
                                if not cards:
                                    vk_session.method('messages.send', {
                                        'peer_id': peer_id,
                                        'message': "❌ Не удалось распознать колоду. Вставьте текст из декбилдера полностью.",
                                        'random_id': 0
                                    })
                                    continue

                                total_cards = sum(c[0] for c in cards)

                                def load_card(item):
                                    count, cost, name = item
                                    img = download_card_image(name, prefix="bgo-")
                                    element = get_card_element(name)
                                    return cost, name, count, img, element

                                with ThreadPoolExecutor(max_workers=10) as executor:
                                    card_data = list(executor.map(load_card, cards))

                                card_data.sort(key=lambda x: x[0])

                                img_bytes = build_deck_image(
                                    hero_name or "Колода",
                                    total_cards,
                                    60,
                                    card_data
                                )

                                up_srv = vk_session.method('photos.getMessagesUploadServer', {'peer_id': peer_id})
                                upload_url = up_srv['response']['upload_url'] if 'response' in up_srv else up_srv['upload_url']
                                upload_resp = requests.post(upload_url, files={'photo': ('deck.jpg', img_bytes, 'image/jpeg')}).json()
                                save_resp = vk_session.method('photos.saveMessagesPhoto', {
                                    'photo': upload_resp['photo'],
                                    'server': upload_resp['server'],
                                    'hash': upload_resp['hash']
                                })
                                actual_data = save_resp['response'] if 'response' in save_resp else save_resp
                                attachment = f"photo{actual_data[0]['owner_id']}_{actual_data[0]['id']}"

                                vk_session.method('messages.send', {
                                    'peer_id': peer_id,
                                    'message': "",
                                    'attachment': attachment,
                                    'random_id': 0
                                })
                                continue

                            # ==================== !бго / !бк ====================
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

                            cache_key = f"{chosen_command}_{card_name_ru}"
                            game_title = "Берсерк Герои" if chosen_command == "!бго" else "Берсерк Классика"
                            response_msg = f"🃏 [{game_title}] Карта: {card_name_ru.capitalize()}\n\nБаза карт: ep-ccg.ru"

                            if cache_key in ATTACHMENT_CACHE:
                                vk_session.method('messages.send', {
                                    'peer_id': peer_id,
                                    'message': response_msg,
                                    'attachment': ATTACHMENT_CACHE[cache_key],
                                    'random_id': 0
                                })
                                continue

                            cleaned_text = card_name_ru.replace(" ", "-").replace("_", "-")
                            card_name_lat = to_lat(cleaned_text)
                            prefix = "bgo-" if chosen_command == "!бго" else "bk-"
                            ideal_filename = prefix + card_name_lat + ".webp"
                            full_filename = get_smart_filename(ideal_filename)

                            photo_content = None
                            headers = {'User-Agent': 'Mozilla/5.0'}
                            with ThreadPoolExecutor(max_workers=len(POSSIBLE_PATHS)) as executor:
                                futures = [executor.submit(fetch_photo, path, full_filename, headers) for path in POSSIBLE_PATHS]
                                for future in as_completed(futures):
                                    content, _ = future.result()
                                    if content:
                                        photo_content = content
                                        break

                            if photo_content:
                                try:
                                    img = Image.open(io.BytesIO(photo_content)).convert("RGBA")
                                    canvas_size = 800
                                    white_bg = Image.new("RGBA", (canvas_size, canvas_size), (255, 255, 255, 255))
                                    scale = canvas_size / img.height
                                    card_width = int(img.width * scale)
                                    img = img.resize((card_width, canvas_size), Image.Resampling.BILINEAR)
                                    white_bg.paste(img, ((canvas_size - card_width) // 2, 0), img)
                                    output = io.BytesIO()
                                    white_bg.convert("RGB").save(output, format="JPEG", quality=90)

                                    up_srv = vk_session.method('photos.getMessagesUploadServer', {'peer_id': peer_id})
                                    upload_url = up_srv['response']['upload_url'] if 'response' in up_srv else up_srv['upload_url']
                                    upload_resp = requests.post(upload_url, files={'photo': ('card.jpg', output.getvalue(), 'image/jpeg')}).json()
                                    save_resp = vk_session.method('photos.saveMessagesPhoto', {
                                        'photo': upload_resp['photo'],
                                        'server': upload_resp['server'],
                                        'hash': upload_resp['hash']
                                    })
                                    actual_data = save_resp['response'] if 'response' in save_resp else save_resp
                                    attachment = f"photo{actual_data[0]['owner_id']}_{actual_data[0]['id']}"
                                    ATTACHMENT_CACHE[cache_key] = attachment

                                    vk_session.method('messages.send', {
                                        'peer_id': peer_id,
                                        'message': response_msg,
                                        'attachment': attachment,
                                        'random_id': 0
                                    })
                                except Exception as e:
                                    vk_session.method('messages.send', {
                                        'peer_id': peer_id,
                                        'message': f"❌ Ошибка ВК: {e}",
                                        'random_id': 0
                                    })
                            else:
                                vk_session.method('messages.send', {
                                    'peer_id': peer_id,
                                    'message': f"❌ Карта не найдена!\nФайл: {full_filename}",
                                    'random_id': 0
                                })

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
