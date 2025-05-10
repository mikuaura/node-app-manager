# tooltip.py
import tkinter as tk
from tkinter import ttk

class ToolTip:
    def __init__(self, widget, text, delay=500): # Added delay
        self.widget = widget
        self.text = text
        self.tooltip_window = None
        self.delay = delay
        self._after_id = None
        widget.bind("<Enter>", self.schedule_tooltip)
        widget.bind("<Leave>", self.hide_tooltip)
        widget.bind("<ButtonPress>", self.hide_tooltip) # Hide on click too

    def schedule_tooltip(self, event):
        self.hide_tooltip() # Clear any existing tooltip or schedule
        if self.text:
            self._after_id = self.widget.after(self.delay, lambda e=event: self.show_tooltip(e))

    def show_tooltip(self, event=None): # event can be None if called by after
        if self.tooltip_window or not self.text:
            return

        # If event is None (called by self.widget.after), use widget's current pointer loc
        x = event.x_root + 10 if event else self.widget.winfo_pointerx() + 10
        y = event.y_root + 10 if event else self.widget.winfo_pointery() + 10
        
        self.tooltip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        # Ensure window is created and dimensions known before positioning
        tw.update_idletasks() 
        
        # Basic check to keep tooltip on screen, might need refinement
        screen_width = self.widget.winfo_screenwidth()
        screen_height = self.widget.winfo_screenheight()
        
        if x + tw.winfo_width() > screen_width:
            x = screen_width - tw.winfo_width() - 5
        if y + tw.winfo_height() > screen_height:
            y = screen_height - tw.winfo_height() - 5
        if x < 0: x = 5
        if y < 0: y = 5

        tw.wm_geometry(f"+{x}+{y}")

        label = ttk.Label(tw, text=self.text, justify=tk.LEFT,
                         relief=tk.SOLID, borderwidth=1)
        
        # Try to get theme-aware background for tooltip
        try:
            style = ttk.Style()
            # Use a background color that's common for tooltips or light
            # Tooltip specific style elements are not standard in ttk
            bg_color = style.lookup('TLabel', 'background', ('tooltip',)) \
                       or style.lookup('TLabel', 'background') \
                       or "#ffffe0" # Fallback color
            fg_color = style.lookup('TLabel', 'foreground', ('tooltip',)) \
                       or style.lookup('TLabel', 'foreground') \
                       or "#000000"
            label.configure(background=bg_color, foreground=fg_color)
        except tk.TclError:
            label.configure(background="#ffffe0", foreground="#000000") # Fallback if style lookups fail

        label.pack(ipadx=2, ipady=2)


    def hide_tooltip(self, event=None):
        if self._after_id:
            self.widget.after_cancel(self._after_id)
            self._after_id = None
        if self.tooltip_window:
            self.tooltip_window.destroy()
        self.tooltip_window = None