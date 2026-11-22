# SPDX-License-Identifier: MPL-2.0
import unittest

from cast_audio_lab.backend import MediaMetadata, NullAudioBackend
from cast_audio_lab.group_output import GroupAudioBackend
from cast_audio_lab.output_registry import validate_output_target
from cast_audio_lab.routes import Route, validate_routes

DLNA = {"backend": "dlna", "target": {"description_url": "http://192.168.0.115:49154/MediaRenderer/desc.xml"}}
CAST = {"backend": "cast", "target": {"host": "192.168.0.102"}}


class Member(NullAudioBackend):
    def __init__(self, volume, fail=False):
        super().__init__()
        self._status.volume, self.fail, self.calls = volume, fail, []
    async def load(self, *args):
        self.calls.append(("load",) + args)
        if self.fail:
            raise RuntimeError("offline")
        await super().load(*args)
    async def set_volume(self, level, muted):
        self.calls.append(("volume", round(level, 3)))
        await super().set_volume(level, muted)


class GroupOutputTests(unittest.IsolatedAsyncioTestCase):
    async def test_commands_reach_all_members_and_a_failing_follower_is_tolerated(self):
        leader, follower = Member(0.4), Member(0.2, fail=True)
        group = GroupAudioBackend([leader, follower])
        await group.set_metadata(MediaMetadata(title="Set"))
        await group.load("http://x/a.mp3", "audio/mpeg", True, 30)
        self.assertEqual(follower.calls[0], ("load", "http://x/a.mp3", "audio/mpeg", True, 30))
        self.assertEqual(leader.metadata.title, "Set")
        self.assertEqual(group.status().state, "PLAYING")
        self.assertAlmostEqual(group.status().current_time, 30, delta=1)

    async def test_all_members_failing_raises(self):
        group = GroupAudioBackend([Member(0.4, fail=True), Member(0.2, fail=True)])
        with self.assertRaises(RuntimeError):
            await group.load("http://x/a.mp3", "audio/mpeg", True, 0)

    async def test_volume_change_keeps_the_room_balance(self):
        leader, follower = Member(0.4), Member(0.2)
        group = GroupAudioBackend([leader, follower])
        await group.set_volume(0.2, False)
        self.assertEqual((leader.calls[-1], follower.calls[-1]), (("volume", 0.2), ("volume", 0.1)))

    def test_group_target_and_coexistence_with_member_routes(self):
        target = validate_output_target("group", {"members": [DLNA, CAST]})
        self.assertEqual([m["backend"] for m in target["members"]], ["dlna", "cast"])
        routes = validate_routes([
            {"id": "00000000-0000-4000-8000-00000000000a", "name": "Yamaha", "backend": "dlna", "target": DLNA["target"]},
            {"id": "00000000-0000-4000-8000-00000000000b", "name": "Küche", "backend": "cast", "target": CAST["target"]},
            {"id": "00000000-0000-4000-8000-00000000000c", "name": "Wohnung", "backend": "group", "target": {"members": [DLNA, CAST]}},
        ])
        self.assertEqual(routes[2].public()["target"]["members"][1], {"backend": "cast", "device_id": "192.168.0.102"})
        for bad in ({"members": [DLNA]}, {"members": [DLNA, DLNA]},
                    {"members": [DLNA, {"backend": "mpv", "target": None}]}):
            with self.assertRaises(ValueError):
                validate_output_target("group", bad)
        Route.parse({"id": "00000000-0000-4000-8000-00000000000d", "name": "G", "backend": "group", "target": {"members": [CAST, DLNA]}})
