import unittest
from pinrig_protocol import Command, CommandError
from tests.helpers import command


class ModelTests(unittest.TestCase):
    def test_defaults_and_verbatim_text(self):
        c = Command.parse(command('show_message', title=' T ', body=' B '))
        self.assertEqual(c.params['title'], ' T ')
        self.assertEqual(c.params['duration'], 8)
        self.assertEqual(Command.parse(c.to_dict()), c)

    def test_invalid_boundaries(self):
        values = [None, [], {}, command('bad'), command('set_state', state=[]),
                  command('show_message', title='x'*41, body='b'),
                  command('show_message', title='x', body=''),
                  command('show_message', title='x', body='b', requires_ack=1),
                  command('show_message', title='x', body='b', priority=True),
                  command('set_state', state='on_air', lease_seconds=float('nan')),
                  command('set_state', state='on_air', valid_for=float('inf')),
                  command('set_state', state='on_air', extra=True)]
        for value in values:
            with self.subTest(value=value), self.assertRaises(CommandError): Command.parse(value)

    def test_version_and_session(self):
        value = command('set_state', state='on_air'); value['version'] = True
        with self.assertRaises(CommandError): Command.parse(value)
        value['version'] = 1; del value['session']
        with self.assertRaises(CommandError): Command.parse(value)
