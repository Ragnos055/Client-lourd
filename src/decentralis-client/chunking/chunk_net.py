"""
Serveur réseau P2P pour la réception des requêtes de chunks.

Ce module implémente le serveur TCP asynchrone qui écoute les requêtes
des autres peers pour stocker/récupérer des chunks.

Le serveur utilise le même protocole JSON-RPC que le client PeerRPC:
    - Préfixe de 4 bytes (big-endian) pour la longueur du message
    - Corps JSON avec format JSON-RPC 2.0

Example:
    >>> import asyncio
    >>> from chunking.chunk_net import ChunkNetworkServer
    >>> from chunking.chunk_store import ChunkStore
    >>> from chunking.chunk_db import ChunkDatabase
    >>> 
    >>> async def main():
    ...     db = ChunkDatabase("/path/to/db")
    ...     store = ChunkStore("/path/to/chunks", db)
    ...     server = ChunkNetworkServer("my-peer-uuid", store, db)
    ...     await server.start("0.0.0.0", 7654)
    ...     # Le serveur tourne en arrière-plan
    ...     await asyncio.sleep(3600)
    ...     await server.stop()
"""

import json
import asyncio
import logging
import base64
import hashlib
import traceback
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Callable, Set

from .config import CHUNKING_CONFIG
from .exceptions import (
    ChunkNotFoundError,
    ChunkStorageError,
    ChunkValidationError,
)
from .models import StoredChunk, compute_chunk_hash
from .chunk_store import ChunkStore
from .chunk_db import ChunkDatabase


class ChunkNetworkServer:
    """
    Serveur TCP asynchrone pour les requêtes P2P de chunks.
    
    Cette classe:
    - Écoute sur un port TCP pour les connexions entrantes
    - Traite les requêtes JSON-RPC de manière asynchrone
    - Gère le stockage et la récupération de chunks
    - Limite le nombre de connexions simultanées
    
    Attributes:
        own_uuid: UUID de ce peer
        chunk_store: Gestionnaire de stockage local
        chunk_db: Base de données des métadonnées
        logger: Logger pour le debug
        config: Configuration réseau
        
    Example:
        >>> server = ChunkNetworkServer("my-uuid", chunk_store, chunk_db)
        >>> server.own_uuid
        'my-uuid'
    """
    
    def __init__(
        self,
        own_uuid: str,
        chunk_store: ChunkStore,
        chunk_db: ChunkDatabase,
        own_public_key_pem: Optional[str] = None,
        peer_key_resolver: Optional[Callable[[str], str]] = None,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialise le serveur réseau.
        
        Args:
            own_uuid: UUID de ce peer
            chunk_store: Instance de ChunkStore pour le stockage
            chunk_db: Instance de ChunkDatabase pour les métadonnées
            own_public_key_pem: Clé publique de ce peer (pour vérification)
            peer_key_resolver: Fonction pour résoudre UUID -> clé publique
            logger: Logger optionnel
        """
        self.own_uuid = own_uuid
        self.chunk_store = chunk_store
        self.chunk_db = chunk_db
        self.own_public_key_pem = own_public_key_pem
        self.peer_key_resolver = peer_key_resolver
        self.logger = logger or logging.getLogger(__name__)
        self.config = CHUNKING_CONFIG['NETWORK']
        
        # État du serveur
        self._server: Optional[asyncio.Server] = None
        self._active_connections: Set[asyncio.Task] = set()
        self._running = False
        self._start_time: Optional[datetime] = None
        
        # Méthodes RPC disponibles
        self._rpc_methods = {
            'ping': self._handle_ping,
            'store_chunk': self._handle_store_chunk,
            'get_chunk': self._handle_get_chunk,
            'delete_chunk': self._handle_delete_chunk,
            'get_chunk_info': self._handle_get_chunk_info,
            'list_chunks': self._handle_list_chunks,
            'get_stats': self._handle_get_stats,
            'announce_file': self._handle_announce_file,
            'search_file': self._handle_search_file,
        }
        
        self.logger.info(f"ChunkNetworkServer initialisé pour {own_uuid}")
    
    # ==========================================================================
    # GESTION DU SERVEUR
    # ==========================================================================
    
    async def start(self, host: str = "0.0.0.0", port: int = 7654) -> None:
        """
        Démarre le serveur TCP.
        
        Args:
            host: Adresse d'écoute (défaut: toutes les interfaces)
            port: Port d'écoute (défaut: 7654)
        """
        if self._running:
            self.logger.warning("Serveur déjà en cours d'exécution")
            return
        
        self._server = await asyncio.start_server(
            self._handle_client,
            host,
            port,
            limit=self.config.get('MAX_MESSAGE_SIZE', 10 * 1024 * 1024)
        )
        
        self._running = True
        self._start_time = datetime.utcnow()
        
        addr = self._server.sockets[0].getsockname()
        self.logger.info(f"Serveur démarré sur {addr[0]}:{addr[1]}")
        
        # Lancer la boucle de service en arrière-plan
        asyncio.create_task(self._server.serve_forever())
    
    async def stop(self) -> None:
        """
        Arrête le serveur proprement.
        """
        if not self._running:
            return
        
        self._running = False
        
        # Annuler toutes les connexions actives
        for task in self._active_connections:
            task.cancel()
        
        # Attendre la fin des connexions
        if self._active_connections:
            await asyncio.gather(*self._active_connections, return_exceptions=True)
        
        # Fermer le serveur
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        
        self.logger.info("Serveur arrêté")
    
    @property
    def is_running(self) -> bool:
        """Retourne True si le serveur est en cours d'exécution."""
        return self._running
    
    @property
    def active_connections_count(self) -> int:
        """Retourne le nombre de connexions actives."""
        return len(self._active_connections)
    
    # ==========================================================================
    # GESTION DES CONNEXIONS
    # ==========================================================================
    
    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter
    ) -> None:
        """
        Gère une connexion client entrante.
        
        Args:
            reader: StreamReader pour lire les données
            writer: StreamWriter pour écrire les données
        """
        addr = writer.get_extra_info('peername')
        self.logger.debug(f"Nouvelle connexion depuis {addr}")
        
        # Créer une tâche pour cette connexion
        task = asyncio.current_task()
        self._active_connections.add(task)
        
        try:
            while self._running:
                try:
                    # Lire la longueur du message (4 bytes)
                    length_bytes = await asyncio.wait_for(
                        reader.readexactly(4),
                        timeout=self.config['RPC_TIMEOUT_SECONDS']
                    )
                    message_length = int.from_bytes(length_bytes, 'big')
                    
                    # Vérifier la taille max
                    max_size = self.config.get('MAX_MESSAGE_SIZE', 10 * 1024 * 1024)
                    if message_length > max_size:
                        self.logger.warning(
                            f"Message trop grand: {message_length} > {max_size}"
                        )
                        break
                    
                    # Lire le message
                    message_bytes = await asyncio.wait_for(
                        reader.readexactly(message_length),
                        timeout=self.config['RPC_TIMEOUT_SECONDS']
                    )
                    
                    # Parser la requête
                    request = json.loads(message_bytes.decode('utf-8'))
                    
                    # Traiter et répondre
                    response = await self._process_request(request)
                    
                    # Envoyer la réponse
                    response_bytes = json.dumps(response).encode('utf-8')
                    length_prefix = len(response_bytes).to_bytes(4, 'big')
                    
                    writer.write(length_prefix + response_bytes)
                    await writer.drain()
                    
                except asyncio.TimeoutError:
                    self.logger.debug(f"Timeout de connexion pour {addr}")
                    break
                except asyncio.IncompleteReadError:
                    self.logger.debug(f"Connexion fermée par {addr}")
                    break
                except json.JSONDecodeError as e:
                    self.logger.warning(f"JSON invalide de {addr}: {e}")
                    # Envoyer une erreur
                    error_response = self._make_error_response(
                        None, -32700, "Parse error"
                    )
                    await self._send_response(writer, error_response)
                    break
                    
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.error(f"Erreur inattendue pour {addr}: {e}")
            self.logger.debug(traceback.format_exc())
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            self._active_connections.discard(task)
            self.logger.debug(f"Connexion fermée: {addr}")
    
    async def _send_response(
        self,
        writer: asyncio.StreamWriter,
        response: Dict[str, Any]
    ) -> None:
        """
        Envoie une réponse au client.
        
        Args:
            writer: StreamWriter
            response: Réponse à envoyer
        """
        response_bytes = json.dumps(response).encode('utf-8')
        length_prefix = len(response_bytes).to_bytes(4, 'big')
        writer.write(length_prefix + response_bytes)
        await writer.drain()
    
    # ==========================================================================
    # TRAITEMENT DES REQUÊTES
    # ==========================================================================
    
    async def _process_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Traite une requête JSON-RPC.
        
        Args:
            request: Requête JSON-RPC
            
        Returns:
            Réponse JSON-RPC
        """
        request_id = request.get('id')
        method = request.get('method')
        params = request.get('params', {})
        
        self.logger.debug(f"Requête reçue: {method}")
        
        # Vérifier le format
        if request.get('jsonrpc') != '2.0':
            return self._make_error_response(request_id, -32600, "Invalid Request")
        
        if not method:
            return self._make_error_response(request_id, -32600, "Method required")
        
        # Vérifier si la méthode existe
        if method not in self._rpc_methods:
            return self._make_error_response(
                request_id, -32601, f"Method not found: {method}"
            )
        
        # Exécuter la méthode
        try:
            handler = self._rpc_methods[method]
            result = await handler(params)
            
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result,
            }
            
        except ChunkNotFoundError as e:
            return self._make_error_response(
                request_id, 1001, str(e), {'code': 'CHUNK_NOT_FOUND'}
            )
        except ChunkStorageError as e:
            return self._make_error_response(
                request_id, 1002, str(e), {'code': 'STORAGE_ERROR'}
            )
        except ChunkValidationError as e:
            return self._make_error_response(
                request_id, 1003, str(e), {'code': 'VALIDATION_ERROR'}
            )
        except Exception as e:
            self.logger.error(f"Erreur lors du traitement de {method}: {e}")
            self.logger.debug(traceback.format_exc())
            return self._make_error_response(
                request_id, -32603, f"Internal error: {e}"
            )
    
    def _make_error_response(
        self,
        request_id: Optional[str],
        code: int,
        message: str,
        data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Crée une réponse d'erreur JSON-RPC.
        
        Args:
            request_id: ID de la requête
            code: Code d'erreur
            message: Message d'erreur
            data: Données additionnelles
            
        Returns:
            Réponse d'erreur formatée
        """
        error = {"code": code, "message": message}
        if data:
            error["data"] = data
        
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": error,
        }
    
    # ==========================================================================
    # HANDLERS RPC
    # ==========================================================================
    
    async def _handle_ping(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handler pour la méthode 'ping'.
        
        Args:
            params: Paramètres de la requête
            
        Returns:
            {'pong': True, 'peer_uuid': str, 'timestamp': str}
        """
        return {
            'pong': True,
            'peer_uuid': self.own_uuid,
            'timestamp': datetime.utcnow().isoformat(),
            'received_timestamp': params.get('timestamp'),
        }
    
    async def _handle_store_chunk(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handler pour stocker un chunk.
        
        Args:
            params: {
                'file_uuid': str,
                'chunk_idx': int,
                'owner_uuid': str,
                'chunk_data_b64': str,
                'content_hash': str,
                'chunk_size': int
            }
            
        Returns:
            {'success': bool, 'stored_at': str, 'expires_at': str}
        """
        # Extraire les paramètres
        file_uuid = params['file_uuid']
        chunk_idx = params['chunk_idx']
        owner_uuid = params['owner_uuid']
        chunk_data = base64.b64decode(params['chunk_data_b64'])
        content_hash = params['content_hash']
        
        # Vérifier le hash
        computed_hash = compute_chunk_hash(chunk_data)
        if computed_hash != content_hash:
            raise ChunkValidationError(
                f"Hash mismatch: expected {content_hash}, got {computed_hash}",
                file_uuid=file_uuid,
                chunk_idx=chunk_idx
            )
        
        # Stocker le chunk
        stored_at = datetime.utcnow()
        retention_days = CHUNKING_CONFIG['RETENTION_DAYS']
        expires_at = stored_at + timedelta(days=retention_days)
        
        stored_chunk = StoredChunk(
            file_uuid=file_uuid,
            chunk_idx=chunk_idx,
            owner_uuid=owner_uuid,
            content_hash=content_hash,
            size_bytes=len(chunk_data),
            stored_at=stored_at,
            expires_at=expires_at,
        )
        
        # Sauvegarder
        await asyncio.to_thread(
            self.chunk_store.store_chunk,
            chunk_data, stored_chunk
        )
        
        self.logger.info(
            f"Chunk stocké: {file_uuid}/{chunk_idx} "
            f"({len(chunk_data)} bytes)"
        )
        
        return {
            'success': True,
            'stored_at': stored_at.isoformat(),
            'expires_at': expires_at.isoformat(),
        }
    
    async def _handle_get_chunk(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handler pour récupérer un chunk.
        
        Args:
            params: {
                'file_uuid': str,
                'chunk_idx': int,
                'owner_uuid': str
            }
            
        Returns:
            {
                'success': bool,
                'chunk_data_b64': str,
                'content_hash': str,
                'size_bytes': int
            }
        """
        file_uuid = params['file_uuid']
        chunk_idx = params['chunk_idx']
        owner_uuid = params['owner_uuid']
        
        # Récupérer le chunk
        chunk_data = await asyncio.to_thread(
            self.chunk_store.get_chunk,
            file_uuid, chunk_idx, owner_uuid
        )
        
        if chunk_data is None:
            raise ChunkNotFoundError(
                f"Chunk not found: {file_uuid}/{chunk_idx}",
                file_uuid=file_uuid,
                chunk_idx=chunk_idx
            )
        
        content_hash = compute_chunk_hash(chunk_data)
        chunk_b64 = base64.b64encode(chunk_data).decode('ascii')
        
        return {
            'success': True,
            'chunk_data_b64': chunk_b64,
            'content_hash': content_hash,
            'size_bytes': len(chunk_data),
        }
    
    async def _handle_delete_chunk(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handler pour supprimer un chunk.
        
        Args:
            params: {
                'file_uuid': str,
                'chunk_idx': int,
                'owner_uuid': str
            }
            
        Returns:
            {'success': bool, 'deleted': bool}
        """
        file_uuid = params['file_uuid']
        chunk_idx = params['chunk_idx']
        owner_uuid = params['owner_uuid']
        
        # Vérifier que le chunk existe
        chunk_data = await asyncio.to_thread(
            self.chunk_store.get_chunk,
            file_uuid, chunk_idx, owner_uuid
        )
        
        if chunk_data is None:
            return {'success': True, 'deleted': False, 'reason': 'not_found'}
        
        # Supprimer
        await asyncio.to_thread(
            self.chunk_store.delete_chunk,
            file_uuid, chunk_idx, owner_uuid
        )
        
        self.logger.info(f"Chunk supprimé: {file_uuid}/{chunk_idx}")
        
        return {'success': True, 'deleted': True}
    
    async def _handle_get_chunk_info(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handler pour obtenir les infos d'un chunk sans le télécharger.
        
        Args:
            params: {
                'file_uuid': str,
                'chunk_idx': int,
                'owner_uuid': str
            }
            
        Returns:
            {
                'exists': bool,
                'content_hash': str,
                'size_bytes': int,
                'stored_at': str,
                'expires_at': str
            }
        """
        file_uuid = params['file_uuid']
        chunk_idx = params['chunk_idx']
        owner_uuid = params['owner_uuid']
        
        # Récupérer les métadonnées
        metadata = await asyncio.to_thread(
            self.chunk_store.get_metadata,
            file_uuid, chunk_idx, owner_uuid
        )
        
        if metadata is None:
            return {'exists': False}
        
        return {
            'exists': True,
            'content_hash': metadata.get('content_hash'),
            'size_bytes': metadata.get('size_bytes', 0),
            'stored_at': metadata.get('stored_at'),
            'expires_at': metadata.get('expires_at'),
        }
    
    async def _handle_list_chunks(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handler pour lister les chunks stockés.
        
        Args:
            params: {
                'owner_uuid': str,
                'file_uuid': str (optionnel)
            }
            
        Returns:
            {
                'chunks': [
                    {'file_uuid': str, 'chunk_idx': int, 'size_bytes': int},
                    ...
                ],
                'total_size': int
            }
        """
        owner_uuid = params['owner_uuid']
        file_uuid = params.get('file_uuid')
        
        # Récupérer la liste des chunks
        stats = await asyncio.to_thread(self.chunk_store.get_stats)
        
        # Filtrer par owner/file si nécessaire
        # Note: implémentation simplifiée, une vraie implémentation
        # devrait scanner les fichiers ou utiliser la base de données
        
        chunks = []
        total_size = 0
        
        # Utiliser la base de données pour une liste précise
        with self.chunk_db._get_connection() as conn:
            cursor = conn.cursor()
            
            if file_uuid:
                cursor.execute("""
                    SELECT c.file_uuid, c.chunk_idx, c.size_bytes
                    FROM chunks c
                    JOIN file_metadata f ON c.file_uuid = f.file_uuid
                    WHERE f.owner_uuid = ? AND c.file_uuid = ?
                """, (owner_uuid, file_uuid))
            else:
                cursor.execute("""
                    SELECT c.file_uuid, c.chunk_idx, c.size_bytes
                    FROM chunks c
                    JOIN file_metadata f ON c.file_uuid = f.file_uuid
                    WHERE f.owner_uuid = ?
                """, (owner_uuid,))
            
            for row in cursor.fetchall():
                chunk_info = {
                    'file_uuid': row[0],
                    'chunk_idx': row[1],
                    'size_bytes': row[2] or 0,
                }
                chunks.append(chunk_info)
                total_size += chunk_info['size_bytes']
        
        return {
            'chunks': chunks,
            'total_size': total_size,
            'count': len(chunks),
        }
    
    async def _handle_get_stats(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handler pour obtenir les statistiques du peer.
        
        Returns:
            {
                'peer_uuid': str,
                'chunks_stored': int,
                'total_size_bytes': int,
                'uptime_seconds': int
            }
        """
        stats = await asyncio.to_thread(self.chunk_store.get_stats)
        
        uptime_seconds = 0
        if self._start_time:
            uptime_seconds = int(
                (datetime.utcnow() - self._start_time).total_seconds()
            )
        
        return {
            'peer_uuid': self.own_uuid,
            'chunks_stored': stats.get('total_chunks', 0),
            'total_size_bytes': stats.get('total_size', 0),
            'uptime_seconds': uptime_seconds,
            'active_connections': len(self._active_connections),
        }
    
    async def _handle_announce_file(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handler pour l'annonce d'un fichier (DHT simplifiée).
        
        Args:
            params: {
                'file_uuid': str,
                'owner_uuid': str,
                'metadata_json': str
            }
            
        Returns:
            {'success': bool, 'indexed': bool}
        """
        file_uuid = params['file_uuid']
        owner_uuid = params['owner_uuid']
        metadata_json = params['metadata_json']
        
        # Stocker l'annonce dans la base de données locale
        # pour une recherche ultérieure par d'autres peers
        try:
            self.chunk_db.store_file_announcement(
                file_uuid, owner_uuid, metadata_json
            )
            return {'success': True, 'indexed': True}
        except Exception as e:
            self.logger.warning(f"Erreur lors de l'indexation: {e}")
            return {'success': False, 'indexed': False, 'error': str(e)}
    
    async def _handle_search_file(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handler pour la recherche d'un fichier.
        
        Args:
            params: {
                'file_uuid': str,
                'owner_uuid': str
            }
            
        Returns:
            {
                'found': bool,
                'metadata_json': str (si trouvé),
                'chunk_locations': list
            }
        """
        file_uuid = params['file_uuid']
        owner_uuid = params['owner_uuid']
        
        # Rechercher dans la base locale
        try:
            metadata = self.chunk_db.get_file_metadata(file_uuid, owner_uuid)
            
            if metadata:
                # Récupérer les localisations des chunks
                chunk_locations = self.chunk_db.get_chunk_locations(file_uuid)
                
                return {
                    'found': True,
                    'metadata_json': metadata.to_json() if hasattr(metadata, 'to_json') else str(metadata),
                    'chunk_locations': chunk_locations,
                }
            
            return {'found': False}
            
        except Exception as e:
            self.logger.debug(f"Fichier non trouvé: {file_uuid} - {e}")
            return {'found': False}
