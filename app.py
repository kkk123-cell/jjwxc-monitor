import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import os
import re
import json
import base64
from io import StringIO
from datetime import datetime, timedelta
import time
import concurrent.futures

st.set_page_config(page_title="晋江数据监测助手", page_icon="📚", layout="wide")
st.title("📚 晋江数据监测助手 (云端全功能版)")

# ================= 云端数据读写核心逻辑 =================
try:
    GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
    GITHUB_REPO = st.secrets["GITHUB_REPO"]
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    CLOUD_MODE = True
except:
    CLOUD_MODE = False
    headers = {}

FILE_BOOK = "data/我的监测数据.csv"
FILE_AUTHOR = "data/我的作收数据.csv"
FILE_RANK = "data/榜单数据.csv"
FILE_CHAPTER = "data/章节数据.csv"

def load_df(file_path):
    if CLOUD_MODE:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_path}"
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            content = base64.b64decode(r.json()["content"]).decode("utf-8-sig")
            return pd.read_csv(StringIO(content))
        return pd.DataFrame()
    else:
        if os.path.exists(file_path):
            try: return pd.read_csv(file_path, encoding='utf-8-sig')
            except: return pd.DataFrame()
        return pd.DataFrame()

def save_df(df, file_path):
    if CLOUD_MODE:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_path}"
        r = requests.get(url, headers=headers)
        sha = r.json()["sha"] if r.status_code == 200 else None
        content = df.to_csv(index=False).encode("utf-8-sig")
        encoded = base64.b64encode(content).decode("utf-8")
        data = {"message": "Update data", "content": encoded}
        if sha: data["sha"] = sha
        requests.put(url, json=data, headers=headers)
    else:
        df.to_csv(file_path, index=False, encoding='utf-8-sig')

def save_record(record_dict, file_path):
    df = load_df(file_path)
    df_new = pd.DataFrame([record_dict])
    df = pd.concat([df, df_new], ignore_index=True)
    save_df(df, file_path)

def delete_record(id_col, target_id, file_path, source_col=None, source_val=None):
    df = load_df(file_path)
    if not df.empty:
        if source_col and source_val:
            df = df[(df[id_col].astype(str) != str(target_id)) | (df[source_col] != source_val)]
        else:
            df = df[df[id_col].astype(str) != str(target_id)]
        save_df(df, file_path)

# ================= 爬虫模块 =================
src_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

def fetch_book_data(novel_id):
    url = f"http://www.jjwxc.net/onebook.php?novelid={novel_id}"
    try:
        resp = requests.get(url, headers=src_headers, timeout=10)
        resp.encoding = 'gb18030'
        soup = BeautifulSoup(resp.text, 'html.parser')
        title_tag = soup.find('h1'); collect_tag = soup.find('span', itemprop='collectedCount')
        author_tag = soup.find('span', itemprop='author'); click_tag = soup.find('span', itemprop='clickCount')
        vip_match = re.search(r'霸王票：.*?(\d+)', soup.get_text())
        vip_ticket = int(vip_match.group(1)) if vip_match else 0
        if title_tag and collect_tag:
            return {"书号": str(novel_id), "书名": title_tag.text.strip(), "收藏数": int(collect_tag.text.strip()),
                    "作者": author_tag.text.strip() if author_tag else "未知",
                    "点击数": int(click_tag.text.strip()) if click_tag else 0, "霸王票": vip_ticket}
    except: pass
    return None

def fetch_author_info(author_id):
    url = f"http://www.jjwxc.net/oneauthor.php?authorid={author_id}"
    try:
        resp = requests.get(url, headers=src_headers, timeout=10)
        resp.encoding = 'gb18030'
        soup = BeautifulSoup(resp.text, 'html.parser')
        title_tag = soup.find('title')
        aname = title_tag.text.split('的专栏')[0].replace('晋江文学城', '').strip() if title_tag else f"作者_{author_id}"
        collect_match = re.search(r'被收藏数[：:]\s*(\d+)', resp.text)
        collects = int(collect_match.group(1)) if collect_match else 0
        works = []
        for link in soup.find_all('a'):
            match = re.search(r'novelid=(\d+)', link.get('href', ''))
            if match and match.group(1) not in works and len(match.group(1)) > 5: works.append(match.group(1))
        return {"name": aname, "collects": collects, "works": works}
    except: return None

def fetch_chapter_clicks(novel_id):
    api_url = f"http://s8-static.jjwxc.net/getnovelclick.php?novelid={novel_id}&jsonpcallback=novelclick"
    try:
        resp = requests.get(api_url, headers=src_headers, timeout=10)
        resp.encoding = 'gb18030'
        json_match = re.search(r'novelclick\((.*)\)', resp.text)
        if json_match:
            return {int(k): int(v) for k, v in json.loads(json_match.group(1)).items()}
    except: pass
    return None

def fetch_ranking_books(orderstr, t="0"):
    url = f"http://www.jjwxc.net/topten.php?orderstr={orderstr}&t={t}"
    try:
        resp = requests.get(url, headers=src_headers, timeout=15)
        resp.encoding = 'gb18030'
        soup = BeautifulSoup(resp.text, 'html.parser')
        books = []; seen_ids = set()
        for link in soup.find_all('a'):
            match = re.search(r'novelid=(\d+)', link.get('href', ''))
            if match:
                nid = match.group(1)
                if link.text.strip() and nid not in seen_ids and len(nid) > 5:
                    seen_ids.add(nid); books.append({"novel_id": nid, "title": link.text.strip()})
        return books[:20]
    except: return None

# ================= 涨跌幅计算 =================
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
        item_id = row[id_col]; latest_time = row['时间_dt']; latest_val = row[val_col]
        hist = df[df[id_col] == item_id]
        target_1h = latest_time - timedelta(hours=1)
        past_1h = hist[hist['时间_dt'] <= target_1h]
        base_1h = past_1h.iloc[-1][val_col] if not past_1h.empty else hist.iloc[0][val_col]
        cycle_data = hist[hist['时间_dt'] >= cycle_start]
        base_cycle = cycle_data.iloc[0][val_col] if not cycle_data.empty else hist.iloc[0][val_col]
        row_dict = row.to_dict()
        row_dict['1H涨幅'] = latest_val - base_1h
        row_dict['本周涨幅'] = latest_val - base_cycle
        results.append(row_dict)
    return pd.DataFrame(results)

# ================= 侧边栏 =================
with st.sidebar:
    st.header("导航与操作")
    app_mode = st.radio("选择页面", ["📚 书架", "🏆 榜单监控", "👤 作者专栏", "🔍 单书详情"])
    
    st.markdown("---")
    st.subheader("➕ 添加书籍")
    novel_id = st.text_input("输入书号(novelid)")
    if st.button("添加并抓取"):
        if novel_id:
            with st.spinner("抓取中..."):
                info = fetch_book_data(novel_id)
                if info:
                    save_record({"记录时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), **info, "来源": "手动添加"}, FILE_BOOK)
                    st.success("添加成功"); st.rerun()
    
    st.subheader("➕ 添加作者")
    author_id = st.text_input("输入作者ID")
    if st.button("添加作者及全部作品"):
        if author_id:
            with st.spinner("解析并抓取中..."):
                auth = fetch_author_info(author_id)
                if auth:
                    save_record({"记录时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "作者ID": str(author_id), "作者": auth['name'], "专栏收藏数": auth['collects']}, FILE_AUTHOR)
                    if auth['works']:
                        def process(nid):
                            inf = fetch_book_data(nid)
                            if inf: return {"记录时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), **inf, "来源": f"作者专栏: {auth['name']}"}
                        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
                            res = [r for r in ex.map(process, auth['works']) if r]
                        if res:
                            df_b = load_df(FILE_BOOK)
                            save_df(pd.concat([df_b, pd.DataFrame(res)], ignore_index=True), FILE_BOOK)
                    st.success("作者添加成功"); st.rerun()

# ================= 页面 1：书架 =================
if app_mode == "📚 书架":
    st.subheader("📚 我的书架")
    df_books = load_df(FILE_BOOK)
    if not df_books.empty:
        manual_df = df_books[df_books['来源'] == '手动添加'].copy()
        if not manual_df.empty:
            latest = calculate_metrics(manual_df, '书号', '收藏数')
            if not latest.empty:
                c1, c2, c3, c4, c5, c6 = st.columns([3, 2, 1.5, 1.5, 1.5, 1])
                c1.markdown("**书籍名称**"); c2.markdown("**作者**"); c3.markdown("**收藏数**"); c4.markdown("**1H涨幅**"); c5.markdown("**本周涨幅**"); c6.markdown("**操作**")
                st.markdown("---")
                for _, row in latest.iterrows():
                    col1, col2, col3, col4, col5, col6 = st.columns([3, 2, 1.5, 1.5, 1.5, 1])
                    col1.write(row['书名']); col2.write(row['作者']); col3.write(row['收藏数'])
                    col4.write(f"+{int(row['1H涨幅'])}" if row['1H涨幅'] > 0 else str(int(row['1H涨幅'])))
                    col5.write(f"+{int(row['本周涨幅'])}" if row['本周涨幅'] > 0 else str(int(row['本周涨幅'])))
                    if col6.button("❌", key=f"delb{row['书号']}"):
                        delete_record('书号', row['书号'], FILE_BOOK)
                        st.rerun()

# ================= 页面 2：榜单 =================
elif app_mode == "🏆 榜单监控":
    st.subheader("🏆 榜单实时监控")
    RANK_MAP = {"VIP金榜": {"o": "1", "t": "0"}, "新书千字榜(夹子)": {"o": "17", "t": "0"}, "纯爱VIP": {"o": "1", "t": "5"}, "言情VIP": {"o": "1", "t": "1"}, "百合VIP": {"o": "1", "t": "9"}}
    sel_rank = st.selectbox("选择榜单", list(RANK_MAP.keys()))
    if st.button(f"抓取前20名"):
        books = fetch_ranking_books(RANK_MAP[sel_rank]["o"], RANK_MAP[sel_rank]["t"])
        if books:
            def process(b):
                inf = fetch_book_data(b['novel_id'])
                if inf: return {"记录时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "榜单": sel_rank, **inf}
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
                res = [r for r in ex.map(process, books) if r]
            if res:
                df_r = load_df(FILE_RANK)
                save_df(pd.concat([df_r, pd.DataFrame(res)], ignore_index=True), FILE_RANK)
                st.success("抓取成功"); st.rerun()
    
    df_rank = load_df(FILE_RANK)
    if not df_rank.empty:
        cur = df_rank[df_rank['榜单'] == sel_rank]
        if not cur.empty:
            lat = calculate_metrics(cur, '书号', '收藏数')
            st.dataframe(lat[['书名', '作者', '收藏数', '1H涨幅', '本周涨幅']].sort_values('本周涨幅', ascending=False), use_container_width=True, hide_index=True)

# ================= 页面 3：作者 =================
elif app_mode == "👤 作者专栏":
    st.subheader("👤 作者作收监控")
    df_auth = load_df(FILE_AUTHOR)
    if not df_auth.empty:
        lat_a = calculate_metrics(df_auth, '作者ID', '专栏收藏数')
        for _, row in lat_a.iterrows():
            c1, c2, c3, c4, c5 = st.columns([3, 1.5, 1.5, 1.5, 1])
            c1.markdown(f"**👤 {row['作者']}**"); c2.write(f"作收:{row['专栏收藏数']}")
            c3.write(f"1H:{int(row['1H涨幅'])}"); c4.write(f"周:{int(row['本周涨幅'])}")
            if c5.button("❌", key=f"dela{row['作者ID']}"):
                delete_record('作者ID', row['作者ID'], FILE_AUTHOR)
                delete_record('来源', f"作者专栏: {row['作者']}", FILE_BOOK, '来源', f"作者专栏: {row['作者']}")
                st.rerun()
            with st.expander("作品详情"):
                df_b = load_df(FILE_BOOK)
                ab = df_b[df_b['来源'] == f"作者专栏: {row['作者']}"]
                if not ab.empty:
                    lb = calculate_metrics(ab, '书号', '收藏数')
                    st.dataframe(lb[['书名', '收藏数', '1H涨幅', '本周涨幅']], use_container_width=True, hide_index=True)

# ================= 页面 4：单书详情 =================
elif app_mode == "🔍 单书详情":
    st.subheader("🔍 单本小说数据剖面")
    df_books = load_df(FILE_BOOK)
    if not df_books.empty:
        book_options = df_books.drop_duplicates('书号', keep='last')
        book_select = st.selectbox("选择要查看的书籍", book_options['书名'] + " (" + book_options['书号'].astype(str) + ")")
        if book_select:
            target_id = book_select.split("(")[-1].strip(")")
            target_df = df_books[df_books['书号'].astype(str) == target_id]
            if not target_df.empty:
                latest = target_df.iloc[-1]
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("当前收藏", latest['收藏数']); c2.metric("当前总点击", latest['点击数'])
                c3.metric("霸王票估算", f"{latest['霸王票']} RMB"); c4.metric("作者", latest['作者'])
            
            st.markdown("---")
            st.markdown("### 📖 章节点击与留存")
            if st.button("抓取最新章节数据"):
                with st.spinner("正在获取章节数据..."):
                    chap_data = fetch_chapter_clicks(target_id)
                    if chap_data:
                        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        records = []
                        for chap_no, clicks in sorted(chap_data.items()):
                            records.append({"记录时间": now, "书号": target_id, "章节": f"第{chap_no}章", "点击": clicks})
                        df_chap_old = load_df(FILE_CHAPTER)
                        save_df(pd.concat([df_chap_old, pd.DataFrame(records)], ignore_index=True), FILE_CHAPTER)
                        st.success("章节数据抓取完毕"); st.rerun()

            df_chap = load_df(FILE_CHAPTER)
            if not df_chap.empty:
                target_chap = df_chap[df_chap['书号'].astype(str) == target_id].copy()
                if not target_chap.empty:
                    target_chap['章节号'] = target_chap['章节'].str.extract(r'第(\d+)章').astype(int)
                    target_chap = target_chap.sort_values(['章节号', '记录时间'])
                    target_chap['上次点击'] = target_chap.groupby('章节号')['点击'].shift(1)
                    target_chap['新增点击'] = (target_chap['点击'] - target_chap['上次点击']).fillna(0).astype(int)
                    
                    latest_chap = target_chap.drop_duplicates('章节号', keep='last').copy()
                    first_3 = latest_chap[latest_chap['章节号'].isin([1, 2, 3])]
                    latest_chapter = latest_chap.iloc[-1]
                    first_chapter_click = latest_chap.iloc[0]['点击']
                    
                    st.markdown(f"#### 🔍 核心数据")
                    col_a, col_b, col_c = st.columns(3)
                    if len(first_3) >= 3:
                        retention_3 = (first_3[first_3['章节号'] == 3]['点击'].values[0] / first_3[first_3['章节号'] == 1]['点击'].values[0]) * 100
                        col_a.metric("前三章留存率", f"{retention_3:.2f}%")
                    else:
                        col_a.metric("前三章留存率", "数据不足")
                    retention_latest = (latest_chapter['点击'] / first_chapter_click) * 100 if first_chapter_click > 0 else 0
                    col_b.metric("最新章留存率", f"{retention_latest:.2f}%")
                    col_c.metric("第一章总点击", first_chapter_click)
                    
                    display_chap = latest_chap[['章节', '点击', '新增点击']].copy()
                    display_chap['累计留存率'] = (display_chap['点击'] / first_chapter_click * 100).round(2).astype(str) + '%'
                    display_chap.columns = ['章节', '当前总点击', '本次新增点击', '相对第一章留存率']
                    st.dataframe(display_chap, use_container_width=True, hide_index=True)