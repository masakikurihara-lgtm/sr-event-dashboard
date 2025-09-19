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
                    if "events" in data:
                        page_events = data["events"]
                    elif "event_list" in data:
                        page_events = data["event_list"]
                elif isinstance(data, list):
                    page_events = data

                if not page_events:
                    break

                for event in page_events:
                    event_id = event.get('event_id')
                    event_name = event.get('event_name')
                    if event_id and event_name:
                        if status == 4:
                            event_name = f"＜終了＞ {event_name}"
                        all_events.append({"event_id": event_id, "event_name": event_name})
                
                # 次のページが存在するか確認（ページングロジックの改善）
                if len(page_events) < 20: # ページあたりの最大件数が20のため
                    break
                page += 1
                
            except requests.exceptions.RequestException as e:
                st.error(f"イベントリストの取得中にエラーが発生しました: {e}")
                return []
    return all_events

@st.cache_data(ttl=60)
def get_room_list(event_id):
    """
    指定されたイベントIDの参加ルームリストを取得する。
    """
    url = f"https://www.showroom-live.com/api/event/room_ranking?event_id={event_id}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=5)
        response.raise_for_status()
        data = response.json()
        room_list = data.get("room_ranking_list", [])
        return room_list
    except requests.exceptions.RequestException as e:
        st.error(f"ルームリストの取得中にエラーが発生しました: {e}")
        return []

@st.cache_data(ttl=300)
def get_event_info(event_id):
    """
    イベント情報を取得する。
    """
    url = f"https://www.showroom-live.com/api/event/info?event_id={event_id}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"イベント情報の取得中にエラーが発生しました: {e}")
        return {}
        
@st.cache_data(ttl=60)
def get_gift_list():
    """
    ギフトリストを定期的に取得する
    """
    url = "https://www.showroom-live.com/api/live/gift_list"
    try:
        response = requests.get(url, headers=HEADERS, timeout=5)
        response.raise_for_status()
        data = response.json()
        return data.get("gift_list", [])
    except requests.exceptions.RequestException as e:
        st.error(f"ギフトリストの取得中にエラーが発生しました: {e}")
        return []

@st.cache_data(ttl=60)
def get_special_gifts(room_id, is_active=True):
    """
    特殊ギフトの履歴を取得する
    """
    if not is_active:
        return []
    
    url = f"https://www.showroom-live.com/api/live/stage_user_list?room_id={room_id}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=5)
        response.raise_for_status()
        data = response.json()
        special_gifts = data.get("special_gift_history", [])
        
        # タイムスタンプをJSTに変換
        for gift in special_gifts:
            if 'created_at' in gift and gift['created_at'] is not None:
                # APIのタイムスタンプはミリ秒単位
                created_at_dt = datetime.datetime.fromtimestamp(gift['created_at'] / 1000, tz=JST)
                gift['created_at_jst'] = created_at_dt.strftime('%H:%M:%S')
            else:
                gift['created_at_jst'] = 'N/A'
        
        return special_gifts
    except requests.exceptions.RequestException as e:
        return []

def get_gift_example_points(diff_points):
    """
    必要なポイント差からギフトの例を計算する
    連打倍率は考慮せず、ポイント単価のみで計算
    """
    # 課金アイテム(SRコイン)のポイントは、1G = 1pt
    gifts = [
        {"name": "星 (1G)", "point": 1},
        {"name": "ダルマ (10G)", "point": 10},
        {"name": "アイス (50G)", "point": 50},
        {"name": "くまのぬいぐるみ (100G)", "point": 100},
        {"name": "ペンギン (200G)", "point": 200},
        {"name": "ハート (300G)", "point": 300},
        {"name": "タワー (10000G)", "point": 10000},
        {"name": "レインボースター (2500pt)", "point": 2500},
        {"name": "SG (100G)", "point": 100},
        {"name": "SG (500G)", "point": 500},
        {"name": "SG (1000G)", "point": 1000},
        {"name": "SG (3000G)", "point": 3000},
        {"name": "SG (10000G)", "point": 10000},
        {"name": "SG (20000G)", "point": 20000},
        {"name": "SG (100000G)", "point": 100000},
    ]

    example_list = []
    for gift in gifts:
        required_count = diff_points / gift['point']
        example_list.append({
            "ギフト名": gift['name'],
            "必要な個数": f"{required_count:,.2f} 個"
        })
    return pd.DataFrame(example_list)

def main():
    st.title("🎤 SHOWROOM Event Dashboard")
    
    st.sidebar.header("設定")
    
    # ページ上部に最新情報を表示
    last_updated_time = datetime.datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
    st.sidebar.markdown(f"**最終更新:** {last_updated_time}")
    
    # 自動更新設定
    auto_refresh_sec = st.sidebar.slider("自動更新間隔 (秒)", 30, 300, 60)
    st_autorefresh(interval=auto_refresh_sec * 1000, key="data_refresh")

    event_list = get_events()
    event_names = [event["event_name"] for event in event_list]
    
    selected_event_name = st.sidebar.selectbox("イベントを選択", event_names)
    selected_event_id = None
    for event in event_list:
        if event["event_name"] == selected_event_name:
            selected_event_id = event["event_id"]
            break

    if selected_event_id:
        room_list = get_room_list(selected_event_id)
        if room_list:
            df = pd.DataFrame(room_list)
            df.rename(columns={
                "room_name": "ルーム名",
                "point": "現在のポイント",
                "rank": "現在の順位",
                "upper_gap": "上位とのポイント差",
                "lower_gap": "下位とのポイント差",
                "room_id": "room_id"
            }, inplace=True)
            df['現在のポイント'] = df['現在のポイント'].astype(int)
            df['現在の順位'] = df['現在の順位'].astype(int)
            
            # 複数ルームの選択
            st.session_state.selected_room_names = st.sidebar.multiselect(
                "表示するルームを選択",
                options=df["ルーム名"].unique(),
                default=df["ルーム名"].unique()[:min(len(df["ルーム名"]), 5)]
            )
            
            selected_df = df[df["ルーム名"].isin(st.session_state.selected_room_names)]
            
            # 順位表
            st.header("順位表")
            st.dataframe(selected_df.drop(columns=['room_id']), hide_index=True)
            
            # グラフ表示
            st.header("グラフ")
            
            # 各ルームに色を割り当てるための辞書を作成
            color_map = {name: f"#{hash(name) % 0xffffff:06x}" for name in selected_df["ルーム名"].unique()}
            
            if len(st.session_state.selected_room_names) > 0:
                fig_point = px.bar(
                    selected_df, x="ルーム名", y="現在のポイント", title="現在のポイント", color="ルーム名",
                    color_discrete_map=color_map, hover_data=["現在の順位", "現在のポイント"],
                    labels={"現在のポイント": "ポイント", "ルーム名": "ルーム名"}
                )
                st.plotly_chart(fig_point, use_container_width=True, key="point_chart")
                fig_point.update_layout(uirevision="const")

            if len(st.session_state.selected_room_names) > 1 and "上位とのポイント差" in df.columns:
                df['上位とのポイント差'] = pd.to_numeric(df['上位とのポイント差'], errors='coerce')
                fig_upper_gap = px.bar(
                    df, x="ルーム名", y="上位とのポイント差", title="上位とのポイント差", color="ルーム名",
                    color_discrete_map=color_map, hover_data=["現在の順位", "現在のポイント"],
                    labels={"上位とのポイント差": "ポイント差", "ルーム名": "ルーム名"}
                )
                st.plotly_chart(fig_upper_gap, use_container_width=True, key="upper_gap_chart")
                fig_upper_gap.update_layout(uirevision="const")

            if len(st.session_state.selected_room_names) > 1 and "下位とのポイント差" in df.columns:
                df['下位とのポイント差'] = pd.to_numeric(df['下位とのポイント差'], errors='coerce')
                fig_lower_gap = px.bar(
                    df, x="ルーム名", y="下位とのポイント差", title="下位とのポイント差", color="ルーム名",
                    color_discrete_map=color_map, hover_data=["現在の順位", "現在のポイント"],
                    labels={"下位とのポイント差": "ポイント差", "ルーム名": "ルーム名"}
                )
                st.plotly_chart(fig_lower_gap, use_container_width=True, key="lower_gap_chart")
                fig_lower_gap.update_layout(uirevision="const")
            
            # スペシャルギフト履歴
            st.header("スペシャルギフト履歴")
            if 'selected_room_id' not in st.session_state or st.session_state.selected_room_id not in df['room_id'].values:
                st.session_state.selected_room_id = df.loc[df['ルーム名'] == st.session_state.selected_room_names[0], 'room_id'].values[0] if len(st.session_state.selected_room_names) > 0 else None

            if st.session_state.selected_room_id:
                room_for_gift_history = st.selectbox(
                    "スペシャルギフト履歴を表示するルームを選択",
                    options=st.session_state.selected_room_names,
                    key="gift_history_room"
                )
                selected_room_id = df[df['ルーム名'] == room_for_gift_history]['room_id'].iloc[0]

                special_gifts = get_special_gifts(selected_room_id)
                if special_gifts:
                    gifts_df = pd.DataFrame(special_gifts)
                    gifts_df.rename(columns={
                        "gift_name": "ギフト名",
                        "num": "個数",
                        "point": "ポイント",
                        "sender_name": "贈った人",
                        "created_at_jst": "時刻"
                    }, inplace=True)
                    st.dataframe(gifts_df[["時刻", "ギフト名", "個数", "ポイント", "贈った人"]], hide_index=True)
                else:
                    st.info("スペシャルギフト履歴はありません。")

            # --- ここから「戦闘モード！」の機能を追加 ---
            st.header("戦闘モード！")
            st.info("ターゲットルームとのポイント差を計算し、必要なギフト例を表示します。")
            
            # 対象ルームの選択
            target_room_name = st.selectbox(
                "対象ルームを選択",
                options=df["ルーム名"].unique(),
                key="my_room_select"
            )
            
            # ターゲットルームの選択
            rival_room_name = st.selectbox(
                "ターゲットルームを選択",
                options=df["ルーム名"].unique(),
                key="rival_room_select"
            )
            
            # 対象ルームとターゲットルームの情報を取得
            my_room_info = df[df["ルーム名"] == target_room_name]
            rival_room_info = df[df["ルーム名"] == rival_room_name]

            if not my_room_info.empty and not rival_room_info.empty:
                my_point = my_room_info["現在のポイント"].iloc[0]
                my_rank = my_room_info["現在の順位"].iloc[0]
                
                rival_point = rival_room_info["現在のポイント"].iloc[0]
                rival_rank = rival_room_info["現在の順位"].iloc[0]
                
                # ポイント差の計算
                point_difference = rival_point - my_point
                
                # サブ情報の表示
                with st.expander("詳細情報", expanded=True):
                    cols_info = st.columns(3)
                    with cols_info[0]:
                        st.metric("現在の順位", f"{my_rank} 位")
                    with cols_info[1]:
                        st.metric("現在のポイント", f"{my_point:,} pt")
                    with cols_info[2]:
                        # 下位とのポイント差を計算
                        lower_gap_info = "N/A"
                        if my_rank < len(df):
                            lower_rank_point = df[df["現在の順位"] == my_rank + 1]["現在のポイント"].iloc[0]
                            lower_gap = my_point - lower_rank_point
                            lower_gap_info = f"{lower_gap:,} pt"
                        st.metric("下位とのポイント差", lower_gap_info)
                
                # ポイント差の表示
                st.subheader(f"「{rival_room_name}」とのポイント差")
                if point_difference > 0:
                    st.metric(f"必要なポイント", f"{point_difference:,} pt")
                else:
                    st.success(f"「{rival_room_name}」より {abs(point_difference):,} pt リードしています！")

                # 必要なギフト例の表示
                if point_difference > 0:
                    st.subheader("必要なギフト例")
                    st.warning("※連打数によるポイント変動は考慮していません。目安としてご利用ください。")
                    gift_examples_df = get_gift_example_points(point_difference)
                    st.dataframe(gift_examples_df, hide_index=True)
                
            # --- ここまで「戦闘モード！」の機能を追加 ---
            
        else:
            st.warning("このイベントに参加しているルームが見つかりません。")
    else:
        st.info("イベントを選択してください。")

if __name__ == "__main__":
    main()
