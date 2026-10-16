from tools.demo.scan_release import _scan_root


def test_artifact_scan_checks_env_and_databases_in_any_directory(tmp_path):
    (tmp_path / '.env.local').write_text('')
    (tmp_path / 'random.sqlite').write_bytes(b'\0')
    failures, _ = _scan_root(tmp_path, artifact=True)
    assert any('.env.local' in failure for failure in failures)
    assert any('random.sqlite' in failure for failure in failures)


def test_ignored_build_files_are_still_scanned(tmp_path):
    import subprocess
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    (tmp_path / '.gitignore').write_text('dist/\n')
    dist = tmp_path / 'web/dist'
    dist.mkdir(parents=True)
    (dist / 'bundle.js').write_text('a' + 'k=' + 'abcdefgh12345678')
    failures, _ = _scan_root(tmp_path)
    assert any('bundle.js' in failure for failure in failures)
