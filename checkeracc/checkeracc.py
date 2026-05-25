
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
checkeracc.py
WhatsApp Account Checker Automation

Versi patch v5:
- Fokus utama balik ke app/account, bukan validasi user.
- Close All hanya sekali di awal program.
- WhatsApp Original dibuka via launcher default yang paling stabil.
- Dual/Clone dicoba sebagai fallback teknis opsional, tidak jadi gate utama.
- V5 tidak mengubah flow WhatsApp Original yang sudah sukses.
- V5 menambah deteksi/diagnostic user clone Samsung Dual Messenger dan validasi top-focus lebih ketat.
- Buka menu titik tiga diprioritaskan via KEYCODE_MENU supaya tidak kena icon kamera.
Python + ADB + UIAutomator XML

Tujuan:
- Cek WhatsApp Personal / Original / Dual Clone / Business berdasarkan package/app.
- Ambil nama akun dan nomor yang tampil di UI WhatsApp.
- Simpan bukti debug otomatis: screenshot, XML, result.json.
- Tidak baca database WhatsApp, tidak scraping chat, tidak kirim pesan.

Catatan:
- Script ini sengaja dibuat package-first, bukan user-first.
- Android user seperti 0 / 95 hanya metadata atau target launch teknis.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


# ============================================================
# CONFIG
# ============================================================

DEVICES = "R9RL106EV5D"

ADB_TIMEOUT = 25
WAIT_SHORT = 1.0
WAIT_MEDIUM = 2.0
WAIT_LONG = 3.5

DEBUG_ROOT = Path("debug")

TARGET_PACKAGES = [
    {
        "label_hint": "WhatsApp Personal",
        "package": "com.whatsapp",
        "type": "personal",
        "max_accounts": 2,
    },
    {
        "label_hint": "WhatsApp Business",
        "package": "com.whatsapp.w4b",
        "type": "business",
        "max_accounts": 1,
    },
]


# V4: user Android bukan jalur utama. Original dibuka default launcher.
# Dual tetap dicoba sebagai fallback teknis, tapi kalau gagal tidak merusak scan original.
SCAN_DUAL_FALLBACK_USER95 = True
DUAL_FALLBACK_USER = "95"

# V5: Kalau user clone Samsung bukan 95, coba user lain dari pm list users.
# Ini hanya fallback untuk membuka Dual, bukan validasi utama scan Original.
TRY_OTHER_NON_OWNER_USERS_FOR_DUAL = True

# V4: buka overflow menu pakai tombol MENU dulu. Ini lebih aman daripada tap koordinat
# karena di WhatsApp posisi icon kamera dekat dengan titik tiga.
USE_KEYCODE_MENU_FOR_OVERFLOW = True

PHONE_REGEX = re.compile(r"(?:(?:\+?\d{1,3})[\s().-]*)?(?:\d[\s().-]*){8,15}\d")

TEXT_BLACKLIST_FOR_NAMES = {
    "settings", "pengaturan",
    "account", "akun",
    "chats", "chat",
    "notifications", "notifikasi",
    "storage and data", "penyimpanan dan data",
    "privacy", "privasi",
    "help", "bantuan",
    "invite a friend", "undang teman",
    "add account", "tambah akun",
    "switch account", "ganti akun",
    "profile", "profil",
    "edit profile", "edit profil",
    "contact info", "informasi kontak",
    "phone", "telepon",
    "nomor telepon",
    "business tools", "fitur bisnis",
    "avatar",
    "qr code", "kode qr",
}

NOT_LOGGED_IN_KEYWORDS = [
    "agree and continue",
    "setuju dan lanjutkan",
    "welcome to whatsapp",
    "selamat datang di whatsapp",
    "enter your phone number",
    "masukkan nomor telepon",
    "verify your phone number",
    "verifikasi nomor telepon",
    "use whatsapp",
    "gunakan whatsapp",
]

LOCKED_KEYWORDS = [
    "fingerprint",
    "sidik jari",
    "unlock",
    "buka kunci",
    "locked",
    "terkunci",
    "enter pin",
    "masukkan pin",
    "app lock",
    "kunci aplikasi",
    "draw pattern",
    "gambar pola",
    "use fingerprint",
    "gunakan sidik jari",
]

SETTINGS_KEYWORDS = ["settings", "pengaturan"]

RECENTS_CLOSE_KEYWORDS = [
    "close all",
    "clear all",
    "tutup semua",
    "hapus semua",
    "bersihkan semua",
    "clear",
    "close",
]

MORE_OPTIONS_DESC = [
    "more options",
    "opsi lainnya",
    "lainnya",
    "menu",
    "more",
]

REMOTE_SCREEN = "/sdcard/checkeracc_screen.png"
REMOTE_XML = "/sdcard/checkeracc_window.xml"


# ============================================================
# BASIC UTILS
# ============================================================

def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def safe_slug(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "unknown"


def log(msg: str) -> None:
    print(msg, flush=True)


def sleep(seconds: float) -> None:
    time.sleep(seconds)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_text(path: Path, text: str) -> None:
    path.write_text(text or "", encoding="utf-8", errors="ignore")


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


# ============================================================
# ADB WRAPPER
# ============================================================

class ADBResult:
    def __init__(self, returncode: int, stdout: str, stderr: str, cmd: List[str]):
        self.returncode = returncode
        self.stdout = stdout or ""
        self.stderr = stderr or ""
        self.cmd = cmd

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def combined(self) -> str:
        return (self.stdout + "\n" + self.stderr).strip()


def adb(args: List[str], timeout: int = ADB_TIMEOUT) -> ADBResult:
    """
    Jalankan command adb dengan serial device.
    args contoh: ["shell", "pm", "list", "packages"]
    """
    cmd = ["adb", "-s", DEVICES] + args
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="ignore",
        )
        return ADBResult(p.returncode, p.stdout, p.stderr, cmd)
    except subprocess.TimeoutExpired as e:
        return ADBResult(
            124,
            e.stdout if isinstance(e.stdout, str) else "",
            f"TIMEOUT: {e}",
            cmd,
        )
    except FileNotFoundError:
        return ADBResult(127, "", "adb command not found. Install Android platform-tools dulu.", cmd)
    except Exception as e:
        return ADBResult(1, "", f"ADB ERROR: {e}", cmd)


def adb_shell(shell_args: List[str], timeout: int = ADB_TIMEOUT) -> ADBResult:
    return adb(["shell"] + shell_args, timeout=timeout)


def adb_pull(remote: str, local: Path, timeout: int = ADB_TIMEOUT) -> ADBResult:
    ensure_dir(local.parent)
    return adb(["pull", remote, str(local)], timeout=timeout)


def adb_rm(remote: str) -> None:
    adb_shell(["rm", "-f", remote], timeout=10)


def tap(x: int, y: int) -> bool:
    res = adb_shell(["input", "tap", str(int(x)), str(int(y))], timeout=10)
    sleep(WAIT_SHORT)
    return res.ok


def swipe(x1: int, y1: int, x2: int, y2: int, duration_ms: int = 450) -> bool:
    res = adb_shell(
        ["input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)],
        timeout=10,
    )
    sleep(WAIT_MEDIUM)
    return res.ok


def press_back() -> None:
    adb_shell(["input", "keyevent", "4"], timeout=10)
    sleep(WAIT_SHORT)


def press_home() -> None:
    # KEYCODE_HOME = 3
    adb_shell(["input", "keyevent", "3"], timeout=10)
    sleep(WAIT_SHORT)


def press_recent_apps() -> None:
    # KEYCODE_APP_SWITCH = 187
    adb_shell(["input", "keyevent", "187"], timeout=10)
    sleep(WAIT_MEDIUM)


def press_menu() -> None:
    # KEYCODE_MENU = 82. Di banyak app Android ini membuka overflow/titik tiga.
    adb_shell(["input", "keyevent", "82"], timeout=10)
    sleep(WAIT_MEDIUM)



# ============================================================
# CLEAN START / RECENTS RESET
# ============================================================

def reset_to_clean_home(debug_dir: Optional[Path] = None, prefix: str = "reset") -> bool:
    """
    Bikin start state lebih bersih sebelum scan:
    1. Buka Recent Apps.
    2. Klik Close all / Tutup semua kalau ada.
    3. Paksa balik Home.

    Kenapa ini penting:
    - Kalau WhatsApp terakhir nyangkut di Camera/Settings/Edit Profile,
      UI dump bisa ngaco.
    - Dengan recents ditutup, launch app lebih sering mulai dari state fresh/home app.
    """
    log("[RESET] Buka Recent Apps untuk close all tabs/apps.")

    try:
        press_recent_apps()

        width, height = get_screen_size()
        nodes = []

        if debug_dir is not None:
            save_screenshot(debug_dir, f"{prefix}_recent_apps.png")
            recents_xml = dump_ui(debug_dir, f"{prefix}_recent_apps.xml")
            nodes = parse_ui_xml(recents_xml) if recents_xml else []
        else:
            tmp_dir = DEBUG_ROOT / f"{now_stamp()}_startup_reset"
            ensure_dir(tmp_dir)
            recents_xml = dump_ui(tmp_dir, f"{prefix}_recent_apps.xml")
            nodes = parse_ui_xml(recents_xml) if recents_xml else []

        close_node = find_node_by_keywords(nodes, RECENTS_CLOSE_KEYWORDS, clickable_preferred=True)
        if not close_node:
            close_node = find_node_by_keywords(nodes, RECENTS_CLOSE_KEYWORDS, clickable_preferred=False)

        if close_node:
            log("[RESET] Klik Close all/Tutup semua dari XML.")
            click_node(close_node)
            sleep(WAIT_MEDIUM)
        else:
            # Fallback Samsung/Android umum: tombol Close all biasanya di tengah bawah.
            # Hanya dipakai setelah recents terbuka; kalau tidak ada tombol, tap ini umumnya aman.
            log("[RESET] Tombol Close all tidak kebaca XML, fallback tap area bawah tengah.")
            tap(int(width * 0.50), int(height * 0.92))
            sleep(WAIT_MEDIUM)

        press_home()
        log("[RESET] Start state: Home screen.")
        return True

    except Exception as e:
        log(f"[RESET] Gagal reset clean home: {type(e).__name__}: {e}")
        press_home()
        return False


def force_stop_package(package: str, user_id: Optional[str] = None) -> bool:
    """
    Tutup app target tanpa buka Recent Apps.
    Ini menghindari loop Close All berulang, tapi tetap bikin launch berikutnya lebih fresh.
    """
    if user_id is None:
        res = adb_shell(["am", "force-stop", package], timeout=10)
    else:
        res = adb_shell(["am", "force-stop", "--user", str(user_id), package], timeout=10)
    sleep(0.4)
    return res.ok


def prepare_before_launch(package: str, user_id: Optional[str], debug_dir: Path, prefix: str = "before_launch") -> None:
    """
    V4: persiapan ringan saja.

    Jangan force-stop per user dan jangan validasi user di awal, karena di HP target
    explicit user launch tidak stabil. Target utamanya: balik Home, lalu buka app.
    """
    log(f"[PREP] Home sebelum buka {package}" + (f" fallback user {user_id}" if user_id is not None else " default"))
    press_home()
    save_screenshot(debug_dir, f"{prefix}_home.png")
    dump_ui(debug_dir, f"{prefix}_home.xml")


# ============================================================
# DEVICE / PACKAGE
# ============================================================

def check_device() -> bool:
    log(f"[DEVICE] Cek device serial: {DEVICES}")

    res = adb(["get-state"], timeout=10)
    if res.ok and "device" in res.stdout.lower():
        log("[DEVICE] OK device connected.")
        return True

    log("[DEVICE] get-state gagal, cek adb devices...")
    res2 = subprocess.run(
        ["adb", "devices"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    log(res2.stdout.strip())

    if DEVICES not in res2.stdout:
        log(f"[DEVICE] Serial {DEVICES} tidak ditemukan.")
        return False

    if f"{DEVICES}\tdevice" not in res2.stdout:
        log(f"[DEVICE] Serial {DEVICES} ada tapi belum status device. Cek authorization USB debugging.")
        return False

    return True


def get_android_users() -> List[str]:
    """
    Ambil user Android dari pm list users.
    Samsung Dual Messenger sering muncul sebagai user 95.
    """
    res = adb_shell(["pm", "list", "users"], timeout=10)
    users = []
    for line in res.combined.splitlines():
        # contoh: UserInfo{0:Owner:13} running
        m = re.search(r"UserInfo\{(\d+):", line)
        if m:
            users.append(m.group(1))

    # Pastikan default kandidat tetap ada
    for u in ["0", "95"]:
        if u not in users:
            users.append(u)

    # Dedup urut
    out = []
    for u in users:
        if u not in out:
            out.append(u)
    return out


def package_exists(package: str) -> bool:
    # pm path lebih kuat untuk cek package global/current user
    res = adb_shell(["pm", "path", package], timeout=15)
    if res.ok and "package:" in res.stdout:
        return True

    res2 = adb_shell(["pm", "list", "packages", package], timeout=15)
    return res2.ok and package in res2.stdout


def package_exists_for_user(package: str, user_id: str) -> Optional[bool]:
    """
    Return:
    - True kalau package ada di user itu
    - False kalau command valid tapi package tidak ada / user tidak ada
    - None kalau device tidak support command / hasil ambigu
    """
    res = adb_shell(["cmd", "package", "list", "packages", "--user", str(user_id), package], timeout=15)
    text = res.combined.lower()

    if package in res.stdout:
        return True

    if "doesn't exist" in text or "unknown user" in text or "not found" in text:
        return False

    if res.ok:
        return False

    return None


def collect_dual_diagnostics(debug_dir: Path, package: str = "com.whatsapp") -> List[str]:
    """
    Simpan bukti teknis untuk cari user/profile Samsung Dual Messenger.
    Tidak dipakai sebagai gate utama; hanya diagnostic + daftar kandidat launch.
    """
    ensure_dir(debug_dir)

    commands = {
        "pm_list_users.txt": ["pm", "list", "users"],
        "pm_list_packages_all.txt": ["pm", "list", "packages"],
        "cmd_package_list_users_all.txt": ["cmd", "package", "list", "packages", "--user", "all", package],
        "launcherapps_help.txt": ["cmd", "launcherapps", "help"],
    }

    for filename, cmd in commands.items():
        res = adb_shell(cmd, timeout=20)
        write_text(debug_dir / filename, res.combined)

    users = get_android_users()
    for user_id in users:
        res1 = adb_shell(["cmd", "package", "list", "packages", "--user", str(user_id), package], timeout=20)
        write_text(debug_dir / f"packages_user_{user_id}.txt", res1.combined)

        res2 = adb_shell([
            "cmd", "package", "resolve-activity", "--brief", "--user", str(user_id),
            "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER", package
        ], timeout=20)
        write_text(debug_dir / f"resolve_activity_user_{user_id}.txt", res2.combined)

        res3 = adb_shell(["cmd", "launcherapps", "get-activities", "--user", str(user_id), package], timeout=20)
        write_text(debug_dir / f"launcherapps_user_{user_id}.txt", res3.combined)

    return users


def resolve_launcher_component(package: str, user_id: Optional[str] = None) -> Optional[str]:
    """
    Coba resolve activity launcher package. Return format package/.Activity kalau ketemu.
    Ini hanya fallback ketika monkey default gagal.
    """
    cmd = ["cmd", "package", "resolve-activity", "--brief"]
    if user_id is not None:
        cmd += ["--user", str(user_id)]
    cmd += ["-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER", package]

    res = adb_shell(cmd, timeout=15)
    lines = [x.strip() for x in res.combined.splitlines() if x.strip()]
    for line in reversed(lines):
        if package in line and "/" in line and "No activity" not in line:
            return line
    return None


def get_top_focus_text() -> str:
    """
    Ambil hanya indikator app yang benar-benar sedang tampil/top.
    V4 pernah terlalu longgar karena get_current_focus() juga memuat activity history,
    sehingga package lama bisa kebaca walaupun layar sudah Home.
    """
    chunks = []
    for cmd in (
        ["dumpsys", "window"],
        ["dumpsys", "activity", "top"],
        ["dumpsys", "activity", "activities"],
    ):
        res = adb_shell(cmd, timeout=15)
        if not res.combined:
            continue
        selected = []
        for line in res.combined.splitlines():
            low = line.lower()
            if (
                "mcurrentfocus" in low
                or "mfocusedapp" in low
                or "mresumedactivity" in low
                or "topresumedactivity" in low
                or "resumedactivity" in low
            ):
                selected.append(line)
        if selected:
            chunks.append(f"$ {' '.join(cmd)}\n" + "\n".join(selected))
    return "\n\n".join(chunks)


def verify_package_opened(package: str, debug_dir: Optional[Path] = None, tag: str = "") -> bool:
    """
    True hanya kalau package ada di top/focused/resumed activity.
    Ini mencegah false positive ketika package cuma muncul di activity history.
    """
    top_focus = get_top_focus_text()
    if debug_dir is not None:
        suffix = f"_{safe_slug(tag)}" if tag else ""
        write_text(debug_dir / f"top_focus{suffix}.txt", top_focus)
    return package in top_focus


def open_package(package: str, user_id: Optional[str] = None, debug_dir: Optional[Path] = None) -> bool:
    """
    V4 launch policy:
    - Original/default: pakai monkey default dulu. Ini yang sebelumnya terbukti bisa buka WA ori.
    - Explicit user seperti 95 hanya fallback teknis untuk clone, bukan jalur utama.
    - Return True berdasarkan current focus package, bukan semata return code command.
    """
    attempts: List[Tuple[str, List[str]]] = []

    if user_id is None:
        attempts.append((
            "monkey default",
            ["monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"],
        ))
        attempts.append((
            "am start default intent",
            ["am", "start", "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER", "-p", package],
        ))
    else:
        # Jangan jadikan user sebagai validasi. Ini hanya dicoba untuk membuka clone.
        attempts.append((
            f"am start fallback user {user_id}",
            ["am", "start", "--user", str(user_id), "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER", "-p", package],
        ))
        attempts.append((
            f"monkey fallback user {user_id}",
            ["monkey", "--user", str(user_id), "-p", package, "-c", "android.intent.category.LAUNCHER", "1"],
        ))

    component = resolve_launcher_component(package, user_id=user_id)
    if component:
        if user_id is None:
            attempts.append(("am start resolved component", ["am", "start", "-n", component]))
        else:
            attempts.append((f"am start resolved component user {user_id}", ["am", "start", "--user", str(user_id), "-n", component]))

    for name, args in attempts:
        log(f"[OPEN] {name}: {package}" + (f" user {user_id}" if user_id is not None else ""))
        res = adb_shell(args, timeout=20)
        sleep(WAIT_LONG)

        # Yang penting app benar-benar tampil. Kadang command return code tidak konsisten.
        if verify_package_opened(package, debug_dir=debug_dir, tag=name):
            return True

        text = res.combined.lower()
        if text.strip():
            log(f"[OPEN] {name} belum berhasil: {text[:300].replace(chr(10), ' ')}")

    return False


def get_current_focus() -> str:
    chunks = []

    for cmd in (
        ["dumpsys", "window"],
        ["dumpsys", "activity", "top"],
        ["dumpsys", "activity", "activities"],
    ):
        res = adb_shell(cmd, timeout=15)
        if res.combined:
            chunks.append(f"$ {' '.join(cmd)}\n{res.combined}")

    return "\n\n".join(chunks)


def is_current_package(package: str, focus_text: Optional[str] = None) -> bool:
    focus_text = focus_text if focus_text is not None else get_current_focus()
    return package in focus_text


def detect_current_android_user(package: str) -> Optional[str]:
    """
    Coba deteksi user dari dumpsys activity.
    Cari pola u0/u95 dekat nama package.
    """
    focus = get_current_focus()
    candidates = []

    for line in focus.splitlines():
        if package not in line:
            continue

        # Contoh umum:
        # ActivityRecord{... u0 com.whatsapp/.HomeActivity ...}
        for m in re.finditer(r"\bu(\d+)\b", line):
            candidates.append(m.group(1))

        # Kadang format userId=0
        for m in re.finditer(r"userId=(\d+)", line):
            candidates.append(m.group(1))

    for c in candidates:
        if c.isdigit():
            return c

    # Fallback current user Android aktif, tapi ini bukan bukti kuat instance app.
    res = adb_shell(["cmd", "activity", "get-current-user"], timeout=10)
    m = re.search(r"\d+", res.combined)
    if m:
        return m.group(0)

    return None


# ============================================================
# DEBUG FILES
# ============================================================

def create_debug_dir(label_hint: str, launch_user: Optional[str] = None) -> Path:
    DEBUG_ROOT.mkdir(exist_ok=True)
    user_part = f"user{launch_user}" if launch_user is not None else "user_default"
    name = f"{now_stamp()}_{safe_slug(label_hint)}_{user_part}"
    path = DEBUG_ROOT / name
    ensure_dir(path)
    return path


def finalize_debug_dir(old_dir: Path, final_label: str, detected_user: Optional[str]) -> Path:
    """
    Rename debug dir setelah label final dan detected_user diketahui.
    Kalau rename gagal, tetap pakai folder lama.
    """
    if not old_dir.exists():
        return old_dir

    user_part = f"user{detected_user}" if detected_user else "user_unknown"
    new_name = f"{now_stamp()}_{safe_slug(final_label)}_{user_part}"
    new_dir = old_dir.parent / new_name

    if old_dir.name == new_dir.name:
        return old_dir

    try:
        if not new_dir.exists():
            old_dir.rename(new_dir)
            return new_dir
    except Exception:
        pass

    return old_dir


def save_screenshot(debug_dir: Path, filename: str) -> Optional[Path]:
    local = debug_dir / filename
    adb_rm(REMOTE_SCREEN)

    res = adb_shell(["screencap", "-p", REMOTE_SCREEN], timeout=15)
    if not res.ok:
        write_text(debug_dir / f"{filename}.error.txt", res.combined)
        return None

    pull = adb_pull(REMOTE_SCREEN, local, timeout=20)
    adb_rm(REMOTE_SCREEN)

    if not pull.ok:
        write_text(debug_dir / f"{filename}.error.txt", pull.combined)
        return None

    return local


def dump_ui(debug_dir: Path, filename: str) -> Optional[Path]:
    local = debug_dir / filename
    adb_rm(REMOTE_XML)

    res = adb_shell(["uiautomator", "dump", REMOTE_XML], timeout=20)
    if not res.ok:
        write_text(debug_dir / f"{filename}.dump_error.txt", res.combined)
        return None

    pull = adb_pull(REMOTE_XML, local, timeout=20)
    adb_rm(REMOTE_XML)

    if not pull.ok or not local.exists():
        write_text(debug_dir / f"{filename}.pull_error.txt", pull.combined)
        return None

    # Validasi minimal isi XML
    txt = read_text(local)
    if "<hierarchy" not in txt:
        write_text(debug_dir / f"{filename}.invalid_error.txt", txt[:2000])
        return None

    return local


def save_result_json(result: Dict[str, Any], debug_dir: Path) -> None:
    result["debug_dir"] = str(debug_dir)
    path = debug_dir / "result.json"
    path.write_text(json.dumps(result, indent=4, ensure_ascii=False), encoding="utf-8")


# ============================================================
# XML PARSING
# ============================================================

def parse_bounds(bounds: str) -> Optional[Tuple[int, int, int, int]]:
    if not bounds:
        return None
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
    if not m:
        return None
    return tuple(int(x) for x in m.groups())


def center_of_bounds(bounds: Tuple[int, int, int, int]) -> Tuple[int, int]:
    x1, y1, x2, y2 = bounds
    return (x1 + x2) // 2, (y1 + y2) // 2


def parse_ui_xml(xml_path: Path) -> List[Dict[str, Any]]:
    nodes = []
    try:
        root = ET.parse(str(xml_path)).getroot()
    except Exception:
        return nodes

    for el in root.iter("node"):
        attrib = dict(el.attrib)
        text = attrib.get("text") or ""
        desc = attrib.get("content-desc") or ""
        rid = attrib.get("resource-id") or ""
        cls = attrib.get("class") or ""
        bounds_raw = attrib.get("bounds") or ""
        bounds = parse_bounds(bounds_raw)

        nodes.append({
            "text": text,
            "desc": desc,
            "rid": rid,
            "class": cls,
            "clickable": attrib.get("clickable") == "true",
            "enabled": attrib.get("enabled") != "false",
            "bounds_raw": bounds_raw,
            "bounds": bounds,
            "raw": attrib,
        })

    return nodes


def get_all_texts(nodes: List[Dict[str, Any]], include_desc: bool = True) -> List[str]:
    texts = []
    for n in nodes:
        for key in ("text", "desc") if include_desc else ("text",):
            v = (n.get(key) or "").strip()
            if v:
                texts.append(v)
    return texts


def normalized_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def node_text_blob(node: Dict[str, Any]) -> str:
    return " ".join([
        normalized_text(node.get("text", "")),
        normalized_text(node.get("desc", "")),
        normalized_text(node.get("rid", "")),
    ]).strip()


def find_node_by_keywords(
    nodes: List[Dict[str, Any]],
    keywords: List[str],
    clickable_preferred: bool = True,
) -> Optional[Dict[str, Any]]:
    keys = [k.lower() for k in keywords]

    matches = []
    for n in nodes:
        blob = node_text_blob(n)
        if not blob:
            continue
        if any(k in blob for k in keys):
            if n.get("bounds"):
                matches.append(n)

    if not matches:
        return None

    if clickable_preferred:
        clickable = [n for n in matches if n.get("clickable")]
        if clickable:
            return clickable[0]

    return matches[0]


def click_node(node: Dict[str, Any]) -> bool:
    bounds = node.get("bounds")
    if not bounds:
        return False
    x, y = center_of_bounds(bounds)
    return tap(x, y)


def get_screen_size() -> Tuple[int, int]:
    res = adb_shell(["wm", "size"], timeout=10)
    # Physical size: 1080x2400
    m = re.search(r"(\d+)x(\d+)", res.combined)
    if m:
        return int(m.group(1)), int(m.group(2))
    return 1080, 2400


# ============================================================
# DETECTION HELPERS
# ============================================================

def detect_not_logged_in(nodes: List[Dict[str, Any]]) -> bool:
    blob = " | ".join(get_all_texts(nodes)).lower()
    return any(k in blob for k in NOT_LOGGED_IN_KEYWORDS)


def detect_locked(nodes: List[Dict[str, Any]]) -> bool:
    blob = " | ".join(get_all_texts(nodes)).lower()
    return any(k in blob for k in LOCKED_KEYWORDS)


def normalize_phone_number(number: str) -> Optional[str]:
    if not number:
        return None

    raw = number.strip()
    has_plus = raw.startswith("+")
    digits = re.sub(r"\D+", "", raw)

    if len(digits) < 9 or len(digits) > 16:
        return None

    # Indonesia-friendly normalization
    if digits.startswith("0"):
        digits = "62" + digits[1:]
        return "+" + digits

    if digits.startswith("62"):
        return "+" + digits

    if has_plus:
        return "+" + digits

    # Kalau nomor lokal tanpa 0, jangan terlalu agresif.
    return "+" + digits if len(digits) >= 10 else None


def extract_phone_numbers(texts: List[str]) -> List[Dict[str, str]]:
    found = []
    seen = set()

    for text in texts:
        if not text:
            continue

        for m in PHONE_REGEX.finditer(text):
            candidate = m.group(0).strip()

            # Skip angka yang terlalu mirip versi/tanggal
            norm = normalize_phone_number(candidate)
            if not norm:
                continue

            digits = re.sub(r"\D+", "", norm)
            if len(digits) < 10:
                continue

            if norm not in seen:
                seen.add(norm)
                found.append({
                    "display_number": candidate,
                    "normalized_number": norm,
                })

    return found


def is_phone_text(text: str) -> bool:
    return len(extract_phone_numbers([text])) > 0


def is_good_name_candidate(text: str) -> bool:
    t = normalized_text(text)
    if not t:
        return False
    if is_phone_text(t):
        return False
    if t in TEXT_BLACKLIST_FOR_NAMES:
        return False
    if any(bad == t or bad in t for bad in TEXT_BLACKLIST_FOR_NAMES):
        return False
    if len(t) > 60:
        return False
    if len(t) < 2:
        return False
    return True


def classify_final_label(package: str, detected_user: Optional[str]) -> str:
    if package == "com.whatsapp.w4b":
        return "WhatsApp Business"

    if package == "com.whatsapp":
        if detected_user == "0":
            return "WhatsApp Original"
        if detected_user and detected_user != "0":
            return "WhatsApp Dual / Clone"
        return "WhatsApp Personal"

    return "Unknown App"


def base_result(label_hint: str, package: str) -> Dict[str, Any]:
    return {
        "label_hint": label_hint,
        "final_label": label_hint,
        "package": package,
        "detected_user": None,
        "launch_user": None,
        "package_found": False,
        "app_opened": False,
        "status": "unknown_error",
        "accounts": [],
        "debug_dir": None,
        "notes": [],
    }


# ============================================================
# NAVIGATION
# ============================================================

def find_more_options_node(nodes: List[Dict[str, Any]], width: int, height: int) -> Optional[Dict[str, Any]]:
    """
    Cari tombol titik tiga secara ketat.
    Jangan fallback ke clickable kanan generic, karena di WhatsApp bisa kena icon kamera.
    """
    strict_words = ["more options", "opsi lainnya"]
    loose_words = ["more", "lainnya", "menu"]

    candidates: List[Dict[str, Any]] = []

    for n in nodes:
        b = n.get("bounds")
        if not b:
            continue

        cx, cy = center_of_bounds(b)
        if not (cx > width * 0.70 and height * 0.015 < cy < height * 0.14):
            continue

        text_desc = " ".join([
            normalized_text(n.get("text", "")),
            normalized_text(n.get("desc", "")),
        ]).strip()
        rid = normalized_text(n.get("rid", ""))

        if any(w in text_desc for w in strict_words):
            candidates.append(n)
            continue

        # resource-id WhatsApp biasanya mengandung overflow/menu/more, tapi jangan kamera/search.
        if any(w in rid for w in ["overflow", "more", "menu"]) and not any(w in rid for w in ["camera", "search"]):
            candidates.append(n)
            continue

        if any(w == text_desc for w in loose_words) and "camera" not in text_desc and "search" not in text_desc:
            candidates.append(n)

    if not candidates:
        return None

    # Pilih yang paling kanan dari kandidat yang memang punya tanda More/menu.
    candidates.sort(key=lambda n: center_of_bounds(n["bounds"])[0], reverse=True)
    return candidates[0]



def open_settings(debug_dir: Path, settings_filename: str = "settings.xml") -> Optional[Path]:
    """
    Buka menu titik tiga -> Settings/Pengaturan.

    V4: jangan langsung tap koordinat. Coba KEYCODE_MENU dulu supaya tidak kena icon kamera.
    Kalau menu tidak terbuka, baru pakai XML More options exact, lalu fallback edge kanan.
    """
    width, height = get_screen_size()

    before_xml = dump_ui(debug_dir, "before_open_settings.xml")
    before_nodes = parse_ui_xml(before_xml) if before_xml else []

    if find_node_by_keywords(before_nodes, SETTINGS_KEYWORDS, clickable_preferred=False):
        return dump_ui(debug_dir, settings_filename)

    def try_click_settings_from_menu(menu_filename: str) -> Optional[Path]:
        menu_xml = dump_ui(debug_dir, menu_filename)
        menu_nodes = parse_ui_xml(menu_xml) if menu_xml else []
        settings_node = find_node_by_keywords(menu_nodes, SETTINGS_KEYWORDS, clickable_preferred=True)
        if not settings_node:
            settings_node = find_node_by_keywords(menu_nodes, SETTINGS_KEYWORDS, clickable_preferred=False)
        if not settings_node:
            return None
        log("[NAV] Klik Settings/Pengaturan.")
        click_node(settings_node)
        sleep(WAIT_LONG)
        return dump_ui(debug_dir, settings_filename)

    # 1) Cara paling aman: Android MENU key membuka overflow/titik tiga.
    if USE_KEYCODE_MENU_FOR_OVERFLOW:
        log("[NAV] Coba buka overflow pakai KEYCODE_MENU.")
        press_menu()
        settings_xml = try_click_settings_from_menu("overflow_menu_keyevent.xml")
        if settings_xml:
            return settings_xml
        # Kalau KEYCODE_MENU tidak membuka menu, lanjut fallback tanpa Back.
        # Menekan Back di halaman utama WhatsApp bisa malah keluar app.

    # 2) XML exact More options.
    more_node = find_more_options_node(before_nodes, width, height)
    if more_node:
        log("[NAV] Klik More options/titik tiga dari XML exact.")
        click_node(more_node)
    else:
        # 3) Fallback koordinat edge kanan paling atas.
        # Sengaja x dekat edge kanan, bukan area kamera.
        x = max(1, width - 8)
        y = max(1, int(height * 0.060))
        log(f"[NAV] More options tidak ketemu, fallback tap edge kanan atas: {x},{y}")
        tap(x, y)

    sleep(WAIT_MEDIUM)
    settings_xml = try_click_settings_from_menu("overflow_menu.xml")
    if settings_xml:
        return settings_xml

    log("[NAV] Settings/Pengaturan tidak ketemu setelah semua cara buka menu.")
    return None


def open_account_switcher(debug_dir: Path) -> Optional[Path]:
    """
    Dari halaman Settings WhatsApp Personal, klik icon kanan akun atas.
    Icon bisa panah hijau atau plus hijau. Karena icon sering tidak punya text,
    script pakai XML dulu, lalu fallback koordinat area kanan atas.
    """
    width, height = get_screen_size()

    settings_xml = dump_ui(debug_dir, "settings_before_switcher.xml")
    nodes = parse_ui_xml(settings_xml) if settings_xml else []

    # Cari clickable node di kanan atas area profile/settings header
    candidates = []
    for n in nodes:
        b = n.get("bounds")
        if not b:
            continue
        x1, y1, x2, y2 = b
        cx, cy = center_of_bounds(b)
        if n.get("clickable") and cx > width * 0.55 and height * 0.07 < cy < height * 0.32:
            candidates.append(n)

    if candidates:
        # Pilih yang paling kanan, biasanya icon switch/add account.
        candidates.sort(key=lambda n: center_of_bounds(n["bounds"])[0], reverse=True)
        log("[NAV] Klik icon kanan profile top dari XML.")
        click_node(candidates[0])
    else:
        # Fallback sesuai deskripsi: icon di sebelah kanan nomor / plus / panah.
        log("[NAV] Icon switcher tidak ketemu di XML, fallback tap kanan area profile atas.")
        tap(int(width * 0.88), int(height * 0.18))

    sleep(WAIT_LONG)

    switcher_xml = dump_ui(debug_dir, "switcher.xml")
    if not switcher_xml:
        return None

    return switcher_xml


def open_business_edit_profile(debug_dir: Path) -> Optional[Path]:
    """
    Dari halaman Settings WhatsApp Business, klik area profile atas,
    lalu dump halaman edit profile.
    """
    width, height = get_screen_size()

    business_settings_xml = dump_ui(debug_dir, "business_settings_before_profile_click.xml")
    nodes = parse_ui_xml(business_settings_xml) if business_settings_xml else []

    # Coba klik area profile yang clickable di bagian atas kiri/tengah.
    candidates = []
    for n in nodes:
        b = n.get("bounds")
        if not b:
            continue
        cx, cy = center_of_bounds(b)
        if n.get("clickable") and height * 0.08 < cy < height * 0.32 and cx < width * 0.85:
            blob = node_text_blob(n)
            # Hindari more options kanan atas kalau kebaca clickable
            if "more" not in blob and "opsi" not in blob:
                candidates.append(n)

    if candidates:
        candidates.sort(key=lambda n: center_of_bounds(n["bounds"])[1])
        log("[NAV] Klik profile Business dari XML.")
        click_node(candidates[0])
    else:
        log("[NAV] Fallback klik area upper sheet/profile Business.")
        tap(int(width * 0.42), int(height * 0.18))

    sleep(WAIT_LONG)

    edit_xml = dump_ui(debug_dir, "business_edit_profile.xml")
    if not edit_xml:
        return None

    return edit_xml


# ============================================================
# PARSE ACCOUNTS
# ============================================================

def parse_accounts_from_text_sequence(texts: List[str], source: str) -> List[Dict[str, str]]:
    """
    Parse nama+nomor dari urutan text XML.
    Strategi:
    - Temukan text yang berisi nomor.
    - Ambil nama dari text valid terdekat sebelumnya.
    """
    accounts = []
    seen = set()

    clean_texts = [t.strip() for t in texts if t and t.strip()]

    for i, text in enumerate(clean_texts):
        nums = extract_phone_numbers([text])
        if not nums:
            continue

        for num in nums:
            norm = num["normalized_number"]
            if norm in seen:
                continue

            name = None
            for j in range(i - 1, max(-1, i - 5), -1):
                cand = clean_texts[j].strip()
                if is_good_name_candidate(cand):
                    name = cand
                    break

            accounts.append({
                "name": name or "",
                "display_number": num["display_number"],
                "normalized_number": norm,
                "source": source,
            })
            seen.add(norm)

    return accounts


def parse_accounts_from_bottom_sheet(xml_path: Path) -> List[Dict[str, str]]:
    nodes = parse_ui_xml(xml_path)
    texts = get_all_texts(nodes, include_desc=False)
    return parse_accounts_from_text_sequence(texts, "account_switcher_bottom_sheet")


def parse_accounts_from_settings(xml_path: Path) -> List[Dict[str, str]]:
    nodes = parse_ui_xml(xml_path)
    texts = get_all_texts(nodes, include_desc=False)
    return parse_accounts_from_text_sequence(texts, "settings_page")


def parse_business_accounts(xml_paths: List[Path]) -> List[Dict[str, str]]:
    all_texts = []
    for p in xml_paths:
        nodes = parse_ui_xml(p)
        all_texts.extend(get_all_texts(nodes, include_desc=False))

    accounts = parse_accounts_from_text_sequence(all_texts, "business_edit_profile")

    # Business kadang nomor muncul tanpa nama di Contact info.
    if accounts:
        for acc in accounts:
            if not acc.get("name"):
                acc["name"] = ""
        return accounts

    return []


def dedupe_accounts(accounts: List[Dict[str, str]]) -> List[Dict[str, str]]:
    out = []
    seen = set()
    for acc in accounts:
        norm = acc.get("normalized_number") or ""
        key = norm or (acc.get("display_number") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(acc)
    return out


# ============================================================
# SCAN PERSONAL
# ============================================================

def scan_personal_whatsapp(package: str, label_hint: str, launch_user: Optional[str]) -> Dict[str, Any]:
    result = base_result(label_hint, package)
    result["launch_user"] = launch_user
    result["package_found"] = True

    debug_dir = create_debug_dir("wa_personal", launch_user)

    try:
        prepare_before_launch(package, launch_user, debug_dir, prefix="before_launch")
        opened = open_package(package, user_id=launch_user, debug_dir=debug_dir)
        result["app_opened"] = opened

        save_screenshot(debug_dir, "launch_screen.png")
        launch_xml = dump_ui(debug_dir, "launch.xml")

        if not opened:
            result["status"] = "package_found_but_cannot_open"
            result["notes"].append("Package ditemukan, tapi app gagal dibuka lewat launcher/monkey.")
            save_result_json(result, debug_dir)
            return result

        focus = get_current_focus()
        write_text(debug_dir / "focus.txt", focus)

        if not is_current_package(package, focus):
            result["status"] = "package_found_but_cannot_open"
            result["notes"].append("App dibuka, tapi current focus bukan package target.")
            save_result_json(result, debug_dir)
            return result

        detected_user = detect_current_android_user(package)
        result["detected_user"] = detected_user
        result["final_label"] = classify_final_label(package, detected_user)
        if detected_user is None and label_hint in ("WhatsApp Original", "WhatsApp Dual / Clone"):
            # V4: kalau user metadata tidak kebaca, jangan ubah label teknis yang sedang discan.
            result["final_label"] = label_hint

        nodes = parse_ui_xml(launch_xml) if launch_xml else []

        if not launch_xml:
            result["status"] = "opened_but_ui_dump_failed"
            result["notes"].append("App terbuka, tapi UIAutomator XML launch gagal di-dump.")
            save_result_json(result, debug_dir)
            return result

        if detect_locked(nodes):
            result["status"] = "opened_but_locked"
            result["notes"].append("App terbuka, tapi tertahan lock/fingerprint/PIN.")
            save_result_json(result, debug_dir)
            return result

        if detect_not_logged_in(nodes):
            result["status"] = "opened_but_not_logged_in"
            result["notes"].append("App terbuka, tapi WhatsApp belum login / masih welcome screen.")
            save_result_json(result, debug_dir)
            return result

        settings_xml = open_settings(debug_dir, settings_filename="settings.xml")
        if not settings_xml:
            result["status"] = "opened_but_navigation_failed"
            result["notes"].append("Gagal masuk Settings/Pengaturan.")
            save_result_json(result, debug_dir)
            return result

        settings_accounts = parse_accounts_from_settings(settings_xml)

        switcher_xml = open_account_switcher(debug_dir)
        switcher_accounts = []
        if switcher_xml:
            switcher_accounts = parse_accounts_from_bottom_sheet(switcher_xml)

        accounts = dedupe_accounts(switcher_accounts + settings_accounts)
        result["accounts"] = accounts

        if accounts:
            if detected_user is None:
                result["status"] = "package_found_user_unknown"
                result["notes"].append("Akun berhasil dibaca, tapi Android user aktif tidak bisa dipastikan.")
            else:
                result["status"] = "success"
        else:
            result["status"] = "opened_but_number_not_found"
            result["notes"].append("Settings/switcher terbuka, tapi nomor tidak ditemukan di XML.")

        # Rename folder ke label final kalau bisa
        final_debug_dir = finalize_debug_dir(debug_dir, result["final_label"], result["detected_user"])
        save_result_json(result, final_debug_dir)
        return result

    except Exception as e:
        result["status"] = "unknown_error"
        result["notes"].append(f"Exception: {type(e).__name__}: {e}")
        save_result_json(result, debug_dir)
        return result


def account_key_set(result: Dict[str, Any]) -> set:
    return {a.get("normalized_number") for a in (result.get("accounts") or []) if a.get("normalized_number")}


def make_clone_not_found_result(package: str, reason: str) -> Dict[str, Any]:
    debug_dir = create_debug_dir("wa_dual_clone_not_found", None)
    clone_result = base_result("WhatsApp Dual / Clone", package)
    clone_result["final_label"] = "WhatsApp Dual / Clone"
    clone_result["package_found"] = True
    clone_result["app_opened"] = False
    clone_result["status"] = "clone_not_found"
    clone_result["notes"].append(reason)
    save_result_json(clone_result, debug_dir)
    return clone_result


def scan_all_personal_instances(target: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    V4 Personal scan:
    - Tidak scan semua user.
    - Original dibuka default launcher dulu.
    - Dual user 95 hanya fallback teknis opsional, bukan validasi/gate utama.
    """
    package = target["package"]
    results: List[Dict[str, Any]] = []

    if not package_exists(package):
        debug_dir = create_debug_dir("wa_personal_package_not_found", None)
        result = base_result("WhatsApp Personal", package)
        result["package_found"] = False
        result["app_opened"] = False
        result["status"] = "package_not_found"
        result["notes"].append("Package com.whatsapp tidak ditemukan di device.")
        save_result_json(result, debug_dir)
        results.append(result)
        results.append(make_clone_not_found_result(package, "Clone tidak bisa dicek karena package personal tidak ditemukan."))
        return results

    # 1) Original: default launcher. Ini jalur utama.
    original = scan_personal_whatsapp(package, "WhatsApp Original", None)
    results.append(original)

    original_accounts = account_key_set(original)

    # 2) Dual: fallback teknis saja. Original di atas tidak diubah.
    # Samsung Dual Messenger umumnya memakai package yang sama di user/profile lain.
    # Karena di beberapa HP user clone bukan 95, V5 simpan diagnostic dan coba non-owner users.
    if SCAN_DUAL_FALLBACK_USER95:
        diag_dir = create_debug_dir("wa_dual_probe", None)
        users = collect_dual_diagnostics(diag_dir, package)

        candidate_users: List[str] = []
        for u in [DUAL_FALLBACK_USER] + users:
            if u and u != "0" and u not in candidate_users:
                candidate_users.append(u)

        if not TRY_OTHER_NON_OWNER_USERS_FOR_DUAL:
            candidate_users = [DUAL_FALLBACK_USER]

        found_dual = None
        last_dual = None
        last_same_as_original = False

        for dual_user in candidate_users:
            log(f"[DUAL] Coba buka clone via user {dual_user}.")
            dual = scan_personal_whatsapp(package, "WhatsApp Dual / Clone", dual_user)
            last_dual = dual
            dual_accounts = account_key_set(dual)

            dual_success = dual.get("status") in ("success", "package_found_user_unknown") and bool(dual_accounts)
            same_as_original = bool(dual_accounts) and dual_accounts == original_accounts
            last_same_as_original = same_as_original

            if dual_success and not same_as_original:
                dual["final_label"] = "WhatsApp Dual / Clone"
                found_dual = dual
                break

            if same_as_original:
                log(f"[DUAL] User {dual_user} membuka akun yang sama dengan Original, lanjut kandidat lain kalau ada.")
            else:
                log(f"[DUAL] User {dual_user} belum menghasilkan akun clone.")

        if found_dual:
            results.append(found_dual)
        else:
            reason = "Tidak ada bukti instance Dual/Clone yang berhasil dibuka atau terbaca."
            if last_same_as_original:
                reason = "Fallback membuka akun yang sama dengan WhatsApp Original, jadi tidak dihitung sebagai clone terpisah."
            elif last_dual and last_dual.get("app_opened") is False:
                reason = "Fallback user clone gagal membuka WhatsApp Dual. Cek debug wa_dual_probe untuk user/profile/package sebenarnya."
            reason += f" Diagnostic: {diag_dir}"
            results.append(make_clone_not_found_result(package, reason))
    else:
        results.append(make_clone_not_found_result(package, "Scan fallback Dual user 95 dimatikan di konfigurasi."))

    return results


# ============================================================
# SCAN BUSINESS
# ============================================================

def scan_business_whatsapp(package: str, label_hint: str) -> Dict[str, Any]:
    result = base_result(label_hint, package)
    result["package_found"] = True
    result["final_label"] = "WhatsApp Business"

    debug_dir = create_debug_dir("wa_business", None)

    try:
        prepare_before_launch(package, None, debug_dir, prefix="before_launch")
        opened = open_package(package, user_id=None, debug_dir=debug_dir)
        result["app_opened"] = opened

        save_screenshot(debug_dir, "launch_screen.png")
        launch_xml = dump_ui(debug_dir, "launch.xml")

        if not opened:
            result["status"] = "package_found_but_cannot_open"
            result["notes"].append("Package Business ditemukan, tapi app gagal dibuka.")
            save_result_json(result, debug_dir)
            return result

        focus = get_current_focus()
        write_text(debug_dir / "focus.txt", focus)

        if not is_current_package(package, focus):
            result["status"] = "package_found_but_cannot_open"
            result["notes"].append("Business dibuka, tapi current focus bukan package target.")
            save_result_json(result, debug_dir)
            return result

        detected_user = detect_current_android_user(package)
        result["detected_user"] = detected_user

        nodes = parse_ui_xml(launch_xml) if launch_xml else []

        if not launch_xml:
            result["status"] = "opened_but_ui_dump_failed"
            result["notes"].append("App Business terbuka, tapi UIAutomator XML launch gagal di-dump.")
            save_result_json(result, debug_dir)
            return result

        if detect_locked(nodes):
            result["status"] = "opened_but_locked"
            result["notes"].append("Business terbuka, tapi tertahan lock/fingerprint/PIN.")
            save_result_json(result, debug_dir)
            return result

        if detect_not_logged_in(nodes):
            result["status"] = "opened_but_not_logged_in"
            result["notes"].append("Business terbuka, tapi WhatsApp belum login / masih welcome screen.")
            save_result_json(result, debug_dir)
            return result

        settings_xml = open_settings(debug_dir, settings_filename="business_settings.xml")
        if not settings_xml:
            result["status"] = "opened_but_navigation_failed"
            result["notes"].append("Gagal masuk Settings/Pengaturan Business.")
            save_result_json(result, debug_dir)
            return result

        edit_xml = open_business_edit_profile(debug_dir)
        if not edit_xml:
            result["status"] = "opened_but_navigation_failed"
            result["notes"].append("Gagal masuk halaman Edit Profile Business.")
            save_result_json(result, debug_dir)
            return result

        xml_paths = [settings_xml, edit_xml]

        # Scroll bawah beberapa kali untuk cari Contact info / Informasi kontak.
        width, height = get_screen_size()
        for idx in range(1, 4):
            accounts = parse_business_accounts(xml_paths)
            if accounts:
                break

            log(f"[BUSINESS] Scroll cari nomor/contact info #{idx}")
            swipe(int(width * 0.50), int(height * 0.80), int(width * 0.50), int(height * 0.35), 550)
            scrolled_xml = dump_ui(debug_dir, f"business_edit_profile_scroll_{idx}.xml")
            if scrolled_xml:
                xml_paths.append(scrolled_xml)

        accounts = dedupe_accounts(parse_business_accounts(xml_paths))
        result["accounts"] = accounts

        if accounts:
            if detected_user is None:
                result["status"] = "package_found_user_unknown"
                result["notes"].append("Nomor Business berhasil dibaca, tapi Android user aktif tidak bisa dipastikan.")
            else:
                result["status"] = "success"
        else:
            result["status"] = "opened_but_number_not_found"
            result["notes"].append("Edit Profile Business terbuka, tapi nomor tidak ditemukan di XML.")

        final_debug_dir = finalize_debug_dir(debug_dir, result["final_label"], result["detected_user"])
        save_result_json(result, final_debug_dir)
        return result

    except Exception as e:
        result["status"] = "unknown_error"
        result["notes"].append(f"Exception: {type(e).__name__}: {e}")
        save_result_json(result, debug_dir)
        return result


def scan_business_target(target: Dict[str, Any]) -> Dict[str, Any]:
    package = target["package"]
    label_hint = target["label_hint"]

    if not package_exists(package):
        debug_dir = create_debug_dir("wa_business_not_found", None)
        result = base_result(label_hint, package)
        result["final_label"] = "WhatsApp Business"
        result["package_found"] = False
        result["app_opened"] = False
        result["status"] = "business_not_found"
        result["notes"].append("Package com.whatsapp.w4b tidak ditemukan.")
        save_result_json(result, debug_dir)
        return result

    return scan_business_whatsapp(package, label_hint)


# ============================================================
# SUMMARY
# ============================================================

def print_summary(results: List[Dict[str, Any]]) -> None:
    print("\n" + "=" * 80)
    print("SUMMARY CHECKERACC")
    print("=" * 80)

    for idx, r in enumerate(results, start=1):
        print(f"\n[{idx}] {r.get('final_label')}")
        print(f"    Package       : {r.get('package')}")
        print(f"    Launch user   : {r.get('launch_user')}")
        print(f"    Detected user : {r.get('detected_user')}")
        print(f"    Package found : {r.get('package_found')}")
        print(f"    App opened    : {r.get('app_opened')}")
        print(f"    Status        : {r.get('status')}")
        print(f"    Debug dir     : {r.get('debug_dir')}")

        accounts = r.get("accounts") or []
        print(f"    Accounts      : {len(accounts)}")

        for a_idx, acc in enumerate(accounts, start=1):
            name = acc.get("name") or "-"
            display = acc.get("display_number") or "-"
            norm = acc.get("normalized_number") or "-"
            source = acc.get("source") or "-"
            print(f"      - Account {a_idx}")
            print(f"        Name      : {name}")
            print(f"        Display   : {display}")
            print(f"        Normalized: {norm}")
            print(f"        Source    : {source}")

        notes = r.get("notes") or []
        if notes:
            print("    Notes:")
            for note in notes:
                print(f"      - {note}")

    print("\n" + "=" * 80)
    print("Selesai. Cek folder debug/ kalau parsing salah atau butuh bukti XML/screenshot.")
    print("=" * 80)


def save_all_results(results: List[Dict[str, Any]]) -> None:
    ensure_dir(DEBUG_ROOT)
    path = DEBUG_ROOT / f"{now_stamp()}_all_results.json"
    path.write_text(json.dumps(results, indent=4, ensure_ascii=False), encoding="utf-8")
    log(f"[SAVE] Semua result disimpan: {path}")


# ============================================================
# MAIN
# ============================================================

def main() -> int:
    print("=" * 80)
    print("checkeracc.py - WhatsApp Account Checker Automation")
    print("=" * 80)

    if not check_device():
        print("\nDevice tidak siap. Pastikan:")
        print("1. HP tersambung USB.")
        print("2. USB debugging aktif.")
        print("3. adb devices statusnya device, bukan unauthorized.")
        print(f"4. DEVICES sudah benar: {DEVICES}")
        return 1

    # Reset Recent Apps cukup sekali di awal program.
    # Setelah itu antar-scan cukup Home + force-stop target, biar tidak terjadi loop Close All.
    reset_to_clean_home(prefix="startup")

    results: List[Dict[str, Any]] = []

    for target in TARGET_PACKAGES:
        print("\n" + "-" * 80)
        print(f"SCAN TARGET: {target['label_hint']} ({target['package']})")
        print("-" * 80)

        if target["type"] == "personal":
            personal_results = scan_all_personal_instances(target)
            results.extend(personal_results)

        elif target["type"] == "business":
            business_result = scan_business_target(target)
            results.append(business_result)

        else:
            log(f"[SKIP] Unknown target type: {target['type']}")

        # Jangan buka Recent Apps lagi setelah target.
        # Cukup balik Home supaya tidak terjadi Close All berulang.
        press_home()

    save_all_results(results)
    print_summary(results)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nDibatalkan user.")
        raise SystemExit(130)
