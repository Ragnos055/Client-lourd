import tkinter as tk
from tkinter import ttk, messagebox
import threading

from connection.connection import connection


class DecentralisGUI:
    def __init__(self, root):
        self.root = root
        root.title("Decentralis - Client")

        frm = ttk.Frame(root, padding=12)
        frm.grid(row=0, column=0, sticky='nsew')

        # Tracker inputs
        ttk.Label(frm, text="Tracker IP:").grid(row=0, column=0, sticky='e')
        self.srv_ip = tk.StringVar(value="10.0.0.30")
        ttk.Entry(frm, textvariable=self.srv_ip, width=18).grid(row=0, column=1, sticky='w')

        ttk.Label(frm, text="Tracker Port:").grid(row=0, column=2, sticky='e')
        self.srv_port = tk.IntVar(value=5000)
        ttk.Entry(frm, textvariable=self.srv_port, width=8).grid(row=0, column=3, sticky='w')

        # Peer inputs
        ttk.Label(frm, text="Pair IP:").grid(row=1, column=0, sticky='e')
        self.peer_ip = tk.StringVar(value="127.0.0.1")
        ttk.Entry(frm, textvariable=self.peer_ip, width=18).grid(row=1, column=1, sticky='w')

        ttk.Label(frm, text="Pair Port:").grid(row=1, column=2, sticky='e')
        self.peer_port = tk.IntVar(value=6000)
        ttk.Entry(frm, textvariable=self.peer_port, width=8).grid(row=1, column=3, sticky='w')

        # Keepalive
        ttk.Label(frm, text="Keepalive (s):").grid(row=2, column=0, sticky='e')
        self.keepalive = tk.IntVar(value=15)
        ttk.Entry(frm, textvariable=self.keepalive, width=8).grid(row=2, column=1, sticky='w')

        self.connect_btn = ttk.Button(frm, text="Connexion", command=self._on_connect_click)
        self.connect_btn.grid(row=2, column=2, columnspan=2)

        ttk.Label(frm, text="Pairs connus:").grid(row=3, column=0, sticky='w', pady=(10, 0))
        self.listbox = tk.Listbox(frm, height=12, width=60)
        self.listbox.grid(row=4, column=0, columnspan=4, pady=(4, 0))

        self.conn = None
        self._updating = False

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

        # Crée la connexion (non bloquante)
        try:
            # Connection peut lancer des opérations réseau — exécuter dans thread
            def create_conn():
                try:
                    self.conn = connection(srv_ip, srv_port, peer_ip, peer_port, keepalive)
                except Exception as e:
                    self.conn = None
                    self.root.after(0, lambda: messagebox.showerror("Erreur de connexion", str(e)))

            t = threading.Thread(target=create_conn, daemon=True)
            t.start()

        except Exception as e:
            messagebox.showerror("Erreur", str(e))
            return

        self.connect_btn.config(text="Déconnexion")
        self.connect_btn.config(command=self._on_connect_click)
        self._updating = True
        # démarrer boucle d'actualisation
        self.root.after(1000, self._update_peers)

    def _disconnect(self):
        # tente d'arrêter proprement la connexion
        try:
            if self.conn:
                # connection.close utilise stop_event global
                try:
                    self.conn.close()
                except Exception:
                    pass
                self.conn = None
        finally:
            self._updating = False
            self.listbox.delete(0, tk.END)
            self.connect_btn.config(text="Connexion")

    def _update_peers(self):
        if not self._updating:
            return
        try:
            if self.conn:
                resp = self.conn.get_peers()
                peers = resp.get('pairs', []) if isinstance(resp, dict) else []
            else:
                peers = []

            # Met à jour la listbox
            self.listbox.delete(0, tk.END)
            for p in peers:
                if isinstance(p, dict):
                    ip = p.get('ip')
                    port = p.get('port')
                    self.listbox.insert(tk.END, f"{ip}:{port}")
                else:
                    self.listbox.insert(tk.END, str(p))
        except Exception as e:
            # ne pas spammer l'utilisateur, on log seulement
            print("Erreur récupération pairs:", e)
        finally:
            # relancer après 2s
            self.root.after(2000, self._update_peers)


def run_gui():
    root = tk.Tk()
    DecentralisGUI(root)
    root.mainloop()


if __name__ == '__main__':
    run_gui()
