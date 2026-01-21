"""
Gestionnaire principal du chunking P2P.

Ce module orchestre toutes les opérations de chunking:
- Découpe de fichiers en chunks avec Reed-Solomon
- Distribution des chunks aux peers
- Reconstruction de fichiers depuis les chunks distribués
- Maintenance et monitoring

Example:
    >>> import asyncio
    >>> from chunking.chunking_mgr import ChunkingManager
    >>> async def main():
    ...     mgr = ChunkingManager("my-peer-uuid", "/tmp/storage", "/tmp/db.sqlite")
    ...     # file_uuid = await mgr.chunk_file("container.dat", "owner-uuid")
    ...     await mgr.shutdown()
    >>> # asyncio.run(main())
"""

import os
import uuid
import hashlib
import logging
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable

from .config import CHUNKING_CONFIG, get_config, calculate_optimal_chunk_size
from .models import (
    ChunkMetadata, StoredChunk, ChunkAssignment, 
    LocalGroup, ReplicationTask, PeerInfo, compute_chunk_hash
)
from .exceptions import (
    ChunkingException, ChunkEncodingError, ChunkDecodingError,
    InsufficientChunksError, ChunkNotFoundError, FileMetadataNotFoundError,
    ChunkStorageError, PeerCommunicationError
)
from .chunk_db import ChunkDatabase
from .chunk_store import ChunkStore
from .reed_solomon import ReedSolomonEncoder, create_encoder
from .chunk_net import ChunkNetworkServer
from .peer_rpc import PeerRPC


class ChunkingManager:
    """
    Orchestrateur principal du système de chunking P2P.
    
    Cette classe coordonne toutes les opérations de chunking:
    - Découpe de fichiers chiffrés en chunks avec Reed-Solomon + LRC
    - Distribution des chunks vers les peers du réseau
    - Reconstruction de fichiers depuis les chunks distribués
    - Gestion de la rétention (30 jours)
    - Tâches de maintenance en arrière-plan
    
    Attributes:
        peer_uuid: UUID de ce peer
        storage_dir: Répertoire de stockage des chunks
        db_path: Chemin de la base de données SQLite
        config: Configuration du chunking
        db: Instance de ChunkDatabase
        store: Instance de ChunkStore
        encoder: Instance de ReedSolomonEncoder
        logger: Logger pour le debug
        _background_tasks: Liste des tâches asyncio en cours
        _shutdown_event: Event pour arrêter les tâches
        
    Example:
        >>> mgr = ChunkingManager(
        ...     peer_uuid="peer-123",
        ...     storage_dir="/tmp/chunks",
        ...     db_path="/tmp/chunks.db"
        ... )
        >>> mgr.peer_uuid
        'peer-123'
    """
    
    def __init__(
        self,
        peer_uuid: str,
        storage_dir: str,
        db_path: str,
        config: Optional[Dict[str, Any]] = None,
        logger: Optional[logging.Logger] = None,
        connection_handler: Optional[Any] = None,
        peer_rpc: Optional[Any] = None
    ):
        """
        Initialise le gestionnaire de chunking.
        
        Args:
            peer_uuid: UUID unique de ce peer
            storage_dir: Répertoire pour stocker les chunks localement
            db_path: Chemin du fichier SQLite pour les métadonnées
            config: Configuration optionnelle (utilise CHUNKING_CONFIG par défaut)
            logger: Logger optionnel
            connection_handler: Handler de connexion au tracker (pour obtenir les peers)
            peer_rpc: Client RPC pour communiquer avec les peers
            
        Raises:
            ChunkingException: Si l'initialisation échoue
        """
        self.peer_uuid = peer_uuid
        self.storage_dir = os.path.abspath(os.path.expanduser(storage_dir))
        self.db_path = os.path.abspath(os.path.expanduser(db_path))
        self._distribution_locks: Dict[str, asyncio.Lock] = {}
        self.config = config or get_config()
        self.logger = logger or logging.getLogger(__name__)
        self.connection_handler = connection_handler
        self.peer_rpc = peer_rpc
        self._local_addr = None  # Sera défini plus tard (ip:port local)
        self._peer_address_map = {}  # Mapping peer_uuid -> (ip, port)
        
        # Initialiser les composants
        try:
            self.db = ChunkDatabase(self.db_path, self.logger)
            self.store = ChunkStore(self.storage_dir, self.logger)
            
            # Créer l'encodeur Reed-Solomon
            rs_config = self.config['REED_SOLOMON']
            self.encoder = create_encoder(
                k=rs_config['K'],
                m=rs_config['M'],
                logger=self.logger
            )
            
            # Créer le serveur réseau P2P pour recevoir les chunks
            self.network_server = ChunkNetworkServer(
                own_uuid=peer_uuid,
                chunk_store=self.store,
                chunk_db=self.db,
                logger=self.logger
            )
            
            # Créer le client RPC P2P pour envoyer les chunks
            self.peer_rpc = PeerRPC(
                own_uuid=peer_uuid,
                peer_resolver=self._resolve_peer_address,
                logger=self.logger
            )
            
            self.logger.info(
                f"ChunkingManager initialisé: peer={peer_uuid}, "
                f"storage={self.storage_dir}"
            )
            
        except Exception as e:
            raise ChunkingException(
                f"Failed to initialize ChunkingManager: {e}",
                {"peer_uuid": peer_uuid, "storage_dir": storage_dir}
            )
        
        # État des tâches d'arrière-plan
        self._background_tasks: List[asyncio.Task] = []
        self._shutdown_event = asyncio.Event()
        self._running = False
    
    def _resolve_peer_address(self, peer_uuid: str) -> Optional[tuple]:
        """
        Résout un UUID de peer en adresse (ip, port).
        
        Args:
            peer_uuid: UUID du peer à résoudre
            
        Returns:
            Tuple (ip, port) ou None si non trouvé
        """
        result = self._peer_address_map.get(peer_uuid)
        self.logger.debug(f"Résolution peer {peer_uuid}: {result}")
        return result
    
    def set_connection_handler(self, handler, local_ip: str = None, local_port: int = None):
        """
        Définit le handler de connexion au tracker.
        
        Args:
            handler: Instance de connection (tracker)
            local_ip: IP locale de ce peer
            local_port: Port local de ce peer
        """
        self.connection_handler = handler
        if local_ip and local_port:
            self._local_addr = f"{local_ip}:{local_port}"
            self.logger.info(f"Connection handler défini, local_addr={self._local_addr}")
    
    # ==========================================================================
    # CHUNKING DE FICHIERS
    # ==========================================================================
    
    async def chunk_file(
        self,
        file_path: str,
        owner_uuid: str,
        file_logical_path: str = None,
        delete_source_after: bool = False
    ) -> str:
        """
        Découpe un fichier en chunks avec Reed-Solomon + LRC.

        Cette méthode:
        1. Lit le fichier et calcule son hash
        2. Découpe les données en K chunks de données
        3. Génère M chunks de parité avec Reed-Solomon
        4. Crée les groupes locaux LRC et leurs symboles de récupération
        5. Stocke les chunks localement
        6. Enregistre les métadonnées en base
        7. Optionnellement supprime le fichier source

        Args:
            file_path: Chemin du fichier à chunker (ex: container.dat)
            owner_uuid: UUID du propriétaire du fichier
            file_logical_path: Chemin logique du fichier (ex: dossier/sub/file.txt)
                              Si None, utilise le basename de file_path
            delete_source_after: Si True, supprime le fichier source après
                                 un chunking réussi

        Returns:
            file_uuid: UUID unique généré pour ce fichier chunké

        Raises:
            ChunkEncodingError: Si l'encodage échoue
            ChunkStorageError: Si le stockage échoue
            FileNotFoundError: Si le fichier source n'existe pas

        Example:
            >>> import asyncio
            >>> async def example():
            ...     mgr = ChunkingManager("peer", "/tmp/store", "/tmp/db.sqlite")
            ...     # file_uuid = await mgr.chunk_file("test.dat", "owner")
            ...     await mgr.shutdown()
        """
        file_path = os.path.abspath(file_path)
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        self.logger.info(f"Début du chunking: {file_path} pour {owner_uuid}")
        
        try:
            # Lire le fichier
            with open(file_path, 'rb') as f:
                file_data = f.read()
            
            original_size = len(file_data)
            original_hash = hashlib.sha256(file_data).hexdigest()
            original_filename = os.path.basename(file_path)
            
            # Utiliser le chemin logique fourni ou générer depuis le basename
            if file_logical_path is None:
                file_logical_path = original_filename
            
            self.logger.debug(
                f"Fichier lu: {original_size} bytes, hash={original_hash[:16]}..."
            )
            
            # Générer un UUID unique pour ce fichier
            file_uuid = str(uuid.uuid4())
            
            # Calculer la taille optimale des chunks
            chunk_size = calculate_optimal_chunk_size(original_size)
            
            # Encoder avec Reed-Solomon
            data_chunks, parity_chunks = self.encoder.encode_data(file_data)
            
            self.logger.debug(
                f"Encodage RS terminé: {len(data_chunks)} data + "
                f"{len(parity_chunks)} parity chunks"
            )
            
            # Créer les groupes locaux LRC
            lrc_config = self.config['LRC']
            local_groups = self.encoder.create_local_groups(
                k=len(data_chunks),
                group_size=lrc_config['LOCAL_GROUP_SIZE']
            )
            
            # Générer les symboles de récupération locaux
            local_recovery_symbols = self.encoder.encode_local_recovery_symbols(
                data_chunks, local_groups
            )
            
            # Combiner tous les chunks
            all_chunks = data_chunks + parity_chunks + local_recovery_symbols
            
            # Calculer les hashes de tous les chunks
            chunk_hashes = {}
            for i, chunk in enumerate(all_chunks):
                chunk_hashes[i] = compute_chunk_hash(chunk)
            
            # Indices de récupération globaux
            global_recovery_indices = list(range(
                len(data_chunks) + len(parity_chunks),
                len(all_chunks)
            ))
            
            # Créer les métadonnées
            metadata = ChunkMetadata(
                file_uuid=file_uuid,
                owner_uuid=owner_uuid,
                original_filename=original_filename,
                file_path=file_logical_path,
                original_hash=original_hash,
                original_size=original_size,
                total_chunks=len(all_chunks),
                data_chunks=len(data_chunks),
                parity_chunks=len(parity_chunks),
                chunk_size=len(data_chunks[0]) if data_chunks else 0,
                algorithm='reed-solomon+lrc',
                local_groups=local_groups,
                global_recovery_indices=global_recovery_indices,
                chunk_hashes=chunk_hashes,
            )
            
            # Stocker les chunks localement
            # Note: chaque opération DB fait son propre commit, protégé par RLock
            for i, chunk_data in enumerate(all_chunks):
                # Déterminer le type de chunk
                if i < len(data_chunks):
                    chunk_type = 'data'
                elif i < len(data_chunks) + len(parity_chunks):
                    chunk_type = 'parity'
                else:
                    chunk_type = 'local_recovery'
                
                # Stocker sur disque
                local_path = self.store.store_chunk(
                    owner_uuid, file_uuid, i, chunk_data
                )
                
                # Enregistrer en base
                stored_chunk = StoredChunk(
                    file_uuid=file_uuid,
                    chunk_idx=i,
                    owner_uuid=owner_uuid,
                    local_path=local_path,
                    content_hash=chunk_hashes[i],
                    chunk_type=chunk_type,
                    size_bytes=len(chunk_data),
                )
                self.db.add_chunk(stored_chunk)
            
            # Stocker les métadonnées
            self.store.store_metadata(owner_uuid, file_uuid, metadata)
            self.db.add_file_metadata(metadata)

            self.logger.info(
                f"Chunking terminé: file_uuid={file_uuid}, "
                f"{len(all_chunks)} chunks créés"
            )

            # Supprimer le fichier source si demandé
            if delete_source_after:
                try:
                    os.remove(file_path)
                    self.logger.info(
                        f"Fichier source supprimé après chunking: {file_path}"
                    )
                except OSError as del_err:
                    self.logger.warning(
                        f"Impossible de supprimer le fichier source: {del_err}"
                    )

            return file_uuid

        except Exception as e:
            if isinstance(e, (ChunkEncodingError, ChunkStorageError)):
                raise
            raise ChunkEncodingError(
                f"Chunking failed: {e}",
                {"file_path": file_path, "owner_uuid": owner_uuid}
            )
    
    # ==========================================================================
    # DISTRIBUTION DES CHUNKS
    # ==========================================================================
    
    async def distribute_chunks(
        self,
        file_uuid: str,
        owner_uuid: str,
        exclude_local: bool = True,
        delete_local_after_confirm: bool = True
    ) -> Dict[str, Any]:
        """
        Distribue les chunks d'un fichier vers les peers du réseau.

        Cette méthode:
        1. Vérifie que le serveur réseau est actif
        2. Récupère la liste des peers fiables
        3. Assigne les chunks aux peers (round-robin)
        4. Envoie les chunks via RPC avec retry
        5. Enregistre les localisations en base
        6. Supprime les chunks locaux après confirmation (si demandé)

        Args:
            file_uuid: UUID du fichier à distribuer
            owner_uuid: UUID du propriétaire
            exclude_local: Exclure les chunks locaux de la distribution
            delete_local_after_confirm: Supprimer les chunks locaux après
                                        confirmation par le peer distant

        Returns:
            Rapport de distribution:
            {
                'total_chunks': int,
                'distributed': int,
                'failed': int,
                'local_deleted': int,
                'assignments': List[dict]
            }

        Raises:
            FileMetadataNotFoundError: Si les métadonnées n'existent pas
            PeerCommunicationError: Si la communication échoue
        """
        # Empêcher les distributions concurrentes sur le même fichier
        lock = self._distribution_locks.setdefault(file_uuid, asyncio.Lock())
        if lock.locked():
            self.logger.info(f"Distribution déjà en cours pour {file_uuid}, on ignore la requête")
            return {
                'total_chunks': 0,
                'distributed': 0,
                'failed': 0,
                'assignments': [],
                'error': 'distribution_in_progress'
            }

        try:
            self.logger.info(f">>> DEBUT distribute_chunks pour {file_uuid}")
        except Exception as e:
            self.logger.error(f"Erreur logging debut: {e}")
        
        async with lock:
            # Vérifier que le serveur réseau est actif
            if self.network_server and not self.network_server._running:
                self.logger.warning(
                    "Le serveur réseau n'est pas démarré. "
                    "Les autres peers ne pourront pas nous contacter."
                )
                # On continue quand même, mais on log l'avertissement

            # Vérifier que PeerRPC est configuré
            if self.peer_rpc is None:
                self.logger.error("PeerRPC non configuré, distribution impossible")
                return {
                    'total_chunks': 0,
                    'distributed': 0,
                    'failed': 0,
                    'assignments': [],
                    'error': 'PeerRPC not configured'
                }

            # Récupérer les métadonnées
            metadata = self.db.get_file_metadata(file_uuid)
            if not metadata:
                raise FileMetadataNotFoundError(
                    f"File metadata not found: {file_uuid}",
                    {"file_uuid": file_uuid}
                )
            
            # Vérifier qu'il existe au moins un chunk local avant de distribuer
            local_chunks = self.db.list_chunks_by_file(file_uuid, owner_uuid)
            if not local_chunks:
                self.logger.warning(
                    f"Aucun chunk local trouvé pour {file_uuid}, distribution annulée. "
                    "Les chunks ont peut-être déjà été distribués."
                )
                return {
                    'total_chunks': metadata.total_chunks,
                    'distributed': 0,
                    'failed': 0,
                    'local_deleted': 0,
                    'assignments': [],
                    'error': 'no_local_chunks'
                }

            self.logger.info(f"Distribution des chunks: {file_uuid}")

            # Récupérer les peers disponibles
            peers = await self._get_available_peers(exclude_self=True)

            if not peers:
                self.logger.warning("Aucun peer disponible pour la distribution")
                return {
                    'total_chunks': metadata.total_chunks,
                    'distributed': 0,
                    'failed': 0,
                    'assignments': [],
                    'error': 'No peers available'
                }

            # Préparer les chunks à distribuer avec logique optimale
            chunks_to_distribute = list(range(metadata.total_chunks))

            self.logger.info(f">>> chunks_to_distribute créé: {len(chunks_to_distribute)} chunks")

            # Logique de distribution:
            # - Si chunks <= peers: 1 chunk par peer (optimal)
            # - Si chunks > peers: Round-robin sur tous les peers disponibles

            assignments = []

            # Toujours utiliser round-robin pour éviter IndexError
            self.logger.info(
                f"Distribution: {len(chunks_to_distribute)} chunks sur "
                f"{len(peers)} peer(s)"
            )

            self.logger.info(f">>> Début boucle création assignments...")

            for peer_index, chunk_idx in enumerate(chunks_to_distribute):
                # Utiliser round-robin pour distribuer sur tous les peers disponibles
                peer = peers[peer_index % len(peers)]

                self.logger.info(f">>> Création assignment {peer_index}: chunk {chunk_idx} -> peer {peer.get('uuid', 'unknown')[:16]}")

                assignment = ChunkAssignment(
                    file_uuid=file_uuid,
                    chunk_idx=chunk_idx,
                    owner_uuid=owner_uuid,
                    peer_uuid=peer['uuid'],
                )
                assignments.append(assignment)
                self.logger.debug(
                    f"Chunk {chunk_idx} -> Peer {peer['uuid']}"
                )

            self.logger.info(f">>> Assignments créés: {len(assignments)}")

            # Distribuer les chunks
            distributed = 0
            failed = 0
            local_deleted = 0
            results = []

            self.logger.info(f"Début distribution de {len(assignments)} chunks...")

            for i, assignment in enumerate(assignments):
                self.logger.info(
                    f"[{i+1}/{len(assignments)}] Traitement chunk {assignment.chunk_idx} "
                    f"vers {assignment.peer_uuid}..."
                )
                try:
                    # Récupérer les données du chunk
                    chunk_data = self.store.get_chunk(
                        owner_uuid, file_uuid, assignment.chunk_idx
                    )

                    if chunk_data is None:
                        self.logger.error(
                            f"Chunk non trouvé localement: {file_uuid}#{assignment.chunk_idx}"
                        )
                        assignment.mark_failed("Chunk not found locally")
                        failed += 1
                        continue

                    self.logger.info(
                        f"  Chunk {assignment.chunk_idx} lu ({len(chunk_data)} bytes), "
                        f"envoi vers {assignment.peer_uuid}..."
                    )

                    # Envoyer au peer
                    success = await self._send_chunk_to_peer(
                        assignment.peer_uuid,
                        file_uuid,
                        assignment.chunk_idx,
                        owner_uuid,
                        chunk_data,
                        metadata.chunk_hashes.get(assignment.chunk_idx, '')
                    )

                    self.logger.info(f"  Résultat envoi chunk {assignment.chunk_idx}: {success}")

                    if success:
                        assignment.mark_confirmed()
                        distributed += 1

                        # Supprimer le chunk local après confirmation du peer distant
                        # Le peer distant a validé le checksum et confirmé le stockage
                        if delete_local_after_confirm:
                            try:
                                # Supprimer du disque
                                deleted = self.store.delete_chunk(
                                    owner_uuid, file_uuid, assignment.chunk_idx
                                )
                                if deleted:
                                    # Supprimer aussi de la base de données
                                    self.db.delete_chunk(
                                        file_uuid, assignment.chunk_idx, owner_uuid
                                    )
                                    local_deleted += 1
                                    self.logger.info(
                                        f"Chunk local supprimé après confirmation: "
                                        f"{file_uuid}#{assignment.chunk_idx}"
                                    )
                            except Exception as del_err:
                                self.logger.warning(
                                    f"Erreur suppression chunk local {assignment.chunk_idx}: "
                                    f"{del_err}"
                                )
                    else:
                        assignment.mark_failed("Transfer failed")
                        failed += 1

                    # Enregistrer l'assignation
                    self.db.add_location(assignment)
                    results.append(assignment.to_dict())

                except Exception as e:
                    self.logger.error(
                        f"Erreur distribution chunk {assignment.chunk_idx}: {e}"
                    )
                    assignment.mark_failed(str(e))
                    failed += 1
                    self.db.add_location(assignment)
                    results.append(assignment.to_dict())

            self.logger.info(
                f"Distribution terminée: {distributed}/{len(assignments)} réussis, "
                f"{failed} échecs, {local_deleted} chunks locaux supprimés"
            )

            return {
                'total_chunks': metadata.total_chunks,
                'distributed': distributed,
                'failed': failed,
                'local_deleted': local_deleted,
                'assignments': results,
            }
    
    async def _send_chunk_to_peer(
        self,
        peer_uuid: str,
        file_uuid: str,
        chunk_idx: int,
        owner_uuid: str,
        chunk_data: bytes,
        content_hash: str,
        max_retries: int = None
    ) -> bool:
        """
        Envoie un chunk à un peer via RPC avec retry.

        Args:
            peer_uuid: UUID du peer destinataire
            file_uuid: UUID du fichier
            chunk_idx: Index du chunk
            owner_uuid: UUID du propriétaire
            chunk_data: Données du chunk
            content_hash: Hash du contenu
            max_retries: Nombre max de retries (défaut: config)

        Returns:
            True si l'envoi a réussi
        """
        if self.peer_rpc is None:
            self.logger.error(
                f"PeerRPC non configuré, chunk {chunk_idx} non envoyé"
            )
            return False

        # Utiliser les paramètres de config
        if max_retries is None:
            max_retries = self.config.get('REPLICATION', {}).get('MAX_RETRIES', 3)
        retry_delay = self.config.get('REPLICATION', {}).get('RETRY_DELAY_SECONDS', 5)

        last_error = None

        for attempt in range(max_retries + 1):
            try:
                if attempt > 0:
                    # Attendre avant de réessayer avec backoff exponentiel
                    wait_time = retry_delay * (2 ** (attempt - 1))
                    self.logger.info(
                        f"Retry {attempt}/{max_retries} pour chunk {chunk_idx} "
                        f"vers {peer_uuid} dans {wait_time}s..."
                    )
                    await asyncio.sleep(wait_time)

                # Vérifier la résolution du peer
                peer_addr = self._peer_address_map.get(peer_uuid)
                if peer_addr is None:
                    # Essayer de résoudre via le cache du peer_rpc
                    peer_addr = self.peer_rpc.get_cached_address(peer_uuid)
                
                if peer_addr:
                    addr_str = f" at {peer_addr[0]}:{peer_addr[1]}"
                else:
                    addr_str = " (address unresolved)"
                
                self.logger.info(
                    f"Envoi chunk {chunk_idx} vers {peer_uuid}{addr_str} "
                    f"(tentative {attempt + 1}/{max_retries + 1}, {len(chunk_data)} bytes)..."
                )

                # Utiliser le client RPC pour envoyer
                result = await self.peer_rpc.store_chunk(
                    peer_uuid=peer_uuid,
                    file_uuid=file_uuid,
                    chunk_idx=chunk_idx,
                    owner_uuid=owner_uuid,
                    chunk_data=chunk_data,
                    content_hash=content_hash
                )

                success = result.get('success', False)
                if success:
                    self.logger.info(f"✓ Chunk {chunk_idx} envoyé et stocké sur {peer_uuid}")
                    return True
                else:
                    last_error = f"Server returned: {result}"
                    self.logger.warning(
                        f"✗ Échec envoi chunk {chunk_idx} à {peer_uuid}: {result} "
                        f"(tentative {attempt + 1}/{max_retries + 1})"
                    )

            except Exception as e:
                last_error = str(e)
                addr_str_err = f" at {peer_addr[0]}:{peer_addr[1]}" if 'peer_addr' in locals() and peer_addr else " (address unresolved)"
                self.logger.error(
                    f"Erreur envoi chunk {chunk_idx} à {peer_uuid}{addr_str_err}: "
                    f"{type(e).__name__}: {e} "
                    f"(tentative {attempt + 1}/{max_retries + 1})"
                )

        # Tous les retries ont échoué
        self.logger.error(
            f"✗ Échec définitif envoi chunk {chunk_idx} à {peer_uuid} "
            f"après {max_retries + 1} tentatives. Dernière erreur: {last_error}"
        )
        return False
    
    async def _get_available_peers(
        self,
        exclude_self: bool = True,
        min_reliability: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        Récupère la liste des peers disponibles et fiables.
        
        Args:
            exclude_self: Exclure notre propre peer
            min_reliability: Score minimum de fiabilité (défaut: config)
            
        Returns:
            Liste de dictionnaires avec les infos des peers
        """
        if min_reliability is None:
            min_reliability = self.config['PEER_SELECTION']['MIN_RELIABILITY_SCORE']
        
        peers = []
        
        # 1. Essayer de récupérer les peers depuis le connection_handler (tracker)
        if self.connection_handler is not None:
            try:
                resp = self.connection_handler.get_peers()
                tracker_peers = resp.get('peers', []) if isinstance(resp, dict) else []
                for p in tracker_peers:
                    # Le tracker peut renvoyer soit des dicts soit des strings "ip:port"
                    if isinstance(p, str):
                        # Format "ip:port"
                        parts = p.rsplit(':', 1)
                        if len(parts) == 2:
                            ip = parts[0]
                            port = int(parts[1])
                            peer_uuid = p  # Utiliser ip:port comme UUID temporaire
                        else:
                            continue
                    else:
                        # Format dict
                        ip = p.get('ip')
                        port = p.get('port')
                        peer_uuid = p.get('uuid', f"{ip}:{port}")
                    
                    peer_info = {
                        'uuid': peer_uuid,
                        'ip': ip,
                        'port': port,
                        'reliability_score': 1.0,  # Peers du tracker considérés fiables
                        'is_online': True
                    }
                    peers.append(peer_info)
                    
                    # Stocker dans le mapping pour la résolution
                    self._peer_address_map[peer_uuid] = (ip, port)

                    # Mettre à jour aussi le cache du PeerRPC
                    if self.peer_rpc:
                        self.peer_rpc.update_peer_address(peer_uuid, ip, port)

                    self.logger.debug(f"Peer ajouté au mapping: {peer_uuid} -> ({ip}, {port})")
                    
                self.logger.debug(f"Peers récupérés du tracker: {len(peers)}")
            except Exception as e:
                self.logger.warning(f"Erreur récupération peers du tracker: {e}")
        
        # 2. Ajouter les peers de la base locale si pas de tracker
        if not peers:
            peers = self.db.get_online_peers()
            # Stocker dans le mapping
            for peer in peers:
                peer_uuid = peer.get('uuid')
                ip = peer.get('ip')
                port = peer.get('port')
                if peer_uuid and ip and port:
                    self._peer_address_map[peer_uuid] = (ip, port)
                    # Mettre à jour aussi le cache du PeerRPC
                    if self.peer_rpc:
                        self.peer_rpc.update_peer_address(peer_uuid, ip, port)
        
        # Filtrer
        filtered = []
        for peer in peers:
            # Exclure soi-même (par UUID ou par IP:port)
            if exclude_self:
                peer_id = peer.get('uuid', '')
                peer_addr = f"{peer.get('ip')}:{peer.get('port')}"
                if peer_id == self.peer_uuid or peer_addr == self._local_addr:
                    continue
            
            # Vérifier le score de fiabilité
            if peer.get('reliability_score', 0) < min_reliability:
                continue
            
            filtered.append(peer)
        
        # Trier par score de fiabilité décroissant
        filtered.sort(key=lambda p: p.get('reliability_score', 0), reverse=True)
        
        self.logger.debug(f"Peers disponibles après filtrage: {len(filtered)}")
        
        return filtered
    
    # ==========================================================================
    # RECONSTRUCTION DE FICHIERS
    # ==========================================================================
    
    async def reconstruct_file(
        self,
        file_uuid: str,
        owner_uuid: Optional[str] = None,
        output_path: Optional[str] = None
    ) -> bytes:
        """
        Reconstruit un fichier depuis ses chunks distribués.
        
        Cette méthode:
        1. Récupère les métadonnées du fichier
        2. Collecte les chunks disponibles (locaux + réseau)
        3. Utilise Reed-Solomon pour reconstruire si nécessaire
        4. Vérifie le hash du fichier reconstruit
        5. Écrit optionnellement le fichier sur disque
        
        Args:
            file_uuid: UUID du fichier à reconstruire
            owner_uuid: UUID du propriétaire
            output_path: Chemin optionnel pour écrire le fichier
            
        Returns:
            Données du fichier reconstruit
            
        Raises:
            FileMetadataNotFoundError: Si les métadonnées n'existent pas
            InsufficientChunksError: Si pas assez de chunks disponibles
            ChunkDecodingError: Si la reconstruction échoue
        """
        # Récupérer les métadonnées
        metadata = self.db.get_file_metadata(file_uuid)
        if not metadata and owner_uuid:
            # Essayer depuis le disque avec l'owner fourni
            metadata = self.store.get_metadata(owner_uuid, file_uuid)
        
        if not metadata:
            raise FileMetadataNotFoundError(
                f"File metadata not found: {file_uuid}",
                {"file_uuid": file_uuid}
            )

        # Utiliser l'owner présent dans les métadonnées si non fourni
        effective_owner_uuid = owner_uuid or metadata.owner_uuid
        
        self.logger.info(
            f"Reconstruction fichier: {file_uuid} "
            f"({metadata.original_filename}, {metadata.original_size} bytes)"
        )
        
        # Collecter les chunks disponibles
        available_chunks: Dict[int, bytes] = {}
        local_recovery_symbols: Dict[int, bytes] = {}
        
        # 1. Chunks locaux
        for chunk_idx in range(metadata.total_chunks):
            chunk_data = self.store.get_chunk(effective_owner_uuid, file_uuid, chunk_idx)
            if chunk_data:
                # Vérifier le hash
                expected_hash = metadata.chunk_hashes.get(chunk_idx)
                if expected_hash:
                    actual_hash = compute_chunk_hash(chunk_data)
                    if actual_hash != expected_hash:
                        self.logger.warning(
                            f"Hash invalide pour chunk {chunk_idx}, ignoré"
                        )
                        continue
                
                if chunk_idx >= metadata.data_chunks + metadata.parity_chunks:
                    # C'est un symbole de récupération local
                    local_idx = chunk_idx - (metadata.data_chunks + metadata.parity_chunks)
                    local_recovery_symbols[local_idx] = chunk_data
                else:
                    available_chunks[chunk_idx] = chunk_data
        
        self.logger.debug(
            f"Chunks locaux trouvés: {len(available_chunks)} data/parity, "
            f"{len(local_recovery_symbols)} local recovery"
        )
        
        # 2. Chunks depuis le réseau si nécessaire
        if len(available_chunks) < metadata.data_chunks:
            network_chunks = await self._fetch_chunks_from_network(
                file_uuid, effective_owner_uuid, metadata,
                needed_count=metadata.data_chunks - len(available_chunks),
                exclude_indices=set(available_chunks.keys())
            )
            available_chunks.update(network_chunks)
        
        # 3. Vérifier qu'on a assez de chunks
        if len(available_chunks) < metadata.data_chunks:
            raise InsufficientChunksError(
                f"Not enough chunks: {len(available_chunks)}/{metadata.data_chunks}",
                file_uuid=file_uuid,
                available_chunks=len(available_chunks),
                required_chunks=metadata.data_chunks,
                missing_indices=[
                    i for i in range(metadata.total_chunks) 
                    if i not in available_chunks
                ]
            )
        
        # 4. Reconstruire avec LRC si on a des symboles locaux
        if local_recovery_symbols and metadata.local_groups:
            self.logger.debug("Tentative de reconstruction avec LRC")
            try:
                reconstructed = self.encoder.decode_with_lrc(
                    available_chunks,
                    metadata.local_groups,
                    local_recovery_symbols,
                    metadata.original_size
                )
            except Exception as e:
                self.logger.warning(f"LRC échoué, fallback sur RS: {e}")
                reconstructed = self.encoder.decode_data(
                    available_chunks,
                    metadata.original_size
                )
        else:
            # Reconstruction standard Reed-Solomon
            reconstructed = self.encoder.decode_data(
                available_chunks,
                metadata.original_size
            )
        
        # 5. Vérifier le hash
        actual_hash = hashlib.sha256(reconstructed).hexdigest()
        if actual_hash != metadata.original_hash:
            raise ChunkDecodingError(
                "Reconstructed file hash mismatch",
                {
                    "expected": metadata.original_hash,
                    "actual": actual_hash
                }
            )
        
        self.logger.info(
            f"Fichier reconstruit avec succès: {metadata.original_filename} "
            f"({len(reconstructed)} bytes)"
        )
        
        # 6. Écrire sur disque si demandé
        if output_path:
            output_path = os.path.abspath(output_path)
            with open(output_path, 'wb') as f:
                f.write(reconstructed)
            self.logger.info(f"Fichier écrit: {output_path}")
        
        return reconstructed
    
    async def _fetch_chunks_from_network(
        self,
        file_uuid: str,
        owner_uuid: str,
        metadata: ChunkMetadata,
        needed_count: int,
        exclude_indices: set
    ) -> Dict[int, bytes]:
        """
        Récupère des chunks depuis le réseau P2P.
        
        Args:
            file_uuid: UUID du fichier
            owner_uuid: UUID du propriétaire
            metadata: Métadonnées du fichier
            needed_count: Nombre de chunks nécessaires
            exclude_indices: Indices à ne pas récupérer (déjà disponibles)
            
        Returns:
            Dictionnaire {chunk_idx: chunk_data}
        """
        fetched = {}
        
        # Récupérer les localisations depuis la base
        all_locations = self.db.get_locations_by_file(file_uuid, owner_uuid)
        
        # Grouper par chunk_idx
        locations_by_chunk: Dict[int, List[ChunkAssignment]] = {}
        for loc in all_locations:
            if loc.chunk_idx not in exclude_indices and loc.status == 'confirmed':
                if loc.chunk_idx not in locations_by_chunk:
                    locations_by_chunk[loc.chunk_idx] = []
                locations_by_chunk[loc.chunk_idx].append(loc)
        
        # Essayer de récupérer les chunks manquants
        for chunk_idx, locations in locations_by_chunk.items():
            if len(fetched) >= needed_count:
                break
            
            for location in locations:
                try:
                    chunk_data = await self._fetch_chunk_from_peer(
                        location.peer_uuid,
                        file_uuid,
                        chunk_idx,
                        owner_uuid
                    )
                    
                    if chunk_data:
                        # Vérifier le hash
                        expected_hash = metadata.chunk_hashes.get(chunk_idx)
                        if expected_hash:
                            actual_hash = compute_chunk_hash(chunk_data)
                            if actual_hash != expected_hash:
                                self.logger.warning(
                                    f"Hash invalide depuis {location.peer_uuid}, "
                                    f"chunk {chunk_idx}"
                                )
                                continue
                        
                        fetched[chunk_idx] = chunk_data
                        self.logger.debug(
                            f"Chunk {chunk_idx} récupéré depuis {location.peer_uuid}"
                        )
                        break
                        
                except Exception as e:
                    self.logger.error(
                        f"Erreur récupération chunk {chunk_idx} depuis "
                        f"{location.peer_uuid}: {e}"
                    )
        
        return fetched
    
    async def _fetch_chunk_from_peer(
        self,
        peer_uuid: str,
        file_uuid: str,
        chunk_idx: int,
        owner_uuid: str
    ) -> Optional[bytes]:
        """
        Récupère un chunk depuis un peer via RPC.
        
        Args:
            peer_uuid: UUID du peer
            file_uuid: UUID du fichier
            chunk_idx: Index du chunk
            owner_uuid: UUID du propriétaire
            
        Returns:
            Données du chunk ou None
        """
        if self.peer_rpc is None:
            return None
        
        try:
            result = await self.peer_rpc.get_chunk(
                peer_uuid=peer_uuid,
                file_uuid=file_uuid,
                chunk_idx=chunk_idx,
                owner_uuid=owner_uuid
            )
            return result.get('chunk_data')
            
        except Exception as e:
            self.logger.error(f"Erreur récupération depuis {peer_uuid}: {e}")
            return None
    
    # ==========================================================================
    # LISTING ET GESTION
    # ==========================================================================
    
    def list_my_files(self, owner_uuid: str) -> List[Dict[str, Any]]:
        """
        Liste tous les fichiers d'un propriétaire.
        
        Args:
            owner_uuid: UUID du propriétaire
            
        Returns:
            Liste de dictionnaires avec les infos de chaque fichier:
            [
                {
                    'file_uuid': str,
                    'original_filename': str,
                    'original_size': int,
                    'total_chunks': int,
                    'local_chunks': int,
                    'distributed_chunks': int,
                    'created_at': str,
                    'expires_at': str,
                    'status': str  # 'complete', 'partial', 'distributed'
                },
                ...
            ]
        """
        files = []
        
        # Récupérer depuis la base de données
        metadata_list = self.db.list_files_by_owner(owner_uuid)
        
        for metadata in metadata_list:
            # Compter les chunks locaux
            local_chunks = len(self.store.list_chunks(owner_uuid, metadata.file_uuid))
            
            # Compter les chunks distribués
            locations = self.db.get_locations_by_file(metadata.file_uuid, owner_uuid)
            distributed_chunks = len([l for l in locations if l.status == 'confirmed'])
            
            # Déterminer le statut
            if local_chunks >= metadata.total_chunks:
                status = 'complete'
            elif distributed_chunks > 0:
                status = 'distributed'
            else:
                status = 'partial'
            
            files.append({
                'file_uuid': metadata.file_uuid,
                'original_filename': metadata.original_filename,
                'original_size': metadata.original_size,
                'original_hash': metadata.original_hash,
                'total_chunks': metadata.total_chunks,
                'data_chunks': metadata.data_chunks,
                'parity_chunks': metadata.parity_chunks,
                'local_chunks': local_chunks,
                'distributed_chunks': distributed_chunks,
                'created_at': metadata.created_at.isoformat() if metadata.created_at else None,
                'expires_at': metadata.expires_at.isoformat() if metadata.expires_at else None,
                'status': status,
            })
        
        return files
    
    def delete_file(self, file_uuid: str, owner_uuid: str) -> bool:
        """
        Supprime un fichier et tous ses chunks.
        
        Args:
            file_uuid: UUID du fichier
            owner_uuid: UUID du propriétaire
            
        Returns:
            True si la suppression a réussi
        """
        try:
            # Supprimer les chunks du disque
            deleted_count = self.store.delete_file(owner_uuid, file_uuid)
            
            # Supprimer de la base de données
            self.db.delete_file_metadata(file_uuid)
            
            # Supprimer les chunks de la base
            chunks = self.db.list_chunks_by_file(file_uuid, owner_uuid)
            for chunk in chunks:
                self.db.delete_chunk(file_uuid, chunk.chunk_idx, owner_uuid)
            
            self.logger.info(
                f"Fichier supprimé: {file_uuid} ({deleted_count} fichiers)"
            )
            return True
            
        except Exception as e:
            self.logger.error(f"Erreur suppression fichier {file_uuid}: {e}")
            return False
    
    # ==========================================================================
    # TÂCHES D'ARRIÈRE-PLAN
    # ==========================================================================
    
    async def start_background_tasks(self) -> None:
        """
        Démarre les tâches de maintenance en arrière-plan.
        
        Tâches lancées:
        - Nettoyage des chunks expirés
        - Vérification de l'intégrité des chunks
        - Mise à jour des scores de fiabilité des peers
        """
        if self._running:
            self.logger.warning("Tâches d'arrière-plan déjà en cours")
            return
        
        self._running = True
        self._shutdown_event.clear()
        
        self.logger.info("Démarrage des tâches d'arrière-plan")
        
        # Tâche de nettoyage périodique
        cleanup_task = asyncio.create_task(self._cleanup_loop())
        self._background_tasks.append(cleanup_task)
        
        # Tâche de vérification d'intégrité
        integrity_task = asyncio.create_task(self._integrity_check_loop())
        self._background_tasks.append(integrity_task)
    
    async def _cleanup_loop(self) -> None:
        """Boucle de nettoyage des chunks expirés."""
        interval = self.config['RETENTION']['CLEANUP_INTERVAL_SECONDS']
        
        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(interval)
                
                if self._shutdown_event.is_set():
                    break
                
                # Nettoyer les chunks expirés
                expired_count = self.db.cleanup_expired_chunks()
                if expired_count > 0:
                    self.logger.info(f"Chunks expirés nettoyés: {expired_count}")
                
                # Nettoyer les fichiers orphelins
                orphaned_count = self.store.cleanup_orphaned_chunks()
                if orphaned_count > 0:
                    self.logger.info(f"Fichiers orphelins nettoyés: {orphaned_count}")
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Erreur dans la boucle de nettoyage: {e}")
    
    async def _integrity_check_loop(self) -> None:
        """Boucle de vérification d'intégrité."""
        interval = 3600  # Toutes les heures
        
        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(interval)
                
                if self._shutdown_event.is_set():
                    break
                
                # Vérifier l'intégrité de la base
                if not self.db.verify_integrity():
                    self.logger.error("Problème d'intégrité de la base de données!")
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Erreur dans la boucle d'intégrité: {e}")
    
    async def shutdown(self) -> None:
        """
        Arrête proprement le gestionnaire de chunking.
        
        - Arrête le serveur réseau P2P
        - Arrête les tâches d'arrière-plan
        - Ferme la connexion à la base de données
        """
        self.logger.info("Arrêt du ChunkingManager...")
        
        # Signaler l'arrêt
        self._shutdown_event.set()
        self._running = False
        
        # Arrêter le serveur réseau
        if self.network_server:
            try:
                await self.network_server.stop()
            except Exception as e:
                self.logger.warning(f"Erreur lors de l'arrêt du serveur: {e}")
        
        # Fermer le client RPC
        if self.peer_rpc:
            try:
                await self.peer_rpc.close()
            except Exception as e:
                self.logger.warning(f"Erreur lors de la fermeture du client RPC: {e}")
        
        # Annuler les tâches d'arrière-plan
        for task in self._background_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        self._background_tasks.clear()
        
        # Fermer la base de données
        self.db.close()
        
        self.logger.info("ChunkingManager arrêté")
    
    # ==========================================================================
    # STATISTIQUES ET MONITORING
    # ==========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Retourne les statistiques complètes du système de chunking.
        
        Returns:
            Dictionnaire avec toutes les statistiques:
            {
                'peer_uuid': str,
                'storage': {...},
                'database': {...},
                'encoding': {...},
                'running': bool
            }
        """
        return {
            'peer_uuid': self.peer_uuid,
            'storage': self.store.get_stats(),
            'database': self.db.export_stats(),
            'encoding': self.encoder.get_encoding_info(),
            'config': {
                'chunk_size_mb': self.config['DEFAULT_CHUNK_SIZE_MB'],
                'retention_days': self.config['RETENTION']['DAYS'],
                'rs_k': self.config['REED_SOLOMON']['K'],
                'rs_m': self.config['REED_SOLOMON']['M'],
            },
            'running': self._running,
            'background_tasks': len(self._background_tasks),
        }
    
    def update_peer(self, peer_uuid: str, ip_address: str, port: int) -> None:
        """
        Met à jour ou ajoute un peer dans la base.
        
        Args:
            peer_uuid: UUID du peer
            ip_address: Adresse IP
            port: Port
        """
        self.db.add_or_update_peer(peer_uuid, ip_address, port)
    
    def set_peer_offline(self, peer_uuid: str) -> None:
        """
        Marque un peer comme hors ligne.
        
        Args:
            peer_uuid: UUID du peer
        """
        self.db.set_peer_offline(peer_uuid)
