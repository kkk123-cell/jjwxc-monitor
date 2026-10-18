import streamlit as st
import pandas as pd
import os
import re
from datetime import datetime, timedelta

st.set_page_config(page_title="晋江数据监测助手", page_icon="📚", layout="wide")
st.title("📚 晋江数据监测助手 (云端版)")

DATA_DIR = "data"
FILE_BOOK = f"{DATA_DIR}/我的监测数据.csv"
FILE_AUTHOR = f"{DATA_DIR}/我的作收数据.csv"
FILE_RANK = f"{DATA_DIR}/榜单数据.csv"

def load_df(file_path):
    if os.path.exists(file_path):
        try:
            return pd.read_csv(file_path, encoding='utf-8-sig')
        except:
            return pd.DataFrame()
    return pd.DataFrame()

def get_current_cycle_start():
    now = datetime.now()
    days_since_thursday = (now.weekday() - 3) % 7
    thursday = now - timedelta(days=days_since_thursday)
    cycle_start = thursday.replace(hour=12, minute=0, second=0, microsecond=0)
    if now < cycle_start: cycle_start -= timedelta(days=7)
    return cycle_start

def calculate_metrics(df, id_col, val_col):
    if df.empty: return df
    df = df.copy()
    df['时间_dt'] = pd.to_datetime(df['记录时间'])
    df = df.sort_values(by=[id_col, '时间_dt'])
    latest_df = df.drop_duplicates(subset=[id_col], keep='last').copy()
    cycle_start = get_current_cycle_start()
    results = []
    for _, row in latest_df.iterrows():
        item_id = row[id_col]
        latest_time = row['时间_dt']
        latest_val = row[val_col]
        hist = df[df[id_col] == item_id]
        target_1h_time = latest_time - timedelta(hours=1)
        past_1h_data = hist[hist['时间_dt'] <= target_1h_time]
        base_1h_val = past_1h_data.iloc[-1][val_col] if not past_1h_data.empty else hist.iloc[0][val_col]
        growth_1h = latest_val - base_1h_val
        cycle_data = hist[hist['时间_dt'] >= cycle_start]
        base_cycle_val = cycle_data.iloc[0][val_col] if not cycle_data.empty else hist.iloc[0][val_col]
        growth_cycle = latest_val - base_cycle_val
        row_dict = row.to_dict()
        row_dict['1H涨幅'] = growth_1h
        row_dict['本周涨幅'] = growth_cycle
        results.append(row_dict)
    return pd.DataFrame(results)

# 这里只做展示，不再有添加抓取按钮（因为是云端自动抓的）
st.info("💡 提示：此版本数据由 GitHub 云端自动抓取，这里仅作展示。")

app_mode = st.sidebar.radio("选择页面", ["📚 书架", "🏆 榜单监控", "👤 作者专栏"])

if app_mode == "📚 书架":
    st.subheader("📚 我的手动书架")
    df_books_all = load_df(FILE_BOOK)
    if not df_books_all.empty:
        manual_df = df_books_all[df_books_all['来源'] == '手动添加'].copy()
        if not manual_df.empty:
            latest = calculate_metrics(manual_df, '书号', '收藏数')
            if not latest.empty:
                view = latest[['书名', '作者', '收藏数', '1H涨幅', '本周涨幅']]
                st.dataframe(view, use_container_width=True, hide_index=True)
                chart_data = manual_df.pivot_table(index='记录时间', columns='书名', values='收藏数', aggfunc='last')
                st.line_chart(chart_data)

elif app_mode == "👤 作者专栏":
    st.subheader("👤 作者作收监控")
    df_auth = load_df(FILE_AUTHOR)
    if not df_auth.empty:
        latest_auth = calculate_metrics(df_auth, '作者ID', '专栏收藏数')
        st.dataframe(latest_auth[['作者', '专栏收藏数', '1H涨幅', '本周涨幅']], use_container_width=True, hide_index=True)