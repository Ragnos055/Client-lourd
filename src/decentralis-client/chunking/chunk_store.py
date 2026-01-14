"""
Gestion du stockage local des chunks sur disque.

Ce module gère toutes les opérations de fichiers pour le stockage
des chunks: écriture, lecture, validation, et nettoyage.

Structure du répertoire de stockage:
    ~/.decentralis/chunks/
    ├── {owner_uuid}/
    │   ├── {file_uuid}/
    │   │   ├── metadata.json
    │   │   ├── 0.chunk
    │   │   ├── 1.chunk
    │   │   └── ...
    │   └── {file_uuid2}/
    └── {owner_uuid2}/

Example:
    >>> from chunking.chunk_store import ChunkStore
    >>> store = ChunkStore("~/.decentralis/chunks")
    >>> store.store_chunk("owner123", "file456", 0, b"chunk data")
    '.../.decentralis/chunks/owner123/file456/0.chunk'
"""

import os
import json
import hashlib
import shutil
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from .models import ChunkMetadata
from .exceptions import ChunkStorageError, ChunkValidationError


class ChunkStore:
    """
    Gestionnaire de stockage local des chunks sur disque.
    
    Cette classe gère toutes les opérations de fichiers pour:
    - Stocker des chunks sur le disque
    - Récupérer des chunks depuis le disque
    - Valider l'intégrité des chunks (hash)
    - Nettoyer les fichiers orphelins
    
    Attributes:
        storage_dir: Répertoire racine de stockage
        logger: Logger pour le debug
        
    Example:
        >>> store = ChunkStore("/tmp/chunks")
        >>> store.storage_dir  # doctest: +ELLIPSIS
        '...'
    """
    
    def __init__(self, storage_dir: str, logger: Optional[logging.Logger] = None):
        """
        Initialise le gestionnaire de stockage.
        
        Args:
            storage_dir: Répertoire de stockage (sera étendu avec ~ et créé si nécessaire)
            logger: Logger optionnel pour le debug
            
        Raises:
            ChunkStorageError: Si le répertoire ne peut pas être créé
        """
        self.storage_dir = os.path.abspath(os.path.expanduser(storage_dir))
        self.logger = logger or logging.getLogger(__name__)
        
        try:
            Path(self.storage_dir).mkdir(parents=True, exist_ok=True)
            self.logger.info(f"ChunkStore initialisé: {self.storage_dir}")
        except OSError as e:
            raise ChunkStorageError(
                f"Failed to create storage directory: {e}",
                path=storage_dir,
                operation="init"
            )
    
    # ==========================================================================
    # GESTION DES RÉPERTOIRES
    # ==========================================================================
    
    def get_file_dir(self, owner_uuid: str, file_uuid: str) -> str:
        """
        Retourne le chemin du répertoire d'un fichier.
        
        Args:
            owner_uuid: UUID du propriétaire
            file_uuid: UUID du fichier
            
        Returns:
            Chemin absolu du répertoire du fichier
            
        Example:
            >>> store = ChunkStore("/tmp/chunks")
            >>> path = store.get_file_dir("owner123", "file456")
            >>> "owner123" in path and "file456" in path
            True
        """
        return os.path.join(self.storage_dir, owner_uuid, file_uuid)
    
    def ensure_file_dir(self, owner_uuid: str, file_uuid: str) -> str:
        """
        Crée le répertoire d'un fichier s'il n'existe pas.
        
        Args:
            owner_uuid: UUID du propriétaire
            file_uuid: UUID du fichier
            
        Returns:
            Chemin absolu du répertoire créé
            
        Raises:
            ChunkStorageError: Si la création échoue
        """
        file_dir = self.get_file_dir(owner_uuid, file_uuid)
        try:
            Path(file_dir).mkdir(parents=True, exist_ok=True)
            return file_dir
        except OSError as e:
            raise ChunkStorageError(
                f"Failed to create file directory: {e}",
                path=file_dir,
                operation="mkdir"
            )
    
    def get_owner_dir(self, owner_uuid: str) -> str:
        """
        Retourne le chemin du répertoire d'un propriétaire.
        
        Args:
            owner_uuid: UUID du propriétaire
            
        Returns:
            Chemin absolu du répertoire du propriétaire
        """
        return os.path.join(self.storage_dir, owner_uuid)
    
    # ==========================================================================
    # STOCKAGE DE CHUNKS
    # ==========================================================================
    
    def store_chunk(self, owner_uuid: str, file_uuid: str,
                   chunk_idx: int, chunk_data: bytes) -> str:
        """
        Stocke un chunk sur le disque.
        
        Args:
            owner_uuid: UUID du propriétaire
            file_uuid: UUID du fichier
            chunk_idx: Index du chunk
            chunk_data: Données du chunk
            
        Returns:
            Chemin absolu du fichier chunk créé
            
        Raises:
            ChunkStorageError: Si l'écriture échoue
            
        Example:
            >>> store = ChunkStore("/tmp/chunks")
            >>> path = store.store_chunk("owner", "file", 0, b"data")
            >>> os.path.exists(path)
            True
        """
        file_dir = self.ensure_file_dir(owner_uuid, file_uuid)
        chunk_path = os.path.join(file_dir, f"{chunk_idx}.chunk")
        
        try:
            with open(chunk_path, 'wb') as f:
                f.write(chunk_data)
            
            self.logger.debug(
                f"Chunk stocké: {owner_uuid}/{file_uuid}#{chunk_idx} "
                f"({len(chunk_data)} bytes)"
            )
            return chunk_path
            
        except IOError as e:
            raise ChunkStorageError(
                f"Failed to write chunk: {e}",
                path=chunk_path,
                operation="write"
            )
    
    def store_metadata(self, owner_uuid: str, file_uuid: str,
                      metadata: ChunkMetadata) -> str:
        """
        Stocke les métadonnées d'un fichier.
        
        Args:
            owner_uuid: UUID du propriétaire
            file_uuid: UUID du fichier
            metadata: Métadonnées à stocker
            
        Returns:
            Chemin absolu du fichier metadata.json
            
        Raises:
            ChunkStorageError: Si l'écriture échoue
        """
        file_dir = self.ensure_file_dir(owner_uuid, file_uuid)
        metadata_path = os.path.join(file_dir, "metadata.json")
        
        try:
            with open(metadata_path, 'w', encoding='utf-8') as f:
                f.write(metadata.to_json())
            
            self.logger.debug(f"Métadonnées stockées: {metadata_path}")
            return metadata_path
            
        except IOError as e:
            raise ChunkStorageError(
                f"Failed to write metadata: {e}",
                path=metadata_path,
                operation="write"
            )
    
    # ==========================================================================
    # RÉCUPÉRATION DE CHUNKS
    # ==========================================================================
    
    def get_chunk(self, owner_uuid: str, file_uuid: str,
                 chunk_idx: int) -> Optional[bytes]:
        """
        Récupère un chunk depuis le disque.
        
        Args:
            owner_uuid: UUID du propriétaire
            file_uuid: UUID du fichier
            chunk_idx: Index du chunk
            
        Returns:
            Données du chunk ou None si non trouvé
            
        Example:
            >>> store = ChunkStore("/tmp/chunks")
            >>> store.store_chunk("owner", "file", 0, b"test data")  # doctest: +ELLIPSIS
            '...'
            >>> store.get_chunk("owner", "file", 0)
            b'test data'
            >>> store.get_chunk("owner", "file", 999) is None
            True
        """
        chunk_path = os.path.join(
            self.get_file_dir(owner_uuid, file_uuid),
            f"{chunk_idx}.chunk"
        )
        
        if not os.path.exists(chunk_path):
            return None
        
        try:
            with open(chunk_path, 'rb') as f:
                data = f.read()
            
            self.logger.debug(
                f"Chunk lu: {owner_uuid}/{file_uuid}#{chunk_idx} "
                f"({len(data)} bytes)"
            )
            return data
            
        except IOError as e:
            self.logger.error(f"Erreur lecture chunk {chunk_path}: {e}")
            return None
    
    def get_metadata(self, owner_uuid: str, file_uuid: str) -> Optional[ChunkMetadata]:
        """
        Récupère les métadonnées d'un fichier.
        
        Args:
            owner_uuid: UUID du propriétaire
            file_uuid: UUID du fichier
            
        Returns:
            ChunkMetadata ou None si non trouvé
        """
        metadata_path = os.path.join(
            self.get_file_dir(owner_uuid, file_uuid),
            "metadata.json"
        )
        
        if not os.path.exists(metadata_path):
            return None
        
        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                json_str = f.read()
            return ChunkMetadata.from_json(json_str)
            
        except (IOError, json.JSONDecodeError) as e:
            self.logger.error(f"Erreur lecture métadonnées {metadata_path}: {e}")
            return None
    
    # ==========================================================================
    # GESTION DES FICHIERS
    # ==========================================================================
    
    def list_files(self, owner_uuid: str) -> List[str]:
        """
        Liste tous les file_uuid d'un propriétaire.
        
        Args:
            owner_uuid: UUID du propriétaire
            
        Returns:
            Liste des file_uuid
        """
        owner_dir = self.get_owner_dir(owner_uuid)
        
        if not os.path.exists(owner_dir):
            return []
        
        try:
            return [
                name for name in os.listdir(owner_dir)
                if os.path.isdir(os.path.join(owner_dir, name))
            ]
        except OSError as e:
            self.logger.error(f"Erreur listage fichiers {owner_dir}: {e}")
            return []
    
    def list_chunks(self, owner_uuid: str, file_uuid: str) -> List[int]:
        """
        Liste tous les chunk_idx stockés pour un fichier.
        
        Args:
            owner_uuid: UUID du propriétaire
            file_uuid: UUID du fichier
            
        Returns:
            Liste des indices de chunks triés
        """
        file_dir = self.get_file_dir(owner_uuid, file_uuid)
        
        if not os.path.exists(file_dir):
            return []
        
        chunks = []
        try:
            for name in os.listdir(file_dir):
                if name.endswith('.chunk'):
                    try:
                        idx = int(name.replace('.chunk', ''))
                        chunks.append(idx)
                    except ValueError:
                        pass
            return sorted(chunks)
        except OSError as e:
            self.logger.error(f"Erreur listage chunks {file_dir}: {e}")
            return []
    
    def delete_chunk(self, owner_uuid: str, file_uuid: str, chunk_idx: int) -> bool:
        """
        Supprime un chunk du disque.
        
        Args:
            owner_uuid: UUID du propriétaire
            file_uuid: UUID du fichier
            chunk_idx: Index du chunk
            
        Returns:
            True si supprimé, False si non trouvé
        """
        chunk_path = os.path.join(
            self.get_file_dir(owner_uuid, file_uuid),
            f"{chunk_idx}.chunk"
        )
        
        if not os.path.exists(chunk_path):
            return False
        
        try:
            os.remove(chunk_path)
            self.logger.debug(f"Chunk supprimé: {chunk_path}")
            return True
        except OSError as e:
            self.logger.error(f"Erreur suppression chunk {chunk_path}: {e}")
            return False
    
    def delete_file(self, owner_uuid: str, file_uuid: str) -> int:
        """
        Supprime tous les chunks et métadonnées d'un fichier.
        
        Args:
            owner_uuid: UUID du propriétaire
            file_uuid: UUID du fichier
            
        Returns:
            Nombre de fichiers supprimés
        """
        file_dir = self.get_file_dir(owner_uuid, file_uuid)
        
        if not os.path.exists(file_dir):
            return 0
        
        try:
            count = len(os.listdir(file_dir))
            shutil.rmtree(file_dir)
            self.logger.info(f"Fichier supprimé: {owner_uuid}/{file_uuid} ({count} fichiers)")
            return count
        except OSError as e:
            self.logger.error(f"Erreur suppression fichier {file_dir}: {e}")
            return 0
    
    # Alias pour compatibilité
    delete_file_chunks = delete_file
    
    def get_file_size(self, owner_uuid: str, file_uuid: str) -> int:
        """
        Calcule la taille totale occupée par un fichier (tous les chunks).
        
        Args:
            owner_uuid: UUID du propriétaire
            file_uuid: UUID du fichier
            
        Returns:
            Taille en bytes
        """
        file_dir = self.get_file_dir(owner_uuid, file_uuid)
        
        if not os.path.exists(file_dir):
            return 0
        
        total = 0
        try:
            for name in os.listdir(file_dir):
                file_path = os.path.join(file_dir, name)
                if os.path.isfile(file_path):
                    total += os.path.getsize(file_path)
            return total
        except OSError as e:
            self.logger.error(f"Erreur calcul taille {file_dir}: {e}")
            return 0
    
    def get_owner_size(self, owner_uuid: str) -> int:
        """
        Calcule la taille totale occupée par un propriétaire.
        
        Args:
            owner_uuid: UUID du propriétaire
            
        Returns:
            Taille en bytes
        """
        owner_dir = self.get_owner_dir(owner_uuid)
        
        if not os.path.exists(owner_dir):
            return 0
        
        total = 0
        for file_uuid in self.list_files(owner_uuid):
            total += self.get_file_size(owner_uuid, file_uuid)
        return total
    
    # ==========================================================================
    # VALIDATION
    # ==========================================================================
    
    def get_chunk_hash(self, owner_uuid: str, file_uuid: str, 
                      chunk_idx: int) -> Optional[str]:
        """
        Calcule le hash SHA-256 d'un chunk.
        
        Args:
            owner_uuid: UUID du propriétaire
            file_uuid: UUID du fichier
            chunk_idx: Index du chunk
            
        Returns:
            Hash hexadécimal ou None si chunk non trouvé
        """
        data = self.get_chunk(owner_uuid, file_uuid, chunk_idx)
        if data is None:
            return None
        return hashlib.sha256(data).hexdigest()
    
    def verify_chunk_hash(self, owner_uuid: str, file_uuid: str,
                         chunk_idx: int, expected_hash: str) -> bool:
        """
        Vérifie le hash d'un chunk.
        
        Args:
            owner_uuid: UUID du propriétaire
            file_uuid: UUID du fichier
            chunk_idx: Index du chunk
            expected_hash: Hash attendu (hex)
            
        Returns:
            True si le hash correspond, False sinon
            
        Raises:
            ChunkValidationError: Si le chunk est corrompu
        """
        actual_hash = self.get_chunk_hash(owner_uuid, file_uuid, chunk_idx)
        
        if actual_hash is None:
            return False
        
        if actual_hash != expected_hash:
            raise ChunkValidationError(
                "Chunk hash mismatch",
                {"file_uuid": file_uuid, "chunk_idx": chunk_idx},
                expected_hash=expected_hash,
                actual_hash=actual_hash,
                chunk_idx=chunk_idx
            )
        
        return True
    
    def verify_file_integrity(self, owner_uuid: str, file_uuid: str,
                             expected_hashes: Dict[int, str]) -> Dict[int, bool]:
        """
        Vérifie l'intégrité de tous les chunks d'un fichier.
        
        Args:
            owner_uuid: UUID du propriétaire
            file_uuid: UUID du fichier
            expected_hashes: Dictionnaire {chunk_idx: expected_hash}
            
        Returns:
            Dictionnaire {chunk_idx: is_valid}
        """
        results = {}
        
        for chunk_idx, expected_hash in expected_hashes.items():
            try:
                results[chunk_idx] = self.verify_chunk_hash(
                    owner_uuid, file_uuid, chunk_idx, expected_hash
                )
            except ChunkValidationError:
                results[chunk_idx] = False
        
        return results
    
    # ==========================================================================
    # UTILITAIRES
    # ==========================================================================
    
    def get_available_space(self) -> int:
        """
        Retourne l'espace disque libre disponible.
        
        Returns:
            Espace libre en bytes
        """
        try:
            stat = os.statvfs(self.storage_dir)
            return stat.f_frsize * stat.f_bavail
        except (OSError, AttributeError):
            # Windows n'a pas statvfs
            try:
                import ctypes
                free_bytes = ctypes.c_ulonglong(0)
                ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                    ctypes.c_wchar_p(self.storage_dir),
                    None,
                    None,
                    ctypes.pointer(free_bytes)
                )
                return free_bytes.value
            except Exception as e:
                self.logger.warning(f"Impossible de déterminer l'espace libre: {e}")
                return 0
    
    def get_total_stored(self) -> int:
        """
        Calcule la taille totale de tous les chunks stockés.
        
        Returns:
            Taille totale en bytes
        """
        total = 0
        
        try:
            for owner_uuid in os.listdir(self.storage_dir):
                owner_path = os.path.join(self.storage_dir, owner_uuid)
                if os.path.isdir(owner_path):
                    total += self.get_owner_size(owner_uuid)
            return total
        except OSError as e:
            self.logger.error(f"Erreur calcul taille totale: {e}")
            return 0
    
    def cleanup_orphaned_chunks(self) -> int:
        """
        Nettoie les chunks orphelins (sans métadonnées).
        
        Un chunk est considéré orphelin si le fichier metadata.json
        est absent du répertoire.
        
        Returns:
            Nombre de fichiers/dossiers supprimés
        """
        cleaned = 0
        
        try:
            for owner_uuid in os.listdir(self.storage_dir):
                owner_path = os.path.join(self.storage_dir, owner_uuid)
                if not os.path.isdir(owner_path):
                    continue
                
                for file_uuid in os.listdir(owner_path):
                    file_path = os.path.join(owner_path, file_uuid)
                    if not os.path.isdir(file_path):
                        continue
                    
                    metadata_path = os.path.join(file_path, "metadata.json")
                    if not os.path.exists(metadata_path):
                        # Orphelin: pas de métadonnées
                        try:
                            shutil.rmtree(file_path)
                            cleaned += 1
                            self.logger.info(f"Orphelin nettoyé: {owner_uuid}/{file_uuid}")
                        except OSError:
                            pass
                
                # Nettoyer le répertoire owner s'il est vide
                if os.path.exists(owner_path) and not os.listdir(owner_path):
                    try:
                        os.rmdir(owner_path)
                        self.logger.debug(f"Répertoire owner vide supprimé: {owner_uuid}")
                    except OSError:
                        pass
            
            self.logger.info(f"Nettoyage terminé: {cleaned} orphelins supprimés")
            return cleaned
            
        except OSError as e:
            self.logger.error(f"Erreur nettoyage orphelins: {e}")
            return cleaned
    
    def cleanup_empty_dirs(self) -> int:
        """
        Supprime les répertoires vides.
        
        Returns:
            Nombre de répertoires supprimés
        """
        cleaned = 0
        
        try:
            for owner_uuid in os.listdir(self.storage_dir):
                owner_path = os.path.join(self.storage_dir, owner_uuid)
                if not os.path.isdir(owner_path):
                    continue
                
                for file_uuid in os.listdir(owner_path):
                    file_path = os.path.join(owner_path, file_uuid)
                    if os.path.isdir(file_path) and not os.listdir(file_path):
                        try:
                            os.rmdir(file_path)
                            cleaned += 1
                        except OSError:
                            pass
                
                if os.path.exists(owner_path) and not os.listdir(owner_path):
                    try:
                        os.rmdir(owner_path)
                        cleaned += 1
                    except OSError:
                        pass
            
            return cleaned
            
        except OSError:
            return cleaned
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Retourne des statistiques sur le stockage.
        
        Returns:
            Dictionnaire avec les statistiques
        """
        total_size = self.get_total_stored()
        available = self.get_available_space()
        
        # Compter les fichiers et chunks
        total_files = 0
        total_chunks = 0
        
        try:
            for owner_uuid in os.listdir(self.storage_dir):
                owner_path = os.path.join(self.storage_dir, owner_uuid)
                if not os.path.isdir(owner_path):
                    continue
                
                for file_uuid in os.listdir(owner_path):
                    file_path = os.path.join(owner_path, file_uuid)
                    if os.path.isdir(file_path):
                        total_files += 1
                        total_chunks += len(self.list_chunks(owner_uuid, file_uuid))
        except OSError:
            pass
        
        return {
            'storage_dir': self.storage_dir,
            'total_size_bytes': total_size,
            'total_size_mb': round(total_size / (1024 * 1024), 2),
            'available_bytes': available,
            'available_mb': round(available / (1024 * 1024), 2),
            'total_files': total_files,
            'total_chunks': total_chunks,
        }
    
    def list_all_owners(self) -> List[str]:
        """
        Liste tous les propriétaires ayant des fichiers stockés.
        
        Returns:
            Liste des owner_uuid
        """
        try:
            return [
                name for name in os.listdir(self.storage_dir)
                if os.path.isdir(os.path.join(self.storage_dir, name))
            ]
        except OSError:
            return []
    
    def file_exists(self, owner_uuid: str, file_uuid: str) -> bool:
        """
        Vérifie si un fichier existe.
        
        Args:
            owner_uuid: UUID du propriétaire
            file_uuid: UUID du fichier
            
        Returns:
            True si le fichier existe (a des métadonnées)
        """
        metadata_path = os.path.join(
            self.get_file_dir(owner_uuid, file_uuid),
            "metadata.json"
        )
        return os.path.exists(metadata_path)
    
    def chunk_exists(self, owner_uuid: str, file_uuid: str, chunk_idx: int) -> bool:
        """
        Vérifie si un chunk existe.
        
        Args:
            owner_uuid: UUID du propriétaire
            file_uuid: UUID du fichier
            chunk_idx: Index du chunk
            
        Returns:
            True si le chunk existe
        """
        chunk_path = os.path.join(
            self.get_file_dir(owner_uuid, file_uuid),
            f"{chunk_idx}.chunk"
        )
        return os.path.exists(chunk_path)
    
    def get_chunk_size(self, owner_uuid: str, file_uuid: str, chunk_idx: int) -> int:
        """
        Retourne la taille d'un chunk.
        
        Args:
            owner_uuid: UUID du propriétaire
            file_uuid: UUID du fichier
            chunk_idx: Index du chunk
            
        Returns:
            Taille en bytes, ou 0 si non trouvé
        """
        chunk_path = os.path.join(
            self.get_file_dir(owner_uuid, file_uuid),
            f"{chunk_idx}.chunk"
        )
        
        if not os.path.exists(chunk_path):
            return 0
        
        try:
            return os.path.getsize(chunk_path)
        except OSError:
            return 0
