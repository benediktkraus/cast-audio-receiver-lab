# SPDX-License-Identifier: MPL-2.0
"""Google Cast output: plays through the target's built-in Default Media Receiver.

Some Cast devices (e.g. a Nest Hub) fail to launch music apps such as SoundCloud
or Spotify while their Default Media Receiver works. This output resolves the
stream here, relays it as plain HTTP audio on the LAN and only asks the device
to play a URL, so the device's own app runtime is never involved.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path

from .backend import NullAudioBackend
from .dlna import should_stream

LOGGER = logging.getLogger(__name__)

# Formats every Default Media Receiver decodes; anything else is transcoded by the relay.
CAST_AUDIO_TYPES = {"audio/mpeg", "audio/mp4", "audio/aac", "audio/ogg", "audio/webm", "audio/flac", "audio/wav"}
BUFFERING_TIMEOUT = 20


def _connect(host: str, port: int):
    import pychromecast

    cast = pychromecast.get_chromecast_from_host((host, port, uuid.uuid4(), None, None))
    cast.wait(timeout=10)
    return cast


class CastAudioBackend(NullAudioBackend):
    def __init__(self, host: str, port: int = 8009, *, cast_factory=_connect, relay_factory=None, ffmpeg="ffmpeg"):
        super().__init__()
        self.host = host
        self.port = port
        self._cast_factory = cast_factory
        self._cast = None
        self._relay = None
        self._relay_factory = relay_factory
        self._ffmpeg = ffmpeg
        self._poll_task = None
        self._load_started = 0.0
        self._seen_playing = False
        self._stream_offset = 0.0
        self._stream_source = None  # (url, content_type) of a progressive stream

    async def _device(self):
        if self._cast is None or not self._cast.socket_client.is_connected:
            self._cast = await asyncio.to_thread(self._cast_factory, self.host, self.port)
        return self._cast

    async def _call(self, function, *args, **kwargs):
        try:
            return await asyncio.to_thread(function, *args, **kwargs)
        except Exception as error:
            LOGGER.warning("Cast command=%s failed: %s", getattr(function, "__name__", "?"), type(error).__name__)
            raise RuntimeError(f"Cast command failed ({type(error).__name__})") from None

    async def load(self, url, content_type, autoplay, start_time):
        await self._cancel_polling()
        cast = await self._device()
        self._status.state = "BUFFERING"
        self._status.url = url
        self._status.content_type = content_type
        self._status.idle_reason = None
        self._set_position(max(0, start_time))
        self._seen_playing = False
        self._emit_status()
        from .dlna_media import DlnaMediaRelay, needs_relay

        self._stream_offset = 0.0
        self._stream_source = None
        if needs_relay(url, content_type, CAST_AUDIO_TYPES):
            if self._relay is None:
                self._relay = (self._relay_factory or DlnaMediaRelay)(self.host, ffmpeg=self._ffmpeg)
            if should_stream(content_type, self.metadata.duration):
                self._stream_source = (url, content_type)
                url, content_type, _codec = await self._relay.stream(
                    url, CAST_AUDIO_TYPES, max(0, start_time), self.metadata.duration)
                self._stream_offset, start_time = max(0, start_time), 0
            else:
                url, content_type = await self._relay.prepare(url, content_type, CAST_AUDIO_TYPES)
        metadata = {"metadataType": 3, "title": self.metadata.title or "Cast audio"}
        if self.metadata.artist:
            metadata["artist"] = self.metadata.artist
        if self.metadata.album:
            metadata["albumName"] = self.metadata.album
        if self.metadata.artwork_url:
            metadata["images"] = [{"url": self.metadata.artwork_url}]
        self._load_started = time.monotonic()
        await self._call(
            cast.media_controller.play_media, url, content_type,
            current_time=start_time or None, autoplay=autoplay, metadata=metadata,
        )
        LOGGER.info("Cast load mime=%s offset=%.1f", content_type, self._stream_offset)
        self._status.state = "BUFFERING" if autoplay else "PAUSED"
        self._emit_status()
        self._start_polling()

    async def play(self):
        await self._call((await self._device()).media_controller.play)
        self._status.idle_reason = None
        self._start_polling()

    async def pause(self):
        await self._call((await self._device()).media_controller.pause)
        await super().pause()

    async def seek(self, position):
        if self._stream_source is not None:
            # A progressive stream has no byte ranges: restart it at the target.
            await self.load(*self._stream_source, True, max(0, position))
            await super().seek(position)
            return
        await self._call((await self._device()).media_controller.seek, max(0, position))
        await super().seek(position)

    async def read_volume(self):
        status = (await self._device()).status
        return (status.volume_level, status.volume_muted) if status else None

    async def set_volume(self, level, muted):
        cast = await self._device()
        await self._call(cast.set_volume, max(0.0, min(1.0, level)))
        await self._call(cast.set_volume_muted, bool(muted))
        await super().set_volume(level, muted)

    async def stop(self):
        await self._cancel_polling()
        try:
            if self._cast is not None:
                # Quit, not only stop: the device returns to its idle screen.
                await asyncio.to_thread(self._cast.quit_app)
        except Exception:
            LOGGER.debug("Cast quit failed", exc_info=True)
        finally:
            if self._relay is not None:
                relay, self._relay = self._relay, None
                await relay.close()
            await super().stop()

    async def shutdown(self):
        await self.stop()
        if self._cast is not None:
            cast, self._cast = self._cast, None
            await asyncio.to_thread(cast.disconnect, 3)

    def _start_polling(self):
        if self._poll_task is None or self._poll_task.done():
            self._poll_task = asyncio.create_task(self._poll())

    async def _cancel_polling(self):
        task, self._poll_task = self._poll_task, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def _finish(self, reason):
        self._status.state = "IDLE"
        self._status.idle_reason = reason
        self._emit_status()

    async def _poll(self):
        while self._cast is not None and self._status.url:
            await asyncio.sleep(1)
            media = self._cast.media_controller.status
            cast_status = self._cast.status
            if cast_status is not None:
                self._status.volume = float(cast_status.volume_level)
                self._status.muted = bool(cast_status.volume_muted)
                if self._seen_playing and cast_status.app_id != "CC1AD845":
                    # Another sender took the device over.
                    return self._finish("INTERRUPTED")
            state = media.player_state
            if state in {"PLAYING", "PAUSED"}:
                self._seen_playing = True
                self._set_position(float(media.adjusted_current_time or 0) + self._stream_offset)
                self._status.state = state
                self._emit_status()
            elif state == "BUFFERING" or not self._seen_playing:
                if time.monotonic() - self._load_started >= BUFFERING_TIMEOUT:
                    return self._finish("ERROR")
                if state == "BUFFERING" and self._status.state != "BUFFERING":
                    self._status.state = "BUFFERING"
                    self._emit_status()
            elif state == "IDLE":
                reason = media.idle_reason or "FINISHED"
                return self._finish(reason if reason in {"FINISHED", "ERROR", "INTERRUPTED"} else "CANCELLED")


def load_cast_target(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or not isinstance(value.get("host"), str):
        raise ValueError("invalid Cast target file")
    return value
