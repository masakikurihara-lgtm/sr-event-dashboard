import streamlit as st
import requests
import pandas as pd
import time
import datetime
import plotly.express as px
import pytz

# Set page configuration
st.set_page_config(
    page_title="SHOWROOM Event Dashboard",
    page_icon="🎤",
    layout="wide",
)

# -----------------------
# ヘルパー関数
# -----------------------
HEADERS = {"User-Agent": "Mozilla/5.0"}
JST = pytz.timezone('Asia/Tokyo')

@st.cache_data(ttl=3600)
def get_events():
    """Fetches a list of ongoing SHOWROOM events."""
    events = []
    page = 1
    # 念のため最大10ページまで取得
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
            
            events.extend(page_events)
            page += 1
            if len(page_events) < 50: # 1ページあたりの最大件数に満たない場合は終了
                break

        except requests.RequestException as e:
            st.error(f"イベント情報の取得中にエラーが発生しました: {e}")
            break
    
    return events

@st.cache_data(ttl=60)
def get_event_rooms(event_id):
    """Fetches the list of rooms participating in a specific event."""
    url = f"https://www.showroom-live.com/api/event/room_list?event_id={event_id}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=5)
        response.raise_for_status()
        data = response.json()
        rooms = data.get('room_list', [])
        return rooms
    except requests.RequestException:
        return []

@st.cache_data(ttl=1)
def get_onlives_rooms(selected_room_ids):
    """Fetches the list of rooms that are currently on live."""
    url = "https://www.showroom-live.com/api/live/onlives"
    try:
        response = requests.get(url, headers=HEADERS, timeout=5)
        response.raise_for_status()
        onlives = response.json().get('onlives', {})
        onlives_rooms_data = set()
        for genre, rooms in onlives.items():
            for room in rooms:
                onlives_rooms_data.add(room.get('room_id'))
        
        return onlives_rooms_data
    except requests.RequestException as e:
        return set()

@st.cache_data(ttl=1)
def get_gift_log(room_id):
    """Fetches the gift log for a specific room."""
    url = f"https://www.showroom-live.com/api/live/gift_log?room_id={room_id}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=5)
        response.raise_for_status()
        return response.json().get('gift_log', [])
    except requests.RequestException as e:
        return []

@st.cache_data(ttl=3600)
def get_gift_list(room_id):
    """Fetches the list of gifts for a specific room."""
    url = f"https://www.showroom-live.com/api/live/gift_list?room_id={room_id}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=5)
        response.raise_for_status()
        gift_data = response.json().get('gift_list', [])
        gift_list_map = {item.get('gift_id'): item for item in gift_data}
        return gift_list_map
    except requests.RequestException as e:
        return {}

# -----------------------
# メインアプリケーション
# -----------------------

def main():
    st.title("SHOWROOM Events Dashboard")

    # セッションステートの初期化
    if 'selected_event_id' not in st.session_state:
        st.session_state.selected_event_id = None
    if 'selected_room_names' not in st.session_state:
        st.session_state.selected_room_names = []
    if 'room_map_data' not in st.session_state:
        st.session_state.room_map_data = {}

    # イベント選択
    events = get_events()
    event_names = {event['event_id']: event['event_name'] for event in events}
    
    selected_event_name = st.selectbox(
        "イベントを選択してください",
        list(event_names.values()),
        index=0 if events else None,
        key="event_select_box"
    )

    if selected_event_name:
        selected_event_id = [k for k, v in event_names.items() if v == selected_event_name][0]
        st.session_state.selected_event_id = selected_event_id

        # 参加ルーム選択
        rooms_in_event = get_event_rooms(st.session_state.selected_event_id)
        st.session_state.room_map_data = {room['room_name']: room for room in rooms_in_event}
        room_names = [room['room_name'] for room in rooms_in_event]
        
        st.session_state.selected_room_names = st.multiselect(
            "ライブ配信情報を表示したいルームを選択してください",
            room_names,
            default=st.session_state.selected_room_names
        )

    # -----------------------
    # ライブ配信情報表示セクション
    # -----------------------

    st.header("ライブ配信状況")
    onlives_rooms = get_onlives_rooms(st.session_state.selected_room_names)
    
    # st.empty()を使用して、このセクションの内容を上書きするプレースホルダーを作成
    placeholder = st.empty()
    time_placeholder = st.empty()
    
    while True:
        with placeholder.container():
            live_rooms_data = []
            if st.session_state.selected_room_names and st.session_state.room_map_data:
                for room_name in st.session_state.selected_room_names:
                    if room_name in st.session_state.room_map_data:
                        room_id = st.session_state.room_map_data[room_name]['room_id']
                        if int(room_id) in onlives_rooms:
                            live_rooms_data.append({
                                "room_name": room_name,
                                "room_id": room_id,
                                "rank": st.session_state.room_map_data[room_name].get('rank', float('inf')) 
                            })
                live_rooms_data.sort(key=lambda x: x['rank'])
            
            if live_rooms_data:
                cols = st.columns(len(live_rooms_data))
                for i, room_data in enumerate(live_rooms_data):
                    with cols[i]:
                        room_name = room_data['room_name']
                        room_id = room_data['room_id']
                        rank = room_data.get('rank', 'N/A')
                        st.markdown(f"#### {rank}位: {room_name}")
                        st.image(f"https://www.showroom-live.com/image/room/thumbnail/s__{room_id}.jpeg", use_column_width=True)
                        st.write(f"ルームID: {room_id}")

            else:
                st.info("選択されたルームに現在ライブ配信中のルームはありません。")
                
            # ランキング更新時間の表示
            now_time = datetime.datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
            st.markdown(f"**最終更新時刻: {now_time}**", unsafe_allow_html=True)
            
            # 残り時間の取得と表示
            final_remain_time = None
            if st.session_state.selected_event_id:
                for event in events:
                    if event['event_id'] == st.session_state.selected_event_id:
                        final_remain_time = event.get('remain_time', None)
                        break
        
        # --- スペシャルギフト履歴表示セクション ---
        
        # コンテナのプレースホルダーを定義 (変更なし)
        gift_history_placeholder = st.empty()

        live_rooms_data = []
        if st.session_state.selected_room_names and st.session_state.room_map_data:
            for room_name in st.session_state.selected_room_names:
                if room_name in st.session_state.room_map_data:
                    room_id = st.session_state.room_map_data[room_name]['room_id']
                    if int(room_id) in onlives_rooms:
                        live_rooms_data.append({
                            "room_name": room_name,
                            "room_id": room_id,
                            "rank": st.session_state.room_map_data[room_name].get('rank', float('inf')) 
                        })
            live_rooms_data.sort(key=lambda x: x['rank'])
            
        col_count = len(live_rooms_data)
        
        # 修正: 全ての表示内容をこのコンテナ内に移動
        with gift_history_placeholder.container():
            # 修正: ここにサブヘッダーとスタイルを移動させます
            st.subheader("🎁 スペシャルギフト履歴")
            st.markdown("""
                <style>
                .gift-list-container {
                    border: 1px solid #ddd;
                    border-radius: 5px;
                    padding: 10px;
                    height: 400px;
                    overflow-y: scroll;
                    width: 100%;
                }
                .gift-item {
                    display: flex;
                    flex-direction: column;
                    padding: 8px 0;
                    border-bottom: 1px solid #eee;
                    gap: 4px;
                }
                .gift-item:last-child {
                    border-bottom: none;
                }
                .gift-header {
                    font-weight: bold;
                }
                .gift-info-row {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    flex-wrap: wrap;
                }
                .gift-image {
                    width: 30px;
                    height: 30px;
                    border-radius: 5px;
                    object-fit: contain;
                }
                </style>
            """, unsafe_allow_html=True)
            
            if col_count > 0:
                columns = st.columns(col_count, gap="small")
    
                for i, room_data in enumerate(live_rooms_data):
                    with columns[i]:
                        room_name = room_data['room_name']
                        room_id = room_data['room_id']
                        rank = room_data.get('rank', 'N/A')
                        
                        st.markdown(f"<h4 style='text-align: center;'>{rank}位：{room_name}</h4>", unsafe_allow_html=True)
                        
                        if int(room_id) in onlives_rooms:
                            gift_list_map = get_gift_list(room_id)
                            gift_log = get_gift_log(room_id)
                            
                            if gift_log:
                                gift_log.sort(key=lambda x: x.get('created_at', 0), reverse=True)
    
                                gift_list_html = '<div class="gift-list-container">'
                                for log in gift_log:
                                    gift_id = log.get('gift_id')
                                    gift_info = gift_list_map.get(gift_id, {})
                                    
                                    gift_time = datetime.datetime.fromtimestamp(log.get('created_at', 0), JST).strftime("%H:%M:%S")
                                    gift_image = log.get('image', '')
                                    gift_count = log.get('num', 0)
                                    
                                    gift_list_html += '<div class="gift-item">'
                                    gift_list_html += '<div class="gift-header">'
                                    gift_list_html += f'<small>{gift_time}</small>'
                                    gift_list_html += '</div>'
                                    gift_list_html += '<div class="gift-info-row">'
                                    gift_list_html += f'<img src="{gift_image}" class="gift-image" />'
                                    gift_list_html += f'<span>×{gift_count}</span>'
                                    gift_list_html += '</div>'
                                    gift_list_html += '</div>'
    
                                gift_list_html += '</div>'
                                st.markdown(gift_list_html, unsafe_allow_html=True)
                            else:
                                st.info("ギフト履歴がありません。")
                        else:
                            st.info("ライブ配信していません。")
            else:
                st.info("選択されたルームに現在ライブ配信中のルームはありません。")
        
        if final_remain_time is not None:
            remain_time_readable = str(datetime.timedelta(seconds=final_remain_time))
            time_placeholder.markdown(f"<span style='color: red;'>**{remain_time_readable}**</span>", unsafe_allow_html=True)
        else:
            time_placeholder.info("残り時間情報を取得できませんでした。")
    
    time.sleep(5)
    st.rerun()

if __name__ == "__main__":
    main()