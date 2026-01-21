"""
Client RPC asynchrone pour la communication P2P.

Ce module implémente le client pour communiquer avec les autres peers
du réseau en utilisant un protocole JSON-RPC sur TCP.

Format du protocole:
    Requête:
    {
        "jsonrpc": "2.0",
        "id": "unique-request-id",
        "method": "store_chunk|get_chunk|ping|...",
        "params": {...}
    }
    
    Réponse:
    {
        "jsonrpc": "2.0",
        "id": "unique-request-id",
        "result": {...}  // ou "error": {...}
    }

Example:
    >>> import asyncio
    >>> from chunking.peer_rpc import PeerRPC
    >>> async def main():
    ...     rpc = PeerRPC("my-peer-uuid")
    ...     # result = await rpc.ping("other-peer-uuid")
    ...     await rpc.close()
"""

import json
import asyncio
import logging
import hashlib
import base64
import uuid as uuid_module
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass

from .config import CHUNKING_CONFIG
from .exceptions import PeerCommunicationError
from .models import compute_chunk_hash


@dataclass
class PeerConnection:
    """
    Représente une connexion à un peer.
    
    Attributes:
        peer_uuid: UUID du peer
        ip_address: Adresse IP
        port: Port
        reader: StreamReader asyncio
        writer: StreamWriter asyncio
        last_used: Dernière utilisation
        is_connected: État de la connexion
    """
    peer_uuid: str
    ip_address: str
    port: int
    reader: Optional[asyncio.StreamReader] = None
    writer: Optional[asyncio.StreamWriter] = None
    last_used: datetime = None
    is_connected: bool = False
    
    def __post_init__(self):
        if self.last_used is None:
            self.last_used = datetime.utcnow()


class PeerRPC:
    """
    Client RPC asynchrone pour communiquer avec les peers.
    
    Cette classe gère:
    - L'établissement de connexions TCP avec les peers
    - L'envoi et la réception de messages JSON-RPC
    - Le pool de connexions pour la réutilisation
    - Les timeouts et la gestion d'erreurs
    
    Attributes:
        own_uuid: UUID de ce peer
        own_private_key_pem: Clé privée pour signer (optionnel)
        logger: Logger pour le debug
        config: Configuration réseau
        _connections: Pool de connexions actives
        _lock: Lock pour la synchronisation
        
    Example:
        >>> rpc = PeerRPC("my-peer-uuid")
        >>> rpc.own_uuid
        'my-peer-uuid'
    """
    
    def __init__(
        self,
        own_uuid: str,
        own_private_key_pem: Optional[str] = None,
        peer_resolver: Optional[Any] = None,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialise le client RPC.
        
        Args:
            own_uuid: UUID de ce peer
            own_private_key_pem: Clé privée PEM pour signer les requêtes
            peer_resolver: Fonction/objet pour résoudre UUID -> (ip, port)
            logger: Logger optionnel
        """
        self.own_uuid = own_uuid
        self.own_private_key_pem = own_private_key_pem
        self.peer_resolver = peer_resolver
        self.logger = logger or logging.getLogger(__name__)
        self.config = CHUNKING_CONFIG['NETWORK']
        
        # Pool de connexions
        self._connections: Dict[str, PeerConnection] = {}
        self._lock = asyncio.Lock()
        
        self.logger.info(f"PeerRPC initialisé pour {own_uuid}")
    
    # ==========================================================================
    # GESTION DES CONNEXIONS
    # ==========================================================================
    
    async def _get_connection(
        self,
        peer_uuid: str,
        ip_address: Optional[str] = None,
        port: Optional[int] = None
    ) -> PeerConnection:
        """
        Obtient ou crée une connexion vers un peer.
        
        Args:
            peer_uuid: UUID du peer cible
            ip_address: Adresse IP (optionnel si resolver disponible)
            port: Port (optionnel si resolver disponible)
            
        Returns:
            PeerConnection active
            
        Raises:
            PeerCommunicationError: Si la connexion échoue
        """
        async with self._lock:
            # Vérifier si on a déjà une connexion active
            if peer_uuid in self._connections:
                conn = self._connections[peer_uuid]
                if conn.is_connected:
                    conn.last_used = datetime.utcnow()
                    return conn
            
            # Résoudre l'adresse si nécessaire
            if ip_address is None or port is None:
                if self.peer_resolver:
                    try:
                        resolved = await self._resolve_peer(peer_uuid)
                        ip_address = resolved[0]
                        port = resolved[1]
                    except Exception as e:
                        raise PeerCommunicationError(
                            f"Cannot resolve peer address: {e}",
                            peer_uuid=peer_uuid
                        )
                else:
                    raise PeerCommunicationError(
                        "No address provided and no resolver available",
                        peer_uuid=peer_uuid
                    )
            
            # Établir la connexion
            try:
                timeout = self.config['RPC_TIMEOUT_SECONDS']
                self.logger.info(f"Connexion à {ip_address}:{port} (timeout={timeout}s)...")
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(ip_address, port),
                    timeout=timeout
                )
                
                conn = PeerConnection(
                    peer_uuid=peer_uuid,
                    ip_address=ip_address,
                    port=port,
                    reader=reader,
                    writer=writer,
                    is_connected=True,
                )
                
                self._connections[peer_uuid] = conn
                self.logger.info(f"✓ Connexion établie vers {peer_uuid} ({ip_address}:{port})")
                
                return conn
                
            except asyncio.TimeoutError:
                self.logger.error(f"✗ Timeout connexion à {ip_address}:{port}")
                raise PeerCommunicationError(
                    "Connection timeout",
                    peer_uuid=peer_uuid,
                    peer_address=f"{ip_address}:{port}",
                    operation="connect"
                )
            except ConnectionRefusedError:
                self.logger.error(f"✗ Connexion refusée par {ip_address}:{port}")
                raise PeerCommunicationError(
                    "Connection refused",
                    peer_uuid=peer_uuid,
                    peer_address=f"{ip_address}:{port}",
                    operation="connect"
                )
            except Exception as e:
                self.logger.error(f"✗ Erreur connexion à {ip_address}:{port}: {e}")
                raise PeerCommunicationError(
                    f"Connection failed: {e}",
                    peer_uuid=peer_uuid,
                    peer_address=f"{ip_address}:{port}",
                    operation="connect"
                )
    
    async def _resolve_peer(self, peer_uuid: str) -> Tuple[str, int]:
        """
        Résout l'adresse d'un peer depuis son UUID.
        
        Args:
            peer_uuid: UUID du peer
            
        Returns:
            Tuple (ip_address, port)
        """
        if callable(self.peer_resolver):
            result = self.peer_resolver(peer_uuid)
            if asyncio.iscoroutine(result):
                result = await result
            if result is None:
                raise ValueError(f"Resolver returned None for peer: {peer_uuid}")
            self.logger.debug(f"Peer résolu: {peer_uuid} -> {result}")
            return result
        elif hasattr(self.peer_resolver, 'get_peer'):
            peer = self.peer_resolver.get_peer(peer_uuid)
            if peer:
                return (peer['ip_address'], peer['port'])
        
        raise ValueError(f"Cannot resolve peer: {peer_uuid}")
    
    async def _close_connection(self, peer_uuid: str) -> None:
        """
        Ferme une connexion à un peer.
        
        Args:
            peer_uuid: UUID du peer
        """
        async with self._lock:
            if peer_uuid in self._connections:
                conn = self._connections[peer_uuid]
                if conn.writer:
                    conn.writer.close()
                    try:
                        await conn.writer.wait_closed()
                    except Exception:
                        pass
                conn.is_connected = False
                del self._connections[peer_uuid]
                self.logger.debug(f"Connexion fermée: {peer_uuid}")
    
    async def close(self) -> None:
        """
        Ferme toutes les connexions.
        """
        for peer_uuid in list(self._connections.keys()):
            await self._close_connection(peer_uuid)
        self.logger.info("Toutes les connexions fermées")
    
    # ==========================================================================
    # ENVOI/RÉCEPTION RPC
    # ==========================================================================
    
    async def _send_request(
        self,
        conn: PeerConnection,
        method: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Envoie une requête JSON-RPC et attend la réponse.
        
        Args:
            conn: Connexion à utiliser
            method: Nom de la méthode RPC
            params: Paramètres de la méthode
            
        Returns:
            Résultat de la requête
            
        Raises:
            PeerCommunicationError: Si l'envoi/réception échoue
        """
        request_id = str(uuid_module.uuid4())
        
        # Construire la requête
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
            "sender_uuid": self.own_uuid,
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        # Sérialiser
        request_json = json.dumps(request)
        request_bytes = request_json.encode('utf-8')
        
        # Ajouter la longueur en préfixe (4 bytes big-endian)
        length_prefix = len(request_bytes).to_bytes(4, 'big')
        
        try:
            # Envoyer
            conn.writer.write(length_prefix + request_bytes)
            await conn.writer.drain()
            
            self.logger.debug(
                f"Requête envoyée à {conn.peer_uuid}: {method} "
                f"({len(request_bytes)} bytes)"
            )
            
            # Recevoir la réponse
            timeout = self.config['RPC_TIMEOUT_SECONDS']
            
            # Lire la longueur
            length_bytes = await asyncio.wait_for(
                conn.reader.readexactly(4),
                timeout=timeout
            )
            response_length = int.from_bytes(length_bytes, 'big')
            
            # Lire la réponse
            response_bytes = await asyncio.wait_for(
                conn.reader.readexactly(response_length),
                timeout=timeout
            )
            
            response = json.loads(response_bytes.decode('utf-8'))
            
            self.logger.debug(
                f"Réponse reçue de {conn.peer_uuid}: {len(response_bytes)} bytes"
            )
            
            # Vérifier le format de la réponse
            if response.get('id') != request_id:
                raise PeerCommunicationError(
                    "Response ID mismatch",
                    peer_uuid=conn.peer_uuid,
                    operation=method
                )
            
            # Vérifier s'il y a une erreur
            if 'error' in response:
                error = response['error']
                raise PeerCommunicationError(
                    f"RPC error: {error.get('message', 'Unknown error')}",
                    peer_uuid=conn.peer_uuid,
                    operation=method,
                    details={'code': error.get('code'), 'data': error.get('data')}
                )
            
            return response.get('result', {})
            
        except asyncio.TimeoutError:
            conn.is_connected = False
            raise PeerCommunicationError(
                "Request timeout",
                peer_uuid=conn.peer_uuid,
                operation=method
            )
        except asyncio.IncompleteReadError:
            conn.is_connected = False
            raise PeerCommunicationError(
                "Connection closed by peer",
                peer_uuid=conn.peer_uuid,
                operation=method
            )
        except json.JSONDecodeError as e:
            raise PeerCommunicationError(
                f"Invalid JSON response: {e}",
                peer_uuid=conn.peer_uuid,
                operation=method
            )
    
    async def call(
        self,
        peer_uuid: str,
        method: str,
        params: Dict[str, Any],
        ip_address: Optional[str] = None,
        port: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Appelle une méthode RPC sur un peer distant.
        
        Args:
            peer_uuid: UUID du peer cible
            method: Nom de la méthode RPC
            params: Paramètres de la méthode
            ip_address: Adresse IP (optionnel)
            port: Port (optionnel)
            
        Returns:
            Résultat de l'appel RPC
            
        Raises:
            PeerCommunicationError: Si l'appel échoue
        """
        conn = await self._get_connection(peer_uuid, ip_address, port)
        
        try:
            return await self._send_request(conn, method, params)
        except PeerCommunicationError:
            # Fermer la connexion en cas d'erreur
            await self._close_connection(peer_uuid)
            raise
    
    # ==========================================================================
    # MÉTHODES RPC SPÉCIFIQUES
    # ==========================================================================
    
    async def ping(
        self,
        peer_uuid: str,
        ip_address: Optional[str] = None,
        port: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Ping un peer pour vérifier sa disponibilité.
        
        Args:
            peer_uuid: UUID du peer
            ip_address: Adresse IP (optionnel)
            port: Port (optionnel)
            
        Returns:
            {
                'success': bool,
                'peer_uuid': str,
                'latency_ms': float
            }
        """
        start_time = asyncio.get_event_loop().time()
        
        try:
            result = await self.call(
                peer_uuid, 'ping',
                {'timestamp': datetime.utcnow().isoformat()},
                ip_address, port
            )
            
            latency = (asyncio.get_event_loop().time() - start_time) * 1000
            
            return {
                'success': True,
                'peer_uuid': peer_uuid,
                'latency_ms': round(latency, 2),
                'response': result,
            }
            
        except PeerCommunicationError as e:
            return {
                'success': False,
                'peer_uuid': peer_uuid,
                'error': str(e),
            }
    
    async def store_chunk(
        self,
        peer_uuid: str,
        file_uuid: str,
        chunk_idx: int,
        owner_uuid: str,
        chunk_data: bytes,
        content_hash: str,
        ip_address: Optional[str] = None,
        port: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Envoie un chunk à stocker sur un peer distant.
        
        Args:
            peer_uuid: UUID du peer cible
            file_uuid: UUID du fichier
            chunk_idx: Index du chunk
            owner_uuid: UUID du propriétaire
            chunk_data: Données du chunk
            content_hash: Hash SHA-256 du contenu
            ip_address: Adresse IP (optionnel)
            port: Port (optionnel)
            
        Returns:
            {
                'success': bool,
                'stored_at': str (timestamp),
                'expires_at': str (timestamp)
            }
        """
        # Encoder les données en base64 pour le JSON
        chunk_b64 = base64.b64encode(chunk_data).decode('ascii')
        
        # Calculer le hash si non fourni
        if not content_hash:
            content_hash = compute_chunk_hash(chunk_data)
        
        params = {
            'file_uuid': file_uuid,
            'chunk_idx': chunk_idx,
            'owner_uuid': owner_uuid,
            'chunk_data_b64': chunk_b64,
            'content_hash': content_hash,
            'chunk_size': len(chunk_data),
        }
        
        result = await self.call(peer_uuid, 'store_chunk', params, ip_address, port)
        return result
    
    async def get_chunk(
        self,
        peer_uuid: str,
        file_uuid: str,
        chunk_idx: int,
        owner_uuid: str,
        ip_address: Optional[str] = None,
        port: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Récupère un chunk depuis un peer distant.
        
        Args:
            peer_uuid: UUID du peer
            file_uuid: UUID du fichier
            chunk_idx: Index du chunk
            owner_uuid: UUID du propriétaire
            ip_address: Adresse IP (optionnel)
            port: Port (optionnel)
            
        Returns:
            {
                'success': bool,
                'chunk_data': bytes,
                'content_hash': str
            }
        """
        params = {
            'file_uuid': file_uuid,
            'chunk_idx': chunk_idx,
            'owner_uuid': owner_uuid,
        }
        
        result = await self.call(peer_uuid, 'get_chunk', params, ip_address, port)
        
        # Décoder les données
        if result.get('success') and 'chunk_data_b64' in result:
            chunk_data = base64.b64decode(result['chunk_data_b64'])
            result['chunk_data'] = chunk_data
            del result['chunk_data_b64']
        
        return result
    
    async def delete_chunk(
        self,
        peer_uuid: str,
        file_uuid: str,
        chunk_idx: int,
        owner_uuid: str,
        ip_address: Optional[str] = None,
        port: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Demande la suppression d'un chunk sur un peer distant.
        
        Args:
            peer_uuid: UUID du peer
            file_uuid: UUID du fichier
            chunk_idx: Index du chunk
            owner_uuid: UUID du propriétaire
            ip_address: Adresse IP (optionnel)
            port: Port (optionnel)
            
        Returns:
            {'success': bool}
        """
        params = {
            'file_uuid': file_uuid,
            'chunk_idx': chunk_idx,
            'owner_uuid': owner_uuid,
        }
        
        return await self.call(peer_uuid, 'delete_chunk', params, ip_address, port)
    
    async def get_chunk_info(
        self,
        peer_uuid: str,
        file_uuid: str,
        chunk_idx: int,
        owner_uuid: str,
        ip_address: Optional[str] = None,
        port: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Récupère les informations d'un chunk sans le télécharger.
        
        Args:
            peer_uuid: UUID du peer
            file_uuid: UUID du fichier
            chunk_idx: Index du chunk
            owner_uuid: UUID du propriétaire
            ip_address: Adresse IP (optionnel)
            port: Port (optionnel)
            
        Returns:
            {
                'exists': bool,
                'content_hash': str,
                'size_bytes': int,
                'stored_at': str,
                'expires_at': str
            }
        """
        params = {
            'file_uuid': file_uuid,
            'chunk_idx': chunk_idx,
            'owner_uuid': owner_uuid,
        }
        
        return await self.call(peer_uuid, 'get_chunk_info', params, ip_address, port)
    
    async def list_chunks(
        self,
        peer_uuid: str,
        owner_uuid: str,
        file_uuid: Optional[str] = None,
        ip_address: Optional[str] = None,
        port: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Liste les chunks stockés sur un peer.
        
        Args:
            peer_uuid: UUID du peer
            owner_uuid: UUID du propriétaire
            file_uuid: UUID du fichier (optionnel, pour filtrer)
            ip_address: Adresse IP (optionnel)
            port: Port (optionnel)
            
        Returns:
            {
                'chunks': [
                    {'file_uuid': str, 'chunk_idx': int, 'size_bytes': int},
                    ...
                ],
                'total_size': int
            }
        """
        params = {
            'owner_uuid': owner_uuid,
        }
        if file_uuid:
            params['file_uuid'] = file_uuid
        
        return await self.call(peer_uuid, 'list_chunks', params, ip_address, port)
    
    async def get_peer_stats(
        self,
        peer_uuid: str,
        ip_address: Optional[str] = None,
        port: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Récupère les statistiques d'un peer.
        
        Args:
            peer_uuid: UUID du peer
            ip_address: Adresse IP (optionnel)
            port: Port (optionnel)
            
        Returns:
            {
                'peer_uuid': str,
                'chunks_stored': int,
                'total_size_bytes': int,
                'available_space_bytes': int,
                'uptime_seconds': int
            }
        """
        return await self.call(peer_uuid, 'get_stats', {}, ip_address, port)
    
    async def announce_file(
        self,
        peer_uuid: str,
        file_uuid: str,
        owner_uuid: str,
        metadata_json: str,
        ip_address: Optional[str] = None,
        port: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Annonce un fichier à un peer (pour l'indexation distribuée).
        
        Args:
            peer_uuid: UUID du peer
            file_uuid: UUID du fichier
            owner_uuid: UUID du propriétaire
            metadata_json: Métadonnées JSON du fichier
            ip_address: Adresse IP (optionnel)
            port: Port (optionnel)
            
        Returns:
            {'success': bool, 'indexed': bool}
        """
        params = {
            'file_uuid': file_uuid,
            'owner_uuid': owner_uuid,
            'metadata_json': metadata_json,
        }
        
        return await self.call(peer_uuid, 'announce_file', params, ip_address, port)
    
    async def search_file(
        self,
        peer_uuid: str,
        file_uuid: str,
        owner_uuid: str,
        ip_address: Optional[str] = None,
        port: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Recherche un fichier sur un peer (index distribué).
        
        Args:
            peer_uuid: UUID du peer
            file_uuid: UUID du fichier
            owner_uuid: UUID du propriétaire
            ip_address: Adresse IP (optionnel)
            port: Port (optionnel)
            
        Returns:
            {
                'found': bool,
                'metadata_json': str (si trouvé),
                'chunk_locations': [{'chunk_idx': int, 'peer_uuid': str}, ...]
            }
        """
        params = {
            'file_uuid': file_uuid,
            'owner_uuid': owner_uuid,
        }
        
        return await self.call(peer_uuid, 'search_file', params, ip_address, port)
