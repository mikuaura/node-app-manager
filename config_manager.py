# config_manager.py
import json
from pathlib import Path
import sys
import os
import constants

def get_app_config_dir():
    """Gets the OS-dependent application configuration directory."""
    app_name = constants.APP_NAME_FOR_CONFIG
    if sys.platform == "win32":
        # %APPDATA%\AppName
        return Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming")) / app_name
    elif sys.platform == "darwin":
        # ~/Library/Application Support/AppName
        return Path.home() / "Library" / "Application Support" / app_name
    else: # Linux and other XDG-based systems
        # ~/.config/AppName
        return Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config")) / app_name

class ConfigManager:
    def __init__(self, app_instance):
        self.app = app_instance
        self.config_dir = get_app_config_dir()
        self.config_file_path = self.config_dir / constants.CONFIG_FILE_NAME
        self.data = {}

    def get_default_projects_folder(self):
        default_folder = Path(constants.DEFAULT_PROJECTS_FOLDER_STR).expanduser()
        if not default_folder.exists():
            try:
                default_folder.mkdir(parents=True, exist_ok=True)
                self.app._log(f"Created default projects folder: {default_folder}")
            except Exception as e:
                self.app._log(f"Could not create default projects folder {default_folder}: {e}", error=True)
                # Fallback to a user's home subfolder if primary default fails
                home_fallback = Path.home() / "node_app_manager_projects" # Simplified fallback
                try:
                    home_fallback.mkdir(parents=True, exist_ok=True)
                    self.app._log(f"Using fallback projects folder: {home_fallback}")
                    return str(home_fallback)
                except Exception as e_fb:
                    self.app._log(f"Could not create fallback projects folder {home_fallback}: {e_fb}", error=True)
                    return str(Path.home())
        return str(default_folder)


    def load_config(self):
        if self.config_file_path.exists():
            try:
                with open(self.config_file_path, 'r', encoding='utf-8') as f:
                    self.data = json.load(f)
                self.app._log(f"Config loaded from: {self.config_file_path}")
            except json.JSONDecodeError:
                self.app._log(f"Error decoding config file: {self.config_file_path}. Using defaults.", error=True)
                self.data = {}
            except Exception as e:
                self.app._log(f"Error loading config file {self.config_file_path}: {e}. Using defaults.", error=True)
                self.data = {}
        else:
            self.app._log(f"Config file not found at {self.config_file_path}. Using defaults.")
            self.data = {} # Ensure data is an empty dict if file not found

        if "projects_folder" not in self.data or not self.data["projects_folder"]: # Also check if empty
            self.data["projects_folder"] = self.get_default_projects_folder()
        if "theme" not in self.data and constants.TTKTHEMES_AVAILABLE:
             self.data["theme"] = "arc"

        return self.data

    def save_config(self):
        self.data["projects_folder"] = self.app.projects_folder.get()
        if constants.TTKTHEMES_AVAILABLE and hasattr(self.app, 'get_theme'):
            try:
                current_theme = self.app.get_theme()
                if current_theme:
                    self.data["theme"] = current_theme
            except Exception as e:
                self.app._log(f"Could not get current theme to save: {e}", warning=True)

        try:
            self.config_dir.mkdir(parents=True, exist_ok=True) # Ensure directory exists
            with open(self.config_file_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2)
            self.app._log(f"Config saved to: {self.config_file_path}")
        except Exception as e:
            self.app._log(f"Error saving config file {self.config_file_path}: {e}", error=True)