import tkinter as tk
from tkinter import ttk, messagebox


class PeersView(ttk.Frame):
    def __init__(self, parent, app_gui, **kwargs):
        super().__init__(parent, **kwargs)
        self.app_gui = app_gui
        ttk.Label(self, text="Pairs connus:").pack(anchor='w')
        self.listbox = tk.Listbox(self, height=12)
        self.listbox.pack(fill='both', expand=True)
        ttk.Button(self, text="Envoyer un fichier (TCP)", command=self._send_to_selected).pack(pady=(6,0), anchor='w')
        self._peers = []

    def update_peers(self, peers):
        self.listbox.delete(0, tk.END)
        self._peers = peers or []
        for p in self._peers:
            if isinstance(p, dict):
                ip = p.get('ip')
                port = p.get('port')
                self.listbox.insert(tk.END, f"{ip}:{port}")
            else:
                self.listbox.insert(tk.END, str(p))

    def _send_to_selected(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showinfo("Info", "Sélectionnez un pair dans la liste.")
            return
        idx = sel[0]
        peer = None
        try:
            peer = self._peers[idx]
        except Exception:
            peer = None
        try:
            self.app_gui.send_file_to_peer(peer)
        except Exception as e:
            messagebox.showerror("Erreur", f"Echec envoi: {e}")
