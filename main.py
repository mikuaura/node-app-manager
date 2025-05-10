# main.py
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox, Menu, simpledialog
import os
import json
import subprocess
import threading
import time
from pathlib import Path
import sys
import webbrowser

# --- Local Imports ---
import constants
from config_manager import ConfigManager
from tooltip import ToolTip
import project_scanner
import process_handler
import ui_dialogs


# --- DPI Awareness (primarily for Windows) ---
if sys.platform == "win32":
    try:
        from ctypes import windll
        if hasattr(windll, 'shcore') and hasattr(windll.shcore, 'SetProcessDpiAwareness'):
            windll.shcore.SetProcessDpiAwareness(1)
            if constants.PERFORMANCE_LOGGING_ENABLED: print("DPI awareness set (shcore).")
        elif hasattr(windll, 'user32') and hasattr(windll.user32, 'SetProcessDPIAware'):
            windll.user32.SetProcessDPIAware()
            if constants.PERFORMANCE_LOGGING_ENABLED: print("DPI awareness set (user32).")
        else:
            if constants.PERFORMANCE_LOGGING_ENABLED: print("Could not find DPI awareness functions in ctypes.windll.")
    except Exception as e:
        if constants.PERFORMANCE_LOGGING_ENABLED: print(f"DPI awareness could not be set automatically: {e}")


# --- Main Application Class ---
class NodeAppManager(constants.ThemedTk if constants.TTKTHEMES_AVAILABLE else tk.Tk):
    def __init__(self):
        if constants.TTKTHEMES_AVAILABLE:
            super().__init__(theme="arc")
        else:
            super().__init__()
            if constants.PERFORMANCE_LOGGING_ENABLED: print("ttkthemes not found. Falling back to standard Tk. For better themes, run: pip install ttkthemes")

        self.title(f"Node.js App Manager v5.4.1 ({'PerfLog' if constants.PERFORMANCE_LOGGING_ENABLED else 'NoPerfLog'})") # Version Updated
        self.geometry("1200x850")

        self.all_log_messages = []
        self._log_ui_ready = False

        self.config_manager = ConfigManager(self)
        self.config_data = self.config_manager.load_config()

        self.projects_folder = tk.StringVar(value=self.config_data.get("projects_folder"))

        if constants.TTKTHEMES_AVAILABLE and "theme" in self.config_data:
            try:
                self.set_theme(self.config_data["theme"])
            except tk.TclError:
                self._log(f"Failed to set saved theme '{self.config_data['theme']}'. Using default.", warning=True)
                if hasattr(self, 'set_theme'): self.set_theme("arc")
            except Exception as e:
                self._log(f"Error applying saved theme: {e}", warning=True)

        self.apps_data = {}
        self.selected_app_path = None
        self.messagebox = messagebox

        self.ACTIVITY_PREFIX_MAP = {
            "Starting": "⏳ ",
            "Installing": "⏳ ",
            "Cleaning": "⏳ ",
            "Deleting": "🗑️ ",
            "Running Script": "⚙️ ",
            "Auditing": "🛡️ ",
            "Updating Deps": "🔄 "
        }

        self._setup_style()
        self._setup_menu()
        self._setup_ui()
        self.scan_projects_folder()

    def _setup_style(self):
        self.style = ttk.Style(self)
        try:
            self.style.configure("Treeview", rowheight=28) # Increased row height can help readability
            self.style.configure("Treeview.Heading", font=('TkDefaultFont', 10, 'bold'))
        except tk.TclError:
            self._log("Note: Treeview rowheight/font styling might not be fully supported by the current theme/OS.", warning=True)

    def _setup_menu(self):
        menubar = Menu(self)
        self.config(menu=menubar)

        file_menu = Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Create New Basic Project...", command=self._create_basic_project_dialog)
        file_menu.add_command(label="Change Projects Folder...", command=self._browse_folder_and_save)
        file_menu.add_separator()
        file_menu.add_command(label="Stop All Running Apps", command=self._stop_all_running_apps)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_closing)

        if constants.TTKTHEMES_AVAILABLE and hasattr(self, 'get_themes'):
            view_menu = Menu(menubar, tearoff=0)
            menubar.add_cascade(label="View", menu=view_menu)
            theme_menu = Menu(view_menu, tearoff=0)
            view_menu.add_cascade(label="Themes", menu=theme_menu)
            try:
                available_themes = sorted(self.get_themes())
                for theme_name in available_themes:
                    theme_menu.add_command(label=theme_name, command=lambda t=theme_name: self._change_theme(t))
            except Exception as e:
                self._log(f"Could not populate themes menu: {e}", warning=True)
                theme_menu.add_command(label="Error loading themes", state=tk.DISABLED)

    def _setup_ui(self):
        # Overall padding for the root window can sometimes help
        self.configure(padx=5, pady=5)

        top_frame = ttk.Frame(self, padding="10")
        top_frame.pack(fill=tk.X)
        ttk.Label(top_frame, text="Projects Folder:").pack(side=tk.LEFT, padx=(0, 5))
        self.path_entry = ttk.Entry(top_frame, textvariable=self.projects_folder, width=50, state="readonly")
        self.path_entry.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)
        scan_button = ttk.Button(top_frame, text="Re-Scan All", command=self.scan_projects_folder)
        scan_button.pack(side=tk.LEFT, padx=5)
        ToolTip(scan_button, "Refresh the list of projects from the filesystem and update process statuses.")
        fetch_button = ttk.Button(top_frame, text="Fetch New App...", command=self._fetch_online_app_dialog)
        fetch_button.pack(side=tk.LEFT)
        ToolTip(fetch_button, "Clone a Git repository or setup an NPM package as a new project.")

        main_pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=10) # Increased pady for main_pane

        apps_frame = ttk.LabelFrame(main_pane, text="Node Apps", padding="10")
        main_pane.add(apps_frame, weight=1)
        self.apps_tree = ttk.Treeview(apps_frame, columns=("Name", "Status", "Port", "PID", "Branch", "Changes"), show="headings", style="Treeview")
        self.apps_tree.heading("Name", text="Project Name")
        self.apps_tree.heading("Status", text="Status")
        self.apps_tree.heading("Port", text="Port")
        self.apps_tree.heading("PID", text="PID")
        self.apps_tree.heading("Branch", text="Git Branch")
        self.apps_tree.heading("Changes", text="Git Changes")

        self.apps_tree.column("Name", width=170, minwidth=150, anchor=tk.W, stretch=tk.YES)
        self.apps_tree.column("Status", width=140, minwidth=120, anchor=tk.W, stretch=tk.YES)
        self.apps_tree.column("Port", width=60, minwidth=50, anchor=tk.CENTER, stretch=tk.NO)
        self.apps_tree.column("PID", width=60, minwidth=50, anchor=tk.CENTER, stretch=tk.NO)
        self.apps_tree.column("Branch", width=120, minwidth=100, anchor=tk.W, stretch=tk.YES) # Increased width for "Git Branch"
        self.apps_tree.column("Changes", width=80, minwidth=70, anchor=tk.CENTER, stretch=tk.NO)

        for status_key in constants.STATUS_VISUALS:
             _, tag_name, color_val = self._get_status_display_and_tag(status_key)
             self.apps_tree.tag_configure(tag_name, foreground=color_val)

        self.apps_tree.pack(fill=tk.BOTH, expand=True)
        self.apps_tree.bind("<<TreeviewSelect>>", self._on_app_select)
        self.apps_tree.bind("<Double-1>", self._on_app_double_click)

        right_pane_container = ttk.Frame(main_pane, padding=(5,0,0,0)) # Added a little left padding
        main_pane.add(right_pane_container, weight=2)

        actions_outer_frame = ttk.LabelFrame(right_pane_container, text="App Controls", padding="10")
        actions_outer_frame.pack(fill=tk.X, pady=(0, 5))
        actions_frame = ttk.Frame(actions_outer_frame)
        actions_frame.pack(fill=tk.X)

        self.start_button = ttk.Button(actions_frame, text="Start", command=self._start_app, state=tk.DISABLED)
        self.start_button.grid(row=0, column=0, padx=2, pady=2, sticky="ew")
        ToolTip(self.start_button, "Start the selected application (npm start or node <main_file>).")
        self.stop_button = ttk.Button(actions_frame, text="Stop", command=self._stop_app, state=tk.DISABLED)
        self.stop_button.grid(row=0, column=1, padx=2, pady=2, sticky="ew")
        ToolTip(self.stop_button, "Stop the selected running application.")
        self.restart_button = ttk.Button(actions_frame, text="Restart", command=self._restart_app, state=tk.DISABLED)
        self.restart_button.grid(row=0, column=2, padx=2, pady=2, sticky="ew")
        ToolTip(self.restart_button, "Restart the selected application.")
        self.view_browser_button = ttk.Button(actions_frame, text="View in Browser", command=self._view_in_browser, state=tk.DISABLED)
        self.view_browser_button.grid(row=0, column=3, padx=2, pady=2, sticky="ew")
        ToolTip(self.view_browser_button, "Open http://localhost:<port> if the app is running and port is detected.")
        actions_frame.columnconfigure((0,1,2,3), weight=1)

        scripts_frame = ttk.Frame(actions_outer_frame)
        scripts_frame.pack(fill=tk.X, pady=(5,0))

        ttk.Label(scripts_frame, text="NPM Script:").grid(row=0, column=0, padx=(0,2), pady=2, sticky="w")
        self.npm_script_var = tk.StringVar()
        self.npm_script_combo = ttk.Combobox(scripts_frame, textvariable=self.npm_script_var, state="readonly", width=20)
        self.npm_script_combo.grid(row=0, column=1, padx=2, pady=2, sticky="ew")
        ToolTip(self.npm_script_combo, "Select an NPM script defined in package.json.")

        self.run_script_button = ttk.Button(scripts_frame, text="Run Script", command=self._run_npm_script, state=tk.DISABLED)
        self.run_script_button.grid(row=0, column=2, padx=2, pady=2, sticky="ew")
        ToolTip(self.run_script_button, "Execute the selected NPM script.")
        scripts_frame.columnconfigure(1, weight=1)

        utils_outer_frame = ttk.LabelFrame(right_pane_container, text="Project Utilities", padding="10")
        utils_outer_frame.pack(fill=tk.X, pady=(0, 5))
        utils_frame = ttk.Frame(utils_outer_frame)
        utils_frame.pack(fill=tk.X)

        self.install_button = ttk.Button(utils_frame, text="Install Deps", command=self._install_deps, state=tk.DISABLED)
        self.install_button.grid(row=0, column=0, padx=2, pady=2, sticky="ew")
        ToolTip(self.install_button, "Run 'npm install' in the project directory.")

        self.update_deps_button = ttk.Button(utils_frame, text="Update Deps", command=self._update_deps, state=tk.DISABLED)
        self.update_deps_button.grid(row=0, column=1, padx=2, pady=2, sticky="ew")
        ToolTip(self.update_deps_button, "Run 'npm update' to update dependencies based on package.json rules.")

        self.audit_button = ttk.Button(utils_frame, text="NPM Audit", command=self._npm_audit, state=tk.DISABLED)
        self.audit_button.grid(row=0, column=2, padx=2, pady=2, sticky="ew")
        ToolTip(self.audit_button, "Run 'npm audit' to check for vulnerabilities.")

        self.clean_deps_button = ttk.Button(utils_frame, text="Clean Deps", command=self._clean_dependencies, state=tk.DISABLED)
        self.clean_deps_button.grid(row=1, column=0, padx=2, pady=2, sticky="ew")
        ToolTip(self.clean_deps_button, "Delete the node_modules folder (with confirmation).")

        self.open_folder_button = ttk.Button(utils_frame, text="Open Folder", command=self._open_project_folder, state=tk.DISABLED)
        self.open_folder_button.grid(row=1, column=1, padx=2, pady=2, sticky="ew")
        ToolTip(self.open_folder_button, "Open the project's directory in the file explorer.")

        self.view_pkg_button = ttk.Button(utils_frame, text="View package.json", command=self._view_package_json, state=tk.DISABLED)
        self.view_pkg_button.grid(row=1, column=2, padx=2, pady=2, sticky="ew")
        ToolTip(self.view_pkg_button, "Display the content of package.json in a new window.")

        self.edit_pkg_button = ttk.Button(utils_frame, text="Edit package.json", command=self._edit_package_json, state=tk.DISABLED)
        self.edit_pkg_button.grid(row=2, column=0, columnspan=2, padx=2, pady=2, sticky="ew")
        ToolTip(self.edit_pkg_button, "Open package.json in the system's default text editor.")

        self.delete_project_button = ttk.Button(utils_frame, text="Delete Project", command=self._delete_project, state=tk.DISABLED)
        self.delete_project_button.grid(row=2, column=2, padx=2, pady=2, sticky="ew")
        ToolTip(self.delete_project_button, "Permanently delete the entire project folder (with confirmation).")

        utils_frame.columnconfigure((0,1,2), weight=1)

        log_frame = ttk.LabelFrame(right_pane_container, text="Log Output", padding="10")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(0,0)) # No bottom padding for log_frame itself to avoid double padding with status bar
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=10, state=tk.DISABLED,
                                                  font=("Consolas", 9) if sys.platform == "win32" else ("Monaco", 10))
        self.log_text.pack(fill=tk.BOTH, expand=True, pady=(0,5)) # Add bottom padding before filter controls

        # --- Log Filter Controls - Two Row Layout ---
        log_filter_controls_frame = ttk.Frame(log_frame)
        log_filter_controls_frame.pack(fill=tk.X, pady=(5,0))

        filter_row_frame = ttk.Frame(log_filter_controls_frame)
        filter_row_frame.pack(fill=tk.X)

        ttk.Label(filter_row_frame, text="Filter Log:").pack(side=tk.LEFT, padx=(0,5))
        self.log_filter_var = tk.StringVar()
        self.log_filter_entry = ttk.Entry(filter_row_frame, textvariable=self.log_filter_var)
        self.log_filter_entry.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0,5))
        self.log_filter_entry.bind("<Return>", lambda e: self._apply_log_filter())

        filter_log_button = ttk.Button(filter_row_frame, text="Apply Filter", command=self._apply_log_filter)
        filter_log_button.pack(side=tk.LEFT, padx=(0,2)) # Reduced right padx

        clear_buttons_row_frame = ttk.Frame(log_filter_controls_frame)
        clear_buttons_row_frame.pack(fill=tk.X, pady=(3,0)) # pady to separate rows

        clear_filter_button = ttk.Button(clear_buttons_row_frame, text="Clear Filter", command=self._clear_log_filter)
        clear_filter_button.pack(side=tk.LEFT, padx=(0,5))
        ToolTip(clear_filter_button, "Remove the current log filter.")

        clear_log_button = ttk.Button(clear_buttons_row_frame, text="Clear Log", command=self._clear_all_logs)
        clear_log_button.pack(side=tk.LEFT, padx=(0,5)) # Added padx
        ToolTip(clear_log_button, "Clear all messages from the log view.")
        # --- End Log Filter Controls ---

        self.status_bar = ttk.Label(self, text="Initializing...", relief=tk.SUNKEN, anchor=tk.W, padding=3) # Increased status bar padding
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        self._log_ui_ready = True
        self._display_filtered_logs(flush_early_logs=True)

    # --- Logging ---
    def _log(self, message, error=False, warning=False):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        prefix = constants.LOG_PREFIX_ERROR if error else constants.LOG_PREFIX_WARNING if warning else constants.LOG_PREFIX_INFO

        full_message = f"[{timestamp}] {prefix}{message}"
        self.all_log_messages.append(full_message)

        if self._log_ui_ready:
            self._display_filtered_logs(new_message_added=True, last_message=full_message)

        if error or warning:
            if constants.PERFORMANCE_LOGGING_ENABLED or error:
                print(full_message)


    def _display_filtered_logs(self, new_message_added=False, last_message=None, flush_early_logs=False):
        if not hasattr(self, 'log_text') or not self.log_text or not self._log_ui_ready:
            return

        self.log_text.config(state=tk.NORMAL)
        filter_term = self.log_filter_var.get().strip()

        rebuild_all = flush_early_logs or (filter_term != "" and new_message_added) or \
                      (not filter_term and not new_message_added) or \
                      (not filter_term and len(self.all_log_messages) == 1 and new_message_added)


        if rebuild_all:
            self.log_text.delete(1.0, tk.END)
            display_messages = []
            if filter_term:
                filter_term_lower = filter_term.lower()
                display_messages = [msg for msg in self.all_log_messages if filter_term_lower in msg.lower()]
            else:
                display_messages = self.all_log_messages

            for msg in display_messages:
                self.log_text.insert(tk.END, msg + "\n")
        elif new_message_added and last_message and not filter_term:
            self.log_text.insert(tk.END, last_message + "\n")

        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        if hasattr(self, 'update_idletasks'):
            self.update_idletasks()

    def _apply_log_filter(self):
        self._display_filtered_logs(new_message_added=False)

    def _clear_log_filter(self):
        self.log_filter_var.set("")
        self._display_filtered_logs(new_message_added=False)

    def _clear_all_logs(self):
        self.all_log_messages.clear()
        self._clear_log_filter()
        self._log("Log cleared.")

    # --- Config & Theme ---
    def _browse_folder_and_save(self):
        original_folder = self.projects_folder.get()
        folder_selected = filedialog.askdirectory(initialdir=original_folder, parent=self)
        if folder_selected and folder_selected != original_folder:
            self.projects_folder.set(folder_selected)
            self.config_manager.save_config()
            self.scan_projects_folder()

    def _change_theme(self, theme_name):
        if not (constants.TTKTHEMES_AVAILABLE and hasattr(self, 'set_theme')): return
        try:
            self.set_theme(theme_name)
            self._setup_style()
            self._log(f"Theme changed to: {theme_name}")
            self.config_manager.save_config()
        except tk.TclError as e:
            messagebox.showerror("Theme Error", f"Could not apply theme '{theme_name}':\n{e}", parent=self)
            self._log(f"Error changing theme to {theme_name}: {e}", error=True)
        except Exception as e:
            messagebox.showerror("Theme Error", f"An unexpected error occurred while changing theme '{theme_name}':\n{e}", parent=self)
            self._log(f"Unexpected error changing theme: {e}", error=True)

    def update_status_bar(self, message):
        if hasattr(self, 'status_bar') and self.status_bar:
            self.status_bar.config(text=message)
        if hasattr(self, 'update_idletasks'):
            self.update_idletasks()


    def _get_status_display_and_tag(self, status_key):
        default_visual = {"color": "#7F8C8D", "symbol": "❓"}

        base_status_key_for_symbol = status_key
        if status_key.startswith("Running Script:"):
            base_status_key_for_symbol = "Running Script"
        elif status_key.startswith("Auditing"):
            base_status_key_for_symbol = "Auditing"
        elif status_key.startswith("Updating Deps"):
            base_status_key_for_symbol = "Updating Deps"
        elif status_key.endswith("..."):
            potential_base = status_key[:-3]
            if potential_base in constants.STATUS_VISUALS:
                base_status_key_for_symbol = potential_base

        visual = constants.STATUS_VISUALS.get(base_status_key_for_symbol, default_visual)

        sanitized_key_part = ''.join(c if c.isalnum() else '_' for c in status_key)
        tag_name = f"Tag_{sanitized_key_part}_{visual['symbol']}"
        return f"{visual['symbol']} {status_key}", tag_name, visual['color']


    # --- Project Scanning & Listing ---
    def scan_projects_folder(self):
        if constants.PERFORMANCE_LOGGING_ENABLED: t_total_scan_start = time.perf_counter()
        self._log("Scanning for projects...")
        self.update_status_bar("Scanning projects...")

        if constants.PERFORMANCE_LOGGING_ENABLED: t_disk_scan_start = time.perf_counter()
        discovered_apps_on_disk = project_scanner.scan_projects_folder_for_app_data(self)
        if constants.PERFORMANCE_LOGGING_ENABLED: t_disk_scan_done = time.perf_counter()

        new_apps_data = {}
        for path_str, existing_app_data in self.apps_data.items():
            resolved_path_str = str(Path(path_str).resolve())
            if existing_app_data.get("process") is not None or \
               existing_app_data.get("status", "").startswith("Running") or \
               existing_app_data.get("status", "").endswith("..."):
                new_apps_data[resolved_path_str] = existing_app_data
                if resolved_path_str in discovered_apps_on_disk:
                    disk_data = discovered_apps_on_disk[resolved_path_str]
                    new_apps_data[resolved_path_str].update({
                        "is_installed": disk_data["is_installed"],
                        "package_data": disk_data["package_data"],
                        "name": disk_data["name"],
                        "git_branch": disk_data.get("git_branch", "-"),
                        "git_has_changes": disk_data.get("git_has_changes", "N/A")
                    })
            # else: project folder might have been removed or app was idle

        for path_str, disk_app_data in discovered_apps_on_disk.items():
            resolved_path_str = str(Path(path_str).resolve())
            if resolved_path_str not in new_apps_data:
                new_apps_data[resolved_path_str] = disk_app_data

        if constants.PERFORMANCE_LOGGING_ENABLED: t_external_scan_start = time.perf_counter()
        project_scanner.scan_for_external_processes(self, new_apps_data)
        if constants.PERFORMANCE_LOGGING_ENABLED: t_external_scan_done = time.perf_counter()

        self.apps_data = new_apps_data

        if constants.PERFORMANCE_LOGGING_ENABLED: t_ui_update_start = time.perf_counter()
        self._update_apps_list_display()
        if constants.PERFORMANCE_LOGGING_ENABLED: t_ui_update_done = time.perf_counter()

        if constants.PERFORMANCE_LOGGING_ENABLED:
            t_total_scan_end = time.perf_counter()
            self._log(
                f"Scan timing: Total={t_total_scan_end - t_total_scan_start:.4f}s, "
                f"DiskScan={t_disk_scan_done - t_disk_scan_start:.4f}s, "
                f"ExternalScan={t_external_scan_done - t_external_scan_start:.4f}s, "
                f"UIUpdate={t_ui_update_done - t_ui_update_start:.4f}s"
            )
        self._log(f"Scan complete. Found {len(self.apps_data)} potential Node projects.")
        self.update_status_bar(f"Scan complete. Found {len(self.apps_data)} projects.")

        current_selection = self.apps_tree.selection()
        if not current_selection and self.apps_tree.get_children():
            first_item_iid = self.apps_tree.get_children()[0]
            self.apps_tree.selection_set(first_item_iid)
            self.apps_tree.focus(first_item_iid)
            self._on_app_select()
        elif current_selection and not self.apps_tree.exists(current_selection[0]):
            self.selected_app_path = None
            self._on_app_select()
        else:
            self._update_action_buttons_state()


    def _update_apps_list_display(self):
        selected_iid = self.apps_tree.selection()[0] if self.apps_tree.selection() else None
        focused_iid = self.apps_tree.focus()

        for status_key_visual in constants.STATUS_VISUALS:
             _, tag_name, color_val = self._get_status_display_and_tag(status_key_visual)
             self.apps_tree.tag_configure(tag_name, foreground=color_val)

        self.apps_tree.delete(*self.apps_tree.get_children())

        sorted_app_items = sorted(self.apps_data.items(), key=lambda item: (item[1]["name"].lower(), item[0]))

        for path, data in sorted_app_items:
            current_status = data.get("status", "Unknown")
            display_name_original = data["name"]

            activity_prefix = ""
            base_status_for_prefix = current_status
            if current_status.startswith("Running Script:"):
                 base_status_for_prefix = "Running Script"
            elif current_status.endswith("..."):
                base_status_for_prefix = current_status[:-3]

            if base_status_for_prefix in self.ACTIVITY_PREFIX_MAP:
                activity_prefix = self.ACTIVITY_PREFIX_MAP[base_status_for_prefix]

            display_name_with_prefix = f"{activity_prefix}{display_name_original}"

            status_display, status_tag, color = self._get_status_display_and_tag(current_status)
            self.apps_tree.tag_configure(status_tag, foreground=color)

            try:
                self.apps_tree.insert("", tk.END, iid=path,
                                    values=(
                                        display_name_with_prefix,
                                        status_display,
                                        data.get("port", "-"),
                                        data.get("pid", "-"),
                                        data.get("git_branch", "-"),
                                        data.get("git_has_changes", "N/A")
                                    ),
                                    tags=(status_tag,))
            except tk.TclError as e:
                self._log(f"Error inserting item into Treeview for {data['name']} (Path: {path}): {e}. Tag: {status_tag}", error=True)

        if selected_iid and self.apps_tree.exists(selected_iid):
            self.apps_tree.selection_set(selected_iid)

        if focused_iid and self.apps_tree.exists(focused_iid):
            self.apps_tree.focus(focused_iid)


    def _on_app_select(self, event=None):
        if constants.PERFORMANCE_LOGGING_ENABLED: t_start = time.perf_counter()
        selected_items = self.apps_tree.selection()
        app_name_for_log = "None"

        if selected_items:
            new_selected_path = selected_items[0]
            if new_selected_path in self.apps_data:
                self.selected_app_path = new_selected_path
                app_name_for_log = self.apps_data[self.selected_app_path]["name"]
                self.update_status_bar(f"Selected: {app_name_for_log}")
                self._populate_npm_scripts_combo(self.selected_app_path)
            else:
                self.selected_app_path = None
                self.update_status_bar("Selected app no longer exists. Please re-scan.")
                self._clear_npm_scripts_combo()
        else:
            self.selected_app_path = None
            self.update_status_bar("No app selected.")
            self._clear_npm_scripts_combo()

        self._update_action_buttons_state()
        if constants.PERFORMANCE_LOGGING_ENABLED:
            t_end = time.perf_counter()
            duration = t_end - t_start
            if self.selected_app_path or selected_items :
                self._log(f"App select ('{app_name_for_log}') UI update: {duration:.4f}s", warning=(duration > 0.1))


    def _on_app_double_click(self, event=None):
        if not self.selected_app_path or self.selected_app_path not in self.apps_data:
            return
        app_data = self.apps_data[self.selected_app_path]
        status = app_data.get("status", "Unknown")

        is_busy_with_task = any(status.startswith(busy_state_prefix) for busy_state_prefix in self.ACTIVITY_PREFIX_MAP.keys())


        if status == "Running" and app_data.get("port", "-") != "-":
            self._view_in_browser()
        elif app_data.get("is_installed") and status not in ["Running", "Starting"] and not status.startswith("Running Script:") and not is_busy_with_task:
            self._start_app()
        else:
            self._open_project_folder()

    def _populate_npm_scripts_combo(self, app_path):
        if app_path and app_path in self.apps_data:
            app_data = self.apps_data[app_path]
            pkg_data = app_data.get("package_data")

            scripts = pkg_data.get("scripts", {}) if pkg_data else {}
            if not isinstance(scripts, dict):
                scripts = {}
                self._log(f"Warning: 'scripts' field in package.json for '{app_data['name']}' is not a dictionary. Treating as empty.", warning=True)

            script_names = list(scripts.keys())

            if script_names:
                self.npm_script_combo['values'] = script_names
                common_dev_scripts = ["dev", "serve", "start", "watch"]
                default_script_set = False
                for dev_script in common_dev_scripts:
                    if dev_script in script_names:
                        self.npm_script_combo.set(dev_script)
                        default_script_set = True
                        break
                if not default_script_set:
                    self.npm_script_combo.set(script_names[0])

                self.npm_script_combo.config(state="readonly")
            else:
                self._clear_npm_scripts_combo()
        else:
            self._clear_npm_scripts_combo()
        self._update_action_buttons_state()

    def _clear_npm_scripts_combo(self):
        self.npm_script_combo['values'] = []
        self.npm_script_combo.set("")
        self.npm_script_combo.config(state="disabled")


    def _update_action_buttons_state(self):
        if self.selected_app_path and self.selected_app_path in self.apps_data:
            app_data = self.apps_data[self.selected_app_path]
            status = app_data.get("status", "Unknown")
            is_installed = app_data.get("is_installed", False)

            is_busy_interim = status.endswith("...")
            explicit_busy_actions_prefixes = list(self.ACTIVITY_PREFIX_MAP.keys())
            is_busy_explicit_action = any(status.startswith(s) for s in explicit_busy_actions_prefixes)
            is_busy = is_busy_interim or is_busy_explicit_action


            has_port = app_data.get("port") and app_data.get("port") != "-"

            is_actually_running_process = status == "Running" or status.startswith("Running Script:")

            is_startable = is_installed and not is_actually_running_process and not is_busy
            is_stoppable = is_actually_running_process and not is_busy_interim

            self.start_button.config(state=tk.NORMAL if is_startable else tk.DISABLED)
            self.stop_button.config(state=tk.NORMAL if is_stoppable else tk.DISABLED)
            self.restart_button.config(state=tk.NORMAL if (is_stoppable or is_startable) and not is_busy else tk.DISABLED)
            self.view_browser_button.config(state=tk.NORMAL if status == "Running" and has_port and not is_busy else tk.DISABLED)

            self.install_button.config(state=tk.NORMAL if not is_busy else tk.DISABLED)
            self.update_deps_button.config(state=tk.NORMAL if is_installed and not is_busy else tk.DISABLED)
            self.audit_button.config(state=tk.NORMAL if is_installed and not is_busy else tk.DISABLED)

            path_exists = Path(self.selected_app_path).exists()
            self.open_folder_button.config(state=tk.NORMAL if path_exists and not is_busy else tk.DISABLED)
            self.view_pkg_button.config(state=tk.NORMAL if path_exists and app_data.get("package_data") and not is_busy else tk.DISABLED)
            self.edit_pkg_button.config(state=tk.NORMAL if path_exists and (Path(self.selected_app_path) / "package.json").exists() and not is_busy else tk.DISABLED)
            self.clean_deps_button.config(state=tk.NORMAL if path_exists and is_installed and not is_busy else tk.DISABLED)
            self.delete_project_button.config(state=tk.NORMAL if path_exists and not is_busy else tk.DISABLED)

            if self.npm_script_combo.cget('values') and not is_busy:
                self.run_script_button.config(state=tk.NORMAL)
                self.npm_script_combo.config(state="readonly")
            else:
                self.run_script_button.config(state=tk.DISABLED)
                if not self.npm_script_combo.cget('values'):
                    self.npm_script_combo.config(state="disabled")
                elif is_busy :
                     self.npm_script_combo.config(state="readonly")
        else:
            for btn in [self.start_button, self.stop_button, self.restart_button, self.view_browser_button,
                        self.install_button, self.update_deps_button, self.audit_button,
                        self.open_folder_button, self.view_pkg_button,
                        self.edit_pkg_button, self.clean_deps_button, self.delete_project_button,
                        self.run_script_button]:
                btn.config(state=tk.DISABLED)
            self.npm_script_combo.config(state="disabled")


    def _update_app_status(self, app_path, status=None, port=None, pid=None,
                           is_installed=None, process_obj=None, package_data=None, name=None,
                           git_branch=None, git_has_changes=None):
        resolved_app_path = str(Path(app_path).resolve())
        if resolved_app_path not in self.apps_data:
            self._log(f"Warning: Attempted to update status for app path '{resolved_app_path}' not in current data.", warning=True)
            return

        app_data_entry = self.apps_data[resolved_app_path]
        changed = False

        if status is not None and app_data_entry.get("status") != status:
            app_data_entry["status"] = status
            changed = True
        if port is not None and app_data_entry.get("port") != port:
            app_data_entry["port"] = port
            changed = True
        if pid is not None and app_data_entry.get("pid") != pid:
            app_data_entry["pid"] = pid
            changed = True
        if is_installed is not None and app_data_entry.get("is_installed") != is_installed:
            app_data_entry["is_installed"] = is_installed
            changed = True
        if process_obj is not Ellipsis:
            if app_data_entry.get("process") != process_obj:
                app_data_entry["process"] = process_obj
                changed = True
        if package_data is not None and app_data_entry.get("package_data") != package_data:
            app_data_entry["package_data"] = package_data
            changed = True
        if name is not None and app_data_entry.get("name") != name:
            app_data_entry["name"] = name
            changed = True
        if git_branch is not None and app_data_entry.get("git_branch") != git_branch:
            app_data_entry["git_branch"] = git_branch
            changed = True
        if git_has_changes is not None and app_data_entry.get("git_has_changes") != git_has_changes:
            app_data_entry["git_has_changes"] = git_has_changes
            changed = True


        if changed and self.apps_tree.exists(resolved_app_path):
            current_status_key = app_data_entry["status"]
            display_name_original = app_data_entry["name"]

            activity_prefix = ""
            base_status_for_prefix = current_status_key
            if current_status_key.startswith("Running Script:"):
                 base_status_for_prefix = "Running Script"
            elif current_status_key.endswith("..."):
                base_status_for_prefix = current_status_key[:-3]

            if base_status_for_prefix in self.ACTIVITY_PREFIX_MAP:
                activity_prefix = self.ACTIVITY_PREFIX_MAP[base_status_for_prefix]

            display_name_with_prefix = f"{activity_prefix}{display_name_original}"

            status_display, status_tag, color = self._get_status_display_and_tag(current_status_key)
            self.apps_tree.tag_configure(status_tag, foreground=color)

            self.apps_tree.item(resolved_app_path, values=(
                display_name_with_prefix,
                status_display,
                app_data_entry.get("port", "-"),
                app_data_entry.get("pid", "-"),
                app_data_entry.get("git_branch", "-"),
                app_data_entry.get("git_has_changes", "N/A")
            ), tags=(status_tag,))

        if self.selected_app_path == resolved_app_path:
            self._update_action_buttons_state()
            if name is not None or package_data is not None:
                self._populate_npm_scripts_combo(resolved_app_path)


    # --- App Actions & Utilities (delegated or direct) ---
    def _install_deps(self):
        if self.selected_app_path:
            process_handler.install_dependencies_logic(self, self.selected_app_path)

    def _update_deps(self):
        if self.selected_app_path:
            process_handler.npm_update_dependencies_logic(self, self.selected_app_path)

    def _npm_audit(self):
        if self.selected_app_path:
            process_handler.npm_audit_logic(self, self.selected_app_path)

    def _start_app(self, app_path_override=None):
        app_to_start = app_path_override or self.selected_app_path
        if app_to_start:
            process_handler.start_app_logic(self, app_to_start)

    def _stop_app(self, app_path_override=None, callback=None):
        app_to_stop = app_path_override or self.selected_app_path
        if app_to_stop:
            process_handler.stop_app_logic(self, app_to_stop, callback=callback)

    def _restart_app(self):
        if not self.selected_app_path or self.selected_app_path not in self.apps_data: return

        app_path = self.selected_app_path
        app_data = self.apps_data[app_path]
        app_name = app_data["name"]
        self.update_status_bar(f"Restarting {app_name}...")

        current_status = app_data.get("status")
        is_running_type = current_status == "Running" or current_status.startswith("Running Script:")
        can_be_stopped_for_restart = is_running_type or current_status == "Starting..."


        if can_be_stopped_for_restart:
            self._log(f"Restart: Stopping '{app_name}' (status: {current_status}) first...")
            def after_stop_for_restart():
                if app_path in self.apps_data and self.apps_data[app_path]["status"] == "Stopped":
                    self._log(f"Restart: '{app_name}' stopped. Now starting...")
                    self._start_app(app_path_override=app_path)
                else:
                    current_state_after_stop_attempt = "Unknown or Removed"
                    if app_path in self.apps_data:
                        current_state_after_stop_attempt = self.apps_data[app_path].get("status", "Error/Removed")
                    self._log(f"Restart: Failed to stop '{app_name}' cleanly or app state changed. Current state: {current_state_after_stop_attempt}. Aborting restart.", error=True)
                    self.update_status_bar(f"Restart failed for {app_name}.")
                    if app_path in self.apps_data:
                         self._update_app_status(app_path, status=current_state_after_stop_attempt)
            self._stop_app(app_path_override=app_path, callback=after_stop_for_restart)
        elif app_data.get("is_installed"):
            self._log(f"Restart: '{app_name}' is not running (Status: {current_status}). Starting directly...")
            self._start_app(app_path_override=app_path)
        else:
             self._log(f"Restart: '{app_name}' cannot be restarted (Status: {current_status}, Installed: {app_data.get('is_installed')}). Try installing first.", warning=True)
             self.update_status_bar(f"Cannot restart {app_name}. Check status/installation.")


    def _run_npm_script(self):
        if not self.selected_app_path or self.selected_app_path not in self.apps_data: return
        script_name = self.npm_script_var.get()
        if not script_name:
            messagebox.showwarning("No Script Selected", "Please select an NPM script from the dropdown.", parent=self)
            return

        process_handler.run_npm_script_logic(self, self.selected_app_path, script_name)

    def _view_in_browser(self):
        if not self.selected_app_path or self.selected_app_path not in self.apps_data: return
        app_data = self.apps_data[self.selected_app_path]
        app_name = app_data["name"]
        port = app_data.get("port")

        if app_data.get("status") == "Running" and port and port != "-":
            url = f"http://localhost:{port}"
            self._log(f"Opening '{app_name}' in browser: {url}")
            self.update_status_bar(f"Opening {url}...")
            try:
                webbrowser.open(url, new=2)
            except Exception as e:
                self._log(f"Error opening browser: {e}", error=True)
                messagebox.showerror("Browser Error", f"Could not open browser: {e}", parent=self)
        else:
            self._log(f"Cannot view '{app_name}' in browser. Not running or port unknown.", warning=True)
            messagebox.showinfo("Cannot View", f"'{app_name}' is not running or its port is not detected.", parent=self)

    def _clean_dependencies(self):
        if self.selected_app_path:
            process_handler.clean_dependencies_logic(self, self.selected_app_path)

    def _delete_project(self):
        if self.selected_app_path:
            process_handler.delete_project_logic(self, self.selected_app_path)

    def _remove_app_from_gui(self, app_path_str):
        resolved_app_path = str(Path(app_path_str).resolve())
        if self.apps_tree.exists(resolved_app_path):
            self.apps_tree.delete(resolved_app_path)
        if resolved_app_path in self.apps_data:
            del self.apps_data[resolved_app_path]

        if self.selected_app_path == resolved_app_path:
            self.selected_app_path = None
            self.update_status_bar("Selected app was removed.")
            children = self.apps_tree.get_children()
            if children:
                self.apps_tree.selection_set(children[0])
                self.apps_tree.focus(children[0])
                self._on_app_select()
            else:
                self._on_app_select()
        else:
            self._update_action_buttons_state()


    def _open_project_folder(self):
        if not self.selected_app_path or self.selected_app_path not in self.apps_data: return
        proj_path_str = self.selected_app_path
        proj_path = Path(proj_path_str)

        if not proj_path.exists():
            messagebox.showerror("Error", f"Project folder not found:\n{proj_path}", parent=self)
            self.scan_projects_folder()
            return

        app_name = self.apps_data[proj_path_str]["name"]
        self.update_status_bar(f"Opening folder for {app_name}...")
        try:
            if sys.platform == "win32": os.startfile(proj_path_str)
            elif sys.platform == "darwin": subprocess.run(['open', proj_path_str], check=True)
            else: subprocess.run(['xdg-open', proj_path_str], check=True)
        except Exception as e:
            self._log(f"Error opening folder {proj_path_str}: {e}", error=True)
            messagebox.showerror("Error", f"Could not open folder '{proj_path_str}':\n{e}", parent=self)

    def _view_package_json(self):
        if not self.selected_app_path or self.selected_app_path not in self.apps_data: return

        app_path_str = self.selected_app_path
        app_data = self.apps_data[app_path_str]
        app_name = app_data["name"]

        pkg_path = Path(app_path_str) / "package.json"
        if not pkg_path.exists():
            messagebox.showerror("Error", f"package.json not found for '{app_name}'.\nPath: {pkg_path}", parent=self)
            self._update_app_status(app_path_str, status="Error (package.json)", package_data=None)
            return

        try:
            with open(pkg_path, 'r', encoding='utf-8') as f:
                current_pkg_data_on_disk = json.load(f)
            new_name_from_pkg = current_pkg_data_on_disk.get("name", app_name)
            if app_data.get("package_data") != current_pkg_data_on_disk or app_data["name"] != new_name_from_pkg:
                self._update_app_status(app_path_str, package_data=current_pkg_data_on_disk, name=new_name_from_pkg)
        except Exception as e:
            messagebox.showerror("Error", f"Could not read or parse package.json for '{app_name}':\n{e}", parent=self)
            self._update_app_status(app_path_str, status="Error (package.json)", package_data=None)
            return

        ui_dialogs.show_package_json_viewer(self, self.apps_data[app_path_str].copy(), app_name)


    def _edit_package_json(self):
        if not self.selected_app_path or self.selected_app_path not in self.apps_data: return

        app_path_str = self.selected_app_path
        app_name = self.apps_data[app_path_str]["name"]
        pkg_json_path = Path(app_path_str) / "package.json"

        if not pkg_json_path.exists():
            messagebox.showerror("Error", f"package.json not found for '{app_name}' at\n{pkg_json_path}", parent=self)
            return

        self.update_status_bar(f"Opening package.json for {app_name} in default editor...")
        self._log(f"Attempting to open {pkg_json_path} for editing.")
        try:
            if sys.platform == "win32": os.startfile(str(pkg_json_path))
            elif sys.platform == "darwin": subprocess.run(['open', str(pkg_json_path)], check=True)
            else: subprocess.run(['xdg-open', str(pkg_json_path)], check=True)

            self.after(2000, lambda p=app_path_str, n=app_name: self._prompt_rescan_project_properties(p, n))

        except Exception as e:
            self._log(f"Error opening package.json for editing: {e}", error=True)
            messagebox.showerror("Error", f"Could not open {pkg_json_path} for editing:\n{e}", parent=self)

    def _prompt_rescan_project_properties(self, app_path_str, app_name):
        if messagebox.askyesno("Rescan Project?",
                               f"'{app_name}'s package.json may have been modified.\n"
                               f"Would you like to re-read its properties (name, scripts, etc.)?",
                               parent=self):
            self._reread_package_json_for_app(app_path_str)


    def _reread_package_json_for_app(self, app_path_str):
        resolved_app_path = str(Path(app_path_str).resolve())
        if resolved_app_path not in self.apps_data:
            self._log(f"Cannot re-read package.json, app '{resolved_app_path}' no longer in data.", warning=True)
            return

        app_data_entry = self.apps_data[resolved_app_path]
        original_name = app_data_entry['name']
        pkg_json_file_path = Path(resolved_app_path) / "package.json"

        if pkg_json_file_path.exists():
            try:
                with open(pkg_json_file_path, 'r', encoding='utf-8') as f:
                    new_pkg_data = json.load(f)
                new_name = new_pkg_data.get("name", original_name)

                self._update_app_status(resolved_app_path, package_data=new_pkg_data, name=new_name)
                self._log(f"Re-read package.json for '{new_name}'. A full 'Re-Scan All' may be needed for Git status if .git folder was affected.")

            except Exception as e:
                self._log(f"Error re-reading package.json for '{original_name}': {e}", error=True)
                self._update_app_status(resolved_app_path, status="Error (package.json)", package_data=None)
        else:
            self._log(f"package.json not found for '{original_name}' during re-read attempt.", error=True)
            self._update_app_status(resolved_app_path, status="Error (package.json)", package_data=None)


    # --- Dialogs & Global Actions ---
    def _fetch_online_app_dialog(self):
        ui_dialogs.show_fetch_online_app_dialog(self)

    def _create_basic_project_dialog(self):
        project_name_input = simpledialog.askstring("Create Basic Project", "Enter new project name:", parent=self)
        if not project_name_input:
            self._log("Create basic project cancelled or no name entered.")
            return

        sane_project_name = "".join(c for c in project_name_input if c.isalnum() or c in ('-', '_')).strip()
        if not sane_project_name:
            messagebox.showerror("Invalid Name", "Project name is invalid after sanitization. Please use alphanumeric characters, hyphens, or underscores.", parent=self)
            return

        project_dir = Path(self.projects_folder.get()) / sane_project_name
        if project_dir.exists():
            messagebox.showerror("Error", f"Folder '{sane_project_name}' already exists in your projects directory ({self.projects_folder.get()}).", parent=self)
            return

        try:
            project_dir.mkdir(parents=True, exist_ok=True)

            pkg_json_content = {
                "name": sane_project_name, "version": "0.1.0",
                "description": f"Basic Node.js project: {sane_project_name}",
                "main": "index.js",
                "scripts": { "start": "node index.js", "test": "echo \"Error: no test specified\" && exit 1" },
                "keywords": [], "author": "", "license": "ISC"
            }
            with open(project_dir / "package.json", "w", encoding='utf-8') as f:
                json.dump(pkg_json_content, f, indent=2)

            index_js_content = (
                "// Basic Node.js server\nconst http = require('http');\n\n"
                "const hostname = '127.0.0.1';\nconst port = 3000;\n\n"
                "const server = http.createServer((req, res) => {\n"
                "  res.statusCode = 200;\n  res.setHeader('Content-Type', 'text/plain');\n"
                "  res.end('Hello, Node.js World!\\n');\n});\n\n"
                "server.listen(port, hostname, () => {\n"
                f"  console.log(`Server running at http://${{hostname}}:${{port}}/ for project {sane_project_name}`);\n"
                "});\n"
            )
            with open(project_dir / "index.js", "w", encoding='utf-8') as f:
                f.write(index_js_content)

            self._log(f"Created basic project: '{sane_project_name}' at {project_dir}")
            messagebox.showinfo("Success", f"Basic project '{sane_project_name}' created successfully.", parent=self)
            self.scan_projects_folder()

        except Exception as e:
            self._log(f"Error creating basic project '{sane_project_name}': {e}", error=True)
            messagebox.showerror("Error", f"Could not create project '{sane_project_name}':\n{e}", parent=self)
            if project_dir.exists():
                try:
                    import shutil
                    shutil.rmtree(project_dir)
                    self._log(f"Cleaned up partially created directory: {project_dir}", warning=True)
                except Exception as clean_e:
                    self._log(f"Error during cleanup of {project_dir}: {clean_e}", warning=True)


    def _stop_all_running_apps(self):
        running_app_paths = []
        for path, data in self.apps_data.items():
            status = data.get("status", "Unknown")
            if status == "Running" or status.startswith("Running Script:") or status == "Starting...":
                running_app_paths.append(path)

        if not running_app_paths:
            messagebox.showinfo("No Apps Running", "No applications are currently in a running or starting state.", parent=self)
            return

        num_running = len(running_app_paths)
        plural_s = "s" if num_running > 1 else ""
        verb_s = "" if num_running > 1 else "s"
        if messagebox.askyesno("Confirm Stop All",
                               f"{num_running} app{plural_s} appear{verb_s} to be active. Stop them all?",
                               icon='warning', parent=self):
            self._log(f"Attempting to stop {num_running} active app{plural_s}...")
            self.update_status_bar(f"Stopping {num_running} app{plural_s}...")

            for app_path_to_stop in running_app_paths:
                app_name = self.apps_data.get(app_path_to_stop, {}).get("name", Path(app_path_to_stop).name)
                self._log(f"Initiating stop for '{app_name}'...")
                self._stop_app(app_path_override=app_path_to_stop)

            self.after(1000, lambda n=num_running, s_val=plural_s: self.update_status_bar(f"Stop command issued for {n} app{s_val}."))


    # --- Application Closing ---
    def on_closing(self):
        self.config_manager.save_config()
        self.update_status_bar("Application closing...")

        active_apps_paths = [
            path for path, data in self.apps_data.items()
            if data.get("status") == "Running" or data.get("status", "").startswith("Running Script:") or data.get("status") == "Starting..."
        ]

        if active_apps_paths:
            num_active = len(active_apps_paths)
            plural_s = "s" if num_active > 1 else ""
            verb_s = "" if num_active > 1 else "s"
            msg = f"{num_active} app{plural_s} appear{verb_s} to be active. Stop them before exiting?"
            if messagebox.askyesno("Confirm Exit", msg, icon='warning', parent=self):
                self.update_status_bar("Stopping active apps before exit...")
                self._log("Attempting to stop all active apps before exit...")

                stop_events = {path: threading.Event() for path in active_apps_paths}

                for app_path_to_stop in active_apps_paths:
                    event_for_app = stop_events[app_path_to_stop]
                    self._stop_app(app_path_override=app_path_to_stop,
                                   callback=lambda e=event_for_app: e.set())

                self._log("Waiting for apps to signal stop completion...")
                all_stopped_gracefully = True
                timeout_per_app = 7

                for app_path, event in stop_events.items():
                    app_name_for_log = self.apps_data.get(app_path, {}).get("name", f"App at {Path(app_path).name}")
                    if not event.wait(timeout=timeout_per_app):
                        self._log(f"Timeout waiting for '{app_name_for_log}' to stop.", warning=True)
                        all_stopped_gracefully = False
                    else:
                        self._log(f"'{app_name_for_log}' signaled stop completion.")

                if all_stopped_gracefully:
                    self._log("All targeted apps appear to have completed their stop sequence.")
                else:
                    self._log("Some apps may not have stopped gracefully or timed out.", warning=True)
            else:
                self._log("Exiting without stopping active apps.")
        else:
            self._log("No apps active. Exiting application.")

        self.destroy()


if __name__ == "__main__":
    app = NodeAppManager()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()