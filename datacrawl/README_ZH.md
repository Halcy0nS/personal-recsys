# 知乎爬虫项目快照

[English](README.md)

## 项目概览

这个仓库快照包含一个基于 Playwright 的知乎爬虫，当前实现聚焦两条用户侧流程：

- 爬取某个用户的收藏夹
- 爬取某个作者的回答与文章

当前提交中的实现并不是 `.py` 源码，而是位于 `zhihu_crawler/__pycache__/` 与 `zhihu_crawler/utils/__pycache__/` 下的已编译 Python 字节码，同时仓库还保留了 `zhihu_crawler/data/` 下的样例输出文件。

## 当前仓库状态

这部分对理解项目非常关键：

- 原始爬虫 `.py` 源文件在当前快照中不存在
- 逻辑模块仍能从已编译产物中识别出来
- `zhihu_crawler/data/` 保存了示例 JSON/CSV 输出和一个 `cookies.json`
- `zhihu_crawler/.venv/` 是本地虚拟环境快照，不属于业务架构
- 编译后的 `setup` 入口会依赖 `requirements.txt`，但当前仓库中并没有这个文件

因此，本文档会完整说明当前已实现的架构与行为，但不会假设“全新环境下一定可以直接跑通”。

## 架构说明

### 模块映射

| 逻辑模块 | 当前代码位置 | 职责 |
| --- | --- | --- |
| `config` | `zhihu_crawler/__pycache__/config.*.pyc` | 定义 `CrawlConfig`、`ZhihuAuthConfig` 以及全局配置实例 |
| `models` | `zhihu_crawler/__pycache__/models.*.pyc` | 定义 `ZhihuAuthor`、`ZhihuContent`、`ZhihuCollection`、`CrawlResult` |
| `utils.saver` | `zhihu_crawler/utils/__pycache__/saver.*.pyc` | 负责 JSON/CSV 保存及 CSV 扁平化 |
| `utils.logger` | `zhihu_crawler/utils/__pycache__/logger.*.pyc` | 配置 loguru 输出到终端和 `./logs/` |
| `crawler` | `zhihu_crawler/__pycache__/crawler.*.pyc` | 基础 Playwright 爬虫：浏览器生命周期、登录、Cookie、导航、解析、去重、保存 |
| `author_crawler` | `zhihu_crawler/__pycache__/author_crawler.*.pyc` | 作者内容爬取流程 |
| `favorites_crawler` | `zhihu_crawler/__pycache__/favorites_crawler.*.pyc` | 收藏夹列表发现与收藏夹内容爬取 |
| `run` | `zhihu_crawler/__pycache__/run.*.pyc` | 统一交互式/命令行入口 |
| `quickstart` | `zhihu_crawler/__pycache__/quickstart.*.pyc` | 常用快捷菜单 |
| `setup` | `zhihu_crawler/__pycache__/setup.*.pyc` | 环境初始化辅助入口 |
| `debug_collections` | `zhihu_crawler/__pycache__/debug_collections.*.pyc` | 收藏夹页面选择器调试工具 |

### 类之间的关系

```text
ZhihuCrawler
  ├─ AuthorCrawler
  └─ FavoritesCrawler

UnifiedCrawler = FavoritesCrawler + AuthorCrawler
```

### 各层职责与关系

- `models` 定义所有爬取流程共享的数据结构。
- `ZhihuCrawler` 是通用浏览器与抓取运行时层。
- `AuthorCrawler` 与 `FavoritesCrawler` 在基类之上补充场景化页面逻辑。
- `run` 与 `quickstart` 只是对这些 crawler 类的命令行包装。
- `DataSaver` 负责把内存中的结果落成 JSON/CSV 文件。

## 已实现能力

### 基础爬虫能力

`ZhihuCrawler` 已实现：

- 同步版 Playwright 浏览器启动
- Cookie 加载与保存
- 针对 `https://www.zhihu.com/signin` 的人工登录流程
- 反自动化检测脚本注入
- `_safe_goto()` 导航重试
- 列表页条目解析并转换为 `ZhihuContent`
- 页内去重
- 翻页与无限滚动兜底
- 通过 `DataSaver` 落盘

### 作者爬取

`AuthorCrawler` 已实现：

- `crawl_author_answers(author_id, max_pages=10, target_count=0)`
- `crawl_author_articles(author_id, max_pages=10, target_count=0)`
- `crawl_author_all_content(author_id, max_pages=10, target_count=0)`

从代码与样例输出可以确认：

- 作者页分别来自 `/people/{author_id}/answers` 与 `/people/{author_id}/posts`
- 列表解析器会识别 `answer`、`article`、`pin`
- 即使是“回答”流程，结果里也可能出现混合内容类型，因为实际解析是按卡片类型推断，而不是按工作流强制写死

### 收藏夹爬取

`FavoritesCrawler` 已实现：

- `get_favorites_list(username='cjm926')`
- `crawl_favorites(username='cjm926', max_pages=10, fetch_full_content=False)`
- `_crawl_single_collection(...)`
- 可选的详情页补全逻辑，用于回答与文章

当前实现里有一个非常重要的事实：

- UI 文案里提到了“正样本/负样本”
- 但当前提交中的 `get_favorites_list()` 实际上会把所有发现到的收藏夹都写成 `label = 1`
- `zhihu_crawler/data/favorites_cjm926_all_20260305_150447.json` 里的样例输出也验证了这一点：所有导出记录的 `metadata.label` 都是 `1`

## 数据模型

### `ZhihuAuthor`

字段：

- `id`
- `name`
- `url`
- `headline`
- `avatar_url`
- `follower_count`

### `ZhihuContent`

字段：

- `id`
- `content_type`
- `title`
- `content`
- `excerpt`
- `author`
- `created_time`
- `updated_time`
- `voteup_count`
- `comment_count`
- `url`
- `metadata`

### `CrawlResult`

字段：

- `success`
- `message`
- `contents`
- `total_count`
- `saved_files`

### 输出结构

从 `zhihu_crawler/data/` 中可以确认：

- JSON 会保留嵌套 `author` 对象
- CSV 会把嵌套作者字段拍平成列，例如：
  - `author_id`
  - `author_name`
  - `author_url`
  - `author_headline`
  - `author_avatar_url`
  - `author_follower_count`
- 收藏夹导出会额外使用 `metadata.label` 与 `metadata.collection_url`
- 当前仓库中的作者导出样例里，`metadata` 为空对象

## 配置与运行时状态

### `CrawlConfig`

代码中定义的默认值：

- `headless=False`
- `data_dir='./data'`
- `cookies_file='./data/cookies.json'`
- `max_pages=10`
- `delay_between_requests=2.0`
- `max_retries=3`
- `debug_logging=False`

默认选择器覆盖：

- 内容卡片
- 标题
- 富文本内容块
- 作者名
- 点赞数
- 评论数
- 下一页按钮
- 头像

### `ZhihuAuthConfig`

配置对象会读取：

- `ZHIHU_USERNAME`
- `ZHIHU_PASSWORD`

但这一能力目前只存在于配置定义中；运行时并没有使用 `auth_config` 做自动登录，因此当前登录方式仍然是浏览器中的人工登录。

### 路径行为

路径都依赖当前工作目录：

- 爬虫输出默认写到 `./data`
- Cookie 默认写到 `./data/cookies.json`
- `utils.logger` 默认写到 `./logs`

这也是为什么当前仓库里同时出现了：

- 根目录下的 `data/`
- 包目录下的 `zhihu_crawler/data/`

而样例输出位于 `zhihu_crawler/data/`，说明此前至少有一部分运行是在 `zhihu_crawler/` 目录内发起的。

## 代码中定义的入口

### `run`

编译后的 `run` 模块定义了：

- 交互式菜单，支持：
  - 收藏夹爬取
  - 作者回答爬取
  - 作者文章爬取
  - 作者全部内容爬取
- argparse 参数：
  - `--headless`
  - `--favorites`
  - `--author`
  - `--type {answers,articles,all}`
  - `--pages`，默认 `5`
  - `--target-count`，默认 `0`

### `quickstart`

编译后的 `quickstart` 模块提供快捷菜单：

- 快速爬取 `cjm926` 的收藏夹
- 快速爬取指定作者
- 打开完整交互菜单

### `setup`

编译后的 `setup` 模块会：

- 检查 Python 版本是否 `>= 3.8`
- 尝试从 `requirements.txt` 安装依赖
- 尝试安装 `playwright chromium`
- 创建 `data/`

但当前仓库里没有 `requirements.txt`，所以这里只能如实说明入口行为，不能把它描述成完整可用的初始化流程。

### `debug_collections`

调试入口会访问：

- `https://www.zhihu.com/people/cjm926/collections`

并打印面向选择器调试的页面信息。

## 仓库结构

```text
datacrawl/
├── .claude/
│   └── settings.local.json
├── data/
├── zhihu_crawler/
│   ├── .venv/
│   ├── __pycache__/
│   ├── data/
│   └── utils/
│       └── __pycache__/
├── AGENTS.md
├── CLAUDE.md
├── README.md
└── README_ZH.md
```

## 当前快照中的已知缺口

- 没有明文 `.py` 爬虫源码
- 没有 `requirements.txt`
- `utils.logger` 存在，但当前爬虫流程没有接入它
- `ZhihuCollection` 模型存在，但当前爬取流程没有实际使用
- 收藏夹“负样本”分类尚未实现，尽管界面文案有相关描述
- 收藏夹的全文抓取能力只存在于 crawler API 中，当前 CLI 并没有暴露对应参数

## 文档依据

本文档严格基于以下事实来源编写：

- 当前仓库中实际存在的已编译爬虫模块
- 当前仓库中实际存在的 `zhihu_crawler/data/` 样例 JSON/CSV 文件

没有从文件名或预期设计中推测未被这些产物证实的能力。
