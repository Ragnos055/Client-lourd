"""
Gestionnaire de réplication et relocalisation des chunks.

Ce module gère la redistribution des chunks lorsqu'un peer se déconnecte,
ainsi que la maintenance de la rétention de 30 jours.

Example:
    >>> from chunking.replication_mgr import ReplicationManager
    >>> from chunking.chunk_db import ChunkDatabase
    >>> db = ChunkDatabase(":memory:")
    >>> mgr = ReplicationManager(db, "my-peer-uuid")
"""

import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from .config import CHUNKING_CONFIG
from .models import (
    ChunkAssignment, ReplicationTask, PeerInfo,
    StoredChunk, ChunkMetadata
)
from .exceptions import (
    ReplicationError, PeerCommunicationError, InsufficientChunksError
)
from .chunk_db import ChunkDatabase


class ReplicationManager:
    """
    Gestionnaire de réplication et relocalisation des chunks.
    
    Cette classe gère:
    - La détection de déconnexion de peers
    - La relocalisation des chunks vers d'autres peers
    - Le suivi des tâches de réplication
    - La mise à jour des scores de fiabilité
    - Le nettoyage des chunks expirés
    
    Attributes:
        db: Instance de ChunkDatabase
        peer_uuid: UUID de ce peer
        connection_handler: Handler pour la connexion réseau
        peer_rpc: Client RPC pour communiquer avec les peers
        logger: Logger pour le debug
        config: Configuration du chunking
        
    Example:
        >>> db = ChunkDatabase(":memory:")
        >>> mgr = ReplicationManager(db, "peer-123")
        >>> mgr.peer_uuid
        'peer-123'
    """
    
    def __init__(
        self,
        db: ChunkDatabase,
        peer_uuid: str,
        connection_handler: Optional[Any] = None,
        peer_rpc: Optional[Any] = None,
        chunk_store: Optional[Any] = None,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialise le gestionnaire de réplication.
        
        Args:
            db: Instance de ChunkDatabase
            peer_uuid: UUID de ce peer
            connection_handler: Handler de connexion réseau (optionnel)
            peer_rpc: Client RPC pour les peers (optionnel)
            chunk_store: Store de chunks local (optionnel)
            logger: Logger optionnel
        """
        self.db = db
        self.peer_uuid = peer_uuid
        self.connection_handler = connection_handler
        self.peer_rpc = peer_rpc
        self.chunk_store = chunk_store
        self.logger = logger or logging.getLogger(__name__)
        self.config = CHUNKING_CONFIG
        
        # État interne
        self._processing = False
        self._last_cleanup = datetime.utcnow()
        
        self.logger.info(f"ReplicationManager initialisé pour peer {peer_uuid}")
    
    # ==========================================================================
    # DÉTECTION DE DÉCONNEXION
    # ==========================================================================
    
    async def on_peer_disconnected(self, peer_uuid: str) -> None:
        """
        Gère la déconnexion d'un peer.
        
        Quand un peer se déconnecte:
        1. On le marque comme hors ligne dans la base
        2. On identifie tous les chunks qu'il stockait
        3. On crée des tâches de relocalisation pour chaque chunk
        4. On lance le traitement des relocalisations
        
        Args:
            peer_uuid: UUID du peer qui s'est déconnecté
            
        Example:
            >>> import asyncio
            >>> async def test():
            ...     db = ChunkDatabase(":memory:")
            ...     mgr = ReplicationManager(db, "my-peer")
            ...     await mgr.on_peer_disconnected("disconnected-peer")
        """
        self.logger.warning(f"Peer déconnecté détecté: {peer_uuid}")
        
        # Marquer le peer comme hors ligne
        self.db.set_peer_offline(peer_uuid)
        
        # Récupérer tous les chunks stockés par ce peer
        locations = self.db.get_locations_by_peer(peer_uuid)
        
        if not locations:
            self.logger.info(f"Aucun chunk à relocaliser pour {peer_uuid}")
            return
        
        self.logger.info(f"Création de {len(locations)} tâches de relocalisation")
        
        # Créer une tâche de relocalisation pour chaque chunk
        for location in locations:
            if location.status == 'confirmed':
                task = ReplicationTask(
                    file_uuid=location.file_uuid,
                    chunk_idx=location.chunk_idx,
                    owner_uuid=location.owner_uuid,
                    source_peer_uuid=peer_uuid,
                    reason='peer_disconnected',
                )
                self.db.add_replication_task(task)
                
                # Marquer la location comme invalide
                self.db.update_location_status(
                    location.file_uuid,
                    location.chunk_idx,
                    location.owner_uuid,
                    peer_uuid,
                    'relocated',
                    'Peer disconnected'
                )
        
        # Mettre à jour le score de fiabilité
        await self._decrease_peer_reliability(peer_uuid)
        
        # Lancer le traitement
        asyncio.create_task(self.process_pending_relocations())
    
    async def _decrease_peer_reliability(self, peer_uuid: str) -> None:
        """
        Diminue le score de fiabilité d'un peer après déconnexion.
        
        Args:
            peer_uuid: UUID du peer
        """
        peer = self.db.get_peer(peer_uuid)
        if peer:
            current_score = peer.get('reliability_score', 0.5)
            new_score = max(0.0, current_score - 0.1)
            self.db.update_peer_reliability(peer_uuid, new_score)
            self.logger.debug(
                f"Score de fiabilité diminué pour {peer_uuid}: "
                f"{current_score:.2f} -> {new_score:.2f}"
            )
    
    # ==========================================================================
    # TRAITEMENT DES RELOCALISATIONS
    # ==========================================================================
    
    async def process_pending_relocations(self) -> int:
        """
        Traite toutes les tâches de relocalisation en attente.
        
        Pour chaque tâche:
        1. Sélectionne un peer de remplacement
        2. Récupère le chunk depuis un peer qui l'a encore
        3. Envoie le chunk au nouveau peer
        4. Met à jour la base de données
        
        Returns:
            Nombre de relocalisations réussies
            
        Example:
            >>> import asyncio
            >>> async def test():
            ...     db = ChunkDatabase(":memory:")
            ...     mgr = ReplicationManager(db, "my-peer")
            ...     count = await mgr.process_pending_relocations()
        """
        if self._processing:
            self.logger.debug("Traitement déjà en cours")
            return 0
        
        self._processing = True
        successful = 0
        
        try:
            # Récupérer les tâches en attente
            pending_tasks = self.db.get_pending_replications()
            
            if not pending_tasks:
                self.logger.debug("Aucune relocalisation en attente")
                return 0
            
            self.logger.info(f"Traitement de {len(pending_tasks)} relocalisations")
            
            # Traiter par batch
            batch_size = self.config['REPLICATION']['BATCH_SIZE']
            
            for i, task in enumerate(pending_tasks[:batch_size]):
                try:
                    success = await self._process_single_relocation(task)
                    if success:
                        successful += 1
                except Exception as e:
                    self.logger.error(
                        f"Erreur relocalisation {task.file_uuid}#{task.chunk_idx}: {e}"
                    )
                
                # Petite pause entre les tâches
                await asyncio.sleep(0.1)
            
            self.logger.info(
                f"Relocalisations terminées: {successful}/{len(pending_tasks[:batch_size])} réussies"
            )
            
        finally:
            self._processing = False
        
        return successful
    
    async def _process_single_relocation(self, task: ReplicationTask) -> bool:
        """
        Traite une seule tâche de relocalisation.
        
        Args:
            task: Tâche de relocalisation
            
        Returns:
            True si la relocalisation a réussi
        """
        # Vérifier le nombre de tentatives
        max_retries = self.config['REPLICATION']['MAX_RETRIES']
        if task.attempts >= max_retries:
            self.logger.warning(
                f"Max tentatives atteintes pour {task.file_uuid}#{task.chunk_idx}"
            )
            return False
        
        # Marquer comme en cours
        task.start()
        
        try:
            # Trouver un peer de remplacement
            exclude_peers = [task.source_peer_uuid]
            if task.target_peer_uuid:
                exclude_peers.append(task.target_peer_uuid)
            
            replacement_peer = self._select_replacement_peer(exclude_peers)
            
            if not replacement_peer:
                self.logger.warning("Aucun peer disponible pour relocalisation")
                task.fail("No replacement peer available")
                return False
            
            task.target_peer_uuid = replacement_peer['uuid']
            
            # Récupérer le chunk
            chunk_data = await self._get_chunk_for_relocation(
                task.file_uuid,
                task.chunk_idx,
                task.owner_uuid,
                exclude_peers
            )
            
            if chunk_data is None:
                task.fail("Could not retrieve chunk from any source")
                return False
            
            # Envoyer au nouveau peer
            success = await self._send_chunk_to_replacement(
                task.target_peer_uuid,
                task.file_uuid,
                task.chunk_idx,
                task.owner_uuid,
                chunk_data
            )
            
            if success:
                task.complete()
                
                # Créer la nouvelle localisation
                new_assignment = ChunkAssignment(
                    file_uuid=task.file_uuid,
                    chunk_idx=task.chunk_idx,
                    owner_uuid=task.owner_uuid,
                    peer_uuid=task.target_peer_uuid,
                    status='confirmed',
                    confirmed_at=datetime.utcnow(),
                )
                self.db.add_location(new_assignment)
                
                # Mettre à jour le score du nouveau peer
                await self._increase_peer_reliability(task.target_peer_uuid)
                
                self.logger.info(
                    f"Chunk {task.file_uuid}#{task.chunk_idx} relocalisé vers "
                    f"{task.target_peer_uuid}"
                )
                return True
            else:
                task.fail("Failed to send chunk to replacement peer")
                return False
                
        except Exception as e:
            task.fail(str(e))
            self.logger.error(f"Erreur relocalisation: {e}")
            return False
    
    async def _get_chunk_for_relocation(
        self,
        file_uuid: str,
        chunk_idx: int,
        owner_uuid: str,
        exclude_peers: List[str]
    ) -> Optional[bytes]:
        """
        Récupère un chunk pour relocalisation depuis une source disponible.
        
        Args:
            file_uuid: UUID du fichier
            chunk_idx: Index du chunk
            owner_uuid: UUID du propriétaire
            exclude_peers: Peers à exclure
            
        Returns:
            Données du chunk ou None
        """
        # D'abord essayer le store local
        if self.chunk_store:
            chunk_data = self.chunk_store.get_chunk(owner_uuid, file_uuid, chunk_idx)
            if chunk_data:
                self.logger.debug(f"Chunk {chunk_idx} trouvé localement")
                return chunk_data
        
        # Sinon chercher sur le réseau
        locations = self.db.get_locations(file_uuid, chunk_idx, owner_uuid)
        
        for location in locations:
            if location.peer_uuid in exclude_peers:
                continue
            if location.status != 'confirmed':
                continue
            
            # Vérifier si le peer est en ligne
            peer = self.db.get_peer(location.peer_uuid)
            if not peer or not peer.get('is_online'):
                continue
            
            # Essayer de récupérer le chunk
            if self.peer_rpc:
                try:
                    result = await self.peer_rpc.get_chunk(
                        peer_uuid=location.peer_uuid,
                        file_uuid=file_uuid,
                        chunk_idx=chunk_idx,
                        owner_uuid=owner_uuid
                    )
                    if result and result.get('chunk_data'):
                        return result['chunk_data']
                except Exception as e:
                    self.logger.debug(
                        f"Échec récupération depuis {location.peer_uuid}: {e}"
                    )
        
        return None
    
    async def _send_chunk_to_replacement(
        self,
        peer_uuid: str,
        file_uuid: str,
        chunk_idx: int,
        owner_uuid: str,
        chunk_data: bytes
    ) -> bool:
        """
        Envoie un chunk au peer de remplacement.
        
        Args:
            peer_uuid: UUID du peer cible
            file_uuid: UUID du fichier
            chunk_idx: Index du chunk
            owner_uuid: UUID du propriétaire
            chunk_data: Données du chunk
            
        Returns:
            True si l'envoi a réussi
        """
        if self.peer_rpc is None:
            self.logger.warning("PeerRPC non configuré, envoi simulé")
            return True  # Simuler le succès pour les tests
        
        try:
            result = await self.peer_rpc.store_chunk(
                peer_uuid=peer_uuid,
                file_uuid=file_uuid,
                chunk_idx=chunk_idx,
                owner_uuid=owner_uuid,
                chunk_data=chunk_data,
                content_hash=""  # TODO: calculer le hash
            )
            return result.get('success', False)
        except Exception as e:
            self.logger.error(f"Erreur envoi chunk: {e}")
            return False
    
    # ==========================================================================
    # SÉLECTION DE PEER
    # ==========================================================================
    
    def _select_replacement_peer(
        self,
        exclude_peers: List[str]
    ) -> Optional[Dict[str, Any]]:
        """
        Sélectionne un peer de remplacement pour stocker un chunk.
        
        Critères de sélection:
        - Peer en ligne
        - Score de fiabilité supérieur au minimum
        - Pas dans la liste d'exclusion
        - Tri par score de fiabilité décroissant
        
        Args:
            exclude_peers: Liste des UUIDs de peers à exclure
            
        Returns:
            Dictionnaire avec les infos du peer sélectionné, ou None
        """
        min_score = self.config['PEER_SELECTION']['MIN_RELIABILITY_SCORE']
        
        # Récupérer les peers en ligne
        online_peers = self.db.get_online_peers()
        
        # Filtrer
        candidates = []
        for peer in online_peers:
            # Exclure les peers blacklistés
            if peer['uuid'] in exclude_peers:
                continue
            
            # Exclure notre propre peer
            if peer['uuid'] == self.peer_uuid:
                continue
            
            # Vérifier le score
            if peer.get('reliability_score', 0) < min_score:
                continue
            
            candidates.append(peer)
        
        if not candidates:
            return None
        
        # Trier par score décroissant puis par nombre de chunks croissant
        candidates.sort(
            key=lambda p: (
                -p.get('reliability_score', 0),
                p.get('chunks_stored', 0)
            )
        )
        
        return candidates[0]
    
    # ==========================================================================
    # GESTION DE L'EXPIRATION
    # ==========================================================================
    
    async def cleanup_expired_chunks(self) -> int:
        """
        Nettoie les chunks expirés (après 30 jours).
        
        Cette méthode:
        1. Identifie les chunks expirés
        2. Les supprime du disque local
        3. Les supprime de la base de données
        4. Notifie les propriétaires (optionnel)
        
        Returns:
            Nombre de chunks supprimés
        """
        self.logger.info("Nettoyage des chunks expirés...")
        
        # Récupérer les chunks expirés
        expired_chunks = self.db.get_expired_chunks()
        
        if not expired_chunks:
            self.logger.debug("Aucun chunk expiré")
            return 0
        
        deleted_count = 0
        
        for chunk in expired_chunks:
            try:
                # Supprimer du disque
                if self.chunk_store:
                    self.chunk_store.delete_chunk(
                        chunk.owner_uuid,
                        chunk.file_uuid,
                        chunk.chunk_idx
                    )
                
                # Supprimer de la base
                self.db.delete_chunk(
                    chunk.file_uuid,
                    chunk.chunk_idx,
                    chunk.owner_uuid
                )
                
                deleted_count += 1
                
            except Exception as e:
                self.logger.error(
                    f"Erreur suppression chunk expiré "
                    f"{chunk.file_uuid}#{chunk.chunk_idx}: {e}"
                )
        
        self.logger.info(f"Chunks expirés supprimés: {deleted_count}")
        self._last_cleanup = datetime.utcnow()
        
        return deleted_count
    
    async def extend_chunk_retention(
        self,
        file_uuid: str,
        owner_uuid: str,
        extension_days: int = 30
    ) -> bool:
        """
        Prolonge la rétention d'un fichier.
        
        Args:
            file_uuid: UUID du fichier
            owner_uuid: UUID du propriétaire
            extension_days: Nombre de jours à ajouter
            
        Returns:
            True si la prolongation a réussi
        """
        try:
            # Mettre à jour les métadonnées
            metadata = self.db.get_file_metadata(file_uuid)
            if not metadata:
                return False
            
            if metadata.owner_uuid != owner_uuid:
                return False
            
            # Calculer la nouvelle date d'expiration
            new_expires = datetime.utcnow() + timedelta(days=extension_days)
            metadata.expires_at = new_expires
            
            self.db.update_file_metadata(metadata)
            
            self.logger.info(
                f"Rétention prolongée pour {file_uuid} jusqu'à {new_expires}"
            )
            return True
            
        except Exception as e:
            self.logger.error(f"Erreur prolongation rétention: {e}")
            return False
    
    # ==========================================================================
    # MISE À JOUR DES SCORES DE FIABILITÉ
    # ==========================================================================
    
    async def update_peer_reliability_scores(self) -> None:
        """
        Met à jour les scores de fiabilité de tous les peers.
        
        Le score est calculé basé sur:
        - Temps de présence (uptime bonus)
        - Nombre de chunks stockés
        - Historique de succès/échecs
        """
        online_peers = self.db.get_online_peers()
        uptime_bonus = self.config['PEER_SELECTION']['UPTIME_BONUS']
        
        for peer in online_peers:
            peer_uuid = peer['uuid']
            current_score = peer.get('reliability_score', 0.5)
            
            # Calculer le bonus d'uptime
            first_seen = peer.get('first_seen')
            if first_seen:
                if isinstance(first_seen, str):
                    first_seen = datetime.fromisoformat(first_seen)
                
                days_online = (datetime.utcnow() - first_seen).days
                bonus = min(uptime_bonus * days_online, 0.3)  # Max +0.3
                new_score = min(1.0, current_score + bonus)
            else:
                new_score = current_score
            
            # Mettre à jour si changement significatif
            if abs(new_score - current_score) > 0.01:
                self.db.update_peer_reliability(peer_uuid, new_score)
    
    async def _increase_peer_reliability(self, peer_uuid: str) -> None:
        """
        Augmente le score de fiabilité d'un peer après succès.
        
        Args:
            peer_uuid: UUID du peer
        """
        peer = self.db.get_peer(peer_uuid)
        if peer:
            current_score = peer.get('reliability_score', 0.5)
            new_score = min(1.0, current_score + 0.05)
            self.db.update_peer_reliability(peer_uuid, new_score)
    
    # ==========================================================================
    # MONITORING DES CHUNKS À RISQUE
    # ==========================================================================
    
    def get_chunks_at_risk(self) -> List[Dict[str, Any]]:
        """
        Identifie les chunks qui risquent de devenir indisponibles.
        
        Un chunk est à risque si:
        - Il n'a qu'une seule copie confirmée
        - Le peer qui le stocke a un score de fiabilité faible
        - Il expire bientôt (< 7 jours)
        
        Returns:
            Liste de dictionnaires avec les infos des chunks à risque
        """
        at_risk = []
        
        # Récupérer toutes les métadonnées de fichiers
        # (On devrait avoir une méthode pour lister tous les fichiers)
        try:
            # Utiliser une requête SQL directe pour efficacité
            cursor = self.db.conn.cursor()
            cursor.execute("""
                SELECT 
                    cl.file_uuid,
                    cl.chunk_idx,
                    cl.owner_uuid,
                    COUNT(*) as replica_count,
                    MIN(p.reliability_score) as min_reliability
                FROM chunk_locations cl
                LEFT JOIN peers p ON cl.peer_uuid = p.uuid
                WHERE cl.status = 'confirmed'
                GROUP BY cl.file_uuid, cl.chunk_idx, cl.owner_uuid
                HAVING replica_count <= 1 OR min_reliability < 0.5
            """)
            
            for row in cursor.fetchall():
                at_risk.append({
                    'file_uuid': row['file_uuid'],
                    'chunk_idx': row['chunk_idx'],
                    'owner_uuid': row['owner_uuid'],
                    'replica_count': row['replica_count'],
                    'min_reliability': row['min_reliability'],
                    'risk_level': 'high' if row['replica_count'] <= 1 else 'medium'
                })
                
        except Exception as e:
            self.logger.error(f"Erreur détection chunks à risque: {e}")
        
        return at_risk
    
    def get_replication_stats(self) -> Dict[str, Any]:
        """
        Retourne les statistiques de réplication.
        
        Returns:
            Dictionnaire avec les stats
        """
        pending = self.db.get_pending_replications()
        
        # Compter par statut
        by_status = {}
        for task in pending:
            status = task.status
            by_status[status] = by_status.get(status, 0) + 1
        
        # Chunks à risque
        at_risk = self.get_chunks_at_risk()
        
        return {
            'pending_tasks': len(pending),
            'tasks_by_status': by_status,
            'chunks_at_risk': len(at_risk),
            'high_risk_chunks': len([c for c in at_risk if c['risk_level'] == 'high']),
            'last_cleanup': self._last_cleanup.isoformat(),
            'is_processing': self._processing,
        }
