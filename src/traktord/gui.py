"""Interface graphique Traktor Data Converter.

Fenetre simple : selectionner un export Rekordbox, convertir vers Traktor
avec injection automatique des artworks.
"""

from __future__ import annotations

import shutil
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional


# ----------------------------------------------------------------------------
# Detection automatique
# ----------------------------------------------------------------------------

def _find_traktor4_dir() -> Optional[Path]:
    """Trouver le dossier Traktor 4 dans ~/Documents/Native Instruments."""
    ni_dir = Path.home() / "Documents" / "Native Instruments"
    if not ni_dir.exists():
        return None
    for d in sorted(ni_dir.iterdir(), reverse=True):
        if d.name.startswith("Traktor 4") and d.is_dir():
            return d
    return None


def _backup_collection(traktor_dir: Path) -> Optional[Path]:
    """Sauvegarder le collection.nml existant avant ecrasement."""
    nml = traktor_dir / "collection.nml"
    if not nml.exists():
        return None
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = traktor_dir / "Backup"
    backup_dir.mkdir(exist_ok=True)
    backup = backup_dir / f"collection_{timestamp}.nml"
    shutil.copy2(nml, backup)
    return backup


# ----------------------------------------------------------------------------
# Conversion en arriere-plan
# ----------------------------------------------------------------------------

def _run_conversion(
    xml_path: str,
    traktor_dir: Path,
    inject_art: bool,
    on_progress: callable,
    on_done: callable,
    on_error: callable,
) -> None:
    """Execute la conversion dans un thread separe."""
    try:
        from traktord.parsers.rekordbox import RekordboxParser
        from traktord.converters.traktor import TraktorWriter

        # Etape 1 : Parser
        on_progress("Lecture de l'export Rekordbox...", 0, 0)
        parser = RekordboxParser()
        collection = parser.parse(xml_path)
        total = len(collection.tracks)
        on_progress(f"{total} tracks chargees", 0, total)

        # Etape 2 : Backup + ecriture NML
        backup = _backup_collection(traktor_dir)
        nml_path = traktor_dir / "collection.nml"
        on_progress("Ecriture du fichier Traktor...", 0, total)
        writer = TraktorWriter()
        writer.write(collection, str(nml_path))

        # Etape 3 : Artworks
        injected = 0
        skipped = 0
        if inject_art:
            from traktord.utils.trmd import inject_artwork
            coverart_dir = traktor_dir / "Coverart"
            coverart_dir.mkdir(exist_ok=True)

            for i, track in enumerate(collection.tracks):
                mp3 = Path(track.file_path)
                if mp3.exists() and mp3.suffix.lower() == ".mp3":
                    try:
                        result = inject_artwork(mp3, coverart_dir)
                        if result:
                            injected += 1
                        else:
                            skipped += 1
                    except Exception:
                        skipped += 1
                else:
                    skipped += 1

                if (i + 1) % 10 == 0 or i + 1 == total:
                    on_progress(
                        f"Artworks : {injected} injectes, {skipped} ignores",
                        i + 1,
                        total,
                    )

        # Resume
        summary = f"{total} tracks converties"
        if inject_art:
            summary += f", {injected} artworks injectes"
        if backup:
            summary += f"\nBackup : {backup.name}"
        summary += f"\nFichier : {nml_path}"

        on_done(summary)

    except Exception as e:
        on_error(str(e))


# ----------------------------------------------------------------------------
# Interface graphique
# ----------------------------------------------------------------------------

class ConverterApp:
    """Fenetre principale du convertisseur."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Traktor Data Converter")
        self.root.resizable(False, False)

        # Taille et centrage
        w, h = 520, 420
        sx = self.root.winfo_screenwidth() // 2 - w // 2
        sy = self.root.winfo_screenheight() // 3 - h // 2
        self.root.geometry(f"{w}x{h}+{sx}+{sy}")

        # Style
        self.root.configure(bg="#1a1a2e")
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TLabel", background="#1a1a2e", foreground="#e0e0e0", font=("Helvetica", 12))
        style.configure("Title.TLabel", font=("Helvetica", 18, "bold"), foreground="#00d4ff")
        style.configure("Sub.TLabel", font=("Helvetica", 10), foreground="#888888")
        style.configure("Status.TLabel", font=("Helvetica", 11), foreground="#aaaaaa")
        style.configure("TButton", font=("Helvetica", 12), padding=8)
        style.configure("Convert.TButton", font=("Helvetica", 14, "bold"), padding=12)
        style.configure("TCheckbutton", background="#1a1a2e", foreground="#e0e0e0", font=("Helvetica", 11))
        style.configure(
            "pointed.Horizontal.TProgressbar",
            troughcolor="#2a2a4a",
            background="#00d4ff",
        )

        self._build_ui()
        self._detect_traktor()

    def _build_ui(self) -> None:
        pad = {"padx": 20, "pady": 4}
        frame = self.root

        # Titre
        ttk.Label(frame, text="Traktor Data Converter", style="Title.TLabel").pack(pady=(20, 2))
        ttk.Label(frame, text="Rekordbox → Traktor Pro 4", style="Sub.TLabel").pack(pady=(0, 16))

        # Export Rekordbox
        ttk.Label(frame, text="Export Rekordbox (.xml)").pack(anchor="w", **pad)
        file_frame = tk.Frame(frame, bg="#1a1a2e")
        file_frame.pack(fill="x", padx=20, pady=(0, 10))

        self.xml_var = tk.StringVar()
        self.xml_entry = ttk.Entry(file_frame, textvariable=self.xml_var, width=42)
        self.xml_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(file_frame, text="Parcourir", command=self._browse_xml).pack(side="right", padx=(8, 0))

        # Dossier Traktor (auto-detecte)
        ttk.Label(frame, text="Dossier Traktor 4 (auto-detecte)").pack(anchor="w", **pad)
        traktor_frame = tk.Frame(frame, bg="#1a1a2e")
        traktor_frame.pack(fill="x", padx=20, pady=(0, 10))

        self.traktor_var = tk.StringVar()
        self.traktor_entry = ttk.Entry(traktor_frame, textvariable=self.traktor_var, width=42)
        self.traktor_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(traktor_frame, text="Changer", command=self._browse_traktor).pack(side="right", padx=(8, 0))

        # Checkbox artworks
        self.artwork_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            frame,
            text="Injecter les artworks (pochettes) dans les MP3",
            variable=self.artwork_var,
        ).pack(anchor="w", padx=20, pady=(4, 12))

        # Bouton Convertir
        self.convert_btn = ttk.Button(
            frame,
            text="Convertir",
            style="Convert.TButton",
            command=self._start_conversion,
        )
        self.convert_btn.pack(pady=(4, 12))

        # Progress bar
        self.progress = ttk.Progressbar(
            frame,
            style="pointed.Horizontal.TProgressbar",
            length=460,
            mode="determinate",
        )
        self.progress.pack(pady=(0, 6))

        # Status
        self.status_var = tk.StringVar(value="Pret")
        ttk.Label(frame, textvariable=self.status_var, style="Status.TLabel").pack(pady=(0, 10))

    def _detect_traktor(self) -> None:
        traktor = _find_traktor4_dir()
        if traktor:
            self.traktor_var.set(str(traktor))
        else:
            self.traktor_var.set("")
            self.status_var.set("Traktor 4 non detecte — selectionner le dossier manuellement")

    def _browse_xml(self) -> None:
        path = filedialog.askopenfilename(
            title="Selectionner l'export Rekordbox",
            filetypes=[("Fichiers XML", "*.xml"), ("Tous", "*.*")],
        )
        if path:
            self.xml_var.set(path)

    def _browse_traktor(self) -> None:
        path = filedialog.askdirectory(title="Selectionner le dossier Traktor 4")
        if path:
            self.traktor_var.set(path)

    def _start_conversion(self) -> None:
        xml = self.xml_var.get().strip()
        traktor = self.traktor_var.get().strip()

        if not xml:
            messagebox.showwarning("Attention", "Selectionner un fichier XML Rekordbox.")
            return
        if not Path(xml).exists():
            messagebox.showerror("Erreur", f"Fichier introuvable :\n{xml}")
            return
        if not traktor:
            messagebox.showwarning("Attention", "Selectionner le dossier Traktor 4.")
            return
        if not Path(traktor).is_dir():
            messagebox.showerror("Erreur", f"Dossier introuvable :\n{traktor}")
            return

        self.convert_btn.configure(state="disabled")
        self.progress["value"] = 0

        thread = threading.Thread(
            target=_run_conversion,
            args=(
                xml,
                Path(traktor),
                self.artwork_var.get(),
                self._on_progress,
                self._on_done,
                self._on_error,
            ),
            daemon=True,
        )
        thread.start()

    def _on_progress(self, message: str, current: int, total: int) -> None:
        def _update():
            self.status_var.set(message)
            if total > 0:
                self.progress["maximum"] = total
                self.progress["value"] = current
        self.root.after(0, _update)

    def _on_done(self, summary: str) -> None:
        def _update():
            self.progress["value"] = self.progress["maximum"]
            self.status_var.set("Conversion terminee !")
            self.convert_btn.configure(state="normal")
            messagebox.showinfo("Conversion terminee", summary)
        self.root.after(0, _update)

    def _on_error(self, error: str) -> None:
        def _update():
            self.status_var.set("Erreur")
            self.convert_btn.configure(state="normal")
            messagebox.showerror("Erreur", error)
        self.root.after(0, _update)

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    """Point d'entree de l'interface graphique."""
    app = ConverterApp()
    app.run()


if __name__ == "__main__":
    main()
