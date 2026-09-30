"""The live companion window.

A Qt scene rather than a plot: dragging pans, the wheel zooms about the cursor, and
POIs and the player are scene items that keep a constant on-screen size at any zoom.

Rendering happens on a worker thread and only when the plugin's files have actually
changed, so panning and zooming stay smooth while the game is running.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QObject, QPointF, QRectF, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QGraphicsEllipseItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QLabel,
    QMainWindow,
    QToolBar,
    QWidget,
)

from foggymap.mapview import FOUND_POI, LABEL_ZOOM, PLAYER, MapView, dot, label, to_pixmap

from foggymap.pipboy import export_for_pipboy
from foggymap.pipeline import FogMap, Settings, Worldspace, load_manifest, load_worldspace, render
from foggymap.readout import point_description, status_line
from foggymap.watcher import fingerprint

POLL_MS = 2000



class _RenderSignals(QObject):
    done = Signal(object, object)  # editor_id, FogMap
    failed = Signal(str)


class _RenderTask(QRunnable):
    """One off-thread render. Rendering the Commonwealth costs about a second."""

    def __init__(self, worldspace: Worldspace, data_dir: str, settings: Settings):
        super().__init__()
        self.worldspace = worldspace
        self.data_dir = data_dir
        self.settings = settings
        self.signals = _RenderSignals()

    def run(self) -> None:
        # A half-written CSV must not kill the window, but the failure has to be
        # reported: swallowing it would also leave the window permanently "rendering".
        try:
            fog = render(self.worldspace, self.data_dir, self.settings)
        except Exception as error:
            self.signals.failed.emit(f"{type(error).__name__}: {error}")
            return
        self.signals.done.emit(self.worldspace.editor_id, fog)


class Window(QMainWindow):
    def __init__(self, assets_dir: str, data_dir: str, editor_ids: list[str]):
        super().__init__()
        self.assets_dir = assets_dir
        self.data_dir = data_dir
        self.editor_ids = editor_ids
        self.editor_id = editor_ids[0]
        self.settings = Settings()
        self.worldspaces: dict[str, Worldspace] = {}
        self.fog: FogMap | None = None
        self.fingerprint: tuple | None = None
        self.rendering = False
        self.last_error: str | None = None
        self.pool = QThreadPool()

        self.setWindowTitle("FoggyMap")
        self.resize(1100, 900)

        self.scene = QGraphicsScene(self)
        self.map_item = QGraphicsPixmapItem()
        # Without this the map is upscaled nearest-neighbour and goes blocky when
        # zoomed in past 1:1.
        self.map_item.setTransformationMode(Qt.SmoothTransformation)
        self.scene.addItem(self.map_item)
        self.poi_items: list[QGraphicsEllipseItem | QGraphicsSimpleTextItem] = []
        self.label_items: list[QGraphicsSimpleTextItem] = []
        self.player_item: QGraphicsEllipseItem | None = None

        self.view = MapView(self.scene)
        self.view.hovered.connect(self.on_hover)
        self.view.zoomed.connect(self.on_zoom_changed)
        self.setCentralWidget(self.view)

        self._build_toolbar()
        self.status = QLabel("loading...")
        self.status.setStyleSheet("font-family: Consolas, monospace; padding: 3px;")
        self.statusBar().addWidget(self.status)
        self.hover = QLabel("")
        self.hover.setStyleSheet("font-family: Consolas, monospace; padding: 3px;")
        self.statusBar().addPermanentWidget(self.hover)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(POLL_MS)
        self.request_render(force=True)

    # -- setup ---------------------------------------------------------------

    def _build_toolbar(self) -> None:
        bar = QToolBar("view", self)
        bar.setMovable(False)
        self.addToolBar(bar)

        self.chooser = QComboBox()
        self.chooser.addItems(self.editor_ids)
        self.chooser.currentTextChanged.connect(self.on_worldspace_changed)
        bar.addWidget(QLabel(" worldspace "))
        bar.addWidget(self.chooser)

        bar.addSeparator()
        self.spoiler_free = QCheckBox("No spoilers")
        self.spoiler_free.setToolTip(
            "Hide every trace of places you have not found yet: no fog circles on\n"
            "undiscovered locations, and no 'nearest undiscovered' readout."
        )
        self.spoiler_free.toggled.connect(self.on_spoilers_toggled)
        bar.addWidget(self.spoiler_free)

        bar.addSeparator()
        self.names = QCheckBox("POI names")
        self.names.setChecked(True)
        self.names.setToolTip(f"Names appear once zoomed past {LABEL_ZOOM:g}x")
        self.names.toggled.connect(lambda: self.update_label_visibility())
        bar.addWidget(self.names)

        bar.addWidget(QWidget())

    def worldspace(self) -> Worldspace:
        if self.editor_id not in self.worldspaces:
            self.worldspaces[self.editor_id] = load_worldspace(self.assets_dir, self.editor_id)
        return self.worldspaces[self.editor_id]

    # -- refresh cycle -------------------------------------------------------

    def poll(self) -> None:
        """Only spend a render when the plugin has actually written something."""
        current = fingerprint(self.data_dir, self.editor_id)
        if current != self.fingerprint:
            self.request_render()

    def request_render(self, force: bool = False) -> None:
        if self.rendering and not force:
            return
        self.rendering = True
        self.fingerprint = fingerprint(self.data_dir, self.editor_id)
        task = _RenderTask(self.worldspace(), self.data_dir, self.settings)
        task.signals.done.connect(self.on_rendered)
        task.signals.failed.connect(self.on_render_failed)
        self.pool.start(task)

    def on_render_failed(self, message: str) -> None:
        self.rendering = False
        self.last_error = message
        self.status.setText(f"render failed - {message}")

    def on_rendered(self, editor_id: str, fog: FogMap) -> None:
        self.rendering = False
        if editor_id != self.editor_id:
            return  # the user switched worldspace while this was in flight
        first = self.fog is None
        self.fog = fog

        # Keep the Pip-Boy's copy current. Failing to write it must never take the
        # window down -- it is a nice-to-have on top of the live view.
        try:
            export_for_pipboy(self.worldspace(), fog, self.data_dir)
        except OSError as error:
            self.last_error = f"pip-boy export failed: {error}"

        self.map_item.setPixmap(to_pixmap(fog.rgb))
        self.scene.setSceneRect(QRectF(self.map_item.pixmap().rect()))
        self.rebuild_markers()
        self.status.setText(status_line(self.editor_id, fog, self.settings))
        if first:
            self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
            self.on_zoom_changed(self.view.transform().m11())

    # -- scene items ---------------------------------------------------------

    def rebuild_markers(self) -> None:
        for item in self.poi_items:
            self.scene.removeItem(item)
        self.poi_items.clear()
        self.label_items.clear()
        if self.player_item is not None:
            self.scene.removeItem(self.player_item)
            self.player_item = None
        if self.fog is None:
            return

        grid = self.worldspace().grid
        for poi in self.fog.pois:
            # Only discovered POIs are drawn. Marking the others would give away
            # locations the player has not found.
            if not poi.discovered:
                continue
            col, row = grid.to_px(poi.x, poi.y)
            self.poi_items.append(dot(self.scene, col, row, 3.0, FOUND_POI))
            if poi.name:
                self.label_items.append(label(self.scene, col, row, poi.name))
        self.poi_items.extend(self.label_items)

        if self.fog.player_position is not None:
            col, row = grid.to_px(*self.fog.player_position)
            self.player_item = dot(self.scene, col, row, 6.0, PLAYER, ring=True)

        self.update_label_visibility()

    def update_label_visibility(self) -> None:
        zoom = self.view.transform().m11()
        visible = self.names.isChecked() and zoom >= LABEL_ZOOM
        for item in self.label_items:
            item.setVisible(visible)

    def on_zoom_changed(self, _zoom: float) -> None:
        self.update_label_visibility()

    # -- interaction ---------------------------------------------------------

    def on_worldspace_changed(self, editor_id: str) -> None:
        self.editor_id = editor_id
        self.fog = None
        self.fingerprint = None
        self.request_render(force=True)

    def on_spoilers_toggled(self, spoiler_free: bool) -> None:
        self.settings = replace_settings(self.settings, show_missed_pois=not spoiler_free)
        self.hover.setText("")
        self.request_render(force=True)

    def on_hover(self, point: QPointF) -> None:
        if self.fog is None:
            return
        self.hover.setText(
            point_description(
                self.fog,
                self.worldspace(),
                self.settings,
                point.x(),
                point.y(),
                spoilers=not self.spoiler_free.isChecked(),
            )
        )


def replace_settings(settings: Settings, **changes) -> Settings:
    """Settings is frozen, so changing a knob makes a new one."""
    import dataclasses

    return dataclasses.replace(settings, **changes)


def default_data_dir() -> str:
    return os.path.join(os.environ.get("LOCALAPPDATA", "."), "FoggyMap")


def main(assets_dir: str = "assets", data_dir: str | None = None) -> None:
    data_dir = data_dir or default_data_dir()
    application = QApplication.instance() or QApplication([])
    window = Window(assets_dir, data_dir, list(load_manifest(assets_dir)))
    window.show()
    application.exec()
