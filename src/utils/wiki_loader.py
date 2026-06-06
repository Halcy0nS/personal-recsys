import os
import glob
import re
import hashlib
from typing import List, Dict, Any

# Adjust import based on the actual path in the repository
from src.engine import CandidateItem

def parse_yaml_frontmatter(content: str) -> tuple[Dict[str, Any], str]:
    """
    极简的 YAML Frontmatter 解析器。
    返回 (frontmatter_dict, remaining_content)
    """
    frontmatter = {}
    remaining_content = content

    # 匹配以 --- 开头和 --- 结尾的块
    pattern = r'^---\s*\n(.*?)\n---\s*\n'
    match = re.search(pattern, content, re.DOTALL)
    
    if match:
        yaml_text = match.group(1)
        remaining_content = content[match.end():]
        
        # 逐行解析简单的 key: value
        for line in yaml_text.split('\n'):
            line = line.strip()
            if not line or ':' not in line:
                continue
            
            # 分割出 key 和 value
            parts = line.split(':', 1)
            key = parts[0].strip()
            val = parts[1].strip()
            
            # 简单处理列表格式，如 tags: [tag1, tag2]
            if val.startswith('[') and val.endswith(']'):
                val_inner = val[1:-1].strip()
                if val_inner:
                    # 分割并去掉多余引号和空格
                    items = [x.strip(" '\"") for x in val_inner.split(',')]
                    frontmatter[key] = items
                else:
                    frontmatter[key] = []
            else:
                # 简单去除首尾引号
                frontmatter[key] = val.strip(" '\"")
                
    return frontmatter, remaining_content

def load_wiki_candidates(wiki_dir: str) -> List[CandidateItem]:
    """
    遍历指定目录下的所有 Markdown 文件，将其加载为推荐引擎的候选池 (CandidateItem) 列表。
    """
    candidates = []
    
    if not os.path.isdir(wiki_dir):
        print(f"Warning: Wiki directory {wiki_dir} does not exist.")
        return candidates

    md_files = glob.glob(os.path.join(wiki_dir, "**", "*.md"), recursive=True)
    
    for file_path in md_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            frontmatter, main_content = parse_yaml_frontmatter(content)
            
            # 确定标题：优先使用 yaml 的 title，否则使用文件名
            rel_path = os.path.relpath(file_path, wiki_dir)
            default_title = os.path.basename(file_path).replace(".md", "")
            title = frontmatter.get("title", default_title)
            
            # 提取 tags
            tags = frontmatter.get("tags", [])
            if isinstance(tags, str):
                tags = [tags]
                
            # 为避免内容过长导致 Embedding 溢出，对 content 进行截断 (取前 2000 字符作为语义摘要)
            truncated_content = main_content[:2000].strip()
            if not truncated_content:
                truncated_content = title # 兜底，防止空内容报错
                
            # 使用相对路径的 MD5 作为唯一的 item_id
            item_id = hashlib.md5(rel_path.encode('utf-8')).hexdigest()
            
            # 构建 CandidateItem
            # 将 metadata 里的 popularity 默认设为 1.0 (因为我们假设 wiki 里留下的都是高价值笔记)
            item = CandidateItem(
                item_id=item_id,
                title=title,
                content=truncated_content,
                tags=tags,
                metadata={
                    "popularity": 1.0,
                    "path": rel_path,
                    "type": "wiki",
                    "frontmatter": frontmatter
                }
            )
            candidates.append(item)
            
        except Exception as e:
            print(f"Failed to load {file_path}: {e}")
            
    print(f"Successfully loaded {len(candidates)} wiki candidates from {wiki_dir}")
    return candidates
