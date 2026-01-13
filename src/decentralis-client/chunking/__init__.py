"""
Module de chunking pour Decentralis.

Ce module fournit un système complet de fragmentation de fichiers
avec codes de correction d'erreurs Reed-Solomon et Local Reconstruction
Codes (LRC) pour le stockage distribué P2P.

Composants principaux:
    - ChunkingManager: Orchestrateur principal pour le chunking
    - ReplicationManager: Gestion de la relocalisation des chunks
    - ChunkStore: Stockage local des chunks
    - ChunkDatabase: Métadonnées SQLite
    - ReedSolomonEncoder: Encodage/décodage RS + LRC
    - PeerRPC: Client RPC pour communication P2P
    - ChunkNetworkServer: Serveur P2P pour requêtes entrantes

Configuration:
    Le module utilise des variables d'environnement pour la configuration:
    - DECENTRALIS_RETENTION_DAYS: Durée de rétention (défaut: 30)
    - DECENTRALIS_CHUNK_SIZE: Taille des chunks (défaut: 64KB)
    - DECENTRALIS_RS_K: Chunks de données (défaut: 6)
    - DECENTRALIS_RS_M: Chunks de parité (défaut: 4)

Example:
    >>> import asyncio
    >>> from chunking import ChunkingManager, ChunkDatabase, ChunkStore
    >>> 
    >>> async def main():
    ...     db = ChunkDatabase("/path/to/db")
    ...     store = ChunkStore("/path/to/chunks", db)
    ...     mgr = ChunkingManager("my-peer-uuid", db, store)
    ...     
    ...     # Chunker un fichier
    ...     result = await mgr.chunk_file(
    ...         "/path/to/file.pdf",
    ...         "my-peer-uuid"
    ...     )
    ...     print(f"File UUID: {result['file_uuid']}")
    ...     
    ...     await mgr.shutdown()
    ... 
    >>> asyncio.run(main())

Architecture:
    Le système utilise une architecture en couches:
    
    1. Couche Orchestration (chunking_mgr.py, replication_mgr.py)
       - Coordination des opérations de haut niveau
       - Gestion du cycle de vie des fichiers
    
    2. Couche Encodage (reed_solomon.py)
       - Encodage Reed-Solomon (K=6, M=4)
       - Local Reconstruction Codes (LRC)
    
    3. Couche Stockage (chunk_store.py, chunk_db.py)
       - Stockage local sur disque
       - Métadonnées SQLite
    
    4. Couche Réseau (peer_rpc.py, chunk_net.py)
       - Communication P2P JSON-RPC
       - Serveur TCP asynchrone

Voir ARCHITECTURE-CHUNKING.md pour plus de détails.
"""

# Configuration
from .config import CHUNKING_CONFIG, get_config

# Modèles de données
from .models import (
    LocalGroup,
    ChunkMetadata,
    StoredChunk,
    ChunkAssignment,
    ReplicationTask,
    PeerInfo,
    compute_chunk_hash,
)

# Exceptions
from .exceptions import (
    ChunkingException,
    ChunkEncodingError,
    ChunkDecodingError,
    ChunkValidationError,
    ChunkStorageError,
    ChunkDatabaseError,
    PeerCommunicationError,
    InsufficientChunksError,
    ChunkNotFoundError,
    FileMetadataNotFoundError,
    ReplicationError,
    ConfigurationError,
    SignatureValidationError,
)

# Composants principaux
from .chunk_db import ChunkDatabase
from .chunk_store import ChunkStore
from .reed_solomon import ReedSolomonEncoder
from .chunking_mgr import ChunkingManager
from .replication_mgr import ReplicationManager

# Réseau P2P
from .peer_rpc import PeerRPC
from .chunk_net import ChunkNetworkServer


__version__ = "1.0.0"

__all__ = [
    # Configuration
    "CHUNKING_CONFIG",
    "get_config",
    
    # Modèles
    "LocalGroup",
    "ChunkMetadata",
    "StoredChunk",
    "ChunkAssignment",
    "ReplicationTask",
    "PeerInfo",
    "compute_chunk_hash",
    
    # Exceptions
    "ChunkingException",
    "ChunkEncodingError",
    "ChunkDecodingError",
    "ChunkValidationError",
    "ChunkStorageError",
    "ChunkDatabaseError",
    "PeerCommunicationError",
    "InsufficientChunksError",
    "ChunkNotFoundError",
    "FileMetadataNotFoundError",
    "ReplicationError",
    "ConfigurationError",
    "SignatureValidationError",
    
    # Composants
    "ChunkDatabase",
    "ChunkStore",
    "ReedSolomonEncoder",
    "ChunkingManager",
    "ReplicationManager",
    
    # Réseau
    "PeerRPC",
    "ChunkNetworkServer",
]
