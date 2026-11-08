"""
Floaty Rec v2 - tiny floating screen recorder + screenshot for low-end Windows PCs.

  * F9  = start / stop recording
  * F10 = screenshot (PNG)
  * Capture + encoding run inside ffmpeg (separate process) so the app never lags.
  * Uses your GPU encoder when available, otherwise x264 ultrafast.
  * If ffmpeg.exe is missing, click the download button on the bar (auto-downloads it).
  * If a recording fails, it automatically retries with safer settings and shows
    the real error message if everything fails.

Just double-click FloatyRec.pyw  (needs Python 3.9+, nothing else to install).
"""
import ctypes
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
import zipfile
from tkinter import filedialog, messagebox, ttk

try:  # sharp UI on high-DPI screens
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

APP_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
CFG_PATH = os.path.join(os.environ.get("APPDATA", APP_DIR), "FloatyRec.json")
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW

BG = "#15171c"
FG = "#e8eaf0"
RED = "#ff3b4e"
GREY = "#2a2e38"
DIM = "#7d8494"

FFMPEG_URLS = [
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
]

RES_OPTIONS = {"Original": 0, "1080p": 1080, "720p": 720, "480p": 480}
DEFAULTS = {
    "fps": "30",
    "res": "720p",
    "audio": "None",
    "encoder": "Auto",
    "folder": os.path.join(os.path.expanduser("~"), "Videos", "FloatyRec"),
    "x": 40,
    "y": 40,
}
X264 = ["-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-crf", "30"]


def find_ffmpeg():
    local = os.path.join(APP_DIR, "ffmpeg.exe")
    if os.path.isfile(local):
        return local
    return shutil.which("ffmpeg")


def run_quiet(args, timeout=15):
    try:
        r = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout,
            creationflags=NO_WINDOW, errors="ignore",
        )
        return (r.stdout or "") + (r.stderr or ""), r.returncode
    except Exception as e:  # noqa
        return str(e), -1


class FloatyRec:
    def __init__(self):
        self.cfg = dict(DEFAULTS)
        try:
            with open(CFG_PATH, "r", encoding="utf-8") as f:
                self.cfg.update(json.load(f))
        except Exception:
            pass

        self.ffmpeg = find_ffmpeg()
        self.proc = None
        self.log_file = None
        self.log_path = ""
        self.raw_path = None
        self.start_time = 0
        self.recording = False
        self.busy = False
        self.attempts = []
        self.launch_id = 0
        self.encoders = ["Auto", "x264 (CPU)"]
        self.audio_devices = ["None"]
        self.f9_down = False
        self.f10_down = False

        self.root = tk.Tk()
        self.root.title("Floaty Rec")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=BG)
        self.root.geometry(f"+{self.cfg['x']}+{self.cfg['y']}")

        self._build_ui()
        self.root.after(300, self._exclude_from_capture)
        self.root.after(500, self._tick)
        self.root.after(100, self._poll_hotkeys)

        if not self.ffmpeg:
            self._need_ffmpeg()
        else:
            threading.Thread(target=self._detect_hw, daemon=True).start()

    # ---------------------------------------------------------------- UI
    def _build_ui(self):
        bar = tk.Frame(self.root, bg=BG, padx=6, pady=5)
        bar.pack(fill="x")
        self.bar = bar

        self.rec_btn = tk.Canvas(bar, width=30, height=30, bg=BG, highlightthickness=0, cursor="hand2")
        self.rec_btn.pack(side="left")
        self.rec_btn.bind("<Button-1>", lambda e: self.toggle())
        self._draw_rec_btn()

        self.timer = tk.Label(bar, text="00:00", bg=BG, fg=FG, font=("Segoe UI", 11, "bold"), width=6)
        self.timer.pack(side="left", padx=(6, 2))

        self.status = tk.Label(bar, text="F9 rec \u2022 F10 shot", bg=BG, fg=DIM, font=("Segoe UI", 8), width=15, anchor="w")
        self.status.pack(side="left")

        self.shot_btn = tk.Label(bar, text="\U0001F4F7", bg=BG, fg=FG, font=("Segoe UI Emoji", 12), cursor="hand2")
        self.shot_btn.pack(side="left", padx=3)
        self.shot_btn.bind("<Button-1>", lambda e: self.screenshot())

        self.dl_btn = tk.Label(bar, text="\u2B07 ffmpeg", bg=RED, fg="white", font=("Segoe UI", 8, "bold"), padx=5, cursor="hand2")
        self.dl_btn.bind("<Button-1>", lambda e: self._download_ffmpeg())

        self.gear = tk.Label(bar, text="\u2699", bg=BG, fg=FG, font=("Segoe UI", 13), cursor="hand2")
        self.gear.pack(side="left", padx=3)
        self.gear.bind("<Button-1>", lambda e: self._toggle_settings())

        close = tk.Label(bar, text="\u2715", bg=BG, fg=DIM, font=("Segoe UI", 11), cursor="hand2")
        close.pack(side="left", padx=(2, 2))
        close.bind("<Button-1>", lambda e: self.quit())

        for w in (bar, self.timer, self.status):
            w.bind("<Button-1>", self._drag_start, add="+")
            w.bind("<B1-Motion>", self._drag_move)

        self.panel = tk.Frame(self.root, bg=BG, padx=10, pady=6)
        self.panel_open = False

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TCombobox", fieldbackground=GREY, background=GREY, foreground=FG, arrowcolor=FG)

        def row(label, values, key):
            f = tk.Frame(self.panel, bg=BG)
            f.pack(fill="x", pady=2)
            tk.Label(f, text=label, bg=BG, fg="#9aa1b2", font=("Segoe UI", 9), width=9, anchor="w").pack(side="left")
            var = tk.StringVar(value=str(self.cfg[key]))
            cb = ttk.Combobox(f, textvariable=var, values=values, state="readonly", width=24)
            cb.pack(side="left")
            cb.bind("<<ComboboxSelected>>", lambda e: self._save())
            return var, cb

        self.fps_var, _ = row("FPS", ["15", "24", "30", "60"], "fps")
        self.res_var, _ = row("Quality", list(RES_OPTIONS.keys()), "res")
        self.aud_var, self.aud_cb = row("Audio", self.audio_devices, "audio")
        self.enc_var, self.enc_cb = row("Encoder", self.encoders, "encoder")

        f = tk.Frame(self.panel, bg=BG)
        f.pack(fill="x", pady=(6, 0))
        self.folder_lbl = tk.Label(f, text=self._short(self.cfg["folder"]), bg=BG, fg="#9aa1b2", font=("Segoe UI", 8), anchor="w")
        self.folder_lbl.pack(side="left", fill="x", expand=True)
        for txt, cmd in (("Folder", self._pick_folder), ("Open", self._open_folder)):
            b = tk.Label(f, text=txt, bg=GREY, fg=FG, font=("Segoe UI", 9), padx=8, pady=2, cursor="hand2")
            b.pack(side="left", padx=(4, 0))
            b.bind("<Button-1>", lambda e, c=cmd: c())

    def _draw_rec_btn(self):
        c = self.rec_btn
        c.delete("all")
        c.create_oval(2, 2, 28, 28, outline="#555b6b", width=2)
        if self.recording:
            c.create_rectangle(9, 9, 21, 21, fill=RED, outline=RED)
        else:
            c.create_oval(8, 8, 22, 22, fill=RED, outline=RED)

    def _short(self, p, n=34):
        return p if len(p) <= n else "..." + p[-(n - 3):]

    def _set_status(self, text, color=DIM, reset_after=0):
        self.status.config(text=text, fg=color)
        if reset_after:
            self.root.after(reset_after, lambda: (not self.recording and not self.busy) and
                            self.status.config(text="F9 rec \u2022 F10 shot", fg=DIM))

    def _toggle_settings(self):
        if self.recording:
            return
        if self.panel_open:
            self.panel.pack_forget()
        else:
            self.panel.pack(fill="x")
        self.panel_open = not self.panel_open

    def _drag_start(self, e):
        self._dx, self._dy = e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y()

    def _drag_move(self, e):
        self.root.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def _pick_folder(self):
        d = filedialog.askdirectory(initialdir=self.cfg["folder"])
        if d:
            self.cfg["folder"] = d
            self.folder_lbl.config(text=self._short(d))
            self._save()

    def _open_folder(self):
        os.makedirs(self.cfg["folder"], exist_ok=True)
        os.startfile(self.cfg["folder"])

    def _save(self):
        self.cfg.update(
            fps=self.fps_var.get(), res=self.res_var.get(),
            audio=self.aud_var.get(), encoder=self.enc_var.get(),
            x=self.root.winfo_x(), y=self.root.winfo_y(),
        )
        try:
            with open(CFG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f)
        except Exception:
            pass

    def _exclude_from_capture(self):
        """Hide this bar from recordings/screenshots (Windows 10 2004+)."""
        try:
            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
            ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0x11)
        except Exception:
            pass

    # ------------------------------------------------------ ffmpeg download
    def _need_ffmpeg(self):
        self._set_status("ffmpeg missing ->", RED)
        self.dl_btn.pack(side="left", padx=3, before=self.gear)

    def _download_ffmpeg(self):
        if self.busy:
            return
        self.busy = True
        self._set_status("Downloading 0%", "#f5c542")
        threading.Thread(target=self._download_worker, daemon=True).start()

    def _download_worker(self):
        zpath = os.path.join(APP_DIR, "_ffmpeg_download.zip")
        err = ""
        ok = False
        for url in FFMPEG_URLS:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=30) as r, open(zpath, "wb") as out:
                    total = int(r.headers.get("Content-Length") or 0)
                    got = 0
                    last = 0
                    while True:
                        chunk = r.read(256 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
                        got += len(chunk)
                        if total and time.time() - last > 0.4:
                            last = time.time()
                            pct = int(got * 100 / total)
                            self.root.after(0, lambda p=pct: self._set_status(f"Downloading {p}%", "#f5c542"))
                self.root.after(0, lambda: self._set_status("Extracting...", "#f5c542"))
                with zipfile.ZipFile(zpath) as z:
                    member = next(n for n in z.namelist() if n.lower().endswith("/bin/ffmpeg.exe"))
                    with z.open(member) as src, open(os.path.join(APP_DIR, "ffmpeg.exe"), "wb") as dst:
                        shutil.copyfileobj(src, dst)
                ok = True
                break
            except Exception as e:  # noqa
                err = str(e)
        try:
            os.remove(zpath)
        except Exception:
            pass

        def done():
            self.busy = False
            if ok:
                self.ffmpeg = find_ffmpeg()
                self.dl_btn.pack_forget()
                self._set_status("ffmpeg ready \u2713", "#3ddc84", 2500)
                threading.Thread(target=self._detect_hw, daemon=True).start()
            else:
                self._set_status("Download failed", RED)
                messagebox.showerror(
                    "Floaty Rec",
                    "Could not download ffmpeg:\n" + err +
                    "\n\nDownload it manually from gyan.dev (release essentials) and put "
                    "ffmpeg.exe next to FloatyRec.pyw.", parent=self.root)

        self.root.after(0, done)

    # ---------------------------------------------------- hardware detection
    def _detect_hw(self):
        out, _ = run_quiet([self.ffmpeg, "-hide_banner", "-encoders"])
        found = []
        for name, label in (("h264_nvenc", "NVIDIA (GPU)"), ("h264_qsv", "Intel (GPU)"), ("h264_amf", "AMD (GPU)")):
            if name in out and self._test_encoder(name):
                found.append(label)
        encs = ["Auto"] + found + ["x264 (CPU)"]

        out, _ = run_quiet([self.ffmpeg, "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"])
        auds = ["None"] + re.findall(r'"([^"]+)" \(audio\)', out)

        def apply():
            self.encoders = encs
            self.enc_cb["values"] = encs
            if self.enc_var.get() not in encs:
                self.enc_var.set("Auto")
            self.audio_devices = auds
            self.aud_cb["values"] = auds
            if self.aud_var.get() not in auds:
                self.aud_var.set("None")

        self.root.after(0, apply)

    def _test_encoder(self, name):
        _, code = run_quiet([
            self.ffmpeg, "-hide_banner", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.2",
            "-frames:v", "2", "-c:v", name, "-pix_fmt", "yuv420p", "-f", "null", "-",
        ], timeout=12)
        return code == 0

    def _gpu_args(self):
        choice = self.enc_var.get()
        if choice == "Auto":
            gpus = [e for e in self.encoders if "GPU" in e]
            choice = gpus[0] if gpus else "x264 (CPU)"
        if choice.startswith("NVIDIA"):
            return ["-c:v", "h264_nvenc", "-preset", "p1", "-rc", "vbr", "-cq", "30", "-b:v", "0"]
        if choice.startswith("Intel"):
            return ["-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", "30"]
        if choice.startswith("AMD"):
            return ["-c:v", "h264_amf", "-quality", "speed", "-rc", "cqp", "-qp_i", "30", "-qp_p", "30"]
        return None

    # ------------------------------------------------------------ recording
    def toggle(self):
        if self.busy:
            return
        if not self.ffmpeg:
            self._need_ffmpeg()
            return
        if self.recording:
            self.stop()
        else:
            self.start()

    def _video_filter(self):
        h = RES_OPTIONS.get(self.res_var.get(), 0)
        if h:
            return f"scale=-2:{h}:flags=fast_bilinear"
        return "scale=trunc(iw/2)*2:trunc(ih/2)*2"  # even size is required by H.264

    def start(self):
        self._save()
        try:
            os.makedirs(self.cfg["folder"], exist_ok=True)
        except Exception as e:
            messagebox.showerror("Floaty Rec", f"Can't create folder:\n{e}", parent=self.root)
            return
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.raw_path = os.path.join(self.cfg["folder"], f"FloatyRec_{stamp}.mkv")
        self.log_path = os.path.join(self.cfg["folder"], "last_ffmpeg_log.txt")

        aud = self.aud_var.get()
        has_aud = bool(aud and aud != "None")
        gpu = self._gpu_args()
        # (video args, use audio) - tried in order until one works
        attempts = []
        if gpu:
            attempts.append((gpu, has_aud))
        attempts.append((X264, has_aud))
        if has_aud:
            attempts.append((X264, False))
        self.attempts = attempts

        self.recording = True
        self._draw_rec_btn()
        if self.panel_open:
            self._toggle_settings()
        self._launch(0)

    def _launch(self, i):
        self._close_proc_files()
        vargs, use_aud = self.attempts[i]
        cmd = [self.ffmpeg, "-hide_banner", "-y",
               "-thread_queue_size", "512",
               "-f", "gdigrab", "-framerate", self.fps_var.get(), "-draw_mouse", "1",
               "-use_wallclock_as_timestamps", "1", "-i", "desktop"]
        if use_aud:
            cmd += ["-thread_queue_size", "512", "-f", "dshow", "-i", f"audio={self.aud_var.get()}"]
        cmd += ["-vf", self._video_filter()] + vargs + ["-pix_fmt", "yuv420p"]
        if use_aud:
            cmd += ["-c:a", "aac", "-b:a", "128k"]
        cmd += [self.raw_path]

        try:
            self.log_file = open(self.log_path, "w", encoding="utf-8", errors="ignore")
            self.log_file.write("COMMAND: " + " ".join(cmd) + "\n\n")
            self.log_file.flush()
            self.proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self.log_file,
                creationflags=NO_WINDOW,
            )
        except Exception as e:
            self.recording = False
            self._draw_rec_btn()
            self._set_status("Start failed", RED)
            messagebox.showerror("Floaty Rec", f"Could not start ffmpeg:\n{e}", parent=self.root)
            return

        self.launch_id += 1
        lid = self.launch_id
        self.attempt = i
        self.start_time = time.time()
        self._set_status("Recording", RED)
        self.root.after(1800, lambda: self._check_alive(lid))

    def _close_proc_files(self):
        try:
            if self.log_file:
                self.log_file.close()
        except Exception:
            pass
        self.log_file = None

    def _log_tail(self, n=12):
        try:
            with open(self.log_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = [l.rstrip() for l in f.readlines() if l.strip()]
            return "\n".join(lines[-n:])
        except Exception:
            return "(no log)"

    def _check_alive(self, lid):
        if lid != self.launch_id or not self.recording or not self.proc:
            return
        if self.proc.poll() is None:
            return  # all good
        if self.attempt + 1 < len(self.attempts):
            self._set_status("Retrying safe mode", "#f5c542")
            self._launch(self.attempt + 1)
        else:
            self.recording = False
            self._draw_rec_btn()
            self.timer.config(text="00:00")
            self._set_status("Failed", RED)
            self._close_proc_files()
            messagebox.showerror(
                "Floaty Rec - recording failed",
                "ffmpeg stopped immediately. Last lines of its log:\n\n" + self._log_tail() +
                f"\n\nFull log: {self.log_path}", parent=self.root)

    def stop(self):
        self.busy = True
        self.recording = False
        self._draw_rec_btn()
        self._set_status("Saving...", "#f5c542")
        threading.Thread(target=self._finish, daemon=True).start()

    def _finish(self):
        p = self.proc
        try:
            if p and p.poll() is None:
                try:
                    p.stdin.write(b"q")
                    p.stdin.flush()
                except Exception:
                    pass
                try:
                    p.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    p.kill()
        finally:
            self._close_proc_files()

        ok = False
        if self.raw_path and os.path.isfile(self.raw_path) and os.path.getsize(self.raw_path) > 1024:
            mp4 = self.raw_path[:-4] + ".mp4"
            _, code = run_quiet([
                self.ffmpeg, "-hide_banner", "-y", "-i", self.raw_path,
                "-c", "copy", "-movflags", "+faststart", mp4,
            ], timeout=300)
            if code == 0 and os.path.isfile(mp4) and os.path.getsize(mp4) > 1024:
                try:
                    os.remove(self.raw_path)
                except Exception:
                    pass
            ok = True

        def done():
            self.busy = False
            self.timer.config(text="00:00")
            if ok:
                self._set_status("Saved \u2713", "#3ddc84", 2500)
            else:
                self._set_status("Nothing saved", RED, 3000)

        self.root.after(0, done)

    # --------------------------------------------------------- screenshot
    def screenshot(self):
        if self.busy and not self.recording:
            return
        if not self.ffmpeg:
            self._need_ffmpeg()
            return
        try:
            os.makedirs(self.cfg["folder"], exist_ok=True)
        except Exception:
            return
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = os.path.join(self.cfg["folder"], f"Screenshot_{stamp}.png")

        def work():
            _, code = run_quiet([
                self.ffmpeg, "-hide_banner", "-y", "-f", "gdigrab", "-draw_mouse", "0",
                "-framerate", "1", "-i", "desktop", "-frames:v", "1", "-update", "1", path,
            ], timeout=15)
            good = code == 0 and os.path.isfile(path)

            def show():
                if good:
                    self._set_status("Screenshot \u2713", "#3ddc84", 2000)
                else:
                    self._set_status("Screenshot failed", RED, 2500)

            self.root.after(0, show)

        threading.Thread(target=work, daemon=True).start()

    # ----------------------------------------------------- timers / hotkeys
    def _tick(self):
        if self.recording:
            s = int(time.time() - self.start_time)
            self.timer.config(text=f"{s // 60:02d}:{s % 60:02d}" if s < 3600 else f"{s // 3600}:{(s % 3600) // 60:02d}h",
                              fg=RED if s % 2 == 0 else FG)
            # ffmpeg died on its own mid-recording -> save what we have
            if self.proc and self.proc.poll() is not None and s > 3 and not self.busy:
                self.stop()
        else:
            self.timer.config(fg=FG)
        self.root.after(500, self._tick)

    def _poll_hotkeys(self):
        try:
            u = ctypes.windll.user32
            f9 = bool(u.GetAsyncKeyState(0x78) & 0x8000)
            f10 = bool(u.GetAsyncKeyState(0x79) & 0x8000)
        except Exception:
            f9 = f10 = False
        if f9 and not self.f9_down:
            self.toggle()
        if f10 and not self.f10_down:
            self.screenshot()
        self.f9_down, self.f10_down = f9, f10
        self.root.after(60, self._poll_hotkeys)

    def quit(self):
        if self.recording and self.proc:
            try:
                self.proc.stdin.write(b"q")
                self.proc.stdin.flush()
                self.proc.wait(timeout=10)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
        self._save()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    FloatyRec().run()
