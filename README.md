# Bazzite Clipboard

Clipboard history for **Bazzite** (KDE Plasma 6 on Wayland). It records text and images you copy, keeps them for 30 days, and restores a selected item to the clipboard.

## Install

From this directory:

```bash
chmod +x install.sh
./install.sh
```

That sets up:

- `~/.local/bin/bazzite-clipboard` (uses system Python, PySide6, Pillow, and `wl-clipboard`)
- autostart on login
- **Ctrl+`** to open the popup at the pointer
- the background daemon

Uninstall (keeps history):

```bash
./install.sh --uninstall
```

Remove history too:

```bash
./install.sh --uninstall --purge
```

## Use

- Copy as usual. Text and images are stored automatically.
- Press **Ctrl+`** for the popup. Search, arrow keys, **Enter** to make that item the current clipboard, **Delete** to remove, **Esc** to close.
- Image rows show a thumbnail; the right pane shows a larger preview.
- Click the tray icon to open history.

## Shortcut troubleshooting

Plasma 6 sometimes ignores shortcut files until they are added in the GUI. If Ctrl+` does not open the popup:

1. System Settings → Keyboard → Shortcuts
2. Add New → Command or Script
3. Command (use the **full path**, not `~`): `/home/crystal/.local/bin/bazzite-clipboard --toggle`
4. Bind **Ctrl+`**

KDE does not expand `~`. If the shortcut shows `/.local/bin/...`, it will fail with “can’t find the program.”

Cursor and VS Code also use Ctrl+` for the terminal. A Plasma global shortcut wins over that binding.

## Logs

`~/.local/state/bazzite-clipboard/clipboard.log`
