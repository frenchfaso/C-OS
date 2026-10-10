"""Independent NMOS timing vectors and fail-closed assembled-bound checks."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('m2_bounds_explicit', ROOT / 'scripts/m2_bounds.py')
BOUNDS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BOUNDS)


class NmosBounds(unittest.TestCase):
    def fixture(self, directory, step):
        """Hand-encoded native CPU code, independent of VM/assembler encoders."""
        out = Path(directory)
        native = bytearray(0x400)
        native[:len(step)] = step
        native[0x10:0x13] = b'\x60\x60\x60'
        # Admission remains the existing high PAL interval, 280..299.
        video = bytes.fromhex('a5 c1 d0 17 ad b1 03 f0 10 2c 11 d0 10 0d '
                              'ad 12 d0 c9 18 90 06 c9 2c b0 02 18 60 '
                              'ee 05 fe d0 03 ee 06 fe 38 60')
        dma = bytes.fromhex('a5 c1 d0 25 ad b1 03 f0 e0 ad 37 03 c9 02 b0 19 '
                            'ad 4b 03 c9 02 b0 12 2c 11 d0 10 0d ad 12 d0 '
                            'c9 18 90 06 c9 2c b0 02 18 60 '
                            'ee 07 fe d0 03 ee 08 fe 38 60')
        native[0x30:0x30 + len(video)] = video
        native[0x60:0x60 + len(dma)] = dma
        native[0xa0:0xa0 + 118] = b'\x20\x18' * 59
        prg = b'\x01\x08\x60'
        (out / 'native.bin').write_bytes(native)
        (out / 'm2.prg').write_bytes(prg)
        sha = lambda value: hashlib.sha256(value).hexdigest()
        symbols = dict(vm_step=0x1800, cache_service=0x1810, cache_native_read=0x1811,
                       cache_native_write=0x1812, vm_execute=0x181f, vm_e_nop=0x1820,
                       vm_video_admit=0x1830, vm_dma_admit=0x1860,
                       m2_admission_safe=0x1849, m2_video_deferred=0x184b,
                       m2_dma_deferred=0x1889, nmi_pending=0xc1,
                       vm_handlers=0x18a0, vm_tables_start=0x1950)
        (out / 'map.json').write_text(json.dumps(dict(
            format='COSM2MAP1', cache_line_bytes=128, native_ram_first=0x1800,
            build_tag=7, symbols=symbols,
            artifact_sha256={'native.bin': sha(native), 'm2.prg': sha(prg)})))
        return out

    def mutate_native(self, build, offset, replacement):
        native = bytearray((build / 'native.bin').read_bytes())
        native[offset:offset + len(replacement)] = replacement
        (build / 'native.bin').write_bytes(native)
        metadata = json.loads((build / 'map.json').read_text())
        metadata['artifact_sha256']['native.bin'] = hashlib.sha256(native).hexdigest()
        (build / 'map.json').write_text(json.dumps(metadata))

    def coherent_admission(self):
        """Independent, hand-encoded three-read PAL classification hooks."""
        ram = bytearray(65536)
        video = bytes.fromhex('a5 c1 d0 0c ad b1 03 f0 05 20 60 12 b0 02 18 60 '
                              'ee 16 03 d0 03 ee 17 03 38 60')
        dma = bytes.fromhex('a5 c1 d0 1a ad b1 03 f0 d5 ad 37 03 c9 02 b0 0e '
                            'ad 4b 03 c9 02 b0 07 20 60 12 b0 02 18 60 '
                            'ee 18 03 d0 03 ee 19 03 38 60')
        raster = bytes.fromhex('2c 11 d0 30 0e ad 12 d0 c9 15 b0 19 '
                               '2c 11 d0 30 14 18 60 ad 12 d0 c9 04 90 0b '
                               'c9 38 b0 07 2c 11 d0 10 02 18 60 38 60')
        for origin, body in ((0x1200, video), (0x1230, dma), (0x1260, raster)):
            ram[origin:origin + len(body)] = body
        symbols = dict(vm_video_admit=0x1200, vm_dma_admit=0x1230,
                       m3_admission_safe=0x120e, m3_video_deferred=0x1210,
                       m3_dma_deferred=0x124e, nmi_pending=0xc1,
                       m3_raster_admit=0x1260, m3_raster_post=0x1273,
                       m3_raster_reject=0x1285)
        return ram, symbols

    def split_admission(self):
        """Hand-encoded separate VM and scheduler gates sharing one post path."""
        ram, symbols = self.coherent_admission()
        ram[0x1300:0x1327] = ram[0x1260:0x1287]
        ram[0x120a:0x120c] = b'\xed\x12'
        ram[0x1248:0x124a] = b'\x00\x13'
        ram[0x1190:0x11a0] = bytes.fromhex(
            'a5 c1 d0 7c ad b1 03 f0 75 20 00 13 b0 72 18 60')
        ram[0x12ed:0x1300] = bytes.fromhex(
            '2c 11 d0 30 21 ad 12 d0 c9 33 b0 2c 2c 11 d0 30 27 18 60')
        symbols |= dict(m3_raster_admit=0x1300, m3_raster_post=0x1313,
                        m3_raster_reject=0x1325, m3_vm_raster_admit=0x12ed,
                        scheduler_video_admit=0x1190)
        return ram, symbols

    def test_known_cycle_maxima_include_page_cross_branch_and_stack_costs(self):
        vectors = {
            0xea: 2, 0x69: 2, 0xa9: 2, 0x45: 3, 0xa5: 3, 0x55: 4,
            0x95: 4, 0xad: 4, 0xbd: 5, 0xb9: 5, 0x9d: 5,
            0xb1: 6, 0x91: 6, 0xa1: 6, 0x06: 5, 0x16: 6,
            0x0e: 6, 0x1e: 7, 0xee: 6, 0xfe: 7,
            0x08: 3, 0x48: 3, 0x28: 4, 0x68: 4,
            0x4c: 3, 0x6c: 5, 0x20: 6, 0x60: 6, 0x40: 6,
        }
        for opcode, maximum in vectors.items():
            self.assertEqual(BOUNDS.CYCLES[opcode], maximum, f'opcode ${opcode:02x}')
        self.assertTrue(all(BOUNDS.CYCLES[opcode] == 4 for opcode in BOUNDS.BRANCHES))
        self.assertEqual(BOUNDS.CYCLES.keys(), BOUNDS.LENGTHS.keys())
        self.assertEqual(len(BOUNDS.CYCLES), 150)
        self.assertTrue(all(2 <= cycles <= 7 for cycles in BOUNDS.CYCLES.values()))

    def test_instruction_costs_preserve_io_and_caller_and_uniform_model(self):
        with tempfile.TemporaryDirectory() as directory:
            # LDA#1, LDA$D012, LDA($02),Y, RTS:2+4+6+6, callerJSR6.
            build = self.fixture(directory, b'\xa9\x01\xad\x12\xd0\xb1\x02\x60')
            report = BOUNDS.analyze(build)
            step = report['results']['vm_step']
            self.assertEqual(step['instruction_visits'], 4)
            self.assertEqual(step['cpu_cycle_upper_bound'], 24)
            self.assertEqual(step['uniform_cpu_cycle_upper_bound'], 35)
            self.assertEqual(step['io_access_upper_bound'], 1)
            self.assertEqual(step['cpu_io_phi2_upper_bound'], 8)
            self.assertEqual(step['dma_phi2_allowance'], 0)
            self.assertEqual(report['results']['cache_service']['dma_phi2_allowance'], 511)
            self.assertEqual(report['latest_admission_guard_phi2'], 4410)

    def test_branch_four_cycle_maximum_is_charged_on_either_feasible_path(self):
        with tempfile.TemporaryDirectory() as directory:
            build = self.fixture(directory, b'\xd0\x01\xea\x60')
            step = BOUNDS.analyze(build)['results']['vm_step']
            self.assertEqual(step['instruction_visits'], 3)
            self.assertEqual(step['cpu_cycle_upper_bound'], 4 + 2 + 6 + 6)

    def test_unknown_native_opcode_and_missing_cycle_maximum_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            build = self.fixture(directory, b'\xff')
            with self.assertRaisesRegex(ValueError, 'Unknown opcode'):
                BOUNDS.analyze(build)
            build = self.fixture(directory, b'\xa9\x01\x60')
            with patch.dict(BOUNDS.CYCLES):
                del BOUNDS.CYCLES[0xa9]
                with self.assertRaisesRegex(ValueError, 'No explicit NMOS cycle maximum'):
                    BOUNDS.analyze(build)

    def test_irq_guard_requires_strict_slack(self):
        candidate = dict(conditional_total_phi2_upper_bound=2214)
        report = dict(results={'vm_step': candidate}, last_opcode_admission_audit={},
                      latest_admission_guard_phi2=2215)
        BOUNDS.check_admission(report)
        report['latest_admission_guard_phi2'] = 2214
        with self.assertRaisesRegex(ValueError, 'Unsafe admission'):
            BOUNDS.check_admission(report)
        report['latest_admission_guard_phi2'] = 4410
        report['last_opcode_admission_audit'] = {
            'scheduler_tick': dict(conditional_total_phi2_upper_bound=4411)}
        with self.assertRaisesRegex(ValueError, 'scheduler_tick'):
            BOUNDS.check_admission(report)

    def test_complete_admission_signature_rejects_wrong_gating_or_return_edges(self):
        # Recompute artifact hashes after mutation: the check must reject the
        # unsafe hook itself, not simply notice stale map hashes.
        for offset, replacement in ((0x3c, b'\x30'), (0x44, b'\x07'),
                                    (0x30, b'\xa6'), (0x49, b'\x38'),
                                    (0x67, b'\xd0'), (0x6b, b'\x38')):
            with self.subTest(offset=offset), tempfile.TemporaryDirectory() as directory:
                build = self.fixture(directory, b'\x60')
                self.mutate_native(build, offset, replacement)
                with self.assertRaisesRegex(ValueError, 'Unrecognized'):
                    BOUNDS.analyze(build)

    def test_coherent_wrapping_window_has_explicit_intervals_and_minimum_guard(self):
        ram, symbols = self.coherent_admission()
        windows = BOUNDS.admission_windows(ram, symbols, True)
        self.assertEqual(windows['vm_video_admit'], windows['vm_dma_admit'])
        window = windows['vm_video_admit']
        self.assertTrue(window['coherent_high_low_high'])
        self.assertTrue(window['wraps_frame'])
        self.assertEqual(window['intervals'], [dict(first_line=0, last_line=20),
                                               dict(first_line=260, last_line=311)])
        self.assertEqual(BOUNDS.admission_guard(windows), (58 - 21) * 63)

    def test_coherent_diagnostic_and_four_step_windows_are_known_exact_variants(self):
        for early, first, end, guard, expected in (
                (0, 24, 44, 4410, [dict(first_line=280, last_line=299)]),
                (11, 4, 56, 2961, [dict(first_line=0, last_line=10),
                                   dict(first_line=260, last_line=311)])):
            with self.subTest(early=early):
                ram, symbols = self.coherent_admission()
                ram[0x1269], ram[0x1277], ram[0x127b] = early, first, end
                windows = BOUNDS.admission_windows(ram, symbols, True)
                self.assertEqual(windows['vm_video_admit']['intervals'], expected)
                self.assertEqual(BOUNDS.admission_guard(windows), guard)

    def test_map_cannot_describe_wider_admission_than_assembled_bytes(self):
        ram, symbols = self.coherent_admission()
        windows = BOUNDS.admission_windows(ram, symbols, True)
        metadata = dict(runtime_admission_first_line=260, runtime_admission_last_line=311,
                        runtime_admission_early_first_line=0, runtime_admission_early_last_line=20,
                        latest_admission_guard_phi2=2331)
        BOUNDS.verify_map_windows(metadata, windows)
        for change in (dict(runtime_admission_first_line=259),
                       dict(runtime_admission_early_last_line=21),
                       dict(latest_admission_guard_phi2=4410)):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'differ'):
                BOUNDS.verify_map_windows(metadata | change, windows)

    def test_valid_pc_wrapper_rejects_bypassing_first_check_or_changed_shared_flag(self):
        ram, symbols = self.coherent_admission()
        symbols |= dict(vm_run=0x1300, vm_run_valid_pc=0x1307, vm_run_return=0x130e,
                        vm_step=0x1340, vm_step_valid_pc=0x1344, vm_check_video=0x1364,
                        vm_attempt=0x136e, vm_boundary=0x1480, vm_check_pc=0x14a0,
                        vm_fault_boundary=0x1490)
        wrapper = bytes.fromhex('20 40 13 a5 47 d0 07 20 44 13 a5 47 f0 f9 60')
        step = bytes.fromhex('a2 01 d0 02 a2 00 86 7f a5 47 c9 05 f0 0c c9 06 '
                             'f0 08 a5 5c f0 05 a9 04 85 47 60 a5 24 d0 05 a9 01 '
                             '4c 80 14 20 00 12 90 05 a9 07 4c 80 14 '
                             'a9 00 85 78 85 7b 85 77 85 48 85 4d a5 1e 85 66 '
                             'a5 1f 85 67 a5 20 85 68 a5 7f f0 08 20 a0 14 '
                             '90 03 4c 90 14')
        ram[0x1300:0x1300 + len(wrapper)] = wrapper
        ram[0x1340:0x1340 + len(step)] = step
        verified = BOUNDS.verify_valid_pc_wrapper(ram, symbols)
        self.assertTrue(verified['every_entry_first_step_checks_current_pc'])
        self.assertTrue(verified['every_step_video_admitted'])
        for address, value in ((0x1301, 0x44), (0x130c, 0xd0), (0x1341, 0),
                               (0x1347, 0x7e), (0x1388, 0x90), (0x1364, 0x4c)):
            with self.subTest(address=address):
                changed = bytearray(ram)
                changed[address] = value
                with self.assertRaisesRegex(ValueError, 'Unrecognized'):
                    BOUNDS.verify_valid_pc_wrapper(changed, symbols)

    def test_coherent_window_rejects_torn_read_checks_changed_constants_and_hook_bypasses(self):
        for address, replacement in ((0x1260, 0xea), (0x126f, 0x10), (0x1281, 0x30),
                                     (0x1269, 22), (0x127c, 57), (0x1264, 0x0f),
                                     (0x1209, 0x4c), (0x1247, 0x61), (0x120c, 0x90),
                                     (0x1211, 0x18)):
            with self.subTest(address=address):
                ram, symbols = self.coherent_admission()
                ram[address] = replacement
                with self.assertRaisesRegex(ValueError, 'Unrecognized'):
                    BOUNDS.admission_windows(ram, symbols, True)

    def test_split_windows_keep_scheduler_and_dma_early_deadlines(self):
        ram, symbols = self.split_admission()
        windows = BOUNDS.admission_windows(ram, symbols, True)
        self.assertEqual(BOUNDS.admission_guard(windows), 441)
        self.assertEqual(BOUNDS.admission_guard(windows, 'scheduler_video_admit'), 2331)
        self.assertEqual(windows['scheduler_video_admit'], windows['vm_dma_admit'])
        self.assertEqual(windows['vm_video_admit']['intervals'][0]['last_line'], 50)
        metadata = dict(runtime_admission_first_line=260, runtime_admission_last_line=311,
                        runtime_admission_early_first_line=0, runtime_admission_early_last_line=50,
                        latest_admission_guard_phi2=441, scheduler_admission_early_last_line=20,
                        dma_admission_early_last_line=20, scheduler_latest_admission_guard_phi2=2331,
                        dma_latest_admission_guard_phi2=2331)
        BOUNDS.verify_map_windows(metadata, windows)
        for change in (dict(scheduler_admission_early_last_line=50),
                       dict(dma_latest_admission_guard_phi2=441),
                       dict(scheduler_latest_admission_guard_phi2=2332)):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'differ'):
                BOUNDS.verify_map_windows(metadata | change, windows)
        for address, value in ((0x12f6, 52), (0x12fd, 0x10), (0x12f1, 0x20),
                               (0x119a, 0xed), (0x1248, 0xed), (0x120a, 0)):
            with self.subTest(address=address):
                altered = bytearray(ram)
                altered[address] = value
                with self.assertRaisesRegex(ValueError, 'Unrecognized'):
                    BOUNDS.admission_windows(altered, symbols, True)

    def test_split_admission_guards_each_domain_and_the_complete_late_tail(self):
        report = dict(results={
            'vm_step': dict(conditional_total_phi2_upper_bound=225),
            'cache_service': dict(conditional_total_phi2_upper_bound=657)},
            last_opcode_admission_audit={
                'scheduler_tick': dict(conditional_total_phi2_upper_bound=2257),
                'late_vm_return_tail': dict(conditional_total_phi2_upper_bound=371)},
            latest_admission_guard_phi2=441,
            admission_guard_phi2=dict(vm=441, scheduler=2331, dma=2331))
        BOUNDS.check_admission(report)
        for group, name, value in (('results', 'vm_step', 441),
                                  ('results', 'cache_service', 2331),
                                  ('last_opcode_admission_audit', 'scheduler_tick', 2331),
                                  ('last_opcode_admission_audit', 'late_vm_return_tail', 441)):
            original = report[group][name]['conditional_total_phi2_upper_bound']
            report[group][name]['conditional_total_phi2_upper_bound'] = value
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, name):
                BOUNDS.check_admission(report)
            report[group][name]['conditional_total_phi2_upper_bound'] = original

    def test_split_scheduler_rejects_fallback_bypass_and_changed_result_dispatch(self):
        ram = bytearray(65536)
        symbols = dict(scheduler_tick=0x2000, scheduler_tick_vm_first=0x2033,
                       scheduler_tick_vm_done=0x2041, scheduler_tick_native_done=0x2047,
                       scheduler_tick_done=0x204c, scheduler_vm_phase=0x204d,
                       scheduler_video_admit=0x1200, scheduler_select=0x2100,
                       scheduler_cancel_current=0x2200, scheduler_wake_timed=0x2300,
                       scheduler_native_phase=0x2400, scheduler_has_job=0x2500,
                       scheduler_vm_timestamp_done=0x2060, scheduler_vm_single=0x206b,
                       scheduler_vm_result=0x206e, vm_run=0x2600, vm_step=0x2700)
        body = bytes.fromhex(
            'ad 0d fe f0 47 20 00 12 b0 42 ad 0e fe f0 13 38 e9 01 29 03 '
            '20 00 21 20 00 22 a9 00 8d 0e fe ee 0f fe 20 00 23 ad 0a fe f0 09 '
            '20 00 24 90 18 20 4d 20 60 20 4d 20 90 09 20 00 12 b0 0f '
            '20 00 24 60 a9 01 8d 0a fe 60 a9 00 8d 0a fe 60')
        ram[0x2000:0x204d] = body
        ram[0x2060:0x206e] = bytes.fromhex('20 00 25 b0 06 20 00 26 4c 6e 20 20 00 27')
        proof = BOUNDS.verify_split_scheduler(ram, symbols)
        self.assertEqual(proof['refused_fallback_branch'], 0x203b)
        for address, value in ((0x203b, 0x90), (0x2039, 1), (0x2036, 0xb0),
                               (0x2006, 1), (0x2068, 0x20), (0x206c, 1)):
            with self.subTest(address=address):
                altered = bytearray(ram)
                altered[address] = value
                with self.assertRaisesRegex(ValueError, 'Unrecognized'):
                    BOUNDS.verify_split_scheduler(altered, symbols)

    def test_active_reporter_confirms_both_pal_transitions_without_retry_or_scratch(self):
        ram = bytearray(65536)
        symbols = dict(vm_dma_completed=0x133a, raster_active=0x1350,
                       m3_not_active=0x136f, m3_is_active=0x1371,
                       m3_recover_nmi=0x1373)
        counter = bytes.fromhex('ee 1d 03 ad b1 03 f0 0d 20 50 13 90 08 '
                                'ee 1a 03 d0 03 ee 1b 03 60')
        classifier = bytes.fromhex('2c 11 d0 30 0e ad 12 d0 c9 3c 2c 11 d0 30 12 '
                                   '90 0e 38 60 ad 12 d0 c9 04 2c 11 d0 10 02 '
                                   '90 02 18 60 38 60')
        ram[0x133a:0x1350] = counter
        ram[0x1350:0x1373] = classifier
        report = BOUNDS.verify_active_classifier(ram, symbols)
        self.assertEqual(report['maximum_io_reads_per_call'], 3)
        self.assertEqual(report['retries'], 0)
        self.assertTrue(report['low_to_high_transition_active'])
        self.assertTrue(report['high_to_low_transition_inactive'])
        for address, value in ((0x135e, 0x10), (0x136b, 0x30), (0x1359, 61),
                               (0x1367, 3), (0x1371, 0x18), (0x133b, 0x1a),
                               (0x1345, 0xb0)):
            with self.subTest(address=address):
                altered = bytearray(ram)
                altered[address] = value
                with self.assertRaisesRegex(ValueError, 'Unrecognized'):
                    BOUNDS.verify_active_classifier(altered, symbols)

    def test_weighted_bounds_never_exceed_uniform_bounds_in_available_abi2_packs(self):
        builds = [ROOT / f'build/m3/{line}' for line in (128, 64)]
        if not all(path.is_file() for build in builds for path in (build / 'map.json', build / 'm3.manifest.json')) \
                or any(json.loads((build / 'm3.manifest.json').read_text())['abi'] != 2 for build in builds):
            builds = [ROOT / f'build/m3-perf/registers/{line}' for line in (128, 64)]
        if not all((build / 'map.json').is_file() for build in builds):
            self.skipTest('Build current ABI2 normal M3 packs first')
        for build in builds:
            report = BOUNDS.analyze(build)
            bound_groups = [report['results'], report['separately_bounded_helpers'],
                            report['last_opcode_admission_audit']]
            for bounds in bound_groups:
                for name, value in bounds.items():
                    if isinstance(value, dict):
                        self.assertLessEqual(value['cpu_cycle_upper_bound'],
                                             value['uniform_cpu_cycle_upper_bound'], name)
                        self.assertLessEqual(value['conditional_total_phi2_upper_bound'],
                                             value['uniform_conditional_total_phi2_upper_bound'], name)
            self.assertEqual(report['loops']['vm_multiply_bit'], 15)
            self.assertNotIn('vm_run', report['results'])


if __name__ == '__main__':
    unittest.main()
