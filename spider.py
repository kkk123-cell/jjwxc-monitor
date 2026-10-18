import requests
from bs4 import BeautifulSoup
import pandas as pd
import os
import re
import json
from datetime import datetime
import concurrent.futures

# 统一存储路径
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

FILE_BOOK = f"{DATA_DIR}/我的监测数据.csv"
FILE_AUTHOR = f"{DATA_DIR}/我的作收数据.csv"
FILE_RANK = f"{DATA_DIR}/榜单数据.csv"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def fetch_book_data(novel_id):
    url = f"http://www.jjwxc.net/onebook.php?novelid={novel_id}"
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = 'gb18030'
        soup = BeautifulSoup(resp.text, 'html.parser')
        title_tag = soup.find('h1')
        collect_tag = soup.find('span', itemprop='collectedCount')
        author_tag = soup.find('span', itemprop='author')
        click_tag = soup.find('span', itemprop='clickCount')
        vip_match = re.search(r'霸王票：.*?(\d+)', soup.get_text())
        vip_ticket = int(vip_match.group(1)) if vip_match else 0
        if title_tag and collect_tag:
            return {
                "书号": str(novel_id), "书名": title_tag.text.strip(), 
                "收藏数": int(collect_tag.text.strip()),
                "作者": author_tag.text.strip() if author_tag else "未知",
                "点击数": int(click_tag.text.strip()) if click_tag else 0,
                "霸王票": vip_ticket
            }
    except Exception:
        pass
    return None

def save_record(record_dict, file_path):
    df_new = pd.DataFrame([record_dict])
    file_exists = os.path.exists(file_path)
    df_new.to_csv(file_path, mode='a', header=not file_exists, index=False, encoding='utf-8-sig')

def run_job():
    print("开始抓取...")
    # 1. 自动读取你之前存的书单并更新
    if os.path.exists(FILE_BOOK):
        df = pd.read_csv(FILE_BOOK, encoding='utf-8-sig')
        unique_books = df.drop_duplicates('书号', keep='last')
        for _, row in unique_books.iterrows():
            info = fetch_book_data(row['书号'])
            if info:
                save_record({
                    "记录时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "书号": info["书号"], "书名": info['书名'],
                    "作者": info['作者'], "收藏数": info['收藏数'],
                    "点击数": info['点击数'], "霸王票": info['霸王票'],
                    "来源": row['来源']
                }, FILE_BOOK)
    print("抓取完成！")

if __name__ == "__main__":
    run_job()