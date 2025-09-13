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
            # 修正箇所: show_rankingがfalseではないイベントとis_event_blockがtrueではないイベントのみを追加
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
            # ★ 修正箇所: gift_idを文字列に変換してキーとして保存する
            gift_list_map[str(gift['gift_id'])] = {
                'name': gift.get('gift_name', 'N/A'),
                'point': point_value,
                'image': gift.get('image', '')
            }
        return gift_list_map
    except requests.exceptions.RequestException as e:
        st.error(f"ルームID {room_id} のギフトリスト取得中にエラーが発生しました: {e}")
        return {}

# 差分更新のためのキャッシュをセッション状態に保存する
if "gift_log_cache" not in st.session_state:
    st.session_state.gift_log_cache = {}

# 更新されたギフトログのみを取得・マージする関数
def get_and_update_gift_log(room_id):
    url = f"https://www.showroom-live.com/api/live/gift_log?room_id={room_id}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=5)
        response.raise_for_status()
        new_gift_log = response.json().get('gift_log', [])
        
        # セッション状態から既存のログを取得
        if room_id not in st.session_state.gift_log_cache:
            st.session_state.gift_log_cache[room_id] = []
        
        existing_log = st.session_state.gift_log_cache[room_id]
        
        # 新しいログを既存のログにマージ
        if new_gift_log:
            # 重複を避けるために既存のログをセットに変換
            existing_log_set = {(log.get('gift_id'), log.get('created_at'), log.get('num')) for log in existing_log}
            
            for log in new_gift_log:
                # ユニークなキーを作成して重複をチェック
                log_key = (log.get('gift_id'), log.get('created_at'), log.get('num'))
                if log_key not in existing_log_set:
                    existing_log.append(log)
        
        # ログをタイムスタンプでソート
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

    st.markdown("<h2 style='font-size:2em;'>1. イベントを選択</h2>", unsafe_allow_html=True)
    events = get_events()
    if not events:
        st.warning("現在開催中のイベントが見つかりませんでした。")
        return

    event_options = {event['event_name']: event for event in events}
    selected_event_name = st.selectbox(
        "イベント名を選択してください:", 
        options=list(event_options.keys()), key="event_selector")
    
    # 修正箇所: ここに注意書きを追加
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
    st.info("5秒ごとに自動更新されます。")
    with st.container(border=True):
        col1, col2 = st.columns([1, 1])
        with col1:
            st.markdown(f"**<font size='5'>イベント期間</font>**", unsafe_allow_html=True)
            st.write(f"**{event_period_str}**")
        with col2:
            st.markdown(f"**<font size='5'>残り時間</font>**", unsafe_allow_html=True)
            time_placeholder = st.empty()

    current_time = datetime.datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    st.write(f"最終更新日時 (日本時間): {current_time}")
    onlives_rooms = get_onlives_rooms()

    data_to_display = []
    final_remain_time = None
    if st.session_state.selected_room_names:
        for room_name in st.session_state.selected_room_names:
            try:
                if room_name not in st.session_state.room_map_data:
                    st.error(f"選択されたルーム名 '{room_name}' が見つかりません。リストを更新してください。")
                    continue
                room_id = st.session_state.room_map_data[room_name]['room_id']
                room_info = get_room_event_info(room_id)
                if not isinstance(room_info, dict):
                    st.warning(f"ルームID {room_id} のデータが不正な形式です。スキップします。")
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
                
                if rank_info and 'point' in rank_info and remain_time_sec is not None:
                    is_live = int(room_id) in onlives_rooms
                    data_to_display.append({
                        "ライブ中": "🔴" if is_live else "",
                        "ルーム名": room_name,
                        "現在の順位": rank_info.get('rank', 'N/A'),
                        "現在のポイント": rank_info.get('point', 'N/A'),
                        "上位とのポイント差": rank_info.get('upper_gap', 'N/A'),
                        "下位とのポイント差": rank_info.get('lower_gap', 'N/A'),
                    })
                    if final_remain_time is None:
                        final_remain_time = remain_time_sec
                else:
                    st.warning(f"ルーム名 '{room_name}' のランキング情報が不完全です。スキップします。")
            except Exception as e:
                st.error(f"データ処理中に予期せぬエラーが発生しました（ルーム名: {room_name}）。エラー: {e}")
                continue

    if data_to_display:
        df = pd.DataFrame(data_to_display)
        df['現在の順位'] = pd.to_numeric(df['現在の順位'], errors='coerce')
        df['現在のポイント'] = pd.to_numeric(df['現在のポイント'], errors='coerce')
        df = df.sort_values(by='現在の順位', ascending=True, na_position='last').reset_index(drop=True)
        
        live_status = df['ライブ中']
        df = df.drop(columns=['ライブ中'])
        
        # 上位とのポイント差と下位とのポイント差を計算し、欠損値を0で埋める
        df['上位とのポイント差'] = (df['現在のポイント'].shift(1) - df['現在のポイント']).abs().fillna(0).astype(int)
        if not df.empty:
            df.at[0, '上位とのポイント差'] = 0
        df['下位とのポイント差'] = (df['現在のポイント'].shift(-1) - df['現在のポイント']).abs().fillna(0).astype(int)
        
        df.insert(0, 'ライブ中', live_status)
        
        st.subheader("📊 比較対象ルームのステータス")
        
        required_cols = ['現在のポイント', '上位とのポイント差', '下位とのポイント差']
        if all(col in df.columns for col in required_cols):
            try:
                def highlight_rows(row):
                    if row['ライブ中'] == '🔴':
                        return ['background-color: #e6fff2'] * len(row)
                    elif row.name % 2 == 1:
                        return ['background-color: #fafafa'] * len(row)
                    else:
                        return [''] * len(row)
                
                df_to_format = df.copy()
                for col in required_cols:
                    if col in df_to_format.columns:
                        df_to_format[col] = df_to_format[col].astype(str)
                
                st.dataframe(
                    df_to_format.style.apply(highlight_rows, axis=1), 
                    use_container_width=True, 
                    hide_index=True
                )
            except Exception as e:
                st.error(f"データフレームの表示中にエラーが発生しました: {e}")
        else:
            st.error("必要なカラムがデータフレームに存在しません。")

        # グラフ描画
        st.subheader("📈 ポイント推移・ポイント差のグラフ")
        
        if len(st.session_state.selected_room_names) > 0 and "現在のポイント" in df.columns:
            df['現在のポイント'] = pd.to_numeric(df['現在のポイント'], errors='coerce')
            color_map = {name: get_rank_color(st.session_state.room_map_data[name]['rank']) for name in st.session_state.selected_room_names}
            
            fig_point = px.bar(df, x="ルーム名", y="現在のポイント",
                                title="現在のポイント", color="ルーム名",
                                color_discrete_map=color_map,
                                hover_data=["現在の順位"],
                                labels={"現在のポイント": "ポイント", "ルーム名": "ルーム名"})
            st.plotly_chart(fig_point, use_container_width=True)

            # グラフの重複を解消する修正
            if len(st.session_state.selected_room_names) > 1:
                if "上位とのポイント差" in df.columns:
                    df['上位とのポイント差'] = pd.to_numeric(df['上位とのポイント差'], errors='coerce')
                    fig_upper_gap = px.bar(df, x="ルーム名", y="上位とのポイント差",
                                           title="上位とのポイント差", color="ルーム名",
                                           color_discrete_map=color_map,
                                           hover_data=["現在の順位", "現在のポイント"],
                                           labels={"上位とのポイント差": "ポイント差", "ルーム名": "ルーム名"})
                    st.plotly_chart(fig_upper_gap, use_container_width=True)

                if "下位とのポイント差" in df.columns:
                    df['下位とのポイント差'] = pd.to_numeric(df['下位とのポイント差'], errors='coerce')
                    fig_lower_gap = px.bar(df, x="ルーム名", y="下位とのポイント差",
                                           title="下位とのポイント差", color="ルーム名",
                                           color_discrete_map=color_map,
                                           hover_data=["現在の順位", "現在のポイント"],
                                           labels={"下位とのポイント差": "ポイント差", "ルーム名": "ルーム名"})
                    st.plotly_chart(fig_lower_gap, use_container_width=True)
    
    # ライブ配信中のルームのギフト履歴を表示
    st.markdown("<h2 style='font-size:2em;'>4. スペシャルギフト履歴</h2>", unsafe_allow_html=True)
    
    live_room_names = [name for name in st.session_state.selected_room_names if int(st.session_state.room_map_data[name]['room_id']) in onlives_rooms]
    
    gift_container = st.container(border=True)
    
    if live_room_names:
        room_html_list = []
        css_style = """
        <style>
            .container-wrapper {
                display: flex;
                flex-wrap: wrap;
                gap: 20px;
                justify-content: center;
            }
            .room-container {
                border: 2px solid #ccc;
                border-radius: 12px;
                padding: 15px;
                flex: 1 1 300px;
                max-width: 400px;
                box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
                background-color: #fff;
                transition: transform 0.2s;
            }
            .room-container:hover {
                transform: translateY(-5px);
            }
            .room-title {
                font-size: 1.5em;
                font-weight: bold;
                text-align: center;
                margin-bottom: 15px;
            }
            .ranking-label {
                font-size: 1.2em;
                font-weight: bold;
                color: white;
                padding: 5px 10px;
                border-radius: 8px;
                text-align: center;
                width: fit-content;
                margin: 0 auto 10px auto;
            }
            .gift-item {
                display: flex;
                align-items: center;
                margin-bottom: 10px;
                padding: 8px;
                border-radius: 8px;
                background-color: #f0f0f0;
            }
            .gift-item img {
                width: 40px;
                height: 40px;
                margin-right: 10px;
                border-radius: 50%;
                background-color: #fff;
            }
            .gift-info {
                display: flex;
                flex-direction: column;
                justify-content: center;
            }
            .gift-name {
                font-weight: bold;
                font-size: 1em;
            }
            .gift-detail {
                font-size: 0.9em;
                color: #555;
            }
        </style>
        """
        
        for room_name in live_room_names:
            room_id = st.session_state.room_map_data[room_name]['room_id']
            rank = st.session_state.room_map_data[room_name]['rank']
            rank_color = get_rank_color(rank)
            
            # get_and_update_gift_log関数を呼び出す
            gift_log = get_and_update_gift_log(room_id)
            gift_list_map = get_gift_list(room_id)
            
            html_content = f"""
            <div class="room-container">
                <div class="ranking-label" style="background-color: {rank_color};">{rank}位</div>
                <div class="room-title">{room_name}</div>
            """
            
            special_gifts = [log for log in gift_log if gift_list_map.get(str(log.get('gift_id')), {}).get('point', 0) > 1000]
            
            if special_gifts:
                html_content += '<div style="max-height: 400px; overflow-y: auto;">'
                for gift in special_gifts:
                    gift_id = str(gift.get('gift_id'))
                    gift_info = gift_list_map.get(gift_id, {})
                    gift_name = gift_info.get('name', 'N/A')
                    gift_point = gift_info.get('point', 'N/A')
                    gift_image = gift_info.get('image', 'N/A')
                    user_name = gift.get('user_name', '匿名')
                    num = gift.get('num', 1)
                    created_at = datetime.datetime.fromtimestamp(gift.get('created_at'), JST).strftime('%H:%M:%S')
                    
                    html_content += (
                        f'<div class="gift-item">'
                        f'<img src="{gift_image}" alt="{gift_name}">'
                        f'<div class="gift-info">'
                        f'<div class="gift-name">{gift_name}</div>'
                        f'<div class="gift-detail">🎁 {user_name} が {num}個 送りました</div>'
                        f'<div class="gift-detail">⏱ {created_at}</div>'
                        f'</div>'
                        f'<div style="margin-left: auto; text-align: right;">'
                        f'<div style="font-size: 1.2em; font-weight: bold;">{num}個</div>'
                        f'<div>{gift_point}pt</div>'
                        f'</div>'
                    )
                    html_content += '</div>'
                html_content += '</div>'
            else:
                html_content += '<p style="text-align: center; padding: 12px 0;">ギフト履歴がありません。</p></div>'
            
            html_content += '</div>'
            room_html_list.append(html_content)

        html_container_content = '<div class="container-wrapper">' + ''.join(room_html_list) + '</div>'
        gift_container.markdown(css_style + html_container_content, unsafe_allow_html=True)
    else:
        gift_container.info("選択されたルームに現在ライブ配信中のルームはありません。")

    if final_remain_time is not None:
        remain_time_readable = str(datetime.timedelta(seconds=final_remain_time))
        time_placeholder.markdown(f"<span style='color: red;'>**{remain_time_readable}**</span>", unsafe_allow_html=True)
    else:
        time_placeholder.warning("残り時間を取得できませんでした。")

    time.sleep(5)
    st.rerun()

if __name__ == "__main__":
    main()