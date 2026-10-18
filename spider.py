import requests
from bs4 import BeautifulSoup
import pandas as pd
import os
import re
import json
from datetime import datetime
import concurrent.futures

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

FILE_BOOK = f"{DATA_DIR}/我的监测数据.csv"
FILE_AUTHOR = f"{DATA_DIR}/我的作收数据.csv"
FILE_RANK = f"{DATA_DIR}/榜单数据.csv"

headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

# 全榜单配置（与 app.py 保持一致）
RANK_MAP = {
    "全站-VIP金榜": {"o": "1", "t": "0"},
    "全站-收入金榜": {"o": "12", "t": "0"},
    "全站-新书千字榜(夹子)": {"o": "17", "t": "0"},
    "全站-季度排行": {"o": "2", "t": "0"},
    "全站-完结金榜": {"o": "18", "t": "0"},
    "言情-VIP金榜": {"o": "1", "t": "1"},
    "纯爱-VIP金榜": {"o": "1", "t": "5"},
    "百合-VIP金榜": {"o": "1", "t": "9"},
    "无CP-VIP金榜": {"o": "1", "t": "13"},
    "衍生-新书千字榜": {"o": "17", "t": "10"},
    "言情-季度排行": {"o": "2", "t": "1"},
    "纯爱-季度排行": {"o": "2", "t": "5"},
}

def fetch_book_data(novel_id):
    url = f"http://www.jjwxc.net/onebook.php?novelid={novel_id}"
    try:
        resp = requests.get(url, headers=headers, timeout=10)
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
        resp = requests.get(url, headers=headers, timeout=10)
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
        resp = requests.get(url, headers=headers, timeout=15)
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

def save_record(record_dict, file_path):
    df_new = pd.DataFrame([record_dict])
    file_exists = os.path.exists(file_path)
    df_new.to_csv(file_path, mode='a', header=not file_exists, index=False, encoding='utf-8-sig')

def run_job():
    print("开始抓取全榜单与书架数据...")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 1. 抓取全榜单
    for rank_name, params in RANK_MAP.items():
        print(f"  抓取榜单: {rank_name}")
        books = fetch_ranking_books(params["o"], params["t"])
        if books:
            def process(b):
                inf = fetch_book_data(b['novel_id'])
                if inf: return {"记录时间": now, "榜单": rank_name, **inf}
                return None
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
                res = [r for r in ex.map(process, books) if r]
            for r in res:
                save_record(r, FILE_RANK)
    
    # 2. 刷新书架中手动添加的书
    if os.path.exists(FILE_BOOK):
        df_b = pd.read_csv(FILE_BOOK, encoding='utf-8-sig')
        if not df_b.empty:
            unique_books = df_b.drop_duplicates('书号', keep='last')
            print(f"  刷新书架 {len(unique_books)} 本书")
            for _, row in unique_books.iterrows():
                nid = str(row['书号'])
                info = fetch_book_data(nid)
                if info:
                    save_record({"记录时间": now, "书号": nid, "书名": info['书名'], "作者": info['作者'],
                                 "收藏数": info['收藏数'], "点击数": info['点击数'], "霸王票": info['霸王票'], "来源": row['来源']}, FILE_BOOK)
    
    # 3. 刷新作者作收
    if os.path.exists(FILE_AUTHOR):
        df_a = pd.read_csv(FILE_AUTHOR, encoding='utf-8-sig')
        if not df_a.empty:
            unique_auth = df_a.drop_duplicates('作者ID', keep='last')
            print(f"  刷新作者 {len(unique_auth)} 位")
            for _, row in unique_auth.iterrows():
                auth = fetch_author_info(str(row['作者ID']))
                if auth:
                    save_record({"记录时间": now, "作者ID": str(row['作者ID']), "作者": auth['name'], "专栏收藏数": auth['collects']}, FILE_AUTHOR)
    
    print("全部抓取完成！")

if __name__ == "__main__":
    run_job()