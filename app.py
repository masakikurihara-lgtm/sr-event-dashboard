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
        st.session_state.show_dashboard = False
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
        st.session_state.show_dashboard = True
        st.rerun()

    if st.session_state.show_dashboard:
        if not st.session_state.selected_room_names:
            st.warning("最低1つのルームを選択してください。")
            return
        
        st.markdown("<h2 style='font-size:2em;'>3. リアルタイムダッシュボード</h2>", unsafe_allow_html=True)
        st.info("10秒ごとに自動更新されます。")

        st_autorefresh(interval=10000, limit=None, key="data_refresh")

        if st.session_state.get("selected_room_names") and selected_event_data:
            ended_at = selected_event_data.get("ended_at")
            if ended_at:
                now_jst = datetime.datetime.now(JST).timestamp()
                final_remain_time = max(0, int(ended_at - now_jst))
            else:
                final_remain_time = None
        else:
            final_remain_time = None

        time_placeholder = st.empty()
        
        with st.container():
            st.markdown("### ポイントランキング")
            
            def get_ranking_df(selected_rooms, room_map):
                ranking_data = []
                for room_name in selected_rooms:
                    room_info = room_map.get(room_name, {})
                    room_id = room_info.get('room_id')
                    rank = room_info.get('rank')
                    point = room_info.get('point')

                    current_info = get_room_event_info(room_id)
                    current_rank = current_info.get('current_rank')
                    current_point = current_info.get('point')

                    points_list = [v['point'] for k, v in room_map.items() if 'point' in v]
                    if points_list:
                        sorted_points = sorted(points_list, reverse=True)
                        current_index = sorted_points.index(current_point) if current_point in sorted_points else -1
                        
                        upper_gap = None
                        lower_gap = None

                        if current_index > 0:
                            upper_gap = sorted_points[current_index - 1] - current_point
                        if current_index < len(sorted_points) - 1:
                            lower_gap = current_point - sorted_points[current_index + 1]

                        ranking_data.append({
                            "ルーム名": room_name,
                            "現在の順位": current_rank,
                            "現在のポイント": current_point,
                            "上位とのポイント差": upper_gap,
                            "下位とのポイント差": lower_gap,
                            "ルームID": room_id,
                        })
                
                df_ranking = pd.DataFrame(ranking_data)
                
                if "現在の順位" in df_ranking.columns:
                    df_ranking["sort_rank"] = pd.to_numeric(df_ranking["現在の順位"], errors='coerce')
                    df_ranking = df_ranking.sort_values(by="sort_rank").drop(columns=["sort_rank"])
                
                return df_ranking
            
            df_ranking = get_ranking_df(st.session_state.selected_room_names, st.session_state.room_map_data)
            
            if not df_ranking.empty:
                # 修正箇所: ここでデータフレームの高さを指定
                st.dataframe(df_ranking, use_container_width=True, hide_index=True, height=250)
            else:
                st.warning("選択したルームのランキングデータを取得できませんでした。")

            st.markdown("### ポイント推移グラフ")
            
            if "point_history" not in st.session_state:
                st.session_state.point_history = {}
            
            for room_name in st.session_state.selected_room_names:
                room_id = st.session_state.room_map_data.get(room_name, {}).get('room_id')
                if room_id:
                    current_info = get_room_event_info(room_id)
                    current_point = current_info.get('point')
                    
                    if room_name not in st.session_state.point_history:
                        st.session_state.point_history[room_name] = []
                    
                    st.session_state.point_history[room_name].append({
                        "time": datetime.datetime.now(JST).isoformat(),
                        "point": current_point
                    })
            
            if st.session_state.point_history:
                history_df = pd.DataFrame()
                for room_name, history in st.session_state.point_history.items():
                    temp_df = pd.DataFrame(history)
                    temp_df['ルーム名'] = room_name
                    history_df = pd.concat([history_df, temp_df], ignore_index=True)
                
                if not history_df.empty:
                    history_df['time'] = pd.to_datetime(history_df['time'])
                    fig = px.line(
                        history_df,
                        x="time",
                        y="point",
                        color="ルーム名",
                        title="リアルタイムポイント推移",
                        markers=True
                    )
                    st.plotly_chart(fig, use_container_width=True)
                    fig.update_layout(uirevision="const")


            st.markdown("### スペシャルギフト履歴")
            selected_room_for_gift = st.selectbox(
                "ギフト履歴を確認するルームを選択:",
                options=st.session_state.selected_room_names,
                key="gift_room_selector"
            )
            
            if selected_room_for_gift:
                room_id_for_gift = st.session_state.room_map_data.get(selected_room_for_gift, {}).get('room_id')
                
                if room_id_for_gift:
                    with st.spinner(f"{selected_room_for_gift} のギフト履歴を更新中..."):
                        gift_log_data = get_and_update_gift_log(room_id_for_gift)
                        gift_list = get_gift_list(room_id_for_gift)
                        
                        gift_df_rows = []
                        if gift_log_data:
                            for log in gift_log_data:
                                gift_id_str = str(log.get('gift_id'))
                                gift_info = gift_list.get(gift_id_str, {})
                                gift_name = gift_info.get('name', f"ギフトID:{gift_id_str}")
                                gift_point = gift_info.get('point', 'N/A')
                                gift_image = gift_info.get('image', '')
                                
                                is_special_gift = False
                                if gift_name in ["スーパースター", "タワー"]:
                                    is_special_gift = True
                                else:
                                    if gift_point == 10000 and log.get('num') == 1:
                                        is_special_gift = True
                                
                                if is_special_gift:
                                    created_at = datetime.datetime.fromtimestamp(log.get('created_at'), JST)
                                    gift_df_rows.append({
                                        "時間": created_at.strftime('%Y/%m/%d %H:%M:%S'),
                                        "ルーム名": selected_room_for_gift,
                                        "ユーザー名": log.get('user_name', 'N/A'),
                                        "ギフト名": gift_name,
                                        "個数": log.get('num', 'N/A'),
                                        "ポイント": f"{gift_point * log.get('num', 0):,}",
                                        "画像": gift_image
                                    })

                        if gift_df_rows:
                            df_gifts = pd.DataFrame(gift_df_rows)
                            df_gifts['時間'] = pd.to_datetime(df_gifts['時間'])
                            df_gifts = df_gifts.sort_values(by="時間", ascending=False).reset_index(drop=True)
                            
                            st.write(f"**{selected_room_for_gift}** のスペシャルギフト履歴:")
                            df_display = df_gifts.drop(columns=["画像"])
                            
                            st.dataframe(df_display, use_container_width=True, height=350)

                            col1, col2 = st.columns([1, 4])
                            for index, row in df_gifts.iterrows():
                                if row['画像']:
                                    with col1:
                                        st.image(row['画像'], width=50)
                                    with col2:
                                        st.write(f"**{row['ギフト名']}** x {row['個数']} 個 ({row['ポイント']} pt) by {row['ユーザー名']} ({row['時間']})")
                                        st.markdown("---")
                                        
                            st.write("---")
                        else:
                            st.info("このルームにはまだスペシャルギフトの履歴がありません。")

        if final_remain_time is not None:
            remain_time_readable = str(datetime.timedelta(seconds=final_remain_time))
            time_placeholder.markdown(f"<span style='color: red;'>**イベント終了まで残り時間:** {remain_time_readable}</span>", unsafe_allow_html=True)
        else:
            time_placeholder.write("")


if __name__ == "__main__":
    main()