const $ = (s) => document.querySelector(s);
const form = $("#form");
let historyExample = null;
let fullCaseExample = null;
let latest = null;
let boardPollTimer = null;
let categoryNoteEvidence = [];
let creatorEvidence = [];
let competitorEvidence = [];
let competitorBenchmarkBrief = null;
let currentMockSeed = "";
const SESSION_STORAGE_KEY = "xhs_agent_session_id";

function createSessionId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  if (globalThis.crypto?.getRandomValues) {
    const values = new Uint32Array(4);
    globalThis.crypto.getRandomValues(values);
    return [...values].map(value => value.toString(16).padStart(8, "0")).join("-");
  }
  return `local-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

function getOrCreateSessionId() {
  const existing = localStorage.getItem(SESSION_STORAGE_KEY);
  if (existing) return existing;
  const created = createSessionId();
  localStorage.setItem(SESSION_STORAGE_KEY, created);
  return created;
}

let currentSessionId = getOrCreateSessionId();

function renderSessionState(state=null) {
  const sessionId = state?.session_id || currentSessionId;
  const count = Number(state?.analysis_count || 0);
  const report = state?.last_report_id ? ` · ${state.last_report_id.slice(0, 12)}` : "";
  $("#sessionState").textContent = `会话 ${sessionId.slice(0, 8)} · 已完成 ${count} 次分析${report}`;
}

function newSession() {
  currentSessionId = createSessionId();
  localStorage.setItem(SESSION_STORAGE_KEY, currentSessionId);
  latest = null;
  $("#result").classList.add("hidden");
  $("#error").classList.add("hidden");
  renderSessionState();
}

function createMockSeed() {
  if (globalThis.crypto?.getRandomValues) {
    const values = new Uint32Array(2);
    globalThis.crypto.getRandomValues(values);
    return `mock-${values[0].toString(16)}-${values[1].toString(16)}`;
  }
  return `mock-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function ensureMockSeed() {
  if (!currentMockSeed) currentMockSeed = createMockSeed();
  $("#mockSeed").value = currentMockSeed;
  return currentMockSeed;
}

const moduleNames = {
  module_1_market_competitor: "01 赛道与竞品",
  module_2_audience_content: "02 用户与内容",
  module_3_keyword_creator: "03 关键词与达人",
  module_4_spotlight_decision: "04 聚光决策",
  module_5_budget_pacing: "05 全域预算与节奏",
  module_6_keyword_strategy: "06 关键词策略",
  bonus_content_audit: "加分 内容审核",
  bonus_ab_test: "加分 A/B测试",
  bonus_competitor_monitor: "加分 竞品监控",
};

const fieldNames = {
  analysis_window_days: "分析时间范围（天）",
  organic_market: "1. 自然流量大盘",
  spotlight_market: "2. 聚光投放大盘（2026最新）",
  competitor_full_funnel: "3. 竞品全域投放拆解",
  risk_warning: "4. 风险预警",
  status: "数据状态",
  sample_size: "样本数量",
  keywords_covered: "覆盖关键词",
  publication_interaction_trend: "笔记发布量／互动量趋势",
  granularity: "统计粒度",
  series: "趋势明细",
  date: "日期",
  note_count: "笔记数量",
  interactions: "互动量",
  decision_conclusion: "决策结论",
  traffic_peak_hours: "流量高峰时段",
  hours: "高峰时段明细",
  hour: "发布时间段",
  average_interactions: "平均互动量",
  warning: "证据边界",
  evidence_boundary: "证据边界",
  total_interactions: "总互动量",
  average_interactions_per_note: "篇均互动量",
  interaction_breakdown: "互动量构成",
  likes: "点赞",
  favorites: "收藏",
  comments: "评论",
  shares: "分享",
  observed_hot_tags: "平台扶持标签／样本热门标签",
  top_tags: "热门标签（兼容视图）",
  tags: "标签",
  tag: "标签名称",
  sample_count: "样本数",
  next_action: "下一步动作",
  popular_content_formats: "内容热门形式",
  content_formats: "内容形式（兼容视图）",
  popular_content_format_conclusion: "热门形式决策结论",
  format: "内容类型",
  sampling_warning: "抽样限制",
  source_names: "数据来源",
  latest_collected_at: "最近采集时间",
  average_cpc: "品类平均 CPC",
  average_cpm: "品类平均 CPM",
  conversion_cost: "平均转化成本",
  value: "数值",
  unit: "单位",
  source: "证据来源",
  collected_at: "采集时间",
  popular_promotion_goals: "热门推广目标（种草／成交／客资）",
  requested_goal: "本次推广目标",
  market_ranking: "市场热度排序",
  required_fields: "所需数据字段",
  search_feed_budget_share: "搜索与信息流预算占比",
  search_ratio: "搜索预算占比",
  feed_ratio: "信息流预算占比",
  latest_traffic_direction_2026: "平台最新流量倾斜方向",
  conclusion: "事实结论",
  benchmarks: "已接入指标证据",
  cpc: "CPC",
  cpm: "CPM",
  ctr: "CTR",
  cost_per_interaction: "单次互动成本",
  organic_content_ctr: "自然内容点击率",
  organic_interaction_rate: "自然内容互动率",
  accounts: "竞品账号／笔记证据",
  account: "竞品账号",
  url: "证据链接",
  ad_labeled: "是否带广告标识",
  ad_note_status: "广告笔记识别状态",
  campaign_duration: "投放时长",
  days: "天数",
  audience_signals: "受众画像信号",
  evidence_status: "证据状态",
  organic_hits_commonalities: "竞品自然流量爆款共性",
  observed_formats: "已观察内容形式",
  content_gaps: "竞品内容空白点",
  opportunities: "机会点",
  paid_notes: "正在投流的笔记识别",
  confirmed_count: "已确认广告笔记数",
  notes: "笔记明细",
  targeting_inference: "竞品聚光定向推测",
  budget_range: "竞品大致预算范围",
  low_cny: "预算下限（元）",
  high_cny: "预算上限（元）",
  required_evidence: "所需证据",
  recent_restricted_content_types: "近期被限流／违规的内容类型",
  confirmed_types: "已确认类型",
  official_sources: "官方证据来源",
  title: "规则标题",
  rule_title: "规则标题",
  risk_item: "官方审核／违规风险项",
  source_url: "官方链接",
  source_updated_at: "官方更新时间",
  frequent_ad_rejection_reasons: "聚光广告拒审高频原因",
  confirmed_reasons: "已确认原因",
  baseline_checks: "发布与投放前检查",
  official_rules: "官方规则（合规底线）",
  category_high_frequency_violations: "赛道高频违规／拒审台账",
  ranked_reasons: "按频次排序原因",
  account_ledger_reasons: "账户台账原因",
  topic_pipeline: "选题生成管线",
  theme_clusters: "证据主题聚类",
  daily_schedules: "每日投放时段",
  slots: "时段明细",
  role: "时段角色",
  budget_share_hint: "预算份额提示",
  action: "执行动作",
  test_bandwidth: "测试带宽",
  cold_start_budget_cny: "首轮测试预算（元）",
  stop_loss: "止损公式",
  risk_playbook: "投流问题应对 SOP",
  demo_scenario: "Mock 演示诊断情景",
  example_diagnosis: "示例诊断",
  demo_signals: "演示信号指标",
  sample_note_count: "样本笔记数",
  sample_avg_interactions: "样本均互动",
  paid_risk_demo_scenarios: "投流问题 Mock 情景",
  creator_candidates: "达人候选（含 Mock 演示项时会标注）",
  creator_recommendations_20: "达人候选列表",
  creator_roster: "达人编制与开放槽位",
  open_slots: "开放检索槽位",
  is_recommendation: "是否真实推荐",
  mock_candidate_count: "Mock 演示候选数",
  real_candidate_count: "真实候选数",
  trending_monitor: "热搜／趋势监控",
  scored_keywords: "已评分热搜词",
  keyword_pipeline: "关键词生成管线",
  pipeline: "生成管线",
  data_type: "数据类型",
  is_mock: "是否模拟",
  source_name: "来源名称",
  as_of: "适用日期",
  evidence_grade: "证据等级",
  mock_basis: "模拟依据",
  mock_seed: "Mock种子",
  scenario: "低／中／高情景",
  low: "低位情景",
  base: "中位情景",
  high: "高位情景",
};

const fieldName = (key) => fieldNames[key] || key.replaceAll("_", " ");

const esc = (v) => String(v ?? "—").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const lines = (v) => v.split(/\n+/).map(x => x.trim()).filter(Boolean);

async function updateKnowledgeStatus() {
  const target = $("#knowledgeStatus");
  try {
    const response = await fetch("/knowledge/status");
    if (!response.ok) throw new Error("状态读取失败");
    const status = await response.json();
    target.textContent = status.total_notes
      ? `已保存 ${status.total_notes} 条笔记，累计互动 ${Number(status.total_interactions).toLocaleString()}，官方规则 ${status.total_official_rules || 0} 份，共 ${status.import_batches} 个笔记导入批次。`
      : "知识库为空，请导入采集器生成的 category_notes.json。";
  } catch (error) {
    target.textContent = `知识库暂不可用：${error.message}`;
  }
}

async function getHistory() {
  if (!historyExample) historyExample = await fetch("/example/history").then(r => r.json());
  return historyExample;
}

async function getFullCase() {
  if (!fullCaseExample) fullCaseExample = await fetch("/example/full-case").then(r => r.json());
  return fullCaseExample;
}

function fill(data) {
  for (const [key, value] of Object.entries(data)) {
    const el = form.elements[key];
    if (!el) continue;
    if (key === "selling_points" || key === "competitor_links" || key === "competitor_candidates") el.value = value.join("\n");
    else el.value = value ?? "";
  }
}

$("#loadHistory").addEventListener("click", async () => {
  const data = await getHistory();
  fill(data);
  $("#useEvidence").checked = true;
  $("#brief").scrollIntoView({behavior: "smooth"});
});

function setCompetitorEvidence(rows, statusText) {
  competitorEvidence = Array.isArray(rows) ? rows : [];
  const el = $("#competitorEvidenceStatus");
  if (el) el.textContent = statusText;
}

async function loadCompetitorBenchmark() {
  const data = await fetch("/example/competitor-benchmark").then(r => r.json());
  if (data.competitor_links?.length && form.elements.competitor_links) {
    form.elements.competitor_links.value = data.competitor_links.join("\n");
  }
  // 默认只填链接，让服务端抓取给定链接并自动合成四章看板
  competitorBenchmarkBrief = null;
  setCompetitorEvidence(
    [],
    `已填入 ${ (data.competitor_links || []).length } 条对标链接；生成时将抓取这些链接并自动输出四章拆解。`,
  );
}

$("#loadFullCase").addEventListener("click", async () => {
  const data = await getFullCase();
  fill(data);
  categoryNoteEvidence = data.category_note_evidence || [];
  creatorEvidence = data.creator_evidence || [];
  competitorBenchmarkBrief = data.competitor_benchmark_brief || null;
  setCompetitorEvidence(
    data.competitor_evidence || [],
    `已载入全案对标看板：${ (data.competitor_evidence || []).length } 条证据` +
      (competitorBenchmarkBrief ? " + 拆解文案" : "") +
      "（生成后见「赛道与竞品深度分析」页）。",
  );
  const trending = (data.trending_keyword_evidence || [])
    .map(item => item.heat_score != null ? `${item.keyword}|${item.heat_score}` : item.keyword)
    .join("\n");
  if (form.elements.trending_keywords) form.elements.trending_keywords.value = trending;
  $("#categoryDataStatus").textContent = `已载入全案示例笔记 ${categoryNoteEvidence.length} 条（本次请求携带；知识库仍可另行导入）。`;
  $("#creatorCsvStatus").textContent = `已载入全案示例达人 ${creatorEvidence.length} 位真实候选。`;
  $("#useEvidence").checked = true;
  $("#brief").scrollIntoView({behavior: "smooth"});
});

$("#loadCompetitorBenchmark")?.addEventListener("click", async () => {
  try {
    await loadCompetitorBenchmark();
    $("#brief").scrollIntoView({behavior: "smooth"});
  } catch (error) {
    setCompetitorEvidence([], `载入失败：${error.message}`);
  }
});

$("#competitorEvidenceFile")?.addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    const parsed = JSON.parse(await file.text());
    const rows = Array.isArray(parsed)
      ? parsed
      : (parsed.competitor_evidence || []);
    if (!Array.isArray(rows) || !rows.length) {
      throw new Error("需要数组，或含 competitor_evidence 数组的对象");
    }
    if (rows.length > 5) throw new Error("对标证据最多 5 条");
    if (parsed.competitor_links?.length && form.elements.competitor_links) {
      form.elements.competitor_links.value = parsed.competitor_links.join("\n");
    }
    competitorBenchmarkBrief = parsed.competitor_benchmark_brief || null;
    setCompetitorEvidence(
      rows,
      `已导入 ${rows.length} 条对标证据` +
        (competitorBenchmarkBrief ? " + 拆解看板文案" : "") +
        "（生成后见「赛道与竞品深度分析」页）。",
    );
  } catch (error) {
    competitorBenchmarkBrief = null;
    setCompetitorEvidence([], `导入失败：${error.message}`);
    event.target.value = "";
  }
});

form.addEventListener("reset", () => {
  setTimeout(() => {
    $("#useEvidence").checked = true;
    $("#useModel").checked = false;
    $("#useAgentModules").checked = false;
    $("#allowMock").checked = false;
    currentMockSeed = createMockSeed();
    $("#mockSeed").value = currentMockSeed;
    $("#mockSeed").disabled = true;
    $("#regenerateMock").disabled = true;
    categoryNoteEvidence = [];
    creatorEvidence = [];
    competitorBenchmarkBrief = null;
    setCompetitorEvidence(
      [],
      "可导入对标证据 JSON，或点「载入珍妮曲奇对标看板」。生成后在结果页「赛道与竞品深度分析」查看完整看板。",
    );
    $("#categoryDataStatus").textContent = "选择采集器生成的 category_notes.json；数据将写入本机 SQLite 知识库。";
    $("#creatorCsvStatus").textContent = "列：name,profile_url,followers,average_interactions,quote_cny,audience_tags,past_campaign_result,source_name,collected_at。无 CSV 时不输出推荐名单。";
  });
});

$("#allowMock").addEventListener("change", (event) => {
  $("#mockSeed").disabled = !event.target.checked;
  $("#regenerateMock").disabled = !event.target.checked;
  if (event.target.checked) ensureMockSeed();
});

$("#regenerateMock").addEventListener("click", () => {
  currentMockSeed = createMockSeed();
  $("#mockSeed").value = currentMockSeed;
  form.requestSubmit();
});

$("#refreshKnowledge").addEventListener("click", updateKnowledgeStatus);

$("#categoryDataFile").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    const parsed = JSON.parse(await file.text());
    if (!Array.isArray(parsed)) throw new Error("文件根节点必须是数组");
    if (parsed.length > 1000) throw new Error("单次最多导入1000条笔记");
    categoryNoteEvidence = parsed;
    $("#categoryDataStatus").textContent = `正在写入 ${parsed.length} 条笔记…`;
    const response = await fetch("/knowledge/import", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(parsed),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail?.[0]?.msg || result.detail || "知识库导入失败");
    $("#categoryDataStatus").textContent =
      `导入完成：新增 ${result.inserted_count} 条，更新 ${result.updated_count} 条，知识库共 ${result.total_notes} 条。`;
    await updateKnowledgeStatus();
  } catch (error) {
    categoryNoteEvidence = [];
    event.target.value = "";
    $("#categoryDataStatus").textContent = `导入失败：${error.message}`;
  }
});

$("#creatorCsvFile").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    const body = new FormData();
    body.append("file", file);
    $("#creatorCsvStatus").textContent = "正在解析达人 CSV…";
    const response = await fetch("/creators/parse-csv", {method: "POST", body});
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail?.[0]?.msg || result.detail || "CSV 解析失败");
    creatorEvidence = result.creators || [];
    $("#creatorCsvStatus").textContent = `已解析 ${result.count} 位真实达人候选；无证据不会补造推荐名单。`;
  } catch (error) {
    creatorEvidence = [];
    event.target.value = "";
    $("#creatorCsvStatus").textContent = `导入失败：${error.message}`;
  }
});

function parseTrendingKeywords(raw) {
  const today = new Date().toISOString().slice(0, 10);
  return lines(raw || "").map(line => {
    const [keyword, heat] = line.split("|").map(x => x.trim());
    return {
      keyword,
      source_name: "人工粘贴热搜词",
      collected_at: today,
      heat_score: heat ? Number(heat) : null,
      notes: "页面人工粘贴后评分",
    };
  }).filter(item => item.keyword);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  $("#error").classList.add("hidden");
  $("#loading").classList.remove("hidden");
  try {
    const values = Object.fromEntries(new FormData(form).entries());
    const payload = {
      ...values,
      selling_points: lines(values.selling_points),
      draft_title: (values.draft_title || "").trim() || null,
      draft_body: (values.draft_body || "").trim() || null,
      draft_tags: lines(values.draft_tags || ""),
      draft_image_urls: lines(values.draft_image_urls || ""),
      draft_video_urls: lines(values.draft_video_urls || ""),
      competitor_links: lines(values.competitor_links || ""),
      competitor_candidates: lines(values.competitor_candidates || ""),
      price_min: Number(values.price_min),
      price_max: Number(values.price_max),
      total_budget_cny: Number(values.total_budget_cny),
      spotlight_budget_cny: values.spotlight_budget_cny ? Number(values.spotlight_budget_cny) : null,
      campaign_days: Number(values.campaign_days),
      analysis_days: Number(values.analysis_days),
      competitor_evidence: competitorEvidence,
      competitor_benchmark_brief: competitorBenchmarkBrief,
      benchmark_evidence: [],
      creator_evidence: creatorEvidence,
      category_note_evidence: categoryNoteEvidence,
      trending_keyword_evidence: parseTrendingKeywords(values.trending_keywords || ""),
      account_violation_evidence: [],
      constraints: ["不得虚构实时平台数据", "竞品仅抓取用户给定链接，禁止全站爬取"],
    };
    delete payload.trending_keywords;
    const linkLines = payload.competitor_links || [];
    // 文本框里有对标链接时：强制实时抓取这些链接；丢掉旧证据/示例看板，避免帝苑空行等脏数据
    if (linkLines.length) {
      delete payload.competitor_benchmark_brief;
      competitorBenchmarkBrief = null;
      payload.competitor_evidence = [];
      competitorEvidence = [];
    } else if (!payload.competitor_benchmark_brief) {
      delete payload.competitor_benchmark_brief;
    }
    const useEvidence = $("#useEvidence").checked;
    if (useEvidence) {
      const data = await getHistory();
      payload.benchmark_evidence = data.benchmark_evidence;
      payload.owned_history_summary = data.owned_history_summary;
      payload.constraints = [
        ...(data.constraints || []),
        "竞品仅抓取用户给定链接，禁止全站爬取",
      ];
    }
    if (fullCaseExample?.account_violation_evidence?.length && creatorEvidence.length) {
      payload.account_violation_evidence = fullCaseExample.account_violation_evidence;
    }
    const useModel = $("#useModel").checked;
    // 历史基准与本地知识库是同一套默认证据入口；保留后端 use_knowledge 参数兼容 API。
    const useKnowledge = useEvidence;
    const useAgentModules = $("#useAgentModules").checked;
    const allowMock = $("#allowMock").checked;
    if (allowMock) ensureMockSeed();
    const idempotencyKey = createSessionId();
    const fetchCompetitors = linkLines.length > 0;
    const response = await fetch(`/analyze?use_model=${useModel}&use_knowledge=${useKnowledge}&allow_mock=${allowMock}&use_agent_modules=${useAgentModules}&fetch_competitors=${fetchCompetitors}&mock_seed=${encodeURIComponent(currentMockSeed)}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Session-ID": currentSessionId,
        "Idempotency-Key": idempotencyKey,
      },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail?.[0]?.msg || result.detail || "生成失败");
    latest = result;
    const fetchStep = (result.trace || []).find(step => step.step === "competitor_fetch");
    if (fetchStep && $("#competitorEvidenceStatus")) {
      const fetched = fetchStep.fetched || 0;
      const total = fetchStep.evidence_count || 0;
      $("#competitorEvidenceStatus").textContent =
        `本次对标：抓取成功 ${fetched} 条，进入分析 ${total} 条` +
        (fetchStep.brief_refreshed ? "；已按新链接重算对标看板" : "");
    }
    render(result, payload);
    $("#result").classList.remove("hidden");
    $("#result").scrollIntoView({behavior: "smooth"});
  } catch (err) {
    $("#error").textContent = err.message;
    $("#error").classList.remove("hidden");
  } finally {
    $("#loading").classList.add("hidden");
  }
});

function render(result, payload) {
  $("#resultTitle").textContent = `${payload.brand_name}｜${payload.product_name}`;
  const executive = result.report_view.executive_summary;
  const budget = executive.budget_focus;
  const gapCount = Number(executive.gap_count || result.evidence_gaps?.length || 0);
  const ungrounded = Number(executive.agent_ungrounded_count || 0);
  $("#summary").innerHTML = [
    ["数据可信度", result.data_confidence.toUpperCase()],
    ["总预算", `¥${Number(budget.total_cny).toLocaleString()}`],
    ["自然内容", `¥${Number(budget.organic_cny).toLocaleString()}`],
    ["聚光投流", `¥${Number(budget.spotlight_cny).toLocaleString()}`],
    ["证据缺口", String(gapCount)],
    ...(executive.mock_seed ? [["Mock种子", executive.mock_seed]] : []),
    ...(ungrounded ? [["未溯源Agent", String(ungrounded)]] : []),
  ].map(([k,v], i) => `<div class="${i===0?"accent":""}"><span>${esc(k)}</span><b>${esc(v)}</b></div>`).join("");
  renderGaps(result, executive);
  renderSessionState(result.session_state);
  const hasBenchmark = Boolean(result.report_view?.competitor_benchmark_board?.available);
  setResultView(hasBenchmark ? "benchmark" : "tools");
}

function renderGaps(result, executive) {
  const gaps = (executive && executive.evidence_gaps)
    || (result.report_view?.evidence_appendix?.evidence_gaps)
    || (result.evidence_gaps || []);
  const alerts = (executive && executive.agent_grounding_alerts) || [];
  const parts = [];
  if (gaps.length) {
    parts.push(`<div class="gap"><b>证据缺口（${gaps.length}）</b>${gaps.map(g =>
      `<p><b>${esc(g.field || "")}</b>：${esc(g.impact || "")}<br><small>建议来源：${esc(g.recommended_source || "")}</small></p>`
    ).join("")}</div>`);
  } else {
    parts.push(`<div class="gap ok"><b>证据缺口</b><p>当前关键证据齐全，或缺口已在章节证据边界中说明。</p></div>`);
  }
  if (alerts.length) {
    parts.push(`<div class="gap"><b>数字未溯源告警（${alerts.length}）</b>${alerts.map(a =>
      `<p><b>${esc(a.module_label || a.engine_key || "")}</b>：decision_source=${esc(a.decision_source || "llm_agent_ungrounded")} · ${esc(a.mismatch_count || 0)} 处未溯源</p>`
    ).join("")}</div>`);
  }
  $("#gaps").innerHTML = parts.join("");
}

function getAudienceSection(view=latest?.report_view) {
  return (view?.report_sections || []).find(s => s.key === "audience") || null;
}

function getKeywordStrategySection(view=latest?.report_view) {
  return (view?.report_sections || []).find(s => s.key === "keyword_strategy") || null;
}

function getCreatorKeywordSection(view=latest?.report_view) {
  return (view?.report_sections || []).find(s => s.key === "creator_keyword") || null;
}

function getSpotlightDecisionSection(view=latest?.report_view) {
  return (view?.report_sections || []).find(s => s.key === "spotlight_decision") || null;
}

function getBudgetPacingSection(view=latest?.report_view) {
  return (view?.report_sections || []).find(s => s.key === "budget") || null;
}

function setResultView(viewName) {
  if (!latest) return;
  if (viewName === "board") viewName = "tools";
  if (viewName !== "tools") stopBoardAutoRefresh();
  const board = latest.report_view?.competitor_benchmark_board;
  const audience = getAudienceSection();
  const kwStrategy = getKeywordStrategySection();
  const keywords = getCreatorKeywordSection();
  const spotlight = getSpotlightDecisionSection();
  const budget = getBudgetPacingSection();
  if (viewName === "benchmark" && !board?.available) {
    viewName = audience ? "audience" : (kwStrategy ? "kwstrategy" : (keywords ? "keywords" : (spotlight ? "spotlight" : (budget ? "budget" : "tools"))));
  }
  if (viewName === "audience" && !audience) {
    viewName = kwStrategy ? "kwstrategy" : (keywords ? "keywords" : (spotlight ? "spotlight" : (budget ? "budget" : "tools")));
  }
  if (viewName === "kwstrategy" && !kwStrategy) {
    viewName = keywords ? "keywords" : (spotlight ? "spotlight" : (budget ? "budget" : "tools"));
  }
  if (viewName === "keywords" && !keywords) {
    viewName = spotlight ? "spotlight" : (budget ? "budget" : "tools");
  }
  if (viewName === "spotlight" && !spotlight) {
    viewName = budget ? "budget" : "tools";
  }
  if (viewName === "budget" && !budget) {
    viewName = "tools";
  }
  if (viewName === "report") {
    viewName = board?.available ? "benchmark" : (budget ? "budget" : "tools");
  }
  $("#resultViews").querySelectorAll("button").forEach(button => {
    button.classList.toggle("active", button.dataset.view === viewName);
    if (button.dataset.view === "benchmark") {
      button.classList.toggle("hidden", !board?.available);
    }
    if (button.dataset.view === "audience") {
      button.classList.toggle("hidden", !audience);
    }
    if (button.dataset.view === "kwstrategy") {
      button.classList.toggle("hidden", !kwStrategy);
    }
    if (button.dataset.view === "keywords") {
      button.classList.toggle("hidden", !keywords);
    }
    if (button.dataset.view === "spotlight") {
      button.classList.toggle("hidden", !spotlight);
    }
    if (button.dataset.view === "budget") {
      button.classList.toggle("hidden", !budget);
    }
  });
  const body = $(".result-body");
  if (viewName === "benchmark") {
    body.classList.add("report-mode");
    $("#tabs").classList.add("hidden");
    renderCompetitorBenchmarkBoard(board);
  } else if (viewName === "audience") {
    body.classList.add("report-mode");
    $("#tabs").classList.add("hidden");
    renderAudiencePersonaSheet(audience);
  } else if (viewName === "kwstrategy") {
    body.classList.add("report-mode");
    $("#tabs").classList.add("hidden");
    renderKeywordStrategySheet(kwStrategy);
  } else if (viewName === "keywords") {
    body.classList.add("report-mode");
    $("#tabs").classList.add("hidden");
    renderCreatorKeywordSheet(keywords);
  } else if (viewName === "spotlight") {
    body.classList.add("report-mode");
    $("#tabs").classList.add("hidden");
    renderSpotlightDecisionSheet(spotlight);
  } else if (viewName === "budget") {
    body.classList.add("report-mode");
    $("#tabs").classList.add("hidden");
    renderBudgetPacingSheet(budget);
  } else if (viewName === "tools") {
    body.classList.add("report-mode");
    $("#tabs").classList.add("hidden");
    renderAddonToolsSheet(latest.report_view || {});
    startBoardAutoRefresh();
  } else {
    body.classList.remove("report-mode");
    $("#tabs").classList.remove("hidden");
    renderEvidenceAppendix(latest.modules, latest.report_view?.evidence_appendix || {});
  }
}

function renderModuleSheet(section, fallbackTitle, heroSmall) {
  if (!section) {
    $("#module").innerHTML = `<div class="gap"><b>${esc(fallbackTitle)}</b><p>暂无该章节，请重新生成方案。</p></div>`;
    return;
  }
  $("#module").innerHTML = `<div class="benchmark-board module-sheet">
    <div class="bench-hero">
      <small>${esc(heroSmall)}</small>
      <h2>${esc(section.title || fallbackTitle)}</h2>
      <p>${esc(section.decision || "")}</p>
    </div>
    ${metricCards(section.visuals?.metric_cards || [])}
    ${sectionVisuals(section)}
    <section class="bench-section">
      <div class="section-heading"><small>ACTIONS</small><h3>建议动作与验证指标</h3></div>
      <div class="report-prose">
        <div><h4>建议动作</h4>${bulletList(section.actions || [], "action-list")}</div>
        <div><h4>验证指标</h4>${bulletList(section.success_metrics || [], "metric-list")}</div>
      </div>
      <div class="boundary-note"><b>证据边界</b><span>${esc(section.evidence_boundary || "")}</span></div>
    </section>
    ${agentDecisionBlock(section)}
  </div>`;
}

function renderAudiencePersonaSheet(section) {
  renderModuleSheet(section, "目标用户精准画像", "MODULE 2 · AUDIENCE PERSONA");
}

function renderKeywordStrategySheet(section) {
  renderModuleSheet(section, "关键词策略", "MODULE 6 · KEYWORD STRATEGY");
}

function renderCreatorKeywordSheet(section) {
  renderModuleSheet(section, "关键词与达人匹配", "MODULE 3 · KEYWORDS & CREATORS");
}

function renderSpotlightDecisionSheet(section) {
  renderModuleSheet(section, "聚光投流前置决策（含投手执行）", "MODULE 4 · SPOTLIGHT + OPERATOR");
}

function renderBudgetPacingSheet(section) {
  renderModuleSheet(section, "全域预算与节奏规划", "MODULE 5 · FULL-FUNNEL BUDGET & PACING");
}

function scopeBadge(scopeLabel, scope="window") {
  if (!scopeLabel) return "";
  const cls = scope === "full" ? "scope-full" : "scope-window";
  return `<em class="data-badge scope-badge ${cls}">${esc(scopeLabel)}</em>`;
}

function brandMonthlyTrendTable(org={}, analysisDays=30) {
  const brandRows = (org.brand_natural_rows || []).filter(row => row && row.month);
  const cats = org.trend_categories || [];
  const counts = org.trend_note_counts || [];
  const exposure = org.trend_exposure_wan || [];
  const rows = brandRows.length
    ? brandRows
    : cats.map((month, index) => ({
      month,
      supply: counts[index],
      note_count: counts[index],
      exposure_wan: exposure[index],
    }));
  if (!rows.length || (!rows.some(r => Number(r.supply ?? r.note_count) > 0) && !rows.some(r => Number(r.exposure_wan) > 0))) {
    return "";
  }
  const kbMonths = (org.trend_series || [])
    .map(row => String(row.date || "").slice(0, 7))
    .filter(Boolean);
  const aligned = kbMonths.length
    ? `KB 趋势月份：${kbMonths.slice(0, 6).join("、")}${kbMonths.length > 6 ? "…" : ""}`
    : "KB 趋势按北京时间日期聚合；下表月份已规范为 YYYY-MM。";
  return `<div class="section-heading"><small>BRAND HISTORY</small><h4>品牌自然内容表 ${scopeBadge(`近${analysisDays}天筛选`, "window")}</h4>
    <p class="bench-caption">来自 workbook organic_metrics；「内容供给」=篇数。${esc(aligned)}</p>
  </div>${reportTable(rows, [
    {label: "月份", value: "month"},
    {label: "内容供给(篇)", value: r => r.supply ?? r.note_count},
    {label: "曝光(万)", value: "exposure_wan"},
    {label: "点击", value: r => r.clicks == null || r.clicks === "" ? "—" : r.clicks},
  ])}`;
}

function peakSlotChart(slots=[]) {
  const rows = (slots || []).filter(row => Number(row.count) > 0 || Number(row.note_count) > 0);
  if (!rows.length) return '<div class="chart-empty">暂无高峰分布（需 KB 笔记带 published_at）</div>';
  const values = rows.map(row => Number(row.count ?? row.note_count) || 0);
  const max = Math.max(...values, 1);
  const width = 520, height = 220, padL = 42, padR = 16, padT = 18, padB = 42;
  const innerW = width - padL - padR;
  const innerH = height - padT - padB;
  const barW = Math.min(72, innerW / Math.max(rows.length, 1) * 0.6);
  const gap = innerW / Math.max(rows.length, 1);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map(ratio => Math.round(max * ratio));
  const grid = ticks.map(tick => {
    const y = padT + innerH - (tick / max) * innerH;
    return `<line x1="${padL}" y1="${y}" x2="${width - padR}" y2="${y}" class="axis"/><text x="${padL - 8}" y="${y + 4}" text-anchor="end" class="chart-tick">${tick}</text>`;
  }).join("");
  const bars = rows.map((row, index) => {
    const value = values[index];
    const h = (value / max) * innerH;
    const x = padL + gap * index + (gap - barW) / 2;
    const y = padT + innerH - h;
    const label = row.slot || row.hour || "";
    return `<rect x="${x}" y="${y}" width="${barW}" height="${Math.max(h, 1)}" rx="4" class="peak-bar"/>
      <text x="${x + barW / 2}" y="${y - 6}" text-anchor="middle" class="chart-tick">${value}</text>
      <text x="${x + barW / 2}" y="${height - 14}" text-anchor="middle" class="chart-tick">${esc(label)}</text>`;
  }).join("");
  return `<div class="report-chart peak-chart">
    <div class="chart-head"><b>伴手礼/相关笔记发布时间分布</b><span>published_at → 北京时间</span></div>
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="流量高峰时段柱状图">
      ${grid}${bars}
      <line x1="${padL}" y1="${padT + innerH}" x2="${width - padR}" y2="${padT + innerH}" class="axis"/>
    </svg>
  </div>`;
}

function competitorBenchmarkBoardHtml(board, marketSection=null) {
  if (!board?.available) {
    return `<div class="gap"><b>赛道与竞品深度分析</b><p>请粘贴 3–5 条竞品笔记链接并生成方案；系统将抓取给定链接，并输出自然流量大盘、聚光投放大盘、竞品拆解与风险预警。</p></div>`;
  }
  const org = board.section_organic || {};
  const spot = board.section_spotlight || {};
  const comp = board.section_competitor || {};
  const risk = board.section_risk || {};
  const metrics = spot.metrics || {};
  const organicVisuals = marketSection?.visuals?.organic || {};
  const spotlightVisuals = marketSection?.visuals?.spotlight || {};
  const trendSeries = org.trend_series?.length ? org.trend_series : (organicVisuals.trend_series || []);
  const peakHours = organicVisuals.peak_hours || [];
  const pills = (board.pills || []).map(p => `<span class="bench-pill">${esc(p)}</span>`).join("");
  const stats = (board.hero_stats || []).map(s =>
    `<div class="bench-stat ${s.tone === "warning" ? "warn" : ""}"><b>${esc(s.value)}</b><span>${esc(s.label)}</span></div>`
  ).join("");
  const sampleDash = (value) => {
    if (value === null || value === undefined || value === "" || value === "待接入") return "—";
    if (typeof value === "number") return value.toLocaleString();
    return String(value);
  };
  const samples = reportTable(board.sample_notes || [], [
    {label: "账号", value: "account"},
    {label: "内容角度", value: r => sampleDash(r.angle)},
    {label: "形式", value: r => sampleDash(r.format)},
    {label: "赞", value: r => sampleDash(r.likes)},
    {label: "藏", value: r => sampleDash(r.collects)},
    {label: "评", value: r => sampleDash(r.comments)},
    {label: "广告标识", value: r => sampleDash(r.ad_label)},
    {label: "抓取时间", value: r => sampleDash(r.published)},
  ]);
  const list = (items) => `<ul class="bench-list">${(items || []).map(i => `<li>${esc(i)}</li>`).join("")}</ul>`;
  const peakSource = (org.peak_slots || []).length
    ? org.peak_slots
    : (org.peak_hours_beijing || peakHours).map(row => ({
      slot: row.hour || row.slot,
      count: row.note_count ?? row.count,
      average_interactions: row.average_interactions,
    }));
  const peakTableRows = peakSource.map(row => ({
    hour: row.slot || row.hour,
    note_count: row.count ?? row.note_count,
    average_interactions: row.average_interactions,
  }));
  const monthly = reportTable(spot.monthly_rows || [], [
    {label: "月份", value: "month"},
    {label: "消费(¥)", value: "spend"},
    {label: "CPC", value: "cpc"},
    {label: "CPM", value: "cpm"},
    {label: "CTR", value: "ctr"},
  ], "暂无聚光月度明细（需导入投流月度表或 brief.spotlight_monthly）");
  const commonality = reportTable(comp.commonality_rows || [], [
    {label: "维度", value: "dimension"},
    {label: "观察", value: "observation"},
  ], "暂无爆款共性明细（需对标笔记主题/形式证据）");
  const paidNotes = reportTable(comp.paid_note_rows || [], [
    {label: "笔记", value: "note"},
    {label: "广告标识", value: "ad_label"},
    {label: "内容类型", value: "content_type"},
    {label: "投放时长判断", value: "duration_judgment"},
  ], "暂无投流笔记明细（需给定链接抓取结果）");
  const targeting = (comp.targeting_cards || []).map(card =>
    `<article class="bench-card"><h4>${esc(card.title)}</h4><p>${esc(card.body)}</p></article>`
  ).join("");
  const counters = reportTable(board.counter_actions || [], [
    {label: "优先级", value: "priority"},
    {label: "动作", value: "action"},
    {label: "对应空白", value: "gap"},
  ], "暂无可执行反击条目");
  const cpc = metrics.cpc == null ? "—" : (typeof metrics.cpc === "number" ? `¥${Number(metrics.cpc).toFixed(2)}` : esc(metrics.cpc));
  const cpm = metrics.cpm == null ? "—" : (typeof metrics.cpm === "number" ? `¥${Number(metrics.cpm).toFixed(2)}` : esc(metrics.cpm));
  const ctr = metrics.ctr == null ? "—" : (typeof metrics.ctr === "number" ? `${(metrics.ctr * 100).toFixed(1)}%` : esc(metrics.ctr));
  const interaction = metrics.interaction_cost == null
    ? "—"
    : (typeof metrics.interaction_cost === "number" ? `¥${Number(metrics.interaction_cost).toFixed(2)}` : esc(metrics.interaction_cost));
  const cpa = metrics.conversion_cost == null || metrics.conversion_cost === ""
    ? "缺口"
    : (typeof metrics.conversion_cost === "number" ? `¥${Number(metrics.conversion_cost).toFixed(2)}` : esc(metrics.conversion_cost));
  const analysisDays = board.analysis_days || latest?.request?.analysis_days || 30;
  const windowLabel = `近${analysisDays}天`;
  const trendMeta = [
    org.trend_sample_size != null ? `趋势/高峰全量 ${org.trend_sample_size} 条` : "",
    org.window_sample_size != null ? `${windowLabel}窗口样本 ${org.window_sample_size} 条` : "",
    org.trend_granularity ? `粒度 ${org.trend_granularity}` : "",
  ].filter(Boolean).join(" · ");
  const windowMetricCards = [
    {
      label: "窗口样本",
      value: org.window_sample_size,
      unit: "条",
      scope: "window",
      scope_label: windowLabel,
    },
    {
      label: "窗口篇均互动",
      value: org.window_average_interactions,
      unit: "次",
      scope: "window",
      scope_label: windowLabel,
    },
    {
      label: "趋势/高峰样本",
      value: org.trend_sample_size,
      unit: "条",
      scope: "full",
      scope_label: "全量命中",
    },
  ];
  const spotlightExtras = spotlightVisuals.scenario_rows?.length
    ? reportTable(spotlightVisuals.scenario_rows, [
      {label:"指标", value:"metric"},
      {label:"参考值", value:r => {
        if (r.value == null || r.value === "") return "缺口";
        if (typeof r.value === "number" && r.unit) return `${formatMetric(r.value)} ${r.unit}`;
        if (typeof r.value === "number") return formatMetric(r.value);
        return r.value;
      }},
      {label:"来源/状态", value:"source"},
    ])
    : "";

  const insight = board.agent_insight || {};
  const insightHtml = insight.applied
    ? `<div class="gap ok agent-insight"><b>DeepSeek 模块 Agent 已写入看板文案</b>
        <p>${esc(insight.note || "数字图表仍由本地计算；共性/空白/定向/应对文案来自 Agent。")}</p>
        ${insight.boundary_note ? `<p class="bench-caption">${esc(insight.boundary_note)}</p>` : ""}
        ${(insight.risk_alerts || []).length ? `<ul class="bench-list">${insight.risk_alerts.map(r =>
          `<li><b>${esc(r.risk || "")}</b> → ${esc(r.action || "")}<small> · ${esc(r.source || "")}</small></li>`
        ).join("")}</ul>` : ""}
        ${(insight.human_review_items || []).length ? `<p class="bench-caption">人工复核：${esc((insight.human_review_items || []).join("；"))}</p>` : ""}
      </div>`
    : "";

  return `<div class="benchmark-board">
    <div class="bench-hero">
      <small>MODULE 1 · MARKET & COMPETITOR</small>
      <h2>${esc(board.headline || "赛道与竞品深度分析")}</h2>
      <p>${esc(board.subtitle || "")}</p>
      <div class="bench-pills">${pills}${scopeBadge(`${windowLabel}窗口约束项已标注`, "window")}</div>
    </div>
    <div class="gap bench-boundary"><b>证据边界</b><p>${esc(board.evidence_boundary || "")}</p>
      <p class="bench-caption">橙色「${esc(windowLabel)}」标识表示该指标受分析范围限制；趋势图与高峰时段为全量命中样本，不受此限。</p>
    </div>
    ${insightHtml}
    <div class="bench-stats">${stats}</div>
    <section class="bench-section"><div class="section-heading"><small>SAMPLES</small><h3>${esc(board.brand_label || "")}对标笔记样本</h3></div>${samples}</section>
    <section class="bench-section">
      <div class="section-heading"><small>01</small><h3>自然流量大盘分析</h3><p>${esc(org.summary || "")}</p></div>
      <div class="bench-split">
        <article class="bench-card"><h4>对标内容共性</h4>${list(org.commonalities)}</article>
        <article class="bench-card"><h4>空白点</h4>${list(org.gaps)}</article>
      </div>
      ${metricCards(windowMetricCards)}
      <p class="bench-caption">${esc(org.trend_caption || "")}${trendMeta ? `（${esc(trendMeta)}）` : ""} ${scopeBadge("全量命中", "full")}</p>
      ${lineChart(trendSeries)}
      ${brandMonthlyTrendTable(org, analysisDays)}
      <div class="section-heading"><small>PEAK</small><h4>流量高峰时段（KB published_at → 北京时间） ${scopeBadge("全量命中", "full")}</h4>
        <p class="bench-caption">${esc(org.peak_warning || "按笔记发布时间转北京时间分桶；不是平台曝光高峰。")}</p>
      </div>
      ${peakSlotChart(peakSource)}
      ${peakTableRows.length ? reportTable(peakTableRows, [
        {label:"时段(北京时间)", value:"hour"},
        {label:"发布样本数", value:"note_count"},
        {label:"平均互动", value:"average_interactions"},
      ]) : ""}
      <p>${esc(org.peak_caption || "")}</p>
      <p>${esc(org.format_note || "")}</p>
    </section>
    <section class="bench-section">
      <div class="section-heading"><small>02</small><h3>聚光投放大盘分析（2026）</h3></div>
      <div class="gap ok"><b>数据说明</b><p>${esc(spot.notice || "")}</p></div>
      <div class="bench-stats compact">
        <div class="bench-stat scoped-window"><b>${cpc}</b><span>加权 CPC</span>${scopeBadge(`${windowLabel}加权`, "window")}</div>
        <div class="bench-stat scoped-window"><b>${cpm}</b><span>加权 CPM</span>${scopeBadge(`${windowLabel}加权`, "window")}</div>
        <div class="bench-stat scoped-window"><b>${ctr}</b><span>加权 CTR</span>${scopeBadge(`${windowLabel}加权`, "window")}</div>
        <div class="bench-stat scoped-window"><b>${interaction}</b><span>单次互动成本</span>${scopeBadge(`${windowLabel}加权`, "window")}</div>
        <div class="bench-stat warn"><b>${cpa}</b><span>转化成本(≠互动)</span></div>
      </div>
      <p class="bench-caption">下方月度明细为知识库导入全量月份，不受分析范围截断。${scopeBadge("全量导入月", "full")}</p>
      <div class="visual-split">${donutChart(spotlightVisuals.budget_share?.search_ratio, spotlightVisuals.budget_share?.feed_ratio)}${monthly}</div>
      ${spotlightExtras}
      <div class="bench-split">
        <article class="bench-card"><h4>热门推广目标</h4>${list(spot.goal_notes)}</article>
        <article class="bench-card"><h4>搜索 vs 信息流</h4>${list(spot.traffic_notes)}</article>
      </div>
    </section>
    <section class="bench-section">
      <div class="section-heading"><small>03</small><h3>竞品全域投放拆解</h3></div>
      <h4>爆款共性</h4>${commonality}
      <h4>正在投流笔记识别</h4>${paidNotes}
      <p class="bench-caption">${esc(comp.paid_conclusion || "")}</p>
      <h4>定向推测（评论画像 → 测试包）</h4>
      <div class="bench-split three">${targeting}</div>
    </section>
    <section class="bench-section risk-section">
      <div class="section-heading"><small>04</small><h3>风险预警</h3></div>
      <div class="bench-split">
        <article class="bench-card risk-card">
          <h4>${esc(risk.title_content || "该赛道近期被限流/违规的内容类型")}</h4>
          <p class="bench-caption">${esc(risk.content_status || "")}</p>
          ${list(risk.content_signals)}
        </article>
        <article class="bench-card risk-card">
          <h4>${esc(risk.title_rejection || "聚光广告拒审高频原因")}</h4>
          <p class="bench-caption">${esc(risk.rejection_status || "")}</p>
          ${list(risk.rejection_signals)}
          <p class="bench-caption">${esc(risk.risk_note || "")}</p>
        </article>
      </div>
      ${(risk.baseline_checks || []).length ? `<div class="risk-baseline"><h4>发布前必检</h4>${list(risk.baseline_checks)}</div>` : ""}
    </section>
    <section class="bench-section">
      <div class="section-heading"><small>NEXT</small><h3>可执行反击</h3></div>
      ${counters}
    </section>
    ${(marketSection?.actions?.length || marketSection?.success_metrics?.length) ? `
    <section class="bench-section">
      <div class="section-heading"><small>ACTIONS</small><h3>建议动作与验证指标</h3></div>
      <div class="report-prose">
        <div><h4>建议动作</h4>${bulletList(marketSection.actions || [], "action-list")}</div>
        <div><h4>验证指标</h4>${bulletList(marketSection.success_metrics || [], "metric-list")}</div>
      </div>
    </section>` : ""}
  </div>`;
}

function renderCompetitorBenchmarkBoard(board) {
  const market = (latest?.report_view?.report_sections || []).find(s => s.key === "market_competitor");
  $("#module").innerHTML = competitorBenchmarkBoardHtml(board, market);
}

function stopBoardAutoRefresh() {
  if (boardPollTimer) {
    clearInterval(boardPollTimer);
    boardPollTimer = null;
  }
}

function startBoardAutoRefresh() {
  stopBoardAutoRefresh();
  const reportId = latest?.report_id;
  if (!reportId) return;
  const seconds = Number(latest?.report_view?.dashboard?.live?.recommended_poll_seconds) || 30;
  boardPollTimer = setInterval(() => {
    const active = $("#resultViews")?.querySelector("button.active")?.dataset?.view;
    if (active === "tools" || active === "board") refreshDashboardFromServer({ silent: true });
  }, Math.max(15, seconds) * 1000);
}

async function refreshDashboardFromServer({ silent = false } = {}) {
  const reportId = latest?.report_id;
  if (!reportId) {
    if (!silent) alert("当前结果尚未落库 report_id，无法从服务端刷新看板。");
    return;
  }
  try {
    const response = await fetch(`/board/${encodeURIComponent(reportId)}?refresh=true`);
    const dashboard = await response.json();
    if (!response.ok) throw new Error(dashboard.detail || "刷新看板失败");
    latest.report_view = latest.report_view || {};
    latest.report_view.dashboard = dashboard;
    const active = $("#resultViews")?.querySelector("button.active")?.dataset?.view;
    if (active === "tools" || active === "board") {
      renderAddonToolsSheet(latest.report_view);
    }
  } catch (err) {
    if (!silent) {
      $("#error").textContent = err.message || "刷新看板失败";
      $("#error").classList.remove("hidden");
    }
  }
}

function exportDashboardLocal(format = "json") {
  const dashboard = latest?.report_view?.dashboard;
  if (!dashboard) return;
  const stamp = (dashboard.refreshed_at || "export").replace(/[:/+]/g, "");
  if (format === "json") {
    download(`dashboard-${stamp}.json`, JSON.stringify(dashboard, null, 2), "application/json");
    return;
  }
  const reportId = latest?.report_id;
  if (reportId) {
    window.open(`/board/${encodeURIComponent(reportId)}/export?format=${encodeURIComponent(format)}`, "_blank");
    return;
  }
  // 无 report_id 时本地拼一份简易 Markdown
  if (format === "markdown") {
    const lines = [
      `# ${dashboard.title || "全域投放数据看板"}`,
      "",
      ...(dashboard.kpis || []).map(k => `- ${k.label}：${k.value ?? "—"} ${k.unit || ""}`),
    ];
    download(`dashboard-${stamp}.md`, lines.join("\n"), "text/markdown");
  }
}

function buildDashboardInnerHtml(dashboard = {}, reportView = null) {
  const delivery = dashboard.delivery || {};
  const split = delivery.organic_paid_split || dashboard.organic_paid_share || {};
  const orgPct = Number.isFinite(Number(split.organic_ratio)) ? Math.round(Number(split.organic_ratio) * 100) : null;
  const paidPct = Number.isFinite(Number(split.spotlight_ratio)) ? Math.round(Number(split.spotlight_ratio) * 100) : null;
  const kpis = metricCards((dashboard.kpis || []).map(k => ({
    label: k.label, value: k.value, unit: k.unit || "", hint: k.hint || "",
  })));
  const live = dashboard.live || {};
  const feed = live.feed_status || {};
  const meta = `<div class="board-toolbar">
    <div class="board-meta">
      <span>报告 ${(dashboard.report_id || latest?.report_id || "—").toString().slice(0, 12)}</span>
      <span>生成 ${esc(dashboard.generated_at || latest?.generated_at || "—")}</span>
      <span>刷新 ${esc(dashboard.refreshed_at || "—")}</span>
      <span>实时源 ${feed.batch_count != null ? `${feed.batch_count} 批` : "未接入"} ${feed.latest_generated_at ? `· ${esc(feed.latest_generated_at)}` : ""}</span>
    </div>
    <div class="board-actions">
      <button type="button" class="link" data-board-act="refresh">刷新看板</button>
      <label class="board-auto"><input type="checkbox" id="boardAutoRefresh" checked> 自动刷新</label>
      <button type="button" data-board-act="json">导出 JSON</button>
      <button type="button" data-board-act="markdown">导出 MD</button>
      <button type="button" class="dark" data-board-act="csv">导出 CSV</button>
    </div>
  </div>`;
  const panels = (dashboard.module_panels || []).map(panel => `<article class="bench-card board-panel ${panel.is_mock ? "mock-card" : ""}">
    <h4>${esc(panel.title || "")}</h4>
    <p class="bench-caption">${esc(panel.highlight || "")}</p>
    <p>${esc(panel.decision || "")}</p>
    ${(panel.metrics || []).map(m => `<small><b>${esc(m.label || "")}</b> ${esc(m.value || "")}</small>`).join("<br>")}
    ${panel.badge ? `<em class="data-badge">${esc(panel.badge)}</em>` : ""}
  </article>`).join("");
  const phaseBars = (delivery.phases || dashboard.tables?.phases || []).map(phase => {
    const share = Number(phase.paid_ratio ?? phase.budget_ratio ?? 0);
    const pct = Number.isFinite(share) ? Math.round(share * 100) : 0;
    const money = phase.paid_budget_cny != null ? `¥${Number(phase.paid_budget_cny).toLocaleString()}` : "";
    return `<div class="phase-bar-row">
      <div class="phase-bar-label"><b>${esc(phase.name || "")}</b><span>${esc(phase.day_range || "")} · ${pct}% · ${esc(money)}</span></div>
      <div class="phase-bar-track"><i style="width:${pct}%"></i></div>
      <p class="bench-caption">${esc(phase.summary || "")}</p>
    </div>`;
  }).join("");
  const chipList = (items) => (items || []).map(i => `<span class="kw-chip">${esc(i)}</span>`).join("") || "<span class='bench-caption'>待补充</span>";
  const tiers = dashboard.keyword_tiers || {};
  const keywordBlock = `<div class="bench-split three">
    <article class="bench-card"><h4>核心词</h4><div class="bench-pills">${chipList(tiers.core)}</div></article>
    <article class="bench-card"><h4>长尾词</h4><div class="bench-pills">${chipList(tiers.long_tail)}</div></article>
    <article class="bench-card"><h4>蓝海词</h4><div class="bench-pills">${chipList(tiers.blue_ocean)}</div></article>
  </div>`;
  const orgPaidDonut = (orgPct != null && paidPct != null)
    ? `<div class="budget-chart"><div class="donut-chart" style="--search-angle:${orgPct * 3.6}deg"><b>${esc(split.ratio_label || `${orgPct}:${paidPct}`)}</b><span>自然:聚光</span></div>
        <div class="budget-legend"><p><i class="search"></i>自然 ${orgPct}%</p><p><i class="feed"></i>聚光 ${paidPct}%</p></div></div>`
    : '<div class="chart-empty">待生成自然/聚光预算拆分</div>';
  const fc = delivery.forecast || {};
  const forecastCard = `<article class="bench-card"><h4>投放效果参考</h4>
    <ul class="bench-list">
      <li>状态：${esc(fc.status || "—")}</li>
      <li>CTR / CPC / CPA：${fc.ctr != null ? esc(fc.ctr) : "—"} / ${fc.cpc != null ? `¥${esc(fc.cpc)}` : "—"} / ${fc.cpa != null ? `¥${esc(fc.cpa)}` : "—"}</li>
      <li>ROI：${fc.roi_point != null ? esc(fc.roi_point) : "—"} ${Array.isArray(fc.roi_band) ? `（${esc(fc.roi_band.join(" ~ "))}）` : ""}</li>
      <li>探测预算：${delivery.probe_budget_cny != null ? `¥${Number(delivery.probe_budget_cny).toLocaleString()}` : "—"}</li>
      <li>启动门槛：${esc((delivery.paid_start_gate || {}).rule_text || "自然过线后再投流")}</li>
    </ul>
  </article>`;
  const plans = reportTable(delivery.account_plans || [], [
    {label:"计划", value:"name"},
    {label:"目标", value:"objective"},
    {label:"版位", value:"placement"},
    {label:"预算占比", value:r => Number.isFinite(Number(r.budget_ratio ?? r.budget_share)) ? `${Math.round(Number(r.budget_ratio ?? r.budget_share)*100)}%` : ""},
  ]);
  const creators = reportTable(delivery.creator_tiers || [], [
    {label:"分层", value:"tier"},
    {label:"人数", value:"count"},
    {label:"预算占比", value:r => Number.isFinite(Number(r.budget_ratio)) ? `${Math.round(Number(r.budget_ratio)*100)}%` : ""},
    {label:"合作预算", value:"collaboration_budget_cny"},
  ]);
  const actions = reportTable(dashboard.tables?.action_plan || [], [
    {label:"优先级", value:"priority"},
    {label:"动作", value:"title"},
    {label:"预算", value:"budget_cny"},
    {label:"时间", value:"timeline"},
    {label:"负责人", value:"owner"},
  ]);
  const badges = reportTable(dashboard.tables?.execution_badges || [], [
    {label:"章节", value:"chapter"}, {label:"徽章", value:"badge"}, {label:"状态", value:"status"},
  ]);
  return `${meta}${kpis}
    <div class="section-heading"><small>MODULES</small><h3>分析结果总览</h3></div>
    <div class="board-panel-grid">${panels || "<p class='bench-caption'>暂无模块投影</p>"}</div>
    <div class="section-heading"><small>BUDGET & PACING</small><h3>预算拆分与投放节奏</h3></div>
    <div class="visual-split">${orgPaidDonut}<div>${phaseBars || "<p class='bench-caption'>暂无阶段节奏</p>"}</div></div>
    <div class="visual-split">${donutChart(dashboard.budget_share?.search_ratio ?? delivery.search_feed_share?.search_ratio, dashboard.budget_share?.feed_ratio ?? delivery.search_feed_share?.feed_ratio)}${forecastCard}</div>
    <div class="section-heading"><small>KEYWORDS</small><h3>关键词策略摘要</h3></div>${keywordBlock}
    <div class="section-heading"><small>DELIVERY</small><h3>账户计划与达人分层</h3></div>
    ${plans}${creators}
    <div class="section-heading"><small>TREND</small><h3>自然流量趋势</h3></div>
    ${lineChart(dashboard.series || [])}
    <div class="section-heading"><small>ACTIONS</small><h3>执行动作与章节状态</h3></div>
    ${actions}<div class="visual-split">${badges}<div></div></div>
    ${benchmarkSsotCard((reportView || latest?.report_view || {}).benchmark_ssot)}`;
}

function bindBoardToolbar(root) {
  root.querySelectorAll("[data-board-act]").forEach(btn => {
    btn.addEventListener("click", () => {
      const act = btn.getAttribute("data-board-act");
      if (act === "refresh") refreshDashboardFromServer();
      else exportDashboardLocal(act);
    });
  });
  const auto = root.querySelector("#boardAutoRefresh");
  if (auto) {
    auto.addEventListener("change", () => {
      if (auto.checked) startBoardAutoRefresh();
      else stopBoardAutoRefresh();
    });
  }
}

function renderAddonToolsSheet(reportView = {}) {
  const tools = reportView.addon_tools || {};
  const bonus = reportView.bonus_modules || {};
  const dashboard = reportView.dashboard || {};
  const audit = tools.content_audit || bonus.content_audit || {};
  const abPlan = tools.ab_test || bonus.ab_test || {};
  const monitor = tools.competitor_monitor || bonus.competitor_monitor || {};
  const nav = (tools.nav || [
    {id: "addon-dashboard", label: "数据看板集成"},
    {id: "addon-audit", label: "多模态内容审核"},
    {id: "addon-ab", label: "A/B测试方案生成"},
    {id: "addon-monitor", label: "竞品投放监控Agent"},
  ]).map(item => `<a href="#${esc(item.id)}">${esc(item.label)}</a>`).join("");

  const findings = (audit.findings || []).map(row =>
    `<div class="gap severity-${esc(row.severity || "low")}"><b>${esc(row.severity || "")}</b>
      <p>${esc(row.message || "")}</p>
      <small>${esc(row.rule || row.source || "")}${row.status ? ` · ${esc(row.status)}` : ""}</small></div>`
  ).join("") || '<div class="gap ok"><b>预审通过</b><p>文本侧暂未发现高风险表述。</p></div>';
  const pendingVision = (audit.pending_vision || []).map(row =>
    `<li>${esc(row.message || row.status || "")}</li>`
  ).join("");
  const gate = audit.gate_application || {};
  const gateNote = gate.blocked_topics != null || gate.creative_blocked != null
    ? `<p class="bench-caption">门禁回写：阻断付费选题 ${esc(gate.blocked_topics ?? "—")} · 创意门禁 ${gate.creative_blocked ? "未通过" : "通过"}</p>`
    : "";

  const abMatrix = reportTable((abPlan.matrix || []).slice(0, 12), [
    {label: "测哪一格", value: "cell_id"},
    {label: "内容方向", value: "direction"},
    {label: "标题", value: r => r.title_text || r.title_variant || ""},
    {label: "封面", value: r => r.cover_text || r.cover_variant || ""},
    {label: "正文要点", value: r => r.body_text || r.content_variant || ""},
    {label: "探测份额", value: r => r.probe_share_label || ""},
    {label: "最少点击", value: "min_clicks"},
  ]);
  const abMetrics = (abPlan.success_metrics || []).map(item => `<li>${esc(item)}</li>`).join("")
    || "<li>达到最小点击后再比较 CTR / 互动率</li>";

  const alerts = (monitor.alerts || []).map(row =>
    `<div class="gap severity-${esc(row.severity || "low")}"><b>${esc(row.severity || "")} · ${esc(row.type || "alert")}</b>
      <p>${esc(row.message || "")}</p>
      <small>应对：${esc(row.response || "")}</small></div>`
  ).join("") || '<div class="gap ok"><b>监控</b><p>暂无增量预警。</p></div>';
  const viral = reportTable(monitor.viral_candidates || [], [
    {label: "账号/笔记", value: "account"},
    {label: "互动", value: "interactions"},
    {label: "广告标识", value: r => r.ad_labeled ? "是" : "否"},
    {label: "形式", value: "format"},
  ]);
  const playbook = (monitor.playbook || []).map(item => `<li>${esc(item)}</li>`).join("");
  const snap = monitor.snapshot || {};

  $("#module").innerHTML = `<div class="report-document board-document addon-tools-document">
    <section>
      <div class="section-heading"><small>ADD-ON TOOLS</small><h2>${esc(tools.title || "附加工具")}</h2>
        <p>${esc(tools.subtitle || "数据看板、多模态内容审核、A/B 测试方案与竞品投放监控")}</p></div>
      <nav class="addon-tools-nav">${nav}</nav>
    </section>

    <section id="addon-dashboard" class="addon-tool-section">
      <div class="section-heading"><small>01</small><h3>数据看板集成</h3>
        <p>${esc((tools.dashboard || {}).summary || dashboard.note || "汇总模块决策、预算节奏与执行动作，支持刷新与导出。")}</p></div>
      ${buildDashboardInnerHtml(dashboard, reportView)}
    </section>

    <section id="addon-audit" class="addon-tool-section">
      <div class="section-heading"><small>02</small><h3>多模态内容审核</h3>
        <p>${esc(audit.summary || "文本规则预审 + 图/视频待视觉核验，结果回写付费选题与创意门禁。")}</p></div>
      <div class="metric-card-grid">
        <div class="metric-card"><span>风险等级</span><b>${esc(audit.risk_level || "low")}</b></div>
        <div class="metric-card"><span>是否通过</span><b>${audit.passed === false ? "未通过" : "通过"}</b></div>
        <div class="metric-card"><span>发现问题</span><b>${esc(audit.finding_count ?? (audit.findings || []).length)}</b></div>
      </div>
      ${gateNote}
      ${findings}
      ${pendingVision ? `<article class="bench-card"><h4>待视觉核验</h4><ul class="bench-list">${pendingVision}</ul></article>` : ""}
      <p class="bench-caption">${esc(audit.evidence_boundary || "")}</p>
    </section>

    <section id="addon-ab" class="addon-tool-section">
      <div class="section-heading"><small>03</small><h3>A/B测试方案生成</h3>
        <p>${esc(abPlan.summary || abPlan.what_it_is || "自动设计标题、封面、正文要点组合，并给出测试指标与判断标准。")}</p></div>
      <div class="gap ok"><b>${esc(abPlan.status_label || "仅实验计划 · 无实测效果")}</b>
        ${abPlan.probe_budget_cny != null ? `<p>探测总预算约 ¥${Number(abPlan.probe_budget_cny).toLocaleString()}${abPlan.budget_per_cell_cny != null ? ` · 每格约 ¥${Number(abPlan.budget_per_cell_cny).toLocaleString()}` : ""} · 共 ${esc(abPlan.cell_count || 0)} 格</p>` : ""}
        <ul class="bench-list">${(abPlan.how_to_read || []).map(item => `<li>${esc(item)}</li>`).join("")}</ul>
      </div>
      <article class="bench-card"><h4>测试指标与判断标准</h4>
        <ul class="bench-list">${abMetrics}</ul>
        ${abPlan.decision_rule ? `<p><b>决策规则：</b>${esc(abPlan.decision_rule)}</p>` : ""}
      </article>
      ${abMatrix}
    </section>

    <section id="addon-monitor" class="addon-tool-section">
      <div class="section-heading"><small>04</small><h3>竞品投放监控Agent</h3>
        <p>${esc(monitor.summary || "监控竞品爆款与投放加码，自动预警并给出应对策略。")}</p></div>
      <div class="metric-card-grid">
        <div class="metric-card"><span>监控状态</span><b>${esc(monitor.status || "baseline")}</b></div>
        <div class="metric-card"><span>预警数</span><b>${esc(monitor.alert_count ?? (monitor.alerts || []).length)}</b></div>
        <div class="metric-card"><span>广告标识笔记</span><b>${esc(snap.ad_labeled_count ?? "—")}</b></div>
        <div class="metric-card"><span>对标条目</span><b>${esc(snap.account_count ?? "—")}</b></div>
      </div>
      ${alerts}
      <div class="section-heading"><small>VIRAL</small><h4>高互动/疑似爆款样本</h4></div>
      ${viral}
      ${playbook ? `<article class="bench-card"><h4>应对策略手册</h4><ul class="bench-list">${playbook}</ul></article>` : ""}
      <p class="bench-caption">${esc(monitor.evidence_boundary || "")}</p>
    </section>
  </div>`;
  bindBoardToolbar($("#module"));
}

function renderDashboard(dashboard = {}, bonus = {}, reportView = null) {
  const view = reportView || latest?.report_view || {};
  view.dashboard = dashboard;
  if (bonus && Object.keys(bonus).length) view.bonus_modules = bonus;
  renderAddonToolsSheet(view);
}

function formatMetric(value) {
  if (value === null || value === undefined || value === "") return "待接入";
  if (typeof value === "number") return Number.isInteger(value)
    ? value.toLocaleString()
    : value.toLocaleString(undefined, {maximumFractionDigits: 2});
  return String(value);
}

function metricCards(cards=[]) {
  return `<div class="metric-card-grid">${cards.map(card => `
    <div class="metric-card ${card.is_mock ? "mock-card" : ""} ${card.scope === "window" ? "scoped-window" : ""} ${card.scope === "full" ? "scoped-full" : ""}">
      <span>${esc(card.label)}</span>
      <b>${esc(formatMetric(card.value))}</b>
      <small>${esc(card.unit || "")}${card.hint ? " · " + esc(card.hint) : ""}</small>
      ${card.is_mock ? '<em class="data-badge mock">Mock</em>' : ""}
      ${card.scope_label ? scopeBadge(card.scope_label, card.scope || "window") : ""}
    </div>`).join("")}</div>`;
}

function lineChart(series=[]) {
  const rows = series.filter(row => Number.isFinite(Number(row.note_count)) && Number.isFinite(Number(row.interactions)));
  if (!rows.length) return '<div class="chart-empty">缺少趋势数据，暂不绘制图表</div>';
  const width = 760, height = 230, pad = 28;
  const x = index => pad + index * ((width - pad * 2) / Math.max(1, rows.length - 1));
  const points = key => {
    const values = rows.map(row => Number(row[key]));
    const min = Math.min(...values), max = Math.max(...values);
    return values.map((value, index) => {
      const ratio = max === min ? 0.5 : (value - min) / (max - min);
      return `${x(index).toFixed(1)},${(height - pad - ratio * (height - pad * 2)).toFixed(1)}`;
    }).join(" ");
  };
  const start = rows[0].date || "开始", end = rows[rows.length - 1].date || "结束";
  return `<div class="report-chart">
    <div class="chart-head"><b>发布量／互动量趋势</b><span>${esc(start)} — ${esc(end)}</span></div>
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="发布量和互动量趋势图">
      <line x1="${pad}" y1="${height-pad}" x2="${width-pad}" y2="${height-pad}" class="axis"/>
      <polyline points="${points("note_count")}" class="line notes"/>
      <polyline points="${points("interactions")}" class="line interactions"/>
    </svg>
    <div class="chart-legend"><span><i class="notes"></i>笔记发布量（归一化）</span><span><i class="interactions"></i>互动量（归一化）</span></div>
  </div>`;
}

function donutChart(searchRatio, feedRatio) {
  if (!Number.isFinite(Number(searchRatio)) || !Number.isFinite(Number(feedRatio))) {
    return '<div class="chart-empty">待接入搜索／信息流版位消耗数据</div>';
  }
  const search = Math.round(Number(searchRatio) * 100);
  const feed = Math.round(Number(feedRatio) * 100);
  return `<div class="budget-chart"><div class="donut-chart" style="--search-angle:${search * 3.6}deg"><b>${search}%</b><span>搜索</span></div>
    <div class="budget-legend"><p><i class="search"></i>搜索推广 ${search}%</p><p><i class="feed"></i>信息流 ${feed}%</p></div></div>`;
}

function bulletList(items=[], className="") {
  return `<ul class="${className}">${items.map(item => `<li>${esc(item)}</li>`).join("")}</ul>`;
}

function reportTable(rows=[], columns=[], emptyText="当前没有可展示的明细") {
  if (!rows.length) return `<div class="chart-empty">${esc(emptyText)}</div>`;
  return `<div class="table-wrap report-table"><table><thead><tr>${columns.map(column => `<th>${esc(column.label)}</th>`).join("")}</tr></thead><tbody>${rows.slice(0, 12).map(row => `<tr class="${row.is_mock ? "mock-row" : ""}">${columns.map(column => {
    const raw = typeof column.value === "function" ? column.value(row) : row[column.value];
    return `<td>${esc(formatMetric(raw))}</td>`;
  }).join("")}</tr>`).join("")}</tbody></table></div>`;
}

function sectionVisuals(section) {
  const visuals = section.visuals || {};
  if (section.key === "market_competitor") {
    const board = latest?.report_view?.competitor_benchmark_board;
    if (board?.available) {
      // 与顶部「赛道与竞品深度分析」同一套最全内容，避免两页各缺一块
      return competitorBenchmarkBoardHtml(board, section);
    }
    const subs = section.subsections || [];
    return subs.map(sub => {
      const subVisuals = sub.visuals || visuals[sub.key] || {};
      const body = sectionVisuals({ ...sub, visuals: subVisuals });
      return `<article class="bench-section nested-chapter">
        <div class="section-heading"><small>${esc((sub.key || "").toUpperCase())}</small><h4>${esc(sub.title || "")}</h4>
          <p>${esc(sub.decision || "")}</p></div>
        ${metricCards(subVisuals.metric_cards)}
        ${body}
      </article>`;
    }).join("");
  }
  if (section.key === "organic") return `${lineChart(visuals.trend_series)}${reportTable(visuals.peak_hours, [
    {label:"高峰时段", value:"hour"}, {label:"样本数", value:"note_count"}, {label:"平均互动", value:"average_interactions"},
  ])}`;
  if (section.key === "spotlight") {
    const metricTable = reportTable(visuals.scenario_rows || [], [
      {label:"指标", value:"metric"},
      {label:"参考值", value:r => {
        if (r.value == null || r.value === "") return "缺口";
        if (typeof r.value === "number" && r.unit) return `${formatMetric(r.value)} ${r.unit}`;
        if (typeof r.value === "number") return formatMetric(r.value);
        return r.value;
      }},
      {label:"来源/状态", value:"source"},
    ]);
    const core = `<div class="visual-split">${donutChart(visuals.budget_share?.search_ratio, visuals.budget_share?.feed_ratio)}${metricTable}</div>`;
    const goals = (visuals.goal_notes || []).length
      ? `<article class="bench-card"><h4>推广目标测试优先级</h4><ul class="bench-list">${(visuals.goal_notes || []).map(i => `<li>${esc(i)}</li>`).join("")}</ul></article>`
      : "";
    const traffic = (visuals.traffic_points || []).length
      ? `<article class="bench-card"><h4>流量方向（首轮）</h4><ul class="bench-list">${(visuals.traffic_points || []).map(i => `<li>${esc(i)}</li>`).join("")}</ul></article>`
      : "";
    const side = (goals || traffic) ? `<div class="bench-split">${goals}${traffic}</div>` : "";
    const plans = reportTable(visuals.account_plans || [], [
      {label:"计划", value:"name"}, {label:"预算占比", value:r => Number.isFinite(Number(r.budget_ratio)) ? `${Math.round(Number(r.budget_ratio)*100)}%` : ""},
    ]);
    const packages = reportTable(visuals.targeting_packages || [], [
      {label:"定向包", value:"name"}, {label:"占比", value:r => Number.isFinite(Number(r.ratio)) ? `${Math.round(Number(r.ratio)*100)}%` : ""}, {label:"阶段", value:"stage"}, {label:"智能扩量", value:r => r.expansion ? "是" : "否"},
    ]);
    const slots = reportTable(visuals.daily_slots || [], [
      {label:"时段", value:"slot"}, {label:"角色", value:"role"}, {label:"动作", value:"action"}, {label:"样本数", value:"sample_note_count"},
    ]);
    return `${core}${side}<div class="section-heading"><small>MODULE 4</small><h4>账户／定向／日程</h4></div>${plans}${packages}${slots}`;
  }
  if (section.key === "spotlight_decision") {
    const hierarchy = visuals.hierarchy_logic
      ? `<article class="bench-card"><h4>计划层级划分逻辑</h4><p class="bench-caption">${esc(visuals.hierarchy_logic)}</p>
          <ul class="bench-list">
            <li>单元命名：${esc(visuals.unit_naming || "—")}</li>
            <li>创意分组：${esc(visuals.creative_grouping || visuals.creative_test || "—")}</li>
          </ul></article>`
      : "";
    const plans = reportTable(visuals.account_plans || [], [
      {label:"计划", value:"name"},
      {label:"推广目标", value:"objective"},
      {label:"版位", value:"placement"},
      {label:"预算占比", value:r => Number.isFinite(Number(r.budget_ratio ?? r.budget_share)) ? `${Math.round(Number(r.budget_ratio ?? r.budget_share)*100)}%` : ""},
    ]);
    const packages = reportTable(visuals.targeting_packages || [], [
      {label:"定向包", value:r => r.package || r.name || ""},
      {label:"人群描述", value:"audience_desc"},
      {label:"预算占比", value:r => Number.isFinite(Number(r.budget_share ?? r.ratio)) ? `${Math.round(Number(r.budget_share ?? r.ratio)*100)}%` : ""},
      {label:"适用阶段", value:r => r.applicable_stage || r.stage || ""},
      {label:"智能扩量", value:r => (r.smart_expansion ?? r.expansion) ? "开" : "关"},
    ]);
    const cold = visuals.bidding?.cold_start || {};
    const bidBlock = `<article class="bench-card"><h4>冷启动出价</h4>
      <ul class="bench-list">
        <li>方式：${esc(cold.method || "稳定成本出价")}</li>
        <li>初始出价：${cold.bid_low_cny != null || cold.bid_high_cny != null
          ? `¥${cold.bid_low_cny ?? "?"}–¥${cold.bid_high_cny ?? "?"}`
          : "待账户建议价"}</li>
        <li>依据：${esc(cold.basis || "—")}</li>
      </ul>
      <h4>放量调价规则</h4>${bulletList(visuals.bidding?.scaling_rules || [], "action-list")}
      <p class="bench-caption">止损：${esc(visuals.bidding?.stop_loss || "—")}</p>
    </article>`;
    const slots = reportTable(visuals.daily_slots || [], [
      {label:"时段", value:r => r.slot || r.time_range || ""},
      {label:"角色", value:"role"},
      {label:"动作", value:"action"},
      {label:"样本数", value:r => r.sample_note_count ?? r.note_count ?? ""},
    ]);
    const synergy = `<div class="visual-split">${donutChart(visuals.budget_share?.search_ratio, visuals.budget_share?.feed_ratio)}
      <article class="bench-card"><h4>搜推联动</h4><p class="bench-caption">${esc(visuals.synergy_note || "搜索承接后信息流二次触达")}</p></article>
    </div>`;
    const fc = visuals.forecast || {};
    const roiBand = Array.isArray(fc.roi_band) ? fc.roi_band.join(" ~ ") : (fc.roi_band || "—");
    const forecastBlock = `<article class="bench-card"><h4>效果预估</h4>
      <ul class="bench-list">
        <li>状态：${esc(fc.status || "—")}</li>
        <li>CTR参考：${fc.ctr != null && fc.ctr !== "" ? esc(fc.ctr) + (typeof fc.ctr === "number" ? "%" : "") : "缺口"}</li>
        <li>CPC参考：${fc.cpc != null ? `¥${esc(fc.cpc)}` : "缺口"}</li>
        <li>转化成本参考：${fc.cpa != null ? `¥${esc(fc.cpa)}` : "缺口"}</li>
        <li>ROI点估 / 区间：${fc.roi_point != null ? esc(fc.roi_point) : "—"} / ${esc(roiBand)}</li>
        <li>止损 CPC/CPA：${fc.stop_loss_cpc != null ? `¥${esc(fc.stop_loss_cpc)}` : "—"} / ${fc.stop_loss_cpa != null ? `¥${esc(fc.stop_loss_cpa)}` : "—"}</li>
      </ul></article>`;
    const compliance = visuals.content_audit_gate || {};
    const complianceBlock = compliance.gate || compliance.reason
      ? `<div class="gap ${compliance.block_new_creatives ? "" : "ok"}"><b>内容预审门禁 · ${esc(compliance.gate || compliance.risk_level || "")}</b>
          <p>${esc(compliance.reason || compliance.action || "")}</p>
          ${compliance.action && compliance.reason !== compliance.action ? `<small>${esc(compliance.action)}</small>` : ""}
        </div>`
      : "";
    const risks = (visuals.risk_playbook || visuals.operational_risk_playbook || []).map((row, idx) => `<article class="bench-card">
      <h4>${idx + 1}. ${esc(row.problem || row.issue || "投流问题")}</h4>
      <p class="bench-caption">${esc(row.symptom || row.diagnosis || "")}</p>
      <div class="report-prose">
        <div><h4>0–2h</h4>${bulletList(row.actions_0_2h || [], "action-list")}</div>
        <div><h4>2–24h</h4>${bulletList(row.actions_2_24h || [], "action-list")}</div>
      </div>
      <p class="bench-caption">止损/升级：${esc(row.stop_or_escalate || "—")} · 负责人：${esc(row.owner || "—")}</p>
    </article>`).join("");
    const playbook = (visuals.operator_playbook || []).map(action => {
      const budgetLabel = action.budget_kind === "probe"
        ? (action.budget_label || "探测预算（非全案投放预算）")
        : "预算";
      const budgetValue = typeof action.budget_cny === "number"
        ? `¥${action.budget_cny.toLocaleString()}${typeof action.campaign_budget_cny === "number" && action.budget_kind === "probe" ? ` · 全案聚光 ¥${Number(action.campaign_budget_cny).toLocaleString()}` : ""}`
        : "待证据确认";
      return `<article class="action-card priority-${String(action.priority || "").toLowerCase()}">
        <div class="action-head"><b>${esc(action.priority || "")}</b><div><h3>${esc(action.title || "")}</h3><p>${esc(action.why || "")}</p></div></div>
        <div class="action-meta"><span><small>负责人</small>${esc(action.owner || "")}</span><span><small>时间</small>${esc(action.timeline || "")}</span><span><small>${esc(budgetLabel)}</small>${esc(budgetValue)}</span></div>
        <div class="report-prose"><div><h4>执行步骤</h4>${bulletList(action.steps || [])}</div><div><h4>成功指标</h4>${bulletList(action.success_metrics || [])}</div></div>
        <div class="boundary-note stop"><b>止损／升级</b><span>${esc(action.stop_condition || "")}</span></div>
        <p class="dependency"><b>证据依赖：</b>${esc(action.evidence_dependency || "")}</p>
      </article>`;
    }).join("");
    const operatorBlock = playbook
      ? `<div class="section-heading"><small>6 · OPERATOR</small><h4>投手执行方案</h4>
          <p class="bench-caption">按优先级执行；达到最小样本后依据真实成本继续、调整或停止。</p></div>
          <div class="action-plan">${playbook}</div>`
      : "";
    return `${hierarchy}${complianceBlock}
      <div class="section-heading"><small>1 · ACCOUNT</small><h4>账户结构搭建</h4></div>${plans}
      <div class="section-heading"><small>2 · TARGETING</small><h4>三套差异化定向包</h4></div>${packages}
      <div class="section-heading"><small>3 · BIDDING</small><h4>出价与投放节奏</h4></div>
      <div class="bench-split">${bidBlock}<article class="bench-card"><h4>每日投放时段</h4>${slots}${visuals.schedule_warning ? `<p class="bench-caption">${esc(visuals.schedule_warning)}</p>` : ""}</article></div>
      <div class="section-heading"><small>4 · SEARCH × FEED</small><h4>搜推联动策略</h4></div>${synergy}
      <div class="section-heading"><small>5 · FORECAST & RISK</small><h4>效果预估与风控</h4></div>
      ${forecastBlock}<div class="bench-split three">${risks}</div>
      ${operatorBlock}`;
  }
  if (section.key === "competitor") return reportTable(visuals.accounts, [
    {label:"对标账号", value:"account"},
    {label:"标题", value:r => r.title || "—"},
    {label:"形式", value:"format"},
    {label:"互动", value:"interactions"},
    {label:"广告标识", value:r => r.ad_labeled === true ? "有" : r.ad_labeled === false ? "无" : "未标注"},
    {label:"用户主题", value:r => (r.content_themes || []).slice(0, 3).join("、") || "—"},
    {label:"证据备注", value:"evidence_status"},
  ]);
  if (section.key === "audience") {
    const persona = visuals.persona || {};
    const tags = visuals.targeting_tags || {};
    const screening = visuals.material_screening || {};
    const knowledge = visuals.knowledge_targeting || {};
    const listBlock = (title, items) => `<article class="bench-card"><h4>${esc(title)}</h4><ul class="bench-list">${(items || []).map(i => `<li>${esc(i)}</li>`).join("") || "<li>待补充</li>"}</ul></article>`;
    const personaBlock = `<div class="section-heading"><small>PERSONA</small><h4>三维精准用户画像</h4>
      ${persona.price_band ? `<p class="bench-caption">定价带：${esc(persona.price_band)}</p>` : ""}
      <div class="bench-split three">
        ${listBlock("人口属性", persona.demographic)}
        ${listBlock("行为属性", persona.behavioral)}
        ${listBlock("心理属性", persona.psychological)}
      </div></div>`;
    const tagBlock = `<div class="section-heading"><small>KNOWLEDGE TAGS</small><h4>聚光定向标签（知识库候选）</h4>
      <p class="bench-caption">${esc(visuals.tag_status || knowledge.warning || "须在聚光后台核对可用性")}</p>
      ${knowledge.playbook_title ? `<p class="bench-caption">命中剧本：${esc(knowledge.playbook_title)}${knowledge.playbook_id ? `（${esc(knowledge.playbook_id)}）` : ""}</p>` : ""}
      <div class="bench-split three">
        ${listBlock("兴趣标签", tags.interest_tags)}
        ${listBlock("行为标签", tags.behavior_tags)}
        ${listBlock("人群包", tags.crowd_packages)}
      </div></div>`;
    const directions = reportTable(visuals.directions || [], [
      {label:"内容方向", value:r => r.name || r.direction || ""},
      {label:"自然流量潜力", value:"organic_score"},
      {label:"投流转化潜力", value:"paid_score"},
      {label:"理由", value:r => r.rationale || ""},
    ]);
    const topics = reportTable(visuals.topics || [], [
      {label:"#", value:"id"},
      {label:"标题模板", value:"title_template"},
      {label:"方向", value:"direction"},
      {label:"主打卖点", value:r => r.selling_point_focus || ""},
      {label:"画像钩子", value:r => {
        const h = r.persona_hook || {};
        return [h.demographic, h.psychological].filter(Boolean).join("｜");
      }},
      {label:"封面建议", value:r => r.cover_suggestion || r.cover || ""},
      {label:"内容大纲", value:r => Array.isArray(r.outline) ? r.outline.map((step, idx) => `${idx + 1}.${step}`).join("；") : (r.outline || "")},
      {label:"适合投流", value:r => (r.suitable_for_paid ?? r.suitable_for_spotlight) ? "是" : "否"},
      {label:"推广目标", value:r => r.paid_objective || r.promotion_goal || ""},
      {label:"自然分", value:"organic_potential"},
      {label:"投流分", value:"paid_conversion_potential"},
    ]);
    const gate = `<div class="gap ok"><b>投流素材筛选标准</b>
      <p>${esc(screening.rule_text || `发布${screening.observation_hours || 24}小时内 CTR>${screening.ctr_percent || 10}% 且互动率>${screening.engagement_rate_percent || 7}%`)}</p>
      ${screening.warning ? `<small>${esc(screening.warning)}</small>` : ""}
    </div>`;
    return `${personaBlock}${tagBlock}<div class="section-heading"><small>DIRECTIONS</small><h4>3个差异化内容方向</h4></div>${directions}${gate}<div class="section-heading"><small>TOPICS</small><h4>15个爆款选题</h4></div>${topics}`;
  }
  if (section.key === "keyword_strategy") {
    const chipList = (items) => (items || []).map(i => `<span class="kw-chip">${esc(i)}</span>`).join("") || "<span class='bench-caption'>待补充</span>";
    const split = visuals.level_budget_split || {};
    const freq = visuals.frequency_guide || {};
    const layout = visuals.layout_plan || {};
    const layoutRule = visuals.layout_rule || {};
    const tiers = `<div class="section-heading"><small>1 · TIERS</small><h4>三级关键词库</h4>
      <p class="bench-caption">${esc(visuals.status || visuals.pipeline || "")}</p></div>
      <div class="bench-split three">
        <article class="bench-card"><h4>核心词</h4><div class="bench-pills">${chipList(visuals.core_keywords)}</div></article>
        <article class="bench-card"><h4>长尾词</h4><div class="bench-pills">${chipList(visuals.long_tail_keywords)}</div></article>
        <article class="bench-card"><h4>蓝海待验证</h4><div class="bench-pills">${chipList(visuals.blue_ocean_keywords)}</div>
          <p class="bench-caption">需搜索量/竞争度验证后再放量</p></article>
      </div>`;
    const layoutBlock = `<div class="section-heading"><small>2 · LAYOUT</small><h4>关键词布局与投放比例</h4></div>
      <div class="bench-split">
        <article class="bench-card"><h4>标题 / 正文 / 标签</h4>
          <ul class="bench-list">
            <li>标题：${esc(layoutRule.title || "")}<br><span class="bench-caption">${esc(freq.title || "")} → ${esc((layout.title_keywords || []).join("、") || "—")}</span></li>
            <li>正文：${esc(layoutRule.body || "")}<br><span class="bench-caption">${esc(freq.body || "")} → ${esc((layout.body_keywords || []).join("、") || "—")}</span></li>
            <li>标签：${esc(layoutRule.tags || "")}<br><span class="bench-caption">${esc(freq.tags || "")} → ${esc((layout.tag_keywords || []).join("、") || "—")}</span></li>
          </ul>
          ${layout.example ? `<p class="bench-caption">${esc(layout.example)}</p>` : ""}
        </article>
        <article class="bench-card"><h4>层级投放比例</h4>
          <ul class="bench-list">
            <li>核心词：${Number.isFinite(Number(split.core)) ? `${Math.round(Number(split.core)*100)}%` : "—"}</li>
            <li>长尾词：${Number.isFinite(Number(split.long_tail)) ? `${Math.round(Number(split.long_tail)*100)}%` : "—"}</li>
            <li>蓝海试探：${Number.isFinite(Number(split.blue_ocean)) ? `${Math.round(Number(split.blue_ocean)*100)}%` : "—"}</li>
          </ul>
          <p class="bench-caption">合计应为 100%；蓝海仅低价试探，验证前不放量。</p>
        </article>
      </div>`;
    const trendTable = reportTable(visuals.trending_rows || [], [
      {label:"热搜词", value:"keyword"},
      {label:"热度", value:r => r.heat_score ?? "—"},
      {label:"建议", value:r => r.recommendation || r.action || ""},
      {label:"原因", value:r => r.reason || r.notes || ""},
      {label:"来源", value:"source_name"},
    ]);
    const trendBlock = `<div class="section-heading"><small>3 · TRENDING</small><h4>热搜词监控与跟进建议</h4></div>
      <p class="bench-caption">${esc((visuals.trending_monitor || {}).status || "")} · ${esc((visuals.trending_monitor || {}).decision_rule || "")}</p>
      ${(visuals.trending_monitor || {}).how_to_supply ? `<div class="gap"><b>如何补充</b><p>${esc(visuals.trending_monitor.how_to_supply)}</p></div>` : ""}
      ${trendTable || "<p class='bench-caption'>暂无热搜评分词</p>"}`;
    return `${tiers}${layoutBlock}${trendBlock}`;
  }
  if (section.key === "creator_keyword") {
    const organic = visuals.organic_traffic || {};
    const layout = visuals.layout_plan || {};
    const layoutRule = visuals.layout_rule || {};
    const chipList = (items) => (items || []).map(i => `<span class="kw-chip">${esc(i)}</span>`).join("") || "<span class='bench-caption'>待补充</span>";
    const formatBid = (bid={}) => {
      const low = bid.low_cny_per_click, high = bid.high_cny_per_click;
      if (low == null && high == null) return "待补CPC";
      const note = bid.bid_note ? `（${bid.bid_note}）` : "";
      const fmt = v => (typeof v === "number" ? `¥${v.toFixed(2)}` : `¥${v}`);
      return `${fmt(low ?? "?")}–${fmt(high ?? "?")}${note}`;
    };
    const handoff = `<div class="gap ok"><b>已承接关键词策略</b>
      <p>${esc((visuals.keyword_strategy_ref || {}).note || organic.usage || "三级词库与布局来自关键词策略，本页聚焦聚光出价与达人匹配。")}</p>
      ${(visuals.rising_follow || []).length ? `<p>热搜跟进词：${esc((visuals.rising_follow || []).join("、"))}</p>` : ""}
    </div>`;
    const organicBlock = `<div class="section-heading"><small>HANDOFF</small><h4>承接词库（只读摘要）</h4></div>
      ${handoff}
      <div class="bench-split three">
        <article class="bench-card"><h4>核心词</h4><div class="bench-pills">${chipList(organic.core_keywords)}</div></article>
        <article class="bench-card"><h4>长尾词</h4><div class="bench-pills">${chipList(organic.long_tail_keywords)}</div></article>
        <article class="bench-card"><h4>蓝海待验证</h4><div class="bench-pills">${chipList(organic.blue_ocean_candidates_to_validate)}</div></article>
      </div>
      <div class="bench-split">
        <article class="bench-card"><h4>场景词</h4><div class="bench-pills">${chipList(organic.scene_keywords)}</div></article>
        <article class="bench-card"><h4>人群词</h4><div class="bench-pills">${chipList(organic.audience_keywords)}</div></article>
      </div>
      <article class="bench-card"><h4>达人笔记落词（承接布局）</h4>
        <ul class="bench-list">
          <li>标题：${esc(layoutRule.title || "")} → ${esc((layout.title_keywords || []).join("、") || "—")}</li>
          <li>正文：${esc(layoutRule.body || "")} → ${esc((layout.body_keywords || []).join("、") || "—")}</li>
          <li>标签：${esc(layoutRule.tags || "")} → ${esc((layout.tag_keywords || []).join("、") || "—")}</li>
        </ul>
        ${layout.example ? `<p class="bench-caption">${esc(layout.example)}</p>` : ""}
      </article>`;
    const searchTable = reportTable(visuals.search_keywords || [], [
      {label:"搜索推广词", value:"keyword"},
      {label:"意图", value:"intent"},
      {label:"建议出价", value:r => formatBid(r.suggested_bid_range || {})},
    ]);
    const feedTable = reportTable(visuals.feed_keywords || [], [
      {label:"信息流兴趣词", value:r => r.interest_word || r.keyword || ""},
      {label:"角色", value:"audience_role"},
      {label:"建议出价", value:r => formatBid(r.suggested_bid_range || {})},
    ]);
    const paidBlock = `<div class="section-heading"><small>PAID</small><h4>聚光投流关键词库（由策略词转换）</h4>
      ${visuals.bid_note ? `<div class="gap ok"><b>出价说明</b><p>${esc(visuals.bid_note)}</p></div>` : ""}
      <h4>搜索推广词（高意向长尾）</h4>${searchTable}
      <h4>信息流兴趣词（泛需求）</h4>${feedTable}</div>`;
    const tierPlan = visuals.creator_tier_plan || {};
    const tiers = reportTable(tierPlan.tiers || [], [
      {label:"分层", value:"tier"},
      {label:"人数", value:"count"},
      {label:"预算占比", value:r => Number.isFinite(Number(r.budget_ratio)) ? `${Math.round(Number(r.budget_ratio)*100)}%` : ""},
      {label:"合作预算", value:"collaboration_budget_cny"},
      {label:"笔记建议投流", value:"suggested_spotlight_per_note_cny"},
    ]);
    const creators = reportTable(visuals.top_creators || [], [
      {label:"达人", value:"name"},
      {label:"分层", value:"tier"},
      {label:"粉丝", value:"followers"},
      {label:"均互", value:"avg_interactions"},
      {label:"报价CNY", value:"quote_cny"},
      {label:"匹配度", value:"audience_match_score"},
      {label:"过往投流", value:r => r.past_paid_effect || "待复核"},
    ]);
    return `${organicBlock}${paidBlock}<div class="section-heading"><small>CREATORS</small><h4>达人分层与推荐名单</h4></div>${tiers}${creators}`;
  }
  if (section.key === "budget") {
    const split = visuals.budget_split || {};
    const orgPct = Number.isFinite(Number(split.organic_ratio)) ? Math.round(Number(split.organic_ratio) * 100) : null;
    const paidPct = Number.isFinite(Number(split.spotlight_ratio)) ? Math.round(Number(split.spotlight_ratio) * 100) : null;
    const splitCard = `<article class="bench-card">
      <h4>总预算拆分（按目标）</h4>
      <p class="bench-caption">当前目标：${esc(split.goal_label || "—")} · 建议配比自然:聚光 = <b>${esc(split.ratio_label || "—")}</b>
        ${orgPct != null && paidPct != null ? `（${orgPct}% : ${paidPct}%）` : ""}</p>
      <ul class="bench-list">
        <li>自然内容生产：${split.organic_cny != null ? `¥${Number(split.organic_cny).toLocaleString()}` : "—"}</li>
        <li>聚光投流：${split.spotlight_cny != null ? `¥${Number(split.spotlight_cny).toLocaleString()}` : "—"}</li>
      </ul>
      <p class="bench-caption">${esc(split.rationale || "")}</p>
      ${orgPct != null && paidPct != null ? `<div class="budget-chart"><div class="donut-chart" style="--search-angle:${orgPct * 3.6}deg"><b>${esc(split.ratio_label || "")}</b><span>自然:聚光</span></div>
        <div class="budget-legend"><p><i class="search"></i>自然内容 ${orgPct}%</p><p><i class="feed"></i>聚光投流 ${paidPct}%</p></div></div>` : ""}
    </article>`;
    const matrix = reportTable(visuals.goal_split_matrix || [], [
      {label:"目标", value:r => `${r.is_current ? "▶ " : ""}${r.goal_label || r.goal || ""}`},
      {label:"自然:聚光", value:"ratio_label"},
      {label:"自然占比", value:r => Number.isFinite(Number(r.organic_ratio)) ? `${Math.round(Number(r.organic_ratio)*100)}%` : ""},
      {label:"聚光占比", value:r => Number.isFinite(Number(r.paid_ratio)) ? `${Math.round(Number(r.paid_ratio)*100)}%` : ""},
      {label:"原因建议", value:"rationale"},
    ]);
    const phaseCards = (visuals.phases || []).map((phase, idx) => {
      const share = phase.budget_ratio ?? phase.ratio ?? phase.paid_ratio;
      const pct = Number.isFinite(Number(share)) ? `${Math.round(Number(share) * 100)}%` : "—";
      const money = phase.paid_budget_cny != null ? `¥${Number(phase.paid_budget_cny).toLocaleString()}` : "—";
      return `<article class="bench-card">
        <h4>${idx + 1}. ${esc(phase.name || phase.phase || "阶段")} · 投流 ${esc(pct)}</h4>
        <p class="bench-caption">${esc(phase.day_range || (phase.days != null ? `${phase.days}天` : ""))} · ${esc(money)} · ${esc(phase.owner || "")}</p>
        <p><b>${esc(phase.summary || phase.action || "")}</b></p>
        <ul class="bench-list">
          <li>自然：${esc(phase.organic_focus || "—")}</li>
          <li>聚光：${esc(phase.paid_focus || "—")}</li>
          <li>出阶段门槛：${esc(phase.exit_criteria || "—")}</li>
        </ul>
        ${bulletList(phase.key_actions || [], "action-list")}
      </article>`;
    }).join("");
    const synergy = visuals.organic_paid_synergy || {};
    const startWhen = synergy.start_paid_when || {};
    const triggerTable = reportTable(synergy.triggers || [], [
      {label:"指标", value:"metric"},
      {label:"达标阈值", value:"threshold"},
      {label:"动作", value:"action"},
    ]);
    const handoff = visuals.upstream_handoff || {};
    const synergyBlock = `<div class="section-heading"><small>3 · SYNERGY</small><h4>自然流与付费流协同</h4></div>
      <div class="gap ok"><b>何时启动投流</b>
        <p>${esc(startWhen.rule_text || synergy.principle || "自然笔记过门槛后再小预算投流")}</p>
        ${startWhen.probe_budget_cny != null ? `<p>首轮探测预算：¥${Number(startWhen.probe_budget_cny).toLocaleString()}（非全案）</p>` : ""}
        ${startWhen.warning ? `<small>${esc(startWhen.warning)}</small>` : ""}
      </div>
      ${triggerTable}
      <div class="bench-split">
        <article class="bench-card"><h4>付费撬动自然回流</h4>${bulletList(synergy.recirculation_loops || [], "action-list")}</article>
        <article class="bench-card"><h4>阶段交接</h4>
          <ul class="bench-list">${(synergy.phase_handoff || []).map(row =>
            `<li><b>${esc(row.from_phase || "")} → ${esc(row.to_phase || "")}</b>：${esc(row.condition || "")}；${esc(row.action || "")}</li>`
          ).join("") || "<li>按预热→爆发→长尾交接</li>"}</ul>
        </article>
      </div>
      ${handoff.note ? `<p class="bench-caption">${esc(handoff.note)}</p>` : ""}`;
    const emergencyCards = (visuals.emergency_playbook || []).map((row, idx) => `<article class="bench-card">
      <h4>${idx + 1}. ${esc(row.scenario || "应急场景")}</h4>
      <p class="bench-caption">${esc(row.symptom || "")} · 聚焦：${esc(row.phase_focus || "全周期")} · ${esc(row.owner || "")}</p>
      <p><b>预算调整</b>：${esc(row.budget_adjustment || "—")}</p>
      <div><h4>内容方向调整</h4>${bulletList(row.content_adjustment || [], "action-list")}</div>
    </article>`).join("");
    const emergencyBlock = `<div class="section-heading"><small>4 · CONTINGENCY</small><h4>应急调整方案</h4></div>
      <div class="bench-split">${emergencyCards || "<p class='bench-caption'>暂无应急方案</p>"}</div>`;
    return `<div class="section-heading"><small>1 · SPLIT</small><h4>总预算拆分（自然 vs 聚光）</h4></div>
      ${splitCard}
      <div class="section-heading"><small>MATRIX</small><h4>不同目标建议配比</h4></div>
      ${matrix}
      <div class="section-heading"><small>2 · PACING</small><h4>分阶段全域投放节奏</h4></div>
      <p class="bench-caption">${esc(visuals.pacing_rule || "预热20% → 爆发60% → 长尾20%（占聚光/投流预算）")}</p>
      <div class="bench-split three">${phaseCards || "<p class='bench-caption'>暂无阶段节奏</p>"}</div>
      ${synergyBlock}${emergencyBlock}`;
  }
  if (section.key === "risk") {
    const contentList = `<ul class="bench-list">${(visuals.content_types || []).map(i => `<li>${esc(i)}</li>`).join("")}</ul>`;
    const rejectList = `<ul class="bench-list">${(visuals.rejection_reasons || []).map(i => `<li>${esc(i)}</li>`).join("")}</ul>`;
    const ledger = reportTable(visuals.risk_rows || [], [
      {label:"风险／拒审原因", value:"reason"},
      {label:"次数", value:"occurrence_count"},
      {label:"周期", value:"period"},
      {label:"来源", value:"source_name"},
    ]);
    return `<div class="risk-panel">
      <div class="bench-split">
        <article class="bench-card risk-card">
          <h4>该赛道近期被限流/违规的内容类型</h4>
          <p class="bench-caption">${esc(visuals.content_status || "")}</p>
          ${contentList || "<p class='bench-caption'>暂无</p>"}
        </article>
        <article class="bench-card risk-card">
          <h4>聚光广告拒审高频原因</h4>
          <p class="bench-caption">${esc(visuals.rejection_status || "")}</p>
          ${rejectList || "<p class='bench-caption'>暂无</p>"}
        </article>
      </div>
      ${visuals.has_ledger ? `<div class="section-heading"><small>LEDGER</small><h4>拒审/违规台账</h4></div>${ledger}` : ""}
    </div>`;
  }
  return reportTable(visuals.risk_rows, [
    {label:"风险／拒审原因", value:"reason"}, {label:"次数", value:"occurrence_count"}, {label:"周期", value:"period"}, {label:"来源", value:"source_name"},
  ]);
}

// ---- 单 B 新增：Agent 决策方案 + 基准指标 SSOT 渲染 ----
function agentCellText(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (Array.isArray(value)) return value.map(agentCellText).join("、");
  if (typeof value === "object") return Object.entries(value).map(([k, v]) => `${k}:${agentCellText(v)}`).join("；");
  return formatMetric(value);
}

function agentSection(section) {
  const title = esc(section.title || "");
  if (section.kind === "table") {
    const cols = section.columns || [];
    const head = cols.map(c => `<th>${esc(c.label || "")}</th>`).join("");
    const body = (section.rows || []).map(row => `<tr>${cols.map(c => `<td>${esc(agentCellText(row[c.key]))}</td>`).join("")}</tr>`).join("");
    return `<div class="agent-section"><h5>${title}</h5><div class="table-wrap report-table"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div></div>`;
  }
  if (section.kind === "kv") {
    const items = (section.items || []).map(i => `<div class="agent-kv-row"><span>${esc(i.label || "")}</span><b>${esc(agentCellText(i.value))}</b></div>`).join("");
    return `<div class="agent-section"><h5>${title}</h5><div class="agent-kv">${items}</div></div>`;
  }
  if (section.kind === "list") {
    const items = (section.items || []).map(i => `<li>${esc(agentCellText(i))}</li>`).join("");
    return `<div class="agent-section"><h5>${title}</h5><ul>${items}</ul></div>`;
  }
  return "";
}

function agentDecisionCard(view) {
  const g = view.grounding || {};
  const passed = g.passed === true;
  const badgeClass = passed ? "agent-badge pass" : "agent-badge warn";
  const source = view.decision_source || (passed ? "llm_agent" : "llm_agent_ungrounded");
  const mismatches = (g.mismatches || []).map(m => `<li>${esc((m && m.path) || "")} = ${esc(agentCellText(m && m.value))}</li>`).join("");
  const mismatchBlock = (!passed && mismatches) ? `<div class="agent-mismatch"><b>未溯源数字：</b><ul>${mismatches}</ul></div>` : "";
  const steps = (view.steps_used !== null && view.steps_used !== undefined) ? `<span class="agent-steps">推理步数 ${esc(view.steps_used)}</span>` : "";
  const sections = (view.sections || []).map(agentSection).join("");
  // 模块状态徽标：completed=绿 / completed_with_gaps=橙 / blocked=红（02 模块状态输出契约）
  const st = view.module_status || {};
  const statusBadge = st.label ? `<span class="agent-badge status-${esc(st.tone || "green")}">${esc(st.label)}</span>` : "";
  const gaps = (st.unresolved_gaps || []).map(item => `<li>${esc(item)}</li>`).join("");
  const gapBlock = gaps ? `<div class="agent-gaps"><b>未解决缺口：</b><ul>${gaps}</ul></div>` : "";
  return `<details class="agent-decision" ${passed && st.status !== "completed_with_gaps" && st.status !== "blocked" ? "" : "open"}>
    <summary>Agent 决策方案 · ${esc(view.module_label || "")} <span class="agent-source">decision_source: ${esc(source)}</span><span class="${badgeClass}">${esc(g.badge || "")}</span>${statusBadge}${steps}</summary>
    ${gapBlock}
    ${mismatchBlock}
    <div class="agent-decision-body">${sections}</div>
  </details>`;
}

function agentDecisionBlock(section) {
  const views = section.agent_decision_views || (section.agent_decision_view ? [section.agent_decision_view] : []);
  if (!views.length) return "";
  return views.map(agentDecisionCard).join("");
}

function benchmarkSsotCard(ssot) {
  const groups = ((ssot && ssot.groups) || []).filter(g => g.conflict);
  if (!groups.length) return "";
  const same = (a, b) => !!a && !!b && a.value === b.value && a.source_name === b.source_name && a.collected_at === b.collected_at;
  const escalations = [];
  const rows = groups.map(g => {
    const sel = g.selected || {};
    const others = (g.candidates || []).filter(c => !same(c, sel)).map(c => agentCellText(c.value) + "（" + (c.source_name || "") + "）").join("；");
    // 同等级数值冲突 / 仅有 Mock 候选：不给选用值，标人工裁决（治理规范 03/04）
    const escalation = g.escalation || g.note || "";
    if (escalation) escalations.push((g.category || "") + "：" + escalation);
    const valueCell = g.selected ? `<b>${esc(agentCellText(sel.value))}</b>` : (escalation ? '<b class="ssot-escalated">待人工裁决</b>' : "");
    return `<tr><td>${esc(g.category || "")}</td><td>${valueCell}</td><td>${esc(sel.unit || "")}</td><td>${esc(sel.source_name || "")}</td><td>${esc(sel.collected_at || "")}</td><td>${esc(g.evidence_level || "")}</td><td>${esc(others)}</td></tr>`;
  }).join("");
  const escalationBlock = escalations.length
    ? `<ul class="ssot-escalations">${escalations.map(item => `<li>⚠️ ${esc(item)}</li>`).join("")}</ul>`
    : "";
  return `<section class="benchmark-ssot"><div class="section-heading"><small>METRIC SSOT</small><h3>基准指标口径（单一事实源）</h3></div>
    <p class="ssot-note">以下同类基准指标存在多来源冲突，报告统一按口径选用；下游模块引用时须注明来源。</p>
    <div class="table-wrap report-table"><table><thead><tr><th>指标类别</th><th>选用值</th><th>单位</th><th>选用来源</th><th>采集时间</th><th>证据等级</th><th>其他候选</th></tr></thead><tbody>${rows}</tbody></table></div>
    ${escalationBlock}
    <p class="ssot-policy"><b>选用规则：</b>${esc((ssot && ssot.policy) || "")}</p>
  </section>`;
}

function renderEvidenceAppendix(modules, appendix={}) {
  const agents = appendix.mock_subagents || [];
  const gaps = appendix.evidence_gaps || [];
  const gapBlock = gaps.length
    ? `<div class="gap"><b>证据缺口清单（${gaps.length}）</b>${gaps.map(g =>
        `<p><b>${esc(g.field || "")}</b>：${esc(g.impact || "")}<br><small>建议来源：${esc(g.recommended_source || "")}</small></p>`
      ).join("")}</div>`
    : "";
  const agentBlock = agents.length ? `<div class="subagent-panel"><div class="section-heading"><small>MOCK SUBAGENTS</small><h3>缺失数据子 Agent</h3><p>${esc(appendix.instruction || "")}</p></div><div class="subagent-grid">${agents.map(agent => `<article class="subagent-card ${agent.status}"><b>${esc(agent.name)}</b><span>${esc(agent.specialty)}</span><small>${esc(agent.status)} · 注入 ${agent.injected_count || 0}</small><p>${esc(agent.notes || "")}</p></article>`).join("")}</div></div>` : "";
  const coreKeys = appendix.module_keys || Object.keys(modules).filter(k => !String(k).startsWith("bonus_"));
  const bonusKeys = appendix.bonus_module_keys || Object.keys(modules).filter(k => String(k).startsWith("bonus_"));
  const keys = [...coreKeys, ...bonusKeys].filter(k => modules[k] != null);
  $("#tabs").innerHTML = keys.map((k,i) => `<button data-key="${k}" class="${i===0?"active":""}">${moduleNames[k] || k}</button>`).join("");
  $("#tabs").querySelectorAll("button").forEach(btn => btn.addEventListener("click", () => {
    $("#tabs").querySelectorAll("button").forEach(x => x.classList.remove("active"));
    btn.classList.add("active");
    renderModule(btn.dataset.key, modules[btn.dataset.key], gapBlock + agentBlock);
  }));
  renderModule(keys[0], modules[keys[0]], gapBlock + agentBlock);
}

$("#resultViews").querySelectorAll("button").forEach(button => {
  button.addEventListener("click", () => setResultView(button.dataset.view));
});

function renderModule(key, value, agentBlock="") {
  const label = moduleNames[key] || key;
  $("#module").innerHTML = `${agentBlock}<small>${esc(label)}</small><h3>${esc(label)}</h3>${tree(value)}`;
}

function dataBadge(value) {
  if (!value || typeof value !== "object") return "";
  if (value.is_mock === true) return '<span class="data-badge mock">模拟数据（Mock）</span>';
  if (value.data_type === "真实样本") return '<span class="data-badge real">真实样本</span>';
  if (value.data_type === "公开资料") return '<span class="data-badge public">公开资料</span>';
  if (value.data_type === "数据缺口") return '<span class="data-badge gap-badge">数据缺口</span>';
  return "";
}

function tree(value, depth=0) {
  if (Array.isArray(value)) {
    if (value.length && value.every(x => x && typeof x === "object")) return table(value);
    return `<ul>${value.map(x => `<li>${typeof x === "object" ? tree(x, depth+1) : esc(x)}</li>`).join("")}</ul>`;
  }
  if (value && typeof value === "object") {
    return `${dataBadge(value)}${Object.entries(value).map(([k,v]) => typeof v === "object" && v !== null
      ? `<details ${depth<1?"open":""}><summary>${esc(fieldName(k))}${Array.isArray(v)?` <em>${v.length}</em>`:""}</summary>${tree(v, depth+1)}</details>`
      : `<p><b>${esc(fieldName(k))}：</b>${k === "data_type" ? `${dataBadge(value)} ${esc(v)}` : esc(v)}</p>`).join("")}`;
  }
  return `<p>${esc(value)}</p>`;
}

function table(rows) {
  const keys = [...new Set(rows.flatMap(x => Object.keys(x)))];
  const cell = (key, value) => {
    if ((key === "url" || key.endsWith("_url")) && typeof value === "string" && value.startsWith("http")) {
      return `<a href="${esc(value)}" target="_blank" rel="noopener noreferrer">查看官方原文</a>`;
    }
    return esc(typeof value === "object" ? JSON.stringify(value) : value);
  };
  return `<div class="table-wrap"><table><thead><tr><th>数据标识</th>${keys.map(k=>`<th>${esc(fieldName(k))}</th>`).join("")}</tr></thead><tbody>${rows.map(r=>`<tr class="${r.is_mock === true ? "mock-row" : ""}"><td>${dataBadge(r) || "—"}</td>${keys.map(k=>`<td>${cell(k, r[k])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

function download(name, content, type) {
  const url = URL.createObjectURL(new Blob([content], {type}));
  const a = document.createElement("a"); a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

$("#downloadJson").addEventListener("click", () => latest && download("小红书投放全案.json", JSON.stringify(latest, null, 2), "application/json"));
$("#downloadMd").addEventListener("click", () => latest && download("小红书投放全案.md", latest.report_markdown, "text/markdown"));
$("#newSession").addEventListener("click", newSession);

ensureMockSeed();
renderSessionState();
updateKnowledgeStatus();
