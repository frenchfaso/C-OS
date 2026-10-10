"""Exercise profiler evidence binding and independently encoded target records."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('m3_profile', ROOT / 'scripts/m3_profile.py')
PROFILE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROFILE)


class ProfileEvidence(unittest.TestCase):
    def observations(self):
        data = bytearray(PROFILE.PROFILE_BYTES)
        # Bin0: 3 calls, 120 accumulated ticks, min35/max45, one carry return.
        for offset, value in [(0, 120), (4, 3), (8, 35), (12, 45), (0x104, 42), (0x108, 1)]:
            data[offset:offset + 4] = value.to_bytes(4, 'little')
        # Empty bin15: 256 samples, min10/max12, sum2816 ticks.
        for offset, value in [(240, 2816), (244, 256), (248, 10), (252, 12)]:
            data[offset:offset + 4] = value.to_bytes(4, 'little')
        return data

    def test_counter_layout_and_calibrated_interval(self):
        measured = PROFILE.metrics(self.observations())
        self.assertEqual(measured['vm_step']['calls'], 3)
        self.assertEqual(measured['vm_step']['inclusive_phi2_ticks'], 120)
        self.assertEqual(measured['vm_step']['carry_set_calls'], 1)
        self.assertEqual(measured['vm_step']['body_excess_vs_empty_interval_phi2_ticks'], [84, 90])

    def test_exact_lifetime_calls_from_sample_count_and_remainder(self):
        data = self.observations()
        data[0x230] = 145  # Counter modulo256; low7bits retain17 calls.
        measured = PROFILE.metrics(data, sample_factor=128)
        self.assertEqual(measured['vm_step']['lifetime_calls'], 3 * 128 + 17)
        self.assertEqual(measured['empty_probe']['lifetime_calls'], 256)

    def test_rejects_overflow_and_incomplete_calibration(self):
        overflow = self.observations()
        overflow[0x222] = 1
        with self.assertRaisesRegex(ValueError, 'overflowed'):
            PROFILE.metrics(overflow)
        incomplete = self.observations()
        incomplete[244:248] = (255).to_bytes(4, 'little')
        with self.assertRaisesRegex(ValueError, 'calibration failed'):
            PROFILE.metrics(incomplete)

    def test_rejects_discontinuous_or_inconsistent_interval(self):
        discontinuous = self.observations()
        discontinuous[12:16] = (0xffff0007).to_bytes(4, 'little')
        with self.assertRaisesRegex(ValueError, 'discontinuous'):
            PROFILE.metrics(discontinuous)
        inconsistent = self.observations()
        inconsistent[0:4] = (1000).to_bytes(4, 'little')
        with self.assertRaisesRegex(ValueError, 'discontinuous'):
            PROFILE.metrics(inconsistent)

    def test_existing_snapshot_requires_linker_binding(self):
        with tempfile.TemporaryDirectory(prefix='cos-profile-existing-') as directory:
            base = Path(directory)
            source = base / 'source'
            (source / 'target/release').mkdir(parents=True)
            (source / 'target/release/cospack').write_bytes(b'unbound ABI2 linker')
            (base / 'source-snapshot.json').write_text(json.dumps({'source_sha256': {}}))
            with self.assertRaisesRegex(ValueError, 'does not bind'):
                PROFILE.snapshot(source, base / 'unused.json', existing=True)

    def test_frozen_snapshot_rejects_source_change(self):
        with tempfile.TemporaryDirectory(prefix='cos-profile-evidence-') as directory:
            base = Path(directory)
            source = base / 'source'
            (source / 'native').mkdir(parents=True)
            (source / 'target/release').mkdir(parents=True)
            native = source / 'native/vm.asm'
            native.write_bytes(b'original source')
            tool = source / 'target/release/cospack'
            tool.write_bytes(b'original host tool')
            receipt = dict(source_sha256={'native/vm.asm': hashlib.sha256(native.read_bytes()).hexdigest()},
                           host_tool_sha256={'cospack': hashlib.sha256(tool.read_bytes()).hexdigest()})
            (base / 'source-snapshot.json').write_text(json.dumps(receipt))
            self.assertEqual(PROFILE.snapshot(source, base / 'unused.json'), receipt)
            native.write_bytes(b'changed source')
            with self.assertRaisesRegex(ValueError, 'Frozen source changed'):
                PROFILE.snapshot(source, base / 'unused.json')

    def test_frozen_snapshot_rejects_host_linker_change(self):
        with tempfile.TemporaryDirectory(prefix='cos-profile-linker-') as directory:
            base = Path(directory)
            source = base / 'source'
            (source / 'target/release').mkdir(parents=True)
            tool = source / 'target/release/cospack'
            tool.write_bytes(b'ABI1 linker')
            receipt = dict(source_sha256={}, host_tool_sha256={'cospack': hashlib.sha256(tool.read_bytes()).hexdigest()})
            (base / 'source-snapshot.json').write_text(json.dumps(receipt))
            tool.write_bytes(b'ABI2 linker')
            with self.assertRaisesRegex(ValueError, 'Frozen host tool changed'):
                PROFILE.snapshot(source, base / 'unused.json')


if __name__ == '__main__':
    unittest.main()
