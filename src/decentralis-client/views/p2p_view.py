"""
Vue P2P pour la gestion des fichiers distribués sur le réseau.

Cette vue permet de :
- Voir les fichiers locaux chunkés
- Distribuer des fichiers vers les peers
- Récupérer des fichiers depuis le réseau
- Voir l'état des chunks et de la réplication
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import asyncio
import os
from datetime import datetime
from typing import Optional, Dict, Any


class P2PView(ttk.Frame):
    """
    Vue de gestion des fichiers distribués P2P.
    
    Cette vue permet de chunker des fichiers, les distribuer
    sur le réseau, et récupérer des fichiers depuis les peers.
    """
    
    def __init__(self, parent, app_gui, **kwargs):
        super().__init__(parent, **kwargs)
        self.app_gui = app_gui
        
        # Frame principal avec deux colonnes
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        
        # === Section gauche: Fichiers locaux ===
        left_frame = ttk.LabelFrame(self, text="Fichiers locaux (chunkés)", padding=5)
        left_frame.grid(row=0, column=0, rowspan=2, sticky='nsew', padx=(0, 5), pady=5)
        left_frame.columnconfigure(0, weight=1)
        left_frame.rowconfigure(1, weight=1)
        
        # Toolbar gauche
        left_toolbar = ttk.Frame(left_frame)
        left_toolbar.grid(row=0, column=0, sticky='ew', pady=(0, 5))
        
        ttk.Button(left_toolbar, text="📁 Chunker fichier", 
                   command=self._chunk_file).pack(side='left', padx=2)
        ttk.Button(left_toolbar, text="🔄 Rafraîchir", 
                   command=self._refresh_local).pack(side='left', padx=2)
        ttk.Button(left_toolbar, text="🗑️ Supprimer", 
                   command=self._delete_local).pack(side='left', padx=2)
        
        # Liste des fichiers locaux
        self.local_tree = ttk.Treeview(
            left_frame,
            columns=('size', 'local', 'distributed', 'check', 'status'),
            show='headings', height=12
        )
        self.local_tree.heading('size', text='Taille')
        self.local_tree.heading('local', text='Local')
        self.local_tree.heading('distributed', text='Distribué')
        self.local_tree.heading('check', text='Check')
        self.local_tree.heading('status', text='État')
        self.local_tree.column('size', width=70)
        self.local_tree.column('local', width=60)
        self.local_tree.column('distributed', width=70)
        self.local_tree.column('check', width=70)
        self.local_tree.column('status', width=90)
        self.local_tree.grid(row=1, column=0, sticky='nsew')
        
        # Scrollbar pour la liste
        local_scroll = ttk.Scrollbar(left_frame, orient='vertical', 
                                      command=self.local_tree.yview)
        local_scroll.grid(row=1, column=1, sticky='ns')
        self.local_tree.configure(yscrollcommand=local_scroll.set)
        
        # Double-clic pour voir les détails
        self.local_tree.bind('<Double-1>', self._show_file_details)
        
        # === Section droite: Actions et Distribution ===
        right_frame = ttk.Frame(self)
        right_frame.grid(row=0, column=1, rowspan=2, sticky='nsew', pady=5)
        right_frame.columnconfigure(0, weight=1)
        right_frame.rowconfigure(2, weight=1)
        
        # Actions de distribution
        dist_frame = ttk.LabelFrame(right_frame, text="Distribution P2P", padding=5)
        dist_frame.grid(row=0, column=0, sticky='ew', pady=(0, 5))
        
        ttk.Button(dist_frame, text="📤 Distribuer sélection", 
                   command=self._distribute_file).pack(fill='x', pady=2)
        ttk.Button(dist_frame, text="📥 Récupérer fichier", 
                   command=self._fetch_file).pack(fill='x', pady=2)
        ttk.Button(dist_frame, text="🔍 Rechercher fichier", 
                   command=self._search_file).pack(fill='x', pady=2)
        
        # État du réseau
        net_frame = ttk.LabelFrame(right_frame, text="État du réseau", padding=5)
        net_frame.grid(row=1, column=0, sticky='ew', pady=5)
        
        self.peers_count_var = tk.StringVar(value="Peers: 0")
        ttk.Label(net_frame, textvariable=self.peers_count_var).pack(anchor='w')
        
        self.server_status_var = tk.StringVar(value="Serveur: Non démarré")
        ttk.Label(net_frame, textvariable=self.server_status_var).pack(anchor='w')
        
        self.chunks_stored_var = tk.StringVar(value="Chunks stockés: 0")
        ttk.Label(net_frame, textvariable=self.chunks_stored_var).pack(anchor='w')

        self.foreign_chunks_var = tk.StringVar(value="Chunks étrangers hébergés: 0")
        ttk.Label(net_frame, textvariable=self.foreign_chunks_var).pack(anchor='w')
        
        ttk.Button(net_frame, text="▶️ Démarrer serveur P2P", 
                   command=self._toggle_server).pack(fill='x', pady=(5, 0))
        
        # Log des opérations
        log_frame = ttk.LabelFrame(right_frame, text="Journal", padding=5)
        log_frame.grid(row=2, column=0, sticky='nsew')
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        
        self.log_text = tk.Text(log_frame, height=10, width=40, state='disabled')
        self.log_text.grid(row=0, column=0, sticky='nsew')
        
        log_scroll = ttk.Scrollbar(log_frame, orient='vertical', 
                                    command=self.log_text.yview)
        log_scroll.grid(row=0, column=1, sticky='ns')
        self.log_text.configure(yscrollcommand=log_scroll.set)
        
        # État interne
        self._server_running = False
        self._async_loop = None
        self._local_files = {}  # file_uuid -> metadata
        
        # Rafraîchir à l'initialisation
        self.after(500, self._refresh_local)
    
    def _log(self, message: str):
        """Ajoute un message au journal."""
        self.log_text.configure(state='normal')
        timestamp = datetime.now().strftime('%H:%M:%S')
        self.log_text.insert('end', f"[{timestamp}] {message}\n")
        self.log_text.see('end')
        self.log_text.configure(state='disabled')
    
    def _get_chunking_mgr(self):
        """Récupère le ChunkingManager depuis l'app principale."""
        return getattr(self.app_gui, 'chunking_mgr', None)
    
    def _run_async(self, coro):
        """Exécute une coroutine dans un thread séparé avec une boucle dédiée."""
        def run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                # Exécuter la coroutine
                loop.run_until_complete(coro)
                
                # Après la coroutine, laisser la boucle tourner pour les tâches background
                mgr = self._get_chunking_mgr()
                if mgr and hasattr(mgr, 'network_server') and mgr.network_server and mgr.network_server._running:
                    # Lancer une tâche pour garder la boucle active
                    async def keep_alive():
                        while mgr.network_server._running:
                            await asyncio.sleep(0.1)
                    
                    loop.run_until_complete(keep_alive())
            finally:
                loop.close()
        
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread
    
    def _refresh_local(self):
        """Rafraîchit la liste des fichiers locaux chunkés."""
        mgr = self._get_chunking_mgr()
        if not mgr:
            self._log("ChunkingManager non initialisé")
            return

        try:
            # Récupérer tous les fichiers de la base
            files = mgr.db.get_all_file_metadata()

            # Vider la liste
            for item in self.local_tree.get_children():
                self.local_tree.delete(item)

            self._local_files = {}

            for file_meta in files:
                if isinstance(file_meta, dict):
                    file_uuid = file_meta.get('file_uuid', '')
                    filename = file_meta.get('original_filename', 'unknown')
                    size = file_meta.get('original_size', 0)
                    total_chunks = file_meta.get('total_chunks', 0)
                    owner_uuid = file_meta.get('owner_uuid', mgr.peer_uuid)
                else:
                    file_uuid = file_meta.file_uuid
                    filename = file_meta.original_filename
                    size = file_meta.original_size
                    total_chunks = file_meta.total_chunks
                    owner_uuid = file_meta.owner_uuid

                # Compter les chunks locaux présents sur disque
                local_chunks = len(mgr.store.list_chunks(owner_uuid, file_uuid))

                # Compter les chunks distribués (confirmés)
                try:
                    locations = mgr.db.get_locations_by_file(file_uuid, owner_uuid)
                    distributed_chunks = len([
                        loc for loc in locations
                        if loc.status == 'confirmed'
                    ])
                except Exception:
                    distributed_chunks = 0

                # Formater la taille
                if size > 1024 * 1024:
                    size_str = f"{size / (1024*1024):.1f} MB"
                elif size > 1024:
                    size_str = f"{size / 1024:.1f} KB"
                else:
                    size_str = f"{size} B"

                # Déterminer le statut
                if local_chunks == 0 and distributed_chunks > 0:
                    status = "Distant"
                elif local_chunks == total_chunks:
                    status = "Local"
                elif distributed_chunks > 0:
                    status = "Partiel"
                else:
                    status = "En attente"

                # Indicateur check: local présent ou non
                check_str = "Local" if local_chunks > 0 else "Distance"

                # Afficher local/total et distribué/total
                local_str = f"{local_chunks}/{total_chunks}"
                dist_str = f"{distributed_chunks}/{total_chunks}"

                self.local_tree.insert(
                    '', 'end', iid=file_uuid,
                    values=(size_str, local_str, dist_str, check_str, status),
                    text=filename
                )
                self._local_files[file_uuid] = file_meta

            # Mettre à jour le nombre de fichiers dans le titre
            self._log(f"Rafraîchi: {len(files)} fichier(s) chunké(s)")

            # Mettre à jour les stats
            self._update_stats()

        except Exception as e:
            self._log(f"Erreur rafraîchissement: {e}")
    
    def _update_stats(self):
        """Met à jour les statistiques affichées."""
        mgr = self._get_chunking_mgr()
        if not mgr:
            return
        
        try:
            # Nombre de chunks stockés localement
            stats = mgr.db.get_local_stats() if hasattr(mgr.db, 'get_local_stats') else {}
            chunks_count = stats.get('chunks_count', 0)
            self.chunks_stored_var.set(f"Chunks stockés: {chunks_count}")

            # Nombre de chunks hébergés pour d'autres owners
            try:
                foreign = mgr.db.get_foreign_chunks_stats(mgr.peer_uuid)
                foreign_count = foreign.get('count', 0)
                self.logger = mgr.logger
                self.logger.info(f"Stats chunks: total={chunks_count}, peer_uuid={mgr.peer_uuid[:16]}, foreign={foreign_count}")
            except Exception as e:
                foreign_count = 0
                self.logger.error(f"Erreur foreign chunks: {e}")
            self.foreign_chunks_var.set(f"Chunks étrangers hébergés: {foreign_count}")
            
            # Nombre de peers (si connexion active)
            if self.app_gui.conn:
                try:
                    resp = self.app_gui.conn.get_peers()
                    peers = resp.get('peers', []) if isinstance(resp, dict) else []
                    self.peers_count_var.set(f"Peers: {len(peers)}")
                except:
                    self.peers_count_var.set("Peers: ?")
            else:
                self.peers_count_var.set("Peers: Non connecté")
                
        except Exception as e:
            self._log(f"Erreur stats: {e}")
    
    def _chunk_file(self):
        """Ouvre un fichier et le découpe en chunks."""
        mgr = self._get_chunking_mgr()
        if not mgr:
            messagebox.showerror("Erreur", "ChunkingManager non initialisé")
            return

        # Sélectionner un fichier
        path = filedialog.askopenfilename(title="Sélectionner un fichier à chunker")
        if not path:
            return

        # Demander si on doit supprimer le fichier source après le chunking
        delete_source = messagebox.askyesno(
            "Supprimer le fichier source?",
            f"Voulez-vous supprimer le fichier original après le chunking?\n\n"
            f"Fichier: {os.path.basename(path)}\n\n"
            f"Si vous répondez 'Oui', le fichier sera supprimé après avoir été "
            f"découpé en chunks. Vous pourrez toujours le récupérer depuis les chunks."
        )

        self._log(f"Chunking: {os.path.basename(path)}...")
        if delete_source:
            self._log("  → Le fichier source sera supprimé après le chunking")

        async def do_chunk():
            try:
                # Utiliser l'UUID du peer comme owner
                owner_uuid = mgr.peer_uuid
                file_uuid = await mgr.chunk_file(
                    path, owner_uuid, delete_source_after=delete_source
                )
                self.after(0, lambda: self._log(f"✓ Chunké: {file_uuid[:8]}..."))
                if delete_source:
                    self.after(0, lambda: self._log("  → Fichier source supprimé"))
                self.after(0, self._refresh_local)
            except Exception as e:
                self.after(0, lambda: self._log(f"✗ Erreur: {e}"))
                self.after(0, lambda: messagebox.showerror("Erreur", f"Echec chunking: {e}"))

        self._run_async(do_chunk())
    
    def _distribute_file(self):
        """Distribue le fichier sélectionné vers les peers."""
        selection = self.local_tree.selection()
        if not selection:
            messagebox.showinfo("Info", "Sélectionnez un fichier à distribuer")
            return

        file_uuid = selection[0]
        mgr = self._get_chunking_mgr()
        if not mgr:
            messagebox.showerror("Erreur", "ChunkingManager non initialisé")
            return

        if not self.app_gui.conn:
            messagebox.showerror("Erreur", "Non connecté au tracker. Connectez-vous d'abord.")
            return

        self._log(f"Distribution: {file_uuid[:8]}...")
        self._log("  → Les chunks locaux seront supprimés après confirmation")

        async def do_distribute():
            try:
                owner_uuid = mgr.peer_uuid
                self.after(0, lambda: self._log(f"  Owner UUID: {owner_uuid[:8]}..."))

                # Vérifier les peers disponibles
                peers = await mgr._get_available_peers(exclude_self=True)
                self.after(0, lambda: self._log(f"  Peers disponibles: {len(peers)}"))
                for p in peers:
                    self.after(0, lambda p=p: self._log(f"    - {p.get('uuid')[:16]}... ({p.get('ip')}:{p.get('port')})"))

                if not peers:
                    self.after(0, lambda: self._log("  ⚠ Aucun peer disponible!"))
                    self.after(0, lambda: self._log("  Assurez-vous que:"))
                    self.after(0, lambda: self._log("    1. L'autre client est connecté au tracker"))
                    self.after(0, lambda: self._log("    2. L'autre client a démarré son serveur P2P"))
                    return

                self.after(0, lambda: self._log("  Début de la distribution..."))

                # distribute_chunks supprime automatiquement les chunks locaux
                # après confirmation par le peer distant
                result = await mgr.distribute_chunks(
                    file_uuid, owner_uuid,
                    delete_local_after_confirm=True
                )

                self.after(0, lambda: self._log("  Distribution terminée, traitement du résultat..."))

                distributed = result.get('distributed', 0)
                failed = result.get('failed', 0)
                total = result.get('total_chunks', 0)
                local_deleted = result.get('local_deleted', 0)
                error = result.get('error', '')
                assignments = result.get('assignments', [])

                # Gestion des erreurs spécifiques
                if error == 'no_local_chunks':
                    self.after(0, lambda: self._log("⚠ Aucun chunk local trouvé - déjà distribués?"))
                    self.after(0, lambda: messagebox.showwarning(
                        "Distribution impossible",
                        "Aucun chunk local trouvé pour ce fichier.\n\n"
                        "Les chunks ont probablement déjà été distribués.\n"
                        "Utilisez 'Récupérer fichier' pour le reconstruire."
                    ))
                    self.after(0, self._refresh_local)
                    return
                elif error == 'distribution_in_progress':
                    self.after(0, lambda: self._log("⚠ Distribution déjà en cours"))
                    self.after(0, lambda: messagebox.showinfo(
                        "Distribution en cours",
                        "Une distribution est déjà en cours pour ce fichier."
                    ))
                    return

                msg = f"Distribution: {distributed}/{total} chunks envoyés"
                if local_deleted > 0:
                    msg += f", {local_deleted} locaux supprimés"
                if failed > 0:
                    msg += f", {failed} échecs"
                if error and error not in ['no_local_chunks', 'distribution_in_progress']:
                    msg += f" ({error})"

                self.after(0, lambda: self._log(f"✓ {msg}"))
                
                # Si des échecs, afficher les détails
                if failed > 0 and assignments:
                    self.after(0, lambda: self._log("  Détails des échecs:"))
                    for assign in assignments:
                        if assign.get('status') == 'failed':
                            chunk_idx = assign.get('chunk_idx', '?')
                            peer_uuid = assign.get('peer_uuid', 'unknown')
                            if peer_uuid != 'unknown':
                                peer_uuid = peer_uuid[:16] + '...'
                            error_msg = assign.get('error_message', 'Unknown error')
                            self.after(0, lambda cidx=chunk_idx, puuid=peer_uuid, err=error_msg: 
                                      self._log(f"    Chunk {cidx} -> {puuid}: {err}"))
                
                self.after(0, self._refresh_local)
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                self.after(0, lambda: self._log(f"✗ Erreur distribution: {e}"))
                lines = tb.split('\n')
                for line in lines[-5:]:
                    if line.strip():
                        self.after(0, lambda l=line: self._log(f"  {l}"))

        self._run_async(do_distribute())
    
    def _fetch_file(self):
        """Récupère un fichier depuis le réseau."""
        from tkinter import simpledialog
        
        file_uuid = simpledialog.askstring("Récupérer fichier", 
                                            "UUID du fichier à récupérer:")
        if not file_uuid:
            return
        
        mgr = self._get_chunking_mgr()
        if not mgr:
            messagebox.showerror("Erreur", "ChunkingManager non initialisé")
            return
        
        # Sélectionner le dossier de destination
        dst_dir = filedialog.askdirectory(title="Dossier de destination")
        if not dst_dir:
            return
        
        self._log(f"Récupération: {file_uuid[:8]}...")
        
        async def do_fetch():
            try:
                # Récupérer les métadonnées
                metadata = mgr.db.get_file_metadata(file_uuid)
                if not metadata:
                    self.after(0, lambda: messagebox.showerror("Erreur", "Fichier non trouvé"))
                    return
                
                filename = metadata.original_filename if hasattr(metadata, 'original_filename') else metadata.get('original_filename', 'recovered.dat')
                output_path = os.path.join(dst_dir, filename)
                
                await mgr.reconstruct_file(file_uuid, None, output_path)
                
                self.after(0, lambda: self._log(f"✓ Récupéré: {filename}"))
                self.after(0, lambda: messagebox.showinfo("Succès", f"Fichier récupéré:\n{output_path}"))
            except Exception as e:
                self.after(0, lambda: self._log(f"✗ Erreur récupération: {e}"))
                self.after(0, lambda: messagebox.showerror("Erreur", f"Echec récupération: {e}"))
        
        self._run_async(do_fetch())
    
    def _search_file(self):
        """Recherche un fichier sur le réseau."""
        from tkinter import simpledialog
        
        query = simpledialog.askstring("Rechercher", "Nom du fichier à rechercher:")
        if not query:
            return
        
        self._log(f"Recherche: {query}...")
        # TODO: Implémenter la recherche via peer_rpc
        self._log("Recherche non implémentée (nécessite serveur P2P)")
    
    def _delete_local(self):
        """Supprime un fichier chunké local."""
        selection = self.local_tree.selection()
        if not selection:
            messagebox.showinfo("Info", "Sélectionnez un fichier à supprimer")
            return
        
        file_uuid = selection[0]
        
        if not messagebox.askyesno("Confirmer", 
                                    f"Supprimer le fichier chunké {file_uuid[:8]}... ?\n"
                                    "Cette action supprimera tous les chunks locaux."):
            return
        
        mgr = self._get_chunking_mgr()
        if not mgr:
            messagebox.showerror("Erreur", "ChunkingManager non initialisé")
            return
        
        try:
            # Récupérer le owner_uuid
            metadata = mgr.db.get_file_metadata(file_uuid)
            if metadata:
                owner_uuid = metadata.owner_uuid if hasattr(metadata, 'owner_uuid') else metadata.get('owner_uuid', mgr.peer_uuid)
            else:
                owner_uuid = mgr.peer_uuid
            
            # Supprimer les chunks du disque
            mgr.store.delete_file_chunks(owner_uuid, file_uuid)
            
            # Supprimer de la base de données
            mgr.db.delete_file_metadata(file_uuid)
            
            self._log(f"✓ Supprimé: {file_uuid[:8]}...")
            self._refresh_local()
            
        except Exception as e:
            self._log(f"✗ Erreur suppression: {e}")
            messagebox.showerror("Erreur", f"Echec suppression: {e}")
    
    def _show_file_details(self, event):
        """Affiche les détails d'un fichier."""
        selection = self.local_tree.selection()
        if not selection:
            return
        
        file_uuid = selection[0]
        mgr = self._get_chunking_mgr()
        if not mgr:
            return
        
        try:
            metadata = mgr.db.get_file_metadata(file_uuid)
            if not metadata:
                return
            
            # Construire le message de détails
            if hasattr(metadata, 'original_filename'):
                details = f"""Fichier: {metadata.original_filename}
UUID: {file_uuid}
Taille originale: {metadata.original_size} bytes
Hash SHA-256: {metadata.original_hash[:32]}...
Chunks: {metadata.data_chunks} data + {metadata.parity_chunks} parité
Algorithme: {metadata.algorithm}
Créé le: {metadata.created_at}
Expire le: {metadata.expires_at}"""
            else:
                details = f"""UUID: {file_uuid}
Fichier: {metadata.get('original_filename', 'N/A')}
Taille: {metadata.get('original_size', 0)} bytes"""
            
            messagebox.showinfo("Détails du fichier", details)
            
        except Exception as e:
            self._log(f"Erreur détails: {e}")
    
    def _toggle_server(self):
        """Démarre ou arrête le serveur P2P."""
        mgr = self._get_chunking_mgr()
        if not mgr:
            messagebox.showerror("Erreur", "ChunkingManager non initialisé")
            return
        
        if self._server_running:
            self._stop_server()
        else:
            self._start_server()
    
    def _start_server(self):
        """Démarre le serveur P2P."""
        mgr = self._get_chunking_mgr()
        if not mgr:
            return
        
        try:
            # Récupérer le port du peer depuis la config
            port = self.app_gui.peer_port.get()
            
            self._log(f"Démarrage serveur P2P sur port {port}...")
            self._log(f"  Network server existe: {hasattr(mgr, 'network_server') and mgr.network_server is not None}")
            
            # Le serveur est déjà créé dans le ChunkingManager si disponible
            if hasattr(mgr, 'network_server') and mgr.network_server:
                # Enregistrer le callback pour mettre à jour les stats automatiquement
                def on_chunk_received():
                    try:
                        self.after(0, self._update_stats)
                    except Exception as e:
                        self.logger.warning(f"Erreur callback update stats: {e}")
                
                mgr.network_server.on_chunk_stored = on_chunk_received
                
                async def start():
                    try:
                        self.after(0, lambda: self._log(f"  Appel network_server.start(0.0.0.0, {port})..."))
                        await mgr.network_server.start("0.0.0.0", port)
                        self.after(0, lambda: self._log(f"✓ Serveur P2P démarré sur 0.0.0.0:{port}"))
                        self.after(0, lambda: self._log(f"  Les autres clients peuvent maintenant envoyer des chunks"))
                        self.after(0, lambda: self.server_status_var.set(f"Serveur: Port {port}"))
                    except Exception as e:
                        self.after(0, lambda: self._log(f"✗ Erreur dans start(): {e}"))
                
                self._run_async(start())
                self._server_running = True
            else:
                self._log("✗ Serveur P2P non configuré dans ChunkingManager")
                self._log(f"  hasattr network_server: {hasattr(mgr, 'network_server')}")
                if hasattr(mgr, 'network_server'):
                    self._log(f"  network_server value: {mgr.network_server}")
                
        except Exception as e:
            import traceback
            self._log(f"✗ Erreur démarrage serveur: {e}")
            self._log(f"  {traceback.format_exc()[:200]}")
    
    def _stop_server(self):
        """Arrête le serveur P2P."""
        mgr = self._get_chunking_mgr()
        if not mgr:
            return
        
        try:
            if hasattr(mgr, 'network_server') and mgr.network_server:
                async def stop():
                    await mgr.network_server.stop()
                    self.after(0, lambda: self._log("✓ Serveur arrêté"))
                    self.after(0, lambda: self.server_status_var.set("Serveur: Arrêté"))
                
                self._run_async(stop())
                self._server_running = False
            
        except Exception as e:
            self._log(f"✗ Erreur arrêt serveur: {e}")
    
    def on_peers_updated(self, peers: list):
        """Appelé quand la liste des peers est mise à jour."""
        self.peers_count_var.set(f"Peers: {len(peers)}")
