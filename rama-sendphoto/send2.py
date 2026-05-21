import os
import re
import time
import math
import subprocess
import xml.etree.ElementTree as ET

import cv2
import numpy as np

# ============================================================
# KONFIGURASI UTAMA
# ============================================================
DEVICE_ID = "R9RL106EV5D"
PHONE_NUM = "628985509377"
FILE_NAME = "tesvideo.mp4"

# "0"  = WhatsApp ori / normal
# "95" = WhatsApp Dual Messenger / clone
USER = "95"

FILE_PATH_HP = f"/storage/emulated/0/DCIM/sendWA/{FILE_NAME}"
WHATSAPP_PACKAGE = "com.whatsapp"

SCREENSHOT_DEVICE = "/sdcard/screen.png"
SCREENSHOT_LOCAL = "screen.png"

UI_XML_DEVICE = "/sdcard/window.xml"
UI_XML_LOCAL = "window.xml"

SAVE_DEBUG_IMAGE = True

# ============================================================
# KONFIG USER 0 - DIAMBIL DARI KODE PERTAMA, JANGAN DIUBAH
# ============================================================
U0_CHOOSER_Y_START_RATIO = 0.22
U0_BADGE_TO_ICON_OFFSET_X = 45
U0_BADGE_TO_ICON_OFFSET_Y = 45
U0_JUST_ONCE_X_RATIO = 0.27
U0_JUST_ONCE_Y_RATIO = 0.92
U0_FALLBACK_ORI_X_RATIO = 0.25
U0_FALLBACK_DUAL_X_RATIO = 0.75
U0_FALLBACK_SHARE_ICON_Y_RATIO = 0.68
U0_SEND_BUTTON_FALLBACK_X_RATIO = 0.92
U0_SEND_BUTTON_FALLBACK_Y_RATIO = 0.91
U0_CHOOSER_SCAN_RETRY = 5
U0_CHOOSER_SCAN_DELAY = 0.8

# ============================================================
# KONFIG USER 95 - DIAMBIL DARI KODE KEDUA, JANGAN DIUBAH
# ============================================================
U95_CHOOSER_TIMEOUT = 14
U95_SEND_TIMEOUT = 22
U95_CHOOSER_Y_START_RATIO = 0.05
U95_BADGE_TO_ICON_OFFSET_X = 45
U95_BADGE_TO_ICON_OFFSET_Y = 45
U95_FALLBACK_ORI_X_RATIO = 0.25
U95_FALLBACK_DUAL_X_RATIO = 0.75
U95_FALLBACK_CHOOSER_Y_RATIO = 0.68
U95_JUST_ONCE_X_RATIO = 0.27
U95_JUST_ONCE_Y_RATIO = 0.92
U95_SEND_BUTTON_FALLBACK_X_RATIO = 0.92
U95_SEND_BUTTON_FALLBACK_Y_RATIO = 0.91


# ============================================================
# HELPER ADB UMUM
# ============================================================
def jalankan_adb(perintah, capture=False):
    full_cmd = f'adb -s "{DEVICE_ID}" {perintah}'
    print(full_cmd)

    if capture:
        return subprocess.run(
            full_cmd,
            shell=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    return subprocess.run(full_cmd, shell=True)


def tap(x, y, label=""):
    x = int(x)
    y = int(y)

    if label:
        print(f"Tap {label} di x={x}, y={y}")
    else:
        print(f"Tap di x={x}, y={y}")

    jalankan_adb(f"shell input tap {x} {y}")


def ambil_screenshot(local_path=SCREENSHOT_LOCAL):
    jalankan_adb(f"shell screencap -p {SCREENSHOT_DEVICE}")
    jalankan_adb(f"pull {SCREENSHOT_DEVICE} {local_path}")

    img = cv2.imread(local_path)
    if img is None:
        print(f"Error: gagal membaca screenshot lokal: {local_path}")
        return None

    return img


def jarak(p1, p2):
    return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)


# ============================================================
# HELPER UIAUTOMATOR - HANYA UNTUK USER 95, SESUAI KODE KEDUA
# ============================================================
def ambil_ui_xml():
    jalankan_adb(f"shell uiautomator dump {UI_XML_DEVICE}", capture=True)
    jalankan_adb(f"pull {UI_XML_DEVICE} {UI_XML_LOCAL}", capture=True)

    if not os.path.exists(UI_XML_LOCAL):
        return ""

    try:
        with open(UI_XML_LOCAL, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception as e:
        print(f"Gagal baca UI XML: {e}")
        return ""


def parse_bounds(bounds_text):
    if not bounds_text:
        return None

    m = re.search(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds_text)
    if not m:
        return None

    x1, y1, x2, y2 = map(int, m.groups())
    return ((x1 + x2) // 2, (y1 + y2) // 2, x1, y1, x2, y2)


def tap_node_by_keywords(keywords, label="", prefer_bottom_right=False):
    xml_text = ambil_ui_xml()
    if not xml_text.strip():
        return False

    try:
        root = ET.fromstring(xml_text)
    except Exception as e:
        print(f"Gagal parse UI XML: {e}")
        return False

    keywords_lower = [k.lower() for k in keywords]
    candidates = []

    for node in root.iter("node"):
        text = (node.attrib.get("text") or "").strip()
        desc = (node.attrib.get("content-desc") or "").strip()
        resource_id = (node.attrib.get("resource-id") or "").strip()
        bounds = node.attrib.get("bounds") or ""

        haystack = f"{text} {desc} {resource_id}".lower()
        if not any(k in haystack for k in keywords_lower):
            continue

        parsed = parse_bounds(bounds)
        if not parsed:
            continue

        cx, cy, x1, y1, x2, y2 = parsed
        width = x2 - x1
        height = y2 - y1
        if width <= 0 or height <= 0:
            continue

        candidates.append({
            "cx": cx,
            "cy": cy,
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
            "text": text,
            "desc": desc,
            "resource_id": resource_id,
        })

    if not candidates:
        return False

    if prefer_bottom_right:
        candidates.sort(key=lambda n: (n["cy"], n["cx"]), reverse=True)
    else:
        candidates.sort(key=lambda n: n["cy"], reverse=True)

    target = candidates[0]
    print(
        f"UI node cocok untuk {label}: "
        f"text='{target['text']}', desc='{target['desc']}', "
        f"bounds=[{target['x1']},{target['y1']}][{target['x2']},{target['y2']}]"
    )
    tap(target["cx"], target["cy"], label or "UI node")
    return True


# ============================================================
# HELPER OPENCV UMUM, PARAMETER DIBEDAKAN PER USER
# ============================================================
def cari_kontur_warna(
    img,
    lower_hsv,
    upper_hsv,
    y_start_ratio=0.0,
    x_start_ratio=0.0,
    x_end_ratio=1.0,
    min_area=50,
    max_area=50000,
    kernel_size=5,
):
    tinggi_layar, lebar_layar, _ = img.shape
    y_offset = int(tinggi_layar * y_start_ratio)
    x_offset = int(lebar_layar * x_start_ratio)
    x_end = int(lebar_layar * x_end_ratio)

    area_scan = img[y_offset:tinggi_layar, x_offset:x_end]

    hsv = cv2.cvtColor(area_scan, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, lower_hsv, upper_hsv)

    kernel = np.ones((kernel_size, kernel_size), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    hasil = []
    for c in contours:
        luas = cv2.contourArea(c)
        if not (min_area <= luas <= max_area):
            continue

        x, y, w, h = cv2.boundingRect(c)
        cx = x_offset + x + w // 2
        cy = y_offset + y + h // 2

        hasil.append({
            "cx": cx,
            "cy": cy,
            "x": x_offset + x,
            "y": y_offset + y,
            "w": w,
            "h": h,
            "area": luas,
        })

    return hasil


# ============================================================
# ======================= ENGINE USER 0 ======================
# ============================================================
# Bagian ini sengaja mengikuti kode pertama karena USER 0 di kode pertama sudah jalan.


def u0_cari_badge_biru_dual(img):
    lower_blue = np.array([95, 70, 60])
    upper_blue = np.array([140, 255, 255])

    return cari_kontur_warna(
        img=img,
        lower_hsv=lower_blue,
        upper_hsv=upper_blue,
        y_start_ratio=U0_CHOOSER_Y_START_RATIO,
        min_area=20,
        max_area=8000,
        kernel_size=5,
    )


def u0_cari_icon_hijau_whatsapp(img):
    lower_green = np.array([30, 40, 40])
    upper_green = np.array([95, 255, 255])

    return cari_kontur_warna(
        img=img,
        lower_hsv=lower_green,
        upper_hsv=upper_green,
        y_start_ratio=U0_CHOOSER_Y_START_RATIO,
        min_area=250,
        max_area=70000,
        kernel_size=5,
    )


def u0_gambar_debug_target(img, badge_biru, icon_hijau, target, konteks):
    if not SAVE_DEBUG_IMAGE:
        return

    debug = img.copy()

    for b in badge_biru:
        cv2.rectangle(debug, (b["x"], b["y"]), (b["x"] + b["w"], b["y"] + b["h"]), (255, 0, 0), 2)
        cv2.circle(debug, (b["cx"], b["cy"]), 5, (255, 0, 0), -1)

    for g in icon_hijau:
        cv2.rectangle(debug, (g["x"], g["y"]), (g["x"] + g["w"], g["y"] + g["h"]), (0, 255, 0), 2)
        cv2.circle(debug, (g["cx"], g["cy"]), 5, (0, 255, 0), -1)

    if target is not None:
        cv2.circle(debug, (int(target["cx"]), int(target["cy"])), 14, (0, 0, 255), 3)
        cv2.putText(
            debug,
            f"TARGET USER=0 - {konteks}",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 0, 255),
            2,
        )

    cv2.imwrite("debug_u0_chooser.png", debug)
    print("Debug chooser USER 0 disimpan ke: debug_u0_chooser.png")


def u0_cari_icon_dual_dari_badge(badge, icon_hijau):
    tebakan_cx = badge["cx"] - U0_BADGE_TO_ICON_OFFSET_X
    tebakan_cy = badge["cy"] - U0_BADGE_TO_ICON_OFFSET_Y

    if icon_hijau:
        kandidat = min(icon_hijau, key=lambda g: jarak((g["cx"], g["cy"]), (tebakan_cx, tebakan_cy)))

        if jarak((kandidat["cx"], kandidat["cy"]), (tebakan_cx, tebakan_cy)) <= 220:
            return {
                "cx": kandidat["cx"],
                "cy": kandidat["cy"],
                "source": "u0_green_icon_near_blue_badge",
                "raw": kandidat,
            }

    return {
        "cx": tebakan_cx,
        "cy": tebakan_cy,
        "source": "u0_fallback_badge_offset",
        "raw": badge,
    }


def u0_pilih_target_whatsapp(img, konteks="chooser"):
    tinggi_layar, lebar_layar, _ = img.shape

    badge_biru = u0_cari_badge_biru_dual(img)
    icon_hijau = u0_cari_icon_hijau_whatsapp(img)

    print(f"[USER 0 / {konteks}] Jumlah badge biru terdeteksi: {len(badge_biru)}")
    print(f"[USER 0 / {konteks}] Jumlah kandidat icon hijau WhatsApp terdeteksi: {len(icon_hijau)}")

    if not badge_biru:
        if icon_hijau:
            icon_sorted = sorted(icon_hijau, key=lambda g: (g["cy"], g["cx"]))
            row_y = icon_sorted[0]["cy"]
            satu_baris = [g for g in icon_hijau if abs(g["cy"] - row_y) <= 180]
            pilihan = satu_baris if satu_baris else icon_hijau

            target_raw = min(pilihan, key=lambda g: g["cx"])
            print("USER 0: badge biru tidak ketemu. Fallback kode pertama: pilih icon WhatsApp paling kiri dari deteksi hijau.")
            return {
                "cx": target_raw["cx"],
                "cy": target_raw["cy"],
                "source": "u0_fallback_leftmost_green_icon_for_ori",
                "raw": target_raw,
            }, badge_biru, icon_hijau

        print("USER 0: badge biru dan icon hijau tidak ketemu.")
        return None, badge_biru, icon_hijau

    badge_biru = sorted(badge_biru, key=lambda b: b["area"], reverse=True)
    badge_utama = badge_biru[0]
    icon_dual_list = [u0_cari_icon_dual_dari_badge(b, icon_hijau) for b in badge_biru]
    icon_dual_utama = u0_cari_icon_dual_dari_badge(badge_utama, icon_hijau)

    print("USER 0: memilih WhatsApp ori, yaitu icon hijau yang tidak dekat dengan badge biru.")

    kandidat_ori = []
    for g in icon_hijau:
        dekat_dual = False
        for d in icon_dual_list:
            if jarak((g["cx"], g["cy"]), (d["cx"], d["cy"])) <= 160:
                dekat_dual = True
                break

        if not dekat_dual:
            kandidat_ori.append(g)

    if kandidat_ori:
        same_row = [g for g in kandidat_ori if abs(g["cy"] - icon_dual_utama["cy"]) <= 180]
        pilihan = same_row if same_row else kandidat_ori
        target_raw = min(
            pilihan,
            key=lambda g: (abs(g["cy"] - icon_dual_utama["cy"]), abs(g["cx"] - icon_dual_utama["cx"])),
        )
        return {
            "cx": target_raw["cx"],
            "cy": target_raw["cy"],
            "source": "u0_green_icon_not_near_blue_badge",
            "raw": target_raw,
        }, badge_biru, icon_hijau

    print("USER 0: kandidat ori tidak ketemu. Pakai fallback mirror dari kode pertama.")
    if icon_dual_utama["cx"] >= lebar_layar / 2:
        fallback_cx = int(lebar_layar * U0_FALLBACK_ORI_X_RATIO)
    else:
        fallback_cx = int(lebar_layar * U0_FALLBACK_DUAL_X_RATIO)

    return {
        "cx": fallback_cx,
        "cy": icon_dual_utama["cy"],
        "source": "u0_fallback_mirror_from_dual_icon",
        "raw": None,
    }, badge_biru, icon_hijau


def u0_pilih_whatsapp_di_chooser(tekan_just_once=False, konteks="chooser"):
    print(f"USER 0: mendeteksi pilihan WhatsApp di layar {konteks}...")

    last_img = None
    last_badge = []
    last_green = []
    last_target = None

    for percobaan in range(1, U0_CHOOSER_SCAN_RETRY + 1):
        print(f"USER 0: percobaan scan chooser {percobaan}/{U0_CHOOSER_SCAN_RETRY}...")
        img = ambil_screenshot()
        if img is None:
            time.sleep(U0_CHOOSER_SCAN_DELAY)
            continue

        last_img = img
        tinggi_layar, lebar_layar, _ = img.shape
        target, badge_biru, icon_hijau = u0_pilih_target_whatsapp(img, konteks=konteks)

        last_badge = badge_biru
        last_green = icon_hijau
        last_target = target

        if target is not None:
            u0_gambar_debug_target(img, badge_biru, icon_hijau, target, konteks)
            print(f"USER 0: target dipilih dari metode: {target['source']}")
            tap(target["cx"], target["cy"], label="WhatsApp Ori USER 0")

            if tekan_just_once:
                time.sleep(1)
                just_once_x = int(lebar_layar * U0_JUST_ONCE_X_RATIO)
                just_once_y = int(tinggi_layar * U0_JUST_ONCE_Y_RATIO)
                tap(just_once_x, just_once_y, label="Just once USER 0")

            time.sleep(3)
            return True

        time.sleep(U0_CHOOSER_SCAN_DELAY)

    if last_img is not None:
        u0_gambar_debug_target(last_img, last_badge, last_green, last_target, konteks)

    print("USER 0: target WhatsApp tidak berhasil ditentukan setelah retry.")
    return False


def u0_cari_tombol_kirim_preview(img):
    lower_green = np.array([35, 60, 50])
    upper_green = np.array([95, 255, 255])

    kandidat = cari_kontur_warna(
        img=img,
        lower_hsv=lower_green,
        upper_hsv=upper_green,
        y_start_ratio=0.55,
        x_start_ratio=0.45,
        x_end_ratio=1.0,
        min_area=250,
        max_area=50000,
        kernel_size=5,
    )

    if not kandidat:
        return None, []

    tinggi_layar, lebar_layar, _ = img.shape

    def score(k):
        return (k["cx"] / lebar_layar) * 3 + (k["cy"] / tinggi_layar) * 3 + min(k["area"], 10000) / 10000

    target = max(kandidat, key=score)
    return target, kandidat


def u0_gambar_debug_send_button(img, kandidat, target):
    if not SAVE_DEBUG_IMAGE:
        return

    debug = img.copy()
    for k in kandidat:
        cv2.rectangle(debug, (k["x"], k["y"]), (k["x"] + k["w"], k["y"] + k["h"]), (0, 255, 0), 2)
        cv2.circle(debug, (k["cx"], k["cy"]), 5, (0, 255, 0), -1)

    if target is not None:
        cv2.circle(debug, (target["cx"], target["cy"]), 16, (0, 0, 255), 3)
        cv2.putText(
            debug,
            "SEND BUTTON TARGET USER 0",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 0, 255),
            2,
        )

    cv2.imwrite("debug_u0_send_button.png", debug)
    print("Debug tombol kirim USER 0 disimpan ke: debug_u0_send_button.png")


def u0_tekan_tombol_kirim_gambar():
    print("USER 0: menunggu WhatsApp memuat preview gambar...")
    time.sleep(4)

    img = ambil_screenshot()
    if img is None:
        print("USER 0: screenshot gagal. Tidak bisa tekan tombol kirim.")
        return False

    tinggi_layar, lebar_layar, _ = img.shape
    target, kandidat = u0_cari_tombol_kirim_preview(img)
    u0_gambar_debug_send_button(img, kandidat, target)

    if target is not None:
        print("USER 0: tombol kirim terdeteksi dari warna hijau kanan bawah.")
        tap(target["cx"], target["cy"], label="tombol kirim preview gambar USER 0")
        time.sleep(2)
        return True

    fallback_x = int(lebar_layar * U0_SEND_BUTTON_FALLBACK_X_RATIO)
    fallback_y = int(tinggi_layar * U0_SEND_BUTTON_FALLBACK_Y_RATIO)
    print("USER 0: tombol kirim tidak terdeteksi via OpenCV. Pakai fallback kanan bawah.")
    tap(fallback_x, fallback_y, label="fallback tombol kirim kanan bawah USER 0")
    time.sleep(2)

    print("USER 0: fallback tambahan tekan Enter.")
    jalankan_adb("shell input keyevent 66")
    time.sleep(1)
    return True


def u0_buka_chat_dulu():
    print("USER 0: membuka chat target via wa.me agar nomor dikenali WhatsApp Ori...")
    cmd = (
        f"shell am start "
        f"-a android.intent.action.VIEW "
        f"-d \"https://wa.me/{PHONE_NUM}\" "
    )
    jalankan_adb(cmd)

    time.sleep(2)

    berhasil = u0_pilih_whatsapp_di_chooser(
        tekan_just_once=True,
        konteks="Open with / wa.me",
    )

    time.sleep(5)
    return berhasil


def u0_mulai_intent_share():
    print("USER 0: memicu intent share WhatsApp...")
    
    mime_type = get_mime_type(FILE_NAME)
    cmd_intent = (
        f"shell am start -p {WHATSAPP_PACKAGE} "
        f"-a android.intent.action.SEND "
        f"-c android.intent.category.DEFAULT "
        f"-t \"{mime_type}\" "
        f"-e jid \"{PHONE_NUM}@s.whatsapp.net\" "
        f"--eu android.intent.extra.STREAM file://{FILE_PATH_HP}"
    )

    print("CMD INTENT USER 0:")
    print(cmd_intent)
    jalankan_adb(cmd_intent)


def main_user0():
    print("==================== MODE USER 0 / WHATSAPP ORI ====================")

    if not u0_buka_chat_dulu():
        print("USER 0: otomatisasi dihentikan karena gagal memilih WhatsApp saat buka chat awal.")
        return

    jalankan_adb("shell input keyevent 3")
    time.sleep(1)

    u0_mulai_intent_share()
    time.sleep(2)

    if not u0_pilih_whatsapp_di_chooser(
        tekan_just_once=False,
        konteks="Share with / kirim gambar",
    ):
        print("USER 0: otomatisasi dihentikan karena gagal memilih WhatsApp di layar Share with.")
        return
    
    if FILE_NAME.lower().endswith((".mp4")):
        tap_ok_modal_share()

    if u0_tekan_tombol_kirim_gambar():
        print("USER 0: proses selesai berhasil!")
    else:
        print("USER 0: proses selesai, tapi tombol kirim gagal dieksekusi.")


# ============================================================
# ======================= ENGINE USER 95 =====================
# ============================================================
# Bagian ini sengaja mengikuti kode kedua karena USER 95 di kode kedua sudah jalan.


def u95_cari_badge_biru_dual(img):
    lower_blue = np.array([90, 45, 45])
    upper_blue = np.array([145, 255, 255])

    return cari_kontur_warna(
        img=img,
        lower_hsv=lower_blue,
        upper_hsv=upper_blue,
        y_start_ratio=U95_CHOOSER_Y_START_RATIO,
        min_area=8,
        max_area=12000,
        kernel_size=3,
    )


def u95_cari_icon_hijau_whatsapp(img):
    lower_green = np.array([28, 35, 35])
    upper_green = np.array([95, 255, 255])

    return cari_kontur_warna(
        img=img,
        lower_hsv=lower_green,
        upper_hsv=upper_green,
        y_start_ratio=U95_CHOOSER_Y_START_RATIO,
        min_area=80,
        max_area=60000,
        kernel_size=3,
    )


def u95_simpan_debug_chooser(img, badges, icons, target, nama_file):
    if not SAVE_DEBUG_IMAGE or img is None:
        return

    dbg = img.copy()

    for b in badges:
        cv2.rectangle(
            dbg,
            (b["x"], b["y"]),
            (b["x"] + b["w"], b["y"] + b["h"]),
            (255, 0, 0),
            2,
        )
        cv2.putText(
            dbg,
            "blue",
            (b["x"], max(20, b["y"] - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 0, 0),
            1,
        )

    for g in icons:
        cv2.rectangle(
            dbg,
            (g["x"], g["y"]),
            (g["x"] + g["w"], g["y"] + g["h"]),
            (0, 255, 0),
            2,
        )
        cv2.putText(
            dbg,
            "green",
            (g["x"], max(20, g["y"] - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 255, 0),
            1,
        )

    if target:
        cv2.circle(dbg, (int(target[0]), int(target[1])), 18, (0, 0, 255), 3)
        cv2.putText(
            dbg,
            "TAP USER 95",
            (int(target[0]) + 20, int(target[1])),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 0, 255),
            2,
        )

    cv2.imwrite(nama_file, dbg)
    print(f"Debug chooser USER 95 disimpan: {nama_file}")


def u95_pilih_target_dari_screenshot(img):
    badges = u95_cari_badge_biru_dual(img)
    icons = u95_cari_icon_hijau_whatsapp(img)

    print(f"USER 95: deteksi chooser: badge_biru={len(badges)}, icon_hijau={len(icons)}")

    if badges:
        badge = sorted(badges, key=lambda b: (b["area"], b["cx"], b["cy"]), reverse=True)[0]

        tebakan_cx = badge["cx"] - U95_BADGE_TO_ICON_OFFSET_X
        tebakan_cy = badge["cy"] - U95_BADGE_TO_ICON_OFFSET_Y

        if icons:
            kandidat = min(icons, key=lambda g: jarak((g["cx"], g["cy"]), (tebakan_cx, tebakan_cy)))
            if jarak((kandidat["cx"], kandidat["cy"]), (tebakan_cx, tebakan_cy)) <= 230:
                print("USER 95: pilih icon hijau terdekat dari badge biru.")
                return kandidat["cx"], kandidat["cy"], badges, icons

        print("USER 95: icon hijau dekat badge tidak ketemu. Pakai offset dari badge biru.")
        return tebakan_cx, tebakan_cy, badges, icons

    if icons:
        icons_sorted = sorted(icons, key=lambda g: g["cx"])
        g = icons_sorted[-1]
        print("USER 95: badge biru tidak ketemu. Fallback kode kedua: icon hijau paling kanan.")
        return g["cx"], g["cy"], badges, icons

    return None, None, badges, icons


def u95_tap_just_once_jika_muncul(timeout=6):
    print("USER 95: mencari tombol Just once / Sekali saja...")

    keywords = [
        "just once",
        "sekali",
        "hanya sekali",
        "once",
    ]

    start = time.time()
    while time.time() - start < timeout:
        if tap_node_by_keywords(keywords, label="Just once USER 95"):
            time.sleep(1.2)
            return True
        time.sleep(0.6)

    img = ambil_screenshot()
    if img is not None:
        h, w, _ = img.shape
        tap(w * U95_JUST_ONCE_X_RATIO, h * U95_JUST_ONCE_Y_RATIO, "fallback Just once USER 95")
        time.sleep(1.2)
        return True

    return False


def u95_pilih_whatsapp_di_chooser(konteks, tap_just_once=False):
    print(f"USER 95: menunggu chooser {konteks}...")

    start = time.time()
    last_img = None
    last_badges = []
    last_icons = []

    while time.time() - start < U95_CHOOSER_TIMEOUT:
        img = ambil_screenshot()
        if img is None:
            time.sleep(0.7)
            continue

        last_img = img
        x, y, badges, icons = u95_pilih_target_dari_screenshot(img)
        last_badges = badges
        last_icons = icons

        if x is not None and y is not None:
            debug_name = f"debug_u95_chooser_{konteks}.png".replace("/", "_").replace(" ", "_")
            u95_simpan_debug_chooser(img, badges, icons, (x, y), debug_name)

            tap(x, y, f"WhatsApp Dual USER 95 di chooser {konteks}")

            if tap_just_once:
                time.sleep(0.9)
                u95_tap_just_once_jika_muncul()

            time.sleep(2.0)
            return True

        print("USER 95: chooser belum terdeteksi jelas, retry...")
        time.sleep(0.9)

    if last_img is not None:
        debug_name = f"debug_u95_chooser_{konteks}_failed.png".replace("/", "_").replace(" ", "_")
        u95_simpan_debug_chooser(last_img, last_badges, last_icons, None, debug_name)

        h, w, _ = last_img.shape
        fx = w * U95_FALLBACK_DUAL_X_RATIO
        fy = h * U95_FALLBACK_CHOOSER_Y_RATIO
        print("USER 95: deteksi chooser gagal. Coba fallback WhatsApp Dual berdasarkan posisi kanan.")
        tap(fx, fy, f"fallback WhatsApp Dual USER 95 di chooser {konteks}")

        if tap_just_once:
            time.sleep(0.9)
            u95_tap_just_once_jika_muncul()

        time.sleep(2.0)
        return True

    return False


def u95_cari_tombol_kirim_dari_screenshot(img):
    h, w, _ = img.shape

    lower_green = np.array([35, 45, 45])
    upper_green = np.array([95, 255, 255])

    candidates = cari_kontur_warna(
        img=img,
        lower_hsv=lower_green,
        upper_hsv=upper_green,
        y_start_ratio=0.55,
        x_start_ratio=0.55,
        x_end_ratio=1.0,
        min_area=150,
        max_area=30000,
        kernel_size=3,
    )

    filtered = []
    for c in candidates:
        aspect = c["w"] / max(1, c["h"])
        if not (0.45 <= aspect <= 2.2):
            continue
        if c["cx"] < w * 0.60 or c["cy"] < h * 0.60:
            continue
        filtered.append(c)

    if not filtered:
        return None, candidates

    filtered.sort(key=lambda c: (c["cy"], c["cx"], c["area"]), reverse=True)
    c = filtered[0]
    return (c["cx"], c["cy"]), candidates


def u95_simpan_debug_send(img, candidates, target=None):
    if not SAVE_DEBUG_IMAGE or img is None:
        return

    dbg = img.copy()
    for c in candidates:
        cv2.rectangle(
            dbg,
            (c["x"], c["y"]),
            (c["x"] + c["w"], c["y"] + c["h"]),
            (0, 255, 0),
            2,
        )

    if target:
        cv2.circle(dbg, (int(target[0]), int(target[1])), 18, (0, 0, 255), 3)
        cv2.putText(
            dbg,
            "SEND USER 95",
            (int(target[0]) - 45, int(target[1]) - 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 0, 255),
            2,
        )

    cv2.imwrite("debug_u95_send_button.png", dbg)
    print("Debug send button USER 95 disimpan: debug_u95_send_button.png")


def u95_tunggu_preview_lalu_kirim():
    print("USER 95: menunggu preview gambar WhatsApp sampai tombol kirim siap...")

    send_keywords = [
        "kirim",
        "send",
    ]

    start = time.time()
    last_img = None
    last_candidates = []

    while time.time() - start < U95_SEND_TIMEOUT:
        if tap_node_by_keywords(send_keywords, label="tombol Kirim/Send USER 95", prefer_bottom_right=True):
            time.sleep(1.0)
            print("USER 95: tombol kirim diklik via UIAutomator.")
            return True

        img = ambil_screenshot()
        if img is not None:
            last_img = img
            target, candidates = u95_cari_tombol_kirim_dari_screenshot(img)
            last_candidates = candidates

            if target:
                u95_simpan_debug_send(img, candidates, target)
                tap(target[0], target[1], "tombol kirim hasil deteksi OpenCV USER 95")
                time.sleep(1.0)
                print("USER 95: tombol kirim diklik via OpenCV.")
                return True

        print("USER 95: preview/tombol kirim belum siap, retry...")
        time.sleep(0.9)

    if last_img is not None:
        u95_simpan_debug_send(last_img, last_candidates, None)
        h, w, _ = last_img.shape
        print("USER 95: tombol kirim tidak terdeteksi jelas. Coba fallback kanan bawah + Enter.")
        tap(w * U95_SEND_BUTTON_FALLBACK_X_RATIO, h * U95_SEND_BUTTON_FALLBACK_Y_RATIO, "fallback tombol kirim USER 95")
        time.sleep(0.5)
        jalankan_adb("shell input keyevent 66")
        return True

    return False


def u95_buka_chat_dulu():
    print("USER 95: membuka chat target via wa.me agar nomor dikenali WhatsApp Dual...")
    cmd = (
        f"shell am start "
        f"-a android.intent.action.VIEW "
        f"-d \"https://wa.me/{PHONE_NUM}\""
    )
    jalankan_adb(cmd)

    if not u95_pilih_whatsapp_di_chooser("open_with", tap_just_once=True):
        print("USER 95: gagal memilih WhatsApp di layar Open With.")
        return False

    time.sleep(4)
    return True


def u95_share_file_ke_whatsapp():
    print("USER 95: memicu intent share WhatsApp...")

    mime_type = get_mime_type(FILE_NAME)
    cmd_intent = (
        f"shell am start -p {WHATSAPP_PACKAGE} "
        f"-a android.intent.action.SEND "
        f"-c android.intent.category.DEFAULT "
        f"-t \"{mime_type}\" "
        f"--grant-read-uri-permission "
        f"-e jid \"{PHONE_NUM}@s.whatsapp.net\" "
        f"--eu android.intent.extra.STREAM file://{FILE_PATH_HP}"
    )

    print("CMD INTENT USER 95:")
    print(cmd_intent)
    jalankan_adb(cmd_intent)

    if not u95_pilih_whatsapp_di_chooser("share_with", tap_just_once=False):
        print("USER 95: gagal memilih WhatsApp di layar Share With.")
        return False

    if FILE_NAME.lower().endswith((".mp4")):
        tap_ok_modal_share()

    if not u95_tunggu_preview_lalu_kirim():
        print("USER 95: gagal klik tombol kirim.")
        return False

    return True


def main_user95():
    print("==================== MODE USER 95 / WHATSAPP DUAL ====================")

    if not u95_buka_chat_dulu():
        print("USER 95: proses dihentikan karena chat awal gagal dibuka.")
        return

    jalankan_adb("shell input keyevent 3")
    time.sleep(1.2)

    if u95_share_file_ke_whatsapp():
        print("USER 95: proses selesai berhasil!")
    else:
        print("USER 95: proses selesai, tetapi ada tahap yang gagal.")

# ============================================================
# ============== HANDLING FILE TYPE SENT =====================
# ============================================================

def get_mime_type(file_name):
    ext = file_name.lower()

    if ext.endswith(".jpg") or ext.endswith(".jpeg"):
        return "image/jpeg"
    elif ext.endswith(".png"):
        return "image/png"
    elif ext.endswith(".mp4"):
        return "video/mp4"
    else:
        return "*/*"
    
# ============================================================
# =============== KLIK OK SHARE CONFIRM ======================
# ============================================================    

def tap_ok_modal_share():
    print("Cek / klik OK modal konfirmasi share...")

    # Coba via UIAutomator dulu, lebih aman untuk USER 95
    if tap_node_by_keywords(["ok"], label="OK modal konfirmasi share", prefer_bottom_right=True):
        time.sleep(2)
        return True

    # Fallback koordinat kalau UIAutomator gagal baca OK
    img = ambil_screenshot()
    if img is None:
        print("Gagal screenshot saat cek modal OK.")
        return False

    tinggi_layar, lebar_layar, _ = img.shape

    ok_x = int(lebar_layar * 0.78)
    ok_y = int(tinggi_layar * 0.52)

    tap(ok_x, ok_y, label="fallback OK modal konfirmasi share")
    time.sleep(2)
    return True

# ============================================================
# MAIN DISPATCHER
# ============================================================
def main():
    if USER not in ("0", "95"):
        print(f"USER tidak valid: {USER}. Isi USER dengan \"0\" atau \"95\".")
        return

    print("==================== KONFIGURASI AKTIF ====================")
    print(f"DEVICE_ID : {DEVICE_ID}")
    print(f"PHONE_NUM : {PHONE_NUM}")
    print(f"FILE_NAME : {FILE_NAME}")
    print(f"USER      : {USER} ({'WhatsApp Ori' if USER == '0' else 'WhatsApp Dual'})")
    print("============================================================")

    if USER == "0":
        main_user0()
    else:
        main_user95()


if __name__ == "__main__":
    main()
