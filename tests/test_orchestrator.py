"""模块间依赖传递编排测试：不依赖真实模型 Key，不 import engine。

覆盖：
- 六个模块的摘要函数各一个用例（fixture 贴近真实输出契约形状）+ 字段缺失容错；
- PIPELINE_ORDER 覆盖六模块且顺序为 M1→M2→M6→M3→M4→M5；
- run_pipeline 用 fake runner 验证执行顺序、上游摘要传递、upstream_limit；
- 硬前序检查（PREREQUISITES / should_block）：前序 failed → 下游 blocked；
  前序 completed_with_gaps → 下游照常执行且拿到缺口提示。
"""
from __future__ import annotations

import unittest

from module_agents.orchestrator import (
    BLOCKED_REASON,
    DIGEST_MAX_CHARS,
    MODULE_LABELS,
    PIPELINE_ORDER,
    PREREQUISITES,
    SHARED_KEYWORD_HANDOFF_HEADER,
    build_gap_notice,
    build_shared_keyword_handoff,
    build_upstream_digest,
    module_status_of,
    run_pipeline,
    should_block,
)


# ---------------------------------------------------------------------------
# 贴近真实契约形状的 fixture
# ---------------------------------------------------------------------------
M1_OUTPUT = {
    "organic_landscape": {
        "sample_size": 40,
        "hot_formats": [
            {"format": "开箱测评", "avg_interactions": 1280.5},
            {"format": "送礼场景", "avg_interactions": 860.0},
        ],
        "peak_hour_hypothesis": "20:00-22:00 为高互动时段（待验证假设）",
        "content_form_advice": ["首图放礼盒实拍", "正文前三行讲送礼场景"],
        "boundary_note": "本样本不等于全平台大盘",
    },
    "paid_landscape": {"cpc_cny": 1.6, "cpc_source": "品牌《数据需求.xlsx》"},
    "competitor_breakdown": {
        "common_patterns": ["九宫格实拍", "伴手礼清单"],
        "content_gaps": ["保质期与运输说明", "自用场景"],
        "ad_labeled_count": 2,
        "targeting_hypotheses": ["假设竞品主投到港游客人群", "假设竞品叠加送礼兴趣标签"],
        "budget_inference_policy": "禁止推测竞品预算",
    },
    "risk_alerts": [
        {"risk": "功效化表述拒审", "source": "官方规则", "action": "改为体验描述"},
        {"risk": "跨境物流时效差评", "source": "违规台账", "action": "正文前置时效说明"},
        {"risk": "价格敏感", "source": "通用经验", "action": "强调礼盒规格"},
        {"risk": "第四条不应进摘要", "source": "x", "action": "y"},
    ],
    "human_review_items": ["竞品需补采"],
}

M2_OUTPUT = {
    "persona": {
        "demographic": ["25-34 女性", "一线城市"],
        "behavioral": ["搜索伴手礼", "关注港式点心"],
        "psychological": ["社交货币", "怕踩雷"],
        "targeting_tags": {
            "interest_tags": ["伴手礼", "港式点心", "下午茶", "送礼攻略", "零食测评", "多余标签"],
            "behavior_tags": ["搜索伴手礼", "收藏攻略", "加购零食"],
            "crowd_packages": ["到港游客包", "送礼人群包", "美食兴趣包", "多余人群包"],
        },
        "tag_status": "标签需在聚光后台核对可用性",
    },
    "content_directions": [
        {"direction": "送礼场景", "organic_score": 8, "paid_score": 9, "rationale": "礼盒属性强"},
        {"direction": "口味测评", "organic_score": 9, "paid_score": 7, "rationale": "互动高"},
        {"direction": "香港攻略", "organic_score": 7, "paid_score": 6, "rationale": "带流量"},
    ],
    "topics": [
        {"title_template": f"选题标题{i}", "cover_suggestion": "礼盒实拍",
         "outline": ["开场", "结尾"], "direction": "送礼场景",
         "suitable_for_paid": False, "paid_objective": None}
        for i in range(1, 16)
    ],
    "material_screening": {
        "ctr_threshold": 0.05,
        "engagement_threshold": 0.03,
        "extra_rules": ["首图必须出现礼盒"],
    },
    "human_review_items": ["标签需后台核对"],
}

M6_OUTPUT = {
    "keyword_levels": {
        "core": [
            {"keyword": f"核心词{i}", "intent": "high", "lane": "search", "bid_note": "高价抢位"}
            for i in range(1, 4)
        ],
        "long_tail": [
            {"keyword": f"长尾词{i}", "intent": "mid", "lane": "both", "bid_note": "中价"}
            for i in range(1, 8)
        ],
        "blue_ocean": [
            {"keyword": f"蓝海词{i}", "intent": "low", "lane": "feed", "bid_note": "低价试探"}
            for i in range(1, 3)
        ],
    },
    "layout_rules": [{"position": "标题", "rule": "核心词前置"}],
    "level_budget_split": {"core": 0.5, "long_tail": 0.3, "blue_ocean": 0.2},
    "trending_monitor": {"mechanism": "人工周巡", "follow_criteria": ["相关", "合规"],
                         "data_source_status": "待接入数据源"},
    "human_review_items": ["词库需后台核对"],
}

M3_OUTPUT = {
    "keyword_tracks": {
        "organic": {"core": [], "long_tail": [], "blue_ocean": []},
        "search_ads": [{"keyword": f"搜索词{i}", "bid_note": "note"} for i in range(1, 6)],
        "feed_ads": [{"keyword": f"信息流词{i}", "bid_note": "note"} for i in range(1, 4)],
    },
    "creator_plan": {
        "tiers": [
            {"tier": "素人", "count": 12, "collaboration_budget_cny": 15000,
             "spotlight_amplification_budget_cny": 10500},
            {"tier": "达人", "count": 6, "collaboration_budget_cny": 10500,
             "spotlight_amplification_budget_cny": 7350},
        ],
        "amplification_pool_cny": 21000,
    },
    "matched_creators": [
        {"name": "达人A", "tier": "素人", "match_score": 82,
         "suggested_note_budget_cny": 1250, "source": "CSV"},
        {"name": "达人B", "tier": "达人", "match_score": 74,
         "suggested_note_budget_cny": 1750, "source": "CSV"},
    ],
    "open_slots": [{"tier": "KOL", "slots_needed": 2}],
    "human_review_items": ["需补蒲公英名单"],
}

M4_OUTPUT = {
    "account_structure": {
        "campaign_naming_rule": "目标-版位-日期",
        "unit_naming_rule": "人群-出价",
        "campaigns": [
            {"name": "成交-搜索", "objective": "商品成交", "budget_share": 0.6,
             "placement": "搜索推广"},
            {"name": "种草-信息流", "objective": "产品种草", "budget_share": 0.4,
             "placement": "信息流推广"},
        ],
    },
    "targeting_packages": [
        {"package": "精准定向", "audience_desc": "到港游客", "budget_share": 0.5,
         "applicable_stage": "冷启动", "smart_expansion": False},
        {"package": "宽定向", "audience_desc": "泛送礼", "budget_share": 0.3,
         "applicable_stage": "放量", "smart_expansion": True},
        {"package": "达人相似定向", "audience_desc": "达人粉丝", "budget_share": 0.2,
         "applicable_stage": "放量", "smart_expansion": True},
    ],
    "bidding": {
        "cold_start": {"method": "稳定成本", "bid_low_cny": 1.44, "bid_high_cny": 1.76,
                       "basis": "基准 CPC 1.6 元 × 0.9-1.1"},
        "scaling_rules": ["连续两日 ROI 达标提价5%", "CPA 超标降价10%"],
    },
    "search_feed_split": {"search": 0.6, "feed": 0.4, "synergy_note": "搜索承接信息流种草"},
    "daily_schedule": [{"time_range": "20:00-22:00", "action": "加价5%抢量"}],
    "forecast": {"test_budget_cny": 6000, "stop_loss_cpc_cny": 2.4,
                 "stop_loss_cpa_cny": 180.0, "roi_point": None, "roi_band": None,
                 "status": "partial"},
    "risk_playbook": [],
    "human_review_items": ["出价需后台复核"],
}

M5_OUTPUT = {
    "budget_split": {"organic_budget_cny": 30000, "paid_budget_cny": 70000,
                     "organic_ratio": 0.3, "needs_review": False},
    "phases": [
        {"phase": "预热期", "paid_budget_cny": 14000, "key_actions": ["自然铺量"]},
        {"phase": "爆发期", "paid_budget_cny": 42000, "key_actions": ["放大胜出素材"]},
        {"phase": "长尾期", "paid_budget_cny": 14000, "key_actions": ["搜索词占位"]},
    ],
    "creator_tier_plan": {"tiers": [], "amplification_pool_cny": 21000},
    "bid_plan": {"cold_start": None, "scaling": None, "basis": "无历史 CPC"},
    "synergy_rules": [
        {"metric": "自然笔记互动率", "threshold": "达标后", "action": "进入聚光测试"},
        {"metric": "付费转化数据", "threshold": "跑通后", "action": "回流优化选题"},
    ],
    "contingency_plans": [],
    "human_review_items": ["工作簿来源需确认"],
}

_FIXTURES = {
    "module1": M1_OUTPUT,
    "module2": M2_OUTPUT,
    "module3": M3_OUTPUT,
    "module4": M4_OUTPUT,
    "module5": M5_OUTPUT,
    "module6": M6_OUTPUT,
}


# ---------------------------------------------------------------------------
# 摘要函数
# ---------------------------------------------------------------------------
class DigestModule1Test(unittest.TestCase):
    def test_extracts_formats_peak_gaps_and_risks(self) -> None:
        digest = build_upstream_digest("module1", M1_OUTPUT)
        self.assertIn(MODULE_LABELS["module1"], digest)
        self.assertIn("开箱测评(均互动1280.5)", digest)
        self.assertIn("20:00-22:00", digest)
        self.assertIn("保质期与运输说明", digest)
        self.assertIn("功效化表述拒审→改为体验描述", digest)
        # 风险要点只取前 3 条
        self.assertNotIn("第四条不应进摘要", digest)
        self.assertLessEqual(len(digest), DIGEST_MAX_CHARS)

    def test_missing_fields_tolerated(self) -> None:
        digest = build_upstream_digest("module1", {"organic_landscape": {"hot_formats": []}})
        self.assertIn("无笔记证据", digest)
        self.assertNotIn("峰时假设", digest)
        self.assertNotIn("风险要点", digest)
        # 完全空输入也不抛异常
        self.assertIsInstance(build_upstream_digest("module1", {}), str)


class DigestModule2Test(unittest.TestCase):
    def test_extracts_directions_topics_thresholds_tags(self) -> None:
        digest = build_upstream_digest("module2", M2_OUTPUT)
        self.assertIn("送礼场景(自然8/付费9)", digest)
        self.assertIn("选题标题1", digest)
        self.assertNotIn("选题标题6", digest)  # 只取 Top5
        self.assertIn("CTR≥0.05", digest)
        self.assertIn("互动率≥0.03", digest)
        self.assertIn("伴手礼", digest)
        self.assertNotIn("多余标签", digest)  # 兴趣标签只取前 5
        self.assertNotIn("多余人群包", digest)  # 人群包只取前 3
        self.assertLessEqual(len(digest), DIGEST_MAX_CHARS)

    def test_missing_persona_tolerated(self) -> None:
        digest = build_upstream_digest("module2", {"content_directions": [{"direction": "送礼"}]})
        self.assertIn("送礼", digest)
        self.assertEqual(build_upstream_digest("module2", {}), "")


class DigestModule6Test(unittest.TestCase):
    def test_extracts_three_levels_and_budget_split(self) -> None:
        digest = build_upstream_digest("module6", M6_OUTPUT)
        self.assertIn("核心词1", digest)
        self.assertIn("长尾词5", digest)
        self.assertNotIn("长尾词6", digest)  # 每级只取前 5
        self.assertIn("蓝海词2", digest)
        self.assertIn("核心0.5", digest)
        self.assertIn("长尾0.3", digest)
        self.assertIn("蓝海0.2", digest)
        self.assertLessEqual(len(digest), DIGEST_MAX_CHARS)

    def test_missing_levels_tolerated(self) -> None:
        digest = build_upstream_digest("module6", {"keyword_levels": {"core": None}})
        self.assertEqual(digest, "")


class DigestModule3Test(unittest.TestCase):
    def test_extracts_tiers_matches_gaps_and_word_counts(self) -> None:
        digest = build_upstream_digest("module3", M3_OUTPUT)
        self.assertIn("素人12人/合作15000元+放大10500元", digest)
        self.assertIn("二次放大池：21000元", digest)
        self.assertIn("已匹配达人 2 位", digest)
        self.assertIn("KOL缺2位", digest)
        self.assertIn("搜索 5 个", digest)
        self.assertIn("信息流 3 个", digest)
        self.assertLessEqual(len(digest), DIGEST_MAX_CHARS)

    def test_no_creator_evidence_tolerated(self) -> None:
        digest = build_upstream_digest("module3", {"matched_creators": []})
        self.assertIn("已匹配达人 0 位", digest)
        self.assertIn("无名额缺口", digest)


class DigestModule4Test(unittest.TestCase):
    def test_extracts_structure_targeting_bid_and_stop_loss(self) -> None:
        digest = build_upstream_digest("module4", M4_OUTPUT)
        self.assertIn("成交-搜索(商品成交/搜索推广/0.6)", digest)
        self.assertIn("精准定向0.5", digest)
        self.assertIn("1.44-1.76", digest)
        self.assertIn("CPC>2.4", digest)
        self.assertIn("CPA>180", digest)
        self.assertIn("测试带宽：6000元", digest)
        self.assertLessEqual(len(digest), DIGEST_MAX_CHARS)

    def test_null_bid_tolerated(self) -> None:
        digest = build_upstream_digest(
            "module4", {"bidding": {"cold_start": {"bid_low_cny": None, "bid_high_cny": None}}}
        )
        self.assertIn("无基准 CPC 证据", digest)


class DigestModule5Test(unittest.TestCase):
    def test_extracts_budget_phases_and_synergy(self) -> None:
        digest = build_upstream_digest("module5", M5_OUTPUT)
        self.assertIn("自然30000元 / 付费70000元", digest)
        self.assertIn("自然占比 0.3", digest)
        self.assertIn("预热期14000元", digest)
        self.assertIn("爆发期42000元", digest)
        self.assertIn("自然笔记互动率达标后→进入聚光测试", digest)
        self.assertLessEqual(len(digest), DIGEST_MAX_CHARS)

    def test_missing_phases_tolerated(self) -> None:
        digest = build_upstream_digest("module5", {"phases": [{}], "synergy_rules": None})
        self.assertEqual(digest, "")


class DigestGeneralTest(unittest.TestCase):
    def test_unknown_module_returns_empty(self) -> None:
        self.assertEqual(build_upstream_digest("module9", M1_OUTPUT), "")

    def test_non_dict_output_tolerated(self) -> None:
        for module in PIPELINE_ORDER:
            self.assertIsInstance(build_upstream_digest(module, None), str)
            self.assertIsInstance(build_upstream_digest(module, ["oops"]), str)

    def test_all_digests_within_limit(self) -> None:
        for module, output in _FIXTURES.items():
            self.assertLessEqual(len(build_upstream_digest(module, output)), DIGEST_MAX_CHARS)


class PipelineOrderTest(unittest.TestCase):
    def test_covers_six_modules_in_dependency_order(self) -> None:
        self.assertEqual(
            PIPELINE_ORDER,
            ["module1", "module2", "module6", "module3", "module4", "module5"],
        )
        self.assertEqual(len(set(PIPELINE_ORDER)), 6)
        self.assertEqual(set(PIPELINE_ORDER), set(MODULE_LABELS))


# ---------------------------------------------------------------------------
# run_pipeline
# ---------------------------------------------------------------------------
class _FakeRunner:
    """记录调用顺序与收到的 upstream_context；可指定哪些模块抛异常/带缺口完成。"""

    def __init__(
        self,
        failing: set[str] | None = None,
        gaps: dict[str, list[str]] | None = None,
    ) -> None:
        self.calls: list[tuple[str, str]] = []
        self.failing = failing or set()
        self.gaps = gaps or {}

    def __call__(self, module_name: str, req, upstream_context: str) -> dict:
        self.calls.append((module_name, upstream_context))
        if module_name in self.failing:
            raise RuntimeError(f"{module_name} 故意失败")
        result = {
            "module": module_name,
            "output": _FIXTURES[module_name],
            "grounding_check": {"passed": True, "mismatches": []},
            "steps_used": 4,
            "repair_rounds_used": 0,
            "trace": [],
        }
        if module_name in self.gaps:
            result["module_status"] = "completed_with_gaps"
            result["unresolved_gaps"] = list(self.gaps[module_name])
        return result

    def context_of(self, module_name: str) -> str:
        for name, context in self.calls:
            if name == module_name:
                return context
        raise AssertionError(f"{module_name} 未被执行")


class RunPipelineTest(unittest.TestCase):
    def test_executes_in_dependency_order(self) -> None:
        runner = _FakeRunner()
        outcome = run_pipeline(None, runner=runner)

        self.assertEqual([name for name, _ in runner.calls], PIPELINE_ORDER)
        self.assertEqual(list(outcome["modules"]), PIPELINE_ORDER)
        self.assertTrue(
            all(
                row["status"] in {"success", "shared_keyword_handoff"}
                for row in outcome["pipeline_trace"]
            )
        )

    def test_subset_still_follows_pipeline_order(self) -> None:
        runner = _FakeRunner()
        run_pipeline(None, ["module5", "module1", "module6"], runner=runner)
        self.assertEqual([name for name, _ in runner.calls], ["module1", "module6", "module5"])

    def test_unknown_module_recorded_as_skipped(self) -> None:
        runner = _FakeRunner()
        outcome = run_pipeline(None, ["module1", "module9"], runner=runner)
        self.assertEqual([name for name, _ in runner.calls], ["module1"])
        skipped = [row for row in outcome["pipeline_trace"] if row["status"] == "skipped"]
        self.assertEqual(skipped[0]["module"], "module9")

    def test_third_module_receives_first_two_digests(self) -> None:
        runner = _FakeRunner()
        run_pipeline(None, runner=runner)

        self.assertEqual(runner.context_of("module1"), "")
        second = runner.context_of("module2")
        self.assertIn(MODULE_LABELS["module1"], second)
        self.assertIn("开箱测评", second)

        third = runner.context_of("module6")  # 第 3 个执行的模块
        self.assertIn(MODULE_LABELS["module1"], third)
        self.assertIn(MODULE_LABELS["module2"], third)
        self.assertIn("送礼场景(自然8/付费9)", third)

    def test_trace_records_digest_sizes(self) -> None:
        runner = _FakeRunner()
        outcome = run_pipeline(None, runner=runner)
        by_module = {row["module"]: row for row in outcome["pipeline_trace"]}

        self.assertEqual(by_module["module1"]["upstream_digest_chars"], 0)
        self.assertGreater(by_module["module2"]["upstream_digest_chars"], 0)
        self.assertEqual(
            by_module["module2"]["upstream_digest_chars"],
            len(runner.context_of("module2")),
        )
        self.assertEqual(
            by_module["module1"]["digest_chars"],
            len(build_upstream_digest("module1", M1_OUTPUT)),
        )
        self.assertEqual(by_module["module1"]["steps_used"], 4)
        self.assertTrue(by_module["module1"]["grounding_passed"])

    def test_failed_module_blocks_only_its_hard_dependents(self) -> None:
        runner = _FakeRunner(failing={"module2"})
        outcome = run_pipeline(None, runner=runner)

        # module6 只依赖 module1，照跑；module3/4/5 因硬前序缺失被阻塞
        self.assertEqual([name for name, _ in runner.calls], ["module1", "module2", "module6"])
        self.assertNotIn("module2", outcome["modules"])
        self.assertEqual(list(outcome["modules"]), ["module1", "module6"])

        failed = [row for row in outcome["pipeline_trace"] if row["status"] == "failed"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["module"], "module2")
        self.assertEqual(failed[0]["reason"], "RuntimeError")

        blocked = {
            row["module"]: row for row in outcome["pipeline_trace"] if row["status"] == "blocked"
        }
        self.assertEqual(set(blocked), {"module3", "module4", "module5"})
        self.assertEqual(blocked["module3"]["blocked_by"], ["module2"])
        self.assertEqual(blocked["module4"]["blocked_by"], ["module3"])  # 阻塞会级联
        self.assertEqual(blocked["module5"]["blocked_by"], ["module4"])
        self.assertEqual(blocked["module3"]["reason"], BLOCKED_REASON)

        # 下游拿不到失败模块的摘要，但仍拿得到成功上游的摘要
        third = runner.context_of("module6")
        self.assertNotIn(MODULE_LABELS["module2"], third)
        self.assertIn(MODULE_LABELS["module1"], third)

    def test_completed_with_gaps_upstream_still_runs_downstream_with_notice(self) -> None:
        runner = _FakeRunner(gaps={"module2": ["未提供账户级 CPC", "标签待后台核对"]})
        outcome = run_pipeline(None, runner=runner)

        # 带缺口完成不阻塞：六个模块全部执行
        self.assertEqual([name for name, _ in runner.calls], PIPELINE_ORDER)
        self.assertEqual(len(outcome["modules"]), 6)

        # 直接下游（module3 硬前序含 module2）拿到缺口提示
        third_party_ctx = runner.context_of("module3")
        self.assertIn("注意：上游", third_party_ctx)
        self.assertIn(MODULE_LABELS["module2"], third_party_ctx)
        self.assertIn("缺口数 2", third_party_ctx)

        by_module = {row["module"]: row for row in outcome["pipeline_trace"]}
        self.assertEqual(by_module["module2"]["module_status"], "completed_with_gaps")
        self.assertEqual(by_module["module2"]["unresolved_gap_count"], 2)
        self.assertEqual(by_module["module1"]["module_status"], "completed")

    def test_blocked_module_is_not_executed_at_all(self) -> None:
        runner = _FakeRunner(failing={"module4"})
        outcome = run_pipeline(None, runner=runner)
        self.assertNotIn("module5", [name for name, _ in runner.calls])
        blocked = [row for row in outcome["pipeline_trace"] if row["status"] == "blocked"]
        self.assertEqual([row["module"] for row in blocked], ["module5"])

    def test_upstream_limit_caps_injected_digests(self) -> None:
        runner = _FakeRunner()
        run_pipeline(None, runner=runner, upstream_limit=1)

        third = runner.context_of("module6")
        self.assertIn(MODULE_LABELS["module2"], third)      # 仅最近一段
        self.assertNotIn(MODULE_LABELS["module1"], third)

        # limit=1 时优先保留共享词表 handoff，而不是模块6 短摘要
        fourth = runner.context_of("module3")
        self.assertIn(SHARED_KEYWORD_HANDOFF_HEADER, fourth)
        self.assertNotIn(MODULE_LABELS["module2"], fourth)

    def test_shared_keyword_handoff_reaches_module3(self) -> None:
        runner = _FakeRunner()
        outcome = run_pipeline(None, runner=runner, module_names=["module6", "module3"])
        ctx = runner.context_of("module3")
        self.assertIn(SHARED_KEYWORD_HANDOFF_HEADER, ctx)
        handoff = build_shared_keyword_handoff(M6_OUTPUT)
        self.assertTrue(handoff.startswith(SHARED_KEYWORD_HANDOFF_HEADER))
        self.assertTrue(
            any(row.get("status") == "shared_keyword_handoff" for row in outcome["pipeline_trace"])
        )

    def test_upstream_limit_zero_disables_injection(self) -> None:
        runner = _FakeRunner()
        run_pipeline(None, runner=runner, upstream_limit=0)
        self.assertTrue(all(context == "" for _, context in runner.calls))


# ---------------------------------------------------------------------------
# 硬前序判定（engine 侧编排复用同一函数）
# ---------------------------------------------------------------------------
class PrerequisiteTest(unittest.TestCase):
    def test_prerequisites_match_dependency_order(self) -> None:
        self.assertEqual(
            PREREQUISITES,
            {
                "module2": ["module1"],
                "module6": ["module1"],
                "module3": ["module2", "module6"],
                "module4": ["module3"],
                "module5": ["module4"],
            },
        )
        # 前序必须在 PIPELINE_ORDER 里排在本模块之前
        for name, prerequisites in PREREQUISITES.items():
            for prerequisite in prerequisites:
                self.assertLess(
                    PIPELINE_ORDER.index(prerequisite), PIPELINE_ORDER.index(name), name
                )

    def test_should_block_on_failed_or_blocked_prerequisite(self) -> None:
        self.assertEqual(should_block("module3", {"module2": "failed", "module6": "completed"}), ["module2"])
        self.assertEqual(should_block("module3", {"module2": "blocked", "module6": "blocked"}), ["module2", "module6"])
        self.assertEqual(should_block("module5", {"module4": "failed"}), ["module4"])

    def test_should_not_block_on_completed_or_gaps_or_absent(self) -> None:
        self.assertEqual(should_block("module3", {"module2": "completed", "module6": "completed"}), [])
        self.assertEqual(should_block("module3", {"module2": "completed_with_gaps", "module6": "completed"}), [])
        # 本次运行没跑的前序（子集执行）不阻塞
        self.assertEqual(should_block("module5", {}), [])
        self.assertEqual(should_block("module1", {}), [])
        self.assertEqual(should_block("module9", {"module4": "failed"}), [])
        self.assertEqual(should_block("module5", None), [])

    def test_build_gap_notice_only_for_gapped_prerequisites(self) -> None:
        notice = build_gap_notice(
            "module3",
            {"module2": "completed_with_gaps", "module6": "completed"},
            {"module2": ["a", "b", "c"]},
        )
        self.assertIn(MODULE_LABELS["module2"], notice)
        self.assertIn("缺口数 3", notice)
        self.assertNotIn(MODULE_LABELS["module6"], notice)
        self.assertEqual(build_gap_notice("module3", {"module2": "completed"}, {}), "")

    def test_module_status_of_falls_back_to_grounding(self) -> None:
        self.assertEqual(module_status_of({"module_status": "completed_with_gaps"}), "completed_with_gaps")
        self.assertEqual(module_status_of({"grounding_check": {"passed": True}}), "completed")
        self.assertEqual(module_status_of({"grounding_check": {"passed": False}}), "completed_with_gaps")
        self.assertEqual(module_status_of({"module_status": "胡说"}), "completed_with_gaps")
        self.assertEqual(module_status_of(None), "completed_with_gaps")


if __name__ == "__main__":
    unittest.main()
