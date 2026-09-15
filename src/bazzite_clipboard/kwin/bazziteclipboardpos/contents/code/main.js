function isClipboardPopup(w) {
    if (!w) {
        return false;
    }
    const caption = (w.caption || "").toString();
    const cls = (w.resourceClass || "").toString().toLowerCase();
    const name = (w.resourceName || "").toString().toLowerCase();
    return caption === "Bazzite Clipboard"
        || cls.indexOf("bazzite-clipboard") !== -1
        || name.indexOf("bazzite-clipboard") !== -1;
}

function placeAtCursor(w) {
    if (!isClipboardPopup(w)) {
        return;
    }
    try {
        w.skipTaskbar = true;
        w.keepAbove = true;
    } catch (e) {}
    const pos = workspace.cursorPos;
    const g = w.frameGeometry;
    let x = pos.x;
    let y = pos.y + 12;
    let area = null;
    try {
        area = workspace.clientArea(KWin.WorkArea, w);
    } catch (e) {
        try {
            area = workspace.clientArea(KWin.PlacementArea, w);
        } catch (e2) {
            area = null;
        }
    }
    if (area) {
        if (x + g.width > area.x + area.width) {
            x = area.x + area.width - g.width;
        }
        if (y + g.height > area.y + area.height) {
            y = area.y + area.height - g.height;
        }
        if (x < area.x) {
            x = area.x;
        }
        if (y < area.y) {
            y = area.y;
        }
    }
    w.frameGeometry = {
        x: Math.round(x),
        y: Math.round(y),
        width: g.width,
        height: g.height
    };
}

workspace.windowAdded.connect(placeAtCursor);
try {
    workspace.windowList().forEach(placeAtCursor);
} catch (e) {}
