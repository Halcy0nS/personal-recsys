import os
import re
import time
from datetime import datetime, timedelta, timezone
import requests
from markdownify import markdownify as md

# Configuration
GRAPHQL_URL = "https://www.lesswrong.com/graphql"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "data", "md")

def get_past_days_range(days: int) -> tuple[datetime, datetime]:
    """计算基于 UTC 时间的过去 N 天的起止时间"""
    now_utc = datetime.now(timezone.utc)
    start_dt = now_utc - timedelta(days=days)
    return start_dt, now_utc

def clean_html(html_content: str) -> str:
    """使用 markdownify 将 HTML 转换为结构良好的 Markdown"""
    # 过滤掉一些可能引起混乱的特殊标签
    markdown_text = md(html_content, heading_style="ATX", autolinks=False)
    # 简单清理多余的换行
    markdown_text = re.sub(r'\n{3,}', '\n\n', markdown_text)
    return markdown_text.strip()

def sanitize_filename(title: str) -> str:
    """生成合法的文件名"""
    title = re.sub(r'[\\/*?:"<>|]', "", title)
    title = title.replace(" ", "_")
    return title[:100]  # 防止文件名过长

def crawl_lesswrong(days: int = 7):
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        
    start_dt, end_dt = get_past_days_range(days)
    print(f"Targeting articles published between {start_dt.strftime('%Y-%m-%d %H:%M:%S')} and {end_dt.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    
    query = """
    {
      posts(input: {terms: {view: "new", limit: 150}}) {
        results {
          title
          slug
          postedAt
          user { username }
          htmlBody
        }
      }
    }
    """
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/json"
    }
    
    print(f"Fetching posts from {GRAPHQL_URL} ...")
    response = requests.post(GRAPHQL_URL, json={"query": query}, headers=headers, timeout=30)
    response.raise_for_status()
    
    data = response.json()
    posts = data.get("data", {}).get("posts", {}).get("results", [])
    
    articles_saved = 0
    print(f"Retrieved {len(posts)} posts from GraphQL API. Filtering for the past {days} days...")
    
    for entry in posts:
        posted_at_str = entry.get('postedAt')
        if not posted_at_str:
            continue
            
        # Parse ISO format datetime (e.g. 2026-06-02T23:54:52.022Z)
        # Handle 'Z' suffix by converting it to UTC timezone offset '+00:00'
        if posted_at_str.endswith('Z'):
            posted_at_str = posted_at_str[:-1] + '+00:00'
        
        try:
            pub_dt = datetime.fromisoformat(posted_at_str)
        except ValueError as e:
            print(f"Warning: Could not parse date '{posted_at_str}': {e}")
            continue
        
        # 检查是否属于指定天数范围内
        if start_dt <= pub_dt <= end_dt:
            title = entry.get('title', 'Untitled')
            user_info = entry.get('user')
            author = user_info.get('username', 'Unknown') if user_info else 'Unknown'
            slug = entry.get('slug', '')
            link = f"https://www.lesswrong.com/posts/{slug}" if slug else ""
            
            html_content = entry.get('htmlBody', '')
            if not html_content:
                print(f"Skip '{title}' due to missing content.")
                continue
                
            markdown_content = clean_html(html_content)
            
            # 生成带 YAML 前缀的 Markdown
            yaml_frontmatter = f"""---
title: {title}
author: {author}
published: {pub_dt.strftime('%Y-%m-%d %H:%M:%S')}
url: {link}
tags: [lesswrong, graphql_crawl]
---

"""
            full_text = yaml_frontmatter + markdown_content
            
            filename = f"{pub_dt.strftime('%Y%m%d')}_{sanitize_filename(title)}.md"
            filepath = os.path.join(OUTPUT_DIR, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(full_text)
                
            print(f"Saved: {filename}")
            articles_saved += 1
            
    print(f"Crawl complete! Saved {articles_saved} articles to {OUTPUT_DIR}")

def crawl_lesswrong_yesterday():
    """保留旧的入口函数名，向下兼容，但实际上抓取过去 7 天以符合新需求"""
    crawl_lesswrong(days=7)

if __name__ == "__main__":
    crawl_lesswrong(days=7)
