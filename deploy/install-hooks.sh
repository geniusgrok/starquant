#!/bin/bash
# StarQuant — 安装本地 git hooks
#
#   bash deploy/install-hooks.sh
#
# 每个新 clone 跑一次。`git worktree` 不用再跑——`core.hooksPath` 是仓库级配置，
# worktree 共享同一份 `.git/config`。
#
# 为什么不用 `cp .githooks/* .git/hooks/`：那是复制，会漂。改了 `.githooks/pre-commit`
# 之后没人会想起去同步那份副本，于是本地跑的是三个月前的旧 hook 而看起来一切正常。
# `core.hooksPath` 是指向，不是副本。

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

git config core.hooksPath .githooks
chmod +x .githooks/* 2>/dev/null || true

echo "hooks 已指向 .githooks/（core.hooksPath）"
echo "  当前值: $(git config core.hooksPath)"
for h in .githooks/*; do
    [ -f "$h" ] || continue
    if [ -x "$h" ]; then
        echo "  ✓ $(basename "$h")"
    else
        echo "  ✗ $(basename "$h") 没有可执行位——git 会静默跳过它"
    fi
done

if command -v gitleaks >/dev/null 2>&1; then
    echo "  gitleaks: $(gitleaks version 2>&1 | head -1)"
else
    echo
    echo "  ⚠  gitleaks 没装，pre-commit 会放行并打一行提示。"
    echo "     装它：brew install gitleaks"
fi

echo
echo "自检（应当拦下一个伪造的凭据形态）:"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
if command -v gitleaks >/dev/null 2>&1; then
    # 造一个 Binance 形态的假值。不用真密钥，也不写进仓库目录。
    python3 - "$tmp" <<'PY'
import random, string, sys, pathlib
random.seed()
a, A, d = string.ascii_lowercase, string.ascii_uppercase, string.digits
v = ([random.choice(a) for _ in range(28)]
     + [random.choice(A) for _ in range(26)]
     + [random.choice(d) for _ in range(10)])
random.shuffle(v)
pathlib.Path(sys.argv[1], "canary.txt").write_text(
    "STARQUANT_BINANCE_API_KEY=%s\n" % "".join(v), encoding="utf-8")
PY
    if gitleaks detect --source "$tmp" --config "$repo_root/.gitleaks.toml" \
            --no-git --redact --no-banner >/dev/null 2>&1; then
        echo "  ✗ 自检失败：伪造的凭据形态没有被拦下。"
        echo "    这说明 .gitleaks.toml 的 allowlist 被放得太宽，扫描已经失去意义。"
        exit 1
    else
        echo "  ✓ 伪造的凭据形态被拦下，扫描是活的。"
    fi
else
    echo "  (跳过：gitleaks 未安装)"
fi
