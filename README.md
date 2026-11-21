# FolderFusion

**Merge folders in seconds.** FolderFusion takes subfolders from several folders
(for example `train`, `valid`, `test` from multiple datasets) and combines them into one clean folder.

## Shortcuts

- `Ctrl+O` add folder
- `Ctrl+Enter` merge


## Project structure

| File | Purpose |
| --- | --- |
| `main.py` | UI (windows, cards, dialogs) |
| `merge_engine.py` | Merge logic: validation, planning, copy/move, cancel, rollback (no UI code) |
| `theme.py` | Colors, spacing, fonts |
| `branding.py` | Logo, icon and glyph generation (Pillow) |
| `settings.py` | Saved settings (`~/.folderfusion/settings.json`) |

## Screenshots

```md
<img width="1917" height="1018" alt="image" src="https://github.com/user-attachments/assets/39ca1e0f-c187-4c00-b881-6bc5683610fc" />
```
