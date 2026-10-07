"""A tiny clamd stand-in on a Unix socket for tests and screenshots (no real malware involved).

Speaks the parts of the clamd protocol the app uses (zPING, zVERSION, zINSTREAM) and reports the standard
EICAR anti-virus *test string* as "Eicar-Test-Signature FOUND". ``stream_max`` mimics clamd's StreamMaxLength.
Usage: python fake_clamd.py SOCKET_PATH  (runs until killed)
"""
from __future__ import annotations

import os
import socket
import struct
import sys
import threading
from datetime import datetime, timezone

# The EICAR test file is a harmless 68-byte string every antivirus engine detects on purpose. It is assembled from
# two halves here so that this source file itself is not flagged by scanners.
EICAR = (b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS" + b"-TEST-FILE!$H+H*")


class FakeClamd:
    def __init__(self, path: str, *, stream_max: int = 100 * 1024 * 1024, signatures_date: datetime | None = None):
        self.path, self.stream_max = path, stream_max
        self.signatures_date = signatures_date or datetime.now(timezone.utc)
        self.scans = 0
        self.fail_next = False
        if os.path.exists(path):
            os.unlink(path)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(path)
        self.sock.listen(16)
        self._stop = False
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while not self._stop:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _read_cmd(self, conn) -> bytes:
        buf = b""
        while not buf.endswith(b"\0"):
            ch = conn.recv(1)
            if not ch:
                break
            buf += ch
        return buf.rstrip(b"\0")

    def _handle(self, conn):
        try:
            cmd = self._read_cmd(conn)
            if cmd == b"zPING":
                conn.sendall(b"PONG\0")
            elif cmd == b"zVERSION":
                stamp = self.signatures_date.strftime("%a %b %d %H:%M:%S %Y")
                conn.sendall(f"ClamAV 1.4.3/27800/{stamp}\0".encode())
            elif cmd == b"zINSTREAM":
                data, total = b"", 0
                while True:
                    head = b""
                    while len(head) < 4:
                        part = conn.recv(4 - len(head))
                        if not part:
                            return
                        head += part
                    (n,) = struct.unpack("!L", head)
                    if n == 0:
                        break
                    chunk = b""
                    while len(chunk) < n:
                        part = conn.recv(n - len(chunk))
                        if not part:
                            return
                        chunk += part
                    total += n
                    if total > self.stream_max:
                        conn.sendall(b"INSTREAM size limit exceeded. ERROR\0")
                        return
                    data += chunk
                self.scans += 1
                if self.fail_next:
                    self.fail_next = False
                    conn.sendall(b"stream: lstat() failed: Permission denied. ERROR\0")
                elif EICAR in data:
                    conn.sendall(b"stream: Eicar-Test-Signature FOUND\0")
                else:
                    conn.sendall(b"stream: OK\0")
            else:
                conn.sendall(b"UNKNOWN COMMAND\0")
        finally:
            conn.close()

    def stop(self):
        self._stop = True
        self.sock.close()
        if os.path.exists(self.path):
            os.unlink(self.path)


if __name__ == "__main__":
    srv = FakeClamd(sys.argv[1])
    os.chmod(sys.argv[1], 0o666)
    threading.Event().wait()
