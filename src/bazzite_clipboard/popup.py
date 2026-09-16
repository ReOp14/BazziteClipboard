from __future__ import annotations

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QPropertyAnimation,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QKeyEvent, QPixmap, QShowEvent, QWheelEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizeGrip,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import WINDOW_TITLE
from .effects import enable_plasma_backdrop
from .position import place_popup_at_cursor
from .settings import (
    MAX_OPACITY,
    MAX_WINDOW_HEIGHT,
    MAX_WINDOW_WIDTH,
    MIN_OPACITY,
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
    DEFAULT_ITEM_SPACING,
    MAX_ITEM_SPACING,
    MIN_ITEM_SPACING,
    Settings,
    format_bytes,
)
from .store import ClipItem, ClipboardStore
from .watcher import is_image_url

POPUP_WIDTH = 520
POPUP_HEIGHT = 560
TEXT_ROW_HEIGHT = 36
IMAGE_PREVIEW_HEIGHT = 128
INITIAL_LOAD_LIMIT = 150


class SmoothListWidget(QListWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._anim = QPropertyAnimation(self.verticalScrollBar(), b"value", self)
        self._anim.setDuration(240)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        delta = event.angleDelta().y()
        if delta == 0:
            delta = event.pixelDelta().y()
        if delta == 0:
            return
        bar = self.verticalScrollBar()
        running = self._anim.state() == QAbstractAnimation.State.Running
        current = int(self._anim.endValue()) if running and self._anim.endValue() is not None else bar.value()
        step = int(-delta * 0.85)
        target = max(bar.minimum(), min(bar.maximum(), current + step))
        self._anim.stop()
        self._anim.setStartValue(bar.value())
        self._anim.setEndValue(target)
        self._anim.start()
        event.accept()


class ElidedLabel(QLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = text
        self.setWordWrap(False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def setFullText(self, text: str) -> None:
        self._full = text
        self._elide()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        width = max(40, self.width())
        self.setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, width))
        self.setToolTip(self._full if self._full else None)


class ActionButton(QPushButton):
    def __init__(self, label: str, tooltip: str, parent: QWidget | None = None) -> None:
        super().__init__(label, parent)
        self.setObjectName("RowAction")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(30, 30)
        self.setToolTip(tooltip)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)


class ClipRow(QFrame):
    useClicked = Signal()
    deleteClicked = Signal()

    def __init__(self, item: ClipItem, preview: QPixmap | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ClipRow")
        self.item = item
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 3, 8, 3)
        root.setSpacing(4)

        self.actions = QWidget()
        self.actions.setObjectName("RowActions")
        action_layout = QHBoxLayout(self.actions)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(4)
        use_btn = ActionButton("▸", "Use (Enter)")
        use_btn.clicked.connect(self.useClicked.emit)
        delete_btn = ActionButton("✕", "Delete")
        delete_btn.clicked.connect(self.deleteClicked.emit)
        action_layout.addWidget(use_btn)
        action_layout.addWidget(delete_btn)
        self.actions.hide()

        if item.kind == "image":
            image_wrap = QFrame()
            image_wrap.setObjectName("ImageWrap")
            grid = QGridLayout(image_wrap)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(0)
            image = QLabel()
            image.setObjectName("RowImage")
            image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if preview is not None and not preview.isNull():
                image.setPixmap(preview)
                image.setMinimumHeight(preview.height())
            else:
                image.setText("Image")
                image.setFixedHeight(IMAGE_PREVIEW_HEIGHT)
            grid.addWidget(image, 0, 0)
            self.actions.setParent(image_wrap)
            grid.addWidget(self.actions, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
            root.addWidget(image_wrap)
            self.setMinimumHeight((preview.height() if preview is not None and not preview.isNull() else IMAGE_PREVIEW_HEIGHT) + 6)
        else:
            top = QHBoxLayout()
            top.setContentsMargins(4, 0, 0, 0)
            top.setSpacing(8)
            title = ElidedLabel(_row_title(item))
            title.setObjectName("RowTitle")
            title.setFullText(_row_title(item))
            top.addWidget(title, 1)
            top.addWidget(self.actions, 0, Qt.AlignmentFlag.AlignRight)
            root.addLayout(top)
            self.setFixedHeight(TEXT_ROW_HEIGHT)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.actions.setVisible(selected)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


class ClipboardPopup(QWidget):
    restoreRequested = Signal(int)
    deleteRequested = Signal(int)

    def __init__(
        self,
        store: ClipboardStore,
        settings: Settings | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._settings = settings or Settings.load()
        self._items: dict[int, ClipItem] = {}
        self._close_on_deactivate = False
        self._pixmap_cache: dict[str, QPixmap] = {}
        self._effects_applied = False
        self._reveal = None
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(250)
        self._save_timer.timeout.connect(self._persist_settings)
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(140)
        self._resize_timer.timeout.connect(self._on_resize_settled)
        self._updating_size = False

        self.setWindowTitle(WINDOW_TITLE)
        self.setObjectName("ClipboardPopup")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
        self.resize(self._settings.window_width, self._settings.window_height)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setWindowOpacity(0.0)

        self._shell = QFrame(self)
        self._shell.setObjectName("PopupShell")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._shell)

        layout = QVBoxLayout(self._shell)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_history_page())
        self.pages.addWidget(self._build_settings_page())
        layout.addWidget(self.pages, 1)
        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 0, 0)
        grip_row.addStretch(1)
        grip_row.addWidget(QSizeGrip(self))
        layout.addLayout(grip_row)

        self._apply_base_style()
        self._apply_panel_opacity(self._settings.panel_opacity)

    def _build_history_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        search_wrap = QFrame()
        search_wrap.setObjectName("SearchWrap")
        search_wrap.setFixedHeight(28)
        search_row = QHBoxLayout(search_wrap)
        search_row.setContentsMargins(10, 0, 4, 0)
        search_row.setSpacing(6)
        search_icon = QLabel("⌕")
        search_icon.setObjectName("SearchIcon")
        search_row.addWidget(search_icon)
        self.search = QLineEdit()
        self.search.setObjectName("SearchField")
        self.search.setPlaceholderText("Search...")
        self.search.setFrame(False)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.reload)
        self.search.installEventFilter(self)
        search_row.addWidget(self.search, 1)
        settings_btn = QPushButton("⚙")
        settings_btn.setObjectName("TabButton")
        settings_btn.setFixedSize(24, 24)
        settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_btn.setToolTip("Settings")
        settings_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        settings_btn.clicked.connect(self._show_settings)
        search_row.addWidget(settings_btn)
        layout.addWidget(search_wrap)

        self.list = SmoothListWidget()
        self.list.setObjectName("ClipList")
        self.list.setSpacing(self._settings.item_spacing)
        self.list.setUniformItemSizes(False)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.list.currentItemChanged.connect(self._on_current_changed)
        self.list.itemActivated.connect(self._activate_item)
        self.list.installEventFilter(self)
        layout.addWidget(self.list, 1)

        self.empty = QLabel("Copy something and it will show up here.")
        self.empty.setObjectName("EmptyLabel")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.hide()
        layout.addWidget(self.empty, 1)
        return page

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 0, 4, 4)
        layout.setSpacing(12)

        header = QHBoxLayout()
        back = QPushButton("←")
        back.setObjectName("TabButton")
        back.setFixedSize(32, 32)
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.setToolTip("Back to history")
        back.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        back.clicked.connect(self._show_history)
        header.addWidget(back)
        title = QLabel("Settings")
        title.setObjectName("SettingsTitle")
        header.addWidget(title)
        header.addStretch(1)
        layout.addLayout(header)

        layout.addWidget(_settings_label("Panel opacity"))
        opacity_row = QHBoxLayout()
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(int(MIN_OPACITY * 100), int(MAX_OPACITY * 100))
        self.opacity_slider.setValue(int(self._settings.panel_opacity * 100))
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        opacity_row.addWidget(self.opacity_slider, 1)
        self.opacity_value = QLabel(f"{int(self._settings.panel_opacity * 100)}%")
        self.opacity_value.setObjectName("SettingsValue")
        self.opacity_value.setFixedWidth(44)
        opacity_row.addWidget(self.opacity_value)
        layout.addLayout(opacity_row)
        hint = QLabel("Lower is more see-through. Default is 88%.")
        hint.setObjectName("SettingsHint")
        layout.addWidget(hint)

        layout.addWidget(_settings_label("Item spacing"))
        spacing_row = QHBoxLayout()
        self.spacing_slider = QSlider(Qt.Orientation.Horizontal)
        self.spacing_slider.setRange(MIN_ITEM_SPACING, MAX_ITEM_SPACING)
        self.spacing_slider.setValue(self._settings.item_spacing)
        self.spacing_slider.valueChanged.connect(self._on_spacing_changed)
        spacing_row.addWidget(self.spacing_slider, 1)
        self.spacing_value = QLabel(f"{self._settings.item_spacing} px")
        self.spacing_value.setObjectName("SettingsValue")
        self.spacing_value.setFixedWidth(44)
        spacing_row.addWidget(self.spacing_value)
        layout.addLayout(spacing_row)
        spacing_hint = QLabel("Gap between clipboard entries. Default is 2.")
        spacing_hint.setObjectName("SettingsHint")
        layout.addWidget(spacing_hint)

        layout.addWidget(_settings_label("Keep at most"))
        entries_row = QHBoxLayout()
        self.entries_spin = QSpinBox()
        self.entries_spin.setRange(0, 50_000)
        self.entries_spin.setSingleStep(50)
        self.entries_spin.setSpecialValueText("Unlimited")
        self.entries_spin.setValue(self._settings.max_entries)
        self.entries_spin.valueChanged.connect(self._on_entries_changed)
        entries_row.addWidget(self.entries_spin)
        entries_suffix = QLabel("entries")
        entries_suffix.setObjectName("SettingsHint")
        entries_row.addWidget(entries_suffix)
        entries_row.addStretch(1)
        layout.addLayout(entries_row)

        layout.addWidget(_settings_label("Keep for"))
        days_row = QHBoxLayout()
        self.days_spin = QSpinBox()
        self.days_spin.setRange(1, 3650)
        self.days_spin.setValue(self._settings.retention_days)
        self.days_spin.valueChanged.connect(self._on_days_changed)
        days_row.addWidget(self.days_spin)
        days_suffix = QLabel("days")
        days_suffix.setObjectName("SettingsHint")
        days_row.addWidget(days_suffix)
        days_row.addStretch(1)
        layout.addLayout(days_row)

        layout.addWidget(_settings_label("Window size"))
        size_row = QHBoxLayout()
        self.width_spin = QSpinBox()
        self.width_spin.setRange(MIN_WINDOW_WIDTH, MAX_WINDOW_WIDTH)
        self.width_spin.setSingleStep(20)
        self.width_spin.setValue(self._settings.window_width)
        self.width_spin.valueChanged.connect(self._on_window_size_changed)
        size_row.addWidget(self.width_spin)
        width_suffix = QLabel("W")
        width_suffix.setObjectName("SettingsHint")
        size_row.addWidget(width_suffix)
        self.height_spin = QSpinBox()
        self.height_spin.setRange(MIN_WINDOW_HEIGHT, MAX_WINDOW_HEIGHT)
        self.height_spin.setSingleStep(20)
        self.height_spin.setValue(self._settings.window_height)
        self.height_spin.valueChanged.connect(self._on_window_size_changed)
        size_row.addWidget(self.height_spin)
        height_suffix = QLabel("H")
        height_suffix.setObjectName("SettingsHint")
        size_row.addWidget(height_suffix)
        size_row.addStretch(1)
        layout.addLayout(size_row)
        size_hint = QLabel("Drag the corner to resize, or set width and height here.")
        size_hint.setObjectName("SettingsHint")
        size_hint.setWordWrap(True)
        layout.addWidget(size_hint)

        layout.addWidget(_settings_label("Storage used"))
        self.storage_label = QLabel()
        self.storage_label.setObjectName("StorageLabel")
        self.storage_label.setWordWrap(True)
        layout.addWidget(self.storage_label)
        layout.addStretch(1)
        return page

    def _apply_base_style(self) -> None:
        self.setStyleSheet(
            """
            QWidget#ClipboardPopup {
                background: transparent;
            }
            #PopupShell {
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 12px;
            }
            #SearchWrap {
                background-color: rgba(255, 255, 255, 0.06);
                border: 1px solid rgba(255, 255, 255, 0.06);
                border-radius: 8px;
                min-height: 28px;
                max-height: 28px;
            }
            #SearchIcon {
                color: rgba(255, 255, 255, 0.45);
                font-size: 13px;
            }
            #SearchField {
                background: transparent;
                color: rgba(255, 255, 255, 0.94);
                border: none;
                padding: 2px 4px;
                min-height: 22px;
                max-height: 22px;
                selection-background-color: rgba(61, 174, 233, 0.45);
            }
            #ClipList {
                background: transparent;
                border: none;
                outline: none;
                padding: 2px 0;
            }
            #ClipList::item {
                background: transparent;
                border: none;
                border-radius: 8px;
                padding: 0;
                margin: 1px 0;
            }
            #ClipList::item:selected {
                background: transparent;
            }
            #ClipList QScrollBar:vertical {
                background: transparent;
                width: 8px;
                margin: 4px 0;
            }
            #ClipList QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.18);
                border-radius: 4px;
                min-height: 24px;
            }
            #ClipList QScrollBar::add-line:vertical,
            #ClipList QScrollBar::sub-line:vertical {
                height: 0;
            }
            QLineEdit {
                background: transparent;
                color: rgba(255, 255, 255, 0.94);
                border: none;
                padding: 8px 4px;
                selection-background-color: rgba(61, 174, 233, 0.45);
            }
            QSpinBox {
                background: rgba(255, 255, 255, 0.08);
                color: rgba(255, 255, 255, 0.94);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
                padding: 6px 10px;
                min-width: 110px;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: rgba(255, 255, 255, 0.12);
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                width: 16px;
                height: 16px;
                margin: -6px 0;
                background: #3daee9;
                border-radius: 8px;
            }
            #ClipRow {
                background: transparent;
                border-radius: 8px;
            }
            #ClipRow[selected="true"] {
                background-color: rgba(255, 255, 255, 0.09);
            }
            #RowTitle, #SettingsTitle, #StorageLabel {
                color: rgba(255, 255, 255, 0.92);
                font-size: 13px;
            }
            #SettingsTitle {
                font-weight: 600;
                font-size: 15px;
            }
            #RowImage, #ImageWrap {
                background: rgba(0, 0, 0, 0.22);
                border-radius: 8px;
            }
            #RowAction, #TabButton {
                background: rgba(20, 20, 24, 0.72);
                color: rgba(255, 255, 255, 0.9);
                border: none;
                border-radius: 8px;
                font-size: 13px;
            }
            #RowAction:hover, #TabButton:hover {
                background: rgba(255, 255, 255, 0.16);
            }
            #EmptyLabel, #SettingsHint, #SettingsValue {
                color: rgba(255, 255, 255, 0.45);
            }
            #EmptyLabel {
                padding: 24px;
            }
            #SettingsLabel {
                color: rgba(255, 255, 255, 0.78);
                font-weight: 600;
                padding-top: 4px;
            }
            """
        )

    def _apply_panel_opacity(self, opacity: float) -> None:
        alpha = int(max(MIN_OPACITY, min(MAX_OPACITY, opacity)) * 255)
        self._shell.setStyleSheet(
            f"#PopupShell {{ background-color: rgba(20, 20, 24, {alpha}); }}"
        )

    def _show_settings(self) -> None:
        self._refresh_storage()
        self.pages.setCurrentIndex(1)

    def _show_history(self) -> None:
        self.pages.setCurrentIndex(0)
        self.search.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def _on_opacity_changed(self, value: int) -> None:
        opacity = value / 100.0
        self._settings.panel_opacity = opacity
        self.opacity_value.setText(f"{value}%")
        self._apply_panel_opacity(opacity)
        self._save_timer.start()

    def _on_spacing_changed(self, value: int) -> None:
        self._settings.item_spacing = value
        self.spacing_value.setText(f"{value} px")
        self.list.setSpacing(value)
        self._save_timer.start()

    def _on_entries_changed(self, value: int) -> None:
        self._settings.max_entries = value
        self._save_timer.start()

    def _on_days_changed(self, value: int) -> None:
        self._settings.retention_days = value
        self._save_timer.start()

    def _on_window_size_changed(self, _value: int) -> None:
        width = self.width_spin.value()
        height = self.height_spin.value()
        self._settings.window_width = width
        self._settings.window_height = height
        self._updating_size = True
        self.resize(width, height)
        self._updating_size = False
        self._save_timer.start()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._updating_size:
            return
        self._settings.window_width = self.width()
        self._settings.window_height = self.height()
        if hasattr(self, "width_spin"):
            self.width_spin.blockSignals(True)
            self.height_spin.blockSignals(True)
            self.width_spin.setValue(self.width())
            self.height_spin.setValue(self.height())
            self.width_spin.blockSignals(False)
            self.height_spin.blockSignals(False)
        self._save_timer.start()
        self._resize_timer.start()

    def _on_resize_settled(self) -> None:
        self._pixmap_cache.clear()
        if self.pages.currentIndex() == 0:
            self.reload()

    def _persist_settings(self) -> None:
        self._settings.save()
        self._store.prune()
        if self.pages.currentIndex() == 1:
            self._refresh_storage()

    def _refresh_storage(self) -> None:
        used = format_bytes(self._store.storage_bytes())
        count = self._store.count()
        noun = "item" if count == 1 else "items"
        self.storage_label.setText(f"{used}  ·  {count} {noun}")

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._effects_applied:
            enable_plasma_backdrop(self)
            self._effects_applied = True

    def show_popup(self) -> None:
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.pages.setCurrentIndex(0)
        self.reload(limit=INITIAL_LOAD_LIMIT)
        self._close_on_deactivate = False
        self.setWindowOpacity(0.0)
        self.show()
        QTimer.singleShot(0, self._place_then_reveal)

    def hide_popup(self) -> None:
        self._close_on_deactivate = False
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._persist_settings()
        self.setWindowOpacity(0.0)
        self.hide()

    def toggle_popup(self) -> None:
        if self.isVisible() and self.windowOpacity() > 0.05:
            self.hide_popup()
        else:
            self.show_popup()

    def reload(self, limit: int | None = None) -> None:
        query = self.search.text()
        items = [
            item
            for item in self._store.list_items(query, limit=limit)
            if item.kind == "image" or not is_image_url(item.text_content or "")
        ]
        current_id = self._current_id()
        self.list.clear()
        self.list.setSpacing(self._settings.item_spacing)
        self._items = {item.id: item for item in items}

        if not items:
            self.list.hide()
            self.empty.setText(
                "No clipboard items match that search." if query else "Copy something and it will show up here."
            )
            self.empty.show()
            return

        self.empty.hide()
        self.list.show()
        for item in items:
            row = QListWidgetItem()
            row.setData(Qt.ItemDataRole.UserRole, item.id)
            preview = self._preview_pixmap(item) if item.kind == "image" else None
            widget = ClipRow(item, preview)
            widget.useClicked.connect(self._restore_current)
            widget.deleteClicked.connect(self._delete_current)
            row.setSizeHint(widget.sizeHint() if widget.sizeHint().height() > 20 else QSize(POPUP_WIDTH, widget.minimumHeight() or TEXT_ROW_HEIGHT))
            if item.kind == "image":
                row.setSizeHint(QSize(self.width() - 24, widget.minimumHeight()))
            else:
                row.setSizeHint(QSize(self.width() - 24, TEXT_ROW_HEIGHT))
            self.list.addItem(row)
            self.list.setItemWidget(row, widget)

        match_row = 0
        if current_id is not None:
            for i in range(self.list.count()):
                if self.list.item(i).data(Qt.ItemDataRole.UserRole) == current_id:
                    match_row = i
                    break
        self.list.setCurrentRow(match_row)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        if (
            event.type() == QEvent.Type.ActivationChange
            and self._close_on_deactivate
            and not self.isActiveWindow()
        ):
            self.hide_popup()
        super().changeEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            if self.pages.currentIndex() == 1:
                self._show_history()
                return
            self.hide_popup()
            return
        if event.key() == Qt.Key.Key_Delete:
            if self.pages.currentIndex() == 0:
                self._delete_current()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.pages.currentIndex() == 0:
                self._restore_current()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if watched is self.search:
                if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                    self.list.setFocus()
                    if self.list.count() and self.list.currentRow() < 0:
                        self.list.setCurrentRow(0)
                    return False
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._restore_current()
                    return True
                if key == Qt.Key.Key_Escape:
                    self.hide_popup()
                    return True
            if watched is self.list:
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._restore_current()
                    return True
                if key == Qt.Key.Key_Delete:
                    self._delete_current()
                    return True
                if key == Qt.Key.Key_Escape:
                    self.hide_popup()
                    return True
        return super().eventFilter(watched, event)

    def _place_then_reveal(self) -> None:
        place_popup_at_cursor()
        QTimer.singleShot(25, self._reveal_window)

    def _reveal_window(self) -> None:
        enable_plasma_backdrop(self)
        self.raise_()
        self.activateWindow()
        self.search.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(55)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        self._reveal = anim
        QTimer.singleShot(100, self._enable_deactivate_close)

    def _enable_deactivate_close(self) -> None:
        self._close_on_deactivate = True

    def _preview_pixmap(self, item: ClipItem) -> QPixmap:
        width = max(200, self.list.viewport().width() - 16 or self.width() - 48)
        cache_key = f"{item.content_hash}:{width}"
        cached = self._pixmap_cache.get(cache_key)
        if cached is not None:
            return cached
        pix = QPixmap()
        blob = item.blob_path
        thumb = item.thumb_path
        if blob is not None and blob.exists():
            pix.load(str(blob))
        elif thumb is not None and thumb.exists():
            pix.load(str(thumb))
        if not pix.isNull():
            pix = pix.scaled(
                width,
                IMAGE_PREVIEW_HEIGHT,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._pixmap_cache[cache_key] = pix
        return pix

    def _current_id(self) -> int | None:
        item = self.list.currentItem()
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return int(value) if value is not None else None

    def _current_clip(self) -> ClipItem | None:
        item_id = self._current_id()
        if item_id is None:
            return None
        return self._items.get(item_id) or self._store.get(item_id)

    def _on_current_changed(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        for i in range(self.list.count()):
            widget = self.list.itemWidget(self.list.item(i))
            if isinstance(widget, ClipRow):
                widget.set_selected(self.list.item(i) is current)

    def _activate_item(self, _item: QListWidgetItem | None = None) -> None:
        self._restore_current()

    def _restore_current(self) -> None:
        clip = self._current_clip()
        if clip is None:
            return
        self.restoreRequested.emit(clip.id)

    def _delete_current(self) -> None:
        clip = self._current_clip()
        if clip is None:
            return
        row = self.list.currentRow()
        self.deleteRequested.emit(clip.id)
        if 0 <= row < self.list.count():
            self.list.setCurrentRow(min(row, self.list.count() - 1))


def _row_title(item: ClipItem) -> str:
    if item.kind == "image":
        return item.text_preview or "Image"
    preview = item.text_preview or (item.text_content or "").strip() or "(empty)"
    return " ".join(preview.split())


def _settings_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("SettingsLabel")
    return label
