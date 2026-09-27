"""密钥扫描这道门必须是活的，而不只是配置文件存在。

2026-09-19 发现本仓库**从 2026-08-05 创建起就是公开的**，而仓库文档里一直写着
「本仓库是 Free plan 的 private repo」。认知差持续了 45 天。当天做了全历史扫描，结论
是干净的：1,637 个 commit、72 MB、所有凭据形态零命中，凭据设计本身也是对的（从
`env.sh` / `~/.zshrc` 读，代码与 plist 里都没有值）。

于是这个文件的职责不是「找密钥」——CI 的 Secrets 门每次跑都在找。它守的是**扫描本身
还有没有用**，因为这道门有两种坏法，而且都不会自己喊出来：

  1. **配置崩了，扫描根本没跑。**  建这道门的当天就撞上了：`.gitleaks.toml` 第一版用
     `(?=.*[A-Z])(?=.*[a-z])` 表达「大小写混排」，而 gitleaks 用 Go 的 RE2，**不支持
     lookahead**。它不是报一个配置错误，是带栈回溯地 panic。在 CI 里这会红，能看见；
     但在 pre-commit hook 里 `2>/dev/null` 一挡，就成了「扫描通过」。

  2. **allowlist 被放宽到什么都抓不住。**  这道门上线时压掉了 117 处误报（全部核实过：
     100 处是 trial ledger 的 `param_key`、9 处是 sha256 文件摘要、2 处是 SSH 公钥指纹、
     其余是测试里写死的假值）。压误报是必要的——117 个红的检查等于没有检查，人看三次
     就开始无视它。但每压一条，抓真密钥的能力就少一点。下面 `test_a_forged_credential_is_caught`
     就是这件事的刹车：allowlist 再怎么加，一个伪造的 Binance 形态必须还能被抓出来。

测试用的「密钥」全部是当场随机生成的假值，不落在仓库里，也从未对应任何账户。
"""

from __future__ import annotations

import json
import random
import shutil
import string
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / ".gitleaks.toml"

pytestmark = pytest.mark.skipif(
    shutil.which("gitleaks") is None,
    reason="本地没装 gitleaks（brew install gitleaks）；CI 的 Secrets 门有独立的一份",
)


def _forged_binance_credential() -> str:
    """造一个 Binance API key/secret 的形态：64 位，大小写字母与数字混排。

    随机生成而不是写死一个常量：写死的那个会被将来某次 allowlist 调整按值放行掉
    （这正是本仓库放行 `sk-1234567890abcdef` 的方式），于是测试继续绿，而真密钥
    不再被拦。每次跑都换一个值，就没有「按值放行」这条捷径。
    """
    lower = [random.choice(string.ascii_lowercase) for _ in range(28)]
    upper = [random.choice(string.ascii_uppercase) for _ in range(26)]
    digits = [random.choice(string.digits) for _ in range(10)]
    chars = lower + upper + digits
    random.shuffle(chars)
    forged = "".join(chars)
    assert len(forged) == 64
    return forged


def _scan(contents: dict[str, str]) -> list[dict]:
    """把给定内容写进一个临时目录，用仓库的配置扫它，返回命中列表。"""
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
    """配置能被 gitleaks 加载。抓的是 RE2 那个坑：panic 不是报错，容易被当成通过。"""
    assert CONFIG.exists(), f"{CONFIG} 不在了——CI 的 Secrets 门会连着一起哑掉"
    findings = _scan({"ordinary.py": "x = 1\n"})
    assert findings == [], f"一个只写了 x = 1 的文件不该有命中：{findings}"


def test_a_forged_credential_is_caught() -> None:
    """伪造的 Binance 形态必须被抓到——这是 allowlist 的刹车。

    这条红了，说明 allowlist 已经宽到扫描失去意义。修法不是改这个测试，
    是回头看最近一次往 `.gitleaks.toml` 加了什么。
    """
    forged = _forged_binance_credential()
    findings = _scan({"leak.py": f'STARQUANT_BINANCE_API_KEY = "{forged}"\n'})
    assert findings, (
        "伪造的 Binance 凭据形态没有被拦下。\n.gitleaks.toml 的 allowlist 被放得太宽，密钥扫描已经失去意义。"
    )


def test_a_credential_with_no_assignment_context_is_caught() -> None:
    """裸串也要抓到，不能只在 `KEY = "..."` 这种上下文里才响。

    这正是 `starquant-binance-credential-shape` 那条自定义规则存在的理由：内置的
    `generic-api-key` 靠赋值上下文触发，而泄漏最常见的形态是一行裸串——粘进
    注释、贴进报告、抄进 RESEARCH_LOG 的一段日志。
    """
    forged = _forged_binance_credential()
    findings = _scan({"note.md": f"循环昨天报错，日志里那行是：\n{forged}\n应该是权限问题。\n"})
    assert findings, (
        "没有赋值上下文的裸凭据没有被拦下。\n"
        "内置规则靠 `key =` 触发，自定义规则 `starquant-binance-credential-shape` "
        "就是为这个形态加的——检查它是不是被删掉或改窄了。"
    )


@pytest.mark.parametrize(
    ("name", "text"),
    [
        # 本仓库满地都是的哈希形态。任何一条误报，基线就不是零，
        # 而不是零基线的检查三天之内就会被忽略。
        ("digest.json", '{"api.py": "4c4148b58b39095d1a004b3e9af4c3715b7448765850d7140572b6805f9bb735"}\n'),
        ("trials.jsonl", '{"param_key": "207ad3fb54979ace", "trial": 1}\n'),
        ("objectid.txt", "9ca85c6900000000000000000000000000000000\n"),
    ],
)
def test_repository_hash_shapes_do_not_false_positive(name: str, text: str) -> None:
    """摘要、指纹、object id 不该报。它们是单一字符集的 hex，不可能是 Binance 凭据。"""
    findings = _scan({name: text})
    assert findings == [], f"{name} 的哈希形态被误报成密钥：{findings}\n基线必须是零，否则这道门会被当成噪声忽略掉。"


@pytest.mark.parametrize("name", ["pre-commit", "pre-push"])
def test_the_local_hooks_are_present_and_executable(name: str) -> None:
    """本地两层拦截都在仓库里，而且是可执行的。

    不可执行时 git 会**静默跳过** hook——不报错，不提示，看起来和「扫描通过」
    一模一样。

    这两层比一般项目重要：见 `test_the_docs_record_that_github_cannot_catch_binance_keys`，
    服务端那层接不住 Binance 的密钥，所以本机这两个是它进入公开仓库前仅有的拦截。
    """
    hook = ROOT / ".githooks" / name
    assert hook.exists(), f"`.githooks/{name}` 不在了，本地少了一层"
    assert hook.stat().st_mode & 0o111, (
        f"`.githooks/{name}` 没有可执行位。git 会静默跳过它，"
        f"看起来与「扫描通过」无法区分。修：chmod +x .githooks/{name}"
    )


def test_the_docs_record_that_github_cannot_catch_binance_keys() -> None:
    """这个限制必须留在文档里，因为它反直觉且代价很高。

    2026-09-19 核实：Binance **不在** GitHub secret scanning 的 partner pattern
    列表里，而 custom patterns 要求仓库属于组织并启用付费的 Secret Protection。
    个人账户下的公开仓库两条都不满足。

    为什么给一句文档写测试：这条限制不写出来，读者的默认假设恰好是相反的
    （「开了 push protection 就有人兜底了」），而那个假设会直接导出
    「`--no-verify` 一下没关系」。它在任何一次文档重写里都可能被当成啰嗦删掉。
    """
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    assert "partner pattern" in security, (
        "SECURITY.md 不再说明 GitHub 的 push protection 认不出 Binance 密钥。\n"
        "这条删不得：少了它，读者会以为服务端有人兜底，而实际上 Binance 密钥\n"
        "进入公开仓库之前只有本机那两个 hook 拦得住。"
    )


def test_ci_scans_full_history_not_a_shallow_checkout() -> None:
    """CI 的 Secrets 门要有完整历史才有意义。

    `actions/checkout` 默认只取一个 commit。在浅检出上跑历史扫描会安静地通过，
    而密钥进了历史之后，把文件删掉并不会让它从公开仓库里消失。
    """
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "gitleaks" in ci, "CI 里没有 Secrets 门了"
    assert "fetch-depth: 0" in ci, (
        "CI 的 checkout 没有 `fetch-depth: 0`。浅检出上的历史扫描会空跑通过，"
        "这是最难发现的一种失败：它长得和平安一模一样。"
    )
