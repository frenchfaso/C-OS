"""Counter observations must share a scheduler boundary and resume on error."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from m3_ue2 import AutonomousTarget


class AdvancingTarget(AutonomousTarget):
    def __init__(self,fail=False):
        self.running=True
        self.chunks=100
        self.fail=fail

    def write(self,address,data):
        assert address==0xfe0d
        self.running=bool(data[0])

    def command(self,line):
        assert line=='wait 50'

    def read(self,address,length,physical=False):
        if self.fail:raise OSError('lost monitor connection')
        pair=bytearray(256)
        pair[96]=pair[224]=3
        pair[124:128]=pair[252:256]=self.chunks.to_bytes(4,'little')
        if self.running:self.chunks+=8
        return bytes(pair[address-0x500:address-0x500+length])


class CoherentJobSampling(unittest.TestCase):
    def test_running_separate_reads_skew_but_boundary_sample_is_coherent(self):
        target=AdvancingTarget()
        a=target.read(0x500,128);b=target.read(0x580,128)
        self.assertEqual(int.from_bytes(b[124:128],'little')-
                         int.from_bytes(a[124:128],'little'),8)
        a,b=target.pending_job_pair()
        self.assertEqual(a[124:128],b[124:128])
        self.assertEqual((a[96],b[96]),(3,3))
        self.assertTrue(target.running)

    def test_monitor_read_error_restores_scheduler_control(self):
        target=AdvancingTarget(fail=True)
        with self.assertRaisesRegex(OSError,'lost monitor connection'):
            target.pending_job_pair()
        self.assertTrue(target.running)


if __name__=='__main__':unittest.main()
