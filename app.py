/**
 * ДЕКБИЛДЕР БГО v23 (Diagnostic Edition)
 * Расширенный поиск game_id и исправление ошибок фильтрации.
 */

add_action('rest_api_init', function () {
    register_rest_route('berserk/v1', '/data', array(
        'methods' => 'GET',
        'callback' => 'get_berserk_v23_data',
        'permission_callback' => '__return_true'
    ));
});

function get_berserk_v23_data() {
    global $wpdb;
    // Мапа картинок из медиабиблиотеки
    $attachments = $wpdb->get_results("SELECT post_title, guid FROM {$wpdb->posts} WHERE post_type = 'attachment' AND post_title LIKE 'бго %'");
    $img_map = [];
    foreach ($attachments as $att) {
        $img_map[trim(str_replace('бго ', '', $att->post_title))] = $att->guid;
    }

    $heroes_posts = get_posts(['post_type' => 'mm_hero', 'numberposts' => -1, 'post_status' => 'publish']);
    $cards_posts = get_posts(['post_type' => 'mmf_card', 'numberposts' => -1, 'post_status' => 'publish']);
    $data = ['heroes' => [], 'cards' => []];

    $all_hero_names = [];
    foreach ($heroes_posts as $h) { $all_hero_names[] = trim($h->post_title); }

    foreach (['heroes' => $heroes_posts, 'cards' => $cards_posts] as $key => $posts) {
        foreach ($posts as $post) {
            $title = trim($post->post_title);
            if ($key == 'cards' && in_array($title, $all_hero_names)) continue;

            $img_url = isset($img_map[$title]) ? $img_map[$title] : get_the_post_thumbnail_url($post->ID, 'medium');
            
            // Сбор стихий
            $tax = ($key == 'heroes') ? 'hero_element' : 'mmf_element';
            $terms = wp_get_post_terms($post->ID, $tax);
            $element_data = [];
            if (!empty($terms)) {
                foreach ($terms as $t) {
                    $element_data[] = $t->slug;
                    $element_data[] = mb_strtolower($t->name);
                }
            }

            // УМНЫЙ ПОИСК ID (пробуем все варианты)
            $game_id = get_field('card_id', $post->ID) 
                    ?: get_field('card_game_id', $post->ID) 
                    ?: get_post_meta($post->ID, 'card_id', true) 
                    ?: get_post_meta($post->ID, 'card_game_id', true) 
                    ?: get_post_meta($post->ID, 'ид_на_источнике', true) 
                    ?: '';

            $data[$key][] = [
                'id' => $post->ID,
                'title' => $title,
                'image' => $img_url ?: 'https://via.placeholder.com/200x280?text=IMG',
                'elements' => $element_data,
                'is_horde' => (mb_stripos($post->post_content, 'Орда') !== false),
                'cost' => (int)get_post_meta($post->ID, 'стоимость', true) ?: (int)get_field('card_cost', $post->ID) ?: 0,
                'game_id' => strtolower(trim($game_id)),
            ];
        }
    }
    return $data;
}

add_shortcode('berserk_deckbuilder', function() {
    ob_start();
    ?>
    <div id="berserk-app" class="db-pro-v23">
        <div v-if="loading" class="db-loading">Синхронизация с базой ep-ccg.ru...</div>
        <div v-else>
            <!-- Экран выбора героя -->
            <div v-if="!selectedHero" class="hero-screen">
                <h1 class="db-main-title">ВЫБЕРИТЕ ГЕРОЯ</h1>
                <div class="db-grid db-heroes-grid">
                    <div v-for="h in heroes" @click="selectedHero = h" class="db-card-item">
                        <img :src="h.image">
                        <div class="db-label">{{ h.title }}</div>
                        <div v-if="!h.game_id" class="db-id-error">ID НЕ ЗАПОЛНЕН!</div>
                    </div>
                </div>
            </div>

            <!-- Экран декбилдера -->
            <div v-else class="db-builder-layout">
                <div class="db-left-side">
                    <div class="db-toolbar">
                        <button @click="selectedHero = null" class="db-btn-back">← НАЗАД К ГЕРОЯМ</button>
                        <input v-model="search" placeholder="Поиск карты..." class="db-search">
                        <div class="db-hero-tag">{{ selectedHero.title }}</div>
                    </div>
                    
                    <div class="db-grid db-cards-grid">
                        <div v-for="c in filteredCards" @click="addToDeck(c)" class="db-card-item" :class="{ 'maxed': isMaxed(c) }">
                            <img :src="c.image">
                            <div v-if="getCount(c.id) > 0" class="db-badge">{{ getCount(c.id) }}</div>
                            <div v-if="c.is_horde" class="db-horde-tag">ОРДА</div>
                            <div class="db-cost-tag">{{ c.cost }}</div>
                        </div>
                    </div>
                </div>

                <div class="db-right-side">
                    <div class="db-sidebar-card">
                        <h3 style="color:#f1c40f; margin:0">{{ selectedHero.title }}</h3>
                        <div class="db-counter" :class="{ 'ok': deck.length >= 40 }">
                            Карт: {{ deck.length }} / 60
                        </div>
                        
                        <div class="db-deck-list">
                            <div v-for="item in groupedDeck" @click="removeFromDeckById(item.id)" class="db-deck-strip" :style="{ backgroundImage: 'url(' + item.image + ')' }">
                                <div class="strip-overlay"></div>
                                <span class="strip-cost">{{ item.cost }}</span>
                                <span class="strip-title">{{ item.title }}</span>
                                <span class="strip-count">{{ item.count }}x</span>
                            </div>
                        </div>

                        <div class="db-footer">
                            <button @click="copyCode" :disabled="deck.length < 40" class="db-btn-copy">КОПИРОВАТЬ КОД</button>
                            <button @click="importFromGame" class="db-btn-import">ИМПОРТ ИЗ ИГРЫ</button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script src="https://unpkg.com/vue@3/dist/vue.global.js"></script>
    <style>
        .db-pro-v23 { background:#070707; color:#eee; padding:20px; border-radius:15px; font-family: sans-serif; }
        .db-grid { display:grid; gap:12px; }
        .db-heroes-grid { grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); }
        .db-cards-grid { grid-template-columns: repeat(auto-fill, minmax(110px, 1fr)); max-height:800px; overflow-y:auto; }
        .db-card-item { cursor:pointer; position:relative; }
        .db-card-item img { width:100%; border-radius:8px; border:1px solid #333; }
        .db-card-item.maxed img { filter: brightness(0.2) grayscale(1); }
        .db-badge { position:absolute; top:-8px; right:-8px; background:#e74c3c; width:22px; height:22px; border-radius:50%; text-align:center; line-height:22px; font-weight:bold; font-size:12px; border:2px solid #000; z-index:5; }
        .db-cost-tag { position:absolute; top:5px; left:5px; background:rgba(0,0,0,0.8); color:#f1c40f; padding:2px 5px; border-radius:4px; font-weight:bold; font-size:10px; }
        .db-id-error { color:#e74c3c; font-size:10px; text-align:center; font-weight:bold; margin-top:5px; }
        .db-builder-layout { display:flex; gap:20px; }
        .db-left-side { flex:3; }
        .db-right-side { flex:1; min-width:260px; }
        .db-sidebar-card { background:#111; border:1px solid #333; padding:15px; border-radius:12px; position:sticky; top:20px; }
        .db-deck-strip { height:40px; margin-bottom:4px; border-radius:4px; position:relative; display:flex; align-items:center; cursor:pointer; background-size:150%; background-position:center 30%; border-left:4px solid #f1c40f; overflow:hidden; }
        .strip-overlay { position:absolute; inset:0; background: linear-gradient(90deg, #000 0%, rgba(0,0,0,0.5) 50%, transparent 100%); }
        .strip-cost { position:relative; width:30px; text-align:center; font-weight:bold; color:#f1c40f; z-index:2; }
        .strip-title { position:relative; flex:1; font-size:11px; font-weight:bold; color:#fff; z-index:2; padding-left:5px; }
        .strip-count { position:relative; background:#f1c40f; color:#000; font-weight:bold; padding:0 8px; height:100%; display:flex; align-items:center; z-index:2; }
        .db-counter { margin:10px 0; font-weight:bold; color:#555; }
        .db-counter.ok { color:#27ae60; }
        .db-btn-copy { width:100%; padding:12px; background:#27ae60; color:#fff; border:none; border-radius:8px; font-weight:bold; cursor:pointer; }
        .db-btn-copy:disabled { opacity:0.2; cursor:not-allowed; }
        .db-loading { text-align:center; padding:100px; color:#f1c40f; }
        .db-hero-tag { font-size:12px; color:#f1c40f; border:1px solid #f1c40f; padding:5px 10px; border-radius:5px; }
        .db-main-title { text-align:center; color:#f1c40f; margin-bottom:20px; }
    </style>

    <script>
    const { createApp, ref, computed, onMounted } = Vue;
    createApp({
        setup() {
            const loading = ref(true);
            const heroes = ref([]);
            const cards = ref([]);
            const selectedHero = ref(null);
            const deck = ref([]);
            const search = ref('');

            const groupedDeck = computed(() => {
                const groups = {};
                deck.value.forEach(card => {
                    if (!groups[card.id]) groups[card.id] = { ...card, count: 0 };
                    groups[card.id].count++;
                });
                return Object.values(groups).sort((a, b) => (a.cost - b.cost) || a.title.localeCompare(b.title));
            });

            const filteredCards = computed(() => {
                if (!selectedHero.value) return [];
                const s = search.value.toLowerCase();
                const isHigart = selectedHero.value.title === 'Хигарт';
                const hElems = selectedHero.value.elements || [];

                return cards.value.filter(c => {
                    if (!c.title.toLowerCase().includes(s)) return false;
                    if (isHigart) return true;
                    const cElems = c.elements || [];
                    const isMatch = cElems.some(ce => hElems.includes(ce));
                    const isNeutral = cElems.some(ce => ce.includes('nejtraly') || ce.includes('neutral') || ce.includes('нейтралы'));
                    return isMatch || isNeutral;
                });
            });

            const getCount = (id) => deck.value.filter(i => i.id === id).length;
            const isMaxed = (card) => getCount(card.id) >= (card.is_horde ? 5 : 3);

            const addToDeck = (card) => {
                if (!isMaxed(card) && deck.value.length < 60) deck.value.push(card);
            };

            const removeFromDeckById = (id) => {
                const idx = deck.value.map(i => i.id).lastIndexOf(id);
                if (idx !== -1) deck.value.splice(idx, 1);
            };

            const copyCode = () => {
                if (!selectedHero.value || !selectedHero.value.game_id) {
                    alert('Ошибка: У этого героя не заполнен game_id в WordPress!');
                    return;
                }
                let hex = "42484431" + selectedHero.value.game_id.padStart(8, '0').slice(0, 8);
                const counts = {};
                deck.value.forEach(c => {
                    if (c.game_id) counts[c.game_id] = (counts[c.game_id] || 0) + 1;
                });
                Object.keys(counts).sort().forEach(id => {
                    hex += "00500008" + counts[id].toString(16).padStart(2, '0') + id.padStart(8, '0').slice(0, 8);
                });
                const bytes = hex.match(/\w{2}/g).map(a => parseInt(a, 16));
                const b64 = btoa(String.fromCharCode.apply(null, bytes));
                navigator.clipboard.writeText(b64).then(() => alert("Код колоды скопирован!"));
            };

            const importFromGame = () => {
                const code = prompt("Вставьте код BHD1:");
                if (!code) return;
                try {
                    const bin = atob(code);
                    const hex = bin.split('').map(c => c.charCodeAt(0).toString(16).padStart(2, '0')).join('');
                    const hId = hex.substring(8, 16).toLowerCase();
                    const h = heroes.value.find(i => i.game_id === hId);
                    if (h) selectedHero.value = h;
                    const parts = hex.split('00500008'); parts.shift();
                    deck.value = [];
                    parts.forEach(p => {
                        const card = cards.value.find(c => c.game_id === p.substring(2).toLowerCase());
                        if (card) {
                            for (let i = 0; i < parseInt(p.substring(0, 2), 16); i++) deck.value.push(card);
                        }
                    });
                } catch(e) { alert("Ошибка кода."); }
            };

            onMounted(async () => {
                const r = await fetch('/wp-json/berserk/v1/data');
                const d = await r.json();
                heroes.value = d.heroes;
                cards.value = d.cards;
                loading.value = false;
                console.log('✅ База героев загружена:', heroes.value);
            });

            return { loading, heroes, cards, selectedHero, deck, groupedDeck, search, filteredCards, addToDeck, removeFromDeckById, getCount, isMaxed, copyCode, importFromGame };
        }
    }).mount('#berserk-app');
    </script>
    <?php
    return ob_get_clean();
});




