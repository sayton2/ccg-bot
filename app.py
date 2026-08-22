# -*- coding: utf-8 -*-
# CardHero Connect — VK бот для карточной игры «Берсерк»
# Возможности: поиск карт, визуализация колод, конкурс «Угадай карту» (ротация 3 типов подсказок)
# Рейтинг чата сбрасывается 1-го числа каждого месяца автоматически.

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
import datetime
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
import difflib

app = Flask(__name__)

@app.route('/')
def home():
    return "CardHero Connect — бот активен", 200

# ==================== НАСТРОЙКИ ====================
VK_TOKEN = os.environ.get("VK_TOKEN", "")
GROUP_ID = int(os.environ.get("GROUP_ID", 202318207))
OWNER_ID = int(os.environ.get("OWNER_ID", 0))

ELEMENT_CACHE_FILE   = "element_cache.json"
SCORES_FILE          = "chat_scores.json"
CONTEST_FILE         = "contest_state.json"
CONTEST_CHATS_FILE   = "contest_chats.json"
CLUE_INDEX_FILE      = "clue_index.json"
MOSCOW_OFFSET = datetime.timedelta(hours=3)

CLUE_TYPES = ["blur", "text", "fragment"]

def rnd_id():
    return random.randint(0, 2**31)

def moscow_now():
    return datetime.datetime.utcnow() + MOSCOW_OFFSET
# ====================================================

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
CARD_IMAGE_CACHE = {}
CARD_META_CACHE = {}
SITE_FILES_INDEX = []
INDEX_LOCK = threading.Lock()
CACHE_LOCK = threading.Lock()

# ==================== КЭШ И СОСТОЯНИЕ ====================

def load_json(filename, default):
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return default

def save_json(filename, data):
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        print(f"[SAVE ERROR] {filename}: {e}", flush=True)

ELEMENT_CACHE  = load_json(ELEMENT_CACHE_FILE, {})
CHAT_SCORES    = load_json(SCORES_FILE, {})
CONTEST_STATE  = load_json(CONTEST_FILE, {})
CONTEST_CHATS  = load_json(CONTEST_CHATS_FILE, [])
CLUE_INDEX     = load_json(CLUE_INDEX_FILE, {"index": 0})
print(f"[CACHE] Стихий: {len(ELEMENT_CACHE)}, Чатов в конкурсе: {len(CONTEST_CHATS)}", flush=True)

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
                print(f"Индекс обновлён! Карт: {len(SITE_FILES_INDEX)}", flush=True)
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

# ==================== API-ПОИСК КАРТЫ ====================

def resolve_card_meta(card_name_ru):
    key = card_name_ru.strip().lower()
    with CACHE_LOCK:
        if key in CARD_META_CACHE:
            return CARD_META_CACHE[key]

    def _extract_card(card):
        element_key = 'nejtraly'
        for cls in card.get('class_list', []):
            m = re.match(r'mmf_element-(\w+)', cls)
            if m:
                element_key = API_ELEMENT_MAP.get(m.group(1), 'nejtraly')
                break
        slug = card.get('slug', to_lat(key))
        media_id = card.get('featured_media')
        return (slug, media_id, element_key)

    # 1. Поиск по slug — точное совпадение (надёжнее для новых карт)
    slug_candidate = to_lat(key)
    try:
        res = requests.get(
            "https://ep-ccg.ru/wp-json/wp/v2/mmf_card",
            params={'slug': slug_candidate, '_fields': 'id,featured_media,title,class_list,slug'},
            headers=BROWSER_HEADERS, timeout=7
        )
        if res.status_code == 200 and res.text.strip():
            data = res.json()
            if data and isinstance(data, list) and len(data) > 0:
                result = _extract_card(data[0])
                with CACHE_LOCK:
                    CARD_META_CACHE[key] = result
                ELEMENT_CACHE[result[0]] = result[2]
                save_json(ELEMENT_CACHE_FILE, ELEMENT_CACHE)
                return result
    except Exception as e:
        print(f"[META SLUG ERROR] {card_name_ru}: {e}", flush=True)

    # 2. Полнотекстовый поиск с увеличенным лимитом
    try:
        res = requests.get(
            "https://ep-ccg.ru/wp-json/wp/v2/mmf_card",
            params={'search': card_name_ru, 'per_page': 50, '_fields': 'id,featured_media,title,class_list,slug'},
            headers=BROWSER_HEADERS, timeout=7
        )
        if res.status_code != 200 or not res.text.strip():
            return None
        data = res.json()
        if not data or not isinstance(data, list) or len(data) == 0:
            return None
        target = key
        card = None
        for c in data:
            if c.get('title', {}).get('rendered', '').strip().lower() == target:
                card = c
                break
        if not card:
            card = data[0]
        result = _extract_card(card)
        with CACHE_LOCK:
            CARD_META_CACHE[key] = result
        ELEMENT_CACHE[result[0]] = result[2]
        save_json(ELEMENT_CACHE_FILE, ELEMENT_CACHE)
        return result
    except Exception as e:
        print(f"[META ERROR] {card_name_ru}: {e}", flush=True)
    return None

def download_card_image_fast(card_name_ru):
    key = card_name_ru.strip().lower()
    with CACHE_LOCK:
        if key in CARD_IMAGE_CACHE:
            return CARD_IMAGE_CACHE[key]
    meta = resolve_card_meta(card_name_ru)
    if not meta:
        return None, None
    slug, media_id, element_key = meta
    if not media_id:
        return None, element_key
    try:
        media_res = requests.get(f"https://ep-ccg.ru/wp-json/wp/v2/media/{media_id}",
                                 params={'_fields': 'source_url'}, headers=BROWSER_HEADERS, timeout=7)
        if media_res.status_code != 200:
            return None, element_key
        image_url = media_res.json().get('source_url')
        if not image_url:
            return None, element_key
        img_res = requests.get(image_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        if img_res.status_code == 200:
            result = (img_res.content, element_key)
            with CACHE_LOCK:
                CARD_IMAGE_CACHE[key] = result
            return result
    except Exception as e:
        print(f"[IMG DOWNLOAD ERROR] {card_name_ru}: {e}", flush=True)
    return None, element_key

# ==================== СТИХИЯ КАРТЫ ====================

def get_card_element(card_name_ru):
    slug = to_lat(card_name_ru.strip().lower())
    if slug in ELEMENT_CACHE:
        return ELEMENT_CACHE[slug]
    meta = resolve_card_meta(card_name_ru)
    if meta:
        return meta[2]
    if slug not in ELEMENT_CACHE:
        ELEMENT_CACHE[slug] = 'nejtraly'
    return ELEMENT_CACHE[slug]

# ==================== ЗАГРУЗКА КАРТ (FALLBACK) ====================

POSSIBLE_PATHS = [
    "wp-content/uploads/2026/08/", "wp-content/uploads/2026/07/",
    "wp-content/uploads/2026/06/", "wp-content/uploads/2026/05/",
    "wp-content/uploads/", "wp-content/uploads/2024/06/", "wp-content/uploads/2024/05/",
]

def fetch_photo(path, full_filename, headers):
    photo_url = urljoin("https://ep-ccg.ru", f"{path.strip('/')}/{full_filename}")
    try:
        res = requests.get(photo_url, headers=headers, timeout=4)
        if res.status_code == 200:
            return res.content
    except:
        pass
    return None

def _try_fetch_filename(filename, headers):
    with ThreadPoolExecutor(max_workers=len(POSSIBLE_PATHS)) as executor:
        futures = [executor.submit(fetch_photo, path, filename, headers) for path in POSSIBLE_PATHS]
        for future in as_completed(futures):
            content = future.result()
            if content:
                return content
    return None

def download_card_image(card_name_ru, prefix="bgo-"):
    img, elem = download_card_image_fast(card_name_ru)
    if img:
        return img
    cleaned = card_name_ru.strip().lower()
    lat = to_lat(cleaned)
    ideal = prefix + lat + ".webp"
    headers = {'User-Agent': 'Mozilla/5.0'}
    content = _try_fetch_filename(ideal, headers)
    if content:
        return content
    smart = get_smart_filename(ideal)
    if smart != ideal:
        content = _try_fetch_filename(smart, headers)
        if content:
            return content
    return None

# ==================== ШРИФТ ====================

def get_font(size):
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except:
                pass
    return ImageFont.load_default()

# ==================== СБОРКА ИЗОБРАЖЕНИЯ КОЛОДЫ ====================

CARD_W, CARD_H = 480, 64
COST_W, COUNT_W, BORDER_W, PADDING = 44, 64, 8, 5
HEADER_H = 80
PANEL_COLOR     = (17, 17, 17)
HEADER_COLOR    = (241, 196, 15)
SUBHEADER_COLOR = (85, 85, 85)
COUNTER_OK      = (39, 174, 96)
COUNTER_ERR     = (231, 76, 60)
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

    draw.text((14, 12), hero_name, font=font_hero, fill=HEADER_COLOR)
    counter_text = f"Карт: {total_cards} / {max_cards}"
    counter_color = COUNTER_ERR if total_cards > max_cards else (COUNTER_OK if total_cards >= 40 else SUBHEADER_COLOR)
    draw.text((14, 44), counter_text, font=font_counter, fill=counter_color)

    y = HEADER_H
    for cost, name, count, img_bytes, element_key in cards:
        row_y = y
        ed = ELEMENT_DATA.get(element_key, DEFAULT_ELEMENT)
        elem_color, elem_text = ed['color'], ed['text']
        elem_alpha_rgb = ed['alpha']

        row_bg = Image.new("RGB", (CARD_W, CARD_H), PANEL_COLOR)
        if img_bytes:
            try:
                card_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                zw, zh = int(card_img.width * 1.6), int(card_img.height * 1.6)
                card_img = card_img.resize((zw, zh), Image.Resampling.BILINEAR)
                left = max(0, min(zw // 2 - CARD_W // 2, zw - CARD_W))
                top  = max(0, min(int(zh * 0.30) - CARD_H // 2, zh - CARD_H))
                row_bg = card_img.crop((left, top, left + CARD_W, top + CARD_H))
            except:
                pass

        overlay = _make_gradient_overlay(CARD_W, CARD_H, elem_alpha_rgb)
        row_rgba = row_bg.convert("RGBA")
        row_rgba = Image.alpha_composite(row_rgba, overlay)
        canvas.paste(row_rgba.convert("RGB"), (0, row_y))

        draw.rectangle([0, row_y, BORDER_W, row_y + CARD_H - 1], fill=elem_color)

        cost_str = str(cost)
        bbox = draw.textbbox((0, 0), cost_str, font=font_cost)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        cost_x = BORDER_W + (COST_W - tw) // 2 - bbox[0]
        cost_y = row_y + (CARD_H - th) // 2 - bbox[1] - 1
        for dx, dy in [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(1,1),(-1,1),(1,-1)]:
            draw.text((cost_x + dx, cost_y + dy), cost_str, font=font_cost, fill=TEXT_BLACK)
        draw.text((cost_x, cost_y), cost_str, font=font_cost, fill=TEXT_WHITE)

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
            cards.append((int(m.group(1)), int(m.group(2)), m.group(3).strip()))
    return hero_name, cards

# ==================== ОТПРАВКА КАРТИНОК В ВК ====================

def upload_and_get_attachment(vk_session, img_bytes, filename, peer_id):
    last_error = None
    for attempt in range(5):
        try:
            up_srv = vk_session.method('photos.getMessagesUploadServer', {'peer_id': peer_id})
            upload_url = up_srv['response']['upload_url'] if 'response' in up_srv else up_srv['upload_url']
            upload_resp = requests.post(upload_url, files={'photo': (filename, img_bytes, 'image/jpeg')}, timeout=30).json()
            photo_val = upload_resp.get('photo')
            if not photo_val or photo_val == '[]':
                last_error = f"empty photo: {upload_resp}"
                time.sleep(2 + attempt * 2)
                continue
            save_resp = vk_session.method('photos.saveMessagesPhoto', {
                'photo': upload_resp.get('photo', ''), 'server': upload_resp.get('server', ''), 'hash': upload_resp.get('hash', '')
            })
            actual_data = save_resp['response'] if 'response' in save_resp else save_resp
            return f"photo{actual_data[0]['owner_id']}_{actual_data[0]['id']}"
        except Exception as e:
            last_error = str(e)
            time.sleep(2 + attempt * 2)
    raise RuntimeError(f"Upload failed: {last_error}")

# ==================== КОНКУРС «УГАДАЙ КАРТУ» ====================

def get_random_card():
    try:
        res = requests.get("https://ep-ccg.ru/wp-json/wp/v2/mmf_card",
                            params={'per_page': 1, '_fields': 'id'},
                            headers=BROWSER_HEADERS, timeout=10)
        if res.status_code != 200:
            return None
        total = int(res.headers.get('X-WP-Total', '0'))
        if total == 0:
            return None
        offset = random.randint(0, total - 1)
        res = requests.get("https://ep-ccg.ru/wp-json/wp/v2/mmf_card",
                           params={'per_page': 1, 'offset': offset,
                                   '_fields': 'id,title,featured_media,class_list,content,slug'},
                           headers=BROWSER_HEADERS, timeout=10)
        if res.status_code == 200 and res.json():
            return res.json()[0]
    except Exception as e:
        print(f"[RANDOM CARD ERROR] {e}", flush=True)
    return None

def make_blur_crop(img_bytes):
    try:
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        zw, zh = int(img.width * 2.5), int(img.height * 2.5)
        img = img.resize((zw, zh), Image.Resampling.BILINEAR)
        img = img.filter(ImageFilter.GaussianBlur(radius=18))
        crop_size = 400
        left = random.randint(0, max(0, zw - crop_size))
        top  = random.randint(0, max(0, int(zh * 0.60) - crop_size))
        cropped = img.crop((left, top, left + crop_size, top + crop_size))
        output = io.BytesIO()
        cropped.save(output, format="JPEG", quality=85)
        return output.getvalue()
    except Exception as e:
        print(f"[BLUR CROP ERROR] {e}", flush=True)
        return None

def make_fragment_crop(img_bytes):
    try:
        img = Image.open(io.BytesIO(img_bytes)).convert("L")
        zw, zh = int(img.width * 2.5), int(img.height * 2.5)
        img = img.resize((zw, zh), Image.Resampling.BILINEAR)
        frag_size = 80
        left = random.randint(0, max(0, zw - frag_size))
        top  = random.randint(0, max(0, int(zh * 0.60) - frag_size))
        cropped = img.crop((left, top, left + frag_size, top + frag_size))
        cropped = cropped.resize((400, 400), Image.Resampling.NEAREST)
        output = io.BytesIO()
        cropped.save(output, format="JPEG", quality=80)
        return output.getvalue()
    except Exception as e:
        print(f"[FRAGMENT CROP ERROR] {e}", flush=True)
        return None

def start_contest(vk_session):
    global CONTEST_STATE, CLUE_INDEX
    if not CONTEST_CHATS:
        print("[CONTEST] Белый список пуст — конкурс не запущен", flush=True)
        return
    card = get_random_card()
    if not card:
        print("[CONTEST] Не удалось получить карту", flush=True)
        return
    card_name = card.get('title', {}).get('rendered', '').strip()
    card_slug = card.get('slug', '')
    if not card_name:
        return
    element_key = 'nejtraly'
    for cls in card.get('class_list', []):
        m = re.match(r'mmf_element-(\w+)', cls)
        if m:
            element_key = API_ELEMENT_MAP.get(m.group(1), 'nejtraly')
            break
    img_bytes = None
    media_id = card.get('featured_media')
    if media_id:
        try:
            media_res = requests.get(f"https://ep-ccg.ru/wp-json/wp/v2/media/{media_id}",
                                     params={'_fields': 'source_url'}, headers=BROWSER_HEADERS, timeout=7)
            if media_res.status_code == 200:
                image_url = media_res.json().get('source_url')
                if image_url:
                    img_res = requests.get(image_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
                    if img_res.status_code == 200:
                        img_bytes = img_res.content
        except:
            pass
    content_html = card.get('content', {}).get('rendered', '')
    card_text = re.sub(r'<[^>]+>', '', content_html).strip()

    idx = CLUE_INDEX.get('index', 0) % len(CLUE_TYPES)
    clue_type = CLUE_TYPES[idx]
    CLUE_INDEX['index'] = (idx + 1) % len(CLUE_TYPES)
    save_json(CLUE_INDEX_FILE, CLUE_INDEX)
    print(f"[CONTEST] Тип подсказки сегодня: {clue_type} (карта: «{card_name}»)", flush=True)

    new_state = {}
    for chat_id in CONTEST_CHATS:
        new_state[str(chat_id)] = {
            'card_name': card_name, 'card_slug': card_slug, 'element': element_key,
            'started_at': moscow_now().isoformat(), 'guessed': False, 'revealed': False,
            'clue_type': clue_type
        }
    CONTEST_STATE = new_state
    save_json(CONTEST_FILE, CONTEST_STATE)

    for chat_id in CONTEST_CHATS:
        try:
            send_contest_clue(vk_session, chat_id, clue_type, img_bytes, card_text)
        except Exception as e:
            print(f"[CONTEST SEND ERROR] chat={chat_id}: {e}", flush=True)

def send_contest_clue(vk_session, chat_id, clue_type, img_bytes, card_text):
    if clue_type == "text":
        clue = card_text if card_text else "Карта из вселенной Берсерк"
        vk_session.method('messages.send', {
            'peer_id': chat_id,
            'message': f"🎯 Угадай карту по описанию!\n\n«{clue}»\n\nПервый правильный ответ — +10 баллов. Ответ будет раскрыт в 23:55.",
            'random_id': rnd_id()
        })
        return

    if clue_type == "blur" and img_bytes:
        crop = make_blur_crop(img_bytes)
        if crop:
            attachment = upload_and_get_attachment(vk_session, crop, 'clue.jpg', chat_id)
            vk_session.method('messages.send', {
                'peer_id': chat_id,
                'message': "🎯 Угадай карту!\n\nНа картинке — сильно размытый фрагмент арта. Что это за карта? Первый правильный ответ — +10 баллов.",
                'attachment': attachment, 'random_id': rnd_id()
            })
            return

    if clue_type == "fragment" and img_bytes:
        crop = make_fragment_crop(img_bytes)
        if crop:
            attachment = upload_and_get_attachment(vk_session, crop, 'clue.jpg', chat_id)
            vk_session.method('messages.send', {
                'peer_id': chat_id,
                'message': "🎯 Угадай карту!\n\nНа картинке — мелкий чёрно-белый фрагмент арта. Что это за карта? Первый правильный ответ — +10 баллов.",
                'attachment': attachment, 'random_id': rnd_id()
            })
            return

    clue = card_text if card_text else "Карта из вселенной Берсерк"
    vk_session.method('messages.send', {
        'peer_id': chat_id,
        'message': f"🎯 Угадай карту по описанию!\n\n«{clue}»\n\nПервый правильный ответ — +10 баллов. Ответ будет раскрыт в 23:55.",
        'random_id': rnd_id()
    })

def normalize_text(text):
    return re.sub(r'\s+', ' ', text.strip().lower())

def check_contest_answer(vk_session, peer_id, user_id, user_name, text):
    state = CONTEST_STATE.get(str(peer_id))
    if not state or state.get('guessed') or state.get('revealed'):
        return False
    if normalize_text(text) == normalize_text(state['card_name']):
        state['guessed'] = True
        save_json(CONTEST_FILE, CONTEST_STATE)
        add_score(peer_id, user_id, user_name, 10)
        vk_session.method('messages.send', {
            'peer_id': peer_id,
            'message': f"🎉 {user_name} угадал(а)! Это «{state['card_name']}».\n+10 баллов в рейтинг!",
            'random_id': rnd_id()
        })
        try:
            img, _ = download_card_image_fast(state['card_name'])
            if img:
                attachment = upload_and_get_attachment(vk_session, img, 'card.jpg', peer_id)
                vk_session.method('messages.send', {
                    'peer_id': peer_id, 'message': state['card_name'],
                    'attachment': attachment, 'random_id': rnd_id()
                })
        except:
            pass
        return True
    return False

def end_contest_timeout(vk_session):
    global CONTEST_STATE
    changed = False
    for chat_id_str, state in CONTEST_STATE.items():
        if not state.get('guessed') and not state.get('revealed'):
            chat_id = int(chat_id_str)
            state['revealed'] = True
            changed = True
            try:
                vk_session.method('messages.send', {
                    'peer_id': chat_id,
                    'message': f"⏰ Время вышло! Никто не угадал.\nЭто была карта «{state['card_name']}».",
                    'random_id': rnd_id()
                })
                img, _ = download_card_image_fast(state['card_name'])
                if img:
                    attachment = upload_and_get_attachment(vk_session, img, 'card.jpg', chat_id)
                    vk_session.method('messages.send', {
                        'peer_id': chat_id, 'message': state['card_name'],
                        'attachment': attachment, 'random_id': rnd_id()
                    })
            except Exception as e:
                print(f"[CONTEST TIMEOUT ERROR] chat={chat_id}: {e}", flush=True)
    if changed:
        save_json(CONTEST_FILE, CONTEST_STATE)
        print("[CONTEST] Тайм-аут: ответы раскрыты", flush=True)

# ==================== УПРАВЛЕНИЕ БЕЛЫМ СПИСКОМ ЧАТОВ ====================

def is_owner(user_id):
    return OWNER_ID and user_id == OWNER_ID

def add_contest_chat(peer_id):
    if peer_id not in CONTEST_CHATS:
        CONTEST_CHATS.append(peer_id)
        save_json(CONTEST_CHATS_FILE, CONTEST_CHATS)
        return True
    return False

def remove_contest_chat(peer_id):
    if peer_id in CONTEST_CHATS:
        CONTEST_CHATS.remove(peer_id)
        save_json(CONTEST_CHATS_FILE, CONTEST_CHATS)
        CONTEST_STATE.pop(str(peer_id), None)
        save_json(CONTEST_FILE, CONTEST_STATE)
        return True
    return False

def show_contest_chats(vk_session, peer_id):
    if not CONTEST_CHATS:
        msg = "📋 Белый список пуст.\nНапишите «!конкурс +» в чате, чтобы добавить его."
    else:
        lines = [f"📋 Чаты в конкурсе ({len(CONTEST_CHATS)}):"]
        for i, cid in enumerate(CONTEST_CHATS, 1):
            tag = " ← этот чат" if cid == peer_id else ""
            lines.append(f"{i}. {cid}{tag}")
        msg = "\n".join(lines)
    vk_session.method('messages.send', {'peer_id': peer_id, 'message': msg, 'random_id': rnd_id()})

# ==================== РЕЙТИНГ ЧАТА (С АВТОСБРОСОМ 1-ГО ЧИСЛА) ====================

def reset_chat_scores(chat_id_str):
    if chat_id_str in CHAT_SCORES:
        for uid in list(CHAT_SCORES[chat_id_str].keys()):
            if uid != '_reset_month':
                if isinstance(CHAT_SCORES[chat_id_str][uid], dict):
                    CHAT_SCORES[chat_id_str][uid]['score'] = 0
        CHAT_SCORES[chat_id_str]['_reset_month'] = moscow_now().strftime('%Y-%m')
        save_json(SCORES_FILE, CHAT_SCORES)
        print(f"[SCORES] Рейтинг чата {chat_id_str} сброшен (1-е число)", flush=True)

def reset_all_scores():
    if not CHAT_SCORES:
        return
    current_month = moscow_now().strftime('%Y-%m')
    for chat_id_str in list(CHAT_SCORES.keys()):
        reset_chat_scores(chat_id_str)
    print(f"[SCORES] Полный сброс всех рейтингов ({current_month})", flush=True)

def check_monthly_reset(chat_id_str):
    current_month = moscow_now().strftime('%Y-%m')
    if chat_id_str not in CHAT_SCORES:
        CHAT_SCORES[chat_id_str] = {'_reset_month': current_month}
        return
    if CHAT_SCORES[chat_id_str].get('_reset_month') != current_month:
        reset_chat_scores(chat_id_str)

def add_score(chat_id, user_id, user_name, points):
    chat_id_str = str(chat_id)
    user_id_str = str(user_id)
    check_monthly_reset(chat_id_str)
    if user_id_str not in CHAT_SCORES[chat_id_str] or not isinstance(CHAT_SCORES[chat_id_str][user_id_str], dict):
        CHAT_SCORES[chat_id_str][user_id_str] = {'name': user_name, 'score': 0}
    CHAT_SCORES[chat_id_str][user_id_str]['name'] = user_name
    CHAT_SCORES[chat_id_str][user_id_str]['score'] += points
    save_json(SCORES_FILE, CHAT_SCORES)

def fetch_users_names(vk_session, user_ids):
    if not user_ids:
        return {}
    names = {}
    try:
        result = vk_session.method('users.get', {'user_ids': ','.join(str(uid) for uid in user_ids)})
        users = result if isinstance(result, list) else result.get('response', [])
        for u in users:
            uid = str(u.get('id', ''))
            full = f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
            if uid and full:
                names[uid] = full
    except Exception as e:
        print(f"[NAMES FETCH ERROR] {e}", flush=True)
    return names

def refresh_chat_names(vk_session, chat_id_str):
    chat_data = CHAT_SCORES.get(chat_id_str, {})
    user_ids = [uid for uid in chat_data.keys() if uid != '_reset_month' and uid.isdigit()]
    if not user_ids:
        return
    fresh_names = fetch_users_names(vk_session, user_ids)
    updated = False
    for uid in user_ids:
        new_name = fresh_names.get(uid)
        if new_name and chat_data[uid].get('name') != new_name:
            chat_data[uid]['name'] = new_name
            updated = True
    if updated:
        save_json(SCORES_FILE, CHAT_SCORES)

def show_top(vk_session, peer_id):
    chat_id_str = str(peer_id)
    check_monthly_reset(chat_id_str)
    refresh_chat_names(vk_session, chat_id_str)
    scores = CHAT_SCORES.get(chat_id_str, {})
    entries = [(uid, data) for uid, data in scores.items() if uid != '_reset_month' and isinstance(data, dict)]
    entries.sort(key=lambda x: x[1].get('score', 0), reverse=True)

    if not entries:
        vk_session.method('messages.send', {
            'peer_id': peer_id,
            'message': "📊 Рейтинг чата пуст.\nПишите сообщения (+1 балл) и угадывайте карты (+10 баллов)!",
            'random_id': rnd_id()
        })
        return

    lines = ["📊 Рейтинг чата за этот месяц:\n"]
    for i, (uid, data) in enumerate(entries[:10], 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        name = data.get('name', '???')
        score = data.get('score', 0)
        lines.append(f"{medal} {name} — {score} баллов")
    lines.append(f"\nВсего игроков: {len(entries)}")
    lines.append(f"\n📅 Сброс рейтинга — 1-го числа каждого месяца")
    vk_session.method('messages.send', {'peer_id': peer_id, 'message': "\n".join(lines), 'random_id': rnd_id()})

# ==================== ПЛАНИРОВЩИКИ ====================

def contest_scheduler(vk_session):
    last_start = None
    last_end   = None
    while True:
        try:
            now = moscow_now()
            today = now.strftime('%Y-%m-%d')
            if now.hour == 20 and now.minute == 0 and last_start != today:
                last_start = today
                start_contest(vk_session)
            if now.hour == 23 and now.minute == 55 and last_end != today:
                last_end = today
                end_contest_timeout(vk_session)
        except Exception as e:
            print(f"[SCHEDULER ERROR] {e}", flush=True)
        time.sleep(20)

def monthly_reset_scheduler():
    last_reset_month = moscow_now().strftime('%Y-%m')
    while True:
        try:
            now = moscow_now()
            current_month = now.strftime('%Y-%m')
            if now.day == 1 and current_month != last_reset_month:
                print(f"[MONTHLY RESET] 1-е число месяца — сброс всех рейтингов...", flush=True)
                reset_all_scores()
                last_reset_month = current_month
        except Exception as e:
            print(f"[MONTHLY RESET ERROR] {e}", flush=True)
        time.sleep(1800)

# ==================== ОБРАБОТКА СООБЩЕНИЙ ====================

def get_user_name(vk_session, user_id):
    try:
        result = vk_session.method('users.get', {'user_ids': user_id})
        users = result if isinstance(result, list) else result.get('response', [])
        if users:
            return f"{users[0].get('first_name', '')} {users[0].get('last_name', '')}".strip()
    except:
        pass
    return "Игрок"

def handle_message(vk_session, message_obj):
    raw_text = message_obj.get('text', '').strip()
    peer_id  = message_obj.get('peer_id')
    user_id  = message_obj.get('from_id')

    text_clean = re.sub(r'\[club\d+\|@?[^\]]+\]\s*', '', raw_text).strip()
    text_lower = text_clean.lower()

    if text_lower in ("!конкурс +", "!конкурс+", "!конкурс добавить"):
        if is_owner(user_id):
            added = add_contest_chat(peer_id)
            msg = "✅ Чат добавлен в конкурс! Каждый день в 20:00 — «Угадай карту»." if added else "ℹ️ Этот чат уже в конкурсе."
        else:
            msg = "❌ Только владелец бота может управлять конкурсом."
        vk_session.method('messages.send', {'peer_id': peer_id, 'message': msg, 'random_id': rnd_id()})
        return

    if text_lower in ("!конкурс -", "!конкурс-", "!конкурс удалить"):
        if is_owner(user_id):
            removed = remove_contest_chat(peer_id)
            msg = "✅ Чат удалён из конкурса." if removed else "ℹ️ Этого чата не было в конкурсе."
        else:
            msg = "❌ Только владелец бота может управлять конкурсом."
        vk_session.method('messages.send', {'peer_id': peer_id, 'message': msg, 'random_id': rnd_id()})
        return

    if text_lower in ("!конкурс список", "!конкурс"):
        if is_owner(user_id):
            show_contest_chats(vk_session, peer_id)
        else:
            vk_session.method('messages.send', {
                'peer_id': peer_id, 'message': "❌ Только владелец бота может смотреть список чатов.",
                'random_id': rnd_id()
            })
        return

    in_contest = peer_id in CONTEST_CHATS
    if in_contest and user_id and user_id > 0:
        user_name = get_user_name(vk_session, user_id)
        add_score(peer_id, user_id, user_name, 1)
        check_contest_answer(vk_session, peer_id, user_id, user_name, raw_text)

    if text_lower in ("!топ", "!top"):
        show_top(vk_session, peer_id)
        return

    if text_lower.startswith("!deck"):
        deck_text = text_clean[5:].strip()
        if not deck_text:
            vk_session.method('messages.send', {
                'peer_id': peer_id, 'message': "Использование: !deck [текст колоды из игры]",
                'random_id': rnd_id()
            })
            return
        hero_name, cards = parse_deck_text(deck_text)
        if not cards:
            vk_session.method('messages.send', {
                'peer_id': peer_id, 'message': "Не удалось распознать колоду. Вставьте текст из игры полностью.",
                'random_id': rnd_id()
            })
            return
        total_cards = sum(c[0] for c in cards)

        def load_card(item):
            count, cost, name = item
            img, element = download_card_image_fast(name)
            if not img:
                img = download_card_image(name, prefix="bgo-")
            if not element or element == 'nejtraly':
                element = get_card_element(name)
            return cost, name, count, img, element

        with ThreadPoolExecutor(max_workers=20) as executor:
            card_data = list(executor.map(load_card, cards))
        card_data.sort(key=lambda x: x[0])

        img_bytes = build_deck_image(hero_name or "Колода", total_cards, 60, card_data)
        attachment = upload_and_get_attachment(vk_session, img_bytes, 'deck.jpg', peer_id)
        vk_session.method('messages.send', {
            'peer_id': peer_id, 'message': " ", 'attachment': attachment, 'random_id': rnd_id()
        })
        return

    chosen_command = None
    for command in ["!бго", "!бк"]:
        if text_lower.startswith(command + " "):
            chosen_command = command
            break
    if not chosen_command:
        return

    card_name_ru = text_clean[len(chosen_command) + 1:].strip().lower()
    if not card_name_ru:
        return

    cache_key  = f"{chosen_command}_{card_name_ru}"
    game_title = "Берсерк Герои" if chosen_command == "!бго" else "Берсерк Классика"
    response_msg = f"🃏 [{game_title}] Карта: {card_name_ru.capitalize()}\n\nБаза карт: ep-ccg.ru"

    if cache_key in ATTACHMENT_CACHE:
        vk_session.method('messages.send', {
            'peer_id': peer_id, 'message': response_msg,
            'attachment': ATTACHMENT_CACHE[cache_key], 'random_id': rnd_id()
        })
        return

    photo_content, _ = download_card_image_fast(card_name_ru)
    full_filename = "api"
    if not photo_content:
        cleaned_text  = card_name_ru.replace(" ", "-").replace("_", "-")
        card_name_lat = to_lat(cleaned_text)
        prefix        = "bgo-" if chosen_command == "!бго" else "bk-"
        ideal_filename = prefix + card_name_lat + ".webp"
        headers = {'User-Agent': 'Mozilla/5.0'}
        photo_content = _try_fetch_filename(ideal_filename, headers)
        if not photo_content:
            smart_filename = get_smart_filename(ideal_filename)
            if smart_filename != ideal_filename:
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
                'peer_id': peer_id, 'message': response_msg,
                'attachment': attachment, 'random_id': rnd_id()
            })
        except Exception as e:
            print(f"[CARD ERROR] {e}", flush=True)
            traceback.print_exc()
            vk_session.method('messages.send', {
                'peer_id': peer_id, 'message': f"Ошибка: {e}", 'random_id': rnd_id()
            })
    else:
        vk_session.method('messages.send', {
            'peer_id': peer_id, 'message': f"Карта не найдена: {full_filename}", 'random_id': rnd_id()
        })

def _safe_handle(vk_session, message_obj):
    try:
        handle_message(vk_session, message_obj)
    except Exception as e:
        print(f"[HANDLE ERROR] {e}", flush=True)
        traceback.print_exc()
        try:
            peer_id = message_obj.get('peer_id')
            if peer_id:
                vk_session.method('messages.send', {
                    'peer_id': peer_id, 'message': f"⚠️ Ошибка: {e}", 'random_id': rnd_id()
                })
        except:
            pass

# ==================== ОСНОВНОЙ БОТ ====================

def run_vk_bot():
    update_site_files_index()
    vk_session = vk_api.VkApi(token=VK_TOKEN, api_version='5.199')
    threading.Thread(target=contest_scheduler, args=(vk_session,), daemon=True).start()
    threading.Thread(target=monthly_reset_scheduler, daemon=True).start()
    print(f"Планировщики запущены: конкурс ({len(CONTEST_CHATS)} чатов) + ежемесячный сброс рейтинга", flush=True)
    if not OWNER_ID:
        print("⚠️ OWNER_ID не задан — управление конкурсом недоступно!", flush=True)

    while True:
        try:
            bot_longpoll = VkBotLongPoll(vk_session, group_id=GROUP_ID)
            print("Бот успешно запущен и слушает ВК...", flush=True)
            while True:
                try:
                    events = bot_longpoll.check()
                    for event in events:
                        if event.type == VkBotEventType.MESSAGE_NEW:
                            threading.Thread(target=_safe_handle, args=(vk_session, event.obj.message), daemon=True).start()
                except Exception as e:
                    print(f"[LOOP ERROR] {e} — reconnect через 3 сек", flush=True)
                    traceback.print_exc()
                    time.sleep(3)
        except Exception as e:
            print(f"[BOT ERROR] {e} — рестарт через 5 сек", flush=True)
            traceback.print_exc()
            time.sleep(5)

if __name__ == '__main__':
    bot_thread = threading.Thread(target=run_vk_bot)
    bot_thread.daemon = True
    bot_thread.start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
  

