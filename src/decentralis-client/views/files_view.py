import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import os
import shutil
import json
import base64
import tempfile
import asyncio
import threading
import hashlib

import crypto


class FilesView(ttk.Frame):
    CONTAINER_NAME = 'container.dat'
    CONTAINER_FILE_UUID = 'container-dat-primary'  # UUID fixe pour le container

    def __init__(self, parent, app_gui, **kwargs):
        super().__init__(parent, **kwargs)
        self.app_gui = app_gui
        self.cwd = ''  # virtual path inside container ('' = root)
        self.container = {'entries': {}}  # in-memory container structure
        self._container_hash = None  # Hash du container pour détecter les changements
        self._auto_sync_enabled = True  # Activer/désactiver la sync automatique

        # toolbar
        toolbar = ttk.Frame(self)
        toolbar.pack(fill='x', pady=(0, 4))
        ttk.Button(toolbar, text='Up', command=self.go_up).pack(side='left')
        ttk.Button(toolbar, text='New Folder', command=self.new_folder).pack(side='left')
        ttk.Button(toolbar, text='Upload', command=self.upload_file).pack(side='left')
        ttk.Button(toolbar, text='Download', command=self.download_file).pack(side='left')
        ttk.Button(toolbar, text='Delete', command=self.delete_selected).pack(side='left')
        ttk.Button(toolbar, text='Refresh', command=self.refresh).pack(side='left')

        # path label
        self.path_var = tk.StringVar()
        ttk.Label(self, textvariable=self.path_var).pack(anchor='w')

        # list
        self.listbox = tk.Listbox(self, height=16)
        self.listbox.pack(fill='both', expand=True)
        self.listbox.bind('<Double-1>', lambda e: self.enter_selected())

        # ensure storage dir
        os.makedirs(self.app_gui.storage_dir, exist_ok=True)

        self.refresh()

    def container_path(self):
        return os.path.join(self.app_gui.storage_dir, self.CONTAINER_NAME)

    def load_container(self):
        path = self.container_path()
        if not os.path.exists(path):
            # start with empty container
            self.container = {'entries': {}}
            return True

        settings = getattr(self.app_gui, 'encryption_settings', None) or {}
        algo = settings.get('algorithm')
        key = settings.get('key')
        if not algo or not key:
            messagebox.showerror('Erreur', 'Paramètres de chiffrement manquants pour ouvrir le conteneur')
            return False

        # decrypt to a temp file then load JSON
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(prefix='dec_container_', suffix='.json')
            os.close(fd)
            crypto.decrypt_file(path, tmp, key, algorithm=algo)
            with open(tmp, 'r', encoding='utf-8') as f:
                self.container = json.load(f)
            return True
        except Exception as e:
            messagebox.showerror('Erreur', f'Echec lecture conteneur: {e}')
            return False
        finally:
            try:
                if tmp and os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass

    def save_container(self):
        path = self.container_path()
        settings = getattr(self.app_gui, 'encryption_settings', None) or {}
        algo = settings.get('algorithm')
        key = settings.get('key')
        if not algo or not key:
            messagebox.showerror('Erreur', 'Paramètres de chiffrement manquants pour sauvegarder le conteneur')
            return False

        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(prefix='enc_container_', suffix='.json')
            os.close(fd)
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.container, f)
            crypto.encrypt_file(tmp, path, key, algorithm=algo)
            
            # Déclencher le chunking automatique après sauvegarde
            self._trigger_auto_chunk()
            
            return True
        except Exception as e:
            messagebox.showerror('Erreur', f'Echec sauvegarde conteneur: {e}')
            return False
        finally:
            try:
                if tmp and os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass

    def _trigger_auto_chunk(self):
        """
        Déclenche le chunking automatique du container.dat
        et la distribution vers les pairs si connecté.
        """
        if not self._auto_sync_enabled:
            return
            
        chunking_mgr = getattr(self.app_gui, 'chunking_mgr', None)
        if not chunking_mgr:
            return
        
        # Calculer le hash du container pour détecter les changements
        container_path = self.container_path()
        if not os.path.exists(container_path):
            return
            
        try:
            with open(container_path, 'rb') as f:
                new_hash = hashlib.sha256(f.read()).hexdigest()
        except Exception:
            return
        
        # Si le hash n'a pas changé, pas besoin de re-chunker
        if new_hash == self._container_hash:
            return
        
        self._container_hash = new_hash
        
        # Exécuter le chunking dans un thread séparé
        def do_chunk():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # Chunker le fichier
                owner_uuid = getattr(self.app_gui, '_peer_uuid', 'local')
                
                # Supprimer l'ancien chunking du container s'il existe
                try:
                    existing = chunking_mgr.db.get_file_metadata_by_name(
                        self.CONTAINER_NAME, owner_uuid
                    )
                    if existing:
                        loop.run_until_complete(
                            self._delete_old_container_chunks(chunking_mgr, existing.file_uuid, owner_uuid)
                        )
                except Exception:
                    pass
                
                # Chunker le nouveau container
                file_uuid = loop.run_until_complete(
                    chunking_mgr.chunk_file(container_path, owner_uuid)
                )
                
                print(f"[Auto-Chunk] container.dat chunké: {file_uuid[:8]}...")
                
                # Distribuer si on est connecté au tracker
                conn = getattr(self.app_gui, 'conn', None)
                if conn:
                    try:
                        result = loop.run_until_complete(
                            chunking_mgr.distribute_chunks(file_uuid, owner_uuid)
                        )
                        print(f"[Auto-Sync] Distribué: {result.get('distributed', 0)}/{result.get('total_chunks', 0)} chunks")
                    except Exception as e:
                        print(f"[Auto-Sync] Erreur distribution: {e}")
                
                loop.close()
                
            except Exception as e:
                print(f"[Auto-Chunk] Erreur: {e}")
        
        thread = threading.Thread(target=do_chunk, daemon=True)
        thread.start()
    
    async def _delete_old_container_chunks(self, mgr, file_uuid: str, owner_uuid: str):
        """Supprime les anciens chunks du container."""
        try:
            mgr.delete_file(file_uuid, owner_uuid)
        except Exception:
            pass

    def refresh(self):
        if not self.load_container():
            return

        # compute direct children in current cwd
        prefix = (self.cwd + '/') if self.cwd else ''
        children = {}
        for key, meta in self.container.get('entries', {}).items():
            if not key.startswith(prefix):
                continue
            rest = key[len(prefix):]
            if '/' in rest:
                name = rest.split('/', 1)[0]
                children[name] = {'type': 'dir'}
            else:
                # file or dir at this level
                children[rest] = {'type': meta.get('type', 'file')}

        # sort directories first
        items = sorted(children.items(), key=lambda kv: (kv[1]['type'] != 'dir', kv[0].lower()))

        self.listbox.delete(0, tk.END)
        for name, info in items:
            display = name + ('/' if info['type'] == 'dir' else '')
            self.listbox.insert(tk.END, display)

        rel = '/' + self.cwd if self.cwd else '/'
        self.path_var.set(f'Storage: {rel}')

    def go_up(self):
        if not self.cwd:
            return
        self.cwd = os.path.dirname(self.cwd)
        if self.cwd == '.':
            self.cwd = ''
        self.refresh()

    def enter_selected(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        name = self.listbox.get(sel[0])
        if name.endswith('/'):
            name = name[:-1]
            self.cwd = os.path.join(self.cwd, name) if self.cwd else name
            # normalize separators
            self.cwd = self.cwd.replace('\\', '/')
            self.refresh()

    def new_folder(self):
        name = simpledialog.askstring('Nouveau dossier', 'Nom du dossier:')
        if not name:
            return
        key = os.path.join(self.cwd, name) if self.cwd else name
        key = key.replace('\\', '/')
        entries = self.container.setdefault('entries', {})
        if key in entries and entries[key].get('type') == 'dir':
            messagebox.showerror('Erreur', 'Le dossier existe déjà')
            return
        entries[key] = {'type': 'dir'}
        if self.save_container():
            self.refresh()

    def upload_file(self):
        path = filedialog.askopenfilename()
        if not path:
            return

        # require encryption settings
        settings = getattr(self.app_gui, 'encryption_settings', None) or {}
        algo = settings.get('algorithm')
        key = settings.get('key')
        if not algo or not key:
            messagebox.showerror('Erreur', 'Paramètres de chiffrement non configurés. Configurez une clé dans la vue Chiffrement.')
            return

        try:
            with open(path, 'rb') as f:
                data = f.read()
            b64 = base64.b64encode(data).decode('ascii')
            name = os.path.basename(path)
            keypath = os.path.join(self.cwd, name) if self.cwd else name
            keypath = keypath.replace('\\', '/')
            entries = self.container.setdefault('entries', {})
            entries[keypath] = {'type': 'file', 'content': b64}
            if self.save_container():
                messagebox.showinfo('Upload', 'Fichier ajouté au conteneur chiffré')
                self.refresh()
        except Exception as e:
            messagebox.showerror('Erreur', f'Echec upload: {e}')

    def download_file(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showinfo('Info', 'Aucun fichier sélectionné')
            return
        name = self.listbox.get(sel[0])
        if name.endswith('/'):
            messagebox.showinfo('Info', 'Sélectionnez un fichier, pas un dossier')
            return

        rel_name = name
        keypath = os.path.join(self.cwd, rel_name) if self.cwd else rel_name
        keypath = keypath.replace('\\', '/')
        entry = self.container.get('entries', {}).get(keypath)
        if not entry or entry.get('type') != 'file':
            messagebox.showerror('Erreur', 'Entrée non trouvée ou invalide')
            return

        dst_dir = filedialog.askdirectory()
        if not dst_dir:
            return

        try:
            b64 = entry.get('content', '')
            data = base64.b64decode(b64)
            dst_path = os.path.join(dst_dir, os.path.basename(rel_name))
            with open(dst_path, 'wb') as f:
                f.write(data)
            messagebox.showinfo('Download', 'Fichier exporté')
        except Exception as e:
            messagebox.showerror('Erreur', f'Echec download: {e}')

    def delete_selected(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showinfo('Info', 'Aucune sélection')
            return
        name = self.listbox.get(sel[0])
        is_dir = name.endswith('/')
        if is_dir:
            name = name[:-1]
        keypath = os.path.join(self.cwd, name) if self.cwd else name
        keypath = keypath.replace('\\', '/')
        if not messagebox.askyesno('Confirmer', f'Supprimer {name}?'):
            return
        try:
            entries = self.container.setdefault('entries', {})
            if is_dir:
                prefix = keypath + '/'
                to_delete = [k for k in entries.keys() if k == keypath or k.startswith(prefix)]
                for k in to_delete:
                    del entries[k]
            else:
                if keypath in entries:
                    del entries[keypath]
            if self.save_container():
                self.refresh()
        except Exception as e:
            messagebox.showerror('Erreur', f'Echec suppression: {e}')

