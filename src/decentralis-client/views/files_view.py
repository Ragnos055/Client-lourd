import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import os
import shutil
import json
import base64
import tempfile

import crypto
import p2p
import rs_codec


class FilesView(ttk.Frame):
    CONTAINER_NAME = 'container.dat'

    def __init__(self, parent, app_gui, **kwargs):
        super().__init__(parent, **kwargs)
        self.app_gui = app_gui
        self.cwd = ''  # virtual path inside container ('' = root)
        self.container = {'entries': {}}  # in-memory container structure

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

        # require active connection to tracker / peers
        conn = getattr(self.app_gui, 'conn', None)
        if not conn:
            messagebox.showerror('Erreur', 'Pas de connexion au tracker/pairs. Connectez-vous avant de téléverser.')
            return

        try:
            # récupérer la liste des pairs depuis le tracker
            resp = conn.get_peers()
            peers = resp.get('peers', []) if isinstance(resp, dict) else []
            # filtrer self
            filtered = []
            for pinfo in peers:
                if not isinstance(pinfo, dict):
                    continue
                ip = pinfo.get('ip')
                port = pinfo.get('port')
                if ip is None or port is None:
                    continue
                try:
                    if ip == conn.peer_ip and int(port) == int(conn.peer_port):
                        continue
                except Exception:
                    pass
                filtered.append({'ip': ip, 'port': int(port)})

            if not filtered:
                messagebox.showinfo('Info', 'Aucun pair disponible pour recevoir le fichier.')
                return

            # Chargement du fichier source en mémoire pour segmentation RS
            with open(path, 'rb') as f:
                data = f.read()

            total_shards = len(filtered)
            if total_shards < 2:
                # avec un seul pair, RS n'apporte rien : on chiffre et envoie comme avant
                pinfo = filtered[0]
                p2p.send_encrypted_file(pinfo['ip'], pinfo['port'], path, algo=algo, key_hex=key)
                messagebox.showinfo('Upload', 'Fichier chiffré envoyé au seul pair disponible (sans Reed-Solomon).')
                return

            # Choix simple: on garde  total_shards-1  shards de données et 1 shard de parité
            data_shards = total_shards - 1
            try:
                shards, pad_len = rs_codec.encode_to_shards(data, data_shards=data_shards, total_shards=total_shards)
            except Exception as e:
                messagebox.showerror('Erreur', f'Echec encodage Reed-Solomon: {e}')
                return

            file_id = secrets.token_hex(16)
            sent = 0
            errors = 0

            for idx, pinfo in enumerate(filtered):
                shard_bytes = shards[idx]
                # écrire shard dans un fichier temporaire, le chiffrer, puis l'envoyer
                fd_plain, tmp_plain = tempfile.mkstemp(prefix='rs_shard_', suffix='.bin')
                os.close(fd_plain)
                try:
                    with open(tmp_plain, 'wb') as f:
                        f.write(shard_bytes)

                    fd_cipher, tmp_cipher = tempfile.mkstemp(prefix='rs_cipher_', suffix='.bin')
                    os.close(fd_cipher)
                    try:
                        crypto.encrypt_file(tmp_plain, tmp_cipher, key, algorithm=algo)
                        header = {
                            "name": secrets.token_hex(16),
                            "algo": algo,
                            "v": 2,
                            "rs": {
                                "file_id": file_id,
                                "index": idx,
                                "data_shards": data_shards,
                                "total_shards": total_shards,
                                "pad_len": pad_len,
                            },
                        }
                        p2p._send_cipherfile(pinfo['ip'], pinfo['port'], tmp_cipher, header)
                        sent += 1
                    finally:
                        try:
                            os.remove(tmp_cipher)
                        except Exception:
                            pass
                except Exception:
                    errors += 1
                finally:
                    try:
                        os.remove(tmp_plain)
                    except Exception:
                        pass

            if sent > 0:
                messagebox.showinfo('Upload', f'Fichier segmenté (Reed-Solomon) et chiffré envoyé à {sent} pair(s). Erreurs sur {errors} pair(s).')
            else:
                messagebox.showerror('Upload', 'Échec de l’envoi de tous les fragments.')
        except Exception as e:
            messagebox.showerror('Erreur', f'Echec upload vers pairs: {e}')

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

