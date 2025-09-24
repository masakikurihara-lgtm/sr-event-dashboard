import streamlit as st
import requests
import pandas as pd
import io
import time
import datetime
import plotly.express as px
import pytz
from streamlit_autorefresh import st_autorefresh
from datetime import timedelta, date
import logging


# Set page configuration
st.set_page_config(
    page_title="SHOWROOM Event Dashboard",
    page_icon="🎤",
    layout="wide",
)

HEADERS = {"User-Agent": "Mozilla/5.0"}
JST = pytz.timezone('Asia/Tokyo')
ROOM_LIST_URL = "https://mksoul-pro.com/showroom/file/room_list.csv"  #認証用
BACKUP_INDEX_URL = "https://mksoul-pro.com/showroom/file/sr-event-archive-list-index.txt" # バックアップインデックスURL

if "authenticated" not in st.session_state:  #認証用
    st.session_state.authenticated = False  #認証用


# ▼▼▼ ここから修正・追加した関数群 ▼▼▼

def normalize_event_id(val):
    """
    event_idを統一された文字列形式に正規化します。
    (例: 123, 123.0, "123", "123.0" -> "123")
    """
    if val is None:
        return None
    try:
        # 数値や数値形式の文字列を float -> int -> str の順で変換
        return str(int(float(val)))
    except (ValueError, TypeError):
        # 変換に失敗した場合は、そのままの文字列として扱う
        return str(val).strip()

@st.cache_data(ttl=3600)
def get_api_events(status, pages=10):
    """
    APIから指定されたステータスのイベントを取得する汎用関数
    """
    api_events = []
    page = 1
    for _ in range(pages):
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
                break

            filtered_page_events = [
                event for event in page_events 
                if event.get("show_ranking") is not False or event.get("type_name") == "ランキング"
            ]
            api_events.extend(filtered_page_events)
            page += 1
        except requests.exceptions.RequestException as e:
            st.error(f"イベントデータ取得中にエラーが発生しました (status={status}): {e}")
            break
        except ValueError:
            st.error(f"APIからのJSONデコードに失敗しました: {response.text}")
            break
    return api_events


@st.cache_data(ttl=3600)
def get_backup_events(start_date, end_date):
    """
    バックアップファイルから指定された期間の終了イベントを取得する関数
    """
    try:
        res_index = requests.get(BACKUP_INDEX_URL, headers=HEADERS, timeout=10)
        res_index.raise_for_status()
        backup_files = res_index.text.strip().splitlines()
    except requests.exceptions.RequestException as e:
        st.error(f"バックアップインデックスの取得に失敗しました: {e}")
        return []

    all_backup_data = []
    columns = [
        'event_id', 'is_event_block', 'is_entry_scope_inner', 'event_name',
        'image_m', 'started_at', 'ended_at', 'event_url_key', 'show_ranking'
    ]
    for file_url in backup_files:
        try:
            df = pd.read_csv(file_url, header=None, names=columns)
            all_backup_data.append(df)
        except Exception as e:
            st.warning(f"バックアップファイル {file_url} の読み込みに失敗しました: {e}")
            continue
    
    if not all_backup_data:
        return []

    combined_df = pd.concat(all_backup_data, ignore_index=True)
    # started_atとended_atを数値に変換し、エラー時は0で補完
    combined_df['started_at'] = pd.to_numeric(combined_df['started_at'], errors='coerce').fillna(0)
    combined_df['ended_at'] = pd.to_numeric(combined_df['ended_at'], errors='coerce').fillna(0)
    combined_df.drop_duplicates(subset=['event_id'], keep='first', inplace=True)
    
    start_datetime = JST.localize(datetime.datetime.combine(start_date, datetime.time.min))
    end_datetime = JST.localize(datetime.datetime.combine(end_date, datetime.time.max))

    combined_df['ended_at_dt'] = pd.to_datetime(combined_df['ended_at'], unit='s', utc=True).dt.tz_convert(JST)
    combined_df = combined_df[(combined_df['ended_at_dt'] >= start_datetime) & (combined_df['ended_at_dt'] <= end_datetime)]

    return combined_df.to_dict('records')


@st.cache_data(ttl=600)
def get_ongoing_events():
    """
    開催中のイベントを取得する
    """
    events = get_api_events(status=1)
    now_ts = datetime.datetime.now(JST).timestamp()
    
    # 念のため、本当に開催中のものだけをフィルタリング
    ongoing_events = [e for e in events if e.get('ended_at', 0) > now_ts]

    for event in ongoing_events:
        try:
            event['started_at'] = int(float(event.get('started_at', 0)))
            event['ended_at'] = int(float(event.get('ended_at', 0)))
        except (ValueError, TypeError):
            event['started_at'] = 0
            event['ended_at'] = 0
    return ongoing_events


@st.cache_data(ttl=3600)
def get_finished_events(start_date, end_date):
    """
    終了したイベントをAPIとバックアップから取得し、マージして返す
    """
    api_events_raw = get_api_events(status=4)
    backup_events_raw = get_backup_events(start_date, end_date)

    now_ts = datetime.datetime.now(JST).timestamp()
    start_ts = JST.localize(datetime.datetime.combine(start_date, datetime.time.min)).timestamp()
    end_ts = JST.localize(datetime.datetime.combine(end_date, datetime.time.max)).timestamp()

    # APIから取得したイベントをフィルタリング＆サニタイズ
    api_events = []
    for event in api_events_raw:
        ended_at = event.get('ended_at', 0)
        # 日付範囲内で、かつ現在時刻より前に終了していることを確認
        if not (start_ts <= ended_at <= end_ts and ended_at < now_ts):
            continue
        try:
            event['started_at'] = int(float(event.get('started_at', 0)))
            event['ended_at'] = int(float(ended_at))
            api_events.append(event)
        except (ValueError, TypeError):
            continue

    # バックアップから取得したイベントをフィルタリング＆サニタイズ
    backup_events = []
    for event in backup_events_raw:
        ended_at = event.get('ended_at', 0)
        # 現在時刻より前に終了していることを確認 (バグ修正)
        if ended_at >= now_ts:
            continue
        try:
            event['started_at'] = int(float(event.get('started_at', 0)))
            event['ended_at'] = int(float(ended_at))
            backup_events.append(event)
        except (ValueError, TypeError):
            continue

    # 正規化されたevent_idを使ってマージ
    merged_events_map = {}
    for event in backup_events:
        event_id = normalize_event_id(event.get('event_id'))
        if event_id:
            merged_events_map[event_id] = event
    
    for event in api_events:
        event_id = normalize_event_id(event.get('event_id'))
        if event_id:
            merged_events_map[event_id] = event # APIデータが優先される

    all_finished_events = list(merged_events_map.values())
    all_finished_events.sort(key=lambda x: x.get('ended_at', 0), reverse=True)
    
    for event in all_finished_events:
        event_name_str = str(event.get('event_name', ''))
        event['event_name'] = f"＜終了＞ {event_name_str.replace('＜終了＞ ', '').strip()}"
        
    return all_finished_events


# ▲▲▲ ここまで修正・追加した関数群 ▲▲▲


# --- 以下、既存の関数は変更なし ---

# [修正１] 取得元APIの変更に伴い、元の候補リストを削除

@st.cache_data(ttl=300)
def get_event_ranking_with_room_id(event_url_key, event_id, max_pages=10):
    all_ranking_data = []
    
    # [修正１] 新しいAPI候補リスト
    RANKING_API_CANDIDATES = [
        "https://www.showroom-live.com/api/event/room_list?event_id={event_id}&page={page}",      # API候補1 (Primary)
        "https://www.showroom-live.com/api/event/{event_url_key}/ranking?page={page}",      # API候補2 (Fallback)
    ]
    
    for base_url in RANKING_API_CANDIDATES:
        try:
            temp_ranking_data = []
            current_page = 1
            
            # API候補1 (room_list) は next_page が null でない限りループ
            # API候補2 (ranking) は 404 またはランキングリストが空になるまでループ
            
            while current_page <= max_pages:
                url = base_url.format(event_url_key=event_url_key, event_id=event_id, page=current_page)
                response = requests.get(url, headers=HEADERS, timeout=10)
                
                if response.status_code == 404:
                    break
                
                response.raise_for_status()
                data = response.json()
                
                ranking_list = None
                is_room_list_api = "room_list" in base_url
                
                if is_room_list_api:
                    # API候補1: room_list の解析ロジック
                    if isinstance(data, dict) and 'list' in data:
                        ranking_list = data['list']
                        
                        # ページネーションの制御
                        if data.get('next_page') is None:
                            current_page = max_pages + 1 # ループを終了させる
                        else:
                            current_page += 1
                else:
                    # API候補2: ranking の解析ロジック (既存ロジックを踏襲)
                    if isinstance(data, dict) and 'ranking' in data:
                        ranking_list = data['ranking']
                    elif isinstance(data, dict) and 'event_list' in data:
                        ranking_list = data['event_list']
                    elif isinstance(data, list):
                        ranking_list = data
                        
                    # ページネーションの制御 (ランキングAPIはリストが空になったら終了)
                    if not ranking_list:
                        break
                    else:
                        current_page += 1
                        # 1ページあたりのデータ件数が少ない場合も終了の目安とする
                        if len(ranking_list) < 50 and not is_room_list_api:
                            # ページネーションの終わりが近いと想定し、念のためもう1ページ確認後、ループを終了させる
                            if current_page > max_pages:
                                break
                    
                if not ranking_list:
                    break

                temp_ranking_data.extend(ranking_list)
            
            # 取得したデータにroom_idが含まれていれば、そのAPI候補を採用
            # room_list APIではroom_idがトップレベルか、event_entry.room_idにある
            if temp_ranking_data and any(r.get('room_id') or (isinstance(r.get('event_entry'), dict) and r['event_entry'].get('room_id')) for r in temp_ranking_data):
                all_ranking_data = temp_ranking_data
                break
        except requests.exceptions.RequestException:
            continue
        except Exception:
            # JSON解析エラーなどもキャッチして次のAPI候補へ進む
            continue
            
    if not all_ranking_data:
        return None
        
    room_map = {}
    for room_info in all_ranking_data:
        # [修正１] room_list APIにも対応したデータ抽出ロジックに統一
        
        # room_id の取得 (room_list APIではトップレベルかevent_entry内)
        room_id = room_info.get('room_id')
        if not room_id and isinstance(room_info.get('event_entry'), dict):
            room_id = room_info['event_entry'].get('room_id')
            
        room_name = room_info.get('room_name') or room_info.get('user_name')
        
        # point, rank の取得 (room_list APIではトップレベルにあることを優先)
        point = room_info.get('point')
        rank = room_info.get('rank')
        
        # 既存のAPIロジック (ranking API) ではpointとrankがネストされている場合がある
        if point is None and isinstance(room_info.get('ranking'), dict):
             point = room_info['ranking'].get('point')
        if rank is None and isinstance(room_info.get('ranking'), dict):
            rank = room_info['ranking'].get('rank')
        
        if room_id and room_name:
            room_map[room_name] = {
                'room_id': str(room_id),
                'rank': rank,
                'point': point
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

@st.cache_data(ttl=60)
def get_block_event_overall_ranking(event_url_key, max_pages=30):
    """
    ブロックイベント全体のランキング（順位情報のみ）を取得する。
    """
    rank_map = {}
    base_url = "https://www.showroom-live.com/api/event/{event_url_key}/ranking?page={page}"
    try:
        for page in range(1, max_pages + 1):
            url = base_url.format(event_url_key=event_url_key, page=page)
            response = requests.get(url, headers=HEADERS, timeout=10)
            if response.status_code == 404:
                break
            response.raise_for_status()
            data = response.json()
            ranking_list = data.get('ranking', [])
            if not ranking_list:
                break
            for rank_info in ranking_list:
                room_id = rank_info.get('room_id')
                rank = rank_info.get('rank')
                if room_id is not None and rank is not None:
                    rank_map[room_id] = rank
    except requests.exceptions.RequestException as e:
        st.warning(f"ブロックイベントの全体ランキング取得中にエラーが発生しました: {e}")
    return rank_map

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
            premium_room_type = 0
            if isinstance(room, dict):
                room_id = room.get('room_id')
                started_at = room.get('started_at')
                premium_room_type = room.get('premium_room_type', 0)
                if room_id is None and 'live_info' in room and isinstance(room['live_info'], dict):
                    room_id = room['live_info'].get('room_id')
                    started_at = room['live_info'].get('started_at')
                    premium_room_type = room['live_info'].get('premium_room_type', 0)
                if room_id is None and 'room' in room and isinstance(room['room'], dict):
                    room_id = room['room'].get('room_id')
                    started_at = room['room'].get('started_at')
                    premium_room_type = room['room'].get('premium_room_type', 0)
            if room_id and started_at is not None:
                try:
                    onlives[int(room_id)] = {'started_at': started_at, 'premium_room_type': premium_room_type}
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
    st.write("イベント順位やポイント、ポイント差、スペシャルギフトの履歴、必要ギフト数などが、リアルタイムで可視化できるツールです。")


    # ▼▼ 認証ステップ ▼▼
    if not st.session_state.authenticated:
        st.markdown("### 🔑 認証コードを入力してください")
        input_room_id = st.text_input(
            "認証コードを入力してください:",
            placeholder="",
            type="password",
            key="room_id_input"
        )

        # 認証ボタン
        if st.button("認証する"):
            if input_room_id:  # 入力が空でない場合のみ
                try:
                    response = requests.get(ROOM_LIST_URL, timeout=5)
                    response.raise_for_status()
                    room_df = pd.read_csv(io.StringIO(response.text), header=None)

                    valid_codes = set(str(x).strip() for x in room_df.iloc[:, 0].dropna())

                    if input_room_id.strip() in valid_codes:
                        st.session_state.authenticated = True
                        st.success("✅ 認証に成功しました。ツールを利用できます。")
                        st.rerun()  # 認証成功後に再読み込み
                    else:
                        st.error("❌ 認証コードが無効です。正しい認証コードを入力してください。")
                except Exception as e:
                    st.error(f"認証リストを取得できませんでした: {e}")
            else:
                st.warning("認証コードを入力してください。")

        # 認証が終わるまで他のUIを描画しない
        st.stop()
    # ▲▲ 認証ステップここまで ▲▲


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
    # [修正３] オートリフレッシュの制御のためのセッションステート
    if "auto_refresh_enabled" not in st.session_state:
        st.session_state.auto_refresh_enabled = True # デフォルトで有効

    st.markdown("<h2 style='font-size:2em;'>1. イベントを選択</h2>", unsafe_allow_html=True)
    
    # --- ▼▼▼ イベント選択ロジック（変更なし） ▼▼▼ ---
    event_status = st.radio(
        "イベント種別を選択してください:",
        ("開催中", "終了"),
        horizontal=True,
        key="event_status_selector"
    )

    events = []
    if event_status == "開催中":
        with st.spinner('開催中のイベントを取得中...'):
            events = get_ongoing_events()
            # 開催中イベントは終了日時が近い順（昇順）でソート
            events.sort(key=lambda x: x.get('ended_at', float('inf')))
    else: # "終了"
        st.write("表示するイベントの**終了期間**をカレンダーで選択してください:")
        today = date.today()
        thirty_days_ago = today - timedelta(days=30)
        
        selected_date_range = st.date_input(
            "イベント終了期間",
            (thirty_days_ago, today),
            min_value=date(2020, 1, 1),
            max_value=today,
            key="date_range_selector"
        )
        
        if len(selected_date_range) == 2:
            start_date, end_date = selected_date_range
            if start_date > end_date:
                st.error("エラー: 期間の開始日は終了日以前の日付を選択してください。")
                st.stop()
            else:
                with st.spinner(f'終了したイベント ({start_date}〜{end_date}) を取得中...'):
                    events = get_finished_events(start_date, end_date)
        else:
            st.warning("有効な期間（開始日と終了日）を選択してください。")
            st.stop()
    # --- ▲▲▲ イベント選択ロジック（変更なし） ▲▲▲ ---


    if not events:
        st.warning("表示可能なイベントが見つかりませんでした。")
        return


    event_options = {event['event_name']: event for event in events}
    selected_event_name = st.selectbox(
        "イベント名を選択してください:", 
        options=list(event_options.keys()), key="event_selector")
    
    st.markdown(
        "<p style='font-size:12px; margin: -10px 0px 20px 0px; color:#a1a1a1;'>※ランキング型イベントが対象になります。ただし、ブロック型イベントはポイントのみで順位表示（総合ランキング表示）しています（ブロック分けされた表示とはなっていません）。<br />※終了済みイベントのポイント表示は、イベント終了日の翌日12:00頃までは「集計中」となり、その後ポイントが表示され、24時間経過するとクリアされます（0表示になります）。<br />※終了済みイベントは、イベント終了日の約1ヶ月後を目処にイベント一覧の選択対象から削除されます。</p>",
        unsafe_allow_html=True
    )

    if not selected_event_name:
        st.warning("イベントを選択してください。")
        return

    selected_event_data = event_options.get(selected_event_name)
    event_url = f"https://www.showroom-live.com/event/{selected_event_data.get('event_url_key')}"
    started_at_dt = datetime.datetime.fromtimestamp(selected_event_data.get('started_at', 0), JST)
    ended_at_dt = datetime.datetime.fromtimestamp(selected_event_data.get('ended_at', 0), JST)
    event_period_str = f"{started_at_dt.strftime('%Y/%m/%d %H:%M')} - {ended_at_dt.strftime('%Y/%m/%d %H:%M')}"
    st.info(f"選択されたイベント: **{selected_event_name}**")

    st.markdown("<h2 style='font-size:2em;'>2. 比較したいルームを選択</h2>", unsafe_allow_html=True)
    selected_event_key = selected_event_data.get('event_url_key', '')
    selected_event_id = selected_event_data.get('event_id')

    # イベントを変更した場合、「上位10ルームまでを選択」のチェックボックスも初期化する
    if st.session_state.selected_event_name != selected_event_name or st.session_state.room_map_data is None:
        with st.spinner('イベント参加者情報を取得中...'):
            # [修正１] APIの変更は get_event_ranking_with_room_id 内で対応済み
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
        sorted_rooms = sorted(room_map.items(), key=lambda item: item[1].get('point', 0) if item[1].get('point') is not None else 0, reverse=True)
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
            
            # [修正３] オートリフレッシュの制御
            col_msg, col_btn = st.columns([0.7, 0.3])
            
            # メッセージの修正
            col_msg.info("7秒ごとに自動更新されます。※停止ボタン押下時は停止します。")
            
            # ボタンの配置とロジック
            if st.session_state.auto_refresh_enabled:
                if col_btn.button("自動更新を停止", key="stop_autorefresh_btn"):
                    st.session_state.auto_refresh_enabled = False
                    st.rerun()
            else:
                if col_btn.button("自動更新を再開", key="start_autorefresh_btn"):
                    st.session_state.auto_refresh_enabled = True
                    st.rerun()

            # st_autorefreshの呼び出し（制御）
            if st.session_state.auto_refresh_enabled:
                # 7秒 (7000ms) ごとに自動更新
                st_autorefresh(interval=7000, key="dashboard_autorefresh")
            
            with st.container(border=True):
                        col1, col2 = st.columns([1, 1])
                        with col1:
                            st.components.v1.html(f"""
                            <div style="font-weight: bold; font-size: 1.5rem; color: #333333; line-height: 1.2; padding-bottom: 15px;">イベント期間</div>
                            <div style="font-weight: bold; font-size: 1.1rem; color: #333333; line-height: 1.2;">{event_period_str}</div>
                            """, height=80)
                        with col2:
                            st.components.v1.html(f"""
                            <div style="font-weight: bold; font-size: 1.5rem; color: #333333; line-height: 1.2; padding-bottom: 15px;">残り時間</div>
                            <div style="font-weight: bold; font-size: 1.1rem; line-height: 1.2;">
                                <span id="sr_countdown_timer_in_col" style="color: #4CAF50;" data-end="{int(ended_at_dt.timestamp() * 1000)}">計算中...</span>
                            </div>
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
                                        if (days > 0) return `${{days}}d ${{pad(hh)}}:${{pad(mm)}}:${{pad(ss)}}`;
                                        return `${{pad(hh)}}:${{pad(mm)}}:${{pad(ss)}}`;
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
                            })();
                            </script>
                            """, height=80)
                        current_time = datetime.datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
                        st.write(f"最終更新日時 (日本時間): {current_time}")

            is_event_ended = datetime.datetime.now(JST) > ended_at_dt
            is_closed = selected_event_data.get('is_closed', True)
            is_aggregating = is_event_ended and not is_closed # イベント終了後、クローズするまでの期間

            final_ranking_data = {}
            if is_event_ended:
                with st.spinner('イベント終了後の最終ランキングデータを取得中...'):
                    event_url_key = selected_event_data.get('event_url_key')
                    event_id = selected_event_data.get('event_id')
                    # [修正１] APIの変更は get_event_ranking_with_room_id 内で対応済み
                    final_ranking_map = get_event_ranking_with_room_id(event_url_key, event_id, max_pages=30)
                    
                    if final_ranking_map:
                        for name, data in final_ranking_map.items():
                            if 'room_id' in data:
                                final_ranking_data[data['room_id']] = {
                                    'rank': data.get('rank'),
                                    'point': data.get('point')
                                }
                    else:
                        st.warning("イベント終了後の最終ランキングデータを取得できませんでした。")


            onlives_rooms = get_onlives_rooms()
            data_to_display = []
            is_block_event = selected_event_data.get("is_event_block", False)
            block_event_ranks = {}
            if is_block_event and not is_event_ended:
                with st.spinner('ブロックイベントの全体順位を取得中...'):
                    block_event_ranks = get_block_event_overall_ranking(selected_event_data.get('event_url_key'))

            if st.session_state.selected_room_names:
                premium_live_rooms = [
                    name for name in st.session_state.selected_room_names 
                    if st.session_state.room_map_data and name in st.session_state.room_map_data and 
                       int(st.session_state.room_map_data[name]['room_id']) in onlives_rooms and 
                       onlives_rooms.get(int(st.session_state.room_map_data[name]['room_id']), {}).get('premium_room_type') == 1
                ]
                if premium_live_rooms:
                    room_names_str = '、'.join([f"'{name}'" for name in premium_live_rooms])
                    st.info(f"{room_names_str} は、プレミアムライブのため、ポイントおよびスペシャルギフト履歴情報は取得できません。")

                for room_name in st.session_state.selected_room_names:
                    try:
                        if room_name not in st.session_state.room_map_data:
                            st.error(f"選択されたルーム名 '{room_name}' が見つかりません。リストを更新してください。")
                            continue
                        
                        room_id = st.session_state.room_map_data[room_name]['room_id']
                        rank, point, upper_gap, lower_gap = 'N/A', 'N/A', 'N/A', 'N/A'
                        is_live = int(room_id) in onlives_rooms
                        is_premium_live = False
                        
                        if is_live:
                            live_info = onlives_rooms.get(int(room_id))
                            if live_info and live_info.get('premium_room_type') == 1:
                                is_premium_live = True

                        if is_premium_live:
                            rank = st.session_state.room_map_data[room_name].get('rank')
                            started_at_str = ""
                            if is_live:
                                started_at_ts = onlives_rooms.get(int(room_id), {}).get('started_at')
                                if started_at_ts:
                                    started_at_dt = datetime.datetime.fromtimestamp(started_at_ts, JST)
                                    started_at_str = started_at_dt.strftime("%Y/%m/%d %H:%M")

                            data_to_display.append({
                                "配信中": "🔴",
                                "ルーム名": room_name,
                                "現在の順位": rank,
                                "現在のポイント": "N/A",
                                "上位とのポイント差": "N/A",
                                "下位とのポイント差": "N/A",
                                "配信開始時間": started_at_str
                            })
                            continue

                        if is_event_ended:
                            if room_id in final_ranking_data:
                                rank = final_ranking_data[room_id].get('rank', 'N/A')
                                point = final_ranking_data[room_id].get('point', 'N/A')
                                upper_gap, lower_gap = 0, 0

                                # [修正２] 「集計中」の表記の変更
                                if is_aggregating:
                                    # pointがNoneや'N/A'の場合は0として扱い、集計中であることを併記する
                                    point_str = str(point) if point is not None and point != 'N/A' else '0'
                                    point = f"{point_str}（※集計中）"

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
                                point = rank_info.get('point', 'N/A')
                                upper_gap = rank_info.get('upper_gap', 'N/A')
                                lower_gap = rank_info.get('lower_gap', 'N/A')
                                
                                if is_block_event:
                                    rank = block_event_ranks.get(room_id, 'N/A')
                                else:
                                    rank = rank_info.get('rank', 'N/A')
                            else:
                                st.warning(f"ルーム名 '{room_name}' のランキング情報が不完全です。スキップします。")
                                continue

                        started_at_str = ""
                        if is_live:
                            started_at_ts = onlives_rooms.get(int(room_id), {}).get('started_at')
                            if started_at_ts:
                                started_at_dt = datetime.datetime.fromtimestamp(started_at_ts, JST)
                                started_at_str = started_at_dt.strftime("%Y/%m/%d %H:%M")

                        data_to_display.append({
                            "配信中": "🔴" if is_live else "",
                            "ルーム名": room_name,
                            "現在の順位": rank,
                            "現在のポイント": point,
                            "上位とのポイント差": upper_gap,
                            "下位とのポイント差": lower_gap,
                            "配信開始時間": started_at_str
                        })
                    except Exception as e:
                        st.error(f"データ処理中に予期せぬエラーが発生しました（ルーム名: {room_name}）。エラー: {e}")
                        continue
                        
                if data_to_display:
                    df = pd.DataFrame(data_to_display)

                    # --- テーブル表示 ---
                    st.markdown("<h3 style='font-size:1.5em;'>比較したいルームのステータス</h3>", unsafe_allow_html=True)

                    # グラフ用にpointを数値化 (「集計中」の表記を含む場合は、計算できないため0とする)
                    def safe_point_to_numeric(point_val):
                        if isinstance(point_val, str) and '（※集計中）' in point_val:
                             # ポイント部分だけを抽出して数値に変換
                            try:
                                return pd.to_numeric(point_val.replace('（※集計中）', ''), errors='coerce')
                            except:
                                return 0
                        return pd.to_numeric(point_val, errors='coerce').fillna(0)

                    df['現在のポイント_numeric'] = df['現在のポイント'].apply(safe_point_to_numeric)
                    
                    # 順位とポイントでソートし直し
                    df = df.sort_values(by=['現在の順位', '現在のポイント_numeric'], ascending=[True, False]).drop(columns=['現在のポイント_numeric'])

                    # ランキング表示
                    st.dataframe(
                        df.style.apply(
                            lambda x: [f'color: {get_rank_color(r)}' for r in x] if x.name == '現在の順位' else [''], axis=0
                        ),
                        use_container_width=True
                    )
                    
                    # --- グラフ表示 ---
                    st.markdown("---")
                    st.markdown("<h3 style='font-size:1.5em;'>ポイント推移グラフ (最新)</h3>", unsafe_allow_html=True)

                    if '現在のポイント' in df.columns and df['現在のポイント'].astype(str).str.replace('（※集計中）', '').astype(str).str.replace('N/A', '0').astype(float).sum() > 0:
                        df_chart = df.copy()
                        # グラフ描画用にポイントを数値型に変換。集計中の表記がある場合は、表示上のポイントを抽出して使用。
                        df_chart['現在のポイント'] = df_chart['現在のポイント'].astype(str).str.replace('（※集計中）', '').astype(float, errors='ignore').fillna(0)
                        
                        color_map = {name: get_rank_color(rank) for name, rank in zip(df['ルーム名'], df['現在の順位'])}

                        fig_point = px.bar(
                            df_chart, x="ルーム名", y="現在のポイント", title="現在のポイント", color="ルーム名",
                            color_discrete_map=color_map, hover_data=["現在の順位", "現在のポイント"],
                            labels={"現在のポイント": "ポイント", "ルーム名": "ルーム名"}
                        )
                        st.plotly_chart(fig_point, use_container_width=True, key="point_chart")
                        fig_point.update_layout(uirevision="const")

                        # ポイント差グラフ
                        st.markdown("---")
                        st.markdown("<h3 style='font-size:1.5em;'>ポイント差グラフ</h3>", unsafe_allow_html=True)

                        # ポイント差の計算が0で固定されている場合、グラフは不要
                        if is_event_ended:
                            st.info("イベント終了後の最終ランキングデータでは、ポイント差のグラフは表示されません。")
                        elif len(st.session_state.selected_room_names) > 1 and "上位とのポイント差" in df.columns:
                            df['上位とのポイント差'] = pd.to_numeric(df['上位とのポイント差'], errors='coerce')
                            fig_upper_gap = px.bar(
                                df, x="ルーム名", y="上位とのポイント差", title="上位とのポイント差", color="ルーム名",
                                color_discrete_map=color_map, hover_data=["現在の順位", "現在のポイント"],
                                labels={"上位とのポイント差": "ポイント差", "ルーム名": "ルーム名"}
                            )
                            st.plotly_chart(fig_upper_gap, use_container_width=True, key="upper_gap_chart")
                            fig_upper_gap.update_layout(uirevision="const")

                            if "下位とのポイント差" in df.columns:
                                df['下位とのポイント差'] = pd.to_numeric(df['下位とのポイント差'], errors='coerce')
                                fig_lower_gap = px.bar(
                                    df, x="ルーム名", y="下位とのポイント差", title="下位とのポイント差", color="ルーム名",
                                    color_discrete_map=color_map, hover_data=["現在の順位", "現在のポイント"],
                                    labels={"下位とのポイント差": "ポイント差", "ルーム名": "ルーム名"}
                                )
                                st.plotly_chart(fig_lower_gap, use_container_width=True, key="lower_gap_chart")
                                fig_lower_gap.update_layout(uirevision="const")
                else:
                    st.warning("ポイントデータが存在しないため、グラフは表示できません。")

                    # --- スペシャルギフト履歴 ---
                    st.markdown("---")
                    st.markdown("<h3 style='font-size:1.5em;'>スペシャルギフト履歴</h3>", unsafe_allow_html=True)
                    st.info("リアルタイムイベント配信中のルームのみ、スペシャルギフトの履歴が表示されます。")

                    for room_name in df['ルーム名']:
                        try:
                            room_id = st.session_state.room_map_data[room_name]['room_id']
                            room_id_int = int(room_id)
                            
                            is_live = room_id_int in onlives_rooms
                            is_premium_live = is_live and onlives_rooms.get(room_id_int, {}).get('premium_room_type') == 1

                            if not is_live or is_premium_live:
                                continue

                            with st.expander(f"**{room_name} のスペシャルギフト履歴**"):
                                gift_list_map = get_gift_list(room_id)
                                gift_log = get_and_update_gift_log(room_id)
                                
                                if not gift_log:
                                    st.write("履歴が見つかりませんでした。配信中か確認してください。")
                                    continue

                                gift_data = []
                                total_special_gift_point = 0
                                for log in gift_log:
                                    gift_id = str(log.get('gift_id'))
                                    gift_name = gift_list_map.get(gift_id, {}).get('name', '不明なギフト')
                                    gift_point = gift_list_map.get(gift_id, {}).get('point', 0) * log.get('num', 0)
                                    
                                    if gift_point > 0:
                                        total_special_gift_point += gift_point
                                        
                                    created_at_dt = datetime.datetime.fromtimestamp(log.get('created_at', 0), JST)
                                    
                                    gift_data.append({
                                        '時刻': created_at_dt.strftime("%H:%M:%S"),
                                        'ギフト名': gift_name,
                                        '個数': log.get('num', 0),
                                        '合計ポイント': f"{gift_point:,}",
                                        'ユーザ名': log.get('user_name', 'N/A')
                                    })

                                st.write(f"**スペシャルギフト合計ポイント (累計): {total_special_gift_point:,} pt**")
                                df_gift = pd.DataFrame(gift_data)
                                st.dataframe(df_gift, use_container_width=True)

                        except Exception as e:
                            st.error(f"スペシャルギフト履歴の処理中にエラーが発生しました（ルーム名: {room_name}）。エラー: {e}")
                            
                    
if __name__ == '__main__':
    main()