# SPDX-License-Identifier: MPL-2.0
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cast_audio_lab.backend import MediaMetadata
from cast_audio_lab.cast_output import CastAudioBackend
from cast_audio_lab.output_registry import validate_output_target


class FakeMedia:
    def __init__(self):
        self.calls = []
        self.status = SimpleNamespace(player_state="UNKNOWN", adjusted_current_time=0, idle_reason=None)
    def play_media(self, url, content_type, **kwargs): self.calls.append(("load", url, content_type, kwargs))
    def play(self): self.calls.append(("play",))
    def pause(self): self.calls.append(("pause",))
    def seek(self, position): self.calls.append(("seek", position))


class FakeCast:
    def __init__(self):
        self.media_controller = FakeMedia()
        self.status = SimpleNamespace(volume_level=0.4, volume_muted=False, app_id="CC1AD845")
        self.socket_client = SimpleNamespace(is_connected=True)
        self.calls = []
    def set_volume(self, level): self.calls.append(("volume", level))
    def set_volume_muted(self, muted): self.calls.append(("mute", muted))
    def quit_app(self): self.calls.append(("quit",))
    def disconnect(self, timeout): self.calls.append(("disconnect",))


class FakeRelay:
    def __init__(self, host, ffmpeg="ffmpeg"):
        self.host, self.calls = host, []
    async def stream(self, url, supported, start, duration):
        self.calls.append(("stream", url, start, duration))
        return "http://192.168.0.107:5000/stream/x.mp3", "audio/mpeg", "mp3-cbr"
    async def prepare(self, url, content_type, supported):
        self.calls.append(("prepare", url))
        return "http://192.168.0.107:5000/x.mp3", "audio/mpeg"
    async def close(self): self.calls.append(("close",))


class CastOutputTests(unittest.IsolatedAsyncioTestCase):
    def make(self):
        cast, relays = FakeCast(), []
        def relay(host, ffmpeg="ffmpeg"):
            relays.append(FakeRelay(host)); return relays[-1]
        backend = CastAudioBackend("192.168.0.102", cast_factory=lambda h, p: cast, relay_factory=relay)
        return backend, cast, relays

    async def test_hls_is_streamed_through_the_relay_with_metadata(self):
        backend, cast, relays = self.make()
        await backend.set_metadata(MediaMetadata(title="Set", artist="DJ", artwork_url="http://a/i.jpg", duration=3600))
        try:
            await backend.load("https://cdn/playlist.m3u8", "audio/mpegurl", True, 120)
            self.assertEqual(relays[0].host, "192.168.0.102")
            self.assertEqual(relays[0].calls, [("stream", "https://cdn/playlist.m3u8", 120, 3600)])
            _, url, mime, kwargs = cast.media_controller.calls[0]
            self.assertEqual((url, mime), ("http://192.168.0.107:5000/stream/x.mp3", "audio/mpeg"))
            self.assertIsNone(kwargs["current_time"])  # the relay already starts at 120 s
            self.assertEqual(kwargs["metadata"]["artist"], "DJ")
            self.assertEqual(kwargs["metadata"]["images"], [{"url": "http://a/i.jpg"}])
            cast.media_controller.status = SimpleNamespace(player_state="PLAYING", adjusted_current_time=5, idle_reason=None)
            await asyncio.sleep(1.2)
            status = backend.status()
            self.assertEqual(status.state, "PLAYING")
            self.assertAlmostEqual(status.current_time, 125, delta=1)
        finally:
            await backend.shutdown()
        self.assertIn(("quit",), cast.calls)
        self.assertIn(("close",), relays[0].calls)

    async def test_lan_mp3_is_sent_directly_and_seek_uses_the_device(self):
        backend, cast, relays = self.make()
        try:
            await backend.load("http://192.168.0.50/a.mp3", "audio/mpeg", True, 0)
            self.assertEqual(relays, [])
            await backend.seek(30)
            self.assertIn(("seek", 30), cast.media_controller.calls)
        finally:
            await backend.shutdown()

    async def test_finished_takeover_and_stuck_buffering_end_the_session(self):
        backend, cast, _ = self.make()
        try:
            await backend.load("http://192.168.0.50/a.mp3", "audio/mpeg", True, 0)
            cast.media_controller.status = SimpleNamespace(player_state="PLAYING", adjusted_current_time=1, idle_reason=None)
            await asyncio.sleep(1.2)
            cast.status.app_id = "CC32E753"
            await asyncio.sleep(1.2)
            self.assertEqual((backend.status().state, backend.status().idle_reason), ("IDLE", "INTERRUPTED"))
            cast.status.app_id = "CC1AD845"
            with patch("cast_audio_lab.cast_output.BUFFERING_TIMEOUT", 0):
                cast.media_controller.status = SimpleNamespace(player_state="UNKNOWN", adjusted_current_time=0, idle_reason=None)
                await backend.load("http://192.168.0.50/a.mp3", "audio/mpeg", True, 0)
                await asyncio.sleep(1.2)
            self.assertEqual(backend.status().idle_reason, "ERROR")
            cast.media_controller.status = SimpleNamespace(player_state="PLAYING", adjusted_current_time=1, idle_reason=None)
            await backend.load("http://192.168.0.50/a.mp3", "audio/mpeg", True, 0)
            await asyncio.sleep(1.2)
            cast.media_controller.status = SimpleNamespace(player_state="IDLE", adjusted_current_time=0, idle_reason="FINISHED")
            await asyncio.sleep(1.2)
            self.assertEqual(backend.status().idle_reason, "FINISHED")
        finally:
            await backend.shutdown()

    async def test_volume_reads_and_writes_the_device(self):
        backend, cast, _ = self.make()
        self.assertEqual(await backend.read_volume(), (0.4, False))
        await backend.set_volume(1.5, True)
        self.assertEqual(cast.calls[:2], [("volume", 1.0), ("mute", True)])
        await backend.shutdown()

    def test_target_validation(self):
        self.assertEqual(validate_output_target("cast", {"host": "192.168.0.102"}),
                         {"host": "192.168.0.102", "port": 8009, "protocol": "cast", "device_id": "192.168.0.102"})
        for bad in ({"host": "8.8.8.8"}, {"host": "192.168.0.102", "port": 0}, {"host": "192.168.0.102", "extra": 1}):
            with self.assertRaises(ValueError):
                validate_output_target("cast", bad)
