import tkinter as tk
from tkinter import ttk, messagebox
import secrets


class EncryptionView(ttk.Frame):
    def __init__(self, parent, app_gui, **kwargs):
        super().__init__(parent, **kwargs)
        self.app_gui = app_gui

        ttk.Label(self, text='Paramètres de chiffrement', font=('TkDefaultFont', 11, 'bold')).grid(row=0, column=0, columnspan=2, pady=(0,8))

        ttk.Label(self, text='Algorithme:').grid(row=1, column=0, sticky='e')
        self.algo_var = tk.StringVar(value='AES-256')
        ttk.Combobox(self, textvariable=self.algo_var, values=['AES-256', 'ChaCha20'], state='readonly').grid(row=1, column=1, sticky='w')

        ttk.Label(self, text='Clé (hex):').grid(row=2, column=0, sticky='e')
        self.key_var = tk.StringVar()
        ttk.Entry(self, textvariable=self.key_var, width=48).grid(row=2, column=1, sticky='w')

        ttk.Button(self, text='Générer clé', command=self._generate_key).grid(row=3, column=0)
        ttk.Button(self, text='Sauvegarder', command=self._save_encryption_settings).grid(row=3, column=1)

    def _generate_key(self):
        key = secrets.token_hex(32)
        self.key_var.set(key)

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
