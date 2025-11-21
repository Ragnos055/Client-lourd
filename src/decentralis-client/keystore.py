import os
import json
from typing import Dict

from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def derive_key_hex(passphrase: str, salt_hex: str, iterations: int = 200000) -> str:
    salt = bytes.fromhex(salt_hex)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    key = kdf.derive(passphrase.encode('utf-8'))
    return key.hex()


def load_retention(path: str) -> Dict:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def generate_retention_file(path: str, passphrase: str, iterations: int = 200000, algorithm: str = 'AES-256') -> None:
    """Create a retention JSON file describing KDF params and including a small verification blob.

    The file DOES NOT store the passphrase. It stores salt, iterations, algorithm and a verification
    ciphertext that can be used to validate the passphrase later.
    """
    import os

    salt = os.urandom(16)
    salt_hex = salt.hex()
    key_hex = derive_key_hex(passphrase, salt_hex, iterations)
    key = bytes.fromhex(key_hex)

    # verification: encrypt a short known plaintext with AES-GCM using derived key
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, b'decentralis-verification', None)
    verify = (nonce + ct).hex()

    payload = {
        'version': 1,
        'kdf': 'pbkdf2',
        'salt': salt_hex,
        'iterations': iterations,
        'algorithm': algorithm,
        'verify': verify,
    }

    # write atomically
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(payload, f)
    os.replace(tmp, path)


def verify_passphrase_and_get_keyhex(path: str, passphrase: str) -> str:
    data = load_retention(path)
    salt = data.get('salt')
    iterations = int(data.get('iterations', 200000))
    algorithm = data.get('algorithm', 'AES-256')

    key_hex = derive_key_hex(passphrase, salt, iterations)
    key = bytes.fromhex(key_hex)

    # verify by decrypting verify blob
    verify_hex = data.get('verify')
    if not verify_hex:
        raise ValueError('Fichier de rétention invalide: pas de vérification')
    blob = bytes.fromhex(verify_hex)
    nonce = blob[:12]
    ct = blob[12:]
    aesgcm = AESGCM(key)
    pt = aesgcm.decrypt(nonce, ct, None)
    if pt != b'decentralis-verification':
        raise ValueError('Passphrase incorrecte')

    return key_hex


def export_retention(src_path: str, dst_path: str) -> None:
    import shutil

    shutil.copyfile(src_path, dst_path)
