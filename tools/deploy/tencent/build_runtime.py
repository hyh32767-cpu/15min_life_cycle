"""Build a scanned runtime-only archive; credentials and local databases stay out."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import zipfile
from tools.demo.scan_release import _scan_root

ROOT = Path(__file__).resolve().parents[3]


def main():
    output = ROOT / 'output/deploy/shunlu-grid-runtime.zip'
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        stage = Path(directory) / 'shunshou'
        stage.mkdir()
        for folder in ['core', 'api/app', 'web/dist', 'demo-data/v1/cases']:
            for path in (ROOT / folder).rglob('*'):
                if path.is_symlink():
                    raise SystemExit('Unexpected symlink')
                if not path.is_file() or '__pycache__' in path.parts or path.suffix == '.pyc':
                    continue
                target = stage / path.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
        for name in ['api/__init__.py', 'api/requirements.txt', 'LICENSE', 'THIRD_PARTY_NOTICES.md']:
            shutil.copyfile(ROOT / name, stage / name)
        failures, _ = _scan_root(stage, artifact=True)
        if failures:
            raise SystemExit('\n'.join(failures))
        files = {p.relative_to(stage).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(stage.rglob('*')) if p.is_file()}
        (stage / 'manifest.json').write_text(json.dumps(files, indent=2))
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in stage.rglob('*'):
                if path.is_file():
                    archive.write(path, path.relative_to(stage.parent))
        print(json.dumps({'files': len(files), 'archive': str(output), 'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}))


if __name__ == '__main__':
    main()
