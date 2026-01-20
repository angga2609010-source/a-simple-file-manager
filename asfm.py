#!/usr/bin/env python3
"""
ASFM - A Simple File Manager / AnggaSabber File Manager
A Linux-like file explorer built with PyQt6

Setup:
    pip install PyQt6

Run:
    python3 asfm.py

Requirements:
    - Python 3.7+
    - PyQt6
    - Linux system (for native file operations)
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional
from datetime import datetime

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTreeView, QToolBar, QMenuBar, QMenu, QStatusBar,
    QLineEdit, QPushButton, QLabel, QMessageBox, QInputDialog,
    QFileDialog, QCheckBox, QDialog, QDialogButtonBox, QHeaderView,
    QFileIconProvider, QStyledItemDelegate, QStyleOptionViewItem, QToolTip,
    QComboBox, QAbstractItemView
)
from PyQt6.QtCore import (
    Qt, QDir, QModelIndex, QMimeData, pyqtSignal,
    QItemSelectionModel, QUrl, QPoint, QSize, QRect, QTimer
)
from PyQt6.QtGui import (
    QIcon, QAction, QKeySequence, QDesktopServices,
    QPixmap, QPainter, QFileSystemModel, QFontMetrics, QPen, QBrush, QColor
)


class TreeViewDelegate(QStyledItemDelegate):
    """Custom delegate for tree view with better text handling and tooltips"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
    
    def sizeHint(self, option, index):
        """Return size hint for items with better spacing"""
        size = super().sizeHint(option, index)
        # Ensure minimum height for better readability
        size.setHeight(max(size.height(), 22))
        return size
    
    def helpEvent(self, event, view, option, index):
        """Show tooltip with full path when hovering over items"""
        if event is not None:
            model = index.model()
            if isinstance(model, QFileSystemModel):
                file_path = model.filePath(index)
                file_name = model.fileName(index)
                
                # Only show tooltip if the text is actually elided
                if event.type() == event.Type.ToolTip:
                    # Calculate if text would be elided
                    text_rect = option.rect
                    font_metrics = QFontMetrics(option.font)
                    text_width = text_rect.width() - 40  # Account for icon and padding
                    elided_text = font_metrics.elidedText(
                        file_name, 
                        Qt.TextElideMode.ElideMiddle, 
                        text_width
                    )
                    
                    # Show tooltip if text is elided or if it's a long path
                    if elided_text != file_name or len(file_path) > 50:
                        QToolTip.showText(event.globalPos(), file_path, view)
                        return True
        return super().helpEvent(event, view, option, index)


class TrashManager:
    """Manages trash/recycle bin operations"""
    
    def __init__(self):
        # Try to use system trash first, fallback to local trash
        self.trash_dir = Path.home() / ".local" / "share" / "Trash"
        self.trash_files_dir = self.trash_dir / "files"
        self.trash_info_dir = self.trash_dir / "info"
        
        # Create trash directories if they don't exist
        self.trash_files_dir.mkdir(parents=True, exist_ok=True)
        self.trash_info_dir.mkdir(parents=True, exist_ok=True)
    
    def move_to_trash(self, file_path: Path) -> bool:
        """Move a file or directory to trash"""
        try:
            if not file_path.exists():
                return False
            
            # Generate unique name for trash
            base_name = file_path.name
            counter = 0
            trash_path = self.trash_files_dir / base_name
            
            while trash_path.exists():
                counter += 1
                name, ext = os.path.splitext(base_name)
                trash_path = self.trash_files_dir / f"{name}_{counter}{ext}"
            
            # Create trash info file
            info_file = self.trash_info_dir / f"{trash_path.name}.trashinfo"
            with open(info_file, 'w') as f:
                f.write("[Trash Info]\n")
                f.write(f"Path={file_path}\n")
                f.write(f"DeletionDate={datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}\n")
            
            # Move file to trash
            shutil.move(str(file_path), str(trash_path))
            return True
        except Exception as e:
            print(f"Error moving to trash: {e}")
            return False
    
    def empty_trash(self) -> bool:
        """Empty the trash directory"""
        try:
            # Remove all files in trash
            for file in self.trash_files_dir.iterdir():
                if file.is_file() or file.is_dir():
                    if file.is_dir():
                        shutil.rmtree(file)
                    else:
                        file.unlink()
            
            # Remove all info files
            for info_file in self.trash_info_dir.iterdir():
                if info_file.suffix == '.trashinfo':
                    info_file.unlink()
            
            return True
        except Exception as e:
            print(f"Error emptying trash: {e}")
            return False
    
    def get_trash_size(self) -> int:
        """Get the number of items in trash"""
        try:
            return len(list(self.trash_files_dir.iterdir()))
        except:
            return 0


class FileBrowser(QWidget):
    """Main file browser widget with tree and list views"""
    
    # Signals
    path_changed = pyqtSignal(str)
    selection_changed = pyqtSignal(list)
    
    def __init__(self, parent=None, trash_manager=None):
        super().__init__(parent)
        self.current_path = Path.home()
        self.show_hidden = False
        self.clipboard_paths = []
        self.clipboard_mode = None  # 'copy' or 'cut'
        self.navigation_history = []
        self.history_index = -1
        self.trash_manager = trash_manager  # Store reference to trash manager
        
        self.setup_ui()
        self.setup_model()
        self.connect_signals()
        
        # Navigate to home directory
        self.navigate_to(str(self.current_path))
    
    def setup_ui(self):
        """Setup the UI components"""
        # Main horizontal layout
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Left panel with tree view and collapse button
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        
        # Tree controls (collapse button with triangle indicator)
        tree_controls = QHBoxLayout()
        tree_controls.setContentsMargins(6, 6, 6, 6)
        
        # Create a label with triangle indicator (clickable)
        self.triangle_label = QLabel("▼")
        self.triangle_label.setToolTip("Click to collapse all folders")
        self.triangle_label.mousePressEvent = lambda e: self.collapse_all_folders()
        self.triangle_label.setCursor(Qt.CursorShape.PointingHandCursor)
        
        self.collapse_tree_btn = QPushButton("Collapse All")
        self.collapse_tree_btn.setToolTip("Collapse all expanded folders in tree view")
        self.collapse_tree_btn.clicked.connect(self.collapse_all_folders)
        
        tree_controls.addWidget(self.triangle_label)
        tree_controls.addWidget(self.collapse_tree_btn)
        tree_controls.addStretch()
        left_layout.addLayout(tree_controls)
        
        # Create splitter for resizable panels
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Tree view (left panel) - Directory navigation
        # Improved styling inspired by Thunar and Windows Explorer
        self.tree_view = QTreeView()
        self.tree_view.setHeaderHidden(True)
        self.tree_view.setAnimated(True)
        self.tree_view.setIndentation(18)  # Slightly reduced indentation for better space usage
        self.tree_view.setRootIsDecorated(True)  # Show expand/collapse indicators
        self.tree_view.setItemsExpandable(True)
        self.tree_view.setExpandsOnDoubleClick(False)  # Don't expand on double click
        self.tree_view.setUniformRowHeights(True)  # Uniform row heights for better performance
        self.tree_view.setAlternatingRowColors(False)  # Cleaner look for tree view
        self.tree_view.setSelectionBehavior(QTreeView.SelectionBehavior.SelectRows)
        self.tree_view.setSelectionMode(QTreeView.SelectionMode.ExtendedSelection)  # Enable multiselect
        self.tree_view.setTextElideMode(Qt.TextElideMode.ElideMiddle)  # Elide text in the middle for long names
        self.tree_view.setWordWrap(False)  # Don't wrap text, elide instead
        
        # Set minimum width to ensure folder names are visible
        self.tree_view.setMinimumWidth(240)
        self.tree_view.setMaximumWidth(450)
        
        # Enable tooltips
        self.tree_view.setMouseTracking(True)
        
        # Set custom delegate for better text handling and tooltips
        self.tree_delegate = TreeViewDelegate(self.tree_view)
        self.tree_view.setItemDelegate(self.tree_delegate)
        
        # Apply flat styling with simple shadows
        self.tree_view.setStyleSheet("""
            QTreeView {
                border: none;
                background-color: #ffffff;
                outline: none;
                selection-background-color: #e3f2fd;
                selection-color: #1976d2;
            }
            QTreeView::item {
                height: 24px;
                padding: 3px;
                border: none;
                background-color: transparent;
            }
            QTreeView::item:hover {
                background-color: #f5f5f5;
                color: #212121;
            }
            QTreeView::item:selected {
                background-color: #e3f2fd;
                color: #1976d2;
                border: none;
            }
            QTreeView::branch {
                background-color: transparent;
            }
            QTreeView::branch:has-siblings:!adjoins-item {
                border-image: none;
            }
        """)
        
        # File list view (right panel) - Use QTreeView in Details mode for Linux-like experience
        self.list_view = QTreeView()
        self.list_view.setRootIsDecorated(False)  # No tree branches for files
        self.list_view.setSortingEnabled(True)  # Enable sorting by columns
        self.list_view.setAlternatingRowColors(True)  # Zebra striping
        self.list_view.setSelectionMode(QTreeView.SelectionMode.ExtendedSelection)  # Enable multiselect
        self.list_view.setSelectionBehavior(QTreeView.SelectionBehavior.SelectRows)
        
        # Apply flat styling with simple shadows
        self.list_view.setStyleSheet("""
            QTreeView {
                border: none;
                background-color: #ffffff;
                outline: none;
                alternate-background-color: #fafafa;
                selection-background-color: #e3f2fd;
                selection-color: #1976d2;
            }
            QTreeView::item {
                height: 24px;
                padding: 4px;
                border: none;
            }
            QTreeView::item:hover {
                background-color: #f5f5f5;
                color: #212121;
            }
            QTreeView::item:selected {
                background-color: #e3f2fd;
                color: #1976d2;
                border: none;
            }
            QHeaderView::section {
                background-color: #f5f5f5;
                color: #212121;
                padding: 6px;
                border: none;
                border-bottom: 2px solid #e0e0e0;
                font-weight: 500;
            }
            QHeaderView::section:hover {
                background-color: #eeeeee;
            }
        """)
        
        # Add tree view to left panel
        left_layout.addWidget(self.tree_view)
        
        # Add views to splitter
        splitter.addWidget(left_panel)
        splitter.addWidget(self.list_view)
        splitter.setSizes([250, 750])  # Initial sizes - wider tree view for better visibility
        splitter.setCollapsible(0, False)  # Prevent tree view from being collapsed
        splitter.setCollapsible(1, False)  # Prevent list view from being collapsed
        
        main_layout.addWidget(splitter)
    
    def setup_model(self):
        """Setup file system models"""
        # Tree model - show directories only, start with user directory
        self.tree_model = QFileSystemModel()
        # Set root to user's home directory to hide other folders initially
        user_home = str(Path.home())
        self.tree_model.setRootPath(user_home)
        self.tree_model.setFilter(QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot)
        
        # Set icon provider before setting model
        icon_provider = QFileIconProvider()
        self.tree_model.setIconProvider(icon_provider)
        
        # Set model
        self.tree_view.setModel(self.tree_model)
        
        # Set root index to user's home directory
        root_index = self.tree_model.index(user_home)
        self.tree_view.setRootIndex(root_index)
        
        # Hide all columns except the name column (index 0)
        for i in range(1, self.tree_model.columnCount()):
            self.tree_view.hideColumn(i)
        
        # Set column width to fill available space and enable text elision
        header = self.tree_view.header()
        header.setStretchLastSection(True)
        header.setDefaultSectionSize(200)  # Default width for the name column
        header.setMinimumSectionSize(100)  # Minimum width to ensure some text is visible
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Stretch to fill available space
        
        # List model
        self.list_model = QFileSystemModel()
        self.list_model.setRootPath("")
        self.list_model.setFilter(
            QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot
        )
        self.list_view.setModel(self.list_model)
        
        # Configure list view columns (Name, Size, Type, Date Modified)
        header = self.list_view.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Name column stretches
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  # Size
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # Type
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # Date Modified
        
        # Set initial column widths
        self.list_view.setColumnWidth(0, 300)  # Name column
        self.list_view.setColumnWidth(1, 80)   # Size column
        self.list_view.setColumnWidth(2, 100)  # Type column
        self.list_view.setColumnWidth(3, 150)  # Date Modified column
        
        # Use native icons
        icon_provider = QFileIconProvider()
        self.tree_model.setIconProvider(icon_provider)
        self.list_model.setIconProvider(icon_provider)
    
    def connect_signals(self):
        """Connect signals and slots"""
        # Tree view selection
        self.tree_view.selectionModel().selectionChanged.connect(
            self.on_tree_selection_changed
        )
        
        # List view selection
        self.list_view.selectionModel().selectionChanged.connect(
            self.on_list_selection_changed
        )
        
        # Double click on list view
        self.list_view.doubleClicked.connect(self.on_list_double_clicked)
        
        # Tree view clicked
        self.tree_view.clicked.connect(self.on_tree_clicked)
        
        # Enable context menus
        self.tree_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_view.customContextMenuRequested.connect(self.on_tree_context_menu)
        
        self.list_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_view.customContextMenuRequested.connect(self.on_list_context_menu)
    
    def update_hidden_filter(self, show_hidden: bool):
        """Update the hidden files filter"""
        self.show_hidden = show_hidden
        list_filters = QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot
        tree_filters = QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot
        
        if show_hidden:
            list_filters |= QDir.Filter.Hidden
            tree_filters |= QDir.Filter.Hidden
        else:
            list_filters &= ~QDir.Filter.Hidden
            tree_filters &= ~QDir.Filter.Hidden
        
        self.list_model.setFilter(list_filters)
        self.tree_model.setFilter(tree_filters)
        
        # Refresh views
        self.refresh()
    
    def _navigate_to_path(self, path: str, add_to_history: bool = True):
        """Internal method to navigate to a path"""
        path_obj = Path(path)
        if not path_obj.exists():
            return
        
        self.current_path = path_obj.resolve()
        
        # Update list view
        index = self.list_model.index(str(self.current_path))
        self.list_view.setRootIndex(index)
        
        # Update tree view
        index = self.tree_model.index(str(self.current_path))
        self.tree_view.setExpanded(index, True)
        self.tree_view.setCurrentIndex(index)
        self.tree_view.scrollTo(index)
        
        # Add to history if requested
        if add_to_history:
            path_str = str(self.current_path)
            if not self.navigation_history or self.navigation_history[self.history_index] != path_str:
                # Remove future history if we're not at the end
                if self.history_index < len(self.navigation_history) - 1:
                    self.navigation_history = self.navigation_history[:self.history_index + 1]
                self.navigation_history.append(path_str)
                self.history_index = len(self.navigation_history) - 1
        
        # Emit signal
        self.path_changed.emit(str(self.current_path))
    
    def navigate_to(self, path: str):
        """Navigate to a specific path"""
        self._navigate_to_path(path, add_to_history=True)
    
    def navigate_up(self):
        """Navigate to parent directory"""
        if self.current_path.parent != self.current_path:
            self.navigate_to(str(self.current_path.parent))
    
    def navigate_back(self):
        """Navigate back in history"""
        if self.history_index > 0:
            self.history_index -= 1
            self._navigate_to_path(self.navigation_history[self.history_index], add_to_history=False)
    
    def navigate_forward(self):
        """Navigate forward in history"""
        if self.history_index < len(self.navigation_history) - 1:
            self.history_index += 1
            self._navigate_to_path(self.navigation_history[self.history_index], add_to_history=False)
    
    def on_tree_selection_changed(self):
        """Handle tree view selection change"""
        indexes = self.tree_view.selectedIndexes()
        # Only navigate on single selection to avoid conflicts with multiselect
        if len(indexes) == 1:
            index = indexes[0]
            path = self.tree_model.filePath(index)
            if os.path.isdir(path):
                self.navigate_to(path)
    
    def on_tree_clicked(self, index: QModelIndex):
        """Handle tree view click"""
        path = self.tree_model.filePath(index)
        if os.path.isdir(path):
            self.navigate_to(path)
    
    def collapse_all_folders(self):
        """Collapse all expanded folders in the tree view"""
        self.tree_view.collapseAll()
        # Expand root index to show basic structure
        root_index = self.tree_model.index(str(Path.home()))
        if root_index.isValid():
            self.tree_view.expand(root_index)
    
    def open_recycle_bin(self):
        """Open recycle bin directory"""
        if not self.trash_manager:
            return
        trash_path = self.trash_manager.trash_files_dir
        if trash_path.exists():
            self.navigate_to(str(trash_path))
        else:
            QMessageBox.information(self, "Recycle Bin", "Recycle bin is empty or does not exist.")
    
    def on_tree_context_menu(self, position: QPoint):
        """Show context menu for tree view"""
        index = self.tree_view.indexAt(position)
        menu = QMenu(self)
        
        # Add Recycle Bin shortcut at the top
        recycle_bin_action = QAction("🗑️ Recycle Bin", self)
        recycle_bin_action.triggered.connect(self.open_recycle_bin)
        menu.addAction(recycle_bin_action)
        menu.addSeparator()
        
        if not index.isValid():
            # Show menu even if clicking on empty space
            menu.exec(self.tree_view.mapToGlobal(position))
            return
        
        # Get selected items
        selected_indexes = self.tree_view.selectedIndexes()
        selected_paths = [self.tree_model.filePath(idx) for idx in selected_indexes if idx.column() == 0]
        
        # Open action
        open_action = QAction("Open", self)
        open_action.triggered.connect(lambda: self.navigate_to(self.tree_model.filePath(index)))
        menu.addAction(open_action)
        
        menu.addSeparator()
        
        # Rename action
        if len(selected_paths) == 1:
            rename_action = QAction("Rename", self)
            rename_action.triggered.connect(self.rename_selected)
            menu.addAction(rename_action)
        
        # Delete action
        if selected_paths:
            delete_action = QAction(f"Delete ({len(selected_paths)})", self)
            delete_action.triggered.connect(self.delete_selected_tree_items)
            menu.addAction(delete_action)
        
        menu.addSeparator()
        
        # New folder action
        new_folder_action = QAction("New Folder", self)
        new_folder_action.triggered.connect(self.create_new_folder)
        menu.addAction(new_folder_action)
        
        # Show context menu
        menu.exec(self.tree_view.mapToGlobal(position))
    
    def on_list_context_menu(self, position: QPoint):
        """Show context menu for list view"""
        index = self.list_view.indexAt(position)
        selected_paths = self.get_selected_paths()
        
        menu = QMenu(self)
        
        # Open action (only if single file/folder selected)
        if len(selected_paths) == 1:
            path = Path(selected_paths[0])
            if path.is_file():
                open_action = QAction("Open", self)
                open_action.triggered.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))
                menu.addAction(open_action)
            elif path.is_dir():
                open_action = QAction("Open", self)
                open_action.triggered.connect(lambda: self.navigate_to(str(path)))
                menu.addAction(open_action)
            menu.addSeparator()
        
        # Cut, Copy, Paste actions
        if selected_paths:
            cut_action = QAction("Cut", self)
            cut_action.setShortcut(QKeySequence("Ctrl+X"))
            cut_action.triggered.connect(self.cut_selected)
            menu.addAction(cut_action)
            
            copy_action = QAction("Copy", self)
            copy_action.setShortcut(QKeySequence("Ctrl+C"))
            copy_action.triggered.connect(self.copy_selected)
            menu.addAction(copy_action)
        
        # Paste action (if clipboard has items)
        if self.clipboard_paths:
            paste_action = QAction("Paste", self)
            paste_action.setShortcut(QKeySequence("Ctrl+V"))
            paste_action.triggered.connect(lambda: self.paste_files(self.trash_manager))
            menu.addAction(paste_action)
        
        if selected_paths or self.clipboard_paths:
            menu.addSeparator()
        
        # Delete action
        if selected_paths:
            delete_action = QAction(f"Delete ({len(selected_paths)})", self)
            delete_action.setShortcut(QKeySequence("Delete"))
            delete_action.triggered.connect(lambda: self.delete_selected(self.trash_manager))
            menu.addAction(delete_action)
        
        # Rename action (only if single item selected)
        if len(selected_paths) == 1:
            rename_action = QAction("Rename", self)
            rename_action.setShortcut(QKeySequence("F2"))
            rename_action.triggered.connect(self.rename_selected)
            menu.addAction(rename_action)
        
        menu.addSeparator()
        
        # New folder and file actions
        new_folder_action = QAction("New Folder", self)
        new_folder_action.setShortcut(QKeySequence("Ctrl+Shift+N"))
        new_folder_action.triggered.connect(self.create_new_folder)
        menu.addAction(new_folder_action)
        
        new_file_action = QAction("New File", self)
        new_file_action.setShortcut(QKeySequence("Ctrl+Shift+F"))
        new_file_action.triggered.connect(self.create_new_file)
        menu.addAction(new_file_action)
        
        # Show context menu
        menu.exec(self.list_view.mapToGlobal(position))
    
    def delete_selected_tree_items(self):
        """Delete selected items from tree view"""
        selected_indexes = self.tree_view.selectedIndexes()
        selected_paths = [self.tree_model.filePath(idx) for idx in selected_indexes if idx.column() == 0]
        
        if not selected_paths:
            return False
        
        if not self.trash_manager:
            return False
        
        # Confirm deletion
        reply = QMessageBox.question(
            self,
            "Delete Folders",
            f"Move {len(selected_paths)} folder(s) to trash?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.No:
            return False
        
        # Move to trash
        for path in selected_paths:
            self.trash_manager.move_to_trash(Path(path))
        
        self.refresh()
        return True
    
    def on_list_selection_changed(self):
        """Handle list view selection change"""
        indexes = self.list_view.selectedIndexes()
        # Filter to only column 0 (Name column) to get unique rows, not all columns
        selected_paths = [self.list_model.filePath(idx) for idx in indexes if idx.column() == 0]
        self.selection_changed.emit(selected_paths)
    
    def on_list_double_clicked(self, index: QModelIndex):
        """Handle list view double click"""
        path = self.list_model.filePath(index)
        if os.path.isdir(path):
            self.navigate_to(path)
        else:
            # Open file with default application
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
    
    def get_selected_paths(self) -> list:
        """Get currently selected file paths"""
        indexes = self.list_view.selectedIndexes()
        # Filter to only column 0 (Name column) to get unique rows, not all columns
        return [self.list_model.filePath(idx) for idx in indexes if idx.column() == 0]
    
    def get_current_path(self) -> str:
        """Get current directory path"""
        return str(self.current_path)
    
    def refresh(self):
        """Refresh the current view"""
        current = str(self.current_path)
        self.list_model.setRootPath("")
        self.tree_model.setRootPath("")
        self.navigate_to(current)
    
    def copy_selected(self):
        """Copy selected files to clipboard"""
        self.clipboard_paths = self.get_selected_paths()
        self.clipboard_mode = 'copy'
    
    def cut_selected(self):
        """Cut selected files to clipboard"""
        self.clipboard_paths = self.get_selected_paths()
        self.clipboard_mode = 'cut'
    
    def paste_files(self, trash_manager: TrashManager) -> bool:
        """Paste files from clipboard"""
        if not self.clipboard_paths or not self.clipboard_mode:
            return False
        
        dest_dir = self.current_path
        
        for src_path in self.clipboard_paths:
            src = Path(src_path)
            if not src.exists():
                continue
            
            dest = dest_dir / src.name
            
            # Check if destination exists
            if dest.exists():
                reply = QMessageBox.question(
                    self,
                    "File Exists",
                    f"'{dest.name}' already exists. Overwrite?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.No:
                    continue
            
            try:
                if self.clipboard_mode == 'copy':
                    if src.is_dir():
                        shutil.copytree(src, dest, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src, dest)
                elif self.clipboard_mode == 'cut':
                    shutil.move(str(src), str(dest))
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to paste file: {e}")
                return False
        
        # Clear clipboard after cut
        if self.clipboard_mode == 'cut':
            self.clipboard_paths = []
            self.clipboard_mode = None
        
        self.refresh()
        return True
    
    def delete_selected(self, trash_manager: TrashManager) -> bool:
        """Delete selected files (move to trash)"""
        selected = self.get_selected_paths()
        if not selected:
            return False
        
        # Confirm deletion
        reply = QMessageBox.question(
            self,
            "Delete Files",
            f"Move {len(selected)} item(s) to trash?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.No:
            return False
        
        # Move to trash
        for path in selected:
            trash_manager.move_to_trash(Path(path))
        
        self.refresh()
        return True
    
    def rename_selected(self) -> bool:
        """Rename the first selected file"""
        selected = self.get_selected_paths()
        if not selected:
            return False
        
        old_path = Path(selected[0])
        old_name = old_path.name
        
        new_name, ok = QInputDialog.getText(
            self,
            "Rename",
            f"New name for '{old_name}':",
            text=old_name
        )
        
        if not ok or not new_name or new_name == old_name:
            return False
        
        new_path = old_path.parent / new_name
        
        # Check if new name already exists
        if new_path.exists():
            QMessageBox.warning(self, "Error", f"'{new_name}' already exists.")
            return False
        
        try:
            old_path.rename(new_path)
            self.refresh()
            return True
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to rename: {e}")
            return False
    
    def create_new_folder(self) -> bool:
        """Create a new folder in current directory"""
        name, ok = QInputDialog.getText(
            self,
            "New Folder",
            "Folder name:"
        )
        
        if not ok or not name:
            return False
        
        new_path = self.current_path / name
        
        if new_path.exists():
            QMessageBox.warning(self, "Error", f"'{name}' already exists.")
            return False
        
        try:
            new_path.mkdir()
            self.refresh()
            return True
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to create folder: {e}")
            return False
    
    def create_new_file(self) -> bool:
        """Create a new file in current directory"""
        name, ok = QInputDialog.getText(
            self,
            "New File",
            "File name:"
        )
        
        if not ok or not name:
            return False
        
        new_path = self.current_path / name
        
        if new_path.exists():
            QMessageBox.warning(self, "Error", f"'{name}' already exists.")
            return False
        
        try:
            new_path.touch()
            self.refresh()
            return True
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to create file: {e}")
            return False
    
    def get_item_count(self) -> int:
        """Get the number of items in current directory"""
        try:
            index = self.list_model.index(str(self.current_path))
            return self.list_model.rowCount(index)
        except:
            return 0
    
    def apply_theme(self, dark_mode: bool):
        """Apply theme to file browser"""
        self.dark_mode = dark_mode
        self.apply_tree_theme(dark_mode)
        self.apply_list_theme(dark_mode)
        self.apply_button_theme(dark_mode)
    
    def apply_tree_theme(self, dark_mode: bool):
        """Apply theme to tree view"""
        if dark_mode:
            self.tree_view.setStyleSheet("""
                QTreeView {
                    border: none;
                    background-color: #1e1e1e;
                    outline: none;
                    selection-background-color: #0d47a1;
                    selection-color: #ffffff;
                    color: #e0e0e0;
                }
                QTreeView::item {
                    height: 24px;
                    padding: 3px;
                    border: none;
                    background-color: transparent;
                    color: #e0e0e0;
                }
                QTreeView::item:hover {
                    background-color: #2d2d2d;
                    color: #ffffff;
                }
                QTreeView::item:selected {
                    background-color: #0d47a1;
                    color: #ffffff;
                    border: none;
                }
                QTreeView::branch {
                    background-color: transparent;
                }
            """)
        else:
            self.tree_view.setStyleSheet("""
                QTreeView {
                    border: none;
                    background-color: #ffffff;
                    outline: none;
                    selection-background-color: #e3f2fd;
                    selection-color: #1976d2;
                }
                QTreeView::item {
                    height: 24px;
                    padding: 3px;
                    border: none;
                    background-color: transparent;
                }
                QTreeView::item:hover {
                    background-color: #f5f5f5;
                    color: #212121;
                }
                QTreeView::item:selected {
                    background-color: #e3f2fd;
                    color: #1976d2;
                    border: none;
                }
                QTreeView::branch {
                    background-color: transparent;
                }
            """)
    
    def apply_list_theme(self, dark_mode: bool):
        """Apply theme to list view"""
        if dark_mode:
            self.list_view.setStyleSheet("""
                QTreeView {
                    border: none;
                    background-color: #1e1e1e;
                    outline: none;
                    alternate-background-color: #252525;
                    selection-background-color: #0d47a1;
                    selection-color: #ffffff;
                    color: #e0e0e0;
                }
                QTreeView::item {
                    height: 24px;
                    padding: 4px;
                    border: none;
                    color: #e0e0e0;
                }
                QTreeView::item:hover {
                    background-color: #2d2d2d;
                    color: #ffffff;
                }
                QTreeView::item:selected {
                    background-color: #0d47a1;
                    color: #ffffff;
                    border: none;
                }
                QHeaderView::section {
                    background-color: #2d2d2d;
                    color: #e0e0e0;
                    padding: 6px;
                    border: none;
                    border-bottom: 2px solid #3a3a3a;
                    font-weight: 500;
                }
                QHeaderView::section:hover {
                    background-color: #3a3a3a;
                }
            """)
        else:
            self.list_view.setStyleSheet("""
                QTreeView {
                    border: none;
                    background-color: #ffffff;
                    outline: none;
                    alternate-background-color: #fafafa;
                    selection-background-color: #e3f2fd;
                    selection-color: #1976d2;
                }
                QTreeView::item {
                    height: 24px;
                    padding: 4px;
                    border: none;
                }
                QTreeView::item:hover {
                    background-color: #f5f5f5;
                    color: #212121;
                }
                QTreeView::item:selected {
                    background-color: #e3f2fd;
                    color: #1976d2;
                    border: none;
                }
                QHeaderView::section {
                    background-color: #f5f5f5;
                    color: #212121;
                    padding: 6px;
                    border: none;
                    border-bottom: 2px solid #e0e0e0;
                    font-weight: 500;
                }
                QHeaderView::section:hover {
                    background-color: #eeeeee;
                }
            """)
    
    def apply_button_theme(self, dark_mode: bool):
        """Apply theme to buttons"""
        if dark_mode:
            button_style = """
                QPushButton {
                    background-color: #2d2d2d;
                    color: #e0e0e0;
                    border: 1px solid #3a3a3a;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background-color: #3a3a3a;
                    border: 1px solid #4a4a4a;
                }
                QPushButton:pressed {
                    background-color: #1e1e1e;
                }
            """
            triangle_color = "#b0b0b0"
        else:
            button_style = """
                QPushButton {
                    background-color: #f5f5f5;
                    color: #212121;
                    border: 1px solid #e0e0e0;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background-color: #eeeeee;
                    border: 1px solid #bdbdbd;
                }
                QPushButton:pressed {
                    background-color: #e0e0e0;
                }
            """
            triangle_color = "#757575"
        
        self.collapse_tree_btn.setStyleSheet(button_style)
        self.triangle_label.setStyleSheet(f"color: {triangle_color}; font-size: 12px; padding-right: 4px; font-weight: bold;")


class MainWindow(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        self.trash_manager = TrashManager()
        self.dark_mode = False  # Track dark mode state
        self.setup_ui()
        self.setup_menu_bar()
        self.setup_toolbar()
        self.setup_status_bar()
        self.setup_shortcuts()
        self.connect_signals()
        
        # Set window properties
        self.setWindowTitle("ASFM - A Simple File Manager")
        self.setGeometry(100, 100, 1200, 800)
    
    def setup_ui(self):
        """Setup the main UI"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Address bar
        address_layout = QHBoxLayout()
        address_layout.setContentsMargins(5, 5, 5, 5)
        
        self.address_bar = QLineEdit()
        self.address_bar.setPlaceholderText("Enter path or click to navigate...")
        self.address_bar.returnPressed.connect(self.on_address_bar_entered)
        self.address_bar.setStyleSheet("""
            QLineEdit {
                background-color: #ffffff;
                border: 1px solid #e0e0e0;
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 2px solid #2196f3;
                padding: 5px 9px;
            }
        """)
        
        self.refresh_btn = QPushButton("↻")
        self.refresh_btn.setToolTip("Refresh")
        self.refresh_btn.clicked.connect(self.on_refresh)
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #f5f5f5;
                color: #212121;
                border: 1px solid #e0e0e0;
                border-radius: 4px;
                padding: 6px 10px;
                min-width: 30px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #eeeeee;
                border: 1px solid #bdbdbd;
            }
            QPushButton:pressed {
                background-color: #e0e0e0;
            }
        """)
        
        address_layout.addWidget(QLabel("Location:"))
        address_layout.addWidget(self.address_bar)
        address_layout.addWidget(self.refresh_btn)
        
        layout.addLayout(address_layout)
        
        # File browser - pass trash_manager reference
        self.file_browser = FileBrowser(trash_manager=self.trash_manager)
        layout.addWidget(self.file_browser)
    
    def setup_menu_bar(self):
        """Setup the menu bar"""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("File")
        
        self.new_folder_action = QAction("New Folder", self)
        self.new_folder_action.setShortcut(QKeySequence("Ctrl+Shift+N"))
        self.new_folder_action.triggered.connect(self.on_new_folder)
        file_menu.addAction(self.new_folder_action)
        
        self.new_file_action = QAction("New File", self)
        self.new_file_action.setShortcut(QKeySequence("Ctrl+Shift+F"))
        self.new_file_action.triggered.connect(self.on_new_file)
        file_menu.addAction(self.new_file_action)
        
        file_menu.addSeparator()
        
        self.delete_action = QAction("Delete", self)
        self.delete_action.setShortcut(QKeySequence("Delete"))
        self.delete_action.triggered.connect(self.on_delete)
        file_menu.addAction(self.delete_action)
        
        self.rename_action = QAction("Rename", self)
        self.rename_action.setShortcut(QKeySequence("F2"))
        self.rename_action.triggered.connect(self.on_rename)
        file_menu.addAction(self.rename_action)
        
        file_menu.addSeparator()
        
        empty_trash_action = QAction("Empty Trash", self)
        empty_trash_action.triggered.connect(self.on_empty_trash)
        file_menu.addAction(empty_trash_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("Exit", self)
        exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Edit menu
        edit_menu = menubar.addMenu("Edit")
        
        self.copy_action = QAction("Copy", self)
        self.copy_action.setShortcut(QKeySequence("Ctrl+C"))
        self.copy_action.triggered.connect(self.on_copy)
        edit_menu.addAction(self.copy_action)
        
        self.cut_action = QAction("Cut", self)
        self.cut_action.setShortcut(QKeySequence("Ctrl+X"))
        self.cut_action.triggered.connect(self.on_cut)
        edit_menu.addAction(self.cut_action)
        
        self.paste_action = QAction("Paste", self)
        self.paste_action.setShortcut(QKeySequence("Ctrl+V"))
        self.paste_action.triggered.connect(self.on_paste)
        edit_menu.addAction(self.paste_action)
        
        # View menu
        view_menu = menubar.addMenu("View")
        
        self.show_hidden_action = QAction("Show Hidden Files", self)
        self.show_hidden_action.setCheckable(True)
        self.show_hidden_action.setShortcut(QKeySequence("Ctrl+H"))
        self.show_hidden_action.triggered.connect(self.on_toggle_hidden)
        view_menu.addAction(self.show_hidden_action)
        
        view_menu.addSeparator()
        
        self.dark_mode_action = QAction("Dark Mode", self)
        self.dark_mode_action.setCheckable(True)
        self.dark_mode_action.setShortcut(QKeySequence("Ctrl+D"))
        self.dark_mode_action.triggered.connect(self.on_toggle_dark_mode)
        view_menu.addAction(self.dark_mode_action)
        
        # Go menu
        go_menu = menubar.addMenu("Go")
        
        self.back_action = QAction("Back", self)
        self.back_action.setShortcut(QKeySequence("Alt+Left"))
        self.back_action.triggered.connect(self.on_back)
        go_menu.addAction(self.back_action)
        
        self.forward_action = QAction("Forward", self)
        self.forward_action.setShortcut(QKeySequence("Alt+Right"))
        self.forward_action.triggered.connect(self.on_forward)
        go_menu.addAction(self.forward_action)
        
        self.up_action = QAction("Up", self)
        self.up_action.setShortcut(QKeySequence("Alt+Up"))
        self.up_action.triggered.connect(self.on_up)
        go_menu.addAction(self.up_action)
        
        go_menu.addSeparator()
        
        home_action = QAction("Home", self)
        home_action.setShortcut(QKeySequence("Ctrl+Home"))
        home_action.triggered.connect(self.on_home)
        go_menu.addAction(home_action)
    
    def setup_toolbar(self):
        """Setup the toolbar"""
        self.toolbar = QToolBar("Main Toolbar")
        self.toolbar.setMovable(False)
        self.toolbar.setStyleSheet("""
            QToolBar {
                background-color: #fafafa;
                border: none;
                border-bottom: 1px solid #e0e0e0;
                spacing: 4px;
                padding: 4px;
            }
            QToolBar::separator {
                background-color: #e0e0e0;
                width: 1px;
                margin: 4px 2px;
            }
        """)
        self.addToolBar(self.toolbar)
        
        # Flat button style
        button_style = """
            QPushButton {
                background-color: #f5f5f5;
                color: #212121;
                border: 1px solid #e0e0e0;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #eeeeee;
                border: 1px solid #bdbdbd;
            }
            QPushButton:pressed {
                background-color: #e0e0e0;
            }
        """
        
        # Navigation buttons
        self.back_btn = QPushButton("← Back")
        self.back_btn.clicked.connect(self.on_back)
        self.back_btn.setStyleSheet(button_style)
        self.toolbar.addWidget(self.back_btn)
        
        self.forward_btn = QPushButton("Forward →")
        self.forward_btn.clicked.connect(self.on_forward)
        self.forward_btn.setStyleSheet(button_style)
        self.toolbar.addWidget(self.forward_btn)
        
        self.up_btn = QPushButton("↑ Up")
        self.up_btn.clicked.connect(self.on_up)
        self.up_btn.setStyleSheet(button_style)
        self.toolbar.addWidget(self.up_btn)
        
        self.toolbar.addSeparator()
        
        # File operations
        self.copy_btn = QPushButton("Copy")
        self.copy_btn.clicked.connect(self.on_copy)
        self.copy_btn.setStyleSheet(button_style)
        self.toolbar.addWidget(self.copy_btn)
        
        self.paste_btn = QPushButton("Paste")
        self.paste_btn.clicked.connect(self.on_paste)
        self.paste_btn.setStyleSheet(button_style)
        self.toolbar.addWidget(self.paste_btn)
        
        self.toolbar.addSeparator()
        
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self.on_delete)
        self.delete_btn.setStyleSheet(button_style)
        self.toolbar.addWidget(self.delete_btn)
        
        self.rename_btn = QPushButton("Rename")
        self.rename_btn.clicked.connect(self.on_rename)
        self.rename_btn.setStyleSheet(button_style)
        self.toolbar.addWidget(self.rename_btn)
        
        self.toolbar.addSeparator()
        
        self.new_folder_btn = QPushButton("New Folder")
        self.new_folder_btn.clicked.connect(self.on_new_folder)
        self.new_folder_btn.setStyleSheet(button_style)
        self.toolbar.addWidget(self.new_folder_btn)
    
    def setup_status_bar(self):
        """Setup the status bar"""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
    
    def setup_shortcuts(self):
        """Setup keyboard shortcuts"""
        # Most shortcuts are already set in menu actions
        pass
    
    def connect_signals(self):
        """Connect signals from file browser"""
        self.file_browser.path_changed.connect(self.on_path_changed)
        self.file_browser.selection_changed.connect(self.on_selection_changed)
    
    def on_path_changed(self, path: str):
        """Handle path change"""
        self.address_bar.setText(path)
        self.update_status_bar()
    
    def on_selection_changed(self, paths: list):
        """Handle selection change"""
        if paths:
            self.status_bar.showMessage(f"Selected: {len(paths)} item(s)")
        else:
            self.update_status_bar()
    
    def update_status_bar(self):
        """Update status bar with current directory info"""
        path = self.file_browser.get_current_path()
        count = self.file_browser.get_item_count()
        self.status_bar.showMessage(f"Location: {path} | Items: {count}")
    
    def on_address_bar_entered(self):
        """Handle address bar enter"""
        path = self.address_bar.text()
        if os.path.exists(path):
            self.file_browser.navigate_to(path)
        else:
            QMessageBox.warning(self, "Invalid Path", f"Path does not exist: {path}")
            self.address_bar.setText(self.file_browser.get_current_path())
    
    def on_refresh(self):
        """Handle refresh button"""
        self.file_browser.refresh()
        self.update_status_bar()
    
    def on_back(self):
        """Handle back navigation"""
        self.file_browser.navigate_back()
    
    def on_forward(self):
        """Handle forward navigation"""
        self.file_browser.navigate_forward()
    
    def on_up(self):
        """Handle up navigation"""
        self.file_browser.navigate_up()
    
    def on_home(self):
        """Navigate to home directory"""
        self.file_browser.navigate_to(str(Path.home()))
    
    def on_copy(self):
        """Handle copy action"""
        self.file_browser.copy_selected()
        self.status_bar.showMessage("Copied to clipboard")
    
    def on_cut(self):
        """Handle cut action"""
        self.file_browser.cut_selected()
        self.status_bar.showMessage("Cut to clipboard")
    
    def on_paste(self):
        """Handle paste action"""
        if self.file_browser.paste_files(self.trash_manager):
            self.status_bar.showMessage("Pasted successfully")
        else:
            self.status_bar.showMessage("Nothing to paste")
    
    def on_delete(self):
        """Handle delete action"""
        if self.file_browser.delete_selected(self.trash_manager):
            self.status_bar.showMessage("Moved to trash")
        else:
            self.status_bar.showMessage("Nothing selected")
    
    def on_rename(self):
        """Handle rename action"""
        if self.file_browser.rename_selected():
            self.status_bar.showMessage("Renamed successfully")
        else:
            self.status_bar.showMessage("Nothing selected")
    
    def on_new_folder(self):
        """Handle new folder action"""
        if self.file_browser.create_new_folder():
            self.status_bar.showMessage("Folder created")
        else:
            self.status_bar.showMessage("Failed to create folder")
    
    def on_new_file(self):
        """Handle new file action"""
        if self.file_browser.create_new_file():
            self.status_bar.showMessage("File created")
        else:
            self.status_bar.showMessage("Failed to create file")
    
    def on_toggle_hidden(self, checked: bool):
        """Handle show/hide hidden files"""
        self.file_browser.update_hidden_filter(checked)
        self.update_status_bar()
    
    def on_toggle_dark_mode(self, checked: bool):
        """Handle dark mode toggle"""
        self.dark_mode = checked
        self.apply_theme()
    
    def apply_theme(self):
        """Apply light or dark theme to the application"""
        if self.dark_mode:
            self.apply_dark_theme()
        else:
            self.apply_light_theme()
    
    def apply_light_theme(self):
        """Apply light theme"""
        # Update application palette
        palette = self.palette()
        palette.setColor(palette.ColorRole.Window, QColor("#ffffff"))
        palette.setColor(palette.ColorRole.WindowText, QColor("#212121"))
        palette.setColor(palette.ColorRole.Base, QColor("#ffffff"))
        palette.setColor(palette.ColorRole.AlternateBase, QColor("#fafafa"))
        palette.setColor(palette.ColorRole.Text, QColor("#212121"))
        palette.setColor(palette.ColorRole.Button, QColor("#f5f5f5"))
        palette.setColor(palette.ColorRole.ButtonText, QColor("#212121"))
        palette.setColor(palette.ColorRole.Highlight, QColor("#e3f2fd"))
        palette.setColor(palette.ColorRole.HighlightedText, QColor("#1976d2"))
        self.setPalette(palette)
        
        # Apply to file browser
        if hasattr(self, 'file_browser'):
            self.file_browser.apply_theme(False)
        
        # Apply to toolbar and address bar
        self.apply_toolbar_theme(False)
        self.apply_address_bar_theme(False)
    
    def apply_dark_theme(self):
        """Apply dark theme"""
        # Update application palette
        palette = self.palette()
        palette.setColor(palette.ColorRole.Window, QColor("#1e1e1e"))
        palette.setColor(palette.ColorRole.WindowText, QColor("#e0e0e0"))
        palette.setColor(palette.ColorRole.Base, QColor("#1e1e1e"))
        palette.setColor(palette.ColorRole.AlternateBase, QColor("#252525"))
        palette.setColor(palette.ColorRole.Text, QColor("#e0e0e0"))
        palette.setColor(palette.ColorRole.Button, QColor("#2d2d2d"))
        palette.setColor(palette.ColorRole.ButtonText, QColor("#e0e0e0"))
        palette.setColor(palette.ColorRole.Highlight, QColor("#0d47a1"))
        palette.setColor(palette.ColorRole.HighlightedText, QColor("#ffffff"))
        self.setPalette(palette)
        
        # Apply to file browser
        if hasattr(self, 'file_browser'):
            self.file_browser.apply_theme(True)
        
        # Apply to toolbar and address bar
        self.apply_toolbar_theme(True)
        self.apply_address_bar_theme(True)
    
    def apply_toolbar_theme(self, dark_mode: bool):
        """Apply theme to toolbar and toolbar buttons"""
        if dark_mode:
            toolbar_style = """
                QToolBar {
                    background-color: #2d2d2d;
                    border: none;
                    border-bottom: 1px solid #3a3a3a;
                    spacing: 4px;
                    padding: 4px;
                }
                QToolBar::separator {
                    background-color: #3a3a3a;
                    width: 1px;
                    margin: 4px 2px;
                }
            """
            button_style = """
                QPushButton {
                    background-color: #3a3a3a;
                    color: #e0e0e0;
                    border: 1px solid #4a4a4a;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background-color: #4a4a4a;
                    border: 1px solid #5a5a5a;
                }
                QPushButton:pressed {
                    background-color: #2d2d2d;
                }
            """
        else:
            toolbar_style = """
                QToolBar {
                    background-color: #fafafa;
                    border: none;
                    border-bottom: 1px solid #e0e0e0;
                    spacing: 4px;
                    padding: 4px;
                }
                QToolBar::separator {
                    background-color: #e0e0e0;
                    width: 1px;
                    margin: 4px 2px;
                }
            """
            button_style = """
                QPushButton {
                    background-color: #f5f5f5;
                    color: #212121;
                    border: 1px solid #e0e0e0;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background-color: #eeeeee;
                    border: 1px solid #bdbdbd;
                }
                QPushButton:pressed {
                    background-color: #e0e0e0;
                }
            """
        
        if hasattr(self, 'toolbar'):
            self.toolbar.setStyleSheet(toolbar_style)
            
            # Apply button style to all toolbar buttons
            toolbar_buttons = [
                self.back_btn, self.forward_btn, self.up_btn,
                self.copy_btn, self.paste_btn, self.delete_btn,
                self.rename_btn, self.new_folder_btn
            ]
            for btn in toolbar_buttons:
                if btn:
                    btn.setStyleSheet(button_style)
    
    def apply_address_bar_theme(self, dark_mode: bool):
        """Apply theme to address bar and refresh button"""
        if dark_mode:
            address_bar_style = """
                QLineEdit {
                    background-color: #2d2d2d;
                    color: #e0e0e0;
                    border: 1px solid #3a3a3a;
                    border-radius: 4px;
                    padding: 6px 10px;
                    font-size: 12px;
                }
                QLineEdit:focus {
                    border: 2px solid #2196f3;
                    padding: 5px 9px;
                }
            """
            refresh_btn_style = """
                QPushButton {
                    background-color: #3a3a3a;
                    color: #e0e0e0;
                    border: 1px solid #4a4a4a;
                    border-radius: 4px;
                    padding: 6px 10px;
                    min-width: 30px;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: #4a4a4a;
                    border: 1px solid #5a5a5a;
                }
                QPushButton:pressed {
                    background-color: #2d2d2d;
                }
            """
        else:
            address_bar_style = """
                QLineEdit {
                    background-color: #ffffff;
                    border: 1px solid #e0e0e0;
                    border-radius: 4px;
                    padding: 6px 10px;
                    font-size: 12px;
                }
                QLineEdit:focus {
                    border: 2px solid #2196f3;
                    padding: 5px 9px;
                }
            """
            refresh_btn_style = """
                QPushButton {
                    background-color: #f5f5f5;
                    color: #212121;
                    border: 1px solid #e0e0e0;
                    border-radius: 4px;
                    padding: 6px 10px;
                    min-width: 30px;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: #eeeeee;
                    border: 1px solid #bdbdbd;
                }
                QPushButton:pressed {
                    background-color: #e0e0e0;
                }
            """
        
        if hasattr(self, 'address_bar'):
            self.address_bar.setStyleSheet(address_bar_style)
        if hasattr(self, 'refresh_btn'):
            self.refresh_btn.setStyleSheet(refresh_btn_style)
    
    def on_empty_trash(self):
        """Handle empty trash action"""
        trash_size = self.trash_manager.get_trash_size()
        if trash_size == 0:
            QMessageBox.information(self, "Empty Trash", "Trash is already empty.")
            return
        
        reply = QMessageBox.question(
            self,
            "Empty Trash",
            f"Permanently delete {trash_size} item(s) from trash?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            if self.trash_manager.empty_trash():
                QMessageBox.information(self, "Empty Trash", "Trash emptied successfully.")
            else:
                QMessageBox.critical(self, "Error", "Failed to empty trash.")


def main():
    """Main entry point"""
    import sys
    from PyQt6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    app.setApplicationName("ASFM")
    app.setOrganizationName("AnggaSabber")
    
    # Set application style to Fusion for flat design
    app.setStyle("Fusion")
    
    # Apply flat color palette
    palette = app.palette()
    palette.setColor(palette.ColorRole.Window, QColor("#ffffff"))
    palette.setColor(palette.ColorRole.WindowText, QColor("#212121"))
    palette.setColor(palette.ColorRole.Base, QColor("#ffffff"))
    palette.setColor(palette.ColorRole.AlternateBase, QColor("#fafafa"))
    palette.setColor(palette.ColorRole.ToolTipBase, QColor("#ffffff"))
    palette.setColor(palette.ColorRole.ToolTipText, QColor("#212121"))
    palette.setColor(palette.ColorRole.Text, QColor("#212121"))
    palette.setColor(palette.ColorRole.Button, QColor("#f5f5f5"))
    palette.setColor(palette.ColorRole.ButtonText, QColor("#212121"))
    palette.setColor(palette.ColorRole.Highlight, QColor("#e3f2fd"))
    palette.setColor(palette.ColorRole.HighlightedText, QColor("#1976d2"))
    app.setPalette(palette)
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

