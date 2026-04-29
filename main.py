import sys
import os
import pandas as pd
import numpy as np
import pyqtgraph as pg
from datetime import datetime
import threading

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QListWidget, QTableWidget, QTableWidgetItem, QLabel, 
    QPushButton, QHeaderView, QSplitter, QLineEdit, QDialog, 
    QFormLayout, QMessageBox, QTextEdit, QStatusBar, QToolTip
)
from PySide6.QtCore import Qt, QTimer, QThread, QRect
from PySide6.QtGui import QIcon

from database import Database
from tracer import NmapTracer

# --- Resource Helper ---
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# --- UI Config ---
STYLE_SHEET = """
    QWidget { background-color: #1a1a1a; color: #eeeeee; font-family: 'Segoe UI'; }
    QPushButton { background-color: #333; border: 1px solid #444; padding: 8px; border-radius: 4px; }
    QPushButton:hover { background-color: #444; }
    QTableWidget { background-color: #222; border: none; gridline-color: #333; }
    QListWidget { background-color: #222; border: 1px solid #333; }
    QListWidget::item:selected { background-color: #00d1b2; color: black; }
"""

pg.setConfigOption('background', '#111111')
pg.setConfigOption('foreground', '#d1d1d1')
pg.setConfigOption('antialias', True)

class DateAxis(pg.AxisItem):
    def tickStrings(self, values, scale, spacing):
        return [datetime.fromtimestamp(v).strftime('%H:%M:%S') if v > 0 else "" for v in values]

class AddServerDlg(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Monitor Target")
        self.setFixedWidth(300)
        layout = QFormLayout(self)
        self.addr = QLineEdit()
        self.port = QLineEdit("443")
        layout.addRow("Host/IP:", self.addr)
        layout.addRow("Port:", self.port)
        btn = QPushButton("Save")
        btn.clicked.connect(self.accept)
        layout.addRow(btn)

    def get_info(self):
        return self.addr.text().strip(), int(self.port.text()) if self.port.text().isdigit() else 443

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LatencyLog")
        self.resize(1300, 850)
        self.setStyleSheet(STYLE_SHEET)
        
        # Set Window Icon
        icon_file = resource_path("icon.ico")
        if os.path.exists(icon_file):
            self.setWindowIcon(QIcon(icon_file))

        self.db = Database()
        self.tracer = NmapTracer(self.db)
        self.current_server = None
        self.current_df = None
        self.last_hover_id = -1
        self.first_load = True

        self._init_ui()
        self._start_engine()

        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self._safe_refresh)
        self.refresh_timer.start(5000)

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        # Sidebar
        sidebar = QWidget()
        sidebar.setFixedWidth(220)
        side_layout = QVBoxLayout(sidebar)
        side_layout.addWidget(QLabel("<b>DEVICES</b>"))
        
        self.server_list = QListWidget()
        self.server_list.itemClicked.connect(self._on_server_selected)
        side_layout.addWidget(self.server_list)
        self._update_server_list()

        btn_box = QVBoxLayout()
        add_btn = QPushButton("+ Add Server")
        add_btn.setStyleSheet("background-color: #00d1b2; color: #111; font-weight: bold;")
        add_btn.clicked.connect(self._add_server)
        
        rem_btn = QPushButton("Remove Selected")
        rem_btn.clicked.connect(self._remove_server)
        
        reset_btn = QPushButton("⚠ Purge History")
        reset_btn.setStyleSheet("color: #ff4444; border-color: #ff4444; margin-top: 10px;")
        reset_btn.clicked.connect(self._purge_data)

        for b in [add_btn, rem_btn, reset_btn]: btn_box.addWidget(b)
        side_layout.addLayout(btn_box)
        side_layout.addStretch()
        main_layout.addWidget(sidebar)

        # Dashboard
        dash = QSplitter(Qt.Vertical)
        
        self.plot = pg.PlotWidget(axisItems={'bottom': DateAxis(orientation='bottom')})
        self.plot.setTitle("Latency", color="#00d1b2")
        self.plot.showGrid(x=True, y=True, alpha=0.2)
        self.plot.setLabel('left', 'RTT', units='ms')
        self.plot.setMouseEnabled(x=True, y=False)
        self.curve = self.plot.plot(pen=pg.mkPen('#00d1b2', width=2))
        self.vLine = pg.InfiniteLine(angle=90, movable=False, pen='#666')
        self.plot.addItem(self.vLine, ignoreBounds=True)
        self.plot.scene().sigMouseMoved.connect(self._on_hover)
        dash.addWidget(self.plot)

        # Data Panel
        bot_layout = QHBoxLayout()
        bot_widget = QWidget()
        bot_widget.setLayout(bot_layout)
        
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["ID", "Time", "Status"])
        self.table.setColumnHidden(0, True)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        bot_layout.addWidget(self.table, 1)

        self.path_view = QTextEdit()
        self.path_view.setReadOnly(True)
        self.path_view.setPlaceholderText("Node path details...")
        self.path_view.setStyleSheet("background-color: #222; border: 1px solid #333; color: #00d1b2; font-family: Consolas;")
        bot_layout.addWidget(self.path_view, 3)
        
        dash.addWidget(bot_widget)
        dash.setStretchFactor(0, 5)
        dash.setStretchFactor(1, 2)
        main_layout.addWidget(dash)

        self.status = QStatusBar()
        self.setStatusBar(self.status)

    def _start_engine(self):
        self.tracer.stop()
        self.tracer.start_monitoring(self.db.get_servers())

    def _update_server_list(self):
        self.server_list.clear()
        for s in self.db.get_servers():
            self.server_list.addItem(s['server'])

    def _add_server(self):
        dlg = AddServerDlg(self)
        if dlg.exec():
            addr, port = dlg.get_info()
            if addr and self.db.add_server(addr, port):
                self._update_server_list()
                self._start_engine()

    def _remove_server(self):
        item = self.server_list.currentItem()
        if item:
            self.db.remove_server(item.text())
            self._update_server_list()
            self._start_engine()

    def _purge_data(self):
        if QMessageBox.question(self, "Purge", "Delete all traces?") == QMessageBox.Yes:
            self.db.clear_history()
            self._safe_refresh()

    def _on_server_selected(self, item):
        self.current_server = item.text()
        self.first_load = True
        self.last_hover_id = -1
        self._safe_refresh()

    def _on_hover(self, pos):
        if self.plot.sceneBoundingRect().contains(pos):
            mouse_pt = self.plot.getViewBox().mapSceneToView(pos)
            self.vLine.setPos(mouse_pt.x())
            if self.current_df is not None and not self.current_df.empty:
                x_vals = self.current_df['ts'].values
                idx = (np.abs(x_vals - mouse_pt.x())).argmin()
                view_range = self.plot.viewRange()[0]
                if abs(mouse_pt.x() - x_vals[idx]) < (view_range[1] - view_range[0]) * 0.03:
                    tid = int(self.current_df.iloc[idx]['id'])
                    if tid != self.last_hover_id:
                        self.last_hover_id = tid
                        self._show_path(tid, str(self.current_df.iloc[idx]['timestamp']), pos)
                else:
                    self.last_hover_id = -1
                    QToolTip.hideText()

    def _on_row_selected(self):
        row = self.table.currentRow()
        if row >= 0:
            tid = int(self.table.item(row, 0).text())
            ts = self.table.item(row, 1).text()
            self._show_path(tid, ts)

    def _show_path(self, tid, ts, pos=None):
        hops = self.db.get_hops(tid)
        txt = f"<b>PATH (ID: {tid})</b><br><small>{ts}</small><br><br>"
        tip = f"Trace {tid} | {ts}\n" + "-"*20 + "\n"
        if not hops:
            txt += "<i>No nodes.</i>"
            tip += "No nodes."
        else:
            for h in hops:
                line = f"H{h[0]}: {h[1]:.1f}ms -> {h[2]}"
                txt += f"H{h[0]}: <b style='color:#00d1b2;'>{h[1]:.1f}ms</b> &nbsp; {h[2]}<br>"
                tip += line + "\n"
        self.path_view.setHtml(txt)
        if pos:
            g_pos = self.plot.viewport().mapToGlobal(self.plot.mapFromScene(pos))
            QToolTip.showText(g_pos, tip, self.plot, QRect(), 600000)

    def _safe_refresh(self):
        if not self.current_server: return
        try:
            data = self.db.get_latency_data(self.current_server)
            if not data: return
            
            df = pd.DataFrame(data, columns=['id', 'timestamp', 'rtt', 'status'])
            df['ts'] = pd.to_datetime(df['timestamp']).apply(lambda x: x.timestamp())
            df = df.sort_values('ts')
            self.current_df = df
            
            self.curve.setData(df['ts'].values, df['rtt'].values)
            
            max_rtt = df['rtt'].max()
            y_high = max(1000, max_rtt * 1.05)
            max_ts = df['ts'].max()
            
            self.plot.setYRange(0, y_high, padding=0)
            self.plot.getViewBox().setLimits(xMax=max_ts)
            
            view_range = self.plot.viewRange()[0]
            current_span = view_range[1] - view_range[0]
            is_at_edge = abs(view_range[1] - max_ts) < (current_span * 0.05)
            
            if self.first_load or is_at_edge:
                span = 3600 if self.first_load else current_span
                self.plot.setXRange(max_ts - span, max_ts, padding=0)
                self.first_load = False

            self.table.setRowCount(0)
            for _, r in df.iloc[::-1].iterrows():
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(str(int(r['id']))))
                self.table.setItem(row, 1, QTableWidgetItem(str(r['timestamp'])))
                self.table.setItem(row, 2, QTableWidgetItem(str(r['status'])))
                
            self.status.showMessage(f"Live Sync: {datetime.now().strftime('%H:%M:%S')}")
        except Exception as e:
            self.status.showMessage(f"Sync Interrupted: {e}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
