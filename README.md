# FolderFusion

**Merge Folders... Fast.**

FolderFusion takes subfolders from several folders (for example `train`, `valid`, `test` from multiple datasets) and combines them into one clean folder.

## Download

Get the latest version from the [Releases](../../releases) page, unzip it and run `FolderFusion.exe`.

> Windows may show "Windows protected your PC" because the app is not code-signed. Click **More info → Run anyway**.

## Features

- Merge same-named subfolders from many folders into one
- Copy or move files
- Choose what happens on name conflicts: rename, skip or overwrite
- Optional prefix with the source folder name, so files never clash
- Drag and drop folders
- Progress bar, cancel button and automatic rollback
- Dark and light theme

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

## Screenshot

<img width="1917" height="1018" alt="Στιγμιότυπο οθόνης 2026-11-22 015251" src="https://github.com/user-attachments/assets/8ea2ee7c-0583-49e3-b76d-11f6175a8520" />


