# ui_dialogs.py
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
import os
import json
import subprocess
import threading
from pathlib import Path
import shutil # For fetch app cleanup

import constants # constants.py

def show_package_json_viewer(app, app_data_copy, app_name):
    pkg_window = tk.Toplevel(app)
    pkg_window.title(f"package.json - {app_name}")
    pkg_window.geometry("600x500")
    try:
        pkg_window.transient(app) 
        pkg_window.grab_set()      
    except tk.TclError: 
        app._log("Could not make package.json viewer transient or grab_set.", warning=True)

    text_area = scrolledtext.ScrolledText(pkg_window, wrap=tk.WORD, 
                                          font=("Consolas", 9) if sys.platform == "win32" else ("Monaco", 10))
    text_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
    
    try:
        # Use the provided copy of app_data for display
        pretty_json = json.dumps(app_data_copy.get("package_data", {"error": "No package_data found in provided data"}), indent=2)
        text_area.insert(tk.END, pretty_json)
    except Exception as e:
        text_area.insert(tk.END, f"Error formatting JSON: {e}\n\nRaw data:\n{app_data_copy.get('package_data', {})}")
    text_area.config(state=tk.DISABLED)
    
    # Add a close button
    close_button = ttk.Button(pkg_window, text="Close", command=pkg_window.destroy)
    close_button.pack(pady=(0, 10))
    
    pkg_window.focus_set()


def show_fetch_online_app_dialog(app):
    dialog = tk.Toplevel(app)
    dialog.title("Fetch Online Node App")
    dialog.geometry("450x300") # Slightly taller for potentially longer error messages
    try:
        dialog.transient(app)
        dialog.grab_set()
    except tk.TclError:
        app._log("Could not make fetch dialog transient or grab_set.", warning=True)


    ttk.Label(dialog, text="NPM Package Name or Git URL:").pack(pady=(10,0), padx=10, anchor="w")
    source_entry = ttk.Entry(dialog, width=60)
    source_entry.pack(pady=2, padx=10, fill=tk.X)
    source_entry.focus() 

    ttk.Label(dialog, text="Local Folder Name (optional, derived if empty):").pack(pady=(5,0), padx=10, anchor="w")
    name_entry = ttk.Entry(dialog, width=60)
    name_entry.pack(pady=2, padx=10, fill=tk.X)

    status_label = ttk.Label(dialog, text="", wraplength=400) # Wraplength for longer messages
    status_label.pack(pady=5, padx=10, fill=tk.X)

    progress_bar = ttk.Progressbar(dialog, mode='indeterminate')
    # progress_bar is packed when fetch starts

    def do_fetch():
        source = source_entry.get().strip()
        local_name_override = name_entry.get().strip()
        if not source:
            messagebox.showerror("Input Error", "Package name or Git URL is required.", parent=dialog)
            return

        if local_name_override:
            target_folder_name = "".join(c for c in local_name_override if c.isalnum() or c in ('-', '_')).strip()
            if not target_folder_name:
                messagebox.showerror("Input Error", "Local folder name is invalid after sanitization.", parent=dialog)
                return
        elif ".git" in source or source.startswith("git@") or (source.startswith("http") and ".git" in source):
            base_name = source.split('/')[-1]
            raw_folder_name = base_name.removesuffix('.git') if hasattr(str, 'removesuffix') else base_name[:-4] if base_name.endswith('.git') else base_name
            target_folder_name = "".join(c for c in raw_folder_name if c.isalnum() or c in ('-', '_')).strip()
        else: 
            raw_folder_name = source.split('@')[0].split('/')[-1] 
            target_folder_name = "".join(c for c in raw_folder_name if c.isalnum() or c in ('-', '_')).strip()
        
        if not target_folder_name:
             messagebox.showerror("Input Error", "Could not derive a valid local folder name.", parent=dialog)
             return

        target_dir = Path(app.projects_folder.get()) / target_folder_name
        if target_dir.exists():
            messagebox.showerror("Error", f"Folder '{target_dir.name}' already exists in projects directory.", parent=dialog)
            return

        fetch_button.config(state=tk.DISABLED)
        cancel_button.config(state=tk.DISABLED) 
        status_label.config(text=f"Preparing to fetch '{source}'...")
        progress_bar.pack(pady=5, padx=10, fill=tk.X)
        progress_bar.start(10) 
        dialog.update_idletasks()

        def fetch_task():
            cmd_list_git = None
            cmd_list_npm_install_after_clone = None
            cmd_list_npm_pkg_install = None
            try:
                target_dir.mkdir(parents=True, exist_ok=True) 
                process_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                
                is_git_clone = ".git" in source or source.startswith("git@") or \
                               (source.startswith("http") and ".git" in source)

                if is_git_clone:
                    app.after(0, lambda s=f"Cloning '{source}'...": [app._log(s), status_label.config(text=s)])
                    cmd_list_git = [constants.GIT_CMD, "clone", source, str(target_dir)]
                    proc_git = subprocess.Popen(cmd_list_git, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', creationflags=process_flags)
                    stdout_git, stderr_git = proc_git.communicate()
                    if stdout_git: app.after(0, lambda log=f"[{target_dir.name} GIT STDOUT] {stdout_git.strip()}": app._log(log))
                    if stderr_git: app.after(0, lambda log=f"[{target_dir.name} GIT STDERR] {stderr_git.strip()}": app._log(log, warning=(proc_git.returncode==0), error=(proc_git.returncode!=0)))
                    if proc_git.returncode != 0: raise Exception(f"Git clone failed.") 
                    
                    app.after(0, lambda s=f"'{target_dir.name}' cloned. Running npm install...": [app._log(s), status_label.config(text=s)])
                    cmd_list_npm_install_after_clone = [constants.NPM_CMD, "install"]
                    install_proc = subprocess.Popen(cmd_list_npm_install_after_clone, cwd=target_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', creationflags=process_flags)
                    inst_stdout, inst_stderr = install_proc.communicate()
                    if inst_stdout: app.after(0, lambda log=f"[{target_dir.name} NPM STDOUT] {inst_stdout.strip()}": app._log(log))
                    if inst_stderr: app.after(0, lambda log=f"[{target_dir.name} NPM STDERR] {inst_stderr.strip()}": app._log(log, warning=(install_proc.returncode==0), error=(install_proc.returncode!=0)))
                    if install_proc.returncode != 0: raise Exception(f"npm install after clone failed.")
                else: # NPM package install
                    app.after(0, lambda s=f"Setting up '{target_dir.name}' for NPM package '{source}'...": [app._log(s), status_label.config(text=s)])
                    temp_pkg_json = target_dir / "package.json"
                    with open(temp_pkg_json, "w", encoding='utf-8') as f:
                        json.dump({"name": target_dir.name, "version": "0.1.0", "description": f"Project for {source}", "private": True}, f, indent=2)
                    
                    app.after(0, lambda s=f"Installing '{source}' into '{target_dir.name}'...": [app._log(s), status_label.config(text=s)])
                    cmd_list_npm_pkg_install = [constants.NPM_CMD, "install", source, "--save"] 
                    proc_npm_pkg = subprocess.Popen(cmd_list_npm_pkg_install, cwd=target_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', creationflags=process_flags)
                    stdout_npm, stderr_npm = proc_npm_pkg.communicate()
                    if stdout_npm: app.after(0, lambda log=f"[{target_dir.name} NPM STDOUT] {stdout_npm.strip()}": app._log(log))
                    if stderr_npm: app.after(0, lambda log=f"[{target_dir.name} NPM STDERR] {stderr_npm.strip()}": app._log(log, warning=(proc_npm_pkg.returncode==0), error=(proc_npm_pkg.returncode!=0)))
                    if proc_npm_pkg.returncode != 0: raise Exception(f"npm install {source} failed.")

                success_msg = f"Successfully fetched and set up '{target_dir.name}'."
                app.after(0, lambda: [
                    status_label.config(text=success_msg), app._log(success_msg), app.scan_projects_folder(),
                    messagebox.showinfo("Success", success_msg, parent=dialog), dialog.destroy()
                ])

            except Exception as e:
                final_err_msg = f"Error fetching app: {e}" # Default error message
                if isinstance(e, FileNotFoundError):
                    failed_cmd_name = "Unknown command"
                    # Attempt to identify which command failed using e.filename (Python 3.10+)
                    # or by checking which cmd_list was last defined.
                    # Note: e.filename might not always be just the executable name.
                    if hasattr(e, 'filename') and e.filename:
                        failed_cmd_name = e.filename
                    elif cmd_list_git and constants.GIT_CMD in str(e): # Check if error string contains git command
                        failed_cmd_name = constants.GIT_CMD
                    elif (cmd_list_npm_install_after_clone or cmd_list_npm_pkg_install) and constants.NPM_CMD in str(e):
                        failed_cmd_name = constants.NPM_CMD
                    
                    command_type = "Unknown"
                    if constants.GIT_CMD.lower() in failed_cmd_name.lower():
                        command_type = "Git"
                    elif constants.NPM_CMD.lower() in failed_cmd_name.lower():
                        command_type = "Node/NPM"

                    final_err_msg = (
                        f"Command '{failed_cmd_name}' not found. "
                        f"Please ensure {command_type} is installed and its 'bin' or 'cmd' "
                        f"directory is in your system's PATH environment variable. "
                        f"Original error: {e}"
                    )
                
                app.after(0, lambda msg=final_err_msg: [ # Capture final_err_msg in lambda
                    app._log(msg, error=True), 
                    status_label.config(text="Fetch failed. See main log for details."), # Keep status label concise
                    messagebox.showerror("Fetch Error", msg, parent=dialog)
                ])
                # Cleanup partially created directory if it's mostly empty
                if target_dir.exists():
                    try:
                        is_empty_or_only_pkg_json = not any(f for f in target_dir.iterdir() if f.name != "package.json") or \
                                                    (len(list(target_dir.iterdir())) == 1 and (target_dir / "package.json").exists())
                        if is_empty_or_only_pkg_json :
                            shutil.rmtree(target_dir)
                            app._log(f"Cleaned up partially created/failed directory: {target_dir}")
                    except Exception as clean_e:
                        app._log(f"Error during cleanup of {target_dir}: {clean_e}", warning=True)
            finally:
                app.after(0, lambda: [progress_bar.stop(), progress_bar.pack_forget(), 
                                      fetch_button.config(state=tk.NORMAL), cancel_button.config(state=tk.NORMAL)])
        
        threading.Thread(target=fetch_task, daemon=True).start()

    button_frame = ttk.Frame(dialog)
    button_frame.pack(pady=10, padx=10, fill=tk.X)

    fetch_button = ttk.Button(button_frame, text="Fetch and Setup Project", command=do_fetch)
    fetch_button.pack(side=tk.LEFT, expand=True, padx=(0,5))
    
    cancel_button = ttk.Button(button_frame, text="Cancel", command=dialog.destroy)
    cancel_button.pack(side=tk.LEFT, expand=True, padx=(5,0))