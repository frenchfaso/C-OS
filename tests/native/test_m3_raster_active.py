"""Independent classifier inputs and fail-closed extraction checks."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from check_m3_raster_active import map_io, vectors


class ActiveRasterVectors(unittest.TestCase):
    def test_every_pal_line_and_both_torn_directions(self):
        rows=[tuple(vectors()[i:i+4]) for i in range(0,len(vectors()),4)]
        self.assertEqual(len(rows),824)
        self.assertEqual([row[3] for row in rows[:312]],
                         [int(60<=line<260) for line in range(312)])
        self.assertEqual(rows[59],(0,59,0,0))
        self.assertEqual(rows[60],(0,60,0,1))
        self.assertEqual(rows[259],(128,3,128,1))
        self.assertEqual(rows[260],(128,4,128,0))
        self.assertEqual(rows[312:568],[(0,low,128,1) for low in range(256)])
        self.assertEqual(rows[568:],[(128,low,0,0) for low in range(256)])

    def test_old_incoherent_classifier_is_rejected(self):
        old=bytes.fromhex('2c 11 d0 30 08 ad 12 d0 c9 3c 90 08 '
                          '38 60 ad 12 d0 c9 04 90 02 18 60 38 60')
        with self.assertRaisesRegex(ValueError,'confirming high reads'):
            map_io(old)

    def test_unexpected_absolute_operand_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'absolute read operand'):
            map_io(bytes.fromhex('ad 13 d0 60'))

    def test_unknown_opcode_is_rejected_before_it_can_hide_a_patch_site(self):
        with self.assertRaisesRegex(ValueError,'Unexpected classifier opcode'):
            map_io(bytes.fromhex('ea 2c 11 d0 60'))


if __name__=='__main__':unittest.main()
