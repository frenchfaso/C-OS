"""Verify private snapshot identity and fail-closed disposable-input cleanup."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('check_m3_perf', ROOT / 'scripts/check_m3_perf.py')
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class PrivateRegressionRunner(unittest.TestCase):
    def source(self, directory):
        root = Path(directory).resolve()
        for name in RUNNER.DIRECTORIES:
            (root / name).mkdir()
        (root / 'Cargo.toml').write_text('[workspace]\n')
        (root / 'scripts/check_m3_perf.py').write_text('snapshot runner\n')
        (root / 'specs/SPEC.md').write_text('ABI2 normative bytes\n')
        (root / 'native/vm.asm').write_bytes(b'actual native source\0')
        (root / 'target/release').mkdir(parents=True)
        return root

    def private_inputs(self, directory):
        stage = Path(directory).resolve() / 'source'
        out = stage / 'build/case'
        (out / 'usb').mkdir(parents=True)
        for name in ('diagnostic.reu', 'cache.reu', 'rollback.reu'):
            (out / 'usb' / name).write_bytes(b'private input: ' + name.encode())
        (out / 'isolated-flash.bin').write_bytes(b'private flash')
        (out / 'm3.reu').write_bytes(b'compiled pack')
        (out / 'result.json').write_text('{"status":"pass"}\n')
        (out / 'scanout.png').write_bytes(b'image must survive')
        (out / 'usb/other.reu').write_bytes(b'not on the cleanup allowlist')
        return stage, out

    def reclaim(self, stage, out, completed=True, open_pid=''):
        command = dict(name='completed backend helper', returncode=0 if completed else 1)
        with patch.object(RUNNER.shutil, 'which', return_value='/mock/lsof'), \
             patch.object(RUNNER.subprocess, 'run', return_value=subprocess.CompletedProcess(
                 [], 0 if open_pid else 1, stdout=open_pid, stderr='')):
            RUNNER.reclaim(out, stage, [command], stage.parent / 'cleanup.json')

    def test_snapshot_copies_current_bytes_and_excludes_existing_builds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.source(directory)
            (root / 'build').mkdir()
            (root / 'build/old.reu').write_bytes(b'preserved old pack')
            before = RUNNER.inventory(root)
            out = root / 'build/m3-perf/private'
            receipt = RUNNER.prepare(root, out, root / 'target')
            stage = out / 'source'
            self.assertEqual(receipt['source_sha256'], before)
            self.assertEqual(RUNNER.inventory(stage), before)
            self.assertFalse((stage / 'build').exists())
            self.assertEqual((stage / 'target').resolve(), root / 'target')
            self.assertEqual((root / 'build/old.reu').read_bytes(), b'preserved old pack')
            (root / 'specs/SPEC.md').write_text('a later specification\n')
            self.assertNotEqual(RUNNER.inventory(root), receipt['source_sha256'])
            self.assertEqual(RUNNER.inventory(stage), receipt['source_sha256'])

    def test_prepare_preserves_prior_evidence_and_rejects_external_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.source(directory)
            out = root / 'build/m3-perf/previous'
            out.mkdir(parents=True)
            (out / 'result.json').write_text('previous evidence')
            with self.assertRaisesRegex(ValueError, 'Preserve existing evidence'):
                RUNNER.prepare(root, out, root / 'target')
            self.assertEqual((out / 'result.json').read_text(), 'previous evidence')
            with self.assertRaisesRegex(ValueError, 'inside this repository'):
                RUNNER.prepare(root, root / 'other-output', root / 'target')

    def test_source_symlink_cannot_hide_a_mutable_external_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.source(directory)
            (root / 'native/alias.asm').symlink_to(root / 'native/vm.asm')
            with self.assertRaisesRegex(ValueError, 'without symlinks'):
                RUNNER.inventory(root)

    def test_cleanup_only_removes_checked_private_inputs_and_retains_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            stage, out = self.private_inputs(directory)
            expected = {str(path.relative_to(stage)): RUNNER.sha(path)
                        for path in RUNNER.cleanup_candidates(out)}
            self.reclaim(stage, out)
            self.assertEqual(RUNNER.cleanup_candidates(out), [])
            journal = json.loads((stage.parent / 'cleanup.json').read_text())
            self.assertEqual({entry['path']: entry['sha256'] for entry in journal}, expected)
            self.assertEqual((out / 'm3.reu').read_bytes(), b'compiled pack')
            self.assertTrue(all((out / name).is_file()
                                for name in ('result.json', 'scanout.png', 'usb/other.reu')))

    def test_backend_fat_clone_requires_exact_local_ownership_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            stage, out = self.private_inputs(directory)
            clone = out / 'run/usb-dir/usb-123abc/image-1.img'
            clone.parent.mkdir(parents=True)
            clone.write_bytes(b'disposable sparse FAT representation')
            manifest = clone.parent / 'manifest.json'
            value = dict(version=1, image=clone.name, host_root=str(out / 'usb'),
                         label='USB', size=clone.stat().st_size, skipped=[],
                         entries={'diagnostic.reu': dict(dir=False)})
            self.assertNotIn(clone, RUNNER.cleanup_candidates(out))
            manifest.write_text(json.dumps(value))
            self.assertIn(clone, RUNNER.cleanup_candidates(out))
            for changed in (dict(host_root=str(stage / 'another-owner/usb')),
                            dict(image='another-image.img'), dict(size=1),
                            dict(entries={'user-file': dict(dir=False)}),
                            dict(entries={'diagnostic.reu': dict(dir=True)})):
                manifest.write_text(json.dumps(value | changed))
                self.assertNotIn(clone, RUNNER.cleanup_candidates(out))
            manifest.write_text(json.dumps(value))
            self.reclaim(stage, out)
            self.assertFalse(clone.exists())
            self.assertEqual(json.loads(manifest.read_text()), value)
            self.assertTrue((out / 'result.json').is_file())

    def test_live_backend_descriptor_prevents_all_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            stage, out = self.private_inputs(directory)
            before = RUNNER.cleanup_candidates(out)
            with self.assertRaisesRegex(ValueError, 'still open'):
                self.reclaim(stage, out, open_pid='1234\n')
            self.assertTrue(all(path.exists() for path in before))
            self.assertFalse((stage.parent / 'cleanup.json').exists())

    def test_failed_helper_and_external_paths_prevent_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            stage, out = self.private_inputs(directory)
            with self.assertRaisesRegex(ValueError, 'completed successful'):
                self.reclaim(stage, out, completed=False)
            with self.assertRaisesRegex(ValueError, 'confined'):
                self.reclaim(stage, stage.parent)
            self.assertEqual(len(RUNNER.cleanup_candidates(out)), 4)

    def test_shared_private_inode_prevents_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            stage, out = self.private_inputs(directory)
            os.link(out / 'isolated-flash.bin', stage.parent / 'retained-flash.bin')
            with self.assertRaisesRegex(ValueError, 'shared'):
                self.reclaim(stage, out)
            self.assertEqual(len(RUNNER.cleanup_candidates(out)), 4)

    def test_exact_stage_command_receipt_includes_failure_log(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch.object(RUNNER, 'ROOT', root):
                receipt = RUNNER.Receipt(root / 'receipt', dict(os.environ))
                command = [os.sys.executable, '-c', 'print("durable failure"); raise SystemExit(7)']
                with self.assertRaisesRegex(ValueError, r'failed \(7\)'):
                    receipt.run('failure', command)
            record = json.loads((root / 'receipt/commands.json').read_text())[0]
            self.assertEqual(record['returncode'], 7)
            log = root / 'receipt' / record['log']
            self.assertEqual(RUNNER.sha(log), record['log_sha256'])
            self.assertIn('durable failure', log.read_text())


if __name__ == '__main__':
    unittest.main()
