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
        except requests.exceptions.RequestException as e:
            st.error(f"イベント一覧の取得中にエラーが発生しました: {e}")
            break
    return events

@st.cache_data(ttl=60)
def get_live_info(room_id):
    """Fetches live information for a specific room."""
    url = f"https://www.showroom-live.com/api/live/live_info?room_id={room_id}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}

def fetch_gift_log(room_id):
    """Fetches gift log for a specific room."""
    url = f"https://www.room-live.com/api/live/gift_log?room_id={room_id}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}
        
@st.cache_data(ttl=3600)
def get_gift_list(room_id):
    """Fetches a list of gifts for a specific room."""
    url = f"https://www.showroom-live.com/api/gift/gift_list?room_id={room_id}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}

def get_event_info(event_id):
    """Fetches event information."""
    url = f"https://www.showroom-live.com/api/event/event_info?event_id={event_id}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}
    
def get_ranking_info(event_id, page=1):
    """Fetches event ranking."""
    url = f"https://www.showroom-live.com/api/event/ranking?event_id={event_id}&page={page}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}

# -----------------------
# メイン関数
# -----------------------

def main():
    st.title("SHOWROOM Event Dashboard")
    st.sidebar.title("設定")

    # セッションステートの初期化
    if 'event_select_key' not in st.session_state:
        st.session_state.event_select_key = 0
    if 'room_select_key' not in st.session_state:
        st.session_state.room_select_key = 0
    if 'selected_room_names' not in st.session_state:
        st.session_state.selected_room_names = []

    # イベントリストの取得と選択
    events = get_events()
    event_list = {event['event_name']: event for event in events}
    
    selected_event_name = st.sidebar.selectbox("イベントを選択", [""] + list(event_list.keys()), index=0, key=f"event_select_{st.session_state.event_select_key}")

    event_id = None
    if selected_event_name:
        event_id = event_list[selected_event_name]['event_id']

    # ルームリストの取得と選択
    room_list = []
    if event_id:
        ranking_data = get_ranking_info(event_id)
        if ranking_data and 'ranking' in ranking_data:
            room_list = [room for room in ranking_data['ranking'] if room.get('live_status', 0) == 1]
    
    room_names = [room['room_name'] for room in room_list]
    
    st.sidebar.markdown("### ルーム選択")
    # 選択済みのルームをサイドバーで表示し、並び替え可能にする
    if st.session_state.selected_room_names:
        st.session_state.selected_room_names = st.sidebar.multiselect(
            "表示するルームを選択 (複数選択可)",
            options=room_names,
            default=st.session_state.selected_room_names,
            key=f"room_select_{st.session_state.room_select_key}"
        )
    else:
        st.session_state.selected_room_names = st.sidebar.multiselect(
            "表示するルームを選択 (複数選択可)",
            options=room_names,
            key=f"room_select_{st.session_state.room_select_key}"
        )

    # ページのリロードボタン
    if st.sidebar.button("再読み込み"):
        st.session_state.event_select_key += 1
        st.session_state.room_select_key += 1
        st.rerun()

    if not st.session_state.selected_room_names:
        st.info("左のサイドバーからイベントとルームを選択してください。")
        return

    st.header("リアルタイム情報")

    # リアルタイム更新のプレースホルダー
    real_time_placeholder = st.empty()
    time_placeholder = st.empty()
    st.markdown("---")

    final_remain_time = None
    if event_id:
        event_info = get_event_info(event_id)
        if event_info and 'end_time' in event_info:
            end_time = event_info['end_time']
            current_time = time.time()
            final_remain_time = max(0, end_time - current_time)

    # ループしてリアルタイム情報を更新
    while True:
        with real_time_placeholder.container():
            # 💡修正: st.columnsでルームを横並びに表示
            cols = st.columns(len(st.session_state.selected_room_names))
            
            # 各ルームの情報を取得し表示
            for i, room_name in enumerate(st.session_state.selected_room_names):
                room = next((r for r in room_list if r['room_name'] == room_name), None)
                if not room:
                    continue

                room_id = room['room_id']
                live_info = get_live_info(room_id)
                
                with cols[i]:
                    st.subheader(room_name)
                    if not live_info.get("is_live"):
                        st.info("ライブ配信していません。")
                        continue

                    # ポイントと順位の表示
                    st.metric(label="現在の順位", value=f"{room['rank']} 位")
                    st.metric(label="現在のポイント", value=f"{room['point']} pt")

                    st.markdown("---")

                    st.subheader("ギフト履歴")
                    
                    gift_log_data = fetch_gift_log(room_id)
                    gift_list_data = get_gift_list(room_id)
                    gift_list_map = {gift.get('gift_id'): gift for gift in gift_list_data.get('gift_list', [])} if gift_list_data else {}
                    
                    if gift_log_data and gift_log_data.get('gift_log'):
                        # 💡修正: ユーザー要望のHTML構造に合わせた表示
                        for log in gift_log_data['gift_log']:
                            gift_id = log.get('gift_id')
                            gift_info = gift_list_map.get(gift_id, {})
                            
                            gift_time = datetime.datetime.fromtimestamp(log.get('created_at', 0), JST).strftime("%H:%M:%S")
                            gift_image = gift_info.get('image', '')
                            gift_count = log.get('num', 0)
                            gift_name = gift_info.get('name', '')
                            
                            st.markdown(f"""
                                <div class="gift-item" style="display: flex; align-items: center; gap: 8px;">
                                    <small>{gift_time}</small>
                                    <img src="{gift_image}" class="gift-image" style="width: 30px; height: 30px; border-radius: 5px;" />
                                    <span class="gift-count">×{gift_count}</span>
                                    <small class="gift-name">{gift_name}</small>
                                </div>
                            """, unsafe_allow_html=True)
                    else:
                        st.info("ギフト履歴がありません。")

        if final_remain_time is not None:
            remain_time_readable = str(datetime.timedelta(seconds=final_remain_time))
            time_placeholder.markdown(f"<span style='color: red;'>**イベント終了まで残り: {remain_time_readable}**</span>", unsafe_allow_html=True)
        else:
            time_placeholder.info("残り時間情報を取得できませんでした。")

        time.sleep(5)
        st.rerun()

if __name__ == "__main__":
    main()