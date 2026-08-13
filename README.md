# agent-code

一个用于学习 Agent Harness 的、从零实现的 Claude Code 风格命令行工具。它不是
Anthropic 官方 Claude Code 的替代品，也不应直接用于生产环境或高风险操作。

项目的目标是把一个编码 Agent 的关键边界做成可阅读、可测试的最小实现：模型循环、
受限工具、一次性确认、会话和项目记忆、计划模式、技能、只读子代理、任务图、
Worktree 与本地 MCP。

详细学习路线见 [学习计划.md](./学习计划.md)，逐阶段记录见
[learning-log.md](./learning-log.md)，架构说明见
[docs/architecture.md](./docs/architecture.md)。

## 快速开始

已在 Python 3.12.13 验证。项目元数据允许 Python 3.12 的其他补丁版本，但不支持
Python 3.13+；这是当前依赖与测试矩阵的范围，不是 Python 3.12.13 的限制。

```bash
git clone https://github.com/Asaakii/Build-my-own-claude-code-cli.git
cd Build-my-own-claude-code-cli
python3.12 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"

# 不需要密钥、不联网的演示
.venv/bin/agent-code run "请使用 echo 工具回答：你好"
.venv/bin/agent-code repl --provider demo
```

安装并配置真实模型后，直接运行 `agent-code` 即进入前台 DeepSeek 对话，行为类似
`claude`：按 `Ctrl+C`、`/exit` 或 `/quit` 即退出，不会留在后台。需要不联网演示时用
`agent-code repl --provider demo`。在 REPL 中先输入 `/help` 查看命令；默认启用
Plan Mode，输入 `/plan off` 只能退出只读探索，不能绕过文件编辑和 Shell 的确认边界。
REPL 使用终端行编辑：上、下方向键浏览本次启动后的输入历史，左、右方向键移动光标。
真实 Provider 的普通文本会逐段显示，最终回答使用终端 Markdown 渲染（例如 `**粗体**`、
标题、列表和代码块不会原样显示标记）。工具调用仍会等模型完整返回参数后才执行。

## 真实模型配置

当前 `anthropic` Provider 使用 Anthropic Messages API 及其兼容端点。复制
`.env.example` 后，把变量安全地导入当前终端环境，再运行：

```bash
export ANTHROPIC_API_KEY='只在本机终端设置'
export AGENT_CODE_MODEL='模型标识'
export ANTHROPIC_BASE_URL='可选的兼容端点'
.venv/bin/agent-code status
.venv/bin/agent-code run --provider anthropic "用一句话介绍自己"

# 显式运行一次只含 echo 工具的受控真实模型验收
.venv/bin/agent-code smoke
```

程序会以受限文本解析方式自动读取当前工作区 `.env`；它不会执行其中的 Shell 内容，
而且终端中显式设置的变量优先。`.env` 绝不能提交。并非所有“OpenAI 兼容”服务都
兼容 Anthropic Messages API；若服务仅提供 OpenAI 协议，不能只改 Base URL 就假定可用，
需要另写 Provider 适配层。

## Telegram 私聊渠道

本项目支持受限的 Telegram long polling。`.env` 中必须配置
`TELEGRAM_BOT_TOKEN` 与 `TELEGRAM_ALLOWED_USER_ID`；后者是唯一允许使用 Bot 的
Telegram 用户 ID。不要将这些值提交到 Git。

```bash
# 验证 Token，不发送消息也不启动轮询
.venv/bin/agent-code telegram status

# 持续运行 Bot；按 Ctrl+C 停止（不会自动常驻）
.venv/bin/agent-code telegram run
```

Bot 只处理白名单用户的私聊文本，忽略群组、媒体和其他用户。每位白名单用户的对话
保存在本地 `.agent-code/sessions/telegram-<用户ID>.jsonl`。外部渠道始终启用
Plan Mode：读取、搜索和问答可用；文件编辑、命令执行、确认 ID、`/plan off` 等操作
不能通过 Telegram 绕过本地终端的确认流程。

Telegram Bot 目前在模型完整回答后才发送一条消息，不支持逐段刷新；这是该渠道的现有
交付方式，和本地 CLI 的流式终端体验不同。

身份问题由程序给出固定事实回答：这是用户开发的 `agent-code` Bot，底层使用
DeepSeek；`Anthropic` 仅指 Messages API 兼容协议，不能被误解为模型身份或开发者。

## 功能与安全边界

- 文件读取、目录列举、glob 与文本搜索被限制在当前工作区。
- 文件创建和替换先生成预览；仅用户用一次性确认 ID 批准后才会写入。
- Shell 默认只自动运行少量只读命令；删除、提权、联网、管道/重定向、工作区外路径
  一律拒绝。`touch`、`mkdir` 等写入仍必须单次确认。
- 会话、Todo、任务图和项目记忆保存在被 Git 忽略的 `.agent-code/` 中；会话写入会
  脱敏，工具完整输出不会持久化到会话历史。
- Plan Mode 默认拦截文件写入和 Shell 工具。关闭它不会提升其他权限。
- Skills 只在显式 `/skill load <ID>` 后读取正文；子代理无工具且只能做只读研究。
- Worktree 创建、合并和清理均需要明确命令与确认标志，不会自动提交或推送。
- MCP 第一版只支持本地 stdio。发现到 MCP 工具不等于可执行：外部工具默认需显式
  确认，schema 按需加载，输出有大小上限。
- Telegram 仅为白名单私聊提供只读问答，且会保存脱敏会话；运行进程本身需要保持
  在本机终端中，停止进程后 Bot 不再响应。

更完整的安全回归项见 [docs/security-checklist.md](./docs/security-checklist.md)。

## 常用命令

```text
/status                       当前 Provider、会话、Plan Mode 与 Todo 汇总
/plan | /plan add <步骤>      查看/补充结构化计划
/plan off                     明确退出当前会话的只读计划模式
/todo | /todo add <内容>      管理持久化 Todo
/memory add <约定>            保存可审阅的项目长期约定
/skills | /skill load <ID>    按需加载项目技能
/task | /task dispatch        查看/分派受限只读任务
/worktree create <任务ID>     创建隔离 Git Worktree
/permissions                  查看 Shell 安全边界
/audit                        查看本会话最小审计
/exit                         退出
```

完整的 REPL 帮助以运行时 `/help` 输出为准。

`agent-code smoke` 不会使用文件或 Shell 工具，只要求模型调用 `echo` 并返回
`SMOKE_OK`；它是有配置时的真实 Provider 验收命令，可能产生一次模型请求费用。

### 复用 HermesLite 的 DeepSeek 配置

HermesLite 的 `LLM_API_KEY` 和 `LLM_MODEL` 可以复用，但它的
`LLM_BASE_URL=https://api.deepseek.com` 是 OpenAI 兼容地址，不能原样传给本项目。
本项目需使用 DeepSeek 的 Anthropic 兼容地址：
`https://api.deepseek.com/anthropic`。本次项目验收已用该映射成功完成一次受控工具调用。
不要复制或提交密钥；仅在当前终端临时映射变量后运行 `agent-code smoke`。

## 验证与打包

```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m pytest
.venv/bin/python -m build
```

构建完成后，可以在新的 Python 3.12 虚拟环境中安装生成的 wheel，运行
`agent-code --help` 与无密钥的 Mock 演示。构建/安装不应把 `.env`、`.agent-code/`
或私有复盘带入发行物。

## 已知限制与下一步

- 没有无限 `/loop`：刻意避免缺少停止/预算控制的后台循环。
- REPL 是基础终端交互，不提供复杂的全屏编辑或跨进程取消。
- 真实模型只支持 Anthropic Messages API 兼容端点；未实现 OpenAI Provider、重试、
  多模型路由或自动成本控制。
- MCP 不含 OAuth、远程服务发现、云连接器、组织级策略或运行时注册表。
- 子代理只能做无工具的只读研究；任务图不并行执行写任务。
- Worktree 不自动生成提交、执行合并后的推送或替用户处理冲突。

这些限制是有意保留的学习边界，下一版优先考虑 Provider 抽象扩展、可审计的 MCP
服务器注册、可取消的流式交互与更全面的端到端测试。
