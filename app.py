import streamlit as st
import requests
import pandas as pd
import datetime
import plotly.express as px
import pytz

# Set page configuration
st.set_page_config(
    page_title="SHOWROOM Event Dashboard",
    page_icon="🎤",
    layout="wide",
)

HEADERS = {"User-Agent": "Mozilla/5.0"}
JST = pytz.timezone('Asia/Tokyo')

# -------------------- データ取得関数 --------------------
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
            page_events = data.get('events', []) if isinstance(data, dict) else data
            if not page_events:
                break
            events.extend(page_events)
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
                ranking_list = data.get('ranking') or data.get('event_list') or (data if isinstance(data, list) else [])
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

@st.cache_data(ttl=5)
def get_gift_log(room_id):
    url = f"https://www.showroom-live.com/api/live/gift_log?room_id={room_id}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=5)
        response.raise_for_status()
        return response.json().get('gift_log', [])
    except requests.exceptions.RequestException:
        return []

def get_onlives_rooms():
    onlives = set()
    try:
        url = "https://www.showroom-live.com/api/live/onlives"
        response = requests.get(url, headers=HEADERS, timeout=5)
        response.raise_for_status()
        data = response.json()
        all_lives = []
        if isinstance(data, dict):
            if 'onlives' in data:
                for genre_group in data['onlives']:
                    all_lives.extend(genre_group.get('lives', []))
            for live_type in ['official_lives', 'talent_lives', 'amateur_lives']:
                all_lives.extend(data.get(live_type, []))
        for room in all_lives:
            room_id = room.get('room_id') or room.get('live_info', {}).get('room_id') or room.get('room', {}).get('room_id')
            if room_id:
                try:
                    onlives.add(int(room_id))
                except (ValueError, TypeError):
                    continue
    except requests.exceptions.RequestException:
        pass
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

# -------------------- メイン処理 --------------------
def main():
    st.title("🎤 SHOWROOM Event Dashboard")
    st.write("ライバーとリスナーのための、イベント順位とポイント差をリアルタイムで可視化するツールです。")

    if "room_map_data" not in st.session_state:
        st.session_state.room_map_data = None
    if "selected_event_name" not in st.session_state:
        st.session_state.selected_event_name = None
    if "selected_room_names" not in st.session_state:
        st.session_state.selected_room_names = []

    # --- イベント選択 ---
    events = get_events()
    if not events:
        st.warning("現在開催中のイベントが見つかりません。")
        return

    event_options = {event['event_name']: event for event in events}
    selected_event_name = st.selectbox("イベント名を選択してください:", options=list(event_options.keys()))
    if not selected_event_name:
        st.warning("イベントを選択してください。")
        return

    selected_event_data = event_options[selected_event_name]
    selected_event_key = selected_event_data.get('event_url_key')
    selected_event_id = selected_event_data.get('event_id')

    if st.session_state.selected_event_name != selected_event_name or st.session_state.room_map_data is None:
        st.session_state.room_map_data = get_event_ranking_with_room_id(selected_event_key, selected_event_id)
        st.session_state.selected_event_name = selected_event_name
        st.session_state.selected_room_names = []

    # --- ルーム選択 ---
    st.subheader("比較したいルームを選択")
    room_map = st.session_state.room_map_data
    if not room_map:
        st.warning("参加者情報を取得できません。")
        return
    sorted_rooms = sorted(room_map.items(), key=lambda item: item[1].get('point', 0), reverse=True)
    room_options = [room[0] for room in sorted_rooms]
    selected_room_names_temp = st.multiselect("ルーム選択:", options=room_options, default=st.session_state.selected_room_names)

    if selected_room_names_temp:
        st.session_state.selected_room_names = selected_room_names_temp
    else:
        st.warning("最低1つのルームを選択してください。")
        return

    # --- ダッシュボード表示 ---
    st.header("リアルタイムダッシュボード")
    onlives_rooms = get_onlives_rooms()

    data_to_display = []
    final_remain_time = None

    for room_name in st.session_state.selected_room_names:
        room_id = room_map[room_name]['room_id']
        room_info = get_room_event_info(room_id)
        if not room_info:
            continue
        rank_info = room_info.get('ranking') or room_info.get('event_and_support_info', {}).get('ranking') or room_info.get('event', {}).get('ranking')
        remain_time_sec = room_info.get('remain_time') or room_info.get('event_and_support_info', {}).get('remain_time') or room_info.get('event', {}).get('remain_time')
        if rank_info and 'point' in rank_info and remain_time_sec is not None:
            is_live = int(room_id) in onlives_rooms
            data_to_display.append({
                "ライブ中": "🔴" if is_live else "",
                "ルーム名": room_name,
                "現在の順位": rank_info.get('rank', 'N/A'),
                "現在のポイント": rank_info.get('point', 'N/A'),
            })
            if final_remain_time is None:
                final_remain_time = remain_time_sec

    if data_to_display:
        df = pd.DataFrame(data_to_display)
        st.subheader("🎁 スペシャルギフト履歴")
        gift_placeholder = st.empty()

        room_html_list = []
        for index, row in df.iterrows():
            room_name = row['ルーム名']
            room_id = room_map[room_name]['room_id']
            rank = row['現在の順位']
            rank_color = get_rank_color(rank)

            if int(room_id) in onlives_rooms:
                gift_log = get_gift_log(room_id)
                gift_list_map = get_gift_list(room_id)

                html_content = f"""
                <div class="room-container">
                    <div class="ranking-label" style="background-color: {rank_color};">{rank}位</div>
                    <div class="room-title">{room_name}</div>
                    <div class="gift-list-container">
                """
                if not gift_log:
                    html_content += '<p style="text-align:center; padding:12px 0;">ギフト履歴がありません。</p>'
                else:
                    gift_log.sort(key=lambda x: x.get('created_at',0), reverse=True)
                    for log in gift_log:
                        gift_id = log.get('gift_id')
                        gift_info = gift_list_map.get(str(gift_id), {})
                        gift_point = gift_info.get('point', 0)
                        gift_count = log.get('num', 0)
                        total_point = gift_point * gift_count
                        highlight_class = ""
                        if gift_point >= 500:
                            if total_point >= 300000: highlight_class="highlight-300000"
                            elif total_point >= 100000: highlight_class="highlight-100000"
                            elif total_point >= 60000: highlight_class="highlight-60000"
                            elif total_point >= 30000: highlight_class="highlight-30000"
                            elif total_point >= 10000: highlight_class="highlight-10000"
                        gift_image = log.get('image', gift_info.get('image',''))
                        html_content += (
                            f'<div class="gift-item {highlight_class}">'
                            f'<div class="gift-header"><small>{datetime.datetime.fromtimestamp(log.get("created_at",0), JST).strftime("%H:%M:%S")}</small></div>'
                            f'<div class="gift-info-row"><img src="{gift_image}" class="gift-image"/>'
                            f'<span>×{gift_count}</span></div>'
                            f'<div>{gift_point}pt</div></div>'
                        )
                html_content += '</div></div>'
                room_html_list.append(html_content)
            else:
                room_html_list.append(
                    f'<div class="room-container">'
                    f'<div class="ranking-label" style="background-color: {rank_color};">{rank}位</div>'
                    f'<div class="room-title">{room_name}</div>'
                    f'<p style="text-align:center;">ライブ配信していません。</p>'
                    f'</div>'
                )

        if room_html_list:
            html_container_content = '<div class="container-wrapper">' + ''.join(room_html_list) + '</div>'
            gift_placeholder.markdown(html_container_content, unsafe_allow_html=True)
        else:
            gift_placeholder.info("選択されたルームに現在ライブ配信中のルームはありません。")
    else:
        st.info("選択されたルームに表示可能なデータがありません。")

if __name__ == "__main__":
    main()
