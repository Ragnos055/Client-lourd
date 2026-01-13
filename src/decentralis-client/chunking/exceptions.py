"""
Exceptions personnalisées pour le système de chunking P2P.

Ce module définit une hiérarchie d'exceptions spécifiques au chunking
pour une gestion d'erreurs précise et informative.

Example:
    >>> from chunking.exceptions import ChunkEncodingError
    >>> raise ChunkEncodingError("Reed-Solomon encoding failed for chunk 0")
    Traceback (most recent call last):
    ...
    chunking.exceptions.ChunkEncodingError: Reed-Solomon encoding failed for chunk 0
"""

from typing import Optional, List, Dict, Any


class ChunkingException(Exception):
    """
    Exception de base pour toutes les erreurs de chunking.
    
    Toutes les exceptions spécifiques au chunking héritent de cette classe,
    permettant de capturer toutes les erreurs de chunking avec un seul except.
    
    Attributes:
        message: Message d'erreur descriptif
        details: Dictionnaire avec des informations supplémentaires
        
    Example:
        >>> try:
        ...     raise ChunkingException("Something went wrong", {"file_uuid": "abc"})
        ... except ChunkingException as e:
        ...     print(e.message)
        Something went wrong
    """
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        """
        Initialise l'exception.
        
        Args:
            message: Message d'erreur
            details: Informations supplémentaires optionnelles
        """
        self.message = message
        self.details = details or {}
        super().__init__(self._format_message())
    
    def _format_message(self) -> str:
        """Formate le message avec les détails."""
        if self.details:
            details_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            return f"{self.message} [{details_str}]"
        return self.message


class ChunkEncodingError(ChunkingException):
    """
    Erreur lors de l'encodage Reed-Solomon.
    
    Levée quand l'encodage d'un fichier en chunks avec Reed-Solomon échoue.
    
    Example:
        >>> raise ChunkEncodingError(
        ...     "Failed to encode data",
        ...     {"file_uuid": "abc-123", "data_size": 1048576}
        ... )  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        ...
        ChunkEncodingError: Failed to encode data [file_uuid=abc-123, data_size=1048576]
    """
    pass


class ChunkDecodingError(ChunkingException):
    """
    Erreur lors du décodage Reed-Solomon.
    
    Levée quand la reconstruction d'un fichier depuis ses chunks échoue.
    Cela peut arriver si trop de chunks sont manquants ou corrompus.
    
    Attributes:
        available_chunks: Nombre de chunks disponibles
        required_chunks: Nombre de chunks requis pour la reconstruction
        
    Example:
        >>> raise ChunkDecodingError(
        ...     "Not enough chunks for recovery",
        ...     {"available": 4, "required": 6}
        ... )  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        ...
        ChunkDecodingError: Not enough chunks for recovery [available=4, required=6]
    """
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None,
                 available_chunks: int = 0, required_chunks: int = 0):
        """
        Initialise l'exception.
        
        Args:
            message: Message d'erreur
            details: Informations supplémentaires
            available_chunks: Nombre de chunks disponibles
            required_chunks: Nombre de chunks requis
        """
        self.available_chunks = available_chunks
        self.required_chunks = required_chunks
        super().__init__(message, details)


class ChunkValidationError(ChunkingException):
    """
    Erreur de validation d'un chunk.
    
    Levée quand le hash ou la signature d'un chunk ne correspond pas
    à ce qui était attendu. Indique une corruption ou une tentative
    de falsification.
    
    Attributes:
        expected_hash: Hash attendu
        actual_hash: Hash calculé
        chunk_idx: Index du chunk concerné
        
    Example:
        >>> raise ChunkValidationError(
        ...     "Hash mismatch",
        ...     {"chunk_idx": 0, "expected": "abc...", "actual": "def..."}
        ... )  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        ...
        ChunkValidationError: Hash mismatch [chunk_idx=0, expected=abc..., actual=def...]
    """
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None,
                 expected_hash: Optional[str] = None, actual_hash: Optional[str] = None,
                 chunk_idx: Optional[int] = None):
        """
        Initialise l'exception.
        
        Args:
            message: Message d'erreur
            details: Informations supplémentaires
            expected_hash: Hash attendu
            actual_hash: Hash calculé
            chunk_idx: Index du chunk
        """
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash
        self.chunk_idx = chunk_idx
        super().__init__(message, details)


class ChunkStorageError(ChunkingException):
    """
    Erreur de stockage sur disque.
    
    Levée lors d'erreurs d'écriture ou de lecture de chunks sur le disque.
    Peut indiquer un problème d'espace, de permissions, ou de corruption.
    
    Attributes:
        path: Chemin du fichier concerné
        operation: Opération tentée ('read', 'write', 'delete')
        
    Example:
        >>> raise ChunkStorageError(
        ...     "Failed to write chunk",
        ...     {"path": "/tmp/chunk.dat", "operation": "write"}
        ... )  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        ...
        ChunkStorageError: Failed to write chunk [path=/tmp/chunk.dat, operation=write]
    """
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None,
                 path: Optional[str] = None, operation: Optional[str] = None):
        """
        Initialise l'exception.
        
        Args:
            message: Message d'erreur
            details: Informations supplémentaires
            path: Chemin du fichier
            operation: Opération tentée
        """
        self.path = path
        self.operation = operation
        if path and 'path' not in (details or {}):
            details = details or {}
            details['path'] = path
        if operation and 'operation' not in (details or {}):
            details = details or {}
            details['operation'] = operation
        super().__init__(message, details)


class ChunkDatabaseError(ChunkingException):
    """
    Erreur de base de données.
    
    Levée lors d'erreurs SQLite: requêtes invalides, contraintes
    violées, corruption de la base, etc.
    
    Attributes:
        query: Requête SQL qui a échoué
        sqlite_error: Message d'erreur SQLite original
        
    Example:
        >>> raise ChunkDatabaseError(
        ...     "Failed to insert chunk metadata",
        ...     {"table": "chunks", "sqlite_error": "UNIQUE constraint failed"}
        ... )  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        ...
        ChunkDatabaseError: Failed to insert chunk metadata [table=chunks, ...]
    """
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None,
                 query: Optional[str] = None, sqlite_error: Optional[str] = None):
        """
        Initialise l'exception.
        
        Args:
            message: Message d'erreur
            details: Informations supplémentaires
            query: Requête SQL qui a échoué
            sqlite_error: Message d'erreur SQLite
        """
        self.query = query
        self.sqlite_error = sqlite_error
        if sqlite_error and 'sqlite_error' not in (details or {}):
            details = details or {}
            details['sqlite_error'] = sqlite_error
        super().__init__(message, details)


class PeerCommunicationError(ChunkingException):
    """
    Erreur de communication avec un peer.
    
    Levée lors d'erreurs réseau: connexion refusée, timeout,
    protocole invalide, etc.
    
    Attributes:
        peer_uuid: UUID du peer concerné
        peer_address: Adresse IP:port du peer
        operation: Opération tentée ('send_chunk', 'get_chunk', 'ping')
        
    Example:
        >>> raise PeerCommunicationError(
        ...     "Connection refused",
        ...     {"peer_uuid": "peer-123", "address": "192.168.1.10:6000"}
        ... )  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        ...
        PeerCommunicationError: Connection refused [peer_uuid=peer-123, ...]
    """
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None,
                 peer_uuid: Optional[str] = None, peer_address: Optional[str] = None,
                 operation: Optional[str] = None):
        """
        Initialise l'exception.
        
        Args:
            message: Message d'erreur
            details: Informations supplémentaires
            peer_uuid: UUID du peer
            peer_address: Adresse du peer
            operation: Opération tentée
        """
        self.peer_uuid = peer_uuid
        self.peer_address = peer_address
        self.operation = operation
        details = details or {}
        if peer_uuid and 'peer_uuid' not in details:
            details['peer_uuid'] = peer_uuid
        if peer_address and 'address' not in details:
            details['address'] = peer_address
        super().__init__(message, details)


class InsufficientChunksError(ChunkingException):
    """
    Pas assez de chunks pour reconstruire le fichier.
    
    Levée quand le nombre de chunks disponibles est inférieur
    au minimum requis par Reed-Solomon pour la reconstruction.
    
    Attributes:
        file_uuid: UUID du fichier concerné
        available_chunks: Nombre de chunks disponibles
        required_chunks: Nombre minimum requis (K pour Reed-Solomon)
        missing_indices: Liste des indices de chunks manquants
        
    Example:
        >>> raise InsufficientChunksError(
        ...     "Cannot reconstruct file",
        ...     {"file_uuid": "abc-123"},
        ...     available_chunks=4,
        ...     required_chunks=6,
        ...     missing_indices=[2, 5, 7, 8]
        ... )  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        ...
        InsufficientChunksError: Cannot reconstruct file [file_uuid=abc-123]
    """
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None,
                 file_uuid: Optional[str] = None, available_chunks: int = 0,
                 required_chunks: int = 0, missing_indices: Optional[List[int]] = None):
        """
        Initialise l'exception.
        
        Args:
            message: Message d'erreur
            details: Informations supplémentaires
            file_uuid: UUID du fichier
            available_chunks: Nombre de chunks disponibles
            required_chunks: Nombre minimum requis
            missing_indices: Liste des indices manquants
        """
        self.file_uuid = file_uuid
        self.available_chunks = available_chunks
        self.required_chunks = required_chunks
        self.missing_indices = missing_indices or []
        details = details or {}
        details['available'] = available_chunks
        details['required'] = required_chunks
        if file_uuid and 'file_uuid' not in details:
            details['file_uuid'] = file_uuid
        super().__init__(message, details)


class ChunkNotFoundError(ChunkingException):
    """
    Chunk non trouvé.
    
    Levée quand un chunk spécifique n'est pas trouvé localement
    ou sur aucun peer du réseau.
    
    Attributes:
        file_uuid: UUID du fichier parent
        chunk_idx: Index du chunk manquant
        
    Example:
        >>> raise ChunkNotFoundError(
        ...     "Chunk not found locally or on network",
        ...     {"file_uuid": "abc-123", "chunk_idx": 5}
        ... )  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        ...
        ChunkNotFoundError: Chunk not found locally or on network [file_uuid=abc-123, chunk_idx=5]
    """
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None,
                 file_uuid: Optional[str] = None, chunk_idx: Optional[int] = None):
        """
        Initialise l'exception.
        
        Args:
            message: Message d'erreur
            details: Informations supplémentaires
            file_uuid: UUID du fichier
            chunk_idx: Index du chunk
        """
        self.file_uuid = file_uuid
        self.chunk_idx = chunk_idx
        details = details or {}
        if file_uuid and 'file_uuid' not in details:
            details['file_uuid'] = file_uuid
        if chunk_idx is not None and 'chunk_idx' not in details:
            details['chunk_idx'] = chunk_idx
        super().__init__(message, details)


class FileMetadataNotFoundError(ChunkingException):
    """
    Métadonnées de fichier non trouvées.
    
    Levée quand les métadonnées d'un fichier chunké ne sont pas
    trouvées dans la base de données.
    
    Example:
        >>> raise FileMetadataNotFoundError(
        ...     "File metadata not found",
        ...     {"file_uuid": "abc-123"}
        ... )  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        ...
        FileMetadataNotFoundError: File metadata not found [file_uuid=abc-123]
    """
    pass


class ReplicationError(ChunkingException):
    """
    Erreur de réplication.
    
    Levée lors d'erreurs dans le processus de relocalisation
    de chunks vers d'autres peers.
    
    Attributes:
        source_peer: UUID du peer source
        target_peer: UUID du peer cible
        chunk_info: Informations sur le chunk concerné
        
    Example:
        >>> raise ReplicationError(
        ...     "Failed to relocate chunk",
        ...     {"source": "peer-old", "target": "peer-new", "chunk_idx": 0}
        ... )  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        ...
        ReplicationError: Failed to relocate chunk [source=peer-old, target=peer-new, chunk_idx=0]
    """
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None,
                 source_peer: Optional[str] = None, target_peer: Optional[str] = None):
        """
        Initialise l'exception.
        
        Args:
            message: Message d'erreur
            details: Informations supplémentaires
            source_peer: UUID du peer source
            target_peer: UUID du peer cible
        """
        self.source_peer = source_peer
        self.target_peer = target_peer
        details = details or {}
        if source_peer and 'source' not in details:
            details['source'] = source_peer
        if target_peer and 'target' not in details:
            details['target'] = target_peer
        super().__init__(message, details)


class ConfigurationError(ChunkingException):
    """
    Erreur de configuration.
    
    Levée quand la configuration du chunking est invalide.
    
    Example:
        >>> raise ConfigurationError(
        ...     "Invalid Reed-Solomon parameters",
        ...     {"K": 260, "M": 10, "reason": "K + M > 255"}
        ... )  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        ...
        ConfigurationError: Invalid Reed-Solomon parameters [K=260, M=10, reason=K + M > 255]
    """
    pass


class SignatureValidationError(ChunkingException):
    """
    Erreur de validation de signature.
    
    Levée quand la signature cryptographique d'un chunk
    ne peut pas être validée.
    
    Example:
        >>> raise SignatureValidationError(
        ...     "Invalid chunk signature",
        ...     {"chunk_idx": 0, "peer_uuid": "peer-123"}
        ... )  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        ...
        SignatureValidationError: Invalid chunk signature [chunk_idx=0, peer_uuid=peer-123]
    """
    pass


# Alias pour compatibilité
ChunkError = ChunkingException
