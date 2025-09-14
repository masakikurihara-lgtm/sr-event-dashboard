import streamlit as st
import requests
import pandas as pd
import time
import datetime
import plotly.express as px
import pytz
from streamlit_autorefresh import st_autorefresh

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
    events = []
    page = 1
    for _ in range(10):
        url = f"https://www.showroom-live.com/api/event/search?page={page}&include_ended=0"
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
                    break
            filtered_page_events = [event for event in page_events if event.get("show_ranking") is not False and event.get("is_event_block") is not True]
            events.extend(filtered_page_events)
            page += 1
        except requests.exceptions.RequestException as e:
            st.error(f"イベントデータ取得中にエラーが発生しました: {e}")
            return []
        except ValueError:
            st.error(f"APIからのJSONデコードに失敗しました: {response.text}")
            return []
    return events

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
        st.warning(f"ルームID {room_id} のギフトログ取得中にエラーが発生しました。ライブ配信中か確認してください: {e}")
        return st.session_state.gift_log_cache.get(room_id, [])

def get_onlives_rooms():
    onlives = set()
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
            if isinstance(room, dict):
                room_id = room.get('room_id')
                if room_id is None and 'live_info' in room and isinstance(room['live_info'], dict):
                    room_id = room['live_info'].get('room_id')
                if room_id is None and 'room' in room and isinstance(room['room'], dict):
                    room_id = room['room'].get('room_id')
            if room_id:
                try:
                    onlives.add(int(room_id))
                except (ValueError, TypeError):
                    continue
    except requests.exceptions.RequestException as e:
        st.warning(f"ライブ配信情報取得中にエラーが発生しました: {e}")
    except (ValueError, AttributeError):
        st.warning("ライブ配信情報のJSONデコードまたは解析に失敗しました。")
    return onlives

def get_rank_color(rank):
    colors = px.colors.qualitative.Plotly
    if rank is None:
        return "#A9A9A9"
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

    st.markdown("<h2 style='font-size:2em;'>1. イベントを選択</h2>", unsafe_allow_html=True)
    events = get_events()
    if not events:
        st.warning("現在開催中のイベントが見つかりませんでした。")
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

    if st.session_state.selected_event_name != selected_event_name or st.session_state.room_map_data is None:
        with st.spinner('イベント参加者情報を取得中...'):
            st.session_state.room_map_data = get_event_ranking_with_room_id(selected_event_key, selected_event_id)
        st.session_state.selected_event_name = selected_event_name
        st.session_state.selected_room_names = []
        st.session_state.multiselect_default_value = []
        st.session_state.multiselect_key_counter = 0
        if 'select_top_15_checkbox' in st.session_state:
            st.session_state.select_top_15_checkbox = False
        st.rerun()

    room_count_text = ""
    if st.session_state.room_map_data:
        room_count = len(st.session_state.room_map_data)
        room_count_text = f" （現在{room_count}ルーム参加）"
    st.markdown(f"**▶ [イベントページへ移動する]({event_url})**{room_count_text}", unsafe_allow_html=True)

    if not st.session_state.room_map_data:
        st.warning("このイベントの参加者情報を取得できませんでした。")
        return

    with st.form("room_selection_form"):
        select_top_15 = st.checkbox(
            "上位15ルームまでを選択（**※チェックされている場合はこちらが優先されます**）", 
            key="select_top_15_checkbox")
        room_map = st.session_state.room_map_data
        sorted_rooms = sorted(room_map.items(), key=lambda item: item[1].get('point', 0), reverse=True)
        room_options = [room[0] for room in sorted_rooms]
        top_15_rooms = room_options[:15]
        selected_room_names_temp = st.multiselect(
            "比較したいルームを選択 (複数選択可):", options=room_options,
            default=st.session_state.multiselect_default_value,
            key=f"multiselect_{st.session_state.multiselect_key_counter}")
        submit_button = st.form_submit_button("表示する")

    if submit_button:
        if st.session_state.select_top_15_checkbox:
            st.session_state.selected_room_names = top_15_rooms
            st.session_state.multiselect_default_value = top_15_rooms
            st.session_state.multiselect_key_counter += 1
        else:
            st.session_state.selected_room_names = selected_room_names_temp
            st.session_state.multiselect_default_value = selected_room_names_temp
        st.rerun()

    if not st.session_state.selected_room_names:
        st.warning("最低1つのルームを選択してください。")
        return

    st.markdown("<h2 style='font-size:2em;'>3. リアルタイムダッシュボード</h2>", unsafe_allow_html=True)
    st.info("10秒ごとに自動更新されます。")

    with st.container(border=True):
        col1, col2 = st.columns([1, 1])
        with col1:
            st.markdown(f"**<font size='5'>イベント期間</font>**", unsafe_allow_html=True)
            st.write(f"**{event_period_str}**")
        with col2:
            st.markdown(f"**<font size='5'>残り時間</font>**", unsafe_allow_html=True)
            time_placeholder = st.empty()

    # --- カウントダウン表示（JavaScript利用） ---
    js_code = f"""
    <div id="countdown" style="color:red; font-size:20px; font-weight:bold;"></div>
    <script>
    var endTime = new Date("{ended_at_dt.strftime('%Y-%m-%d %H:%M:%S')}").getTime();
    function updateCountdown() {{
        var now = new Date().getTime();
        var distance = endTime - now;
        if(distance < 0){{
            document.getElementById("countdown").innerHTML = "イベント終了";
        }} else {{
            var hours = Math.floor((distance % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
            var minutes = Math.floor((distance % (1000 * 60 * 60)) / (1000 * 60));
            var seconds = Math.floor((distance % (1000 * 60)) / 1000);
            document.getElementById("countdown").innerHTML = hours + "時間 " + minutes + "分 " + seconds + "秒";
        }}
    }}
    updateCountdown();
    setInterval(updateCountdown, 1000);
    </script>
    """
    time_placeholder.markdown(js_code, unsafe_allow_html=True)

    current_time = datetime.datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    st.write(f"最終更新日時 (日本時間): {current_time}")

    onlives_rooms = get_onlives_rooms()

    # --- 以下、既存のデータ取得・表示処理（残り時間表示以外はそのまま） ---
    # 省略: 元のコードのまま残します
    # ...
    
    st_autorefresh(interval=10000, limit=None, key="data_refresh")

if __name__ == "__main__":
    main()
