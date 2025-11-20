import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import os
import shutil


class FilesView(ttk.Frame):
    def __init__(self, parent, app_gui, **kwargs):
        super().__init__(parent, **kwargs)
        self.app_gui = app_gui
        self.cwd = ''  # relative to storage_dir

        # toolbar
        toolbar = ttk.Frame(self)
        toolbar.pack(fill='x', pady=(0,4))
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

        self.refresh()

    def storage_path(self, *parts):
        base = self.app_gui.storage_dir
        if self.cwd:
            base = os.path.join(base, self.cwd)
        return os.path.join(base, *parts) if parts else base

    def refresh(self):
        try:
            storage = self.storage_path()
            if not os.path.isdir(storage):
                os.makedirs(storage, exist_ok=True)
            entries = sorted(os.listdir(storage), key=lambda s: (not os.path.isdir(os.path.join(storage, s)), s.lower()))
            self.listbox.delete(0, tk.END)
            for e in entries:
                p = os.path.join(storage, e)
                display = e + ('/' if os.path.isdir(p) else '')
                self.listbox.insert(tk.END, display)
            # update path label
            rel = '/' + self.cwd if self.cwd else '/'
            self.path_var.set(f'Storage: {rel}')
        except Exception as e:
            messagebox.showerror('Erreur', f'Impossible de lister le répertoire: {e}')

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
            self.refresh()

    def new_folder(self):
        name = simpledialog.askstring('Nouveau dossier', 'Nom du dossier:')
        if not name:
            return
        target = self.storage_path(name)
        try:
            os.makedirs(target, exist_ok=False)
            self.refresh()
        except FileExistsError:
            messagebox.showerror('Erreur', 'Le dossier existe déjà')
        except Exception as e:
            messagebox.showerror('Erreur', f'Echec création dossier: {e}')

    def upload_file(self):
        path = filedialog.askopenfilename()
        if not path:
            return
        try:
            dst = self.storage_path(os.path.basename(path))
            shutil.copy2(path, dst)
            self.refresh()
            messagebox.showinfo('Upload', 'Fichier copié dans le stockage local')
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
        src = self.storage_path(name)
        dst_dir = filedialog.askdirectory()
        if not dst_dir:
            return
        try:
            shutil.copy2(src, os.path.join(dst_dir, os.path.basename(src)))
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
        path = self.storage_path(name)
        if not messagebox.askyesno('Confirmer', f'Supprimer {name}?'):
            return
        try:
            if is_dir:
                shutil.rmtree(path)
            else:
                os.remove(path)
            self.refresh()
        except Exception as e:
            messagebox.showerror('Erreur', f'Echec suppression: {e}')

