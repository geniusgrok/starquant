#!/bin/bash
# family gate 的日读数：R0 按今天的 ledger 桶大小重算（§3 给 `probe -> main` 的第三个条件）。
#
# **为什么它要是一个 job。** 机制 2026-09-09 就齐了：`starquant_governance/family_gate.py` 会算，
# `lifecycle.py` 有 `FAMILY_GATE_FAILED` 分支，`governance gate --check` 是现成的命令。
# （那个分支原本是 `-> retired`；2026-09-23 操作者裁定改为 main 降回 probe、probe 不动。）缺的只有调用者——七个 plist 里没有它，所以这个读数只在有人手敲命令时才存在。
# 这正是 `run_check.sh` 里那段「a file in deploy/ is not a job」记下的同一种错误，它是 2026-09-17
# forward-board 发出去却没人装换来的。写下来的规则没有闹钟，就只是一段散文。
#
# **它测的是什么，不测什么。** 门是 `max_sharpe_quantile(N, variance, alpha)`，重算把证据整个钉住、
# 只动 N（ledger 桶是 append-only，别人每搜一次它就涨）。所以读数的任何移动都只能归给分母。
# 它**不是**重跑 validate：重跑会同时动数据窗口，那是两个变量，答案不可归因。
# 2026-09-19 两种口径的差别就是这个：重算说 PASS，而同一构造延到 09-18 重跑的报告是 FAIL。
#
# **今天的基线（2026-09-19，写下来好让后面的人看出趋势）：**
#   PASS       tsmom   OOS 1.5919 vs 1.5761 at N=305（上线时是 1.5493 at N=242）
#   UNREADABLE flow    报告没有 `oos_selection` 块
# headroom 从上线时的 +0.0426 缩到 +0.0158，缩了 63%，N 从 242 涨到 305。门按 sqrt(2 ln N) 涨，
# 会饱和——incumbent 活下来靠的就是这个——但薄着上线的策略不会靠站着不动保住余量。
# **这个 job 存在的理由就是这条曲线：它在缩，而在此之前没有任何东西定期量它。**
#
# **它有写副作用，措辞上不要说成只读。** 每个 PASS/FAIL 会往 `governance/verdicts.jsonl` 追一行，
# 这是要的——判了而不留痕的门没人能审。幂等键是 `(gate, subject, call, reasons)`，reasons 带数字，
# 所以 N 没动时重复跑不会进 M-G05 的分母，N 动了就该是一条新 ruling。命令自己的 docstring 里有
# 2026-09-14 那次「拿它当 read-only 跑、结果追了一行」的更正，别再把它读成只读。
#
# **它改不了任何 book。** 这里只交读数：它写下的 `refuse` 行由 `governance advance` 经
# `family_gate.refusals` 折进状态机（main 降回 probe）。`advance` 没有排进任何 job，要人跑 `--commit`。
#
# 排在 forward-board（02:00）之后：两个都读 `reports/research/`，错开好让日志分得清是谁。
#
# 安装（操作者动作）：
#   cp deploy/com.starquant.governance-gate.plist ~/Library/LaunchAgents/
#   launchctl load -w ~/Library/LaunchAgents/com.starquant.governance-gate.plist
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

# 与 run_check.sh 同一个 notify：一份「这家 provider 读哪种 shape」和「消息到底发出去没有」的实现。
# 那里记着代价——手搓的第三份曾经对 Lark 发 Slack 的扁平 {"text": ...}，HTTP 200、消息被丢、
# `curl -f` 还成功，于是告警路径整条静默。
# 两个通道都发，URL 走环境变量不走 argv——理由与 2026-09-25 的改动都记在 run_check.sh 的 notify 上方。
notify() {
  echo "[$(stamp)] FAIL governance-gate: $1"
  if [ -n "${STARQUANT_ALERTS_WEBHOOK_URL:-}${STARQUANT_ALERTS_WEBHOOK_URL_2:-}" ]; then
    STARQUANT_ALERTS_WEBHOOK_URL="${STARQUANT_ALERTS_WEBHOOK_URL:-}" STARQUANT_ALERTS_WEBHOOK_URL_2="${STARQUANT_ALERTS_WEBHOOK_URL_2:-}" \
      "$REPO/.venv/bin/python" -c '
import asyncio, os, sys
from pathlib import Path
from starquant_live.alerts import WebhookAlerts
alerts = WebhookAlerts(
    os.environ["STARQUANT_ALERTS_WEBHOOK_URL"],
    secondary_url=os.environ["STARQUANT_ALERTS_WEBHOOK_URL_2"],
    state_path=Path(sys.argv[3]),
)
sys.exit(0 if asyncio.run(alerts.send(sys.argv[1], key=sys.argv[2])) else 1)
' "StarQuant family gate 失败：$1" "governance-gate" "$SUPPORT/alert-dedup.json" \
      || echo "[$(stamp)] webhook did NOT deliver the line above (or it was a duplicate inside the window)"
  fi
}

# `--check` 只在 FAIL 时非零；UNREADABLE 不进它的判据，理由见下。
output="$("$REPO/.venv/bin/starquant" governance gate --check 2>&1)"
rc=$?
echo "$output" | sed "s/^/           /"
if [ "$rc" -ne 0 ]; then
  # 先取 FAIL 行；取不到就用输出尾部，**不能让告警内容为空**。非零有两种来源——门判了 FAIL，
  # 和命令根本没跑起来（.venv 没了、导入炸了）——后者不会印出 `FAIL` 开头的行，而它恰恰是更要紧的
  # 那种。按「grep 到什么发什么」写，第二种会发出一条正文为空的告警，等于告诉操作者「有事」却不说
  # 是什么事。这和 run_check.sh 记下的那次 Lark 静默是同一族：路径通了，内容没到。
  detail="$(echo "$output" | grep '^FAIL' | tr '\n' ' ')"
  [ -n "$detail" ] || detail="$(echo "$output" | tail -n 3 | tr '\n' ' ')"
  [ -n "$detail" ] || detail="`governance gate --check` 退出码 $rc，且没有任何输出"
  notify "$detail"
  exit 1
fi
echo "[$(stamp)] ok   governance-gate"

# UNREADABLE 报告但不 gate，而这条区分是 `family_gate.py` 自己下的：「门没有判，是它没能问」。
# 把「读不了证据」记成 REFUSE，等于往一个关于判断的分母里塞一条关于可读性的记录。
# 它仍然需要操作者动作（flow 今天就是：报告没有 `oos_selection` 块），所以要看得见——
# 但它不是「这策略该退休了」，按 FAIL 告警会教会操作者忽略这个告警。
if echo "$output" | grep -q '^UNREADABLE'; then
  echo "[$(stamp)] 有证据读不出来，需要操作者处理（不 gate，因为「没判」不是「判了不过」）："
  echo "$output" | grep '^UNREADABLE' | sed "s/^/           /"
fi
exit 0
