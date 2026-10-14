#!/usr/bin/env python3
"""GenBrowser: local, cross-platform thumbnail and metadata viewer."""
from __future__ import annotations

import json
import sys
import shutil
from send2trash import send2trash
from pathlib import Path

from PIL import Image, ImageOps
from PySide6.QtCore import Qt, QItemSelectionModel, QSize, QThreadPool, QRunnable, QObject, Signal, QSettings
from PySide6.QtGui import QAction, QIcon, QImage, QPixmap, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
    QListWidgetItem, QLabel, QPushButton, QSlider, QSplitter, QFileDialog,
    QPlainTextEdit, QScrollArea, QFrame, QStackedWidget, QToolBar,
    QMessageBox, QLineEdit, QStatusBar, QMenu, QAbstractItemView, QToolButton
)

EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif', '.tif', '.tiff', '.avif'}
APP_NAME = 'GenBrowser'


def images_in(folder: Path) -> list[Path]:
    try:
        return sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONS), key=lambda p: p.name.casefold())
    except OSError:
        return []


def normalize_json(value):
    if isinstance(value, str):
        value = value.strip()
        if value and value[:1] in '[{':
            try:
                return json.loads(value)
            except (ValueError, TypeError):
                pass
    return value


def format_metadata(value, prefix='') -> list[str]:
    """Readable key/value output, including nested dicts/lists."""
    if isinstance(value, dict):
        output = []
        for key, val in value.items():
            name = f'{prefix}.{key}' if prefix else str(key)
            output.extend(format_metadata(val, name))
        return output
    if isinstance(value, list):
        output = []
        for i, val in enumerate(value, 1):
            output.extend(format_metadata(val, f'{prefix}[{i}]'))
        return output or [f'{prefix}: (empty)']
    return [f'{prefix}: {value if value is not None else ""}']


def format_models(value) -> list[str]:
    if not isinstance(value, list):
        return format_metadata(value)
    output = []
    for i, model in enumerate(value, 1):
        if not isinstance(model, dict):
            output.append(f'Model {i}: {model}')
            continue
        output.append(f'Model {i}: {model.get("name", "(unnamed)")}')
        for key, val in model.items():
            if key != 'name':
                output.extend(format_metadata(val, f'  {key}'))
        if i < len(value):
            output.append('')
    return output


def metadata_for(path: Path) -> tuple[str, str]:
    """Return formatted human-readable parameters and raw metadata, safely."""
    try:
        with Image.open(path) as im:
            raw = {}
            for key, value in im.info.items():
                if isinstance(value, bytes):
                    value = f'<binary: {len(value)} bytes>'
                elif isinstance(value, (dict, list)):
                    pass
                elif not isinstance(value, (str, int, float, bool, type(None))):
                    value = str(value)
                raw[str(key)] = normalize_json(value)
            try:
                exif = im.getexif()
                if exif:
                    raw['EXIF'] = {str(k): str(v) for k, v in exif.items()}
            except Exception:
                pass
            dims = f'{im.width} × {im.height} | {im.format or path.suffix[1:].upper()}'
    except Exception as exc:
        return f'Unable to read metadata: {exc}', ''

    lines = [f'File: {path.name}', f'Dimensions: {dims}', f'Size: {path.stat().st_size / (1024 * 1024):.2f} MiB', '']
    # SwarmUI typically stores JSON in a PNG text chunk called parameters.
    swarm = raw.get('parameters')
    if isinstance(swarm, dict):
        # SwarmUI sometimes uses a direct generation parameters dict, sometimes nests it.
        params = swarm.get('sui_image_params', swarm)
        extras = swarm.get('sui_extra_data')
        models = swarm.get('sui_models')
        lines.append('SWARMUI GENERATION PARAMETERS')
        for name, val in (params.items() if isinstance(params, dict) else [('parameters', params)]):
            lines.append(f'{name}: {json.dumps(val, ensure_ascii=False) if isinstance(val, (dict, list)) else val}')
        if extras is not None:
            lines.extend(['', 'EXTRA DATA'])
            lines.extend(format_metadata(extras))
        if models is not None:
            lines.extend(['', 'MODELS'])
            lines.extend(format_models(models))
    elif isinstance(swarm, str) and swarm:
        lines.extend(['GENERATION PARAMETERS', swarm])
    else:
        # Some pipelines write dedicated SwarmUI keys rather than embedding them.
        sui = {k: v for k, v in raw.items() if k.startswith('sui_')}
        if sui:
            lines.append('SWARMUI METADATA')
            lines.extend(format_metadata(sui))
        if 'prompt' in raw:
            lines.extend(['', 'COMFYUI PROMPT / WORKFLOW', json.dumps(raw['prompt'], indent=2, ensure_ascii=False)])
        if 'workflow' in raw:
            lines.extend(['', 'COMFYUI WORKFLOW', json.dumps(raw['workflow'], indent=2, ensure_ascii=False)])
        if not sui and 'prompt' not in raw and 'workflow' not in raw:
            lines.append('No recognized AI generation parameters found.')
    raw_text = json.dumps(raw, ensure_ascii=False, indent=2, default=str)
    return '\n'.join(lines), raw_text


def pil_to_qimage(im: Image.Image) -> QImage:
    im = ImageOps.exif_transpose(im).convert('RGBA')
    data = im.tobytes('raw', 'RGBA')
    return QImage(data, im.width, im.height, im.width * 4, QImage.Format.Format_RGBA8888).copy()


class WorkerSignals(QObject):
    ready = Signal(str, int, object)


class ThumbnailJob(QRunnable):
    def __init__(self, path: Path, size: int, generation: int):
        super().__init__()
        self.path, self.size, self.generation = path, size, generation
        self.signals = WorkerSignals()

    def run(self):
        try:
            with Image.open(self.path) as im:
                im.thumbnail((self.size, self.size), Image.Resampling.LANCZOS)
                image = pil_to_qimage(im)
        except Exception:
            image = QImage()
        self.signals.ready.emit(str(self.path), self.generation, image)


class ImageView(QScrollArea):
    clicked = Signal()
    wheel_step = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(False)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWidget(self.label)
        self.original = QPixmap()
        self.zoom = 1.0
        self.auto_fit = True
        self.enlarge_to_fit = False
        self.label.installEventFilter(self)
        self.setStyleSheet('QScrollArea {background:#1d1d1d;} QLabel {background:#1d1d1d;}')

    def eventFilter(self, source, event):
        if source is getattr(self, 'label', None):
            if event.type() == event.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                self.clicked.emit()
                return True
        return super().eventFilter(source, event)

    def set_image(self, path: Path | None):
        self.original = QPixmap(str(path)) if path else QPixmap()
        # Qt may not decode every Pillow-supported format. Fall back to Pillow.
        if self.original.isNull() and path:
            try:
                with Image.open(path) as im:
                    self.original = QPixmap.fromImage(pil_to_qimage(im))
            except Exception:
                pass
        self.auto_fit = True
        self.refresh()

    def refresh(self):
        if self.original.isNull():
            self.label.setPixmap(QPixmap())
            self.label.setText('Image could not be loaded')
            self.label.adjustSize()
            return
        self.label.setText('')
        if self.auto_fit:
            available = self.viewport().size()
            factor = min(available.width() / max(self.original.width(), 1), available.height() / max(self.original.height(), 1), float("inf") if self.enlarge_to_fit else 1.0)
            self.zoom = max(.01, factor)
        target = self.original.size() * self.zoom
        self.label.setPixmap(self.original.scaled(target, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.label.adjustSize()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.auto_fit:
            self.refresh()

    def wheelEvent(self, event):
        steps = event.angleDelta().y()
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if self.original.isNull():
                return
            self.auto_fit = False
            self.zoom = min(12, max(.02, self.zoom * (1.15 if steps > 0 else 1 / 1.15)))
            self.refresh()
        else:
            self.wheel_step.emit(-1 if steps > 0 else 1)
        event.accept()

    def fit(self):
        self.auto_fit = True
        self.refresh()


class ThumbnailList(QListWidget):
    """Thumbnail selection with stable file-manager-style modifier semantics."""
    selection_clicked = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selection_anchor_row = None
        self._pressed_row = None
        self._selection_before_press = set()
        self._press_modifiers = Qt.KeyboardModifier.NoModifier

    def mousePressEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        self._pressed_row = self.row(item) if item is not None else None
        self._selection_before_press = {self.row(x) for x in self.selectedItems()}
        self._press_modifiers = event.modifiers()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        item = self.itemAt(event.position().toPoint())
        row = self.row(item) if item is not None else None
        if (event.button() != Qt.MouseButton.LeftButton or row is None
                or row != self._pressed_row):
            return

        shift = bool(self._press_modifiers & Qt.KeyboardModifier.ShiftModifier)
        ctrl = bool(self._press_modifiers & Qt.KeyboardModifier.ControlModifier)
        if shift:
            anchor = self.selection_anchor_row
            if anchor is None:
                anchor = row
            wanted = set(range(min(anchor, row), max(anchor, row) + 1))
            # Ctrl+Shift extends a selection rather than replacing it.
            if ctrl:
                wanted.update(self._selection_before_press)
        elif ctrl:
            wanted = set(self._selection_before_press)
            if row in wanted:
                wanted.remove(row)
            else:
                wanted.add(row)
            self.selection_anchor_row = row
        else:
            wanted = {row}
            self.selection_anchor_row = row

        self.blockSignals(True)
        try:
            for i in range(self.count()):
                self.item(i).setSelected(i in wanted)
            self.setCurrentRow(row, QItemSelectionModel.SelectionFlag.NoUpdate)
        finally:
            self.blockSignals(False)
        self.selection_clicked.emit(item)

class MainWindow(QMainWindow):
    def __init__(self, initial: Path | None = None):
        super().__init__()
        self.settings = QSettings('LocalAI', APP_NAME)
        self.folder = Path.home()
        self.paths: list[Path] = []
        self.index = -1
        self.mode = 'grid'  # grid, detail, image
        self.generation = 0
        self.pool = QThreadPool.globalInstance()
        self.pool.setMaxThreadCount(4)
        self.jobs = []
        self.confirm_on_delete = self.settings.value('confirm_on_delete', True, type=bool)
        self.enlarge_to_fit = self.settings.value('enlarge_to_fit', False, type=bool)
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 840)
        self.build_ui()
        saved_size = self.settings.value('thumbnail_size', 150, type=int)
        self.size_slider.setValue(max(80, min(300, saved_size)))
        if initial and initial.is_file():
            self.open_folder(initial.parent, select=initial, view='image')
        elif initial and initial.is_dir():
            self.open_folder(initial, view='grid')
        else:
            prior = Path(self.settings.value('last_folder', str(Path.home())))
            self.open_folder(prior if prior.is_dir() else Path.home(), view='grid')

    def build_ui(self):
        self.toolbar = QToolBar('Navigation')
        self.toolbar.setMovable(False)
        self.addToolBar(self.toolbar)
        a = QAction('Open folder', self)
        a.setShortcut(QKeySequence.StandardKey.Open)
        a.triggered.connect(self.choose_folder)
        self.toolbar.addAction(a)
        a = QAction('Thumbnails', self)
        a.triggered.connect(lambda: self.set_mode('grid'))
        self.toolbar.addAction(a)
        a = QAction('Details', self)
        a.triggered.connect(lambda: self.set_mode('detail'))
        self.toolbar.addAction(a)
        # Settings shares the navigation toolbar rather than occupying a separate menu bar.
        self.settings_menu = QMenu('Settings', self)
        self.settings_button = QToolButton(self)
        self.settings_button.setText('Settings')
        self.settings_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.settings_button.setMenu(self.settings_menu)
        self.toolbar.addWidget(self.settings_button)
        self.toolbar.addSeparator()
        self.toolbar.addWidget(QLabel('Thumbnail size  '))
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(80, 300)
        self.size_slider.setSingleStep(10)
        self.size_slider.setFixedWidth(150)
        self.size_slider.valueChanged.connect(self.change_thumbnail_size)
        self.toolbar.addWidget(self.size_slider)
        self.toolbar.addSeparator()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Filter filenames...')
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(220)
        self.search.textChanged.connect(self.filter_list)
        self.toolbar.addWidget(self.search)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.grid = ThumbnailList()
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setMovement(QListWidget.Movement.Static)
        self.grid.setWrapping(True)
        self.grid.setSpacing(8)
        self.grid.setUniformItemSizes(True)
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.grid.selection_clicked.connect(self.on_selected)
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(lambda pos: self.show_image_menu(self.grid, pos))
        self.grid.itemDoubleClicked.connect(self.on_double_clicked)
        self.stack.addWidget(self.grid)

        self.detail_split = QSplitter(Qt.Orientation.Horizontal)
        self.detail_grid = ThumbnailList()
        self.detail_grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.detail_grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.detail_grid.setMovement(QListWidget.Movement.Static)
        self.detail_grid.setWrapping(True)
        self.detail_grid.setSpacing(8)
        self.detail_grid.setUniformItemSizes(True)
        self.detail_grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.detail_grid.selection_clicked.connect(self.on_selected)
        self.detail_grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.detail_grid.customContextMenuRequested.connect(lambda pos: self.show_image_menu(self.detail_grid, pos))
        self.detail_grid.itemDoubleClicked.connect(self.on_double_clicked)
        self.detail_split.addWidget(self.detail_grid)
        self.preview_split = QSplitter(Qt.Orientation.Horizontal)
        self.preview = ImageView()
        self.preview.enlarge_to_fit = self.enlarge_to_fit
        self.preview.clicked.connect(lambda: self.set_mode('image'))
        self.preview.wheel_step.connect(self.step_image)
        self.preview_split.addWidget(self.preview)
        meta_container = QWidget()
        meta_layout = QVBoxLayout(meta_container)
        meta_layout.setContentsMargins(4, 4, 4, 4)
        head = QHBoxLayout()
        head.addWidget(QLabel('Generation metadata'))
        self.raw_button = QPushButton('Raw / Parsed')
        self.raw_button.clicked.connect(self.toggle_raw)
        head.addWidget(self.raw_button)
        meta_layout.addLayout(head)
        self.metadata = QPlainTextEdit()
        self.metadata.setReadOnly(True)
        self.metadata.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        meta_layout.addWidget(self.metadata)
        self.preview_split.addWidget(meta_container)
        self.preview_split.setSizes([650, 350])
        self.detail_split.addWidget(self.preview_split)
        self.detail_split.setSizes([380, 900])
        self.stack.addWidget(self.detail_split)

        self.full_image = ImageView()
        self.full_image.enlarge_to_fit = self.enlarge_to_fit
        self.full_image.wheel_step.connect(self.step_image)
        self.stack.addWidget(self.full_image)
        self.raw_mode = False
        self.parsed_text = ''
        self.raw_text = ''

        self.confirm_action = QAction('Confirm on Delete?', self)
        self.confirm_action.setCheckable(True)
        self.confirm_action.setChecked(self.confirm_on_delete)
        self.confirm_action.toggled.connect(self.set_confirm_on_delete)
        self.settings_menu.addAction(self.confirm_action)
        self.enlarge_action = QAction('Enlarge to fit?', self)
        self.enlarge_action.setCheckable(True)
        self.enlarge_action.setChecked(self.enlarge_to_fit)
        self.enlarge_action.toggled.connect(self.set_enlarge_to_fit)
        self.settings_menu.addAction(self.enlarge_action)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        for key, fn in [('Escape', self.escape), ('Left', lambda: self.step_image(-1)), ('Right', lambda: self.step_image(1)), ('F', self.fit_images)]:
            action = QAction(self)
            action.setShortcut(QKeySequence(key))
            action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
            action.triggered.connect(fn)
            self.addAction(action)
        delete_action = QAction('Delete selected images', self)
        delete_action.setShortcut(QKeySequence.StandardKey.Delete)
        delete_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        delete_action.triggered.connect(self.delete_selection)
        self.addAction(delete_action)

    def set_confirm_on_delete(self, checked):
        self.confirm_on_delete = checked
        self.settings.setValue('confirm_on_delete', checked)

    def set_enlarge_to_fit(self, checked):
        self.enlarge_to_fit = checked
        self.settings.setValue('enlarge_to_fit', checked)
        for image_view in (self.preview, self.full_image):
            image_view.enlarge_to_fit = checked
            image_view.fit()

    def delete_selection(self):
        if self.mode == 'image':
            paths = [self.paths[self.index]] if 0 <= self.index < len(self.paths) else []
        else:
            widget = self.detail_grid if self.mode == 'detail' else self.grid
            paths = self.selected_paths(widget)
        if paths:
            self.delete_images(paths)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Select image directory', str(self.folder))
        if folder:
            self.open_folder(Path(folder), view='grid')

    def open_folder(self, folder: Path, select: Path | None = None, view='grid'):
        if not folder.is_dir():
            return
        self.folder = folder
        self.settings.setValue('last_folder', str(folder))
        self.setWindowTitle(f'{APP_NAME} - {folder}')
        self.paths = images_in(folder)
        self.generation += 1
        self.jobs = []
        self.search.clear()
        self.grid.clear()
        self.detail_grid.clear()
        self.grid.selection_anchor_row = None
        self.detail_grid.selection_anchor_row = None
        size = self.size_slider.value()
        for path in self.paths:
            for widget in (self.grid, self.detail_grid):
                item = QListWidgetItem(path.name)
                item.setData(Qt.ItemDataRole.UserRole, str(path))
                item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
                item.setToolTip(str(path))
                item.setSizeHint(QSize(size + 35, size + 44))
                widget.addItem(item)
        self.apply_thumbnail_geometry(size)
        self.index = self.paths.index(select) if select in self.paths else (0 if self.paths else -1)
        self.update_selected()
        self.set_mode(view)
        self.status.showMessage(f'{len(self.paths)} images in {folder}')
        self.start_thumbnails()

    def apply_thumbnail_geometry(self, size):
        for widget in (self.grid, self.detail_grid):
            widget.setIconSize(QSize(size, size))
            widget.setGridSize(QSize(size + 35, size + 44))
            for i in range(widget.count()):
                widget.item(i).setSizeHint(QSize(size + 35, size + 44))
            widget.doItemsLayout()
            widget.viewport().update()

    def change_thumbnail_size(self, size):
        self.settings.setValue('thumbnail_size', size)
        self.apply_thumbnail_geometry(size)
        if self.paths:
            self.generation += 1
            self.jobs.clear()
            self.start_thumbnails()

    def start_thumbnails(self):
        gen = self.generation
        size = self.size_slider.value()
        # Queue current selection first, then remaining files. Workers emit QImages, never QPixmaps.
        order = sorted(range(len(self.paths)), key=lambda x: abs(x - max(0, self.index)))
        for i in order:
            path = self.paths[i]
            job = ThumbnailJob(path, size, gen)
            job.signals.ready.connect(self.thumbnail_ready)
            self.jobs.append(job)
            self.pool.start(job)

    def thumbnail_ready(self, path, gen, image):
        if gen != self.generation or image.isNull():
            return
        pix = QPixmap.fromImage(image)
        icon = QIcon(pix)
        for widget in (self.grid, self.detail_grid):
            # Index remains stable even when filename filter hides items.
            for item_idx in range(widget.count()):
                item = widget.item(item_idx)
                if item.data(Qt.ItemDataRole.UserRole) == path:
                    item.setIcon(icon)
                    widget.viewport().update()
                    break

    def filter_list(self, text):
        term = text.casefold().strip()
        for widget in (self.grid, self.detail_grid):
            for i in range(widget.count()):
                item = widget.item(i)
                item.setHidden(term not in item.text().casefold())

    def on_selected(self, item):
        path = Path(item.data(Qt.ItemDataRole.UserRole))
        try:
            self.index = self.paths.index(path)
        except ValueError:
            return
        widget = item.listWidget()
        chosen = [it.data(Qt.ItemDataRole.UserRole) for it in widget.selectedItems()]
        other = self.detail_grid if widget is self.grid else self.grid
        self.select_paths(other, chosen)
        other.selection_anchor_row = widget.selection_anchor_row
        self.update_selected(preserve_selection=True)
        if len(chosen) > 1:
            self.status.showMessage(f'{len(chosen)} images selected')
        # Single-click in the full grid only selects; double-click opens details.

    def select_paths(self, widget, paths):
        wanted = set(paths)
        widget.blockSignals(True)
        try:
            for i in range(widget.count()):
                item = widget.item(i)
                item.setSelected(item.data(Qt.ItemDataRole.UserRole) in wanted)
        finally:
            widget.blockSignals(False)

    def on_double_clicked(self, item):
        self.on_selected(item)
        if self.mode == 'grid':
            self.set_mode('detail')
        elif self.mode == 'detail':
            self.set_mode('image')

    def update_selected(self, preserve_selection=False):
        if self.index < 0 or self.index >= len(self.paths):
            self.preview.set_image(None)
            self.full_image.set_image(None)
            self.metadata.setPlainText('No images in this directory.')
            return
        path = self.paths[self.index]
        self.preview.set_image(path)
        self.full_image.set_image(path)
        self.parsed_text, self.raw_text = metadata_for(path)
        self.metadata.setPlainText(self.raw_text if self.raw_mode else self.parsed_text)
        for widget in (self.grid, self.detail_grid):
            for i in range(widget.count()):
                item = widget.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == str(path):
                    widget.blockSignals(True)
                    if not preserve_selection:
                        widget.setCurrentItem(item)
                    widget.scrollToItem(item)
                    widget.blockSignals(False)
                    break
        self.status.showMessage(f'{self.index + 1} / {len(self.paths)}  •  {path.name}')

    def step_image(self, delta):
        if not self.paths:
            return
        self.index = (self.index + delta) % len(self.paths)
        self.update_selected()

    def selected_paths(self, widget):
        return [Path(it.data(Qt.ItemDataRole.UserRole)) for it in widget.selectedItems()]

    def recent_folders(self):
        folders = self.settings.value('recent_move_folders', [])
        if isinstance(folders, str):
            folders = [folders] if folders else []
        return [Path(folder) for folder in folders if folder]

    def remember_move_folder(self, folder):
        recent = [str(folder)] + [str(p) for p in self.recent_folders() if p != folder]
        self.settings.setValue('recent_move_folders', recent[:3])

    def show_image_menu(self, widget, pos):
        item = widget.itemAt(pos)
        if item is None:
            return
        if not item.isSelected():
            widget.clearSelection()
            item.setSelected(True)
        paths = self.selected_paths(widget)
        if not paths:
            return
        menu = QMenu(self)
        delete = menu.addAction(f'Delete to Trash ({len(paths)})')
        move = menu.addAction('Move To...')
        recent = self.recent_folders()
        if recent:
            menu.addSeparator()
            for folder in recent:
                action = menu.addAction(f'Move to {folder}')
                action.setData(str(folder))
        chosen = menu.exec(widget.viewport().mapToGlobal(pos))
        if chosen is delete:
            self.delete_images(paths)
        elif chosen is move:
            folder = QFileDialog.getExistingDirectory(self, 'Move selected images to', str(recent[0] if recent else self.folder))
            if folder:
                self.move_images(paths, Path(folder))
        elif chosen and chosen.data():
            self.move_images(paths, Path(chosen.data()))

    def delete_images(self, paths):
        count = len(paths)
        if self.confirm_on_delete:
            answer = QMessageBox.question(
                self, 'Move images to Trash',
                f'Move {count} selected image{"s" if count != 1 else ""} to the Trash?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel)
            if answer != QMessageBox.StandardButton.Yes:
                return
        errors = []
        for path in paths:
            try:
                send2trash(str(path))
            except Exception as exc:
                errors.append(f'{path.name}: {exc}')
        self.refresh_after_changes(paths)
        if errors:
            QMessageBox.warning(self, 'Some files could not be trashed', '\n'.join(errors[:12]))

    def move_images(self, paths, folder):
        if not folder.is_dir():
            QMessageBox.warning(self, 'Folder unavailable', f'Destination does not exist:\n{folder}')
            return
        errors = []
        moved = 0
        for path in paths:
            try:
                if path.parent.resolve() == folder.resolve():
                    continue
                dest = folder / path.name
                if dest.exists():
                    raise FileExistsError('destination already contains a file with that name')
                shutil.move(str(path), str(dest))
                moved += 1
            except Exception as exc:
                errors.append(f'{path.name}: {exc}')
        if moved:
            self.remember_move_folder(folder)
        self.refresh_after_changes(paths)
        if errors:
            QMessageBox.warning(self, 'Some files could not be moved', '\n'.join(errors[:12]))
        else:
            self.status.showMessage(f'Moved {moved} image(s) to {folder}', 5000)

    def refresh_after_changes(self, _old_paths):
        old_index = self.index
        self.open_folder(self.folder, view=self.mode)
        if self.paths:
            self.index = min(max(0, old_index), len(self.paths)-1)
            self.update_selected()

    def toggle_raw(self):
        self.raw_mode = not self.raw_mode
        self.metadata.setPlainText(self.raw_text if self.raw_mode else self.parsed_text)

    def fit_images(self):
        self.preview.fit()
        self.full_image.fit()

    def set_mode(self, mode):
        if mode not in ('grid', 'detail', 'image'):
            return
        self.mode = mode
        self.stack.setCurrentIndex({'grid': 0, 'detail': 1, 'image': 2}[mode])
        self.toolbar.setVisible(mode != 'image')
        self.status.setVisible(mode != 'image')
        if mode == 'image':
            self.full_image.fit()

    def escape(self):
        self.set_mode({'image': 'detail', 'detail': 'grid', 'grid': 'grid'}[self.mode])

    def closeEvent(self, event):
        self.settings.setValue('window_geometry', self.saveGeometry())
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName('LocalAI')
    initial = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else None
    window = MainWindow(initial)
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
