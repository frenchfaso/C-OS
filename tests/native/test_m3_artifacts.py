"""Verify normal M3 boot reuse, paired images, and the complete fixed RAM map."""
import hashlib
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[2]


class NormalM3Artifacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not all((ROOT/f"build/m3/{line}/map.json").is_file() for line in (128,64)):
            raise unittest.SkipTest("Build both normal M3 variants first")

    def test_bootstrap_and_resident_destinations_are_disjoint(self):
        for line in (128,64):
            with self.subTest(line=line):
                out=ROOT/f"build/m3/{line}"
                report=json.loads((out/"map.json").read_text())
                prg=(out/"m3.prg").read_bytes()
                kernel=(out/"native.bin").read_bytes()
                self.assertEqual(prg[:2],b"\x01\x08")
                self.assertEqual(prg[7:11],b"2061")
                self.assertEqual(report["symbols"]["entry"],0x080d)
                self.assertEqual(0x0801+len(prg)-2,report["symbols"]["m3_bootstrap_end"])
                self.assertLessEqual(0x0801+len(prg)-2,0x1200)
                self.assertEqual(report["native_ram_first"],0x1200)
                self.assertEqual(report["symbols"]["m3_kernel_entry"],0x1200)
                self.assertEqual(0x1200+len(kernel),report["symbols"]["m3_native_end"])
                self.assertEqual(report["resident_alignment_and_loader_bytes"],0)
                self.assertEqual(report["diagnostic_harness_assembled_bytes"],0)
                self.assertEqual(report["temporary_boot_staging_first"],0x0600)
                self.assertEqual(report["temporary_boot_staging_last"],0x07ff)

    def test_normal_profile_preserves_numeric_and_future_fixed_reserves(self):
        for line in (128,64):
            with self.subTest(line=line):
                d=json.loads((ROOT/f"build/m3/{line}/map.json").read_text())
                self.assertEqual(d["format"],"COSM3MAP1")
                self.assertTrue(d["normal_build"])
                self.assertFalse(d["extended_diagnostics"])
                self.assertFalse(d["margin_hook_enabled"])
                self.assertEqual(d["directly_usable_non_framebuffer_ram"],20480)
                self.assertEqual(d["numerical_future_target"],4096)
                self.assertEqual(d["numeric_target_shortfall"],0)
                self.assertEqual(d["resident_future_numeric_first"],d["symbols"]["m3_native_end"])
                self.assertLess(d["resident_future_numeric_last"],0x4000)
                self.assertEqual(d["normal_stack_static_bound"],18)
                self.assertEqual(d["combined_stack_static_bound"],30)
                self.assertEqual(d["runtime_admission_first_line"],260)
                self.assertEqual(d["runtime_admission_last_line"],311)
                self.assertEqual(d["runtime_admission_early_first_line"],0)
                self.assertEqual(d["runtime_admission_early_last_line"],50)
                self.assertEqual(d["latest_admission_guard_phi2"],441)
                self.assertEqual(d["scheduler_admission_early_last_line"],20)
                self.assertEqual(d["scheduler_latest_admission_guard_phi2"],2331)
                self.assertEqual(d["dma_admission_early_last_line"],20)
                self.assertEqual(d["dma_latest_admission_guard_phi2"],2331)
                self.assertTrue(d["native_link_does_not_import_bootstrap"])
                self.assertGreaterEqual(d["resident_headroom_after_numeric_target"],0)
                self.assertEqual(d["scheduler_completion_and_replacement_staging_bytes"],96)
                rows=d["sections"]
                self.assertEqual(rows[0]["first"],0)
                self.assertEqual(rows[-1]["last"],0xffff)
                for a,b in zip(rows,rows[1:]):
                    self.assertEqual(a["last"]+1,b["first"])
                for r in rows:
                    self.assertLessEqual(r["assembled_bytes"]+r["runtime_bytes"],r["reserved_bytes"])
                reserves={r["name"]:r for r in rows}
                self.assertEqual(reserves["event rings (future)"]["reserved_bytes"],512)
                self.assertEqual(reserves["font (future)"]["reserved_bytes"],768)
                self.assertEqual(reserves["cursor (future)"]["reserved_bytes"],128)
                self.assertEqual(reserves["scheduler globals and syscall completion"]["runtime_bytes"],224)
                self.assertEqual(d["code_cache_runtime_bytes"],8*line)
                self.assertEqual(d["data_cache_runtime_bytes"],8*line)
                self.assertEqual(d["cache_work_area_used_bytes"],d["symbols"]["cache_work_end"]-0x0350)

    def test_pack_and_descriptors_match_linked_apps(self):
        for line in (128,64):
            with self.subTest(line=line):
                out=ROOT/f"build/m3/{line}"
                d=json.loads((out/"map.json").read_text())
                manifest=json.loads((out/"m3.manifest.json").read_text())
                image=(out/"m3.reu").read_bytes()
                self.assertEqual(len(image),1<<24)
                self.assertEqual(image[:8],b"COSREU01")
                self.assertEqual(int.from_bytes(image[8:12],"little"),d["build_tag"])
                self.assertEqual(image[12:14],b"\x02\x00")
                self.assertEqual(image[14],len(manifest["apps"]))
                self.assertLessEqual(image[14],4)
                self.assertEqual(image[15],0)
                for name,digest in d["artifact_sha256"].items():
                    self.assertEqual(hashlib.sha256((out/name).read_bytes()).hexdigest(),digest)
                self.assertEqual(image[0x8000:0x8000+len((out/"native.bin").read_bytes())],(out/"native.bin").read_bytes())
                renderer=(out/"renderer.prg").read_bytes()[2:]
                self.assertEqual(image[0xb000:0xb000+len(renderer)],renderer)
                ranges=d["reu_boot_images"]
                for a,b in zip(ranges,ranges[1:]):
                    self.assertLess(a["last"],b["first"])
                for slot,app in enumerate(manifest["apps"]):
                    self.assertLessEqual(app["data_seed"]["start"]+app["data_seed"]["length"],0x8000)
                    context=image[0xc000+128*slot:0xc000+128*(slot+1)]
                    self.assertEqual(context[:2],app["id"].to_bytes(2,"little"))
                    self.assertEqual(int.from_bytes(context[28:31],"little"),app["entry"])
                    self.assertEqual(int.from_bytes(context[31:34],"little"),app["stack"]["last"])
                    self.assertEqual(context[34],128)
                    self.assertEqual(context[91:93],b"\x01\x00")
                    self.assertEqual(context[96:],bytes(32))

    def test_default_pixel_stream_retains_m0_geometry_and_cadence(self):
        m0map=ROOT/"build/m0/map.json"
        if not m0map.is_file():
            self.skipTest("Build M0 to compare its pixel stream")
        m0symbols=json.loads(m0map.read_text())["symbols"]["renderer"]
        reference=(ROOT/"build/m0/renderer.prg").read_bytes()[2:]
        for line in (128,64):
            with self.subTest(line=line):
                out=ROOT/f"build/m3/{line}"
                d=json.loads((out/"map.json").read_text())
                r=d["renderer_symbols"]
                actual=(out/"renderer.prg").read_bytes()[2:]
                self.assertEqual(r["render_line"],m0symbols["render_line"])
                self.assertEqual(r["pixel_stream"],m0symbols["pixel_stream"])
                self.assertEqual(r["pixel_stream_end"]-r["pixel_stream"],1900)
                self.assertEqual(actual[r["render_line"]-0xf000:],reference[m0symbols["render_line"]-0xf000:])


if __name__=="__main__":
    unittest.main()
