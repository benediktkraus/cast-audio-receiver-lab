# SPDX-License-Identifier: MPL-2.0
"""Group output: one Cast session played on several outputs at once (e.g. a DLNA and a Cast speaker).

The first member leads: its status is the group's status. Followers are started
together with it; a failing follower is logged and dropped from that command, so
one unreachable speaker never stops the others. Each member pulls its own stream,
so playback is started simultaneously but not sample-synchronised.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from .backend import NullAudioBackend

LOGGER = logging.getLogger(__name__)
MEMBER_BACKENDS = ("dlna", "cast")


def create_member(member: dict, ffmpeg: str):
    target = member["target"]
    if member["backend"] == "dlna":
        from .dlna import DlnaAudioBackend
        return DlnaAudioBackend(target["description_url"], ffmpeg=ffmpeg)
    from .cast_output import CastAudioBackend
    return CastAudioBackend(target["host"], target.get("port", 8009), ffmpeg=ffmpeg)


class GroupAudioBackend(NullAudioBackend):
    def __init__(self, members):
        super().__init__()
        if not members:
            raise ValueError("a group needs members")
        self.members = list(members)
        self.leader = self.members[0]
        self.leader.add_status_listener(self._leader_status)

    def _leader_status(self, status):
        self._status.state = status.state
        self._status.url = status.url
        self._status.content_type = status.content_type
        self._status.idle_reason = status.idle_reason
        self._status.volume, self._status.muted = status.volume, status.muted
        self._set_position(status.current_time)
        self._emit_status()

    async def _all(self, name, *args):
        results = await asyncio.gather(*(getattr(m, name)(*args) for m in self.members), return_exceptions=True)
        failed = [r for r in results if isinstance(r, BaseException)]
        for member, result in zip(self.members, results):
            if isinstance(result, BaseException):
                LOGGER.warning("group member %s command=%s failed: %s", type(member).__name__, name, result)
        if len(failed) == len(results):
            raise RuntimeError(f"all group members failed {name}")
        return results

    async def set_metadata(self, metadata):
        await super().set_metadata(metadata)
        await self._all("set_metadata", metadata)

    async def load(self, url, content_type, autoplay, start_time):
        await self._all("load", url, content_type, autoplay, start_time)

    async def play(self):
        await self._all("play")

    async def pause(self):
        await self._all("pause")

    async def seek(self, position):
        await self._all("seek", position)

    async def stop(self):
        await self._all("stop")

    async def read_volume(self):
        return await self.leader.read_volume()

    async def initialize_volume(self):
        # Keep each speaker's own level; a group must not reset every room to one value.
        await self._all("initialize_volume")
        self._status.volume, self._status.muted = self.leader.status().volume, self.leader.status().muted
        self._emit_status()

    async def set_volume(self, level, muted):
        # Scale every speaker by the leader's change so the rooms keep their balance.
        base = self.leader.status().volume
        ratio = level / base if base > 0 else None
        await asyncio.gather(*(
            m.set_volume(max(0.0, min(1.0, m.status().volume * ratio if ratio is not None else level)), muted)
            for m in self.members), return_exceptions=True)
        await super().set_volume(level, muted)

    def status(self):
        status = self.leader.status()
        status.volume, status.muted = self._status.volume, self._status.muted
        return status

    async def shutdown(self):
        await asyncio.gather(*(m.shutdown() for m in self.members), return_exceptions=True)


def load_group_target(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or not isinstance(value.get("members"), list):
        raise ValueError("invalid group target file")
    return value
