"""
Modèles de données pour le système de chunking P2P.

Ce module définit les dataclasses utilisées pour représenter
les métadonnées de fichiers, chunks, assignations et tâches
de réplication.

Example:
    >>> from chunking.models import ChunkMetadata, StoredChunk
    >>> metadata = ChunkMetadata(
    ...     file_uuid="abc-123",
    ...     owner_uuid="user-456",
    ...     original_filename="container.dat"
    ... )
    >>> metadata.file_uuid
    'abc-123'
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import json
import hashlib


@dataclass
class LocalGroup:
    """
    Groupe local pour LRC (Local Reconstruction Codes).
    
    Un groupe local contient plusieurs chunks de données et un symbole
    de récupération local qui permet de reconstruire un chunk manquant
    dans le groupe sans avoir besoin des autres groupes.
    
    Attributes:
        group_id: Identifiant unique du groupe
        chunk_indices: Liste des indices des chunks dans ce groupe
        local_recovery_idx: Index du symbole de récupération local
        
    Example:
        >>> group = LocalGroup(group_id=0, chunk_indices=[0, 1], local_recovery_idx=10)
        >>> group.group_id
        0
        >>> len(group.chunk_indices)
        2
    """
    group_id: int
    chunk_indices: List[int] = field(default_factory=list)
    local_recovery_idx: int = -1
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour sérialisation JSON."""
        return {
            'group_id': self.group_id,
            'chunk_indices': self.chunk_indices,
            'local_recovery_idx': self.local_recovery_idx,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LocalGroup':
        """Crée une instance depuis un dictionnaire."""
        return cls(
            group_id=data['group_id'],
            chunk_indices=data.get('chunk_indices', []),
            local_recovery_idx=data.get('local_recovery_idx', -1),
        )


@dataclass
class ChunkMetadata:
    """
    Métadonnées complètes d'un fichier découpé en chunks.
    
    Cette classe contient toutes les informations nécessaires pour
    reconstituer un fichier à partir de ses chunks distribués.
    
    Attributes:
        file_uuid: Identifiant unique du fichier chunké
        owner_uuid: UUID du propriétaire du fichier
        original_filename: Nom original du fichier
        file_path: Chemin complet du fichier (dossier/sub/fichier.txt)
        original_hash: Hash SHA-256 du fichier original
        original_size: Taille originale en bytes
        total_chunks: Nombre total de chunks (data + parité)
        data_chunks: Nombre de chunks de données (K)
        parity_chunks: Nombre de chunks de parité (M)
        chunk_size: Taille d'un chunk en bytes
        algorithm: Algorithme utilisé ('reed-solomon+lrc')
        local_groups: Liste des groupes locaux LRC
        global_recovery_indices: Indices des symboles de récupération globaux
        created_at: Date de création
        expires_at: Date d'expiration (rétention 30 jours)
        chunk_hashes: Dictionnaire {chunk_idx: hash} pour validation
        
    Example:
        >>> metadata = ChunkMetadata(
        ...     file_uuid="abc-123",
        ...     owner_uuid="user-456",
        ...     original_filename="test.dat",
        ...     file_path="dossier/test.dat",
        ...     original_hash="sha256...",
        ...     original_size=1048576,
        ...     total_chunks=10,
        ...     data_chunks=6,
        ...     parity_chunks=4,
        ...     chunk_size=174763
        ... )
        >>> metadata.total_chunks
        10
    """
    file_uuid: str
    owner_uuid: str
    original_filename: str = ""
    file_path: str = ""
    original_hash: str = ""
    original_size: int = 0
    total_chunks: int = 0
    data_chunks: int = 6
    parity_chunks: int = 4
    chunk_size: int = 0
    algorithm: str = "reed-solomon+lrc"
    local_groups: List[LocalGroup] = field(default_factory=list)
    global_recovery_indices: List[int] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    chunk_hashes: Dict[int, str] = field(default_factory=dict)
    
    def __post_init__(self):
        """Calcule expires_at si non défini."""
        if self.expires_at is None:
            self.expires_at = self.created_at + timedelta(days=30)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convertit en dictionnaire pour sérialisation JSON.
        
        Returns:
            Dictionnaire sérialisable en JSON
        """
        return {
            'file_uuid': self.file_uuid,
            'owner_uuid': self.owner_uuid,
            'original_filename': self.original_filename,
            'file_path': self.file_path,
            'original_hash': self.original_hash,
            'original_size': self.original_size,
            'total_chunks': self.total_chunks,
            'data_chunks': self.data_chunks,
            'parity_chunks': self.parity_chunks,
            'chunk_size': self.chunk_size,
            'algorithm': self.algorithm,
            'local_groups': [g.to_dict() for g in self.local_groups],
            'global_recovery_indices': self.global_recovery_indices,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'chunk_hashes': self.chunk_hashes,
        }
    
    def to_json(self) -> str:
        """
        Sérialise en JSON.
        
        Returns:
            Chaîne JSON
            
        Example:
            >>> metadata = ChunkMetadata(file_uuid="test", owner_uuid="user")
            >>> json_str = metadata.to_json()
            >>> '"file_uuid": "test"' in json_str
            True
        """
        return json.dumps(self.to_dict(), indent=2)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ChunkMetadata':
        """
        Crée une instance depuis un dictionnaire.
        
        Args:
            data: Dictionnaire avec les données
            
        Returns:
            Instance de ChunkMetadata
        """
        local_groups = [
            LocalGroup.from_dict(g) for g in data.get('local_groups', [])
        ]
        
        created_at = data.get('created_at')
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif created_at is None:
            created_at = datetime.utcnow()
            
        expires_at = data.get('expires_at')
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at)
            
        return cls(
            file_uuid=data['file_uuid'],
            owner_uuid=data['owner_uuid'],
            original_filename=data.get('original_filename', ''),
            file_path=data.get('file_path', ''),
            original_hash=data.get('original_hash', ''),
            original_size=data.get('original_size', 0),
            total_chunks=data.get('total_chunks', 0),
            data_chunks=data.get('data_chunks', 6),
            parity_chunks=data.get('parity_chunks', 4),
            chunk_size=data.get('chunk_size', 0),
            algorithm=data.get('algorithm', 'reed-solomon+lrc'),
            local_groups=local_groups,
            global_recovery_indices=data.get('global_recovery_indices', []),
            created_at=created_at,
            expires_at=expires_at,
            chunk_hashes=data.get('chunk_hashes', {}),
        )
    
    @classmethod
    def from_json(cls, json_str: str) -> 'ChunkMetadata':
        """
        Désérialise depuis JSON.
        
        Args:
            json_str: Chaîne JSON
            
        Returns:
            Instance de ChunkMetadata
            
        Example:
            >>> json_str = '{"file_uuid": "test", "owner_uuid": "user"}'
            >>> metadata = ChunkMetadata.from_json(json_str)
            >>> metadata.file_uuid
            'test'
        """
        data = json.loads(json_str)
        return cls.from_dict(data)
    
    def is_expired(self) -> bool:
        """Vérifie si le fichier est expiré."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at
    
    def get_required_chunks_for_recovery(self) -> int:
        """Retourne le nombre minimum de chunks pour reconstruction."""
        return self.data_chunks


@dataclass
class StoredChunk:
    """
    Représente un chunk stocké localement sur le disque.
    
    Cette classe contient les informations sur un chunk individuel
    stocké sur le peer local.
    
    Attributes:
        file_uuid: UUID du fichier parent
        chunk_idx: Index du chunk (0-based)
        owner_uuid: UUID du propriétaire
        local_path: Chemin complet sur le disque local
        content_hash: Hash SHA-256 du contenu du chunk
        chunk_type: Type de chunk ('data', 'parity', 'local_recovery', 'global_recovery')
        size_bytes: Taille du chunk en bytes
        stored_at: Date de stockage
        expires_at: Date d'expiration
        last_accessed: Dernier accès
        status: État du chunk ('verified', 'pending', 'corrupted')
        
    Example:
        >>> chunk = StoredChunk(
        ...     file_uuid="file-123",
        ...     chunk_idx=0,
        ...     owner_uuid="user-456",
        ...     local_path="/path/to/chunk",
        ...     content_hash="sha256..."
        ... )
        >>> chunk.status
        'verified'
    """
    file_uuid: str
    chunk_idx: int
    owner_uuid: str
    local_path: str
    content_hash: str
    chunk_type: str = 'data'
    size_bytes: int = 0
    stored_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    last_accessed: Optional[datetime] = None
    status: str = 'verified'
    
    def __post_init__(self):
        """Initialise expires_at si non défini."""
        if self.expires_at is None:
            self.expires_at = self.stored_at + timedelta(days=30)
        if self.last_accessed is None:
            self.last_accessed = self.stored_at
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            'file_uuid': self.file_uuid,
            'chunk_idx': self.chunk_idx,
            'owner_uuid': self.owner_uuid,
            'local_path': self.local_path,
            'content_hash': self.content_hash,
            'chunk_type': self.chunk_type,
            'size_bytes': self.size_bytes,
            'stored_at': self.stored_at.isoformat() if self.stored_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'last_accessed': self.last_accessed.isoformat() if self.last_accessed else None,
            'status': self.status,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StoredChunk':
        """Crée une instance depuis un dictionnaire."""
        stored_at = data.get('stored_at')
        if isinstance(stored_at, str):
            stored_at = datetime.fromisoformat(stored_at)
        elif stored_at is None:
            stored_at = datetime.utcnow()
            
        expires_at = data.get('expires_at')
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at)
            
        last_accessed = data.get('last_accessed')
        if isinstance(last_accessed, str):
            last_accessed = datetime.fromisoformat(last_accessed)
            
        return cls(
            file_uuid=data['file_uuid'],
            chunk_idx=data['chunk_idx'],
            owner_uuid=data['owner_uuid'],
            local_path=data['local_path'],
            content_hash=data['content_hash'],
            chunk_type=data.get('chunk_type', 'data'),
            size_bytes=data.get('size_bytes', 0),
            stored_at=stored_at,
            expires_at=expires_at,
            last_accessed=last_accessed,
            status=data.get('status', 'verified'),
        )
    
    def is_expired(self) -> bool:
        """Vérifie si le chunk est expiré."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at
    
    def is_valid(self) -> bool:
        """Vérifie si le chunk est valide (non corrompu et non expiré)."""
        return self.status == 'verified' and not self.is_expired()


@dataclass
class ChunkAssignment:
    """
    Attribution d'un chunk à un peer pour stockage.
    
    Représente l'assignation d'un chunk spécifique à un peer
    du réseau pour la distribution.
    
    Attributes:
        file_uuid: UUID du fichier parent
        chunk_idx: Index du chunk
        owner_uuid: UUID du propriétaire
        peer_uuid: UUID du peer assigné
        assigned_at: Date d'assignation
        confirmed_at: Date de confirmation (quand le peer a confirmé le stockage)
        status: État ('pending', 'confirmed', 'failed', 'relocated')
        attempts: Nombre de tentatives d'envoi
        failure_reason: Raison de l'échec si status='failed'
        
    Example:
        >>> assignment = ChunkAssignment(
        ...     file_uuid="file-123",
        ...     chunk_idx=0,
        ...     owner_uuid="user-456",
        ...     peer_uuid="peer-789"
        ... )
        >>> assignment.status
        'pending'
    """
    file_uuid: str
    chunk_idx: int
    owner_uuid: str
    peer_uuid: str
    assigned_at: datetime = field(default_factory=datetime.utcnow)
    confirmed_at: Optional[datetime] = None
    status: str = 'pending'
    attempts: int = 0
    failure_reason: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            'file_uuid': self.file_uuid,
            'chunk_idx': self.chunk_idx,
            'owner_uuid': self.owner_uuid,
            'peer_uuid': self.peer_uuid,
            'assigned_at': self.assigned_at.isoformat() if self.assigned_at else None,
            'confirmed_at': self.confirmed_at.isoformat() if self.confirmed_at else None,
            'status': self.status,
            'attempts': self.attempts,
            'failure_reason': self.failure_reason,
            'error_message': self.failure_reason,  # Alias pour la GUI
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ChunkAssignment':
        """Crée une instance depuis un dictionnaire."""
        assigned_at = data.get('assigned_at')
        if isinstance(assigned_at, str):
            assigned_at = datetime.fromisoformat(assigned_at)
        elif assigned_at is None:
            assigned_at = datetime.utcnow()
            
        confirmed_at = data.get('confirmed_at')
        if isinstance(confirmed_at, str):
            confirmed_at = datetime.fromisoformat(confirmed_at)
            
        return cls(
            file_uuid=data['file_uuid'],
            chunk_idx=data['chunk_idx'],
            owner_uuid=data['owner_uuid'],
            peer_uuid=data['peer_uuid'],
            assigned_at=assigned_at,
            confirmed_at=confirmed_at,
            status=data.get('status', 'pending'),
            attempts=data.get('attempts', 0),
            failure_reason=data.get('failure_reason'),
        )
    
    def mark_confirmed(self) -> None:
        """Marque l'assignation comme confirmée."""
        self.status = 'confirmed'
        self.confirmed_at = datetime.utcnow()
    
    def mark_failed(self, reason: str) -> None:
        """Marque l'assignation comme échouée."""
        self.status = 'failed'
        self.failure_reason = reason
        self.attempts += 1
    
    def is_confirmed(self) -> bool:
        """Vérifie si l'assignation est confirmée."""
        return self.status == 'confirmed'


@dataclass
class ReplicationTask:
    """
    Tâche de relocalisation d'un chunk.
    
    Quand un peer se déconnecte, ses chunks doivent être relocalisés
    vers d'autres peers. Cette classe représente une tâche de réplication.
    
    Attributes:
        file_uuid: UUID du fichier parent
        chunk_idx: Index du chunk à relocaliser
        owner_uuid: UUID du propriétaire
        source_peer_uuid: UUID du peer source (déconnecté ou défaillant)
        target_peer_uuid: UUID du peer cible (nouveau stockage)
        reason: Raison de la relocalisation ('peer_disconnected', 'chunk_corrupted', etc.)
        created_at: Date de création de la tâche
        completed_at: Date de complétion
        attempts: Nombre de tentatives
        status: État ('pending', 'in_progress', 'completed', 'failed')
        error_message: Message d'erreur si échec
        
    Example:
        >>> task = ReplicationTask(
        ...     file_uuid="file-123",
        ...     chunk_idx=0,
        ...     owner_uuid="user-456",
        ...     source_peer_uuid="peer-old",
        ...     target_peer_uuid="peer-new",
        ...     reason="peer_disconnected"
        ... )
        >>> task.status
        'pending'
    """
    file_uuid: str
    chunk_idx: int
    owner_uuid: str
    source_peer_uuid: str
    target_peer_uuid: Optional[str] = None
    reason: str = 'peer_disconnected'
    created_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    attempts: int = 0
    status: str = 'pending'
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            'file_uuid': self.file_uuid,
            'chunk_idx': self.chunk_idx,
            'owner_uuid': self.owner_uuid,
            'source_peer_uuid': self.source_peer_uuid,
            'target_peer_uuid': self.target_peer_uuid,
            'reason': self.reason,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'attempts': self.attempts,
            'status': self.status,
            'error_message': self.error_message,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ReplicationTask':
        """Crée une instance depuis un dictionnaire."""
        created_at = data.get('created_at')
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif created_at is None:
            created_at = datetime.utcnow()
            
        completed_at = data.get('completed_at')
        if isinstance(completed_at, str):
            completed_at = datetime.fromisoformat(completed_at)
            
        return cls(
            file_uuid=data['file_uuid'],
            chunk_idx=data['chunk_idx'],
            owner_uuid=data['owner_uuid'],
            source_peer_uuid=data['source_peer_uuid'],
            target_peer_uuid=data.get('target_peer_uuid'),
            reason=data.get('reason', 'peer_disconnected'),
            created_at=created_at,
            completed_at=completed_at,
            attempts=data.get('attempts', 0),
            status=data.get('status', 'pending'),
            error_message=data.get('error_message'),
        )
    
    def start(self) -> None:
        """Marque la tâche comme en cours."""
        self.status = 'in_progress'
        self.attempts += 1
    
    def complete(self) -> None:
        """Marque la tâche comme complétée."""
        self.status = 'completed'
        self.completed_at = datetime.utcnow()
    
    def fail(self, error_message: str) -> None:
        """Marque la tâche comme échouée."""
        self.status = 'failed'
        self.error_message = error_message
    
    def is_retriable(self, max_attempts: int = 3) -> bool:
        """Vérifie si la tâche peut être réessayée."""
        return self.status == 'failed' and self.attempts < max_attempts


@dataclass
class PeerInfo:
    """
    Informations sur un peer du réseau.
    
    Attributes:
        uuid: UUID unique du peer
        ip_address: Adresse IP
        port: Port d'écoute
        reliability_score: Score de fiabilité (0.0 à 1.0)
        chunks_stored: Nombre de chunks stockés par ce peer
        last_seen: Dernière fois que le peer a été vu
        first_seen: Première fois que le peer a été vu
        is_online: Si le peer est actuellement en ligne
        storage_available: Espace de stockage disponible en bytes
        
    Example:
        >>> peer = PeerInfo(uuid="peer-123", ip_address="192.168.1.10", port=6000)
        >>> peer.reliability_score
        0.5
    """
    uuid: str
    ip_address: str
    port: int
    reliability_score: float = 0.5
    chunks_stored: int = 0
    last_seen: datetime = field(default_factory=datetime.utcnow)
    first_seen: datetime = field(default_factory=datetime.utcnow)
    is_online: bool = True
    storage_available: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            'uuid': self.uuid,
            'ip_address': self.ip_address,
            'port': self.port,
            'reliability_score': self.reliability_score,
            'chunks_stored': self.chunks_stored,
            'last_seen': self.last_seen.isoformat() if self.last_seen else None,
            'first_seen': self.first_seen.isoformat() if self.first_seen else None,
            'is_online': self.is_online,
            'storage_available': self.storage_available,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PeerInfo':
        """Crée une instance depuis un dictionnaire."""
        last_seen = data.get('last_seen')
        if isinstance(last_seen, str):
            last_seen = datetime.fromisoformat(last_seen)
        elif last_seen is None:
            last_seen = datetime.utcnow()
            
        first_seen = data.get('first_seen')
        if isinstance(first_seen, str):
            first_seen = datetime.fromisoformat(first_seen)
        elif first_seen is None:
            first_seen = datetime.utcnow()
            
        return cls(
            uuid=data['uuid'],
            ip_address=data['ip_address'],
            port=data['port'],
            reliability_score=data.get('reliability_score', 0.5),
            chunks_stored=data.get('chunks_stored', 0),
            last_seen=last_seen,
            first_seen=first_seen,
            is_online=data.get('is_online', True),
            storage_available=data.get('storage_available', 0),
        )
    
    def update_reliability(self, success: bool, weight: float = 0.1) -> None:
        """
        Met à jour le score de fiabilité après une opération.
        
        Args:
            success: Si l'opération a réussi
            weight: Poids de cette observation (0.0-1.0)
        """
        if success:
            self.reliability_score = min(1.0, self.reliability_score + weight)
        else:
            self.reliability_score = max(0.0, self.reliability_score - weight)
    
    def mark_online(self) -> None:
        """Marque le peer comme en ligne."""
        self.is_online = True
        self.last_seen = datetime.utcnow()
    
    def mark_offline(self) -> None:
        """Marque le peer comme hors ligne."""
        self.is_online = False
    
    def get_address(self) -> str:
        """Retourne l'adresse complète ip:port."""
        return f"{self.ip_address}:{self.port}"


def compute_chunk_hash(data: bytes) -> str:
    """
    Calcule le hash SHA-256 d'un chunk.
    
    Args:
        data: Données du chunk
        
    Returns:
        Hash hexadécimal
        
    Example:
        >>> compute_chunk_hash(b'test data')
        '916f0027a575074ce72a331777c3478d6513f786a591bd892da1a577bf2335f9'
    """
    return hashlib.sha256(data).hexdigest()
