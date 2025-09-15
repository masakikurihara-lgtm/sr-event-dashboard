import streamlit as st
import requests
import pandas as pd
import time
import datetime
import plotly.express as px
import pytz
from streamlit_autorefresh import st_autorefresh
from datetime import timedelta
import logging


# Set page configuration
st.set_page_config(
    page_title="SHOWROOM Event Dashboard",
    page_icon="🎤",
    layout="wide",
)

HEADERS = {"User-Agent": "Mozilla/5.0"}
JST = pytz.timezone('Asia/Tokyo')

@st.cache_data(ttl=3600)
def get_events():
    """
    開催中および終了済みのイベントリストを取得する。
    終了済みイベントには "[終了]" という接頭辞を付ける。
    """
    all_events = []
    # status=1 (開催中) と status=4 (終了済み) の両方を取得
    for status in [1, 4]:
        page = 1
        # 各ステータスで最大10ページまで取得
        for _ in range(10):
            url = f"https://www.showroom-live.com/api/event/search?status={status}&page={page}"
            try:
                response = requests.get(url, headers=HEADERS, timeout=5)
                response.raise_for_status()
                data = response.json()
                
                page_events = []
                if isinstance(data, dict):
                    if 'events' in data:
                        page_events = data['events']
                    elif 'event_list' in data:
                        page_events = data['event_list']
                elif isinstance(data, list):
                    page_events = data

                if not page_events:
                    break  # イベントがなくなったらループを抜ける

                # 既存のフィルタリングロジックを適用
                filtered_page_events = [
                    event for event in page_events 
                    if event.get("show_ranking") is not False and event.get("is_event_block") is not True
                ]
                
                # 終了済みイベントの場合、イベント名に接頭辞を追加
                if status == 4:
                    for event in filtered_page_events:
                        event['event_name'] = f"[終了] {event['event_name']}"

                all_events.extend(filtered_page_events)
                page += 1
            except requests.exceptions.RequestException as e:
                st.error(f"イベントデータ取得中にエラーが発生しました (status={status}): {e}")
                break
            except ValueError:
                st.error(f"APIからのJSONデコードに失敗しました: {response.text}")
                break
    return all_events


RANKING_API_CANDIDATES = [
    "https://www.showroom-live.com/api/event/{event_url_key}/ranking?page={page}",
    "https://www.showroom-live.com/api/event/ranking?event_id={event_id}&page={page}",
]

@st.cache_data(ttl=300)
def get_event_ranking_with_room_id(event_url_key, event_id, max_pages=10):
    all_ranking_data = []
    for base_url in RANKING_API_CANDIDATES:
        try:
            temp_ranking_data = []
            for page in range(1, max_pages + 1):
                url = base_url.format(event_url_key=event_url_key, event_id=event_id, page=page)
                response = requests.get(url, headers=HEADERS, timeout=10)
                if response.status_code == 404:
                    break
                response.raise_for_status()
                data = response.json()
                ranking_list = None
                if isinstance(data, dict) and 'ranking' in data:
                    ranking_list = data['ranking']
                elif isinstance(data, dict) and 'event_list' in data:
                    ranking_list = data['event_list']
                elif isinstance(data, list):
                    ranking_list = data
                if not ranking_list:
                    break
                temp_ranking_data.extend(ranking_list)
            if temp_ranking_data and any('room_id' in r for r in temp_ranking_data):
                all_ranking_data = temp_ranking_data
                break
        except requests.exceptions.RequestException:
            continue
    if not all_ranking_data:
        return None
    room_map = {}
    for room_info in all_ranking_data:
        room_id = room_info.get('room_id')
        room_name = room_info.get('room_name') or room_info.get('user_name')
        if room_id and room_name:
            room_map[room_name] = {
                'room_id': room_id,
                'rank': room_info.get('rank'),
                'point': room_info.get('point')
            }
    return room_map

def get_room_event_info(room_id):
    url = f"https://www.showroom-live.com/api/room/event_and_support?room_id={room_id}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"ルームID {room_id} のデータ取得中にエラーが発生しました: {e}")
        return None

@st.cache_data(ttl=30)
def get_gift_list(room_id):
    url = f"https://www.showroom-live.com/api/live/gift_list?room_id={room_id}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=5)
        response.raise_for_status()
        data = response.json()
        gift_list_map = {}
        for gift in data.get('normal', []) + data.get('special', []):
            try:
                point_value = int(gift.get('point', 0))
            except (ValueError, TypeError):
                point_value = 0
            gift_list_map[str(gift['gift_id'])] = {
                'name': gift.get('gift_name', 'N/A'),
                'point': point_value,
                'image': gift.get('image', '')
            }
        return gift_list_map
    except requests.exceptions.RequestException as e:
        st.error(f"ルームID {room_id} のギフトリスト取得中にエラーが発生しました: {e}")
        return {}

if "gift_log_cache" not in st.session_state:
    st.session_state.gift_log_cache = {}

def get_and_update_gift_log(room_id):
    url = f"https://www.showroom-live.com/api/live/gift_log?room_id={room_id}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=5)
        response.raise_for_status()
        new_gift_log = response.json().get('gift_log', [])
        
        if room_id not in st.session_state.gift_log_cache:
            st.session_state.gift_log_cache[room_id] = []
        
        existing_log = st.session_state.gift_log_cache[room_id]
        
        if new_gift_log:
            existing_log_set = {(log.get('gift_id'), log.get('created_at'), log.get('num')) for log in existing_log}
            
            for log in new_gift_log:
                log_key = (log.get('gift_id'), log.get('created_at'), log.get('num'))
                if log_key not in existing_log_set:
                    existing_log.append(log)
        
        st.session_state.gift_log_cache[room_id].sort(key=lambda x: x.get('created_at', 0), reverse=True)
        
        return st.session_state.gift_log_cache[room_id]
        
    except requests.exceptions.RequestException as e:
        st.warning(f"ルームID {room_id} のギフトログ取得中にエラーが発生しました。配信中か確認してください: {e}")
        return st.session_state.gift_log_cache.get(room_id, [])

def get_onlives_rooms():
    onlives = {}
    try:
        url = "https://www.showroom-live.com/api/live/onlives"
        response = requests.get(url, headers=HEADERS, timeout=5)
        response.raise_for_status()
        data = response.json()
        all_lives = []
        if isinstance(data, dict):
            if 'onlives' in data and isinstance(data['onlives'], list):
                for genre_group in data['onlives']:
                    if 'lives' in genre_group and isinstance(genre_group['lives'], list):
                        all_lives.extend(genre_group['lives'])
            for live_type in ['official_lives', 'talent_lives', 'amateur_lives']:
                if live_type in data and isinstance(data.get(live_type), list):
                    all_lives.extend(data[live_type])
        for room in all_lives:
            room_id = None
            started_at = None
            if isinstance(room, dict):
                room_id = room.get('room_id')
                started_at = room.get('started_at')
                if room_id is None and 'live_info' in room and isinstance(room['live_info'], dict):
                    room_id = room['live_info'].get('room_id')
                    started_at = room['live_info'].get('started_at')
                if room_id is None and 'room' in room and isinstance(room['room'], dict):
                    room_id = room['room'].get('room_id')
                    started_at = room['room'].get('started_at')
            if room_id and started_at is not None:
                try:
                    onlives[int(room_id)] = started_at
                except (ValueError, TypeError):
                    continue
    except requests.exceptions.RequestException as e:
        st.warning(f"配信情報取得中にエラーが発生しました: {e}")
    except (ValueError, AttributeError):
        st.warning("配信情報のJSONデコードまたは解析に失敗しました。")
    return onlives

def get_rank_color(rank):
    """
    ランキングに応じたカラーコードを返す
    Plotlyのデフォルトカラーを参考に設定
    """
    colors = px.colors.qualitative.Plotly
    if rank is None:
        return "#A9A9A9"  # DarkGray
    try:
        rank_int = int(rank)
        if rank_int <= 0:
            return colors[0]
        return colors[(rank_int - 1) % len(colors)]
    except (ValueError, TypeError):
        return "#A9A9A9"
    
def main():
    st.markdown("<h1 style='font-size:2.5em;'>🎤 SHOWROOM Event Dashboard</h1>", unsafe_allow_html=True)
    st.write("イベント順位やポイント差、スペシャルギフトの履歴などを、リアルタイムで可視化するツールです。")

    if "room_map_data" not in st.session_state:
        st.session_state.room_map_data = None
    if "selected_event_name" not in st.session_state:
        st.session_state.selected_event_name = None
    if "selected_room_names" not in st.session_state:
        st.session_state.selected_room_names = []
    if "multiselect_default_value" not in st.session_state:
        st.session_state.multiselect_default_value = []
    if "multiselect_key_counter" not in st.session_state:
        st.session_state.multiselect_key_counter = 0
    if "show_dashboard" not in st.session_state:
        st.session_state.show_dashboard = False

    st.markdown("<h2 style='font-size:2em;'>1. イベントを選択</h2>", unsafe_allow_html=True)
    events = get_events()
    if not events:
        st.warning("表示可能なイベントが見つかりませんでした。")
        return

    event_options = {event['event_name']: event for event in events}
    selected_event_name = st.selectbox(
        "イベント名を選択してください:", 
        options=list(event_options.keys()), key="event_selector")
    
    st.markdown(
        "<p style='font-size:12px; margin: -10px 0px 20px 0px; color:#a1a1a1;'>※ランキング型イベントが対象になります。ただし、ブロック型は対象外になります。</p>",
        unsafe_allow_html=True
    )

    if not selected_event_name:
        st.warning("イベントを選択してください。")
        return

    selected_event_data = event_options.get(selected_event_name)
    event_url = f"https://www.showroom-live.com/event/{selected_event_data.get('event_url_key')}"
    started_at_dt = datetime.datetime.fromtimestamp(selected_event_data.get('started_at'), JST)
    ended_at_dt = datetime.datetime.fromtimestamp(selected_event_data.get('ended_at'), JST)
    event_period_str = f"{started_at_dt.strftime('%Y/%m/%d %H:%M')} - {ended_at_dt.strftime('%Y/%m/%d %H:%M')}"
    st.info(f"選択されたイベント: **{selected_event_name}**")

    st.markdown("<h2 style='font-size:2em;'>2. 比較したいルームを選択</h2>", unsafe_allow_html=True)
    selected_event_key = selected_event_data.get('event_url_key', '')
    selected_event_id = selected_event_data.get('event_id')

    # --- ▼▼▼ ここからが修正箇所(1) ▼▼▼ ---
    # イベントを変更した場合、「上位10ルームまでを選択」のチェックボックスも初期化する
    if st.session_state.selected_event_name != selected_event_name or st.session_state.room_map_data is None:
        with st.spinner('イベント参加者情報を取得中...'):
            st.session_state.room_map_data = get_event_ranking_with_room_id(selected_event_key, selected_event_id)
        st.session_state.selected_event_name = selected_event_name
        st.session_state.selected_room_names = []
        st.session_state.multiselect_default_value = []
        st.session_state.multiselect_key_counter += 1
        # チェックボックスのキーが存在すればFalseに設定
        if 'select_top_10_checkbox' in st.session_state:
            st.session_state.select_top_10_checkbox = False
        st.session_state.show_dashboard = False
        st.rerun()
    # --- ▲▲▲ ここまでが修正箇所(1) ▲▲▲ ---

    room_count_text = ""
    if st.session_state.room_map_data:
        room_count = len(st.session_state.room_map_data)
        room_count_text = f" （現在{room_count}ルーム参加）"
    st.markdown(f"**▶ [イベントページへ移動する]({event_url})**{room_count_text}", unsafe_allow_html=True)

    if not st.session_state.room_map_data:
        st.warning("このイベントの参加者情報を取得できませんでした。")
        return

    with st.form("room_selection_form"):
        select_top_10 = st.checkbox(
            "上位10ルームまでを選択（**※チェックされている場合はこちらが優先されます**）", 
            key="select_top_10_checkbox")
        room_map = st.session_state.room_map_data
        sorted_rooms = sorted(room_map.items(), key=lambda item: item[1].get('point', 0), reverse=True)
        room_options = [room[0] for room in sorted_rooms]
        top_10_rooms = room_options[:10]
        selected_room_names_temp = st.multiselect(
            "比較したいルームを選択 (複数選択可):", options=room_options,
            default=st.session_state.multiselect_default_value,
            key=f"multiselect_{st.session_state.multiselect_key_counter}")
        submit_button = st.form_submit_button("表示する")

    if submit_button:
        if st.session_state.select_top_10_checkbox:
            st.session_state.selected_room_names = top_10_rooms
            st.session_state.multiselect_default_value = top_10_rooms
            st.session_state.multiselect_key_counter += 1
        else:
            st.session_state.selected_room_names = selected_room_names_temp
            st.session_state.multiselect_default_value = selected_room_names_temp
        st.session_state.show_dashboard = True
        st.rerun()
    
    if st.session_state.show_dashboard:
            if not st.session_state.selected_room_names:
                st.warning("最低1つのルームを選択してください。")
                return

            st.markdown("<h2 style='font-size:2em;'>3. リアルタイムダッシュボード</h2>", unsafe_allow_html=True)
            st.info("10秒ごとに自動更新されます。")

            with st.container(border=True):
                        col1, col2 = st.columns([1, 1])
                        with col1:
                            st.markdown(f"**<font size='5'>イベント期間</font>**", unsafe_allow_html=True)
                            st.markdown(f"**{event_period_str}**", unsafe_allow_html=True)
                        with col2:
                            st.markdown(f"**<font size='5'>残り時間</font>**", unsafe_allow_html=True)

                            if selected_event_data and selected_event_data.get("ended_at"):
                                ended_at = selected_event_data.get("ended_at")
                                try:
                                    ended_at = int(ended_at)
                                except Exception:
                                    ended_at = 0
                            else:
                                ended_at = 0

                            if ended_at > 0:
                                ended_ms = ended_at * 1000
                                st.components.v1.html(f"""
                                <div style="height: 25px; display: flex; align-items: center; padding-top: 5px;">
                                    <span id="sr_countdown_timer_in_col" style="color: red; font-weight: bold; font-size: 1.5rem;" data-end="{ended_ms}">計算中...</span>
                                </div>
                                <script>
                                (function() {{
                                    function start() {{
                                        const timer = document.getElementById('sr_countdown_timer_in_col');
                                        if (!timer) return false;
                                        const END = parseInt(timer.dataset.end, 10);
                                        if (isNaN(END)) return false;
                                        if (window._sr_countdown_interval_in_col) clearInterval(window._sr_countdown_interval_in_col);

                                        function pad(n) {{ return String(n).padStart(2,'0'); }}
                                        function formatMs(ms) {{
                                            if (ms < 0) ms = 0;
                                            let s = Math.floor(ms / 1000), days = Math.floor(s / 86400);
                                            s %= 86400;
                                            let hh = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
                                            if (days > 0) return days + 'd ' + pad(hh) + ':' + pad(mm) + ':' + pad(ss);
                                            return pad(hh) + ':' + pad(mm) + ':' + pad(ss);
                                        }}
                                        function update() {{
                                            const diff = END - Date.now();
                                            if (diff <= 0) {{
                                                timer.textContent = 'イベント終了';
                                                timer.style.color = '#808080';
                                                clearInterval(window._sr_countdown_interval_in_col);
                                                return;
                                            }}
                                            timer.textContent = formatMs(diff);
                                            const totalSeconds = Math.floor(diff / 1000);
                                            if (totalSeconds <= 3600) timer.style.color = '#ff4b4b';
                                            else if (totalSeconds <= 10800) timer.style.color = '#ffa500';
                                            else timer.style.color = '#4CAF50';
                                        }}
                                        update();
                                        window._sr_countdown_interval_in_col = setInterval(update, 1000);
                                        return true;
                                    }}
                                    let retries = 0;
                                    const retry = () => {{
                                        if (window._sr_countdown_interval_in_col || retries++ > 10) return;
                                        if (!start()) setTimeout(retry, 300);
                                    }};
                                    if (document.readyState === 'complete' || document.readyState === 'interactive') retry();
                                    else window.addEventListener('load', retry);
                                }})();
                                </script>
                                """, height=40)
                            else:
                                st.markdown(f"<span style='color: #808080;'>**イベント終了**</span>", unsafe_allow_html=True)
                    

            current_time = datetime.datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
            st.write(f"最終更新日時 (日本時間): {current_time}")

            is_event_ended = datetime.datetime.now(JST) > ended_at_dt
            
            final_ranking_data = {}
            if is_event_ended:
                with st.spinner('イベント終了後の最終ランキングデータを取得中...'):
                    event_url_key = selected_event_data.get('event_url_key')
                    event_id = selected_event_data.get('event_id')
                    final_ranking_map = get_event_ranking_with_room_id(event_url_key, event_id, max_pages=30)
                    if final_ranking_map:
                        for name, data in final_ranking_map.items():
                            if 'room_id' in data:
                                final_ranking_data[data['room_id']] = {
                                    'rank': data.get('rank'), 'point': data.get('point')
                                }
                    else:
                        st.warning("イベント終了後の最終ランキングデータを取得できませんでした。")

            onlives_rooms = get_onlives_rooms()

            data_to_display = []
            if st.session_state.selected_room_names:
                for room_name in st.session_state.selected_room_names:
                    try:
                        if room_name not in st.session_state.room_map_data:
                            st.error(f"選択されたルーム名 '{room_name}' が見つかりません。リストを更新してください。")
                            continue
                        
                        room_id = st.session_state.room_map_data[room_name]['room_id']
                        rank, point, upper_gap, lower_gap = 'N/A', 'N/A', 'N/A', 'N/A'
                        
                        if is_event_ended:
                            if room_id in final_ranking_data:
                                rank = final_ranking_data[room_id].get('rank', 'N/A')
                                point = final_ranking_data[room_id].get('point', 'N/A')
                                upper_gap, lower_gap = 0, 0
                            else:
                                st.warning(f"ルーム名 '{room_name}' の最終ランキング情報が見つかりませんでした。")
                                continue
                        else:
                            room_info = get_room_event_info(room_id)
                            if not isinstance(room_info, dict):
                                st.warning(f"ルームID {room_id} のデータが不正な形式です。スキップします。")
                                continue
                            
                            rank_info = None
                            if 'ranking' in room_info and isinstance(room_info['ranking'], dict):
                                rank_info = room_info['ranking']
                            elif 'event_and_support_info' in room_info and isinstance(room_info['event_and_support_info'], dict):
                                event_info = room_info['event_and_support_info']
                                if 'ranking' in event_info and isinstance(event_info['ranking'], dict):
                                    rank_info = event_info['ranking']
                            elif 'event' in room_info and isinstance(room_info['event'], dict):
                                event_data = room_info['event']
                                if 'ranking' in event_data and isinstance(event_data['ranking'], dict):
                                    rank_info = event_data['ranking']

                            if rank_info and 'point' in rank_info:
                                rank = rank_info.get('rank', 'N/A')
                                point = rank_info.get('point', 'N/A')
                                upper_gap = rank_info.get('upper_gap', 'N/A')
                                lower_gap = rank_info.get('lower_gap', 'N/A')
                            else:
                                st.warning(f"ルーム名 '{room_name}' のランキング情報が不完全です。スキップします。")
                                continue
                        
                        is_live = int(room_id) in onlives_rooms
                        started_at_str = ""
                        if is_live:
                            started_at_ts = onlives_rooms.get(int(room_id))
                            if started_at_ts:
                                started_at_dt = datetime.datetime.fromtimestamp(started_at_ts, JST)
                                started_at_str = started_at_dt.strftime("%Y/%m/%d %H:%M")

                        data_to_display.append({
                            "配信中": "🔴" if is_live else "", "ルーム名": room_name,
                            "現在の順位": rank, "現在のポイント": point,
                            "上位とのポイント差": upper_gap, "下位とのポイント差": lower_gap,
                            "配信開始時間": started_at_str
                        })
                    except Exception as e:
                        st.error(f"データ処理中に予期せぬエラーが発生しました（ルーム名: {room_name}）。エラー: {e}")
                        continue

            if data_to_display:
                df = pd.DataFrame(data_to_display)
                df['現在の順位'] = pd.to_numeric(df['現在の順位'], errors='coerce')
                df['現在のポイント'] = pd.to_numeric(df['現在のポイント'], errors='coerce')
                df = df.sort_values(by='現在の順位', ascending=True, na_position='last').reset_index(drop=True)
                live_status = df['配信中']
                
                df = df.drop(columns=['配信中'])
                
                df['上位とのポイント差'] = (df['現在のポイント'].shift(1) - df['現在のポイント']).abs().fillna(0).astype(int)
                if not df.empty:
                    df.at[0, '上位とのポイント差'] = 0
                df['下位とのポイント差'] = (df['現在のポイント'].shift(-1) - df['現在のポイント']).abs().fillna(0).astype(int)
                df.insert(0, '配信中', live_status)
                
                started_at_column = df['配信開始時間']
                df = df.drop(columns=['配信開始時間'])
                df.insert(1, '配信開始時間', started_at_column)

                st.subheader("📊 比較対象ルームのステータス")
                required_cols = ['現在のポイント', '上位とのポイント差', '下位とのポイント差']
                if all(col in df.columns for col in required_cols):
                    try:
                        def highlight_rows(row):
                            if row['配信中'] == '🔴':
                                return ['background-color: #e6fff2'] * len(row)
                            elif row.name % 2 == 1:
                                return ['background-color: #fcfcfc'] * len(row)
                            else:
                                return [''] * len(row)
                        df_to_format = df.copy()
                        for col in required_cols:
                            df_to_format[col] = pd.to_numeric(df_to_format[col], errors='coerce').fillna(0).astype(int)
                        styled_df = df_to_format.style.apply(highlight_rows, axis=1).highlight_max(axis=0, subset=['現在のポイント']).format(
                            {'現在のポイント': '{:,}', '上位とのポイント差': '{:,}', '下位とのポイント差': '{:,}'})
                        
                        table_height_css = """
                        <style> .st-emotion-cache-1r7r34u { height: 265px; overflow-y: auto; } </style>
                        """
                        st.markdown(table_height_css, unsafe_allow_html=True)
                        st.dataframe(styled_df, use_container_width=True, hide_index=True, height=265)
                    except Exception as e:
                        st.error(f"データフレームのスタイル適用中にエラーが発生しました: {e}")
                        st.dataframe(df, use_container_width=True, hide_index=True, height=265)
                else:
                    st.dataframe(df, use_container_width=True, hide_index=True, height=265)

            gift_history_title = "🎁 スペシャルギフト履歴"
            if is_event_ended:
                gift_history_title += " <span style='font-size: 14px;'>（イベントは終了しましたが、現在配信中のルームのみ表示）</span>"
            else:
                gift_history_title += " <span style='font-size: 14px;'>（配信中のルームのみ表示）</span>"
            st.markdown(f"### {gift_history_title}", unsafe_allow_html=True)

            st.markdown("<div style='margin-bottom: 16px;'></div>", unsafe_allow_html=True)
            gift_container = st.container()
            
            css_style = """
                <style>
                .container-wrapper { display: flex; flex-wrap: wrap; gap: 15px; }
                .room-container {
                    position: relative; width: 175px; flex-shrink: 0; border: 1px solid #ddd; border-radius: 5px;
                    padding: 10px; height: 500px; display: flex; flex-direction: column; padding-top: 30px;
                }
                .ranking-label {
                    position: absolute; top: -12px; left: 50%; transform: translateX(-50%); padding: 2px 8px;
                    border-radius: 12px; color: white; font-weight: bold; font-size: 0.9rem; z-index: 10;
                    white-space: nowrap; box-shadow: 0 2px 5px rgba(0,0,0,0.2);
                }
                .room-title {
                    text-align: center; font-size: 1rem; font-weight: bold; margin-bottom: 10px; display: -webkit-box;
                    -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; white-space: normal;
                    line-height: 1.4em; min-height: calc(1.4em * 3);
                }
                .gift-list-container { flex-grow: 1; height: 400px; overflow-y: scroll; scrollbar-width: auto; }
                .gift-item { display: flex; flex-direction: column; padding: 8px 8px; border-bottom: 1px solid #eee; gap: 4px; }
                .gift-item:last-child { border-bottom: none; }
                .gift-header { font-weight: bold; }
                .gift-info-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
                .gift-image { width: 30px; height: 30px; border-radius: 5px; object-fit: contain; }
                .highlight-10000 { background-color: #ffe5e5; } .highlight-30000 { background-color: #ffcccc; }
                .highlight-60000 { background-color: #ffb2b2; } .highlight-100000 { background-color: #ff9999; }
                .highlight-300000 { background-color: #ff7f7f; }
                </style>
            """
            
            live_rooms_data = []
            if not df.empty and st.session_state.room_map_data:
                selected_live_room_ids = {int(st.session_state.room_map_data[row['ルーム名']]['room_id']) for index, row in df.iterrows() if '配信中' in row and row['配信中'] == '🔴'}
                rooms_to_delete = [room_id for room_id in st.session_state.gift_log_cache if int(room_id) not in selected_live_room_ids]
                for room_id in rooms_to_delete:
                    del st.session_state.gift_log_cache[room_id]
                
                for index, row in df.iterrows():
                    room_name = row['ルーム名']
                    if room_name in st.session_state.room_map_data:
                        room_id = st.session_state.room_map_data[room_name]['room_id']
                        if int(room_id) in onlives_rooms:
                            live_rooms_data.append({
                                "room_name": room_name, "room_id": room_id, "rank": row['現在の順位']
                            })
            
            room_html_list = []
            if len(live_rooms_data) > 0:
                for room_data in live_rooms_data:
                    room_name = room_data['room_name']
                    room_id = room_data['room_id']
                    rank = room_data.get('rank', 'N/A')
                    rank_color = get_rank_color(rank)

                    if int(room_id) in onlives_rooms:
                        gift_log = get_and_update_gift_log(room_id)
                        gift_list_map = get_gift_list(room_id)
                        
                        html_content = f"""
                        <div class="room-container">
                            <div class="ranking-label" style="background-color: {rank_color};">{rank}位</div>
                            <div class="room-title">{room_name}</div>
                            <div class="gift-list-container">
                        """
                        if not gift_list_map:
                            html_content += '<p style="text-align: center; padding: 12px 0; color: orange;">ギフト情報取得失敗</p>'

                        if gift_log:
                            for log in gift_log:
                                gift_id = log.get('gift_id')
                                gift_info = gift_list_map.get(str(gift_id), {})
                                gift_point = gift_info.get('point', 0)
                                gift_count = log.get('num', 0)
                                total_point = gift_point * gift_count
                                highlight_class = ""
                                if gift_point >= 500:
                                    if total_point >= 300000: highlight_class = "highlight-300000"
                                    elif total_point >= 100000: highlight_class = "highlight-100000"
                                    elif total_point >= 60000: highlight_class = "highlight-60000"
                                    elif total_point >= 30000: highlight_class = "highlight-30000"
                                    elif total_point >= 10000: highlight_class = "highlight-10000"
                                
                                gift_image = log.get('image', gift_info.get('image', ''))
                                html_content += (
                                    f'<div class="gift-item {highlight_class}">'
                                    f'<div class="gift-header"><small>{datetime.datetime.fromtimestamp(log.get("created_at", 0), JST).strftime("%H:%M:%S")}</small></div>'
                                    f'<div class="gift-info-row"><img src="{gift_image}" class="gift-image" /><span>×{gift_count}</span></div>'
                                    f'<div>{gift_point}pt</div></div>'
                                )
                            html_content += '</div>'
                        else:
                            html_content += '<p style="text-align: center; padding: 12px 0;">ギフト履歴がありません。</p></div>'
                        
                        html_content += '</div>'
                        room_html_list.append(html_content)
                html_container_content = '<div class="container-wrapper">' + ''.join(room_html_list) + '</div>'
                gift_container.markdown(css_style + html_container_content, unsafe_allow_html=True)
            else:
                gift_container.info("選択されたルームに現在配信中のルームはありません。")
            
            st.markdown("<div style='margin-top: 40px;'></div>", unsafe_allow_html=True)
            
            st.subheader("📈 ポイントと順位の比較")
            color_map = {row['ルーム名']: get_rank_color(row['現在の順位']) for index, row in df.iterrows()}
            points_container = st.container()

            with points_container:
                if '現在のポイント' in df.columns:
                    fig_points = px.bar(
                        df, x="ルーム名", y="現在のポイント", title="各ルームの現在のポイント", color="ルーム名",
                        color_discrete_map=color_map, hover_data=["現在の順位", "上位とのポイント差", "下位とのポイント差"],
                        labels={"現在のポイント": "ポイント", "ルーム名": "ルーム名"}
                    )
                    st.plotly_chart(fig_points, use_container_width=True, key="points_chart")
                    fig_points.update_layout(uirevision="const")

                if len(st.session_state.selected_room_names) > 1 and "上位とのポイント差" in df.columns:
                    df['上位とのポイント差'] = pd.to_numeric(df['上位とのポイント差'], errors='coerce')
                    fig_upper_gap = px.bar(
                        df, x="ルーム名", y="上位とのポイント差", title="上位とのポイント差", color="ルーム名",
                        color_discrete_map=color_map, hover_data=["現在の順位", "現在のポイント"],
                        labels={"上位とのポイント差": "ポイント差", "ルーム名": "ルーム名"}
                    )
                    st.plotly_chart(fig_upper_gap, use_container_width=True, key="upper_gap_chart")
                    fig_upper_gap.update_layout(uirevision="const")

                if len(st.session_state.selected_room_names) > 1 and "下位とのポイント差" in df.columns:
                    df['下位とのポイント差'] = pd.to_numeric(df['下位とのポイント差'], errors='coerce')
                    fig_lower_gap = px.bar(
                        df, x="ルーム名", y="下位とのポイント差", title="下位とのポイント差", color="ルーム名",
                        color_discrete_map=color_map, hover_data=["現在の順位", "現在のポイント"],
                        labels={"下位とのポイント差": "ポイント差", "ルーム名": "ルーム名"}
                    )
                    st.plotly_chart(fig_lower_gap, use_container_width=True, key="lower_gap_chart")
                    fig_lower_gap.update_layout(uirevision="const")
                    
            st_autorefresh(interval=10000, limit=None, key="data_refresh")
        
    
if __name__ == "__main__":
    main()