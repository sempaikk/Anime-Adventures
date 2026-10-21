import unittest

from timing import PausableTimer


class TimingTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.timer = PausableTimer(45, lambda: self.now)

    def test_pause_freezes_time_across_large_wall_time_gap(self):
        self.now += 12
        self.assertTrue(self.timer.pause())
        self.assertEqual(self.timer.remaining, 33)
        self.assertIsNone(self.timer.deadline)
        self.now += 10000
        self.assertEqual(self.timer.remaining, 33)
        self.assertTrue(self.timer.resume())
        self.assertEqual(self.timer.remaining, 33)
        self.now += 32
        self.assertEqual(self.timer.remaining, 1)
        self.now += 1
        self.assertEqual(self.timer.remaining, 0)

    def test_multiple_pause_resume_cycles_do_not_reset_or_consume_budget(self):
        for _ in range(4):
            self.now += 5
            self.assertTrue(self.timer.pause())
            self.assertFalse(self.timer.pause())
            self.now += 50
            self.assertTrue(self.timer.resume())
            self.assertFalse(self.timer.resume())
        self.assertEqual(self.timer.remaining, 25)

    def test_expired_timer_cannot_be_resurrected_by_pause(self):
        self.now += 46
        self.assertFalse(self.timer.pause())
        self.assertFalse(self.timer.resume())
        self.assertFalse(self.timer.paused)
        self.assertEqual(self.timer.remaining, 0)

    def test_zero_or_negative_duration_is_rejected(self):
        for duration in (0, -1):
            with self.assertRaises(ValueError):
                PausableTimer(duration)
