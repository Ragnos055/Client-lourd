import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import secrets
import os

from connection.connection import connection
from views.peers_view import PeersView
from views.files_view import FilesView
from views.encryption_view import EncryptionView


class DecentralisGUI:
    def __init__(self, root):
        self.root = root
        root.title("Decentralis - Client")

        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        # Header (tracker / peer inputs)
        header = ttk.Frame(root, padding=8)
        header.grid(row=0, column=0, sticky='ew')

        ttk.Label(header, text="Tracker IP:").grid(row=0, column=0, sticky='e')
        self.srv_ip = tk.StringVar(value="127.0.0.1")
        ttk.Entry(header, textvariable=self.srv_ip, width=18).grid(row=0, column=1, sticky='w')

        ttk.Label(header, text="Tracker Port:").grid(row=0, column=2, sticky='e')
        self.srv_port = tk.IntVar(value=5000)
        ttk.Entry(header, textvariable=self.srv_port, width=8).grid(row=0, column=3, sticky='w')

        ttk.Label(header, text="Peer IP:").grid(row=1, column=0, sticky='e')
        self.peer_ip = tk.StringVar(value="127.0.0.1")
        ttk.Entry(header, textvariable=self.peer_ip, width=18).grid(row=1, column=1, sticky='w')

        ttk.Label(header, text="Peer Port:").grid(row=1, column=2, sticky='e')
        self.peer_port = tk.IntVar(value=6000)
        ttk.Entry(header, textvariable=self.peer_port, width=8).grid(row=1, column=3, sticky='w')

        ttk.Label(header, text="Keepalive (s):").grid(row=2, column=0, sticky='e')
        self.keepalive = tk.IntVar(value=15)
        ttk.Entry(header, textvariable=self.keepalive, width=8).grid(row=2, column=1, sticky='w')

        self.connect_btn = ttk.Button(header, text="Connexion", command=self._on_connect_click)
        self.connect_btn.grid(row=2, column=2, columnspan=2)

        # Menu bar (Views)
        menubar = tk.Menu(root)
        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(label="Pairs", command=lambda: self.show_view('peers'))
        view_menu.add_command(label="Gestionnaire de fichiers", command=lambda: self.show_view('files'))
        view_menu.add_command(label="Chiffrement", command=lambda: self.show_view('encryption'))
        menubar.add_cascade(label="Vue", menu=view_menu)
        root.config(menu=menubar)

        # Main container where views are stacked
        container = ttk.Frame(root, padding=8)
        container.grid(row=1, column=0, sticky='nsew')
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        # Frames for each view (now provided by separate modules)
        self.frames = {}
        # storage directory for files (per-user storage)
        self.storage_dir = os.path.join(os.path.expanduser('~'), '.decentralis', 'storage')
        os.makedirs(self.storage_dir, exist_ok=True)
        self.frames['peers'] = PeersView(container, self)
        self.frames['peers'].grid(row=0, column=0, sticky='nsew')

        self.frames['files'] = FilesView(container, self)
        self.frames['files'].grid(row=0, column=0, sticky='nsew')

        self.frames['encryption'] = EncryptionView(container, self)
        self.frames['encryption'].grid(row=0, column=0, sticky='nsew')

        self.show_view('peers')

        # connection state
        self.conn = None
        self._updating = False
        self.encryption_settings = {}

    # --- Views creation ---
    # view creation is now delegated to separate view classes in files under views/

    # --- View switching ---
    def show_view(self, name):
        for k, f in self.frames.items():
            if k == name:
                f.lift()
                f.tkraise()
            else:
                f.lower()

    # --- Connection handling (unchanged logic) ---
    def _on_connect_click(self):
        if self.conn:
            self._disconnect()
            return

        try:
            srv_ip = self.srv_ip.get()
            srv_port = int(self.srv_port.get())
            peer_ip = self.peer_ip.get()
            peer_port = int(self.peer_port.get())
            keepalive = int(self.keepalive.get())
        except Exception as e:
            messagebox.showerror("Erreur", f"Valeurs invalides: {e}")
            return

        def create_conn():
            try:
                self.conn = connection(srv_ip, srv_port, peer_ip, peer_port, keepalive)
            except Exception as e:
                self.conn = None
                self.root.after(0, lambda: messagebox.showerror("Erreur de connexion", str(e)))

        t = threading.Thread(target=create_conn, daemon=True)
        t.start()

        self.connect_btn.config(text="Déconnexion")
        self._updating = True
        self.root.after(1000, self._update_peers)

    def _disconnect(self):
        try:
            if self.conn:
                try:
                    self.conn.close()
                except Exception:
                    pass
                self.conn = None
        finally:
            self._updating = False
            # clear peers view listbox if present
            try:
                if 'peers' in self.frames and hasattr(self.frames['peers'], 'listbox'):
                    self.frames['peers'].listbox.delete(0, tk.END)
            except Exception:
                pass
            self.connect_btn.config(text="Connexion")

    def _update_peers(self):
        if not self._updating:
            return
        try:
            if self.conn:
                resp = self.conn.get_peers()
                peers = resp.get('peers', []) if isinstance(resp, dict) else []
            else:
                peers = []
            # Delegate update to peers view
            try:
                if 'peers' in self.frames and hasattr(self.frames['peers'], 'update_peers'):
                    self.frames['peers'].update_peers(peers)
            except Exception as e:
                print('Erreur mise à jour view peers:', e)
        except Exception as e:
            print("Erreur récupération pairs:", e)
        finally:
            self.root.after(2000, self._update_peers)
    # File manager and encryption actions are implemented inside their respective view classes


def run_gui():
    root = tk.Tk()
    DecentralisGUI(root)
    root.mainloop()


if __name__ == '__main__':
    run_gui()
