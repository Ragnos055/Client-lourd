import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import threading
import secrets
import os
import sys
import asyncio
import uuid

from connection.connection import connection


def get_app_dir():
    """
    Retourne le répertoire de l'application.
    - Si exécuté depuis un exécutable PyInstaller: répertoire de l'exécutable
    - Si exécuté en mode script: répertoire du script principal
    """
    if getattr(sys, 'frozen', False):
        # Exécuté depuis un exécutable PyInstaller
        return os.path.dirname(sys.executable)
    else:
        # Exécuté en mode script
        return os.path.dirname(os.path.abspath(__file__))
from views.peers_view import PeersView
from views.files_view import FilesView
from views.encryption_view import EncryptionView
from views.p2p_view import P2PView

# Import du module chunking
try:
    from chunking import ChunkingManager, ChunkDatabase, ChunkStore, ChunkNetworkServer, PeerRPC
    CHUNKING_AVAILABLE = True
except ImportError as e:
    print(f"Warning: chunking module not available: {e}")
    CHUNKING_AVAILABLE = False


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
        view_menu.add_command(label="Réseau P2P", command=lambda: self.show_view('p2p'))
        view_menu.add_separator()
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
        # storage directory for files (relative to executable for portability)
        self.config_dir = os.path.join(get_app_dir(), 'data')
        os.makedirs(self.config_dir, exist_ok=True)
        self.storage_dir = os.path.join(self.config_dir, 'storage')
        os.makedirs(self.storage_dir, exist_ok=True)
        # retention (key) file path
        self.retention_path = os.path.join(self.config_dir, 'key.json')
        # encryption settings object (cached for the session)
        self.encryption_settings = {}
        self._cached_passphrase = None
        
        # Chunking P2P manager
        self.chunking_mgr = None
        self._peer_uuid = str(uuid.uuid4())  # UUID unique pour ce peer
        self._init_chunking()

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

        # Vue P2P
        self.frames['p2p'] = P2PView(container, self)
        self.frames['p2p'].grid(row=0, column=0, sticky='nsew')

        # Vérifier et restaurer container.dat si nécessaire
        self._check_and_restore_container()

        self.show_view('files')

        # connection state
        self.conn = None
        self._updating = False
        
        # Bind cleanup on window close
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _init_chunking(self):
        """Initialise le système de chunking P2P."""
        if not CHUNKING_AVAILABLE:
            print("Module chunking non disponible")
            return
        
        try:
            # Chemins pour le chunking
            chunks_dir = os.path.join(self.config_dir, 'chunks')
            db_path = os.path.join(self.config_dir, 'chunk_metadata.db')
            
            # Créer le ChunkingManager
            self.chunking_mgr = ChunkingManager(
                peer_uuid=self._peer_uuid,
                storage_dir=chunks_dir,
                db_path=db_path,
                connection_handler=None  # Sera mis à jour lors de la connexion
            )
            
            print(f"ChunkingManager initialisé: peer={self._peer_uuid[:8]}...")
            
        except Exception as e:
            print(f"Erreur initialisation chunking: {e}")
            self.chunking_mgr = None

    def _check_and_restore_container(self):
        """
        Vérifie si container.dat existe localement.
        Si non, tente de le restaurer depuis les chunks distribués sur les pairs.
        """
        container_path = os.path.join(self.storage_dir, 'container.dat')
        
        # Si le container existe déjà, rien à faire
        if os.path.exists(container_path):
            print("[Container] container.dat trouvé localement")
            return
        
        # Pas de chunking manager = pas de restauration possible
        if not self.chunking_mgr:
            print("[Container] Pas de ChunkingManager, restauration impossible")
            return
        
        # Vérifier si on a des chunks du container dans notre base
        try:
            metadata = self.chunking_mgr.db.get_file_metadata_by_name(
                'container.dat', 
                self._peer_uuid
            )
            
            if not metadata:
                # Chercher aussi sans filtre de propriétaire (au cas où)
                metadata = self.chunking_mgr.db.get_file_metadata_by_name('container.dat')
            
            if not metadata:
                print("[Container] Aucun container.dat chunké trouvé en base")
                return
            
            # On a trouvé des métadonnées, demander à l'utilisateur
            if not self.encryption_settings or not self.encryption_settings.get('key'):
                print("[Container] Clé de chiffrement non disponible pour restauration")
                return
            
            # Afficher un dialogue de confirmation
            answer = messagebox.askyesno(
                'Restauration du conteneur',
                'Le fichier container.dat n\'existe pas localement mais des chunks '
                'ont été trouvés. Voulez-vous tenter de le restaurer depuis les chunks ?'
            )
            
            if not answer:
                return
            
            # Lancer la restauration dans un thread
            self._restore_container_async(metadata.file_uuid, metadata.owner_uuid, container_path)
            
        except Exception as e:
            print(f"[Container] Erreur vérification: {e}")

    def _restore_container_async(self, file_uuid: str, owner_uuid: str, output_path: str):
        """
        Restaure le container.dat de manière asynchrone.
        
        Args:
            file_uuid: UUID du fichier chunké
            owner_uuid: UUID du propriétaire
            output_path: Chemin de sortie pour le container restauré
        """
        def do_restore():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # Afficher une fenêtre de progression
                self.root.after(0, lambda: messagebox.showinfo(
                    'Restauration',
                    'Restauration du container.dat en cours...\n'
                    'Cela peut prendre quelques instants.'
                ))
                
                # Tenter la reconstruction
                reconstructed_data = loop.run_until_complete(
                    self.chunking_mgr.reconstruct_file(file_uuid, owner_uuid, output_path)
                )
                
                loop.close()
                
                # Succès
                self.root.after(0, lambda: self._on_container_restored(output_path))
                
            except Exception as e:
                error_msg = str(e)
                self.root.after(0, lambda: messagebox.showerror(
                    'Erreur de restauration',
                    f'Impossible de restaurer container.dat:\n{error_msg}\n\n'
                    'Il manque peut-être des chunks sur les pairs.'
                ))
                print(f"[Container] Erreur restauration: {e}")
        
        thread = threading.Thread(target=do_restore, daemon=True)
        thread.start()

    def _on_container_restored(self, container_path: str):
        """
        Callback appelé après la restauration réussie du container.
        
        Args:
            container_path: Chemin du container restauré
        """
        messagebox.showinfo(
            'Restauration réussie',
            f'Le fichier container.dat a été restauré avec succès !\n\n'
            f'Emplacement: {container_path}'
        )
        
        # Rafraîchir la vue des fichiers
        try:
            if 'files' in self.frames:
                self.frames['files'].refresh()
        except Exception as e:
            print(f"[Container] Erreur refresh après restauration: {e}")

    def _on_close(self):
        """Gère la fermeture propre de l'application."""
        try:
            # Fermer la connexion au tracker
            if self.conn:
                try:
                    self.conn.close()
                except:
                    pass
            
            # Arrêter le ChunkingManager
            if self.chunking_mgr:
                try:
                    # Créer une boucle asyncio pour shutdown
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(self.chunking_mgr.shutdown())
                    loop.close()
                except:
                    pass
        finally:
            self.root.destroy()

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
                # Mettre à jour le ChunkingManager avec le connection handler
                if self.chunking_mgr and self.conn:
                    self.chunking_mgr.set_connection_handler(self.conn, peer_ip, peer_port)
                    print(f"[Chunking] Connection handler mis à jour: {peer_ip}:{peer_port}")
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
            # Déconnecter aussi le ChunkingManager du tracker
            if self.chunking_mgr:
                self.chunking_mgr.set_connection_handler(None)
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
