## nanobot（HKUDS/nanobot）从零到一复现指导

> 基于仓库 C:\Users\33020\Desktop\codex\nanobot（v0.2.2），全部通过阅读源码形成。目标是帮助读者按模块理解整条数据流，并具备自行复现的能力。

本文档按项目的数据流向自底向上组织。每节包含：该模块解决什么问题 → 核心设计 → 关键代码入口 → 复现时要注意的点。

---

## 一、整体架构概览

`
Channel（CLI / WebUI / Telegram / Discord / ...）
     │  InboundMessage
     ▼
MessageBus (bus/events.py, bus/queue.py)
     │
     ▼
AgentLoop (agent/loop.py)     ← 接收消息、管理 session、构建 context、发布回复
     │
     ▼
AgentRunner (agent/runner.py) ← 与 LLM 对话，执行 tool calls，流式处理
     │
     ▼
Provider (providers/)         ← 具体的大模型后端（OpenAI、Anthropic、Bedrock 等）
     │
     ▼
Tools (agent/tools/)          ← 文件、Shell、Web 搜索、MCP、Cron、图片生成等
`

**核心哲学**：nanobot 的核心（AgentLoop + AgentRunner）极小且可读，所有功能通过 Provider 注册、Channel 插件、Tool 注册表三种扩展机制
**两个关键分离**：
- AgentLoop 面向通道：负责消息路由、session 选择、上下文构建、回复发布
- AgentRunner 面向模型：负责 provider 调用、tool call 循环、流式处理、迭代限制
- ContextGovernor（agent/context_governance.py）：在 runner 内部监控 token 使用，必要时自动截断或 compact

---

## 二、配置系统（config/）

### 2.1 解决的问题

需要一个类型安全、可序列化、支持环境变量插值的配置层，统一管理 provider 凭据、model preset、channel 开关、tool 控制、gateway 端口等所有运行
### 2.2 核心设计

| 文件 | 职责 |
|---|---|
| config/schema.py | Pydantic v2 模型，定义所有配置字段（ProvidersConfig、ModelPresetConfig、AgentDefaults、ChannelsConfig、GatewayConfig 等） |
| config/loader.py | 从 ~/.nanobot/config.json 加载 JSON，做环境变量 ${VAR} 插值，返回 Config 实例 |
| config/paths.py | 统一解析 config/workspace/session/memory 的文件系统路径 |
| config_base.py | 所有配置模型的基类，提供 camelCase ↔ snake_case 双向兼容 |

### 2.3 复现要点

1. **Pydantic 模型定义**：每个配置域是一个 class（如 ProvidersConfig），字段类型精确到 str | None、int、ool，用 Field(default=...) 给默认值。
2. **camelCase 双向兼容**：config_base.py 的 Base 类配置了 model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)。这意味着 JSON 里写 piKey 和 pi_key 都能正确解析，保存时统一写 camelCase。
3. **环境变量插值**：loader.py 用正则匹配 ${VAR} 模式，从 os.environ 获取值替换。这允许用户把 API key 写成 "apiKey": "" 而不硬编码在 config 里。
4. **配置路径默认值**：~/.nanobot/config.json 和 ~/.nanobot/workspace/，可通过 CLI 参数 --config / --workspace 覆盖。

### 2.4 最小复现

`python
# config/schema.py 核心结构示意
from pydantic import BaseModel, Field

class ProviderConfig(BaseModel):
    api_key: str | None = None
    api_base: str | None = None

class ProvidersConfig(BaseModel):
    openai: ProviderConfig = Field(default_factory=ProviderConfig)
    anthropic: ProviderConfig = Field(default_factory=ProviderConfig)
    # ... 更多 provider

class ModelPresetConfig(BaseModel):
    provider: str = "auto"
    model: str = ""

class Config(BaseModel):
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    model_presets: dict[str, ModelPresetConfig] = Field(default_factory=dict)
    agents: AgentDefaults = Field(default_factory=AgentDefaults)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
`

---

## 三、消息总线（bus/）

### 3.1 解决的问题

所有 Channel 和 AgentLoop 之间需要一个解耦的通信机制。Channel 产生消息 → Bus 分发 → AgentLoop 处理 → 结果通过 Bus 返回给 Channel。

### 3.2 核心设计

| 文件 | 职责 |
|---|---|
| us/events.py | 定义 InboundMessage 和 OutboundMessage 两个数据类 |
| us/queue.py | MessageBus：asyncio.Queue 驱动的消息总线，支持多 channel 并发 |
| us/outbound_events.py | 定义流式输出事件：StreamDeltaEvent、StreamedResponseEvent、StreamEndEvent、ProgressEvent、RetryWaitEvent |
| us/runtime_events.py | 运行时级事件总线，用于 SDK/API 层监听 agent 生命周期 |
| us/progress.py | 进度回调构建器 |

### 3.3 InboundMessage 结构

`python
@dataclass
class InboundMessage:
    channel: str          # "telegram" / "discord" / "cli" / "websocket"
    sender_id: str        # 发送者 ID
    chat_id: str          # 会话 ID
    content: str          # 文本内容
    timestamp: datetime
    media: list[str]      # 媒体 URL 列表
    metadata: dict        # channel 特有元数据
    session_key_override: str | None  # 覆盖默认 session key
`

**session_key 的生成规则**：默认 <channel>:<chat_id>，如 	elegram:123456。这是 session 隔离的核心——不同的 channel+chat 组合自动拥有独立的对话历史。

### 3.4 复现要点

1. MessageBus 是 asyncio 原生的，内部用 syncio.Queue 做消息缓冲。
2. OutboundMessage 携带一个 event 字段（OutboundEvent | None），用于区分普通文本回复和流式 delta/progress 事件。
3. RuntimeEventBus 是第二层总线，用于 SDK 和 API 服务监听 agent 内部状态（run_started、tool_started、run_completed 等），与面向 channel 的消息总线完全独立。

---

## 四、Agent 循环：AgentLoop（agent/loop.py）
222
### 4.1 解决的问题

这是整个 nanobot 的"心脏"。它负责：接收消息 → 确定 session → 构建 context → 调用 runner → 发布回复。所有 channel 最终都汇入这里。

### 4.2 核心流程（一帧 turn）

`
1. bus.receive()                           # 从消息总线取一条 InboundMessage
2. 确定 session_key                        # channel:chat_id 或 unified session
3. SessionManager.load_or_create()         # 加载 JSONL 会话历史
4. ContextBuilder.build()                  # 组装 system prompt + history + skills + memory
5. 检查是否 slash command（/exit, /model, /dream 等）→ 直接处理，不调模型
6. AgentRunner.run()                       # 交给 runner 与 LLM 对话
7. SessionManager.save()                   # 保存本轮对话到 JSONL
8. bus.publish(outbound)                   # 发布回复到消息总线
`

### 4.3 关键设计决策

1. **CommandRouter 优先级**：在执行 agent 之前，先检查消息是否为内置命令（/exit、/model、/dream、/clear、/trigger 等）。命令匹配成功则短路，不入模型。
2. **SubagentManager**：支持 	ask 工具启动子 agent。子 agent 复用同一个 AgentLoop，但有独立的 session 和 context。
3. **AutoCompact**：在每个 turn 开始前检查 session 文件是否过大，自动触发上下文压缩。
4. **CronTurnCoordinator**：管理定时任务的 turn 调度，确保 cron job 在其绑定的 session 中执行。
5. **Goal 系统**：支持长期目标追踪，通过 goal_permission.py 控制 agent 行为边界。

### 4.4 复现要点

1. AgentLoop 的构造函数接收 MessageBus、Config、workspace，不直接依赖任何具体 channel。
2. Hook 系统（gent/hook.py）允许在 turn 生命周期注入回调：on_turn_start、on_turn_end、on_message 等。SDK 的流式输出就是通过 SDKStreamingHook 实现的。
3. 进度回调（ProgressEvent）用于向 channel 报告"正在搜索"、"正在读取文件"等中间状态。

---

## 五、Agent 执行器：AgentRunner（agent/runner.py）

### 5.1 解决的问题

负责与 LLM provider 的具体对话循环：发消息 → 收回复 → 如果是 tool call 就执行 → 把 tool 结果喂回去 → 直到模型给出最终文本回复。

### 5.2 核心流程

`
while iteration < max_iterations:
    1. provider.chat(messages, tools, ...)    # 调用 LLM
    2. 如果是 streaming：逐 delta 回调 hook.on_delta()
    3. 如果 response 包含 tool_calls：
       a. 执行 tool（支持并发）
       b. 构建 tool_result 消息，追加到 messages
       c. continue 循环
    4. 如果是最终文本回复：回调 hook.on_complete()，退出循环
`

### 5.3 关键设计

1. **AgentRunSpec**：一个 dataclass，把 runner 所需的所有参数（initial_messages、tools、runtime、max_iterations 等）打包成一个不可变对象。
2. **ContextGovernor**：在每次迭代前检查 token 使用量，超出限制时自动执行上下文治理（截断旧消息、触发 compact）。
3. **错误重试**：区分可重试错误（网络超时、rate limit）和不可重试错误（401 认证失败）。可重试的用指数退避。
4. **空回复处理**：连续收到空回复时，runner 会注入一条系统提示，要求模型给出实质内容，最多重试 _MAX_EMPTY_RETRIES 次。
5. **MessageTool（message 工具）**：一种特殊的 tool，允许 agent 在tool call 中直接向用户发送中间消息，而不中断 tool call 循环。

### 5.4 复现要点

1. AgentRunner 不持有任何状态——它只是一个纯函数式的执行器。所有状态（messages、iteration 计数）通过参数传入，通过返回值传出。
2. Tool 执行支持并发模式（concurrent_tools=True）：当模型一次返回多个 tool call 时，用 syncio.gather 并行执行。
3. Thinking/Reasoning 处理：IncrementalThinkExtractor 从 provider 流式响应中提取 	hinking 块，区分推理内容和最终文本。

---

## 六、上下文构建：ContextBuilder（agent/context.py）

### 6.1 解决的问题

将零散的信息源（system prompt 模板、workspace 文件、skills、memory、session 历史、channel 元数据、runtime context）组装成 LLM 可消费的 messages 列表。

### 6.2 构建顺序

`
1. System Prompt
   ├── 基础 agent 提示词（从 nanobot/templates/ 加载 Jinja2 模板渲染）
   ├── SOUL.md、USER.md、AGENTS.md（workspace 引导文件）
   ├── Skills 定义（workspace/skills/ 下的 .md 文件）
   ├── Memory（MEMORY.md 内容）
   ├── 当前时间、时区、操作系统信息
   └── Runtime Context（MCP server 状态、CLI apps 配置等）

2. Messages
   ├── Session 历史（从 JSONL 回放最近 N 条消息）
   ├── 当前用户消息（InboundMessage.content）
   └── 媒体附件（图片、文件等）
`

### 6.3 关键设计

1. **Bootstrap 文件优先级**：AGENTS.md > SOUL.md > USER.md。这些文件让用户可以"编程" agent 的行为和人格。
2. **Skills 系统**（gent/skills.py）：workspace 下的 skills/ 目录，每个子目录是一个 skill，包含 SKILL.md 定义文件。Skills 通过 SkillsLoader 发现并注入 system prompt。
3. **RUNTIME_CONTEXT_TAG**：system prompt 中有一个 {{RUNTIME_CONTEXT}} 占位符，在运行时由各 tool 动态填充（如当前打开的 MCP servers 列表）。
4. **token 预算**：历史消息回放有 token 上限（_MAX_HISTORY_TOKENS = 8000），超出部分从旧到新截断。

### 6.4 复现要点

1. Jinja2 模板位于 
anobot/templates/，核心模板定义了 agent 的能力声明、tool 使用规范、安全边界等。
2. ContextBuilder 是 AgentLoop 内部创建的，每个 turn 重新构建一次。
3. 图片附件通过 base64 编码直接嵌入 messages，不依赖外部 URL。

---

## 七、Provider 系统（providers/）

### 7.1 解决的问题

统一抽象 30+ 个大模型后端的差异（OpenAI、Anthropic、Azure、Bedrock、Ollama、vLLM、OpenRouter、GitHub Copilot 等），让 AgentRunner 用同一套接口调用任意模型。

### 7.2 核心设计

| 文件 | 职责 |
|---|---|
| providers/registry.py | ProviderSpec 数据类：定义每个 provider 的元数据（名称、关键词、env key、默认 API base、后端类型等） |
| providers/base.py | LLMProvider 抽象基类：定义 chat() 和 chat_stream() 两个核心方法 |
| providers/factory.py | ProviderFactory：根据 config 和 ProviderSpec 创建具体的 provider 实例 |
| providers/openai_compat.py | OpenAI 兼容实现（多数 provider 共用此实现） |
| providers/anthropic.py | Anthropic 专用实现 |
| providers/image_generation.py | 图片生成 provider 抽象 |
| providers/transcription.py | 语音转文字 provider |

### 7.3 ProviderSpec 关键字段

`python
@dataclass(frozen=True)
class ProviderSpec:
    name: str                          # 配置字段名，如 "openrouter"
    keywords: tuple[str, ...]          # 模型名关键词，用于自动匹配
    env_key: str                       # 环境变量名
    display_name: str                  # 显示名
    backend: str                       # "openai_compat" | "anthropic" | "azure_openai" | "bedrock" 等
    default_api_base: str              # 默认 API 端点
    is_gateway: bool                   # 是否为网关（可路由多种模型）
    is_local: bool                     # 是否为本地部署
    detect_by_key_prefix: str          # 通过 API key 前缀自动识别
    detect_by_base_keyword: str        # 通过 API base URL 关键词自动识别
    supports_max_completion_tokens: bool
    strip_model_prefix: bool           # 发送前去掉 provider/ 前缀
    model_overrides: tuple             # 特定模型的参数覆盖
    is_oauth: bool                     # 是否使用 OAuth 登录
`

### 7.4 复现要点

1. **添加新 provider 只需两处改动**：在 
egistry.py 加一个 ProviderSpec，在 schema.py 的 ProvidersConfig 加一个字段。大部分 provider 直接用 openai_compat 后端即可。
2. **Provider 选择优先级**：显式指定 > model name 关键词匹配 > API key 前缀匹配 > API base URL 匹配 > 本地 provider fallback。
3. **Anthropic 专用路径**：因为 Anthropic API 的 tool use 格式与 OpenAI 不兼容，所以有独立的 nthropic.py 实现。
4. **OAuth provider**（OpenAI Codex、GitHub Copilot）：不走 API key，而是通过 oauth-cli-kit 做浏览器 OAuth 登录。

---

## 八、Tool 系统（agent/tools/）

### 8.1 解决的问题

让 LLM 能执行具体操作：读写文件、运行 shell 命令、搜索网页、调用 MCP server、生成图片、设置定时提醒等。需要一个可扩展的 tool 注册和执行框架。

### 8.2 核心设计

| 文件 | 职责 |
|---|---|
| gent/tools/base.py | Tool 抽象基类：定义 
ame、description、parameters（JSON Schema）、execute() |
| gent/tools/registry.py | ToolRegistry：动态注册/查找/执行 tool |
| gent/tools/schema.py | Tool schema 相关工具 |
| gent/tools/filesystem.py | 文件读写/编辑/patch |
| gent/tools/shell.py | Shell 命令执行（含沙箱） |
| gent/tools/web.py | Web 搜索和网页抓取 |
| gent/tools/mcp.py | MCP 协议集成 |
| gent/tools/cron.py | 定时提醒 |
| gent/tools/image_generation.py | 图片生成 |
| gent/tools/self.py | 运行时自省（查看 session、config 等） |
| gent/tools/message.py | 向用户发送中间消息 |

### 8.3 Tool 接口

`python
class Tool(ABC):
    name: str
    description: str
    parameters: dict  # JSON Schema

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        ...
`

### 8.4 复现要点

1. **Tool 自动发现**：ToolLoader.discover() 通过 pkgutil 扫描 
anobot/agent/tools/ 目录，自动注册所有 Tool 子类。第三方可以通过 [project.entry-points."nanobot.tools"] 注册插件 tool。
2. **MCP 集成**：mcp.py 封装了 MCP Python SDK，支持 stdio 和 HTTP 两种传输。MCP server 的 tools 会自动映射为 nanobot tools。
3. **Shell 沙箱**：shell.py 实现了多层安全策略——workspace 路径约束、命令白名单/黑名单、超时控制、禁止交互式命令。
4. **文件编辑**：ilesystem.py 的 pply_patch 工具实现了一个自定义的 patch 格式（*** Begin Patch / *** End Patch），用于精确的文件修改。
5. **Web 安全**：web.py 内置 SSRF 防护，禁止访问内网地址和 localhost。

---

## 九、Session 管理（session/manager.py）

### 9.1 解决的问题

持久化存储对话历史，支持高效的追加写入和按需回放。session 是 agent 记忆的核心载体。

### 9.2 核心设计

- **存储格式**：JSONL（每行一个 JSON 对象），文件路径 <workspace>/sessions/<safe_session_key>.jsonl
- **消息结构**：{"role": "user"|"assistant"|"system"|"tool", "content": "...", "timestamp": "...", ...}
- **回放策略**：最多回放 FILE_MAX_MESSAGES=2000 条或 context_window_tokens / 100 条，取较小值
- **Fork 机制**：支持从任意消息点分叉创建新 session

### 9.3 复现要点

1. JSONL 格式简单但有效——追加 O(1)，不需要重写整个文件。
2. SessionManager 使用 ilelock 保证并发安全。
3. session key 的"安全文件名"转换：safe_filename() 函数将特殊字符替换为 _，确保跨平台兼容。

---

## 十、Memory 与 Dream（agent/memory.py）

### 10.1 解决的问题

Session 历史只能记住最近几十轮对话。Memory 是长期记忆层，通过周期性"Dream"合并进程，将碎片化的对话历史提炼为结构化的记忆文件。

### 10.2 核心设计

| 文件 | 用途 |
|---|---|
| <workspace>/memory/MEMORY.md | 长期记忆的主文件 |
| <workspace>/memory/history.jsonl | 待合并的原始对话历史 |

**Dream 流程**：
1. Gateway 启动时注册一个周期性 cron job（默认每 2 小时）
2. Consolidator 读取 history.jsonl 中的增量对话
3. 调用 LLM（可使用独立 model）将增量对话合并到 MEMORY.md
4. 合并完成后清空 history.jsonl

### 10.3 复现要点

1. Dream 是一个标准的 agent turn——它复用 AgentRunner，只是 system prompt 不同（提示词要求"合并记忆"而非"回答问题"）。
2. Memory 文件在每次 context 构建时被注入 system prompt。
3. memory.md 的 guides/ai-agent-memory.md 有更详细的用户视角说明。

---

## 十一、Channel 系统（channels/）

### 11.1 解决的问题

统一抽象不同聊天平台（CLI、WebSocket/WebUI、Telegram、Discord、Slack、WeChat、Feishu、Email 等）的差异，让 AgentLoop 只看到统一的 InboundMessage / OutboundMessage。

### 11.2 核心设计

| 文件 | 职责 |
|---|---|
| channels/base.py | BaseChannel 抽象基类：start()、stop()、send_message() |
| channels/manager.py | ChannelManager：根据 config 启动/停止所有启用的 channel |
| channels/registry.py | ChannelRegistry：内置 channel 列表 + 插件入口点发现 |
| channels/websocket.py | WebSocket channel：同时承载 WebUI 和 WebSocket 协议 |

### 11.3 BaseChannel 接口

`python
class BaseChannel(ABC):
    name: str
    display_name: str

    async def start(self) -> None: ...       # 启动监听
    async def stop(self) -> None: ...        # 停止
    async def send_message(self, msg: OutboundMessage) -> None: ...  # 发送回复
`

### 11.4 复现要点

1. **频道特定的消息格式化**：每个 channel 自行处理 Markdown → 平台格式的转换（如 Telegram 的 HTML、Discord 的 embed）。
2. **流式输出**：channel 如果支持编辑消息（如 Telegram），可以将 StreamDeltaEvent 实时更新为正在输入中的消息。
3. **登录机制**：部分 channel（如 WeChat）需要扫码登录，通过 login() 方法实现。
4. **WebSocket channel 的特殊性**：它同时承载 WebUI（浏览器）和 WebSocket 客户端，是 Gateway 的核心 channel。

---

## 十二、Gateway（gateway/）

### 12.1 解决的问题

将 nanobot 作为长期运行的后台服务：启动所有 channel、注册 cron jobs、提供健康检查端点。
anobot gateway 命令即为入口。

### 12.2 核心组件

| 组件 | 职责 |
|---|---|
| gateway/service.py | 系统服务安装器（systemd / launchd） |
| gateway/runtime.py | Gateway 运行时：启动 channels + cron + Dream |
| pi/server.py | OpenAI 兼容 API 和健康检查端点 |

### 12.3 运行时组件

Gateway 启动时同时运行：
1. 所有已启用的 chat channel
2. WebSocket channel（如果配置了 WebUI）
3. Cron service（用户定时提醒）
4. Dream consolidation job（如果启用）
5. Heartbeat job（如果 <workspace>/HEARTBEAT.md 存在）
6. 健康检查 HTTP 端点（默认端口 18790）

### 12.4 复现要点

1. Gateway 的多任务并发通过 syncio.gather 实现，每个 channel 是一个独立的协程。
2. 健康检查端点用 iohttp 实现，路由简单（/health 返回 {"status": "ok"}）。
3. --background 标志通过 subprocess.Popen + 日志文件实现后台化。
4. macOS/Linux 上支持通过 systemd 或 launchd 注册为系统服务。

---

## 十三、WebUI（webui/）

### 13.1 解决的问题

提供一个功能完整的浏览器端 AI 对话工作台：多会话管理、设置面板、工具配置、实时流式对话。

### 13.2 技术栈

- React 18 + TypeScript
- Vite 构建
- Tailwind CSS + shadcn/ui 组件库
- WebSocket 与后端通信

### 13.3 关键目录

| 目录 | 职责 |
|---|---|
| webui/src/App.tsx | 主应用组件（73000+ 行，包含所有页面逻辑） |
| webui/src/components/ | UI 组件 |
| webui/src/hooks/ | 自定义 React hooks |
| webui/src/lib/ | 工具函数和 API 客户端 |
| webui/src/providers/ | React context providers |
| webui/src/i18n/ | 国际化 |
| webui/src/workers/ | Web Workers |

### 13.4 构建与部署

构建产物输出到 
anobot/web/dist/，在 hatch build 时被打包进 wheel。用户安装 pip 包后即可直接使用 WebUI，无需 Node.js。

### 13.5 复现要点

1. WebUI 通过 WebSocket 与后端的 channels/websocket.py 通信。协议不是标准的 OpenAI API，而是自定义的 JSON 消息格式。
2. Settings 面板直接读写 config.json（通过后端 API），不经过数据库。
3. 多会话支持通过 session_key 实现，WebUI 中的每个"对话"对应一个独立的 session JSONL 文件。

---

## 十四、CLI（cli/commands.py）

### 14.1 解决的问题

提供命令行入口：
anobot agent、
anobot gateway、
anobot onboard、
anobot serve、
anobot status 等。

### 14.2 关键命令

| 命令 | 作用 |
|---|---|
| 
anobot agent -m "Hello" | 一次性 CLI 对话 |
| 
anobot agent | 交互式终端对话 |
| 
anobot gateway | 启动长期服务 |
| 
anobot onboard --wizard | 交互式配置向导 |
| 
anobot serve | 启动 OpenAI 兼容 API |
| 
anobot status | 检查配置状态 |
| 
anobot webui | 启动 WebUI |

### 14.3 复现要点

1. CLI 框架使用 **Typer**（基于 Click），支持丰富的参数解析和帮助信息。
2. 交互式终端使用 **prompt-toolkit**，支持多行输入（Alt+Enter）、历史记录、语法高亮。
3. Markdown 渲染使用 **Rich** 库，在终端中提供格式化输出。
4. 流式输出通过 StreamRenderer 和 ThinkingSpinner 实现，实时显示模型回复的增量内容。

---

## 十五、SDK（nanobot.py + sdk/）

### 15.1 解决的问题

提供编程式 Python 接口，让开发者将 nanobot 嵌入自己的应用中。

### 15.2 核心 API

`python
from nanobot.nanobot import Nanobot

bot = Nanobot.from_config()
result = await bot.run("Summarize this repo")
print(result.content)

# 流式调用
async for event in bot.stream("Explain this code"):
    if event.type == "text_delta":
        print(event.text, end="")
`

### 15.3 复现要点

1. Nanobot 类是 AgentLoop 的包装器，提供三个子客户端：ot.sessions、ot.memory、ot.runtime。
2. 流式输出通过 SDKStreamingHook（一种 AgentHook）捕获 runner 事件并转换为 Python 迭代器。
3. RuntimeClient 允许程序化控制 gateway 的生命周期。

---

## 十六、复现路线图（推荐顺序）

以下是按依赖关系排列的最小复现路径。每个阶段完成后都有一个可运行的验证检查点。

### 阶段 1：最小骨架 ✓

1. **配置系统**：Pydantic schema + JSON loader + 路径解析
2. **消息总线**：InboundMessage / OutboundMessage + asyncio.Queue
3. **Provider 基础**：一个 openai_compat provider + registry

**验证**：python -c "from mybot.config import load_config; print(load_config())"

### 阶段 2：Agent 核心 ✓

4. **Tool 基础**：Tool 基类 + ToolRegistry + 至少一个 tool（如 shell）
5. **AgentRunner**：消息循环 + tool call 处理 + 流式回调
6. **Session 管理**：JSONL 读写 + 历史回放
7. **ContextBuilder**：system prompt 模板 + session 历史拼接
8. **AgentLoop**：连接 Bus → Runner → Context → Session

**验证**：python -m mybot agent -m "Hello! 请用 ls 列出当前目录"

### 阶段 3：CLI 体验 ✓

9. **CLI 命令**：Typer app + gent 命令 + 交互式对话
10. **流式渲染**：Rich 实时输出

**验证**：终端中与 agent 多轮对话，检查历史是否正确保存和加载

### 阶段 4：Gateway 化 ✓

11. **WebSocket Channel**：aiohttp + WebSocket handler
12. **Gateway 运行时**：多 channel 并发 + 健康检查
13. **Cron + Dream**：定时任务 + 记忆合并

**验证**：python -m mybot gateway 后能通过 WebSocket 客户端对话

### 阶段 5：WebUI（前端）✓

14. **Vite + React 项目**：Tailwind + shadcn/ui
15. **WebSocket 客户端**：连接后端、发送消息、接收流式回复
16. **设置面板**：配置管理界面

**验证**：浏览器打开 WebUI，完成登录和对话

### 阶段 6：扩展生态 ✓

17. **更多 provider**：Anthropic、Azure、Bedrock、Ollama
18. **更多 channel**：Telegram、Discord
19. **MCP 集成**：MCP client + tool 映射
20. **Python SDK**：Nanobot 类 + 流式 API

---

## 十七、关键文件速查表

| 当你需要... | 查看 |
|---|---|
| 理解一条消息的完整旅程 | us/events.py → gent/loop.py → gent/runner.py → us/outbound_events.py |
| 添加新的 LLM provider | providers/registry.py + config/schema.py |
| 添加新的 chat channel | channels/base.py → 参考 channels/telegram.py |
| 添加新的 tool | gent/tools/base.py → 参考 gent/tools/web.py |
| 修改 agent 行为 | gent/context.py（system prompt）+ 	emplates/ |
| 理解配置结构 | config/schema.py |
| 调试 session 问题 | session/manager.py |
| 理解 memory 机制 | gent/memory.py + gent/context.py |
| 理解安全边界 | security/workspace_policy.py + gent/tools/shell.py |
| 修改 WebUI | webui/src/App.tsx + webui/src/components/ |

---

*本文档完全基于 C:\Users\33020\Desktop\codex\nanobot 源码阅读形成，v0.2.2。*
