"""
Base de données SQLite pour le système de chunking P2P.

Ce module gère la persistance des métadonnées de fichiers, chunks,
localisations, historique de réplication et informations sur les peers.

Example:
    >>> from chunking.chunk_db import ChunkDatabase
    >>> db = ChunkDatabase(":memory:")
    >>> # Utiliser la base de données
    >>> db.close()
"""

import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
from pathlib import Path

from .models import (
    ChunkMetadata, StoredChunk, ChunkAssignment,
    ReplicationTask, LocalGroup, PeerInfo
)
from .exceptions import ChunkDatabaseError


class ChunkDatabase:
    """
    Couche d'accès à la base de données SQLite pour le chunking.
    
    Cette classe gère toutes les opérations de persistance pour:
    - Métadonnées des fichiers chunkés
    - Chunks stockés localement
    - Localisations des chunks sur le réseau
    - Historique de réplication
    - Informations sur les peers
    
    Attributes:
        db_path: Chemin vers le fichier SQLite
        conn: Connexion SQLite active
        logger: Logger pour le debug
        
    Example:
        >>> db = ChunkDatabase(":memory:")
        >>> db.verify_integrity()
        True
        >>> db.close()
    """
    
    def __init__(self, db_path: str, logger: Optional[logging.Logger] = None):
        """
        Initialise la base de données.
        
        Args:
            db_path: Chemin du fichier SQLite. Utiliser ":memory:" pour une base en mémoire.
            logger: Logger optionnel pour le debug
            
        Raises:
            ChunkDatabaseError: Si l'initialisation échoue
        """
        self.db_path = db_path
        self.logger = logger or logging.getLogger(__name__)
        self.conn: Optional[sqlite3.Connection] = None
        self._in_transaction = False
        
        try:
            # Créer le répertoire parent si nécessaire
            if db_path != ":memory:":
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            
            # Ouvrir la connexion
            self.conn = sqlite3.connect(db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            
            # Activer les foreign keys
            self.conn.execute("PRAGMA foreign_keys = ON")
            
            # Créer les tables
            self._create_tables()
            
            self.logger.info(f"Base de données initialisée: {db_path}")
            
        except sqlite3.Error as e:
            raise ChunkDatabaseError(
                "Failed to initialize database",
                {"path": db_path},
                sqlite_error=str(e)
            )
    
    def __enter__(self) -> 'ChunkDatabase':
        """Support du context manager."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Ferme la connexion à la sortie du context manager."""
        self.close()
    
    def _create_tables(self) -> None:
        """Crée toutes les tables si elles n'existent pas."""
        cursor = self.conn.cursor()
        
        # Table: file_metadata - Métadonnées des fichiers
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS file_metadata (
                file_uuid TEXT PRIMARY KEY,
                owner_uuid TEXT NOT NULL,
                original_filename TEXT,
                original_hash TEXT,
                original_size INTEGER DEFAULT 0,
                total_chunks INTEGER DEFAULT 0,
                data_chunks INTEGER DEFAULT 6,
                parity_chunks INTEGER DEFAULT 4,
                chunk_size INTEGER DEFAULT 0,
                algorithm TEXT DEFAULT 'reed-solomon+lrc',
                local_groups_json TEXT,
                global_recovery_indices_json TEXT,
                chunk_hashes_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP
            )
        """)
        
        # Table: chunks - Chunks stockés localement
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_uuid TEXT NOT NULL,
                chunk_idx INTEGER NOT NULL,
                owner_uuid TEXT NOT NULL,
                local_path TEXT UNIQUE NOT NULL,
                content_hash TEXT NOT NULL,
                chunk_type TEXT DEFAULT 'data',
                size_bytes INTEGER DEFAULT 0,
                stored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                last_accessed TIMESTAMP,
                status TEXT DEFAULT 'verified',
                UNIQUE(file_uuid, chunk_idx, owner_uuid)
            )
        """)
        
        # Table: chunk_locations - Index de réplication (où sont les chunks)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chunk_locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_uuid TEXT NOT NULL,
                chunk_idx INTEGER NOT NULL,
                owner_uuid TEXT NOT NULL,
                peer_uuid TEXT NOT NULL,
                assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                confirmed_at TIMESTAMP,
                status TEXT DEFAULT 'pending',
                attempts INTEGER DEFAULT 0,
                failure_reason TEXT,
                UNIQUE(file_uuid, chunk_idx, owner_uuid, peer_uuid)
            )
        """)
        
        # Table: replication_history - Historique des relocalisations
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS replication_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_uuid TEXT NOT NULL,
                chunk_idx INTEGER NOT NULL,
                owner_uuid TEXT NOT NULL,
                source_peer_uuid TEXT NOT NULL,
                target_peer_uuid TEXT,
                reason TEXT DEFAULT 'peer_disconnected',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                attempts INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                error_message TEXT
            )
        """)
        
        # Table: peers - Informations sur les peers
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS peers (
                uuid TEXT PRIMARY KEY,
                ip_address TEXT NOT NULL,
                port INTEGER NOT NULL,
                reliability_score REAL DEFAULT 0.5,
                chunks_stored INTEGER DEFAULT 0,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_online INTEGER DEFAULT 1,
                storage_available INTEGER DEFAULT 0
            )
        """)
        
        # Table: chunk_assignments - Assignations chunk → peer (pour la distribution initiale)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chunk_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_uuid TEXT NOT NULL,
                chunk_idx INTEGER NOT NULL,
                owner_uuid TEXT NOT NULL,
                peer_uuid TEXT NOT NULL,
                assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                confirmed_at TIMESTAMP,
                status TEXT DEFAULT 'pending',
                attempts INTEGER DEFAULT 0,
                failure_reason TEXT,
                UNIQUE(file_uuid, chunk_idx, owner_uuid, peer_uuid)
            )
        """)
        
        # Table: local_groups - Structure LRC
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS local_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_uuid TEXT NOT NULL,
                group_id INTEGER NOT NULL,
                chunk_indices_json TEXT NOT NULL,
                local_recovery_idx INTEGER NOT NULL,
                UNIQUE(file_uuid, group_id)
            )
        """)
        
        # Table: global_recovery - Indices globaux LRC
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS global_recovery (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_uuid TEXT NOT NULL,
                recovery_idx INTEGER NOT NULL,
                UNIQUE(file_uuid, recovery_idx)
            )
        """)
        
        # Index pour les requêtes fréquentes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_file_owner 
            ON chunks(file_uuid, owner_uuid)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_expires 
            ON chunks(expires_at)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_status 
            ON chunks(status)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_locations_file 
            ON chunk_locations(file_uuid, owner_uuid)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_locations_peer 
            ON chunk_locations(peer_uuid)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_locations_status 
            ON chunk_locations(status)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_peers_online 
            ON peers(is_online)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_replication_status 
            ON replication_history(status)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_file_metadata_owner 
            ON file_metadata(owner_uuid)
        """)
        
        self.conn.commit()
        self.logger.debug("Tables créées avec succès")
    
    # ==========================================================================
    # TRANSACTIONS
    # ==========================================================================
    
    def begin_transaction(self) -> None:
        """Démarre une transaction explicite."""
        if self._in_transaction:
            self.logger.warning("Transaction déjà en cours")
            return
        self.conn.execute("BEGIN TRANSACTION")
        self._in_transaction = True
        self.logger.debug("Transaction démarrée")
    
    def commit(self) -> None:
        """Valide la transaction en cours."""
        if not self._in_transaction:
            self.logger.warning("Pas de transaction à valider")
            return
        self.conn.commit()
        self._in_transaction = False
        self.logger.debug("Transaction validée")
    
    def rollback(self) -> None:
        """Annule la transaction en cours."""
        if not self._in_transaction:
            self.logger.warning("Pas de transaction à annuler")
            return
        self.conn.rollback()
        self._in_transaction = False
        self.logger.debug("Transaction annulée")
    
    @contextmanager
    def transaction(self):
        """
        Context manager pour les transactions.
        
        Example:
            >>> with db.transaction():
            ...     db.add_chunk(chunk1)
            ...     db.add_chunk(chunk2)
        """
        self.begin_transaction()
        try:
            yield
            self.commit()
        except Exception:
            self.rollback()
            raise
    
    # ==========================================================================
    # FILE_METADATA
    # ==========================================================================
    
    def add_file_metadata(self, metadata: ChunkMetadata) -> None:
        """
        Ajoute les métadonnées d'un fichier.
        
        Args:
            metadata: Métadonnées du fichier à ajouter
            
        Raises:
            ChunkDatabaseError: Si l'insertion échoue
        """
        import json
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO file_metadata (
                    file_uuid, owner_uuid, original_filename, original_hash,
                    original_size, total_chunks, data_chunks, parity_chunks,
                    chunk_size, algorithm, local_groups_json,
                    global_recovery_indices_json, chunk_hashes_json,
                    created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                metadata.file_uuid,
                metadata.owner_uuid,
                metadata.original_filename,
                metadata.original_hash,
                metadata.original_size,
                metadata.total_chunks,
                metadata.data_chunks,
                metadata.parity_chunks,
                metadata.chunk_size,
                metadata.algorithm,
                json.dumps([g.to_dict() for g in metadata.local_groups]),
                json.dumps(metadata.global_recovery_indices),
                json.dumps(metadata.chunk_hashes),
                metadata.created_at.isoformat() if metadata.created_at else None,
                metadata.expires_at.isoformat() if metadata.expires_at else None,
            ))
            if not self._in_transaction:
                self.conn.commit()
            self.logger.debug(f"Métadonnées ajoutées: {metadata.file_uuid}")
        except sqlite3.Error as e:
            raise ChunkDatabaseError(
                "Failed to add file metadata",
                {"file_uuid": metadata.file_uuid},
                sqlite_error=str(e)
            )
    
    def get_file_metadata(self, file_uuid: str) -> Optional[ChunkMetadata]:
        """
        Récupère les métadonnées d'un fichier.
        
        Args:
            file_uuid: UUID du fichier
            
        Returns:
            ChunkMetadata ou None si non trouvé
        """
        import json
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM file_metadata WHERE file_uuid = ?
        """, (file_uuid,))
        row = cursor.fetchone()
        
        if not row:
            return None
        
        # Reconstruire l'objet
        local_groups = []
        if row['local_groups_json']:
            local_groups = [
                LocalGroup.from_dict(g) 
                for g in json.loads(row['local_groups_json'])
            ]
        
        global_indices = []
        if row['global_recovery_indices_json']:
            global_indices = json.loads(row['global_recovery_indices_json'])
        
        chunk_hashes = {}
        if row['chunk_hashes_json']:
            chunk_hashes = json.loads(row['chunk_hashes_json'])
        
        created_at = None
        if row['created_at']:
            created_at = datetime.fromisoformat(row['created_at'])
        
        expires_at = None
        if row['expires_at']:
            expires_at = datetime.fromisoformat(row['expires_at'])
        
        return ChunkMetadata(
            file_uuid=row['file_uuid'],
            owner_uuid=row['owner_uuid'],
            original_filename=row['original_filename'] or '',
            original_hash=row['original_hash'] or '',
            original_size=row['original_size'] or 0,
            total_chunks=row['total_chunks'] or 0,
            data_chunks=row['data_chunks'] or 6,
            parity_chunks=row['parity_chunks'] or 4,
            chunk_size=row['chunk_size'] or 0,
            algorithm=row['algorithm'] or 'reed-solomon+lrc',
            local_groups=local_groups,
            global_recovery_indices=global_indices,
            created_at=created_at,
            expires_at=expires_at,
            chunk_hashes=chunk_hashes,
        )
    
    def list_files_by_owner(self, owner_uuid: str) -> List[ChunkMetadata]:
        """
        Liste tous les fichiers d'un propriétaire.
        
        Args:
            owner_uuid: UUID du propriétaire
            
        Returns:
            Liste de ChunkMetadata
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT file_uuid FROM file_metadata WHERE owner_uuid = ?
        """, (owner_uuid,))
        
        files = []
        for row in cursor.fetchall():
            metadata = self.get_file_metadata(row['file_uuid'])
            if metadata:
                files.append(metadata)
        
        return files
    
    def delete_file_metadata(self, file_uuid: str) -> None:
        """
        Supprime les métadonnées d'un fichier.
        
        Args:
            file_uuid: UUID du fichier à supprimer
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            DELETE FROM file_metadata WHERE file_uuid = ?
        """, (file_uuid,))
        if not self._in_transaction:
            self.conn.commit()
        self.logger.debug(f"Métadonnées supprimées: {file_uuid}")
    
    def get_file_by_uuid(self, file_uuid: str, owner_uuid: str) -> Optional[ChunkMetadata]:
        """
        Récupère un fichier par UUID et propriétaire.
        
        Args:
            file_uuid: UUID du fichier
            owner_uuid: UUID du propriétaire
            
        Returns:
            ChunkMetadata ou None
        """
        metadata = self.get_file_metadata(file_uuid)
        if metadata and metadata.owner_uuid == owner_uuid:
            return metadata
        return None
    
    def update_file_metadata(self, metadata: ChunkMetadata) -> None:
        """
        Met à jour les métadonnées d'un fichier existant.
        
        Args:
            metadata: Métadonnées mises à jour
        """
        import json
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                UPDATE file_metadata SET
                    original_filename = ?,
                    original_hash = ?,
                    original_size = ?,
                    total_chunks = ?,
                    data_chunks = ?,
                    parity_chunks = ?,
                    chunk_size = ?,
                    algorithm = ?,
                    local_groups_json = ?,
                    global_recovery_indices_json = ?,
                    chunk_hashes_json = ?,
                    expires_at = ?
                WHERE file_uuid = ?
            """, (
                metadata.original_filename,
                metadata.original_hash,
                metadata.original_size,
                metadata.total_chunks,
                metadata.data_chunks,
                metadata.parity_chunks,
                metadata.chunk_size,
                metadata.algorithm,
                json.dumps([g.to_dict() for g in metadata.local_groups]),
                json.dumps(metadata.global_recovery_indices),
                json.dumps(metadata.chunk_hashes),
                metadata.expires_at.isoformat() if metadata.expires_at else None,
                metadata.file_uuid,
            ))
            if not self._in_transaction:
                self.conn.commit()
        except sqlite3.Error as e:
            raise ChunkDatabaseError(
                "Failed to update file metadata",
                {"file_uuid": metadata.file_uuid},
                sqlite_error=str(e)
            )
    
    # ==========================================================================
    # CHUNKS
    # ==========================================================================
    
    def add_chunk(self, stored_chunk: StoredChunk) -> int:
        """
        Ajoute un chunk stocké localement.
        
        Args:
            stored_chunk: Chunk à ajouter
            
        Returns:
            ID du chunk inséré
            
        Raises:
            ChunkDatabaseError: Si l'insertion échoue
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO chunks (
                    file_uuid, chunk_idx, owner_uuid, local_path,
                    content_hash, chunk_type, size_bytes, stored_at,
                    expires_at, last_accessed, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                stored_chunk.file_uuid,
                stored_chunk.chunk_idx,
                stored_chunk.owner_uuid,
                stored_chunk.local_path,
                stored_chunk.content_hash,
                stored_chunk.chunk_type,
                stored_chunk.size_bytes,
                stored_chunk.stored_at.isoformat() if stored_chunk.stored_at else None,
                stored_chunk.expires_at.isoformat() if stored_chunk.expires_at else None,
                stored_chunk.last_accessed.isoformat() if stored_chunk.last_accessed else None,
                stored_chunk.status,
            ))
            if not self._in_transaction:
                self.conn.commit()
            self.logger.debug(f"Chunk ajouté: {stored_chunk.file_uuid}#{stored_chunk.chunk_idx}")
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            # Le chunk existe déjà, on met à jour
            self.update_chunk_status(
                stored_chunk.file_uuid,
                stored_chunk.chunk_idx,
                stored_chunk.owner_uuid,
                stored_chunk.status
            )
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT id FROM chunks 
                WHERE file_uuid = ? AND chunk_idx = ? AND owner_uuid = ?
            """, (stored_chunk.file_uuid, stored_chunk.chunk_idx, stored_chunk.owner_uuid))
            row = cursor.fetchone()
            return row['id'] if row else -1
        except sqlite3.Error as e:
            raise ChunkDatabaseError(
                "Failed to add chunk",
                {"file_uuid": stored_chunk.file_uuid, "chunk_idx": stored_chunk.chunk_idx},
                sqlite_error=str(e)
            )
    
    def get_chunk(self, file_uuid: str, chunk_idx: int, owner_uuid: str) -> Optional[StoredChunk]:
        """
        Récupère un chunk spécifique.
        
        Args:
            file_uuid: UUID du fichier
            chunk_idx: Index du chunk
            owner_uuid: UUID du propriétaire
            
        Returns:
            StoredChunk ou None
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM chunks 
            WHERE file_uuid = ? AND chunk_idx = ? AND owner_uuid = ?
        """, (file_uuid, chunk_idx, owner_uuid))
        row = cursor.fetchone()
        
        if not row:
            return None
        
        return self._row_to_stored_chunk(row)
    
    def _row_to_stored_chunk(self, row: sqlite3.Row) -> StoredChunk:
        """Convertit une row SQLite en StoredChunk."""
        stored_at = None
        if row['stored_at']:
            stored_at = datetime.fromisoformat(row['stored_at'])
        
        expires_at = None
        if row['expires_at']:
            expires_at = datetime.fromisoformat(row['expires_at'])
        
        last_accessed = None
        if row['last_accessed']:
            last_accessed = datetime.fromisoformat(row['last_accessed'])
        
        return StoredChunk(
            file_uuid=row['file_uuid'],
            chunk_idx=row['chunk_idx'],
            owner_uuid=row['owner_uuid'],
            local_path=row['local_path'],
            content_hash=row['content_hash'],
            chunk_type=row['chunk_type'] or 'data',
            size_bytes=row['size_bytes'] or 0,
            stored_at=stored_at,
            expires_at=expires_at,
            last_accessed=last_accessed,
            status=row['status'] or 'verified',
        )
    
    def list_chunks_by_file(self, file_uuid: str, owner_uuid: str) -> List[StoredChunk]:
        """
        Liste tous les chunks d'un fichier.
        
        Args:
            file_uuid: UUID du fichier
            owner_uuid: UUID du propriétaire
            
        Returns:
            Liste de StoredChunk
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM chunks 
            WHERE file_uuid = ? AND owner_uuid = ?
            ORDER BY chunk_idx
        """, (file_uuid, owner_uuid))
        
        return [self._row_to_stored_chunk(row) for row in cursor.fetchall()]
    
    def list_chunks_by_owner(self, owner_uuid: str) -> List[StoredChunk]:
        """
        Liste tous les chunks d'un propriétaire.
        
        Args:
            owner_uuid: UUID du propriétaire
            
        Returns:
            Liste de StoredChunk
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM chunks WHERE owner_uuid = ? ORDER BY file_uuid, chunk_idx
        """, (owner_uuid,))
        
        return [self._row_to_stored_chunk(row) for row in cursor.fetchall()]
    
    def update_chunk_status(self, file_uuid: str, chunk_idx: int, 
                           owner_uuid: str, status: str) -> None:
        """
        Met à jour le statut d'un chunk.
        
        Args:
            file_uuid: UUID du fichier
            chunk_idx: Index du chunk
            owner_uuid: UUID du propriétaire
            status: Nouveau statut ('verified', 'pending', 'corrupted')
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE chunks SET status = ?
            WHERE file_uuid = ? AND chunk_idx = ? AND owner_uuid = ?
        """, (status, file_uuid, chunk_idx, owner_uuid))
        if not self._in_transaction:
            self.conn.commit()
    
    def delete_chunk(self, file_uuid: str, chunk_idx: int, owner_uuid: str) -> None:
        """
        Supprime un chunk de la base.
        
        Args:
            file_uuid: UUID du fichier
            chunk_idx: Index du chunk
            owner_uuid: UUID du propriétaire
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            DELETE FROM chunks 
            WHERE file_uuid = ? AND chunk_idx = ? AND owner_uuid = ?
        """, (file_uuid, chunk_idx, owner_uuid))
        if not self._in_transaction:
            self.conn.commit()
        self.logger.debug(f"Chunk supprimé: {file_uuid}#{chunk_idx}")
    
    def get_expired_chunks(self) -> List[StoredChunk]:
        """
        Récupère tous les chunks expirés.
        
        Returns:
            Liste de StoredChunk expirés
        """
        cursor = self.conn.cursor()
        now = datetime.utcnow().isoformat()
        cursor.execute("""
            SELECT * FROM chunks WHERE expires_at < ?
        """, (now,))
        
        return [self._row_to_stored_chunk(row) for row in cursor.fetchall()]
    
    def cleanup_expired_chunks(self) -> int:
        """
        Supprime tous les chunks expirés.
        
        Returns:
            Nombre de chunks supprimés
        """
        cursor = self.conn.cursor()
        now = datetime.utcnow().isoformat()
        cursor.execute("""
            DELETE FROM chunks WHERE expires_at < ?
        """, (now,))
        count = cursor.rowcount
        if not self._in_transaction:
            self.conn.commit()
        self.logger.info(f"Chunks expirés nettoyés: {count}")
        return count
    
    def update_last_accessed(self, file_uuid: str, chunk_idx: int, owner_uuid: str) -> None:
        """
        Met à jour la date de dernier accès d'un chunk.
        
        Args:
            file_uuid: UUID du fichier
            chunk_idx: Index du chunk
            owner_uuid: UUID du propriétaire
        """
        cursor = self.conn.cursor()
        now = datetime.utcnow().isoformat()
        cursor.execute("""
            UPDATE chunks SET last_accessed = ?
            WHERE file_uuid = ? AND chunk_idx = ? AND owner_uuid = ?
        """, (now, file_uuid, chunk_idx, owner_uuid))
        if not self._in_transaction:
            self.conn.commit()
    
    # ==========================================================================
    # CHUNK_LOCATIONS
    # ==========================================================================
    
    def add_location(self, assignment: ChunkAssignment) -> int:
        """
        Ajoute une localisation de chunk.
        
        Args:
            assignment: Assignation chunk → peer
            
        Returns:
            ID de la localisation
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO chunk_locations (
                    file_uuid, chunk_idx, owner_uuid, peer_uuid,
                    assigned_at, confirmed_at, status, attempts, failure_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                assignment.file_uuid,
                assignment.chunk_idx,
                assignment.owner_uuid,
                assignment.peer_uuid,
                assignment.assigned_at.isoformat() if assignment.assigned_at else None,
                assignment.confirmed_at.isoformat() if assignment.confirmed_at else None,
                assignment.status,
                assignment.attempts,
                assignment.failure_reason,
            ))
            if not self._in_transaction:
                self.conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            # La localisation existe déjà, on met à jour
            self.update_location_status(
                assignment.file_uuid,
                assignment.chunk_idx,
                assignment.owner_uuid,
                assignment.peer_uuid,
                assignment.status,
                assignment.failure_reason
            )
            return -1
        except sqlite3.Error as e:
            raise ChunkDatabaseError(
                "Failed to add location",
                {"file_uuid": assignment.file_uuid, "peer_uuid": assignment.peer_uuid},
                sqlite_error=str(e)
            )
    
    def get_locations(self, file_uuid: str, chunk_idx: int, 
                     owner_uuid: str) -> List[ChunkAssignment]:
        """
        Récupère toutes les localisations d'un chunk.
        
        Args:
            file_uuid: UUID du fichier
            chunk_idx: Index du chunk
            owner_uuid: UUID du propriétaire
            
        Returns:
            Liste de ChunkAssignment
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM chunk_locations
            WHERE file_uuid = ? AND chunk_idx = ? AND owner_uuid = ?
        """, (file_uuid, chunk_idx, owner_uuid))
        
        return [self._row_to_chunk_assignment(row) for row in cursor.fetchall()]
    
    def _row_to_chunk_assignment(self, row: sqlite3.Row) -> ChunkAssignment:
        """Convertit une row SQLite en ChunkAssignment."""
        assigned_at = None
        if row['assigned_at']:
            assigned_at = datetime.fromisoformat(row['assigned_at'])
        
        confirmed_at = None
        if row['confirmed_at']:
            confirmed_at = datetime.fromisoformat(row['confirmed_at'])
        
        return ChunkAssignment(
            file_uuid=row['file_uuid'],
            chunk_idx=row['chunk_idx'],
            owner_uuid=row['owner_uuid'],
            peer_uuid=row['peer_uuid'],
            assigned_at=assigned_at,
            confirmed_at=confirmed_at,
            status=row['status'] or 'pending',
            attempts=row['attempts'] or 0,
            failure_reason=row['failure_reason'],
        )
    
    def get_locations_by_peer(self, peer_uuid: str) -> List[ChunkAssignment]:
        """
        Récupère toutes les localisations d'un peer.
        
        Args:
            peer_uuid: UUID du peer
            
        Returns:
            Liste de ChunkAssignment
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM chunk_locations WHERE peer_uuid = ?
        """, (peer_uuid,))
        
        return [self._row_to_chunk_assignment(row) for row in cursor.fetchall()]
    
    def get_locations_by_file(self, file_uuid: str, owner_uuid: str) -> List[ChunkAssignment]:
        """
        Récupère toutes les localisations d'un fichier.
        
        Args:
            file_uuid: UUID du fichier
            owner_uuid: UUID du propriétaire
            
        Returns:
            Liste de ChunkAssignment
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM chunk_locations 
            WHERE file_uuid = ? AND owner_uuid = ?
            ORDER BY chunk_idx
        """, (file_uuid, owner_uuid))
        
        return [self._row_to_chunk_assignment(row) for row in cursor.fetchall()]
    
    def update_location_status(self, file_uuid: str, chunk_idx: int,
                              owner_uuid: str, peer_uuid: str,
                              status: str, failure_reason: Optional[str] = None) -> None:
        """
        Met à jour le statut d'une localisation.
        
        Args:
            file_uuid: UUID du fichier
            chunk_idx: Index du chunk
            owner_uuid: UUID du propriétaire
            peer_uuid: UUID du peer
            status: Nouveau statut
            failure_reason: Raison de l'échec optionnelle
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE chunk_locations SET status = ?, failure_reason = ?
            WHERE file_uuid = ? AND chunk_idx = ? AND owner_uuid = ? AND peer_uuid = ?
        """, (status, failure_reason, file_uuid, chunk_idx, owner_uuid, peer_uuid))
        if not self._in_transaction:
            self.conn.commit()
    
    def confirm_location(self, file_uuid: str, chunk_idx: int,
                        owner_uuid: str, peer_uuid: str) -> None:
        """
        Confirme une localisation (chunk reçu par le peer).
        
        Args:
            file_uuid: UUID du fichier
            chunk_idx: Index du chunk
            owner_uuid: UUID du propriétaire
            peer_uuid: UUID du peer
        """
        cursor = self.conn.cursor()
        now = datetime.utcnow().isoformat()
        cursor.execute("""
            UPDATE chunk_locations 
            SET status = 'confirmed', confirmed_at = ?
            WHERE file_uuid = ? AND chunk_idx = ? AND owner_uuid = ? AND peer_uuid = ?
        """, (now, file_uuid, chunk_idx, owner_uuid, peer_uuid))
        if not self._in_transaction:
            self.conn.commit()
    
    def get_pending_locations(self) -> List[ChunkAssignment]:
        """
        Récupère toutes les localisations en attente.
        
        Returns:
            Liste de ChunkAssignment avec status='pending'
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM chunk_locations WHERE status = 'pending'
        """)
        
        return [self._row_to_chunk_assignment(row) for row in cursor.fetchall()]
    
    def delete_location(self, file_uuid: str, chunk_idx: int,
                       owner_uuid: str, peer_uuid: str) -> None:
        """
        Supprime une localisation.
        
        Args:
            file_uuid: UUID du fichier
            chunk_idx: Index du chunk
            owner_uuid: UUID du propriétaire
            peer_uuid: UUID du peer
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            DELETE FROM chunk_locations
            WHERE file_uuid = ? AND chunk_idx = ? AND owner_uuid = ? AND peer_uuid = ?
        """, (file_uuid, chunk_idx, owner_uuid, peer_uuid))
        if not self._in_transaction:
            self.conn.commit()
    
    # ==========================================================================
    # REPLICATION_HISTORY
    # ==========================================================================
    
    def add_replication_task(self, task: ReplicationTask) -> int:
        """
        Ajoute une tâche de réplication.
        
        Args:
            task: Tâche de réplication
            
        Returns:
            ID de la tâche
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO replication_history (
                    file_uuid, chunk_idx, owner_uuid, source_peer_uuid,
                    target_peer_uuid, reason, created_at, completed_at,
                    attempts, status, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task.file_uuid,
                task.chunk_idx,
                task.owner_uuid,
                task.source_peer_uuid,
                task.target_peer_uuid,
                task.reason,
                task.created_at.isoformat() if task.created_at else None,
                task.completed_at.isoformat() if task.completed_at else None,
                task.attempts,
                task.status,
                task.error_message,
            ))
            if not self._in_transaction:
                self.conn.commit()
            return cursor.lastrowid
        except sqlite3.Error as e:
            raise ChunkDatabaseError(
                "Failed to add replication task",
                {"file_uuid": task.file_uuid},
                sqlite_error=str(e)
            )
    
    def get_replication_tasks(self, file_uuid: str) -> List[ReplicationTask]:
        """
        Récupère les tâches de réplication d'un fichier.
        
        Args:
            file_uuid: UUID du fichier
            
        Returns:
            Liste de ReplicationTask
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM replication_history WHERE file_uuid = ?
        """, (file_uuid,))
        
        return [self._row_to_replication_task(row) for row in cursor.fetchall()]
    
    def _row_to_replication_task(self, row: sqlite3.Row) -> ReplicationTask:
        """Convertit une row SQLite en ReplicationTask."""
        created_at = None
        if row['created_at']:
            created_at = datetime.fromisoformat(row['created_at'])
        
        completed_at = None
        if row['completed_at']:
            completed_at = datetime.fromisoformat(row['completed_at'])
        
        return ReplicationTask(
            file_uuid=row['file_uuid'],
            chunk_idx=row['chunk_idx'],
            owner_uuid=row['owner_uuid'],
            source_peer_uuid=row['source_peer_uuid'],
            target_peer_uuid=row['target_peer_uuid'],
            reason=row['reason'] or 'peer_disconnected',
            created_at=created_at,
            completed_at=completed_at,
            attempts=row['attempts'] or 0,
            status=row['status'] or 'pending',
            error_message=row['error_message'],
        )
    
    def update_replication_task(self, task_id: int, status: str,
                               completed_at: Optional[datetime] = None) -> None:
        """
        Met à jour une tâche de réplication.
        
        Args:
            task_id: ID de la tâche
            status: Nouveau statut
            completed_at: Date de complétion optionnelle
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE replication_history SET status = ?, completed_at = ?
            WHERE id = ?
        """, (status, completed_at.isoformat() if completed_at else None, task_id))
        if not self._in_transaction:
            self.conn.commit()
    
    def get_pending_replications(self) -> List[ReplicationTask]:
        """
        Récupère toutes les réplications en attente.
        
        Returns:
            Liste de ReplicationTask avec status='pending'
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM replication_history 
            WHERE status IN ('pending', 'in_progress')
            ORDER BY created_at
        """)
        
        return [self._row_to_replication_task(row) for row in cursor.fetchall()]
    
    # ==========================================================================
    # PEERS
    # ==========================================================================
    
    def add_or_update_peer(self, uuid: str, ip_address: str, port: int) -> None:
        """
        Ajoute ou met à jour un peer.
        
        Args:
            uuid: UUID du peer
            ip_address: Adresse IP
            port: Port
        """
        cursor = self.conn.cursor()
        now = datetime.utcnow().isoformat()
        
        # Vérifier si le peer existe
        cursor.execute("SELECT uuid FROM peers WHERE uuid = ?", (uuid,))
        if cursor.fetchone():
            # Mise à jour
            cursor.execute("""
                UPDATE peers SET ip_address = ?, port = ?, last_seen = ?, is_online = 1
                WHERE uuid = ?
            """, (ip_address, port, now, uuid))
        else:
            # Insertion
            cursor.execute("""
                INSERT INTO peers (uuid, ip_address, port, first_seen, last_seen, is_online)
                VALUES (?, ?, ?, ?, ?, 1)
            """, (uuid, ip_address, port, now, now))
        
        if not self._in_transaction:
            self.conn.commit()
    
    def get_peer(self, uuid: str) -> Optional[Dict[str, Any]]:
        """
        Récupère les informations d'un peer.
        
        Args:
            uuid: UUID du peer
            
        Returns:
            Dictionnaire avec les infos ou None
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM peers WHERE uuid = ?", (uuid,))
        row = cursor.fetchone()
        
        if not row:
            return None
        
        return dict(row)
    
    def get_peer_info(self, uuid: str) -> Optional[PeerInfo]:
        """
        Récupère un PeerInfo.
        
        Args:
            uuid: UUID du peer
            
        Returns:
            PeerInfo ou None
        """
        data = self.get_peer(uuid)
        if not data:
            return None
        
        return PeerInfo.from_dict(data)
    
    def update_peer_reliability(self, uuid: str, score: float) -> None:
        """
        Met à jour le score de fiabilité d'un peer.
        
        Args:
            uuid: UUID du peer
            score: Nouveau score (0.0 - 1.0)
        """
        score = max(0.0, min(1.0, score))  # Clamp entre 0 et 1
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE peers SET reliability_score = ? WHERE uuid = ?
        """, (score, uuid))
        if not self._in_transaction:
            self.conn.commit()
    
    def update_peer_chunks_count(self, uuid: str, count: int) -> None:
        """
        Met à jour le nombre de chunks stockés par un peer.
        
        Args:
            uuid: UUID du peer
            count: Nouveau nombre de chunks
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE peers SET chunks_stored = ? WHERE uuid = ?
        """, (count, uuid))
        if not self._in_transaction:
            self.conn.commit()
    
    def get_online_peers(self) -> List[Dict[str, Any]]:
        """
        Récupère tous les peers en ligne.
        
        Returns:
            Liste de dictionnaires avec les infos des peers
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM peers WHERE is_online = 1
            ORDER BY reliability_score DESC
        """)
        
        return [dict(row) for row in cursor.fetchall()]
    
    def set_peer_offline(self, uuid: str) -> None:
        """
        Marque un peer comme hors ligne.
        
        Args:
            uuid: UUID du peer
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE peers SET is_online = 0 WHERE uuid = ?
        """, (uuid,))
        if not self._in_transaction:
            self.conn.commit()
        self.logger.info(f"Peer marqué hors ligne: {uuid}")
    
    def get_peer_stats(self) -> Dict[str, Any]:
        """
        Récupère les statistiques globales des peers.
        
        Returns:
            Dictionnaire avec les stats
        """
        cursor = self.conn.cursor()
        
        # Total peers
        cursor.execute("SELECT COUNT(*) as count FROM peers")
        total_peers = cursor.fetchone()['count']
        
        # Online peers
        cursor.execute("SELECT COUNT(*) as count FROM peers WHERE is_online = 1")
        online_peers = cursor.fetchone()['count']
        
        # Average reliability
        cursor.execute("""
            SELECT AVG(reliability_score) as avg_score FROM peers WHERE is_online = 1
        """)
        row = cursor.fetchone()
        avg_reliability = row['avg_score'] if row['avg_score'] else 0.0
        
        # Total chunks stored
        cursor.execute("SELECT SUM(chunks_stored) as total FROM peers")
        row = cursor.fetchone()
        total_chunks = row['total'] if row['total'] else 0
        
        return {
            'total_peers': total_peers,
            'online_peers': online_peers,
            'offline_peers': total_peers - online_peers,
            'avg_reliability': round(avg_reliability, 3),
            'total_chunks_stored': total_chunks,
        }
    
    # ==========================================================================
    # UTILITAIRES
    # ==========================================================================
    
    def close(self) -> None:
        """Ferme la connexion à la base de données."""
        if self.conn:
            self.conn.close()
            self.conn = None
            self.logger.info("Connexion à la base de données fermée")
    
    def verify_integrity(self) -> bool:
        """
        Vérifie l'intégrité de la base de données.
        
        Returns:
            True si la base est cohérente
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()
            is_ok = result[0] == 'ok'
            if not is_ok:
                self.logger.error(f"Problème d'intégrité: {result[0]}")
            return is_ok
        except sqlite3.Error as e:
            self.logger.error(f"Erreur lors de la vérification d'intégrité: {e}")
            return False
    
    def export_stats(self) -> Dict[str, Any]:
        """
        Exporte les statistiques complètes de la base.
        
        Returns:
            Dictionnaire avec toutes les statistiques
        """
        cursor = self.conn.cursor()
        
        # Compter les fichiers
        cursor.execute("SELECT COUNT(*) as count FROM file_metadata")
        file_count = cursor.fetchone()['count']
        
        # Compter les chunks locaux
        cursor.execute("SELECT COUNT(*) as count FROM chunks")
        chunk_count = cursor.fetchone()['count']
        
        # Chunks par statut
        cursor.execute("""
            SELECT status, COUNT(*) as count FROM chunks GROUP BY status
        """)
        chunks_by_status = {row['status']: row['count'] for row in cursor.fetchall()}
        
        # Réplications en attente
        cursor.execute("""
            SELECT COUNT(*) as count FROM replication_history 
            WHERE status IN ('pending', 'in_progress')
        """)
        replication_pending = cursor.fetchone()['count']
        
        # Localisations
        cursor.execute("SELECT COUNT(*) as count FROM chunk_locations")
        locations_count = cursor.fetchone()['count']
        
        # Localisations confirmées
        cursor.execute("""
            SELECT COUNT(*) as count FROM chunk_locations WHERE status = 'confirmed'
        """)
        locations_confirmed = cursor.fetchone()['count']
        
        # Stats des peers
        peer_stats = self.get_peer_stats()
        
        # Taille totale stockée
        cursor.execute("SELECT SUM(size_bytes) as total FROM chunks")
        row = cursor.fetchone()
        total_size = row['total'] if row['total'] else 0
        
        return {
            'file_count': file_count,
            'chunk_count': chunk_count,
            'chunks_by_status': chunks_by_status,
            'replication_pending': replication_pending,
            'locations_count': locations_count,
            'locations_confirmed': locations_confirmed,
            'total_size_bytes': total_size,
            'total_size_mb': round(total_size / (1024 * 1024), 2) if total_size else 0,
            'peers': peer_stats,
        }
    
    def vacuum(self) -> None:
        """
        Optimise la base de données (VACUUM).
        
        Libère l'espace inutilisé et réorganise les données.
        """
        self.conn.execute("VACUUM")
        self.logger.info("Base de données optimisée (VACUUM)")
