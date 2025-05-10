# project_scanner.py
import json
import psutil
from pathlib import Path
import subprocess # Added for Git commands
import os # Added for subprocess flags
import constants

def scan_for_external_processes(app, projects_map):
    app._log("Scanning for externally running Node processes...")
    externally_running_paths = set()
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cwd', 'cmdline']):
            if proc.info['name'] and (proc.info['name'].lower() in constants.NODE_EXE_NAMES):
                try:
                    proc_cwd_str = proc.info['cwd']
                    if not proc_cwd_str: continue

                    proc_cwd_path = Path(proc_cwd_str).resolve()

                    for proj_path_str, app_data_ref in projects_map.items():
                        proj_path_resolved = Path(proj_path_str).resolve()

                        if proc_cwd_path == proj_path_resolved or proj_path_resolved in proc_cwd_path.parents:
                            if app_data_ref.get("process") is None and app_data_ref.get("status") not in ["Starting...", "Stopping..."]: # Adjusted status check
                                app._log(f"Detected external process PID {proc.info['pid']} for '{app_data_ref['name']}'")
                                app_data_ref["status"] = "Running"
                                app_data_ref["pid"] = proc.info['pid']

                                # Attempt to detect port for external process
                                detected_port = app_data_ref.get("port", "-") # Keep old port if any
                                try:
                                    p_obj = psutil.Process(proc.info['pid'])
                                    connections = p_obj.connections(kind='inet')
                                    for conn in connections:
                                        if conn.status == psutil.CONN_LISTEN and conn.laddr and conn.laddr.port:
                                            detected_port = conn.laddr.port
                                            app._log(f"Detected port {detected_port} for external PID {proc.info['pid']} ('{app_data_ref['name']}')")
                                            break
                                except psutil.AccessDenied:
                                    app._log(f"Access denied getting connections for PID {proc.info['pid']}", warning=True)
                                except psutil.NoSuchProcess:
                                    pass # Process might have died quickly
                                except Exception as e_conn:
                                    app._log(f"Error getting connections for PID {proc.info['pid']}: {e_conn}", warning=True)
                                app_data_ref["port"] = detected_port

                                app_data_ref["process"] = None
                                externally_running_paths.add(proj_path_str)
                            break
                except (psutil.NoSuchProcess, psutil.AccessDenied, FileNotFoundError):
                    continue
                except Exception as e_inner:
                    app._log(f"Minor error checking process PID {proc.info.get('pid', 'N/A')}: {e_inner}", warning=True)
    except Exception as e_outer:
        app._log(f"Error during external process scan: {e_outer}", error=True)
    return externally_running_paths

def scan_projects_folder_for_app_data(app):
    folder_path = Path(app.projects_folder.get())
    discovered_apps = {}
    if not folder_path.is_dir():
        app._log(f"Error: Projects folder '{folder_path}' not found or is not a directory.", error=True)
        app.update_status_bar(f"Error: Projects folder '{folder_path}' not found.")
        return discovered_apps # Return empty dict

    process_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

    for item in folder_path.iterdir():
        if item.is_dir():
            package_json_path = item / "package.json"
            project_name = item.name
            app_path_str = str(item.resolve()) # Use resolved path as key

            if package_json_path.exists():
                app_entry = {
                    "name": project_name, "status": "Unknown", "process": None,
                    "port": "-", "pid": "-", "package_data": None, "is_installed": False,
                    "path": app_path_str, # Store the resolved path
                    "git_branch": "-", # Initialize Git Branch
                    "git_has_changes": "N/A" # Initialize Git Changes Status (N/A, No, Yes, Error)
                }
                try:
                    with open(package_json_path, 'r', encoding='utf-8') as f:
                        app_entry["package_data"] = json.load(f)
                    app_entry["name"] = app_entry["package_data"].get("name", project_name)
                    app_entry["is_installed"] = (item / "node_modules").exists()
                    app_entry["status"] = "Installed" if app_entry["is_installed"] else "Not Installed"
                except Exception as e:
                    app._log(f"Error processing package.json for {project_name}: {e}", error=True)
                    app_entry["status"] = "Error (package.json)"

                # --- Git Info Detection ---
                git_dir = item / ".git"
                if git_dir.is_dir():
                    try:
                        # Get branch
                        branch_proc = subprocess.run(
                            [constants.GIT_CMD, "rev-parse", "--abbrev-ref", "HEAD"],
                            cwd=str(item), capture_output=True, text=True, check=False, # check=False for robustness
                            encoding='utf-8', errors='replace', creationflags=process_flags
                        )
                        if branch_proc.returncode == 0 and branch_proc.stdout.strip():
                            current_branch_name = branch_proc.stdout.strip()
                            if current_branch_name == "HEAD": # Detached HEAD state
                                commit_hash_proc = subprocess.run(
                                    [constants.GIT_CMD, "rev-parse", "--short", "HEAD"],
                                    cwd=str(item), capture_output=True, text=True, check=False,
                                    encoding='utf-8', errors='replace', creationflags=process_flags
                                )
                                if commit_hash_proc.returncode == 0 and commit_hash_proc.stdout.strip():
                                    app_entry["git_branch"] = f"DETACHED ({commit_hash_proc.stdout.strip()})"
                                else:
                                    app_entry["git_branch"] = "DETACHED" # Fallback if short hash fails
                            else:
                                app_entry["git_branch"] = current_branch_name
                        else:
                            app_entry["git_branch"] = "Error (branch)"
                            if branch_proc.stderr.strip():
                                app._log(f"Git branch check failed for '{project_name}': {branch_proc.stderr.strip()}", warning=True)

                        # Check for uncommitted changes
                        status_proc = subprocess.run(
                            [constants.GIT_CMD, "status", "--porcelain"],
                            cwd=str(item), capture_output=True, text=True, check=False,
                            encoding='utf-8', errors='replace', creationflags=process_flags
                        )
                        if status_proc.returncode == 0:
                            app_entry["git_has_changes"] = "Yes" if status_proc.stdout.strip() else "No"
                        else:
                            app_entry["git_has_changes"] = "Error (status)"
                            if status_proc.stderr.strip():
                                app._log(f"Git status check failed for '{project_name}': {status_proc.stderr.strip()}", warning=True)

                    except FileNotFoundError:
                        app._log(f"Git command ('{constants.GIT_CMD}') not found while checking '{project_name}'. Git info unavailable.", warning=True)
                        app_entry["git_branch"] = "N/A (No Git)"
                        app_entry["git_has_changes"] = "N/A (No Git)"
                    except Exception as e_git:
                        app._log(f"Error getting Git info for '{project_name}': {e_git}", error=True)
                        app_entry["git_branch"] = "Error (Exception)"
                        app_entry["git_has_changes"] = "Error (Exception)"
                else: # Not a git repo (no .git folder)
                    app_entry["git_branch"] = "-"
                    app_entry["git_has_changes"] = "N/A" # Or simply "-"

                discovered_apps[app_path_str] = app_entry
            else:
                app._log(f"Skipping '{project_name}': no package.json found.")
    return discovered_apps