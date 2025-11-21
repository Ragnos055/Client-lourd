import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import secrets
import os
import shutil

import keystore


class EncryptionView(ttk.Frame):
    def __init__(self, parent, app_gui, **kwargs):
        super().__init__(parent, **kwargs)
        self.app_gui = app_gui

        ttk.Label(self, text='Paramètres de chiffrement', font=('TkDefaultFont', 11, 'bold')).grid(row=0, column=0, columnspan=2, pady=(0,8))

        ttk.Label(self, text='Algorithme:').grid(row=1, column=0, sticky='e')
        self.algo_var = tk.StringVar(value='AES-256')
        ttk.Combobox(self, textvariable=self.algo_var, values=['AES-256', 'ChaCha20'], state='readonly').grid(row=1, column=1, sticky='w')

        ttk.Label(self, text='Passphrase:').grid(row=2, column=0, sticky='e')
        self.passphrase_var = tk.StringVar()
        self.pass_entry = ttk.Entry(self, textvariable=self.passphrase_var, width=32, show='*')
        self.pass_entry.grid(row=2, column=1, sticky='w')

        self.apply_btn = ttk.Button(self, text='Appliquer passphrase', command=self.apply_passphrase)
        self.apply_btn.grid(row=3, column=0)
        ttk.Button(self, text='Générer fichier rétention', command=self.create_retention).grid(row=3, column=1)
        ttk.Button(self, text='Importer fichier rétention', command=self.import_retention).grid(row=4, column=0)
        ttk.Button(self, text='Exporter fichier rétention', command=self.export_retention).grid(row=4, column=1)

        # controls to clear cached passphrase and display status
        self.clear_btn = ttk.Button(self, text='Oublier passphrase', command=self.clear_cached_passphrase)
        self.clear_btn.grid(row=5, column=0)
        self.status_var = tk.StringVar(value='')
        ttk.Label(self, textvariable=self.status_var).grid(row=5, column=1, sticky='w')

        # If a passphrase is already cached by the GUI (from startup), reflect that
        cached = getattr(self.app_gui, '_cached_passphrase', None)
        if cached:
            self.status_var.set('Passphrase appliquée (en mémoire)')
            try:
                self.pass_entry.state(['disabled'])
            except Exception:
                self.pass_entry.configure(state='disabled')
            try:
                self.apply_btn.state(['disabled'])
            except Exception:
                self.apply_btn.configure(state='disabled')
        else:
            try:
                self.clear_btn.state(['disabled'])
            except Exception:
                self.clear_btn.configure(state='disabled')

    def _generate_key(self):
        key = secrets.token_hex(32)
        # set into app settings
        self.passphrase_var.set('')
        self.app_gui.encryption_settings = {'algorithm': 'AES-256', 'key': key}
        messagebox.showinfo('Généré', 'Clé générée et appliquée en mémoire')

    def _save_encryption_settings(self):
        settings = {
            'algorithm': self.algo_var.get(),
            'key': self.key_var.get()
        }
        # delegate saving to app_gui (or store locally)
        try:
            self.app_gui.encryption_settings = settings
            messagebox.showinfo('Saved', 'Paramètres de chiffrement sauvegardés')
        except Exception as e:
            messagebox.showerror('Erreur', f'Echec sauvegarde: {e}')

    def create_retention(self):
        # Ask passphrase twice
        p1 = simpledialog.askstring('Passphrase', 'Entrez la passphrase:', show='*')
        if not p1:
            return
        p2 = simpledialog.askstring('Confirmer', 'Confirmez la passphrase:', show='*')
        if p1 != p2:
            messagebox.showerror('Erreur', 'Passphrases différentes')
            return

        path = os.path.join(self.app_gui.config_dir, 'key.json')
        try:
            keystore.generate_retention_file(path, p1, iterations=200000, algorithm=self.algo_var.get())
            messagebox.showinfo('Succès', f'Fichier de rétention créé: {path}')
        except Exception as e:
            messagebox.showerror('Erreur', f'Echec création: {e}')

    def import_retention(self):
        src = filedialog.askopenfilename(title='Importer fichier rétention')
        if not src:
            return
        dst = os.path.join(self.app_gui.config_dir, 'key.json')
        try:
            shutil.copyfile(src, dst)
            messagebox.showinfo('Succès', f'Fichier importé: {dst}')
        except Exception as e:
            messagebox.showerror('Erreur', f'Echec import: {e}')

    def export_retention(self):
        src = os.path.join(self.app_gui.config_dir, 'key.json')
        if not os.path.exists(src):
            messagebox.showerror('Erreur', 'Aucun fichier de rétention à exporter')
            return
        dst = filedialog.asksaveasfilename(defaultextension='.json', title='Exporter fichier rétention', initialfile='key.json')
        if not dst:
            return
        try:
            keystore.export_retention(src, dst)
            messagebox.showinfo('Succès', f'Fichier exporté: {dst}')
        except Exception as e:
            messagebox.showerror('Erreur', f'Echec export: {e}')

    def apply_passphrase(self):
        p = self.passphrase_var.get()
        if not p:
            p = simpledialog.askstring('Passphrase', 'Entrez la passphrase:', show='*')
        if not p:
            return
        path = os.path.join(self.app_gui.config_dir, 'key.json')
        if not os.path.exists(path):
            messagebox.showerror('Erreur', 'Aucun fichier de rétention trouvé, créez ou importez-en un first')
            return
        try:
            keyhex = keystore.verify_passphrase_and_get_keyhex(path, p)
            data = keystore.load_retention(path)
            self.app_gui.encryption_settings = {'algorithm': data.get('algorithm', 'AES-256'), 'key': keyhex}
            # cache passphrase
            self.app_gui._cached_passphrase = p
            messagebox.showinfo('Succès', 'Passphrase appliquée en mémoire')
            # update UI state
            self.status_var.set('Passphrase appliquée (en mémoire)')
            try:
                self.pass_entry.state(['disabled'])
            except Exception:
                self.pass_entry.configure(state='disabled')
            try:
                self.apply_btn.state(['disabled'])
            except Exception:
                self.apply_btn.configure(state='disabled')
            try:
                self.clear_btn.state(['!disabled'])
            except Exception:
                self.clear_btn.configure(state='normal')
        except Exception as e:
            messagebox.showerror('Erreur', f'Passphrase invalide: {e}')

    def _generate_key(self):
        key = secrets.token_hex(32)
        self.key_var.set(key)

    def _save_encryption_settings(self):
        settings = {
            'algorithm': self.algo_var.get(),
            'key': getattr(self.app_gui, 'encryption_settings', {}).get('key')
        }
        try:
            self.app_gui.encryption_settings = settings
            messagebox.showinfo('Saved', 'Paramètres de chiffrement sauvegardés')
        except Exception as e:
            messagebox.showerror('Erreur', f'Echec sauvegarde: {e}')

    def clear_cached_passphrase(self):
        if hasattr(self.app_gui, '_cached_passphrase'):
            delattr(self.app_gui, '_cached_passphrase')
        self.app_gui.encryption_settings = {}
        self.status_var.set('Passphrase oubliée')
        try:
            self.pass_entry.state(['!disabled'])
        except Exception:
            self.pass_entry.configure(state='normal')
        try:
            self.apply_btn.state(['!disabled'])
        except Exception:
            self.apply_btn.configure(state='normal')
        try:
            self.clear_btn.state(['disabled'])
        except Exception:
            self.clear_btn.configure(state='disabled')
