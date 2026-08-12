# 学习日志

## 2026-06-12

### 阶段 0.1：项目环境与安全基线

- 完成 Claude Code 风格 CLI 的资料评估、范围界定与分阶段开发计划。
- 建立本地 Git 仓库、GitHub 远程关联、Python 3.12.13 虚拟环境和可安装项目骨架。
- 建立依赖、测试、静态检查、凭据模板与 Git 忽略规则；`.env`、虚拟环境和私有复盘不会进入版本控制。
- 验证结果：项目可编辑安装；`agent-code --help`、`agent-code version`、测试与 Ruff 检查均可执行。
- 关键理解：开发 Agent 功能前，先确保运行环境可重建、测试可重复执行，并使密钥和私有运行数据与版本控制隔离。

### 阶段 0.2：最小命令行与 Agent Loop

- 实现命令组、帮助页和版本命令，避免单命令模式导致子命令解析错误。
- 建立消息、工具调用和模型响应的数据模型，以及 Provider 协议与可控的 MockProvider。
- 实现 echo 工具和最小 Agent Loop，支持直接回答、工具结果回填、未知工具错误回传与最大轮数保护。
- 验证结果：Python 3.12.13 环境下共 10 项测试通过；`ruff check .` 通过；帮助页和版本命令输出符合预期。
- 关键理解：模型负责决定是否调用工具；Agent Loop 负责执行工具、把结果写回消息历史，并在模型给出最终文本或达到安全上限时结束。

### 阶段 0.3：一次性运行与交互式终端

- 实现本地 DemoProvider、`agent-code run` 与 `agent-code repl`，将命令行输入接入最小 Agent Loop。
- REPL 支持连续输入、空输入跳过、`/exit`、`/quit`、EOF 与 Ctrl+C 退出。
- 验证结果：Python 3.12.13 环境下共 14 项测试通过；`ruff check .` 通过；一次性运行和 REPL 均完成“请求 echo 工具 → 回填结果 → 输出最终文本”的本地端到端演示。
- 关键理解：CLI 只负责接收和呈现用户输入输出；Agent Loop 负责运行时循环；Provider 决定模型响应。三者分离后，后续替换真实模型不需要重写 CLI 或工具逻辑。

### 阶段 1.1：Anthropic 兼容协议适配

- 引入 Anthropic Python SDK，并将工具协议扩展为名称、说明和 JSON Schema。
- 实现 AnthropicProvider，将内部消息转换为 Messages API 的文本、`tool_use` 与 `tool_result` 内容块。
- 保留 MockProvider 与 DemoProvider，测试时使用假客户端，不发起真实网络请求或读取真实密钥。
- 验证结果：Python 3.12.13 环境下共 16 项测试通过；Ruff 自动修正 import 排序后复查通过。
- 关键理解：真实模型接入的关键不只是发送提示词，还要严格保持“assistant 发出 tool_use，user 回传 tool_result”的消息顺序；协议转换集中在 Provider，Agent Loop 不应感知具体 SDK。

### 阶段 1.2：Provider 配置与安全选择

- 实现 Anthropic 配置加载，支持从命令行选项或环境变量读取模型名、Base URL 与凭据；命令行选项优先。
- 为 `run` 与 `repl` 添加 `--provider`、`--model`、`--base-url`；默认仍使用本地 demo，不会意外调用真实模型。
- 未选择受支持 Provider，或选择真实 Provider 但缺少配置时，命令行给出明确错误并以状态码 2 退出。
- 验证结果：Python 3.12.13 环境下共 21 项测试通过；`ruff check .` 通过；默认 demo 正常运行，未配置真实 Provider 时未联网并提示缺少 `ANTHROPIC_API_KEY` 和 `AGENT_CODE_MODEL`。
- 关键理解：真实 Provider 必须是显式选择；配置校验应发生在网络调用之前，并且错误信息只指出缺失配置名称，绝不输出密钥内容。

### 阶段 1.3：模型服务错误处理

- 将 Anthropic SDK 的认证失败、限流、超时、连接与服务端异常转换为统一的 ProviderError。
- 一次性运行在模型服务失败时以明确状态码退出；REPL 显示错误后保持会话，不因一次失败崩溃。
- 禁用 SDK 的自动重试，避免在初版中因隐式重试增加难以观察的等待、额度消耗或重复行为。
- 验证结果：Python 3.12.13 环境下共 24 项测试通过；`ruff check .` 通过。测试覆盖认证、限流、连接错误的中文提示，并验证错误文本不包含测试密钥。
- 关键理解：网络与模型错误应在 Provider 边界被转换为稳定、可操作且不含敏感信息的应用错误；CLI 负责呈现和退出策略，而不应直接暴露 SDK 异常。
