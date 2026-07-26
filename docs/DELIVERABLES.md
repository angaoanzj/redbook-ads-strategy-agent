# 作业交付物索引

本仓库是独立可运行的「小红书投放策略决策 Agent」原型，对应五份交付如下。

| # | 交付项 | 文档 / 入口 | 说明 |
| --- | --- | --- | --- |
| 1 | 可运行的 Agent 原型 | [README.md](../README.md)、`main.py`、`web/`、`module_agents/`、`examples/` | FastAPI + 六模块 Agent Loop（工具护栏）；也可用网页直接输入参数生成结果。无代码路径见 `docs/no-code-agent/` |
| 2 | 使用说明书 | [USER_GUIDE.md](./USER_GUIDE.md) | 各模块用法、输入输出格式、开关参数、注意事项与降级行为 |
| 3 | 测试报告 | [TEST_REPORT.md](./TEST_REPORT.md) | 真实品牌「曲奇四重奏」全流程测试：环境、复现命令、结果准确性与实用性 |
| 4 | 技术架构图 | [ARCHITECTURE_OVERVIEW.md](./ARCHITECTURE_OVERVIEW.md)、[TECHNICAL_ARCHITECTURE.md](./TECHNICAL_ARCHITECTURE.md) | 实现原理、大模型与工具、数据来源；含总览 Mermaid 图 |
| 5 | 后续优化方向 | [OPTIMIZATION_ROADMAP.md](./OPTIMIZATION_ROADMAP.md) | 3–5 个可继续提升性能的方向（含方案与预期收益） |

## 最快验收路径（10 分钟）

```bash
cd /Users/llan/Documents/xiaohongshu-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 可选：填入 AGENT_ANALYZER_API_KEY
python -m uvicorn main:app --host 127.0.0.1 --port 8010
```

浏览器打开 http://127.0.0.1:8010/ ，载入曲奇四重奏案例或粘贴竞品链接后生成。

不配模型 Key 时仍可跑确定性引擎；勾选「启用六模块 LLM Agent」后走完整 Agent 决策。

## 案例文件

- `examples/cookie_quartet_full_case.json`：满证据全案（测试报告主案例）
- `examples/cookie_quartet.json`：精简案例
- `examples/jenny_benchmark_competitor_evidence.json`：珍妮对标拆解证据 + 看板金样
- `examples/creators_cookie_quartet.csv`：达人候选表
