"""Exercise the installed SpringBoard service boundary without an iPhone.

The JSON command tests replace device.read_layout/write_layout entirely. This
test keeps the actual pymobiledevice3 service and plist serializer in the path.
It cannot establish what physical SpringBoard does with a write.
"""

import plistlib
import struct
from datetime import datetime

from unjiggle import device


class MemorySpringBoard:
    def __init__(self, state):
        self.state = state
        self.requests = []

    async def send_recv_plist(self, request):
        self.requests.append(request)
        assert request == {"command": "getIconState", "formatVersion": "2"}
        return self.state

    async def send_recv_prefixed(self, data):
        size = struct.unpack(">L", data[:4])[0]
        assert size == len(data) - 4
        request = plistlib.loads(data[4:])
        self.requests.append(request)
        assert request["command"] == "setIconState"
        self.state = request["iconState"]
        return b""

    async def close(self):
        pass


class MemoryLockdown:
    def __init__(self, service):
        self.service = service
        self.started = []

    async def start_lockdown_service(self, name, *, include_escrow_bag=False):
        self.started.append(name)
        assert include_escrow_bag is False
        return self.service


def test_real_service_serializes_raw_state_and_reads_back_without_loss():
    original = [
        [{"bundleIdentifier": "com.example.dock", "iconModDate": datetime(2026, 10, 1)}],
        [{"listType": "folder", "displayName": "Keep", "iconLists": [
            [{"bundleIdentifier": "com.example.a"}],
        ]}, {"iconType": "widget", "gridSize": "small", "custom": {"keep": True}}],
        [],
    ]
    service = MemorySpringBoard(original)
    phone = MemoryLockdown(service)

    before = device.read_layout(phone)
    assert before.raw == original
    device.write_layout(phone, before.raw)
    after = device.read_layout(phone)

    assert after.raw == original
    assert [request["command"] for request in service.requests] == [
        "getIconState", "setIconState", "getIconState",
    ]
    assert phone.started == ["com.apple.springboardservices.shim.remote"] * 3
