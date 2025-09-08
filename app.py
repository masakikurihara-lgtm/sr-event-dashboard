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
    st.info("複数のAPIエンドポイントを試行してランキングデータを取得します。")
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
                st.success(f"ルームIDを含むランキングデータ取得に成功しました。")
                all_ranking_data = temp_ranking_data
                break
            
        except requests.exceptions.RequestException:
            continue

    if not all_ranking_data:
        st.error("どのAPIからもルームIDを含むランキングデータを取得できませんでした。")
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
    
    st.write("---")
    st.subheader("デバッグ情報")
    if room_map:
        st.success(f"有効なルームIDを含むルーム情報が {len(room_map)} 件見つかりました。")
        st.json(list(room_map.items())[0] if room_map else {})
    else:
        st.error("有効なルームIDを含むルーム情報が見つかりませんでした。")
    st.write("---")

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
    
    def on_event_change():
        st.session_state.room_map_data = None
        st.session_state.selected_event_name = st.session_state.event_selector
        st.session_state.selected_room_names = []
        st.rerun()

    events = get_events()
    if not events:
        st.warning("現在開催中のイベントが見つかりませんでした。")
        return

    event_options = {event['event_name']: event for event in events}
    selected_event_name = st.selectbox(
        "イベント名を選択してください:", 
        options=list(event_options.keys()),
        key="event_selector",
        on_change=on_event_change
    )
    
    if not selected_event_name:
        st.warning("イベントを選択してください。")
        return

    st.info(f"選択されたイベント: **{selected_event_name}**")
    selected_event_data = event_options.get(selected_event_name)

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
    
    # `st.multiselect`の戻り値を直接セッションステートに代入
    st.session_state.selected_room_names = st.multiselect(
        "比較したいルームを選択 (複数選択可):", 
        options=list(st.session_state.room_map_data.keys()),
        default=st.session_state.selected_room_names,
        key="room_selector"
    )

    if not st.session_state.selected_room_names:
        st.warning("最低1つのルームを選択してください。")
        return

    selected_room_ids = [st.session_state.room_map_data[name]['room_id'] for name in st.session_state.selected_room_names]

    # --- Real-time Dashboard Section ---
    st.header("3. リアルタイムダッシュボード")
    st.info("5秒ごとに自動更新されます。")
    
    JST = pytz.timezone('Asia/Tokyo')
    current_time = datetime.datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")

    st.write(f"最終更新日時 (日本時間): {current_time}")

    data_to_display = []
    all_info_found = True
    
    for room_id in selected_room_ids:
        room_info = get_room_event_info(room_id)
        
        if not isinstance(room_info, dict):
            st.warning(f"ルームID {room_id} のAPIレスポンスが不正な形式です。スキップします。")
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
            try:
                remain_time_str = str(datetime.timedelta(seconds=remain_time_sec))
                room_name = [name for name, info in st.session_state.room_map_data.items() if info['room_id'] == room_id][0]

                data_to_display.append({
                    "ルーム名": room_name,
                    "現在の順位": rank_info.get('rank', 'N/A'),
                    "現在のポイント": rank_info.get('point', 'N/A'),
                    "下位とのポイント差": rank_info.get('lower_gap', 'N/A') if rank_info.get('lower_rank', 0) > 0 else 0,
                    "下位の順位": rank_info.get('lower_rank', 'N/A'),
                    "残り時間": remain_time_str,
                })
            except Exception as e:
                st.error(f"データ処理中にエラーが発生しました（ルームID: {room_id}）。エラー: {e}")
                all_info_found = False
                continue
        else:
            st.warning(f"ルームID {room_id} のランキング情報が見つかりませんでした。")
            all_info_found = False
    
    if data_to_display:
        df = pd.DataFrame(data_to_display)
        
        df['現在の順位'] = pd.to_numeric(df['現在の順位'], errors='coerce')
        df_sorted = df.sort_values(by="現在の順位").reset_index(drop=True)
        
        st.subheader("📊 比較対象ルームのステータス")
        st.dataframe(df_sorted.style.highlight_max(axis=0, subset=['現在のポイント']).format(
            {'現在のポイント': '{:,}', '下位とのポイント差': '{:,}'}
        ), use_container_width=True)

        st.subheader("📈 ポイントと順位の比較")
        
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

    if not all_info_found:
        st.warning("一部のルーム情報が取得できませんでした。")
    elif not data_to_display:
        st.warning("選択されたルームの情報を取得できませんでした。")

    time.sleep(5)
    st.rerun()

if __name__ == "__main__":
    main()