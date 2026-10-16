# -*- coding: utf-8 -*-
"""发布包扫描:疑似密钥、签名与未脱敏数据库误入检查。

用法:
    python3 tools/demo/scan_release.py [--root .]
    python3 tools/demo/scan_release.py --root web/dist

规则:
- 扫描发布包候选目录(api/、web/dist、demo-data/v1/cases)内的
  文本文件,匹配疑似密钥模式(ak/sk/sn=/signature=/token= 等,大小写不敏感)。
- 检查 .env 文件与未脱敏 SQLite(experiments/*.db、cache/*.db、api/var/*.db)
  是否被误放入发布包候选目录。
- 输出命中文件与行号;无命中 exit 0,有命中 exit 1。
- 只读检查,不打印任何密钥值,只打印文件名、行号与命中的模式名。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# 大小写不敏感的疑似密钥赋值模式。要求 key 后紧跟 = 或 : 且右侧有非空值,
# 避免把普通单词(如 token 变量名)误报;BAIDU_MAP_AK 这类变量名引用不带值,
# 不会命中,只有真正的赋值才命中。
PATTERNS = [
    ("ak_assignment", re.compile(
        r'''(?i)(?<![A-Za-z0-9_])ak\s*[:=]\s*['"]?[A-Za-z0-9]{8,}''')),
    ("sk_assignment", re.compile(
        r'''(?i)(?<![A-Za-z0-9_])sk\s*[:=]\s*['"]?[A-Za-z0-9]{8,}''')),
    ("sn_assignment", re.compile(
        r'''(?i)(?<![A-Za-z0-9_])sn\s*[:=]\s*['"]?[A-Za-z0-9]{8,}''')),
    ("signature_assignment", re.compile(
        r'''(?i)(?<![A-Za-z0-9_])signature\s*[:=]\s*['"]?[A-Za-z0-9]{8,}''')),
    ("sign_param_assignment", re.compile(
        r'''(?i)(?<![A-Za-z0-9_])sign\s*[:=]\s*['"]?[A-Za-z0-9]{16,}''')),
    ("token_assignment", re.compile(
        r'''(?i)(?<![A-Za-z0-9_])token\s*[:=]\s*['"]?[A-Za-z0-9]{16,}''')),
    ("secret_assignment", re.compile(
        r'''(?i)(?<![A-Za-z0-9_])secret\s*[:=]\s*['"]?\S+''')),
    ("password_assignment", re.compile(
        r'''(?i)(?<![A-Za-z0-9_])pass(word|wd)\s*[:=]\s*['"]?\S+''')),
    ("api_key_assignment", re.compile(
        r'''(?i)(?<![A-Za-z0-9_])api[_-]?key\s*[:=]\s*['"]?[A-Za-z0-9]{8,}''')),
    # BAIDU_MAP_AK/SK:只报带真实值的赋值(≥8位字母数字);占位符
    # (.../${VAR}/<key>/空)不命中，${VAR:-} 引用不命中。
    ("baidu_ak_value", re.compile(
        r'''BAIDU_MAP_AK\s*[:=]\s*['"]?[A-Za-z0-9]{8,}''')),
    ("baidu_sk_value", re.compile(
        r'''BAIDU_MAP_SK\s*[:=]\s*['"]?[A-Za-z0-9]{8,}''')),
]

# 文本扫描时跳过的二进制/锁文件后缀。
SKIP_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".woff", ".woff2",
    ".ttf", ".otf", ".eot", ".mp4", ".map",
}

# 单个文件超过此体积跳过内容扫描(只检查文件名)。
MAX_SCAN_BYTES = 2 * 1024 * 1024

# 发布包候选目录。
CANDIDATE_DIRS = ["api", "web/dist", "demo-data/v1/cases"]

# 允许的例外：浏览器端 AK 只经以下受控位置出现（Referer 白名单保护，
# 与 Server AK/SK 分离，绝不互换）。
ALLOWLIST = [
    # 后端读取浏览器端 AK 的环境变量名（无值引用，不命中赋值规则也明确豁免）
    "api/app/config.py",
    # 浏览器端 AK 下发接口（字段名为 ak，值来自环境，非硬编码密钥）
    "api/app/routers/maps.py",
    # 前端读取构建时注入/运行时配置的变量名
    "web/env.d.ts",
    "web/src/stores/maps.ts",
    # 文档与示例（占位符/变量名引用，无真实值）
    "README.md",
    ".env.example",
    "docs/24-code_artifact-UI适配与改造方案.md",
]

# 绝不允许出现在发布包候选目录中的文件(按文件名匹配)。
FORBIDDEN_NAMES = {".env"}

# 未脱敏数据库:这些路径的 .db 文件不得进入发布包候选目录。
FORBIDDEN_DB_PATTERNS = [
    re.compile(r"(^|/)experiments/.*\.db$"),
    re.compile(r"(^|/)cache/.*\.db$"),
    re.compile(r"(^|/)api/var/.*\.db$"),
]


def _is_text(path: Path) -> bool:
    if path.suffix.lower() in SKIP_SUFFIXES:
        return False
    if path.stat().st_size > MAX_SCAN_BYTES:
        return False
    try:
        with path.open("rb") as f:
            chunk = f.read(8192)
        if b"\x00" in chunk:
            return False
        chunk.decode("utf-8")
        return True
    except (OSError, UnicodeDecodeError):
        return False


def scan_file(path: Path, rel: str) -> list[str]:
    """扫描单个文本文件,返回命中描述行。"""
    hits: list[str] = []
    try:
        text = path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeDecodeError):
        return [f"{rel}: 无法按 UTF-8 读取,需人工确认是否含敏感内容"]
    for lineno, line in enumerate(text.splitlines(), start=1):
        for name, pattern in PATTERNS:
            if pattern.search(line):
                hits.append(f"{rel}:{lineno}: [{name}]")
                break  # 一行只报一次,避免重复
    return hits


def _ignored_by_git(root: Path, paths: list[Path]) -> set[Path]:
    """返回被 git ignore 的路径集合;git 不可用时返回空集(全部扫描)。"""
    import subprocess
    try:
        proc = subprocess.run(
            ["git", "check-ignore", "--stdin"],
            input="\n".join(str(p.relative_to(root)) for p in paths) + "\n",
            capture_output=True, text=True, cwd=str(root), timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    if proc.returncode not in (0, 1):
        return set()
    ignored = set()
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line:
            ignored.add(root / line)
    return ignored


def _scan_root(root: Path, *, artifact: bool = False) -> tuple[list[str], list[str]]:
    """扫描发布包候选目录,返回 (failures, skipped)。"""
    failures: list[str] = []
    skipped: list[str] = []
    import subprocess
    # tracked 检查:.env 与未脱敏 db 不得被 git 跟踪进发布包候选目录。
    try:
        proc = subprocess.run(
            ["git", "ls-files"], capture_output=True, text=True,
            cwd=str(root), timeout=30,
        )
        tracked = proc.stdout.splitlines() if proc.returncode == 0 else []
    except (OSError, subprocess.SubprocessError):
        tracked = []
    for entry in tracked:
        entry = entry.strip()
        if not entry:
            continue
        in_candidate = any(
            entry == c or entry.startswith(c + "/") for c in CANDIDATE_DIRS)
        if not in_candidate:
            continue
        name = entry.rsplit("/", 1)[-1]
        if name in FORBIDDEN_NAMES:
            failures.append(f"{entry}: .env 被 git 跟踪,不得进入发布包")
        elif entry.endswith(".db"):
            failures.append(f"{entry}: 未脱敏数据库被 git 跟踪,不得进入发布包")
    # 工作区内容扫描:跳过 git-ignored 的运行时文件(如 api/var/*.db),
    # 报告未忽略的 .env/db 误入与疑似密钥。
    work_files: list[Path] = []
    for candidate in (["."] if artifact else CANDIDATE_DIRS):
        base = root / candidate
        if not base.exists():
            skipped.append(candidate)
            continue
        work_files.extend(p for p in sorted(base.rglob("*")) if p.is_file())
    ignored = set() if artifact else _ignored_by_git(root, work_files)
    for path in work_files:
        if path in ignored and not rel_is_dist(path, root):
            continue
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            failures.append(f"{rel}: 发布内容不能包含符号链接")
        elif path.name in FORBIDDEN_NAMES or (path.name.startswith('.env.') and path.name != '.env.example'):
            failures.append(f"{rel}: 禁止文件(.env)误入发布包")
        elif path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
            failures.append(f"{rel}: 未脱敏数据库误入发布包")
        elif _is_text(path):
            failures.extend(scan_file(path, rel))
    return failures, skipped


def rel_is_dist(path: Path, root: Path) -> bool:
    return path.relative_to(root).as_posix().startswith("web/dist/")


def main() -> None:
    parser = argparse.ArgumentParser(description="发布包密钥/敏感文件扫描")
    parser.add_argument("--root", default=str(ROOT),
                        help="仓库根目录(默认脚本所在仓库根)")
    parser.add_argument("--artifact", action="store_true", help="扫描给定目录全部内容，不遵循 git ignore")
    args = parser.parse_args()
    root = Path(args.root).resolve()

    failures, skipped = _scan_root(root, artifact=args.artifact)
    for candidate in skipped:
        print(f"SKIP {candidate}: 目录不存在")
    if failures:
        print("scan_release: 发现疑似问题:")
        for line in failures:
            print(f"  {line}")
        sys.exit(1)
    print("scan_release: 无命中(发布包候选目录无疑似密钥/.env/未脱敏db)")


if __name__ == "__main__":
    main()
