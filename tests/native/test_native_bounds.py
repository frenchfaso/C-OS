"""Check profile loading and fail-closed behavior of the assembled CFG audit."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import m2_bounds  # noqa: E402


class NativeBounds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.builds = [ROOT / f"build/{profile}/{line}"
                      for profile in ["m2", "m3"] for line in [128, 64]]
        if not all((build / "map.json").exists() for build in cls.builds):
            raise unittest.SkipTest("Build both M2 and M3 cache variants first")

    def test_both_origins_and_diagnostic_profiles(self):
        for build in self.builds:
            with self.subTest(build=build):
                result = m2_bounds.analyze(build)
                m3 = build.parent.name == "m3"
                self.assertEqual(result["native_ram_first"], 0x1200 if m3 else 0x1800)
                self.assertEqual(result["format"], "COSM3STATICBOUND1" if m3 else "COSM2STATICBOUND1")
                for name, bound in result["results"].items():
                    domain = "vm" if name.startswith("vm_step") else "dma"
                    self.assertLess(bound["conditional_total_phi2_upper_bound"],
                                    result["admission_guard_phi2"][domain])
                self.assertNotIn("vm_run", result["results"])
                if m3:
                    self.assertEqual(result["conditional_loops"]["scheduler_timer_read"], 1)
                    self.assertNotIn("scheduler_timer_read", result["loops"])
                    self.assertLess(result["timer_read_model"]["read_triplet_phi2_upper_bound"], 256)
                    self.assertIn("scheduler_native_phase", result["separately_bounded_helpers"])
                    self.assertIn("scheduler_vm_result", result["last_opcode_admission_audit"])

    def altered_build(self, path, replacement, update_hash):
        build = self.builds[2]
        spec = json.loads((build / "map.json").read_text())
        for name in ["map.json", "m3.prg", "native.bin"]:
            shutil.copyfile(build / name, path / name)
        data = bytearray((path / "native.bin").read_bytes())
        # Keep the reviewed entry/gate signature intact, so the intended CFG
        # rejection is reached independently of dispatch-wrapper recognition.
        offset = spec["symbols"]["vm_execute"] - spec["native_ram_first"]
        data[offset:offset + len(replacement)] = replacement
        (path / "native.bin").write_bytes(data)
        if update_hash:
            spec["artifact_sha256"]["native.bin"] = hashlib.sha256(data).hexdigest()
            (path / "map.json").write_text(json.dumps(spec))

    def test_rejects_artifact_tampering(self):
        with tempfile.TemporaryDirectory(prefix="cos-bounds-") as directory:
            path = Path(directory)
            self.altered_build(path, b"\xff", False)
            with self.assertRaisesRegex(ValueError, "differs from the build map"):
                m2_bounds.analyze(path)

    def test_rejects_unrecognized_opcode(self):
        with tempfile.TemporaryDirectory(prefix="cos-bounds-") as directory:
            path = Path(directory)
            self.altered_build(path, b"\xff", True)
            with self.assertRaisesRegex(ValueError, "Unknown opcode"):
                m2_bounds.analyze(path)

    def test_rejects_new_unbounded_cycle(self):
        with tempfile.TemporaryDirectory(prefix="cos-bounds-") as directory:
            path = Path(directory)
            spec = json.loads((self.builds[2] / "map.json").read_text())
            address = spec["symbols"]["vm_execute"]
            self.altered_build(path, b"\x4c" + address.to_bytes(2, "little"), True)
            with self.assertRaisesRegex(ValueError, "Unbounded native cycle"):
                m2_bounds.analyze(path)


if __name__ == "__main__":
    unittest.main()
