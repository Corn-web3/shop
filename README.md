# SSB Listing Studio Challenge｜电商链接自动化挑战

**中文** | [English](./README.en.md)

> 这是一个面向 **AI 产品工程 / LLM 应用 / Agent 工程** 候选人的实战挑战。
> 它考察的是真实工作中最难的部分：把"一堆产品数据"经过 **多智能体编排**，端到端变成 **符合亚马逊 A+ 标准、且图文与真实物理世界一致** 的可上架链接，并能通过 **对话** 灵活地重组成多件装 / 组合装。

---

## 1. 背景 Background

SSB（SuperSonicBrick）在亚马逊等平台销售实体产品。我们的产品数据库里有完整的产品参数，但把每一个 SKU、每一种打包方式（单件 / 多件装 / 组合装）都做成一条**合规、高转化**的 Listing（标题、五点描述、A+ 图文、主图与场景图）目前是纯人工、极其耗时的工作。

我们想要一个 **Agentic 系统** 来自动完成这件事。这个挑战就是它的最小可用原型。

> ⚠️ 这不是一个"调一次大模型生成一段文案"的任务。我们明确想看到 **多智能体协作**、**工具调用**、**结果可审查**，以及对 **物理一致性** 和 **平台合规** 的工程化保证。

---

## 2. 你要构建什么 What You Build

一个可以一键启动的服务，完成以下闭环：

1. **取数**：用我们提供的连接串连接 SSB 数据库（只读），自省 schema，加载产品数据。
2. **增强 Enrich**：根据产品参数，从全网 fetch 资料，补全/校正产品参数与卖点，并保留**来源引用**。
3. **多智能体生成**：spawn 多个分工明确的 Agent，完成：
   - 全网数据采集（Research）
   - 商品图制作（Image，需与真实物理世界吻合）
   - 标题与卖点阐述（Copy，需达到亚马逊 A+ 要求）
   - 质检与编排（Critic / Supervisor）
4. **对话式重组**：通过对话把
   - 商品 **A** → **多件装（multipack）** Listing；或
   - 商品 **A + B** → **组合装（combo）** Listing。
   - 要求**图片和产品介绍都必须随之变化**，且物理参数（数量、总重、包装尺寸等）要重新计算。

---

## 3. 数据访问与密钥 Data Access & Keys

- **数据库连接串由我们提供**（单独发给你，PostgreSQL，**只读**）。
  - 请自行自省（introspect）schema：产品表大致包含 `sku / 标题 / 品牌 / 类目 / 颜色 / 材质 / 单件数量(piece/unit count) / 尺寸 / 重量 / 现有图片URL / 价格` 等字段，以实际为准。
  - **严禁写库**。任何写操作（INSERT/UPDATE/DELETE/DDL）都会被判为不通过。
- **LLM / 图像生成 / 联网检索 的 API key 由你自备**（OpenAI-compatible、任意图像生成 API、任意 web fetch/search 均可）。
  - 所有 key 走 `.env`，**禁止提交到仓库**。我们 review 时会用自己的 key 跑。
  - 即使没有配置 key，服务也应能启动，并对依赖 key 的端点返回清晰的配置提示。

---

## 4. 功能需求（分层）Functional Requirements (Tiered)

> **时间：10 天。预算：约 1500 元人民币**（你自备的 LLM / 图像生成 / 联网检索 API 花费，请控制在此额度内，并在 REPORT 中报告实际花费）。
> **Tier 0–3 与全部 Bonus（B1–B5）均为必做。** 请优先保证 **Tier 2 / Tier 3 的真实多智能体能力**，这是本挑战的核心；Bonus 用于体现你的工程完整度与上限。

### Tier 0 — 基础设施（必做）
- 用连接串连上 SSB 库，自省 schema，加载若干 seed SKU。
- 提供 `GET /products` 与 `GET /product/{sku}`，返回归一化后的产品记录。
- Docker 一键启动；`README` + `REPORT.md` + `.env.example`；仓库内无任何密钥/数据库文件。

### Tier 1 — 产品参数全网增强 Enrichment（核心）
- 给定一个 SKU，从全网 fetch 并 enrich：类目规范、竞品规格、常见卖点、合规关键词、相关认证等。
- 输出**结构化**的增强记录，必须包含：
  - 每条补全字段的 **来源引用（URL）**；
  - 置信度 / 备注字段；
  - 对**缺失或冲突数据**的优雅处理（不得编造规格）。

### Tier 2 — 多智能体生成 Listing（核心）
- **真正的多智能体编排**：≥3 个分工明确的 Agent + 一个 Supervisor / Orchestrator。推荐角色：Research、Image、Copy、Critic/QA、Supervisor。
- 产出一个 **符合亚马逊 A+ 要求** 的 Listing 对象（详见 §6 合规清单），至少包含：
  - **标题**：品牌前置、无促销词，长度合规；
  - **五点描述（5 bullets）**：以利益点为主，长度合规；
  - **产品描述 / A+ 图文模块**：模块类型 + 图片 + 文案；
  - **图片集**：主图（纯白底 RGB 255,255,255、长边 ≥1600px、产品占比 ≥85%）+ 场景图 / 信息图 / A+ 模块图（按规定尺寸，如 970×600）；
  - **后台搜索词**：≤250 bytes。
- **可审查**：输出一份 **Agent 执行轨迹（trace）**——哪个 Agent 做了什么、调用了哪些工具、产生了哪些中间产物（SSE 实时流或结构化日志均可）。
- **物理一致性（重点）**：生成的图片必须与数据库参数吻合——**单件数量、颜色、材质、比例/形态**正确。必须包含一个 **自检 / Critic 步骤**，对"图片 vs. 参数"做一致性校验并报告偏差。

### Tier 3 — 对话式重组 Multipack / Combo（核心）
- 提供 `/chat`（或带 UI 的对话）端点，用户用自然语言即可：
  - **多件装**：「把 A 做成 3 件装」→ 新标题（含数量/Pack of 3）、更新后的五点、**重新生成"展示 3 件"的图片**、重算包装重量与尺寸、更新打包相关字段。
  - **组合装**：「把 A 和 B 做成 combo」→ 合并后的标题、去重合并的卖点、**新的"同时展示 A 与 B"的组合图**、重算合并后的物理参数。
- 必须由**智能体系统驱动**（不接受纯关键词/正则状态机硬编码），需支持多轮引用与追问。
- **图片与文案都必须明显变化，并保持物理一致**（例如 3 件装的图就该有 3 件、总重≈单件×3 + 包装）。

### Bonus（同样必做 B1–B5）
- **B1 合规校验器**：自动检查并标记任何违规项（标题超长、违禁词、主图非纯白底、缺 alt 文本等），输出 pass/fail 报告。
- **B2 成本与可观测性**：统计 token、图像生成成本、各 Agent 耗时；对 enrich/生成结果做缓存。
- **B3 变体管理**：父子变体（尺寸/颜色），并基于竞品增强数据给出定价建议。
- **B4 Human-in-the-loop**：发布前的人工 Review Gate；原始 vs. 重组 Listing 的 diff 视图。
- **B5 评测 harness**：给定若干 SKU，自动对 Listing 质量 / 物理一致性打分。

---

## 5. 约束 Constraints

- **多智能体必须是真实编排**（LangGraph / CrewAI / 自研图皆可）：角色分工清晰、有 Supervisor、有中间产物传递。**单一巨型 prompt 或正则状态机在 Tier 2/3 不得分。**
- 数据库**只读**；API key **自备**；一切通过 **Docker 一键复现**。
- 增强得来的事实必须**标注来源**，不得编造规格。
- 图片必须是**生成的**（不得直接抓取竞品图），且**物理上忠实**于产品参数。

---

## 6. 亚马逊 A+ / Listing 合规清单（验收标准）

> 以下为我们验收时会核对的硬性规则（数值以亚马逊官方 2025–2026 指南为准，见文末来源）。你的系统应尽量自动满足，并在 REPORT 中说明你如何保证。

**主图 Main Image**
- 纯白背景，RGB 必须精确为 (255, 255, 255)，无阴影/渐变；
- 长边 ≥1000px，**推荐 ≥1600px**（≥1600×1600 才会触发缩放/zoom）；
- 产品占画面 ≥85%；正方形 1:1 或 5:6 竖图；sRGB；JPEG，<10MB；
- 无文字/水印/Logo/附加道具。

**标题 Title**
- 品牌前置，标题式大小写，无促销/主观词（如 best、free shipping、保证等）；
- 长度合规（多数类目 ≤200 字符，强烈建议 ≤80–150）。

**五点描述 Bullet Points**
- 最多 5 条，利益点导向；单条长度合规（通常 ≤500 字符/条）；无违禁词、无联系方式。

**A+ 图文模块 A+ Content**
- 模块图常见尺寸：标准模块 970×300、整宽 970×600、对比图 150×300、Logo 600×180；
- 单图 ≤2MB；JPEG/PNG/静态 GIF；需提供 **alt 文本（keyword 文本）**；
- 注意：真实发布 A+ 需 Brand Registry——本挑战只需**产出符合规格的内容对象与图片**即可，无需真实上传。

**后台搜索词 Backend Search Terms**：≤250 bytes。

---

## 7. 建议的接口 Suggested Endpoints

```
GET  /health
GET  /products                 # 列出可用 SKU
GET  /product/{sku}            # 归一化产品记录
POST /enrich/{sku}             # 全网增强，返回结构化记录 + 来源
POST /listing/{sku}            # 多智能体生成 A+ Listing（可返回 job_id）
GET  /trace/{job_id}           # Agent 执行轨迹（或用 SSE 实时推送）
POST /chat                     # 对话式重组：multipack / combo
```

> 接口设计可自由调整，但必须能体现：**取数 → 增强 → 多智能体生成 → 对话重组** 的完整链路，且轨迹可审查。

---

## 8. 示例交互 Example Interactions

```
POST /listing/{sku}
→ 返回 A+ Listing 对象（标题/五点/A+模块/图片集）+ job_id

GET /trace/{job_id}
→ [Research] 采集到 12 条竞品规格 ...
  [Copy] 生成标题与五点 ...
  [Image] 生成主图(纯白底) + 3 张 A+ 模块图 ...
  [Critic] 校验：图中单件数量=1 ✓ 颜色=蓝 ✓ 主图底色(255,255,255) ✓

POST /chat {"session_id":"s1","message":"把这个 SKU 做成 3 件装"}
→ 标题加 "(Pack of 3)"，五点更新，图片重画为 3 件，重量×3+包装，包装尺寸重算

POST /chat {"session_id":"s1","message":"再把它和 {另一个SKU} 组成 combo"}
→ 合并标题与卖点，生成同框组合图，物理参数重算
```

---

## 9. 交付物 Deliverables

1. **Git 仓库**：Docker 一键启动；`README`（中/英）+ `REPORT.md` + `.env.example`；无密钥。
2. **演示视频（≤5 分钟）**：展示 取数/增强 → 带 trace 的生成 → A+ 产出 → **现场对话生成一个多件装 + 一个组合装**。
3. **样例产出**：≥3 个 SKU 的 Listing（JSON + 图片），并各提交 1 个多件装、1 个组合装示例到仓库。
4. **REPORT.md** 需覆盖：
   - 架构与 **Agent 设计（含架构图）**；
   - Prompt 迭代过程；
   - 你如何保证 **A+ 合规**；
   - 你如何保证 **图片物理一致性**；
   - **AI 工具使用**：哪些是 AI 写的、哪些是你重写/推翻的；
   - 验证记录（你实际跑通了哪些、用什么 SKU 验的）；
   - 如果有更多时间会怎么做。

---

## 10. 提交方式 Submission

- 提交 **仓库链接 + 演示视频**。
- 我们会用**与示例不同的 SKU 集**在我们自己的环境用 Docker 复跑，并可能请你做一次 **现场 walkthrough**：用一个全新的 SKU 当场生成 + 对话重组。请确保流程对未见过的 SKU 也稳健。

---

## 来源 Sources（A+ / 图片规格）

- [Amazon Product Image Requirements (amalytix, 2026)](https://www.amalytix.com/en/knowledge/seo/amazon-images/)
- [Amazon Product Image Requirements Guide (squareshot)](https://www.squareshot.com/post/amazon-product-image-requirements-guide)
- [Amazon A+ Content Image Sizes — all modules (teamzlab)](https://tool.teamzlab.com/amazon/a-plus-content-image-guide/)
- [Amazon A+ Content Image Specs 2026 (flairox)](https://www.flairox.com/amazon-a-plus-content-best-practices-image-specs/)
