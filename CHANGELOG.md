# Changelog — Traktor Data Converter

> Historique des sessions de travail

---

## [2026-03-30] — Diagnostic du problème d'artworks

### Modifications
- Aucune modification de code (session d'analyse uniquement)

### Decisions
- Identification du problème : les pochettes/artworks ne s'affichent pas après conversion Rekordbox → Traktor
- Cause identifiée : le modèle `Track` n'a pas de champ artwork, le parser Rekordbox ignore `ArtworkPath`, le writer Traktor n'écrit rien pour l'artwork

### A faire
- Ajouter un champ `artwork_path: str = ""` au modèle `Track`
- Parser l'attribut `ArtworkPath` dans le parser Rekordbox
- Gérer l'artwork dans le writer Traktor (référence ou intégration ID3)
- Clarifier avec Lorys : artwork intégré dans les tags ID3 ou images séparées ?
