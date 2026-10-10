"""Independent literal checks for M0 artifacts; UE2 supplies execution tests."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import m0


class PublicationContract(unittest.TestCase):
    def test_publish_failure_restores_previous_complete_set(self):
        with tempfile.TemporaryDirectory() as temporary:
            stage=Path(temporary)/"stage"
            out=Path(temporary)/"out"
            stage.mkdir()
            out.mkdir()
            (stage/"a.prg").write_bytes(b"new a")
            (stage/"b.prg").write_bytes(b"new b")
            (out/"a.prg").write_bytes(b"previous a")
            replace=m0.os.replace
            def fail_second(source,destination):
                if Path(source).name=="b.prg":
                    raise OSError("injected publication failure")
                replace(source,destination)
            with patch.object(m0.os,"replace",side_effect=fail_second):
                with self.assertRaises(OSError):
                    m0.publish(stage,out)
            self.assertEqual((out/"a.prg").read_bytes(),b"previous a")
            self.assertFalse((out/"b.prg").exists())


class PatternContract(unittest.TestCase):
    def test_literal_geometry_edges_and_nibble_order(self):
        columns=m0.pattern()
        self.assertEqual(len(columns),40960)
        self.assertEqual(columns[0],0x11)
        self.assertEqual(columns[199],0x11)
        self.assertEqual(columns[1],0x02)
        self.assertEqual(columns[159*256+1],0x3f)
        self.assertEqual(columns[40*256+100],0x01)
        self.assertEqual(columns[140*256+30],0xee)
        self.assertEqual(columns[200:256],bytes(56))
        self.assertEqual(hashlib.sha256(columns).hexdigest(),
                         "a0d78a842e0f23fd183d12017a7099157e0c55fddd7f0260301748f6d42e3b79")


class AssembledContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (ROOT/"build/m0/map.json").is_file():
            raise unittest.SkipTest("Build native artifacts with scripts/m0.py first")
        cls.map=json.loads((ROOT/"build/m0/map.json").read_text())
        cls.renderer=(ROOT/"build/m0/renderer.prg").read_bytes()[2:]

    def test_independent_pixel_machine_bytes(self):
        symbols=self.map["symbols"]["renderer"]
        start=symbols["pixel_stream"]-0xf000
        # Pair 0 uses LDX immediate, then STX border, LDA $0200,X, STA border.
        self.assertEqual(self.renderer[start:start+11],
                         bytes.fromhex("a2 00 8e 20 d0 bd 00 02 8d 20 d0"))
        # Pair 1 reads framebuffer column 1 ($4100), indexed by the row.
        self.assertEqual(self.renderer[start+11:start+23],
                         bytes.fromhex("be 00 41 8e 20 d0 bd 00 02 8d 20 d0"))
        # Last column is $EF00. The last high pixel has the extra NOPs.
        end=symbols["pixel_stream_end"]-0xf000
        self.assertEqual(self.renderer[end-12:end+11],
                         bytes.fromhex("be 00 ef 8e 20 d0 bd 00 02 8d 20 d0 ea ea a9 00 8d 20 d0 60"))
        self.assertEqual(end-start,1900)
        self.assertEqual(self.map["renderer_pixel_cpu_cycles"],2520)

    def test_map_covers_64k_and_never_claims_io_as_ram(self):
        sections=self.map["sections"]
        self.assertEqual(sections[0]["first"],0)
        self.assertEqual(sections[-1]["last"],65535)
        for first,second in zip(sections,sections[1:]):
            self.assertEqual(first["last"]+1,second["first"])
        for section in sections:
            self.assertLessEqual(section["assembled_bytes"]+section["runtime_bytes"],section["reserved_bytes"])
        self.assertEqual(self.map["directly_usable_non_framebuffer_ram"],20480)
        self.assertEqual(self.map["app_reu_available"],16515072)
        self.assertEqual(self.map["system_reu_reservation"],262144)
        self.assertEqual(self.map["numeric_future_target_within_resident_budget"],4096)

    def test_pack_and_bootstrap_safe_ranges(self):
        image=(ROOT/"build/m0/diagnostic.reu").read_bytes()
        self.assertEqual(len(image),16777216)
        self.assertEqual(image[:8],b"COSREU01")
        self.assertEqual(int.from_bytes(image[8:12],"little"),self.map["build_tag"])
        self.assertEqual(image[12:16],bytes.fromhex("02 00 00 00"))
        self.assertEqual(image[0x1000:0x1000+len(self.renderer)],self.renderer)
        prg=(ROOT/"build/m0/probe.prg").read_bytes()
        self.assertEqual(prg[:2],bytes.fromhex("01 08"))
        self.assertLessEqual(0x801+len(prg)-2,0x4000)
        self.assertLessEqual(0xf000+len(self.renderer),0xfa00)


if __name__=="__main__":
    unittest.main()
