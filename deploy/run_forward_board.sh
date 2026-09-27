#!/bin/bash
# 候选前向板的日读数（操作者 2026-09-17 裁定 Q-C = 建）。
#
# 它跑的是 `research forward status`，而那条命令**不写 ledger**。这不是「顺便也没写」，是这块东西
# 的设计：上板时把假设钉死并计一笔，此后每天重算的是同一个假设在多出来的数据上的读数，不是一次
# 新的选择。板的门按 `forward_board` 桶里的行数算——所以日任务若误计一笔，不是记错一个数，是把
# 整块板的判定年限一起往后推，而且以一天一次的速度累积。
# `tests/cli/test_the_board_charges_on_entry_and_never_on_a_read.py` 把这条钉住。
#
# 排在数据同步（01:20）之后：板读的是 store，store 空一天，读数就少一天。
#
# 读数写进 `reports/forward-board/`，**不是** `reports/research/`：后者放的是计过费的证据，
# 而板读数是可从板与数据完全复现的派生物，这个任务每天写一份。混在一起，一年 365 个未跟踪
# 文件会把 `git status` 淹掉，掩盖真正的新证据。目录由命令的默认值决定，这里不传 `--out`。
#
# 正常输出是一整版 OBSERVING、`decidable: 0`。按方案的定价，板上 30 个候选要约 3.8 年才谈得上判，
# 所以这个任务在头几年不会有任何「结果」——它在攒的是那几年本身。
#
# 安装（操作者动作）：
#   cp deploy/com.starquant.forward-board.plist ~/Library/LaunchAgents/
#   launchctl load -w ~/Library/LaunchAgents/com.starquant.forward-board.plist
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUPPORT="$HOME/Library/Application Support/starquant"
if [ -f "$SUPPORT/env.sh" ]; then
  # shellcheck disable=SC1091
  source "$SUPPORT/env.sh"
elif [ -f "$HOME/.zshrc" ]; then
  eval "$(grep -E '^export STARQUANT_[A-Z0-9_]+=' "$HOME/.zshrc" || true)"
fi
cd "$REPO" || exit 78
stamp() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }

BOARD="${STARQUANT_FORWARD_BOARD:-reports/research/forward_board.jsonl}"
if [ ! -s "$BOARD" ]; then
  echo "[$(stamp)] 板是空的（$BOARD）——没有候选要读。用 \`research forward add\` 放第一个上去。"
  exit 0
fi

# 显式传 `--board`，不靠命令的默认值：这个任务跑在无人看管的环境里，而「默认值改了没人发现」
# 正是这个仓库付过两次学费的那种错误。
if output="$("$REPO/.venv/bin/starquant" research forward status --board "$BOARD" 2>&1)"; then
  echo "[$(stamp)] ok"
  echo "$output" | sed "s/^/           /"
else
  echo "[$(stamp)] FAIL forward-board"
  echo "$output" | tail -n 20 | sed "s/^/           /"
  exit 1
fi
