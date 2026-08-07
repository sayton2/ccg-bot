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
import random
import traceback
from PIL import Image, ImageDraw, ImageFont
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
import difflib

app = Flask(__name__)

@app.route('/')
def home():
    return "Многопользовательский бот активен", 200

# ==================== НАСТРОЙКИ ====================
VK_TOKEN = os.environ.get("VK_TOKEN", "")
GROUP_ID = int(os.environ.get("GROUP_ID", 202318207))
ELEMENT_CACHE_FILE = "element_cache.json"
# ====================================================

def rnd_id():
    return random.randint(0, 2**31)

RULES = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'j', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'cz', 'ч': 'ch', 'ш': 'sh', 'щ': 'shh',
    'ы': 'y', 'э': 'e', 'ю': 'yu', 'я': 'ya', 'ь': '', 'ъ': ''
}

API_ELEMENT_MAP = {
    'forest': 'les', 'steppe': 'stepi', 'mountains': 'gory', 'mountain': 'gory',
    'swamp': 'boloto', 'darkness': 'tma', 'dark': 'tma',
    'nejtraly': 'nejtraly', 'neutral': 'nejtraly',
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
            links = re.findall(r'(?:href|src|data-src|data-lazy-src)__?="([^"]+\.webp)"', res.text, re.IGNORECASE)
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

# ==================== API-ПОИСК КАРТЫ (по русскому названию) ====================

def resolve_card_via_api(card_name_ru):
    """Ищет карту через WP REST API по русскому названию.
    Возвращает (image_bytes, element_key) или (None, None).
    Надёжнее транслитерации — сайт сам отдаёт правильный slug и URL картинки."""
    try:
        res = requests.get(
            "https://ep-ccg.ru/wp-json/wp/v2/mmf_card",
            params={
                'search': card_name_ru,
                '_fields': 'id,featured_media,title,class_list'
            },
            headers=BROWSER_HEADERS, timeout=7
        )
        print(f"[API SEARCH] '{card_name_ru}' status={res.status_code}", flush=True)
        if res.status_code != 200 or not res.text.strip():
            return None, None

        data = res.json()
        if not data or not isinstance(data, list) or len(data) == 0:
            return None, None

        # Точное совпадение по названию; иначе берём первый результат
        target = card_name_ru.strip().lower()
        card = None
        for c in data:
            title = c.get('title', {}).get('rendered', '').strip().lower()
            if title == target:
                card = c
                break
        if not card:
            card = data[0]

        # Элемент из class_list
        element_key = 'nejtraly'
        for cls in card.get('class_list', []):
            m = re.match(r'mmf_element-(\w+)', cls)
            if m:
                raw = m.group(1)
                element_key = API_ELEMENT_MAP.get(raw, 'nejtraly')
                break

        # Кэшируем стихию
        slug = card.get('slug', to_lat(card_name_ru.strip().lower()))
        ELEMENT_CACHE[slug] = element_key
        save_element_cache(ELEMENT_CACHE)

        # URL картинки через media endpoint
        media_id = card.get('featured_media')
        if not media_id:
            return None, element_key

        media_res = requests.get(
            f"https://ep-ccg.ru/wp-json/wp/v2/media/{media_id}",
            params={'_fields': 'source_url'},
            headers=BROWSER_HEADERS, timeout=7
        )
        if media_res.status_code != 200:
            return None, element_key
        image_url = media_res.json().get('source_url')
        if not image_url:
            return None, element_key

        img_res = requests.get(image_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        if img_res.status_code == 200:
            return img_res.content, element_key

    except Exception as e:
        print(f"[API RESOLVE ERROR] {card_name_ru}: {e}", flush=True)
    return None, None

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
    "wp-content/uploads/2026/08/",
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

def _try_fetch_filename(filename, headers):
    with ThreadPoolExecutor(max_workers=len(POSSIBLE_PATHS)) as executor:
        futures = [executor.submit(fetch_photo, path, filename, headers) for path in POSSIBLE_PATHS]
        for future in as_completed(futures):
            content, _ = future.result()
            if content:
                return content
    return None

def download_card_image(card_name_ru, prefix="bgo-"):
    # Сначала пробуем API — надёжно, без транслитерации
    img, _ = resolve_card_via_api(card_name_ru)
    if img:
        print(f"[CARD] API нашёл: {card_name_ru}", flush=True)
        return img

    # Фолбэк: старый способ через транслитерацию
    cleaned = card_name_ru.strip().lower()
    lat = to_lat(cleaned)
    ideal = prefix + lat + ".webp"
    headers = {'User-Agent': 'Mozilla/5.0'}
    content = _try_fetch_filename(ideal, headers)
    if content:
        return content
    smart = get_smart_filename(ideal)
    if smart != ideal:
        print(f"[CARD] Точное не найдено, пробую smart: {ideal} -> {smart}", flush=True)
        content = _try_fetch_filename(smart, headers)
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

# ==================== СБОРКА ИЗОБРАЖЕНИЯ КОЛОДЫ (в стиле декбилдера v41) ====================

CARD_W    = 480
CARD_H    = 64
COST_W    = 44
COUNT_W   = 64
BORDER_W  = 8
PADDING   = 5
HEADER_H  = 80
BG_COLOR        = (7, 7, 7)         # #070707
PANEL_COLOR     = (17, 17, 17)      # #111
HEADER_COLOR    = (241, 196, 15)    # #f1c40f
SUBHEADER_COLOR = (85, 85, 85)     # #555
COUNTER_OK      = (39, 174, 96)    # #27ae60
COUNTER_ERR     = (231, 76, 60)   # #e74c3c
TEXT_WHITE      = (255, 255, 255)
TEXT_BLACK      = (0, 0, 0)

ELEMENT_DATA = {
    'stepi':    {'color': (241, 196,  15), 'text': (0, 0, 0),     'alpha': (180, 150,   0)},
    'gory':     {'color': ( 41, 128, 185), 'text': (255,255,255), 'alpha': ( 20,  80, 160)},
    'boloto':   {'color': (168, 213, 162), 'text': (0, 0, 0),     'alpha': (100, 170, 100)},
    'les':      {'color': ( 39, 174,  96), 'text': (255,255,255), 'alpha': ( 15, 110,  50)},
    'tma':      {'color': (142,  68, 173), 'text': (255,255,255), 'alpha': ( 80,  20, 120)},
    'nejtraly': {'color': (205, 127,  50), 'text': (255,255,255), 'alpha': (130,  80,  20)},
}
DEFAULT_ELEMENT = ELEMENT_DATA['nejtraly']


def _make_gradient_overlay(width, height, elem_alpha_rgb):
    """Градиент как в декбилдере:
       linear-gradient(90deg, elem_alpha 0%, rgba(0,0,0,0.55) 45%, rgba(0,0,0,0.05) 100%)"""
    grad_line = Image.new("RGBA", (width, 1), (0, 0, 0, 0))
    for x in range(width):
        t = x / max(1, width - 1)
        if t < 0.45:
            lt = t / 0.45
            r = int(elem_alpha_rgb[0] * (1 - lt))
            g = int(elem_alpha_rgb[1] * (1 - lt))
            b = int(elem_alpha_rgb[2] * (1 - lt))
            a = int((0.93 * (1 - lt) + 0.55 * lt) * 255)
        else:
            lt = (t - 0.45) / 0.55
            r, g, b = 0, 0, 0
            a = int((0.55 * (1 - lt) + 0.05 * lt) * 255)
        grad_line.putpixel((x, 0), (r, g, b, a))
    return grad_line.resize((width, height))


def build_deck_image(hero_name, total_cards, max_cards, cards):
    font_hero    = get_font(22)
    font_counter = get_font(20)
    font_cost    = get_font(22)
    font_title   = get_font(18)
    font_count   = get_font(18)

    img_h = HEADER_H + len(cards) * (CARD_H + PADDING) + PADDING
    canvas = Image.new("RGB", (CARD_W, img_h), PANEL_COLOR)
    draw = ImageDraw.Draw(canvas)

    # Заголовок
    draw.text((14, 12), hero_name, font=font_hero, fill=HEADER_COLOR)

    # Счётчик: зелёный если >=40, красный если >60
    counter_text = f"Карт: {total_cards} / {max_cards}"
    if total_cards > max_cards:
        counter_color = COUNTER_ERR
    elif total_cards >= 40:
        counter_color = COUNTER_OK
    else:
        counter_color = SUBHEADER_COLOR
    draw.text((14, 44), counter_text, font=font_counter, fill=counter_color)

    y = HEADER_H
    for cost, name, count, img_bytes, element_key in cards:
        row_y = y
        ed = ELEMENT_DATA.get(element_key, DEFAULT_ELEMENT)
        elem_color = ed['color']
        elem_text  = ed['text']
        elem_alpha_rgb = ed['alpha']

        # Фон: арт карты, zoom 160%, center 30% (верх с лицом)
        row_bg = Image.new("RGB", (CARD_W, CARD_H), PANEL_COLOR)
        if img_bytes:
            try:
                card_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                zoom = 1.6
                zw = int(card_img.width * zoom)
                zh = int(card_img.height * zoom)
                card_img = card_img.resize((zw, zh), Image.Resampling.BILINEAR)
                center_x = zw // 2
                center_y = int(zh * 0.30)
                left = max(0, min(center_x - CARD_W // 2, zw - CARD_W))
                top  = max(0, min(center_y - CARD_H // 2, zh - CARD_H))
                row_bg = card_img.crop((left, top, left + CARD_W, top + CARD_H))
            except:
                pass

        # Градиент-оверлей поверх арта
        overlay = _make_gradient_overlay(CARD_W, CARD_H, elem_alpha_rgb)
        row_rgba = row_bg.convert("RGBA")
        row_rgba = Image.alpha_composite(row_rgba, overlay)
        canvas.paste(row_rgba.convert("RGB"), (0, row_y))

        # Border-left: сплошной цвет стихии слева
        draw.rectangle([0, row_y, BORDER_W, row_y + CARD_H - 1], fill=elem_color)

        # Стоимость: по центру слева, белый с тенью
        cost_str = str(cost)
        bbox = draw.textbbox((0, 0), cost_str, font=font_cost)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        cost_x = BORDER_W + (COST_W - tw) // 2 - bbox[0]
        cost_y = row_y + (CARD_H - th) // 2 - bbox[1] - 1
        for dx, dy in [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(1,1),(-1,1),(1,-1)]:
            draw.text((cost_x + dx, cost_y + dy), cost_str, font=font_cost, fill=TEXT_BLACK)
        draw.text((cost_x, cost_y), cost_str, font=font_cost, fill=TEXT_WHITE)

        # Название: flex, белый, text-shadow, обрезка с …
        title_x = BORDER_W + COST_W + 4
        title_max_w = CARD_W - title_x - COUNT_W
        title = name
        if draw.textlength(title, font=font_title) > title_max_w:
            ellipsis_w = draw.textlength("…", font=font_title)
            while len(title) > 1 and draw.textlength(title, font=font_title) + ellipsis_w > title_max_w:
                title = title[:-1]
            title = title + "…"
        bbox_t = draw.textbbox((0, 0), title, font=font_title)
        title_y = row_y + (CARD_H - (bbox_t[3] - bbox_t[1])) // 2 - bbox_t[1] - 1
        draw.text((title_x + 1, title_y + 1), title, font=font_title, fill=TEXT_BLACK)
        draw.text((title_x, title_y), title, font=font_title, fill=TEXT_WHITE)

        # Количество: фон = цвет стихии, текст = цвет элемента (чёрный для степей/болота)
        count_x = CARD_W - COUNT_W
        draw.rectangle([count_x, row_y, CARD_W, row_y + CARD_H], fill=elem_color)
        count_str = f"{count}x"
        bbox_c = draw.textbbox((0, 0), count_str, font=font_count)
        cw, ch = bbox_c[2] - bbox_c[0], bbox_c[3] - bbox_c[1]
        cx = count_x + (COUNT_W - cw) // 2 - bbox_c[0]
        cy = row_y + (CARD_H - ch) // 2 - bbox_c[1] - 1
        draw.text((cx, cy), count_str, font=font_count, fill=elem_text)

        y += CARD_H + PADDING

    output = io.BytesIO()
    canvas.save(output, format="JPEG", quality=85)
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

# ==================== ОТПРАВКА КАРТИНОК В ВК ====================

def upload_and_get_attachment(vk_session, img_bytes, filename, peer_id):
    last_error = None
    for attempt in range(5):
        try:
            # Свежий URL для каждой попытки
            up_srv = vk_session.method('photos.getMessagesUploadServer', {'peer_id': peer_id})
            upload_url = up_srv['response']['upload_url'] if 'response' in up_srv else up_srv['upload_url']

            upload_resp = requests.post(
                upload_url,
                files={'photo': (filename, img_bytes, 'image/jpeg')},
                timeout=30
            ).json()

            print(f"[UPLOAD] attempt={attempt+1} resp={upload_resp}", flush=True)

            photo_val = upload_resp.get('photo')
            if not photo_val or photo_val == '[]':
                last_error = f"empty photo: {upload_resp}"
                print(f"[UPLOAD RETRY] {last_error}", flush=True)
                time.sleep(2 + attempt * 2)
                continue

            save_resp = vk_session.method('photos.saveMessagesPhoto', {
                'photo':  upload_resp.get('photo', ''),
                'server': upload_resp.get('server', ''),
                'hash':   upload_resp.get('hash', '')
            })
            actual_data = save_resp['response'] if 'response' in save_resp else save_resp
            return f"photo{actual_data[0]['owner_id']}_{actual_data[0]['id']}"

        except Exception as e:
            last_error = str(e)
            print(f"[UPLOAD ERROR] attempt={attempt+1}: {e}", flush=True)
            time.sleep(2 + attempt * 2)

    raise RuntimeError(f"Upload failed: {last_error}")

# ==================== ОБРАБОТКА ОДНОГО СООБЩЕНИЯ ====================

def handle_message(vk_session, message_obj):
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
                'random_id': rnd_id()
            })
            return

        print(f"[DECK] Получен текст длиной {len(deck_text)}", flush=True)
        hero_name, cards = parse_deck_text(deck_text)
        print(f"[DECK] Герой: '{hero_name}', карт: {len(cards)}", flush=True)

        if not cards:
            vk_session.method('messages.send', {
                'peer_id': peer_id,
                'message': "Не удалось распознать колоду. Вставьте текст из игры полностью.",
                'random_id': rnd_id()
            })
            return

        total_cards = sum(c[0] for c in cards)

        def load_card(item):
            count, cost, name = item
            img, element = resolve_card_via_api(name)
            if not img:
                img = download_card_image(name, prefix="bgo-")
            if not element or element == 'nejtraly':
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

        attachment = upload_and_get_attachment(vk_session, img_bytes, 'deck.jpg', peer_id)
        vk_session.method('messages.send', {
            'peer_id': peer_id,
            'message': " ",
            'attachment': attachment,
            'random_id': rnd_id()
        })
        print(f"[DECK] Отправлено!", flush=True)
        return

    # ==================== !бго / !бк ====================
    chosen_command = None
    for command in ["!бго", "!бк"]:
        if text_lower.startswith(command + " "):
            chosen_command = command
            break
    if not chosen_command:
        return

    card_name_ru = text[len(chosen_command) + 1:].strip().lower()
    if not card_name_ru:
        return

    cache_key  = f"{chosen_command}_{card_name_ru}"
    game_title = "Берсерк Герои" if chosen_command == "!бго" else "Берсерк Классика"
    response_msg = f"🃏 [{game_title}] Карта: {card_name_ru.capitalize()}\n\nБаза карт: ep-ccg.ru"

    if cache_key in ATTACHMENT_CACHE:
        vk_session.method('messages.send', {
            'peer_id': peer_id,
            'message': response_msg,
            'attachment': ATTACHMENT_CACHE[cache_key],
            'random_id': rnd_id()
        })
        return

    # Сначала пробуем API — надёжно, без транслитерации
    photo_content, _ = resolve_card_via_api(card_name_ru)
    full_filename = "api"
    if not photo_content:
        cleaned_text   = card_name_ru.replace(" ", "-").replace("_", "-")
        card_name_lat  = to_lat(cleaned_text)
        prefix         = "bgo-" if chosen_command == "!бго" else "bk-"
        ideal_filename = prefix + card_name_lat + ".webp"
        headers = {'User-Agent': 'Mozilla/5.0'}

        photo_content = _try_fetch_filename(ideal_filename, headers)
        if not photo_content:
            smart_filename = get_smart_filename(ideal_filename)
            if smart_filename != ideal_filename:
                print(f"[CARD] Точное не найдено, пробую smart: {ideal_filename} -> {smart_filename}", flush=True)
                photo_content = _try_fetch_filename(smart_filename, headers)
            full_filename = smart_filename
        else:
            full_filename = ideal_filename

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

            attachment = upload_and_get_attachment(vk_session, output.getvalue(), 'card.jpg', peer_id)
            ATTACHMENT_CACHE[cache_key] = attachment

            vk_session.method('messages.send', {
                'peer_id': peer_id,
                'message': response_msg,
                'attachment': attachment,
                'random_id': rnd_id()
            })
        except Exception as e:
            print(f"[CARD ERROR] {e}", flush=True)
            traceback.print_exc()
            vk_session.method('messages.send', {
                'peer_id': peer_id,
                'message': f"Ошибка: {e}",
                'random_id': rnd_id()
            })
    else:
        vk_session.method('messages.send', {
            'peer_id': peer_id,
            'message': f"Карта не найдена: {full_filename}",
            'random_id': rnd_id()
        })

# ==================== ОСНОВНОЙ БОТ (с авто-восстановлением) ====================

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
                            t = threading.Thread(
                                target=_safe_handle,
                                args=(vk_session, event.obj.message),
                                daemon=True
                            )
                            t.start()
                except Exception as e:
                    print(f"[LOOP ERROR] {e} — reconnect через 3 сек", flush=True)
                    traceback.print_exc()
                    time.sleep(3)
        except Exception as e:
            print(f"[BOT ERROR] {e} — полный рестарт через 5 сек", flush=True)
            traceback.print_exc()
            time.sleep(5)

def _safe_handle(vk_session, message_obj):
    """Обёртка: ловит любые ошибки и сообщает пользователю реальную ошибку."""
    try:
        handle_message(vk_session, message_obj)
    except Exception as e:
        print(f"[HANDLE ERROR] {e}", flush=True)
        traceback.print_exc()
        try:
            peer_id = message_obj.get('peer_id')
            if peer_id:
                vk_session.method('messages.send', {
                    'peer_id': peer_id,
                    'message': f"⚠️ Ошибка: {e}\n\nПопробуйте ещё раз.",
                    'random_id': rnd_id()
                })
        except:
            pass

if __name__ == '__main__':
    bot_thread = threading.Thread(target=run_vk_bot)
    bot_thread.daemon = True
    bot_thread.start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

