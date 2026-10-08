"""The secret scan must load and catch random forged Binance credential shapes."""
from __future__ import annotations

import json
import random
import shutil
import string
import subprocess
import tempfile
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".gitleaks.toml"
pytestmark = pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks is installed by CI's Secrets step")


def _forged_binance_credential() -> str:
    lower = [random.choice(string.ascii_lowercase) for _ in range(28)]
    upper = [random.choice(string.ascii_uppercase) for _ in range(26)]
    digits = [random.choice(string.digits) for _ in range(10)]
    chars = lower + upper + digits
    random.shuffle(chars)
    forged = "".join(chars)
    assert len(forged) == 64
    return forged


def _scan(contents: dict[str, str]) -> list[dict]:
    with tempfile.TemporaryDirectory() as tmp:
        for name, text in contents.items():
            (Path(tmp) / name).write_text(text, encoding="utf-8")
        report = Path(tmp) / "_report.json"
        proc = subprocess.run(
            [
                "gitleaks",
                "detect",
                "--source",
                tmp,
                "--config",
                str(CONFIG),
                "--no-git",
                "--no-banner",
                "--report-format",
                "json",
                "--report-path",
                str(report),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        # returncode 1 = 有命中，0 = 干净。其它值意味着 gitleaks 自己出了问题
        # （配置加载失败会是 2 或者一个 panic），那必须炸出来而不是当成「没命中」。
        assert proc.returncode in (0, 1), (
            f"gitleaks 没能正常跑完（returncode={proc.returncode}）。\n"
            f"这通常意味着 .gitleaks.toml 加载失败——RE2 不支持 lookahead，\n"
            f"写了 (?=...) 会让它 panic 而不是报错。\n"
            f"stderr:\n{proc.stderr[:2000]}"
        )
        if not report.exists():
            return []
        return json.loads(report.read_text(encoding="utf-8") or "[]")


def test_the_config_loads_at_all() -> None:
    assert CONFIG.exists(), f"{CONFIG} 不在了——CI 的 Secrets 门会连着一起哑掉"
    findings = _scan({"ordinary.py": "x = 1\n"})
    assert findings == [], f"一个只写了 x = 1 的文件不该有命中：{findings}"


def test_a_forged_credential_is_caught() -> None:
    forged = _forged_binance_credential()
    findings = _scan({"leak.py": f'STARQUANT_BINANCE_API_KEY = "{forged}"\n'})
    assert findings, (
        "伪造的 Binance 凭据形态没有被拦下。\n.gitleaks.toml 的 allowlist 被放得太宽，密钥扫描已经失去意义。"
    )


def test_a_credential_with_no_assignment_context_is_caught() -> None:
    forged = _forged_binance_credential()
    findings = _scan({"note.md": f"循环昨天报错，日志里那行是：\n{forged}\n应该是权限问题。\n"})
    assert findings, (
        "没有赋值上下文的裸凭据没有被拦下。\n"
        "内置规则靠 `key =` 触发，自定义规则 `starquant-binance-credential-shape` "
        "就是为这个形态加的——检查它是不是被删掉或改窄了。"
    )


def test_ci_scans_full_history_not_a_shallow_checkout() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "gitleaks" in ci, "CI 里没有 Secrets 门了"
    assert "fetch-depth: 0" in ci, (
        "CI 的 checkout 没有 `fetch-depth: 0`。浅检出上的历史扫描会空跑通过，"
        "这是最难发现的一种失败：它长得和平安一模一样。"
    )
