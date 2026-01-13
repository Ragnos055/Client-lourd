import json
import os
import secrets
import socket
import struct
import threading
import tempfile
from typing import Optional, Callable

import crypto


class P2PServer:
    """
    Petit serveur TCP pour recevoir des fichiers chiffrés.
    Il n'effectue AUCUN déchiffrement : il stocke le ciphertext tel quel avec un nom aléatoire fourni par l'émetteur.
    """

    def __init__(self, host: str, port: int, storage_dir: str, on_file_received: Optional[Callable[[str, str], None]] = None):
        self.host = host
        self.port = port
        self.storage_dir = storage_dir
        self.on_file_received = on_file_received
        self._thread = None
        self._stop = threading.Event()

        os.makedirs(self.storage_dir, exist_ok=True)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        try:
            # connexion factice pour débloquer accept
            with socket.create_connection((self.host, self.port), timeout=1):
                pass
        except Exception:
            pass
        if self._thread:
            self._thread.join(timeout=1)

    def _serve(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind((self.host, self.port))
            srv.listen(5)
            while not self._stop.is_set():
                try:
                    srv.settimeout(1.0)
                    conn, addr = srv.accept()
                except socket.timeout:
                    continue
                except Exception:
                    if self._stop.is_set():
                        break
                    continue

                with conn:
                    try:
                        header = _recv_header(conn)
                        if not header:
                            continue
                        name = header.get("name") or secrets.token_hex(16)
                        size = int(header.get("size", 0))
                        dst_dir = os.path.join(self.storage_dir, "incoming")
                        os.makedirs(dst_dir, exist_ok=True)
                        dst_path = os.path.join(dst_dir, name)
                        _recv_file(conn, dst_path, size)
                        if self.on_file_received:
                            try:
                                self.on_file_received(dst_path, addr[0])
                            except Exception:
                                pass
                    except Exception:
                        continue


def _recv_all(conn: socket.socket, n: int) -> bytes:
    data = b""
    while len(data) < n:
        chunk = conn.recv(n - len(data))
        if not chunk:
            break
        data += chunk
    return data


def _recv_header(conn: socket.socket) -> Optional[dict]:
    raw = _recv_all(conn, 4)
    if len(raw) != 4:
        return None
    (hdr_len,) = struct.unpack("!I", raw)
    hdr_bytes = _recv_all(conn, hdr_len)
    if len(hdr_bytes) != hdr_len:
        return None
    return json.loads(hdr_bytes.decode())


def _recv_file(conn: socket.socket, dst_path: str, size: int):
    with open(dst_path, "wb") as f:
        remaining = size
        while remaining > 0:
            chunk = conn.recv(min(65536, remaining))
            if not chunk:
                break
            f.write(chunk)
            remaining -= len(chunk)


def _send_cipherfile(dst_host: str, dst_port: int, cipher_path: str, header: dict):
    size = os.path.getsize(cipher_path)
    header = dict(header)
    header.setdefault("size", size)
    header_bytes = json.dumps(header).encode()
    prefix = struct.pack("!I", len(header_bytes))

    with socket.create_connection((dst_host, dst_port), timeout=5) as s:
        s.sendall(prefix + header_bytes)
        with open(cipher_path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                s.sendall(chunk)


def send_encrypted_file(dst_host: str, dst_port: int, in_path: str, algo: str, key_hex: str):
    """
    Chiffre le fichier local avec la clé/algorithme fournis puis envoie le ciphertext via TCP.
    Le nom envoyé dans l'en-tête est un jeton aléatoire pour éviter toute fuite d'information.
    """
    rand_name = secrets.token_hex(16)

    # chiffrer vers un fichier temporaire
    fd, tmp_cipher = tempfile.mkstemp(prefix="cipher_", suffix=".bin")
    os.close(fd)
    try:
        crypto.encrypt_file(in_path, tmp_cipher, key_hex, algorithm=algo)
        header = {
            "name": rand_name,
            "algo": algo,
            "v": 1,
        }
        _send_cipherfile(dst_host, dst_port, tmp_cipher, header)
    finally:
        try:
            os.remove(tmp_cipher)
        except Exception:
            pass

