import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from PIL import Image, ImageDraw, ImageChops
from shared.artwork.pages import BACKGROUND, PageRenderer, _wrap, _font


class PageTests(unittest.TestCase):
    def test_unknown_uses_packaged_logo_and_exact_small_caption(self):
        pages = PageRenderer()
        self.assertTrue(pages.logo_path.is_absolute())
        self.assertTrue(pages.logo_path.is_file())
        image = pages.compose('unknown', None, 'Host lease expired')
        self.assertIsNotNone(ImageChops.difference(
            image.crop((0, 0, 480, 275)), Image.new('RGB', (480, 275), BACKGROUND)
        ).getbbox())
        expected = Image.new('RGB', (480, 40), BACKGROUND)
        draw = ImageDraw.Draw(expected)
        font = _font(20)
        caption = 'Stream Status Unknown'
        left, top, right, bottom = draw.textbbox((0, 0), caption, font=font)
        draw.text(((480 - (right - left)) // 2 - left,
                   (32 - (bottom - top)) // 2 - top), caption,
                  font=font, fill='#f5f1e8')
        self.assertIsNone(ImageChops.difference(image.crop((0, 280, 480, 320)), expected).getbbox())

    def test_unknown_preserves_logo_aspect_ratio_and_transparency(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'logo.png'
            logo = Image.new('RGBA', (200, 100), (255, 0, 255, 0))
            ImageDraw.Draw(logo).rectangle((20, 10, 179, 89), fill=(255, 0, 255, 255))
            logo.save(path)
            image = PageRenderer(path).compose('unknown', None, '')
        self.assertEqual(image.getpixel((40, 12)), Image.new('RGB', (1, 1), BACKGROUND).getpixel((0, 0)))
        points = [(x, y) for y in range(275) for x in range(480)
                  if image.getpixel((x, y)) == (255, 0, 255)]
        self.assertTrue(points)
        xs, ys = zip(*points)
        self.assertAlmostEqual((max(xs) - min(xs)) / (max(ys) - min(ys)), 2, delta=.03)
        self.assertAlmostEqual((min(xs) + max(xs)) / 2, 239.5, delta=1)

    def test_unknown_is_static_full_screen_and_does_not_expose_diagnostics(self):
        pages = PageRenderer()
        original = pages.compose('unknown', None, 'Waiting', 320, 0)
        alternate = pages.compose('unknown', None, 'Host lease expired', 320, 10)
        self.assertEqual(original.tobytes(), alternate.tobytes())
        alternate.paste('red', (0, 0, 480, 320))
        self.assertEqual(original.tobytes(), pages.compose('unknown', None, '').tobytes())

    def test_unknown_shows_the_same_message_card_as_known_states(self):
        pages = PageRenderer()
        message = {'title': 'BOOTH', 'body': 'Please wait for the next player.'}
        unknown = pages.compose('unknown', message, 'OBS unavailable', 188)
        known = pages.compose('on_air', message, '', 188)
        self.assertEqual(unknown.crop((0, 188, 480, 320)).tobytes(),
                         known.crop((0, 188, 480, 320)).tobytes())
        self.assertNotEqual(unknown.tobytes(), pages.compose('unknown', None, '').tobytes())
        self.assertEqual(unknown.tobytes(),
                         pages.compose('unknown', message, 'Different diagnostic', 188, 10).tobytes())

    def test_missing_logo_is_reported(self):
        with TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                PageRenderer(Path(directory) / 'missing.png').compose('unknown', None, '')

    def test_all_states_and_layouts(self):
        pages = PageRenderer()
        for state in ('on_air', 'camera_active', 'camera_inactive', 'unknown'):
            for height in (188, 240, 320):
                image = pages.compose(state, {'title': 'T'*40, 'body': 'B'*240}, 'Waiting', height, 1.)
                self.assertEqual(image.size, (480, 320))
                self.assertEqual(image.mode, 'RGB')

    def test_housing_animates_but_lettering_is_steady(self):
        pages = PageRenderer()
        a, b = pages.on_air(.78), pages.on_air(1.)
        self.assertNotEqual(a.tobytes(), b.tobytes())
        letters = [(x,y) for y in range(320) for x in range(480) if a.getpixel((x,y)) == (255,244,204)]
        self.assertGreater(len(letters), 100)
        self.assertTrue(all(b.getpixel(p) == (255,244,204) for p in letters))

    def test_all_signs_animate(self):
        p = PageRenderer()
        for state in ('on_air', 'camera_active', 'camera_inactive'):
            self.assertNotEqual(p.compose(state, None, '', 320, 0).tobytes(),
                                p.compose(state, None, '', 320, 1).tobytes())

    def test_overflow_ellipsized_at_fixed_font_size(self):
        draw = ImageDraw.Draw(Image.new('RGB', (480,320)))
        font = _font(22)
        lines = _wrap(draw, 'X'*240, font, 452, 3)
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[-1].endswith('…'))
        self.assertTrue(all(draw.textlength(line, font=font) <= 452 for line in lines))


class TwitchSettingsPageTests(unittest.TestCase):
    def test_connect_and_persist_toggle_through_dashboard(self):
        import json
        from stream.chat import Chat
        from stream.overview import Status, handler
        from stream.twitch import Twitch
        from shared.jobs import Jobs
        from tests.helpers import Clock
        from tests.test_integrations import FakeConnection

        rigs = [{'id': 'rig1', 'url': 'http://rig1'}]
        clock = Clock()

        def twitch_http(url, **kwargs):
            if url.endswith('/device'):
                return {'verification_uri': 'https://www.twitch.tv/activate',
                        'user_code': 'APPROVE', 'device_code': 'private-device-code',
                        'interval': 5, 'expires_in': 300}
            if url.endswith('/token'):
                return {'access_token': 'private-access-token', 'refresh_token': 'private-refresh-token'}
            if url.endswith('/validate'):
                return {'client_id': 'client', 'scopes': ['user:read:chat'], 'user_id': '123',
                        'login': 'pinball', 'expires_in': 3600}
            self.fail(url)

        with TemporaryDirectory() as directory:
            state = Path(directory)
            twitch = Twitch('client', state, Chat(rigs), clock=clock, http=twitch_http)
            page = handler(Status(rigs), Jobs(state / 'jobs.json'), None, twitch=twitch)

            def request(path, value=None):
                payload = b'' if value is None else json.dumps(value).encode()
                method = 'GET' if value is None else 'POST'
                raw = (f'{method} {path} HTTP/1.0\r\nHost: localhost\r\n'
                       f'Content-Type: application/json\r\nContent-Length: {len(payload)}\r\n\r\n').encode()
                socket = FakeConnection(raw + payload)
                page(socket, ('127.0.0.1', 0), object())
                head, body = socket.output.getvalue().split(b'\r\n\r\n', 1)
                self.assertEqual(int(head.split()[1]), 200, body)
                return body

            self.assertIn(b'Send test card', request('/'))
            self.assertTrue(twitch.chat.targets['rig1'].enabled)
            request('/api/twitch', {'action': 'connect'})
            body = request('/api/status')
            self.assertIn(b'APPROVE', body)
            self.assertNotIn(b'private-device-code', body)
            clock.advance(5)
            twitch._poll_device(twitch.device, twitch.generation)
            request('/api/twitch', {'action': 'toggle', 'rig': 'rig1', 'enabled': False})
            self.assertEqual((state / 'twitch-auth.json').stat().st_mode & 0o777, 0o600)
            restart = Twitch('client', state, Chat(rigs))
            self.assertEqual(restart.snapshot()['channel'], 'pinball')
            self.assertFalse(restart.chat.targets['rig1'].enabled)
            self.assertNotIn(b'private-access-token', request('/api/status'))
            request('/api/twitch', {'action': 'disconnect'})
            self.assertFalse((state / 'twitch-auth.json').exists())
            self.assertFalse(Twitch('client', state, Chat(rigs)).chat.targets['rig1'].enabled)
