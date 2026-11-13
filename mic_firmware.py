"""Get the Kinect's audio firmware straight from Microsoft.

The Kinect v1's microphone array only works after Microsoft's audio firmware
(audios.bin) is uploaded to it at every power-up. That file belongs to
Microsoft, so KinectCam doesn't ship it: with the user's OK it downloads
Microsoft's official Xbox 360 system update (about 116 MB, from xbox.com) and
unpacks the file from it with libfreenect's fwfetcher (container parsing
only, nothing is decrypted). The result is checked against the known-good
SHA-256 before it is used.
"""
import hashlib
import io
import os
import shutil
import subprocess
import sys
import threading
import time
import zipfile

URL = "https://www.xbox.com/system-update-usb"     # redirects to download.microsoft.com
DOWNLOAD_BYTES = 115_992_188                       # SystemUpdate_17559_USB.zip
SHA256 = "3c7eaea16a4eb0c4b8afe3a82c01fb33c78fb6376e3dbd4fe34da6a0a7dfb3d8"
HERE = os.path.dirname(os.path.abspath(__file__))
_cwd_lock = threading.Lock()


def data_dir():
    return os.environ.get("KINECTCAM_DATA") or HERE


def target_path():
    """Where a downloaded copy is kept (writable, outside the app bundle)."""
    return os.path.join(data_dir(), "firmware", "audios.bin")


def find():
    """Path of a usable firmware file, or None."""
    for p in (target_path(), os.path.join(HERE, "firmware", "audios.bin")):
        if os.path.isfile(p) and os.path.getsize(p) > 100_000:
            return p
    return None


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class Fetcher(threading.Thread):
    """Background download + extract. Watch .state ("downloading",
    "extracting", "done", "failed"), .progress (0..1) and .error."""

    def __init__(self):
        super().__init__(daemon=True, name="mic-firmware")
        self.state, self.progress, self.error, self.path = "downloading", 0.0, None, None

    def run(self):
        work = os.path.join(data_dir(), "firmware", ".download")
        try:
            shutil.rmtree(work, ignore_errors=True)
            os.makedirs(work, exist_ok=True)
            zpath = os.path.join(work, "SystemUpdate.zip")
            self._download(zpath)
            self.state = "extracting"
            fw = self._extract(zpath, work)
            if _sha256(fw) != SHA256:
                raise RuntimeError("the extracted file isn't the expected Kinect firmware")
            os.makedirs(os.path.dirname(target_path()), exist_ok=True)
            os.replace(fw, target_path())
            self.path, self.state, self.progress = target_path(), "done", 1.0
            print("[ok] microphone firmware downloaded from Microsoft:", self.path, flush=True)
        except Exception as e:  # noqa: BLE001
            self.state, self.error = "failed", str(e)
            print("[warn] microphone firmware download failed:", e, flush=True)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _download(self, zpath):
        # curl ships with macOS and with Windows 10/11, and uses the system's certificates
        curl = "curl.exe" if sys.platform == "win32" else "/usr/bin/curl"
        flags = 0x08000000 if sys.platform == "win32" else 0     # CREATE_NO_WINDOW
        p = subprocess.Popen([curl, "-L", "-f", "-sS", "--retry", "3", "--connect-timeout", "20",
                              "-A", "Mozilla/5.0", "-o", zpath, URL],
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=flags)
        while p.poll() is None:
            if os.path.exists(zpath):
                self.progress = min(0.99, os.path.getsize(zpath) / DOWNLOAD_BYTES)
            time.sleep(0.3)
        if p.returncode != 0:
            err = (p.stderr.read() or b"").decode(errors="replace").strip()
            raise RuntimeError(f"download failed ({err or 'curl exit ' + str(p.returncode)}) - "
                               "check the internet connection")
        self.progress = 1.0

    @staticmethod
    def _extract(zpath, work):
        import fwfetcher
        # fwfetcher's __main__ normally defines this list (used for the info file)
        fwfetcher.lang = ["English", "Japanese", "German", "French", "Spanish",
                          "Italian", "Korean", "Chinese", "Portuguese"]
        with zipfile.ZipFile(zpath) as z:
            pirs = z.open("$SystemUpdate/FFFE07DF00000001").read()
        bio = io.BytesIO(pirs)
        bio.name = "FFFE07DF00000001"
        with _cwd_lock:                 # fwfetcher writes relative to the current folder
            old = os.getcwd()
            os.chdir(work)
            try:
                fwfetcher.handle_live_pirs(bio, len(pirs) - 4)
            finally:
                os.chdir(old)
        for root, _, files in os.walk(work):
            if "audios.bin" in files:
                return os.path.join(root, "audios.bin")
        raise RuntimeError("audios.bin not found in Microsoft's update")


if __name__ == "__main__":       # manual use: python mic_firmware.py
    if find():
        print("already have it:", find())
        sys.exit(0)
    f = Fetcher()
    f.start()
    while f.is_alive():
        print(f"\r{f.state} {f.progress * 100:5.1f}%", end="", flush=True)
        time.sleep(0.5)
    print("\n", f.state, f.error or f.path)
    sys.exit(0 if f.state == "done" else 1)
