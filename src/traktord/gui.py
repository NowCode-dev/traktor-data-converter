"""Interface graphique Traktor Data Converter.

Utilise customtkinter pour un rendu correct sur macOS (dark mode).
Charte graphique NowCode : fond anthracite, accent cyan, texte silver.
"""

from __future__ import annotations

import shutil
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Optional

import customtkinter as ctk


# ----------------------------------------------------------------------------
# Charte NowCode
# ----------------------------------------------------------------------------

BG = "#12161D"
BG_FIELD = "#1E2532"
FG = "#D2DEE3"
FG_DIM = "#7A8A94"
ACCENT = "#15E9F2"
ACCENT_HOVER = "#3AB2CD"
BTN_FG = "#12161D"


# ----------------------------------------------------------------------------
# Detection automatique
# ----------------------------------------------------------------------------

def _find_traktor4_dir() -> Optional[Path]:
    ni_dir = Path.home() / "Documents" / "Native Instruments"
    if not ni_dir.exists():
        return None
    for d in sorted(ni_dir.iterdir(), reverse=True):
        if d.name.startswith("Traktor 4") and d.is_dir():
            return d
    return None


def _backup_collection(traktor_dir: Path) -> Optional[Path]:
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
    on_progress,
    on_done,
    on_error,
) -> None:
    try:
        from traktord.parsers.rekordbox import RekordboxParser
        from traktord.converters.traktor import TraktorWriter

        on_progress("Lecture de l'export Rekordbox...", 0, 0)
        parser = RekordboxParser()
        collection = parser.parse(xml_path)
        total = len(collection.tracks)
        on_progress(f"{total} tracks chargees", 0, total)

        backup = _backup_collection(traktor_dir)
        nml_path = traktor_dir / "collection.nml"
        on_progress("Ecriture du fichier Traktor...", 0, total)
        writer = TraktorWriter()
        writer.write(collection, str(nml_path))

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

        summary = f"{total} tracks converties"
        if inject_art:
            summary += f"\n{injected} artworks injectes"
        if backup:
            summary += f"\n\nBackup : {backup.name}"
        summary += f"\nFichier : {nml_path}"

        on_done(summary)

    except Exception as e:
        on_error(str(e))


# ----------------------------------------------------------------------------
# Interface graphique
# ----------------------------------------------------------------------------

class ConverterApp(ctk.CTk):
    """Fenetre principale du convertisseur."""

    def __init__(self) -> None:
        super().__init__()

        # Theme customtkinter
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.title("Traktor Data Converter — NowCode")
        self.resizable(False, False)
        self.configure(fg_color=BG)

        w, h = 560, 440
        sx = self.winfo_screenwidth() // 2 - w // 2
        sy = self.winfo_screenheight() // 3 - h // 2
        self.geometry(f"{w}x{h}+{sx}+{sy}")

        self._build_ui()
        self._detect_traktor()

    def _build_ui(self) -> None:
        # --- Logo NowCode ---
        logo_path = Path(__file__).parent / "logo.png"
        if logo_path.exists():
            try:
                self._logo_img = tk.PhotoImage(file=str(logo_path)).subsample(2, 2)
                tk.Label(self, image=self._logo_img, bg=BG).pack(pady=(16, 4))
            except Exception:
                pass

        # --- Titre ---
        ctk.CTkLabel(
            self, text="Traktor Data Converter",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=ACCENT,
        ).pack(pady=(4, 0))
        ctk.CTkLabel(
            self, text="Rekordbox  \u2192  Traktor Pro 4",
            font=ctk.CTkFont(size=12),
            text_color=FG_DIM,
        ).pack(pady=(0, 16))

        # --- Export Rekordbox ---
        ctk.CTkLabel(
            self, text="Export Rekordbox (.xml)",
            font=ctk.CTkFont(size=13), text_color=FG, anchor="w",
        ).pack(fill="x", padx=30)

        row1 = ctk.CTkFrame(self, fg_color=BG)
        row1.pack(fill="x", padx=30, pady=(2, 10))
        self.xml_var = tk.StringVar()
        ctk.CTkEntry(
            row1, textvariable=self.xml_var, width=380,
            font=ctk.CTkFont(size=12),
            fg_color=BG_FIELD, text_color=FG, border_color=ACCENT_HOVER,
        ).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            row1, text="Parcourir", command=self._browse_xml, width=90,
            font=ctk.CTkFont(size=12),
            fg_color=BG_FIELD, hover_color=ACCENT_HOVER, text_color=FG,
        ).pack(side="right", padx=(8, 0))

        # --- Dossier Traktor ---
        ctk.CTkLabel(
            self, text="Dossier Traktor 4 (auto-detecte)",
            font=ctk.CTkFont(size=13), text_color=FG, anchor="w",
        ).pack(fill="x", padx=30)

        row2 = ctk.CTkFrame(self, fg_color=BG)
        row2.pack(fill="x", padx=30, pady=(2, 10))
        self.traktor_var = tk.StringVar()
        ctk.CTkEntry(
            row2, textvariable=self.traktor_var, width=380,
            font=ctk.CTkFont(size=12),
            fg_color=BG_FIELD, text_color=FG, border_color=ACCENT_HOVER,
        ).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            row2, text="Changer", command=self._browse_traktor, width=90,
            font=ctk.CTkFont(size=12),
            fg_color=BG_FIELD, hover_color=ACCENT_HOVER, text_color=FG,
        ).pack(side="right", padx=(8, 0))

        # --- Checkbox artworks ---
        self.artwork_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            self, text="Injecter les artworks (pochettes) dans les MP3",
            variable=self.artwork_var,
            font=ctk.CTkFont(size=12), text_color=FG,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            checkmark_color=BTN_FG,
        ).pack(anchor="w", padx=30, pady=(2, 16))

        # --- Bouton Convertir ---
        self.convert_btn = ctk.CTkButton(
            self, text="CONVERTIR", command=self._start_conversion,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=BTN_FG,
            height=44, corner_radius=8,
        )
        self.convert_btn.pack(pady=(0, 14))

        # --- Barre de progression ---
        self.progress = ctk.CTkProgressBar(
            self, width=500, height=10,
            fg_color=BG_FIELD, progress_color=ACCENT,
        )
        self.progress.pack(padx=30, pady=(0, 8))
        self.progress.set(0)

        # --- Status ---
        self.status_label = ctk.CTkLabel(
            self, text="Pret",
            font=ctk.CTkFont(size=11), text_color=FG_DIM,
        )
        self.status_label.pack()

    def _detect_traktor(self) -> None:
        traktor = _find_traktor4_dir()
        if traktor:
            self.traktor_var.set(str(traktor))
        else:
            self.status_label.configure(text="Traktor 4 non detecte — cliquer 'Changer'")

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

        self.convert_btn.configure(state="disabled", fg_color=FG_DIM)
        self.progress.set(0)

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
            self.status_label.configure(text=message)
            if total > 0:
                self.progress.set(current / total)
        self.after(0, _update)

    def _on_done(self, summary: str) -> None:
        def _update():
            self.progress.set(1.0)
            self.status_label.configure(text="Conversion terminee !")
            self.convert_btn.configure(state="normal", fg_color=ACCENT)
            messagebox.showinfo("Conversion terminee", summary)
        self.after(0, _update)

    def _on_error(self, error: str) -> None:
        def _update():
            self.status_label.configure(text="Erreur")
            self.convert_btn.configure(state="normal", fg_color=ACCENT)
            messagebox.showerror("Erreur", error)
        self.after(0, _update)


def main() -> None:
    """Point d'entree de l'interface graphique."""
    app = ConverterApp()
    app.mainloop()


if __name__ == "__main__":
    main()
