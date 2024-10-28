import unittest

from snap_tracker.split_rates import get_split_rate


class TestSplitRates(unittest.TestCase):
    def test_infinity_splits(self):
        with self.subTest(f"Split #0"):
            rates = get_split_rate(0)
            self.assertEqual(sum(rates.finish.values()), 1)
            self.assertEqual(sum(rates.flare.values()), 0)

        for split in range(1, 7):
            with self.subTest(f"Split #{split}"):
                rates = get_split_rate(split)
                self.assertEqual(sum(rates.finish.values()), 1)
                self.assertEqual(sum(rates.flare.values()), 1)


if __name__ == '__main__':
    unittest.main()
