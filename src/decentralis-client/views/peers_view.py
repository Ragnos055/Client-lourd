import tkinter as tk
from tkinter import ttk


class PeersView(ttk.Frame):
    def __init__(self, parent, app_gui, **kwargs):
        super().__init__(parent, **kwargs)
        self.app_gui = app_gui
        ttk.Label(self, text="Pairs connus:").pack(anchor='w')
        self.listbox = tk.Listbox(self, height=12)
        self.listbox.pack(fill='both', expand=True)

    def update_peers(self, peers):
        self.listbox.delete(0, tk.END)
        for p in peers:
            if isinstance(p, dict):
                ip = p.get('ip')
                port = p.get('port')
                self.listbox.insert(tk.END, f"{ip}:{port}")
            else:
                self.listbox.insert(tk.END, str(p))
