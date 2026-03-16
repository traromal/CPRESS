from __future__ import annotations
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path

from cpress import archive
from cpress.cli import resolve_format  # type: ignore


def compress_action():
    inputs = filedialog.askopenfilenames(title="Select files/folders to compress")
    if not inputs:
        return
    out_path = filedialog.asksaveasfilename(title="Save archive as", defaultextension=".zip")
    if not out_path:
        return
    fmt = resolve_format(Path(out_path), None)
    def run():
        try:
            archive.compress([Path(p) for p in inputs], Path(out_path), fmt, level=6, exclude=[], password=None, zip_aes=True)
            archive.test_archive(Path(out_path), fmt, None)
            messagebox.showinfo("cpress", f"Created {out_path}")
        except Exception as exc:
            messagebox.showerror("cpress", str(exc))
    threading.Thread(target=run, daemon=True).start()


def extract_action():
    archive_path = filedialog.askopenfilename(title="Select archive to extract")
    if not archive_path:
        return
    dest = filedialog.askdirectory(title="Select destination")
    if not dest:
        return
    fmt = resolve_format(Path(archive_path), None)
    def run():
        try:
            archive.decompress(Path(archive_path), Path(dest), fmt, password=None)
            messagebox.showinfo("cpress", f"Extracted to {dest}")
        except Exception as exc:
            messagebox.showerror("cpress", str(exc))
    threading.Thread(target=run, daemon=True).start()


def main():
    root = tk.Tk()
    root.title("cpress")
    root.geometry("320x160")
    tk.Button(root, text="Compress", width=20, command=compress_action).pack(pady=15)
    tk.Button(root, text="Extract", width=20, command=extract_action).pack(pady=5)
    tk.Label(root, text="Quick GUI powered by cpress", fg="gray").pack(side=tk.BOTTOM, pady=10)
    root.mainloop()


if __name__ == "__main__":
    main()
