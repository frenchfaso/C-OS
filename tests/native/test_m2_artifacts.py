"""Check native boot layout against literal shared-memory limits."""
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class NativeBootArtifacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not all((ROOT / f"build/m2/{line}/map.json").is_file() for line in [128, 64]):
            raise unittest.SkipTest("Build both M2 cache variants first")

    def test_pairing_images_and_nonoverlapping_system_ranges(self):
        for line in [128, 64]:
            with self.subTest(line=line):
                out = ROOT / f"build/m2/{line}"
                report = json.loads((out / "map.json").read_text())
                linked = json.loads((out / "m2.manifest.json").read_text())
                image = (out / "m2.reu").read_bytes()
                self.assertEqual(len(image), 1 << 24)
                self.assertEqual(image[:8], b"COSREU01")
                self.assertEqual(int.from_bytes(image[8:12], "little"), report["build_tag"])
                self.assertEqual(image[12:14], b"\x02\x00")
                self.assertEqual(int.from_bytes(image[14:16], "little"), len(linked["apps"]))
                ranges = report["reu_boot_images"]
                self.assertEqual([r["first"] for r in ranges], [0x8000, 0xb000, 0xc000, 0xc200])
                for first, second in zip(ranges, ranges[1:]):
                    self.assertLess(first["last"], second["first"])
                self.assertLess(ranges[-1]["last"], 0x40000)
                kernel = (out / "native.bin").read_bytes()
                renderer = (out / "renderer.prg").read_bytes()
                self.assertEqual(renderer[:2], b"\x00\xf0")
                self.assertEqual(image[0x8000:0x8000 + len(kernel)], kernel)
                self.assertEqual(image[0xb000:0xb000 + len(renderer) - 2], renderer[2:])
                self.assertLessEqual(0x1800 + len(kernel), 0x4000)
                self.assertLessEqual(0xf000 + len(renderer) - 2, 0xfa00)
                prg = (out / "m2.prg").read_bytes()
                self.assertEqual(prg[:2], b"\x01\x08")
                self.assertLessEqual(0x801 + len(prg) - 2, 0x1800)
                for app in linked["apps"]:
                    self.assertLessEqual(app["data_seed"]["start"] + app["data_seed"]["length"], 0x8000)
                for name, digest in report["artifact_sha256"].items():
                    self.assertEqual(hashlib.sha256((out / name).read_bytes()).hexdigest(), digest)

    def test_cumulative_map_includes_all_caches_and_future_numeric_reserve(self):
        for line in [128, 64]:
            with self.subTest(line=line):
                report = json.loads((ROOT / f"build/m2/{line}/map.json").read_text())
                rows = report["sections"]
                self.assertEqual(rows[0]["first"], 0)
                self.assertEqual(rows[-1]["last"], 0xffff)
                for first, second in zip(rows, rows[1:]):
                    self.assertEqual(first["last"] + 1, second["first"])
                for row in rows:
                    self.assertLessEqual(row["assembled_bytes"] + row["runtime_bytes"], row["reserved_bytes"])
                self.assertEqual(report["directly_usable_non_framebuffer_ram"], 20480)
                self.assertEqual(report["code_cache_runtime_bytes"], 8 * line)
                self.assertEqual(report["data_cache_runtime_bytes"], 8 * line)
                self.assertEqual(report["cache_metadata_bytes"], 112)
                self.assertEqual(report["active_architecture_and_bounds_bytes"], 96)
                self.assertEqual(report["interpreter_scratch_bytes"], 30)
                self.assertEqual(report["instruction_dispatch_entries"], 59)
                self.assertEqual(report["interpreter_table_bytes"], 177)
                self.assertEqual(report["interpreter_instruction_bytes"], 2619)
                self.assertEqual(report["cache_work_area_reserved_bytes"], 96)
                self.assertEqual(report["cache_work_area_used_bytes"], 82)
                self.assertEqual(report["numerical_future_target"], 4096)
                # Extended diagnostics occupy real resident bytes. They may
                # consume numeric headroom; the normal M3 gate is separate.
                free = 0x4000 - (0x1200 + report["resident_assembled_bytes"])
                self.assertEqual(report["numeric_target_shortfall"], max(0,4096-free))
                if report["numeric_target_shortfall"]:
                    self.assertTrue(report["extended_diagnostics"])
                    self.assertFalse(report["normal_build"])
                    self.assertIn("diagnostic",report["numeric_shortfall_disposition"].lower())


if __name__ == "__main__":
    unittest.main()
