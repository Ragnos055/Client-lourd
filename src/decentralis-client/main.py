from connection.connection import connection

TRACKER_HOST = "127.0.0.1"
TRACKER_PORT = 5000

PEER_IP = "127.0.0.1"  # Put your public IP or local IP here
PEER_PORT = 6000       # Port your peer will listen on
KEEPALIVE_INTERVAL = 15

def main():
    connection(TRACKER_HOST, TRACKER_PORT, PEER_IP, PEER_PORT, KEEPALIVE_INTERVAL)

main()