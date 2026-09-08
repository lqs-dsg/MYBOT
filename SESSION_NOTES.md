---
##   Codex角色：老师，学生动手写，Codex引导理解并检查
---

# lqs/mybot 复现进度

> 复现目标：HKUDS/nanobot（v0.2.2）→ 自己的 mybot
> 复现指导：nanobot复现指导.md
> 角色：**Codex = 老师（讲解 + 引导 + 检查），lqs = 学生（亲自动手写）**

## 阶段 1：最小骨架 ✅

| # | 模块 | 状态 | 文件 | 备注 |
|---|------|------|------|------|
| 1 | 项目配置 | ✅ | pyproject.toml | hatchling build |
| 2 | config_base | ✅ | mybot/config_base.py | Pydantic Base：alias_generator=to_camel + populate_by_name=True |
| 3 | 配置 schema | ✅ | mybot/config/schema.py | ProviderConfig / ProvidersConfig / AgentDefaults / AgentsConfig / Config |
| 4 | 配置 loader | ✅ (基础) | mybot/config/loader.py | JSON读取 + VAR替换 + model_validate |
| 5 | 配置 paths | ✅ | mybot/config/paths.py | ensure_dir + get_workspace_path + get_config_path(懒加载打破循环导入) |
| 6 | loader 完善 | ✅ | mybot/config/loader.py | _current_config_path + DEFAULT_CONFIG_PATH + set_config_path/get_config_path + load_config + save_config(model_dump by_alias=True) |
| 7 | 消息总线 | ✅ | mybot/bus/ | events.py ✅ / queue.py ✅ / __init__.py ✅ |
| 8 | Provider 基础 | ✅ | mybot/providers/ | base.py ✅ / registry.py ✅ / openai_compat.py ✅ |

## bus 模块进度（2026-07-29）

- **events.py ✅**：InboundMessage（8字段 + session_key property）+ OutboundMessage（6字段），纯 @dataclass
- **queue.py ✅**：MessageBus 类，两个 asyncio.Queue（inbound/outbound），publish/consume + qsize 属性
- **__init__.py ✅**：重导出 MessageBus、InboundMessage、OutboundMessage

## Provider 模块总览（2026-07-30）

Provider 模块是 config 和实际模型调用之间的“翻译层”：
- **config = 账本**：读 JSON → 结构化对象（api_key / api_base / model）
- **provider = 执行者**：从 config 拿参数 → 真正发网络请求 → 返回 LLMResponse
- 两者通过**依赖注入**衔接，provider 不 import config，只接收参数

三个文件的分工：
- **base.py**：定义协议（LLMResponse 数据结构 + LLMProvider 抽象类）
- **registry.py**：通讯录（dict[str, LLMProvider]，按名字查找 provider 实例）
- **openai_compat.py**：OpenAI 兼容 API 的具体实现（懒加载复用 AsyncOpenAI client，支持 tools / tool_choice，并转成 LLMResponse）

## Step 8a 完成（2026-07-30）

- **base.py ✅**：
  - GenerationSettings：dataclass（temperature=0.7 / max_tokens=4096）
  - LLMResponse：frozen dataclass（content: str|None / prompt_tokens / completion_tokens / finish_reason / tool_calls）
  - LLMProvider：ABC（__init__ 存 api_key/api_base/generation + 抽象方法 chat(messages, model, tools, tool_choice) / get_default_model）

## Step 8b 完成（2026-08-02）

- **registry.py ✅**：
  - ProviderRegistry：内部 dict[str, LLMProvider]
  - register(name, provider)：名字统一转小写
  - get(name)：找不到抛 KeyError
  - list_providers()：返回注册名字列表
- 验证：用临时 Dummy provider 跑了导入 + 注册 + 查找 + 缺失报错，全部通过

## Step 8c 完成（2026-08-02）

- **openai_compat.py ✅**：
  - OpenAICompatProvider：继承 LLMProvider，default_model 缺省 gpt-4o
  - _ensure_client()：asyncio.Lock 懒加载单例，避免每次对话新建 AsyncOpenAI
  - chat()：支持 model / tools / tool_choice，temperature / max_tokens 来自 generation
  - _convert_response()：映射 content / prompt_tokens / completion_tokens / finish_reason / tool_calls
- **base.py 同步 ✅**：LLMProvider.chat 增加 tools / tool_choice 参数
- 验证：mock AsyncOpenAI 连续调用两次，client 只创建 1 次；tool_calls、token 映射全部通过

## config 模块数据流（2026-07-23）

用户 JSON（camelCase：apiKey）
    → loader.load_config() → json.load + VAR替换 + model_validate
    → Config 对象（Python snake_case：api_key）

paths.get_workspace_path() → runtime 找 session/skills 目录
paths.get_config_path()    → 懒加载转发到 loader.get_config_path()
loader.get_config_path()   → 持有状态 _current_config_path
loader.set_config_path()   → CLI --config 写入状态
loader.save_config()       → model_dump(by_alias=True) → JSON（camelCase）

## paths.py 设计要点

- ensure_dir：mkdir(parents=True, exist_ok=True)，返回 Path 支持链式调用
- get_workspace_path(workspace=None)：有传参就用，否则默认 ~/.mybot/workspace/
- get_config_path()：懒加载 from mybot.config.loader import ...，打破循环导入
  如果顶层 import，loader 里 import paths 时会炸——loader 还没加载完
  放到函数体内，调用时两个模块都已就绪

## schema.py 设计要点

- ProviderConfig：api_key / api_base / model，可缺省 → None / "
- ProvidersConfig：openai: ProviderConfig，Field(default_factory=...) 保证空 JSON 也有值
- AgentDefaults：provider=auto / model="，runner 启动时读取决定用哪个模型
- AgentsConfig：defaults: AgentDefaults，容器模式
- Field(default_factory=...) vs 直接 =：BaseModel 类型字段必须工厂，基本类型直接默认值

## model_validate 缺省补全逻辑

Pydantic 逐字段递归：
1. JSON 里有 → 类型校验 + 递归
2. JSON 里没有 → 找 Field(default_factory=...) → 调用工厂新建
3. 没有 default_factory → 用类属性的 Python 默认值
4. 最终 Config 对象必然完整，不管用户写了 0% 还是 90%

## 下次继续（2026-08-02 结束点）

- **阶段 2：Agent 核心**
- Step 9：Tool 基础
  - agent/tools/base.py：Tool 抽象基类（name / description / parameters / execute）
  - agent/tools/registry.py：ToolRegistry（register / get / list / execute）
  - 先做一个最小 shell tool，供后续 AgentRunner 测试工具循环

## Step 9 重新开始（2026-08-04）

角色确认：Codex = 老师，lqs = 学生；代码由 lqs 写，Codex 只讲解 + 检查。

之前误写的 Step 9 代码已删除，现在由 lqs 重新写。

### 已完成

- base.py ✅（lqs 编写）
  - 路径：mybot/agent/tools/base.py
  - Tool 抽象基类：name / description / parameters / execute / to_schema
  - ToolResult：dataclass，text + is_error，error() / ok()，str() 返回文本
  - 已验证：语法通过，Tool / ToolResult 可以正常导入

### 数据流讲解（本次教学重点）

用户消息
  → provider.chat(messages, tools=工具定义)
  → LLMResponse
    - content：直接回答
    - tool_calls：模型想调用工具
      → registry.execute(工具名, 参数)
      → ToolResult
      → 转成 tool message
      → provider.chat(原消息 + tool message)
      → 模型看到工具结果后继续回答

Step 8 已经完成 provider 返回 tool_calls；
Step 9 负责把 tool_calls 变成真实工具执行；
Step 10 AgentRunner 负责循环上述过程。

### registry.py 明天要写

位置：mybot/agent/tools/registry.py

要求：
- register(tool)：按 tool.name 放入字典
- get(name)：找不到返回 None
- tool_names：列出工具名
- execute(name, params)：找到工具并执行
- execute 要能接收 dict 参数，也能处理 OpenAI 返回的 JSON 字符串参数
- 找不到工具、参数错误、执行异常都返回 ToolResult.error(...)
- 不能把异常抛给 AgentRunner

待办提醒：
- mybot/agent/tools/__init__.py 还没有写
- shell.py 还没写

## 老师检查（2026-08-05）

### 发现的问题

1. **base.py 内容丢失（严重）**：mybot/agent/tools/base.py 实际内容是一行乱码数字"2"，昨天验证过的 Tool 基类代码没了
2. **registry.py 未实现**：只有 import json/typing 两行
3. **__init__.py 缺失**：mybot/agent/__init__.py 和 mybot/agent/tools/__init__.py 都不存在
4. **git 未初始化**：.git 是空目录，不是有效仓库 → 代码丢失无法恢复（这就是 base.py 丢代码的根源）

### 教训

没有版本控制 = 代码随时可能永久丢失。写完一个模块就 git commit，任何误操作（覆盖、编辑器事故）都能恢复。

### 本课知识点（Step 9 下半场）

1. **registry 的作用**：AgentRunner 不 import 具体工具，只按名字查表执行 → 新增工具零改动 runner（和 ProviderRegistry 同模式）
2. **错误处理哲学**：工具错误不是异常，是"可恢复的业务错误"。返回 ToolResult.error + 提示语（原版 hint: "[Analyze the error above and try a different approach.]"），错误作为 tool message 喂回 LLM，让模型自己换策略重试
3. **OpenAI 的 arguments 是 JSON 字符串**：tool_calls[].function.arguments 是 str，execute 必须 json.loads 解析，失败走 ToolResult.error
4. **分层设计**：prepare_call(name, params) 负责查表+解析+校验，返回 (tool, clean_params, error)；execute 只做执行+兜底异常 → 校验逻辑可单独测试

### 作业清单（Step 9 收尾，每完成一个就 git commit）

- [x] 作业 0：git init + 首次 commit（2026-08-05 完成，含 .gitignore）
- [x] 作业 1：重写 mybot/agent/tools/base.py（2026-08-05 老师评审通过；建议改进：Dict->dict 内置泛型、execute 参数名 kwargs->params）
- [x] 作业 2：实现 mybot/agent/tools/registry.py + test_ToolRegistry.py 测试全绿（2026-08-05 完成）
- [x] 作业 3：补 mybot/agent/__init__.py + mybot/agent/tools/__init__.py（重导出 Tool/ToolResult/ToolRegistry，2026-08-05 完成）
- [x] 作业 4（加分）：最小 shell.py —— ✅ 完成（2026-08-05，df92084）
  - ShellTool：asyncio.create_subprocess_shell + 30s 超时 + 2000字符截断 + stderr 收集
  - test_shell.py：Test1 正常命令 / Test2 exit 3 / Test3 超长输出截断 / Test4 超时（ping 35s 触发）全绿
  - 🐛 排障实录（重要一课）："幽灵导入"——pip 可编辑安装的旧项目 codex\mybot 遮蔽 lqs\mybot；
    脚本放包目录内时 sys.path[0] 不是项目根 → import 到旧代码。排查用 module.__file__。
    修复：测试文件放项目根目录 + pip uninstall mybot（待确认执行）
  - 🐛 shell.py 踩坑：required 用集合{"command"}应为列表、eerors/errors 拼写、ToolResult.success 不存在、ToolResul.ok 少 t

## Step 9 完成（工具层 ✅ 2026-08-05）

- ✅ Tool 基类 + ToolResult
- ✅ ToolRegistry（4 条失败路径全走 ToolResult.error）
- ✅ ShellTool（第一个真工具）
- ✅ 测试：test_ToolRegistry.py（5 用例）+ test_shell.py（4 用例）全绿
- ➡️ 下一步：**Step 10 AgentRunner**（agent 的心脏）——连接 Provider + ToolRegistry + Session

### 附：git 已启用（2026-08-05）

- 提交历史：13b67bf（保护现有代码）→ 1308fea（清理误放文件）→ 36f799a（registry 初版）
- test_step6.py 已归位到项目根目录
- 今后每完成一个模块：git add -A && git commit -m "说明"

## 今日收尾（2026-08-05 晚）

- ✅ base.py 重写并通过老师评审（作业 1）
- ✅ registry.py 修复 1-4 通过老师复查：
  1. 导入改为相对导入 `from .base import ...`
  2. tool_names / execute 缩进收进类
  3. _normalize_params 挪到类级且定义在 execute 之前
  4. base.py 的 error/ok 签名统一为 message 关键字
- ⚠️ 修复版【尚未提交】——收工前必须 commit（36f799a 里是坏版本）
- 📌 明日任务（作业 2 收尾 + 作业 3/4）：
  - [ ] 写 test_registry.py（5 用例：正常/JSON字符串/未知工具/工具异常/get与tool_names）
  - [ ] 跑绿后 commit（分两个：registry 一个、test 一个）
  - [ ] 作业 3：补 mybot/agent/__init__.py + mybot/agent/tools/__init__.py
  - [ ] 作业 4（加分）：最小 shell.py

### registry.py 验收标准

临时脚本注册一个假工具，测 4 条路径：
1. 正常调用 → 返回结果
2. JSON 字符串参数 → 被解析
3. 不存在的工具 → ToolResult.error（不抛异常）
4. 工具抛异常 → 被捕获转 ToolResult.error
