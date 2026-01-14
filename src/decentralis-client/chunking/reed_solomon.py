"""
Encodeur et décodeur Reed-Solomon avec support LRC.

Ce module implémente l'encodage et le décodage de données utilisant
Reed-Solomon Erasure Coding avec extension Local Reconstruction Codes (LRC).

Reed-Solomon permet de reconstruire des données même si certains chunks
sont perdus, tant qu'on dispose d'au moins K chunks sur N total.

LRC ajoute des groupes locaux avec des symboles de récupération locaux,
permettant de récupérer un chunk manquant dans un groupe sans avoir
besoin de tous les autres chunks.

Example:
    >>> from chunking.reed_solomon import ReedSolomonEncoder
    >>> encoder = ReedSolomonEncoder(k=6, m=4)
    >>> data = b'Hello World!' * 1000
    >>> data_chunks, parity_chunks = encoder.encode_data(data)
    >>> len(data_chunks)
    6
    >>> len(parity_chunks)
    4
"""

import logging
from typing import List, Tuple, Dict, Optional
from functools import reduce
from operator import xor

from .models import LocalGroup
from .exceptions import (
    ChunkEncodingError, ChunkDecodingError, InsufficientChunksError
)

# Import de reedsolo pour l'encodage Reed-Solomon
try:
    from reedsolo import RSCodec, ReedSolomonError
    REEDSOLO_AVAILABLE = True
except ImportError:
    REEDSOLO_AVAILABLE = False
    RSCodec = None
    ReedSolomonError = Exception


class ReedSolomonEncoder:
    """
    Encodeur/Décodeur Reed-Solomon avec support LRC.
    
    Cette classe gère l'encodage de données en chunks avec parité,
    permettant la récupération même en cas de perte de chunks.
    
    Reed-Solomon Parameters:
        - K: Nombre de chunks de données originaux
        - M: Nombre de chunks de parité
        - N = K + M: Nombre total de chunks
        - On peut récupérer les données avec n'importe quels K chunks sur N
    
    LRC Parameters:
        - LOCAL_GROUP_SIZE: Nombre de chunks de données par groupe local
        - Chaque groupe a un symbole de récupération local (XOR)
        - Permet une récupération locale rapide sans accéder à tous les chunks
    
    Attributes:
        k: Nombre de chunks de données
        m: Nombre de chunks de parité  
        nsym: Nombre de symboles de parité pour reedsolo
        codec: Instance RSCodec de reedsolo
        logger: Logger pour le debug
        
    Example:
        >>> encoder = ReedSolomonEncoder(k=6, m=4)
        >>> encoder.k
        6
        >>> encoder.m
        4
    """
    
    def __init__(self, k: int = 6, m: int = 4, nsym: int = None,
                 logger: Optional[logging.Logger] = None):
        """
        Initialise l'encodeur Reed-Solomon.
        
        Args:
            k: Nombre de chunks de données (défaut: 6)
            m: Nombre de chunks de parité (défaut: 4)
            nsym: Nombre de symboles de parité pour reedsolo (défaut: m)
            logger: Logger optionnel
            
        Raises:
            ChunkEncodingError: Si les paramètres sont invalides ou reedsolo non disponible
            
        Example:
            >>> encoder = ReedSolomonEncoder(k=6, m=4)
            >>> encoder.total_chunks
            10
        """
        self.k = k
        self.m = m
        self.nsym = nsym if nsym is not None else m  # nsym par défaut = m
        self.total_chunks = k + m
        self.logger = logger or logging.getLogger(__name__)
        
        # Validation des paramètres
        if k < 1:
            raise ChunkEncodingError(
                "K must be at least 1",
                {"k": k}
            )
        if m < 1:
            raise ChunkEncodingError(
                "M must be at least 1",
                {"m": m}
            )
        if k + m > 255:
            raise ChunkEncodingError(
                "K + M cannot exceed 255 (Galois Field GF(2^8) limit)",
                {"k": k, "m": m, "total": k + m}
            )
        
        # Initialiser le codec Reed-Solomon
        if REEDSOLO_AVAILABLE:
            try:
                self.codec = RSCodec(self.nsym)
                self.logger.debug(f"RSCodec initialisé avec nsym={self.nsym}")
            except Exception as e:
                raise ChunkEncodingError(
                    "Failed to initialize RSCodec",
                    {"nsym": self.nsym, "error": str(e)}
                )
        else:
            self.codec = None
            self.logger.warning(
                "reedsolo non disponible, utilisation du mode fallback (XOR uniquement)"
            )
    
    def encode_data(self, data: bytes) -> Tuple[List[bytes], List[bytes]]:
        """
        Encode des données en chunks avec parité Reed-Solomon.
        
        Les données sont divisées en K chunks de données, puis M chunks
        de parité sont générés pour permettre la reconstruction.
        
        Args:
            data: Données à encoder
            
        Returns:
            Tuple (data_chunks, parity_chunks):
                - data_chunks: Liste de K chunks de données
                - parity_chunks: Liste de M chunks de parité
                
        Raises:
            ChunkEncodingError: Si l'encodage échoue
            
        Example:
            >>> encoder = ReedSolomonEncoder(k=4, m=2)
            >>> data = b'A' * 1000
            >>> data_chunks, parity_chunks = encoder.encode_data(data)
            >>> len(data_chunks)
            4
            >>> len(parity_chunks)
            2
            >>> # Chaque chunk fait environ 250 bytes
            >>> all(len(c) == len(data_chunks[0]) for c in data_chunks)
            True
        """
        if not data:
            raise ChunkEncodingError("Cannot encode empty data")
        
        try:
            # Calculer la taille de chaque chunk de données
            chunk_size = (len(data) + self.k - 1) // self.k
            
            # Padding pour avoir une taille multiple de k
            padded_data = data + bytes(chunk_size * self.k - len(data))
            
            # Diviser en chunks de données
            data_chunks = [
                padded_data[i * chunk_size:(i + 1) * chunk_size]
                for i in range(self.k)
            ]
            
            self.logger.debug(
                f"Données divisées en {self.k} chunks de {chunk_size} bytes"
            )
            
            # Générer les chunks de parité
            if self.codec and REEDSOLO_AVAILABLE:
                parity_chunks = self._generate_parity_rs(data_chunks, chunk_size)
            else:
                parity_chunks = self._generate_parity_xor(data_chunks)
            
            self.logger.info(
                f"Encodage terminé: {self.k} data + {len(parity_chunks)} parity chunks"
            )
            
            return data_chunks, parity_chunks
            
        except Exception as e:
            if isinstance(e, ChunkEncodingError):
                raise
            raise ChunkEncodingError(
                f"Encoding failed: {str(e)}",
                {"data_size": len(data), "k": self.k, "m": self.m}
            )
    
    def _generate_parity_rs(self, data_chunks: List[bytes], 
                           chunk_size: int) -> List[bytes]:
        """
        Génère les chunks de parité avec Reed-Solomon.
        
        Args:
            data_chunks: Liste des chunks de données
            chunk_size: Taille d'un chunk
            
        Returns:
            Liste des chunks de parité
        """
        parity_chunks = []
        
        # Pour chaque position de byte dans les chunks
        for byte_pos in range(chunk_size):
            # Collecter les bytes à cette position dans tous les chunks
            data_bytes = bytes([
                chunk[byte_pos] if byte_pos < len(chunk) else 0
                for chunk in data_chunks
            ])
            
            # Encoder avec Reed-Solomon
            encoded = self.codec.encode(data_bytes)
            
            # Les bytes de parité sont à la fin
            parity_bytes = encoded[len(data_bytes):]
            
            # Initialiser les chunks de parité si nécessaire
            while len(parity_chunks) < len(parity_bytes):
                parity_chunks.append(bytearray(chunk_size))
            
            # Stocker les bytes de parité
            for i, pb in enumerate(parity_bytes):
                parity_chunks[i][byte_pos] = pb
        
        # Convertir en bytes
        parity_chunks = [bytes(chunk) for chunk in parity_chunks]
        
        # Limiter au nombre demandé
        return parity_chunks[:self.m]
    
    def _generate_parity_xor(self, data_chunks: List[bytes]) -> List[bytes]:
        """
        Génère les chunks de parité avec XOR simple (fallback).
        
        Cette méthode est utilisée quand reedsolo n'est pas disponible.
        Elle génère M chunks de parité en utilisant différentes combinaisons XOR.
        
        Args:
            data_chunks: Liste des chunks de données
            
        Returns:
            Liste des chunks de parité
        """
        parity_chunks = []
        chunk_size = len(data_chunks[0])
        
        for p in range(self.m):
            parity = bytearray(chunk_size)
            
            # Utiliser différents patterns XOR pour chaque chunk de parité
            for i, chunk in enumerate(data_chunks):
                if (i + p) % (self.m + 1) != self.m:  # Pattern de sélection
                    for j in range(len(chunk)):
                        parity[j] ^= chunk[j]
            
            parity_chunks.append(bytes(parity))
        
        return parity_chunks
    
    def decode_data(self, chunks: Dict[int, bytes], original_size: int) -> bytes:
        """
        Décode les données depuis les chunks disponibles.
        
        Reconstruit les données originales à partir d'au moins K chunks
        (data ou parité) sur les N totaux.
        
        Args:
            chunks: Dictionnaire {chunk_idx: chunk_data} des chunks disponibles
            original_size: Taille originale des données (pour retirer le padding)
            
        Returns:
            Données originales reconstruites
            
        Raises:
            InsufficientChunksError: Si moins de K chunks sont disponibles
            ChunkDecodingError: Si le décodage échoue
            
        Example:
            >>> encoder = ReedSolomonEncoder(k=4, m=2)
            >>> data = b'Hello World!' * 100
            >>> data_chunks, parity_chunks = encoder.encode_data(data)
            >>> # Simuler la perte de 2 chunks
            >>> available = {0: data_chunks[0], 1: data_chunks[1], 
            ...              2: data_chunks[2], 4: parity_chunks[0]}
            >>> recovered = encoder.decode_data(available, len(data))
            >>> recovered == data
            True
        """
        if len(chunks) < self.k:
            raise InsufficientChunksError(
                f"Need at least {self.k} chunks, only {len(chunks)} available",
                available_chunks=len(chunks),
                required_chunks=self.k,
                missing_indices=[
                    i for i in range(self.total_chunks) if i not in chunks
                ]
            )
        
        try:
            # Identifier les chunks de données disponibles
            data_indices = [i for i in range(self.k) if i in chunks]
            
            # Si tous les chunks de données sont disponibles, reconstruction directe
            if len(data_indices) == self.k:
                self.logger.debug("Tous les chunks de données disponibles, reconstruction directe")
                result = b''.join(chunks[i] for i in range(self.k))
                return result[:original_size]
            
            # Sinon, utiliser Reed-Solomon pour reconstruire
            if self.codec and REEDSOLO_AVAILABLE:
                result = self._decode_rs(chunks, original_size)
            else:
                result = self._decode_xor(chunks, original_size)
            
            return result
            
        except InsufficientChunksError:
            raise
        except Exception as e:
            if isinstance(e, (ChunkDecodingError, InsufficientChunksError)):
                raise
            raise ChunkDecodingError(
                f"Decoding failed: {str(e)}",
                {"available_chunks": len(chunks), "original_size": original_size}
            )
    
    def _decode_rs(self, chunks: Dict[int, bytes], original_size: int) -> bytes:
        """
        Décode avec Reed-Solomon.
        
        Args:
            chunks: Chunks disponibles
            original_size: Taille originale
            
        Returns:
            Données reconstruites
        """
        chunk_size = len(next(iter(chunks.values())))
        result = bytearray(chunk_size * self.k)
        
        # Pour chaque position de byte
        for byte_pos in range(chunk_size):
            # Construire le vecteur avec erasures
            data_with_erasures = bytearray(self.k + self.nsym)
            erasure_positions = []
            
            for i in range(self.k):
                if i in chunks and byte_pos < len(chunks[i]):
                    data_with_erasures[i] = chunks[i][byte_pos]
                else:
                    erasure_positions.append(i)
            
            # Ajouter les bytes de parité disponibles
            for i in range(self.m):
                parity_idx = self.k + i
                if parity_idx in chunks and byte_pos < len(chunks[parity_idx]):
                    if i < self.nsym:
                        data_with_erasures[self.k + i] = chunks[parity_idx][byte_pos]
                else:
                    if i < self.nsym:
                        erasure_positions.append(self.k + i)
            
            try:
                # Décoder avec les positions d'effacement
                # reedsolo.decode retourne (data, ecc, errata_pos) 
                decoded_result = self.codec.decode(
                    bytes(data_with_erasures), 
                    erase_pos=erasure_positions[:self.nsym]
                )
                
                # Extraire les données décodées (premier élément du tuple)
                decoded_data = decoded_result[0] if isinstance(decoded_result, tuple) else decoded_result
                
                # Extraire les bytes de données
                for i in range(self.k):
                    result[i * chunk_size + byte_pos] = decoded_data[i]
                    
            except ReedSolomonError as e:
                raise ChunkDecodingError(
                    f"Reed-Solomon decode failed at byte {byte_pos}",
                    {"error": str(e)}
                )
        
        return bytes(result)[:original_size]
    
    def _decode_xor(self, chunks: Dict[int, bytes], original_size: int) -> bytes:
        """
        Décode avec XOR simple (fallback).
        
        Cette méthode ne peut récupérer qu'un seul chunk manquant par groupe.
        
        Args:
            chunks: Chunks disponibles
            original_size: Taille originale
            
        Returns:
            Données reconstruites
        """
        # Vérifier qu'on a assez de chunks
        data_indices = [i for i in range(self.k) if i in chunks]
        
        if len(data_indices) >= self.k:
            # Tous les chunks de données sont là
            result = b''.join(chunks[i] for i in range(self.k))
            return result[:original_size]
        
        # Essayer de récupérer les chunks manquants avec XOR
        missing_data = [i for i in range(self.k) if i not in chunks]
        
        if len(missing_data) > self.m:
            raise InsufficientChunksError(
                f"XOR fallback can only recover {self.m} missing chunks",
                available_chunks=len(chunks),
                required_chunks=self.k,
                missing_indices=missing_data
            )
        
        # Reconstruction simple avec XOR
        chunk_size = len(next(iter(chunks.values())))
        reconstructed = dict(chunks)
        
        for missing_idx in missing_data:
            # Trouver un chunk de parité qui couvre ce chunk
            for p in range(self.m):
                parity_idx = self.k + p
                if parity_idx in chunks:
                    # Reconstruire avec XOR
                    recovered = bytearray(chunk_size)
                    for j in range(chunk_size):
                        recovered[j] = chunks[parity_idx][j]
                        for i in range(self.k):
                            if i != missing_idx and i in reconstructed:
                                recovered[j] ^= reconstructed[i][j]
                    reconstructed[missing_idx] = bytes(recovered)
                    break
        
        result = b''.join(reconstructed[i] for i in range(self.k))
        return result[:original_size]
    
    def create_local_groups(self, k: int, group_size: int = 2) -> List[LocalGroup]:
        """
        Crée les groupes locaux pour LRC.
        
        Divise les K chunks de données en groupes de taille group_size.
        Chaque groupe aura un symbole de récupération local.
        
        Args:
            k: Nombre de chunks de données
            group_size: Taille de chaque groupe local (défaut: 2)
            
        Returns:
            Liste de LocalGroup
            
        Example:
            >>> encoder = ReedSolomonEncoder(k=6, m=4)
            >>> groups = encoder.create_local_groups(6, group_size=2)
            >>> len(groups)
            3
            >>> groups[0].chunk_indices
            [0, 1]
            >>> groups[1].chunk_indices
            [2, 3]
        """
        groups = []
        num_groups = (k + group_size - 1) // group_size
        
        # L'index de récupération locale commence après data + parity
        local_recovery_start = self.k + self.m
        
        for g in range(num_groups):
            start_idx = g * group_size
            end_idx = min(start_idx + group_size, k)
            
            group = LocalGroup(
                group_id=g,
                chunk_indices=list(range(start_idx, end_idx)),
                local_recovery_idx=local_recovery_start + g
            )
            groups.append(group)
        
        self.logger.debug(f"Créé {len(groups)} groupes locaux LRC")
        return groups
    
    def encode_local_recovery_symbols(
        self, 
        data_chunks: List[bytes],
        local_groups: List[LocalGroup]
    ) -> List[bytes]:
        """
        Encode les symboles de récupération locaux pour LRC.
        
        Pour chaque groupe local, génère un symbole de récupération
        qui est le XOR de tous les chunks du groupe.
        
        Args:
            data_chunks: Liste des chunks de données
            local_groups: Liste des groupes locaux
            
        Returns:
            Liste des symboles de récupération locaux
            
        Example:
            >>> encoder = ReedSolomonEncoder(k=4, m=2)
            >>> data = b'A' * 100 + b'B' * 100 + b'C' * 100 + b'D' * 100
            >>> data_chunks, _ = encoder.encode_data(data)
            >>> groups = encoder.create_local_groups(4, group_size=2)
            >>> local_symbols = encoder.encode_local_recovery_symbols(data_chunks, groups)
            >>> len(local_symbols)
            2
        """
        local_recovery_symbols = []
        
        for group in local_groups:
            # XOR tous les chunks du groupe
            chunk_size = len(data_chunks[group.chunk_indices[0]])
            recovery = bytearray(chunk_size)
            
            for idx in group.chunk_indices:
                if idx < len(data_chunks):
                    chunk = data_chunks[idx]
                    for j in range(len(chunk)):
                        recovery[j] ^= chunk[j]
            
            local_recovery_symbols.append(bytes(recovery))
            self.logger.debug(
                f"Symbole de récupération local créé pour groupe {group.group_id}: "
                f"indices {group.chunk_indices}"
            )
        
        return local_recovery_symbols
    
    def decode_with_lrc(
        self,
        chunks: Dict[int, bytes],
        local_groups: List[LocalGroup],
        local_recovery_symbols: Dict[int, bytes],
        original_size: int
    ) -> bytes:
        """
        Décode avec LRC (Local Reconstruction Codes).
        
        Essaie d'abord de récupérer les chunks manquants via les groupes
        locaux (plus efficace), puis utilise Reed-Solomon si nécessaire.
        
        Args:
            chunks: Chunks de données et parité disponibles {idx: data}
            local_groups: Liste des groupes locaux
            local_recovery_symbols: Symboles de récupération locaux {group_idx: data}
            original_size: Taille originale des données
            
        Returns:
            Données originales reconstruites
            
        Example:
            >>> encoder = ReedSolomonEncoder(k=4, m=2)
            >>> data = b'Test data for LRC encoding'
            >>> data_chunks, parity_chunks = encoder.encode_data(data)
            >>> groups = encoder.create_local_groups(4, group_size=2)
            >>> local_symbols = encoder.encode_local_recovery_symbols(data_chunks, groups)
            >>> # Simuler perte du chunk 1
            >>> available = {0: data_chunks[0], 2: data_chunks[2], 3: data_chunks[3]}
            >>> local_syms = {0: local_symbols[0]}  # Symbole du groupe 0
            >>> recovered = encoder.decode_with_lrc(available, groups, local_syms, len(data))
            >>> recovered[:len(data)] == data
            True
        """
        recovered_chunks = dict(chunks)
        
        # Phase 1: Récupération locale
        for group in local_groups:
            missing_in_group = [
                idx for idx in group.chunk_indices 
                if idx not in recovered_chunks
            ]
            
            # Si un seul chunk manque dans le groupe et qu'on a le symbole local
            if len(missing_in_group) == 1:
                local_sym_idx = group.group_id
                if local_sym_idx in local_recovery_symbols:
                    missing_idx = missing_in_group[0]
                    
                    # Récupérer avec XOR
                    local_sym = local_recovery_symbols[local_sym_idx]
                    recovered = bytearray(len(local_sym))
                    
                    for j in range(len(local_sym)):
                        recovered[j] = local_sym[j]
                        for idx in group.chunk_indices:
                            if idx != missing_idx and idx in recovered_chunks:
                                recovered[j] ^= recovered_chunks[idx][j]
                    
                    recovered_chunks[missing_idx] = bytes(recovered)
                    self.logger.debug(
                        f"Chunk {missing_idx} récupéré via LRC groupe {group.group_id}"
                    )
        
        # Phase 2: Si on a maintenant tous les chunks de données
        data_indices = [i for i in range(self.k) if i in recovered_chunks]
        if len(data_indices) == self.k:
            result = b''.join(recovered_chunks[i] for i in range(self.k))
            return result[:original_size]
        
        # Phase 3: Utiliser Reed-Solomon pour les chunks restants
        self.logger.debug(
            f"LRC incomplet, passage à RS: {len(data_indices)}/{self.k} chunks de données"
        )
        return self.decode_data(recovered_chunks, original_size)
    
    def get_encoding_info(self) -> Dict:
        """
        Retourne les informations sur la configuration d'encodage.
        
        Returns:
            Dictionnaire avec les paramètres d'encodage
        """
        return {
            'k': self.k,
            'm': self.m,
            'nsym': self.nsym,
            'total_chunks': self.total_chunks,
            'min_recovery': self.k,
            'overhead_ratio': (self.k + self.m) / self.k,
            'reedsolo_available': REEDSOLO_AVAILABLE,
        }


def create_encoder(k: int = 6, m: int = 4, 
                  logger: Optional[logging.Logger] = None) -> ReedSolomonEncoder:
    """
    Factory function pour créer un encodeur Reed-Solomon.
    
    Args:
        k: Nombre de chunks de données
        m: Nombre de chunks de parité
        logger: Logger optionnel
        
    Returns:
        Instance de ReedSolomonEncoder configurée
        
    Example:
        >>> encoder = create_encoder(k=6, m=4)
        >>> encoder.k
        6
    """
    return ReedSolomonEncoder(k=k, m=m, nsym=m, logger=logger)
