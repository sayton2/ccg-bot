<?php
/**
 * Plugin Name: Berserk Deck Builder
 * Description: Декбилдер для Berserk Heroes Online v63
 * Version: 63
 */

define('BH_DECKBUILDER_URL', 'https://ep-ccg.ru/dekbilder/');
define('BH_DECKVIEW_URL', 'https://ep-ccg.ru/koloda/');
if (!defined('BH_PUBLIC_DECKS_URL')) define('BH_PUBLIC_DECKS_URL', '/publichnye-kolody/');

if (!defined('BH_DUST_EPIC'))      define('BH_DUST_EPIC', 400);
if (!defined('BH_DUST_LEGENDARY')) define('BH_DUST_LEGENDARY', 2000);
if (!defined('BH_DUST_RARE'))      define('BH_DUST_RARE', 120);
if (!defined('BH_DUST_COMMON'))   define('BH_DUST_COMMON', 60);

/** Игровой ID карты/героя из штатного meta/ACF поля записи WordPress. */
function bh_get_card_game_id($post_id) {
    $gid = '';
    if (function_exists('get_field')) {
        $val = get_field('card_game_id', $post_id);
        if ($val) $gid = $val;
    }
    if ($gid === '' || $gid === null) {
        $gid = get_post_meta($post_id, 'card_game_id', true);
    }
    return strtolower(trim((string)$gid));
}

/** URL картинки, привязанной к записи карты/героя (оригинал full, без мыльной миниатюры). */
function bh_get_card_image_url($post_id) {
    $url = get_the_post_thumbnail_url($post_id, 'full');
    if ($url) return $url;

    if (function_exists('get_field')) {
        foreach (array('card_image', 'hero_image', 'image', 'card_img', 'изображение', 'картинка') as $key) {
            $val = get_field($key, $post_id);
            $resolved = bh_resolve_image_field_url($val);
            if ($resolved) return $resolved;
        }
    }

    if (function_exists('get_field_objects')) {
        $fields = get_field_objects($post_id);
        if (is_array($fields)) {
            $use_mb = function_exists('mb_strtolower');
            foreach ($fields as $field) {
                $type = isset($field['type']) ? $field['type'] : '';
                $label = isset($field['label']) ? $field['label'] : '';
                $name = isset($field['name']) ? $field['name'] : '';
                $label_l = $use_mb ? mb_strtolower($label . ' ' . $name) : strtolower($label . ' ' . $name);
                $is_image = ($type === 'image');
                if (!$is_image) {
                    foreach (array('изображ', 'картин', 'image', 'thumb', 'photo', 'фото') as $kw) {
                        if ($use_mb ? (mb_strpos($label_l, $kw) !== false) : (strpos($label_l, $kw) !== false)) {
                            $is_image = true;
                            break;
                        }
                    }
                }
                if (!$is_image) continue;
                $resolved = bh_resolve_image_field_url(isset($field['value']) ? $field['value'] : null);
                if ($resolved) return $resolved;
            }
        }
    }

    return '';
}

/** Разобрать значение ACF image (ID / URL / массив) в URL оригинала. */
function bh_resolve_image_field_url($val) {
    if (!$val) return '';
    if (is_numeric($val)) {
        $url = wp_get_attachment_image_url(intval($val), 'full');
        return $url ? $url : '';
    }
    if (is_string($val)) {
        $val = trim($val);
        if ($val === '') return '';
        if (preg_match('#^https?://#i', $val) || strpos($val, '/') === 0) return $val;
        if (ctype_digit($val)) {
            $url = wp_get_attachment_image_url(intval($val), 'full');
            return $url ? $url : '';
        }
        return '';
    }
    if (is_array($val)) {
        if (!empty($val['url'])) return $val['url'];
        if (!empty($val['sizes']['full'])) return $val['sizes']['full'];
        if (!empty($val['ID'])) return bh_resolve_image_field_url($val['ID']);
        if (!empty($val['id'])) return bh_resolve_image_field_url($val['id']);
    }
    return '';
}

register_activation_hook(__FILE__, 'bh_create_tables');
function bh_create_tables() {
    global $wpdb;
    $charset = $wpdb->get_charset_collate();
    $wpdb->query("CREATE TABLE IF NOT EXISTS {$wpdb->prefix}bh_decks (
        id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        user_id BIGINT UNSIGNED NOT NULL,
        name VARCHAR(255) NOT NULL,
        hero_wp_id BIGINT UNSIGNED NOT NULL,
        deck_json LONGTEXT NOT NULL,
        header_id VARCHAR(8) NOT NULL DEFAULT '',
        hero_le VARCHAR(8) NOT NULL DEFAULT '',
        game_code TEXT,
        description LONGTEXT,
        guide_url TEXT,
        video_guide_url TEXT,
        is_public TINYINT(1) DEFAULT 0,
        likes INT DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) $charset");
    $wpdb->query("CREATE TABLE IF NOT EXISTS {$wpdb->prefix}bh_card_mappings (
        id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        game_id_be VARCHAR(8) NOT NULL,
        wp_post_id BIGINT UNSIGNED NOT NULL,
        card_name VARCHAR(255) NOT NULL DEFAULT '',
        votes INT DEFAULT 1,
        status ENUM('pending','approved') DEFAULT 'pending',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY unique_mapping (game_id_be, wp_post_id)
    ) $charset");
    $wpdb->query("CREATE TABLE IF NOT EXISTS {$wpdb->prefix}bh_deck_likes (
        id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        deck_id BIGINT UNSIGNED NOT NULL,
        ip VARCHAR(45) NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY unique_like (deck_id, ip)
    ) $charset");
    $wpdb->query("CREATE TABLE IF NOT EXISTS {$wpdb->prefix}bh_deck_stats (
        id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        deck_id BIGINT UNSIGNED NOT NULL,
        user_id BIGINT UNSIGNED NOT NULL,
        result ENUM('win','loss') NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_deck (deck_id)
    ) $charset");
    $cols = $wpdb->get_col("SHOW COLUMNS FROM {$wpdb->prefix}bh_decks");
    if ($cols) {
        if (!in_array('likes', $cols))       $wpdb->query("ALTER TABLE {$wpdb->prefix}bh_decks ADD COLUMN likes INT DEFAULT 0");
        if (!in_array('header_id', $cols))  $wpdb->query("ALTER TABLE {$wpdb->prefix}bh_decks ADD COLUMN header_id VARCHAR(8) NOT NULL DEFAULT ''");
        if (!in_array('hero_le', $cols))    $wpdb->query("ALTER TABLE {$wpdb->prefix}bh_decks ADD COLUMN hero_le VARCHAR(8) NOT NULL DEFAULT ''");
        if (!in_array('game_code', $cols))  $wpdb->query("ALTER TABLE {$wpdb->prefix}bh_decks ADD COLUMN game_code TEXT");
        if (!in_array('description', $cols)) $wpdb->query("ALTER TABLE {$wpdb->prefix}bh_decks ADD COLUMN description LONGTEXT");
        if (!in_array('guide_url', $cols)) $wpdb->query("ALTER TABLE {$wpdb->prefix}bh_decks ADD COLUMN guide_url TEXT");
        if (!in_array('video_guide_url', $cols)) $wpdb->query("ALTER TABLE {$wpdb->prefix}bh_decks ADD COLUMN video_guide_url TEXT");
    }
}

// Авто-миграция схемы при обновлении плагина
add_action('init', 'bh_ensure_schema');
function bh_ensure_schema() {
    if (get_option('bh_schema_version') >= 63) return;
    bh_create_tables();
    update_option('bh_schema_version', 63);
}

add_action('rest_api_init', function () {
    register_rest_route('berserk/v1', '/data', array('methods' => 'GET', 'callback' => 'get_berserk_data', 'permission_callback' => '__return_true'));
    register_rest_route('berserk/v1', '/decks/public', array('methods' => 'GET', 'callback' => 'bh_get_public_decks', 'permission_callback' => '__return_true'));
    register_rest_route('berserk/v1', '/decks/my', array('methods' => 'GET', 'callback' => 'bh_get_my_decks', 'permission_callback' => '__return_true'));
    register_rest_route('berserk/v1', '/decks/(?P<id>\d+)', array('methods' => 'GET', 'callback' => 'bh_get_deck', 'permission_callback' => '__return_true'));
    register_rest_route('berserk/v1', '/decks/save', array('methods' => 'POST', 'callback' => 'bh_save_deck', 'permission_callback' => '__return_true'));
    register_rest_route('berserk/v1', '/decks/(?P<id>\d+)/update-meta', array('methods' => 'POST', 'callback' => 'bh_update_deck_meta', 'permission_callback' => function () { return is_user_logged_in(); }));
    register_rest_route('berserk/v1', '/decks/delete/(?P<id>\d+)', array('methods' => array('DELETE', 'POST'), 'callback' => 'bh_delete_deck', 'permission_callback' => '__return_true'));
    register_rest_route('berserk/v1', '/decks/(?P<id>\d+)/like', array('methods' => 'POST', 'callback' => 'bh_like_deck', 'permission_callback' => '__return_true'));
    register_rest_route('berserk/v1', '/decks/(?P<id>\d+)/visibility', array('methods' => 'POST', 'callback' => 'bh_set_deck_visibility', 'permission_callback' => '__return_true'));
    register_rest_route('berserk/v1', '/mappings/submit', array('methods' => 'POST', 'callback' => 'bh_submit_mapping', 'permission_callback' => '__return_true'));
    register_rest_route('berserk/v1', '/mappings', array('methods' => 'GET', 'callback' => 'bh_get_mappings', 'permission_callback' => '__return_true'));
    register_rest_route('berserk/v1', '/debug/acf', array('methods' => 'GET', 'callback' => 'bh_debug_acf', 'permission_callback' => '__return_true'));
    register_rest_route('berserk/v1', '/decks/(?P<id>\d+)/result', array('methods' => 'POST', 'callback' => 'bh_record_deck_result', 'permission_callback' => function () { return is_user_logged_in(); }));
    register_rest_route('berserk/v1', '/stats/meta', array('methods' => 'GET', 'callback' => 'bh_get_meta_stats', 'permission_callback' => '__return_true'));
    register_rest_route('berserk/v1', '/pro/request', array('methods' => 'POST', 'callback' => 'bh_pro_request', 'permission_callback' => function () { return is_user_logged_in(); }));
    register_rest_route('berserk/v1', '/pro/me', array('methods' => 'GET', 'callback' => 'bh_pro_me', 'permission_callback' => function () { return is_user_logged_in(); }));
});

/** Нормализация типа карты к ключам creature / spell / equipment. */
function bh_normalize_card_type($raw) {
    $s = function_exists('mb_strtolower') ? mb_strtolower(trim((string)$raw)) : strtolower(trim((string)$raw));
    if ($s === '') return '';
    // Числовые коды (частый формат ACF select)
    if ($s === '1' || $s === '01') return 'creature';
    if ($s === '2' || $s === '02') return 'spell';
    if ($s === '3' || $s === '03') return 'equipment';
    // Заклинания
    if (
        strpos($s, 'закл') !== false || strpos($s, 'spell') !== false ||
        strpos($s, 'магия') !== false || strpos($s, 'magic') !== false ||
        $s === 's' || $s === 'sp'
    ) return 'spell';
    // Экипировка / предметы
    if (
        strpos($s, 'экип') !== false || strpos($s, 'equip') !== false || strpos($s, 'предм') !== false ||
        strpos($s, 'оруж') !== false || strpos($s, 'weapon') !== false ||
        strpos($s, 'доспех') !== false || strpos($s, 'armor') !== false || strpos($s, 'armour') !== false ||
        strpos($s, 'амулет') !== false || strpos($s, 'amulet') !== false ||
        strpos($s, 'артеф') !== false || strpos($s, 'artifact') !== false ||
        strpos($s, 'item') !== false || strpos($s, 'gear') !== false ||
        $s === 'e' || $s === 'eq'
    ) return 'equipment';
    // Герои (не считаем как существо в колоде карт)
    if (strpos($s, 'герой') !== false || strpos($s, 'hero') !== false) return 'hero';
    // Существа / юниты / монстры
    if (
        strpos($s, 'сущ') !== false || strpos($s, 'creat') !== false ||
        strpos($s, 'unit') !== false || strpos($s, 'minion') !== false ||
        strpos($s, 'monster') !== false || strpos($s, 'монстр') !== false ||
        strpos($s, 'юнит') !== false || strpos($s, 'воин') !== false ||
        strpos($s, 'fighter') !== false || strpos($s, 'warrior') !== false ||
        strpos($s, 'troop') !== false || strpos($s, 'отряд') !== false ||
        strpos($s, 'боец') !== false || strpos($s, 'персонаж') !== false ||
        $s === 'c' || $s === 'cr' || $s === 'u'
    ) return 'creature';
    return '';
}

/** Тип карты из ACF / meta / таксономии mmf_card. Пустой/неизвестный → creature. */
function bh_get_card_type($post_id) {
    $raw = bh_get_field_by_label($post_id, array('тип', 'type', 'card type', 'вид карты', 'тип карты', 'card_type'));
    if (!$raw) {
        foreach (array('card_type', 'type', 'тип', 'mmf_type', 'cardtype', 'bgo_type') as $fk) {
            if (function_exists('get_field')) {
                $v = bh_to_string(get_field($fk, $post_id));
                if ($v) { $raw = $v; break; }
            }
            $v = bh_to_string(get_post_meta($post_id, $fk, true));
            if ($v) { $raw = $v; break; }
        }
    }
    $norm = bh_normalize_card_type($raw);
    if ($norm && $norm !== 'hero') return $norm;

    $taxes = get_object_taxonomies('mmf_card', 'objects');
    $use_mb = function_exists('mb_strtolower');
    foreach ($taxes as $slug => $obj) {
        $check = $use_mb
            ? mb_strtolower(($obj->labels->name ?? '') . ' ' . ($obj->labels->singular_name ?? '') . ' ' . $slug)
            : strtolower(($obj->labels->name ?? '') . ' ' . ($obj->labels->singular_name ?? '') . ' ' . $slug);
        if (
            strpos($check, 'тип') === false && strpos($check, 'type') === false &&
            strpos($check, 'вид') === false && strpos($check, 'card_type') === false
        ) continue;
        $terms = wp_get_post_terms($post_id, $slug);
        if (is_wp_error($terms) || !$terms) continue;
        foreach ($terms as $term) {
            $norm = bh_normalize_card_type($term->name);
            if (!$norm) $norm = bh_normalize_card_type($term->slug);
            if ($norm && $norm !== 'hero') return $norm;
        }
    }
    // Любая карта mmf_card, не определённая как spell/equipment/hero — существо
    return 'creature';
}

function bh_user_is_pro($user_id) {
    $v = get_user_meta(intval($user_id), 'bgo_is_pro', true);
    return ($v === '1' || $v === 1 || $v === true || $v === 'yes');
}

function bh_user_pro_achievements($user_id) {
    return trim((string)get_user_meta(intval($user_id), 'bgo_pro_achievements', true));
}

function bh_attach_author_pro($row) {
    if (!$row || !is_object($row)) return $row;
    $uid = isset($row->user_id) ? intval($row->user_id) : 0;
    $row->author_id = $uid;
    $is_pro = $uid ? bh_user_is_pro($uid) : false;
    $ach = ($is_pro && $uid) ? bh_user_pro_achievements($uid) : '';
    $row->is_pro = (bool)$is_pro;
    $row->pro_achievements = $ach;
    // совместимость со старыми ключами во Vue
    $row->author_is_pro = (bool)$is_pro;
    $row->author_pro_achievements = $ach;
    return $row;
}

function bh_user_pro_request_status($user_id) {
    return trim((string)get_user_meta(intval($user_id), 'bgo_pro_request_status', true));
}

function bh_count_pending_pro_requests() {
    $users = get_users(array(
        'meta_key'   => 'bgo_pro_request_status',
        'meta_value' => 'pending',
        'fields'     => 'ID',
        'number'     => 9999,
        'count_total'=> false,
    ));
    return is_array($users) ? count($users) : 0;
}

function bh_pro_me() {
    $user = wp_get_current_user();
    if (!$user->ID) return new WP_Error('unauthorized', 'Не авторизован', array('status' => 401));
    $is_pro = bh_user_is_pro($user->ID);
    $status = bh_user_pro_request_status($user->ID);
    if ($is_pro && $status !== 'approved') {
        $status = 'approved';
    }
    return array(
        'is_pro' => $is_pro,
        'achievements' => bh_user_pro_achievements($user->ID),
        'request' => (string)get_user_meta($user->ID, 'bgo_pro_request', true),
        'request_status' => $status,
    );
}

function bh_pro_request(WP_REST_Request $request) {
    $user = wp_get_current_user();
    if (!$user->ID) return new WP_Error('unauthorized', 'Не авторизован', array('status' => 401));

    $status = bh_user_pro_request_status($user->ID);
    if (bh_user_is_pro($user->ID) || $status === 'pending') {
        return array(
            'success' => false,
            'status'  => bh_user_is_pro($user->ID) ? 'approved' : 'pending',
            'message' => 'Ваша заявка уже находится на рассмотрении',
        );
    }

    $p = $request->get_json_params();
    $text = isset($p['achievements']) ? sanitize_textarea_field($p['achievements']) : '';
    if ($text === '') return new WP_Error('invalid', 'Укажите достижения', array('status' => 400));

    update_user_meta($user->ID, 'bgo_pro_request', $text);
    update_user_meta($user->ID, 'bgo_pro_request_status', 'pending');
    if (!bh_user_pro_achievements($user->ID)) {
        update_user_meta($user->ID, 'bgo_pro_achievements', $text);
    }

    $admin_email = get_option('admin_email');
    if ($admin_email) {
        $nick = $user->display_name ? $user->display_name : $user->user_login;
        $edit_url = admin_url('user-edit.php?user_id=' . intval($user->ID));
        $subject = '[BGO] Заявка на статус PRO: ' . $nick;
        $body = "Новая заявка на статус PRO\n\n"
            . "Автор: {$nick} ({$user->user_login})\n"
            . "User ID: {$user->ID}\n"
            . "Email: {$user->user_email}\n\n"
            . "Достижения:\n{$text}\n\n"
            . "Редактировать профиль:\n{$edit_url}\n";
        wp_mail($admin_email, $subject, $body);
    }

    return array('success' => true, 'status' => 'pending', 'message' => 'Заявка отправлена');
}

add_action('show_user_profile', 'bh_pro_admin_profile_fields');
add_action('edit_user_profile', 'bh_pro_admin_profile_fields');
function bh_pro_admin_profile_fields($user) {
    if (!current_user_can('edit_users')) return;
    $is_pro = bh_user_is_pro($user->ID);
    $ach = bh_user_pro_achievements($user->ID);
    $req = (string)get_user_meta($user->ID, 'bgo_pro_request', true);
    $req_status = bh_user_pro_request_status($user->ID);
    echo '<h2>BGO PRO статус</h2><table class="form-table">';
    echo '<tr><th><label>Заявка</label></th><td>';
    echo $req !== '' || $req_status !== ''
        ? '<p><strong>Статус:</strong> ' . esc_html($req_status !== '' ? $req_status : '—') . '</p>'
          . ($req !== '' ? '<pre style="white-space:pre-wrap;background:#f6f7f7;padding:8px">' . esc_html($req) . '</pre>' : '')
        : '<em>Заявок нет</em>';
    echo '</td></tr>';
    echo '<tr><th><label for="bgo_pro_achievements">Достижения (тултип PRO)</label></th><td>';
    echo '<textarea name="bgo_pro_achievements" id="bgo_pro_achievements" rows="5" class="large-text">' . esc_textarea($ach) . '</textarea>';
    echo '</td></tr>';
    echo '<tr><th>Активировать статус PRO</th><td><label><input type="checkbox" name="bgo_is_pro" value="1" ' . checked($is_pro, true, false) . '> Показывать бейдж PRO на всех колодах автора</label></td></tr>';
    echo '</table>';
}
add_action('personal_options_update', 'bh_pro_admin_profile_save');
add_action('edit_user_profile_update', 'bh_pro_admin_profile_save');
function bh_pro_admin_profile_save($user_id) {
    if (!current_user_can('edit_users')) return;
    $was_pro = bh_user_is_pro($user_id);
    $make_pro = !empty($_POST['bgo_is_pro']);
    update_user_meta($user_id, 'bgo_is_pro', $make_pro ? '1' : '0');
    if (isset($_POST['bgo_pro_achievements'])) {
        update_user_meta($user_id, 'bgo_pro_achievements', sanitize_textarea_field(wp_unslash($_POST['bgo_pro_achievements'])));
    }
    // При одобрении PRO: pending → approved
    if ($make_pro) {
        update_user_meta($user_id, 'bgo_pro_request_status', 'approved');
    } elseif ($was_pro && !$make_pro) {
        // сняли PRO — сбрасываем статус заявки, чтобы можно было подать снова
        $st = bh_user_pro_request_status($user_id);
        if ($st === 'approved') {
            update_user_meta($user_id, 'bgo_pro_request_status', '');
        }
    }
}

// Счётчик pending-заявок PRO рядом с пунктом «Пользователи»
add_action('admin_menu', function () {
    $count = bh_count_pending_pro_requests();
    if ($count <= 0) return;
    global $menu, $submenu;
    $badge = " <span class='awaiting-mod update-plugins count-{$count}'><span class='pending-count'>" . intval($count) . '</span></span>';
    if (is_array($menu)) {
        foreach ($menu as $i => $item) {
            if (isset($item[2]) && $item[2] === 'users.php') {
                $menu[$i][0] .= $badge;
                break;
            }
        }
    }
    if (isset($submenu['users.php']) && is_array($submenu['users.php'])) {
        foreach ($submenu['users.php'] as $i => $item) {
            if (isset($item[2]) && $item[2] === 'users.php') {
                $submenu['users.php'][$i][0] .= $badge;
                break;
            }
        }
    }
}, 999);

// Безопасное преобразование любого значения ACF в строку
function bh_to_string($val) {
    if ($val === null || $val === '') return '';
    if (is_string($val)) return trim($val);
    if (is_numeric($val)) return trim((string)$val);
    if (is_array($val)) {
        if (isset($val['value']) && $val['value'] !== '') return trim((string)$val['value']);
        if (isset($val['label']) && $val['label'] !== '') return trim((string)$val['label']);
        $parts = array();
        foreach ($val as $item) {
            if (is_object($item)) {
                if (isset($item->name)) $parts[] = $item->name;
                else if (isset($item->post_title)) $parts[] = $item->post_title;
            } else if (is_array($item)) {
                if (isset($item['name'])) $parts[] = $item['name'];
                else if (isset($item['post_title'])) $parts[] = $item['post_title'];
                else if (isset($item['title'])) $parts[] = $item['title'];
            } else if (is_string($item)) {
                $parts[] = $item;
            }
        }
        return trim(implode(', ', $parts));
    }
    if (is_object($val)) {
        if (isset($val->name)) return trim($val->name);
        if (isset($val->post_title)) return trim($val->post_title);
    }
    return '';
}

// Поиск значения ACF-поля по фрагменту подписи (label)
function bh_get_field_by_label($post_id, $label_keywords) {
    if (!function_exists('get_field_objects')) return '';
    static $cache = array();
    if (!isset($cache[$post_id])) {
        $fields = get_field_objects($post_id);
        $cache[$post_id] = is_array($fields) ? $fields : array();
    }
    $use_mb = function_exists('mb_strtolower');
    foreach ($cache[$post_id] as $field) {
        $label = isset($field['label']) ? $field['label'] : '';
        $label_lower = $use_mb ? mb_strtolower($label) : strtolower($label);
        foreach ((array)$label_keywords as $kw) {
            $kw_lower = $use_mb ? mb_strtolower($kw) : strtolower($kw);
            $found = $use_mb ? (mb_strpos($label_lower, $kw_lower) !== false) : (strpos($label_lower, $kw_lower) !== false);
            if ($found) {
                return bh_to_string(isset($field['value']) ? $field['value'] : '');
            }
        }
    }
    return '';
}

// Нормализация редкости к английским ключам, используемым в фильтрах
function bh_normalize_rarity($raw) {
    $r = function_exists('mb_strtolower') ? mb_strtolower(trim((string)$raw)) : strtolower(trim((string)$raw));
    if ($r === '') return '';
    if (strpos($r, 'ультра') !== false) return 'legendary';
    if (strpos($r, 'редк') !== false) return 'epic';
    if (strpos($r, 'необыч') !== false) return 'rare';
    if (strpos($r, 'част') !== false) return 'common';
    $en = array('legendary' => 'legendary', 'epic' => 'epic', 'rare' => 'rare', 'common' => 'common');
    return isset($en[$r]) ? $en[$r] : $r;
}

// Получение дополнения (герой-привязка): meta-поле _mmf_hero → ACF
function bh_get_expansion_taxonomy($post_id) {
    $hero = get_post_meta($post_id, '_mmf_hero', true);
    if ($hero && is_string($hero)) {
        $hero = trim($hero);
        if ($hero !== '') return $hero;
    }
    $acf = bh_get_field_by_label($post_id, array('дополнение', 'expansion', 'set', 'серия', 'привязка', 'герой'));
    if ($acf) return $acf;
    foreach (array('card_expansion', 'card_set', 'expansion', 'set', 'card_hero', 'hero') as $fk) {
        $v = trim((string)get_field($fk, $post_id));
        if ($v) return $v;
    }
    return '';
}

// Получение редкости: ACF-поле → таксономия → post meta
function bh_get_rarity($post_id) {
    $rar = bh_get_field_by_label($post_id, array('редкость', 'редк', 'rarity'));
    if (!$rar) $rar = trim((string)get_field('card_rarity', $post_id));
    if (!$rar) $rar = trim((string)get_field('rarity', $post_id));
    if ($rar) return bh_normalize_rarity($rar);

    static $rar_tax = null;
    if ($rar_tax === null) {
        $rar_tax = false;
        $all_tax = get_taxonomies(array(), 'objects');
        $use_mb = function_exists('mb_strtolower');
        foreach ($all_tax as $slug => $obj) {
            $name = $obj->labels->name ?? '';
            $singular = $obj->labels->singular_name ?? '';
            $check = ($use_mb ? mb_strtolower($name . ' ' . $singular . ' ' . $slug) : strtolower($name . ' ' . $singular . ' ' . $slug));
            if (strpos($check, 'редкост') !== false || strpos($check, 'редк') !== false || strpos($check, 'rarity') !== false) {
                $tax_obj = get_taxonomy($slug);
                if ($tax_obj && (in_array('mmf_card', $tax_obj->object_type) || in_array('mm_card', $tax_obj->object_type))) {
                    $rar_tax = $slug;
                    break;
                }
            }
        }
    }
    if ($rar_tax) {
        $terms = wp_get_post_terms($post_id, $rar_tax);
        if (!is_wp_error($terms) && $terms) return bh_normalize_rarity($terms[0]->name);
    }
    $meta_val = get_post_meta($post_id, 'редкость', true);
    if ($meta_val) return bh_normalize_rarity($meta_val);
    return '';
}

// Расчёт стоимости колоды в пыли
function bh_calc_deck_dust($deck_json) {
    if (!$deck_json || !is_array($deck_json)) return 0;
    $cards = isset($deck_json['cards']) ? $deck_json['cards'] : array();
    if (!is_array($cards)) return 0;
    $total = 0;
    foreach ($cards as $c) {
        $rar = isset($c['rarity']) ? $c['rarity'] : '';
        $map = array('legendary' => BH_DUST_LEGENDARY, 'epic' => BH_DUST_EPIC, 'rare' => BH_DUST_RARE, 'common' => BH_DUST_COMMON);
        $cost = isset($map[$rar]) ? $map[$rar] : 0;
        $total += $cost;
    }
    return $total;
}

function bh_debug_acf() {
    $post_id = 44110;
    $all_meta = get_post_meta($post_id);
    $meta_result = array();
    foreach ($all_meta as $key => $vals) {
        $meta_result[$key] = isset($vals[0]) ? $vals[0] : '';
    }
    $fields = get_field_objects($post_id);
    $acf_result = array();
    if ($fields) {
        foreach ($fields as $key => $f) {
            $acf_result[$key] = array('label' => $f['label'], 'type' => $f['type'], 'value' => bh_to_string($f['value']));
        }
    }
    $taxonomies = get_object_taxonomies('mmf_card', 'objects');
    $tax_result = array();
    foreach ($taxonomies as $slug => $obj) {
        $terms = wp_get_post_terms($post_id, $slug);
        $term_names = array();
        if (!is_wp_error($terms)) { foreach ($terms as $t) $term_names[] = $t->name; }
        $tax_result[$slug] = array('label' => $obj->labels->name, 'singular' => $obj->labels->singular_name, 'terms' => $term_names);
    }
    $all_tax_debug = get_taxonomies(array(), 'objects');
    $all_tax_list = array();
    foreach ($all_tax_debug as $slug => $obj) {
        $tax_obj = get_taxonomy($slug);
        $all_tax_list[$slug] = array(
            'label' => $obj->labels->name ?? '',
            'singular' => $obj->labels->singular_name ?? '',
            'object_type' => $tax_obj ? $tax_obj->object_type : array(),
        );
    }
    return array(
        'post_id' => $post_id,
        'all_meta_including_hidden' => $meta_result,
        'acf_fields' => $acf_result,
        'taxonomies' => $tax_result,
        'all_taxonomies' => $all_tax_list,
        'rarity_resolved' => bh_get_rarity($post_id),
        'expansion_resolved' => bh_get_expansion_taxonomy($post_id),
    );
}

/**
 * База декбилдера: штатные CPT «Герои» (mm_hero) и «Карты» (mmf_card).
 * game_id — поле card_game_id записи; картинка — миниатюра/ACF-поле самой записи.
 * Файлы в медиатеке не ищутся по имени и не переименовываются.
 */
function get_berserk_data() {
    $heroes_posts = get_posts(array('post_type' => 'mm_hero', 'numberposts' => -1, 'post_status' => 'publish'));
    $cards_posts  = get_posts(array('post_type' => 'mmf_card', 'numberposts' => -1, 'post_status' => 'publish'));
    $data = array('heroes' => array(), 'cards' => array());
    $all_hero_names = array_map(function($h) { return trim($h->post_title); }, $heroes_posts);
    foreach (array('heroes' => $heroes_posts, 'cards' => $cards_posts) as $key => $posts) {
        foreach ($posts as $post) {
            $title = trim($post->post_title);
            if ($key == 'cards' && in_array($title, $all_hero_names)) continue;
            $img_url = bh_get_card_image_url($post->ID);
            $tax = ($key == 'heroes') ? 'hero_element' : 'mmf_element';
            $terms = wp_get_post_terms($post->ID, $tax);
            $element_data = array();
            if (!is_wp_error($terms)) {
                foreach ($terms as $t) { $element_data[] = $t->slug; $element_data[] = mb_strtolower($t->name); }
            }
            $row = array(
                'id'       => $post->ID,
                'title'    => $title,
                'image'    => $img_url ? $img_url : 'https://via.placeholder.com/200x280?text=IMG',
                'elements' => $element_data,
                'is_horde' => (mb_stripos($post->post_content, 'Орда') !== false),
                'cost'     => (int)get_post_meta($post->ID, 'стоимость', true) ? (int)get_post_meta($post->ID, 'стоимость', true) : ((int)get_field('card_cost', $post->ID) ? (int)get_field('card_cost', $post->ID) : 0),
                'game_id'  => bh_get_card_game_id($post->ID),
            );
            if ($key == 'cards') {
                $row['rarity']      = bh_get_rarity($post->ID);
                $desc = bh_get_field_by_label($post->ID, array('описание'));
                $row['description'] = $desc ? $desc : trim($post->post_content);
                $row['type']        = bh_get_card_type($post->ID);
                $row['expansion']   = bh_get_expansion_taxonomy($post->ID);
                $row['faction']     = bh_get_field_by_label($post->ID, array('фракция'));
            }
            $data[$key][] = $row;
        }
    }
    return $data;
}

function bh_get_visitor_ip() {
    foreach (array('HTTP_CF_CONNECTING_IP','HTTP_X_FORWARDED_FOR','REMOTE_ADDR') as $key) {
        if (!empty($_SERVER[$key])) return trim(explode(',', $_SERVER[$key])[0]);
    }
    return '0.0.0.0';
}

// Получение одной колоды + флаг is_owner
function bh_get_deck(WP_REST_Request $request) {
    global $wpdb;
    $deck_id = intval($request->get_param('id'));
    $user = wp_get_current_user();
    $row = $wpdb->get_row($wpdb->prepare(
        "SELECT d.*, u.display_name as author,
            (SELECT COUNT(*) FROM {$wpdb->prefix}bh_deck_stats WHERE deck_id = d.id AND result = 'win') as wins,
            (SELECT COUNT(*) FROM {$wpdb->prefix}bh_deck_stats WHERE deck_id = d.id AND result = 'loss') as losses
         FROM {$wpdb->prefix}bh_decks d
         LEFT JOIN {$wpdb->prefix}users u ON d.user_id = u.ID
         WHERE d.id = %d", $deck_id));
    if (!$row) return new WP_Error('not_found', 'Колода не найдена', array('status' => 404));
    // Приватная колода видна только автору
    if (!$row->is_public && (!$user->ID || $user->ID != $row->user_id)) {
        return new WP_Error('forbidden', 'Нет доступа', array('status' => 403));
    }
    $row->deck_json   = json_decode($row->deck_json, true);
    $row->is_public   = (int)$row->is_public;
    $row->likes       = (int)$row->likes;
    $row->id          = (int)$row->id;
    $row->hero_wp_id  = (int)$row->hero_wp_id;
    $row->user_id     = (int)$row->user_id;
    $row->wins        = (int)$row->wins;
    $row->losses      = (int)$row->losses;
    $row->total_games = $row->wins + $row->losses;
    $row->winrate     = $row->total_games > 0 ? round($row->wins / $row->total_games * 100, 1) : null;
    $row->updated_at  = $row->updated_at ? strtotime($row->updated_at) : null;
    $row->created_at  = $row->created_at ? strtotime($row->created_at) : null;
    $row->is_owner    = ($user->ID && $user->ID == $row->user_id);
    $row->dust_cost   = bh_calc_deck_dust($row->deck_json);
    $row->guide_url = isset($row->guide_url) ? (string)$row->guide_url : '';
    $row->video_guide_url = isset($row->video_guide_url) ? (string)$row->video_guide_url : '';
    $row->video_url = $row->video_guide_url;
    $row->author_id = (int)$row->user_id;
    bh_attach_author_pro($row);
    // Лайк от текущего юзера
    $row->liked_by_me = false;
    if ($user->ID) {
        $ip = bh_get_visitor_ip();
        $liked = $wpdb->get_row($wpdb->prepare("SELECT id FROM {$wpdb->prefix}bh_deck_likes WHERE deck_id = %d AND ip = %s", $deck_id, $ip));
        if ($liked) $row->liked_by_me = true;
    }
    return $row;
}

// Обновление description и/или game_code (только автор)
function bh_update_deck_meta(WP_REST_Request $request) {
    $user = wp_get_current_user();
    if (!$user->ID) return new WP_Error('unauthorized', 'Не авторизован', array('status' => 401));
    global $wpdb;
    $deck_id = intval($request->get_param('id'));
    $existing = $wpdb->get_row($wpdb->prepare("SELECT * FROM {$wpdb->prefix}bh_decks WHERE id = %d AND user_id = %d", $deck_id, $user->ID));
    if (!$existing) return new WP_Error('forbidden', 'Нет доступа', array('status' => 403));
    $p = $request->get_json_params();
    $update = array();
    if (isset($p['description'])) $update['description'] = sanitize_textarea_field($p['description']);
    if (isset($p['game_code']))  $update['game_code']  = sanitize_text_field($p['game_code']);
    if (isset($p['guide_url'])) $update['guide_url'] = esc_url_raw($p['guide_url']);
    if (isset($p['video_guide_url'])) $update['video_guide_url'] = esc_url_raw($p['video_guide_url']);
    if (isset($p['name'])) $update['name'] = sanitize_text_field($p['name']);
    if (empty($update)) return array('success' => true);
    $wpdb->update("{$wpdb->prefix}bh_decks", $update, array('id' => $deck_id, 'user_id' => $user->ID));
    return array('success' => true);
}

function bh_get_public_decks() {
    global $wpdb;
    $rows = $wpdb->get_results(
        "SELECT d.*, u.display_name as author,
            (SELECT COUNT(*) FROM {$wpdb->prefix}bh_deck_stats WHERE deck_id = d.id AND result = 'win') as wins,
            (SELECT COUNT(*) FROM {$wpdb->prefix}bh_deck_stats WHERE deck_id = d.id AND result = 'loss') as losses
         FROM {$wpdb->prefix}bh_decks d
         LEFT JOIN {$wpdb->prefix}users u ON d.user_id = u.ID
         WHERE d.is_public = 1
         ORDER BY d.likes DESC, d.updated_at DESC"
    );
    if (!$rows) return array();
    foreach ($rows as &$row) {
        $row->deck_json   = json_decode($row->deck_json, true);
        $row->is_public   = (int) $row->is_public;
        $row->likes       = (int) $row->likes;
        $row->id          = (int) $row->id;
        $row->hero_wp_id  = (int) $row->hero_wp_id;
        $row->wins        = (int) $row->wins;
        $row->losses      = (int) $row->losses;
        $row->total_games = $row->wins + $row->losses;
        $row->winrate     = $row->total_games > 0 ? round($row->wins / $row->total_games * 100, 1) : null;
        $row->updated_at  = $row->updated_at ? strtotime($row->updated_at) : null;
        $row->created_at  = $row->created_at ? strtotime($row->created_at) : null;
        $row->liked_by_me = false;
        $row->dust_cost   = bh_calc_deck_dust($row->deck_json);
        $row->user_id = (int)$row->user_id;
        $row->author_id = $row->user_id;
        $row->guide_url = isset($row->guide_url) ? (string)$row->guide_url : '';
        $row->video_guide_url = isset($row->video_guide_url) ? (string)$row->video_guide_url : '';
        $row->video_url = $row->video_guide_url;
        bh_attach_author_pro($row);
    }
    return $rows;
}

function bh_get_my_decks() {
    $user = wp_get_current_user();
    if (!$user->ID) return new WP_Error('unauthorized', 'Не авторизован', array('status' => 401));
    global $wpdb;
    $decks = $wpdb->get_results($wpdb->prepare("SELECT * FROM {$wpdb->prefix}bh_decks WHERE user_id = %d ORDER BY updated_at DESC", $user->ID));
    foreach ($decks as &$deck) {
        $deck->deck_json  = json_decode($deck->deck_json, true);
        $deck->is_public  = (int) $deck->is_public;
        $deck->likes      = (int) $deck->likes;
        $deck->id         = (int) $deck->id;
        $deck->hero_wp_id = (int) $deck->hero_wp_id;
        $deck->updated_at = $deck->updated_at ? strtotime($deck->updated_at) : null;
        $deck->created_at = $deck->created_at ? strtotime($deck->created_at) : null;
        $deck->dust_cost  = bh_calc_deck_dust($deck->deck_json);
        $deck->guide_url = isset($deck->guide_url) ? (string)$deck->guide_url : '';
        $deck->video_guide_url = isset($deck->video_guide_url) ? (string)$deck->video_guide_url : '';
        $deck->video_url = $deck->video_guide_url;
        $deck->user_id = (int)$deck->user_id;
        $deck->author_id = $deck->user_id;
        bh_attach_author_pro($deck);
    }
    return $decks;
}

function bh_save_deck(WP_REST_Request $request) {
    $user = wp_get_current_user();
    if (!$user->ID) return new WP_Error('unauthorized', 'Не авторизован', array('status' => 401));
    global $wpdb;
    $p = $request->get_json_params();
    $name      = sanitize_text_field($p['name'] ? $p['name'] : 'Без названия');
    $hero_id   = intval($p['hero_wp_id'] ? $p['hero_wp_id'] : 0);
    $deck_json = wp_json_encode($p['deck'] ? $p['deck'] : array());
    $header_id = sanitize_text_field($p['header_id'] ? $p['header_id'] : '');
    $hero_le   = sanitize_text_field($p['hero_le'] ? $p['hero_le'] : '');
    $game_code = isset($p['game_code']) ? sanitize_text_field($p['game_code']) : '';
    $guide_url = isset($p['guide_url']) ? esc_url_raw($p['guide_url']) : '';
    $video_guide_url = isset($p['video_guide_url']) ? esc_url_raw($p['video_guide_url']) : '';
    $is_public = intval($p['is_public'] ? $p['is_public'] : 0);
    $deck_id   = intval($p['id'] ? $p['id'] : 0);
    $payload = array(
        'name' => $name,
        'hero_wp_id' => $hero_id,
        'deck_json' => $deck_json,
        'header_id' => $header_id,
        'hero_le' => $hero_le,
        'game_code' => $game_code,
        'guide_url' => $guide_url,
        'video_guide_url' => $video_guide_url,
        'is_public' => $is_public,
    );
    if ($deck_id) {
        $existing = $wpdb->get_row($wpdb->prepare("SELECT id FROM {$wpdb->prefix}bh_decks WHERE id = %d AND user_id = %d", $deck_id, $user->ID));
        if (!$existing) return new WP_Error('forbidden', 'Нет доступа', array('status' => 403));
        $wpdb->update("{$wpdb->prefix}bh_decks", $payload, array('id' => $deck_id, 'user_id' => $user->ID));
        if ($wpdb->last_error) return new WP_Error('update_failed', 'Ошибка БД: ' . $wpdb->last_error, array('status' => 500));
        return array('success' => true, 'id' => $deck_id);
    } else {
        $payload['user_id'] = $user->ID;
        $wpdb->insert("{$wpdb->prefix}bh_decks", $payload);
        if ($wpdb->last_error || !$wpdb->insert_id) return new WP_Error('insert_failed', 'Ошибка БД: ' . $wpdb->last_error, array('status' => 500));
        return array('success' => true, 'id' => $wpdb->insert_id);
    }
}

function bh_set_deck_visibility(WP_REST_Request $request) {
    $user = wp_get_current_user();
    if (!$user->ID) return new WP_Error('unauthorized', 'Не авторизован', array('status' => 401));
    global $wpdb;
    $deck_id   = intval($request->get_param('id'));
    $is_public = intval($request->get_json_params()['is_public'] ? $request->get_json_params()['is_public'] : 0);
    $existing  = $wpdb->get_row($wpdb->prepare("SELECT id FROM {$wpdb->prefix}bh_decks WHERE id = %d AND user_id = %d", $deck_id, $user->ID));
    if (!$existing) return new WP_Error('forbidden', 'Нет доступа', array('status' => 403));
    $result = $wpdb->query($wpdb->prepare("UPDATE {$wpdb->prefix}bh_decks SET is_public = %d, updated_at = NOW() WHERE id = %d AND user_id = %d", $is_public, $deck_id, $user->ID));
    return array('success' => $result !== false);
}

function bh_delete_deck(WP_REST_Request $request) {
    $user = wp_get_current_user();
    if (!$user->ID) return new WP_Error('unauthorized', 'Не авторизован', array('status' => 401));
    global $wpdb;
    $deck_id = intval($request->get_param('id'));
    $existing = $wpdb->get_row($wpdb->prepare("SELECT id FROM {$wpdb->prefix}bh_decks WHERE id = %d AND user_id = %d", $deck_id, $user->ID));
    if (!$existing) return new WP_Error('not_found', 'Колода не найдена', array('status' => 404));
    $wpdb->delete("{$wpdb->prefix}bh_decks", array('id' => $deck_id, 'user_id' => $user->ID));
    return new WP_REST_Response(array('success' => true), 200);
}

function bh_like_deck(WP_REST_Request $request) {
    global $wpdb;
    $deck_id = intval($request->get_param('id'));
    $ip = bh_get_visitor_ip();
    $existing = $wpdb->get_row($wpdb->prepare("SELECT id FROM {$wpdb->prefix}bh_deck_likes WHERE deck_id = %d AND ip = %s", $deck_id, $ip));
    if ($existing) {
        $wpdb->delete("{$wpdb->prefix}bh_deck_likes", array('deck_id' => $deck_id, 'ip' => $ip));
        $wpdb->query($wpdb->prepare("UPDATE {$wpdb->prefix}bh_decks SET likes = GREATEST(0, likes - 1) WHERE id = %d", $deck_id));
        $liked = false;
    } else {
        $wpdb->insert("{$wpdb->prefix}bh_deck_likes", array('deck_id' => $deck_id, 'ip' => $ip));
        $wpdb->query($wpdb->prepare("UPDATE {$wpdb->prefix}bh_decks SET likes = likes + 1 WHERE id = %d", $deck_id));
        $liked = true;
    }
    $deck = $wpdb->get_row($wpdb->prepare("SELECT likes FROM {$wpdb->prefix}bh_decks WHERE id = %d", $deck_id));
    return array('success' => true, 'liked' => $liked, 'likes' => intval($deck->likes));
}

function bh_record_deck_result(WP_REST_Request $request) {
    $user = wp_get_current_user();
    if (!$user->ID) return new WP_Error('unauthorized', 'Не авторизован', array('status' => 401));
    global $wpdb;
    $deck_id = intval($request->get_param('id'));
    $result  = $request->get_json_params()['result'] ? $request->get_json_params()['result'] : '';
    if (!in_array($result, array('win', 'loss'))) return new WP_Error('invalid', 'Неверный результат', array('status' => 400));
    $deck = $wpdb->get_row($wpdb->prepare("SELECT id FROM {$wpdb->prefix}bh_decks WHERE id = %d", $deck_id));
    if (!$deck) return new WP_Error('not_found', 'Колода не найдена', array('status' => 404));
    $wpdb->insert("{$wpdb->prefix}bh_deck_stats", array('deck_id' => $deck_id, 'user_id' => $user->ID, 'result' => $result));
    return array('success' => true);
}

function bh_get_meta_stats() {
    global $wpdb;
    $decks = $wpdb->get_results(
        "SELECT d.*, u.display_name as author,
            (SELECT COUNT(*) FROM {$wpdb->prefix}bh_deck_stats WHERE deck_id = d.id AND result = 'win') as wins,
            (SELECT COUNT(*) FROM {$wpdb->prefix}bh_deck_stats WHERE deck_id = d.id AND result = 'loss') as losses
         FROM {$wpdb->prefix}bh_decks d
         LEFT JOIN {$wpdb->prefix}users u ON d.user_id = u.ID
         WHERE d.is_public = 1
         ORDER BY d.likes DESC, d.updated_at DESC"
    );
    $cardCounts = array();
    $totalDecks = 0;
    foreach ($decks as $deck) {
        $totalDecks++;
        $deckData = json_decode($deck->deck_json, true);
        $cards = $deckData['cards'] ? $deckData['cards'] : array();
        $seen = array();
        foreach ($cards as $c) {
            if (!in_array($c['id'], $seen)) { $seen[] = $c['id']; $cardCounts[$c['id']] = (isset($cardCounts[$c['id']]) ? $cardCounts[$c['id']] : 0) + 1; }
        }
    }
    arsort($cardCounts);
    $topCards = array_slice($cardCounts, 0, 30, true);
    foreach ($decks as &$row) {
        $row->deck_json   = json_decode($row->deck_json, true);
        $row->is_public   = (int)$row->is_public;
        $row->likes       = (int)$row->likes;
        $row->id          = (int)$row->id;
        $row->hero_wp_id  = (int)$row->hero_wp_id;
        $row->wins        = (int)$row->wins;
        $row->losses      = (int)$row->losses;
        $row->total_games = $row->wins + $row->losses;
        $row->winrate     = $row->total_games > 0 ? round($row->wins / $row->total_games * 100, 1) : null;
        $row->updated_at  = $row->updated_at ? strtotime($row->updated_at) : null;
        $row->created_at  = $row->created_at ? strtotime($row->created_at) : null;
        $row->liked_by_me = false;
        $row->dust_cost   = bh_calc_deck_dust($row->deck_json);
    }
    return array('decks' => $decks, 'top_cards' => $topCards, 'total_decks' => $totalDecks);
}

function bh_submit_mapping(WP_REST_Request $request) {
    global $wpdb;
    $mappings = $request->get_json_params()['mappings'] ? $request->get_json_params()['mappings'] : array();
    foreach ($mappings as $m) {
        $game_id_be = strtolower(sanitize_text_field($m['game_id_be'] ? $m['game_id_be'] : ''));
        $card_name  = sanitize_text_field($m['card_name'] ? $m['card_name'] : '');
        if (!$game_id_be || !preg_match('/^[a-f0-9]{8}$/', $game_id_be)) continue;
        $wp_post_id = 0;
        if ($card_name) {
            $post = get_page_by_title($card_name, OBJECT, 'mmf_card');
            if (!$post) $post = get_page_by_title($card_name, OBJECT, 'mm_hero');
            if ($post) $wp_post_id = $post->ID;
        }
        if ($wp_post_id) {
            $approved = $wpdb->get_row($wpdb->prepare("SELECT * FROM {$wpdb->prefix}bh_card_mappings WHERE game_id_be = %s AND status = 'approved'", $game_id_be));
            if ($approved && $approved->wp_post_id != $wp_post_id) continue;
        }
        $existing = $wpdb->get_row($wpdb->prepare("SELECT * FROM {$wpdb->prefix}bh_card_mappings WHERE game_id_be = %s AND wp_post_id = %d", $game_id_be, $wp_post_id));
        if ($existing) {
            $wpdb->update("{$wpdb->prefix}bh_card_mappings", array('votes' => $existing->votes + 1, 'card_name' => $card_name), array('id' => $existing->id));
        } else {
            $wpdb->insert("{$wpdb->prefix}bh_card_mappings", array('game_id_be' => $game_id_be, 'wp_post_id' => $wp_post_id, 'card_name' => $card_name, 'votes' => 1));
        }
    }
    return array('success' => true);
}

function bh_get_mappings() {
    global $wpdb;
    $rows = $wpdb->get_results("SELECT game_id_be, wp_post_id FROM {$wpdb->prefix}bh_card_mappings WHERE status = 'approved'");
    $result = array();
    foreach ($rows as $r) { $result[$r->game_id_be] = intval($r->wp_post_id); }
    return $result;
}


add_action('admin_menu', function() {
    add_menu_page('BH Маппинги', 'BH Маппинги', 'manage_options', 'bh-mappings', 'bh_mappings_admin_page', 'dashicons-admin-generic', 30);
    add_management_page('BH Маппинги', 'BH Маппинги', 'manage_options', 'bh-mappings-tools', 'bh_mappings_admin_page');
});
add_action('admin_post_bh_approve_mapping', function() {
    if (!current_user_can('manage_options')) wp_die('Нет доступа');
    global $wpdb;
    $id  = intval($_POST['mapping_id']);
    $row = $wpdb->get_row($wpdb->prepare("SELECT * FROM {$wpdb->prefix}bh_card_mappings WHERE id = %d", $id));
    if ($row && $row->wp_post_id) {
        $wpdb->update("{$wpdb->prefix}bh_card_mappings", array('status' => 'approved'), array('id' => $id));
        update_field('card_game_id', $row->game_id_be, $row->wp_post_id);
        update_post_meta($row->wp_post_id, 'card_game_id', $row->game_id_be);
    }
    wp_redirect(admin_url('admin.php?page=bh-mappings&approved=1')); exit;
});
add_action('admin_post_bh_reject_mapping', function() {
    if (!current_user_can('manage_options')) wp_die('Нет доступа');
    global $wpdb;
    $wpdb->delete("{$wpdb->prefix}bh_card_mappings", array('id' => intval($_POST['mapping_id'])));
    wp_redirect(admin_url('admin.php?page=bh-mappings&rejected=1')); exit;
});
add_action('admin_post_bh_bulk_approve', function() {
    if (!current_user_can('manage_options')) wp_die('Нет доступа');
    global $wpdb;
    $min_votes = intval($_POST['min_votes'] ? $_POST['min_votes'] : 3);
    $rows = $wpdb->get_results($wpdb->prepare("SELECT * FROM {$wpdb->prefix}bh_card_mappings WHERE status = 'pending' AND votes >= %d AND wp_post_id > 0", $min_votes));
    $count = 0;
    foreach ($rows as $row) {
        $wpdb->update("{$wpdb->prefix}bh_card_mappings", array('status' => 'approved'), array('id' => $row->id));
        update_field('card_game_id', $row->game_id_be, $row->wp_post_id);
        update_post_meta($row->wp_post_id, 'card_game_id', $row->game_id_be);
        $count++;
    }
    wp_redirect(admin_url('admin.php?page=bh-mappings&bulk_approved=' . $count)); exit;
});

function bh_mappings_admin_page() {
    global $wpdb;
    $filter   = sanitize_text_field($_GET['filter'] ? $_GET['filter'] : 'all');
    $where    = $filter === 'pending' ? "WHERE m.status = 'pending'" : ($filter === 'approved' ? "WHERE m.status = 'approved'" : '');
    $mappings = $wpdb->get_results("SELECT m.*, p.post_title as wp_card_name FROM {$wpdb->prefix}bh_card_mappings m LEFT JOIN {$wpdb->posts} p ON m.wp_post_id = p.ID $where ORDER BY m.votes DESC, m.status ASC");
    echo '<div class="wrap"><h1>BH Маппинги игровых ID</h1>';
    if (isset($_GET['approved'])) echo '<div class="notice notice-success"><p>Маппинг подтверждён.</p></div>';
    if (isset($_GET['rejected'])) echo '<div class="notice notice-warning"><p>Маппинг удалён.</p></div>';
    if (isset($_GET['bulk_approved'])) echo '<div class="notice notice-success"><p>Подтверждено: ' . intval($_GET['bulk_approved']) . '.</p></div>';
    echo '<div style="display:flex;gap:15px;align-items:center;margin-bottom:20px;flex-wrap:wrap">';
    echo '<form method="post" action="' . admin_url('admin-post.php') . '" style="display:flex;gap:8px;align-items:center">';
    echo '<input type="hidden" name="action" value="bh_bulk_approve">';
    wp_nonce_field('bh_mapping_action');
    echo '<label style="font-weight:bold">Массово подтвердить с голосами ≥</label>';
    echo '<input type="number" name="min_votes" value="3" min="1" style="width:60px">';
    echo '<button type="submit" class="button button-primary">Применить</button>';
    echo '</form><div style="margin-left:auto">';
    echo '<a href__="' . admin_url('admin.php?page=bh-mappings&filter=all') . '" class="button ' . ($filter==='all'?'button-primary':'') . '">Все</a> ';
    echo '<a href__="' . admin_url('admin.php?page=bh-mappings&filter=pending') . '" class="button ' . ($filter==='pending'?'button-primary':'') . '">Ожидают</a> ';
    echo '<a href__="' . admin_url('admin.php?page=bh-mappings&filter=approved') . '" class="button ' . ($filter==='approved'?'button-primary':'') . '">Подтверждённые</a>';
    echo '</div></div>';
    echo '<table class="widefat striped"><thead><tr><th>Game ID</th><th>Название</th><th>WP карта</th><th>WP ID</th><th>Голосов</th><th>Статус</th><th>Действия</th></tr></thead><tbody>';
    foreach ($mappings as $m) {
        echo '<tr><td><code>' . esc_html($m->game_id_be) . '</code></td>';
        echo '<td>' . esc_html($m->card_name) . '</td>';
        echo '<td>' . esc_html($m->wp_card_name ? $m->wp_card_name : '—') . '</td>';
        echo '<td>' . ($m->wp_post_id ? esc_html($m->wp_post_id) : '<span style="color:#e74c3c">не найдена</span>') . '</td>';
        echo '<td><strong>' . esc_html($m->votes) . '</strong></td>';
        echo '<td>' . ($m->status === 'approved' ? '<span style="color:green">✓</span>' : '<span style="color:orange">⏳</span>') . '</td><td>';
        if ($m->status === 'pending' && $m->wp_post_id) {
            echo '<form method="post" action="' . admin_url('admin-post.php') . '" style="display:inline">';
            echo '<input type="hidden" name="action" value="bh_approve_mapping">';
            echo '<input type="hidden" name="mapping_id" value="' . $m->id . '">';
            wp_nonce_field('bh_mapping_action');
            echo '<button type="submit" class="button button-primary">Подтвердить</button></form> ';
        }
        echo '<form method="post" action="' . admin_url('admin-post.php') . '" style="display:inline">';
        echo '<input type="hidden" name="action" value="bh_reject_mapping">';
        echo '<input type="hidden" name="mapping_id" value="' . $m->id . '">';
        wp_nonce_field('bh_mapping_action');
        echo '<button type="submit" class="button">Удалить</button></form>';
        echo '</td></tr>';
    }
    echo '</tbody></table></div>';
}

// ============================================================
// ШОРТКОД: Декбилдер [berserk_deckbuilder]
// ============================================================
add_shortcode('berserk_deckbuilder', function() {
    ob_start(); ?>
<div id="berserk-app" class="db-v41">
  <div v-if="loading" class="db-loading">Загрузка базы карт...</div>
  <div v-else>
    <div v-if="!selectedHero">
      <h1 class="db-main-title">ВЫБЕРИТЕ ГЕРОЯ</h1>
      <div v-for="group in heroGroups" :key="group.key" style="margin-bottom:28px">
        <h3 :style="{color:group.color,marginBottom:'10px',letterSpacing:'1px',borderBottom:'1px solid '+group.color,paddingBottom:'5px',fontSize:'14px'}">{{ group.label }}</h3>
        <div class="db-heroes-grid">
          <div v-for="h in group.heroes" :key="h.id" @click="selectedHero = h; hoveredHero = null" @mouseenter="onHeroHover(h)" @mouseleave="onHeroLeave()" class="db-hero-item">
            <div class="db-hero-img-wrap"><img :src="h.image"></div>
            <div class="db-label">{{ h.title }}</div>
          </div>
        </div>
      </div>
    </div>
    <div v-else>
      <div class="db-toolbar">
        <button @click="selectedHero = null; deck = []; resetImport()" class="db-btn-back">← Герои</button>
        <input v-model="search" placeholder="Поиск по названию или тексту карты..." class="db-search">
        <div class="db-hero-tag">{{ selectedHero.title }}</div>
      </div>
      <div class="db-filters">
        <div class="db-filter-group"><span class="db-filter-label">Редкость:</span>
          <button v-for="r in rarityOptions" :key="r.key" @click="filterRarity = filterRarity===r.key ? '' : r.key" :class="['db-filter-btn', filterRarity===r.key ? 'db-filter-active' : '']">{{ r.label }}</button>
        </div>
        <div class="db-filter-group"><span class="db-filter-label">Дополнение:</span>
          <select v-model="filterExpansion" class="db-filter-select"><option value="">Все</option><option v-for="exp in expansionOptions" :key="exp" :value="exp">{{ exp }}</option></select>
        </div>
        <div class="db-filter-group"><span class="db-filter-label">Стоимость:</span>
          <button v-for="c in costOptions" :key="c.key" @click="filterCost = filterCost===c.key ? '' : c.key" :class="['db-filter-btn', filterCost===c.key ? 'db-filter-active' : '']">{{ c.label }}</button>
        </div>
        <button v-if="filterRarity || filterExpansion || filterCost || search" @click="filterRarity=''; filterExpansion=''; filterCost=''; search=''" class="db-filter-clear">Сбросить</button>
      </div>
      <div class="db-mobile-header">
        <div class="db-counter" :class="{ok:deck.length>=40,err:deck.length>60}">{{ deck.length }}/60 · 💎{{ dustCost }}</div>
        <div style="display:flex;gap:6px">
          <button @click="showImportModal = true" class="db-btn-import-sm">📥 Импорт</button>
          <button v-if="currentUser" @click="saveDeck(0)" class="db-btn-save-sm">💾</button>
          <button v-if="currentUser" @click="saveDeck(1)" class="db-btn-save-sm db-btn-save-pub-sm">🌐</button>
        </div>
      </div>
      <div class="db-mobile-tabs">
        <button @click="mobileTab='cards'" :class="['db-tab', mobileTab==='cards' ? 'db-tab-active' : '']">🃏 Карты</button>
        <button @click="mobileTab='deck'" :class="['db-tab', mobileTab==='deck' ? 'db-tab-active' : '']">📋 Колода ({{ deck.length }})</button>
      </div>
      <div class="db-builder-layout">
        <div class="db-left-side" :class="{'db-hidden-mobile': mobileTab !== 'cards'}">
          <div class="db-cards-grid">
            <div v-for="c in filteredCards" :key="c.id" @click="addToDeck(c)" class="db-card-small" :class="{maxed: isMaxed(c)}"
                 @mouseenter="onCardHover(c)" @mouseleave="onCardLeave()">
              <img :src="c.image">
              <div v-if="getCount(c.id) > 0" class="db-badge">{{ getCount(c.id) }}</div>
              <div v-if="c.is_horde" class="db-horde-tag">ОРДА</div>
            </div>
          </div>
        </div>
        <div class="db-right-side" :class="{'db-hidden-mobile': mobileTab !== 'deck'}">
          <div class="db-sidebar-card">
            <h3 style="color:#f1c40f;margin:0 0 4px;font-size:14px">{{ selectedHero.title }}</h3>
            <div v-if="currentDeckId" style="font-size:10px;color:#7ec8e3;margin-bottom:4px">✏️ Редактирование #{{ currentDeckId }}</div>
            <div class="db-counter db-counter-desktop" :class="{ok:deck.length>=40,err:deck.length>60}">Карт: {{ deck.length }} / 60</div>
            <div class="db-dust-cost">💎 Пыль на крафт: {{ dustCost }}</div>
            <div class="db-type-row">
              <div class="db-type-col"><div class="db-type-icon">🐉</div><div class="db-type-count">{{ typeCounts.creature }}</div><div class="db-type-label">Существа</div></div>
              <div class="db-type-col"><div class="db-type-icon">🔥</div><div class="db-type-count">{{ typeCounts.spell }}</div><div class="db-type-label">Заклинания</div></div>
              <div class="db-type-col"><div class="db-type-icon">🛡️</div><div class="db-type-count">{{ typeCounts.equipment }}</div><div class="db-type-label">Экипировка</div></div>
            </div>
            <div class="db-deck-list">
              <div v-for="item in groupedDeck" :key="item.id" @click="removeFromDeckById(item.id)" class="db-deck-strip" :style="{backgroundImage:'url('+item.image+')',borderLeftColor:getElemColor(item.elements)}"
                   @mouseenter="onCardHover(item)" @mouseleave="onCardLeave()">
                <div class="strip-overlay" :style="{background:'linear-gradient(90deg,'+getElemAlpha(item.elements)+' 0%,rgba(0,0,0,0.55) 45%,rgba(0,0,0,0.05) 100%)'}"></div>
                <span class="strip-cost">{{ item.cost }}</span><span class="strip-title">{{ item.title }}</span><span class="strip-count" :style="{background:getElemColor(item.elements),color:getElemText(item.elements)}">{{ item.count }}x</span>
              </div>
            </div>
            <div class="db-footer">
              <div v-if="currentUser" style="font-size:10px;color:#4caf50;margin-bottom:5px">👤 {{ currentUser.name }}</div>
              <div v-if="headerIdHex" class="db-account-badge">✓ Код колоды готов к экспорту</div>
              <div class="db-guide-fields">
                <input v-model="guideUrl" class="db-guide-input" type="url" placeholder="Ссылка на текстовый гайд (необяз.)">
                <input v-model="videoGuideUrl" class="db-guide-input" type="url" placeholder="Ссылка на YouTube-видеогайд (необяз.)">
              </div>
              <div v-if="currentUser" class="db-pro-box">
                <div class="db-pro-head">
                  <strong>Статус PRO</strong>
                  <span v-if="proInfo.is_pro || proInfo.request_status==='approved'" class="bh-pro-badge">У вас активен статус PRO</span>
                </div>
                <div v-if="!proInfo.is_pro && proInfo.request_status==='pending'" class="db-pro-pending">Заявка на статус PRO отправлена и ожидает проверки администратора</div>
                <button v-else-if="!proInfo.is_pro && proInfo.request_status!=='approved' && !showProForm" @click="showProForm=true" class="db-btn-import" style="margin-top:6px">Запросить статус PRO</button>
                <div v-if="showProForm && !proInfo.is_pro && proInfo.request_status!=='pending' && proInfo.request_status!=='approved'" style="margin-top:6px">
                  <textarea v-model="proAchievements" rows="3" class="db-guide-input" placeholder="Турниры, ладдер, достижения..."></textarea>
                  <div style="display:flex;gap:5px;margin-top:5px">
                    <button @click="submitProRequest" :disabled="proSubmitting" class="db-btn-save db-btn-save-pub" style="flex:1">{{ proSubmitting ? '...' : 'Отправить' }}</button>
                    <button @click="showProForm=false" class="db-btn-save" style="flex:1">Отмена</button>
                  </div>
                </div>
              </div>
              <button @click="copyGeneratedCode" class="db-btn-copy" :disabled="deck.length < 40">{{ codeCopied ? '✓ Скопировано' : 'Скопировать код колоды' }}</button>
              <button @click="showImportModal = true" class="db-btn-import">ИМПОРТ КОДА ИЗ ИГРЫ</button>
              <div v-if="currentUser" style="display:flex;gap:5px;margin-top:8px">
                <button @click="saveDeck(0)" class="db-btn-save">💾 Приватно</button>
                <button @click="saveDeck(1)" class="db-btn-save db-btn-save-pub">🌐 Публично</button>
              </div>
              <div v-else style="font-size:10px;color:#888;text-align:center;margin-top:8px"><a :href__="loginUrl" style="color:#7ec8e3;text-decoration:underline;cursor:pointer">Войдите</a> чтобы сохранять колоды</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <div v-if="hoveredCard" class="db-card-popup" :style="{ backgroundImage: 'url(' + hoveredCard.image + ')' }"></div>

  <div v-if="hoveredHero" class="db-hero-popup" :style="{ backgroundImage: 'url(' + hoveredHero.image + ')' }">
    <div class="db-popup-info">
      <span class="db-popup-title">{{ hoveredHero.title }}</span>
    </div>
  </div>

  <div v-if="showImportModal" class="db-modal-overlay" @click.self="showImportModal = false">
    <div class="db-modal">
      <h3 style="color:#f1c40f;margin:0 0 8px;font-size:14px">Импорт кода колоды</h3>
      <p style="color:#aaa;font-size:11px;margin:0 0 10px">Вставьте одну Base64-строку кода колоды (как из «Скопировать код колоды» / импорт в игре).</p>
      <textarea v-model="importText" rows="4" class="db-import-textarea" placeholder="QkhEMa..."></textarea>
      <div style="display:flex;gap:8px;margin-top:10px">
        <button @click="doFullImport" style="flex:1;padding:10px;background:#f1c40f;color:#000;border:none;border-radius:6px;cursor:pointer;font-weight:bold">Импортировать</button>
        <button @click="showImportModal = false" style="flex:1;padding:10px;background:#333;color:#fff;border:none;border-radius:6px;cursor:pointer">Отмена</button>
      </div>
      <div v-if="importStatus" style="margin-top:10px;padding:8px;border-radius:6px;font-size:11px" :style="{background:importStatus.ok?'#1a3d1a':'#3d1a1a',color:importStatus.ok?'#4caf50':'#e74c3c'}">{{ importStatus.msg }}</div>
    </div>
  </div>
</div>
<script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>
<style>
.db-v41{background:#070707;color:#eee;padding:14px;border-radius:15px;font-family:sans-serif;position:relative}
.db-main-title{text-align:center;color:#f1c40f;letter-spacing:2px;margin-bottom:24px;font-size:clamp(16px,5vw,24px);text-transform:uppercase}
.db-loading{text-align:center;padding:80px;color:#f1c40f;font-size:16px}
.db-label{text-align:center;font-size:10px;margin-top:4px;color:#ccc}
.db-heroes-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:12px}
.db-hero-item{cursor:pointer;transition:0.2s;display:flex;flex-direction:column;align-items:center}
.db-hero-item:hover{transform:translateY(-3px)}
.db-hero-img-wrap{width:100%;aspect-ratio:5/7;overflow:hidden;border-radius:8px;border:1px solid #444;background:#111}
.db-hero-img-wrap img{width:100%;height:100%;object-fit:cover;display:block}
.db-toolbar{display:flex;gap:8px;margin-bottom:10px;align-items:center;flex-wrap:wrap}
.db-search{padding:8px;background:#111;border:1px solid #333;color:#fff;border-radius:6px;flex:1;min-width:100px;font-size:13px}
.db-btn-back{background:#222;color:#fff;border:1px solid #333;padding:8px 10px;cursor:pointer;border-radius:6px;font-size:11px;white-space:nowrap}
.db-hero-tag{font-size:11px;color:#f1c40f;border:1px solid #f1c40f;padding:5px 8px;border-radius:5px;font-weight:bold;white-space:nowrap}
.db-filters{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px;align-items:center;padding:8px;background:#0d0d0d;border:1px solid #222;border-radius:8px}
.db-filter-group{display:flex;align-items:center;gap:4px;flex-wrap:wrap}
.db-filter-label{font-size:10px;color:#666;font-weight:bold;white-space:nowrap}
.db-filter-btn{background:#1a1a1a;color:#888;border:1px solid #333;border-radius:4px;padding:3px 8px;cursor:pointer;font-size:10px;font-weight:bold;transition:0.15s}
.db-filter-btn:hover{border-color:#555;color:#ccc}
.db-filter-active{background:#f1c40f!important;color:#000!important;border-color:#f1c40f!important}
.db-filter-select{background:#1a1a1a;color:#ccc;border:1px solid #333;border-radius:4px;padding:3px 6px;font-size:10px;cursor:pointer}
.db-filter-select:focus{outline:none;border-color:#f1c40f}
.db-filter-clear{background:#3d1a1a;color:#e74c3c;border:1px solid #7d2d2d;border-radius:4px;padding:3px 10px;cursor:pointer;font-size:10px;font-weight:bold;margin-left:auto}
.db-dust-cost{font-size:12px;font-weight:bold;color:#7ec8e3;margin:4px 0}
.db-type-row{display:flex;gap:6px;margin:0 0 10px;padding:8px;background:#0a0a0a;border:1px solid #222;border-radius:8px}
.db-type-col{flex:1;text-align:center}
.db-type-icon{font-size:14px;line-height:1}
.db-type-count{font-size:16px;font-weight:bold;color:#fff;margin-top:2px}
.db-type-label{font-size:9px;color:#888;text-transform:uppercase;margin-top:2px}
.db-guide-fields{display:flex;flex-direction:column;gap:5px;margin-bottom:8px}
.db-guide-input{width:100%;box-sizing:border-box;background:#0a0a0a;border:1px solid #333;color:#ccc;border-radius:6px;padding:7px 8px;font-size:11px}
.db-pro-box{margin:8px 0;padding:8px;background:#0d0d0d;border:1px solid #333;border-radius:8px}
.db-pro-head{display:flex;justify-content:space-between;align-items:center;gap:6px;flex-wrap:wrap;font-size:11px;color:#f1c40f;margin-bottom:4px}
.db-pro-pending{font-size:11px;line-height:1.35;color:#ffa726;background:rgba(255,167,38,.08);border:1px solid rgba(255,167,38,.35);border-radius:6px;padding:6px 8px}
.db-v41 .bh-pro-badge{display:inline-block;background:linear-gradient(135deg,#f1c40f,#e67e22);color:#111;font-size:9px;font-weight:900;padding:1px 6px;border-radius:4px}
.db-mobile-header{display:none;align-items:center;justify-content:space-between;margin-bottom:8px}
.db-mobile-tabs{display:none;gap:0;margin-bottom:10px;border-radius:8px;overflow:hidden;border:1px solid #333}
.db-tab{flex:1;padding:10px;background:#111;color:#888;border:none;cursor:pointer;font-size:12px;font-weight:bold;transition:0.2s}
.db-tab-active{background:#222;color:#f1c40f}
.db-btn-import-sm{background:#1a3a5c;color:#7ec8e3;border:1px solid #2a5a8c;border-radius:6px;padding:6px 10px;cursor:pointer;font-size:11px;font-weight:bold}
.db-btn-save-sm{background:#1a3d1a;color:#4caf50;border:1px solid #2e7d32;border-radius:6px;padding:6px 10px;cursor:pointer;font-size:13px}
.db-btn-save-pub-sm{background:#1a3a5c;color:#7ec8e3;border-color:#2a5a8c}
.db-builder-layout{display:flex;gap:16px}
.db-left-side{flex:3;min-width:0}
.db-right-side{flex:1;min-width:240px}
.db-cards-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(100px,1fr));gap:8px;max-height:800px;overflow-y:auto;padding-right:4px}
.db-card-small{cursor:pointer;position:relative;transition:0.2s}
.db-card-small:hover{transform:translateY(-3px)}
.db-card-small img{width:100%;aspect-ratio:5/7;object-fit:cover;border-radius:6px;border:1px solid #333;display:block}
.db-card-small.maxed img{filter:brightness(0.15) grayscale(1)}
.db-badge{position:absolute;top:-7px;right:-7px;background:#e74c3c;width:22px;height:22px;border-radius:50%;text-align:center;line-height:22px;font-weight:bold;font-size:11px;border:2px solid #000;z-index:5}
.db-horde-tag{position:absolute;bottom:4px;right:4px;background:#f1c40f;color:#000;font-size:8px;font-weight:bold;padding:2px 4px;border-radius:3px;z-index:3}
.db-sidebar-card{background:#111;border:1px solid #333;border-radius:12px;padding:14px;position:sticky;top:16px}
.db-deck-list{max-height:400px;overflow-y:auto;margin:8px 0}
.db-deck-strip{height:38px;margin-bottom:3px;border-radius:4px;position:relative;display:flex;align-items:center;cursor:pointer;background-size:160%;background-position:center 30%;border-left:4px solid #888;overflow:hidden;transition:0.15s}
.db-deck-strip:hover{filter:brightness(1.18)}
.strip-overlay{position:absolute;top:0;left:0;width:100%;height:100%}
.strip-cost{position:relative;width:26px;text-align:center;font-weight:bold;color:#fff;z-index:2;font-size:13px;text-shadow:0 0 5px #000;flex-shrink:0}
.strip-title{position:relative;flex:1;font-size:11px;font-weight:bold;color:#fff;z-index:2;padding-left:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-shadow:1px 1px 3px #000}
.strip-count{position:relative;font-weight:bold;padding:0 8px;height:100%;display:flex;align-items:center;z-index:2;font-size:11px;flex-shrink:0}
.db-counter{margin:6px 0;font-size:13px;font-weight:bold;color:#555}
.db-counter.ok{color:#27ae60}
.db-counter.err{color:#e74c3c}
.db-btn-copy{width:100%;padding:11px 12px;margin-top:8px;border:none;border-radius:8px;font-weight:bold;font-size:12px;letter-spacing:.3px;color:#1a1200;cursor:pointer;background:linear-gradient(180deg,#ffe082,#f1c40f 45%,#d4a017);box-shadow:0 2px 10px rgba(241,196,15,.35)}
.db-btn-copy:hover:not(:disabled){filter:brightness(1.08)}
.db-btn-copy:disabled{background:#333;color:#888;cursor:not-allowed;opacity:.55;box-shadow:none}
.db-btn-import{width:100%;margin-top:6px;padding:9px;background:#1a3a5c;color:#7ec8e3;border:1px solid #2a5a8c;border-radius:6px;cursor:pointer;font-size:11px;font-weight:bold}
.db-btn-save{flex:1;padding:7px;background:#1a3d1a;color:#4caf50;border:1px solid #2e7d32;border-radius:6px;cursor:pointer;font-size:11px;font-weight:bold;transition:0.2s}
.db-btn-save:hover{background:#2e7d32;color:#fff}
.db-btn-save-pub{background:#1a3a5c;color:#7ec8e3;border-color:#2a5a8c}
.db-btn-save-pub:hover{background:#2a5a8c;color:#fff}
.db-account-badge{background:#1a3d1a;color:#4caf50;border:1px solid #2e7d32;border-radius:6px;padding:5px 8px;font-size:10px;font-weight:bold;margin-bottom:7px;text-align:center}
.db-account-warning{background:#3d2a00;color:#ffa726;border:1px solid #7d5000;border-radius:6px;padding:5px 8px;font-size:10px;margin-bottom:7px;text-align:center}
.db-footer{padding-top:8px;border-top:1px solid #222}
.db-modal-overlay{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.92);z-index:9999;display:flex;align-items:flex-end;justify-content:center}
.db-modal{background:#111;border:1px solid #444;border-radius:12px 12px 0 0;padding:16px;width:100%;max-width:520px;max-height:92vh;overflow-y:auto}
.db-import-textarea{width:100%;background:#0a0a0a;border:1px solid #333;color:#ccc;padding:10px;border-radius:6px;font-family:monospace;font-size:11px;resize:vertical;box-sizing:border-box}
.db-card-popup{position:fixed;width:220px;height:308px;background-size:cover;background-position:center top;z-index:10000;pointer-events:none;box-shadow:0 8px 40px rgba(0,0,0,0.9);display:flex;align-items:flex-end;transition:opacity 0.1s}
.db-hero-popup{position:fixed;width:220px;height:308px;background-size:cover;background-position:center top;z-index:10000;pointer-events:none;box-shadow:0 8px 40px rgba(0,0,0,0.9);display:flex;align-items:flex-end;transition:opacity 0.1s}
.db-popup-info{width:100%;background:linear-gradient(transparent,rgba(0,0,0,0.85));padding:8px 10px}
.db-popup-cost{display:inline-block;background:#f1c40f;color:#000;font-weight:bold;font-size:15px;padding:2px 10px;border-radius:4px;margin-bottom:5px}
.db-popup-title{display:block;color:#fff;font-size:13px;font-weight:bold;text-shadow:1px 1px 3px #000}
@media(max-width:640px){
  .db-v41{padding:10px;border-radius:10px}
  .db-mobile-header{display:flex}
  .db-mobile-tabs{display:flex}
  .db-builder-layout{display:block}
  .db-right-side{min-width:0;margin-top:0}
  .db-hidden-mobile{display:none!important}
  .db-counter-desktop{display:none}
  .db-sidebar-card{position:static;border-radius:8px}
  .db-deck-list{max-height:none}
  .db-cards-grid{grid-template-columns:repeat(auto-fill,minmax(85px,1fr));max-height:none}
  .db-heroes-grid{grid-template-columns:repeat(auto-fill,minmax(85px,1fr))}
  .db-filters{gap:5px;padding:6px}
  .db-filter-btn{padding:2px 6px;font-size:9px}
  .db-filter-clear{margin-left:0}
  .db-card-popup{width:160px;height:224px}
  .db-hero-popup{width:160px;height:224px}
}
@media (hover: none) {
  .db-card-popup,.db-hero-popup{display:none!important}
}
</style>
<script>
(function(){
const {createApp,ref,computed,onMounted} = Vue;
const ELEM_GROUPS = [
  {key:'степи',label:'🌾 Степи',color:'#f1c40f',textColor:'#000',alpha:'rgba(180,150,0,0.93)',slugs:['stepi','степи']},
  {key:'горы',label:'⛰ Горы',color:'#2980b9',textColor:'#fff',alpha:'rgba(20,80,160,0.93)',slugs:['gory','горы']},
  {key:'болото',label:'🌿 Болото',color:'#a8d5a2',textColor:'#000',alpha:'rgba(100,170,100,0.93)',slugs:['boloto','болото']},
  {key:'лес',label:'🌲 Лес',color:'#27ae60',textColor:'#fff',alpha:'rgba(15,110,50,0.93)',slugs:['les','лес']},
  {key:'тьма',label:'🌑 Тьма',color:'#8e44ad',textColor:'#fff',alpha:'rgba(80,20,120,0.93)',slugs:['tma','тьма']},
  {key:'нейтралы',label:'⚪ Нейтралы',color:'#cd7f32',textColor:'#fff',alpha:'rgba(130,80,20,0.93)',slugs:['nejtraly','neutral','нейтралы']}
];
const getElemGroup = (elems) => { if (!elems || !elems.length) return ELEM_GROUPS[5]; for (const g of ELEM_GROUPS) { if (elems.some(e => g.slugs.some(s => e.includes(s)))) return g; } return ELEM_GROUPS[5]; };
const getElemColor = (elems) => getElemGroup(elems).color;
const getElemAlpha = (elems) => getElemGroup(elems).alpha;
const getElemText = (elems) => getElemGroup(elems).textColor;
const isNeutral = (elems) => getElemGroup(elems).key === 'нейтралы';
const toLE = (hex8) => hex8.match(/.{2}/g).reverse().join('');
const normalizeRarity = (r) => { if (!r) return ''; const s = r.toLowerCase(); if (s.includes('ультра')||s.includes('legend')) return 'legendary'; if (s.includes('редк')||s.includes('epic')) return 'epic'; if (s.includes('необыч')||s.includes('uncommon')||s.includes('rare')) return 'rare'; if (s.includes('част')||s.includes('common')) return 'common'; return s; };

// Официальный формат BHD1 (как в razrab/deckcode.js).
const BH_SIGNATURE = [0x42, 0x48, 0x44, 0x31];
const BH_ID_HIGH = 0x08005000;
const BH_CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? (c >>> 1) ^ 0xedb88320 : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();
function bhCrc32(bytes, length) {
  let crc = 0xffffffff;
  for (let i = 0; i < length; i++) crc = BH_CRC_TABLE[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}
function bhParseId(id) {
  if (typeof id !== 'string' || !/^[0-9A-Fa-f]{8}$/.test(id)) throw new Error('Некорректный ID карты: ' + id);
  const value = parseInt(id, 16) >>> 0;
  if (value === 0) throw new Error('ID карты не может быть 00000000');
  return value;
}
function bhFormatId(value) {
  return value.toString(16).toUpperCase().padStart(8, '0');
}
function decodeDeck(code) {
  const trimmed = String(code || '').trim();
  if (trimmed.length < 24 || trimmed.length > 1024) throw new Error('Неверная длина кода');
  let bytes;
  try {
    const bin = atob(trimmed);
    bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  } catch (e) { throw new Error('Код не является Base64'); }
  if (bytes.length < 17 || bytes.length > 4 + 8 + 1 + 80 * 9 + 4) throw new Error('Неверный размер данных');
  const view = new DataView(bytes.buffer);
  const crcPos = bytes.length - 4;
  if (view.getUint32(crcPos, true) !== bhCrc32(bytes, crcPos)) throw new Error('Не сходится контрольная сумма');
  for (let i = 0; i < 4; i++) if (bytes[i] !== BH_SIGNATURE[i]) throw new Error('Это не код колоды BHD1');
  let p = 4;
  const readId = () => {
    const low = view.getUint32(p, true);
    const high = view.getUint32(p + 4, true);
    p += 8;
    if (low === 0 && high === 0) throw new Error('Пустой ID карты');
    if (high !== BH_ID_HIGH) throw new Error('Неизвестный формат ID карты');
    return bhFormatId(low);
  };
  const hero = readId();
  const count = bytes[p++];
  if (count > 80) throw new Error('Слишком много карт');
  if (bytes.length !== 13 + count * 9 + 4) throw new Error('Неверный размер данных');
  const entries = [];
  const seen = new Set();
  for (let i = 0; i < count; i++) {
    const id = readId();
    const n = bytes[p++];
    if (n < 1 || n > 10) throw new Error('Неверное количество карты ' + id);
    if (seen.has(id)) throw new Error('Карта ' + id + ' указана дважды');
    seen.add(id);
    entries.push({ game_id_be: id.toLowerCase(), count: n, prefix: '00500008' });
  }
  return {
    hero: hero.toLowerCase(),
    heroId: hero.toLowerCase(),
    heroIdLE: toLE(hero.toLowerCase()),
    headerId: 'bhd1',
    entries,
    cards: entries.map(e => ({ id: e.game_id_be.toUpperCase(), count: e.count }))
  };
}
function encodeDeck(cardsOrList, templateCode, heroGameId) {
  let heroHex = '';
  let records = [];
  if (Array.isArray(cardsOrList) && cardsOrList.length && cardsOrList[0] && Object.prototype.hasOwnProperty.call(cardsOrList[0], 'count') && Object.prototype.hasOwnProperty.call(cardsOrList[0], 'id') && typeof cardsOrList[0].title === 'undefined') {
    heroHex = String(templateCode || heroGameId || '').trim();
    records = cardsOrList.map(c => ({ id: bhParseId(String(c.id)), count: c.count|0 }));
  } else {
    heroHex = String(heroGameId || '').trim();
    if (!heroHex && templateCode) {
      try { heroHex = decodeDeck(templateCode).hero; } catch (e) {}
    }
    const grouped = new Map();
    (cardsOrList || []).forEach(card => {
      const id = String(card.game_id || '').trim();
      if (!/^[a-f0-9]{8}$/i.test(id)) throw new Error('Нет игрового ID у карты «' + (card.title || id) + '»');
      const key = id.toUpperCase();
      grouped.set(key, (grouped.get(key) || 0) + 1);
    });
    records = [...grouped.entries()].map(([id, count]) => ({ id: bhParseId(id), count }));
  }
  if (!/^[a-f0-9]{8}$/i.test(heroHex)) throw new Error('У выбранного героя нет игрового ID');
  if (records.length > 80) throw new Error('Слишком много разных карт');
  records.sort((a, b) => a.id - b.id);
  for (let i = 1; i < records.length; i++) if (records[i].id === records[i - 1].id) throw new Error('Карта указана дважды');
  for (const r of records) if (!Number.isInteger(r.count) || r.count < 1 || r.count > 10) throw new Error('Неверное количество копии карты');
  const length = 13 + records.length * 9 + 4;
  const bytes = new Uint8Array(length);
  const view = new DataView(bytes.buffer);
  let p = 0;
  bytes.set(BH_SIGNATURE, p); p += 4;
  view.setUint32(p, bhParseId(heroHex), true); view.setUint32(p + 4, BH_ID_HIGH, true); p += 8;
  view.setUint8(p, records.length); p += 1;
  for (const r of records) {
    view.setUint32(p, r.id, true); view.setUint32(p + 4, BH_ID_HIGH, true); p += 8;
    view.setUint8(p, r.count); p += 1;
  }
  view.setUint32(p, bhCrc32(bytes, p), true);
  let s = '';
  for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
  return btoa(s);
}

createApp({
  setup() {
    const loading = ref(true);
    const heroes = ref([]);
    const cards = ref([]);
    const selectedHero = ref(null);
    const deck = ref([]);
    const search = ref('');
    const headerIdHex = ref('');
    const heroIdLEHex = ref('');
    const gameCode = ref('');
    const codeCopied = ref(false);
    const originalOrder = ref([]);
    const currentUser = ref(null);
    const approvedMaps = ref({});
    const currentDeckId = ref(null);
    const showImportModal = ref(false);
    const importText = ref('');
    const importStatus = ref(null);
    const mobileTab = ref('cards');
    const filterRarity = ref('');
    const filterExpansion = ref('');
    const filterCost = ref('');
    const hoveredCard = ref(null);
    const hoveredHero = ref(null);
    const guideUrl = ref('');
    const videoGuideUrl = ref('');
    const showProForm = ref(false);
    const proSubmitting = ref(false);
    const proAchievements = ref('');
    const proInfo = ref({is_pro:false, request_status:'', achievements:''});
    const canHover = window.matchMedia('(hover: hover)').matches;
    const loginUrl = '/login/?redirect_to=' + encodeURIComponent(window.location.pathname);
    const RARITY_DUST = {legendary:2000, epic:400, rare:120, common:60};
    const rarityOptions = [{key:'',label:'Все'},{key:'common',label:'Частая'},{key:'rare',label:'Необычная'},{key:'epic',label:'Редкая'},{key:'legendary',label:'Ультраредкая'}];
    const costOptions = [{key:'0',label:'0'},{key:'1-2',label:'1-2'},{key:'3-4',label:'3-4'},{key:'5-6',label:'5-6'},{key:'7+',label:'7+'}];
    const expansionOptions = computed(() => { const s = new Set(); cards.value.forEach(c => { if (c.expansion) s.add(c.expansion); }); return [...s].sort(); });
    const dustCost = computed(() => { const g = {}; deck.value.forEach(c => { if (!g[c.id]) g[c.id] = Object.assign({},c,{count:0}); g[c.id].count++; }); return Object.values(g).reduce((sum,item) => sum + (RARITY_DUST[item.rarity]||0) * item.count, 0); });
    const normalizeType = (t) => {
      if (t === null || t === undefined || t === '') return '';
      const s = String(t).toLowerCase().trim();
      if (s === 'creature' || s === 'spell' || s === 'equipment' || s === 'hero') return s;
      if (s === '1' || s === '01') return 'creature';
      if (s === '2' || s === '02') return 'spell';
      if (s === '3' || s === '03') return 'equipment';
      if (s.includes('закл')||s.includes('spell')||s.includes('магия')||s.includes('magic')||s === 's'||s === 'sp') return 'spell';
      if (s.includes('экип')||s.includes('equip')||s.includes('предм')||s.includes('оруж')||s.includes('weapon')||s.includes('доспех')||s.includes('armor')||s.includes('armour')||s.includes('амулет')||s.includes('amulet')||s.includes('артеф')||s.includes('artifact')||s.includes('item')||s.includes('gear')||s === 'e'||s === 'eq') return 'equipment';
      if (s.includes('герой')||s.includes('hero')) return 'hero';
      if (s.includes('сущ')||s.includes('creat')||s.includes('unit')||s.includes('minion')||s.includes('monster')||s.includes('монстр')||s.includes('юнит')||s.includes('воин')||s.includes('fighter')||s.includes('warrior')||s.includes('troop')||s.includes('отряд')||s.includes('боец')||s.includes('персонаж')||s === 'c'||s === 'cr'||s === 'u') return 'creature';
      return '';
    };
    const resolveCardType = (c) => {
      let t = normalizeType(c && c.type);
      if (t === 'hero') return 'hero';
      if (t === 'spell' || t === 'equipment' || t === 'creature') return t;
      const full = cards.value.find(x => String(x.id) === String(c && c.id));
      if (full) {
        t = normalizeType(full.type);
        if (t === 'spell' || t === 'equipment' || t === 'creature') return t;
      }
      // Не герой / не заклинание / не экипировка → существо
      return 'creature';
    };
    const typeCounts = computed(() => {
      let creature = 0, spell = 0, equipment = 0;
      deck.value.forEach(c => {
        const t = resolveCardType(c);
        if (t === 'creature') creature++;
        else if (t === 'spell') spell++;
        else if (t === 'equipment') equipment++;
      });
      return { creature, spell, equipment };
    });
    const matchCost = (cost, filter) => { if (!filter) return true; const c = parseInt(cost)||0; if (filter==='0') return c===0; if (filter==='1-2') return c>=1&&c<=2; if (filter==='3-4') return c>=3&&c<=4; if (filter==='5-6') return c>=5&&c<=6; if (filter==='7+') return c>=7; return true; };
    const resetImport = () => { headerIdHex.value=''; heroIdLEHex.value=''; gameCode.value=''; originalOrder.value=[]; currentDeckId.value=null; guideUrl.value=''; videoGuideUrl.value=''; };
    const onCardHover = (c) => { if (canHover) hoveredCard.value = c; };
    const onCardLeave = () => { hoveredCard.value = null; };
    const onHeroHover = (h) => { if (canHover) hoveredHero.value = h; };
    const onHeroLeave = () => { hoveredHero.value = null; };
    const clearPopups = () => { hoveredCard.value = null; hoveredHero.value = null; };
    const heroGroups = computed(() => ELEM_GROUPS.map(g => Object.assign({},g,{heroes:heroes.value.filter(h => getElemGroup(h.elements||[]).key===g.key)})).filter(g => g.heroes.length>0));
    const groupedDeck = computed(() => { const g = {}; deck.value.forEach(c => { if (!g[c.id]) g[c.id] = Object.assign({},c,{count:0}); g[c.id].count++; }); return Object.values(g).sort((a,b) => (a.cost-b.cost) || a.title.localeCompare(b.title)); });
    const filteredCards = computed(() => {
      if (!selectedHero.value) return [];
      const s = search.value.toLowerCase();
      const isHigart = selectedHero.value.title === 'Хигарт';
      const heroKey = getElemGroup(selectedHero.value.elements||[]).key;
      return cards.value.filter(c => {
        if (s) { const inTitle = c.title.toLowerCase().includes(s); const inDesc = (c.description||'').toLowerCase().includes(s); if (!inTitle && !inDesc) return false; }
        if (filterRarity.value && normalizeRarity(c.rarity) !== filterRarity.value) return false;
        if (filterExpansion.value && (c.expansion || '').trim().toLowerCase() !== filterExpansion.value.trim().toLowerCase()) return false;
        if (filterCost.value && !matchCost(c.cost, filterCost.value)) return false;
        if (isHigart) return true;
        const key = getElemGroup(c.elements||[]).key;
        return key === heroKey || key === 'нейтралы';
      }).sort((a,b) => {
        const ai = isHigart ? ELEM_GROUPS.findIndex(g => g.key===getElemGroup(a.elements||[]).key) : (isNeutral(a.elements||[]) ? 1 : 0);
        const bi = isHigart ? ELEM_GROUPS.findIndex(g => g.key===getElemGroup(b.elements||[]).key) : (isNeutral(b.elements||[]) ? 1 : 0);
        if (ai !== bi) return ai - bi;
        if ((a.cost||0) !== (b.cost||0)) return (a.cost||0) - (b.cost||0);
        return a.title.localeCompare(b.title);
      });
    });
    const getCount = (id) => deck.value.filter(i => i.id === id).length;
    const isMaxed = (c) => getCount(c.id) >= (c.is_horde ? 5 : 3);
    const withResolvedType = (c) => {
      if (!c) return c;
      const t = resolveCardType(c);
      if (c.type === t) return c;
      return Object.assign({}, c, { type: t });
    };
    const addToDeck = (c) => { if (!isMaxed(c) && deck.value.length < 60) deck.value.push(withResolvedType(c)); };
    const removeFromDeckById = (id) => { const i = deck.value.map(c => c.id).lastIndexOf(id); if (i !== -1) deck.value.splice(i, 1); };
    const doFullImport = async () => {
      importStatus.value = null;
      let fullCode = (importText.value || '').trim();
      if (!fullCode) { importStatus.value = {ok:false,msg:'Вставьте код колоды'}; return; }
      // Если вставили текст с мусором — вытащим Base64-строку
      const b64Match = fullCode.match(/[A-Za-z0-9+/]{20,}={0,2}/);
      if (b64Match) fullCode = b64Match[0].trim();
      let decoded;
      try { decoded = decodeDeck(fullCode); }
      catch(e) { importStatus.value = {ok:false,msg:'Ошибка декодирования: ' + e.message}; return; }
      gameCode.value = fullCode;
      heroIdLEHex.value = decoded.heroIdLE || toLE(decoded.hero || '');
      headerIdHex.value = decoded.headerId || 'bhd1';
      originalOrder.value = (decoded.entries || []).map(e => e.game_id_be);

      const heroGid = String(decoded.hero || '').toLowerCase();
      const hero = heroes.value.find(h => String(h.game_id || '').toLowerCase() === heroGid)
        || heroes.value.find(h => String((approvedMaps.value||{})[heroGid] || '') === String(h.id));
      if (!hero) {
        importStatus.value = {ok:false,msg:'Герой с game_id ' + heroGid + ' не найден в базе сайта'};
        return;
      }
      selectedHero.value = hero;

      const restored = [];
      const missing = [];
      (decoded.entries || []).forEach(entry => {
        const gid = String(entry.game_id_be || '').toLowerCase();
        let card = cards.value.find(c => String(c.game_id || '').toLowerCase() === gid);
        if (!card && approvedMaps.value && approvedMaps.value[gid]) {
          const mappedId = approvedMaps.value[gid];
          card = cards.value.find(c => String(c.id) === String(mappedId));
        }
        if (!card) { missing.push(gid); return; }
        const typed = withResolvedType(card);
        for (let k = 0; k < (entry.count || 0); k++) restored.push(typed);
      });
      deck.value = restored;
      showImportModal.value = false;
      importText.value = '';
      mobileTab.value = 'deck';
      importStatus.value = {ok:true,msg:'Импорт успешен'};
      if (missing.length) {
        alert('Импорт выполнен. Карт: ' + deck.value.length + '. Не найдено по card_game_id: ' + missing.length + '\n' + missing.slice(0,20).join(', '));
      } else {
        alert('Импорт успешен! Карт: ' + deck.value.length + '.');
      }
    };
    const copyGeneratedCode = async () => {
      try {
        gameCode.value = encodeDeck(deck.value, null, selectedHero.value && selectedHero.value.game_id);
        try { await navigator.clipboard.writeText(gameCode.value); }
        catch(e) { const ta = document.createElement('textarea'); ta.value = gameCode.value; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta); }
        codeCopied.value = true;
        setTimeout(() => codeCopied.value = false, 2000);
      } catch(e) { alert(e.message || 'Не удалось создать код колоды'); }
    };
    const loadPro = async () => {
      try {
        const r = await fetch('/wp-json/berserk/v1/pro/me', {credentials:'include',headers:{'X-WP-Nonce':window.bhNonce||''}});
        if (r.ok) {
          proInfo.value = await r.json();
          proAchievements.value = proInfo.value.request || proInfo.value.achievements || '';
        }
      } catch(e) {}
    };
    const submitProRequest = async () => {
      if (proInfo.value.is_pro || proInfo.value.request_status === 'pending') {
        alert('Ваша заявка уже находится на рассмотрении');
        showProForm.value = false;
        return;
      }
      if (!(proAchievements.value || '').trim()) { alert('Укажите достижения'); return; }
      if (proSubmitting.value) return;
      proSubmitting.value = true;
      try {
        const r = await fetch('/wp-json/berserk/v1/pro/request', {method:'POST',credentials:'include',headers:{'Content-Type':'application/json','X-WP-Nonce':window.bhNonce||''},body:JSON.stringify({achievements:proAchievements.value})});
        const res = await r.json();
        if (res.success) {
          proInfo.value.request_status = 'pending';
          showProForm.value = false;
          alert(res.message || 'Заявка отправлена');
        } else {
          if (res.status === 'pending') proInfo.value.request_status = 'pending';
          if (res.status === 'approved') { proInfo.value.request_status = 'approved'; proInfo.value.is_pro = true; }
          showProForm.value = false;
          alert(res.message || 'Ошибка отправки заявки');
        }
      } catch(e) {
        alert('Ошибка отправки заявки');
      } finally {
        proSubmitting.value = false;
      }
    };
    const saveDeck = async (isPublic) => {
      if (!currentUser.value) { if (confirm('Нужно войти. Перейти?')) window.location.href = loginUrl; return; }
      const name = prompt('Название колоды:', (selectedHero.value ? selectedHero.value.title : '') + ' колода');
      if (!name) return;
      const cardsToSave = deck.value.map(c => withResolvedType(c));
      const r = await fetch('/wp-json/berserk/v1/decks/save', {method:'POST',credentials:'include',headers:{'Content-Type':'application/json','X-WP-Nonce':window.bhNonce||''},body:JSON.stringify({id:currentDeckId.value||0,name,hero_wp_id:selectedHero.value?selectedHero.value.id:0,deck:{heroTitle:selectedHero.value?selectedHero.value.title:'',cards:cardsToSave},header_id:headerIdHex.value,hero_le:heroIdLEHex.value,game_code:gameCode.value,guide_url:guideUrl.value,video_guide_url:videoGuideUrl.value,is_public:isPublic})});
      const text = await r.text();
      try { const res = JSON.parse(text); if (res.success) { currentDeckId.value = res.id; alert('Колода сохранена! ID: ' + res.id); } else alert('Ошибка сохранения: '+(res.message||JSON.stringify(res))); }
      catch(e) { alert('Ошибка сохранения: HTTP '+r.status+'\n'+text.substring(0,300)); }
    };
    onMounted(async () => {
      const [dataRes, mapsRes] = await Promise.all([fetch('/wp-json/berserk/v1/data',{credentials:'include'}), fetch('/wp-json/berserk/v1/mappings',{credentials:'include'})]);
      const d = await dataRes.json();
      heroes.value = d.heroes || [];
      cards.value = (d.cards || []).map(c => {
        const t = normalizeType(c.type);
        return Object.assign({}, c, { type: (t === 'spell' || t === 'equipment') ? t : (t === 'hero' ? 'hero' : 'creature') });
      });
      approvedMaps.value = await mapsRes.json();
      const me = window.bhCurrentUser || {logged_in:false};
      if (me.logged_in) { currentUser.value = me; await loadPro(); }
      const editData = localStorage.getItem('bh_edit_deck');
      if (editData) {
        try {
          const ed = JSON.parse(editData);
          localStorage.removeItem('bh_edit_deck');
          currentDeckId.value = ed.id;
          const h = heroes.value.find(hr => String(hr.id) === String(ed.hero_wp_id));
          if (h) {
            selectedHero.value = h;
            const restoredDeck = [];
            (ed.deck_json.cards||[]).forEach(savedCard => {
              const found = cards.value.find(c => c.id === savedCard.id);
              if (found) restoredDeck.push(withResolvedType(found));
              else if (savedCard) restoredDeck.push(withResolvedType(savedCard));
            });
            deck.value = restoredDeck;
            headerIdHex.value = ed.header_id || '';
            heroIdLEHex.value = ed.hero_le || '';
            gameCode.value = ed.game_code || '';
            guideUrl.value = ed.guide_url || '';
            videoGuideUrl.value = ed.video_guide_url || '';
            mobileTab.value = 'deck';
          }
        } catch(e) { localStorage.removeItem('bh_edit_deck'); }
      }
      loading.value = false;
      document.addEventListener('mousemove', (e) => {
        if (!canHover) return;
        const popup = document.querySelector('.db-card-popup');
        if (popup && hoveredCard.value) {
          let x = e.clientX + 20;
          let y = e.clientY - 150;
          if (x + 220 > window.innerWidth) x = e.clientX - 240;
          if (y < 0) y = 10;
          popup.style.left = x + 'px';
          popup.style.top = y + 'px';
        }
        const heroPopup = document.querySelector('.db-hero-popup');
        if (heroPopup && hoveredHero.value) {
          let hx = e.clientX + 20;
          let hy = e.clientY - 150;
          if (hx + 220 > window.innerWidth) hx = e.clientX - 240;
          if (hy < 0) hy = 10;
          heroPopup.style.left = hx + 'px';
          heroPopup.style.top = hy + 'px';
        }
      });
      document.addEventListener('touchstart', (e) => {
        if (!e.target.closest || !e.target.closest('.db-card-small,.db-deck-strip,.db-hero-item,.db-card-popup,.db-hero-popup')) {
          clearPopups();
        }
      }, {passive:true});
    });
    return {loading,heroes,cards,heroGroups,selectedHero,deck,groupedDeck,search,filteredCards,headerIdHex,currentUser,loginUrl,showImportModal,importText,importStatus,currentDeckId,mobileTab,filterRarity,filterExpansion,filterCost,hoveredCard,hoveredHero,guideUrl,videoGuideUrl,showProForm,proSubmitting,proAchievements,proInfo,submitProRequest,typeCounts,rarityOptions,costOptions,expansionOptions,dustCost,addToDeck,removeFromDeckById,getCount,isMaxed,getElemColor,getElemAlpha,getElemText,resetImport,saveDeck,doFullImport,copyGeneratedCode,codeCopied,onCardHover,onCardLeave,onHeroHover,onHeroLeave};
  }
}).mount('#berserk-app');
})();
</script>
<?php return ob_get_clean();
});
// ============================================================
// ШОРТКОД: Публичные колоды [berserk_decks]
// ============================================================
add_shortcode('berserk_decks', function() {
    ob_start(); ?>
<div id="bh-decks-page">
  <div v-if="loading" class="bh-loading">Загрузка колод...</div>
  <div v-else>
    <h2 class="bh-page-title">МЕТА-КОЛОДЫ</h2>
    <div class="bh-filter-bar">
      <div v-if="filterAuthorId" class="bh-author-filter">
        <span>Колоды автора: <strong>{{ filterAuthorName || ('#' + filterAuthorId) }}</strong></span>
        <button @click="clearAuthorFilter" class="bh-pill-sm">Сбросить фильтр автора</button>
      </div>
      <div class="bh-filter-pills">
        <button @click="filterElem=''; filterHero=''" :class="['bh-pill', !filterElem && !filterHero ? 'bh-pill-active' : '']">Все ({{ decks.length }})</button>
        <button v-for="eg in ELEM_GROUPS" :key="eg.key" @click="filterElem = filterElem===eg.key ? '' : eg.key; filterHero=''" :class="['bh-pill', filterElem===eg.key ? 'bh-pill-active' : '']" :style="filterElem===eg.key ? { background: eg.color, color: eg.textColor, borderColor: eg.color } : {}">{{ eg.label }} ({{ decksByElem(eg.key).length }})</button>
      </div>
      <div v-if="filterElem" class="bh-hero-pills">
        <button v-for="hero in heroesInElem(filterElem)" :key="hero" @click="filterHero = filterHero===hero ? '' : hero" :class="['bh-pill-sm', filterHero===hero ? 'bh-pill-sm-active' : '']">{{ hero }} ({{ decksByHero(hero).length }})</button>
      </div>
      <div class="bh-sort-bar">
        <span class="bh-sort-label">Сортировка:</span>
        <button @click="sortBy='likes'" :class="['bh-sort-btn', sortBy==='likes' ? 'bh-sort-active' : '']">По популярности</button>
        <button @click="sortBy='date'" :class="['bh-sort-btn', sortBy==='date' ? 'bh-sort-active' : '']">По дате обновления</button>
      </div>
    </div>
    <div v-if="filteredDecks.length === 0" class="bh-empty">Колод не найдено</div>
    <div class="bh-deck-list">
      <div v-for="(deck, idx) in filteredDecks" :key="deck.id" class="bh-deck-row" @click="openDeck(deck.id)">
        <div class="bh-row-bg" :style="{ backgroundImage: 'url(' + (getHeroImage(deck) || '') + ')' }"></div>
        <div class="bh-row-overlay"></div>
        <div class="bh-row-content">
          <div class="bh-col-rank">{{ idx + 1 }}</div>
          <div class="bh-col-info">
            <div class="bh-deck-name">{{ deck.name }} <span v-if="deck.is_pro || deck.author_is_pro" class="bh-pro-badge" :title="(deck.pro_achievements || deck.author_pro_achievements) || 'PRO автор'" @click.stop="toggleProTip(deck)">PRO</span></div>
            <div class="bh-deck-hero"><span class="bh-elem-dot" :style="{ background: getHeroElemColor(deck) }"></span>{{ deck.deck_json.heroTitle || '—' }}</div>
            <div class="bh-deck-author">{{ deck.author }} · {{ (deck.deck_json.cards || []).length }} карт · {{ formatDate(deck.updated_at) }}</div>
            <div class="bh-deck-actions-inline" @click.stop>
              <a v-if="deck.guide_url" :href="deck.guide_url" target="_blank" rel="noopener" class="bh-mini-btn">Гайд</a>
              <button v-if="deck.video_url || deck.video_guide_url" @click="openVideo(deck.video_url || deck.video_guide_url)" class="bh-mini-btn">Видеогайд</button>
              <button @click="followAuthor(deck)" class="bh-mini-btn">Отслеживать автора</button>
            </div>
            <div v-if="proTipDeckId===deck.id && (deck.pro_achievements || deck.author_pro_achievements)" class="bh-pro-tip">{{ deck.pro_achievements || deck.author_pro_achievements }}</div>
          </div>
          <div class="bh-col-cards">
            <div class="bh-card-thumbs">
              <div v-for="(item, ci) in topGroupedCards(deck.deck_json.cards, 8)" :key="ci" class="bh-thumb-wrap">
                <img :src="item.image" :alt="item.title" class="bh-card-thumb" :style="{ borderLeft: '2px solid ' + getElemColor(item.elements) }">
              </div>
            </div>
          </div>
          <div class="bh-col-stats">
            <div class="bh-stat-label">Игры</div>
            <div v-if="deck.total_games > 0" class="bh-stat-val">{{ deck.total_games }}</div>
            <div v-else class="bh-stat-muted">—</div>
          </div>
          <div class="bh-col-stats">
            <div class="bh-stat-label">Винрейт</div>
            <div v-if="deck.winrate !== null" class="bh-stat-val" :class="{ 'bh-wr-good': deck.winrate >= 55, 'bh-wr-bad': deck.winrate < 45 }">{{ deck.winrate }}%</div>
            <div v-else class="bh-stat-muted">—</div>
          </div>
          <div class="bh-col-stats">
            <div class="bh-stat-label">Пыль</div>
            <div class="bh-stat-val">💎{{ deck.dust_cost }}</div>
          </div>
          <div class="bh-col-likes" @click.stop="likeDeck(deck)">
            <button class="bh-like-btn" :class="{ 'bh-liked': deck.liked_by_me }">{{ deck.liked_by_me ? '❤️' : '🤍' }} {{ deck.likes }}</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
<script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>
<script>
Vue.createApp({
  setup() {
    const loading = Vue.ref(true);
    const decks = Vue.ref([]);
    const allCards = Vue.ref([]);
    const allHeroes = Vue.ref([]);
    const filterElem = Vue.ref('');
    const filterHero = Vue.ref('');
    const filterAuthorId = Vue.ref('');
    const filterAuthorName = Vue.ref('');
    const proTipDeckId = Vue.ref(null);
    const sortBy = Vue.ref('likes');
    const deckViewUrl = '<?php echo esc_js(BH_DECKVIEW_URL); ?>';
    const ELEM_GROUPS = [
      {key:'степи',label:'🌾 Степи',color:'#f1c40f',textColor:'#000',alpha:'rgba(180,150,0,0.93)',slugs:['stepi','степи']},
      {key:'горы',label:'⛰ Горы',color:'#2980b9',textColor:'#fff',alpha:'rgba(20,80,160,0.93)',slugs:['gory','горы']},
      {key:'болото',label:'🌿 Болото',color:'#a8d5a2',textColor:'#000',alpha:'rgba(100,170,100,0.93)',slugs:['boloto','болото']},
      {key:'лес',label:'🌲 Лес',color:'#27ae60',textColor:'#fff',alpha:'rgba(15,110,50,0.93)',slugs:['les','лес']},
      {key:'тьма',label:'🌑 Тьма',color:'#8e44ad',textColor:'#fff',alpha:'rgba(80,20,120,0.93)',slugs:['tma','тьма']},
      {key:'нейтралы',label:'⚪ Нейт.',color:'#cd7f32',textColor:'#fff',alpha:'rgba(130,80,20,0.93)',slugs:['nejtraly','neutral','нейтралы']}
    ];
    const getElemGroup = (elems) => { if (!elems || !elems.length) return ELEM_GROUPS[5]; for (const g of ELEM_GROUPS) { if (elems.some(e => g.slugs.some(s => e.includes(s)))) return g; } return ELEM_GROUPS[5]; };
    const getElemColor = (elems) => getElemGroup(elems).color;
    const getHeroElemKey = (deck) => { const hero = allHeroes.value.find(h => h.title === deck.deck_json.heroTitle); return hero ? getElemGroup(hero.elements || []).key : 'нейтралы'; };
    const getHeroElemColor = (deck) => getElemGroup(allHeroes.value.find(h => h.title === deck.deck_json.heroTitle)?.elements || []).color;
    const getHeroImage = (deck) => { const hero = allHeroes.value.find(h => h.title === deck.deck_json.heroTitle); return hero ? hero.image : null; };
    const getCardData = (c) => allCards.value.find(x => x.id === c.id) || c;
    const topGroupedCards = (cards, limit) => { if (!cards) return []; const g = {}; cards.forEach(c => { const f = getCardData(c); if (!g[c.id]) g[c.id] = Object.assign({}, f, {count:0}); g[c.id].count++; }); return Object.values(g).sort((a,b) => (a.cost||0)-(b.cost||0) || a.title.localeCompare(b.title)).slice(0, limit); };
    const decksByElem = (key) => decks.value.filter(d => getHeroElemKey(d) === key);
    const heroesInElem = (key) => [...new Set(decksByElem(key).map(d => d.deck_json ? d.deck_json.heroTitle : null).filter(Boolean))].sort();
    const decksByHero = (hero) => decks.value.filter(d => d.deck_json && d.deck_json.heroTitle === hero);
    const formatDate = (ts) => { if (!ts) return ''; const d = new Date(ts * 1000); return d.toLocaleDateString('ru-RU', {day:'2-digit',month:'2-digit',year:'numeric'}); };
    const openDeck = (id) => { window.location.href = deckViewUrl + '?deck_id=' + id; };
    const openVideo = (url) => { if (window.bhOpenYoutubeModal) window.bhOpenYoutubeModal(url); else window.open(url, '_blank'); };
    const deckAuthorId = (deck) => String(deck.author_id || deck.user_id || '');
    const followAuthor = (deck) => {
      filterAuthorId.value = deckAuthorId(deck);
      filterAuthorName.value = deck.author || '';
      const url = new URL(window.location.href);
      url.searchParams.set('author_id', filterAuthorId.value);
      window.history.replaceState({}, '', url);
    };
    const clearAuthorFilter = () => {
      filterAuthorId.value = '';
      filterAuthorName.value = '';
      const url = new URL(window.location.href);
      url.searchParams.delete('author_id');
      window.history.replaceState({}, '', url);
    };
    const toggleProTip = (deck) => { proTipDeckId.value = proTipDeckId.value === deck.id ? null : deck.id; };
    const filteredDecks = Vue.computed(() => {
      let list = decks.value;
      if (filterAuthorId.value) list = list.filter(d => deckAuthorId(d) === String(filterAuthorId.value));
      if (filterElem.value) list = list.filter(d => getHeroElemKey(d) === filterElem.value);
      if (filterHero.value) list = list.filter(d => d.deck_json && d.deck_json.heroTitle === filterHero.value);
      if (sortBy.value === 'date') list = [...list].sort((a,b) => (b.updated_at||0) - (a.updated_at||0));
      else list = [...list].sort((a,b) => b.likes - a.likes);
      return list;
    });
    const likeDeck = async (deck) => { const r = await fetch('/wp-json/berserk/v1/decks/' + deck.id + '/like', {method:'POST',credentials:'include',headers:{'X-WP-Nonce':window.bhNonce||''}}); const res = await r.json(); if (res.success) { deck.liked_by_me = res.liked; deck.likes = res.likes; } };
    Vue.onMounted(async () => {
      const params = new URLSearchParams(window.location.search);
      if (params.get('author_id')) filterAuthorId.value = params.get('author_id');
      const [decksRes, dataRes] = await Promise.all([fetch('/wp-json/berserk/v1/decks/public',{credentials:'include'}), fetch('/wp-json/berserk/v1/data',{credentials:'include'})]);
      decks.value = await decksRes.json();
      const data = await dataRes.json();
      allCards.value = data.cards || []; allHeroes.value = data.heroes || [];
      if (filterAuthorId.value) {
        const hit = decks.value.find(d => deckAuthorId(d) === String(filterAuthorId.value));
        if (hit) filterAuthorName.value = hit.author || '';
      }
      loading.value = false;
    });
    return { loading, decks, filteredDecks, filterElem, filterHero, filterAuthorId, filterAuthorName, proTipDeckId, sortBy, ELEM_GROUPS, topGroupedCards, likeDeck, getElemColor, getHeroImage, getHeroElemColor, decksByElem, heroesInElem, decksByHero, formatDate, openDeck, openVideo, followAuthor, clearAuthorFilter, toggleProTip };
  }
}).mount('#bh-decks-page');
</script>
<style>
#bh-decks-page{background:#0d0d0d;color:#eee;padding:16px;border-radius:12px;font-family:system-ui,sans-serif;position:relative}
.bh-loading{text-align:center;padding:60px;color:#f1c40f}
.bh-page-title{color:#f1c40f;text-align:center;letter-spacing:2px;margin:0 0 16px;font-size:clamp(16px,4vw,22px);text-transform:uppercase}
.bh-empty{text-align:center;color:#888;padding:40px}
.bh-author-filter{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px;padding:8px 10px;background:#151515;border:1px solid #333;border-radius:8px;font-size:12px}
.bh-pro-badge{display:inline-block;margin-left:6px;background:linear-gradient(135deg,#f1c40f,#e67e22);color:#111;font-size:9px;font-weight:900;padding:1px 6px;border-radius:4px;vertical-align:middle;cursor:help}
.bh-pro-tip{margin-top:6px;padding:6px 8px;background:rgba(0,0,0,.75);border:1px solid #665200;border-radius:6px;font-size:11px;color:#f8e7a1;white-space:pre-wrap}
.bh-deck-actions-inline{display:flex;gap:5px;flex-wrap:wrap;margin-top:6px}
.bh-mini-btn{background:#1a1a1a;color:#ddd;border:1px solid #444;border-radius:6px;padding:3px 8px;font-size:10px;font-weight:bold;cursor:pointer;text-decoration:none;display:inline-block}
.bh-mini-btn:hover{border-color:#777;color:#fff}
.bh-filter-bar{margin-bottom:16px}
.bh-filter-pills{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
.bh-hero-pills{display:flex;flex-wrap:wrap;gap:4px;padding-top:8px;border-top:1px solid #222}
.bh-pill{background:#1a1a1a;color:#aaa;border:1px solid #333;border-radius:20px;padding:5px 12px;cursor:pointer;font-size:12px;font-weight:bold;transition:0.15s}
.bh-pill:hover{border-color:#555;color:#fff}
.bh-pill-active{background:#f1c40f;color:#000;border-color:#f1c40f}
.bh-pill-sm{background:#111;color:#888;border:1px solid #333;border-radius:6px;padding:3px 8px;cursor:pointer;font-size:11px}
.bh-pill-sm:hover{color:#ccc}
.bh-pill-sm-active{background:#333;color:#f1c40f;border-color:#f1c40f}
.bh-sort-bar{display:flex;align-items:center;gap:6px;margin-top:8px;padding-top:8px;border-top:1px solid #222;flex-wrap:wrap}
.bh-sort-label{font-size:11px;color:#888;font-weight:bold}
.bh-sort-btn{background:#1a1a1a;color:#aaa;border:1px solid #333;border-radius:6px;padding:4px 10px;cursor:pointer;font-size:11px;font-weight:bold;transition:0.15s}
.bh-sort-btn:hover{border-color:#555;color:#fff}
.bh-sort-active{background:#f1c40f;color:#000;border-color:#f1c40f}
.bh-deck-list{display:flex;flex-direction:column;gap:6px}
.bh-deck-row{position:relative;border-radius:10px;overflow:hidden;cursor:pointer;min-height:72px;border:1px solid #222;transition:border-color 0.2s}
.bh-deck-row:hover{border-color:#444}
.bh-row-bg{position:absolute;inset:0;background-size:cover;background-position:center 20%;filter:brightness(0.5) saturate(1.3);transform:scale(1.5)}
.bh-row-overlay{position:absolute;inset:0;background:linear-gradient(90deg,rgba(0,0,0,0.88) 0%,rgba(0,0,0,0.6) 35%,rgba(0,0,0,0.3) 100%)}
.bh-row-content{position:relative;display:flex;align-items:center;padding:10px 14px;gap:12px;z-index:2}
.bh-col-rank{width:32px;text-align:center;flex-shrink:0;font-size:18px;font-weight:bold;color:#f1c40f}
.bh-col-info{flex:1;min-width:0}
.bh-deck-name{color:#fff;font-weight:bold;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-shadow:1px 1px 4px #000}
.bh-deck-hero{font-size:12px;color:#ddd;margin-top:2px;display:flex;align-items:center;gap:5px;text-shadow:1px 1px 3px #000;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bh-elem-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0}
.bh-deck-author{font-size:10px;color:#aaa;margin-top:1px;text-shadow:1px 1px 2px #000;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bh-col-cards{flex-shrink:0}
.bh-card-thumbs{display:flex;gap:3px}
.bh-thumb-wrap{position:relative}
.bh-card-thumb{width:36px;height:50px;object-fit:cover;border-radius:4px;flex-shrink:0}
.bh-col-stats{width:64px;text-align:center;flex-shrink:0}
.bh-stat-label{font-size:9px;color:#999;text-transform:uppercase;margin-bottom:2px}
.bh-stat-val{font-weight:bold;font-size:14px;color:#fff;text-shadow:1px 1px 2px #000}
.bh-stat-muted{color:#666;font-size:14px}
.bh-wr-good{color:#4caf50}
.bh-wr-bad{color:#e74c3c}
.bh-col-likes{width:64px;text-align:center;flex-shrink:0}
.bh-like-btn{background:rgba(20,20,20,0.8);color:#aaa;border:1px solid #444;border-radius:20px;padding:5px 10px;cursor:pointer;font-size:11px;transition:0.15s}
.bh-like-btn:hover{border-color:#666}
.bh-liked{background:rgba(60,20,20,0.9);color:#e74c3c;border-color:#7d2d2d}
@media(max-width:768px){.bh-col-cards{display:none}.bh-col-stats{width:42px}.bh-col-likes{width:42px}.bh-deck-name{font-size:13px}.bh-row-content{padding:8px 10px;gap:6px}.bh-col-rank{width:24px;font-size:14px}.bh-stat-label{font-size:8px}.bh-stat-val{font-size:12px}.bh-like-btn{padding:4px 7px;font-size:10px}}
</style>
<?php return ob_get_clean();
});

// ============================================================
// ШОРТКОД: Мои колоды [berserk_mydecks]
// ============================================================
add_shortcode('berserk_mydecks', function() {
    ob_start(); ?>
<div id="bh-mydecks-app">
  <div v-if="loading" style="text-align:center;padding:60px;color:#f1c40f">Загрузка...</div>
  <div v-else-if="!currentUser" style="text-align:center;padding:60px;color:#aaa"><p>Войдите на сайт, чтобы видеть свои колоды.</p><a :href__="loginUrl" style="color:#7ec8e3;text-decoration:underline">Войти</a></div>
  <div v-else>
    <h2 style="color:#f1c40f;letter-spacing:2px;margin-bottom:20px;font-size:clamp(14px,4vw,20px)">МОИ КОЛОДЫ</h2>
    <div class="bh-pro-box" @click.stop>
      <div style="display:flex;justify-content:space-between;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:8px">
        <strong style="color:#f1c40f">Статус PRO</strong>
        <span v-if="proInfo.is_pro || proInfo.request_status==='approved'" class="bh-pro-badge">У вас активен статус PRO</span>
      </div>
      <div v-if="!proInfo.is_pro && proInfo.request_status==='pending'" class="bh-pro-status-msg">Заявка на статус PRO отправлена и ожидает проверки администратора</div>
      <button v-else-if="!proInfo.is_pro && proInfo.request_status!=='approved' && !showProForm" @click="showProForm=true" class="bh-btn bh-btn-public" style="width:100%;margin-bottom:8px">Запросить статус PRO</button>
      <div v-if="showProForm && !proInfo.is_pro && proInfo.request_status!=='pending' && proInfo.request_status!=='approved'">
        <textarea v-model="proAchievements" rows="4" class="bh-pro-textarea" placeholder="Турниры, ладдер, достижения..."></textarea>
        <div style="display:flex;gap:6px;margin-top:6px">
          <button @click="submitProRequest" :disabled="proSubmitting" class="bh-btn bh-btn-public" style="flex:1">{{ proSubmitting ? 'Отправка...' : 'Отправить заявку' }}</button>
          <button @click="showProForm=false" class="bh-btn bh-btn-private" style="flex:1">Отмена</button>
        </div>
      </div>
    </div>
    <div v-if="decks.length === 0" style="color:#888;text-align:center;padding:40px">У вас пока нет сохранённых колод</div>
    <div class="bh-mydecks-grid">
      <div v-for="deck in decks" :key="deck.id" @click="openDeck(deck.id)" class="bh-mydeck-card" @mouseover="$event.currentTarget.style.borderColor='#f1c40f'" @mouseleave="$event.currentTarget.style.borderColor='#333'">
        <div class="bh-mydeck-bg" :style="{ backgroundImage: 'url(' + (getHeroImage(deck) || '') + ')' }"></div>
        <div class="bh-mydeck-overlay"></div>
        <div class="bh-mydeck-content">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px;gap:6px">
          <strong style="color:#f1c40f;font-size:13px;line-height:1.3">{{ deck.name }}</strong>
          <span :style="{ fontSize:'10px', padding:'2px 7px', borderRadius:'10px', background: deck.is_public ? '#1a3a5c' : '#222', color: deck.is_public ? '#7ec8e3' : '#888', whiteSpace:'nowrap', flexShrink:'0' }">{{ deck.is_public ? '🌐 Публ.' : '🔒 Прив.' }}</span>
        </div>
        <div style="font-size:11px;color:#aaa;margin-bottom:3px">Герой: {{ deck.deck_json.heroTitle || '—' }}</div>
        <div style="font-size:11px;color:#aaa;margin-bottom:8px">{{ (deck.deck_json.cards || []).length }} карт · 💎 {{ deck.dust_cost }} · ❤️ {{ deck.likes }} · 📅 {{ formatDate(deck.updated_at) }}</div>
        <div class="bh-guide-edit" @click.stop>
          <input v-model="deck.guide_url" class="bh-guide-input" type="url" placeholder="Ссылка на гайд" @change="saveGuides(deck)">
          <input v-model="deck.video_guide_url" class="bh-guide-input" type="url" placeholder="Ссылка на видеогайд YouTube" @change="saveGuides(deck)">
        </div>
        <div class="bh-deck-actions" @click.stop>
          <button @click.stop="togglePublic(deck, 1)" class="bh-btn bh-btn-public">🌐 Публ.</button>
          <button @click.stop="togglePublic(deck, 0)" class="bh-btn bh-btn-private">🔒 Прив.</button>
        </div>
        </div>
      </div>
    </div>
  </div>
</div>
<script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>
<script>
(function(){
const {createApp,ref,onMounted} = Vue;
createApp({
  setup() {
    const loading = ref(true);
    const currentUser = ref(null);
    const decks = ref([]);
    const allHeroes = ref([]);
    const showProForm = ref(false);
    const proSubmitting = ref(false);
    const proAchievements = ref('');
    const proInfo = ref({is_pro:false, request_status:'', achievements:''});
    const loginUrl = '/login/?redirect_to=' + encodeURIComponent(window.location.pathname);
    const deckViewUrl = '<?php echo esc_js(BH_DECKVIEW_URL); ?>';
    const getHeroImage = (deck) => { const hero = allHeroes.value.find(h => h.title === (deck.deck_json ? deck.deck_json.heroTitle : '')); return hero ? hero.image : null; };
    const formatDate = (ts) => { if (!ts) return ''; const d = new Date(ts * 1000); return d.toLocaleDateString('ru-RU', {day:'2-digit',month:'2-digit',year:'numeric'}); };
    const openDeck = (id) => { window.location.href = deckViewUrl + '?deck_id=' + id; };
    const loadDecks = async () => { const r = await fetch('/wp-json/berserk/v1/decks/my', {credentials:'include',headers:{'X-WP-Nonce':window.bhNonce||''}}); if (r.ok) decks.value = await r.json(); };
    const loadPro = async () => { try { const r = await fetch('/wp-json/berserk/v1/pro/me', {credentials:'include',headers:{'X-WP-Nonce':window.bhNonce||''}}); if (r.ok) { proInfo.value = await r.json(); proAchievements.value = proInfo.value.request || proInfo.value.achievements || ''; } } catch(e){} };
    const submitProRequest = async () => {
      if (proInfo.value.is_pro || proInfo.value.request_status === 'pending') {
        alert('Ваша заявка уже находится на рассмотрении');
        showProForm.value = false;
        return;
      }
      if (!(proAchievements.value || '').trim()) { alert('Укажите достижения'); return; }
      if (proSubmitting.value) return;
      proSubmitting.value = true;
      try {
        const r = await fetch('/wp-json/berserk/v1/pro/request', {method:'POST',credentials:'include',headers:{'Content-Type':'application/json','X-WP-Nonce':window.bhNonce||''},body:JSON.stringify({achievements:proAchievements.value})});
        const res = await r.json();
        if (res.success) {
          proInfo.value.request_status = 'pending';
          showProForm.value = false;
          alert(res.message || 'Заявка отправлена');
        } else {
          if (res.status === 'pending') proInfo.value.request_status = 'pending';
          if (res.status === 'approved') { proInfo.value.request_status = 'approved'; proInfo.value.is_pro = true; }
          showProForm.value = false;
          alert(res.message || 'Ошибка отправки заявки');
        }
      } catch(e) {
        alert('Ошибка отправки заявки');
      } finally {
        proSubmitting.value = false;
      }
    };
    const saveGuides = async (deck) => {
      const r = await fetch('/wp-json/berserk/v1/decks/'+deck.id+'/update-meta', {method:'POST',credentials:'include',headers:{'Content-Type':'application/json','X-WP-Nonce':window.bhNonce||''},body:JSON.stringify({guide_url:deck.guide_url||'', video_guide_url:deck.video_guide_url||''})});
      const res = await r.json();
      if (!res.success) alert('Не удалось сохранить ссылки');
    };
    const togglePublic = async (deck, val) => { const r = await fetch('/wp-json/berserk/v1/decks/'+deck.id+'/visibility', {method:'POST',credentials:'include',headers:{'Content-Type':'application/json','X-WP-Nonce':window.bhNonce||''},body:JSON.stringify({is_public:val})}); const res = await r.json(); if (res.success) deck.is_public = val; else alert('Ошибка: '+(res.message||'неизвестная ошибка')); };
    onMounted(() => { const init = async () => { const me = window.bhCurrentUser || {logged_in:false}; if (me.logged_in) { currentUser.value = me; await Promise.all([loadDecks(), loadPro()]); try { const dataRes = await fetch('/wp-json/berserk/v1/data', {credentials:'include'}); const data = await dataRes.json(); allHeroes.value = data.heroes || []; } catch(e){} } loading.value = false; }; if (document.readyState === 'complete') init(); else window.addEventListener('load', init, {once:true}); });
    return {loading,currentUser,decks,loginUrl,togglePublic,getHeroImage,formatDate,openDeck,showProForm,proSubmitting,proAchievements,proInfo,submitProRequest,saveGuides};
  }
}).mount('#bh-mydecks-app');
})();
</script>
<style>
#bh-mydecks-app{background:#070707;color:#eee;padding:16px;border-radius:15px;font-family:sans-serif}
.bh-pro-box{background:#111;border:1px solid #333;border-radius:10px;padding:12px;margin-bottom:16px}
.bh-pro-textarea,.bh-guide-input{width:100%;box-sizing:border-box;background:#0a0a0a;border:1px solid #333;color:#ccc;border-radius:6px;padding:8px;font-size:12px}
.bh-guide-edit{display:flex;flex-direction:column;gap:5px;margin-bottom:8px}
.bh-pro-badge{display:inline-block;background:linear-gradient(135deg,#f1c40f,#e67e22);color:#111;font-size:10px;font-weight:900;padding:2px 7px;border-radius:4px}
.bh-pro-status-msg{font-size:12px;line-height:1.4;color:#ffa726;background:rgba(255,167,38,.08);border:1px solid rgba(255,167,38,.35);border-radius:8px;padding:8px 10px;margin-bottom:4px}
.bh-mydecks-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px}
.bh-mydeck-card{position:relative;border:1px solid #333;border-radius:12px;padding:14px;cursor:pointer;transition:border-color 0.2s;overflow:hidden}
.bh-mydeck-bg{position:absolute;inset:0;background-size:cover;background-position:center 20%;filter:brightness(0.4) saturate(1.3);transform:scale(1.5);z-index:0}
.bh-mydeck-overlay{position:absolute;inset:0;background:linear-gradient(135deg,rgba(0,0,0,0.9) 0%,rgba(0,0,0,0.72) 100%);z-index:1}
.bh-mydeck-content{position:relative;z-index:2}
.bh-deck-actions{display:grid;grid-template-columns:repeat(2,1fr);gap:5px}
.bh-btn{border-radius:6px;padding:7px 4px;cursor:pointer;font-size:11px;font-weight:bold;border:1px solid}
.bh-btn-public{background:#1a3a5c;color:#7ec8e3;border-color:#2a5a8c}
.bh-btn-private{background:#222;color:#aaa;border-color:#444}
@media(max-width:480px){.bh-mydecks-grid{grid-template-columns:1fr}}
</style>
<?php return ob_get_clean();
});

// ============================================================
// ШОРТКОД: Страница колоды [berserk_deck_view]
// ============================================================
add_shortcode('berserk_deck_view', function() {
    ob_start(); ?>
<div id="bh-deckview-app">
  <div v-if="loading" class="dv-loading">Загрузка колоды...</div>
  <div v-else-if="error" class="dv-error">{{ error }}</div>
  <div v-else>
    <div class="dv-header">
      <img v-if="heroImage" :src="heroImage" class="dv-hero-img">
      <div class="dv-header-info">
        <h1 class="dv-title">{{ deck.name }} <span v-if="deck.is_pro || deck.author_is_pro" class="bh-pro-badge" :title="(deck.pro_achievements || deck.author_pro_achievements) || 'PRO автор'" @click="showProTip=!showProTip">PRO</span></h1>
        <div class="dv-sub">{{ deck.author }} · {{ deck.deck_json.heroTitle || '—' }} · 📅 {{ formatDate(deck.updated_at) }}</div>
        <div v-if="showProTip && (deck.pro_achievements || deck.author_pro_achievements)" class="bh-pro-tip">{{ deck.pro_achievements || deck.author_pro_achievements }}</div>
        <div class="dv-stats-row">
          <span>🃏 {{ (deck.deck_json.cards || []).length }} карт</span>
          <span>💎 {{ deck.dust_cost }}</span>
          <span>❤️ {{ deck.likes }}</span>
          <span v-if="deck.winrate !== null">🏆 {{ deck.winrate }}% ({{ deck.wins }}-{{ deck.losses }})</span>
        </div>
        <div class="dv-guide-row">
          <a v-if="deck.guide_url" :href="deck.guide_url" target="_blank" rel="noopener" class="dv-btn dv-btn-guide">Гайд</a>
          <button v-if="deck.video_url || deck.video_guide_url" @click="openVideo(deck.video_url || deck.video_guide_url)" class="dv-btn dv-btn-guide">Видеогайд</button>
          <button @click="followAuthor" class="dv-btn dv-btn-guide">Отслеживать автора</button>
        </div>
      </div>
      <div class="dv-header-actions">
        <button @click="likeDeck" class="dv-like-btn" :class="{ 'dv-liked': deck.liked_by_me }">{{ deck.liked_by_me ? '❤️' : '🤍' }} {{ deck.likes }}</button>
        <button @click="goBack" class="dv-btn-back">← Назад</button>
      </div>
    </div>
    <div class="dv-main-layout">
      <div class="dv-deck-col">
        <h2 class="dv-section-title">🃏 Карты ({{ (deck.deck_json.cards || []).length }})</h2>
        <div class="dv-card-list">
          <div v-for="item in groupedCards" :key="item.id" class="dv-card-strip" :style="{backgroundImage:'url('+item.image+')',borderLeftColor:getElemColor(item.elements)}">
            <div class="dv-strip-overlay" :style="{background:'linear-gradient(90deg,'+getElemAlpha(item.elements)+' 0%,rgba(0,0,0,0.55) 45%,rgba(0,0,0,0.05) 100%)'}"></div>
            <span class="dv-strip-cost">{{ item.cost }}</span>
            <span class="dv-strip-title">{{ item.title }}</span>
            <span class="dv-strip-count" :style="{background:getElemColor(item.elements),color:getElemText(item.elements)}">{{ item.count }}x</span>
          </div>
        </div>
      </div>
      <div class="dv-side-col">
        <div class="dv-stats-panel">
          <h2 class="dv-section-title dv-chart-title">📊 Кривая маны</h2>
          <div class="dv-cost-chart">
            <div v-for="(bucket, i) in costBuckets" :key="i" class="dv-cost-col">
              <div class="dv-cost-label">x{{ costCounts[i] }}</div>
              <div class="dv-cost-bar-bg">
                <div class="dv-cost-bar" :style="{ height: (costCounts[i] / maxCost * 100) + '%' }"></div>
              </div>
              <div class="dv-cost-hex">{{ bucket }}</div>
            </div>
          </div>
          <div class="dv-type-row">
            <div class="dv-type-col"><div class="dv-type-icon">🐉</div><div class="dv-type-count">{{ typeCounts.creature }}</div><div class="dv-type-label">Существо</div></div>
            <div class="dv-type-divider"></div>
            <div class="dv-type-col"><div class="dv-type-icon">🔥</div><div class="dv-type-count">{{ typeCounts.spell }}</div><div class="dv-type-label">Заклинание</div></div>
            <div class="dv-type-divider"></div>
            <div class="dv-type-col"><div class="dv-type-icon">🛡️</div><div class="dv-type-count">{{ typeCounts.equipment }}</div><div class="dv-type-label">Экипировка</div></div>
          </div>
        </div>
        <div v-if="!isAuthenticated" class="dv-auth-side">
          <button @click="goLogin" class="dv-btn dv-btn-auth">🔑 Авторизоваться</button>
        </div>
        <div v-else-if="deck.is_owner" class="dv-owner-side">
          <button @click="editDeck" class="dv-btn dv-btn-edit-deck">✏️ Редактировать колоду</button>
          <div class="dv-owner-mini">
            <button v-if="!deck.is_public" @click="togglePublic(1)" class="dv-btn dv-btn-public">🌐 Опубл.</button>
            <button v-else @click="togglePublic(0)" class="dv-btn dv-btn-private">🔒 Скрыть</button>
            <button @click="deleteDeck" class="dv-btn dv-btn-delete">🗑 Удалить</button>
          </div>
        </div>
      </div>
    </div>
    <div v-if="isAuthenticated" class="dv-section dv-copy-section">
      <h2 class="dv-section-title">🎮 Код колоды</h2>
      <div v-if="deck.game_code" class="dv-code-block">
        <code class="dv-code-text">{{ deck.game_code }}</code>
        <button @click="copyCode" class="dv-btn dv-btn-copy">{{ copied ? '✓ Скопировано!' : '📋 Скопировать колоду' }}</button>
      </div>
      <div v-else class="dv-code-empty">
        <span v-if="deck.is_owner">Код не импортирован. Используйте импорт в декбилдере.</span>
        <span v-else>Автор не добавил код колоды.</span>
      </div>
    </div>
    <div class="dv-section">
      <h2 class="dv-section-title">📝 Описание колоды</h2>
      <div v-if="deck.is_owner && editingDesc" class="dv-desc-edit">
        <textarea v-model="descText" rows="8" class="dv-desc-textarea" placeholder="Муллиган, геймплей, советы по игре..."></textarea>
        <input v-model="guideText" class="dv-desc-textarea" style="min-height:auto;margin-top:8px" type="url" placeholder="Ссылка на текстовый гайд">
        <input v-model="videoGuideText" class="dv-desc-textarea" style="min-height:auto;margin-top:8px" type="url" placeholder="Ссылка на YouTube-видеогайд">
        <div style="display:flex;gap:8px;margin-top:8px">
          <button @click="saveDesc" class="dv-btn dv-btn-save">💾 Сохранить</button>
          <button @click="editingDesc = false" class="dv-btn dv-btn-cancel">Отмена</button>
        </div>
      </div>
      <div v-else class="dv-desc-view">
        <div v-if="deck.description" class="dv-desc-text" style="white-space:pre-wrap">{{ deck.description }}</div>
        <div v-else class="dv-desc-empty">{{ deck.is_owner ? 'Нет описания. Нажмите «Редактировать» чтобы добавить.' : 'Автор не добавил описание.' }}</div>
        <button v-if="deck.is_owner" @click="startEditDesc" class="dv-btn dv-btn-edit">✏️ Редактировать описание</button>
      </div>
    </div>
  </div>
</div>
<script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>
<script>
(function(){
const {createApp,ref,computed,onMounted} = Vue;
const ELEM_GROUPS = [
  {key:'степи',color:'#f1c40f',textColor:'#000',alpha:'rgba(180,150,0,0.93)',slugs:['stepi','степи']},
  {key:'горы',color:'#2980b9',textColor:'#fff',alpha:'rgba(20,80,160,0.93)',slugs:['gory','горы']},
  {key:'болото',color:'#a8d5a2',textColor:'#000',alpha:'rgba(100,170,100,0.93)',slugs:['boloto','болото']},
  {key:'лес',color:'#27ae60',textColor:'#fff',alpha:'rgba(15,110,50,0.93)',slugs:['les','лес']},
  {key:'тьма',color:'#8e44ad',textColor:'#fff',alpha:'rgba(80,20,120,0.93)',slugs:['tma','тьма']},
  {key:'нейтралы',color:'#cd7f32',textColor:'#fff',alpha:'rgba(130,80,20,0.93)',slugs:['nejtraly','neutral','нейтралы']}
];
const getElemGroup = (elems) => { if (!elems || !elems.length) return ELEM_GROUPS[5]; for (const g of ELEM_GROUPS) { if (elems.some(e => g.slugs.some(s => e.includes(s)))) return g; } return ELEM_GROUPS[5]; };
const getElemColor = (elems) => getElemGroup(elems).color;
const getElemAlpha = (elems) => getElemGroup(elems).alpha;
const getElemText = (elems) => getElemGroup(elems).textColor;
const normalizeType = (t) => {
  if (t === null || t === undefined || t === '') return '';
  const s = String(t).toLowerCase().trim();
  if (s === 'creature' || s === 'spell' || s === 'equipment' || s === 'hero') return s;
  if (s === '1' || s === '01') return 'creature';
  if (s === '2' || s === '02') return 'spell';
  if (s === '3' || s === '03') return 'equipment';
  if (s.includes('закл')||s.includes('spell')||s.includes('магия')||s.includes('magic')||s === 's'||s === 'sp') return 'spell';
  if (s.includes('экип')||s.includes('equip')||s.includes('предм')||s.includes('оруж')||s.includes('weapon')||s.includes('доспех')||s.includes('armor')||s.includes('armour')||s.includes('амулет')||s.includes('amulet')||s.includes('артеф')||s.includes('artifact')||s.includes('item')||s.includes('gear')||s === 'e'||s === 'eq') return 'equipment';
  if (s.includes('герой')||s.includes('hero')) return 'hero';
  if (s.includes('сущ')||s.includes('creat')||s.includes('unit')||s.includes('minion')||s.includes('monster')||s.includes('монстр')||s.includes('юнит')||s.includes('воин')||s.includes('fighter')||s.includes('warrior')||s.includes('troop')||s.includes('отряд')||s.includes('боец')||s.includes('персонаж')||s === 'c'||s === 'cr'||s === 'u') return 'creature';
  return '';
};
const resolveCardType = (c, catalog) => {
  let t = normalizeType(c && c.type);
  if (t === 'spell' || t === 'equipment' || t === 'creature') return t;
  if (t === 'hero') return 'hero';
  const full = (catalog || []).find(x => String(x.id) === String(c && c.id));
  if (full) {
    t = normalizeType(full.type);
    if (t === 'spell' || t === 'equipment' || t === 'creature') return t;
  }
  return 'creature';
};

createApp({
  setup() {
    const loading = ref(true);
    const error = ref('');
    const deck = ref(null);
    const allCards = ref([]);
    const allHeroes = ref([]);
    const editingDesc = ref(false);
    const descText = ref('');
    const guideText = ref('');
    const videoGuideText = ref('');
    const showProTip = ref(false);
    const copied = ref(false);
    const isAuthenticated = ref(false);
    const deckbuilderUrl = '<?php echo esc_js(BH_DECKBUILDER_URL); ?>';
    const publicDecksUrl = '<?php echo esc_js(BH_PUBLIC_DECKS_URL); ?>';
    const loginUrl = '/login/?redirect_to=' + encodeURIComponent(window.location.pathname + window.location.search);

    const urlParams = new URLSearchParams(window.location.search);
    const deckId = urlParams.get('deck_id');

    const heroImage = computed(() => { if (!deck.value) return null; const hero = allHeroes.value.find(h => h.title === deck.value.deck_json.heroTitle); return hero ? hero.image : null; });

    const enrichedCards = computed(() => {
      if (!deck.value) return [];
      const cards = deck.value.deck_json.cards || [];
      return cards.map(c => { const full = allCards.value.find(x => x.id === c.id); return full || c; });
    });

    const costBuckets = [0,1,2,3,4,5,6,'7+'];
    const costCounts = computed(() => {
      const counts = [0,0,0,0,0,0,0,0];
      enrichedCards.value.forEach(c => { const cost = parseInt(c.cost)||0; if (cost >= 7) counts[7]++; else counts[cost]++; });
      return counts;
    });
    const maxCost = computed(() => Math.max(...costCounts.value, 1));

    const typeCounts = computed(() => {
      let creature = 0, spell = 0, equipment = 0;
      enrichedCards.value.forEach(c => {
        const t = resolveCardType(c, allCards.value);
        if (t === 'creature') creature++;
        else if (t === 'spell') spell++;
        else if (t === 'equipment') equipment++;
      });
      return { creature, spell, equipment };
    });

    const groupedCards = computed(() => {
      const g = {};
      enrichedCards.value.forEach(c => { if (!g[c.id]) g[c.id] = Object.assign({},c,{count:0}); g[c.id].count++; });
      return Object.values(g).sort((a,b) => (a.cost||0)-(b.cost||0) || a.title.localeCompare(b.title));
    });

    const formatDate = (ts) => { if (!ts) return ''; const d = new Date(ts * 1000); return d.toLocaleDateString('ru-RU', {day:'2-digit',month:'2-digit',year:'numeric'}); };
    const goBack = () => { window.history.back(); };
    const goLogin = () => { window.location.href = loginUrl; };

    const likeDeck = async () => {
      const r = await fetch('/wp-json/berserk/v1/decks/' + deck.value.id + '/like', {
        method:'POST', credentials:'include', headers:{'X-WP-Nonce': window.bhNonce || ''}
      });
      const res = await r.json();
      if (res.success) { deck.value.liked_by_me = res.liked; deck.value.likes = res.likes; }
    };

    const copyCode = async () => {
      if (!deck.value.game_code) return;
      try { await navigator.clipboard.writeText(deck.value.game_code); copied.value = true; setTimeout(() => copied.value = false, 2000); }
      catch(e) { const ta = document.createElement('textarea'); ta.value = deck.value.game_code; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta); copied.value = true; setTimeout(() => copied.value = false, 2000); }
    };

    const startEditDesc = () => {
      descText.value = deck.value.description || '';
      guideText.value = deck.value.guide_url || '';
      videoGuideText.value = deck.value.video_guide_url || '';
      editingDesc.value = true;
    };
    const saveDesc = async () => {
      const r = await fetch('/wp-json/berserk/v1/decks/' + deck.value.id + '/update-meta', {method:'POST',credentials:'include',headers:{'Content-Type':'application/json','X-WP-Nonce':window.bhNonce||''},body:JSON.stringify({description:descText.value, guide_url:guideText.value, video_guide_url:videoGuideText.value})});
      const res = await r.json();
      if (res.success) {
        deck.value.description = descText.value;
        deck.value.guide_url = guideText.value;
        deck.value.video_guide_url = videoGuideText.value;
        editingDesc.value = false;
      }
      else alert('Ошибка: '+(res.message||'неизвестная ошибка'));
    };
    const openVideo = (url) => { if (window.bhOpenYoutubeModal) window.bhOpenYoutubeModal(url); else window.open(url, '_blank'); };
    const followAuthor = () => {
      const authorId = deck.value.author_id || deck.value.user_id;
      const base = publicDecksUrl.endsWith('/') ? publicDecksUrl : (publicDecksUrl + '/');
      window.location.href = base + '?author_id=' + encodeURIComponent(authorId);
    };

    const editDeck = () => {
      localStorage.setItem('bh_edit_deck', JSON.stringify({
        id: deck.value.id, name: deck.value.name, hero_wp_id: deck.value.hero_wp_id,
        deck_json: deck.value.deck_json, header_id: deck.value.header_id, hero_le: deck.value.hero_le,
        game_code: deck.value.game_code, is_public: deck.value.is_public,
        guide_url: deck.value.guide_url || '', video_guide_url: deck.value.video_guide_url || ''
      }));
      window.location.href = deckbuilderUrl;
    };

    const deleteDeck = async () => {
      if (!confirm('Удалить колоду?')) return;
      const r = await fetch('/wp-json/berserk/v1/decks/delete/'+deck.value.id, {method:'POST',credentials:'include',headers:{'X-WP-Nonce':window.bhNonce||''}});
      if (r.ok) { alert('Колода удалена'); window.history.back(); }
      else alert('Ошибка удаления');
    };

    const togglePublic = async (val) => {
      const r = await fetch('/wp-json/berserk/v1/decks/'+deck.value.id+'/visibility', {method:'POST',credentials:'include',headers:{'Content-Type':'application/json','X-WP-Nonce':window.bhNonce||''},body:JSON.stringify({is_public:val})});
      const res = await r.json();
      if (res.success) deck.value.is_public = val;
      else alert('Ошибка: '+(res.message||'неизвестная ошибка'));
    };

    onMounted(async () => {
      const me = window.bhCurrentUser || {logged_in:false};
      isAuthenticated.value = !!me.logged_in;
      if (!deckId) { error.value = 'Не указан ID колоды'; loading.value = false; return; }
      try {
        const headers = {'X-WP-Nonce': window.bhNonce || ''};
        const [deckRes, dataRes] = await Promise.all([
          fetch('/wp-json/berserk/v1/decks/'+deckId, {credentials:'include', headers}),
          fetch('/wp-json/berserk/v1/data', {credentials:'include'})
        ]);
        if (!deckRes.ok) { error.value = 'Колода не найдена или нет доступа'; loading.value = false; return; }
        deck.value = await deckRes.json();
        const data = await dataRes.json();
        allCards.value = data.cards || [];
        allHeroes.value = data.heroes || [];
      } catch(e) { error.value = 'Ошибка загрузки'; }
      loading.value = false;
    });

    return { loading, error, deck, heroImage, isAuthenticated, costBuckets, costCounts, maxCost, typeCounts, groupedCards, editingDesc, descText, guideText, videoGuideText, showProTip, copied, formatDate, goBack, goLogin, likeDeck, copyCode, startEditDesc, saveDesc, editDeck, deleteDeck, togglePublic, openVideo, followAuthor, getElemColor, getElemAlpha, getElemText };
  }
}).mount('#bh-deckview-app');
})();
</script>
<style>
#bh-deckview-app{background:#070707;color:#eee;padding:16px;border-radius:15px;font-family:system-ui,sans-serif;max-width:900px;margin:0 auto}
.dv-guide-row{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}
.dv-btn-guide{background:#1a1a1a;color:#ddd;border:1px solid #444;border-radius:6px;padding:6px 10px;font-size:11px;font-weight:bold;cursor:pointer;text-decoration:none;display:inline-block}
.bh-pro-badge{display:inline-block;margin-left:6px;background:linear-gradient(135deg,#f1c40f,#e67e22);color:#111;font-size:10px;font-weight:900;padding:2px 7px;border-radius:4px;cursor:help;vertical-align:middle}
.bh-pro-tip{margin:8px 0;padding:8px 10px;background:rgba(0,0,0,.75);border:1px solid #665200;border-radius:6px;font-size:12px;color:#f8e7a1;white-space:pre-wrap}
.dv-loading,.dv-error{text-align:center;padding:80px;color:#f1c40f;font-size:16px}
.dv-error{color:#e74c3c}
.dv-header{display:flex;gap:16px;align-items:flex-start;margin-bottom:20px;flex-wrap:wrap}
.dv-hero-img{width:80px;height:112px;object-fit:cover;border-radius:8px;border:1px solid #555;flex-shrink:0}
.dv-header-info{flex:1;min-width:200px}
.dv-title{color:#f1c40f;margin:0 0 6px;font-size:clamp(18px,4vw,24px)}
.dv-sub{font-size:12px;color:#aaa;margin-bottom:8px}
.dv-stats-row{display:flex;gap:12px;font-size:12px;color:#ccc;flex-wrap:wrap}
.dv-header-actions{display:flex;flex-direction:column;gap:8px;align-items:flex-end}
.dv-like-btn{background:rgba(20,20,20,0.8);color:#aaa;border:1px solid #444;border-radius:20px;padding:6px 14px;cursor:pointer;font-size:13px;transition:0.15s}
.dv-like-btn:hover{border-color:#666}
.dv-liked{background:rgba(60,20,20,0.9);color:#e74c3c;border-color:#7d2d2d}
.dv-btn-back{background:#222;color:#fff;border:1px solid #333;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:12px}
.dv-main-layout{display:flex;gap:16px;align-items:flex-start;margin-bottom:20px}
.dv-deck-col{flex:1;min-width:0}
.dv-side-col{flex:0 0 280px;width:280px}
.dv-section-title{color:#f1c40f;font-size:15px;margin:0 0 10px;letter-spacing:1px}
.dv-chart-title{margin-bottom:14px;text-align:center}
.dv-stats-panel{background:radial-gradient(circle at 50% 30%,#0e1a30 0%,#070707 100%);border:1px solid #1a2a4a;border-radius:12px;padding:16px}
.dv-cost-chart{display:flex;justify-content:space-around;align-items:flex-end;gap:4px;margin-bottom:16px;min-height:120px}
.dv-cost-col{display:flex;flex-direction:column;align-items:center;flex:1;max-width:32px}
.dv-cost-label{font-size:10px;color:#ccc;font-weight:bold;margin-bottom:3px}
.dv-cost-bar-bg{width:100%;max-width:28px;height:70px;background:#0e1a30;border-radius:6px 6px 0 0;display:flex;align-items:flex-end;overflow:hidden;border:1px solid #1a2a4a}
.dv-cost-bar{width:100%;background:#7ba5f2;border-radius:4px 4px 0 0;transition:height 0.3s ease;min-height:2px}
.dv-cost-hex{margin-top:5px;width:24px;height:24px;background:#c8a66a;color:#000;font-weight:bold;font-size:10px;display:flex;align-items:center;justify-content:center;clip-path:polygon(25% 0%,75% 0%,100% 50%,75% 100%,25% 100%,0% 50%)}
.dv-type-row{display:flex;justify-content:space-around;align-items:center;border-top:1px solid #1a2a4a;padding-top:12px}
.dv-type-col{display:flex;flex-direction:column;align-items:center;gap:2px;flex:1}
.dv-type-icon{font-size:22px}
.dv-type-count{font-size:20px;font-weight:bold;color:#fff}
.dv-type-label{font-size:10px;color:#ccc}
.dv-type-divider{width:1px;height:40px;background:#1a2a4a}
.dv-auth-side{margin-top:12px}
.dv-btn-auth{width:100%;background:#1a3a5c;color:#7ec8e3;border:1px solid #2a5a8c;border-radius:6px;padding:10px;cursor:pointer;font-size:13px;font-weight:bold;transition:0.15s}
.dv-btn-auth:hover{background:#2a5a8c;color:#fff}
.dv-owner-side{margin-top:12px;display:flex;flex-direction:column;gap:8px}
.dv-owner-mini{display:flex;gap:6px}
.dv-owner-mini .dv-btn{flex:1;font-size:10px;padding:6px 4px}
.dv-card-list{display:flex;flex-direction:column;gap:3px}
.dv-card-strip{height:38px;border-radius:4px;position:relative;display:flex;align-items:center;background-size:160%;background-position:center 30%;border-left:4px solid #888;overflow:hidden}
.dv-strip-overlay{position:absolute;top:0;left:0;width:100%;height:100%}
.dv-strip-cost{position:relative;width:26px;text-align:center;font-weight:bold;color:#fff;z-index:2;font-size:13px;text-shadow:0 0 5px #000;flex-shrink:0}
.dv-strip-title{position:relative;flex:1;font-size:11px;font-weight:bold;color:#fff;z-index:2;padding-left:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-shadow:1px 1px 3px #000}
.dv-strip-count{position:relative;font-weight:bold;padding:0 8px;height:100%;display:flex;align-items:center;z-index:2;font-size:11px;flex-shrink:0}
.dv-section{margin-bottom:20px}
.dv-copy-section{padding-top:16px;border-top:1px solid #222}
.dv-code-block{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.dv-code-text{flex:1;min-width:200px;background:#0a0a0a;border:1px solid #333;border-radius:6px;padding:10px;color:#7ec8e3;font-size:11px;font-family:monospace;word-break:break-all;display:block}
.dv-code-empty{color:#666;font-size:13px;font-style:italic}
.dv-desc-text{background:#111;border:1px solid #333;border-radius:8px;padding:14px;color:#ddd;font-size:13px;line-height:1.6}
.dv-desc-empty{color:#666;font-size:13px;font-style:italic;margin-bottom:10px}
.dv-desc-textarea{width:100%;background:#0a0a0a;border:1px solid #333;color:#ddd;padding:12px;border-radius:8px;font-size:13px;line-height:1.6;resize:vertical;box-sizing:border-box;font-family:inherit}
.dv-desc-textarea:focus{outline:none;border-color:#f1c40f}
.dv-btn{border-radius:6px;padding:8px 14px;cursor:pointer;font-size:12px;font-weight:bold;border:1px solid;transition:0.15s}
.dv-btn:hover{filter:brightness(1.15)}
.dv-btn-save{background:#1a3d1a;color:#4caf50;border-color:#2e7d32}
.dv-btn-cancel{background:#222;color:#aaa;border-color:#444}
.dv-btn-edit{background:#2a1a3a;color:#c39bd3;border-color:#5a2d7a}
.dv-btn-copy{background:#1a3a5c;color:#7ec8e3;border-color:#2a5a8c}
.dv-btn-edit-deck{width:100%;background:#2a1a3a;color:#c39bd3;border-color:#5a2d7a}
.dv-btn-delete{background:#3d1a1a;color:#e74c3c;border-color:#7d2d2d}
.dv-btn-public{background:#1a3a5c;color:#7ec8e3;border-color:#2a5a8c}
.dv-btn-private{background:#222;color:#aaa;border-color:#444}
@media(max-width:640px){
  #bh-deckview-app{padding:10px;border-radius:10px}
  .dv-header{flex-direction:column;align-items:center;text-align:center}
  .dv-header-actions{flex-direction:row;align-items:center}
  .dv-main-layout{flex-direction:column}
  .dv-side-col{flex:1;width:100%}
  .dv-cost-bar-bg{height:60px}
  .dv-cost-hex{width:22px;height:22px;font-size:10px}
  .dv-type-icon{font-size:20px}
  .dv-type-count{font-size:18px}
}
</style>
<?php return ob_get_clean();
});
add_action('wp_head', function() {
    $user = wp_get_current_user();
    $user_data = $user->ID ? array('logged_in' => true, 'id' => $user->ID, 'name' => $user->display_name) : array('logged_in' => false);
    echo '<script>';
    echo 'window.bhNonce = ' . json_encode(wp_create_nonce('wp_rest')) . ';';
    echo 'window.bhCurrentUser = ' . json_encode($user_data) . ';';
    echo <<<'JS'
window.bhExtractYoutubeId = function(url) {
  if (!url) return '';
  var m = String(url).match(/(?:youtu\.be\/|youtube\.com\/(?:watch\?v=|embed\/|shorts\/|live\/)|youtube-nocookie\.com\/embed\/)([A-Za-z0-9_-]{6,})/);
  return m ? m[1] : '';
};
window.bhOpenYoutubeModal = function(url) {
  var id = window.bhExtractYoutubeId(url);
  if (!id) { window.open(url, '_blank'); return; }
  if (typeof window.openYoutubeModal === 'function') { window.openYoutubeModal(url, id); return; }
  if (typeof window.openVideoModal === 'function') { window.openVideoModal(url, id); return; }
  var existing = document.querySelector('[data-bh-yt-modal], #youtube-modal, .youtube-modal, .yt-modal, #yt-modal');
  if (existing) {
    var iframe = existing.querySelector('iframe');
    if (iframe) iframe.src = 'https://www.youtube.com/embed/' + id + '?autoplay=1';
    existing.classList.add('open', 'active', 'is-open', 'show');
    existing.style.display = 'flex';
    return;
  }
  var modal = document.getElementById('bh-yt-fallback-modal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'bh-yt-fallback-modal';
    modal.setAttribute('data-bh-yt-modal', '1');
    modal.innerHTML = '<div class="bh-yt-backdrop"></div><div class="bh-yt-box"><button type="button" class="bh-yt-close" aria-label="Закрыть">×</button><div class="bh-yt-frame-wrap"><iframe allow="autoplay; encrypted-media" allowfullscreen></iframe></div></div>';
    document.body.appendChild(modal);
    var style = document.createElement('style');
    style.textContent = '#bh-yt-fallback-modal{position:fixed;inset:0;z-index:100000;display:none;align-items:center;justify-content:center}#bh-yt-fallback-modal.open{display:flex}.bh-yt-backdrop{position:absolute;inset:0;background:rgba(0,0,0,.85)}.bh-yt-box{position:relative;width:min(920px,94vw);z-index:1}.bh-yt-frame-wrap{position:relative;padding-top:56.25%;background:#000;border-radius:10px;overflow:hidden}.bh-yt-frame-wrap iframe{position:absolute;inset:0;width:100%;height:100%;border:0}.bh-yt-close{position:absolute;right:-6px;top:-38px;background:transparent;border:0;color:#fff;font-size:32px;cursor:pointer;line-height:1}';
    document.head.appendChild(style);
    modal.querySelector('.bh-yt-backdrop').onclick = function(){ window.bhCloseYoutubeModal(); };
    modal.querySelector('.bh-yt-close').onclick = function(){ window.bhCloseYoutubeModal(); };
  }
  modal.querySelector('iframe').src = 'https://www.youtube.com/embed/' + id + '?autoplay=1';
  modal.classList.add('open');
};
window.bhCloseYoutubeModal = function() {
  var modal = document.getElementById('bh-yt-fallback-modal');
  if (!modal) return;
  var iframe = modal.querySelector('iframe');
  if (iframe) iframe.src = '';
  modal.classList.remove('open');
};
JS;
    echo '</script>';
});
