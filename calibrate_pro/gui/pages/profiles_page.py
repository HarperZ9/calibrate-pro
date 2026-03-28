"""
Profiles Page - ICC Profile management with activation control.
"""

from pathlib import Path

from PyQt6.QtCore import QSettings, Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from calibrate_pro.gui.theme import APP_NAME, APP_ORGANIZATION, COLORS


class ProfilesPage(QWidget):
    """
    ICC Profile management interface with activation status and toggle.

    Shows:
    - List of installed ICC profiles and LUTs
    - Active/inactive status per display
    - Toggle to enable/disable profiles (applies VCGT/LUT)
    - Visual feedback when profiles are applied
    """

    profile_activated = pyqtSignal(str, int)  # profile_path, display_index
    profile_deactivated = pyqtSignal(int)  # display_index

    def __init__(self, parent=None):
        super().__init__(parent)
        self.color_loader = None
        self.active_profiles = {}  # display_index -> profile_path
        self._setup_ui()
        self._init_color_loader()

    def _init_color_loader(self):
        """Initialize the color loader for applying profiles."""
        try:
            from calibrate_pro.lut_system.color_loader import get_color_loader
            self.color_loader = get_color_loader()
        except Exception as e:
            print(f"Could not initialize color loader: {e}")

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # Header
        header_layout = QHBoxLayout()
        header = QLabel("Profile Manager")
        header.setStyleSheet("font-size: 20px; font-weight: 600;")
        header_layout.addWidget(header)
        header_layout.addStretch()

        # Global status
        self.global_status = QLabel("No profiles active")
        self.global_status.setStyleSheet(f"color: {COLORS['text_secondary']};")
        header_layout.addWidget(self.global_status)

        layout.addLayout(header_layout)

        # Active profiles status panel
        status_group = QGroupBox("Active Color Management")
        status_layout = QVBoxLayout(status_group)

        self.status_info = QLabel(
            "Color management applies VCGT (gamma curves) and 3D LUTs to correct display output.\n"
            "When active, you will see visible changes to displayed colors."
        )
        self.status_info.setWordWrap(True)
        self.status_info.setStyleSheet(f"color: {COLORS['text_secondary']}; padding: 4px;")
        status_layout.addWidget(self.status_info)

        # Per-display status
        self.display_status_layout = QHBoxLayout()
        self.display_status_widgets = []

        # Will be populated when profiles are loaded
        status_layout.addLayout(self.display_status_layout)

        layout.addWidget(status_group)

        # Main content
        content = QHBoxLayout()
        content.setSpacing(16)

        # Profile list
        list_widget = QWidget()
        list_layout = QVBoxLayout(list_widget)
        list_layout.setContentsMargins(0, 0, 0, 0)

        list_header = QHBoxLayout()
        list_label = QLabel("Installed Profiles & LUTs")
        list_label.setStyleSheet(f"font-weight: 600; color: {COLORS['text_secondary']};")
        list_header.addWidget(list_label)
        list_header.addStretch()

        import_btn = QPushButton("Import")
        import_btn.setMaximumWidth(80)
        import_btn.clicked.connect(self._import_profile)
        list_header.addWidget(import_btn)

        list_layout.addLayout(list_header)

        self.profile_list = QListWidget()
        self.profile_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.profile_list.itemSelectionChanged.connect(self._on_selection_changed)
        list_layout.addWidget(self.profile_list)

        # Selection buttons row
        select_layout = QHBoxLayout()
        select_layout.setSpacing(8)

        select_all_btn = QPushButton("Select All")
        select_all_btn.setMaximumWidth(80)
        select_all_btn.clicked.connect(self._select_all_profiles)
        select_layout.addWidget(select_all_btn)

        select_none_btn = QPushButton("Select None")
        select_none_btn.setMaximumWidth(80)
        select_none_btn.clicked.connect(self._select_none_profiles)
        select_layout.addWidget(select_none_btn)

        select_custom_btn = QPushButton("Select Custom")
        select_custom_btn.setMaximumWidth(100)
        select_custom_btn.clicked.connect(self._select_custom_profiles)
        select_custom_btn.setToolTip("Select all non-system profiles")
        select_layout.addWidget(select_custom_btn)

        select_layout.addStretch()
        list_layout.addLayout(select_layout)

        # Action buttons - Row 1 (Activation)
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(8)

        self.activate_btn = QPushButton("Activate Profile")
        self.activate_btn.setProperty("primary", True)
        self.activate_btn.clicked.connect(self._activate_profile)
        self.activate_btn.setToolTip("Apply this profile's VCGT/LUT to the display")
        actions_layout.addWidget(self.activate_btn)

        self.deactivate_btn = QPushButton("Deactivate")
        self.deactivate_btn.clicked.connect(self._deactivate_profile)
        self.deactivate_btn.setToolTip("Remove color correction from display")
        actions_layout.addWidget(self.deactivate_btn)

        list_layout.addLayout(actions_layout)

        # Action buttons - Row 2
        actions_layout2 = QHBoxLayout()
        actions_layout2.setSpacing(8)

        rename_btn = QPushButton("Rename")
        rename_btn.clicked.connect(self._rename_profile)
        actions_layout2.addWidget(rename_btn)

        delete_btn = QPushButton("Delete Selected")
        delete_btn.clicked.connect(self._delete_selected_profiles)
        delete_btn.setToolTip("Delete all selected profiles (Ctrl+Click to multi-select)")
        actions_layout2.addWidget(delete_btn)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_profiles)
        actions_layout2.addWidget(refresh_btn)

        list_layout.addLayout(actions_layout2)
        content.addWidget(list_widget, stretch=1)

        # Right panel - Details and display selector
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)

        # Display selector for activation
        display_group = QGroupBox("Target Display")
        display_layout = QVBoxLayout(display_group)

        self.display_combo = QComboBox()
        self._populate_displays()
        display_layout.addWidget(self.display_combo)

        right_layout.addWidget(display_group)

        # Profile details
        details_group = QGroupBox("Profile Details")
        self.details_layout = QFormLayout(details_group)

        self.detail_name = QLabel("-")
        self.details_layout.addRow("Name:", self.detail_name)

        self.detail_status = QLabel("-")
        self.details_layout.addRow("Status:", self.detail_status)

        self.detail_type = QLabel("-")
        self.details_layout.addRow("Type:", self.detail_type)

        self.detail_size = QLabel("-")
        self.details_layout.addRow("Size:", self.detail_size)

        self.detail_lut = QLabel("-")
        self.details_layout.addRow("Has LUT:", self.detail_lut)

        right_layout.addWidget(details_group)

        # Quick actions
        quick_group = QGroupBox("Quick Actions")
        quick_layout = QVBoxLayout(quick_group)

        reset_btn = QPushButton("Reset All Displays to Linear")
        reset_btn.clicked.connect(self._reset_all_displays)
        reset_btn.setToolTip("Remove all color corrections and reset to linear gamma")
        quick_layout.addWidget(reset_btn)

        reload_btn = QPushButton("Reload Active Profiles")
        reload_btn.clicked.connect(self._reload_active_profiles)
        reload_btn.setToolTip("Re-apply all active profiles (useful if overridden by other software)")
        quick_layout.addWidget(reload_btn)

        right_layout.addWidget(quick_group)
        right_layout.addStretch()

        content.addWidget(right_panel, stretch=1)
        layout.addLayout(content)

        # Populate with real profiles on startup
        self._refresh_profiles()
        self._update_display_status()

    def _populate_displays(self):
        """Populate the display selector combo."""
        self.display_combo.clear()
        screens = QGuiApplication.screens()
        for i, screen in enumerate(screens):
            name = screen.name() or f"Display {i+1}"
            geo = screen.geometry()
            self.display_combo.addItem(f"Display {i+1}: {name} ({geo.width()}x{geo.height()})")

    def _update_display_status(self):
        """Update the per-display status widgets."""
        # Clear existing
        for widget in self.display_status_widgets:
            widget.deleteLater()
        self.display_status_widgets.clear()

        screens = QGuiApplication.screens()
        settings = QSettings(APP_ORGANIZATION, APP_NAME)

        active_count = 0

        for i, screen in enumerate(screens):
            frame = QFrame()
            frame.setStyleSheet(f"""
                QFrame {{
                    background-color: {COLORS['surface']};
                    border-radius: 8px;
                    padding: 8px;
                }}
            """)
            frame_layout = QVBoxLayout(frame)
            frame_layout.setContentsMargins(12, 8, 12, 8)
            frame_layout.setSpacing(4)

            # Check if profile is active for this display
            active_profile = settings.value(f"cm/display_{i}/active_profile", "")
            is_active = bool(active_profile)

            if is_active:
                active_count += 1
                status_color = COLORS['success']
                status_text = "ACTIVE"
                profile_name = Path(active_profile).stem if active_profile else ""
            else:
                status_color = COLORS['text_disabled']
                status_text = "Inactive"
                profile_name = "No profile"

            name_label = QLabel(screen.name() or f"Display {i+1}")
            name_label.setStyleSheet("font-weight: 600;")
            frame_layout.addWidget(name_label)

            status_label = QLabel(status_text)
            status_label.setStyleSheet(f"color: {status_color}; font-size: 11px; font-weight: 600;")
            frame_layout.addWidget(status_label)

            if profile_name:
                profile_label = QLabel(profile_name[:25] + "..." if len(profile_name) > 25 else profile_name)
                profile_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 10px;")
                frame_layout.addWidget(profile_label)

            self.display_status_layout.addWidget(frame)
            self.display_status_widgets.append(frame)

        self.display_status_layout.addStretch()

        # Update global status
        if active_count > 0:
            self.global_status.setText(f"{active_count} display(s) with active color management")
            self.global_status.setStyleSheet(f"color: {COLORS['success']}; font-weight: 600;")
        else:
            self.global_status.setText("No profiles active")
            self.global_status.setStyleSheet(f"color: {COLORS['text_disabled']};")

    def _on_selection_changed(self):
        """Handle profile selection change."""
        current_item = self.profile_list.currentItem()
        if not current_item:
            return

        profile_path = current_item.data(Qt.ItemDataRole.UserRole)
        if not profile_path:
            return

        from pathlib import Path
        path = Path(profile_path)

        self.detail_name.setText(path.name)

        # Check if active
        settings = QSettings(APP_ORGANIZATION, APP_NAME)
        display_idx = self.display_combo.currentIndex()
        active_profile = settings.value(f"cm/display_{display_idx}/active_profile", "")

        if active_profile == str(path):
            self.detail_status.setText("ACTIVE")
            self.detail_status.setStyleSheet(f"color: {COLORS['success']}; font-weight: 600;")
        else:
            self.detail_status.setText("Inactive")
            self.detail_status.setStyleSheet(f"color: {COLORS['text_secondary']};")

        # Profile type
        if path.suffix.lower() in ('.icc', '.icm'):
            self.detail_type.setText("ICC Profile")
        elif path.suffix.lower() == '.cube':
            self.detail_type.setText("3D LUT (.cube)")
        elif path.suffix.lower() == '.3dl':
            self.detail_type.setText("3D LUT (.3dl)")
        else:
            self.detail_type.setText("Unknown")

        # Size
        try:
            size = path.stat().st_size
            if size > 1024 * 1024:
                self.detail_size.setText(f"{size / 1024 / 1024:.1f} MB")
            elif size > 1024:
                self.detail_size.setText(f"{size / 1024:.1f} KB")
            else:
                self.detail_size.setText(f"{size} bytes")
        except (OSError, ValueError):
            self.detail_size.setText("-")

        # Check for associated LUT
        lut_path = path.with_suffix('.cube')
        if lut_path.exists():
            self.detail_lut.setText(f"Yes ({lut_path.name})")
            self.detail_lut.setStyleSheet(f"color: {COLORS['success']};")
        else:
            self.detail_lut.setText("No")
            self.detail_lut.setStyleSheet(f"color: {COLORS['text_secondary']};")

    def _activate_profile(self):
        """Activate the selected profile for the selected display."""
        current_item = self.profile_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "No Selection", "Please select a profile to activate.")
            return

        profile_path = current_item.data(Qt.ItemDataRole.UserRole)
        if not profile_path:
            return

        display_idx = self.display_combo.currentIndex()
        from pathlib import Path
        path = Path(profile_path)

        try:
            # Load and apply the profile/LUT
            if self.color_loader:
                success = False

                # Try ICC profile first
                if path.suffix.lower() in ('.icc', '.icm'):
                    success = self.color_loader.load_icc_profile(display_idx, str(path))

                    # Also try to load associated .cube LUT
                    lut_path = path.with_suffix('.cube')
                    if lut_path.exists():
                        self.color_loader.load_lut_file(display_idx, str(lut_path))

                elif path.suffix.lower() in ('.cube', '.3dl'):
                    success = self.color_loader.load_lut_file(display_idx, str(path))

                if success:
                    # Start the loader service if not running
                    self.color_loader.start()

                    # Save as active profile
                    settings = QSettings(APP_ORGANIZATION, APP_NAME)
                    settings.setValue(f"cm/display_{display_idx}/active_profile", str(path))
                    settings.sync()

                    QMessageBox.information(
                        self, "Profile Activated",
                        f"Color profile activated for Display {display_idx + 1}!\n\n"
                        f"Profile: {path.name}\n\n"
                        "You should see visible changes to your display colors.\n"
                        "The VCGT gamma curves have been applied."
                    )

                    self._update_display_status()
                    self._on_selection_changed()
                else:
                    QMessageBox.warning(
                        self, "Activation Failed",
                        "Could not activate profile. The profile may not contain VCGT data,\n"
                        "or the system could not apply the gamma ramp."
                    )
            else:
                QMessageBox.warning(
                    self, "Color Loader Unavailable",
                    "The color loader is not available. Cannot apply profiles."
                )

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to activate profile:\n\n{str(e)}")

    def _deactivate_profile(self):
        """Deactivate color management for the selected display."""
        display_idx = self.display_combo.currentIndex()

        reply = QMessageBox.question(
            self, "Deactivate Profile",
            f"Remove color correction from Display {display_idx + 1}?\n\n"
            "This will reset the display to linear gamma (no correction).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            if self.color_loader:
                self.color_loader.reset_display(display_idx)

            # Clear active profile setting
            settings = QSettings(APP_ORGANIZATION, APP_NAME)
            settings.remove(f"cm/display_{display_idx}/active_profile")
            settings.sync()

            QMessageBox.information(
                self, "Profile Deactivated",
                f"Color management disabled for Display {display_idx + 1}.\n\n"
                "Display is now using linear gamma (no correction)."
            )

            self._update_display_status()
            self._on_selection_changed()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to deactivate:\n\n{str(e)}")

    def _reset_all_displays(self):
        """Reset all displays to linear gamma."""
        reply = QMessageBox.question(
            self, "Reset All Displays",
            "Remove all color corrections from all displays?\n\n"
            "This will reset all displays to linear gamma.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            if self.color_loader:
                self.color_loader.reset_all()

            # Clear all active profile settings
            settings = QSettings(APP_ORGANIZATION, APP_NAME)
            screens = QGuiApplication.screens()
            for i in range(len(screens)):
                settings.remove(f"cm/display_{i}/active_profile")
            settings.sync()

            QMessageBox.information(
                self, "Reset Complete",
                "All displays reset to linear gamma.\n\n"
                "No color correction is active."
            )

            self._update_display_status()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to reset:\n\n{str(e)}")

    def _reload_active_profiles(self):
        """Reload all active profiles."""
        try:
            if self.color_loader:
                results = self.color_loader.apply_all()
                success_count = sum(1 for v in results.values() if v)

                QMessageBox.information(
                    self, "Profiles Reloaded",
                    f"Reloaded {success_count} active profile(s).\n\n"
                    "This is useful if another application has overridden your color settings."
                )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to reload:\n\n{str(e)}")

    def _import_profile(self):
        """Import an ICC profile or LUT file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Profile or LUT",
            str(Path.home()),
            "Color Files (*.icc *.icm *.cube *.3dl);;ICC Profiles (*.icc *.icm);;3D LUTs (*.cube *.3dl)"
        )

        if not file_path:
            return

        # Copy to profiles directory
        try:
            from shutil import copy2
            profiles_dir = Path.home() / ".calibrate_pro" / "profiles"
            profiles_dir.mkdir(parents=True, exist_ok=True)

            dest = profiles_dir / Path(file_path).name
            copy2(file_path, dest)

            QMessageBox.information(
                self, "Profile Imported",
                f"Profile imported successfully:\n\n{dest.name}"
            )

            self._refresh_profiles()

        except Exception as e:
            QMessageBox.critical(self, "Import Failed", f"Could not import profile:\n\n{str(e)}")

    def _select_all_profiles(self):
        """Select all profiles in the list."""
        self.profile_list.selectAll()

    def _select_none_profiles(self):
        """Clear all selections."""
        self.profile_list.clearSelection()

    def _select_custom_profiles(self):
        """Select only custom (non-system) profiles."""
        SYSTEM_PROFILES = {'srgb color space profile.icm', 'rswop.icm', 'wscrgb.icc', 'wsrgb.icc'}

        self.profile_list.clearSelection()
        for i in range(self.profile_list.count()):
            item = self.profile_list.item(i)
            profile_path = item.data(Qt.ItemDataRole.UserRole)
            if profile_path:
                from pathlib import Path
                name = Path(profile_path).name.lower()
                if name not in SYSTEM_PROFILES:
                    item.setSelected(True)

    def _delete_selected_profiles(self):
        """Delete all selected profiles."""
        selected_items = self.profile_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "No Selection", "Please select profiles to delete.\n\nTip: Use Ctrl+Click or Shift+Click to select multiple profiles.")
            return

        # System profiles that should not be deleted
        SYSTEM_PROFILES = {'srgb color space profile.icm', 'rswop.icm', 'wscrgb.icc', 'wsrgb.icc'}

        from pathlib import Path

        # Filter out system profiles
        profiles_to_delete = []
        skipped_system = []

        for item in selected_items:
            profile_path = item.data(Qt.ItemDataRole.UserRole)
            if profile_path:
                path = Path(profile_path)
                if path.name.lower() in SYSTEM_PROFILES:
                    skipped_system.append(path.name)
                else:
                    profiles_to_delete.append(path)

        if not profiles_to_delete:
            QMessageBox.warning(self, "No Deletable Profiles",
                "All selected profiles are system profiles and cannot be deleted.")
            return

        # Confirm deletion
        msg = f"Delete {len(profiles_to_delete)} profile(s)?\n\n"
        if len(profiles_to_delete) <= 10:
            for p in profiles_to_delete:
                msg += f"  - {p.name}\n"
        else:
            for p in profiles_to_delete[:8]:
                msg += f"  - {p.name}\n"
            msg += f"  ... and {len(profiles_to_delete) - 8} more\n"

        if skipped_system:
            msg += f"\n({len(skipped_system)} system profile(s) will be skipped)"

        msg += "\n\nThis cannot be undone."

        reply = QMessageBox.question(
            self, "Delete Profiles",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Delete profiles
        deleted = 0
        failed = []

        for path in profiles_to_delete:
            try:
                path.unlink()
                deleted += 1

                # Also delete associated LUT if present
                lut_path = path.with_suffix('.cube')
                if lut_path.exists():
                    lut_path.unlink()

            except Exception as e:
                failed.append((path.name, str(e)))

        # Show results
        if failed:
            msg = f"Deleted {deleted} of {len(profiles_to_delete)} profiles.\n\n"
            msg += f"{len(failed)} failed (may need administrator rights):\n"
            for name, _err in failed[:5]:
                msg += f"  - {name}\n"
            if len(failed) > 5:
                msg += f"  ... and {len(failed) - 5} more"
            QMessageBox.warning(self, "Partial Success", msg)
        else:
            QMessageBox.information(self, "Success", f"Deleted {deleted} profile(s) successfully.")

        self._refresh_profiles()

    def _refresh_profiles(self):
        """Refresh the profile list with actual installed profiles."""
        self.profile_list.clear()

        # Get profile directories
        import os
        from pathlib import Path

        profile_dirs = []

        # System profile directory (Windows)
        system_dir = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32" / "spool" / "drivers" / "color"
        if system_dir.exists():
            profile_dirs.append(("System", system_dir))

        # Calibrate Pro output directory
        calibrate_output = Path.home() / ".calibrate_pro" / "profiles"
        if calibrate_output.exists():
            profile_dirs.append(("Calibrate Pro", calibrate_output))

        # Also check test_output for development
        test_output = Path(__file__).parent.parent.parent / "test_output"
        if test_output.exists():
            profile_dirs.append(("Test Output", test_output))

        profiles_found = []

        for source_name, dir_path in profile_dirs:
            try:
                for file_path in dir_path.iterdir():
                    if file_path.suffix.lower() in ('.icc', '.icm'):
                        # Get file info
                        stat = file_path.stat()
                        mod_time = stat.st_mtime
                        from datetime import datetime
                        mod_date = datetime.fromtimestamp(mod_time).strftime("%b %d, %Y")

                        profiles_found.append({
                            'name': file_path.name,
                            'path': file_path,
                            'source': source_name,
                            'date': mod_date,
                            'size': stat.st_size
                        })
            except (PermissionError, OSError):
                continue

        # Sort by modification time (newest first)
        profiles_found.sort(key=lambda x: x['path'].stat().st_mtime, reverse=True)

        # Add to list widget
        for profile in profiles_found:
            item = QListWidgetItem(f"{profile['name']}\n{profile['source']} - {profile['date']}")
            item.setData(Qt.ItemDataRole.UserRole, str(profile['path']))
            self.profile_list.addItem(item)

        if not profiles_found:
            item = QListWidgetItem("No profiles found\nCalibrate a display to create profiles")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.profile_list.addItem(item)

    def _rename_profile(self):
        """Rename the selected profile and its associated LUT file."""
        current_item = self.profile_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "No Selection", "Please select a profile to rename.")
            return

        profile_path = current_item.data(Qt.ItemDataRole.UserRole)
        if not profile_path:
            QMessageBox.warning(self, "Cannot Rename", "This profile cannot be renamed.")
            return

        from pathlib import Path
        profile_path = Path(profile_path)

        if not profile_path.exists():
            QMessageBox.warning(self, "File Not Found", f"Profile file not found:\n{profile_path}")
            self._refresh_profiles()
            return

        # Get new name from user
        old_name = profile_path.stem
        new_name, ok = QInputDialog.getText(
            self,
            "Rename Profile",
            f"Enter new name for '{old_name}':",
            QLineEdit.EchoMode.Normal,
            old_name
        )

        if not ok or not new_name.strip():
            return

        new_name = new_name.strip()

        # Sanitize the name
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            new_name = new_name.replace(char, '_')

        if new_name == old_name:
            return

        # Prepare new paths
        new_profile_path = profile_path.parent / f"{new_name}{profile_path.suffix}"

        # Check if target already exists
        if new_profile_path.exists():
            QMessageBox.warning(
                self, "File Exists",
                f"A profile named '{new_name}{profile_path.suffix}' already exists."
            )
            return

        try:
            # Rename ICC/ICM profile
            profile_path.rename(new_profile_path)

            # Also rename associated .cube LUT file if it exists
            lut_path = profile_path.with_suffix('.cube')
            if lut_path.exists():
                new_lut_path = new_profile_path.with_suffix('.cube')
                lut_path.rename(new_lut_path)

            # Also check for .3dl
            lut_3dl_path = profile_path.with_suffix('.3dl')
            if lut_3dl_path.exists():
                new_lut_3dl_path = new_profile_path.with_suffix('.3dl')
                lut_3dl_path.rename(new_lut_3dl_path)

            QMessageBox.information(
                self, "Profile Renamed",
                f"Profile renamed successfully:\n\n{old_name} \u2192 {new_name}"
            )

            # Refresh the list
            self._refresh_profiles()

        except PermissionError:
            QMessageBox.critical(
                self, "Permission Denied",
                "Cannot rename this profile. It may be in use or require administrator privileges."
            )
        except Exception as e:
            QMessageBox.critical(
                self, "Rename Failed",
                f"Failed to rename profile:\n\n{str(e)}"
            )
