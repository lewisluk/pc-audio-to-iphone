"""Autostart wrapper for pc-audio-to-iphone.

Run with pythonw.exe (no console window) by the scheduled task
"PC2iPhone-AudioServer".

Fixes for boot-time startup:
  1. Waits for the LAN to be up (non-loopback IPv4) before starting, so the
     banner lists the real LAN URL and WebRTC has interfaces to use.
  2. Optionally pins the capture device by NAME (indices shift across boots):
     set CAPTURE_DEVICE_HINT below, e.g. "Realtek" or "Steam Streaming".
     Empty string = use whatever the system default output is at start time.

stdout/stderr are redirected to server_autostart.log.
"""
import datetime
import os
import runpy
import socket
import subprocess
import sys
import time
import traceback

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(PROJECT_DIR, "server_autostart.log")
PYTHON_EXE = os.path.join(os.path.dirname(sys.executable), "python.exe")

# --- config ---------------------------------------------------------------
# Substring of the loopback device to capture, e.g. "Realtek" or "Steam".
# Leave "" to capture the current default output device.
CAPTURE_DEVICE_HINT = ""
# Substring of the OUTPUT device the phone's mic plays into. Point it at a
# virtual cable's playback end to make the phone a real system microphone
# (apps then select the cable's recording end, e.g. "Virtual Mic for
# AudioRelay" or VB-CABLE's "CABLE Output"). Leave "" for the system default
# output (phone mic simply plays out loud).
MIC_DEVICE_HINT = "Virtual Speakers"
NETWORK_TIMEOUT_S = 180  # max seconds to wait for a LAN address at boot
# ---------------------------------------------------------------------------


def log(msg):
    with open(LOG_PATH, "a", encoding="utf-8", errors="replace") as f:
        f.write("[%s] %s\n" % (
            datetime.datetime.now().isoformat(timespec="seconds"), msg))


def lan_ip():
    """Return the primary non-loopback IPv4, or None if no LAN yet."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packet is actually sent
        ip = s.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except OSError:
        return None
    finally:
        s.close()


def resolve_device_index(hint):
    """Find the loopback device index whose name contains `hint` (via the
    server's own --list-devices output). Returns None if no match."""
    if not hint:
        return None
    try:
        out = subprocess.run(
            [PYTHON_EXE, "server.py", "--list-devices"],
            capture_output=True, text=True, cwd=PROJECT_DIR, timeout=60,
        ).stdout
        for line in out.splitlines():
            if "[" in line and "]" in line and hint.lower() in line.lower() \
                    and "Loopback" in line:
                return int(line.strip().split("[")[1].split("]")[0])
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        log("device lookup failed: %r" % exc)
    return None


def resolve_output_device_index(hint):
    """Find the OUTPUT device index whose name contains `hint`, using the
    --mic-device section of the server's own --list-devices output (the
    loopback section is excluded so capture names can't shadow the hint).
    Returns None if no match."""
    if not hint:
        return None
    try:
        out = subprocess.run(
            [PYTHON_EXE, "server.py", "--list-devices"],
            capture_output=True, text=True, cwd=PROJECT_DIR, timeout=60,
        ).stdout
        mic_section = out.split("Output devices for --mic-device")[-1]
        for line in mic_section.splitlines():
            if "[" in line and "]" in line and hint.lower() in line.lower():
                return int(line.strip().split("[")[1].split("]")[0])
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        log("mic device lookup failed: %r" % exc)
    return None


def main():
    os.chdir(PROJECT_DIR)
    log("===== autostart wrapper started =====")

    # 1. Wait for the LAN so the default output device and network are settled.
    waited = 0
    while True:
        ip = lan_ip()
        if ip:
            log("LAN ready: %s (waited %ds)" % (ip, waited))
            break
        if waited >= NETWORK_TIMEOUT_S:
            log("WARNING: no LAN after %ds, starting anyway" % waited)
            break
        time.sleep(3)
        waited += 3

    # 2. Resolve capture + mic devices by name hint (if configured).
    argv = ["server.py"]
    idx = resolve_device_index(CAPTURE_DEVICE_HINT)
    if idx is not None:
        argv += ["--device", str(idx)]
        log("capture device pinned by hint %r -> index %d" % (CAPTURE_DEVICE_HINT, idx))
    elif CAPTURE_DEVICE_HINT:
        log("WARNING: no loopback device matching %r, using default" % CAPTURE_DEVICE_HINT)
    mic_idx = resolve_output_device_index(MIC_DEVICE_HINT)
    if mic_idx is not None:
        argv += ["--mic-device", str(mic_idx)]
        log("mic playback device pinned by hint %r -> index %d" % (MIC_DEVICE_HINT, mic_idx))
    elif MIC_DEVICE_HINT:
        log("WARNING: no output device matching %r, mic uses default" % MIC_DEVICE_HINT)

    log("launching: %s %s" % (PYTHON_EXE, " ".join(argv)))
    # 3. Run server.py in-process so its output lands in our log file.
    sys.stdout = sys.stderr = open(
        LOG_PATH, "a", buffering=1, encoding="utf-8", errors="replace")
    sys.argv = argv
    try:
        runpy.run_path(os.path.join(PROJECT_DIR, "server.py"), run_name="__main__")
    except SystemExit:
        pass
    except BaseException:
        with open(LOG_PATH, "a", encoding="utf-8", errors="replace") as f:
            f.write(traceback.format_exc())
            f.write("\n===== server.py CRASHED =====\n")
    else:
        log("===== server.py exited =====")


if __name__ == "__main__":
    main()
