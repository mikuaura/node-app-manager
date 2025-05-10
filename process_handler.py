# process_handler.py
import subprocess
import os
import re
import threading
import time
from pathlib import Path
import psutil
import shutil

import constants

def run_command_in_thread(app, cmd_list, cwd, app_path, action_name,
                          on_success_status, on_fail_status,
                          is_long_running=False, post_success_action=None):

    resolved_app_path = str(Path(app_path).resolve())

    def task():
        if resolved_app_path not in app.apps_data:
            app._log(f"App at path '{resolved_app_path}' removed before '{action_name}' task started.")
            app.update_status_bar(f"Action for removed app aborted.")
            app.after(0, app._update_action_buttons_state)
            return

        app_name = app.apps_data[resolved_app_path].get("name", "Unknown App")

        log_message_start = f"{action_name} '{app_name}'..."
        app._log(log_message_start)
        app.update_status_bar(log_message_start)

        interim_status_key_for_treeview = action_name
        if not interim_status_key_for_treeview.endswith("..."):
            interim_status_key_for_treeview += "..."

        app.after(0, lambda p=resolved_app_path, s=interim_status_key_for_treeview: app._update_app_status(p, status=s))

        process = None
        try:
            process_flags = 0
            if os.name == 'nt': process_flags = subprocess.CREATE_NO_WINDOW

            process = subprocess.Popen(
                cmd_list, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1, universal_newlines=True, encoding='utf-8', errors='replace',
                creationflags=process_flags
            )

            if resolved_app_path not in app.apps_data:
                if process and process.poll() is None: process.terminate()
                app._log(f"App '{app_name}' removed during Popen setup for '{action_name}'.")
                app.after(0, app._update_action_buttons_state)
                return

            current_pid = process.pid
            current_process_obj = process if is_long_running else None
            app.after(0, lambda p=resolved_app_path, pid=current_pid, proc_obj=current_process_obj: \
                      app._update_app_status(p, pid=pid, process_obj=proc_obj if proc_obj is not None else Ellipsis))


            if is_long_running:
                if process.poll() is None:
                    app.after(0, lambda p=resolved_app_path, s=on_success_status, pid_val=process.pid: \
                              app._update_app_status(p, status=s, pid=pid_val))
                else:
                    stderr_on_fail = ""
                    if process.stderr:
                        try: stderr_on_fail = process.stderr.read()
                        except: pass
                    app._log(f"Process for '{app_name}' ({action_name}) exited immediately (code {process.returncode}). {stderr_on_fail.strip()}", error=True)
                    app.after(0, lambda p=resolved_app_path, s=on_fail_status, pid_val=process.pid: \
                              app._update_app_status(p, status=s, pid=pid_val, process_obj=None))
                    app.update_status_bar(f"'{app_name}' ({action_name}) failed to start/run properly.")
                    app.after(0, app._update_action_buttons_state)
                    return

            if is_long_running and process.poll() is None:
                log_action_prefix = action_name.split(':')[0] if ':' in action_name else action_name
                if log_action_prefix.endswith("..."): log_action_prefix = log_action_prefix[:-3]

                app._log(f"Monitoring output for '{app_name}' ({log_action_prefix}, PID: {process.pid})...")
                for line in iter(process.stdout.readline, ''):
                    if resolved_app_path not in app.apps_data or \
                       app.apps_data[resolved_app_path].get("status") == "Stopping...":
                        app._log(f"Process for '{app_name}' ({log_action_prefix}) stop signal/removed. Halting output.")
                        if process.poll() is None: process.terminate()
                        break

                    app._log(f"[{app_name} - {log_action_prefix}] {line.strip()}")

                    if action_name == "Starting":
                        match = re.search(r"(?:port|listening on|on port|url:|local:.*?)\s*[:\- ]\s*(\d{4,5})", line, re.IGNORECASE)
                        if match:
                            port = match.group(1)
                            if resolved_app_path in app.apps_data:
                                app.after(0, lambda p=resolved_app_path, pt=port: app._update_app_status(p, port=pt))
                            app._log(f"Detected port {port} for '{app_name}'")

                process.stdout.close()
                stderr_output = process.stderr.read()
                process.stderr.close()
                return_code = process.wait()

                if stderr_output: app._log(f"[{app_name} - {log_action_prefix} STDERR] {stderr_output.strip()}", warning=True)

                if resolved_app_path in app.apps_data:
                    current_app_status = app.apps_data[resolved_app_path]["status"]
                    if current_app_status == "Stopping...":
                        app._log(f"'{app_name}' ({log_action_prefix}) was stopped by manager.")
                    elif current_app_status == on_success_status:
                         if return_code == 0:
                             app._log(f"'{app_name}' ({log_action_prefix}) finished/exited gracefully (code 0).")
                             app.after(0, lambda p=resolved_app_path: app._update_app_status(p, status="Stopped", port="-", pid=None, process_obj=None))
                         else:
                             app._log(f"'{app_name}' ({log_action_prefix}) exited with error (code {return_code}).", error=True)
                             app.after(0, lambda p=resolved_app_path, s=on_fail_status: app._update_app_status(p, status=s, port="-", pid=None, process_obj=None))

            elif not is_long_running:
                stdout, stderr = process.communicate()
                if stdout: app._log(f"[{app_name} STDOUT] {stdout.strip()}")
                if stderr: app._log(f"[{app_name} STDERR] {stderr.strip()}", warning=(process.returncode == 0), error=(process.returncode != 0))

                final_status_update = {} # This will store kwargs for _update_app_status
                if process.returncode == 0:
                    app._log(f"'{app_name}' {action_name} completed successfully.")
                    final_status_update["status"] = on_success_status
                    if post_success_action:
                        # post_success_action might modify final_status_update (e.g., add is_installed=True)
                        post_success_action(app, resolved_app_path, final_status_update)
                else:
                    app._log(f"'{app_name}' {action_name} failed (code {process.returncode}).", error=True)
                    final_status_update["status"] = on_fail_status

                if resolved_app_path in app.apps_data:
                    # Use lambda to correctly pass keyword arguments from final_status_update
                    app.after(0, lambda p=resolved_app_path, kw=final_status_update.copy(): app._update_app_status(p, **kw))

        except FileNotFoundError:
            app._log(f"Error: Command '{cmd_list[0]}' not found. Is it in PATH?", error=True)
            if resolved_app_path in app.apps_data:
                app.after(0, lambda p=resolved_app_path: app._update_app_status(p, status="Error (Command)", process_obj=None))
        except Exception as e:
            app._log(f"Exception during '{action_name}' for '{app_name}': {e}", error=True)
            if resolved_app_path in app.apps_data:
                app.after(0, lambda p=resolved_app_path: app._update_app_status(p, status="Error (Exception)", process_obj=None))
        finally:
            if resolved_app_path in app.apps_data and app.apps_data[resolved_app_path].get("process") and \
               hasattr(app.apps_data[resolved_app_path]["process"], 'poll') and \
               app.apps_data[resolved_app_path]["process"].poll() is not None:
                app.after(0, lambda p=resolved_app_path: app._update_app_status(p, process_obj=None))

                current_status_final = app.apps_data[resolved_app_path].get("status")
                if (current_status_final == "Stopped" or "Error" in current_status_final) and \
                    app.apps_data[resolved_app_path]["pid"] == (process.pid if process else None):
                        app.after(0, lambda p=resolved_app_path: app._update_app_status(p, pid=None))

            app.update_status_bar(f"'{app_name}' {action_name} finished.")
            app.after(0, app._update_action_buttons_state)

    threading.Thread(target=task, daemon=True).start()


def start_app_logic(app, app_path_to_start):
    resolved_app_path = str(Path(app_path_to_start).resolve())
    if not resolved_app_path or resolved_app_path not in app.apps_data: return

    app_data = app.apps_data[resolved_app_path]
    app_name = app_data["name"]

    if app_data.get("status") == "Running" or app_data.get("status", "").startswith("Running Script:"):
        current_pid = app_data.get("pid")
        if current_pid and str(current_pid).isdigit() and psutil.pid_exists(int(current_pid)):
            try:
                proc = psutil.Process(int(current_pid))
                proc_name_info = proc.name() if hasattr(proc, 'name') else ""
                proc_cwd_info = proc.cwd() if hasattr(proc, 'cwd') else ""

                if constants.NODE_CMD.split('.')[0] in proc_name_info.lower() and \
                   Path(proc_cwd_info).resolve() == Path(resolved_app_path).resolve():
                    app.update_status_bar(f"'{app_name}' already running or a script is running.")
                    app._log(f"'{app_name}' is already reported as running and process is live (PID: {current_pid}).", warning=True)
                    return
                else:
                    app._log(f"Stale PID {current_pid} or mismatched process for '{app_name}'. Will attempt to start fresh.")
                    app._update_app_status(resolved_app_path, pid=None, status="Installed" if app_data.get("is_installed") else "Not Installed", process_obj=None)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
                app._log(f"Error checking PID {current_pid} for '{app_name}': {e}. Starting fresh.", warning=True)
                app._update_app_status(resolved_app_path, pid=None, status="Installed" if app_data.get("is_installed") else "Not Installed", process_obj=None)
        else:
            app._log(f"No valid running process found for '{app_name}' despite 'Running' status. Proceeding with start.", warning=True)
            app._update_app_status(resolved_app_path, pid=None, status="Installed" if app_data.get("is_installed") else "Not Installed", process_obj=None)


    if not app_data.get("package_data"):
        app._log(f"Cannot start '{app_name}': package.json missing or invalid.", error=True)
        app._update_app_status(resolved_app_path, status="Error (package.json)")
        return

    start_script = app_data["package_data"].get("scripts", {}).get("start")
    main_file = app_data["package_data"].get("main")

    cmd = []
    if start_script: cmd = [constants.NPM_CMD, "start"]
    elif main_file: cmd = [constants.NODE_CMD, main_file]
    else:
        found_main = next((cf for cf in constants.COMMON_ENTRY_FILES if (Path(resolved_app_path) / cf).exists()), None)
        if found_main: cmd = [constants.NODE_CMD, found_main]
        else:
            app._log(f"Cannot start '{app_name}': No 'start' script, 'main' field, or common entry point found.", error=True)
            app._update_app_status(resolved_app_path, status="Error (No Start)")
            return

    run_command_in_thread(
        app, cmd, cwd=resolved_app_path, app_path=resolved_app_path,
        action_name="Starting", on_success_status="Running",
        on_fail_status="Error (Start Fail)", is_long_running=True
    )

def stop_app_logic(app, app_path_to_stop, callback=None):
    resolved_app_path = str(Path(app_path_to_stop).resolve())

    if not resolved_app_path or resolved_app_path not in app.apps_data:
        if callback: app.after(0, callback)
        return

    app_data = app.apps_data[resolved_app_path]
    app_name = app_data["name"]
    pid_from_data = app_data.get("pid")
    process_obj_from_data = app_data.get("process")

    current_status = app_data.get("status", "Unknown")

    if current_status == "Stopping...":
         app._log(f"'{app_name}' is already in the process of stopping.")
         if callback: app.after(0, callback)
         return

    stoppable_actual_running_states = ["Running"]
    if current_status.startswith("Running Script:"):
        stoppable_actual_running_states.append(current_status)

    is_stoppable_interim = current_status == "Starting..." or \
                           (current_status.startswith("Running Script:") and current_status.endswith("..."))

    if not (current_status in stoppable_actual_running_states or is_stoppable_interim) :
        app._log(f"'{app_name}' is not in a stoppable state (Status: {current_status}).", warning=True)
        if pid_from_data and str(pid_from_data).isdigit() and psutil.pid_exists(int(pid_from_data)) and process_obj_from_data is None:
            app._log(f"Attempting to stop unmanaged process PID {pid_from_data} for '{app_name}'.")
        else:
            app.after(0, lambda p=resolved_app_path: app._update_app_status(p, status="Stopped", port="-", pid="-", process_obj=None))
            if callback: app.after(0, callback)
            return

    action_being_stopped = "app"
    if current_status.startswith("Running Script:"):
        script_name_part = current_status.split(': ', 1)[1].replace('...', '')
        action_being_stopped = f"script '{script_name_part}'"
    elif current_status == "Starting...":
        action_being_stopped = "starting app"

    app._log(f"Attempting to stop '{app_name}' ({action_being_stopped}, PID: {pid_from_data or 'N/A'}, Managed: {'Yes' if process_obj_from_data else 'No'})...")
    app.update_status_bar(f"Stopping {app_name} ({action_being_stopped})...")
    app.after(0, lambda p=resolved_app_path: app._update_app_status(p, status="Stopping..."))

    def stop_task():
        final_status = "Error (Stop)"
        stopped_successfully = False
        pid_to_use = pid_from_data
        process_to_use = process_obj_from_data

        try:
            if process_to_use and hasattr(process_to_use, 'poll') and process_to_use.poll() is None:
                app._log(f"Stopping '{app_name}' ({action_being_stopped}) using managed Popen object (PID {process_to_use.pid}).")
                pid_to_use = process_to_use.pid
                process_to_use.terminate()
                try:
                    process_to_use.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    app._log(f"'{app_name}' (Popen for {action_being_stopped}) did not terminate, killing...", warning=True)
                    process_to_use.kill()
                    process_to_use.wait(timeout=3)
                stopped_successfully = (process_to_use.poll() is not None)
                if stopped_successfully:
                     app._log(f"'{app_name}' (Popen for {action_being_stopped}) stopped. Return code: {process_to_use.returncode}")
                     final_status = "Stopped"
                else:
                     app._log(f"'{app_name}' (Popen for {action_being_stopped}) failed to stop.", error=True)

            if not stopped_successfully and pid_to_use and str(pid_to_use).isdigit():
                try:
                    parent_process = psutil.Process(int(pid_to_use))
                    if not parent_process.is_running():
                        app._log(f"Process for '{app_name}' ({action_being_stopped}, PID: {pid_to_use}) already exited before psutil stop.")
                        stopped_successfully = True
                        final_status = "Stopped"
                    else:
                        app._log(f"Attempting to stop '{app_name}' ({action_being_stopped}) using psutil for PID {pid_to_use}.")
                        children = parent_process.children(recursive=True)
                        for child in children:
                            try: child.terminate()
                            except psutil.Error: pass
                        psutil.wait_procs(children, timeout=2)
                        for child in children:
                            try:
                                if child.is_running(): child.kill()
                            except psutil.Error: pass

                        parent_process.terminate()
                        parent_process.wait(timeout=3)
                        if parent_process.is_running():
                            parent_process.kill()
                            parent_process.wait(timeout=2)

                        stopped_successfully = not parent_process.is_running()
                        final_status = "Stopped" if stopped_successfully else "Error (Stop)"
                        app._log(f"'{app_name}' ({action_being_stopped}, psutil PID: {pid_to_use}) stop attempt result: {final_status}")

                except psutil.NoSuchProcess:
                    app._log(f"Process for '{app_name}' ({action_being_stopped}, PID: {pid_to_use}) already exited (psutil.NoSuchProcess).")
                    stopped_successfully = True
                    final_status = "Stopped"
                except ValueError:
                    app._log(f"Invalid PID '{pid_to_use}' for '{app_name}' ({action_being_stopped}).", error=True)
                    final_status = "Error (Stop)"

            elif not stopped_successfully:
                app._log(f"No active managed process or valid PID for '{app_name}' ({action_being_stopped}) could be robustly stopped. Assuming stopped or unmanageable.", warning=True)
                if not (pid_to_use and str(pid_to_use).isdigit() and psutil.pid_exists(int(pid_to_use))):
                    stopped_successfully = True
                    final_status = "Stopped"

        except Exception as e:
            app._log(f"Error stopping '{app_name}' ({action_being_stopped}): {e}", error=True)
            final_status = "Error (Stop)"
        finally:
            if resolved_app_path in app.apps_data:
                app.after(0, lambda p=resolved_app_path, s=final_status: \
                          app._update_app_status(p, status=s, port="-", pid="-", process_obj=None))
                app.update_status_bar(f"'{app_name}' ({action_being_stopped}) {final_status}.")
            if callback:
                app.after(0, callback)
            app.after(0, app._update_action_buttons_state)

    threading.Thread(target=stop_task, daemon=True).start()

def install_dependencies_logic(app, app_path):
    resolved_app_path = str(Path(app_path).resolve())
    if not resolved_app_path or resolved_app_path not in app.apps_data: return

    def post_install_action(app_ref, path, status_update_dict):
        status_update_dict["is_installed"] = True

    run_command_in_thread(
        app, [constants.NPM_CMD, "install"], cwd=resolved_app_path, app_path=resolved_app_path,
        action_name="Installing", on_success_status="Installed",
        on_fail_status="Error (Install)", post_success_action=post_install_action
    )

def clean_dependencies_logic(app, app_path_str):
    resolved_app_path_str = str(Path(app_path_str).resolve())
    app_path_obj = Path(resolved_app_path_str)

    if not app_path_obj.exists():
        app.messagebox.showerror("Error", f"Project folder not found:\n{resolved_app_path_str}", parent=app)
        app.scan_projects_folder()
        return

    app_name = app.apps_data[resolved_app_path_str]["name"]
    current_status = app.apps_data[resolved_app_path_str].get("status", "Unknown")

    if current_status == "Running" or current_status.startswith("Running Script:"):
        app.messagebox.showerror("Error", f"'{app_name}' is currently running. Please stop it first.", parent=app)
        return

    if not app.messagebox.askyesno("Confirm Clean", f"Delete 'node_modules' for '{app_name}'?", parent=app, icon='warning'):
        return

    app.after(0, lambda p=resolved_app_path_str: app._update_app_status(p, status="Cleaning..."))

    def task():
        node_modules_path = app_path_obj / "node_modules"
        final_status_key = "Error (Clean)"
        is_now_installed = app.apps_data[resolved_app_path_str].get("is_installed", False)
        try:
            if node_modules_path.exists() and node_modules_path.is_dir():
                shutil.rmtree(node_modules_path)
                app._log(f"'node_modules' for '{app_name}' deleted successfully.")
                final_status_key = "Not Installed"
                is_now_installed = False
            else:
                app._log(f"'node_modules' for '{app_name}' not found or is not a directory.", warning=True)
                final_status_key = "Not Installed"
                is_now_installed = False

            app.after(0, lambda p=resolved_app_path_str, s=final_status_key, inst=is_now_installed: \
                      app._update_app_status(p, status=s, is_installed=inst))
        except Exception as e:
            app._log(f"Error cleaning dependencies for '{app_name}': {e}", error=True)
            app.after(0, lambda p=resolved_app_path_str, inst=is_now_installed: \
                      app._update_app_status(p, status="Error (Clean)", is_installed=inst))
        finally:
            app.after(0, lambda: app.update_status_bar(f"Dependency cleaning for '{app_name}' finished."))
            app.after(0, app._update_action_buttons_state)

    threading.Thread(target=task, daemon=True).start()

def delete_project_logic(app, app_path_str):
    resolved_app_path_str = str(Path(app_path_str).resolve())
    app_path_obj = Path(resolved_app_path_str)

    if not app_path_obj.exists():
        app.messagebox.showerror("Error", f"Project folder already deleted or not found:\n{resolved_app_path_str}", parent=app)
        app.scan_projects_folder()
        return

    app_data = app.apps_data[resolved_app_path_str]
    app_name = app_data["name"]

    if not app.messagebox.askyesno("Confirm Delete",
                               f"Permanently delete project '{app_name}' and all its files from:\n{resolved_app_path_str}?",
                               icon='warning', parent=app):
        return

    app.update_status_bar(f"Preparing to delete {app_name}...")

    def actually_delete():
        app._log(f"Deleting project '{app_name}' at {resolved_app_path_str}...")
        app.after(0, lambda p=resolved_app_path_str: app._update_app_status(p, status="Deleting..."))
        try:
            shutil.rmtree(resolved_app_path_str)
            app._log(f"Project '{app_name}' deleted successfully.")
            app.after(0, lambda p=resolved_app_path_str: app._remove_app_from_gui(p))
            app.after(0, lambda: app.update_status_bar(f"Project '{app_name}' deleted."))
        except Exception as e:
            app._log(f"Error deleting project '{app_name}': {e}", error=True)
            if Path(resolved_app_path_str).exists():
                app.after(0, lambda p=resolved_app_path_str: app._update_app_status(p, status="Error (Delete)"))
            else:
                app.after(0, lambda p=resolved_app_path_str: app._remove_app_from_gui(p))
            app.after(0, lambda: app.update_status_bar(f"Error deleting '{app_name}'."))
        finally:
            app.after(0, app._update_action_buttons_state)

    current_status = app_data.get("status", "Unknown")
    if current_status == "Running" or current_status.startswith("Running Script:") or current_status == "Starting...":
        app._log(f"Project Delete: '{app_name}' is active. Stopping it first...")
        def after_stop_for_delete():
            if resolved_app_path_str in app.apps_data and \
               app.apps_data[resolved_app_path_str].get("status") == "Stopped":
                threading.Thread(target=actually_delete, daemon=True).start()
            else:
                current_state_after_stop_attempt = "Unknown/Removed"
                if resolved_app_path_str in app.apps_data:
                    current_state_after_stop_attempt = app.apps_data[resolved_app_path_str].get("status", "Error (Stop)")

                app._log(f"Project Delete: Failed to stop '{app_name}' (current state: {current_state_after_stop_attempt}). Aborting delete.", error=True)
                app.update_status_bar(f"Could not stop '{app_name}' for deletion.")
                if resolved_app_path_str in app.apps_data:
                    app.after(0, lambda p=resolved_app_path_str, s=current_state_after_stop_attempt: app._update_app_status(p, status=s))

        stop_app_logic(app, resolved_app_path_str, callback=after_stop_for_delete)
    else:
        threading.Thread(target=actually_delete, daemon=True).start()


def run_npm_script_logic(app, app_path, script_name):
    resolved_app_path = str(Path(app_path).resolve())
    if not resolved_app_path or resolved_app_path not in app.apps_data: return

    cmd = [constants.NPM_CMD, "run", script_name]

    action_name_for_run = f"Running script: {script_name}"

    is_potentially_long_running = script_name in ["start", "dev", "serve", "watch"] or \
                                  "watch" in script_name or "dev" in script_name

    on_success_status_for_script = action_name_for_run if is_potentially_long_running else "Installed"

    run_command_in_thread(
        app, cmd, cwd=resolved_app_path, app_path=resolved_app_path,
        action_name=action_name_for_run,
        on_success_status=on_success_status_for_script,
        on_fail_status="Error (Script)",
        is_long_running=is_potentially_long_running
    )

def npm_audit_logic(app, app_path):
    resolved_app_path = str(Path(app_path).resolve())
    if not resolved_app_path or resolved_app_path not in app.apps_data: return

    action_name = "Auditing"
    cmd = [constants.NPM_CMD, "audit"]

    run_command_in_thread(
        app, cmd, cwd=resolved_app_path, app_path=resolved_app_path,
        action_name=action_name,
        on_success_status="Installed",
        on_fail_status="Error (Audit)",
        is_long_running=False
    )

def npm_update_dependencies_logic(app, app_path):
    resolved_app_path = str(Path(app_path).resolve())
    if not resolved_app_path or resolved_app_path not in app.apps_data: return

    action_name = "Updating Deps"
    cmd = [constants.NPM_CMD, "update"]

    run_command_in_thread(
        app, cmd, cwd=resolved_app_path, app_path=resolved_app_path,
        action_name=action_name,
        on_success_status="Installed",
        on_fail_status="Error (Update)",
        is_long_running=False
    )