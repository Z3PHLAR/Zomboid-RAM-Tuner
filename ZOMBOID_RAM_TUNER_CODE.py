"""Windows Project Zomboid client RAM picker. Requires: py -m pip install PySide6
Run with Python or pythonw. Close Zomboid before applying changes.
This standalone utility must be run manually; subscribing on Workshop alone
will not run it or change the game's launcher settings.
"""
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from datetime import datetime
import sys
from PySide6.QtCore import Qt, QUrl, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap, QDesktopServices
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QComboBox, QLineEdit, QPushButton, QFileDialog, QMessageBox,
    QFrame, QGraphicsView, QGraphicsScene)
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem

CHOICES = [(3, '3 GB — Default'), (4, '4 GB'), (6, '6 GB'),
           (8, '8 GB'), (10, '10 GB'), (12, '12 GB'), (16, '16 GB')]
HEAP = re.compile(r'^-Xmx\d+[kKmMgG]?$')


def steam_roots():
    import winreg
    roots = []
    locations = [
        (winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamPath'),
        (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Valve\Steam', 'InstallPath'),
    ]
    for hive, key, value in locations:
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view) as handle:
                    roots.append(Path(winreg.QueryValueEx(handle, value)[0]))
            except OSError:
                pass
    for env in ('ProgramFiles(x86)', 'ProgramFiles'):
        if os.environ.get(env):
            roots.append(Path(os.environ[env]) / 'Steam')
    return list(dict.fromkeys(roots))


def vdf_values(text, key):
    pattern = r'"' + re.escape(key) + r'"\s*"((?:\\.|[^"\\])*)"'
    # VDF uses escaped backslashes and quotes, not Python unicode escapes.
    return [v.replace('\\\\', '\\').replace('\\"', '"')
            for v in re.findall(pattern, text, re.IGNORECASE)]


def discover():
    roots = steam_roots()
    libraries = list(roots)
    for root in roots:
        try:
            data = (root / 'steamapps' / 'libraryfolders.vdf').read_text(encoding='utf-8-sig')
            libraries.extend(Path(p) for p in vdf_values(data, 'path'))
        except OSError:
            pass
    found = []
    for library in dict.fromkeys(libraries):
        apps = library / 'steamapps'
        folders = [apps / 'common' / 'ProjectZomboid']
        try:
            manifest = (apps / 'appmanifest_108600.acf').read_text(encoding='utf-8-sig')
            for directory in vdf_values(manifest, 'installdir'):
                candidate = apps / 'common' / directory
                if candidate.resolve().is_relative_to((apps / 'common').resolve()):
                    folders.insert(0, candidate)
        except OSError:
            pass
        for folder in folders:
            config = folder / 'ProjectZomboid64.json'
            if config.is_file() and config.resolve() not in found:
                found.append(config.resolve())
    return found


def load_config(path):
    raw = path.read_bytes()
    config = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(config, dict) or not isinstance(config.get('vmArgs'), list):
        raise ValueError('This file does not contain a valid top-level vmArgs list.')
    if not all(isinstance(arg, str) for arg in config['vmArgs']):
        raise ValueError('The vmArgs list contains unexpected non-text values.')
    if 'mainClass' not in config:
        raise ValueError('This does not look like a Zomboid launcher configuration.')
    return raw, config


def current_limit(config):
    limits = [a for a in config['vmArgs'] if a.startswith('-Xmx')]
    return ', '.join(limits) if limits else 'No explicit limit'


def apply_limit(path, gb):
    if gb not in dict(CHOICES):
        raise ValueError('Unsupported RAM selection.')
    raw, config = load_config(path)
    args = config['vmArgs']
    if any(a.startswith('-Xmx') and not HEAP.fullmatch(a) for a in args):
        raise ValueError('Unrecognized -Xmx setting; no changes made.')
    # A minimum heap greater than the selected maximum would prevent startup.
    for arg in args:
        if arg.startswith('-Xms'):
            match = re.fullmatch(r'-Xms(\d+)([kKmMgG]?)', arg)
            if not match:
                raise ValueError('Unrecognized -Xms setting; no changes made.')
            number, unit = match.groups()
            minimum = int(number) * {'': 1, 'k': 1024, 'm': 1024**2, 'g': 1024**3}[unit.lower()]
            if minimum > gb * 1024**3:
                raise ValueError('Your existing -Xms minimum exceeds this limit. '
                                 'Lower or remove -Xms first; no changes made.')
    replacement = f'-Xmx{gb * 1024}m'
    updated = []
    inserted = False
    for arg in args:
        if arg.startswith('-Xmx'):
            if not inserted:
                updated.append(replacement)
                inserted = True
        else:
            updated.append(arg)
    if not inserted:
        updated.append(replacement)
    if updated == args:
        return None
    config['vmArgs'] = updated
    newline = '\r\n' if b'\r\n' in raw else '\n'
    output = (json.dumps(config, indent='\t', ensure_ascii=False) + '\n').replace('\n', newline).encode('utf-8')
    if raw.startswith(b'\xef\xbb\xbf'):
        output = b'\xef\xbb\xbf' + output
    backup = path.with_name(path.name + '.' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.bak')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='pz_ram_', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(output)
            stream.flush()
            os.fsync(stream.fileno())
        # Detect another editor changing the file before replacing it.
        if path.read_bytes() != raw:
            raise RuntimeError('The configuration changed while being edited. Try again.')
        shutil.copy2(path, backup)
        os.replace(temporary, path)
        return backup
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


STYLE = """
QWidget { color: #d2dde6; font-family: 'Segoe UI'; font-size: 14px; font-weight: bold; }
QFrame#panel { background-color: rgba(6, 12, 19, 65);
    border: 1px solid #385a75; border-radius: 12px; }
QLabel { background: transparent; border: none; }
QLabel#title { color: #b5ccde; font-size: 26px; font-weight: bold; }
QLabel#subtitle, QLabel#note { color: #91a8ba; }
QLineEdit { background-color: #101c28; color: #e4edf5;
    border: 1px solid #6387a3; border-radius: 5px; padding: 10px; }
QComboBox { background-color: #101c28; color: #e4edf5;
    border: 1px solid #6387a3; border-radius: 5px;
    padding: 10px; padding-right: 42px; }
QComboBox::drop-down { subcontrol-origin: padding;
    subcontrol-position: top right; width: 34px;
    background-color: #29465e; border-left: 1px solid #789ab4;
    border-top-right-radius: 4px; border-bottom-right-radius: 4px; }
QComboBox::down-arrow { image: url("__ARROW_PATH__"); width: 14px; height: 9px; }
QComboBox::drop-down:hover { background-color: #3d627f; }
QComboBox QAbstractItemView { background-color: #121d27; color: #d2dde6;
    selection-background-color: #385a75; }
QPushButton { background-color: #172939; border: 1px solid #385a75;
    border-radius: 5px; padding: 10px 16px; }
QPushButton#apply { background-color: #294b65; color: #f0f6fb;
    border: 1px solid #83a8c3; font-weight: bold; padding: 12px 16px; }
QPushButton#apply:hover { background-color: #3c6685; border-color: #b4d3e9; }
QPushButton#apply:pressed { background-color: #1d384e; }
QPushButton:hover { background-color: #385a75; }
QPushButton:pressed { background-color: #29445a; }
QMessageBox, QFileDialog { background-color: #0b121a; }
"""


def window_icon():
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor('#080c10'))
    painter = QPainter(pixmap)
    painter.fillRect(0, 0, 64, 5, QColor('#385a75'))
    painter.setPen(QColor('#b5ccde'))
    painter.setFont(QFont('Segoe UI', 25, QFont.Weight.Bold))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, 'PZ')
    painter.end()
    return QIcon(pixmap)


def video_path():
    # Beside the executable/script takes priority for portable distribution.
    folder = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
    candidates = [folder / 'slow.mp4']
    if getattr(sys, '_MEIPASS', None):
        candidates.append(Path(sys._MEIPASS) / 'slow.mp4')
    candidates.append(Path.home() / 'Desktop' / 'slow.mp4')
    return next((path for path in candidates if path.is_file()), None)


class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Project Zomboid — RAM Picker')
        self.setWindowIcon(window_icon())
        self.resize(900, 660)
        self.setMinimumSize(760, 620)
        # Generate the arrow locally so no separate image download is needed.
        import atexit
        self._arrow_folder = tempfile.TemporaryDirectory(prefix='pz_ram_icons_')
        atexit.register(self._arrow_folder.cleanup)
        arrow_path = Path(self._arrow_folder.name) / 'down.png'
        arrow = QPixmap(28, 18)
        arrow.fill(Qt.GlobalColor.transparent)
        painter = QPainter(arrow)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#e1f1ff'))
        from PySide6.QtGui import QPolygon
        from PySide6.QtCore import QPoint
        painter.drawPolygon(QPolygon([QPoint(2, 2), QPoint(26, 2), QPoint(14, 16)]))
        painter.end()
        if not arrow.save(str(arrow_path)):
            raise RuntimeError('Could not create the dropdown arrow image.')
        self.setStyleSheet(STYLE.replace('__ARROW_PATH__', arrow_path.as_posix()))
        self.surface = QWidget()
        self.surface.setObjectName('videoSurface')
        self.surface.setStyleSheet('QWidget#videoSurface { background-color: #080c10; }')
        self.setCentralWidget(self.surface)

        # A graphics video item supports ordinary widgets layered above video.
        self.scene = QGraphicsScene(self)
        self.scene.setBackgroundBrush(QColor('#080c10'))
        self.video = QGraphicsVideoItem()
        self.video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.scene.addItem(self.video)
        self.view = QGraphicsView(self.scene, self.surface)
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setInteractive(False)
        self.view.setStyleSheet('background: #080c10; border: none;')
        self.video.nativeSizeChanged.connect(self.fit_video)
        self.player = QMediaPlayer(self)
        self.player.setVideoOutput(self.video)
        # No audio output is attached: playback is silent.
        self.player.setLoops(QMediaPlayer.Loops.Infinite)
        self.player.errorOccurred.connect(self.video_error)

        self.overlay = QWidget(self.surface)
        self.overlay.setObjectName('overlay')
        self.overlay.setStyleSheet('QWidget#overlay { background-color: rgba(0, 0, 0, 18); }')
        outer = QVBoxLayout(self.overlay)
        outer.setContentsMargins(34, 24, 34, 24)
        outer.addStretch()
        panel = QFrame()
        panel.setObjectName('panel')
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(12)
        title = QLabel('PROJECT ZOMBOID RAM')
        title.setObjectName('title')
        layout.addWidget(title)
        subtitle = QLabel('Close the game, choose a limit, then apply.')
        subtitle.setObjectName('subtitle')
        layout.addWidget(subtitle)
        layout.addWidget(QLabel('Game configuration'))
        self.paths = QLineEdit()
        self.paths.setReadOnly(True)
        self.paths.setPlaceholderText('ProjectZomboid64.json location')
        layout.addWidget(self.paths)
        browse = QPushButton('Browse if not found…')
        browse.clicked.connect(self.browse)
        browse_row = QHBoxLayout()
        browse_row.addWidget(browse)
        browse_row.addStretch()
        layout.addLayout(browse_row)
        example = QLabel(r'Example: ...steamapps\common\ProjectZomboid\ProjectZomboid64.json')
        example.setObjectName('note')
        example.setWordWrap(True)
        layout.addWidget(example)
        self.status = QLabel('Detecting Steam installation…')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addWidget(QLabel('Maximum Java heap'))
        self.selection = QComboBox()
        for gb, label in CHOICES:
            self.selection.addItem(label, gb)
        layout.addWidget(self.selection)
        note = QLabel('Default restores the 3 GB heap limit. Total game memory can exceed this limit.\n'
                      'More RAM does not automatically mean more FPS. A backup is made before each change.')
        note.setWordWrap(True)
        note.setObjectName('note')
        layout.addWidget(note)
        self.video_status = QLabel()
        self.video_status.setObjectName('note')
        self.video_status.setWordWrap(True)
        layout.addWidget(self.video_status)
        apply_button = QPushButton('Apply RAM limit')
        apply_button.setObjectName('apply')
        apply_button.clicked.connect(self.apply)
        layout.addWidget(apply_button)
        outer.addWidget(panel)
        outer.addStretch()
        self.overlay.raise_()
        QTimer.singleShot(0, self.detect)
        source = video_path()
        if source:
            self.player.setSource(QUrl.fromLocalFile(str(source)))
            self.player.play()
        else:
            self.video_status.setText('Background video not found. Put slow.mp4 beside this program.')

    def fit_video(self, *unused):
        rect = self.view.viewport().rect()
        self.scene.setSceneRect(0, 0, rect.width(), rect.height())
        native = self.video.nativeSize()
        if native.width() > 0 and native.height() > 0:
            scale = max(rect.width() / native.width(), rect.height() / native.height())
            self.video.setSize(native * scale)
            self.video.setPos((rect.width() - native.width() * scale) / 2,
                              (rect.height() - native.height() * scale) / 2)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'overlay'):
            self.view.setGeometry(self.surface.rect())
            self.overlay.setGeometry(self.surface.rect())
            self.fit_video()

    def video_error(self, *unused):
        self.player.stop()
        self.view.hide()
        self.video_status.setText('Background video could not play. RAM controls are still available.')

    def detect(self):
        try:
            paths = discover()
            if paths:
                self.paths.setText(str(paths[0]))
                self.paths.setToolTip(str(paths[0]))
                self.refresh()
            else:
                self.status.setText('Zomboid was not found automatically. Use Browse to select ProjectZomboid64.json.')
        except Exception as error:
            self.status.setText(f'Automatic detection failed: {error}. Use Browse.')

    def browse(self):
        selected, _ = QFileDialog.getOpenFileName(self, 'Select ProjectZomboid64.json', '',
                        'Zomboid configuration (ProjectZomboid64.json);;JSON files (*.json)')
        if selected:
            self.paths.setText(selected)
            self.paths.setToolTip(selected)
            self.refresh()

    def backup_message(self, backup, text):
        dialog = QMessageBox(self)
        dialog.setWindowTitle('Backup created')
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setText(text)
        dialog.setInformativeText(f'Backup saved here:\n{backup}')
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        browse = dialog.addButton('Browse Folder', QMessageBox.ButtonRole.ActionRole)
        dialog.setDefaultButton(QMessageBox.StandardButton.Ok)
        dialog.exec()
        if dialog.clickedButton() == browse:
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(backup.parent))):
                QMessageBox.warning(self, 'Could not open folder', str(backup.parent))

    def refresh(self, *unused):
        if not self.paths.text():
            return
        try:
            _, config = load_config(Path(self.paths.text()))
            self.status.setText('Current limit: ' + current_limit(config))
            for index, (gb, _) in enumerate(CHOICES):
                if any(arg.lower() in (f'-xmx{gb * 1024}m', f'-xmx{gb}g') for arg in config['vmArgs']):
                    self.selection.setCurrentIndex(index)
                    break
        except Exception as error:
            self.status.setText(f'Cannot read configuration: {error}')

    def apply(self):
        if not self.paths.text():
            QMessageBox.warning(self, 'No configuration selected', 'Select ProjectZomboid64.json first.')
            return
        try:
            gb = self.selection.currentData()
            backup = apply_limit(Path(self.paths.text()), gb)
            self.refresh()
            if backup is None:
                QMessageBox.information(self, 'Already set', f'The limit is already {gb} GB.')
            else:
                self.backup_message(backup,
                    f'RAM limit set to {gb} GB. A backup of the previous configuration was created. '
                    'Start Zomboid to use the new limit.')
        except Exception as error:
            QMessageBox.critical(self, 'Could not apply setting', str(error))

    def closeEvent(self, event):
        self.player.stop()
        super().closeEvent(event)


def main():
    application = QApplication(sys.argv)
    application.setStyle('Fusion')
    if os.name != 'nt':
        QMessageBox.critical(None, 'Windows required', 'This version is for Steam on Windows.')
        return
    window = App()
    window.show()
    sys.exit(application.exec())


if __name__ == '__main__':
    main()
