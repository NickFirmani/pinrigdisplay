import unittest
from pinrig_producers.policy import Observation, resolve, Selection, notice


class ProducerTests(unittest.TestCase):
    def resolve(self, observations):
        return resolve(observations, rig='rig1', required_sources={'obs', 'video'}, now=10, max_age=3).state
    def o(self, source, live, local, rig='rig1', time=10): return Observation(source, rig, time, live, local)

    def test_other_rig_cannot_make_live(self):
        self.assertEqual(self.resolve([self.o('obs', True, True, rig='rig2')]), 'unknown')
    def test_live_preview_recording_local_inactive_and_missing(self):
        for live, local, expected in [(True, False, 'on_air'), (False, True, 'camera_active'),
                                     (False, False, 'camera_inactive'), (None, True, 'unknown'),
                                     (False, None, 'unknown')]:
            with self.subTest(expected=expected):
                self.assertEqual(self.resolve([self.o('obs', live, local), self.o('video', False, False)]), expected)
    def test_stale_missing_and_recovery(self):
        obs = [self.o('obs', False, False, time=1), self.o('video', False, False)]
        self.assertEqual(self.resolve(obs), 'unknown')
        obs.append(self.o('obs', False, True))
        self.assertEqual(self.resolve(obs), 'camera_active')
    def test_conflicting_equal_time_is_unknown(self):
        self.assertEqual(self.resolve([self.o('obs', False, False), self.o('obs', True, True),
                                      self.o('video', False, False)]), 'unknown')
    def test_manual_precedence_and_moderation(self):
        s = Selection(); self.assertIsNone(s.value)
        s.automatic='game1'; s.manual='game2'; s.automatic='game3'
        self.assertEqual(s.value, 'game2'); s.manual=None; self.assertEqual(s.value, 'game3')
        self.assertIsNone(notice(title='T', body='B', observed_at=1, now=10, max_age=2))
        self.assertIsNone(notice(title='T', body='B', observed_at=10, now=10, max_age=2, moderated=False))
