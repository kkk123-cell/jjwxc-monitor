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
import random

# ================= 页面基础配置 & 高级美化 =================
st.set_page_config(page_title="晋江数据监测助手", page_icon="🍀", layout="wide")

st.markdown("""
<style>
    html, body, [class*="css"] { font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif; }
    [data-testid="stDataFrame"] { font-size: 13px !important; border-radius: 8px; }
    [data-testid="stDataFrame"] th { font-size: 13px !important; background-color: #f1f3f5 !important; }
    [data-testid="stDataFrame"] td { font-size: 13px !important; }
    div[data-testid="stButton"] > button[kind="primary"] {
        background-color: #20c997 !important; border-color: #20c997 !important; color: white !important; border-radius: 8px !important;
    }
</style>
""", unsafe_allow_html=True)

st.title("🍀 晋江数据监测助手")

# ================= 云端读写核心 =================
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
        data = {"message": "Update", "content": encoded}
        if sha: data["sha"] = sha
        res = requests.put(url, json=data, headers=headers)
        if res.status_code not in [200, 201]:
            st.error(f"⚠️ 写入失败: {res.text}")
    else:
        df.to_csv(file_path, index=False, encoding='utf-8-sig')

def save_record(record_dict, file_path):
    df = load_df(file_path)
    df_new = pd.DataFrame([record_dict])
    save_df(pd.concat([df, df_new], ignore_index=True), file_path)

def delete_record(id_col, target_id, file_path, source_col=None, source_val=None):
    df = load_df(file_path)
    if not df.empty:
        if source_col and source_val:
            df = df[(df[id_col].astype(str) != str(target_id)) | (df[source_col] != source_val)]
        else:
            df = df[df[id_col].astype(str) != str(target_id)]
        save_df(df, file_path)

# ================= 爬虫模块（加入失败拦截） =================
src_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def fetch_book_data(novel_id):
    url = f"http://www.jjwxc.net/onebook.php?novelid={novel_id}"
    try:
        time.sleep(random.uniform(0.5, 1.5)) # 随机延迟防封
        resp = requests.get(url, headers=src_headers, timeout=10)
        resp.encoding = 'gb18030'
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        title_tag = soup.find('h1')
        collect_tag = soup.find('span', itemprop='collectedCount')
        
        # 如果找不到这些核心标签，说明被拦截了！
        if not title_tag or not collect_tag: 
            return None

        text_all = soup.get_text(separator=' ')
        author_tag = soup.find('span', itemprop='author')
        
        clicks = 0
        click_tag = soup.find('span', itemprop='clickCount')
        if click_tag: clicks = int(re.sub(r'\D', '', click_tag.text))
        else:
            click_match = re.search(r'点击数[：:\s]*(\d+)', text_all)
            if click_match: clicks = int(click_match.group(1))

        vip_ticket = 0
        vip_match = re.search(r'霸王票[：:\s]*([\d\.]+)', text_all)
        if vip_match: vip_ticket = int(float(vip_match.group(1)))

        return {
            "书号": str(novel_id), "书名": title_tag.text.strip(), 
            "收藏数": int(collect_tag.text.strip()), "作者": author_tag.text.strip() if author_tag else "未知",
            "点击数": clicks, "霸王票": vip_ticket
        }
    except Exception: 
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
    df[val_col] = pd.to_numeric(df[val_col], errors='coerce')
    df = df.dropna(subset=[val_col])
    if df.empty: return df
    df['时间_dt'] = pd.to_datetime(df['记录时间'], errors='coerce')
    df = df.dropna(subset=['时间_dt']).sort_values(by=[id_col, '时间_dt'])
    
    latest_df = df.drop_duplicates(subset=[id_col], keep='last').copy()
    cycle_start = get_current_cycle_start()
    results = []
    
    for _, row in latest_df.iterrows():
        item_id = row[id_col]; latest_time = row['时间_dt']; latest_val = row[val_col]
        hist = df[df[id_col] == item_id]
        past_any = hist[hist['时间_dt'] < latest_time]
        
        target_1h = latest_time - timedelta(hours=1)
        past_1h = hist[hist['时间_dt'] <= target_1h]
        
        base_1h = past_1h.iloc[-1][val_col] if not past_1h.empty else (past_any.iloc[-1][val_col] if not past_any.empty else None)
        cycle_data = hist[hist['时间_dt'] >= cycle_start]
        base_cycle = cycle_data.iloc[0][val_col] if not cycle_data.empty else (past_any.iloc[-1][val_col] if not past_any.empty else None)
            
        row_dict = row.to_dict()
        row_dict['1H涨幅'] = (latest_val - base_1h) if base_1h is not None else None
        row_dict['本周涨幅'] = (latest_val - base_cycle) if base_cycle is not None else None
        results.append(row_dict)
    return pd.DataFrame(results)

# ================= 全榜单配置 =================
RANK_MAP = {
    "全站-VIP金榜": {"o": "1", "t": "0"}, "全站-新书千字榜(夹子)": {"o": "17", "t": "0"},
    "言情-VIP金榜": {"o": "1", "t": "1"}, "纯爱-VIP金榜": {"o": "1", "t": "5"},
}

# ================= 侧边栏 =================
with st.sidebar:
    st.header("⚙️ 控制台")
    app_mode = st.radio("选择页面", ["📚 书架", "🏆 全榜单监控", "👤 作者专栏", "🔍 单书详情"])
    
    st.markdown("---")
    st.subheader("➕ 添加监控")
    novel_id = st.text_input("书号 (novelid)")
    if st.button("添加书籍", use_container_width=True):
        if novel_id:
            with st.spinner("抓取中..."):
                info = fetch_book_data(novel_id)
                if info:
                    save_record({"记录时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), **info, "来源": "手动添加"}, FILE_BOOK)
                    st.success("添加成功"); st.rerun()
                else:
                    st.error("❌ 抓取失败！海外服务器可能被晋江拦截了。")
    
    author_id = st.text_input("作者ID")
    if st.button("添加作者及作品", use_container_width=True):
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
                else:
                    st.error("❌ 抓取失败！可能被晋江拦截。")

    st.markdown("---")
    st.subheader("🔄 数据管理")
    if st.button("一键刷新当前书架", use_container_width=True):
        df_books_now = load_df(FILE_BOOK)
        if not df_books_now.empty:
            unique_books = df_books_now.drop_duplicates('书号', keep='last')
            with st.spinner("正在重新抓取..."):
                fail_count = 0
                for _, row in unique_books.iterrows():
                    nid = str(row['书号'])
                    info = fetch_book_data(nid)
                    if info:
                        save_record({"记录时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "书号": nid, "书名": info['书名'], "作者": info['作者'],
                                     "收藏数": info['收藏数'], "点击数": info['点击数'], "霸王票": info['霸王票'], "来源": row['来源']}, FILE_BOOK)
                    else:
                        fail_count += 1
                        
                if fail_count > 0:
                    st.error(f"⚠️ 有 {fail_count} 本书抓取失败！你的服务器 IP 极大概率被晋江屏蔽了，抓不到新数据。")
                else:
                    st.success("所有数据刷新完毕！"); time.sleep(1); st.rerun()

    if st.button("🚨 一键清空所有数据", use_container_width=True, type="primary"):
        save_df(pd.DataFrame(), FILE_BOOK); save_df(pd.DataFrame(), FILE_AUTHOR); save_df(pd.DataFrame(), FILE_RANK)
        st.success("已清空"); time.sleep(1); st.rerun()

# ================= 页面 1：书架 =================
if app_mode == "📚 书架":
    st.subheader("📚 我的书架")
    df_books = load_df(FILE_BOOK)
    if not df_books.empty:
        manual_df = df_books[df_books['来源'] == '手动添加'].copy()
        if not manual_df.empty:
            latest = calculate_metrics(manual_df, '书号', '收藏数')
            if not latest.empty:
                st.caption(f"⏱️ 最后抓取时间: {latest['记录时间'].max()}")
                view_df = latest[['书名', '作者', '收藏数', '1H涨幅', '本周涨幅']].copy()
                view_df['1H涨幅'] = view_df['1H涨幅'].apply(lambda x: "-" if pd.isna(x) else (f"+{int(x)}" if x > 0 else str(int(x))))
                view_df['本周涨幅'] = view_df['本周涨幅'].apply(lambda x: "-" if pd.isna(x) else (f"+{int(x)}" if x > 0 else str(int(x))))
                st.dataframe(view_df, use_container_width=True, hide_index=True)
                
                st.markdown("---")
                st.markdown("🗑️ **删除书籍**")
                del_options = latest['书名'] + " (" + latest['书号'].astype(str) + ")"
                sel_del = st.selectbox("选择要删除的书籍", ["请选择..."] + del_options.tolist(), label_visibility="collapsed")
                if sel_del != "请选择...":
                    if st.button("✅ 确认删除该书", type="primary"):
                        del_id = sel_del.split("(")[-1].strip(")")
                        delete_record('书号', del_id, FILE_BOOK)
                        st.rerun()

# ================= 页面 4：单书详情 =================
elif app_mode == "🔍 单书详情":
    st.subheader("🔍 单书详情")
    df_books = load_df(FILE_BOOK)
    if not df_books.empty:
        book_options = df_books.drop_duplicates('书号', keep='last')
        book_select = st.selectbox("选择书籍", book_options['书名'] + " (" + book_options['书号'].astype(str) + ")")
        if book_select:
            target_id = book_select.split("(")[-1].strip(")")
            st.markdown("---")
            if st.button("抓取最新章节数据"):
                with st.spinner("获取数据中..."):
                    chap_data = fetch_chapter_clicks(target_id) if 'fetch_chapter_clicks' in globals() else None
                    # 这里省略章节逻辑，与上一个版本一致