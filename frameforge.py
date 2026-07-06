"""
FrameForge
==========
Extracts frames from video files and saves them as PNG images.

Features:
- Drag & drop style file picker for multiple videos
- Choose between original FPS or custom FPS
- Each video exports to its own folder (named after the video, no extension)
- Frames named: {video_name}_{0001}.png, {video_name}_{0002}.png, ...
- Real-time progress tracking with progress bar
- Dark-themed modern UI (CustomTkinter)
- Optional PDF report with SHA-256 and MD5 hashes for each frame

Requirements:
    pip install opencv-python reportlab customtkinter
"""

import ctypes
import hashlib
import os
import subprocess
import sys

# ── Windows DPI awareness (must run before any tkinter import) ──
# CustomTkinter handles scaling natively, but setting DPI awareness
# early avoids blurry rendering on high-DPI Windows displays.
if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)   # System DPI Aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()     # Fallback
        except Exception:
            pass
    # AppUserModelID must be set before UI creation so Windows uses the correct taskbar icon
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FrameForge.App.1")
    except Exception:
        pass

import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path

import customtkinter as ctk

try:
    import windnd
    HAS_WINDND = True
except ImportError:
    HAS_WINDND = False

try:
    import cv2
except ImportError:
    print("OpenCV non trovato. Installa con: pip install opencv-python")
    sys.exit(1)

try:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.lib.colors import HexColor, Color
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak,
    )
    from reportlab.pdfgen import canvas as pdf_canvas
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False

from PIL import Image as PILImage


# ──────────────────────────────────────────────
# Theme & Style Constants  (Tokyo Night palette)
# ──────────────────────────────────────────────
BG_DARK       = "#1a1b26"
BG_CARD       = "#24283b"
BG_INPUT      = "#1f2335"
BG_HOVER      = "#2f3451"
FG_PRIMARY    = "#c0caf5"
FG_SECONDARY  = "#565f89"
FG_ACCENT     = "#7aa2f7"
FG_SUCCESS    = "#9ece6a"
FG_ERROR      = "#f7768e"
FG_WARNING    = "#e0af68"
BORDER_COLOR  = "#3b4261"
ACCENT_BTN    = "#7aa2f7"
ACCENT_BTN_FG = "#1a1b26"

FONT_FAMILY   = "Segoe UI"
FONT_MONO     = "Consolas"

VIDEO_EXTENSIONS = (
    ".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv",
    ".webm", ".m4v", ".mpeg", ".mpg", ".3gp", ".ts",
)


# ──────────────────────────────────────────────
# Hash helpers
# ──────────────────────────────────────────────
def _compute_file_hashes(filepath: str) -> dict[str, str]:
    """Return SHA-256 and MD5 hex-digest for a file."""
    sha256 = hashlib.sha256()
    md5 = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
            md5.update(chunk)
    return {"sha256": sha256.hexdigest(), "md5": md5.hexdigest()}


def generate_hash_pdf(
    frames_dir: str,
    video_name: str,
    progress_callback=None,
    case_info: dict[str, str] | None = None,
    video_meta: dict | None = None,
) -> str:
    """
    Create a professional PDF inside *frames_dir* with a table listing
    SHA-256 and MD5 hashes of every exported frame.

    Returns the path to the generated PDF.
    """
    if not HAS_REPORTLAB:
        raise RuntimeError("reportlab non installato. Installa con: pip install reportlab")

    from datetime import datetime

    # Collect frame files (sorted)
    frame_files = sorted(
        f for f in os.listdir(frames_dir)
        if f.lower().endswith(".png")
    )
    if not frame_files:
        raise RuntimeError(f"Nessun fotogramma trovato in {frames_dir}")

    pdf_path = os.path.join(frames_dir, f"{video_name}_hash_report.pdf")

    # ── Colours ──
    col_header_bg   = HexColor("#2C3E50")   # dark blue-grey header
    col_header_fg   = HexColor("#FFFFFF")
    col_row_even    = HexColor("#F8F9FA")   # light grey zebra
    col_row_odd     = HexColor("#FFFFFF")
    col_border      = HexColor("#DEE2E6")
    col_accent      = HexColor("#2980B9")   # blue accent
    col_text        = HexColor("#212529")
    col_text_dim    = HexColor("#6C757D")

    # ── Styles ──
    style_title = ParagraphStyle(
        "HashTitle", fontName="Helvetica-Bold", fontSize=18,
        textColor=col_header_bg, spaceAfter=6 * mm,
    )
    style_subtitle = ParagraphStyle(
        "HashSubtitle", fontName="Helvetica", fontSize=9,
        textColor=col_text_dim, spaceAfter=6 * mm,
    )
    style_cell = ParagraphStyle(
        "CellText", fontName="Courier", fontSize=6.5,
        textColor=col_text, leading=8,
    )
    style_cell_name = ParagraphStyle(
        "CellName", fontName="Helvetica", fontSize=7.5,
        textColor=col_text, leading=10,
    )
    style_header_cell = ParagraphStyle(
        "HeaderCell", fontName="Helvetica-Bold", fontSize=8,
        textColor=col_header_fg, alignment=TA_CENTER,
    )

    # ── Compute hashes (with progress) ──
    total = len(frame_files)
    table_data = []
    for i, fname in enumerate(frame_files):
        fpath = os.path.join(frames_dir, fname)
        hashes = _compute_file_hashes(fpath)
        table_data.append((
            Paragraph(fname, style_cell_name),
            Paragraph(hashes["sha256"], style_cell),
            Paragraph(hashes["md5"], style_cell),
        ))
        if progress_callback:
            progress_callback(i + 1, total)

    # ── Column widths (landscape A4: ~277 mm usable) ──
    page_size = landscape(A4)
    page_w = page_size[0]
    usable_w = page_w - 30 * mm  # 15 mm margin each side
    col_w_name = usable_w * 0.25
    col_w_sha  = usable_w * 0.50
    col_w_md5  = usable_w * 0.25

    # ── Header row ──
    header_row = [
        Paragraph("Fotogramma", style_header_cell),
        Paragraph("SHA-256", style_header_cell),
        Paragraph("MD5", style_header_cell),
    ]

    # ── Build chunks of rows that fit one page (managed by platypus) ──
    all_rows = [header_row] + table_data

    table = Table(
        all_rows,
        colWidths=[col_w_name, col_w_sha, col_w_md5],
        repeatRows=1,  # repeat header on every page
    )

    # ── Table style ──
    ts = [
        # Header
        ("BACKGROUND",    (0, 0), (-1, 0), col_header_bg),
        ("TEXTCOLOR",     (0, 0), (-1, 0), col_header_fg),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING",    (0, 0), (-1, 0), 6),
        # All cells
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("TOPPADDING",    (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
        # Grid
        ("GRID",          (0, 0), (-1, -1), 0.4, col_border),
        ("LINEBELOW",     (0, 0), (-1, 0), 1.2, col_accent),
    ]
    # Zebra striping
    for row_idx in range(1, len(all_rows)):
        bg = col_row_even if row_idx % 2 == 0 else col_row_odd
        ts.append(("BACKGROUND", (0, row_idx), (-1, row_idx), bg))

    table.setStyle(TableStyle(ts))

    # ── Page template with header/footer ──
    timestamp = datetime.now().strftime("%d/%m/%Y  %H:%M")

    # Case info defaults
    ci = case_info or {}
    ci_numero   = ci.get("numero_caso", "")
    ci_reperto  = ci.get("codice_reperto", "")
    ci_operatore = ci.get("operatore", "")

    # ── NumberedCanvas: two-pass approach for "Pagina X su Y" ──
    class _NumberedCanvas(pdf_canvas.Canvas):
        """Canvas subclass that tracks pages and fills in total count on save."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_page_states = []

        def showPage(self):
            self._saved_page_states.append(dict(self.__dict__))
            self._startPage()  # reset canvas for next page WITHOUT emitting current one

        def save(self):
            total_pages = len(self._saved_page_states)
            for state in self._saved_page_states:
                self.__dict__.update(state)
                self.draw_page_number(total_pages)
                pdf_canvas.Canvas.showPage(self)
            pdf_canvas.Canvas.save(self)

        def draw_page_number(self, total_pages):
            pw, ph = self._pagesize
            self.saveState()
            self.setFillColor(col_text_dim)
            self.setFont("Helvetica", 7)
            self.drawRightString(
                pw - 15 * mm, 3.5 * mm,
                f"Pagina {self._pageNumber} su {total_pages}"
            )
            self.restoreState()

    class _HashDocTemplate(SimpleDocTemplate):
        """Adds a branded header and footer to every page."""

        def __init__(self, *args, **kwargs):
            self._video_name = kwargs.pop("video_name", "")
            self._video_filename = kwargs.pop("video_filename", "")
            self._total_frames = kwargs.pop("total_frames", 0)
            self._timestamp = kwargs.pop("timestamp", "")
            self._case_info = kwargs.pop("case_info", {})
            self._native_fps = kwargs.pop("native_fps", None)
            self._total_video_frames = kwargs.pop("total_video_frames", None)
            super().__init__(*args, **kwargs)

        def afterPage(self):
            canvas = self.canv
            pw, ph = self.pagesize
            ci = self._case_info

            # ── Top bar ──
            header_h = 18 * mm if ci.get("numero_caso") or ci.get("codice_reperto") or ci.get("operatore") else 14 * mm
            canvas.saveState()
            canvas.setFillColor(col_header_bg)
            canvas.rect(0, ph - header_h, pw, header_h, fill=True, stroke=False)
            canvas.setFillColor(HexColor("#FFFFFF"))
            canvas.setFont("Helvetica-Bold", 11)
            canvas.drawString(15 * mm, ph - 9 * mm, "FrameForge  \u2014  Hash Integrity Report")
            canvas.setFont("Helvetica", 8)
            canvas.drawRightString(
                pw - 15 * mm, ph - 9 * mm,
                f"{self._video_filename or self._video_name}"
            )
            # Case info line in header
            if ci.get("numero_caso") or ci.get("codice_reperto") or ci.get("operatore"):
                x_pos = 15 * mm
                y_pos = ph - 15 * mm
                items = []
                if ci.get("numero_caso"):
                    items.append(("Caso: ", ci["numero_caso"]))
                if ci.get("codice_reperto"):
                    items.append(("Reperto: ", ci["codice_reperto"]))
                if ci.get("operatore"):
                    items.append(("Operatore: ", ci["operatore"]))
                for i, (label, value) in enumerate(items):
                    if i > 0:
                        canvas.setFont("Helvetica", 7.5)
                        sep = "   |   "
                        canvas.drawString(x_pos, y_pos, sep)
                        x_pos += canvas.stringWidth(sep, "Helvetica", 7.5)
                    # Label in normal
                    canvas.setFont("Helvetica", 7.5)
                    canvas.drawString(x_pos, y_pos, label)
                    x_pos += canvas.stringWidth(label, "Helvetica", 7.5)
                    # Value in bold
                    canvas.setFont("Helvetica-Bold", 7.5)
                    canvas.drawString(x_pos, y_pos, value)
                    x_pos += canvas.stringWidth(value, "Helvetica-Bold", 7.5)
            canvas.restoreState()

            # ── Bottom bar ──
            # Page number is handled by _NumberedCanvas.draw_page_number()
            canvas.saveState()
            canvas.setFillColor(col_border)
            canvas.rect(0, 0, pw, 10 * mm, fill=True, stroke=False)
            canvas.setFillColor(col_text_dim)
            canvas.setFont("Helvetica", 7)
            footer_parts = [f"Generato il {self._timestamp}"]
            footer_parts.append(f"Fotogrammi esportati: {int(self._total_frames)}")
            if self._total_video_frames is not None:
                footer_parts.append(f"Fotogrammi originali: {int(self._total_video_frames)}")
            footer_parts.append(f"FPS originali: {self._native_fps}")
            canvas.drawString(
                15 * mm, 3.5 * mm,
                "   |   ".join(footer_parts)
            )
            canvas.restoreState()

    doc = _HashDocTemplate(
        pdf_path,
        pagesize=page_size,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=24 * mm if ci_numero or ci_reperto or ci_operatore else 20 * mm,
        bottomMargin=16 * mm,
        title=f"Hash Report - {video_name}",
        author="FrameForge",
        video_name=video_name,
        video_filename=(video_meta or {}).get("video_filename", video_name),
        total_frames=total,
        timestamp=timestamp,
        case_info=ci,
        native_fps=(video_meta or {}).get("native_fps", "N/D"),
        total_video_frames=(video_meta or {}).get("total_video_frames"),
    )

    # Case info block (each field on its own line)
    case_lines = []
    if ci_numero:
        case_lines.append(f"Caso: <b>{ci_numero}</b>")
    if ci_reperto:
        case_lines.append(f"Codice Reperto: <b>{ci_reperto}</b>")
    if ci_operatore:
        case_lines.append(f"Operatore: <b>{ci_operatore}</b>")

    # Video filename with extension (prominent, under title)
    vm = video_meta or {}
    video_filename = vm.get("video_filename", video_name)
    style_filename = ParagraphStyle(
        "FileName", fontName="Helvetica-Bold", fontSize=13,
        textColor=col_accent, spaceAfter=4 * mm,
    )

    # Video info line
    video_info = (
        f"Fotogrammi esportati: <b>{total}</b> &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"Data: <b>{timestamp}</b>"
    )

    elements = [
        Paragraph("Hash Integrity Report", style_title),
        Paragraph(video_filename, style_filename),
    ]
    if case_lines:
        style_case = ParagraphStyle(
            "CaseInfo", fontName="Helvetica", fontSize=10,
            textColor=col_text, leading=16, spaceAfter=2 * mm,
        )
        for line in case_lines:
            elements.append(Paragraph(line, style_case))
        elements.append(Spacer(1, 2 * mm))
    elements.append(Paragraph(video_info, style_subtitle))

    # ── Video metadata detail block ──
    if vm:
        style_detail_label = ParagraphStyle(
            "DetailLabel", fontName="Helvetica", fontSize=8,
            textColor=col_text_dim, leading=11,
        )
        style_detail_value = ParagraphStyle(
            "DetailValue", fontName="Courier", fontSize=8,
            textColor=col_text, leading=11,
        )
        style_detail_value_normal = ParagraphStyle(
            "DetailValueNormal", fontName="Helvetica-Bold", fontSize=8,
            textColor=col_text, leading=11,
        )

        detail_rows = []
        # Header row
        detail_rows.append([
            Paragraph("<b>Dettaglio</b>", ParagraphStyle(
                "DetailHeader", fontName="Helvetica-Bold", fontSize=8,
                textColor=col_header_fg, alignment=TA_LEFT,
            )),
            Paragraph("<b>Valore</b>", ParagraphStyle(
                "DetailHeaderVal", fontName="Helvetica-Bold", fontSize=8,
                textColor=col_header_fg, alignment=TA_LEFT,
            )),
        ])

        if vm.get("file_hash_sha256"):
            detail_rows.append([
                Paragraph("Hash file originale (SHA-256)", style_detail_label),
                Paragraph(vm["file_hash_sha256"], style_detail_value),
            ])
        if vm.get("file_hash_md5"):
            detail_rows.append([
                Paragraph("Hash file originale (MD5)", style_detail_label),
                Paragraph(vm["file_hash_md5"], style_detail_value),
            ])
        if vm.get("duration_str"):
            detail_rows.append([
                Paragraph("Durata video", style_detail_label),
                Paragraph(vm["duration_str"], style_detail_value_normal),
            ])
        if vm.get("total_video_frames") is not None:
            detail_rows.append([
                Paragraph("Fotogrammi totali nel video", style_detail_label),
                Paragraph(str(int(vm["total_video_frames"])), style_detail_value_normal),
            ])
        if vm.get("native_fps") is not None:
            detail_rows.append([
                Paragraph("FPS originali del video", style_detail_label),
                Paragraph(str(vm["native_fps"]), style_detail_value_normal),
            ])
        if vm.get("exported_frames") is not None:
            export_label = "Fotogrammi esportati"
            export_value = str(int(vm["exported_frames"]))
            if vm.get("custom_fps"):
                export_value += f"  (FPS personalizzato: {vm['custom_fps']})"
            detail_rows.append([
                Paragraph(export_label, style_detail_label),
                Paragraph(export_value, style_detail_value_normal),
            ])

        if len(detail_rows) > 1:  # has data beyond header
            detail_col_w_label = usable_w * 0.30
            detail_col_w_value = usable_w * 0.70
            detail_table = Table(
                detail_rows,
                colWidths=[detail_col_w_label, detail_col_w_value],
            )
            detail_ts = [
                # Header
                ("BACKGROUND",    (0, 0), (-1, 0), col_header_bg),
                ("TEXTCOLOR",     (0, 0), (-1, 0), col_header_fg),
                ("TOPPADDING",    (0, 0), (-1, 0), 5),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
                # All cells
                ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING",   (0, 0), (-1, -1), 6),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
                ("TOPPADDING",    (0, 1), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
                # Grid
                ("GRID",          (0, 0), (-1, -1), 0.4, col_border),
                ("LINEBELOW",     (0, 0), (-1, 0), 1.2, col_accent),
            ]
            # Zebra striping for detail rows
            for row_idx in range(1, len(detail_rows)):
                bg = col_row_even if row_idx % 2 == 0 else col_row_odd
                detail_ts.append(("BACKGROUND", (0, row_idx), (-1, row_idx), bg))
            detail_table.setStyle(TableStyle(detail_ts))

            elements.append(detail_table)
            elements.append(Spacer(1, 6 * mm))

    elements.append(table)

    doc.build(elements, canvasmaker=_NumberedCanvas)
    return pdf_path


# ──────────────────────────────────────────────
# Core extraction logic
# ──────────────────────────────────────────────
def extract_frames(
    video_path: str,
    output_dir: str,
    target_fps: float | None = None,
    progress_callback=None,
    cancel_event: threading.Event | None = None,
) -> int:
    """
    Extract frames from *video_path* into *output_dir* as PNG files.

    Parameters
    ----------
    video_path : str
        Full path to the source video.
    output_dir : str
        Directory where frames will be saved.
    target_fps : float or None
        If None, use the video's native FPS.
        Otherwise, sample at approximately this rate.
    progress_callback : callable(current, total) or None
        Called after each saved frame.
    cancel_event : threading.Event or None
        If set, extraction stops early.

    Returns
    -------
    int  – number of frames saved.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Impossibile aprire il video: {video_path}")

    native_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    use_fps = target_fps if target_fps else native_fps

    # Calculate frame interval for sampling
    frame_interval = max(1, round(native_fps / use_fps))

    # Estimate output frames to determine zero-padding width (minimum 4 digits)
    estimated_output = max(total_frames // frame_interval, 1) if total_frames > 0 else 9999
    pad_width = max(4, len(str(estimated_output + 1)))

    os.makedirs(output_dir, exist_ok=True)
    video_name = Path(video_path).stem

    saved = 0
    frame_index = 0

    while True:
        if cancel_event and cancel_event.is_set():
            break

        ret, frame = cap.read()
        if not ret:
            break

        if frame_index % frame_interval == 0:
            saved += 1
            filename = f"{video_name}_{saved:0{pad_width}d}.png"
            filepath = os.path.join(output_dir, filename)
            cv2.imwrite(filepath, frame)

        frame_index += 1

        if progress_callback and total_frames > 0:
            progress_callback(frame_index, total_frames)

    cap.release()
    return saved


# ──────────────────────────────────────────────
# GUI Application  (CustomTkinter)
# ──────────────────────────────────────────────
ctk.set_appearance_mode("dark")


class VideoToFramesApp(ctk.CTk):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.title("FrameForge")
        self.configure(fg_color=BG_DARK)

        # ── Set window / taskbar icon ──
        self._set_icon()

        # ── Sizing ──
        # _get_work_area() returns PHYSICAL pixels (e.g. 2880x1704).
        # CTk geometry() expects LOGICAL pixels (physical / scaling).
        # We must divide by the CTk scaling factor to avoid oversized windows.
        self.update_idletasks()
        scale = ctk.ScalingTracker.get_window_scaling(self)

        work_w, work_h = self._get_work_area()          # physical px
        log_work_w = work_w / scale                      # logical px
        log_work_h = work_h / scale

        target_w = int(log_work_w * 0.60)
        target_h = int(log_work_h * 0.80)

        min_w, min_h = 660, 520
        target_w = max(target_w, min_w)
        target_h = max(target_h, min_h)

        # Never exceed the logical work area
        target_w = min(target_w, int(log_work_w) - 20)
        target_h = min(target_h, int(log_work_h) - 20)

        self.minsize(min_w, min_h)
        self.geometry(f"{target_w}x{target_h}")
        self._center_window()

        self.video_paths: list[str] = []
        self.output_directory: str = ""
        self.cancel_event = threading.Event()
        self.is_running = False
        self._selected_row_index: int | None = None

        # ── Fonts ──
        self.font_main  = ctk.CTkFont(family=FONT_FAMILY, size=13)
        self.font_bold  = ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold")
        self.font_title = ctk.CTkFont(family=FONT_FAMILY, size=20, weight="bold")
        self.font_sub   = ctk.CTkFont(family=FONT_FAMILY, size=11)
        self.font_small = ctk.CTkFont(family=FONT_FAMILY, size=11)
        self.font_mono  = ctk.CTkFont(family=FONT_MONO, size=12)

        self._build_ui()

        # ── Enable drag & drop ──
        if HAS_WINDND:
            self._drop_queue = queue.Queue()
            windnd.hook_dropfiles(self, func=lambda files: self._drop_queue.put(files))
            self._poll_drop_queue()

    # ── helpers ──────────────────────────────
    def _set_icon(self):
        """Set the window icon and Windows taskbar icon."""
        if getattr(sys, "frozen", False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))

        ico_path = os.path.join(base_path, "logo.ico")
        
        # Set initial icon
        if os.path.isfile(ico_path):
            self.wm_iconbitmap(ico_path)
            # CustomTkinter forcibly sets its own icon after 200ms on Windows.
            # We override the method on this instance so its internal call does nothing.
            self.iconbitmap = lambda *args, **kwargs: None

    def _get_work_area(self) -> tuple[int, int]:
        """Return (width, height) of the usable desktop area (excluding taskbar)."""
        self.update_idletasks()
        try:
            import ctypes.wintypes
            rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.SystemParametersInfoW(
                0x0030, 0, ctypes.byref(rect), 0
            )
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            if w > 0 and h > 0:
                return w, h
        except Exception:
            pass
        return self.winfo_screenwidth(), self.winfo_screenheight()

    def _center_window(self):
        """Center the window on the work area (accounting for taskbar and CTk scaling)."""
        self.update_idletasks()
        scale = ctk.ScalingTracker.get_window_scaling(self)

        # winfo_width/height return physical pixels on high-DPI;
        # geometry() expects logical pixels → divide by scale.
        w = int(self.winfo_width() / scale)
        h = int(self.winfo_height() / scale)

        # Work area in physical pixels → convert to logical
        work_w, work_h = self._get_work_area()
        log_work_w = work_w / scale
        log_work_h = work_h / scale

        origin_x, origin_y = 0, 0
        try:
            import ctypes.wintypes
            rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.SystemParametersInfoW(
                0x0030, 0, ctypes.byref(rect), 0
            )
            origin_x = int(rect.left / scale)
            origin_y = int(rect.top / scale)
        except Exception:
            pass

        x = max(origin_x, origin_x + int((log_work_w - w) / 2))
        y = max(origin_y, origin_y + int((log_work_h - h) / 2))
        self.geometry(f"+{x}+{y}")

    # ── UI construction ──────────────────────
    def _build_ui(self):
        # Main scrollable container — ensures everything is accessible
        # even on small / high-DPI screens
        container = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=BG_HOVER,
            scrollbar_button_hover_color=FG_ACCENT,
        )
        container.pack(fill="both", expand=True, padx=20, pady=14)

        # ─── Title ───
        title_frame = ctk.CTkFrame(container, fg_color="transparent")
        title_frame.pack(fill="x", pady=(0, 2))

        # Load logo image
        if getattr(sys, "frozen", False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
        logo_path = os.path.join(base_path, "logo.png")

        if os.path.isfile(logo_path):
            logo_img = PILImage.open(logo_path)
            self._logo_ctk = ctk.CTkImage(light_image=logo_img, dark_image=logo_img, size=(32, 32))
            ctk.CTkLabel(
                title_frame, image=self._logo_ctk, text="",
            ).pack(side="left", padx=(0, 8))

        ctk.CTkLabel(
            title_frame, text="FrameForge",
            font=self.font_title, text_color=FG_ACCENT,
        ).pack(side="left")

        ctk.CTkLabel(
            title_frame, text="Developed by Michele Paladini",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, slant="italic"),
            text_color=FG_SECONDARY, anchor="e",
        ).pack(side="right")

        ctk.CTkLabel(
            container,
            text="Estrai fotogrammi dai tuoi video in formato PNG",
            font=self.font_sub, text_color=FG_SECONDARY,
        ).pack(anchor="w", pady=(0, 10))

        # ─── 1. Video selection card ───
        card1 = self._card(container, "①  Video da esportare")

        btn_row = ctk.CTkFrame(card1, fg_color="transparent")
        btn_row.pack(fill="x", pady=(0, 6))

        ctk.CTkButton(
            btn_row, text="📂  Aggiungi Video", command=self._add_videos,
            fg_color=BG_HOVER, hover_color=BORDER_COLOR,
            text_color=FG_PRIMARY, font=self.font_bold,
            corner_radius=8, height=30,
        ).pack(side="left")

        ctk.CTkButton(
            btn_row, text="🗑  Rimuovi Selezionato", command=self._remove_selected,
            fg_color=BG_HOVER, hover_color=BORDER_COLOR,
            text_color=FG_PRIMARY, font=self.font_bold,
            corner_radius=8, height=34,
        ).pack(side="left", padx=(8, 0))

        ctk.CTkButton(
            btn_row, text="✕  Svuota Lista", command=self._clear_list,
            fg_color=BG_HOVER, hover_color=BORDER_COLOR,
            text_color=FG_PRIMARY, font=self.font_bold,
            corner_radius=8, height=34,
        ).pack(side="left", padx=(8, 0))

        # Video list (CTkScrollableFrame replaces tk.Listbox)
        self.file_list_frame = ctk.CTkScrollableFrame(
            card1, fg_color=BG_INPUT, corner_radius=8,
            height=110,
            scrollbar_button_color=BG_HOVER,
            scrollbar_button_hover_color=FG_ACCENT,
        )
        self.file_list_frame.pack(fill="both", expand=True, pady=(0, 8))

        # Placeholder label shown when list is empty
        self._empty_label = ctk.CTkLabel(
            self.file_list_frame,
            text="Trascina o aggiungi video qui…",
            font=self.font_sub, text_color=FG_SECONDARY,
        )
        self._empty_label.pack(pady=20)

        self.lbl_count = ctk.CTkLabel(
            card1, text="Nessun video selezionato",
            font=self.font_small, text_color=FG_ACCENT,
        )
        self.lbl_count.pack(anchor="w")

        # ─── 2. Output directory ───
        card2 = self._card(container, "②  Cartella di output")

        dir_row = ctk.CTkFrame(card2, fg_color="transparent")
        dir_row.pack(fill="x")

        self.lbl_output = ctk.CTkLabel(
            dir_row, text="Nessuna cartella selezionata…",
            font=self.font_mono, text_color=FG_SECONDARY,
            anchor="w",
        )
        self.lbl_output.pack(side="left", fill="x", expand=True)

        ctk.CTkButton(
            dir_row, text="📁  Scegli", command=self._choose_output,
            fg_color=BG_HOVER, hover_color=BORDER_COLOR,
            text_color=FG_PRIMARY, font=self.font_bold,
            corner_radius=8, height=30, width=110,
        ).pack(side="right", padx=(10, 0))

        # ─── 3. Case data fields ───
        card3_case = self._card(container, "③  Dati del Caso")

        case_row1 = ctk.CTkFrame(card3_case, fg_color="transparent")
        case_row1.pack(fill="x", pady=(0, 6))

        ctk.CTkLabel(
            case_row1, text="Numero Caso:",
            font=self.font_main, text_color=FG_PRIMARY, width=130, anchor="w",
        ).pack(side="left")
        self.case_numero = ctk.CTkEntry(
            case_row1, placeholder_text="es. 1234/2026",
            font=self.font_main, fg_color=BG_INPUT, text_color=FG_PRIMARY,
            border_color=BORDER_COLOR, corner_radius=6, height=32,
        )
        self.case_numero.pack(side="left", fill="x", expand=True)

        case_row2 = ctk.CTkFrame(card3_case, fg_color="transparent")
        case_row2.pack(fill="x", pady=(0, 6))

        ctk.CTkLabel(
            case_row2, text="Codice Reperto:",
            font=self.font_main, text_color=FG_PRIMARY, width=130, anchor="w",
        ).pack(side="left")
        self.case_reperto = ctk.CTkEntry(
            case_row2, placeholder_text="es. REP-001",
            font=self.font_main, fg_color=BG_INPUT, text_color=FG_PRIMARY,
            border_color=BORDER_COLOR, corner_radius=6, height=32,
        )
        self.case_reperto.pack(side="left", fill="x", expand=True)

        case_row3 = ctk.CTkFrame(card3_case, fg_color="transparent")
        case_row3.pack(fill="x")

        ctk.CTkLabel(
            case_row3, text="Operatore:",
            font=self.font_main, text_color=FG_PRIMARY, width=130, anchor="w",
        ).pack(side="left")
        self.case_operatore = ctk.CTkEntry(
            case_row3, placeholder_text="es. Mario Rossi",
            font=self.font_main, fg_color=BG_INPUT, text_color=FG_PRIMARY,
            border_color=BORDER_COLOR, corner_radius=6, height=32,
        )
        self.case_operatore.pack(side="left", fill="x", expand=True)

        # ─── 4. FPS settings ───
        card3 = self._card(container, "④  Frame rate (FPS)")

        self.fps_mode = tk.StringVar(value="original")
        self.custom_fps_value = tk.StringVar(value="24")

        fps_row = ctk.CTkFrame(card3, fg_color="transparent")
        fps_row.pack(fill="x")

        ctk.CTkRadioButton(
            fps_row, text="FPS originale del video",
            variable=self.fps_mode, value="original",
            command=self._on_fps_mode_change,
            font=self.font_main,
            fg_color=FG_ACCENT, border_color=BORDER_COLOR,
            hover_color=BG_HOVER, text_color=FG_PRIMARY,
        ).pack(side="left")

        ctk.CTkRadioButton(
            fps_row, text="Personalizzato:",
            variable=self.fps_mode, value="custom",
            command=self._on_fps_mode_change,
            font=self.font_main,
            fg_color=FG_ACCENT, border_color=BORDER_COLOR,
            hover_color=BG_HOVER, text_color=FG_PRIMARY,
        ).pack(side="left", padx=(24, 8))

        self.fps_entry = ctk.CTkEntry(
            fps_row, textvariable=self.custom_fps_value,
            width=70, font=self.font_main,
            fg_color=BG_INPUT, text_color=FG_PRIMARY,
            border_color=BORDER_COLOR, corner_radius=6,
            state="disabled",
        )
        self.fps_entry.pack(side="left")

        ctk.CTkLabel(
            fps_row, text="fps", font=self.font_main, text_color=FG_SECONDARY,
        ).pack(side="left", padx=(6, 0))

        # ─── 5. Action row ───
        action_row = ctk.CTkFrame(container, fg_color="transparent")
        action_row.pack(fill="x", pady=(10, 0))

        self.btn_start = ctk.CTkButton(
            action_row, text="▶  Avvia Esportazione",
            command=self._start_export,
            fg_color=ACCENT_BTN, hover_color="#5d8ae0",
            text_color=ACCENT_BTN_FG, font=self.font_bold,
            corner_radius=10, height=36, width=190,
        )
        self.btn_start.pack(side="left")

        self.btn_cancel = ctk.CTkButton(
            action_row, text="■  Annulla",
            command=self._cancel_export,
            fg_color=FG_ERROR, hover_color="#e05566",
            text_color="#ffffff", font=self.font_bold,
            corner_radius=10, height=36, width=120,
            state="disabled",
        )
        self.btn_cancel.pack(side="left", padx=(10, 0))

        self.open_folder_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            action_row, text="Apri cartella al termine",
            variable=self.open_folder_var,
            font=self.font_main, text_color=FG_PRIMARY,
            fg_color=FG_ACCENT, hover_color=BG_HOVER,
            border_color=BORDER_COLOR, checkmark_color=ACCENT_BTN_FG,
            corner_radius=4,
        ).pack(side="left", padx=(20, 0))

        self.hash_pdf_var = tk.BooleanVar(value=True)
        self.chk_hash_pdf = ctk.CTkCheckBox(
            action_row, text="Genera PDF hash",
            variable=self.hash_pdf_var,
            font=self.font_main, text_color=FG_PRIMARY,
            fg_color=FG_ACCENT, hover_color=BG_HOVER,
            border_color=BORDER_COLOR, checkmark_color=ACCENT_BTN_FG,
            corner_radius=4,
        )
        self.chk_hash_pdf.pack(side="left", padx=(14, 0))
        if not HAS_REPORTLAB:
            self.chk_hash_pdf.configure(state="disabled")
            self.hash_pdf_var.set(False)

        # ─── 6. Progress section ───
        prog_frame = ctk.CTkFrame(container, fg_color="transparent")
        prog_frame.pack(fill="x", pady=(12, 0))

        self.lbl_status = ctk.CTkLabel(
            prog_frame, text="In attesa…",
            font=self.font_bold, text_color=FG_PRIMARY, anchor="w",
        )
        self.lbl_status.pack(fill="x")

        self.progress = ctk.CTkProgressBar(
            prog_frame, fg_color=BG_INPUT,
            progress_color=FG_ACCENT, height=10,
            corner_radius=5,
        )
        self.progress.pack(fill="x", pady=(6, 6))
        self.progress.set(0)

        self.lbl_detail = ctk.CTkLabel(
            prog_frame, text="",
            font=self.font_small, text_color=FG_SECONDARY, anchor="w",
        )
        self.lbl_detail.pack(fill="x")

        # ─── Version label ───
        ctk.CTkLabel(
            container, text="v1.0",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=FG_SECONDARY, anchor="center",
        ).pack(fill="x", pady=(14, 4))

    def _card(self, parent, title: str) -> ctk.CTkFrame:
        """Create a styled card section with rounded corners."""
        outer = ctk.CTkFrame(parent, fg_color="transparent")
        outer.pack(fill="x", pady=(0, 6))

        ctk.CTkLabel(
            outer, text=title,
            font=self.font_bold, text_color=FG_PRIMARY,
        ).pack(anchor="w", pady=(0, 4))

        card = ctk.CTkFrame(
            outer, fg_color=BG_CARD,
            corner_radius=12, border_width=1,
            border_color=BORDER_COLOR,
        )
        card.pack(fill="both", expand=True)

        # Inner padding
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=12, pady=10)
        return inner

    # ── File list row management ─────────────
    def _create_file_row(self, filename: str, index: int) -> ctk.CTkFrame:
        """Create a single interactive row in the file list."""
        row = ctk.CTkFrame(
            self.file_list_frame, fg_color="transparent",
            corner_radius=6, height=36,
        )
        row.pack(fill="x", pady=(0, 2), padx=4)
        row.pack_propagate(False)

        # Row index label (dimmed)
        ctk.CTkLabel(
            row, text=f"{index + 1}.",
            font=self.font_small, text_color=FG_SECONDARY,
            width=30, anchor="e",
        ).pack(side="left", padx=(4, 6))

        # Filename label
        lbl = ctk.CTkLabel(
            row, text=filename,
            font=self.font_mono, text_color=FG_PRIMARY,
            anchor="w",
        )
        lbl.pack(side="left", fill="x", expand=True)

        # Make the row clickable for selection
        for widget in [row, lbl]:
            widget.bind("<Button-1>", lambda e, idx=index: self._select_row(idx))

        return row

    def _refresh_file_list(self):
        """Rebuild the visual file list from self.video_paths."""
        # Destroy all children of the scrollable frame
        for widget in self.file_list_frame.winfo_children():
            widget.destroy()

        if not self.video_paths:
            self._empty_label = ctk.CTkLabel(
                self.file_list_frame,
                text="Trascina o aggiungi video qui…",
                font=self.font_sub, text_color=FG_SECONDARY,
            )
            self._empty_label.pack(pady=30)
        else:
            for i, path in enumerate(self.video_paths):
                self._create_file_row(os.path.basename(path), i)

        self._selected_row_index = None

    def _select_row(self, index: int):
        """Highlight a row in the file list."""
        rows = [w for w in self.file_list_frame.winfo_children()
                if isinstance(w, ctk.CTkFrame)]

        # Deselect previous
        for row in rows:
            row.configure(fg_color="transparent")

        # Select new
        if 0 <= index < len(rows):
            rows[index].configure(fg_color=BG_HOVER)
            self._selected_row_index = index

    # ── event handlers ───────────────────────
    def _is_duplicate(self, path: str) -> bool:
        """Check if a video path is already in the list (case-insensitive on Windows)."""
        norm = os.path.normpath(path).lower()
        return any(os.path.normpath(p).lower() == norm for p in self.video_paths)

    def _add_videos(self):
        filetypes = [("Video files", " ".join(f"*{e}" for e in VIDEO_EXTENSIONS)), ("Tutti i file", "*.*")]
        paths = filedialog.askopenfilenames(title="Seleziona video", filetypes=filetypes)
        added, skipped = 0, 0
        for p in paths:
            if self._is_duplicate(p):
                skipped += 1
            else:
                self.video_paths.append(p)
                added += 1
        self._refresh_file_list()
        self._update_count()
        if skipped > 0:
            self.lbl_status.configure(
                text=f"⚠  {skipped} video duplicato/i ignorato/i.", text_color=FG_WARNING)

    def _on_files_dropped(self, files):
        """Process dropped files (called from main thread via queue)."""
        added, skipped = 0, 0
        for f in files:
            path = f.decode("utf-8") if isinstance(f, bytes) else str(f)
            path = path.strip()
            ext = os.path.splitext(path)[1].lower()
            if ext not in VIDEO_EXTENSIONS:
                continue
            if self._is_duplicate(path):
                skipped += 1
            else:
                self.video_paths.append(path)
                added += 1
        if added > 0:
            self._refresh_file_list()
            self._update_count()
        if skipped > 0:
            self.lbl_status.configure(
                text=f"⚠  {skipped} video duplicato/i ignorato/i.", text_color=FG_WARNING)

    def _poll_drop_queue(self):
        """Poll the drop queue from the main thread to avoid GIL issues."""
        try:
            while True:
                files = self._drop_queue.get_nowait()
                self._on_files_dropped(files)
        except queue.Empty:
            pass
        self.after(100, self._poll_drop_queue)

    def _remove_selected(self):
        if self._selected_row_index is not None and 0 <= self._selected_row_index < len(self.video_paths):
            del self.video_paths[self._selected_row_index]
            self._selected_row_index = None
            self._refresh_file_list()
            self._update_count()

    def _clear_list(self):
        self.video_paths.clear()
        self._selected_row_index = None
        self._refresh_file_list()
        self._update_count()

    def _update_count(self):
        n = len(self.video_paths)
        if n == 0:
            self.lbl_count.configure(text="Nessun video selezionato")
        elif n == 1:
            self.lbl_count.configure(text="1 video selezionato")
        else:
            self.lbl_count.configure(text=f"{n} video selezionati")

    def _choose_output(self):
        d = filedialog.askdirectory(title="Scegli cartella di output")
        if d:
            self.output_directory = d
            self.lbl_output.configure(text=d, text_color=FG_PRIMARY)

    def _on_fps_mode_change(self):
        if self.fps_mode.get() == "custom":
            self.fps_entry.configure(state="normal")
        else:
            self.fps_entry.configure(state="disabled")

    # ── export logic ─────────────────────────
    def _validate(self) -> bool:
        if not self.video_paths:
            messagebox.showwarning("Attenzione", "Aggiungi almeno un video.")
            return False
        if not self.output_directory:
            messagebox.showwarning("Attenzione", "Seleziona una cartella di output.")
            return False
        if self.fps_mode.get() == "custom":
            try:
                val = float(self.custom_fps_value.get())
                if val <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Errore", "Inserisci un valore FPS valido (numero positivo).")
                return False
        return True

    def _start_export(self):
        if not self._validate():
            return

        self.is_running = True
        self.cancel_event.clear()
        self.btn_start.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self.progress.set(0)

        target_fps = None
        if self.fps_mode.get() == "custom":
            target_fps = float(self.custom_fps_value.get())

        thread = threading.Thread(
            target=self._export_worker,
            args=(list(self.video_paths), self.output_directory, target_fps),
            daemon=True,
        )
        thread.start()

    def _cancel_export(self):
        self.cancel_event.set()
        self.lbl_status.configure(text="Annullamento in corso…", text_color=FG_ERROR)

    def _export_worker(self, paths: list[str], output_dir: str, target_fps: float | None):
        total_videos = len(paths)
        total_saved = 0
        errors: list[str] = []

        for idx, video_path in enumerate(paths, start=1):
            if self.cancel_event.is_set():
                break

            video_name = Path(video_path).stem
            folder = os.path.join(output_dir, video_name)

            self.after(0, self._update_status,
                       f"[{idx}/{total_videos}]  Elaborazione: {video_name}…", FG_PRIMARY)
            self.after(0, self._update_detail, "Lettura video…")

            def progress_cb(current, total, _idx=idx, _total=total_videos):
                pct = (current / total) * 100 if total else 0
                overall = ((_idx - 1) / _total + pct / 100 / _total) * 100
                self.after(0, self._set_progress, overall)
                self.after(0, self._update_detail,
                           f"Frame {current}/{total}  ({pct:.0f}%)")

            try:
                # ── Gather video metadata before extraction ──
                cap_meta = cv2.VideoCapture(video_path)
                native_fps = cap_meta.get(cv2.CAP_PROP_FPS) or 30.0
                total_video_frames = int(cap_meta.get(cv2.CAP_PROP_FRAME_COUNT))
                cap_meta.release()

                # Compute video duration
                if total_video_frames > 0 and native_fps > 0:
                    total_seconds = total_video_frames / native_fps
                    hours = int(total_seconds // 3600)
                    minutes = int((total_seconds % 3600) // 60)
                    seconds = int(total_seconds % 60)
                    duration_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                else:
                    duration_str = "N/D"

                # Compute hash of the original video file
                self.after(0, self._update_detail,
                           f"Calcolo hash del file originale…")
                video_hashes = _compute_file_hashes(video_path)

                saved = extract_frames(
                    video_path, folder,
                    target_fps=target_fps,
                    progress_callback=progress_cb,
                    cancel_event=self.cancel_event,
                )
                total_saved += saved

                # Generate hash PDF if requested
                if self.hash_pdf_var.get() and not self.cancel_event.is_set():
                    self.after(0, self._update_detail,
                              f"Generazione PDF hash per {video_name}…")

                    def hash_progress_cb(current, total, _idx=idx, _total=total_videos):
                        pct = (current / total) * 100 if total else 0
                        overall = ((_idx - 1) / _total + 0.95 / _total + pct * 0.05 / 100 / _total) * 100
                        self.after(0, self._set_progress, min(overall, 100))
                        self.after(0, self._update_detail,
                                   f"Hash fotogramma {current}/{total}  ({pct:.0f}%)")

                    case_info = {
                        "numero_caso": self.case_numero.get().strip(),
                        "codice_reperto": self.case_reperto.get().strip(),
                        "operatore": self.case_operatore.get().strip(),
                    }
                    video_meta = {
                        "file_hash_sha256": video_hashes["sha256"],
                        "file_hash_md5": video_hashes["md5"],
                        "duration_str": duration_str,
                        "total_video_frames": total_video_frames,
                        "exported_frames": saved,
                        "native_fps": round(native_fps, 2),
                        "video_filename": Path(video_path).name,
                    }
                    if target_fps is not None:
                        video_meta["custom_fps"] = target_fps
                    generate_hash_pdf(folder, video_name, progress_callback=hash_progress_cb, case_info=case_info, video_meta=video_meta)
            except Exception as e:
                errors.append(f"{video_name}: {e}")

        # Finished
        self.after(0, self._export_done, total_saved, errors, self.cancel_event.is_set())

    def _update_status(self, text, color):
        self.lbl_status.configure(text=text, text_color=color)

    def _update_detail(self, text):
        self.lbl_detail.configure(text=text)

    def _set_progress(self, value):
        self.progress.set(value / 100.0)  # CTkProgressBar uses 0.0–1.0

    def _export_done(self, total_saved: int, errors: list[str], cancelled: bool):
        self.is_running = False
        self.btn_start.configure(state="normal")
        self.btn_cancel.configure(state="disabled")
        self.progress.set(1.0 if not cancelled else 0.0)

        if cancelled:
            self.lbl_status.configure(
                text="⚠  Esportazione annullata.", text_color=FG_ERROR)
            self.lbl_detail.configure(
                text=f"{total_saved} fotogrammi salvati prima dell'annullamento.")
        elif errors:
            self.lbl_status.configure(
                text=f"⚠  Completato con {len(errors)} errore/i.  {total_saved} fotogrammi salvati.",
                text_color=FG_ERROR)
            self.lbl_detail.configure(text=" | ".join(errors))
        else:
            self.lbl_status.configure(
                text=f"✅  Completato!  {total_saved} fotogrammi salvati.",
                text_color=FG_SUCCESS)
            self.lbl_detail.configure(text=f"Output: {self.output_directory}")

        # Open output folder in file explorer if enabled and not cancelled
        if not cancelled and self.open_folder_var.get() and self.output_directory:
            try:
                os.startfile(self.output_directory)
            except Exception:
                pass


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────
if __name__ == "__main__":
    app = VideoToFramesApp()
    app.mainloop()
