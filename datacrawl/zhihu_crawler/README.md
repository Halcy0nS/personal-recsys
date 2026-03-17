# 知乎爬虫工具 (Zhihu Crawler)

一个基于 Playwright 的知乎内容爬取工具，支持爬取收藏夹和作者内容。

## 功能特性

- 📚 **收藏夹爬取** - 爬取指定用户的收藏夹内容
- ✍️ **作者内容爬取** - 爬取指定作者的回答、文章
- 🔐 **自动登录** - 支持扫码/密码登录，Cookie 自动保存
- 💾 **多格式导出** - 支持 JSON、CSV 格式导出
- 🖥️ **交互式界面** - 友好的命令行交互菜单

## 安装

### 1. 克隆/下载项目

```bash
cd zhihu_crawler
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 安装 Playwright 浏览器

```bash
playwright install chromium
```

### 4. 配置环境变量（可选）

```bash
cp .env.example .env
# 编辑 .env 文件，填写知乎账号信息
```

## 使用方法

### 交互式模式（推荐）

```bash
python run.py
```

然后按菜单提示操作。

### 命令行模式

#### 爬取收藏夹

```bash
# 爬取用户 cjm926 的收藏夹，最多5页
python run.py --favorites cjm926 --pages 5
```

#### 爬取作者回答

```bash
# 爬取指定作者的回答
python run.py --author some-author-id --type answers --pages 0
```

#### 爬取作者文章

```bash
# 爬取指定作者的文章
python run.py --author some-author-id --type articles --pages 0
```

#### 爬取作者全部内容

```bash
# 同时爬取回答和文章
python run.py --author some-author-id --type all --pages 0
```

说明：作者任务中 `--pages 0` 表示全量抓取（直到连续 2 轮无新增）。

#### 无头模式（不显示浏览器）

```bash
python run.py --favorites cjm926 --headless
```

## 数据结构

### 内容数据（ZhihuContent）

```json
{
  "id": "1234567890",
  "content_type": "answer",
  "title": "问题标题",
  "content": "内容摘要...",
  "author": {
    "name": "作者名",
    "url": "https://www.zhihu.com/people/xxx"
  },
  "voteup_count": 1000,
  "comment_count": 50,
  "url": "https://www.zhihu.com/question/xxx/answer/xxx"
}
```

## 数据导出

爬取的数据会自动保存到 `data/` 目录：

- `favorites_{username}_{timestamp}.json` - 收藏夹 JSON 数据
- `favorites_{username}_{timestamp}.csv` - 收藏夹 CSV 数据
- `author_{id}_answers_{timestamp}.json` - 作者回答数据
- `author_{id}_articles_{timestamp}.json` - 作者文章数据

## 注意事项

1. **登录状态**：
   - 首次运行需要手动登录知乎
   - 登录后会自动保存 Cookie，后续运行自动登录
   - Cookie 保存在 `data/cookies.json`

2. **反爬限制**：
   - 建议设置合理的爬取间隔（默认2秒）
   - 如仅需抽样，建议设置较小的 max_pages（如 5-10 页）
   - 频繁爬取可能导致账号暂时限制

3. **页面结构**：
   - 知乎页面结构可能随时变化
   - 如遇爬取失败，可能需要更新 CSS 选择器（在 `config.py` 中配置）

4. **法律合规**：
   - 仅爬取公开可见内容
   - 尊重作者版权，仅用于个人学习研究
   - 遵守知乎的 Robots 协议和相关法律法规

## 常见问题

### Q: 首次运行时浏览器没有打开？
A: 确保已运行 `playwright install chromium` 安装浏览器。

### Q: 登录后仍然提示未登录？
A: 删除 `data/cookies.json` 后重新运行，再次手动登录。

### Q: 爬取到的内容为空？
A: 可能是知乎页面结构变化，需要更新 `config.py` 中的 CSS 选择器。

### Q: 爬取速度很慢？
A: 默认设置了2秒间隔防止被封。如需调整，修改 `config.py` 中的 `delay_between_requests`。

## 更新日志

### v1.0.0
- 初始版本
- 支持收藏夹爬取
- 支持作者回答/文章爬取
- 支持 JSON/CSV 导出

## License

MIT License

## 作者

Created for personal use. Please use responsibly.
