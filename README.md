# FolderFusion

**Merge folders in seconds.** FolderFusion takes subfolders from several folders
(for example `train`, `valid`, `test` from multiple datasets) and combines them into one clean folder.

## Features

- Modern dark / light UI (CustomTkinter), rounded cards, live summary
- Add folders one by one or **drag & drop** them into the window
- Pick subfolders per folder, with search/filter and Select all / None
- Same-named subfolders are merged (case-insensitive: `Train` + `train` -> one folder)
- Files are prefixed with their source folder name, so nothing collides and
  image/label pairs stay matched (can be turned off)
- Conflict handling: **Rename** (`file (2).jpg`), **Skip** or **Overwrite**
- **Copy or move**, with a progress bar, current file and a Cancel button (UI never freezes)
- Choose the output location (not just the Desktop); settings are remembered
- Clear error messages, automatic clean-up when a merge fails or is cancelled
- Result summary with an "Open folder" button
- Shortcuts: `Ctrl+O` add folder, `Ctrl+Enter` merge

## Install & run

Requires Python 3.10+.

```bash
pip install -r requirements.txt
python main.py
```

The app icon (`assets/icon.ico`, `assets/icon.png`) is generated automatically.

## Build a Windows .exe

Double-click `build.bat`, or run:

```bash
pip install pyinstaller
python branding.py
python -m PyInstaller --noconfirm --clean --onefile --windowed --name FolderFusion ^
  --icon assets\icon.ico --add-data "assets;assets" ^
  --collect-all customtkinter --collect-all tkinterdnd2 main.py
```

The result is `dist\FolderFusion.exe`.

## Project structure

| File | Purpose |
| --- | --- |
| `main.py` | UI (windows, cards, dialogs) |
| `merge_engine.py` | Merge logic: validation, planning, copy/move, cancel, rollback (no UI code) |
| `theme.py` | Colors, spacing, fonts |
| `branding.py` | Logo, icon and glyph generation (Pillow) |
| `settings.py` | Saved settings (`~/.folderfusion/settings.json`) |

## Screenshots

Add your screenshots to a `screenshots/` folder and reference them here:

```md
![Main window](screenshots/main.png)
```
