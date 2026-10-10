"""Independent checks of differential visibility and suspension diagnostics."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from m2_compare import compare_state, compare_memory, logical_bytes


def entry(metadata, index, tag, flags):
    for byte in range(3):
        metadata[index + byte * 16] = (tag >> (byte * 8)) & 255
    metadata[index + 64] = flags


class NativeVisibility(unittest.TestCase):
    def test_two_dirty_lines_overlay_without_flushing_physical_memory(self):
        metadata = bytearray(112)
        entry(metadata, 8, 0x40080, 3)
        entry(metadata, 9, 0x40100, 7)  # Busy eviction still owns old dirty bytes.
        cache = bytearray(1024)
        cache[126] = 0xa5
        cache[127] = 0xcd
        cache[128] = 0xab
        cache[129] = 0x5a
        raw = bytes([0xa5, 0x55, 0x66, 0x5a])
        expected = bytes([0xa5, 0xcd, 0xab, 0x5a])
        self.assertEqual(logical_bytes(0x400fe, raw, metadata, cache, 128), expected)
        differences = compare_memory([dict(address=0x400fe, data=expected)],
                                     {0x400fe: raw}, metadata, cache, 128, name="split")
        self.assertEqual(differences, 2)
        self.assertEqual(raw, bytes([0xa5, 0x55, 0x66, 0x5a]))

    def test_clean_and_invalid_lines_cannot_mask_a_bad_physical_byte(self):
        for flags in [0, 1, 2, 4]:
            metadata = bytearray(112)
            entry(metadata, 8, 0x40080, flags)
            cache = bytes([42]) * 512
            with self.assertRaisesRegex(ValueError, r"\$040080"):
                compare_memory([dict(address=0x40080, data=[42])],
                               {0x40080: b"\x00"}, metadata, cache, 64, name="guard")

    def test_duplicate_dirty_ownership_is_a_failure(self):
        metadata = bytearray(112)
        entry(metadata, 8, 0x40080, 3)
        entry(metadata, 9, 0x40080, 3)
        with self.assertRaisesRegex(ValueError, "Multiple dirty"):
            logical_bytes(0x40080, b"\x00", metadata, bytes(1024), 128)


class NativeSuspension(unittest.TestCase):
    def test_wait_preserves_effects_fuel_and_pending_identity(self):
        initial = bytearray(96)
        initial[28:31] = bytes([0, 0, 4])
        initial[34] = 3
        initial[91] = 1
        wait = bytearray(initial)
        wait[69] = 2
        compare_state(initial, wait, name="miss", wait=True)
        for changed in [0, 16, 28, 31, 34, 35, 43, 45, 79, 87, 90, 91]:
            corrupt = bytearray(wait)
            corrupt[changed] ^= 1
            with self.assertRaisesRegex(ValueError, "first divergent PC"):
                compare_state(initial, corrupt, name="miss", wait=True, opcode="ST16")

    def test_overflow_fault_retains_the_fourth_address_byte(self):
        expected = bytearray(96)
        expected[69:71] = bytes([5, 3])
        expected[74:76] = bytes([1, 1])  # $01000000, with address present.
        compare_state(expected, expected, name="overflow")
        observed = bytearray(expected)
        observed[74] = 0
        with self.assertRaisesRegex(ValueError, "state byte 74"):
            compare_state(expected, observed, name="overflow")


if __name__ == "__main__":
    unittest.main()
