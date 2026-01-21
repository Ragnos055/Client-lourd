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

# Constantes pour le retry avec backoff exponentiel
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 5  # secondes
DEFAULT_BACKOFF_MULTIPLIER = 2.0
DEFAULT_MAX_RETRY_DELAY = 60  # secondes max entre retries

# Constantes pour le timeout adaptatif
MIN_TIMEOUT_SECONDS = 10  # Timeout minimum
BYTES_PER_SECOND_ESTIMATE = 1024 * 1024  # 1 MB/s estimé (conservateur)
TIMEOUT_OVERHEAD_SECONDS = 10  # Temps additionnel pour le handshake/overhead


def calculate_adaptive_timeout(data_size_bytes: int, base_timeout: int = 30) -> int:
    """
    Calcule un timeout adaptatif basé sur la taille des données.

    Args:
        data_size_bytes: Taille des données à transférer en bytes
        base_timeout: Timeout de base configuré

    Returns:
        Timeout en secondes, adapté à la taille des données
    """
    # Temps estimé pour le transfert (avec marge de sécurité x2)
    transfer_time = (data_size_bytes / BYTES_PER_SECOND_ESTIMATE) * 2

    # Timeout = max(base, transfer_time) + overhead
    adaptive_timeout = max(base_timeout, transfer_time) + TIMEOUT_OVERHEAD_SECONDS

    # Au minimum MIN_TIMEOUT_SECONDS
    return max(int(adaptive_timeout), MIN_TIMEOUT_SECONDS)


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
        self._lock: Optional[asyncio.Lock] = None  # Créé à la demande dans le bon event loop
        self._lock_loop_id: Optional[int] = None   # ID du loop où le lock a été créé

        # Cache d'adresses pour le fallback
        self._address_cache: Dict[str, Tuple[str, int]] = {}

        self.logger.info(f"PeerRPC initialisé pour {own_uuid}")

    def update_peer_address(self, peer_uuid: str, ip_address: str, port: int) -> None:
        """
        Met à jour le cache d'adresse pour un peer.

        Args:
            peer_uuid: UUID du peer
            ip_address: Adresse IP du peer
            port: Port du peer
        """
        self._address_cache[peer_uuid] = (ip_address, port)
        self.logger.debug(f"Cache adresse mis à jour: {peer_uuid} -> {ip_address}:{port}")

    def update_peer_addresses(self, peers: Dict[str, Tuple[str, int]]) -> None:
        """
        Met à jour le cache d'adresses pour plusieurs peers.

        Args:
            peers: Dictionnaire {peer_uuid: (ip_address, port)}
        """
        self._address_cache.update(peers)
        self.logger.debug(f"Cache adresses mis à jour avec {len(peers)} peers")

    def get_cached_address(self, peer_uuid: str) -> Optional[Tuple[str, int]]:
        """
        Récupère l'adresse cachée d'un peer.

        Args:
            peer_uuid: UUID du peer

        Returns:
            Tuple (ip_address, port) ou None si non trouvé
        """
        return self._address_cache.get(peer_uuid)
    
    # ==========================================================================
    # GESTION DES CONNEXIONS
    # ==========================================================================
    
    def _get_lock(self) -> asyncio.Lock:
        """
        Retourne le lock, en le recréant si on est dans un event loop différent.
        Ceci est nécessaire car asyncio.Lock n'est pas thread-safe entre event loops.
        """
        current_loop_id = id(asyncio.get_event_loop())
        if self._lock is None or self._lock_loop_id != current_loop_id:
            self._lock = asyncio.Lock()
            self._lock_loop_id = current_loop_id
            self.logger.debug(f"Lock asyncio recréé pour loop {current_loop_id}")
        return self._lock

    async def _get_connection(
        self,
        peer_uuid: str,
        ip_address: Optional[str] = None,
        port: Optional[int] = None
    ) -> PeerConnection:
        """
        Obtient ou crée une connexion vers un peer avec retry et backoff exponentiel.

        Args:
            peer_uuid: UUID du peer cible
            ip_address: Adresse IP (optionnel si resolver disponible)
            port: Port (optionnel si resolver disponible)

        Returns:
            PeerConnection active

        Raises:
            PeerCommunicationError: Si la connexion échoue après tous les retries
        """
        lock = self._get_lock()
        async with lock:
            # DÉSACTIVER la réutilisation de connexion pour éviter les conflits de concurrence
            # Le bug "readexactly() called while another coroutine is already waiting"
            # se produit quand plusieurs envois simultanés réutilisent la même connexion
            
            # Toujours créer une nouvelle connexion
            # if peer_uuid in self._connections:
            #     conn = self._connections[peer_uuid]
            #     if conn.is_connected:
            #         conn.last_used = datetime.utcnow()
            #         return conn

            # Résoudre l'adresse si nécessaire
            if ip_address is None or port is None:
                resolved_address = await self._resolve_peer_with_fallback(peer_uuid)
                if resolved_address:
                    ip_address, port = resolved_address
                else:
                    raise PeerCommunicationError(
                        "Cannot resolve peer address: no resolver and no cached address",
                        peer_uuid=peer_uuid
                    )

            # Paramètres de retry depuis la config
            max_retries = self.config.get('MAX_CONNECTION_RETRIES', DEFAULT_MAX_RETRIES)
            retry_delay = self.config.get('CONNECTION_RETRY_DELAY_SECONDS', DEFAULT_RETRY_DELAY)
            timeout = self.config['RPC_TIMEOUT_SECONDS']

            last_error = None

            # Boucle de retry avec backoff exponentiel
            for attempt in range(max_retries + 1):
                try:
                    if attempt > 0:
                        # Calculer le délai avec backoff exponentiel
                        current_delay = min(
                            retry_delay * (DEFAULT_BACKOFF_MULTIPLIER ** (attempt - 1)),
                            DEFAULT_MAX_RETRY_DELAY
                        )
                        self.logger.info(
                            f"Retry {attempt}/{max_retries} pour {ip_address}:{port} "
                            f"dans {current_delay:.1f}s..."
                        )
                        await asyncio.sleep(current_delay)

                    self.logger.info(
                        f"Connexion à {ip_address}:{port} (timeout={timeout}s, "
                        f"tentative {attempt + 1}/{max_retries + 1})..."
                    )
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
                    last_error = PeerCommunicationError(
                        "Connection timeout",
                        peer_uuid=peer_uuid,
                        peer_address=f"{ip_address}:{port}",
                        operation="connect"
                    )
                    self.logger.warning(
                        f"✗ Timeout connexion à {ip_address}:{port} "
                        f"(tentative {attempt + 1}/{max_retries + 1})"
                    )
                except ConnectionRefusedError:
                    last_error = PeerCommunicationError(
                        "Connection refused",
                        peer_uuid=peer_uuid,
                        peer_address=f"{ip_address}:{port}",
                        operation="connect"
                    )
                    self.logger.warning(
                        f"✗ Connexion refusée par {ip_address}:{port} "
                        f"(tentative {attempt + 1}/{max_retries + 1})"
                    )
                except OSError as e:
                    # Erreurs réseau (network unreachable, etc.)
                    last_error = PeerCommunicationError(
                        f"Network error: {e}",
                        peer_uuid=peer_uuid,
                        peer_address=f"{ip_address}:{port}",
                        operation="connect"
                    )
                    self.logger.warning(
                        f"✗ Erreur réseau vers {ip_address}:{port}: {e} "
                        f"(tentative {attempt + 1}/{max_retries + 1})"
                    )
                except Exception as e:
                    last_error = PeerCommunicationError(
                        f"Connection failed: {e}",
                        peer_uuid=peer_uuid,
                        peer_address=f"{ip_address}:{port}",
                        operation="connect"
                    )
                    self.logger.warning(
                        f"✗ Erreur connexion à {ip_address}:{port}: {e} "
                        f"(tentative {attempt + 1}/{max_retries + 1})"
                    )

            # Tous les retries ont échoué
            self.logger.error(
                f"✗ Échec définitif connexion à {ip_address}:{port} "
                f"après {max_retries + 1} tentatives"
            )
            raise last_error

    async def _resolve_peer_with_fallback(self, peer_uuid: str) -> Optional[Tuple[str, int]]:
        """
        Résout l'adresse d'un peer avec plusieurs stratégies de fallback.

        Args:
            peer_uuid: UUID du peer à résoudre

        Returns:
            Tuple (ip_address, port) ou None si non résolu
        """
        # 1. Essayer le resolver principal
        if self.peer_resolver:
            try:
                resolved = await self._resolve_peer(peer_uuid)
                if resolved:
                    self.logger.debug(f"Peer {peer_uuid} résolu via resolver: {resolved}")
                    # Mettre en cache
                    self._address_cache[peer_uuid] = resolved
                    return resolved
            except Exception as e:
                self.logger.warning(f"Resolver principal a échoué pour {peer_uuid}: {e}")

        # 2. Fallback: vérifier le cache local
        if hasattr(self, '_address_cache') and peer_uuid in self._address_cache:
            cached = self._address_cache[peer_uuid]
            self.logger.debug(f"Peer {peer_uuid} résolu depuis le cache: {cached}")
            return cached

        # 3. Fallback: essayer de parser l'UUID comme ip:port (format legacy)
        if ':' in peer_uuid:
            try:
                parts = peer_uuid.rsplit(':', 1)
                if len(parts) == 2:
                    ip = parts[0]
                    port = int(parts[1])
                    self.logger.debug(f"Peer {peer_uuid} résolu depuis le format ip:port")
                    return (ip, port)
            except ValueError:
                pass

        self.logger.error(f"Impossible de résoudre l'adresse du peer: {peer_uuid}")
        return None
    
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
        params: Dict[str, Any],
        data_size_hint: int = 0
    ) -> Dict[str, Any]:
        """
        Envoie une requête JSON-RPC et attend la réponse.

        Args:
            conn: Connexion à utiliser
            method: Nom de la méthode RPC
            params: Paramètres de la méthode
            data_size_hint: Indication de la taille des données pour timeout adaptatif

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

        # Calculer le timeout adaptatif basé sur la taille des données
        base_timeout = self.config['RPC_TIMEOUT_SECONDS']
        # Utiliser la taille du request si pas de hint, sinon utiliser le hint
        effective_size = max(len(request_bytes), data_size_hint)
        timeout = calculate_adaptive_timeout(effective_size, base_timeout)

        self.logger.debug(
            f"Timeout adaptatif calculé: {timeout}s pour {effective_size} bytes "
            f"(base: {base_timeout}s)"
        )

        try:
            # Envoyer
            conn.writer.write(length_prefix + request_bytes)
            await conn.writer.drain()

            self.logger.debug(
                f"Requête envoyée à {conn.peer_uuid}: {method} "
                f"({len(request_bytes)} bytes)"
            )

            # Recevoir la réponse avec timeout adaptatif
            # Lire la longueur
            length_bytes = await asyncio.wait_for(
                conn.reader.readexactly(4),
                timeout=timeout
            )
            response_length = int.from_bytes(length_bytes, 'big')

            # Recalculer le timeout pour la réponse si elle est grande
            response_timeout = calculate_adaptive_timeout(response_length, base_timeout)

            # Lire la réponse
            response_bytes = await asyncio.wait_for(
                conn.reader.readexactly(response_length),
                timeout=response_timeout
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
        port: Optional[int] = None,
        data_size_hint: int = 0
    ) -> Dict[str, Any]:
        """
        Appelle une méthode RPC sur un peer distant.

        Args:
            peer_uuid: UUID du peer cible
            method: Nom de la méthode RPC
            params: Paramètres de la méthode
            ip_address: Adresse IP (optionnel)
            port: Port (optionnel)
            data_size_hint: Indication de taille pour le timeout adaptatif

        Returns:
            Résultat de l'appel RPC

        Raises:
            PeerCommunicationError: Si l'appel échoue
        """
        conn = await self._get_connection(peer_uuid, ip_address, port)

        try:
            return await self._send_request(conn, method, params, data_size_hint)
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

        # Utiliser la taille du chunk (base64 = ~1.33x la taille originale)
        data_size_hint = int(len(chunk_data) * 1.4)

        result = await self.call(
            peer_uuid, 'store_chunk', params, ip_address, port,
            data_size_hint=data_size_hint
        )
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
