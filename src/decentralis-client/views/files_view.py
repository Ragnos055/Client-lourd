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
    """
    Gestionnaire de fichiers avec un container par fichier.
    
    Nouvelle architecture:
    - Chaque fichier = un container.dat indépendant nommé {file_uuid}.dat
    - Arborescence (dossiers) stockée en BD et en mémoire
    - Navigation interactive dans l'arborescence
    - Upload/Delete/Rebuild par fichier individuel
    """

    def __init__(self, parent, app_gui, **kwargs):
        super().__init__(parent, **kwargs)
        self.app_gui = app_gui
        self.cwd = ''  # virtual path ('' = root)
        self.container = {'entries': {}}  # in-memory arborescence (dossiers + file_uuid)
        self._file_uuids = {}  # Mapping: logical_path -> file_uuid
        self._progress = {}  # Tracking: logical_path -> {'phase': str, 'percent': int}

        # toolbar
        toolbar = ttk.Frame(self)
        toolbar.pack(fill='x', pady=(0, 4))
        ttk.Button(toolbar, text='Up', command=self.go_up).pack(side='left')
        ttk.Button(toolbar, text='New Folder', command=self.new_folder).pack(side='left')
        ttk.Button(toolbar, text='Upload', command=self.upload_file).pack(side='left')
        ttk.Button(toolbar, text='Force Resync', command=self.force_resync_file).pack(side='left')
        ttk.Button(toolbar, text='Delete Local', command=self.delete_local_file).pack(side='left')
        ttk.Button(toolbar, text='Delete Permanent', command=self.delete_permanent_file).pack(side='left')
        ttk.Button(toolbar, text='Refresh', command=self.refresh).pack(side='left')
        ttk.Button(toolbar, text='Rebuild', command=self.rebuild_container).pack(side='left')
        ttk.Button(toolbar, text='Ouvrir', command=self.open_container_file).pack(side='left')

        # path label
        self.path_var = tk.StringVar()
        ttk.Label(self, textvariable=self.path_var).pack(anchor='w')

        # list avec Treeview
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill='both', expand=True)
        
        self.file_tree = ttk.Treeview(tree_frame, columns=('status',), show='tree', height=16)
        self.file_tree.column('#0', width=400)
        self.file_tree.column('status', width=0, stretch=False)
        
        self.file_tree.tag_configure('available', foreground='green')
        self.file_tree.tag_configure('needs_rebuild', foreground='red')
        self.file_tree.tag_configure('directory', foreground='black')
        
        scrollbar = ttk.Scrollbar(tree_frame, orient='vertical', command=self.file_tree.yview)
        self.file_tree.configure(yscrollcommand=scrollbar.set)
        self.file_tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        
        self.file_tree.bind('<Double-1>', lambda e: self.enter_selected())
        
        self.listbox = self.file_tree

        os.makedirs(self.app_gui.storage_dir, exist_ok=True)

        self.refresh()

    def get_container_path(self, file_uuid: str) -> str:
        """Chemin du container pour un fichier spécifique."""
        return os.path.join(self.app_gui.storage_dir, f'{file_uuid}.dat')

    def _update_progress(self, logical_path: str, phase: str, percent: int):
        """Met à jour la progression d'un fichier et rafraîchit l'affichage."""
        self._progress[logical_path] = {'phase': phase, 'percent': percent}
        self.after(0, self._refresh_item_display, logical_path)
        
        # Nettoyer automatiquement après 2 secondes si 100%
        if percent >= 100:
            self.after(2000, self._clear_progress, logical_path)

    def _clear_progress(self, logical_path: str):
        """Efface la progression d'un fichier après complétion."""
        if logical_path in self._progress and self._progress[logical_path].get('percent', 0) >= 100:
            del self._progress[logical_path]
            self.after(0, self.refresh)

    def _get_progress_text(self, logical_path: str) -> str:
        """Retourne le texte de progression à afficher."""
        if logical_path not in self._progress:
            return ""
        prog = self._progress[logical_path]
        phase = prog.get('phase', '')
        percent = prog.get('percent', 0)
        
        if percent >= 100:
            return f"[✓ {phase}]"
        else:
            # Barre de progression simple: [████░░░░░░ 40%]
            filled = int(percent / 10)
            empty = 10 - filled
            bar = '█' * filled + '░' * empty
            return f"[{bar} {percent}%]"

    def _refresh_item_display(self, logical_path: str):
        """Rafraîchit l'affichage d'un item dans la TreeView avec la progression."""
        # Chercher l'item correspondant
        for item in self.file_tree.get_children(''):
            item_text = self.file_tree.item(item, 'text')
            # Nettoyer le texte du précédent affichage de progression
            base_name = item_text.split(' [')[0] if ' [' in item_text else item_text
            
            # Reconstruire le chemin logique
            keypath = os.path.join(self.cwd, base_name.rstrip('/')) if self.cwd else base_name.rstrip('/')
            keypath = keypath.replace('\\', '/')
            
            if keypath == logical_path:
                # Mettre à jour le texte avec la progression
                progress_text = self._get_progress_text(logical_path)
                new_text = base_name + ' ' + progress_text if progress_text else base_name
                self.file_tree.item(item, text=new_text)
                break

    def load_container(self):
        """
        Charge l'arborescence depuis la BD.
        Reconstruit self.container avec l'arborescence logique.
        """
        mgr = getattr(self.app_gui, 'chunking_mgr', None)
        if not mgr:
            self.container = {'entries': {}}
            return True
        
        try:
            # Récupérer tous les fichiers de la BD
            all_files = mgr.db.get_all_file_metadata()
            
            # Reconstruire l'arborescence
            self.container = {'entries': {}}
            self._file_uuids = {}
            
            for file_meta in all_files:
                # file_meta est toujours un objet ChunkMetadata
                file_uuid = file_meta.file_uuid
                file_path = getattr(file_meta, 'file_path', '')
                
                if not file_path:
                    continue
                
                # Ajouter à l'arborescence
                self._add_to_entries(file_path, file_uuid)
                self._file_uuids[file_path] = file_uuid
            
            return True
        except Exception as e:
            print(f"Erreur load_container: {e}")
            self.container = {'entries': {}}
            return False

    def _add_to_entries(self, file_path: str, file_uuid: str):
        """Ajoute un fichier à l'arborescence (structure plate avec chemins logiques)."""
        # Stocker directement avec le chemin logique comme clé
        self.container['entries'][file_path] = {'type': 'file', 'file_uuid': file_uuid}
        self._file_uuids[file_path] = file_uuid

    def save_container(self):
        """
        Sauvegarde chaque fichier individuellement.
        Chiffre et stocke chaque {file_uuid}.dat.
        """
        settings = getattr(self.app_gui, 'encryption_settings', None) or {}
        algo = settings.get('algorithm')
        key = settings.get('key')
        if not algo or not key:
            messagebox.showerror('Erreur', 'Paramètres de chiffrement manquants')
            return False

        mgr = getattr(self.app_gui, 'chunking_mgr', None)
        if not mgr:
            return False
        
        # TODO: Implémenter la sauvegarde par fichier
        # Pour maintenant, retourner True
        return True

    def refresh(self):
        """Rafraîchit l'affichage depuis l'arborescence en mémoire."""
        # Charger l'arborescence depuis la BD
        self.load_container()
        
        # S'assurer qu'on a une structure
        if not hasattr(self, 'container') or self.container is None:
            self.container = {'entries': {}}

        # Afficher le répertoire courant
        prefix = (self.cwd + '/') if self.cwd else ''
        children = {}
        
        for key in self.container.get('entries', {}).keys():
            if not key.startswith(prefix):
                continue
            rest = key[len(prefix):]
            if '/' in rest:
                # C'est un dossier intermédiaire
                name = rest.split('/', 1)[0]
                children[name] = {'type': 'dir'}
            else:
                # C'est un fichier dans le répertoire courant
                entry = self.container['entries'][key]
                children[rest] = entry

        # Trier: dossiers d'abord
        items = sorted(children.items(), key=lambda kv: (kv[1].get('type') != 'dir', kv[0].lower()))

        self.file_tree.delete(*self.file_tree.get_children())
        
        for name, info in items:
            is_dir = info.get('type') == 'dir'
            display = name + ('/' if is_dir else '')
            
            # Déterminer le tag
            if is_dir:
                tag = 'directory'
            else:
                # Vérifier si le fichier a un container local
                file_uuid = info.get('file_uuid', '')
                if file_uuid:
                    container_file = self.get_container_path(file_uuid)
                    tag = 'available' if os.path.exists(container_file) else 'needs_rebuild'
                else:
                    tag = 'available'
            
            # Ajouter la progression si applicable
            keypath = os.path.join(self.cwd, name.rstrip('/')) if self.cwd else name.rstrip('/')
            keypath = keypath.replace('\\', '/')
            progress_text = self._get_progress_text(keypath)
            if progress_text:
                display = display + ' ' + progress_text
            
            self.file_tree.insert('', 'end', text=display, values=(tag,), tags=(tag,))

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
        sel = self.file_tree.selection()
        if not sel:
            return
        item = self.file_tree.item(sel[0])
        name = item['text']
        if name.endswith('/'):
            name = name[:-1]
            self.cwd = os.path.join(self.cwd, name) if self.cwd else name
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
        """Menu pour choisir upload fichiers ou dossier."""
        # Créer une fenêtre de dialogue avec des boutons clairs
        dialog = tk.Toplevel(self)
        dialog.title('Upload')
        dialog.geometry('300x120')
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        
        # Centrer la fenêtre
        dialog.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - dialog.winfo_width()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f'+{x}+{y}')
        
        label = ttk.Label(dialog, text='Choisir le type d\'upload:', justify='center')
        label.pack(pady=10)
        
        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=10)
        
        choice_var = [None]
        
        def on_files():
            choice_var[0] = 'files'
            dialog.destroy()
        
        def on_folder():
            choice_var[0] = 'folder'
            dialog.destroy()
        
        ttk.Button(button_frame, text='Fichiers multiples', command=on_files).pack(side='left', padx=5)
        ttk.Button(button_frame, text='Dossier entier', command=on_folder).pack(side='left', padx=5)
        
        self.wait_window(dialog)
        
        if choice_var[0] == 'files':
            self.upload_multiple_files()
        elif choice_var[0] == 'folder':
            self.upload_directory()

    def upload_multiple_files(self):
        """Upload plusieurs fichiers à la fois - chacun devient un container indépendant."""
        paths = filedialog.askopenfilenames()
        if not paths:
            return

        settings = getattr(self.app_gui, 'encryption_settings', None) or {}
        algo = settings.get('algorithm')
        key = settings.get('key')
        if not algo or not key:
            messagebox.showerror('Erreur', 'Paramètres de chiffrement non configurés.')
            return

        mgr = getattr(self.app_gui, 'chunking_mgr', None)
        if not mgr:
            messagebox.showerror('Erreur', 'ChunkingManager non disponible')
            return

        count = 0
        for file_path in paths:
            try:
                # Chaque fichier uplodé crée son propre container
                self._upload_single_file(file_path, algo, key, mgr)
                count += 1
            except Exception as e:
                messagebox.showwarning('Avertissement', f'Impossible d\'uploader {os.path.basename(file_path)}: {e}')
        
        if count > 0:
            messagebox.showinfo('Upload', f'{count} fichier(s) uploadé(s)')
            self.refresh()
            # Rafraîchir P2P
            try:
                p2p_view = self.app_gui.frames.get('p2p') if hasattr(self.app_gui, 'frames') else None
                if p2p_view and hasattr(p2p_view, '_refresh_local'):
                    self.after(0, p2p_view._refresh_local)
            except Exception:
                pass

    def upload_directory(self):
        """Upload un dossier entier - chaque fichier devient un container indépendant."""
        dir_path = filedialog.askdirectory(title='Sélectionner le dossier à uploader')
        if not dir_path:
            return

        settings = getattr(self.app_gui, 'encryption_settings', None) or {}
        algo = settings.get('algorithm')
        key = settings.get('key')
        if not algo or not key:
            messagebox.showerror('Erreur', 'Paramètres de chiffrement non configurés.')
            return

        mgr = getattr(self.app_gui, 'chunking_mgr', None)
        if not mgr:
            messagebox.showerror('Erreur', 'ChunkingManager non disponible')
            return

        count = 0
        folder_name = os.path.basename(dir_path)
        
        # Parcourir récursivement
        for root, dirs, files in os.walk(dir_path):
            # Créer les entrées dossiers en mémoire
            for dir_name in dirs:
                abs_dir = os.path.join(root, dir_name)
                rel_path = os.path.relpath(abs_dir, dir_path)
                logical_path = os.path.join(self.cwd, folder_name, rel_path) if self.cwd else os.path.join(folder_name, rel_path)
                logical_path = logical_path.replace('\\', '/')
                entries = self.container.setdefault('entries', {})
                if logical_path not in entries:
                    entries[logical_path] = {'type': 'dir'}
            
            # Uploader chaque fichier
            for file_name in files:
                abs_file = os.path.join(root, file_name)
                rel_path = os.path.relpath(abs_file, dir_path)
                logical_path = os.path.join(self.cwd, folder_name, rel_path) if self.cwd else os.path.join(folder_name, rel_path)
                logical_path = logical_path.replace('\\', '/')
                
                try:
                    self._upload_single_file(abs_file, algo, key, mgr, logical_path)
                    count += 1
                except Exception as e:
                    messagebox.showwarning('Avertissement', f'Impossible d\'uploader {file_name}: {e}')
        
        if count > 0:
            messagebox.showinfo('Upload', f'Dossier "{folder_name}" uploadé avec {count} fichier(s)')
            self.refresh()
            try:
                p2p_view = self.app_gui.frames.get('p2p') if hasattr(self.app_gui, 'frames') else None
                if p2p_view and hasattr(p2p_view, '_refresh_local'):
                    self.after(0, p2p_view._refresh_local)
            except Exception:
                pass

    def _upload_single_file(self, file_path: str, algo: str, key: str, mgr, logical_path: str = None):
        """
        Upload un fichier unique.
        Crée son container individuel et l'enregistre en BD.
        """
        if logical_path is None:
            name = os.path.basename(file_path)
            logical_path = os.path.join(self.cwd, name) if self.cwd else name
            logical_path = logical_path.replace('\\', '/')
        
        # Lire le fichier
        with open(file_path, 'rb') as f:
            data = f.read()
        
        # Créer un UUID pour ce fichier
        import uuid
        file_uuid = str(uuid.uuid4())
        
        # Créer le container pour ce fichier (JSON simple)
        container = {'file_uuid': file_uuid, 'original_filename': os.path.basename(file_path), 'data': base64.b64encode(data).decode('ascii')}
        
        # Chiffrer et sauvegarder
        container_path = self.get_container_path(file_uuid)
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(prefix='enc_file_', suffix='.json')
            os.close(fd)
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(container, f)
            crypto.encrypt_file(tmp, container_path, key, algorithm=algo)
        finally:
            try:
                if tmp and os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass
        
        # Ajouter à l'arborescence en mémoire
        entries = self.container.setdefault('entries', {})
        entries[logical_path] = {'type': 'file', 'file_uuid': file_uuid}
        self._file_uuids[logical_path] = file_uuid
        
        # Enregistrer les métadonnées en BD
        from chunking.models import ChunkMetadata
        owner_uuid = getattr(self.app_gui, '_peer_uuid', 'local')
        
        metadata = ChunkMetadata(
            file_uuid=file_uuid,
            owner_uuid=owner_uuid,
            original_filename=os.path.basename(file_path),
            file_path=logical_path,
            original_hash=hashlib.sha256(data).hexdigest(),
            original_size=len(data),
            total_chunks=0,  # Sera mis à jour lors du chunking
            data_chunks=0,
            parity_chunks=0,
            chunk_size=0,
            algorithm='aes-256'
        )
        
        try:
            mgr.db.add_file_metadata(metadata)
        except Exception as e:
            print(f"Erreur enregistrement BD: {e}")
        
        # Chunker et distribuer automatiquement le fichier
        self._auto_chunk_and_distribute(file_uuid, container_path, mgr, logical_path)

    def _auto_chunk_and_distribute(self, old_file_uuid: str, container_path: str, mgr, logical_path: str):
        """Chunke et distribue automatiquement un fichier après upload."""
        import asyncio
        import threading
        
        def do_chunk():
            try:
                owner_uuid = getattr(self.app_gui, '_peer_uuid', 'local')
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # Chunker - retourne le nouveau file_uuid généré
                # Passer le chemin logique pour préserver le nom du fichier
                self._update_progress(logical_path, 'Chunking', 0)
                new_file_uuid = loop.run_until_complete(
                    mgr.chunk_file(container_path, owner_uuid, file_logical_path=logical_path)
                )
                self._update_progress(logical_path, 'Chunking', 100)
                print(f"[Auto-Chunk] Fichier chunké: {old_file_uuid[:8]}... -> {new_file_uuid[:8]}...")
                
                # Mettre à jour les métadonnées avec le vrai file_uuid des chunks
                # (chunk_file crée ses propres métadonnées, on doit supprimer l'ancienne entrée)
                try:
                    # Supprimer l'ancienne entrée avec old_file_uuid
                    mgr.db.delete_file_metadata(old_file_uuid)
                    
                    # Mettre à jour l'arborescence en mémoire avec le nouveau UUID
                    for path_key, uuid_val in list(self._file_uuids.items()):
                        if uuid_val == old_file_uuid:
                            self._file_uuids[path_key] = new_file_uuid
                            self.container['entries'][path_key]['file_uuid'] = new_file_uuid
                            break
                    
                    # Renommer le container sur disque
                    old_container = self.get_container_path(old_file_uuid)
                    new_container = self.get_container_path(new_file_uuid)
                    if os.path.exists(old_container) and old_container != new_container:
                        os.rename(old_container, new_container)
                except Exception as update_err:
                    print(f"[Auto-Chunk] Erreur mise à jour métadonnées: {update_err}")
                
                # Distribuer si connecté (utiliser le nouveau UUID)
                conn = getattr(self.app_gui, 'conn', None)
                if conn:
                    try:
                        self._update_progress(logical_path, 'Distribution', 0)
                        result = loop.run_until_complete(
                            mgr.distribute_chunks(new_file_uuid, owner_uuid)
                        )
                        distributed = result.get('distributed', 0) if isinstance(result, dict) else 0
                        total_chunks = result.get('total_chunks', 0) if isinstance(result, dict) else 0
                        failed = result.get('failed', 0) if isinstance(result, dict) else 0
                        
                        # Calculer le pourcentage
                        if total_chunks > 0:
                            percent = min(100, int((distributed / total_chunks) * 100))
                        else:
                            percent = 0
                        self._update_progress(logical_path, 'Distribution', percent)
                        
                        print(f"[Auto-Sync] Distribué: {distributed}/{total_chunks} chunks, Échoués: {failed}")
                        print(f"[Auto-Sync] DEBUG: result={result}, distributed={distributed}, total_chunks={total_chunks}, failed={failed}")
                        
                        # Conditions de suppression du container:
                        # 1. Si total_chunks == 0, c'est une distribution qui n'a pas pu se faire
                        #    (lock en cours, erreur...) -> NE PAS SUPPRIMER
                        # 2. Si total_chunks > 0 ET distributed == total_chunks ET failed == 0
                        #    -> SUPPRIMER (distribution réussie)
                        # 3. Si total_chunks > 0 ET distributed > 0 (même si incomplet)
                        #    -> CONSIDÉRER COMME SUCCÈS (au moins certains chunks distribués)
                        
                        should_delete = False
                        reason = ""
                        
                        if total_chunks == 0:
                            reason = "total_chunks=0, distribution n'a pas eu lieu"
                        elif distributed == 0:
                            reason = "distributed=0, aucun chunk envoyé"
                        elif failed > 0:
                            reason = f"failed={failed}, des chunks ont échoué"
                        elif distributed == total_chunks:
                            should_delete = True
                            reason = "SUCCESS: tous les chunks distribués"
                        elif distributed > 0:
                            # Au moins quelques chunks ont été distribués
                            should_delete = True
                            reason = f"PARTIAL SUCCESS: {distributed}/{total_chunks} chunks distribués (pas tous, mais suffisant)"
                        
                        print(f"[Auto-Sync] Décision suppression: should_delete={should_delete}, raison={reason}")
                        
                        if should_delete:
                            try:
                                # Vérifier que new_container existe avant de le supprimer
                                if 'new_container' in locals() and new_container and os.path.exists(new_container):
                                    os.remove(new_container)
                                    print(f"[Auto-Sync] ✓ Container supprimé: {new_container}")
                                    self._update_progress(logical_path, 'Sync', 100)
                                    self.after(0, self.refresh)
                                else:
                                    print(f"[Auto-Sync] ⚠ Container déjà supprimé ou introuvable")
                            except Exception as del_err:
                                print(f"[Auto-Sync] ✗ ERREUR suppression: {del_err}")
                        else:
                            print(f"[Auto-Sync] ✗ Container NON supprimé: {reason}")
                    except Exception as e:
                        print(f"[Auto-Sync] Erreur distribution: {e}")
                        self._update_progress(logical_path, 'Erreur', 0)
                
                loop.close()
            except Exception as e:
                print(f"[Auto-Chunk] Erreur: {e}")
        
        thread = threading.Thread(target=do_chunk, daemon=True)
        thread.start()

    def force_resync_file(self):
        """Force le rechunking et l'envoi des chunks pour un fichier ou dossier."""
        sel = self.file_tree.selection()
        if not sel:
            messagebox.showinfo('Info', 'Aucun fichier ou dossier sélectionné')
            return
        
        item = self.file_tree.item(sel[0])
        name = item['text']
        is_dir = name.endswith('/')
        
        selected_path = os.path.join(self.cwd, name.rstrip('/')) if self.cwd else name.rstrip('/')
        selected_path = selected_path.replace('\\', '/')
        
        if not messagebox.askyesno('Confirmer', 
            f'Forcer le rechunking et l\'envoi des chunks?\n\n'
            f'Cela va créer de nouveaux chunks et les distribuer aux pairs.'):
            return
        
        try:
            if is_dir:
                # Rechunk tous les fichiers du dossier
                self._force_resync_directory_recursive(selected_path)
                messagebox.showinfo('Succès', 'Rechunking et envoi lancés pour le dossier.')
            else:
                # Rechunk ce fichier
                file_uuid = self._file_uuids.get(selected_path)
                if not file_uuid:
                    messagebox.showerror('Erreur', 'Fichier non trouvé dans l\'arborescence')
                    return
                
                mgr = getattr(self.app_gui, 'chunking_mgr', None)
                owner_uuid = getattr(self.app_gui, '_peer_uuid', 'local')
                settings = getattr(self.app_gui, 'encryption_settings', None) or {}
                algo = settings.get('algorithm')
                key = settings.get('key')
                
                if not mgr or not algo or not key:
                    messagebox.showerror('Erreur', 'Configuration incomplète')
                    return
                
                container_path = self.get_container_path(file_uuid)
                container_exists = os.path.exists(container_path)
                
                # Vérifier si des chunks existent déjà
                try:
                    chunks = mgr.store.list_chunks(owner_uuid, file_uuid)
                    has_chunks = len(chunks) > 0
                except:
                    has_chunks = False
                
                if not container_exists and not has_chunks:
                    # Ni container ni chunks → proposer rebuild d'abord
                    if messagebox.askyesno('Container manquant', 
                        'Le container local et les chunks sont manquants.\n\n'
                        'Voulez-vous d\'abord rebuilder le fichier depuis le réseau?'):
                        self._rebuild_file(file_uuid, selected_path, mgr)
                    return
                
                if has_chunks and not container_exists:
                    # Chunks existent mais pas le container → juste redistribuer
                    if messagebox.askyesno('Redistribution', 
                        'Les chunks existent déjà mais le container local est manquant.\n\n'
                        'Voulez-vous forcer la redistribution des chunks existants?'):
                        # Forcer distribution directement
                        self._force_redistribute(file_uuid, owner_uuid, mgr, selected_path)
                    return
                
                # Container existe → rechunker et redistribuer
                self._auto_chunk_and_distribute(file_uuid, container_path, mgr, selected_path)
                messagebox.showinfo('Succès', 'Rechunking et envoi lancés.')
            
            self.refresh()
        except Exception as e:
            messagebox.showerror('Erreur', f'Impossible de forcer resync: {e}')

    def _force_redistribute(self, file_uuid: str, owner_uuid: str, mgr, logical_path: str):
        """Force la redistribution des chunks existants sans rechunker."""
        import asyncio
        import threading
        
        def do_distribute():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                self._update_progress(logical_path, 'Redistribution', 0)
                result = loop.run_until_complete(
                    mgr.distribute_chunks(file_uuid, owner_uuid)
                )
                
                distributed = result.get('distributed', 0) if isinstance(result, dict) else 0
                total_chunks = result.get('total_chunks', 0) if isinstance(result, dict) else 0
                
                if total_chunks > 0:
                    percent = min(100, int((distributed / total_chunks) * 100))
                else:
                    percent = 0
                self._update_progress(logical_path, 'Redistribution', percent)
                
                print(f"[Force-Redistribute] {distributed}/{total_chunks} chunks redistribués")
                
                if distributed > 0:
                    self._update_progress(logical_path, 'Sync', 100)
                
                loop.close()
            except Exception as e:
                print(f"[Force-Redistribute] Erreur: {e}")
                self._update_progress(logical_path, 'Erreur', 0)
        
        threading.Thread(target=do_distribute, daemon=True).start()

    def _force_resync_directory_recursive(self, dir_path: str):
        """Force le rechunking et l'envoi pour tous les fichiers dans un dossier récursivement."""
        prefix = dir_path + '/'
        mgr = getattr(self.app_gui, 'chunking_mgr', None)
        owner_uuid = getattr(self.app_gui, '_peer_uuid', 'local')
        settings = getattr(self.app_gui, 'encryption_settings', None) or {}
        algo = settings.get('algorithm')
        key = settings.get('key')
        
        if not mgr or not algo or not key:
            raise Exception('Configuration incomplète')
        
        for path, entry in self.container.get('entries', {}).items():
            if path.startswith(prefix) and entry.get('type') == 'file':
                file_uuid = entry.get('file_uuid')
                if file_uuid:
                    container_path = self.get_container_path(file_uuid)
                    container_exists = os.path.exists(container_path)
                    
                    # Vérifier si des chunks existent
                    try:
                        chunks = mgr.store.list_chunks(owner_uuid, file_uuid)
                        has_chunks = len(chunks) > 0
                    except:
                        has_chunks = False
                    
                    if container_exists:
                        # Container existe → rechunker
                        self._auto_chunk_and_distribute(file_uuid, container_path, mgr, path)
                    elif has_chunks:
                        # Chunks existent mais pas container → redistribuer
                        self._force_redistribute(file_uuid, owner_uuid, mgr, path)
                    else:
                        # Ni container ni chunks → ignorer et continuer
                        print(f"[Force-Resync-Dir] Ignoré {path}: ni container ni chunks")

    def delete_local_file(self):
        """
        Supprime le fichier container local, SEULEMENT si des chunks ont été distribués aux pairs.
        - Fichier sélectionné: supprime juste ce container
        - Dossier sélectionné: supprime containers de tous fichiers du dossier récursivement
        """
        sel = self.file_tree.selection()
        if not sel:
            messagebox.showinfo('Info', 'Sélectionnez un fichier ou un dossier')
            return
        
        item = self.file_tree.item(sel[0])
        name = item['text']
        is_dir = name.endswith('/')
        
        selected_path = os.path.join(self.cwd, name.rstrip('/')) if self.cwd else name.rstrip('/')
        selected_path = selected_path.replace('\\', '/')
        
        mgr = getattr(self.app_gui, 'chunking_mgr', None)
        owner_uuid = getattr(self.app_gui, '_peer_uuid', 'local')
        
        if not mgr:
            messagebox.showerror('Erreur', 'ChunkingManager non disponible')
            return
        
        # Vérifier que des chunks ont été distribués
        if is_dir:
            prefix = selected_path + '/'
            files_to_check = []
            for path, entry in self.container.get('entries', {}).items():
                if path.startswith(prefix) and entry.get('type') == 'file':
                    file_uuid = entry.get('file_uuid')
                    if file_uuid:
                        files_to_check.append((path, file_uuid))
            
            if not files_to_check:
                messagebox.showinfo('Info', 'Aucun fichier dans ce dossier')
                return
            
            # Vérifier qu'au moins un fichier a des chunks distribués
            has_distributed_chunks = False
            for path, file_uuid in files_to_check:
                locations = mgr.db.get_locations_by_file(file_uuid, owner_uuid)
                if locations:
                    has_distributed_chunks = True
                    break
        else:
            file_uuid = self._file_uuids.get(selected_path)
            if not file_uuid:
                messagebox.showerror('Erreur', 'Fichier non trouvé')
                return
            
            locations = mgr.db.get_locations_by_file(file_uuid, owner_uuid)
            has_distributed_chunks = len(locations) > 0
        
        # Si aucun chunk n'a été distribué, refuser
        if not has_distributed_chunks:
            messagebox.showwarning('Impossible', 
                'Vous ne pouvez supprimer que si des chunks ont déjà été distribués aux pairs.\n\n'
                'Utilisez "Force Resync" pour forcer le chunking et l\'envoi.')
            return
        
        if not messagebox.askyesno('Confirmer', 
            f'Supprimer les versions locales?\n\n'
            f'Les fichiers restent en mémoire distribués et peuvent être reconstruits.'):
            return
        
        try:
            if is_dir:
                # Supprimer containers de tous les fichiers du dossier
                count = self._delete_local_directory_recursive(selected_path)
                messagebox.showinfo('Succès', f'{count} fichier(s) supprimé(s) localement.')
            else:
                # Supprimer container de ce fichier
                container_path = self.get_container_path(file_uuid)
                if os.path.exists(container_path):
                    os.remove(container_path)
                messagebox.showinfo('Succès', 'Fichier supprimé localement.')
            
            self.refresh()
        except Exception as e:
            messagebox.showerror('Erreur', f'Impossible de supprimer: {e}')

    def _delete_local_directory_recursive(self, dir_path: str) -> int:
        """Supprime containers de tous les fichiers dans un dossier récursivement."""
        prefix = dir_path + '/'
        count = 0
        
        for path, entry in self.container.get('entries', {}).items():
            if path.startswith(prefix) and entry.get('type') == 'file':
                file_uuid = entry.get('file_uuid')
                if file_uuid:
                    container_path = self.get_container_path(file_uuid)
                    try:
                        if os.path.exists(container_path):
                            os.remove(container_path)
                        count += 1
                    except Exception:
                        pass
        
        return count

    def delete_permanent_file(self):
        """
        Supprime définitivement fichier(s) du gestionnaire.
        - Fichier sélectionné: supprime juste ce fichier
        - Dossier sélectionné: supprime tous les fichiers du dossier récursivement
        - Envoie l'instruction de suppression aux pairs distants
        - Décrémente le compteur de chunks
        """
        sel = self.file_tree.selection()
        if not sel:
            messagebox.showinfo('Info', 'Sélectionnez un fichier ou un dossier')
            return
        
        item = self.file_tree.item(sel[0])
        name = item['text']
        is_dir = name.endswith('/')
        
        selected_path = os.path.join(self.cwd, name.rstrip('/')) if self.cwd else name.rstrip('/')
        selected_path = selected_path.replace('\\', '/')
        
        if not messagebox.askyesno('ATTENTION', 
            f'Supprimer définitivement {name}?\n\n'
            f'Cette action est irréversible!'):
            return
        
        try:
            chunking_mgr = getattr(self.app_gui, 'chunking_mgr', None)
            
            if is_dir:
                # Supprimer tous les fichiers du dossier
                count = self._delete_permanent_directory_recursive(selected_path, chunking_mgr)
                messagebox.showinfo('Succès', f'{count} fichier(s) supprimé(s) définitivement.')
            else:
                # Supprimer ce fichier
                file_uuid = self._file_uuids.get(selected_path)
                if file_uuid:
                    # Récupérer l'owner_uuid
                    owner_uuid = getattr(self.app_gui, 'peer_uuid', None)
                    
                    # Demander la suppression des chunks aux pairs distants
                    if chunking_mgr and owner_uuid:
                        self._delete_chunks_from_peers(file_uuid, owner_uuid, chunking_mgr)
                    
                    # Supprimer du container en mémoire
                    entries = self.container.setdefault('entries', {})
                    if selected_path in entries:
                        del entries[selected_path]
                    
                    # Supprimer container local
                    container_path = self.get_container_path(file_uuid)
                    if os.path.exists(container_path):
                        os.remove(container_path)
                    
                    # Supprimer de la BD
                    if chunking_mgr:
                        try:
                            chunking_mgr.db.delete_file_metadata(file_uuid)
                        except Exception:
                            pass
                    
                    messagebox.showinfo('Succès', 'Fichier supprimé définitivement.')
            
            self.refresh()
        except Exception as e:
            messagebox.showerror('Erreur', f'Echec suppression: {e}')

    def _delete_permanent_directory_recursive(self, dir_path: str, chunking_mgr) -> int:
        """Supprime définitivement tous les fichiers dans un dossier récursivement."""
        prefix = dir_path + '/'
        entries = self.container.setdefault('entries', {})
        count = 0
        to_delete = []
        owner_uuid = getattr(self.app_gui, 'peer_uuid', None)
        
        for path, entry in entries.items():
            if path.startswith(prefix):
                if entry.get('type') == 'file':
                    file_uuid = entry.get('file_uuid')
                    if file_uuid:
                        # Demander la suppression des chunks aux pairs distants
                        if chunking_mgr and owner_uuid:
                            self._delete_chunks_from_peers(file_uuid, owner_uuid, chunking_mgr)
                        
                        # Supprimer container
                        container_path = self.get_container_path(file_uuid)
                        try:
                            if os.path.exists(container_path):
                                os.remove(container_path)
                        except Exception:
                            pass
                        
                        # Supprimer de la BD
                        if chunking_mgr:
                            try:
                                chunking_mgr.db.delete_file_metadata(file_uuid)
                            except Exception:
                                pass
                        
                        count += 1
                
                to_delete.append(path)
        
        # Supprimer de l'arborescence
        for path in to_delete:
            if path in entries:
                del entries[path]
        
        return count

    def _delete_chunks_from_peers(self, file_uuid: str, owner_uuid: str, chunking_mgr) -> None:
        """Envoie l'instruction de suppression des chunks aux pairs distants."""
        try:
            # Récupérer toutes les localisations des chunks de ce fichier
            locations = chunking_mgr.db.get_locations_by_file(file_uuid, owner_uuid)
            
            if not locations:
                return
            
            # Compter le nombre total de chunks à supprimer
            total_chunks = len(locations)
            
            # Grouper les chunks par peer pour optimiser
            chunks_by_peer = {}
            for loc in locations:
                if loc.peer_uuid not in chunks_by_peer:
                    chunks_by_peer[loc.peer_uuid] = []
                chunks_by_peer[loc.peer_uuid].append(loc.chunk_idx)
            
            # Envoyer les demandes de suppression dans un thread séparé
            def delete_chunks_async():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    for peer_uuid, chunk_indices in chunks_by_peer.items():
                        for chunk_idx in chunk_indices:
                            try:
                                # Envoyer la demande de suppression
                                loop.run_until_complete(
                                    chunking_mgr.peer_rpc.delete_chunk(
                                        peer_uuid=peer_uuid,
                                        file_uuid=file_uuid,
                                        chunk_idx=chunk_idx,
                                        owner_uuid=owner_uuid
                                    )
                                )
                            except Exception as e:
                                # Log l'erreur mais continue avec les autres chunks
                                print(f"Erreur suppression chunk {chunk_idx} sur peer {peer_uuid}: {e}")
                    
                    # Décrémenter le compteur de chunks après suppression
                    chunking_mgr.db.decrement_foreign_chunks_counter(total_chunks)
                    
                finally:
                    loop.close()
            
            # Lancer la suppression dans un thread
            thread = threading.Thread(target=delete_chunks_async, daemon=True)
            thread.start()
            
        except Exception as e:
            print(f"Erreur lors de la suppression des chunks distants: {e}")

    def _run_async(self, coro):
        """Exécute une coroutine dans un thread séparé."""
        def runner():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(coro)
            finally:
                loop.close()

        threading.Thread(target=runner, daemon=True).start()

    def rebuild_container(self):
        """
        Rebuild fichier(s) sélectionné(s) depuis les chunks distribués.
        - Fichier sélectionné: rebuild juste ce fichier
        - Dossier sélectionné: rebuild tous les fichiers du dossier récursivement
        """
        sel = self.file_tree.selection()
        if not sel:
            messagebox.showinfo('Info', 'Sélectionnez un fichier ou un dossier')
            return

        item = self.file_tree.item(sel[0])
        name = item['text']
        
        # Construire le chemin logique sélectionné
        selected_path = os.path.join(self.cwd, name.rstrip('/')) if self.cwd else name.rstrip('/')
        selected_path = selected_path.replace('\\', '/')
        
        is_dir = name.endswith('/')
        
        chunking_mgr = getattr(self.app_gui, 'chunking_mgr', None)
        if not chunking_mgr:
            messagebox.showerror('Erreur', 'ChunkingManager non initialisé')
            return

        if is_dir:
            # Rebuild tous les fichiers dans ce dossier
            self._rebuild_directory_recursive(selected_path, chunking_mgr)
        else:
            # Rebuild juste ce fichier
            file_uuid = self._file_uuids.get(selected_path)
            if not file_uuid:
                messagebox.showerror('Erreur', f'UUID non trouvé pour {selected_path}')
                return
            
            self._rebuild_file(file_uuid, selected_path, chunking_mgr)

    def _rebuild_directory_recursive(self, dir_path: str, chunking_mgr):
        """Rebuild récursivement tous les fichiers dans un dossier."""
        prefix = dir_path + '/'
        files_to_rebuild = []
        
        # Trouver tous les fichiers dans ce dossier (récursivement)
        for path, entry in self.container.get('entries', {}).items():
            if path.startswith(prefix) and entry.get('type') == 'file':
                file_uuid = entry.get('file_uuid')
                if file_uuid:
                    files_to_rebuild.append((path, file_uuid))
        
        if not files_to_rebuild:
            messagebox.showinfo('Info', 'Aucun fichier à rebuilder dans ce dossier')
            return
        
        messagebox.showinfo('Rebuild', f'Rebuild de {len(files_to_rebuild)} fichier(s)...')
        
        async def do_rebuild_all():
            success_count = 0
            total_files = len(files_to_rebuild)
            for idx, (logical_path, file_uuid) in enumerate(files_to_rebuild, 1):
                try:
                    percent = int((idx - 1) / total_files * 100)
                    self._update_progress(logical_path, 'Rebuild', percent)
                    self.after(0, lambda p=logical_path: print(f"[Rebuild] Début: {p}"))
                    container_path = self.get_container_path(file_uuid)
                    await chunking_mgr.reconstruct_file(
                        file_uuid=file_uuid,
                        owner_uuid=None,
                        output_path=container_path
                    )
                    success_count += 1
                    self._update_progress(logical_path, 'Rebuild', 100)
                    self.after(0, lambda p=logical_path: print(f"[Rebuild] Succès: {p}"))
                except Exception as e:
                    print(f"[Rebuild] ERREUR {logical_path}: {e}")
                    self._update_progress(logical_path, 'Erreur', 0)
                    self.after(0, lambda p=logical_path, err=str(e): print(f"[Rebuild] Échec {p}: {err}"))
                    continue
            
            self.after(0, lambda: messagebox.showinfo('Succès', f'{success_count}/{len(files_to_rebuild)} fichier(s) rebuilds'))
            self.after(0, self.refresh)
        
        self._run_async(do_rebuild_all())

    def _rebuild_file(self, file_uuid: str, logical_path: str, chunking_mgr):
        """Rebuild un fichier unique."""
        container_path = self.get_container_path(file_uuid)
        messagebox.showinfo('Reconstruction', f'Reconstruction de {logical_path}...')

        async def do_rebuild():
            try:
                self._update_progress(logical_path, 'Rebuild', 0)
                await chunking_mgr.reconstruct_file(
                    file_uuid=file_uuid,
                    owner_uuid=None,  # Utiliser owner_uuid depuis métadonnées
                    output_path=container_path
                )
                self._update_progress(logical_path, 'Rebuild', 100)
                self.after(0, lambda: messagebox.showinfo(
                    'Succès', f'Fichier reconstruit:\n{container_path}'
                ))
                self.after(0, self.refresh)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror('Erreur', f'Echec reconstruction: {e}'))

        self._run_async(do_rebuild())

    def open_container_file(self):
        """Extrait et ouvre le fichier sélectionné avec l'application par défaut."""
        # Vérifier qu'un fichier est sélectionné
        sel = self.file_tree.selection()
        if not sel:
            messagebox.showinfo('Info', 'Sélectionnez un fichier à ouvrir')
            return
        
        item = self.file_tree.item(sel[0])
        name = item['text']
        
        if name.endswith('/'):
            messagebox.showinfo('Info', 'Sélectionnez un fichier, pas un dossier')
            return
        
        # Construire le chemin logique
        rel_name = name
        keypath = os.path.join(self.cwd, rel_name) if self.cwd else rel_name
        keypath = keypath.replace('\\', '/')
        
        # Récupérer le file_uuid
        file_uuid = self._file_uuids.get(keypath)
        if not file_uuid:
            messagebox.showerror('Erreur', 'Fichier introuvable dans l\'arborescence')
            return
        
        # Vérifier que le container existe
        container_path = self.get_container_path(file_uuid)
        if not os.path.exists(container_path):
            messagebox.showerror('Erreur', 'Conteneur indisponible. Reconstruisez-le d\'abord.')
            return
        
        try:
            # Déchiffrer le container
            settings = getattr(self.app_gui, 'encryption_settings', None) or {}
            key = settings.get('key')
            algo = settings.get('algorithm')
            if not key or not algo:
                messagebox.showerror('Erreur', 'Clé de chiffrement non configurée')
                return
            
            import crypto
            fd, tmp = tempfile.mkstemp(prefix='dec_', suffix='.json')
            os.close(fd)
            
            try:
                # Déchiffrer
                crypto.decrypt_file(container_path, tmp, key, algorithm=algo)
                
                # Lire le JSON
                with open(tmp, 'r', encoding='utf-8') as f:
                    container = json.load(f)
                
                # Extraire les données
                b64 = container.get('data', '')
                data = base64.b64decode(b64)
                original_filename = container.get('original_filename', rel_name)
                
                # Créer un dossier temporaire pour ce fichier
                temp_dir = tempfile.mkdtemp(prefix='decentralis_open_')
                temp_file = os.path.join(temp_dir, original_filename)
                
                with open(temp_file, 'wb') as f:
                    f.write(data)
                
                # Ouvrir le fichier avec l'application par défaut
                os.startfile(temp_file)
                
            finally:
                if tmp and os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except Exception:
                        pass
            
        except Exception as e:
            messagebox.showerror('Erreur', f"Impossible d'ouvrir le fichier: {e}")

