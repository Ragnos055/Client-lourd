import socket
import json
import time
import threading


class connection:

    def __init__(self, srv_addr, srv_port, peer_ip, peer_port, keepalive_interval):
        self.uuid = None
        self.srv_addr = srv_addr
        self.srv_port = srv_port
        self.peer_ip = peer_ip
        self.peer_port = peer_port
        self.keepalive_interval = keepalive_interval
        self._stop_event = threading.Event()  # Event par instance

        # Effectue une annonce initiale et récupère les pairs,
        # puis démarre la boucle périodique dans un thread daemon.
        # Ne bloque plus le thread appelant (utile pour une interface graphique).
        self.announce()
        self.get_peers()
        self._thread = threading.Thread(target=self.periodic_announce, daemon=True)
        self._thread.start()

    def close(self):
        """Arrête proprement la boucle périodique de cette instance."""
        self._stop_event.set()
        try:
            if hasattr(self, '_thread') and self._thread.is_alive():
                self._thread.join(timeout=2)
        except Exception:
            pass

    def send_request(self, payload):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.connect((self.srv_addr, self.srv_port))
                s.sendall(json.dumps(payload).encode())
                response = s.recv(4096)
            except Exception as e:
                print("Erreur de connexion au tracker:", e)
                return {}
        return json.loads(response.decode())


    def announce(self):
        req = {"action": "announce", "ip": self.peer_ip, "port": self.peer_port}
        if self.uuid:
            req["uuid"] = self.uuid
        resp = self.send_request(req)
        self.uuid = resp.get("uuid", self.uuid)
        print("Annonce envoyée:", resp)
        return resp


    def get_peers(self):
        req = {"action": "getpeers"}
        if self.uuid:
            req["uuid"] = self.uuid
        resp = self.send_request(req)
        print("Pairs récupérés:", resp.get("peers", []))
        return resp


    def periodic_announce(self):
        """Boucle de keepalive - annonce périodiquement le peer au tracker."""
        while not self._stop_event.wait(self.keepalive_interval):
            try:
                self.announce()
                self.get_peers()
            except Exception as e:
                print(f"Erreur dans periodic_announce: {e}")
