"""仅从明确允许的源码/构建产物创建本地交付包，扫描通过才写出 ZIP。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import zipfile

from tools.demo.scan_release import _scan_root

ROOT = Path(__file__).resolve().parents[2]
DIRECTORIES = ["core", "api/app", "api/tests", "web/src", "web/tests", "web/dist",
               "tools/demo", "tools/preflight", "demo-data/v1/cases", ".github"]
FILES = ["README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "CONTRIBUTING.md", "SECURITY.md",
         ".env.example", ".gitignore", "Makefile", "api/__init__.py",
         "api/requirements.txt", "api/requirements-dev.txt", "api/requirements.in", "api/requirements-dev.in",
         "web/package.json", "web/package-lock.json", "web/index.html", "web/env.d.ts",
         "web/vite.config.ts", "web/playwright.config.ts", "web/eslint.config.js",
         "web/tsconfig.json", "web/tsconfig.app.json", "web/tsconfig.node.json",
         "docs/18-比赛版产品与实现方案.md", "docs/19-比赛版算法流程与开发契约.md",
         "docs/27-算法审查与赛题交付验收.md", "docs/29-全站交互与交付验收清单.md", "docs/README.md", "docs/dependency-notices.json",
         "docs/12-真实社区对比测试报告-哈尔滨道外.md", "docs/26-手机端组件重构与交互验收.md",
         "docs/28-沿途通勤简化版与通用路径验收.md", "docs/acceptance-live.json",
         "docs/acceptance-community-live.json", "TODO.md",
         "docs/acceptance/community-gray-375.png", "docs/acceptance/community-390.png",
         "docs/acceptance/community-768.png", "docs/acceptance/community-1440.png",
         "docs/acceptance/execution-375.png", "docs/acceptance/explore-375.png",
         "docs/acceptance/community-mobile-verified.pdf",
         "docs/30-沿途等时带缓存与验收.md", "docs/acceptance-route-band-live.json"]


def main():
    if not (ROOT / "web/dist/index.html").is_file():
        raise SystemExit("先运行 make web-build")
    with tempfile.TemporaryDirectory(prefix="shunshou-release-") as temp:
        staging = Path(temp) / "shunshou"
        staging.mkdir()
        for directory in DIRECTORIES:
            for path in sorted((ROOT / directory).rglob("*")):
                if path.is_symlink():
                    raise SystemExit(f"不允许链接：{path.relative_to(ROOT)}")
                if not path.is_file() or '__pycache__' in path.parts or path.suffix == '.pyc':
                    continue
                target = staging / path.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
        for file in FILES:
            path = ROOT / file
            if not path.is_file():
                # 可选 TS 配置名以当前项目配置为准，其余必需文件不能缺失。
                if file in {"web/tsconfig.app.json", "web/tsconfig.node.json"}:
                    continue
                raise SystemExit(f"缺少交付文件：{file}")
            target = staging / file
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        failures, _ = _scan_root(staging, artifact=True)
        if failures:
            raise SystemExit("扫描未通过：\n" + "\n".join(failures))
        inventory = {p.relative_to(staging).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in sorted(staging.rglob('*')) if p.is_file()}
        (staging / "MANIFEST.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2))
        output = ROOT / "release/shunshou-source.zip"
        output.parent.mkdir(exist_ok=True)
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(staging.rglob('*')):
                if path.is_file():
                    archive.write(path, path.relative_to(staging.parent))
        print(f"release: {len(inventory)} files, scan passed, {output}")


if __name__ == '__main__':
    main()
