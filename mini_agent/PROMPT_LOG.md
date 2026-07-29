# AI Prompt 与问题解决记录（PROMPT_LOG）

本文件记录在用 AI 辅助开发本 Agent 过程中：给 AI 的关键 prompt、做出的设计决策、踩过的坑与修法、以及 AI 哪些地方说错或需要纠正。诚实记录，便于复盘与答辩。

---

## 一、开发流程与给 AI 的关键 Prompt

整体流程：**先规划（Plan Mode）→ 确认技术选型 → 让 AI 出架构方案 → 人工审阅修正 → 分模块实现 → 写测试 → 跑测试验证**。

### Prompt 1：澄清技术选型（AskUserQuestion）

> "这是一道 Vibe coding 笔试题：从零实现最小可用 Agent。我是 agent 开发小白。请先制定实现计划，必须覆盖每一个具体要求……用哪种语言 / 哪个真实 LLM API / 终端还是网页 / 怎么持久化？"

**结果**：确认 Python + 智谱 GLM + Gradio 网页 + JSON 持久化。

### Prompt 2：让 AI 设计详细架构（Plan 子代理）

给 Plan 代理的 prompt 核心内容：

> "规划一个全新 Python 项目：从零实现最小可用 Agent，不用 langgraph/langchain/openhands。已确认：Python + 智谱 GLM（openai SDK 兼容端点）+ Gradio + JSON 持久化。
> 要求覆盖：4 步循环、≥3 工具（calculator/search/weather/todo）、工具注册（name/description/schema）、LLM 输出解析（思考/工具调用/最终答案）、两窗口独立 session、context 管理（最大轮次/记忆/追问/压缩）、异常处理、trace、测试用例。
> 我已初步设计（ReAct+手写JSON解析、LLM 滚动摘要压缩、todo 会话级状态、双重上限）。请验证并细化、指出风险与漏掉的需求，但不要写代码文件，只返回方案文本。"

**产出**：AI 验证了我的架构，并补充了几个我漏掉的可靠性细节（见下文"AI 帮忙发现的问题"）。

### Prompt 3：分模块实现

实现阶段按依赖顺序逐模块让 AI 生成代码，每个模块写完立即配测试：
config/llm_client → tools → parser/prompt → context/session/trace → runtime → 测试 → app → 文档。

---

## 二、关键设计决策（与 AI 讨论后拍板）

| 决策 | 选择 | 理由 |
|---|---|---|
| 工具调用方式 | **ReAct + 手写 JSON 解析**，不用原生 function-calling | 题目明确要求"实现 LLM 输出的解析逻辑"，用 function-calling 就拿不到这分 |
| 输出格式 | 单个 JSON 对象 `{thought, action, action_input, final_answer}` | 结构清晰、易解析、显式暴露思考过程 |
| 解析健壮性 | 5 级降级链 + 永不抛异常 | LLM 输出不稳定，解析必须兜底，否则循环极易崩 |
| Context 压缩 | LLM 滚动摘要旧消息，保留最近 8 条原文 | 满足"基础压缩"；摘要累加，保留语义 |
| Observation 注入 | 以 `user` 角色 `Observation(tool): ...` 注入 | 这是"带工具追问"能记住上轮工具结果的关键 |
| todo 状态 | 存 `session.tool_state`，不存进消息 | 摘要损失永不损坏待办；两窗口天然独立 |
| 防死循环 | 最大迭代上限(8) + 重复调用检测 双保险 | 单一保险不够：模型可能反复调同一工具 |
| 持久化 | 每会话一个 JSON，原子写（.tmp + os.replace）+ 锁 | 避免半写文件、并发写冲突 |
| 测试 | FakeLLM 脚本化返回，真实 API 测试单独 skip | 全套循环测试零网络零花费、确定可复现 |

---

## 三、踩过的坑与修法

### 坑 1：calculator 的代码注入风险

- **问题**：若用 `eval()` 算数学表达式，用户/模型可传 `__import__('os').system(...)` 之类，存在安全风险。
- **修法**：改用 `ast.parse(mode="eval")` + 白名单运算符（`_BIN_OPS` / `_UNARY_OPS`）递归求值，遇到非白名单节点（如 `Call`、`Name`）直接拒绝。测试里专门用 `__import__('os')` 和 `open('x')` 验证会被拒绝。

### 坑 2：LLM 不总是输出干净 JSON

- **问题**：即便开了 JSON 模式，模型偶尔会带 ```json 围栏、前后多余文字、单引号、尾逗号。
- **修法**：解析器 5 级降级链（严格→围栏→花括号子串→廉价修复→纯文本兜底）。测试 `test_parser.py` 逐一覆盖这些脏输入。

### 坑 3：循环可能死循环

- **问题**：模型可能反复用相同参数调用同一工具，永远不给 `final_answer`。
- **修法**：① `MAX_INNER_ITERATIONS` 上限兜底；② 用 `seen_calls` 集合检测同一轮内的 `(action, action_input)` 重复，第二次直接给警告 observation。测试 `test_repeated_call_detection` 和 `test_max_iterations_cap` 覆盖。

### 坑 4：Gradio 并发 + 持久化写冲突

- **问题**：Gradio 可多线程服务请求，两个窗口同时写不同文件没问题，但同一会话文件并发写会损坏。
- **修法**：`Session` 持有 `threading.Lock`，`SessionManager.save()` 在锁内做原子写。

### 坑 5：坏会话文件让程序起不来

- **问题**：若 `sessions/*.json` 被人工改坏（非法 JSON），`load()` 直接抛异常会让整个程序崩。
- **修法**：`load()` 读文件包 try/except，损坏则回退新建空会话。测试 `test_corrupt_file_falls_back_to_fresh` 覆盖。

### 坑 6：GLM 没有易用的本地 tokenizer

- **问题**：要估 token 做压缩阈值，但 GLM 没有像 tiktoken 那样的本地分词器。
- **修法**：用"字符数/4"粗估 token。对"基础压缩"足够，且不引入额外依赖。README 已说明这是估算。

### 坑 7：终端显示中文乱码（仅显示，非数据问题）

- **现象**：在 Windows Git Bash 里跑带中文的脚本，print 的中文显示成乱码。
- **真相**：仅是控制台默认 GBK 编码的显示问题；落盘的 JSON 文件是 UTF-8（`ensure_ascii=False`）、Gradio 网页也正常，数据本身无问题。

---

## 四、AI 帮忙发现/纠正的问题（值得记录的功劳）

让 Plan 代理审架构时，它补充了几个我最初没写明的细节，采纳后写进了代码：

1. **重复调用检测**：我最初只有"最大迭代上限"一道保险，AI 提议再加"相同参数重复调用检测"，更早打断死循环。——采纳。
2. **原子文件写**：我最初写 JSON 是直接 `json.dump` 覆盖，AI 提议 `.tmp` + `os.replace` 原子写 + 锁，避免半写/并发损坏。——采纳。
3. **JSON 模式 + temperature 降低**：AI 提议开启智谱 `response_format={"type":"json_object"}` 并把温度降到 0.2，显著提升解析可靠性。——采纳。
4. **`parse` 永不抛异常的契约**：AI 强调解析器的契约应是"永远返回 ParsedOutput"，最差把原文当 final_answer，这样循环天然健壮。——采纳，成为解析器核心设计。
5. **"写周报"无对应工具的解读**：题目 window2 要"写周报"但工具清单里没有周报工具。AI 指出这一歧义，建议解读为"Agent 用 todo 读出待办再组织成周报文字"的组合任务，而非凭空造工具。——采纳，README 已写明。

---

## 五、AI 说错 / 需要人工纠正的地方（诚实记录）

1. **Plan 代理的文件路径自相矛盾**：它在"关键文件"里一度写成 `mini_agent\parser.py`（漏了 `agent\` 层），与它自己的目录结构不一致。实际实现时统一成 `mini_agent/agent/parser.py`，未受影响。
2. **Plan 代理建议的 `ast.Num`**：示例代码用了已废弃的 `ast.Num`。Python 3.12+ 已弱化，3.14 下更稳妥的是只用 `ast.Constant` 并校验是数字。实现时只保留 `ast.Constant` 分支，未用 `ast.Num`。
3. **Gradio `gr.State` vs 模块全局**：AI 给了两种 UI 状态方案并推荐"更正确"的 `gr.State`。但对本 demo（固定 userA 两个窗口），模块全局更简单可靠，最终采用模块全局方案，未盲目采纳"更正确"的那个。
4. **测试里一度出现的 `lambda` 黑科技**：AI 风格的工具注入写法（`lambda: __import__(...)`）既丑又易错，实现时改成直接传工具类列表。

> 经验：AI 给的架构方向大多靠谱，但**具体代码细节（废弃 API、路径、过度设计）必须人工核对**，不能照抄。

---

## 六、最终验证结果

```bash
$ python -m pytest
..................ss................................    [100%]
50 passed, 2 skipped in 0.13s
```

- 50 个单元/循环测试全绿（FakeLLM，零网络）。
- 2 个真实 API 测试在无 key 时自动 skip；配置 `ZHIPU_API_KEY` 后可跑通"17×23=391"与"北京天气"。
- 额外用脚本跑了一遍"两窗口记不同待办 + 重启后续聊"的端到端场景，确认会话独立性与持久化正确。

---

## 七、代码质量审查与修复（第二轮）

用 quality-engineer 做了一次只读多维度体检（注释/安全/类型/错误处理/死代码/并发），评分 8.5/10，随后按"方案 B"全部修复，并补了回归测试。

**修复清单（均已加测试验证）：**

| 编号 | 问题 | 修法 |
|---|---|---|
| M1 | calculator 幂运算无上限，`9**9**9` 可挂死进程（实测 15s+ 卡死） | `_eval_node` 的 Pow 分支加指数上限(1000)、结果位数上限(10000)、嵌套深度与表达式长度上限；实测现 0.000s 拦下 |
| M4 | todo complete/delete 的 id 用 `==` 比，LLM 传字符串 `"1"` 时静默失效 | 取 id 后 `int()` 强转，失败给明确错误 |
| M3 | Gradio 并发下同一窗口的内存状态无锁保护 | `Session._lock` 改 `RLock`，runtime 把整个 turn 包进 `with session._lock:`（RLock 保证内部 `save()` 可重入） |
| L4 | 两个 Trace 实例各持独立锁却写同一 `trace.jsonl`，并发可能损坏 | Trace 改类级共享锁 `_FILE_LOCK` |
| M2 | session 文件名直接拼 user_id/window_id，潜在路径穿越 | `load` 前校验不含 `/ \ ..` 及非空，违则 raise |
| L1 | parser 廉价修复 `replace("'",'"')` 会破坏含撇号的字符串 | 改为先 `ast.literal_eval`（保留撇号），失败再退到廉价替换（救 null/true/false） |
| L5 | 压缩硬上限只算 entries，不算越压越长的 summary | `_est_tokens` 把 summary 长度也计入 |
| L6 | `Tool.schema: dict = {}` 可变类级默认值 | 改 `ClassVar[dict]` 并注释提醒整体覆盖 |
| L3 | 异常 `repr` 回显到聊天界面 | 给用户固定文案，`repr(e)` 只进 trace |
| S1 | 死代码：`config.SESSIONS_DIR/LOGS_DIR` 别名、测试里未用的 `import config` | 删除 |
| S2 | `_now()` 在 3 个文件重复 | 抽到 `utils.now_utc_iso` 复用 |
| S3 | parser action 归一化写得绕 | 简化为"非字符串 action 一律 None" |
| S4 | `_truncate` 注解 `str` 与实现（含 None 判断）不符 | 改 `Optional[str]` |
| 注释 | `llm_client` 重试注释声称"非瞬时错误直接换配置"，与代码矛盾 | 注释改为如实描述"所有错误统一退避重试，配置用尽后切换" |
| L2 | 三处 `except: pass` 静默吞错 | `.env`/坏会话/trace 写失败时打 `stderr` 警告，留排障线索 |

**回归**：测试从 44 增至 50（新增 calculator DoS、todo 字符串 id、parser 撇号、session 非法 id、context summary 计 token 等），全绿；额外实测 `9**9**9` 由"卡死"变为"0.000s 拦截"。

> 这一轮的价值：第一轮 AI 主动指出了"重复调用检测""原子写"等设计补强；第二轮审查则抓出了**两个 AI 自己实现时没暴露的真 bug**（DoS、id 类型静默失效）——说明"AI 写完 + AI 审查 + 实测验证"比单轮更可靠。

---

## 八、真实 API 接入实测（第三轮）

接入智谱 **GLM Coding Plan**（OpenAI 协议端点 `https://open.bigmodel.cn/api/coding/paas/v4`）。实测中发现并解决了三个真问题，都是"不上真 API 就发现不了"的：

1. **端点不同**：Coding Plan 用的是 `/api/coding/paas/v4`（多一段 `/coding/`），不是常规的 `/api/paas/v4/`。为此把 `BASE_URL` 和 `MODEL` 也改成可用环境变量 `ZHIPU_BASE_URL` / `ZHIPU_MODEL` 覆盖（原先只有 API Key 能从 env 读）。写进 `.env`（已 gitignore）。

2. **弱模型不守 JSON 约定（关键）**：`glm-4-flash` 指令跟随差——
   - 给最终答案时常输出 `Thought: ...\nFinal Answer: 391。` 纯文本而非 JSON，导致 "Final Answer:" 前缀漏给用户；
   - 偶尔只吐 `{"command":"add","text":"买牛奶"}` 这样的 action_input 片段，被解析器误当成直接回答、工具根本没执行（todos 没存上）。
   处理：① 默认模型改 **`glm-4.5`**（同套餐可用、指令跟随稳定，实测两轮都输出干净 JSON）；② 解析器第 5 级降级增加 `Final Answer:` / `最终答案：` 文本抽取，即使模型偶尔退化为纯文本也能拿到干净答案；③ system prompt 加一条"最重要"规则强调任何情况都只输出 JSON。glm-4.5 实测：天气/计算器/todo 全部正确走工具并返回干净答案。

3. **限流导致空内容**：Coding Plan 对快速连续调用会返回**空 content**（HTTP 200 但内容为空）。`LLMClient.chat` 现在把"空内容"也视为可重试的瞬时错误、走退避重试，避免 Agent 返回空答案。注意：这会让被限流的单次调用变慢（重试退避），但用户在网页里手动一条条发消息（请求有间隔）不会触发；批量脚本才会。

**配置**（`.env`，已 gitignore，不会进仓库）：
```
ZHIPU_API_KEY=...
ZHIPU_BASE_URL=https://open.bigmodel.cn/api/coding/paas/v4
ZHIPU_MODEL=glm-4.5
```

**最终验证**：`pytest` 共 **54 passed**（含 2 个真实 API 冒烟：17×23=391 走 calculator、北京天气走 weather）；单用脚本跑 glm-4.5 的天气/计算器/todo 均正确。两窗口独立性由 FakeLLM 测试 + 真实 API 单测共同保证。

> 经验：解析器的"多级降级 + 永不抛异常"设计在接真 API 时价值最大——模型不可控，解析器必须兜住各种脏输出。以及"先用弱模型跑通逻辑、再换强模型做演示"是省额度的好习惯。

---

## 九、交付前的调试与加固（第四轮，真实环境踩坑）

这一轮是在真实 Windows 环境 + 用户实际操作中暴露的问题，大多"在沙箱里跑测试永远发现不了"。按时间顺序记录：

### 1. 端口被我自己占着（我的失误）
**现象**：用户启动网页版，浏览器"无法建立连接/拒绝连接"。
**真相**：我每次"验证 app 能不能跑"，都在用户这台机器上后台起了 Gradio，**一直占着 7860 端口**。用户再启动就端口冲突，要么起不来、要么起在别的端口而浏览器还连 7860。
**修法与教训**：杀掉所有占 7860 的进程；**以后验证一律不开常驻服务**——改用单元测试 / FakeLLM / 单次直连 API 这些不占端口的方式。把 7860 留给用户。

### 2. Windows 中文编码（关键真 bug）
**现象**：终端/网页里一输入中文就报 `UnicodeEncodeError(... 'surrogates not allowed')`，连锁导致大模型调用失败、表现成"连接失败"。
**真相**：Windows 控制台默认 **GBK** 编码，中文被读成无效"代理字符"（`\udcXX`），发往大模型做 UTF-8 编码时炸掉。
**修法**：
- 加 `run_cli.bat` / `run_web.bat`，里面 `chcp 65001`（控制台切 UTF-8）+ `set PYTHONUTF8=1`（Python 切 UTF-8 模式），双击即可，根治中文 I/O。
- `cli.py` 里强制 `sys.stdout/stderr.reconfigure(utf-8)`，并对输入做 `encode("utf-8","replace").decode()` 清洗，兜底防崩。

### 3. openai SDK 的隐藏重试
**现象**：单次大模型调用莫名要十几秒。
**真相**：`openai` 库默认对 429 等错误**自己指数退避重试 2 次**，把一次调用偷偷拖到几十秒，雪上加霜。
**修法**：`OpenAI(..., max_retries=0)` 关掉 SDK 自带重试，改由 `LLMClient.chat` 用**短而可控**的策略（1 次重试、固定 1 秒）处理——限流时几秒内快速失败返回"请重试"，而不是死等把连接拖断。

### 4. Gradio 6 改了聊天数据格式
**现象**：网页一交互就报 "Data incompatible with messages format" → 前端显示成 error/连接失败。
**真相**：Gradio 6 **删掉了旧的 tuples 格式** `[[用户,回答]]`，只接受 messages 格式 `[{"role","content"}]`。
**修法**：加 `_to_messages()` 转换函数，所有传给聊天框的数据都转成 messages 格式（`app.py`、`app_demo.py` 都改）。并用 `gradio_client` 真连服务验证了 /new、/send 端到端通。

### 5. 智谱 Coding Plan 被限流 → 切 DeepSeek
**现象**：智谱 Coding Plan 单次调用 8–29 秒（被限流），一条消息（多次调用）累计超 Gradio 连接超时 → "Connection to the server was lost"。
**修法**：换成 **DeepSeek**（`deepseek-chat`），实测每次 1–3 秒、不限流、中文好、指令跟随稳定。同时把配置改成**厂商中立**：优先读 `LLM_API_KEY`/`LLM_BASE_URL`/`LLM_MODEL`，兼容旧的 `ZHIPU_*`/`GLM_*`。`.env`、`.env.example`、README、集成测试的 skip 条件、错误提示全部同步。

### 6. 网页版启动加固
为避免"报错一闪而过用户看不到"：`app.py` 加了**自动找空闲端口**（`_find_free_port`，避免冲突）、**醒目打印地址**、启动失败时 `traceback.print_exc()` + `input()` 停住，让用户能看到完整错误。

### 7. 增加终端版 `cli.py`
作为**不依赖浏览器/端口/防火墙**的可靠备选（题目本就接受"终端操作录屏"）。和网页版同一套引擎，支持 `/new` `/switch` `/list` 会话切换，每轮打印工具调用。实测中文/算数/天气/待办/追问全对。

**本轮教训**：
- **真实环境 ≠ 沙箱**：Windows 编码、端口占用、SDK 隐藏行为、限流，这些只在真机上才暴露。尽早让真实环境介入。
- **失败要可见**：启动报错一定要"停住 + 打印完整 traceback"，否则用户只看到"连不上"，无法定位。
- **给别人用的东西，要给"双击就能跑"的入口**（`.bat` 把环境变量、编码、端口都处理好），而不是假设别人会手动 `python -m ...`。

**最终状态**：54 个测试全绿（52 单测 + 2 个 DeepSeek 真实冒烟）；双击 `run_cli.bat` 即可终端对话；`run_web.bat` 起网页版。README 已重写为通俗易懂版（运行方式 / 系统设计 / 记忆召回时机与放置）。


