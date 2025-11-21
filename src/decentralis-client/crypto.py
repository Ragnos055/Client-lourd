import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305


def _ensure_key_bytes(key_hex: str, expected_len: int):
    if not key_hex:
        raise ValueError('Clé manquante')
    try:
        key = bytes.fromhex(key_hex)
    except Exception as e:
        raise ValueError('Clé invalide (doit être hex)') from e
    if len(key) != expected_len:
        raise ValueError(f'Clé de longueur incorrecte ({len(key)} bytes), attendu {expected_len} bytes')
    return key


def encrypt_file(in_path: str, out_path: str, key_hex: str, algorithm: str = 'AES-256') -> None:
    """Encrypt the whole file and write to out_path.

    File format: nonce (12 bytes) + ciphertext
    """
    data = None
    with open(in_path, 'rb') as f:
        data = f.read()

    if algorithm == 'AES-256':
        key = _ensure_key_bytes(key_hex, 32)
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)
        ct = aesgcm.encrypt(nonce, data, None)
        with open(out_path, 'wb') as f:
            f.write(nonce + ct)
    elif algorithm == 'ChaCha20':
        key = _ensure_key_bytes(key_hex, 32)
        chacha = ChaCha20Poly1305(key)
        nonce = os.urandom(12)
        ct = chacha.encrypt(nonce, data, None)
        with open(out_path, 'wb') as f:
            f.write(nonce + ct)
    else:
        raise ValueError('Algorithme non supporté')


def decrypt_file(in_path: str, out_path: str, key_hex: str, algorithm: str = 'AES-256') -> None:
    """Decrypt file previously created by encrypt_file.

    Expects first 12 bytes to be nonce.
    """
    with open(in_path, 'rb') as f:
        blob = f.read()
    if len(blob) < 12:
        raise ValueError('Fichier chiffré invalide')
    nonce = blob[:12]
    ct = blob[12:]

    if algorithm == 'AES-256':
        key = _ensure_key_bytes(key_hex, 32)
        aesgcm = AESGCM(key)
        pt = aesgcm.decrypt(nonce, ct, None)
        with open(out_path, 'wb') as f:
            f.write(pt)
    elif algorithm == 'ChaCha20':
        key = _ensure_key_bytes(key_hex, 32)
        chacha = ChaCha20Poly1305(key)
        pt = chacha.decrypt(nonce, ct, None)
        with open(out_path, 'wb') as f:
            f.write(pt)
    else:
        raise ValueError('Algorithme non supporté')
