import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import threading
import os
import secrets
import socket
from connection.connection import connection
import p2p
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
        self.config_dir = os.path.join(os.path.expanduser('~'), '.decentralis')
        os.makedirs(self.config_dir, exist_ok=True)
        self.storage_dir = os.path.join(self.config_dir, 'storage')
        os.makedirs(self.storage_dir, exist_ok=True)
        # retention (key) file path
        self.retention_path = os.path.join(self.config_dir, 'key.json')
        # encryption settings object (cached for the session)
        self.encryption_settings = {}
        self._cached_passphrase = None

        self.frames['peers'] = PeersView(container, self)
        self.frames['peers'].grid(row=0, column=0, sticky='nsew')

        self.frames['encryption'] = EncryptionView(container, self)
        self.frames['encryption'].grid(row=0, column=0, sticky='nsew')

        # If a retention file already exists, prompt for passphrase now so it's cached
        # before views are used. If no retention file exists, we'll create frames first
        # and then force creation/import via _ensure_retention_file below.
        try:
            self._ensure_retention_file()
        except Exception as e:
            messagebox.showerror('Erreur', f'Erreur initialisation clé: {e}')

        self.frames['files'] = FilesView(container, self)
        self.frames['files'].grid(row=0, column=0, sticky='nsew')


        self.show_view('files')

        # connection state
        self.conn = None
        self._updating = False
        self.p2p_server = None

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
                # démarrer le serveur TCP pour réception de fichiers chiffrés
                self._start_p2p_server(peer_ip, peer_port)
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
            try:
                self._stop_p2p_server()
            except Exception:
                pass
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
    
    # --- P2P server management ---
    def _start_p2p_server(self, host: str, port: int):
        try:
            self._stop_p2p_server()
        except Exception:
            pass
        try:
            # écoute sur l'adresse configurée (ou 0.0.0.0 si host vide)
            listen_host = host or "0.0.0.0"
            self.p2p_server = p2p.P2PServer(listen_host, port, self.storage_dir, on_file_received=self._on_file_received)
            self.p2p_server.start()
        except OSError as e:
            messagebox.showerror("Erreur P2P", f"Impossible de démarrer l'écoute TCP: {e}")
            self.p2p_server = None

    def _stop_p2p_server(self):
        if self.p2p_server:
            try:
                self.p2p_server.stop()
            except Exception:
                pass
            self.p2p_server = None

    def _on_file_received(self, path: str, sender_ip: str):
        # notification simple en UI
        self.root.after(0, lambda: messagebox.showinfo("Fichier reçu", f"Chiffre reçu depuis {sender_ip}\nStocké: {path}"))

    # --- Sending files to peers ---
    def send_file_to_peer(self, peer):
        """
        peer: dict avec ip/port.
        """
        if not peer:
            messagebox.showinfo("Info", "Sélectionnez un pair.")
            return
        settings = getattr(self, "encryption_settings", {}) or {}
        algo = settings.get("algorithm")
        key = settings.get("key")
        if not algo or not key:
            messagebox.showerror("Erreur", "Paramètres de chiffrement manquants. Configurez une clé.")
            return
        path = filedialog.askopenfilename(title="Choisir le fichier à envoyer (sera chiffré et envoyé)")
        if not path:
            return
        try:
            p2p.send_encrypted_file(peer.get("ip"), int(peer.get("port")), path, algo=algo, key_hex=key)
            messagebox.showinfo("Envoyé", "Fichier chiffré envoyé avec un nom aléatoire.")
        except Exception as e:
            messagebox.showerror("Erreur envoi", f"Echec envoi: {e}")
    
    def _ensure_retention_file(self):
        """Ensure a retention JSON exists; if yes prompt for passphrase; if not force create/import."""
        from keystore import verify_passphrase_and_get_keyhex, load_retention

        if os.path.exists(self.retention_path):
            # ask for passphrase and derive key
            for _ in range(3):
                p = simpledialog.askstring('Passphrase', 'Entrez la passphrase pour la clé de rétention:', show='*')
                if p is None:
                    # user cancelled
                    break
                try:
                    keyhex = verify_passphrase_and_get_keyhex(self.retention_path, p)
                    data = load_retention(self.retention_path)
                    self.encryption_settings = {'algorithm': data.get('algorithm', 'AES-256'), 'key': keyhex}
                    # cache passphrase for this session
                    self._cached_passphrase = p
                    return True
                except Exception as e:
                    messagebox.showerror('Erreur', f'Passphrase incorrecte: {e}')
            raise RuntimeError('Passphrase non fournie ou incorrecte')
        else:
            # force create or import
            ans = messagebox.askyesno('Clé manquante', 'Aucun fichier de rétention trouvé. Voulez-vous en créer un maintenant ? (Oui = créer, Non = importer)')
            if ans:
                # create using Encryption view helper
                self.show_view('encryption')
                try:
                    self.frames['encryption'].create_retention()
                except Exception as e:
                    raise
            else:
                self.show_view('encryption')
                try:
                    self.frames['encryption'].import_retention()
                except Exception as e:
                    raise
            # after create/import, recall to prompt passphrase
            return self._ensure_retention_file()
    # File manager and encryption actions are implemented inside their respective view classes


def run_gui():
    root = tk.Tk()
    DecentralisGUI(root)
    root.mainloop()


if __name__ == '__main__':
    run_gui()
