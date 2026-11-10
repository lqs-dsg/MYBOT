# mybot — 从零实现的个人 AI Agent

> 不依赖 LangChain / LlamaIndex，从 0 到 1 实现一个能**自主使用工具**、**跨会话记忆**、带**评测体系**的 AI Agent。

[![CI](https://github.com/lqs-dsg/MYBOT/actions/workflows/ci.yml/badge.svg)](https://github.com/lqs-dsg/MYBOT/actions)

## ✨ 亮点

- **完整的 Agent 循环**：消息总线 → 上下文构建 → LLM 对话循环 → 工具执行 → 结果回填 → 最终回答
- **跨会话记忆**：会话历史以 JSONL 持久化，支持跨进程回放与多会话隔离
- **工具系统**：4 个内置工具（`shell` / `read_file` / `write_file` / `list_files`），带 **workspace 沙箱**（防路径穿越）
- **Evals 评测体系**：15 个评测用例（4 个能力维度）、双模式（CI 确定性 + 真实模型）、失败归因、结果存档与回归对比
- **数据驱动优化**：基于失败归因优化工具描述与错误提示，live 通过率 **76.2% → 95.3%**

## 🚀 快速开始

```bash
# 安装（含开发依赖）
pip install -e ".[dev]"

# 配置（~/.mybot/config.json）
# {
#   "providers": {"deepseek": {"apiKey": "${DEEPSEEK_API_KEY}", "apiBase": "https://api.deepseek.com", "model": "deepseek-chat"}},
#   "agents": {"defaults": {"provider": "deepseek"}}
# }
setx DEEPSEEK_API_KEY "sk-xxx"

# 对话
mybot agent -m "看看当前目录有哪些文件，告诉我这个项目是做什么的"
mybot agent          # 交互模式（/exit 退出）
```

## 🏗️ 架构

```
Channel (CLI)  ← 可扩展：Telegram / WebSocket ...
     │  InboundMessage / OutboundMessage
     ▼
MessageBus（asyncio.Queue 解耦）
     ▼
AgentLoop（编排一个 turn：读记忆 → 构建上下文 → 跑循环 → 落盘 → 回信）
     ├── SessionManager  （JSONL 持久化 / 历史回放）
     ├── ContextBuilder  （system prompt + 引导文件 + 历史截断）
     └── AgentRunner     （LLM 循环 + 工具执行 + 迭代上限）
             ├── LLMProvider（OpenAI 兼容；DeepSeek 等）
             └── ToolRegistry（插件式工具注册）
```

**设计原则**：每个组件只依赖接口、不依赖实现（依赖注入贯穿全项目），因此每个边界都能被单独测试/替换。

## 📊 评测（Evals）

| 类别 | 用例数 | 测什么 |
|---|---|---|
| tool_selection | 5 | 该用哪个工具（含"不该用工具"） |
| multi_step | 4 | 多步任务规划与执行 |
| error_recovery | 3 | 工具报错后的自我恢复 |
| no_tool_needed | 3 | 防止过度调用工具 |

```bash
python -m evals run                                  # 确定性模式（剧本，零成本，进 CI）
python -m evals run --live --config ~/.mybot/config.json   # 真实模型
python -m evals run --compare last                   # 与上次对比
```

**实测结果（真实模型 deepseek-chat，14 个适用用例，3 次运行平均）**：

| 指标 | 优化前 | 优化后 |
|---|---|---|
| 通过率 | **76.2%** | **95.3%** |
| 平均迭代轮数 | 2.21 | 2.29 |
| 平均延迟 | 2.49s | 2.69s |

优化手段：明确工具分工的描述 + 错误信息附带"下一步提示"（详见 `DEVLOG.md`）。

## 🧪 测试

```bash
pytest -q        # 31 个 pytest 测试（另有 2 个集成脚本：test_step6.py / test_ToolRegistry.py）
```

覆盖：配置加载 / 消息总线 / Provider（含 HTTP 请求体断言）/ 工具执行与路径穿越防护 / Session / ContextBuilder / AgentLoop（跨 turn 记忆、工具落盘、异常韧性）。

## 📌 项目结构

```
mybot/
├── agent/
│   ├── loop.py        # AgentLoop：编排一个 turn
│   ├── runner.py      # AgentRunner：LLM 循环 + 工具执行
│   ├── context.py     # ContextBuilder：system prompt + 历史
│   └── tools/         # Tool 基类 / ToolRegistry / shell / filesystem
├── bus/               # MessageBus + 事件
├── config/            # Pydantic schema + loader + paths
├── providers/         # LLMProvider 抽象 + OpenAI 兼容实现
├── session/           # JSONL 会话持久化
└── cli.py             # CLI 入口
evals/
├── cases/             # 15 个 YAML 评测用例
├── loader.py          # 用例加载
├── runner.py          # 执行器（剧本 / 真模型）
├── graders.py         # 评分器（工具序列/结果/迭代/恢复）
├── report.py          # 指标 + 报告 + 存档 + 对比
└── __main__.py        # python -m evals run
```

## 🛠 技术栈

Python 3.13 / asyncio / Pydantic v2 / OpenAI SDK / Typer / pytest / GitHub Actions

## ⚠️ 已知限制

- 目前只实现 CLI 渠道（Channel 抽象已预留，可扩展 Telegram/WebSocket）
- 评测的确定性模式依赖剧本（测基础设施），测模型能力需 `--live` 模式
- CI 在 Windows 上运行（工具/用例含 Windows 路径）

## 📄 License

MIT
