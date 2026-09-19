# AI 招聘测评 MVP

根据 [业务设计](ai_recruitment_assessment_mvp_v2.md) 实现的本地演示版。HR 上传简历后先获得 AI 初筛；HR 决定是否发放 24 小时内首次打开的候选人链接；首次打开后服务端计 3 小时，完成笔试、三轮问答、候选人专属 AI 编程实操和辅助评价。

## 运行环境

- Python 3.12、Node.js 20+、npm
- 本地演示：SQLite；部署时可用 PostgreSQL（`DATABASE_URL=postgresql+psycopg://...`）
- DeepSeek API Key 通过环境变量提供。没有 Key 时可以维护岗位、题库和档案，简历初筛会进入失败状态，不能发放链接。
- HR 后台口令通过 `HR_ADMIN_PASSWORD` 提供。项目文件、样例配置和日志均不包含明文口令。

## Windows 本地启动

在 `D:\ai_hr` 使用两个 PowerShell 窗口。由于本机 C 盘临时目录空间不足，下面把临时目录和依赖缓存设到工作区；这些目录已被 Git 忽略。

后端窗口：

```powershell
Set-Location D:\ai_hr
New-Item -ItemType Directory -Force -Path .tmp | Out-Null
$env:TEMP = 'D:\ai_hr\.tmp'
$env:TMP = 'D:\ai_hr\.tmp'
$env:UV_CACHE_DIR = 'D:\ai_hr\.uv-cache'
uv venv .venv_uv --python 3.12
uv pip install --python .venv_uv\Scripts\python.exe -r backend\requirements-dev.txt

# 口令以隐藏输入进入当前进程环境，不保存在文件或命令历史中。
$securePassword = Read-Host 'HR 后台口令' -AsSecureString
$passwordPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
try { $env:HR_ADMIN_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPtr) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPtr) }

# 如需真实 AI，请在进程环境中设置 DEEPSEEK_API_KEY。
$env:DATABASE_URL = 'sqlite:///./local.db'
Set-Location D:\ai_hr\backend
..\.venv_uv\Scripts\python.exe -m alembic upgrade head
..\.venv_uv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

前端窗口：

```powershell
Set-Location D:\ai_hr\frontend
$env:TEMP = 'D:\ai_hr\.tmp'
$env:TMP = 'D:\ai_hr\.tmp'
$env:npm_config_cache = 'D:\ai_hr\.npm-cache'
npm install
npm run dev
```

打开 [HR 后台](http://127.0.0.1:5173/applications)。候选人链接由 HR 审核初筛后在详情页生成，只显示一次；丢失时等待链接过期再换发。`127.0.0.1` 下使用 HTTP 演示，部署到网络时应启用 HTTPS 和 `COOKIE_SECURE=1`。

### 导入示例题库

仓库内提供 205 道经过格式校验的单选题，分为 AI 和全栈两组。数据库迁移完成后执行：

```powershell
Set-Location D:\ai_hr\backend
..\.venv_uv\Scripts\python.exe import_question_bank.py '..\data\AI应用开发工程师_选择题库_AI与全栈分组.json'
```

导入命令可重复执行；同名且内容一致的题目会跳过。已有名为 `AI Agent 工程师` 和 `全栈开发工程师` 的岗位时，脚本会把对应的五题规则更新为难度 1–5。

## 验证

```powershell
Set-Location D:\ai_hr
$env:TEMP = 'D:\ai_hr\.tmp'
$env:TMP = 'D:\ai_hr\.tmp'
.venv_uv\Scripts\python.exe -m pytest backend\tests -q

Set-Location D:\ai_hr\frontend
npm run build
```

数据库迁移从 `backend` 目录执行 `..\.venv_uv\Scripts\python.exe -m alembic upgrade head`。不要对已有数据使用 `DB_AUTO_CREATE=1`；该开关仅供隔离测试建库。生产环境需要单独的定时任务或单实例后台扫描器；当前进程内扫描器适合单实例演示。

## 配置与数据边界

- `DEEPSEEK_API_KEY`、`HR_ADMIN_PASSWORD`、`HR_SESSION_SECRET` 从环境注入，不进入数据库或 Git。
- Langfuse 默认关闭；在明确同意连接该账号后，设置 `LANGFUSE_SEND_TRACES=1` 及相应的 `LANGFUSE_PUBLIC_KEY`、`LANGFUSE_SECRET_KEY`、`LANGFUSE_BASE_URL`。仅发送应用 ID、轮次、Prompt 版本、模型、长度、耗时、token 用量与成功/失败标记，不发送简历、答案或候选人 Token。
- 原始简历保存在本地 `uploads/`，SQLite 数据在 `backend/local.db`，两者均已被 Git 忽略；请按演示环境的需要备份和清理。
- AI 编程实操包只依赖 Python 3.11 标准库。候选人上传源码、结果 JSON 和 AI 协作记录；后端只解析产物并执行隐藏数据验收，不运行候选人代码。实操提交包保存在本地 `uploads/practical/`。
- 候选人路径包含 Bearer Token，因此后端用 `--no-access-log` 启动；反向代理也应屏蔽该路径的完整 URL 日志。
