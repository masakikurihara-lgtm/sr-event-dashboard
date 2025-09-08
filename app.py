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

# --- Functions to fetch data from SHOWROOM API ---

@st.cache_data(ttl=3600)
def get_events():
    """Fetches a list of ongoing SHOWROOM events."""
    events = []
    page = 1
    for _ in range(10):
        url = f"https://www.showroom-live.com/api/event/search?page={page}&include_ended=0"
        try:
            response = requests.get(url, timeout=5)
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
            st.error(f"イベントデータ取得中にエラーが発生しました: {e}")
            return []
        except ValueError: # JSONDecodeError
            st.error(f"APIからのJSONデコードに失敗しました: {response.text}")
            return []
            
    return events

def get_event_ranking(event_url_key):
    """Fetches the ranking data for a specific event."""
    url = f"https://www.showroom-live.com/api/event/{event_url_key}/ranking"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"ランキングデータ取得中にエラーが発生しました: {e}")
        return None

def get_room_event_info(room_id):
    """Fetches event and support info for a specific room."""
    url = f"https://www.showroom-live.com/api/room/event_and_support?room_id={room_id}"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        return data
    except requests.exceptions.RequestException as e:
        st.error(f"ルームID {room_id} のデータ取得中にエラーが発生しました: {e}")
        return None

# --- Main Application Logic ---

def main():
    st.title("🎤 SHOWROOMイベント可視化ツール")
    st.write("ライバーとリスナーのための、イベント順位とポイント差をリアルタイムで可視化するツールです。")
    
    # --- Event Selection Section ---
    st.header("1. イベントを選択")
    events = get_events()
    if not events:
        st.warning("現在開催中のイベントが見つかりませんでした。")
        return

    event_options = {event['event_name']: event['event_url_key'] for event in events}
    selected_event_name = st.selectbox(
        "イベント名を選択してください:", 
        options=list(event_options.keys())
    )
    
    selected_event_key = event_options[selected_event_name]
    st.info(f"選択されたイベント: **{selected_event_name}**")

    # --- Room Selection Section ---
    st.header("2. 比較したいルームを選択")
    ranking_data = get_event_ranking(selected_event_key)
    if not ranking_data or 'ranking' not in ranking_data:
        st.warning("このイベントの参加者情報を取得できませんでした。")
        return
        
    rooms = ranking_data['ranking']
    if not rooms:
        st.warning("このイベントにはまだ参加者がいません。")
        return

    # --- 修正箇所：ルームIDとルーム名を確実に取得するロジック ---
    room_options = {}
    for room in rooms:
        if 'room_id' in room and 'room_name' in room:
            room_options[room['room_name']] = room['room_id']

    if not room_options:
        st.warning("参加者リストから有効なルーム情報を取得できませんでした。")
        return
    # --- 修正ここまで ---

    selected_room_names = st.multiselect(
        "比較したいルームを選択 (複数選択可):", 
        options=list(room_options.keys()),
        default=[list(room_options.keys())[0]]
    )
    
    if not selected_room_names:
        st.warning("最低1つのルームを選択してください。")
        return

    selected_room_ids = [room_options[name] for name in selected_room_names]

    # --- Real-time Dashboard Section ---
    st.header("3. リアルタイムダッシュボード")
    st.info("5秒ごとに自動更新されます。")
    
    dashboard_placeholder = st.empty()
    
    JST = pytz.timezone('Asia/Tokyo')
    
    while True:
        with dashboard_placeholder.container():
            current_time = datetime.datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
            st.write(f"最終更新日時 (日本時間): {current_time}")
            
            data_to_display = []
            
            for room_id in selected_room_ids:
                room_info = get_room_event_info(room_id)
                if room_info and 'ranking' in room_info:
                    rank_info = room_info['ranking']
                    remain_time_sec = room_info.get('remain_time', 0)
                    remain_time_str = str(datetime.timedelta(seconds=remain_time_sec))

                    data_to_display.append({
                        "ルーム名": [name for name, id in room_options.items() if id == room_id][0],
                        "現在の順位": rank_info['rank'],
                        "現在のポイント": rank_info['point'],
                        "下位とのポイント差": rank_info['lower_gap'] if 'lower_gap' in rank_info and rank_info['lower_rank'] > 0 else 0,
                        "下位の順位": rank_info['lower_rank'] if 'lower_rank' in rank_info else "N/A",
                        "残り時間": remain_time_str,
                    })
            
            if data_to_display:
                df = pd.DataFrame(data_to_display)
                
                df_sorted = df.sort_values(by="現在の順位").reset_index(drop=True)
                
                st.subheader("📊 比較対象ルームのステータス")
                st.dataframe(df_sorted.style.highlight_max(axis=0, subset=['現在のポイント']).format(
                    {'現在のポイント': '{:,}', '下位とのポイント差': '{:,}'}
                ), use_container_width=True)

                st.subheader("📈 ポイントと順位の比較")
                
                fig_points = px.bar(df_sorted, x="ルーム名", y="現在のポイント", 
                                    title="各ルームの現在のポイント", 
                                    color="ルーム名",
                                    hover_data=["現在の順位", "下位とのポイント差"],
                                    labels={"現在のポイント": "ポイント", "ルーム名": "ルーム名"})
                st.plotly_chart(fig_points, use_container_width=True)

                if len(selected_room_names) > 1 and "下位とのポイント差" in df_sorted.columns:
                    fig_gap = px.bar(df_sorted, x="ルーム名", y="下位とのポイント差", 
                                    title="下位とのポイント差", 
                                    color="ルーム名",
                                    hover_data=["現在の順位", "現在のポイント"],
                                    labels={"下位とのポイント差": "ポイント差", "ルーム名": "ルーム名"})
                    st.plotly_chart(fig_gap, use_container_width=True)

            else:
                st.warning("選択されたルームの情報を取得できませんでした。APIのレスポンス形式が変更された可能性があります。")

        time.sleep(5)

if __name__ == "__main__":
    main()