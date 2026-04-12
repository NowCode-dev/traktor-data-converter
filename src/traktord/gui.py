"""Interface graphique Traktor Data Converter.

Fenetre simple : selectionner un export Rekordbox, convertir vers Traktor
avec injection automatique des artworks.

Charte graphique NowCode : fond anthracite, accent cyan, texte silver.
Couleurs forcees sur chaque widget pour contourner le dark mode macOS.
"""

from __future__ import annotations

import shutil
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
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
    on_progress,
    on_done,
    on_error,
) -> None:
    """Execute la conversion dans un thread separe."""
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

# Charte NowCode
BG = "#12161D"
BG_FIELD = "#1E2532"
FG = "#D2DEE3"
FG_DIM = "#7A8A94"
ACCENT = "#15E9F2"
ACCENT_DARK = "#3AB2CD"
BTN_FG = "#12161D"
BAR_BG = "#1E2532"


def _load_logo() -> Optional[tk.PhotoImage]:
    """Charger le logo NowCode depuis le package."""
    logo_path = Path(__file__).parent / "logo.png"
    if not logo_path.exists():
        return None
    try:
        return tk.PhotoImage(file=str(logo_path))
    except Exception:
        return None


class ConverterApp:
    """Fenetre principale du convertisseur."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Traktor Data Converter — NowCode")
        self.root.resizable(False, False)
        self.root.configure(bg=BG)

        w, h = 560, 430
        sx = self.root.winfo_screenwidth() // 2 - w // 2
        sy = self.root.winfo_screenheight() // 3 - h // 2
        self.root.geometry(f"{w}x{h}+{sx}+{sy}")

        self._build_ui()
        self._detect_traktor()

    def _build_ui(self) -> None:
        root = self.root

        # --- Logo NowCode ---
        self._logo_img = _load_logo()
        if self._logo_img:
            # Reduire a ~128px de large
            self._logo_small = self._logo_img.subsample(2, 2)
            tk.Label(root, image=self._logo_small, bg=BG).pack(pady=(14, 4))

        # --- Titre ---
        tk.Label(
            root, text="Traktor Data Converter",
            font=("Helvetica", 20, "bold"), fg=ACCENT, bg=BG,
        ).pack(pady=(4, 0))
        tk.Label(
            root, text="Rekordbox  \u2192  Traktor Pro 4",
            font=("Helvetica", 11), fg=FG_DIM, bg=BG,
        ).pack(pady=(0, 14))

        # --- Export Rekordbox ---
        tk.Label(
            root, text="Export Rekordbox (.xml)",
            font=("Helvetica", 12), fg=FG, bg=BG, anchor="w",
        ).pack(fill="x", padx=28)

        row1 = tk.Frame(root, bg=BG)
        row1.pack(fill="x", padx=28, pady=(2, 8))
        self.xml_var = tk.StringVar()
        tk.Entry(
            row1, textvariable=self.xml_var, font=("Helvetica", 11),
            bg=BG_FIELD, fg=FG, insertbackground=FG,
            relief="flat", highlightthickness=1,
            highlightbackground="#2a3040", highlightcolor=ACCENT,
        ).pack(side="left", fill="x", expand=True, ipady=4)
        tk.Button(
            row1, text="Parcourir...", command=self._browse_xml,
            font=("Helvetica", 11), bg="#2a3040", fg=FG,
            activebackground=ACCENT_DARK, activeforeground=BTN_FG,
            relief="flat", padx=10, pady=2, cursor="hand2",
        ).pack(side="right", padx=(8, 0))

        # --- Dossier Traktor ---
        tk.Label(
            root, text="Dossier Traktor 4 (auto-detecte)",
            font=("Helvetica", 12), fg=FG, bg=BG, anchor="w",
        ).pack(fill="x", padx=28)

        row2 = tk.Frame(root, bg=BG)
        row2.pack(fill="x", padx=28, pady=(2, 8))
        self.traktor_var = tk.StringVar()
        tk.Entry(
            row2, textvariable=self.traktor_var, font=("Helvetica", 11),
            bg=BG_FIELD, fg=FG, insertbackground=FG,
            relief="flat", highlightthickness=1,
            highlightbackground="#2a3040", highlightcolor=ACCENT,
        ).pack(side="left", fill="x", expand=True, ipady=4)
        tk.Button(
            row2, text="Changer...", command=self._browse_traktor,
            font=("Helvetica", 11), bg="#2a3040", fg=FG,
            activebackground=ACCENT_DARK, activeforeground=BTN_FG,
            relief="flat", padx=10, pady=2, cursor="hand2",
        ).pack(side="right", padx=(8, 0))

        # --- Checkbox artworks ---
        self.artwork_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            root, text="  Injecter les artworks (pochettes) dans les MP3",
            variable=self.artwork_var, font=("Helvetica", 11),
            fg=FG, bg=BG, selectcolor=BG_FIELD,
            activebackground=BG, activeforeground=FG,
        ).pack(anchor="w", padx=24, pady=(4, 14))

        # --- Bouton Convertir ---
        self.convert_btn = tk.Button(
            root, text="CONVERTIR", command=self._start_conversion,
            font=("Helvetica", 14, "bold"),
            bg=ACCENT, fg=BTN_FG,
            activebackground=ACCENT_DARK, activeforeground=BTN_FG,
            relief="flat", padx=40, pady=8, cursor="hand2",
        )
        self.convert_btn.pack(pady=(0, 12))

        # --- Barre de progression ---
        self.progress_canvas = tk.Canvas(
            root, height=10, bg=BG, highlightthickness=0,
        )
        self.progress_canvas.pack(fill="x", padx=28, pady=(0, 6))

        # --- Status ---
        self.status_var = tk.StringVar(value="Pret")
        tk.Label(
            root, textvariable=self.status_var,
            font=("Helvetica", 10), fg=FG_DIM, bg=BG,
        ).pack()

    def _draw_progress(self, fraction: float) -> None:
        c = self.progress_canvas
        c.delete("all")
        w = c.winfo_width() or 504
        h = 10
        c.create_rectangle(0, 0, w, h, fill=BAR_BG, outline="")
        if fraction > 0:
            c.create_rectangle(0, 0, int(w * fraction), h, fill=ACCENT, outline="")

    def _detect_traktor(self) -> None:
        traktor = _find_traktor4_dir()
        if traktor:
            self.traktor_var.set(str(traktor))
        else:
            self.status_var.set("Traktor 4 non detecte — cliquer 'Changer'")

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

        self.convert_btn.configure(state="disabled", bg=FG_DIM)
        self._draw_progress(0)

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
                self._draw_progress(current / total)
        self.root.after(0, _update)

    def _on_done(self, summary: str) -> None:
        def _update():
            self._draw_progress(1.0)
            self.status_var.set("Conversion terminee !")
            self.convert_btn.configure(state="normal", bg=ACCENT)
            messagebox.showinfo("Conversion terminee", summary)
        self.root.after(0, _update)

    def _on_error(self, error: str) -> None:
        def _update():
            self.status_var.set("Erreur")
            self.convert_btn.configure(state="normal", bg=ACCENT)
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
