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
            st.error(f"イベントデータ取得中にエラーが発生しました: {e}")
            return []
        except ValueError:
            st.error(f"APIからのJSONデコードに失敗しました: {response.text}")
            return []
            
    return events

# ランキングAPIの候補を定義
RANKING_API_CANDIDATES = [
    "https://www.showroom-live.com/api/event/{event_url_key}/ranking?page={page}",
    "https://www.showroom-live.com/api/event/ranking?event_id={event_id}&page={page}",
]

@st.cache_data(ttl=300)
def get_event_ranking_with_room_id(event_url_key, event_id, max_pages=10):
    """
    Fetches ranking data, including room_id, by trying multiple API endpoints.
    Returns a dictionary of {room_name: {room_id, rank, point, ...}}
    """
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
    """Fetches event and support info for a specific room."""
    url = f"https://www.showroom-live.com/api/room/event_and_support?room_id={room_id}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=5)
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
    
    # セッションステートの初期化
    if "room_map_data" not in st.session_state:
        st.session_state.room_map_data = None
    if "selected_event_name" not in st.session_state:
        st.session_state.selected_event_name = None
    if "selected_room_names" not in st.session_state:
        st.session_state.selected_room_names = []

    # --- Event Selection Section ---
    st.header("1. イベントを選択")
    
    events = get_events()
    if not events:
        st.warning("現在開催中のイベントが見つかりませんでした。")
        return

    event_options = {event['event_name']: event for event in events}
    selected_event_name = st.selectbox(
        "イベント名を選択してください:", 
        options=list(event_options.keys()),
        key="event_selector"
    )
    
    if not selected_event_name:
        st.warning("イベントを選択してください。")
        return

    selected_event_data = event_options.get(selected_event_name)

    # イベント期間の表示とURLリンク
    event_url = f"https://www.showroom-live.com/event/{selected_event_data.get('event_url_key')}"
    started_at_dt = datetime.datetime.fromtimestamp(selected_event_data.get('started_at'), JST)
    ended_at_dt = datetime.datetime.fromtimestamp(selected_event_data.get('ended_at'), JST)
    event_period_str = f"{started_at_dt.strftime('%Y/%m/%d %H:%M')} - {ended_at_dt.strftime('%Y/%m/%d %H:%M')}"
    
    st.info(f"選択されたイベント: **{selected_event_name}**")
    st.markdown(f"**[イベントページへ移動する]({event_url})**", unsafe_allow_html=True)

    # セッションステートのリセット
    if st.session_state.selected_event_name != selected_event_name:
        st.session_state.selected_event_name = selected_event_name
        st.session_state.room_map_data = None
        st.session_state.selected_room_names = []
        st.rerun()

    if not selected_event_data:
        st.error(f"選択されたイベント '{selected_event_name}' の詳細情報が見つかりませんでした。別のイベントを選択してください。")
        return

    selected_event_key = selected_event_data.get('event_url_key', '')
    selected_event_id = selected_event_data.get('event_id')
    
    # --- Room Selection Section ---
    st.header("2. 比較したいルームを選択")
    
    if st.session_state.room_map_data is None:
        with st.spinner('イベント参加者情報を取得中...'):
            st.session_state.room_map_data = get_event_ranking_with_room_id(selected_event_key, selected_event_id)

    if not st.session_state.room_map_data:
        st.warning("このイベントの参加者情報を取得できませんでした。")
        return
    
    # フォームを使ってプルダウンが閉じないようにする
    with st.form("room_selection_form"):
        st.session_state.selected_room_names_temp = st.multiselect(
            "比較したいルームを選択 (複数選択可):", 
            options=list(st.session_state.room_map_data.keys()),
            default=st.session_state.selected_room_names
        )
        submit_button = st.form_submit_button("表示する")

    if submit_button:
        st.session_state.selected_room_names = st.session_state.selected_room_names_temp
        st.rerun()

    if not st.session_state.selected_room_names:
        st.warning("最低1つのルームを選択してください。")
        return

    # --- Real-time Dashboard Section ---
    st.header("3. リアルタイムダッシュボード")
    
    # 残り時間とイベント期間の表示
    col1, col2 = st.columns([1, 2])
    
    current_time = datetime.datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    st.write(f"最終更新日時 (日本時間): {current_time}")

    selected_room_ids = []
    data_to_display = []
    all_info_found = True
    
    for room_name in st.session_state.selected_room_names:
        try:
            room_id = st.session_state.room_map_data[room_name]['room_id']
            selected_room_ids.append(room_id)
            room_info = get_room_event_info(room_id)
        
            if not isinstance(room_info, dict):
                all_info_found = False
                continue
        
            rank_info = None
            remain_time_sec = None

            if 'ranking' in room_info and isinstance(room_info['ranking'], dict):
                rank_info = room_info['ranking']
                remain_time_sec = room_info.get('remain_time')
            elif 'event_and_support_info' in room_info and isinstance(room_info['event_and_support_info'], dict):
                event_info = room_info['event_and_support_info']
                if 'ranking' in event_info and isinstance(event_info['ranking'], dict):
                    rank_info = event_info['ranking']
                    remain_time_sec = event_info.get('remain_time')
            elif 'event' in room_info and isinstance(room_info['event'], dict):
                event_data = room_info['event']
                if 'ranking' in event_data and isinstance(event_data['ranking'], dict):
                    rank_info = event_data['ranking']
                    remain_time_sec = event_data.get('remain_time')

            if rank_info and remain_time_sec is not None:
                remain_time_str = str(datetime.timedelta(seconds=remain_time_sec))
                
                # ルーム名にURLリンクを付加
                room_url = f"https://www.showroom-live.com/room/{room_id}"
                room_name_link = f"[{room_name}]({room_url})"

                data_to_display.append({
                    "ルーム名": room_name_link,
                    "現在の順位": rank_info.get('rank', 'N/A'),
                    "現在のポイント": rank_info.get('point', 'N/A'),
                    "下位とのポイント差": rank_info.get('lower_gap', 'N/A') if rank_info.get('lower_rank', 0) > 0 else 0,
                    "下位の順位": rank_info.get('lower_rank', 'N/A')
                })
                
                # 残り時間を取得（複数ルームで同じ値を表示するため）
                if remain_time_sec is not None:
                    final_remain_time = remain_time_sec

            else:
                all_info_found = False
                st.warning(f"ルームID {room_id} のランキング情報が見つかりませんでした。")
        except Exception as e:
            all_info_found = False
            st.error(f"データ処理中にエラーが発生しました（ルーム名: {room_name}）。エラー: {e}")
    
    with col1:
        st.subheader("イベント期間")
        st.markdown(f"**{event_period_str}**")

    with col2:
        st.subheader("残り時間")
        if 'final_remain_time' in locals():
            remain_time_readable = str(datetime.timedelta(seconds=final_remain_time))
            st.metric(label="イベント終了まで", value=remain_time_readable)

    if data_to_display:
        df = pd.DataFrame(data_to_display)
        
        # DataFrameのリンクを有効化
        df['ルーム名'] = df['ルーム名'].apply(lambda x: x.replace('[', '「').replace(']', '」') if not x.startswith('<') else x)
        df.columns = ["ルーム名", "現在の順位", "現在のポイント", "下位とのポイント差", "下位の順位"]
        
        st.subheader("📊 比較対象ルームのステータス")
        st.dataframe(df.style.highlight_max(axis=0, subset=['現在のポイント']).format(
            {'現在のポイント': '{:,}', '下位とのポイント差': '{:,}'}
        ), use_container_width=True, hide_index=True)

        st.subheader("📈 ポイントと順位の比較")
        
        df_sorted = df.copy()
        df_sorted['現在のポイント'] = pd.to_numeric(df_sorted['現在のポイント'], errors='coerce')
        fig_points = px.bar(df_sorted, x="ルーム名", y="現在のポイント", 
                            title="各ルームの現在のポイント", 
                            color="ルーム名",
                            hover_data=["現在の順位", "下位とのポイント差"],
                            labels={"現在のポイント": "ポイント", "ルーム名": "ルーム名"})
        st.plotly_chart(fig_points, use_container_width=True)

        if len(st.session_state.selected_room_names) > 1 and "下位とのポイント差" in df_sorted.columns:
            df_sorted['下位とのポイント差'] = pd.to_numeric(df_sorted['下位とのポイント差'], errors='coerce')
            fig_gap = px.bar(df_sorted, x="ルーム名", y="下位とのポイント差", 
                            title="下位とのポイント差", 
                            color="ルーム名",
                            hover_data=["現在の順位", "現在のポイント"],
                            labels={"下位とのポイント差": "ポイント差", "ルーム名": "ルーム名"})
            st.plotly_chart(fig_gap, use_container_width=True)

    if not all_info_found and st.session_state.selected_room_names:
        st.warning("一部のルーム情報が取得できませんでした。")
    elif not data_to_display and st.session_state.selected_room_names:
        st.warning("選択されたルームの情報を取得できませんでした。")

    time.sleep(5)
    st.rerun()

if __name__ == "__main__":
    main()