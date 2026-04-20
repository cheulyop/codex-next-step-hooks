# codex-click-chooser-hooks

[English](README.md) | [한국어](README.ko.md) | [日本語](README.ja.md) | **简体中文**

翻译版本可能会比英文原版更新得慢。

这是一组帮助 Codex 以合适方式结束一轮对话的 hook。它会判断应该直接结束、
在同一轮里自动继续，还是再问一个简短的后续问题。

## 它做什么

这个包会安装两个受管理的 Codex hook。

- 在启动和 resume 时加载 chooser policy 的 `SessionStart` hook
- 决定 closeout 是正常结束、在同一轮自动继续，还是显示一个简短 follow-up chooser 的 `Stop` hook

judge 模型会根据最近的对话上下文选择 `end` / `auto_continue` /
`ask_user` 模式。当需要 `ask_user` 时，Codex 会根据当前会话上下文生成
实际的 chooser 问题和选项。

这些 hook 会以 additive 方式合并到 `~/.codex/hooks.json` 中，`uninstall`
只会移除由这个包管理的条目。

## 包含内容

- 打包好的 `Stop` / `SessionStart` hook 脚本
- 面向 `hooks.json` 的 additive `install` / `uninstall`
- 用于检查本地包状态的 `doctor`
- 向 judge endpoint 发送真实 structured probe 的 `doctor --live-judge`
- 用于 follow-up decision 回归的 deterministic self-test
- 说明运行时与 endpoint 配置的 contract 文档
- 记录 judge mode 和简短 rationale 的 transcript debug event

## 当前能力

- 面向 Codex `Stop` hook 的 context-aware `end` / `auto_continue` / `ask_user` 逻辑
- 当 assistant 回复本身已经给出 follow-up choice 或明确 next step 时阻止 `end` 的 override guard
- 通过 `SessionStart` hook 在启动时加载 policy
- 根据 Python 解释器和 repo root 渲染模板命令
- 针对 ask-user、auto-continue、end 行为的 synthetic regression coverage
- 面向本地环境的安装与运行时验证命令

## 目录结构

```text
codex-click-chooser-hooks/
├─ README.md
├─ README.ko.md
├─ README.ja.md
├─ README.zh-CN.md
├─ LICENSE
├─ pyproject.toml
├─ docs/
│  └─ runtime-contract.md
├─ src/
│  └─ codex_click_chooser_hooks/
│     ├─ __init__.py
│     ├─ cli.py
│     ├─ doctor.py
│     ├─ install.py
│     ├─ uninstall.py
│     ├─ merge.py
│     ├─ runtime_paths.py
│     ├─ selftest.py
│     ├─ hooks/
│     │  ├─ session_start_request_user_input_policy.py
│     │  └─ stop_require_request_user_input.py
│     └─ templates/
│        └─ hooks.json
└─ tests/
   ├─ *.json
   └─ fixtures/
      └─ *.jsonl
```

## 快速开始

```bash
cd /path/to/codex-click-chooser-hooks
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli install --dry-run --json
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli doctor --json
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli doctor --live-judge --json
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli self-test --json
```

## 安装

先预览变更：

```bash
cd /path/to/codex-click-chooser-hooks
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli install --dry-run --json
```

然后正式应用：

```bash
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli install --json
```

`install` 会做这些事：

- 使用当前 Python 解释器路径渲染 hook 模板
- 把当前 repo root 注入到受管理的 hook command 中
- 将受管理的 handler 合并到 `~/.codex/hooks.json`
- 如果文件发生变化，在写入前先创建备份

## 验证

静态检查：

```bash
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli doctor --json
```

live judge probe：

```bash
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli doctor --live-judge --json
```

deterministic regression suite：

```bash
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli self-test --json
```

## 卸载

先预览移除结果：

```bash
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli uninstall --dry-run --json
```

移除受管理的 handler：

```bash
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli uninstall --json
```

`uninstall` 只会移除由这个包管理的条目，不会影响无关的 hook 配置。

## CLI 命令

- `install`: 渲染 hook 模板，并把受管理的 handler 合并到 `hooks.json`
- `uninstall`: 仅移除受管理条目，保留无关 hook 配置
- `doctor`: 检查静态文件和包状态
- `doctor --live-judge`: 向 judge endpoint 发送 structured request 并检查真实响应
- `self-test`: 运行 deterministic synthetic regression suite

## 运行时配置

- judge backend 和环境变量：`docs/runtime-contract.md`

## 受管理的 hook 条目

受管理的模板会在以下事件下各添加一个 handler：

- `SessionStart` with matcher `startup|resume`
- `Stop`

对应的 command 指向：

- `src/codex_click_chooser_hooks/hooks/session_start_request_user_input_policy.py`
- `src/codex_click_chooser_hooks/hooks/stop_require_request_user_input.py`

## 后续可改进方向

- 加强 repo 移动或解释器名称变化时的 uninstall 覆盖
- 扩展 installer 对现有用户配置 edge case 的 safety check
- 在需要时增强 `doctor --live-judge` 的失败提示
- 增加更多适合公开发布的示例和 regression case
