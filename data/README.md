# data/ 目录说明

本目录存放本地运行时的 SQLite 与导入样例，**默认不提交大库文件**（见根目录 `.gitignore`）。

| 文件 | 用途 |
| --- | --- |
| `xhs_knowledge.db` | 品类笔记 / 品牌指标知识库（可选，用于 `use_knowledge=true`） |
| `knowledge.db` | 辅助知识库 |
| `realtime_feed.db` | 实时 Feed 落库（Mock 源演示） |
| `quartet_*.json` / `*.csv` | 曲奇四重奏公开材料索引 |

首次运行若无库文件，Agent 仍可用 `examples/*.json` 内嵌证据生成方案；需要知识库检索时再导入 workbook 或拷贝库文件。
