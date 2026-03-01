#!/usr/bin/env python3
"""
中国語字幕リアルタイム日本語翻訳ツール
YouTube動画に焼き付けられた中国語字幕をOCRで読み取り、日本語に翻訳してオーバーレイ表示する
"""

## WindowsのDPIスケーリング対策なので他の環境では不要
import ctypes
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)   # Per-Monitor DPI Aware
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import tkinter as tk
import threading
import queue
import time
import sys

import mss
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
from paddleocr import PaddleOCR
from deep_translator import GoogleTranslator

CAPTURE_INTERVAL = 0.5      # キャプチャ間隔 (秒)
PIXEL_DIFF_SKIP  = 4.0      # フレーム差分がこれ以下ならOCRをスキップ
OCR_CONFIDENCE   = 0.30     # OCR信頼度の下限

class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("中国語字幕 → 日本語翻訳")
        self.root.resizable(False, False)

        self.region         = None
        self.running     = False
        self.last_text   = ""
        self.last_frame  = None
        self.reader      = None
        self.translator  = None
        self.ui_queue    = queue.Queue()

        self._build_control_panel()
        self._build_overlay()
        self._load_models()
        self._process_ui_queue()

    # ------------------------------------------------------------------
    # UI構築
    # ------------------------------------------------------------------

    def _build_control_panel(self):
        frame = tk.Frame(self.root, padx=16, pady=16)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(frame, text="中国語字幕リアルタイム翻訳",
                 font=("Arial", 13, "bold")).pack(pady=(0, 10))

        self.status_var = tk.StringVar(value="🔄 OCRモデルを読み込み中...")
        tk.Label(frame, textvariable=self.status_var,
                 fg="#555", font=("Arial", 9)).pack()

        self.region_var = tk.StringVar(value="字幕エリア: 未選択")
        tk.Label(frame, textvariable=self.region_var,
                 fg="#0066cc", font=("Arial", 9)).pack(pady=2)

        btn_frame = tk.Frame(frame)
        btn_frame.pack(pady=10)

        self.select_btn = tk.Button(
            btn_frame, text="📌 字幕エリアを選択",
            command=self.select_region,
            state="disabled", width=18, height=2, font=("Arial", 10))
        self.select_btn.pack(side=tk.LEFT, padx=5)

        self.toggle_btn = tk.Button(
            btn_frame, text="▶ 翻訳開始",
            command=self.toggle_translation,
            state="disabled", width=12, height=2,
            font=("Arial", 10, "bold"), bg="#4CAF50", fg="white")
        self.toggle_btn.pack(side=tk.LEFT, padx=5)

        tk.Label(frame, text="検出テキスト:", fg="#888", font=("Arial", 8)).pack(anchor="w", pady=(8, 0))
        self.detected_var = tk.StringVar(value="—")
        tk.Label(frame, textvariable=self.detected_var,
                 fg="#333", wraplength=390, font=("Arial", 8), justify="left").pack(anchor="w")

        tk.Label(frame, text="日本語訳:", fg="#888", font=("Arial", 8)).pack(anchor="w", pady=(4, 0))
        self.translated_var = tk.StringVar(value="—")
        tk.Label(frame, textvariable=self.translated_var,
                 fg="#003399", wraplength=390, font=("Arial", 9, "bold"), justify="left").pack(anchor="w")

    def _build_overlay(self):
        """字幕下に表示する透明オーバーレイ"""
        self.overlay = tk.Toplevel(self.root)
        self.overlay.overrideredirect(True)
        self.overlay.attributes("-topmost", True)
        self.overlay.attributes("-alpha", 0.88)
        self.overlay.configure(bg="#111111")
        self.overlay.withdraw()

        self.overlay_label = tk.Label(
            self.overlay, text="",
            bg="#111111", fg="#FFE000",
            font=("Meiryo UI", 20, "bold"),
            justify="center",
            padx=12, pady=6)
        self.overlay_label.pack()

        # ドラッグで移動
        self.overlay_label.bind("<ButtonPress-1>", self._drag_start)
        self.overlay_label.bind("<B1-Motion>",     self._drag_move)
        self._dx = self._dy = 0

    def _drag_start(self, e):
        self._dx, self._dy = e.x, e.y

    def _drag_move(self, e):
        x = self.overlay.winfo_x() + e.x - self._dx
        y = self.overlay.winfo_y() + e.y - self._dy
        self.overlay.geometry(f"+{x}+{y}")

    # ------------------------------------------------------------------
    # モデル読み込み
    # ------------------------------------------------------------------

    def _load_models(self):
        def _load():
            try:
                self.translator = GoogleTranslator(source="zh-CN", target="ja")
                self.reader = PaddleOCR(use_angle_cls=False, lang="ch", show_log=False)
                self.ui_queue.put(("status", "✅ 準備完了 — 字幕エリアを選択してください"))
                self.ui_queue.put(("enable_select", None))
            except Exception as exc:
                self.ui_queue.put(("status", f"❌ モデル読み込みエラー: {exc}"))

        threading.Thread(target=_load, daemon=True).start()

    # ------------------------------------------------------------------
    # UIキューの処理 (メインスレッドで 50ms ごとに呼ばれる)
    # ------------------------------------------------------------------

    def _process_ui_queue(self):
        try:
            while True:
                kind, data = self.ui_queue.get_nowait()
                if kind == "status":
                    self.status_var.set(data)
                elif kind == "enable_select":
                    self.select_btn.config(state="normal")
                elif kind == "translation":
                    detected, translated = data
                    self.detected_var.set(detected[:70] + ("…" if len(detected) > 70 else ""))
                    self.translated_var.set(translated[:90] + ("…" if len(translated) > 90 else ""))
                    self.overlay_label.config(text=translated)
                    if translated:
                        w = max(self.overlay_label.winfo_reqwidth(), 200)
                        h = self.overlay_label.winfo_reqheight()
                        self.overlay.geometry(f"{w}x{h}")
                        self.overlay.deiconify()
                    else:
                        self.overlay.withdraw()
                elif kind == "error":
                    self.status_var.set(f"⚠ {data[:60]}")
        except queue.Empty:
            pass
        self.root.after(50, self._process_ui_queue)

    # ------------------------------------------------------------------
    # エリア選択
    # ------------------------------------------------------------------

    def select_region(self):
        self.root.withdraw()
        self.root.update()

        sel = tk.Toplevel(self.root)
        sel.attributes("-fullscreen", True)
        sel.attributes("-topmost", True)
        sel.attributes("-alpha", 0.25)
        sel.configure(bg="#000080")
        sel.focus_force()

        canvas = tk.Canvas(sel, bg="#000080", cursor="crosshair", highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True)
        canvas.create_text(
            sel.winfo_screenwidth() // 2, 55,
            text="字幕エリアをドラッグして選択   |   ESC でキャンセル",
            fill="white", font=("Arial", 17, "bold"))

        start = [0, 0]
        rect  = [None]

        def on_press(e):
            start[0], start[1] = e.x, e.y
            if rect[0]:
                canvas.delete(rect[0])

        def on_drag(e):
            if rect[0]:
                canvas.delete(rect[0])
            rect[0] = canvas.create_rectangle(
                start[0], start[1], e.x, e.y,
                outline="#FF3333", width=2, fill="gray", stipple="gray25")

        def on_release(e):
            x1 = min(start[0], e.x);  y1 = min(start[1], e.y)
            x2 = max(start[0], e.x);  y2 = max(start[1], e.y)
            sel.destroy()
            self.root.deiconify()
            if x2 - x1 > 20 and y2 - y1 > 10:
                self.region = {"left": x1, "top": y1, "width": x2 - x1, "height": y2 - y1}
                self.region_var.set(f"字幕エリア: {x2-x1}×{y2-y1}  @  ({x1}, {y1})")
                self.toggle_btn.config(state="normal")
                self.last_frame = None
                self.last_text  = ""
                # オーバーレイを字幕エリアの直下 (または直上) に配置
                ov_x = x1
                ov_y = y2 + 5
                if ov_y + 60 > self.root.winfo_screenheight():
                    ov_y = y1 - 60
                self.overlay.geometry(f"+{ov_x}+{ov_y}")
                self.ui_queue.put(("status", "✅ エリア選択完了 — 翻訳を開始できます"))

        def on_escape(e):
            sel.destroy()
            self.root.deiconify()

        canvas.bind("<ButtonPress-1>",   on_press)
        canvas.bind("<B1-Motion>",       on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        sel.bind("<Escape>",             on_escape)

    # ------------------------------------------------------------------
    # 翻訳の開始 / 停止
    # ------------------------------------------------------------------

    def toggle_translation(self):
        if self.running:
            self.running = False
            self.toggle_btn.config(text="▶ 翻訳開始", bg="#4CAF50")
            self.status_var.set("⏹ 停止しました")
        else:
            self.running = True
            self.toggle_btn.config(text="⏹ 翻訳停止", bg="#f44336")
            self.status_var.set("🔄 翻訳中...")

            threading.Thread(target=self._capture_loop, daemon=True).start()

    # ------------------------------------------------------------------
    # OCR前処理
    # ------------------------------------------------------------------

    def _preprocess(self, pil_img):
        """OCR精度向上のための前処理"""
        # グレースケール化（カラー情報は不要、ノイズ軽減）
        gray = pil_img.convert("L")
        # 2倍拡大（小さい字幕文字はOCRが苦手なため）
        w, h = gray.size
        gray = gray.resize((w * 2, h * 2), Image.LANCZOS)
        # コントラスト強調
        gray = ImageEnhance.Contrast(gray).enhance(2.5)
        # シャープネス強調
        gray = gray.filter(ImageFilter.SHARPEN)
        return gray

    # ------------------------------------------------------------------
    # キャプチャ → OCR → 翻訳ループ (バックグラウンドスレッド)
    # ------------------------------------------------------------------

    def _capture_loop(self):
        with mss.mss() as sct:
            while self.running:
                try:
                    # 1. スクリーンキャプチャ
                    shot = sct.grab(self.region)
                    pil_img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

                    # 2. 前フレームとの差分チェック（変化が小さければOCRをスキップ）
                    frame = np.array(pil_img)

                    if self.last_frame is not None:
                         diff = float(np.mean(np.abs(frame.astype(np.int16) - self.last_frame.astype(np.int16))))
                         if diff < PIXEL_DIFF_SKIP:
                             time.sleep(CAPTURE_INTERVAL)
                             continue
                    self.last_frame = frame

                    #print(f"Pixel difference from last frame: {diff:.2f}")

                    # 3. OCR前処理（グレースケール・拡大・コントラスト・シャープネス）
                    img_np = np.array(self._preprocess(pil_img))

                    # 4. OCR
                    raw = self.reader.ocr(img_np, cls=False)
                    results = raw[0] if raw and raw[0] else []

                    # 5. 信頼度フィルタリング & テキスト結合
                    texts = [
                        text for (_, (text, conf)) in results
                        if conf >= OCR_CONFIDENCE and text.strip()
                    ]
                    combined = "".join(texts).strip()
                    print(f"OCR Results: {combined}")  # 読み取ったテキストと信頼度を表示


                    # 6. 変化があれば翻訳
                    if combined and combined != self.last_text:
                        self.last_text = combined
                        translated = self.translator.translate(combined)
                        print(f"Translated: {translated}")
                        if translated:
                            self.ui_queue.put(("translation", (combined, translated)))

                    if not combined:
                        self.last_text = ""
                        self.ui_queue.put(("translation", ("", "")))

                    time.sleep(CAPTURE_INTERVAL)

                except Exception as exc:
                    self.ui_queue.put(("error", str(exc)))
                    print(f"Error in capture loop: {exc}")
                    time.sleep(2)

    # ------------------------------------------------------------------
    # 終了処理
    # ------------------------------------------------------------------

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    def _on_close(self):
        self.running = False
        self.root.destroy()
        sys.exit(0)


if __name__ == "__main__":
    app = App()
    app.run()
