"""Is a webcam streaming? inotify on /dev wakes us on any open/close of a video node; a node
counts as live when a process has it mmap'd (V4L2 streaming buffers). Merely opening it (apps
and PipeWire probe devices all the time) doesn't count.

Only our own processes are visible in /proc, which covers browsers, meeting apps and PipeWire.
"""

from __future__ import annotations

import ctypes
import os
import struct
from pathlib import Path

from PyQt6.QtCore import QObject, QSocketNotifier, QTimer, pyqtSignal

IN_OPEN = 0x20
IN_CLOSE_WRITE = 0x08
IN_CLOSE_NOWRITE = 0x10
IN_CREATE = 0x100
IN_NONBLOCK = 0o4000
IN_CLOEXEC = 0o2000000
EVENT = struct.Struct("iIII")

POLL_MS = 2000  # while something holds a node open, but isn't streaming yet
SETTLE_MS = 300


def holders() -> set[int]:
    """PIDs with any /dev/video* open."""
    pids = set()
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            for fd in (proc / "fd").iterdir():
                if os.readlink(fd).startswith("/dev/video"):
                    pids.add(int(proc.name))
                    break
        except OSError:
            continue
    return pids


def streaming(pid: int) -> bool:
    try:
        with open(f"/proc/{pid}/maps") as maps:
            return any("/dev/video" in line for line in maps)
    except OSError:
        return False


class CameraWatcher(QObject):
    changed = pyqtSignal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.active = False
        self._holders: set[int] = set()
        libc = ctypes.CDLL(None, use_errno=True)
        self._fd = libc.inotify_init1(IN_NONBLOCK | IN_CLOEXEC)
        if self._fd < 0 or libc.inotify_add_watch(
                self._fd, b"/dev", IN_OPEN | IN_CLOSE_WRITE | IN_CLOSE_NOWRITE | IN_CREATE) < 0:
            raise OSError(ctypes.get_errno(), "inotify on /dev failed")
        self._notifier = QSocketNotifier(self._fd, QSocketNotifier.Type.Read, self)
        self._notifier.activated.connect(self._on_inotify)
        self._settle = QTimer(self, singleShot=True, interval=SETTLE_MS)
        self._settle.timeout.connect(self.rescan)
        self._poll = QTimer(self, interval=POLL_MS)
        self._poll.timeout.connect(self._recheck)
        self.rescan()

    def _on_inotify(self) -> None:
        try:
            data = os.read(self._fd, 65536)
        except BlockingIOError:
            return
        offset, video = 0, False
        while offset < len(data):
            _, _, _, length = EVENT.unpack_from(data, offset)
            name = data[offset + EVENT.size: offset + EVENT.size + length].rstrip(b"\0")
            video = video or name.startswith(b"video")
            offset += EVENT.size + length
        if video:
            self._settle.start()  # an open is usually followed by a burst; scan once it settles

    def rescan(self) -> None:
        self._holders = holders()
        self._recheck()

    def _recheck(self) -> None:
        self._holders = {pid for pid in self._holders if os.path.exists(f"/proc/{pid}")}
        live = any(streaming(pid) for pid in self._holders)
        # While anything holds a node, poll: streams start after the open and can stop before
        # the close, and neither is an inotify event.
        if not self._holders:
            self._poll.stop()
        elif not self._poll.isActive():
            self._poll.start()
        if live != self.active:
            self.active = live
            self.changed.emit(live)
