"""
Configuration globale pour le système de chunking P2P.

Ce module contient toutes les constantes et paramètres configurables
pour le découpage, l'encodage Reed-Solomon/LRC, la distribution
et la rétention des chunks.

Example:
    >>> from chunking.config import CHUNKING_CONFIG
    >>> CHUNKING_CONFIG['DEFAULT_CHUNK_SIZE_MB']
    10
    >>> CHUNKING_CONFIG['REED_SOLOMON']['K']
    6
"""

import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional

# Logger pour ce module
logger = logging.getLogger(__name__)


def _get_env_int(key: str, default: int) -> int:
    """
    Récupère une variable d'environnement comme entier.
    
    Args:
        key: Nom de la variable d'environnement
        default: Valeur par défaut si non définie
        
    Returns:
        Valeur entière de la variable ou default
        
    Example:
        >>> import os
        >>> os.environ['TEST_VAR'] = '42'
        >>> _get_env_int('TEST_VAR', 10)
        42
        >>> _get_env_int('NONEXISTENT', 10)
        10
    """
    value = os.environ.get(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning(f"Variable d'environnement {key}={value} n'est pas un entier, "
                       f"utilisation de la valeur par défaut {default}")
        return default


def _get_env_float(key: str, default: float) -> float:
    """
    Récupère une variable d'environnement comme float.
    
    Args:
        key: Nom de la variable d'environnement
        default: Valeur par défaut si non définie
        
    Returns:
        Valeur float de la variable ou default
    """
    value = os.environ.get(key)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        logger.warning(f"Variable d'environnement {key}={value} n'est pas un float, "
                       f"utilisation de la valeur par défaut {default}")
        return default


def _get_env_str(key: str, default: str) -> str:
    """
    Récupère une variable d'environnement comme string.
    
    Args:
        key: Nom de la variable d'environnement
        default: Valeur par défaut si non définie
        
    Returns:
        Valeur string de la variable ou default
    """
    return os.environ.get(key, default)


def _expand_path(path: str) -> str:
    """
    Étend un chemin avec ~ et variables d'environnement.
    
    Args:
        path: Chemin à étendre
        
    Returns:
        Chemin absolu étendu
        
    Example:
        >>> import os
        >>> _expand_path('~/.decentralis')  # doctest: +ELLIPSIS
        '...'
    """
    return os.path.abspath(os.path.expanduser(os.path.expandvars(path)))


def _ensure_directory(path: str) -> str:
    """
    Crée un répertoire s'il n'existe pas.
    
    Args:
        path: Chemin du répertoire à créer
        
    Returns:
        Chemin absolu du répertoire créé
        
    Raises:
        OSError: Si la création échoue
    """
    expanded = _expand_path(path)
    Path(expanded).mkdir(parents=True, exist_ok=True)
    return expanded


def _validate_reed_solomon_params(k: int, m: int) -> bool:
    """
    Valide les paramètres Reed-Solomon.
    
    Args:
        k: Nombre de chunks de données
        m: Nombre de chunks de parité
        
    Returns:
        True si les paramètres sont valides
        
    Raises:
        ValueError: Si K + M > 255 (limite Reed-Solomon GF(2^8))
        
    Example:
        >>> _validate_reed_solomon_params(6, 4)
        True
        >>> _validate_reed_solomon_params(200, 60)  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        ValueError: ...
    """
    if k + m > 255:
        raise ValueError(
            f"K + M = {k + m} dépasse la limite Reed-Solomon de 255 "
            f"(contrainte du corps de Galois GF(2^8))"
        )
    if k < 1:
        raise ValueError(f"K doit être >= 1, reçu: {k}")
    if m < 1:
        raise ValueError(f"M doit être >= 1, reçu: {m}")
    return True


# ============================================================================
# CONFIGURATION PRINCIPALE
# ============================================================================

# Chemins de base
_BASE_CONFIG_DIR = _get_env_str('DECENTRALIS_CONFIG_DIR', '~/.decentralis')
_BASE_STORAGE_DIR = _get_env_str('DECENTRALIS_STORAGE_DIR', '~/.decentralis/chunks')
_BASE_DB_PATH = _get_env_str('DECENTRALIS_CHUNK_DB', '~/.decentralis/chunk_metadata.db')

# Paramètres de taille
_MIN_FILE_SIZE_MB = _get_env_int('DECENTRALIS_MIN_FILE_SIZE_MB', 1)
_DEFAULT_CHUNK_SIZE_MB = _get_env_int('DECENTRALIS_CHUNK_SIZE_MB', 10)
_MAX_CHUNK_SIZE_MB = _get_env_int('DECENTRALIS_MAX_CHUNK_SIZE_MB', 100)

# Paramètres Reed-Solomon
_RS_K = _get_env_int('DECENTRALIS_RS_K', 6)  # Chunks de données
_RS_M = _get_env_int('DECENTRALIS_RS_M', 4)  # Chunks de parité
_RS_TOTAL = _RS_K + _RS_M
_RS_MIN_RECOVERY = _RS_K  # Minimum pour récupérer

# Valider les paramètres RS
_validate_reed_solomon_params(_RS_K, _RS_M)

# Paramètres LRC (Local Reconstruction Codes)
_LRC_LOCAL_GROUP_SIZE = _get_env_int('DECENTRALIS_LRC_GROUP_SIZE', 2)
_LRC_GLOBAL_RECOVERY_SYMBOLS = _get_env_int('DECENTRALIS_LRC_GLOBAL_SYMBOLS', 2)

# Paramètres de rétention
_RETENTION_DAYS = _get_env_int('DECENTRALIS_RETENTION_DAYS', 30)
_CLEANUP_INTERVAL_HOURS = _get_env_int('DECENTRALIS_CLEANUP_INTERVAL_HOURS', 6)

# Paramètres de sélection des peers
_MIN_PEER_RELIABILITY_SCORE = _get_env_float('DECENTRALIS_MIN_RELIABILITY', 0.5)
_PEER_UPTIME_BONUS = _get_env_float('DECENTRALIS_UPTIME_BONUS', 0.1)

# Paramètres de réplication
_REPLICATION_RETRY_DELAY_SECONDS = _get_env_int('DECENTRALIS_REPLICATION_RETRY_DELAY', 60)
_MAX_REPLICATION_RETRIES = _get_env_int('DECENTRALIS_MAX_REPLICATION_RETRIES', 3)

# Paramètres réseau
_RPC_TIMEOUT_SECONDS = _get_env_int('DECENTRALIS_RPC_TIMEOUT', 30)
_RPC_MAX_CONNECTIONS = _get_env_int('DECENTRALIS_RPC_MAX_CONNECTIONS', 10)
_CHUNK_TRANSFER_BUFFER_SIZE = _get_env_int('DECENTRALIS_TRANSFER_BUFFER', 65536)


# Configuration complète exportée
CHUNKING_CONFIG: Dict[str, Any] = {
    # === Chemins ===
    'CONFIG_DIR': _expand_path(_BASE_CONFIG_DIR),
    'STORAGE_DIR': _expand_path(_BASE_STORAGE_DIR),
    'CHUNK_DB_PATH': _expand_path(_BASE_DB_PATH),
    
    # === Tailles de fichiers ===
    'MIN_FILE_SIZE_MB': _MIN_FILE_SIZE_MB,
    'MIN_FILE_SIZE_BYTES': _MIN_FILE_SIZE_MB * 1024 * 1024,
    'DEFAULT_CHUNK_SIZE_MB': _DEFAULT_CHUNK_SIZE_MB,
    'DEFAULT_CHUNK_SIZE_BYTES': _DEFAULT_CHUNK_SIZE_MB * 1024 * 1024,
    'MAX_CHUNK_SIZE_MB': _MAX_CHUNK_SIZE_MB,
    'MAX_CHUNK_SIZE_BYTES': _MAX_CHUNK_SIZE_MB * 1024 * 1024,
    
    # === Reed-Solomon ===
    'REED_SOLOMON': {
        'K': _RS_K,                    # Chunks de données originaux
        'M': _RS_M,                    # Chunks de parité
        'TOTAL': _RS_TOTAL,            # Total des chunks
        'MIN_RECOVERY': _RS_MIN_RECOVERY,  # Minimum pour reconstruction
        'NSYM': _RS_M,                 # Nombre de symboles de parité pour reedsolo
    },
    
    # === LRC (Local Reconstruction Codes) ===
    'LRC': {
        'LOCAL_GROUP_SIZE': _LRC_LOCAL_GROUP_SIZE,
        'GLOBAL_RECOVERY_SYMBOLS': _LRC_GLOBAL_RECOVERY_SYMBOLS,
    },
    
    # === Rétention ===
    'RETENTION': {
        'DAYS': _RETENTION_DAYS,
        'CLEANUP_INTERVAL_HOURS': _CLEANUP_INTERVAL_HOURS,
        'CLEANUP_INTERVAL_SECONDS': _CLEANUP_INTERVAL_HOURS * 3600,
    },
    
    # === Sélection des peers ===
    'PEER_SELECTION': {
        'MIN_RELIABILITY_SCORE': _MIN_PEER_RELIABILITY_SCORE,
        'UPTIME_BONUS': _PEER_UPTIME_BONUS,
        'MAX_CHUNKS_PER_PEER_RATIO': 0.5,  # Max 50% des chunks sur un peer
    },
    
    # === Réplication ===
    'REPLICATION': {
        'RETRY_DELAY_SECONDS': _REPLICATION_RETRY_DELAY_SECONDS,
        'MAX_RETRIES': _MAX_REPLICATION_RETRIES,
        'BATCH_SIZE': 10,  # Chunks à traiter par batch
    },
    
    # === Réseau ===
    'NETWORK': {
        'RPC_TIMEOUT_SECONDS': _RPC_TIMEOUT_SECONDS,
        'MAX_CONNECTIONS': _RPC_MAX_CONNECTIONS,
        'TRANSFER_BUFFER_SIZE': _CHUNK_TRANSFER_BUFFER_SIZE,
        'KEEPALIVE_INTERVAL_SECONDS': 30,
        'CONNECTION_RETRY_DELAY_SECONDS': 5,
        'MAX_CONNECTION_RETRIES': 3,
    },
    
    # === Algorithmes ===
    'ALGORITHMS': {
        'DEFAULT': 'reed-solomon+lrc',
        'SUPPORTED': ['reed-solomon', 'reed-solomon+lrc'],
        'HASH': 'sha256',
    },
    
    # === Limites ===
    'LIMITS': {
        'MAX_FILE_SIZE_GB': 10,
        'MAX_FILES_PER_OWNER': 1000,
        'MAX_PENDING_REPLICATIONS': 100,
        'MAX_CONCURRENT_TRANSFERS': 5,
    },
}


def get_config() -> Dict[str, Any]:
    """
    Retourne la configuration complète du chunking.
    
    Returns:
        Dictionnaire de configuration
        
    Example:
        >>> config = get_config()
        >>> config['REED_SOLOMON']['K']
        6
    """
    return CHUNKING_CONFIG.copy()


def get_storage_dir() -> str:
    """
    Retourne le répertoire de stockage des chunks, le créant si nécessaire.
    
    Returns:
        Chemin absolu du répertoire de stockage
        
    Example:
        >>> path = get_storage_dir()
        >>> os.path.isabs(path)
        True
    """
    return _ensure_directory(CHUNKING_CONFIG['STORAGE_DIR'])


def get_config_dir() -> str:
    """
    Retourne le répertoire de configuration, le créant si nécessaire.
    
    Returns:
        Chemin absolu du répertoire de configuration
    """
    return _ensure_directory(CHUNKING_CONFIG['CONFIG_DIR'])


def get_db_path() -> str:
    """
    Retourne le chemin de la base de données, créant le répertoire parent si nécessaire.
    
    Returns:
        Chemin absolu de la base de données SQLite
    """
    db_path = CHUNKING_CONFIG['CHUNK_DB_PATH']
    parent_dir = os.path.dirname(db_path)
    _ensure_directory(parent_dir)
    return db_path


def calculate_optimal_chunk_size(file_size_bytes: int) -> int:
    """
    Calcule la taille optimale des chunks pour un fichier donné.
    
    La taille est choisie pour avoir entre 6 et 100 chunks par fichier,
    en restant dans les limites configurées.
    
    Args:
        file_size_bytes: Taille du fichier en bytes
        
    Returns:
        Taille optimale d'un chunk en bytes
        
    Example:
        >>> # Fichier de 100 MB
        >>> size = calculate_optimal_chunk_size(100 * 1024 * 1024)
        >>> 1024 * 1024 <= size <= 100 * 1024 * 1024
        True
    """
    min_size = CHUNKING_CONFIG['MIN_FILE_SIZE_BYTES']
    default_size = CHUNKING_CONFIG['DEFAULT_CHUNK_SIZE_BYTES']
    max_size = CHUNKING_CONFIG['MAX_CHUNK_SIZE_BYTES']
    k = CHUNKING_CONFIG['REED_SOLOMON']['K']
    
    # Calculer la taille idéale pour avoir K chunks de données
    ideal_chunk_size = file_size_bytes // k
    
    # Appliquer les limites
    chunk_size = max(min_size, min(ideal_chunk_size, max_size))
    
    # Si le fichier est petit, utiliser la taille par défaut
    if file_size_bytes < default_size * k:
        chunk_size = min(default_size, file_size_bytes // k) if file_size_bytes >= k else file_size_bytes
    
    return max(chunk_size, 1)  # Toujours au moins 1 byte


def log_config() -> None:
    """
    Log la configuration active pour le debug.
    
    Cette fonction est appelée au démarrage pour tracer
    les paramètres actifs dans les logs.
    """
    logger.info("=== Configuration Chunking P2P ===")
    logger.info(f"Répertoire de stockage: {CHUNKING_CONFIG['STORAGE_DIR']}")
    logger.info(f"Base de données: {CHUNKING_CONFIG['CHUNK_DB_PATH']}")
    logger.info(f"Taille chunk par défaut: {CHUNKING_CONFIG['DEFAULT_CHUNK_SIZE_MB']} MB")
    logger.info(f"Reed-Solomon: K={CHUNKING_CONFIG['REED_SOLOMON']['K']}, "
                f"M={CHUNKING_CONFIG['REED_SOLOMON']['M']}")
    logger.info(f"LRC: group_size={CHUNKING_CONFIG['LRC']['LOCAL_GROUP_SIZE']}, "
                f"global_symbols={CHUNKING_CONFIG['LRC']['GLOBAL_RECOVERY_SYMBOLS']}")
    logger.info(f"Rétention: {CHUNKING_CONFIG['RETENTION']['DAYS']} jours")
    logger.info(f"Score minimum peer: {CHUNKING_CONFIG['PEER_SELECTION']['MIN_RELIABILITY_SCORE']}")
    logger.info("================================")


# Log de la configuration au chargement du module
if __name__ != '__main__':
    # Configurer le logging si pas déjà fait
    if not logger.handlers:
        logging.basicConfig(level=logging.INFO)
    log_config()
