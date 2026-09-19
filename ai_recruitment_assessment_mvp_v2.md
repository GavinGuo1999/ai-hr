# AI 招聘测评平台 MVP v2.1（业务规则修订版）

> 目标：做一个真正能用、逻辑清楚、便于展示的企业招聘测评 MVP。
> 核心原则：**少页面、少状态、少 AI 编排、先把主业务闭环做顺。**
>
> 本版本明确删除：多 Agent、Supervisor、复杂 RAG、Wren、Waza、Ragas、复杂语义层、ChatBI 等非核心能力。

## 1. 产品目标

系统面向 HR / 招聘负责人，用来完成一次结构化应聘测评。

每次应聘都是一份独立的 `Application（应聘档案）`。

```text
HR 新建应聘档案、上传简历
    ↓
选择已有招聘岗位（岗位带 JD）
    ↓
AI 根据 JD 和简历生成初筛评分、评语并存档
    ↓
HR 查看初筛结果，决定是否推进
    ↓
HR 点击“生成测评链接”，系统抽题并冻结试卷
    ↓
候选人首次打开链接，开始 3 小时总计时
    ↓
候选人笔试
    ↓
提交答案
    ↓
AI 基于 JD + 简历 + 笔试答案发起 3 轮简单问答
    ↓
AI 综合 JD + 简历 + 笔试 + 3 轮问答给出结构化评价
    ↓
应聘档案状态变为“已完成”
    ↓
HR 在应聘详情页查看全过程和评价
```

第一版不是完整 ATS，也不做自动录用/淘汰决策。AI 输出仅作为 HR / 面试官的辅助评估材料。

初筛只供 HR 决定是否发送测评链接，绝不自动淘汰。候选人持有链接即可作答，系统不声称通过链接完成身份核验。

---

## 2. 技术栈

### 前端
- React
- TypeScript
- Vite
- Ant Design（或当前已有组件库）
- React Router
- TanStack Query（推荐）

### 后端
- Python
- FastAPI
- SQLAlchemy 2.x
- Alembic
- Pydantic
- PostgreSQL

### AI
- DeepSeek API
- LangGraph：仅用于 3 轮 AI 问答小流程，可选但建议保留
- Langfuse：保留，用于观察 prompt、耗时、token 和错误

### 文件
MVP 先用本地 `uploads/`，后续生产环境再替换 MinIO / S3 / OSS。

### 第一版不要引入
- 多 Agent / Supervisor / Handoff
- LlamaIndex
- Wren
- Waza
- Ragas
- Redis
- Celery
- Kafka
- Elasticsearch
- 向量数据库
- 自动 ChatBI
- 复杂 Prompt Router
- 自动技能图谱

原则：**能用普通 Python / SQL 完成的事情，不交给 LLM。**

---

## 3. 页面设计

HR 端：

```text
1. 应聘列表
2. 应聘详情
3. 新建应聘
4. 岗位管理
5. 题库管理
6. AI 配置
7. HR 登录
```

候选人端：

```text
/assessment/{token}
```

---

## 4. 应聘列表页

路由：

```text
/applications
```

字段：

| 字段 | 含义 |
|---|---|
| 候选人 | 姓名 |
| 招聘岗位 | 当前应聘岗位 |
| 联系方式 | 邮箱 / 手机 |
| 状态 | 当前应聘状态 |
| 创建时间 | HR 创建档案时间 |
| 开始时间 | 候选人开始答题时间 |
| 完成时间 | 整体测评完成时间 |
| 综合评分 | AI 最终综合评分 |
| 简历初筛分 | AI 初筛评分，最终评分前也可查看 |
| 操作 | 查看 |

顶部只做：
- 新建应聘
- 候选人姓名搜索
- 岗位筛选
- 状态筛选
- 创建时间排序

第一版不做复杂 Dashboard。

---

## 5. 应聘状态机

```python
class ApplicationStatus(str, Enum):
    SCREENING = "screening"                 # 简历初筛中
    SCREENING_FAILED = "screening_failed"   # 初筛失败，等待 HR 重试
    REVIEW_PENDING = "review_pending"       # 初筛已存档，等待 HR 决定
    READY = "ready"                         # 链接已发，尚未首次打开
    EXAM_IN_PROGRESS = "exam_in_progress"
    INTERVIEW_IN_PROGRESS = "interview_in_progress"
    PRACTICAL_IN_PROGRESS = "practical_in_progress" # AI 编程实操
    SUSPENDED = "suspended"                 # AI 故障后候选人主动终止本次计时
    SCORING = "scoring"
    COMPLETED = "completed"
    EXPIRED = "expired"                     # 发链接后 24 小时内未首次打开
    CANCELLED = "cancelled"                 # HR 决定不推进或取消
```

正常迁移：

```text
SCREENING → REVIEW_PENDING → READY → EXAM_IN_PROGRESS
                                        ↓ 提交笔试
                               INTERVIEW_IN_PROGRESS
                                        ↓ 完成三轮
                               PRACTICAL_IN_PROGRESS
                                        ↓ 确认实操成绩或总时限届满
                                      SCORING → COMPLETED
```

异常与恢复：

```text
SCREENING → SCREENING_FAILED → SCREENING（HR 重试）
REVIEW_PENDING → CANCELLED（HR 不推进）
READY → EXPIRED（24 小时未首次打开）
EXPIRED → READY（HR 重新生成链接，旧链接立即失效）
EXAM_IN_PROGRESS / INTERVIEW_IN_PROGRESS → SUSPENDED（仅在 AI 调用失败并展示故障按钮时）
SUSPENDED → 原答题阶段（HR 修复并重置计时）
REVIEW_PENDING / READY / EXPIRED / 进行中 / SUSPENDED → CANCELLED（HR 取消）
```

`SCORING` 调用失败仍保持该状态，并另存 `scoring_error` 供 HR 重试；候选人不需要在评分阶段按故障按钮。所有状态只能由后端业务动作修改。状态迁移、HR 决定、故障、恢复和链接换发均写入不可覆盖的事件记录。

---

## 6. 新建应聘档案

路由：

```text
/applications/new
```

表单：

```text
候选人姓名 *
邮箱
手机号

招聘岗位 *
    下拉选择已有岗位

上传简历 *
    PDF / DOCX

[创建]
```

创建时后端完成：

```text
1. 保存候选人信息
2. 保存简历文件
3. 提取简历文本
4. 读取岗位
5. 保存 JD 快照和简历文本/解析状态
6. 解析成功且文本非空：status = SCREENING，启动简历初筛（JD + 简历）；否则 status = SCREENING_FAILED，等待 HR 补文本
7. 初筛成功后保存独立的简历评分、评语、证据和 Prompt 版本，status = REVIEW_PENDING

此时不抽题、不生成候选人链接。HR 在详情页查看初筛结果，可选择“不推进”，也可点击“生成测评链接”。新五题客观测评在同一数据库事务中选出难度 3 的首题、冻结该题并签发 24 小时有效的链接，然后 status = READY；后续题逐题判分后抽取。旧版已发放的固定试卷保持原流程。初筛失败保留档案，HR 可修正简历文本并重试。若简历文本为空，不允许进入初筛或生成链接。
```

创建成功显示：

```text
应聘档案创建成功，简历初筛中
候选人：张三
岗位：AI应用工程师
[进入详情]
```

HR 点击“生成测评链接”成功后才显示一次完整链接并提供复制按钮。后台只保存 Token 的哈希和签发记录；若链接遗失，由 HR 换发新链接，旧链接立即失效。

---

## 7. 快照设计

这是本版必须实现的设计。

应聘创建后，未来岗位或题库被修改，不能影响已经发出去的测评。

Application 保存：

```text
job_id
job_name_snapshot
job_jd_snapshot
ai_config_id
ai_config_version
resume_text_snapshot
```

本次考试题保存到 `application_questions`：

```text
question_id
question_content_snapshot
question_type_snapshot
options_snapshot
standard_answer_snapshot
score_rule_snapshot
```

不要运行时重新从最新 Job / Question 读取考试内容。

简历初筛和最终评分分别绑定当时不可变的 AI 配置版本。HR 在发链接前修改解析文本必须重跑初筛；发链接后锁定本次测评使用的简历文本。配置版本不能通过原地修改旧行实现。

---

## 8. 岗位管理

路由：

```text
/jobs
```

字段：

```text
id
name
department
description
jd
status
question_count
created_at
updated_at
```

支持：
- 新建
- 编辑
- 启用
- 停用
- 查看

岗位额外维护“抽题规则”：

| 分类 | 数量 | 难度 |
|---|---:|---|
| Python | 3 | 2-4 |
| RAG | 3 | 2-4 |
| Agent | 2 | 2-4 |
| 系统设计 | 2 | 3-5 |

---

## 9. 题库管理

路由：

```text
/questions
```

字段：

```text
id
title
content
type
category
difficulty
options
reference_answer
score_points
scoring_guide
enabled
created_at
updated_at
```

第一版题型：

```text
SINGLE_CHOICE
MULTIPLE_CHOICE
SHORT_ANSWER
```

如果还要再缩，可以只做：

```text
SINGLE_CHOICE
SHORT_ANSWER
```

分类建议：

```text
Python
FastAPI
Database
RAG
Agent
SystemDesign
Business
Other
```

难度：

```text
1 - 非常简单
2 - 简单
3 - 中等
4 - 较难
5 - 困难
```

---

## 10. 抽题逻辑

第一版不要 AI 出题，不要 RAG 出题。

直接 PostgreSQL 按规则抽：

```python
for rule in job.question_rules:
    candidates = query(
        Question.category == rule.category,
        Question.enabled == True,
        Question.difficulty >= rule.min_difficulty,
        Question.difficulty <= rule.max_difficulty,
        Question.id.not_in(already_selected_ids),
    )

    selected = random_sample(candidates, rule.count)
```

抽中后复制成 ApplicationQuestion，冻结本次试卷。

所有规则合并后同一题只能出现一次；题目停用或删除不影响已发的试卷。随机抽取要记录题目 ID 与顺序，便于复盘。

五题客观测评采用自适应抽题：首题目标难度 3，候选人逐题提交且提交后不能修改；后端立即判分，答对时下一题目标难度加 1，答错时减 1，限定在 1–5。同一分类没有目标难度的可用题时，抽取未使用题中最接近的难度，记录目标和实际难度。候选人界面显示当前难度及五个进度灯：未答灰色、错误红色、正确绿色，不显示标准答案。旧版已发放试卷仍按固定试卷处理。

如果题目不足，创建应聘直接失败，并明确提示：

```text
RAG 分类要求抽 3 题，
当前符合条件的启用题目只有 2 题。
```

不要偷偷少抽。

---

## 11. 候选人测评页面与链接

路由：

```text
/assessment/{token}
```

候选人无需注册。

Token 必须：
- 随机
- 不可预测
- 足够长
- 唯一
- 签发后 24 小时内须首次打开

打开时检查：
- token 是否存在
- 是否取消
- 是否过期
- 是否已完成

首次成功打开页面的请求由后端原子地记录 `first_opened_at`，从这一刻开始 3 小时总计时，并进入 `EXAM_IN_PROGRESS`。同一候选人刷新、重试或换浏览器不重置时间。此 GET 是唯一有首次激活副作用的接口，必须设置 `Cache-Control: no-store`；页面预览器、爬虫或 HR 自测都可能误触发，因此 HR 复制链接后不要直接访问正式 Token。正式部署宜改成候选人显式点击“开始”才激活；本演示版按“首次打开”执行。

24 小时内没有首次打开才进入 `EXPIRED`。首次打开后不再按链接签发时间过期；仍可通过同一链接续答，直到完成、挂起或取消。HR 可在 `EXPIRED` 状态点击“重新生成链接”，后端签发新 Token、使旧 Token 立即失效、记录换发时间和操作者，并将状态置为 `READY`。换发只允许尚未开始的档案。

---

## 12. 首次打开与服务端计时

首次打开成功后显示：

```text
应聘岗位：AI应用工程师
候选人：张三

本次测评：
10 道笔试题
3 轮 AI 问答

本次测评总时限：
3 小时（包含笔试和 AI 问答）

仅 AI 故障挂起且经 HR 处理后可重置计时。
```

候选人首次打开时，后端在单个事务中检查 Token 和状态，设置 `first_opened_at = server_now`、`deadline_at = first_opened_at + 3 hours`、`status = EXAM_IN_PROGRESS`。并发首次打开只成功激活一次。之后的页面请求均读取同一个截止时间。

### 计时以后端为准

前端倒计时只是展示。每次读取页面、保存答案、切题、提交、读取/提交问答时，服务端返回 `server_now`、`deadline_at` 和当前状态。前端用收到的服务器时间计算时钟偏差，持续显示剩余时间；切回页面及网络恢复时再次同步。服务端按接收请求的时间判断是否超时，客户端显示不能延长时间。

后端始终根据：

```text
deadline_at - server_now
```

判断剩余时间。

刷新页面、修改本地时间、换浏览器，都不能重置考试时间。

到达总截止时间时：笔试阶段保存此前已被服务端接收的答案，自动提交并记录未答；问答阶段保存已提交的轮次，未完成轮次标为缺答。随后进入 `SCORING`，最终评价必须标明“因时间截止，测评未完整完成”并按缺答规则评分。所有写接口在截止后先执行此迁移，不再接受新答案。另用后端定时扫描处理候选人不再访问的档案；进程重启后继续扫描，状态迁移应幂等。不引入 Redis/Celery。

---

## 13. 笔试页

简单结构：

```text
──────────────────────
AI应用工程师测评

总剩余时间 02:32:15

[1] [2] [3] [4] [5]

问题：
请解释 FastAPI dependency injection 的用途。

[答题框]

上一题        下一题

             [提交]
──────────────────────
```

答案接口：

```text
PUT /api/candidate/{token}/answers/{application_question_id}
```

前端不要每个字符都保存，可使用 500-1000ms debounce，或切题时保存。

---

## 14. 笔试提交和评分

笔试阶段候选人主动提交：

```text
POST /api/candidate/{token}/exam/submit
```

后端：

```text
1. 校验当前状态
2. 保存答案
3. 自动评分客观题
4. 保存 exam_submitted_at
5. status = INTERVIEW_IN_PROGRESS
6. 创建 interview_session，并准备第一轮问题
```

笔试提交后总截止时间保持不变；没有第二个独立的 45 分钟考试时钟。到达总截止时间的自动提交按第 12 节执行，不再开始新的 AI 问答。

### 选择题

普通代码评分，不调用 LLM：

```text
candidate_answer == correct_answer
```

### 简答题

第一版不要单独调用一次模型评分。

最终综合评分时把：
- 问题
- 候选人答案
- 参考答案 / scoring guide

一起交给最终评分模型即可。

---

## 15. 三轮 AI 问答

这是唯一值得做 AI 流程的地方。

固定三轮：

```text
Round 1
AI 问
候选人答
    ↓
Round 2
AI 根据上下文追问
候选人答
    ↓
Round 3
AI 最后追问
候选人答
    ↓
Final Score
```

每轮 AI 能看到：

```text
岗位 JD
简历文本
本次笔试题目
候选人笔试答案
之前完成的 AI 问答
```

每轮问题持久化后再返回前端。提交某轮答案必须携带该轮的 `interview_turn_id`；后端只接受当前待答的一轮，先保存答案再生成下一轮，重试请求返回已有数据。`GET /interview` 只读取现有问题，不发起新的模型调用。请求级幂等键和数据库状态检查共同防止双击触发重复调用；生成中的租约/任务状态须能在进程重启后恢复。

Prompt 固定约束：

```text
只能围绕岗位能力、简历项目经历和答题内容提问。
不要询问与工作无关的敏感个人信息。
每次只问一个问题。
问题应简短、明确。
不要输出评价。
不要泄露标准答案。
```

### Round 1：简历项目

只结合简历和岗位出一道简短问题，不引用客观题或错题。

### Round 2：视首答情况出题

先按切题程度、具体做法和验证方式判断第一轮回答是否充分，不能只凭字数。充分时依据简历提出新的考察点；不充分时只针对首答缺少的关键细节追问一次。记录判断及缺口。

### Round 3：综合场景题

结合简历、第一轮回答和第二轮回答，提出新的小型岗位场景；避免重复前两轮的问题。

每轮记录问题、主要考察点及依据。生成结果与历史问题或考察点重复时重试一次；仍不合格则进入已有的 AI 故障处理流程，由候选人挂起并联系 HR。

---

## 16. LangGraph 的定位

可以保留，但只做一个非常小的 StateGraph。

```python
class InterviewState(TypedDict):
    application_id: int
    jd: str
    resume_text: str
    exam_context: list
    current_round: int
    turns: list
    current_question: str
    finished: bool
```

流程：

```text
START
  ↓
prepare_context
  ↓
generate_question
  ↓
wait_candidate_answer
  ↓
save_answer
  ↓
round < 3 ?
  ├── YES → generate_question
  └── NO  → END
```

`wait_candidate_answer` 可用 LangGraph interrupt + checkpoint。

但如果当前代码用普通 API 更简单，也可以不用 LangGraph。业务闭环优先于框架展示。

问答挂起与 HR 恢复是后端持久状态，不依赖浏览器连接或内存中的 Graph 状态。MVP 优先用普通 API 加数据库实现。

---

## 17. AI 配置页面

路由：

```text
/settings/ai
```

第一版字段：

```text
模型
API Base URL
API Key 的环境变量引用（界面只显示“已配置/未配置”）
Temperature
Max Tokens

系统提示词
简历初筛 Prompt
第一轮规则
第二轮规则
第三轮规则
最终评分 Prompt
```

第一版可共用一个模型。

配置简单带版本：

```text
id
name
version
enabled
created_at
```

每次保存：

```text
新增一条不可变的配置版本（version += 1）
```

Application 记录：

```text
ai_config_id
ai_config_version
```

便于追踪历史评分使用的 Prompt。

后台口令从本地环境变量 `HR_ADMIN_PASSWORD` 注入，服务端仅保存/校验哈希；文档、代码、样例配置、日志和版本库都不存放明文。演示后台所有 HR API 和页面都须登录；会话使用 HttpOnly、SameSite Cookie，登出后失效。AI API Key 同样从环境变量/受控密钥配置读取，AI 配置接口只返回掩码，不回传密钥原文。

首次简历初筛与最终评分都使用配置版本。初筛发生在 HR 审核之前，因此 Phase 1 至少应有“初筛待处理/失败”状态及可演示的固定结果适配器；真实 AI 初筛须在链接发放前接通，不能排到完整闭环之后。

---

## 18. 最终 AI 评分

完成 Round 3 后进入 AI 编程实操；候选人确认最高分，或总时限届满后：

```text
status = SCORING
```

然后只进行 **一次最终评分模型调用**。它与创建档案时的 **一次简历初筛模型调用** 是两个不同阶段，不计入问答三轮。失败后的单次重试/HR 手动重试是异常恢复，不应造成重复结果记录。

输入：

```text
1. JD
2. 简历
3. 所有笔试问题
4. 所有笔试答案
5. 客观题结果
6. 三轮 AI 问题
7. 三轮候选人回答
8. AI 编程实操隐藏验收分、分项结果和提交次数
9. 简历初筛结果与缺答/超时标记（初筛结果仅作背景，最终评分仍须引用原始证据）
```

评分依据优先级继续保持笔试最高、简历最低，并让实操成为独立的工程能力证据。固定权重为：笔试 35%、AI 编程实操 30%、问答 25%、简历 10%。实操由后端隐藏规则直接验收；模型返回笔试简答题和问答的分数、各维度解释与证据；简历部分直接使用 HR 审核时存档的初筛分。后端按固定权重计算总分，不直接信任模型给出的总分。客观题由代码判分；简答题和问答由模型依据明确评分要点评价。缺答记 0 分并在报告中标明原因，未完成测评不与完整测评直接排名。

AI 编程实操采用候选人专属数据包。题目要求处理乱序 Agent 轨迹、重复修正、重试语义、工具别名、依赖传播、成本和性能统计。数据规模使手工计算不可行；候选人需要在本地使用编程工具运行和迭代。包内仅使用 Python 3.11 标准库，并提供样例和结构检查器。候选人提交 `solution/solve.py`、`output/report.json` 与 `AI_WORKLOG.md` 的 ZIP；后端不执行源码，只按同一专属数据重算隐藏答案，分别验收提交完整性、总体汇总、工具与重试统计、失败根因及依赖传播、性能瓶颈。最多提交 5 次，只返回分项反馈，最终确认最高分。

每个维度必须有 0–100 的评分锚点及证据位置（题号或问答轮次）；证据不足则说明不确定性。重新评分保留旧结果和模型/配置版本，HR 详情显示最新有效结果及历史，不覆盖原评分。

结构化 JSON：

```json
{
  "overall_score": 82,
  "exam_score": 86,
  "interview_score": 80,
  "resume_score": 73,
  "dimensions": {
    "job_match": 80,
    "technical_knowledge": 84,
    "practical_experience": 86,
    "problem_solving": 78
  },
  "strengths": [
    "具备 FastAPI 实际项目经验"
  ],
  "weaknesses": [
    "分布式部署经验描述较弱"
  ],
  "risks": [
    "部分性能优化数据需要人工进一步确认"
  ],
  "evidence": [
    {
      "dimension": "practical_experience",
      "source": "interview_round_1",
      "summary": "能够说明 LangGraph State 与节点职责"
    }
  ],
  "summary": "候选人与岗位要求整体匹配，建议后续人工面试重点确认分布式部署经验。",
  "incomplete_reason": null
}
```

AI 只能基于岗位相关信息评分，不得依据年龄、性别、婚姻、民族、宗教、籍贯、照片、残障等无关敏感信息。

UI 使用“AI 辅助评价”，不要使用“AI 决定录用/淘汰”。

---

## 19. Structured Output

后端使用 Pydantic 验证：

```python
class DimensionScores(BaseModel):
    job_match: int
    technical_knowledge: int
    practical_experience: int
    problem_solving: int


class AssessmentResultSchema(BaseModel):
    overall_score: int
    exam_score: int
    interview_score: int
    resume_score: int  # 必须等于存档的简历初筛分
    dimensions: DimensionScores
    strengths: list[str]
    weaknesses: list[str]
    risks: list[str]
    evidence: list[dict]
    summary: str
    incomplete_reason: str | None
```

所有 score 限制 `0-100`。模型输出的 `overall_score` 仅用于一致性检查，实际入库总分由后端按来源权重计算；维度分展示为辅助解释。也可从模型输出中移除 `overall_score`，避免两套权威结果。

流程：

```text
LLM JSON
↓
Pydantic validation
↓
失败：Retry 1 次
↓
仍失败：记录错误，状态保持 SCORING
```

---

## 20. 应聘详情页

路由：

```text
/applications/{id}
```

顶部：

```text
张三
AI应用工程师

状态：已完成
综合评分：82

创建时间
开始时间
完成时间
```

页面按模块纵向展示：

### 基础信息
- 姓名
- 邮箱
- 手机
- 岗位

### 岗位信息
显示本次应聘的 Job Snapshot。

### 简历
- 原始文件
- 提取文本
- 下载 / 查看
- HR 在发链接前可编辑解析后的文本；修改后必须重新初筛

### 简历初筛与 HR 决定
- 初筛评分、评语、证据、模型/Prompt 版本和生成时间
- 初筛失败时显示重试
- 待审核时显示“生成测评链接”和“不推进”
- 链接签发/换发历史、首次打开时间、挂起与恢复记录

### 笔试结果
每题展示：
- 问题
- 候选人答案
- 参考答案（仅 HR）
- 客观题正确/错误
- 分值

### AI 三轮问答
完整展示 Round 1 / 2 / 3。

### AI 评价
重点展示：
- 综合评分
- 岗位匹配
- 技术知识
- 实际项目经验
- 问题解决
- 优势
- 不足
- 风险 / 待人工确认
- 评价总结
- 评分证据

---

## 21. 数据表

```text
jobs
question_rules
questions

applications
application_questions
application_answers

interview_sessions
interview_turns

assessment_results
resume_assessments
application_events
candidate_token_issues

ai_configs
```

### jobs

```text
id
name
department
description
jd
status
question_count
created_at
updated_at
```

### question_rules

```text
id
job_id
category
count
min_difficulty
max_difficulty
created_at
updated_at
```

### questions

```text
id
title
content
type
category
difficulty
options_json
correct_answer_json
reference_answer
scoring_guide
score_points
enabled
created_at
updated_at
```

### applications

```text
id
candidate_name
candidate_email
candidate_phone

job_id
job_name_snapshot
job_jd_snapshot

resume_file_path
resume_text

status

active_token_issue_id
token_issued_at
token_expires_at                  # 只限制首次打开
first_opened_at
resume_text_snapshot

created_at
started_at
deadline_at
exam_submitted_at
interview_started_at
completed_at
suspended_at
suspended_from_status
scoring_error

ai_config_id
ai_config_version
```

### application_questions

```text
id
application_id
question_id
order_no
question_content_snapshot
question_type_snapshot
category_snapshot
difficulty_snapshot
options_snapshot_json
correct_answer_snapshot_json
reference_answer_snapshot
scoring_guide_snapshot
score_points_snapshot
```

### application_answers

```text
id
application_id
application_question_id
answer_json
answer_text
is_correct
objective_score
saved_at
submitted_at
```

### interview_sessions

```text
id
application_id
current_round
started_at
finished_at
```

### interview_turns

```text
id
session_id
round_no
question
answer
question_created_at
answer_created_at
```

限制：

```text
round_no = 1 / 2 / 3
UNIQUE(session_id, round_no)
```

### assessment_results

```text
id
application_id
overall_score
job_match_score
technical_score
experience_score
problem_solving_score
strengths_json
weaknesses_json
risks_json
evidence_json
summary
raw_model_output
model_name
prompt_version
ai_config_id
ai_config_version
exam_score
interview_score
resume_score
incomplete_reason
created_at
```

评分结果按版本追加，另存 `attempt_no`、`supersedes_result_id`，不原地覆盖历史。

### resume_assessments

```text
id
application_id
resume_text_version
score
comment
evidence_json
model_name
ai_config_id
ai_config_version
created_at
```

初筛仅依据岗位相关能力和简历证据，不使用照片、年龄、性别等无关敏感信息；结果是 HR 审核材料。模型按 100 分制分别返回制造业场景经验、AI 与 Agent 能力、MVP 与工程交付、沟通与治理四个维度，后端按 30%、30%、25%、15% 加权计算初筛总分，避免模型误用 10 分制。评语必须说明与分数一致的优势和缺口。

### candidate_token_issues / application_events

```text
candidate_token_issues: id, application_id, token_hash, issued_at, first_opened_at, invalidated_at, invalidation_reason
application_events: id, application_id, actor_type, action, from_status, to_status, reason, created_at
```

换发链接保留旧签发记录，旧 Token 立即失效。事件包含初筛、HR 推进/不推进、过期、换发、超时、挂起、修复和重置计时。不得在日志或 Langfuse 中记录完整 Token。

### ai_configs

```text
id
name
version                 # (name, version) 唯一，每版不可变
enabled
base_url
model
api_key_reference       # 环境/密钥配置引用，不回传明文
temperature
max_tokens
system_prompt
round1_prompt
round2_prompt
round3_prompt
scoring_prompt
screening_prompt
created_at
updated_at
```

---

## 22. API

### HR - Applications

```text
GET    /api/applications
POST   /api/applications
GET    /api/applications/{id}
POST   /api/applications/{id}/cancel
POST   /api/applications/{id}/screening/retry
POST   /api/applications/{id}/rescreen-current-job
PUT    /api/applications/{id}/resume-text
POST   /api/applications/{id}/issue-link
POST   /api/applications/{id}/regenerate-token
POST   /api/applications/{id}/resume-assessment
POST   /api/applications/{id}/rescore
POST   /api/applications/{id}/retake
```

`issue-link` 仅允许 `REVIEW_PENDING` 且存在成功初筛；`regenerate-token` 仅允许 `EXPIRED` 且从未首次打开；`resume-assessment` 仅允许 `SUSPENDED`。HR 编辑简历文本是发链接前的受控更新接口，修改后重新初筛。`cancel` 记录 HR 决定和原因。所有 HR 接口需要后台口令登录会话。

`rescreen-current-job` 仅允许测评尚未开始时调用。它使用岗位当前 JD 更新档案快照，作废未打开的旧链接和已预抽题目，然后重新初筛；HR 审核新结果后重新生成链接。

`rescore` 仅对当前答案重新评分，暂时进入 `SCORING`，不允许重新作答。`retake` 仅允许已完成的测评：归档当前答案和问答、保留已有评分及事件，清空当前作答，作废旧链接，生成新链接并转到 `READY`。新链接首次打开后才开始新的 3 小时计时。HR 详情区分当前测评和历史测评。

### HR 登录

```text
POST   /api/hr/session      # 校验环境配置的后台口令并建立会话
DELETE /api/hr/session      # 登出
GET    /api/hr/session      # 查询当前会话
```

浏览器会话应采用安全 Cookie，并对变更请求做 CSRF 防护和登录尝试限速。候选人路由不需要 HR 会话，两种入口和 API 权限严格分开。

### Jobs

```text
GET    /api/jobs
POST   /api/jobs
GET    /api/jobs/{id}
PUT    /api/jobs/{id}
DELETE /api/jobs/{id}
```

已被应聘档案引用的岗位只允许停用/软删除，不能破坏历史记录。

### Questions

```text
GET    /api/questions
POST   /api/questions
GET    /api/questions/{id}
PUT    /api/questions/{id}
DELETE /api/questions/{id}
```

已被试卷引用的题目只允许停用/软删除；历史题目快照继续可读。

### Job Question Rules

```text
GET /api/jobs/{id}/question-rules
PUT /api/jobs/{id}/question-rules
```

### AI Config

```text
GET  /api/ai-config
PUT  /api/ai-config
POST /api/ai-config/test
```

### Candidate

全部使用 token，不暴露 application id：

```text
GET  /api/candidate/{token}

GET  /api/candidate/{token}/exam
PUT  /api/candidate/{token}/answers/{application_question_id}
POST /api/candidate/{token}/exam/submit

GET  /api/candidate/{token}/interview
POST /api/candidate/{token}/interview/answer
POST /api/candidate/{token}/suspend

GET  /api/candidate/{token}/result-status
```

首次有效 `GET /api/candidate/{token}` 按第 11 节激活测评。`suspend` 只在服务端记录了当前 AI 问题生成失败且已向候选人展示故障提示时允许，提交后进入 `SUSPENDED`，记录原阶段、故障 ID 和剩余时间。挂起期间所有答案写入被拒绝；HR 排除故障后点击恢复，后端保留已提交答案与轮次，将总截止时间重置为恢复时刻起 **3 小时**，记录旧/新截止时间，并回到原阶段。候选人可刷新继续；不能借此修改已提交的答案。

候选人接口绝对不能返回：
- 正确答案
- 参考答案
- scoring guide
- 内部 Prompt
- HR 内部评分

---

## 23. 发放测评链接的事务

发放链接时，抽题与快照必须在同一个数据库事务里：

```python
def issue_link(application_id):
    application = lock_review_pending_application(application_id)
    job = get_job(application.job_id)
    questions = select_questions(job)

    if questions_not_enough:
        raise BusinessError(...)

    create_question_snapshots(application, questions)
    save_new_token_hash_and_issue_event(application)
    application.status = READY

    commit()
    return application
```

任一步失败都回滚，避免发出没有完整试卷的链接。创建档案、保存上传文件和启动初筛是独立步骤：文件系统不参加数据库事务，失败时清理孤儿文件或保留明确的解析失败状态。AI 调用不放在持有数据库事务锁的过程中。

---

## 24. 状态校验

每个 Candidate API 必须检查当前状态。

例如 `submit_exam()` 只允许：

```text
EXAM_IN_PROGRESS
```

重复提交返回当前已持久化的状态/结果（或明确的 `409 Conflict`），绝不重复生成问答或评分：

```text
409 Conflict
```

不要重复创建 interview session 或重复触发评分。

---

## 25. AI 服务只保留三个能力

### resume_screening_service

```python
screen_resume(jd, resume_text)  # 返回结构化分数、评语与证据，供 HR 审核
```

### interview_service

```python
generate_question(
    round_no,
    jd,
    resume,
    exam,
    history,
)
```

### scoring_service

```python
score_application(
    jd,
    resume,
    exam,
    interview,
)
```

没有：
- Resume Agent
- Planner Agent
- Judge Agent
- Auditor Agent

---

## 26. 推荐后端目录

目录示意；实际还应增加 HR 登录 API、简历初筛服务与 Prompt，以及到期扫描任务。

```text
backend/
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── applications.py
│   │   ├── jobs.py
│   │   ├── questions.py
│   │   ├── ai_config.py
│   │   └── candidate.py
│   ├── models/
│   ├── schemas/
│   ├── services/
│   │   ├── application_service.py
│   │   ├── question_service.py
│   │   ├── resume_service.py
│   │   ├── interview_service.py
│   │   ├── scoring_service.py
│   │   └── llm_service.py
│   ├── graph/
│   │   └── interview_graph.py
│   ├── prompts/
│   │   ├── interview.py
│   │   └── scoring.py
│   └── db/
└── tests/
```

---

## 27. 推荐前端目录

目录示意；实际还应增加 HR 登录页和候选人挂起提示组件。

```text
frontend/src/
├── pages/
│   ├── applications/
│   │   ├── ApplicationList.tsx
│   │   ├── ApplicationCreate.tsx
│   │   └── ApplicationDetail.tsx
│   ├── jobs/
│   │   ├── JobList.tsx
│   │   └── JobEdit.tsx
│   ├── questions/
│   │   ├── QuestionList.tsx
│   │   └── QuestionEdit.tsx
│   ├── settings/
│   │   └── AISettings.tsx
│   └── candidate/
│       └── AssessmentPage.tsx
├── components/
├── api/
└── types/
```

---

## 28. Candidate 页面按后端状态渲染

```text
READY
→ 此时仅 HR 可见；候选人首次打开即进入 ExamView

EXAM_IN_PROGRESS
→ ExamView

INTERVIEW_IN_PROGRESS
→ InterviewView

PRACTICAL_IN_PROGRESS
→ PracticalView（下载专属题目包、提交 ZIP、查看分项反馈并确认最高分）

SUSPENDED
→ SuspendedView（提示联系 HR，等待恢复）

SCORING
→ ScoringView

COMPLETED
→ CompleteView

EXPIRED
→ ExpiredView（HR 可换发；旧链接无效）

CANCELLED
→ CancelledView
```

前端不要维护第二套独立状态机。

---

## 29. 候选人完成后

只显示：

```text
测评已经完成。
感谢你的参与。
```

第一版不要把内部评分直接展示给候选人。

---

## 30. 简历解析

MVP 只做：

```text
PDF -> text
DOCX -> text
```

目的只是给 AI 提供 `resume_text`。

不做：
- Resume JSON Parser
- Skill Graph
- Embedding
- RAG

如果解析失败：
- 保留原文件
- HR 详情页显示解析失败
- 允许 HR 手工粘贴/编辑简历文本
- 在获得可用简历文本并成功初筛前，禁止发放候选人链接

---

## 31. Langfuse

只作为可观测性：

记录：
- application_id
- prompt_version
- round_no
- model
- latency
- tokens
- error
- 问题/评分的关联 ID 与必要的脱敏摘要
- final_score

trace 分三类：

```text
resume_screening
interview
assessment_scoring
```

第一版不做复杂在线 Eval。

简历和候选人回答可能包含个人信息及针对模型的恶意指令。它们只能作为待评价数据，不得覆盖系统 Prompt；Langfuse 不记录完整简历、答案、候选人链接或 API Key，按应用 ID 关联内部数据。

---

## 32. 错误处理

### AI 生成问题失败
- Retry 1 次
- 仍失败则保留 `INTERVIEW_IN_PROGRESS`
- 前端显示“AI 问答暂时无法继续”及“终止并联系 HR”按钮
- 候选人点击后才迁移 `SUSPENDED`；后端冻结计时并拒绝继续答题
- HR 修复后从详情页恢复并重置 3 小时总计时；若未点击挂起，原截止时间继续运行

### AI 最终评分失败
- 状态保持 `SCORING`
- HR 详情页显示“AI评分失败”
- 提供 `[重新评分]`
- 候选人只看到“已提交，结果处理中”；无须再答题

不要失败后直接标记 COMPLETED。

---

## 33. 防重复请求

数据库约束：

```text
UNIQUE(interview_session_id, round_no)
UNIQUE(application_id, application_question_id)
candidate_token_issues.token_hash UNIQUE
每份应聘至多一条 invalidated_at IS NULL 的 Token 签发记录（部分唯一索引）
```

避免双击提交导致：
- 同一轮 AI 问答生成两次
- 同一道题生成两份答案
- 重复评分

唯一约束是最后一道防线。状态迁移需用行锁或条件更新，模型请求需要持久化中的任务标记与幂等键；崩溃后的重试先检查已保存的问题/结果。不能靠前端禁用按钮保证唯一调用。

---

## 34. 第一版防作弊

只做：
- 服务端计时
- 随机抽题
- 提交后不可修改
- 唯一 Token + 过期时间
- HR 登录会话

不做：
- 摄像头监考
- 切屏检测
- 人脸识别
- IP 识别
- 浏览器锁定

---

## 35. MVP 验收流程

必须完整跑通：

```text
1. HR 创建“AI应用工程师”岗位
2. 填 JD
3. 创建 20 道题
4. 配置岗位抽 5 道题
5. HR 新建候选人张三并上传简历
6. AI 完成简历初筛，评分和评语入库
7. HR 审核并点击“生成测评链接”，系统抽 5 题、冻结快照并签发 24 小时链接
8. 张三首次打开链接，原子记录首次打开时间
9. 服务端设置 3 小时总截止时间
10. status -> EXAM_IN_PROGRESS
11. 前端按服务端时间同步倒计时
12. 张三回答 5 道题
13. 提交
14. status -> INTERVIEW_IN_PROGRESS
15. AI Round 1
16. 张三回答
17. AI Round 2
18. 张三回答
19. AI Round 3
20. 张三回答
21. status -> PRACTICAL_IN_PROGRESS
22. 下载候选人专属实操包，使用 AI 编程工具完成并上传 ZIP
23. 后端隐藏验收，候选人根据分项反馈迭代并确认最高分
24. status -> SCORING
25. AI 返回合法评分 JSON
26. 保存 assessment_results（含实操分）
27. status -> COMPLETED
28. HR 应聘列表显示评分
29. HR 进入详情
30. 完整看到 JD、简历、笔试、三轮问答、实操提交与 AI 评分
```

还必须验收：24 小时未打开后过期并由 HR 换发，旧链接失效；刷新/换浏览器不能延长时限；无人再访问时服务器在截止时间自动结算；超时前后并发保存答案的边界；AI 问题生成失败后候选人挂起、联系 HR、HR 恢复并重置 3 小时且原答案不丢；评分失败后 HR 重试；重复点击不产生重复问题、结果或链接；未登录者无法读取 HR 数据。

主流程与上述异常路径跑顺，第一版即成功。

---

## 36. 开发顺序

### Phase 1：数据与 HR 后台骨架
先不接真实 AI，但须为初筛和登录留出明确接口：

```text
数据库
岗位管理
题库管理
岗位抽题规则
应聘列表
应聘详情
新建应聘
状态模型
JD / Question Snapshot
HR 登录和受保护的 API
简历解析、初筛记录与待审核状态（固定结果适配器只用于本地开发）
不可变 AI 配置版本的数据结构（初筛与后续评分共用）
HR 审核后发链接、24 小时过期与换发事件
```

Phase 1 不得用固定结果适配器宣称已经完成真实初筛。发放链接的正式闭环必须先接通 Phase 3 的真实初筛服务。

### Phase 2：候选人考试

```text
candidate token 哈希与签发事件
首次打开激活
服务端计时
3 小时总截止时间与定时扫描
答题保存
提交
状态迁移
```

### Phase 3：AI 简历初筛与三轮问答

```text
DeepSeek
Prompt
简历初筛评分、评语及 HR 推进决定
Round 1
Round 2
Round 3
AI 故障挂起、HR 修复后恢复及重置计时
LangGraph（可选）
```

### Phase 4：AI 最终评分

```text
Structured Output
Pydantic
评分结果落库
HR详情展示
```

### Phase 5：AI 配置 + Langfuse

```text
AI Settings
Langfuse trace
错误重试
重新评分
配置管理界面与评分历史展示（底层版本记录已在前期建立）
```

---

## 37. Claude Code 开发约束

```text
1. 不引入多 Agent。
2. 不引入 Wren / Waza / Ragas / LlamaIndex。
3. 不构建复杂 RAG。
4. 不把简单 CRUD 写成 LangGraph Node。
5. LangGraph 最多用于三轮问答。
6. 抽题必须使用数据库规则，不使用 LLM。
7. 选择题评分必须使用普通代码。
8. 最终评分只有一次 LLM 调用。
9. 已创建应聘必须使用 JD / Question Snapshot。
10. 状态只能由后端迁移。
11. 考试时间以后端时间为准。
12. 优先完成完整业务闭环，而不是添加技术组件。
13. 每完成一个 Phase 都先确保测试通过，再进入下一阶段。
14. 候选人首次打开即激活 3 小时总计时；只在 24 小时内从未打开时过期。
15. AI 故障挂起必须由候选人点击，恢复和重置计时只能由 HR 操作并留痕。
16. 简历初筛先存档，经 HR 决定后才发放候选人链接；最终评分以笔试、问答、简历的顺序加权。
17. HR 后台必须有口令登录，口令与 API Key 不得写入仓库或日志。
```

---

## 38. 第一条给 Claude Code 的任务

```text
请先阅读本设计文档。

当前目标是重构为简化版 AI 招聘测评 MVP v2.1。

先不要写 AI，不要实现 LangGraph，不要添加新框架。

第一步请：
1. 检查当前项目目录、依赖、数据库模型和页面。
2. 对照文档，指出当前代码哪些可以保留、哪些应该删除或暂时停用。
3. 给出 Phase 1 的具体重构计划。
4. Phase 1 只包含：
   - Job CRUD
   - Question CRUD
   - Job Question Rule
   - Application 创建/查询/取消（不是可任意修改、删除的 CRUD）
   - Application List
   - Application Detail
   - Application Create
   - Application Status model（含初筛待审核、过期和挂起）
   - JD / Question Snapshot
   - HR 登录与权限边界
   - 简历初筛结果数据结构、发链接与换发事件
5. 给出需要新增、修改、删除的文件列表。
6. 先完成分析和计划，不要立刻大规模改代码。

特别注意：
不要恢复旧版 Multi-Agent 架构。
不要为了复用旧代码强行保留复杂设计。
如果旧架构与当前文档冲突，以当前文档为准。
不要把演示后台口令、API Key 或候选人 Token 明文写进代码、文档或测试夹具。
```

---

## 39. 最终产品结构

```text
HR 后台
│
├── 应聘管理
│   ├── 应聘列表
│   ├── 新建应聘
│   └── 应聘详情（简历初筛 → HR 决定 → 发/换链接 → 测评与评价）
│
├── 岗位管理
│   └── JD + 抽题规则
│
├── 题库管理
│
└── AI 配置
      │
      ↓
生成应聘链接
      │
      ↓
候选人
      │
      ├── 计时笔试
      ├── AI 问答 1
      ├── AI 问答 2
      └── AI 问答 3
             │
             ↓
          AI 综合评分
             │
             ↓
          应聘详情
```

这就是 MVP 的全部核心。
