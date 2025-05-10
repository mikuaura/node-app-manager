# constants.py
from pathlib import Path
import sys

# --- Performance Logging ---
PERFORMANCE_LOGGING_ENABLED = False # Set to True to enable performance logs

# --- TTKThemes ---
TTKTHEMES_AVAILABLE = False
try:
    from ttkthemes import ThemedTk
    TTKTHEMES_AVAILABLE = True
except ImportError:
    pass # Will be handled in main app

# --- Paths & Config ---
DEFAULT_PROJECTS_FOLDER_STR = "C:/node_projects" if sys.platform == "win32" else "~/node_projects"
APP_NAME_FOR_CONFIG = "NodeAppManager" # Used for creating app-specific config folder
CONFIG_FILE_NAME = "config.json" # General name, will be inside APP_NAME_FOR_CONFIG folder

# --- Commands ---
NPM_CMD = "npm.cmd" if sys.platform == "win32" else "npm"
NODE_CMD = "node.exe" if sys.platform == "win32" else "node"
GIT_CMD = "git.exe" if sys.platform == "win32" else "git"

# --- Process & Project Detection ---
NODE_EXE_NAMES = {"node", "node.exe"}
COMMON_ENTRY_FILES = ["index.js", "app.js", "server.js", "main.js"]

# --- Status Visuals ---
STATUS_VISUALS = {
    "Running": {"color": "#2ECC71", "symbol": "🟢"},
    "Starting": {"color": "#F39C12", "symbol": "🟠"},
    "Stopping": {"color": "#F39C12", "symbol": "🟠"},
    "Installed": {"color": "#3498DB", "symbol": "🔵"},
    "Not Installed": {"color": "#95A5A6", "symbol": "⚪"},
    "Stopped": {"color": "#E74C3C", "symbol": "🔴"},
    "Error (Install)": {"color": "#C0392B", "symbol": "❌"},
    "Error (Runtime)": {"color": "#C0392B", "symbol": "❌"},
    "Error (Start Fail)": {"color": "#C0392B", "symbol": "❌"},
    "Error (Stop)": {"color": "#C0392B", "symbol": "❌"},
    "Error (Command)": {"color": "#C0392B", "symbol": "❌"},
    "Error (Exception)": {"color": "#C0392B", "symbol": "❌"},
    "Error (package.json)": {"color": "#C0392B", "symbol": "❌"},
    "Error (No Start)": {"color": "#C0392B", "symbol": "❌"},
    "Error (Delete)": {"color": "#C0392B", "symbol": "❌"},
    "Error (Clean)": {"color": "#C0392B", "symbol": "❌"},
    "Error (Script)": {"color": "#C0392B", "symbol": "❌"},
    "Error (Audit)": {"color": "#C0392B", "symbol": "❌"},
    "Error (Update)": {"color": "#C0392B", "symbol": "❌"},
    "Unknown": {"color": "#7F8C8D", "symbol": "❓"},
    "Installing": {"color": "#F39C12", "symbol": "⏳"},
    "Cleaning": {"color": "#F39C12", "symbol": "🧹"},
    "Deleting": {"color": "#E74C3C", "symbol": "🗑️"},
    "Running Script": {"color": "#F39C12", "symbol": "⚙️"},
    "Auditing": {"color": "#F39C12", "symbol": "🛡️"}, 
    "Updating Deps": {"color": "#F39C12", "symbol": "🔄"}, 
}

# --- Log Prefixes ---
LOG_PREFIX_INFO = ""
LOG_PREFIX_WARNING = "[WARN] "
LOG_PREFIX_ERROR = "[ERR] "