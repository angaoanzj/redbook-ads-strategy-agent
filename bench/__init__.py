"""评测基准集与回归评分（对齐 docs/OPTIMIZATION_ROADMAP.md 第 5 节）。

三个文件各司其职：

- `bench.golden`：六模块的黄金断言集（诚实标记 / 数字不变量 / 关键路径），代码即数据；
- `bench.score`：四维加权评分（grounding 40 / honesty 25 / invariants 25 / structure 10）；
- `bench.run_bench`：CLI，`--replay` 回放存档评分，`--live` 真跑 pipeline 后评分。

本包只依赖标准库与自身，绝不 import engine / main / report_view，
因此可以在任何环境（含只装了标准库的沙盒）里被 unittest 导入。
"""

from bench.golden import GOLDEN_EXPECTATIONS, MODULE_KEYS, normalize_module_name
from bench.score import score_module, score_run

__all__ = [
    "GOLDEN_EXPECTATIONS",
    "MODULE_KEYS",
    "normalize_module_name",
    "score_module",
    "score_run",
]
