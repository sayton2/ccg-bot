# -*- coding: utf-8 -*-
# CardHero Connect — VK бот для карточной игры «Берсерк»
# Возможности: поиск карт, визуализация колод, конкурс «Угадай карту» (ротация 3 типов подсказок)
# Рейтинг чата сбрасывается 1-го числа каждого месяца автоматически.

import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
import requests
from requests.exceptions import ReadTimeout as RequestsReadTimeout
from urllib3.exceptions import ReadTimeoutError as Urllib3ReadTimeoutError
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
import sys
import base64
import zlib
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
import difflib

app = Flask(__name__)

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def healthcheck(path):
    """Отвечает 200 OK на любые веб-пинги Render / health-check."""
    return "CardHero Connect — бот активен", 200

# ==================== НАСТРОЙКИ ====================
VK_TOKEN = os.environ.get("VK_TOKEN", "")
GROUP_ID = int(os.environ.get("GROUP_ID", 202318207))
OWNER_ID = int(os.environ.get("OWNER_ID", 0))
ADMIN_VK_ID = int(os.environ.get("ADMIN_VK_ID", OWNER_ID or 0))

ELEMENT_CACHE_FILE   = "element_cache.json"
BOT_DATA_FILE        = "bot_data.json"          # единый снимок: scores + state + meta
CONTESTS_FILE        = "contests.json"          # legacy (миграция)
SCORES_FILE          = "chat_scores.json"       # legacy (миграция)
CONTEST_FILE         = "contest_state.json"     # legacy (миграция)
CONTEST_CHATS_FILE   = "contest_chats.json"
CLUE_INDEX_FILE      = "clue_index.json"
MOSCOW_OFFSET = datetime.timedelta(hours=3)

# GitHub Gist — облачный бэкап состояния (таблица лидеров, викторины, флаг сброса)
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GIST_ID = os.environ.get("GIST_ID", "").strip()
GIST_FILENAME = "bot_data.json"
GIST_DEBOUNCE_SEC = 2.5
GIST_HTTP_TIMEOUT = 8

CLUE_TYPES = ["blur", "text", "fragment"]
BASE_CONTEST_REWARD = 10
HINT_INTERVAL_SEC = 3600
# Доля стороны карты для кропа: старт → почасовые подсказки
BLUR_CROP_RATIOS = [0.22, 0.34, 0.48, 0.62, 0.78]
FRAGMENT_CROP_RATIOS = [0.20, 0.32, 0.45, 0.60, 0.75]
TEXT_REVEAL_RATIOS = [0.22, 0.40, 0.58, 0.75, 0.92]

ELEMENT_NAMES_RU = {
    'les': 'Лес', 'stepi': 'Степи', 'gory': 'Горы',
    'boloto': 'Болото', 'tma': 'Тьма', 'nejtraly': 'Нейтралы',
}
TYPE_NAMES_RU = {
    'creature': 'Существо', 'spell': 'Заклинание',
    'equipment': 'Экипировка', 'hero': 'Герой',
}

# Watchdog: мягкий контроль зависания long poll (без убийства на обычных ReadTimeout)
HEARTBEAT_TIMEOUT = 300  # секунд без heartbeat = рестарт
_last_heartbeat = time.time()
_heartbeat_lock = threading.Lock()

def update_heartbeat():
    global _last_heartbeat
    with _heartbeat_lock:
        _last_heartbeat = time.time()

def get_heartbeat_age():
    with _heartbeat_lock:
        return time.time() - _last_heartbeat

def watchdog_loop():
    """Фоновый поток: если long poll реально завис (нет heartbeat), перезапуск процесса."""
    while True:
        time.sleep(15)
        age = get_heartbeat_age()
        if age > HEARTBEAT_TIMEOUT:
            print(f"[WATCHDOG] Long poll завис (heartbeat {age:.0f}с) — принудительный рестарт процесса", flush=True)
            os._exit(1)
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
    'лес': 'les', 'степи': 'stepi', 'степь': 'stepi', 'горы': 'gory',
    'болото': 'boloto', 'тьма': 'tma', 'нейтральные': 'nejtraly', 'нейтрал': 'nejtraly',
}

BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
    'Accept': 'application/json',
    'Accept-Language': 'ru-RU,ru;q=0.9',
}

# Официальный бинарный формат колоды BHD1 (как decodeDeck в dekbilder)
BH_SIGNATURE = b'BHD1'
BH_ID_HIGH = 0x08005000
PUBLIC_DECKS_URL = "https://ep-ccg.ru/wp-json/berserk/v1/decks/public"
BERSERK_DATA_URL = "https://ep-ccg.ru/wp-json/berserk/v1/data"
DECK_VIEW_URL = "https://ep-ccg.ru/koloda/?deck_id={}"
PUBLIC_DECKS_TTL = 5 * 60  # кэш публичных колод, сек
GAME_DB_TTL = 30 * 60      # кэш базы карт/героев, сек

ATTACHMENT_CACHE = {}
CARD_IMAGE_CACHE = {}
CARD_META_CACHE = {}
SITE_FILES_INDEX = []
INDEX_LOCK = threading.Lock()
CACHE_LOCK = threading.Lock()

_GAME_DB = {'heroes': {}, 'cards': {}, 'by_title': {}, 'loaded_at': 0}
_PUBLIC_DECKS_CACHE = {'items': [], 'loaded_at': 0}
_GAME_DB_LOCK = threading.Lock()
_PUBLIC_DECKS_LOCK = threading.Lock()

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
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[SAVE ERROR] {filename}: {e}", flush=True)

# ==================== ОБЛАЧНОЕ СОСТОЯНИЕ (GitHub Gist + local bot_data.json) ====================

_state_lock = threading.Lock()
_gist_sync_lock = threading.Lock()
_gist_dirty = False
_gist_last_push = 0.0
_gist_worker_started = False
_BOT_STATE_SOURCE = 'empty'

def _normalize_bot_state(data):
    """Единая схема: scores (топ), state (викторины), meta (флаг месячного сброса)."""
    if not isinstance(data, dict):
        data = {}
    return {
        'scores': data.get('scores') if isinstance(data.get('scores'), dict) else {},
        'state': data.get('state') if isinstance(data.get('state'), dict) else {},
        'meta': data.get('meta') if isinstance(data.get('meta'), dict) else {},
        'updated_at': data.get('updated_at') or moscow_now().isoformat(),
    }

def _snapshot_bot_state():
    return _normalize_bot_state({
        'scores': CHAT_SCORES,
        'state': CONTEST_STATE,
        'meta': CONTEST_META,
        'updated_at': moscow_now().isoformat(),
    })

def _gist_headers():
    return {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json',
        'User-Agent': 'CardHeroConnect-VK-Bot',
    }

def _gist_api_url():
    # Корректный REST endpoint GitHub Gist API (не github.com/{id})
    return f'https://api.github.com/gists/{GIST_ID}'

def _fetch_state_from_gist():
    """GET gist → содержимое files[bot_data.json]."""
    if not (GITHUB_TOKEN and GIST_ID):
        return None
    try:
        res = requests.get(
            _gist_api_url(),
            headers=_gist_headers(),
            timeout=GIST_HTTP_TIMEOUT,
        )
        if res.status_code != 200:
            print(f"[GIST LOAD] HTTP {res.status_code}: {res.text[:200]}", flush=True)
            return None
        files = (res.json() or {}).get('files') or {}
        node = files.get(GIST_FILENAME) or {}
        content = node.get('content')
        if not content:
            # иногда большой файл отдаётся только по raw_url
            raw_url = node.get('raw_url')
            if raw_url:
                raw = requests.get(raw_url, headers=_gist_headers(), timeout=GIST_HTTP_TIMEOUT)
                if raw.status_code == 200 and raw.text:
                    content = raw.text
        if not content:
            print("[GIST LOAD] bot_data.json пуст или отсутствует в Gist", flush=True)
            return None
        data = json.loads(content)
        print("[GIST LOAD] Состояние загружено из GitHub Gist", flush=True)
        return _normalize_bot_state(data)
    except Exception as e:
        print(f"[GIST LOAD ERROR] {e}", flush=True)
        return None

def _push_state_to_gist(snapshot):
    """PATCH gist: обновляет files.bot_data.json."""
    if not (GITHUB_TOKEN and GIST_ID):
        return False
    try:
        payload = {
            'files': {
                GIST_FILENAME: {
                    'content': json.dumps(snapshot, ensure_ascii=False, indent=2),
                }
            }
        }
        res = requests.patch(
            _gist_api_url(),
            headers=_gist_headers(),
            json=payload,
            timeout=GIST_HTTP_TIMEOUT,
        )
        if res.status_code in (200, 201):
            print(f"[GIST SAVE] Синхронизировано ({snapshot.get('updated_at')})", flush=True)
            return True
        print(f"[GIST SAVE] HTTP {res.status_code}: {res.text[:240]}", flush=True)
        return False
    except Exception as e:
        print(f"[GIST SAVE ERROR] {e}", flush=True)
        return False

def _gist_flusher_loop():
    """Фоновая отправка в Gist с дебаунсом — не блокирует LongPoll."""
    global _gist_dirty, _gist_last_push
    while True:
        time.sleep(1.0)
        with _gist_sync_lock:
            if not _gist_dirty:
                continue
            if time.time() - _gist_last_push < GIST_DEBOUNCE_SEC:
                continue
            _gist_dirty = False
        try:
            with _state_lock:
                snap = _snapshot_bot_state()
            ok = _push_state_to_gist(snap)
            with _gist_sync_lock:
                _gist_last_push = time.time()
                if not ok:
                    # повторим позже
                    _gist_dirty = True
        except Exception as e:
            print(f"[GIST FLUSHER ERROR] {e}", flush=True)
            with _gist_sync_lock:
                _gist_dirty = True

def ensure_gist_worker():
    global _gist_worker_started
    if _gist_worker_started:
        return
    if not (GITHUB_TOKEN and GIST_ID):
        return
    t = threading.Thread(target=_gist_flusher_loop, name='gist-flusher', daemon=True)
    t.start()
    _gist_worker_started = True
    print("[GIST] Фоновая синхронизация запущена", flush=True)

def load_bot_state():
    """
    Приоритет:
    1) GitHub Gist (если заданы GITHUB_TOKEN + GIST_ID)
    2) локальный bot_data.json
    3) legacy contests.json / отдельные файлы
    """
    global _BOT_STATE_SOURCE
    data = None
    source = 'empty'

    if GITHUB_TOKEN and GIST_ID:
        data = _fetch_state_from_gist()
        if data:
            source = 'gist'

    if data is None:
        local = load_json(BOT_DATA_FILE, None)
        if isinstance(local, dict) and (local.get('scores') is not None or local.get('state') is not None):
            data = _normalize_bot_state(local)
            source = 'local_bot_data'

    if data is None:
        legacy = load_json(CONTESTS_FILE, None)
        if isinstance(legacy, dict) and ('state' in legacy or 'scores' in legacy or 'meta' in legacy):
            data = _normalize_bot_state(legacy)
            source = 'legacy_contests'
        else:
            data = _normalize_bot_state({
                'state': load_json(CONTEST_FILE, {}),
                'scores': load_json(SCORES_FILE, {}),
                'meta': {},
            })
            source = 'legacy_split'

    _BOT_STATE_SOURCE = source
    print(
        f"[BOT STATE] source={source}; scores={len(data['scores'])}, "
        f"quizzes={len(data['state'])}, meta_keys={list(data['meta'].keys())}",
        flush=True,
    )
    return data

def save_bot_state(sync_gist=True):
    """
    Пишет локальный bot_data.json сразу; Gist обновляет в фоне (debounce).
    Не бросает исключения наружу — сбои сети не роняют LongPoll.
    """
    global _gist_dirty
    try:
        with _state_lock:
            snap = _snapshot_bot_state()
        save_json(BOT_DATA_FILE, snap)
        # Дублируем в contests.json для обратной совместимости
        save_json(CONTESTS_FILE, {
            'state': snap['state'],
            'scores': snap['scores'],
            'meta': snap['meta'],
        })
        if sync_gist and GITHUB_TOKEN and GIST_ID:
            ensure_gist_worker()
            with _gist_sync_lock:
                _gist_dirty = True
    except Exception as e:
        print(f"[BOT STATE SAVE ERROR] {e}", flush=True)

def load_contests():
    """Совместимость: загружает единое состояние бота."""
    return load_bot_state()

def save_contests():
    """Совместимость: любое изменение прогресса → локально + Gist."""
    save_bot_state(sync_gist=True)

ELEMENT_CACHE  = load_json(ELEMENT_CACHE_FILE, {})
_contests_data = load_bot_state()
CHAT_SCORES    = _contests_data['scores']
CONTEST_STATE  = _contests_data['state']
CONTEST_META   = _contests_data.get('meta') or {}
CONTEST_CHATS  = load_json(CONTEST_CHATS_FILE, [])
CLUE_INDEX     = load_json(CLUE_INDEX_FILE, {"index": 0})
# Локальный кэш всегда; в Gist на старте пушим только миграцию legacy → облако
# (не затираем Gist пустым снимком, если GET временно упал)
save_bot_state(sync_gist=False)
if _BOT_STATE_SOURCE.startswith('legacy') or _BOT_STATE_SOURCE == 'local_bot_data':
    if GITHUB_TOKEN and GIST_ID and (CHAT_SCORES or CONTEST_STATE or CONTEST_META):
        save_bot_state(sync_gist=True)
ensure_gist_worker()

# FIX: Белый список из env-переменной — переживает рестарт Render (эфемерный диск).
# Формат: CONTEST_CHATS=2000000001,2000000002 (через запятую).
# Команды !конкурс +/- продолжают работать (меняют файл), но при рестарте env переопределяет.
_env_chats = os.environ.get("CONTEST_CHATS", "")
if _env_chats:
    CONTEST_CHATS = [int(c.strip()) for c in _env_chats.split(",") if c.strip().isdigit()]
    save_json(CONTEST_CHATS_FILE, CONTEST_CHATS)

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
    'tma':      {'color': (142,  68, 173), 'text': (255,255,255), 'alpha': ( 80, 20, 120)},
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

# ==================== ДЕКОДИРОВАНИЕ КОЛОДЫ (BHD1 / Base64) ====================

def _element_from_list(elements):
    for el in elements or []:
        key = API_ELEMENT_MAP.get(str(el).strip().lower())
        if key:
            return key
        low = str(el).strip().lower()
        if low in ELEMENT_DATA:
            return low
    return 'nejtraly'

def ensure_game_db(force=False):
    """Локальная база героев/карт по game_id из /wp-json/berserk/v1/data."""
    with _GAME_DB_LOCK:
        age = time.time() - _GAME_DB['loaded_at']
        if not force and _GAME_DB['heroes'] and age < GAME_DB_TTL:
            return _GAME_DB
    try:
        res = requests.get(BERSERK_DATA_URL, headers=BROWSER_HEADERS, timeout=30)
        res.raise_for_status()
        data = res.json()
        heroes, cards, by_title = {}, {}, {}
        for h in data.get('heroes') or []:
            gid = str(h.get('game_id') or '').strip().lower()
            if gid:
                heroes[gid] = h
            title = str(h.get('title') or '').strip().lower()
            if title:
                by_title[title] = h
        for c in data.get('cards') or []:
            gid = str(c.get('game_id') or '').strip().lower()
            if gid:
                cards[gid] = c
            title = str(c.get('title') or '').strip().lower()
            if title and title not in by_title:
                by_title[title] = c
        with _GAME_DB_LOCK:
            _GAME_DB['heroes'] = heroes
            _GAME_DB['cards'] = cards
            _GAME_DB['by_title'] = by_title
            _GAME_DB['loaded_at'] = time.time()
            print(f"[GAME DB] героев={len(heroes)}, карт={len(cards)}", flush=True)
            return {
                'heroes': heroes,
                'cards': cards,
                'by_title': by_title,
                'loaded_at': _GAME_DB['loaded_at'],
            }
    except Exception as e:
        print(f"[GAME DB ERROR] {e}", flush=True)
        with _GAME_DB_LOCK:
            return {
                'heroes': dict(_GAME_DB['heroes']),
                'cards': dict(_GAME_DB['cards']),
                'by_title': dict(_GAME_DB['by_title']),
                'loaded_at': _GAME_DB['loaded_at'],
            }

def looks_like_deck_base64(text):
    """Грубая проверка: одна строка Base64 кода колоды BHD1."""
    if not text:
        return False
    s = text.strip()
    if '\n' in s or ' ' in s:
        s = re.sub(r'\s+', '', s)
    if not (24 <= len(s) <= 1024):
        return False
    if not re.fullmatch(r'[A-Za-z0-9+/=]+', s):
        return False
    # BHD1 в Base64 почти всегда начинается с QkhEM
    return s.startswith('QkhEM') or s.startswith('QkhE')

def decode_deck_bhd1(code):
    """
    Распаковка официального кода колоды BHD1 (decodeDeck с dekbilder):
    signature(4) + hero_id(8) + count(1) + N*(card_id(8)+qty(1)) + crc32(4).
    """
    trimmed = re.sub(r'\s+', '', str(code or '').strip())
    if not (24 <= len(trimmed) <= 1024):
        raise ValueError('Неверная длина кода')
    try:
        raw = base64.b64decode(trimmed)
    except Exception:
        raise ValueError('Код не является Base64')
    data = bytearray(raw)
    if len(data) < 17 or len(data) > 4 + 8 + 1 + 80 * 9 + 4:
        raise ValueError('Неверный размер данных')
    crc_pos = len(data) - 4
    stored_crc = int.from_bytes(data[crc_pos:crc_pos + 4], 'little')
    calc_crc = zlib.crc32(bytes(data[:crc_pos])) & 0xFFFFFFFF
    if stored_crc != calc_crc:
        raise ValueError('Не сходится контрольная сумма')
    if bytes(data[:4]) != BH_SIGNATURE:
        raise ValueError('Это не код колоды BHD1')

    def read_id(pos):
        low = int.from_bytes(data[pos:pos + 4], 'little')
        high = int.from_bytes(data[pos + 4:pos + 8], 'little')
        if low == 0 and high == 0:
            raise ValueError('Пустой ID карты')
        if high != BH_ID_HIGH:
            raise ValueError('Неизвестный формат ID карты')
        return f'{low:08x}', pos + 8

    pos = 4
    hero_id, pos = read_id(pos)
    count = data[pos]
    pos += 1
    if count > 80:
        raise ValueError('Слишком много карт')
    if len(data) != 13 + count * 9 + 4:
        raise ValueError('Неверный размер данных')
    entries = []
    seen = set()
    for _ in range(count):
        cid, pos = read_id(pos)
        n = data[pos]
        pos += 1
        if n < 1 or n > 10:
            raise ValueError(f'Неверное количество карты {cid}')
        if cid in seen:
            raise ValueError(f'Карта {cid} указана дважды')
        seen.add(cid)
        entries.append((cid, int(n)))
    return {'hero': hero_id, 'entries': entries, 'code': trimmed}

def download_image_url(url):
    if not url:
        return None
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        if res.status_code == 200 and res.content:
            return res.content
    except Exception as e:
        print(f"[IMG URL ERROR] {url}: {e}", flush=True)
    return None

def _meta_from_game_card(card):
    title = str((card or {}).get('title') or '???').strip() or '???'
    cost = (card or {}).get('cost')
    try:
        cost = int(cost)
    except Exception:
        cost = 0
    element = _element_from_list((card or {}).get('elements'))
    image_url = (card or {}).get('image') or ''
    return title, cost, element, image_url

def deck_entries_to_card_rows(decoded):
    """game_id + count -> строки для build_deck_image: (cost, name, count, img_bytes, element)."""
    db = ensure_game_db()
    hero_meta = db['heroes'].get(decoded['hero']) or {}
    hero_name = str(hero_meta.get('title') or f"Герой {decoded['hero']}").strip()

    def load_one(item):
        gid, count = item
        card = db['cards'].get(gid) or db['heroes'].get(gid) or {}
        title, cost, element, image_url = _meta_from_game_card(card)
        img = download_image_url(image_url)
        if not img and title and title != '???':
            img, el2 = download_card_image_fast(title)
            if el2 and (not element or element == 'nejtraly'):
                element = el2
            if not img:
                img = download_card_image(title, prefix="bgo-")
        if not title or title == '???':
            title = f"ID {gid}"
        return cost, title, count, img, element or 'nejtraly'

    with ThreadPoolExecutor(max_workers=20) as executor:
        rows = list(executor.map(load_one, decoded['entries']))
    rows.sort(key=lambda x: (x[0], x[1]))
    total = sum(c for _, _, c, _, _ in rows)
    return hero_name, total, rows

def render_deck_image_from_base64(code):
    decoded = decode_deck_bhd1(code)
    hero_name, total, rows = deck_entries_to_card_rows(decoded)
    if not rows:
        raise ValueError('В колоде нет карт')
    img_bytes = build_deck_image(hero_name, total, 60, rows)
    return img_bytes, hero_name, total, decoded

def fetch_public_decks(force=False):
    with _PUBLIC_DECKS_LOCK:
        age = time.time() - _PUBLIC_DECKS_CACHE['loaded_at']
        if not force and _PUBLIC_DECKS_CACHE['items'] and age < PUBLIC_DECKS_TTL:
            return list(_PUBLIC_DECKS_CACHE['items'])
    res = requests.get(PUBLIC_DECKS_URL, headers=BROWSER_HEADERS, timeout=30)
    res.raise_for_status()
    items = res.json()
    if not isinstance(items, list):
        raise ValueError('Некорректный ответ API публичных колод')
    with _PUBLIC_DECKS_LOCK:
        _PUBLIC_DECKS_CACHE['items'] = items
        _PUBLIC_DECKS_CACHE['loaded_at'] = time.time()
    print(f"[PUBLIC DECKS] загружено {len(items)} колод", flush=True)
    return list(items)

def find_best_public_deck(hero_query):
    """Фильтр по герою, сортировка: лайки ↓, дата обновления ↓; предпочтение колод с game_code."""
    q = (hero_query or '').strip().lower()
    if not q:
        return None
    decks = fetch_public_decks()
    matched = []
    for d in decks:
        hero_title = ''
        dj = d.get('deck_json') or {}
        if isinstance(dj, dict):
            hero_title = str(dj.get('heroTitle') or '')
        if q in hero_title.lower() or hero_title.lower() in q or q == hero_title.lower():
            matched.append(d)
    if not matched:
        # мягкий поиск по вхождению
        matched = [
            d for d in decks
            if q in str(((d.get('deck_json') or {}).get('heroTitle') or '')).lower()
        ]
    if not matched:
        return None

    def sort_key(d):
        likes = int(d.get('likes') or 0)
        updated = int(d.get('updated_at') or 0)
        has_code = 1 if str(d.get('game_code') or '').strip() else 0
        return (has_code, likes, updated)

    matched.sort(key=sort_key, reverse=True)
    return matched[0]

def build_rows_from_deck_json(deck_json, hero_fallback=''):
    """Fallback: группировка карт из deck_json, если game_code пуст."""
    dj = deck_json or {}
    hero_name = str(dj.get('heroTitle') or hero_fallback or 'Колода').strip()
    cards = dj.get('cards') or []
    grouped = {}
    for c in cards:
        key = str(c.get('id') or c.get('title') or '').strip()
        if not key:
            continue
        if key not in grouped:
            grouped[key] = {
                'title': str(c.get('title') or '???'),
                'cost': c.get('cost') or 0,
                'count': 0,
                'image': c.get('image') or '',
                'elements': c.get('elements') or [],
                'game_id': str(c.get('game_id') or '').strip().lower(),
            }
        grouped[key]['count'] += 1

    def load_one(item):
        meta = item
        title = meta['title']
        try:
            cost = int(meta['cost'])
        except Exception:
            cost = 0
        element = _element_from_list(meta['elements'])
        img = download_image_url(meta['image'])
        if not img:
            img, el2 = download_card_image_fast(title)
            if el2 and (not element or element == 'nejtraly'):
                element = el2
            if not img:
                img = download_card_image(title, prefix="bgo-")
        return cost, title, meta['count'], img, element or 'nejtraly'

    with ThreadPoolExecutor(max_workers=20) as executor:
        rows = list(executor.map(load_one, grouped.values()))
    rows.sort(key=lambda x: (x[0], x[1]))
    total = sum(c for _, _, c, _, _ in rows)
    return hero_name, total, rows

def format_deck_caption(deck_obj, game_code=''):
    name = str(deck_obj.get('name') or 'Колода').strip()
    author = str(deck_obj.get('author') or '—').strip()
    is_pro = bool(deck_obj.get('is_pro') or deck_obj.get('author_is_pro'))
    pro_mark = " ✅PRO" if is_pro else ""
    deck_id = deck_obj.get('id')
    link = DECK_VIEW_URL.format(deck_id) if deck_id else "https://ep-ccg.ru/publichnye-kolody/"
    hero = str(((deck_obj.get('deck_json') or {}).get('heroTitle')) or '').strip()
    likes = int(deck_obj.get('likes') or 0)
    lines = [
        f"🃏 {name}",
        f"🐉 Герой: {hero}" if hero else None,
        f"👤 Автор: {author}{pro_mark}",
        f"❤️ Лайков: {likes}",
        f"🔗 {link}",
    ]
    code = (game_code or deck_obj.get('game_code') or '').strip()
    if code:
        lines.append("")
        lines.append("📋 Код колоды (Base64):")
        lines.append(code)
    return "\n".join(x for x in lines if x is not None)

def send_deck_image(vk_session, peer_id, img_bytes, message=' '):
    attachment = upload_and_get_attachment(vk_session, img_bytes, 'deck.jpg', peer_id)
    vk_session.method('messages.send', {
        'peer_id': peer_id,
        'message': message or ' ',
        'attachment': attachment,
        'random_id': rnd_id(),
    })
    return attachment

# ==================== ОТПРАВКА КАРТИНОК В ВК ====================

def trim_card_margins(img, padding=10):
    """Убирает внешнюю пустоту через getbbox(), сохраняя рамку с отступом padding."""
    img = img.convert("RGBA")
    w, h = img.size
    bbox = img.getbbox()
    if not bbox:
        return img
    left = max(0, bbox[0] - padding)
    top = max(0, bbox[1] - padding)
    right = min(w, bbox[2] + padding)
    bottom = min(h, bbox[3] + padding)
    return img.crop((left, top, right, bottom))

def prepare_card_square_jpeg(photo_content, max_side=800):
    """Белый квадрат со целой пропорциональной картой по центру (без растягивания)."""
    img = Image.open(io.BytesIO(photo_content))
    img = trim_card_margins(img, padding=10)
    if img.width < 2 or img.height < 2:
        raise ValueError("Карта пустая после обрезки полей")

    card_w, card_h = img.size

    # Квадратный холст: высота карты + поля, но не больше max_side
    square_side = card_h + 40
    if square_side > max_side:
        square_side = max_side
    elif square_side < 400:
        square_side = min(max_side, max(400, square_side))

    # Пропорциональный масштаб под высоту квадрата (без искажений)
    scale = square_side / card_h
    new_w = max(1, int(round(card_w * scale)))
    new_h = square_side
    # Если после масштаба карта шире квадрата — чуть уменьшаем, чтобы влезла целиком
    if new_w > square_side:
        scale = square_side / card_w
        new_w = square_side
        new_h = max(1, int(round(card_h * scale)))

    img = img.resize((new_w, new_h), Image.Resampling.BILINEAR)

    canvas = Image.new("RGB", (square_side, square_side), (255, 255, 255))
    paste_x = (square_side - new_w) // 2
    paste_y = (square_side - new_h) // 2
    if img.mode == "RGBA":
        canvas.paste(img, (paste_x, paste_y), img)
    else:
        canvas.paste(img.convert("RGB"), (paste_x, paste_y))

    output = io.BytesIO()
    canvas.save(output, format="JPEG", quality=90)
    return output.getvalue()

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

def _parse_card_type(class_list):
    for cls in class_list or []:
        m = re.match(r'mmf_(?:type|card_type)-(\w+)', str(cls), re.I)
        if m:
            t = m.group(1).lower()
            if t in TYPE_NAMES_RU:
                return t
        low = str(cls).lower()
        for key in TYPE_NAMES_RU:
            if key in low:
                return key
    return ''

def _lookup_game_card_by_title(card_name):
    try:
        db = ensure_game_db()
        return db['by_title'].get((card_name or '').strip().lower()) or {}
    except Exception:
        return {}

def make_contest_crop(img_bytes, clue_type, center_rel=None, size_ratio=0.22):
    """
    Кроп фрагмента карты.
    size_ratio — доля min(w,h), старт ~20-25%.
    center_rel — (cx, cy) в долях [0..1]; если None, выбирается случайно и возвращается.
    """
    try:
        if clue_type == "fragment":
            base = Image.open(io.BytesIO(img_bytes)).convert("L")
        else:
            base = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        zw, zh = max(1, int(base.width * 2.5)), max(1, int(base.height * 2.5))
        img = base.resize((zw, zh), Image.Resampling.BILINEAR)
        if clue_type == "blur":
            img = img.filter(ImageFilter.GaussianBlur(radius=18))

        crop_size = max(24, int(min(zw, zh) * float(size_ratio)))
        crop_size = min(crop_size, zw, zh)
        half = crop_size / 2.0

        if center_rel is None:
            cx = random.uniform(half / zw, 1.0 - half / zw)
            cy_max = min(0.60, 1.0 - half / zh)
            cy_min = half / zh
            if cy_max <= cy_min:
                cy = 0.5
            else:
                cy = random.uniform(cy_min, cy_max)
            center_rel = (round(cx, 5), round(cy, 5))
        else:
            cx, cy = float(center_rel[0]), float(center_rel[1])

        left = int(round(cx * zw - half))
        top = int(round(cy * zh - half))
        left = max(0, min(left, zw - crop_size))
        top = max(0, min(top, zh - crop_size))
        cropped = img.crop((left, top, left + crop_size, top + crop_size))
        resample = Image.Resampling.NEAREST if clue_type == "fragment" else Image.Resampling.BILINEAR
        cropped = cropped.resize((400, 400), resample)
        output = io.BytesIO()
        cropped.save(output, format="JPEG", quality=85 if clue_type == "blur" else 80)
        return output.getvalue(), center_rel
    except Exception as e:
        print(f"[CONTEST CROP ERROR] {e}", flush=True)
        return None, center_rel

def make_blur_crop(img_bytes, center_rel=None, size_ratio=0.22):
    return make_contest_crop(img_bytes, "blur", center_rel=center_rel, size_ratio=size_ratio)

def make_fragment_crop(img_bytes, center_rel=None, size_ratio=0.20):
    return make_contest_crop(img_bytes, "fragment", center_rel=center_rel, size_ratio=size_ratio)

def mask_ability_text(card_text, card_name, reveal_ratio=0.22):
    """Урезанный текст способности без имени карты."""
    text = re.sub(r'\s+', ' ', (card_text or '').strip())
    if not text:
        return "███"
    if card_name:
        text = re.sub(re.escape(card_name), '???', text, flags=re.IGNORECASE)
        # маскируем отдельные слова имени
        for part in re.findall(r'[A-Za-zА-Яа-яЁё]{3,}', card_name):
            text = re.sub(re.escape(part), '???', text, flags=re.IGNORECASE)
    words = text.split()
    if not words:
        return "███"
    keep = max(2, int(len(words) * float(reveal_ratio)))
    keep = min(keep, len(words))
    shown = []
    for i, w in enumerate(words[:keep]):
        if len(w) <= 3 or w in ('???', '—', '-'):
            shown.append(w)
        elif i % 3 == 2:
            shown.append(w[0] + '█' * max(1, len(w) - 1))
        else:
            shown.append(w)
    suffix = " …███" if keep < len(words) else ""
    return " ".join(shown) + suffix

def build_text_clue_message(state, hint_level=0, is_hourly=False):
    ratios = TEXT_REVEAL_RATIOS
    reveal = ratios[min(hint_level, len(ratios) - 1)]
    element = ELEMENT_NAMES_RU.get(state.get('element'), state.get('element') or '—')
    card_type = TYPE_NAMES_RU.get(state.get('card_type'), state.get('card_type') or '—')
    cost = state.get('cost')
    cost_s = str(cost) if cost is not None and cost != '' else '?'
    ability = mask_ability_text(state.get('card_text'), state.get('card_name'), reveal)
    reward = int(state.get('reward') or BASE_CONTEST_REWARD)
    header = "💡 Подсказка!" if is_hourly else "🎯 Угадай карту по описанию!"
    reward_line = (
        f"Награда удвоена: +{reward} баллов."
        if is_hourly else
        f"Первый правильный ответ — +{reward} баллов. Ответ будет раскрыт в 23:55."
    )
    return (
        f"{header}\n\n"
        f"💰 Стоимость: {cost_s}\n"
        f"🌀 Стихия: {element}\n"
        f"🏷 Тип: {card_type}\n"
        f"📜 Способность:\n«{ability}»\n\n"
        f"{reward_line}"
    )

def _contest_crop_ratio(clue_type, hint_level):
    table = BLUR_CROP_RATIOS if clue_type == "blur" else FRAGMENT_CROP_RATIOS
    return table[min(max(int(hint_level), 0), len(table) - 1)]

def fetch_contest_image(state):
    url = state.get('image_url')
    if url:
        img = download_image_url(url)
        if img:
            return img
    name = state.get('card_name')
    if name:
        img, _ = download_card_image_fast(name)
        if img:
            return img
        return download_card_image(name, prefix="bgo-")
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
    card_type = _parse_card_type(card.get('class_list'))
    img_bytes = None
    image_url = None
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
        except Exception:
            pass
    content_html = card.get('content', {}).get('rendered', '')
    card_text = re.sub(r'<[^>]+>', '', content_html).strip()

    game_card = _lookup_game_card_by_title(card_name)
    cost = game_card.get('cost')
    try:
        cost = int(cost) if cost is not None and cost != '' else None
    except Exception:
        cost = None
    if not card_type:
        card_type = str(game_card.get('type') or '').strip().lower()
    if not img_bytes and game_card.get('image'):
        image_url = game_card.get('image') or image_url
        img_bytes = download_image_url(image_url)

    idx = CLUE_INDEX.get('index', 0) % len(CLUE_TYPES)
    clue_type = CLUE_TYPES[idx]
    CLUE_INDEX['index'] = (idx + 1) % len(CLUE_TYPES)
    save_json(CLUE_INDEX_FILE, CLUE_INDEX)
    print(f"[CONTEST] Тип подсказки сегодня: {clue_type} (карта: «{card_name}»)", flush=True)

    started = moscow_now().isoformat()
    center_rel = None
    if clue_type in ("blur", "fragment") and img_bytes:
        ratio0 = _contest_crop_ratio(clue_type, 0)
        _, center_rel = make_contest_crop(img_bytes, clue_type, center_rel=None, size_ratio=ratio0)

    base_state = {
        'card_name': card_name,
        'card_slug': card_slug,
        'element': element_key,
        'card_type': card_type or '',
        'cost': cost,
        'card_text': card_text,
        'image_url': image_url or '',
        'started_at': started,
        'last_hint_at': started,
        'guessed': False,
        'revealed': False,
        'clue_type': clue_type,
        'reward': BASE_CONTEST_REWARD,
        'hint_level': 0,
        'crop_cx': (center_rel[0] if center_rel else None),
        'crop_cy': (center_rel[1] if center_rel else None),
    }

    new_state = {str(chat_id): dict(base_state) for chat_id in CONTEST_CHATS}
    CONTEST_STATE = new_state
    save_contests()

    for chat_id in CONTEST_CHATS:
        try:
            send_contest_clue(vk_session, chat_id, CONTEST_STATE[str(chat_id)], img_bytes)
        except Exception as e:
            print(f"[CONTEST SEND ERROR] chat={chat_id}: {e}", flush=True)

def send_contest_clue(vk_session, chat_id, state, img_bytes=None, is_hourly=False):
    clue_type = state.get('clue_type') or 'text'
    reward = int(state.get('reward') or BASE_CONTEST_REWARD)
    hint_level = int(state.get('hint_level') or 0)
    reward_line = (
        f"Награда удвоена: +{reward} баллов."
        if is_hourly else
        f"Первый правильный ответ — +{reward} баллов. Ответ будет раскрыт в 23:55."
    )

    if clue_type == "text" or not img_bytes:
        msg = build_text_clue_message(state, hint_level=hint_level, is_hourly=is_hourly)
        vk_session.method('messages.send', {
            'peer_id': chat_id, 'message': msg, 'random_id': rnd_id()
        })
        return

    center = None
    if state.get('crop_cx') is not None and state.get('crop_cy') is not None:
        center = (float(state['crop_cx']), float(state['crop_cy']))
    ratio = _contest_crop_ratio(clue_type, hint_level)
    crop, center = make_contest_crop(img_bytes, clue_type, center_rel=center, size_ratio=ratio)
    if center:
        state['crop_cx'], state['crop_cy'] = center[0], center[1]
    if not crop:
        msg = build_text_clue_message(state, hint_level=hint_level, is_hourly=is_hourly)
        vk_session.method('messages.send', {
            'peer_id': chat_id, 'message': msg, 'random_id': rnd_id()
        })
        return

    if clue_type == "blur":
        lead = "💡 Подсказка: более крупный размытый фрагмент!" if is_hourly else "🎯 Угадай карту!"
        body = (
            "На картинке — размытый фрагмент арта (увеличен)."
            if is_hourly else
            "На картинке — сильно размытый фрагмент арта (~1/4 карты)."
        )
    else:
        lead = "💡 Подсказка: более крупный ч/б фрагмент!" if is_hourly else "🎯 Угадай карту!"
        body = (
            "На картинке — увеличенный чёрно-белый фрагмент арта."
            if is_hourly else
            "На картинке — мелкий чёрно-белый фрагмент арта."
        )
    attachment = upload_and_get_attachment(vk_session, crop, 'clue.jpg', chat_id)
    vk_session.method('messages.send', {
        'peer_id': chat_id,
        'message': f"{lead}\n\n{body} Что это за карта?\n{reward_line}",
        'attachment': attachment,
        'random_id': rnd_id(),
    })

def normalize_text(text):
    return re.sub(r'\s+', ' ', text.strip().lower())

def check_contest_answer(vk_session, peer_id, user_id, user_name, text):
    state = CONTEST_STATE.get(str(peer_id))
    if not state or state.get('guessed') or state.get('revealed'):
        return False
    if normalize_text(text) == normalize_text(state['card_name']):
        state['guessed'] = True
        reward = int(state.get('reward') or BASE_CONTEST_REWARD)
        save_contests()
        add_score(peer_id, user_id, user_name, reward)
        vk_session.method('messages.send', {
            'peer_id': peer_id,
            'message': f"🎉 {user_name} угадал(а)! Это «{state['card_name']}».\n+{reward} баллов в рейтинг!",
            'random_id': rnd_id()
        })
        try:
            img, _ = download_card_image_fast(state['card_name'])
            if img:
                card_jpeg = prepare_card_square_jpeg(img)
                attachment = upload_and_get_attachment(vk_session, card_jpeg, 'card.jpg', peer_id)
                vk_session.method('messages.send', {
                    'peer_id': peer_id, 'message': state['card_name'],
                    'attachment': attachment, 'random_id': rnd_id()
                })
        except Exception:
            pass
        return True
    return False

def _parse_iso(ts):
    if not ts:
        return None
    try:
        return datetime.datetime.fromisoformat(str(ts))
    except Exception:
        return None

def process_hourly_contest_hints(vk_session):
    """Раз в час без ответа: x2 награда + новая подсказка (больший кроп / больше текста)."""
    now = moscow_now()
    changed = False
    for chat_id_str, state in list(CONTEST_STATE.items()):
        if not state or state.get('guessed') or state.get('revealed'):
            continue
        anchor = _parse_iso(state.get('last_hint_at')) or _parse_iso(state.get('started_at'))
        if not anchor:
            continue
        elapsed = (now - anchor).total_seconds()
        if elapsed < HINT_INTERVAL_SEC:
            continue

        state['reward'] = int(state.get('reward') or BASE_CONTEST_REWARD) * 2
        state['hint_level'] = int(state.get('hint_level') or 0) + 1
        state['last_hint_at'] = now.isoformat()
        changed = True
        chat_id = int(chat_id_str)
        try:
            img_bytes = None
            if state.get('clue_type') in ('blur', 'fragment'):
                img_bytes = fetch_contest_image(state)
            send_contest_clue(vk_session, chat_id, state, img_bytes=img_bytes, is_hourly=True)
            print(
                f"[CONTEST HINT] chat={chat_id} level={state['hint_level']} "
                f"reward={state['reward']} type={state.get('clue_type')}",
                flush=True,
            )
        except Exception as e:
            print(f"[CONTEST HINT ERROR] chat={chat_id}: {e}", flush=True)
            traceback.print_exc()
    if changed:
        save_contests()

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
                    card_jpeg = prepare_card_square_jpeg(img)
                    attachment = upload_and_get_attachment(vk_session, card_jpeg, 'card.jpg', chat_id)
                    vk_session.method('messages.send', {
                        'peer_id': chat_id, 'message': state['card_name'],
                        'attachment': attachment, 'random_id': rnd_id()
                    })
            except Exception as e:
                print(f"[CONTEST TIMEOUT ERROR] chat={chat_id}: {e}", flush=True)
    if changed:
        save_contests()
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
        save_contests()
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

def reset_chat_scores(chat_id_str, persist=True):
    if chat_id_str in CHAT_SCORES:
        for uid in list(CHAT_SCORES[chat_id_str].keys()):
            if uid != '_reset_month':
                if isinstance(CHAT_SCORES[chat_id_str][uid], dict):
                    CHAT_SCORES[chat_id_str][uid]['score'] = 0
        CHAT_SCORES[chat_id_str]['_reset_month'] = moscow_now().strftime('%Y-%m')
        if persist:
            save_contests()
        print(f"[SCORES] Рейтинг чата {chat_id_str} сброшен (1-е число)", flush=True)

def reset_all_scores(persist=True):
    if not CHAT_SCORES:
        return
    current_month = moscow_now().strftime('%Y-%m')
    for chat_id_str in list(CHAT_SCORES.keys()):
        reset_chat_scores(chat_id_str, persist=False)
    if persist:
        save_contests()
    print(f"[SCORES] Полный сброс всех рейтингов ({current_month})", flush=True)

def check_monthly_reset(chat_id_str):
    """Ленивый сброс при обращении к рейтингу; дубли месячного отчёта режет CONTEST_META."""
    current_month = moscow_now().strftime('%Y-%m')
    if chat_id_str not in CHAT_SCORES:
        CHAT_SCORES[chat_id_str] = {'_reset_month': current_month}
        return
    if CHAT_SCORES[chat_id_str].get('_reset_month') != current_month:
        # Если плановый отчёт за этот месяц ещё не ушёл — не молча обнуляем
        if CONTEST_META.get('last_monthly_report') == current_month:
            reset_chat_scores(chat_id_str)

def format_month_leaders(chat_id_str, month_label=None):
    scores = CHAT_SCORES.get(chat_id_str, {})
    entries = [
        (uid, data) for uid, data in scores.items()
        if uid != '_reset_month' and isinstance(data, dict) and int(data.get('score') or 0) > 0
    ]
    entries.sort(key=lambda x: x[1].get('score', 0), reverse=True)
    title = month_label or "прошедший месяц"
    if not entries:
        return f"📊 Итоги рейтинга за {title}:\n\nНикто не набрал очков."
    lines = [f"📊 Итоги рейтинга за {title}:\n"]
    for i, (uid, data) in enumerate(entries[:15], 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        lines.append(f"{medal} {data.get('name', '???')} — {data.get('score', 0)} баллов")
    lines.append(f"\nВсего игроков с очками: {len(entries)}")
    lines.append("Рейтинг будет обнулён. Новый месяц — новый сезон!")
    return "\n".join(lines)

def process_monthly_score_reset(vk_session):
    """
    Смена месяца (Europe/Moscow): отчёт лидеров → затем сброс.
    Флаг CONTEST_META['last_monthly_report'] = 'YYYY-MM' защищает от повторов.
    """
    global CONTEST_META
    now = moscow_now()
    current_month = now.strftime('%Y-%m')
    last = CONTEST_META.get('last_monthly_report')
    if last == current_month:
        return
    # Первый запуск в середине месяца — только зафиксировать флаг, без обнуления
    if not last:
        CONTEST_META['last_monthly_report'] = current_month
        save_contests()
        return

    # Подпись прошедшего месяца
    prev = (now.replace(day=1) - datetime.timedelta(days=1))
    prev_label = prev.strftime('%m.%Y')

    chat_ids = set(str(c) for c in CONTEST_CHATS)
    chat_ids.update(str(k) for k in CHAT_SCORES.keys())
    sent_ok = True
    summaries = []

    for chat_id_str in sorted(chat_ids):
        try:
            refresh_chat_names(vk_session, chat_id_str)
        except Exception:
            pass
        msg = format_month_leaders(chat_id_str, month_label=prev_label)
        summaries.append(f"Чат {chat_id_str}:\n{msg}")
        try:
            vk_session.method('messages.send', {
                'peer_id': int(chat_id_str),
                'message': msg,
                'random_id': rnd_id(),
            })
        except Exception as e:
            sent_ok = False
            print(f"[MONTHLY REPORT ERROR] chat={chat_id_str}: {e}", flush=True)

    if ADMIN_VK_ID:
        admin_msg = "📢 Месячный отчёт рейтингов\n\n" + "\n\n———\n\n".join(summaries[:20])
        try:
            vk_session.method('messages.send', {
                'peer_id': ADMIN_VK_ID,
                'message': admin_msg[:4000],
                'random_id': rnd_id(),
            })
        except Exception as e:
            print(f"[MONTHLY REPORT ADMIN ERROR] {e}", flush=True)
            # ЛС админу не блокирует сброс, если чаты уже получили отчёт

    if not sent_ok and chat_ids:
        print("[MONTHLY REPORT] Есть ошибки отправки в чаты — сброс отложен", flush=True)
        return

    reset_all_scores(persist=False)
    CONTEST_META['last_monthly_report'] = current_month
    save_contests()
    print(f"[MONTHLY RESET] Отчёт отправлен, рейтинги сброшены ({current_month})", flush=True)

def add_score(chat_id, user_id, user_name, points):
    chat_id_str = str(chat_id)
    user_id_str = str(user_id)
    check_monthly_reset(chat_id_str)
    if user_id_str not in CHAT_SCORES[chat_id_str] or not isinstance(CHAT_SCORES[chat_id_str][user_id_str], dict):
        CHAT_SCORES[chat_id_str][user_id_str] = {'name': user_name, 'score': 0}
    CHAT_SCORES[chat_id_str][user_id_str]['name'] = user_name
    CHAT_SCORES[chat_id_str][user_id_str]['score'] += points
    save_contests()

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
        save_contests()

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
    """Старт/финиш викторины, почасовые подсказки и месячный отчёт+сброс."""
    last_start = None
    last_end = None
    last_hint_tick = None
    while True:
        try:
            now = moscow_now()
            today = now.strftime('%Y-%m-%d')
            minute_key = now.strftime('%Y-%m-%d %H:%M')

            if now.hour == 20 and now.minute == 0 and last_start != today:
                last_start = today
                start_contest(vk_session)
            if now.hour == 23 and now.minute == 55 and last_end != today:
                last_end = today
                end_contest_timeout(vk_session)

            # Раз в минуту: почасовые подсказки и проверка смены месяца
            if last_hint_tick != minute_key:
                last_hint_tick = minute_key
                process_hourly_contest_hints(vk_session)
                process_monthly_score_reset(vk_session)
        except Exception as e:
            print(f"[SCHEDULER ERROR] {e}", flush=True)
            traceback.print_exc()
        time.sleep(20)

def monthly_reset_scheduler(vk_session=None):
    """Совместимость: месячный сброс теперь в contest_scheduler."""
    if vk_session is None:
        return
    while True:
        try:
            process_monthly_score_reset(vk_session)
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

    # !колода <Герой> — лучшая публичная колода с ep-ccg.ru
    if text_lower.startswith("!колода"):
        hero_query = text_clean[len("!колода"):].strip()
        if not hero_query:
            vk_session.method('messages.send', {
                'peer_id': peer_id,
                'message': "Использование: !колода <имя героя>\nПример: !колода Афари",
                'random_id': rnd_id(),
            })
            return
        try:
            vk_session.method('messages.send', {
                'peer_id': peer_id,
                'message': f"🔎 Ищу лучшую публичную колоду героя «{hero_query}»…",
                'random_id': rnd_id(),
            })
            best = find_best_public_deck(hero_query)
            if not best:
                vk_session.method('messages.send', {
                    'peer_id': peer_id,
                    'message': f"Колоды героя «{hero_query}» не найдены на ep-ccg.ru.",
                    'random_id': rnd_id(),
                })
                return
            game_code = str(best.get('game_code') or '').strip()
            if game_code:
                img_bytes, hero_name, total, _ = render_deck_image_from_base64(game_code)
            else:
                hero_name, total, rows = build_rows_from_deck_json(best.get('deck_json') or {}, hero_query)
                if not rows:
                    raise ValueError('Пустая колода')
                img_bytes = build_deck_image(hero_name, total, 60, rows)
            caption = format_deck_caption(best, game_code)
            send_deck_image(vk_session, peer_id, img_bytes, caption)
        except Exception as e:
            print(f"[KOLODA ERROR] {e}", flush=True)
            traceback.print_exc()
            vk_session.method('messages.send', {
                'peer_id': peer_id,
                'message': f"Не удалось собрать колоду: {e}",
                'random_id': rnd_id(),
            })
        return

    # !deck <Base64> или просто валидный Base64-код колоды BHD1
    deck_code_candidate = None
    if text_lower.startswith("!deck"):
        deck_code_candidate = text_clean[5:].strip()
        if not deck_code_candidate:
            vk_session.method('messages.send', {
                'peer_id': peer_id,
                'message': "Использование:\n!deck <Base64-код колоды>\nили просто пришлите код колоды BHD1\n\nТакже: !колода <Герой>",
                'random_id': rnd_id(),
            })
            return
    elif looks_like_deck_base64(text_clean):
        deck_code_candidate = text_clean.strip()

    if deck_code_candidate is not None:
        try:
            img_bytes, hero_name, total, decoded = render_deck_image_from_base64(deck_code_candidate)
            caption = f"🃏 Колода: {hero_name}\n📦 Карт: {total} / 60\n\n📋 Код:\n{decoded['code']}"
            send_deck_image(vk_session, peer_id, img_bytes, caption)
        except Exception as e:
            print(f"[DECK B64 ERROR] {e}", flush=True)
            traceback.print_exc()
            vk_session.method('messages.send', {
                'peer_id': peer_id,
                'message': f"Не удалось декодировать колоду: {e}",
                'random_id': rnd_id(),
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
            card_jpeg = prepare_card_square_jpeg(photo_content)
            attachment = upload_and_get_attachment(vk_session, card_jpeg, 'card.jpg', peer_id)
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

def run_flask_server():
    """Фоновый Flask: отвечает на пинги Render, чтобы процесс не убивали за «тишину»."""
    port = int(os.environ.get('PORT', 5000))
    print(f"[FLASK] Health-check на 0.0.0.0:{port}", flush=True)
    app.run(host='0.0.0.0', port=port, use_reloader=False, threaded=True)

def run_vk_bot():
    update_site_files_index()
    threading.Thread(target=ensure_game_db, daemon=True).start()
    vk_session = vk_api.VkApi(token=VK_TOKEN, api_version='5.199')
    threading.Thread(target=contest_scheduler, args=(vk_session,), daemon=True).start()
    threading.Thread(target=watchdog_loop, daemon=True).start()
    gist_status = "ON" if (GITHUB_TOKEN and GIST_ID) else "OFF"
    print(
        f"Планировщики: конкурс/подсказки/месячный отчёт "
        f"({len(CONTEST_CHATS)} чатов) + watchdog; "
        f"Gist sync={gist_status}; "
        f"state={len(CONTEST_STATE)}, scores={len(CHAT_SCORES)}",
        flush=True,
    )
    if not OWNER_ID:
        print("⚠️ OWNER_ID не задан — управление конкурсом недоступно!", flush=True)

    while True:
        try:
            bot_longpoll = VkBotLongPoll(vk_session, group_id=GROUP_ID)
            print("Бот успешно запущен и слушает ВК...", flush=True)
            update_heartbeat()
            while True:
                try:
                    events = bot_longpoll.check()
                    update_heartbeat()
                    for event in events:
                        if event.type == VkBotEventType.MESSAGE_NEW:
                            threading.Thread(
                                target=_safe_handle,
                                args=(vk_session, event.obj.message),
                                daemon=True,
                            ).start()
                except (RequestsReadTimeout, Urllib3ReadTimeoutError, requests.exceptions.Timeout) as e:
                    # Таймаут long poll — НЕ падаем, просто продолжаем цикл
                    print(f"[LONGPOLL TIMEOUT] {type(e).__name__}: {e} — переподключение через 3 сек", flush=True)
                    update_heartbeat()
                    time.sleep(3)
                    continue
                except Exception as e:
                    print(f"[LOOP ERROR] {e} — reconnect через 3 сек", flush=True)
                    traceback.print_exc()
                    update_heartbeat()
                    time.sleep(3)
                    break  # пересоздаём VkBotLongPoll
        except (RequestsReadTimeout, Urllib3ReadTimeoutError, requests.exceptions.Timeout) as e:
            print(f"[BOT TIMEOUT] {type(e).__name__}: {e} — переподключение через 3 сек", flush=True)
            update_heartbeat()
            time.sleep(3)
        except Exception as e:
            print(f"[BOT ERROR] {e} — рестарт через 5 сек", flush=True)
            traceback.print_exc()
            update_heartbeat()
            time.sleep(5)

if __name__ == '__main__':
    # Flask в фоне (пинги Render), бот — в главном потоке
    flask_thread = threading.Thread(target=run_flask_server, daemon=True)
    flask_thread.start()
    run_vk_bot()

