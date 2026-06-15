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
    if not html_content:
        return ""
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

def extract_post_id(post_id_or_url: str) -> str:
    """从 LessWrong 链接或字符串中提取文章 ID 或 slug"""
    post_id_or_url = post_id_or_url.strip()
    if "lesswrong.com/posts/" in post_id_or_url:
        match = re.search(r"lesswrong\.com/posts/([^/]+)", post_id_or_url)
        if match:
            return match.group(1)
    if "/" in post_id_or_url:
        return post_id_or_url.split("/")[-1]
    return post_id_or_url

def fetch_post_and_comments_by_id_or_slug(id_or_slug: str):
    """通过 ID 或 slug 获取文章及其评论"""
    if len(id_or_slug) == 17 and id_or_slug.isalnum():
        query_post = """
        query GetPost($postId: String!) {
          post(input: {selector: {_id: $postId}}) {
            result {
              _id
              title
              slug
              postedAt
              htmlBody
              baseScore
              user {
                username
                displayName
              }
            }
          }
        }
        """
        variables = {"postId": id_or_slug}
    else:
        query_post = """
        query GetPost($slug: String!) {
          post(input: {selector: {slug: $slug}}) {
            result {
              _id
              title
              slug
              postedAt
              htmlBody
              baseScore
              user {
                username
                displayName
              }
            }
          }
        }
        """
        variables = {"slug": id_or_slug}
        
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/json"
    }
    
    # 1. Fetch post metadata
    print(f"Fetching post metadata for '{id_or_slug}'...")
    response = requests.post(
        GRAPHQL_URL, 
        json={"query": query_post, "variables": variables}, 
        headers=headers, 
        timeout=30
    )
    response.raise_for_status()
    post_data = response.json()
    if "errors" in post_data:
        raise ValueError(f"GraphQL Errors: {post_data['errors']}")
        
    post = post_data.get("data", {}).get("post", {}).get("result")
    if not post:
        raise ValueError(f"Post '{id_or_slug}' not found.")
        
    post_id = post["_id"]
    
    # 2. Fetch comments
    print(f"Fetching comments for post ID '{post_id}'...")
    query_comments = """
    query GetComments($postId: String!) {
      comments(input: {terms: {view: "postCommentsTop", postId: $postId, limit: 500}}) {
        results {
          _id
          parentCommentId
          postedAt
          htmlBody
          baseScore
          user {
            username
            displayName
          }
        }
      }
    }
    """
    response = requests.post(
        GRAPHQL_URL, 
        json={"query": query_comments, "variables": {"postId": post_id}}, 
        headers=headers, 
        timeout=30
    )
    response.raise_for_status()
    comments_data = response.json()
    if "errors" in comments_data:
        raise ValueError(f"GraphQL Errors: {comments_data['errors']}")
        
    comments = comments_data.get("data", {}).get("comments", {}).get("results", [])
    return post, comments


def format_comment(comment, depth=0):
    user_obj = comment.get('user') or {}
    author = user_obj.get('username') or user_obj.get('displayName') or 'Anonymous'
    score = comment.get('baseScore', 0)
    
    posted_at = comment.get('postedAt', '')
    try:
        dt = datetime.fromisoformat(posted_at.replace('Z', '+00:00'))
        date_str = dt.strftime('%Y-%m-%d %H:%M')
    except Exception:
        date_str = posted_at
        
    body_md = clean_html(comment.get('htmlBody', ''))
    prefix = "> " * depth
    
    formatted = f"{prefix}**@{author}** (Score: {score} | {date_str})\n"
    for line in body_md.split('\n'):
        formatted += f"{prefix}{line}\n"
    formatted += f"{prefix}\n"
    
    replies = comment.get('replies', [])
    replies.sort(key=lambda x: (x.get('baseScore', 0), x.get('postedAt', '')), reverse=True)
    
    for reply in replies:
        formatted += format_comment(reply, depth + 1)
        
    return formatted

def crawl_post_with_comments(post_id_or_url: str, output_path: str = None):
    """抓取单篇文章及其所有评论并保存为 Markdown"""
    post_id_or_slug = extract_post_id(post_id_or_url)
    
    try:
        post, comments = fetch_post_and_comments_by_id_or_slug(post_id_or_slug)
    except Exception as e:
        print(f"Error fetching post: {e}")
        return False
        
    title = post.get('title', 'Untitled')
    user_obj = post.get('user') or {}
    author = user_obj.get('username') or user_obj.get('displayName') or 'Unknown'
    score = post.get('baseScore', 0)
    posted_at = post.get('postedAt', '')
    try:
        dt = datetime.fromisoformat(posted_at.replace('Z', '+00:00'))
        date_str = dt.strftime('%Y-%m-%d %H:%M')
    except Exception:
        date_str = posted_at
        
    body_md = clean_html(post.get('htmlBody', ''))
    post_url = f"https://www.lesswrong.com/posts/{post.get('_id')}/{post.get('slug', '')}"
    
    # Build document
    doc = f"# {title}\n\n"
    doc += f"- **Author**: @{author}\n"
    doc += f"- **Published**: {date_str}\n"
    doc += f"- **Score**: {score}\n"
    doc += f"- **URL**: {post_url}\n\n"
    doc += "---\n\n"
    doc += "## Article Body\n\n"
    doc += f"{body_md}\n\n"
    doc += "---\n\n"
    doc += f"## Comments ({len(comments)})\n\n"
    
    # Reconstruct comment tree
    comment_dict = {c['_id']: {**c, 'replies': []} for c in comments}
    root_comments = []
    
    for c_id, comment in comment_dict.items():
        parent_id = comment.get('parentCommentId')
        if parent_id and parent_id in comment_dict:
            comment_dict[parent_id]['replies'].append(comment)
        else:
            root_comments.append(comment)
            
    root_comments.sort(key=lambda x: (x.get('baseScore', 0), x.get('postedAt', '')), reverse=True)
    
    for root in root_comments:
        doc += format_comment(root, depth=0)
        doc += "\n---\n\n"
        
    if not output_path:
        sanitized_title = sanitize_filename(title)
        filename = f"{dt.strftime('%Y%m%d')}_{sanitized_title}.md"
        output_path = os.path.join(OUTPUT_DIR, filename)
        
    parent_dir = os.path.dirname(output_path)
    if parent_dir and not os.path.exists(parent_dir):
        os.makedirs(parent_dir)
        
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(doc)
        
    print(f"Successfully saved article and comments to: {output_path}")
    return True

def crawl_lesswrong_yesterday():
    """保留旧的入口函数名，向下兼容，但实际上抓取过去 7 天以符合新需求"""
    crawl_lesswrong(days=7)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="LessWrong Article Crawler")
    parser.add_argument("--days", "-d", type=int, default=7, help="Number of past days to crawl (default: 7)")
    parser.add_argument("--post", "-p", type=str, default=None, help="Crawl a specific post and its comments by ID, slug, or URL")
    parser.add_argument("--output", "-o", type=str, default=None, help="Custom output filepath for specific post crawl")
    
    args = parser.parse_args()
    
    if args.post:
        crawl_post_with_comments(args.post, args.output)
    else:
        crawl_lesswrong(days=args.days)

