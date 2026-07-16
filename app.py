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
import json
import traceback
from PIL import Image, ImageDraw, ImageFont
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
import difflib
import math

app = Flask(__name__)

@app.route('/')
def home():
    return "Многопользовательский бот активен", 200

# ==================== НАСТРОЙКИ ====================
VK_TOKEN = os.environ.get("VK_TOKEN", "")
GROUP_ID = int(os.environ.get("GROUP_ID", 202318207))
ELEMENT_CACHE_FILE = "element_cache.json"
# ====================================================

RULES = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'j', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'cz', 'ч': 'ch', 'ш': 'sh', 'щ': 'shh',
    'ы': 'y', 'э': 'e', 'ю': 'yu', 'я': 'ya', 'ь': '', 'ъ': ''
}

# Цвета из декбилдера
ELEMENT_COLORS = {
    'stepi':    (241, 196,  15),   # #f1c40f Степи
    'gory':     ( 41, 128, 185),   # #2980b9 Горы
    'boloto':   (168, 213, 162),   # #a8d5a2 Болото
    'les':      ( 39, 174,  96),   # #27ae60 Лес
    'tma':      (142,  68, 173),   # #8e44ad Тьма
    'nejtraly': (205, 127,  50),   # #cd7f32 Нейтралы
}
ELEMENT_TEXT_COLORS = {
    'stepi':    (0, 0, 0),
    'gory':     (255, 255, 255),
    'boloto':   (0, 0, 0),
    'les':      (255, 255, 255),
    'tma':      (255, 255, 255),
    'nejtraly': (255, 255, 255),
}
DEFAULT_ELEMENT_COLOR      = (205, 127, 50)
DEFAULT_ELEMENT_TEXT_COLOR = (255, 255, 255)

# Маппинг: класс с сайта -> наш ключ
API_ELEMENT_MAP = {
    'forest':    'les',
    'steppe':    'stepi',
    'mountains': 'gory',
    'mountain':  'gory',
    'swamp':     'boloto',
    'darkness':  'tma',
    'dark':      'tma',
    'nejtraly':  'nejtraly',
    'neutral':   'nejtraly',
}

BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
    'Accept': 'application/json',
    'Accept-Language': 'ru-RU,ru;q=0.9',
}

ATTACHMENT_CACHE = {}
SITE_FILES_INDEX = []
INDEX_LOCK = threading.Lock()

# ==================== КЕШ СТИХИЙ ====================

def load_element_cache():
    try:
        with open(ELEMENT_CACHE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

def save_element_cache(cache):
    try:
        with open(ELEMENT_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception as e:
        print(f"[CACHE SAVE ERROR] {e}", flush=True)

ELEMENT_CACHE = load_element_cache()
print(f"[CACHE] Загружено {len(ELEMENT_CACHE)} стихий из файла", flush=True)

# ==================== ИНДЕКС САЙТА ====================

def update_site_files_index():
    global SITE_FILES_INDEX
    try:
        res = requests.get("https://ep-ccg.ru", headers=BROWSER_HEADERS, timeout=10)
        if res.status_code == 200:
            links = re.findall(r'href__="([^"]+\.webp)"', res.text, re.IGNORECASE)
            found = list(set([l.split('/')[-1] for l in links]))
            if found:
                with INDEX_LOCK:
                    SITE_FILES_INDEX = found
                print(f"Индекс обновлен! Карт: {len(SITE_FILES_INDEX)}", flush=True)
    except Exception as e:
        print(f"Ошибка индекса: {e}", flush=True)

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
        res = requests.get(url, headers=BROWSER_HEADERS, timeout=7)
        print(f"[ELEMENT] slug={slug} status={res.status_code}", flush=True)
        if res.status_code == 200:
            data = res.json()
            if data and isinstance(data, list) and len(data) > 0:
                for cls in data[0].get('class_list', []):
                    m = re.match(r'mmf_element-(\w+)', cls)
                    if m:
                        raw = m.group(1)
                        element = API_ELEMENT_MAP.get(raw, 'nejtraly')
                        ELEMENT_CACHE[slug] = element
                        save_element_cache(ELEMENT_CACHE)
                        print(f"[ELEMENT] OK: {slug} -> {raw} -> {element}", flush=True)
                        return element
        elif res.status_code == 447:
            print(f"[ELEMENT] 447 для {slug}", flush=True)
    except Exception as e:
        print(f"[ELEMENT ERROR] {slug}: {e}", flush=True)

    if slug not in ELEMENT_CACHE:
        ELEMENT_CACHE[slug] = 'nejtraly'
    return ELEMENT_CACHE[slug]

# ==================== ЗАГРУЗКА КАРТ ====================

POSSIBLE_PATHS = [
    "wp-content/uploads/2026/07/",
    "wp-content/uploads/2026/06/",
    "wp-content/uploads/2026/05/",
    "wp-content/uploads/",
    "wp-content/uploads/2024/06/",
    "wp-content/uploads/2024/05/",
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

CARD_W   = 300
CARD_H   = 52
COST_W   = 36
COUNT_W  = 42
PADDING  = 3
HEADER_H = 80
BG_COLOR        = (18, 22, 30)
HEADER_COLOR    = (200, 150, 30)
SUBHEADER_COLOR = (100, 200, 80)

def build_deck_image(hero_name, total_cards, max_cards, cards):
    font_header = get_font(26)
    font_sub    = get_font(16)
    font_card   = get_font(18)
    font_cost   = get_font(22)
    font_count  = get_font(18)

    CARD_W   = 340
    CARD_H   = 58
    HEX_R    = 24
    COST_W   = 48
    COUNT_W  = 54
    THUMB_S  = 48
    PADDING  = 2
    HEADER_H = 80

    BG_COLOR     = (30, 40, 55)
    BAR_COLOR    = (42, 55, 74)    # #2a374a
    HEX_COLOR    = (197, 165, 87)  # #c5a557 золото
    HEX_TEXT     = (46, 46, 46)    # #2e2e2e
    TEXT_COLOR   = (255, 255, 255)
    SHADOW_COLOR = (0, 0, 0)

    img_h = HEADER_H + len(cards) * (CARD_H + PADDING) + PADDING
    canvas = Image.new("RGB", (CARD_W, img_h), BG_COLOR)
    draw = ImageDraw.Draw(canvas)

    draw.text((14, 12), hero_name, font=font_header, fill=HEX_COLOR)
    draw.text((14, 48), f"Карт: {total_cards} / {max_cards}", font=font_sub, fill=(180, 200, 220))

    y = HEADER_H
    for cost, name, count, img_bytes, element_key in cards:
        row_y = y
        row_bottom = row_y + CARD_H
        element_color = ELEMENT_COLORS.get(element_key, DEFAULT_ELEMENT_COLOR)

        # --- Тёмно-синяя полоса ---
        bar_x = COST_W
        bar_w = CARD_W - COST_W - COUNT_W
        draw.rectangle([bar_x, row_y, bar_x + bar_w, row_bottom], fill=BAR_COLOR)

        # --- Круглый миниатюр карты (справа в полосе) ---
        thumb_x = bar_x + bar_w - THUMB_S - 6
        thumb_y = row_y + (CARD_H - THUMB_S) // 2
        if img_bytes:
            try:
                card_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                w, h = card_img.size
                cs = min(w, h)
                left = (w - cs) // 2
                top = max(0, int(h * 0.15))
                card_img = card_img.crop((left, top, left + cs, top + cs))
                card_img = card_img.resize((THUMB_S, THUMB_S), Image.Resampling.BILINEAR)
                mask = Image.new("L", (THUMB_S, THUMB_S), 0)
                ImageDraw.Draw(mask).ellipse([0, 0, THUMB_S - 1, THUMB_S - 1], fill=255)
                canvas.paste(card_img, (thumb_x, thumb_y), mask)
            except:
                pass

        # --- Название карты (с тенью) ---
        name_x = bar_x + 10
        name_y = row_y + (CARD_H - 18) // 2
        display_name = name
        bbox = draw.textbbox((0, 0), display_name, font=font_card)
        max_name_w = thumb_x - name_x - 8
        while (bbox[2] - bbox[0]) > max_name_w and len(display_name) > 3:
            display_name = display_name[:-1]
            bbox = draw.textbbox((0, 0), display_name, font=font_card)
        if display_name != name:
            display_name = display_name.rstrip('.') + "…"
        draw.text((name_x + 1, name_y + 1), display_name, font=font_card, fill=SHADOW_COLOR)
        draw.text((name_x, name_y), display_name, font=font_card, fill=TEXT_COLOR)

        # --- Шестиугольный бейдж стоимости ---
        hex_cx = COST_W // 2
        hex_cy = row_y + CARD_H // 2
        hex_pts = [(hex_cx + HEX_R * math.cos(math.pi / 3 * i - math.pi / 2),
                    hex_cy + HEX_R * math.sin(math.pi / 3 * i - math.pi / 2)) for i in range(6)]
        draw.polygon(hex_pts, fill=HEX_COLOR)
        cost_str = str(cost)
        bbox = draw.textbbox((0, 0), cost_str, font=font_cost)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((hex_cx - tw // 2 - bbox[0], hex_cy - th // 2 - bbox[1] - 2),
                  cost_str, font=font_cost, fill=HEX_TEXT)

        # --- Бейдж количества с шевроном ---
        qty_x = CARD_W - COUNT_W
        draw.rectangle([qty_x, row_y, CARD_W, row_bottom], fill=element_color)
        draw.polygon([(qty_x, row_y), (qty_x - 10, row_y + CARD_H // 2), (qty_x, row_bottom)],
                     fill=element_color)
        count_str = str(count)
        bbox2 = draw.textbbox((0, 0), count_str, font=font_count)
        tw2, th2 = bbox2[2] - bbox2[0], bbox2[3] - bbox2[1]
        draw.text((qty_x + (COUNT_W - tw2) // 2 - bbox2[0],
                   row_y + (CARD_H - th2) // 2 - bbox2[1] - 1),
                  count_str, font=font_count, fill=TEXT_COLOR)

        y += CARD_H + PADDING

    output = io.BytesIO()
    canvas.save(output, format="JPEG", quality=92)
    return output.getvalue()
# ==================== ПАРСИНГ КОЛОДЫ ====================

def parse_deck_text(text):
    hero_name = ""
    cards = []
    for line in text.splitlines():
        clean = re.sub(r'^#+\s*', '', line).strip()
        if not clean:
            continue
        m_hero = re.match(r'[Гг]ерой[:\s]+(.+)', clean)
        if m_hero:
            hero_name = m_hero.group(1).strip()
            continue
        m = re.match(r'(\d+)x\s*\((\d+)\)\s*(.+)', clean)
        if m:
            count = int(m.group(1))
            cost  = int(m.group(2))
            name  = m.group(3).strip()
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
                            peer_id  = message_obj.get('peer_id')

                            text = re.sub(r'\[club\d+\|@?[^\]]+\]\s*', '', raw_text).strip()
                            text_lower = text.lower()

                            # ==================== !deck ====================
                            if text_lower.startswith("!deck"):
                                deck_text = text[5:].strip()
                                if not deck_text:
                                    vk_session.method('messages.send', {
                                        'peer_id': peer_id,
                                        'message': "Использование: !deck [текст колоды из игры]",
                                        'random_id': 0
                                    })
                                    continue

                                print(f"[DECK] Получен текст длиной {len(deck_text)}", flush=True)
                                hero_name, cards = parse_deck_text(deck_text)
                                print(f"[DECK] Герой: '{hero_name}', карт: {len(cards)}", flush=True)

                                if not cards:
                                    vk_session.method('messages.send', {
                                        'peer_id': peer_id,
                                        'message': "Не удалось распознать колоду. Вставьте текст из игры полностью.",
                                        'random_id': 0
                                    })
                                    continue

                                total_cards = sum(c[0] for c in cards)

                                def load_card(item):
                                    count, cost, name = item
                                    img     = download_card_image(name, prefix="bgo-")
                                    element = get_card_element(name)
                                    return cost, name, count, img, element

                                with ThreadPoolExecutor(max_workers=10) as executor:
                                    card_data = list(executor.map(load_card, cards))
                                card_data.sort(key=lambda x: x[0])

                                print(f"[DECK] Карты загружены, собираю изображение...", flush=True)
                                img_bytes = build_deck_image(
                                    hero_name or "Колода",
                                    total_cards,
                                    60,
                                    card_data
                                )
                                print(f"[DECK] Изображение собрано, отправляю...", flush=True)

                                up_srv = vk_session.method('photos.getMessagesUploadServer', {'peer_id': peer_id})
                                upload_url = up_srv['response']['upload_url'] if 'response' in up_srv else up_srv['upload_url']
                                upload_resp = requests.post(upload_url, files={'photo': ('deck.jpg', img_bytes, 'image/jpeg')}).json()
                                save_resp = vk_session.method('photos.saveMessagesPhoto', {
                                    'photo': upload_resp['photo'],
                                    'server': upload_resp['server'],
                                    'hash': upload_resp['hash']
                                })
                                actual_data = save_resp['response'] if 'response' in save_resp else save_resp
                                attachment  = f"photo{actual_data[0]['owner_id']}_{actual_data[0]['id']}"

                                vk_session.method('messages.send', {
                                    'peer_id': peer_id,
                                    'message': "",
                                    'attachment': attachment,
                                    'random_id': 0
                                })
                                print(f"[DECK] Отправлено!", flush=True)
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

                            cache_key  = f"{chosen_command}_{card_name_ru}"
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

                            cleaned_text   = card_name_ru.replace(" ", "-").replace("_", "-")
                            card_name_lat  = to_lat(cleaned_text)
                            prefix         = "bgo-" if chosen_command == "!бго" else "bk-"
                            ideal_filename = prefix + card_name_lat + ".webp"
                            full_filename  = get_smart_filename(ideal_filename)

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
                                    attachment  = f"photo{actual_data[0]['owner_id']}_{actual_data[0]['id']}"
                                    ATTACHMENT_CACHE[cache_key] = attachment

                                    vk_session.method('messages.send', {
                                        'peer_id': peer_id,
                                        'message': response_msg,
                                        'attachment': attachment,
                                        'random_id': 0
                                    })
                                except Exception as e:
                                    print(f"[CARD ERROR] {e}", flush=True)
                                    traceback.print_exc()
                                    vk_session.method('messages.send', {
                                        'peer_id': peer_id,
                                        'message': f"Ошибка: {e}",
                                        'random_id': 0
                                    })
                            else:
                                vk_session.method('messages.send', {
                                    'peer_id': peer_id,
                                    'message': f"Карта не найдена: {full_filename}",
                                    'random_id': 0
                                })

                except Exception as e:
                    print(f"[LOOP ERROR] {e}", flush=True)
                    traceback.print_exc()
                    time.sleep(1)
                time.sleep(0.1)
        except Exception as e:
            print(f"[BOT ERROR] {e}", flush=True)
            traceback.print_exc()
            time.sleep(5)

if __name__ == '__main__':
    bot_thread = threading.Thread(target=run_vk_bot)
    bot_thread.daemon = True
    bot_thread.start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
