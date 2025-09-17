import streamlit as st
import requests
import pandas as pd
import time
import datetime
import plotly.express as px
import pytz
from streamlit_autorefresh import st_autorefresh
from datetime import timedelta
import logging

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
    """
    開催中および終了済みのイベントリストを取得する。
    終了済みイベントには "＜終了＞" という接頭辞を付ける。
    """
    all_events = []
    # status=1 (開催中) と status=4 (終了済み) の両方を取得
    for status in [1, 4]:
        page = 1
        # 各ステータスで最大10ページまで取得
        for _ in range(10):
            url = f"https://www.showroom-live.com/api/event/search?status={status}&page={page}"
            try:
                response = requests.get(url, headers=HEADERS, timeout=5)
                response.raise_for_status()
                data = response.json()
                
                page_events = []
                if isinstance(data, dict):
                    if 'events' in data and isinstance(data['events'], list):
                        page_events.extend(data['events'])
                    for event_type in ['official_lives', 'talent_lives', 'amateur_lives']:
                        if event_type in data and isinstance(data.get(event_type), list):
                            page_events.extend(data[event_type])

                if not page_events:
                    break

                for event in page_events:
                    if 'event_name' in event and 'event_url_key' in event:
                        event['event_type'] = status
                        # イベントIDをURLから抽出
                        event_id_match = event['event_url_key']
                        event['event_id'] = event_id_match
                        all_events.append(event)
                
                page += 1
            except requests.exceptions.RequestException as e:
                logging.error(f"イベントリスト取得中にエラーが発生しました: {e}")
                break
            except (ValueError, TypeError) as e:
                logging.error(f"JSON解析エラー: {e}")
                break

    # 重複を削除し、終了済みイベントに接頭辞を付ける
    unique_events = {event['event_id']: event for event in all_events}
    sorted_events = []
    
    # 開催中を優先的にリストに追加
    for event in all_events:
        if event['event_type'] == 1 and event['event_id'] in unique_events:
            sorted_events.append(unique_events.pop(event['event_id']))

    # 終了済みをリストに追加し、接頭辞を付ける
    for event_id in list(unique_events.keys()):
        event = unique_events[event_id]
        if event['event_type'] == 4:
            event['event_name'] = f"＜終了＞ {event['event_name']}"
            sorted_events.append(event)

    return sorted_events

def get_event_rankings(event_id):
    """
    指定されたイベントIDのランキング情報を取得する。
    """
    now_jst = datetime.datetime.now(JST)
    url = f"https://www.showroom-live.com/api/event/{event_id}/ranking"
    
    df_ranking = pd.DataFrame()
    page = 1
    
    while True:
        try:
            response = requests.get(f"{url}?page={page}", headers=HEADERS, timeout=5)
            response.raise_for_status()
            data = response.json()
            
            if 'ranking' not in data or not data['ranking']:
                break
                
            df_page = pd.DataFrame(data['ranking'])
            df_ranking = pd.concat([df_ranking, df_page], ignore_index=True)
            page += 1
        except requests.exceptions.RequestException as e:
            logging.error(f"ランキング情報取得中にエラーが発生しました: {e}")
            break
        except (ValueError, TypeError) as e:
            logging.error(f"JSON解析エラー: {e}")
            break
            
    if not df_ranking.empty:
        df_ranking = df_ranking.rename(columns={
            'rank': '現在の順位',
            'room_name': 'ルーム名',
            'room_url_key': 'ルームURLキー',
            'score': '現在のポイント',
            'user_id': 'ユーザーID'
        })
        
    return df_ranking

def display_event_list(events):
    """
    イベントリストをドロップダウンメニューに表示する。
    """
    event_dict = {event['event_name']: event for event in events}
    event_names = list(event_dict.keys())
    
    selected_event_name = st.selectbox(
        "イベントを選択してください:",
        event_names,
        index=0,
        key="event_select"
    )
    
    selected_event_info = event_dict.get(selected_event_name)
    return selected_event_info

# --- main ---
st.markdown("<h1 style='font-size:2.5em;'>🎤 SHOWROOM イベントダッシュボード</h1>", unsafe_allow_html=True)
st.write("選択したSHOWROOMイベントのランキングと、注目ルームのポイント推移をリアルタイムで表示します。")

st_autorefresh(interval=30000, key="refresh_dashboard")

# イベント選択
st.markdown("### イベント選択")
all_events = get_events()
selected_event = display_event_list(all_events)

if selected_event:
    event_id = selected_event['event_id']
    event_name = selected_event['event_name']
    is_closed = selected_event.get('is_closed', False)
    event_end_time_ts = selected_event.get('ended_at')
    
    st.markdown(f"**選択中のイベント:** {event_name}")

    st.markdown("---")
    st.markdown("<h2 style='font-size:2em;'>📊 リアルタイム・ダッシュボード</h2>", unsafe_allow_html=True)
    st.markdown(f"**最終更新日時 (日本時間): {datetime.datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')}**")
    
    # 選択ルーム
    st.markdown("### 注目ルーム選択")
    # `st.session_state`の初期化
    if 'selected_room_names' not in st.session_state:
        st.session_state.selected_room_names = []

    # ランキングデータ取得
    df_ranking = get_event_rankings(event_id)
    
    is_event_ended = event_end_time_ts and datetime.datetime.fromtimestamp(event_end_time_ts, JST) < datetime.datetime.now(JST)

    # 修正箇所: ポイントを「集計中」に変換するロジック
    if not df_ranking.empty and is_event_ended and not is_closed:
        df_ranking['現在のポイント'] = '集計中'
    
    if not df_ranking.empty:
        # ランキング表示
        st.markdown("### 📈 イベントランキング")
        df_ranking_display = df_ranking.copy()
        
        # `st.data_editor`でルーム名を選択
        st.session_state.selected_room_names = st.data_editor(
            df_ranking_display[['現在の順位', 'ルーム名', '現在のポイント']],
            hide_index=True,
            use_container_width=True,
            column_config={
                "現在の順位": st.column_config.NumberColumn(
                    "順位", help="イベント内での現在の順位", width="small"
                ),
                "ルーム名": st.column_config.TextColumn(
                    "ルーム名", help="ライバーのルーム名", width="large"
                ),
                "現在のポイント": st.column_config.NumberColumn(
                    "ポイント", help="現在のポイント", format="%d" if not any(df_ranking['現在のポイント'].astype(str).str.contains('集計中')) else ""
                ),
            },
            on_select="select",
            selection_mode="multi-select"
        )['ルーム名'].tolist()
        
        # グラフ描画
        # ポイントが数字の場合のみグラフを表示
        if not any(df_ranking['現在のポイント'].astype(str).str.contains('集計中')):
            df_ranking['現在のポイント'] = pd.to_numeric(df_ranking['現在のポイント'], errors='coerce')
            df_chart = df_ranking.head(10).copy()
            df_chart = df_chart.sort_values(by='現在のポイント', ascending=False)

            fig = px.bar(
                df_chart, x="ルーム名", y="現在のポイント", title="トップ10ルームのポイント", color="ルーム名",
                hover_data=["現在の順位"], labels={"現在のポイント": "ポイント", "ルーム名": "ルーム名"}
            )
            st.plotly_chart(fig, use_container_width=True, key="top_10_chart")

    else:
        st.info("このイベントのランキングは現在利用できません。")
    
    if st.session_state.selected_room_names:
        st.markdown("---")
        st.markdown("<h2 style='font-size:2em;'>📈 ポイント推移</h2>", unsafe_allow_html=True)
        st.info("この機能は、過去のポイント推移を表示するために、ここに新しいロジックを実装する必要があります。")
        st.markdown(f"選択ルーム: {', '.join(st.session_state.selected_room_names)}")
else:
    st.info("イベントを選択してください。")