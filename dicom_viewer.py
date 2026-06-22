import sys
import os
import math
import numpy as np
import pydicom

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_DIR = os.path.join(BASE_DIR, "icons")

def icon(name):
    """Return QIcon object from the icons folder"""
    return QIcon(os.path.join(ICON_DIR, name))

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QFileDialog, QLabel, QSlider, QMenu, QMenuBar, QGraphicsView, QGraphicsScene,
    QGraphicsPixmapItem, QMessageBox, QAction, QToolBar, QSplashScreen,
    QToolButton, QMenu, QTextEdit
)
from PyQt5.QtGui import QPixmap, QImage, QIcon, QPen, QColor
from PyQt5.QtCore import Qt, QRectF, QTimer, QSize

# ------------------ Helper Utilities ------------------
def warn(msg):
    print("[WARN]", msg, file=sys.stderr)

def err(msg):
    print("[ERROR]", msg, file=sys.stderr)

def to_8bit(frame):
    if frame is None:
        return None
    arr = np.array(frame, copy=True)
    if arr.dtype == np.uint8:
        return arr
    mn = np.nanmin(arr)
    mx = np.nanmax(arr)
    if not np.isfinite(mn) or not np.isfinite(mx) or mx - mn == 0:
        return np.zeros_like(arr, dtype=np.uint8)
    scaled = (arr - mn) / (mx - mn)
    return (scaled * 255).astype(np.uint8)

def numpy_to_qimage(gray8):
    h, w = gray8.shape
    return QImage(gray8.data.tobytes(), w, h, w, QImage.Format_Grayscale8)

# ------------------ Graphics View ------------------
class ImageView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.pixmap_item = QGraphicsPixmapItem()
        self.scene().addItem(self.pixmap_item)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self._is_panning = False
        self._pan_start = None

        self.measure_points = []
        self.measure_primitives = []
        self.measure_pen = QPen(QColor(255, 170, 0), 2)

        # Dark background for the image area
        self.setBackgroundBrush(QColor(30, 30, 60))

    def set_pixmap(self, qpix):
        self.pixmap_item.setPixmap(qpix)
        self.scene().setSceneRect(QRectF(qpix.rect()))
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

    def wheelEvent(self, event):
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.scale(factor, factor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._is_panning = True
            self._pan_start = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
        elif event.button() == Qt.LeftButton and QApplication.keyboardModifiers() & Qt.ControlModifier:
            self.add_measure_point(self.mapToScene(event.pos()))
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._is_panning and self._pan_start:
            delta = event.pos() - self._pan_start
            self._pan_start = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._is_panning = False
            self.setCursor(Qt.ArrowCursor)
        else:
            super().mouseReleaseEvent(event)

    def clear_measurements(self):
        for it in self.measure_primitives:
            try:
                self.scene().removeItem(it)
            except:
                pass
        self.measure_points = []
        self.measure_primitives = []

    def add_measure_point(self, scene_point):
        self.measure_points.append(scene_point)
        if len(self.measure_points) == 2:
            p0, p1 = self.measure_points
            line = self.scene().addLine(p0.x(), p0.y(), p1.x(), p1.y(), self.measure_pen)
            dist_px = math.hypot(p1.x() - p0.x(), p1.y() - p0.y())
            text_item = self.scene().addText(f"{dist_px:.1f} px")
            text_item.setDefaultTextColor(QColor(255, 170, 0))
            text_item.setPos((p0.x()+p1.x())/2, (p0.y()+p1.y())/2)
            self.measure_primitives.extend([line, text_item])
            self.measure_points = []

# ------------------ Main Application ------------------
class DICOMApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DICOMPix - DICOM Viewer 2025.1 (64-bit) - unlicensed for commercial use")
        ICON_DIR = os.path.dirname(os.path.abspath(__file__))

        icon_path = os.path.join(ICON_DIR, "DICOMPix.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.resize(1200, 800)

        

        self.ds = None
        self.pixel_data = None
        self.current_frame = 0
        self.folder_files = []

        # ------------------ Main Layout ------------------
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        # ------------------ Left Panel ------------------
        left_panel = QVBoxLayout()
        main_layout.addLayout(left_panel, 1)

        # ------------------ Toolbar ------------------
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(15, 15))
        toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)
        toolbar.setStyleSheet("""
            QToolBar { background-color: #4682B4; spacing: 5px; padding: 3px; }
            QToolButton { background-color: white; border-radius: 4px; padding: 5px; }
            QToolButton:hover { background-color: #87CEFA; }
        """)

        # ----- OPEN BUTTON WITH DROPDOWN -----
        open_btn = QToolButton()
        open_btn.setIcon(icon("open_file.png"))  # use your icons/open.png
        open_btn.setPopupMode(QToolButton.MenuButtonPopup)
        open_btn.setToolTip("Open")
        open_btn.setToolTip("Open DICOM file or folder")

        menu = QMenu(open_btn)
        add_file_action=QAction("Add File", self)
        add_file_action.triggered.connect(self.open_file)
        menu.addAction(add_file_action)

        add_folder_action=QAction("Add Folder", self)
        add_folder_action.triggered.connect(self.open_folder)
        menu.addAction(add_folder_action)

        open_btn.setMenu(menu)
        toolbar.addWidget(open_btn)


        open_menu = QMenu(open_btn)
        open_menu.addAction("Open DICOM", self.open_file)
        open_menu.addAction("Open ZIP File")        
        open_menu.addAction("Open CD/DVD")         
        open_menu.addAction("Scan for DICOM files") 
        open_menu.addAction("Download from DICOM Server") 
        open_btn.setMenu(open_menu)
        toolbar.addWidget(open_btn)

        # ----- IMAGE-ONLY ACTION BUTTONS -----
        toolbar.addSeparator()
        toolbar.addAction(icon("export_image.png"), "").setToolTip("Export Image")
        toolbar.addAction(icon("export_video.png"), "").setToolTip("Export Video")
        toolbar.addAction(icon("print.png"), "").setToolTip("Print")
        toolbar.addAction(icon("zoom.png"), "").setToolTip("Zoom")
        toolbar.addAction(icon("fit.png"), "").setToolTip("Fit to Screen")

        # ----- DRAW / MEASURE ICONS -----
        toolbar.addSeparator()
        toolbar.addAction(icon("pencil.png"), "").setToolTip("Freehand")
        toolbar.addAction(icon("distance.png"), "").setToolTip("Measure Distance")
        toolbar.addAction(icon("rectangle.png"), "").setToolTip("Rectangle")
        toolbar.addAction(icon("open_curve.png"), "").setToolTip("Open Curve")
        toolbar.addAction(icon("closed_curve.png"), "").setToolTip("Closed Curve")
        toolbar.addAction(icon("text.png"), "").setToolTip("Text")
        toolbar.addAction(icon("eraser.png"), "").setToolTip("Eraser")

        # ----- ORIENTATION / UNDO ICONS -----
        toolbar.addSeparator()
        toolbar.addAction(icon("undo.png"), "").setToolTip("Undo")
        toolbar.addAction(icon("redo.png"), "").setToolTip("Redo")
        toolbar.addAction(icon("restore.png"), "").setToolTip("Restore Orientation")
        toolbar.addAction(icon("flip_h.png"), "").setToolTip("Flip Horizontal")
        toolbar.addAction(icon("flip_v.png"), "").setToolTip("Flip Vertical")


        menu = QMenu(open_btn)
        add_file_action = QAction("Add File", self)
        add_file_action.triggered.connect(self.open_file)
        menu.addAction(add_file_action)
        add_folder_action = QAction("Add Folder", self)
        add_folder_action.triggered.connect(self.open_folder)
        menu.addAction(add_folder_action)
        open_btn.setMenu(menu)
        toolbar.addWidget(open_btn)

        # ----- Remove File button -----
        remove_btn = QToolButton()
        remove_btn.setIcon(QIcon(os.path.join(ICON_DIR, "remove_file.png")))
        remove_btn.setToolTip("Remove Current File")
        remove_btn.clicked.connect(self.remove_file)
        toolbar.addWidget(remove_btn)

        # Other toolbar actions
        export_action = QAction("Export PNG", self)
        export_action.triggered.connect(self.export_png)
        toolbar.addAction(export_action)
        clear_m_action = QAction("Clear Measurements", self)
        clear_m_action.triggered.connect(lambda: self.view.clear_measurements())
        toolbar.addAction(clear_m_action)
        invert_action = QAction("Invert", self)
        invert_action.setCheckable(True)
        invert_action.toggled.connect(lambda _: self.update_image())
        toolbar.addAction(invert_action)

        # ----- Refresh button -----
        refresh_action = QAction(QIcon(os.path.join(ICON_DIR, "refresh.png")), "Refresh", self)
        refresh_action.setToolTip("Reload current DICOM file")
        refresh_action.triggered.connect(self.refresh_file)
        toolbar.addAction(refresh_action)

        left_panel.addWidget(toolbar)

        # ------------------ Navigation & Sliders ------------------
        nav_row = QHBoxLayout()
        self.btn_prev = QPushButton("Prev")
        self.btn_prev.clicked.connect(self.prev_frame)
        self.btn_prev.setEnabled(False)
        self.btn_next = QPushButton("Next")
        self.btn_next.clicked.connect(self.next_frame)
        self.btn_next.setEnabled(False)
        nav_row.addWidget(self.btn_prev)
        nav_row.addWidget(self.btn_next)
        left_panel.addLayout(nav_row)

        left_panel.addWidget(QLabel("Zoom (%)"))
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(10, 400)
        self.zoom_slider.setValue(100)
        self.zoom_slider.valueChanged.connect(self.apply_zoom_from_slider)
        self.zoom_slider.setStyleSheet("""
            QSlider::groove:horizontal { height: 8px; background: #B0C4DE; border-radius: 4px; }
            QSlider::handle:horizontal { background: #1E90FF; width: 14px; margin: -3px; border-radius: 7px; }
        """)
        left_panel.addWidget(self.zoom_slider)

        left_panel.addWidget(QLabel("Window (contrast)"))
        self.window_slider = QSlider(Qt.Horizontal)
        self.window_slider.setRange(1, 4000)
        self.window_slider.setValue(200)
        self.window_slider.valueChanged.connect(self.update_image)
        left_panel.addWidget(self.window_slider)

        left_panel.addWidget(QLabel("Level (center)"))
        self.level_slider = QSlider(Qt.Horizontal)
        self.level_slider.setRange(-2000, 2000)
        self.level_slider.setValue(2000)
        self.level_slider.valueChanged.connect(self.update_image)
        left_panel.addWidget(self.level_slider)

        self.info_label = QLabel("Drop a DICOM file here.\nCtrl+LeftClick to measure.")
        self.info_label.setWordWrap(True)
        left_panel.addWidget(self.info_label)
        left_panel.addStretch()

        # ------------------ Center Panel ------------------
        self.view = ImageView(self)
        main_layout.addWidget(self.view, 4)

                # =========================
        # Menu Bar (below title bar)
        # =========================
        menu_bar = self.menuBar()

        # ---- File ----
        file_menu = menu_bar.addMenu("File")

        open_action = QAction("Open DICOM", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.open_file)
        file_menu.addAction(open_action)

        file_menu.addSeparator()

        exit_action = QAction("Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # ---- Network ----
        network_menu = menu_bar.addMenu("Network")
        network_menu.addAction("Query / Retrieve")
        network_menu.addAction("Send to PACS")
        network_menu.addAction("PACS Settings")

        # ---- View ----
        view_menu = menu_bar.addMenu("View")

        reset_zoom_action = QAction("Reset Zoom", self)
        reset_zoom_action.triggered.connect(lambda: self.apply_zoom_percent(100))
        view_menu.addAction(reset_zoom_action)

        invert_action_menu = QAction("Invert Image", self)
        invert_action_menu.triggered.connect(lambda: self.update_image())
        view_menu.addAction(invert_action_menu)

        # ---- Measure ----
        measure_menu = menu_bar.addMenu("Measure")
        clear_measure_action = QAction("Clear Measurements", self)
        clear_measure_action.triggered.connect(self.view.clear_measurements)
        measure_menu.addAction(clear_measure_action)
        measure_menu.addAction("Length")
        measure_menu.addAction("Angle")

        # ---- Annotate Image ----
        annotate_menu = menu_bar.addMenu("Annotate Image")
        annotate_menu.addAction("Add Text")
        annotate_menu.addAction("Arrow")
        annotate_menu.addAction("Rectangle")
        annotate_menu.addAction("Circle")

        # ---- Tools ----
        tools_menu = menu_bar.addMenu("Tools")
        tools_menu.addAction("Window / Level Presets")
        tools_menu.addAction("Preferences")

        # ---- Help ----
        help_menu = menu_bar.addMenu("Help")
        about_action = QAction("About", self)
        about_action.triggered.connect(
            lambda: QMessageBox.information(
                self,
                "About DICOMPix",
                "DICOMPix Viewer\nVersion 2025.1\nFor academic use"
            )
        )
        help_menu.addAction(about_action)


        # ------------------ Right Panel ------------------
        right_panel = QVBoxLayout()
        main_layout.addLayout(right_panel, 1)
        right_panel.addWidget(QLabel("Patient Info"))
        self.patient_info = QTextEdit()
        self.patient_info.setReadOnly(True)
        self.patient_info.setStyleSheet("background-color: #E0FFFF; border: 1px solid #4682B4;")
        right_panel.addWidget(self.patient_info)

        self.setAcceptDrops(True)
    
    

    # ------------------ DICOM Handling ------------------
    def open_file(self):
        fname, _ = QFileDialog.getOpenFileName(self, "Open DICOM", "", "DICOM Files (*.dcm)")
        if fname:
            self.load_dicom(fname)

    def open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Open DICOM Folder")
        if folder:
            files = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(".dcm")]
            if not files:
                QMessageBox.information(self, "No DICOM files", "No DICOM files found in this folder.")
                return
            self.folder_files = files
            self.load_dicom(files[0])
            self.current_frame = 0

    def remove_file(self):
        if self.pixel_data is None:
            QMessageBox.information(self, "Remove File", "No file loaded to remove.")
            return

        if hasattr(self, "folder_files") and self.folder_files:
            removed_file = self.folder_files.pop(self.current_frame)
            QMessageBox.information(self, "Remove File", f"Removed: {removed_file}")
            if not self.folder_files:
                self.pixel_data = None
                self.view.set_pixmap(QPixmap())
                self.patient_info.clear()
                self.btn_prev.setEnabled(False)
                self.btn_next.setEnabled(False)
                return
            self.current_frame = min(self.current_frame, len(self.folder_files) - 1)
            self.load_dicom(self.folder_files[self.current_frame])
        else:
            self.pixel_data = None
            self.view.set_pixmap(QPixmap())
            self.patient_info.clear()
            self.btn_prev.setEnabled(False)
            self.btn_next.setEnabled(False)
            QMessageBox.information(self, "Remove File", "File removed.")

    def load_dicom(self, path):
        try:
            ds = pydicom.dcmread(path)
        except Exception as e:
            err(f"Failed reading DICOM: {e}")
            QMessageBox.critical(self, "Read Error", f"Failed to read DICOM file.\n{e}")
            return
        self.ds = ds
        self.patient_info.setPlainText(
            f"Patient Name: {ds.get('PatientName', '')}\n"
            f"ID: {ds.get('PatientID', '')}\n"
            f"Modality: {ds.get('Modality', '')}\n"
            f"Study Date: {ds.get('StudyDate', '')}"
        )
        try:
            arr = ds.pixel_array
        except Exception as e:
            err(f"Failed to decode pixel_array: {e}")
            QMessageBox.critical(self, "Decode Error", f"Cannot decode pixel data.\n{e}")
            return

        arr = np.array(arr)
        if arr.ndim == 2:
            arr = arr[np.newaxis, ...]
        elif arr.ndim == 3 and arr.shape[2] in (3, 4):
            gray = np.mean(arr[..., :3], axis=2).astype(arr.dtype)
            arr = gray[np.newaxis, ...]
        elif arr.ndim == 4:
            frames = [np.mean(fr[..., :3], axis=2).astype(arr.dtype) for fr in arr]
            arr = np.stack(frames, axis=0)
        self.pixel_data = arr
        self.current_frame = 0
        self.btn_prev.setEnabled(self.pixel_data.shape[0] > 1)
        self.btn_next.setEnabled(self.pixel_data.shape[0] > 1)
        self.update_image()

    def update_image(self):
        if self.pixel_data is None:
            return
        frame = self.pixel_data[self.current_frame].astype(np.float32)
        ww = max(1.0, self.window_slider.value())
        wc = self.level_slider.value()
        low = wc - (ww / 2)
        high = wc + (ww / 2)
        lut = np.clip((frame - low) / (high - low), 0, 1)
        gray8 = (lut * 255).astype(np.uint8)

        invert = any(a.text() == "Invert" and a.isChecked() for a in self.findChildren(QAction))
        if invert:
            gray8 = 255 - gray8

        pix = QPixmap.fromImage(numpy_to_qimage(gray8))
        self.view.set_pixmap(pix)
        self.apply_zoom_percent(self.zoom_slider.value())

    def apply_zoom_percent(self, percent):
        if percent <= 0:
            percent = 100
        self.view.resetTransform()
        self.view.scale(percent / 100.0, percent / 100.0)

    def apply_zoom_from_slider(self, val):
        self.apply_zoom_percent(val)

    def next_frame(self):
        if self.pixel_data is None:
            return
        self.current_frame = (self.current_frame + 1) % self.pixel_data.shape[0]
        self.update_image()

    def prev_frame(self):
        if self.pixel_data is None:
            return
        self.current_frame = (self.current_frame - 1) % self.pixel_data.shape[0]
        self.update_image()

    def export_png(self):
        if self.pixel_data is None:
            QMessageBox.information(self, "Export", "No image to export.")
            return
        fname, _ = QFileDialog.getSaveFileName(self, "Save PNG", "", "PNG Files (*.png)")
        if fname:
            pix = self.view.pixmap_item.pixmap()
            if pix and not pix.isNull():
                pix.save(fname, "PNG")
                QMessageBox.information(self, "Export", f"Saved PNG to:\n{fname}")

    # ------------------ Refresh Method ------------------
    def refresh_file(self):
        if self.ds is None:
            QMessageBox.information(self, "Refresh", "No file loaded to refresh.")
            return
        if self.folder_files:
            self.load_dicom(self.folder_files[self.current_frame])
        else:
            try:
                filepath = self.ds.filename
                if filepath:
                    self.load_dicom(filepath)
            except Exception as e:
                err(f"Cannot refresh file: {e}")
                QMessageBox.warning(self, "Refresh", f"Cannot refresh file.\n{e}")

    # ------------------ Drag and Drop ------------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls and urls[0].toLocalFile().lower().endswith(".dcm"):
            self.load_dicom(urls[0].toLocalFile())

# ------------------ Run Application ------------------
def show_main(win, splash):
    win.show()
    if splash:
        splash.finish(win)

def main():
    app = QApplication(sys.argv)
    splash_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "splash.png")
    splash = None
    if os.path.exists(splash_path):
        pixmap = QPixmap(splash_path).scaledToWidth(600, Qt.SmoothTransformation)
        splash = QSplashScreen(pixmap)
        splash.show()
        app.processEvents()

    win = DICOMApp()
    if splash:
        QTimer.singleShot(3000, lambda: show_main(win, splash))
    else:
        win.show()

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
