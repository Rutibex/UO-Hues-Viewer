#!/usr/bin/env python3
# uo_hues_viewer.py
# GUI viewer for Ultima Online hues.mul
# - Parses HueGroup/HueEntry records
# - Shows swatches and 32 RGB values per hue
# - Exports a CSV of all hues and their 32 RGB triplets
#
# References:
# HUES.MUL structure (HueGroup + 8 HueEntry, HueEntry has 32 WORDs + start + end + name[20])
# https://uo.stratics.com/heptazane/fileformats.shtml  (section 3.7 HUES.MUL)
# UO color packing: 0:4=Blue, 5:9=Green, 10:14=Red (bit15 unused), scale 0..31 -> 0..255
# https://uo.stratics.com/heptazane/fileformats.shtml  (section 1.2 Colors)

import os
import struct
import csv
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk

# ---------- Parsing ----------

HUE_ENTRY_STRUCT = "<32HHH20s"  # 32*WORD color table, WORD start, WORD end, 20-byte name (little-endian)
HUE_ENTRY_SIZE = struct.calcsize(HUE_ENTRY_STRUCT)  # 64 + 2 + 2 + 20 = 88 bytes
HUE_GROUP_HEADER_SIZE = 4  # DWORD header per group
HUES_PER_GROUP = 8

def color16_to_rgb888(c16: int):
    """Convert UO 15-bit color (x RRRRR GGGGG BBBBB) to (R,G,B) 0..255."""
    r5 = (c16 >> 10) & 0x1F
    g5 = (c16 >> 5)  & 0x1F
    b5 =  c16        & 0x1F
    # scale 0..31 -> 0..255 (use integer math)
    r = (r5 * 255) // 31
    g = (g5 * 255) // 31
    b = (b5 * 255) // 31
    return (r, g, b)

def parse_hues(path):
    """
    Read hues.mul: a stream of HueGroup blocks until EOF.
    Each HueGroup: DWORD header + 8 HueEntry.
    HueEntry: 32 WORD color table, WORD start, WORD end, CHAR[20] name.
    Returns list of dicts: {index, name, start, end, colors16, colorsRGB}
    """
    hues = []
    idx = 1
    filesize = os.path.getsize(path)
    with open(path, "rb") as f:
        pos = 0
        while True:
            # Read group header
            hdr = f.read(HUE_GROUP_HEADER_SIZE)
            pos += len(hdr)
            if not hdr or len(hdr) < HUE_GROUP_HEADER_SIZE:
                break  # EOF
            # Read 8 entries
            for _ in range(HUES_PER_GROUP):
                data = f.read(HUE_ENTRY_SIZE)
                if not data or len(data) < HUE_ENTRY_SIZE:
                    # graceful stop if file ends unexpectedly
                    return hues
                pos += len(data)

                unpacked = struct.unpack(HUE_ENTRY_STRUCT, data)
                colors16 = list(unpacked[0:32])
                start = unpacked[32]
                end   = unpacked[33]
                rawname = unpacked[34]
                name = rawname.split(b"\x00", 1)[0].decode("ascii", errors="ignore").strip()

                colorsRGB = [color16_to_rgb888(c) for c in colors16]

                hues.append({
                    "index": idx,
                    "name": name,
                    "start": start,
                    "end": end,
                    "colors16": colors16,
                    "colorsRGB": colorsRGB
                })
                idx += 1

            # safety: stop if we somehow overshoot
            if pos >= filesize:
                break

    return hues

# ---------- GUI Helpers ----------

def make_swatch_image(rgb_list, width=640, height=40):
    """
    Create a horizontal swatch image from a list of 32 (R,G,B) tuples.
    """
    # Base 32x1 strip scaled up for crisp bands
    base = Image.new("RGB", (32, 1))
    for i, rgb in enumerate(rgb_list[:32]):
        base.putpixel((i, 0), rgb)
    img = base.resize((width, height), resample=Image.NEAREST)
    return img

def format_rgb_list(rgb_list):
    """
    Return a human-friendly string table of the 32 RGBs.
    """
    lines = []
    for i, (r, g, b) in enumerate(rgb_list):
        lines.append(f"{i:02d}: ({r:3d}, {g:3d}, {b:3d})")
    # group in rows of 8 for readability
    chunks = [lines[i:i+8] for i in range(0, len(lines), 8)]
    return "\n\n".join("\n".join(row) for row in chunks)

# ---------- GUI App ----------

class HuesApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Ultima Online Hues Viewer")
        self.geometry("1000x640")
        self.minsize(900, 560)

        self.hues = []           # loaded hues
        self.current_swatch = None
        self.current_swatch_tk = None

        self._build_menu()
        self._build_widgets()

    def _build_menu(self):
        menubar = tk.Menu(self)
        filemenu = tk.Menu(menubar, tearoff=False)
        filemenu.add_command(label="Open hues.mul…", command=self.open_file)
        filemenu.add_separator()
        filemenu.add_command(label="Exit", command=self.destroy)
        menubar.add_cascade(label="File", menu=filemenu)

        exportmenu = tk.Menu(menubar, tearoff=False)
        exportmenu.add_command(label="CSV of all hues…", command=self.export_csv)
        menubar.add_cascade(label="Export", menu=exportmenu)

        self.config(menu=menubar)

    def _build_widgets(self):
        # Left frame: hue list
        left = ttk.Frame(self)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=6)

        ttk.Label(left, text="Hues").pack(anchor="w")
        self.hue_list = tk.Listbox(left, width=34, height=30, exportselection=False)
        self.hue_list.pack(fill=tk.Y, expand=False, side=tk.LEFT)

        list_scroll = ttk.Scrollbar(left, orient="vertical", command=self.hue_list.yview)
        list_scroll.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 4))
        self.hue_list.config(yscrollcommand=list_scroll.set)
        self.hue_list.bind("<<ListboxSelect>>", self.on_select)

        # Right frame: details
        right = ttk.Frame(self)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=6, pady=6)

        # Metadata
        meta = ttk.Frame(right)
        meta.pack(fill=tk.X, anchor="n")

        self.lbl_index = ttk.Label(meta, text="Index: —", width=18)
        self.lbl_index.pack(side=tk.LEFT, padx=(0, 12))
        self.lbl_name  = ttk.Label(meta, text="Name: —")
        self.lbl_name.pack(side=tk.LEFT, padx=(0, 12))
        self.lbl_range = ttk.Label(meta, text="Range: —")
        self.lbl_range.pack(side=tk.LEFT)

        # Swatch
        self.swatch_canvas = tk.Canvas(right, height=60, highlightthickness=1, bg="#333333", highlightbackground="#555555")
        self.swatch_canvas.pack(fill=tk.X, pady=8)

        # RGB text area
        rgb_frame = ttk.Frame(right)
        rgb_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(rgb_frame, text="RGB values (32 entries per hue):").pack(anchor="w")

        self.txt_rgb = tk.Text(rgb_frame, wrap="none")
        self.txt_rgb.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)

        txt_scroll_y = ttk.Scrollbar(rgb_frame, orient="vertical", command=self.txt_rgb.yview)
        txt_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.txt_rgb.config(yscrollcommand=txt_scroll_y.set)

        txt_scroll_x = ttk.Scrollbar(right, orient="horizontal", command=self.txt_rgb.xview)
        txt_scroll_x.pack(fill=tk.X)
        self.txt_rgb.config(xscrollcommand=txt_scroll_x.set)

        # Status
        self.status = ttk.Label(self, text="Open a hues.mul to get started.")
        self.status.pack(side=tk.BOTTOM, fill=tk.X)

    # -------- actions --------

    def open_file(self):
        path = filedialog.askopenfilename(
            title="Open hues.mul",
            filetypes=[("UO hues.mul", "hues.mul"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            hues = parse_hues(path)
            if not hues:
                raise ValueError("No hues found or file unreadable.")
            self.hues = hues
            self._populate_list()
            self.status.config(text=f"Loaded {len(hues)} hues from: {path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read hues.mul:\n{e}")

    def _populate_list(self):
        self.hue_list.delete(0, tk.END)
        for h in self.hues:
            label = f"{h['index']:4d} — {h['name'] or '(no name)'}"
            self.hue_list.insert(tk.END, label)
        if self.hues:
            self.hue_list.selection_clear(0, tk.END)
            self.hue_list.selection_set(0)
            self.hue_list.event_generate("<<ListboxSelect>>")

    def on_select(self, _evt):
        sel = self.hue_list.curselection()
        if not sel:
            return
        h = self.hues[sel[0]]

        # Labels
        self.lbl_index.config(text=f"Index: {h['index']}")
        self.lbl_name.config(text=f"Name: {h['name'] or '(no name)'}")
        self.lbl_range.config(text=f"Range: {h['start']}–{h['end']}")

        # Swatch
        self.current_swatch = make_swatch_image(h["colorsRGB"], width=self.swatch_canvas.winfo_width() or 640, height=40)
        self.current_swatch_tk = ImageTk.PhotoImage(self.current_swatch)
        self.swatch_canvas.delete("all")
        w = self.swatch_canvas.winfo_width()
        self.swatch_canvas.create_image(10, 10, anchor="nw", image=self.current_swatch_tk)
        self.swatch_canvas.config(height=60)

        # RGB list
        self.txt_rgb.config(state="normal")
        self.txt_rgb.delete("1.0", tk.END)
        self.txt_rgb.insert(tk.END, format_rgb_list(h["colorsRGB"]))
        self.txt_rgb.config(state="disabled")

    def export_csv(self):
        if not self.hues:
            messagebox.showinfo("Export", "Load a hues.mul first.")
            return
        path = filedialog.asksaveasfilename(
            title="Save CSV",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                # header: index, name, start, end, then 32 RGB triplets flattened
                header = ["index", "name", "start", "end"]
                for i in range(32):
                    header += [f"c{i}_R", f"c{i}_G", f"c{i}_B"]
                writer.writerow(header)
                for h in self.hues:
                    row = [h["index"], h["name"], h["start"], h["end"]]
                    for (r, g, b) in h["colorsRGB"]:
                        row += [r, g, b]
                    writer.writerow(row)
            messagebox.showinfo("Export", f"Saved: {path}")
        except Exception as e:
            messagebox.showerror("Export error", f"Could not save CSV:\n{e}")

if __name__ == "__main__":
    app = HuesApp()
    app.mainloop()
