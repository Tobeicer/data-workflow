# -*- coding: utf-8 -*-
"""WeChat 4.1.12.26 DB key capture (self-built, based on the MIT
stargazer-2026/wechat-4.1.12-decrypt approach).

Two modes:
- spawn:  spawns Weixin.exe and hooks every Weixin.exe pid as it appears
          (use when WeChat is closed / a fresh login is acceptable).
- attach: hooks the already-running Weixin.exe processes without restarting
          WeChat (codec config calls happen repeatedly at runtime, so the
          key is captured on the next call).

Notes vs upstream find_key.py:
- frida 17 removed Memory.readByteArray; use NativePointer.readByteArray.
- the codec function at Weixin.dll+0x3486140 fires repeatedly while WeChat
  runs, so attach mode works without killing the user session.
"""
import frida
import os
import sys
import time

WEIXIN_PATH = sys.argv[1] if len(sys.argv) > 1 else r"D:\weixin\Weixin.exe"
CODEC_CFG_OFF = 0x3486140


def log(s: str) -> None:
    with open(os.path.join(os.getcwd(), "hook.log"), "a", encoding="utf-8") as f:
        f.write(str(s) + "\n")


HOOK_JS = r"""
var OFF = 0x3486140;
var hooked = false;
function tryHook() {
    try {
        if (hooked) return true;
        var mod = Process.getModuleByName("Weixin.dll");
        if (!mod) return false;
        Interceptor.attach(mod.base.add(OFF), {
            onEnter: function (args) {
                try {
                    var buf = args[0].readByteArray(64);
                    var u8 = new Uint8Array(buf);
                    var hex = "";
                    for (var i = 0; i < u8.length; i++) hex += ("0" + u8[i].toString(16)).slice(-2);
                    send({ type: "candidate", hex: hex.slice(0, 64) });
                } catch (e) {
                    send({ type: "err", msg: "read fail " + e });
                }
            }
        });
        hooked = true;
        send({ type: "hooked" });
        return true;
    } catch (e) {
        send({ type: "err", msg: String(e) });
        return false;
    }
}
setInterval(tryHook, 1000);
"""

DUMP_JS = r"""
var OFF = 0x3486140;
function toHex(buf, n) {
    var u8 = new Uint8Array(buf);
    var hex = "";
    for (var i = 0; i < u8.length && i < n; i++) hex += ("0" + u8[i].toString(16)).slice(-2);
    return hex;
}
function tryHook() {
    try {
        var mod = Process.getModuleByName("Weixin.dll");
        if (!mod) return false;
        Interceptor.attach(mod.base.add(OFF), {
            onEnter: function (args) {
                var out = "";
                try { out += toHex(args[0].readByteArray(256), 256); } catch (e) { out += "E"; }
                out += "|";
                try { out += toHex(args[1].readByteArray(64), 64); } catch (e) { out += "E"; }
                out += "|";
                try { out += toHex(args[2].readByteArray(64), 64); } catch (e) { out += "E"; }
                send({ type: "buf", hex: out });
            }
        });
        return true;
    } catch (e) {
        return false;
    }
}
setInterval(tryHook, 1000);
"""


def main() -> None:
    mode = sys.argv[2] if len(sys.argv) > 2 else "spawn"
    d = frida.get_local_device()
    sessions = {}
    seen = set()

    def on_message(pid, msg, _data):
        if not isinstance(msg, dict):
            return
        payload = msg.get("payload")
        if not isinstance(payload, dict):
            return
        kind = payload.get("type")
        if kind == "candidate":
            log(f"PID={pid} PASSWORD_CANDIDATE={payload['hex']}")
            with open(os.path.join(os.getcwd(), "candidates.txt"), "a", encoding="utf-8") as f:
                f.write(payload["hex"] + "\n")
        elif kind == "hooked":
            log(f"PID={pid} HOOKED_WEIXIN_DLL")
        elif kind == "err":
            log(f"PID={pid} err={payload.get('msg')}")

    def on_dump_message(pid, msg, _data):
        if not isinstance(msg, dict):
            return
        payload = msg.get("payload")
        if not isinstance(payload, dict):
            return
        if payload.get("type") == "buf":
            with open(os.path.join(os.getcwd(), "dump.txt"), "a", encoding="utf-8") as f:
                f.write(f"{pid}|{payload['hex']}\n")

    def attach_and_hook(pid):
        if pid in seen:
            return
        seen.add(pid)
        try:
            s = d.attach(pid)
            sc = s.create_script(HOOK_JS)
            sc.on("message", lambda m, dt, pid=pid: on_message(pid, m, dt))
            sc.load()
            sessions[pid] = (s, sc)
            log(f"PID={pid} AGENT_LOADED")
        except Exception as e:  # noqa: BLE001
            log(f"PID={pid} attach failed: {e}")

    try:
        duration = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    except ValueError:
        duration = 0

    if mode == "dump":
        log("mode=dump (no restart; logging rcx/rdx/r8 buffers)")
        deadline = time.time() + (duration or 90)
    elif mode == "attach":
        log("mode=attach (no restart; hooking running Weixin.exe processes)")
        deadline = time.time() + (duration or 120)
    else:
        log("spawning: " + WEIXIN_PATH)
        pid0 = d.spawn([WEIXIN_PATH])
        attach_and_hook(pid0)
        d.resume(pid0)
        log(f"resumed pid={pid0} (scan QR or auto-login; key is captured when DBs open)")
        deadline = time.time() + (duration or 240)
    found = False
    while time.time() < deadline and not found:
        try:
            for p in d.enumerate_processes():
                if p.name.lower() == "weixin.exe":
                    if mode == "dump":
                        if p.pid not in seen:
                            seen.add(p.pid)
                            try:
                                s = d.attach(p.pid)
                                sc = s.create_script(DUMP_JS)
                                sc.on("message", lambda m, dt, pid=p.pid: on_dump_message(pid, m, dt))
                                sc.load()
                                sessions[p.pid] = (s, sc)
                                log(f"PID={p.pid} DUMP_AGENT_LOADED")
                            except Exception as e:  # noqa: BLE001
                                log(f"PID={p.pid} dump attach failed: {e}")
                    else:
                        attach_and_hook(p.pid)
            if os.path.isfile(os.path.join(os.getcwd(), "key.txt")):
                found = True
        except Exception as e:  # noqa: BLE001
            log("loop err: " + str(e))
        time.sleep(2)

    for pid, (s, _sc) in sessions.items():
        try:
            s.detach()
        except Exception:  # noqa: BLE001
            pass
    log("DONE_KEY_CAPTURED" if found else "DONE_NO_KEY")


if __name__ == "__main__":
    main()
