# codex-next-step-hooks

[English](README.md) | [한국어](README.ko.md) | **日本語** | [简体中文](README.zh-CN.md)

翻訳版は英語版より更新が遅れることがあります。

会話を締めるときに、適切な形で終わるように支援する Codex hook 集です。
そのまま終えるか、同じターンで自動的に続けるか、短いフォローアップ質問を
1 回だけ出すかを判断します。

## できること

このパッケージは 2 つの managed Codex hook をインストールします。

- 起動時と resume 時に next-step policy を読み込む `SessionStart` hook
- closeout を通常終了するか、同じターンで自動継続するか、短いフォローアップ質問を出すか決める `Stop` hook

judge モデルは最近の会話コンテキストを見て `end` / `auto_continue` /
`ask_user` モードを選びます。`ask_user` が必要な場合は、Codex が現在の
セッション文脈に合わせて実際のフォローアップ質問と選択肢を生成します。

これらの hook は `~/.codex/hooks.json` に additive にマージされ、
`uninstall` はこのパッケージが管理する項目だけを削除します。

## 含まれるもの

- パッケージ化された `Stop` / `SessionStart` hook スクリプト
- `hooks.json` 用の additive `install` / `uninstall`
- ローカルパッケージ状態を確認する `doctor`
- judge endpoint に実際の structured probe を送る `doctor --live-judge`
- follow-up decision 回帰のための deterministic self-test
- runtime と endpoint の構成を説明する contract ドキュメント
- judge mode と短い rationale を記録する transcript debug event

## 現在の機能

- Codex `Stop` hook 向けの context-aware `end` / `auto_continue` / `ask_user` ロジック
- assistant の返答自体が follow-up choice や明確な next step を示したときに `end` を防ぐ override guard
- `SessionStart` hook による起動時 policy 読み込み
- Python interpreter と repo root を反映する template rendering
- ask-user / auto-continue / end 挙動に対する synthetic regression coverage
- ローカル環境向けの install と runtime verification コマンド

## 構成

```text
codex-next-step-hooks/
├─ README.md
├─ README.ko.md
├─ README.ja.md
├─ README.zh-CN.md
├─ LICENSE
├─ pyproject.toml
├─ docs/
│  └─ runtime-contract.md
├─ src/
│  └─ codex_next_step_hooks/
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

## クイックスタート

```bash
cd /path/to/codex-next-step-hooks
PYTHONPATH=src python3 -m codex_next_step_hooks.cli install --dry-run --json
PYTHONPATH=src python3 -m codex_next_step_hooks.cli doctor --json
PYTHONPATH=src python3 -m codex_next_step_hooks.cli doctor --live-judge --json
PYTHONPATH=src python3 -m codex_next_step_hooks.cli self-test --json
```

## インストール

まず変更内容をプレビューします。

```bash
cd /path/to/codex-next-step-hooks
PYTHONPATH=src python3 -m codex_next_step_hooks.cli install --dry-run --json
```

実際に適用します。

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli install --json
```

`install` が行うこと:

- 現在の Python interpreter パスで hook template をレンダリング
- 現在の repo root を managed hook command に埋め込む
- managed handler を `~/.codex/hooks.json` にマージする
- ファイルが変わる場合は書き込み前に backup を作成する

## 検証

静的チェック:

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli doctor --json
```

live judge probe:

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli doctor --live-judge --json
```

deterministic regression suite:

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli self-test --json
```

## アンインストール

まず削除内容をプレビューします。

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli uninstall --dry-run --json
```

managed handler を削除します。

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli uninstall --json
```

`uninstall` はこのパッケージが管理する項目だけを削除し、無関係な hook
設定はそのまま残します。

## CLI コマンド

- `install`: hook template をレンダリングし、managed handler を `hooks.json` にマージ
- `uninstall`: 無関係な hook 設定を残したまま managed 項目だけ削除
- `doctor`: 静的ファイルとパッケージ状態を確認
- `doctor --live-judge`: judge endpoint に structured request を送り実際の応答を確認
- `self-test`: deterministic synthetic regression suite を実行

## ランタイム設定

- judge backend と環境変数: `docs/runtime-contract.md`

## 管理される hook エントリ

managed template は次のイベントごとに 1 つずつ handler を追加します。

- `SessionStart` with matcher `startup|resume`
- `Stop`

各 command は次のスクリプトを指します。

- `src/codex_next_step_hooks/hooks/session_start_request_user_input_policy.py`
- `src/codex_next_step_hooks/hooks/stop_require_request_user_input.py`

## 今後の改善候補

- repo 移動や interpreter 名変更時の uninstall 強化
- 既存ユーザー設定の edge case に対する installer safety check の拡充
- 必要に応じた `doctor --live-judge` の失敗ヒント強化
- 公開向けサンプルと regression case の追加
