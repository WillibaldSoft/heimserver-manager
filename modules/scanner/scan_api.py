#!/usr/bin/env python3

from flask import Flask, jsonify
from datetime import datetime
import subprocess
import os
import glob
import json
import shutil
import fcntl
import traceback
import time

app = Flask(__name__)

DEVICE = os.environ.get("SCANNER_DEVICE", "auto")

OUTDIR = os.environ.get("SCAN_OUTDIR", "/srv/scanner/output")
SESSION_DIR = os.environ.get("SCAN_SESSION_DIR", "/var/lib/scansession")
SESSION_FILE = f"{SESSION_DIR}/session.json"
LOCK_FILE = f"{SESSION_DIR}/scan.lock"

os.makedirs(OUTDIR, exist_ok=True)
os.makedirs(SESSION_DIR, exist_ok=True)


def now_stamp():
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def api_error(message, code=500, detail=None):
    data = {"ok": False, "error": message}
    if detail:
        data["detail"] = detail
    return jsonify(data), code


def read_session():
    if not os.path.exists(SESSION_FILE):
        return None
    with open(SESSION_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_session(session):
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(session, f)


def clear_session_files():
    for f in glob.glob(f"{SESSION_DIR}/*"):
        if os.path.basename(f) == "scan.lock":
            continue
        try:
            os.remove(f)
        except IsADirectoryError:
            shutil.rmtree(f, ignore_errors=True)


def new_session(mode):
    clear_session_files()
    session = {
        "mode": mode,
        "started": now_stamp(),
        "pages": 0
    }
    save_session(session)
    return session


def ensure_session(mode):
    session = read_session()

    if session is None:
        return new_session(mode), None

    current_mode = session.get("mode")

    if current_mode != mode:
        return None, (
            f"Aktive Session ist '{current_mode}', angefordert wurde '{mode}'. "
            "Erst fertigstellen oder abbrechen."
        )

    return session, None


def set_file_permissions(path):
    try:
        os.chmod(path, int(os.environ.get('SCAN_FILE_MODE','0664'),8))
    except PermissionError:
        pass


def valid_files(pattern):
    files = sorted(glob.glob(pattern))
    return [
        f for f in files
        if os.path.exists(f)
        and os.path.isfile(f)
        and os.path.getsize(f) > 0
    ]


def run_scan(path, resolution, color_mode, intent, output_format):
    part_path = f"{path}.part"

    if os.path.exists(part_path):
        os.remove(part_path)

    with open(part_path, "wb") as out:
        subprocess.run(
            [
                "scanimage",
                *(["-d", DEVICE] if DEVICE != "auto" else []),
                "--scan-intent", intent,
                "--resolution", str(resolution),
                "--mode", color_mode,
                f"--format={output_format}",
            ],
            stdout=out,
            stderr=subprocess.PIPE,
            text=False,
            check=True,
        )

    if not os.path.exists(part_path) or os.path.getsize(part_path) == 0:
        try:
            os.remove(part_path)
        except FileNotFoundError:
            pass
        raise RuntimeError("Scanner hat eine leere Datei erzeugt")

    os.rename(part_path, path)
    set_file_permissions(path)


def scan_for_mode(mode):
    session, error = ensure_session(mode)

    if error:
        return api_error(error, 409)

    page = int(session.get("pages", 0)) + 1
    page_str = f"{page:04d}"

    if mode == "pdf":
        filename = f"{SESSION_DIR}/{page_str}.png"
        run_scan(filename, 300, "Color", "Document", "png")

    elif mode == "quickpdf":
        filename = f"{SESSION_DIR}/{page_str}.png"
        run_scan(filename, 150, "Color", "Document", "png")

    elif mode == "jpg":
        filename = f"{SESSION_DIR}/{page_str}.jpg"
        run_scan(filename, 600, "Color", "Photo", "jpeg")

    elif mode == "tiff":
        filename = f"{SESSION_DIR}/{page_str}.tif"
        run_scan(filename, 600, "Color", "Photo", "tiff")

    else:
        return api_error(f"Unbekannter Modus: {mode}", 400)

    session["pages"] = page
    save_session(session)

    return jsonify({
        "ok": True,
        "message": f"Seite {page} gescannt",
        "mode": mode,
        "pages": page,
        "started": session["started"]
    })


def locked_call(func, wait_seconds=0):
    deadline = time.time() + wait_seconds

    with open(LOCK_FILE, "w") as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.time() >= deadline:
                    return api_error("Scanner ist bereits beschäftigt", 423)
                time.sleep(1)

        try:
            return func()

        except subprocess.CalledProcessError as e:
            detail = ""
            try:
                detail = (
                    e.stderr.decode(errors="replace")
                    if isinstance(e.stderr, bytes)
                    else str(e.stderr)
                )
            except Exception:
                detail = str(e)

            return api_error("Scan-Befehl fehlgeschlagen", 500, detail)

        except Exception as e:
            return api_error(str(e), 500, traceback.format_exc())


@app.route("/")
def index():
    return jsonify({
        "service": "Scanner API",
        "device": DEVICE,
        "outdir": OUTDIR,
        "session_dir": SESSION_DIR,
        "logic": "Jeder Scan-Endpunkt startet automatisch eine Session, wenn keine läuft.",
        "endpoints": [
            "/pdfscan",
            "/quickscan",
            "/jpgscan",
            "/tiffscan",
            "/finish",
            "/cancel",
            "/status"
        ]
    })


@app.route("/pdfscan")
def pdfscan():
    return locked_call(lambda: scan_for_mode("pdf"))


@app.route("/quickscan")
def quickscan():
    return locked_call(lambda: scan_for_mode("quickpdf"))


@app.route("/jpgscan")
def jpgscan():
    return locked_call(lambda: scan_for_mode("jpg"))


@app.route("/tiffscan")
def tiffscan():
    return locked_call(lambda: scan_for_mode("tiff"))


@app.route("/finish")
def finish():
    def do_finish():
        session = read_session()

        if not session:
            return api_error("Keine aktive Scan-Session", 400)

        mode = session.get("mode")
        pages = int(session.get("pages", 0))
        stamp = session.get("started", now_stamp())

        if pages <= 0:
            clear_session_files()
            return api_error("Keine Seiten gescannt", 400)

        if mode in ("pdf", "quickpdf"):
            files = valid_files(f"{SESSION_DIR}/*.png")

            if not files:
                return api_error("Keine gültigen PNG-Seiten gefunden", 400)

            prefix = "quickscan" if mode == "quickpdf" else "scan"
            outfile = f"{OUTDIR}/{prefix}_{stamp}.pdf"
            part_outfile = f"{outfile}.part"

            if os.path.exists(part_outfile):
                os.remove(part_outfile)

            subprocess.run(
                ["img2pdf", *files, "-o", part_outfile],
                stderr=subprocess.PIPE,
                check=True,
            )

            if not os.path.exists(part_outfile) or os.path.getsize(part_outfile) == 0:
                return api_error("PDF-Erzeugung fehlgeschlagen: Ausgabedatei ist leer", 500)

            os.rename(part_outfile, outfile)
            set_file_permissions(outfile)
            clear_session_files()

            return jsonify({
                "ok": True,
                "message": "PDF erstellt",
                "file": outfile,
                "pages": len(files)
            })

        if mode == "jpg":
            files = valid_files(f"{SESSION_DIR}/*.jpg")

            if not files:
                return api_error("Keine gültigen JPG-Seiten gefunden", 400)

            created = []

            for index, src in enumerate(files, start=1):
                outfile = f"{OUTDIR}/scan_{stamp}_{index:03d}.jpg"
                shutil.move(src, outfile)
                set_file_permissions(outfile)
                created.append(outfile)

            clear_session_files()

            return jsonify({
                "ok": True,
                "message": "JPG-Dateien gespeichert",
                "files": created,
                "pages": len(created)
            })

        if mode == "tiff":
            files = valid_files(f"{SESSION_DIR}/*.tif")

            if not files:
                return api_error("Keine gültigen TIFF-Seiten gefunden", 400)

            created = []

            for index, src in enumerate(files, start=1):
                outfile = f"{OUTDIR}/scan_{stamp}_{index:03d}.tif"
                shutil.move(src, outfile)
                set_file_permissions(outfile)
                created.append(outfile)

            clear_session_files()

            return jsonify({
                "ok": True,
                "message": "TIFF-Dateien gespeichert",
                "files": created,
                "pages": len(created)
            })

        return api_error(f"Unbekannter Modus: {mode}", 400)

    return locked_call(do_finish, wait_seconds=180)


@app.route("/cancel")
def cancel():
    def do_cancel():
        clear_session_files()
        return jsonify({
            "ok": True,
            "message": "Scan-Session abgebrochen und gelöscht"
        })

    return locked_call(do_cancel, wait_seconds=30)


@app.route("/status")
def status():
    session = read_session()

    if not session:
        return jsonify({"active": False})

    files = glob.glob(f"{SESSION_DIR}/*")
    valid = [
        f for f in files
        if os.path.isfile(f)
        and os.path.getsize(f) > 0
        and not f.endswith(".json")
        and not f.endswith(".lock")
        and not f.endswith(".part")
    ]

    return jsonify({
        "active": True,
        "session": session,
        "valid_temp_files": len(valid)
    })


if __name__ == "__main__":
    app.run(host=os.environ.get("SCAN_BIND", "0.0.0.0"), port=int(os.environ.get("SCAN_PORT", "8181")))
