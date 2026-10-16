"""读取锁文件和已安装 Python 元数据生成依赖归属，不调用网络。"""
import importlib.metadata
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]


def main():
    lock = json.loads((ROOT / 'web/package-lock.json').read_text())
    npm = [{"package": name.removeprefix('node_modules/'), "version": item.get('version'),
            "license": item.get('license', 'UNKNOWN'), "resolved": item.get('resolved')}
           for name, item in lock['packages'].items() if name]
    python = []
    for line in (ROOT / 'api/requirements-dev.txt').read_text().splitlines():
        match = re.match(r'^([\w.-]+)==([^\s]+)', line)
        if not match:
            continue
        name, version = match.groups()
        metadata = importlib.metadata.metadata(name)
        python.append({"package": name, "version": version,
                       "license": metadata.get('License-Expression') or metadata.get('License') or
                       [c for c in metadata.get_all('Classifier', []) if c.startswith('License ::')] or 'UNKNOWN'})
    output = ROOT / 'docs/dependency-notices.json'
    output.write_text(json.dumps({"npm": npm, "python": python}, ensure_ascii=False, indent=2))
    print(f"dependency notices: {len(npm)} npm, {len(python)} Python; {output}")


if __name__ == '__main__':
    main()
