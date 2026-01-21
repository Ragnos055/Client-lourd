# Architecture du Projet Decentralis Client

> Ce document sert de référence complète pour les agents de code et les développeurs.
> Il détaille la structure, les composants, les flux de données et les conventions du projet.

---

## 📋 Vue d'ensemble

**Decentralis Client** est un client GUI de bureau pour un réseau pair-à-pair (P2P) décentralisé.

### Objectifs principaux
- Connexion à un serveur d'annonce (tracker) pour découvrir des pairs
- Envoi et réception de fichiers via le réseau P2P avec chiffrement
- Gestion locale d'un espace de stockage chiffré (conteneur)

### Technologies utilisées
| Composant | Technologie |
|-----------|-------------|
| Langage | Python 3.8+ (recommandé 3.11) |
| Interface graphique | Tkinter (ttk) |
| Cryptographie | `cryptography` (AESGCM, ChaCha20Poly1305, PBKDF2) |
| Chunking P2P | `reedsolo` (Reed-Solomon), asyncio |
| Build | PyInstaller |

---

## 📁 Structure des fichiers

```
Client-lourd/
├── src/
│   └── decentralis-client/          # Code source principal
│       ├── main.py                  # Point d'entrée
│       ├── gui.py                   # Fenêtre principale et orchestration
│       ├── crypto.py                # Fonctions de chiffrement/déchiffrement de fichiers
│       ├── keystore.py              # Gestion des clés et fichier de rétention
│       ├── connection/              # Module de connexion réseau
│       │   ├── __init__.py
│       │   └── connection.py        # Logique de connexion au tracker
│       ├── chunking/                # Module de chunking P2P (NOUVEAU)
│       │   ├── __init__.py          # Exports du module
│       │   ├── config.py            # Configuration globale du chunking
│       │   ├── models.py            # Modèles de données (dataclasses)
│       │   ├── exceptions.py        # Exceptions personnalisées
│       │   ├── reed_solomon.py      # Encodeur/décodeur Reed-Solomon + LRC
│       │   ├── chunk_store.py       # Stockage local des chunks sur disque
│       │   ├── chunk_db.py          # Base de données SQLite des métadonnées
│       │   ├── chunking_mgr.py      # Orchestrateur principal du chunking
│       │   ├── replication_mgr.py   # Gestion de la réplication/relocalisation
│       │   ├── peer_rpc.py          # Client RPC asynchrone pour P2P
│       │   └── chunk_net.py         # Serveur TCP pour requêtes entrantes
│       └── views/                   # Vues de l'interface
│           ├── __init__.py
│           ├── peers_view.py        # Vue liste des pairs
│           ├── files_view.py        # Vue gestionnaire de fichiers
│           ├── encryption_view.py   # Vue paramètres de chiffrement
│           └── p2p_view.py          # Vue réseau P2P et chunking (NOUVEAU)
├── assets/                          # Ressources (icônes, images)
├── build_windows.ps1                # Script de build Windows
├── build_linux.sh                   # Script de build Linux
├── requirements.txt                 # Dépendances Python
├── README.md                        # Documentation utilisateur
├── README_BUILD.md                  # Instructions de build
└── ARCHITECTURE-CLIENT.md           # Ce fichier
```

---

## 🏗️ Architecture des composants

### Diagramme des dépendances

```
                    ┌──────────────┐
                    │   main.py    │
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐
                    │   gui.py     │ (DecentralisGUI)
                    └──────┬───────┘
                           │
     ┌─────────────────────┼─────────────────────┐
     │          │          │          │          │
     ▼          ▼          ▼          ▼          ▼
┌─────────┐┌─────────┐┌─────────┐┌─────────┐┌─────────┐
│ peers_  ││ files_  ││encrypt- ││ p2p_    ││chunking_│
│ view    ││ view    ││ion_view ││ view    ││ mgr     │
└─────────┘└────┬────┘└────┬────┘└────┬────┘└────┬────┘
                │          │          │          │
                ▼          ▼          └────┬─────┘
          ┌─────────┐┌─────────┐           │
          │crypto.py││keystore │           ▼
          └─────────┘└─────────┘    ┌────────────┐
                                    │  chunking/ │
                                    │  module    │
                                    └────────────┘

   ┌───────────────────────────────────────────────┐
   │            connection/connection.py           │
   │         (Gestion tracker indépendante)        │
   └───────────────────────────────────────────────┘

   ┌───────────────────────────────────────────────┐
   │              chunking/ (module P2P)           │
   │  ┌─────────────────────────────────────────┐  │
   │  │         chunking_mgr.py                 │  │
   │  │       (Orchestrateur principal)         │  │
   │  └─────────────┬───────────────────────────┘  │
   │                │                              │
   │    ┌───────────┼───────────┬────────────┐     │
   │    ▼           ▼           ▼            ▼     │
   │ ┌──────┐  ┌──────────┐  ┌──────┐  ┌────────┐  │
   │ │reed_ │  │chunk_    │  │chunk_│  │replica-│  │
   │ │solo- │  │store.py  │  │db.py │  │tion_   │  │
   │ │mon.py│  │(disque)  │  │(SQL) │  │mgr.py  │  │
   │ └──────┘  └──────────┘  └──────┘  └────────┘  │
   │                                               │
   │    ┌─────────────────┬──────────────────┐     │
   │    ▼                 ▼                  │     │
   │ ┌──────────┐   ┌──────────┐             │     │
   │ │peer_rpc  │   │chunk_net │   ◄─────────┘     │
   │ │(client)  │   │(serveur) │                   │
   │ └──────────┘   └──────────┘                   │
   └───────────────────────────────────────────────┘
```

---

## 📝 Description détaillée des modules

### 1. `main.py` - Point d'entrée

**Rôle**: Lancer l'application GUI.

```python
# Fonction unique
def main():
    run_gui()  # Appelle gui.run_gui()
```

**Usage**: `python src/decentralis-client/main.py`

---

### 2. `gui.py` - Fenêtre principale

**Classe**: `DecentralisGUI`

**Responsabilités**:
- Création de la fenêtre Tkinter principale
- Gestion du header (inputs tracker/peer)
- Menu de navigation entre vues
- Orchestration de la connexion au tracker
- Gestion du fichier de rétention (passphrase au démarrage)

#### Attributs importants

| Attribut | Type | Description |
|----------|------|-------------|
| `root` | `tk.Tk` | Fenêtre Tkinter racine |
| `conn` | `connection` \| `None` | Instance de connexion au tracker |
| `frames` | `dict[str, ttk.Frame]` | Vues chargées (`peers`, `files`, `encryption`) |
| `config_dir` | `str` | Dossier de configuration (`<app_dir>/data`) |
| `storage_dir` | `str` | Dossier de stockage (`<app_dir>/data/storage`) |
| `retention_path` | `str` | Chemin du fichier de rétention (`<app_dir>/data/key.json`) |
| `encryption_settings` | `dict` | Paramètres de chiffrement actuels (`algorithm`, `key`) |
| `_cached_passphrase` | `str` \| `None` | Passphrase en mémoire pour la session |

#### Variables Tkinter (inputs)

| Variable | Type | Valeur par défaut | Description |
|----------|------|-------------------|-------------|
| `srv_ip` | `StringVar` | `"127.0.0.1"` | IP du tracker |
| `srv_port` | `IntVar` | `5000` | Port du tracker |
| `peer_ip` | `StringVar` | `"127.0.0.1"` | IP locale du peer |
| `peer_port` | `IntVar` | `6000` | Port local du peer |
| `keepalive` | `IntVar` | `15` | Intervalle keepalive (secondes) |

#### Méthodes principales

| Méthode | Description |
|---------|-------------|
| `show_view(name)` | Affiche une vue (`peers`, `files`, `encryption`, `p2p`) |
| `_on_connect_click()` | Connexion/Déconnexion du tracker |
| `_disconnect()` | Ferme la connexion proprement |
| `_update_peers()` | Mise à jour périodique des pairs (toutes les 2s) |
| `_ensure_retention_file()` | Vérifie/crée le fichier de rétention au démarrage |
| `_init_chunking()` | **Initialise le ChunkingManager** (NOUVEAU) |
| `_on_close()` | **Cleanup à la fermeture (shutdown ChunkingManager)** (NOUVEAU) |
| `_check_and_restore_container()` | **Restaure container.dat depuis chunks si absent** (NOUVEAU) |
| `_restore_container_async()` | **Restauration asynchrone du container** (NOUVEAU) |
| `_on_container_restored()` | **Callback après restauration réussie** (NOUVEAU) |

#### Flux de démarrage

```
1. Création de la fenêtre et du header
2. Création du menu Vue
3. Création du conteneur principal
4. Initialisation des répertoires (~/.decentralis, ~/.decentralis/storage)
5. Génération de _peer_uuid + _init_chunking() (NOUVEAU)
6. Création de PeersView et EncryptionView
7. _ensure_retention_file() :
   - Si key.json existe → demande passphrase (3 tentatives max)
   - Sinon → propose création ou import
8. Création de FilesView (nécessite encryption_settings)
9. Création de P2PView (NOUVEAU)
10. _check_and_restore_container() : (NOUVEAU)
    - Si container.dat absent ET chunks en base → propose restauration
11. Affichage de la vue files par défaut
```

---

### 3. `connection/connection.py` - Module de connexion tracker

**Classe**: `connection`

**Responsabilités**:
- Communication avec le serveur tracker via TCP/JSON
- Annonce du peer au tracker
- Récupération de la liste des pairs
- Keepalive périodique en arrière-plan

#### Attributs

| Attribut | Type | Description |
|----------|------|-------------|
| `uuid` | `str` \| `None` | UUID assigné par le tracker |
| `srv_addr` | `str` | Adresse IP du tracker |
| `srv_port` | `int` | Port du tracker |
| `peer_ip` | `str` | IP du peer local |
| `peer_port` | `int` | Port du peer local |
| `keepalive_interval` | `int` | Intervalle entre les annonces (secondes) |
| `_thread` | `Thread` | Thread daemon pour keepalive |

#### Méthodes

| Méthode | Retour | Description |
|---------|--------|-------------|
| `send_request(payload)` | `dict` | Envoie une requête JSON au tracker |
| `announce()` | `dict` | Annonce le peer au tracker |
| `get_peers()` | `dict` | Récupère la liste des pairs |
| `periodic_announce()` | - | Boucle de keepalive (thread) |
| `close()` | - | Arrête la boucle périodique |

#### Protocole Tracker (JSON sur TCP)

**Requête announce**:
```json
{"action": "announce", "ip": "192.168.1.10", "port": 6000}
// ou avec uuid existant:
{"action": "announce", "ip": "192.168.1.10", "port": 6000, "uuid": "abc123"}
```

**Réponse**:
```json
{"uuid": "abc123", "status": "ok"}
```

**Requête getpeers**:
```json
{"action": "getpeers", "uuid": "abc123"}
```

**Réponse**:
```json
{"peers": [{"ip": "192.168.1.20", "port": 6001}, {"ip": "192.168.1.30", "port": 6002}]}
```

---

### 4. `crypto.py` - Chiffrement de fichiers

**Responsabilités**:
- Chiffrement/déchiffrement de fichiers avec AES-256-GCM ou ChaCha20-Poly1305
- Gestion du nonce (12 bytes)

#### Fonctions

| Fonction | Paramètres | Description |
|----------|------------|-------------|
| `encrypt_file(in_path, out_path, key_hex, algorithm)` | Chemins + clé hex + algo | Chiffre un fichier |
| `decrypt_file(in_path, out_path, key_hex, algorithm)` | Chemins + clé hex + algo | Déchiffre un fichier |
| `_ensure_key_bytes(key_hex, expected_len)` | Clé hex + longueur | Valide et convertit la clé |

#### Format de fichier chiffré

```
┌────────────────┬─────────────────────────────┐
│  Nonce (12B)   │       Ciphertext + Tag      │
└────────────────┴─────────────────────────────┘
```

#### Algorithmes supportés

| Algorithme | Longueur clé | Longueur nonce |
|------------|--------------|----------------|
| `AES-256` | 32 bytes (64 hex) | 12 bytes |
| `ChaCha20` | 32 bytes (64 hex) | 12 bytes |

---

### 5. `keystore.py` - Gestion des clés et rétention

**Responsabilités**:
- Dérivation de clé depuis passphrase (PBKDF2-HMAC-SHA256)
- Création/validation du fichier de rétention
- Import/export du fichier de rétention

#### Fonctions

| Fonction | Description |
|----------|-------------|
| `derive_key_hex(passphrase, salt_hex, iterations)` | Dérive une clé de 32 bytes depuis la passphrase |
| `load_retention(path)` | Charge le fichier JSON de rétention |
| `generate_retention_file(path, passphrase, iterations, algorithm)` | Crée un nouveau fichier de rétention |
| `verify_passphrase_and_get_keyhex(path, passphrase)` | Vérifie la passphrase et retourne la clé |
| `export_retention(src_path, dst_path)` | Copie le fichier de rétention |

#### Structure du fichier de rétention (`key.json`)

```json
{
  "version": 1,
  "kdf": "pbkdf2",
  "salt": "a1b2c3d4e5f6...",        // 16 bytes hex
  "iterations": 200000,
  "algorithm": "AES-256",
  "verify": "nonce+ciphertext_hex"   // Blob de vérification
}
```

**Note**: La passphrase n'est JAMAIS stockée. Le blob `verify` permet de valider la passphrase en déchiffrant un texte connu (`b'decentralis-verification'`).

---

### 6. `views/peers_view.py` - Vue des pairs

**Classe**: `PeersView(ttk.Frame)`

**Responsabilités**:
- Afficher la liste des pairs connectés au réseau
- Mise à jour automatique toutes les 2 secondes

#### Widgets

| Widget | Type | Description |
|--------|------|-------------|
| Label | `ttk.Label` | Titre "Pairs connus:" |
| `listbox` | `tk.Listbox` | Liste des pairs (format `ip:port`) |

#### Méthodes

| Méthode | Description |
|---------|-------------|
| `update_peers(peers)` | Met à jour la listbox avec la liste des pairs |

---

### 7. `views/files_view.py` - Vue gestionnaire de fichiers

**Classe**: `FilesView(ttk.Frame)`

**Responsabilités**:
- Navigation dans le système de fichiers virtuel (conteneur chiffré)
- Upload/Download de fichiers
- Création/suppression de dossiers
- **Auto-chunking du container.dat après modifications** (NOUVEAU)
- **Synchronisation automatique des chunks vers les pairs** (NOUVEAU)

#### Constantes

| Constante | Valeur | Description |
|-----------|--------|-------------|
| `CONTAINER_NAME` | `'container.dat'` | Nom du fichier conteneur chiffré |
| `CONTAINER_FILE_UUID` | `'container-dat-primary'` | UUID fixe pour le container (NOUVEAU) |

#### Attributs

| Attribut | Type | Description |
|----------|------|-------------|
| `app_gui` | `DecentralisGUI` | Référence à l'application principale |
| `cwd` | `str` | Chemin virtuel actuel ('' = racine) |
| `container` | `dict` | Structure en mémoire du conteneur |
| `_container_hash` | `str` | Hash SHA256 du container pour détecter les changements (NOUVEAU) |
| `_auto_sync_enabled` | `bool` | Active/désactive la sync automatique (NOUVEAU) |

#### Structure du conteneur (JSON)

```json
{
  "entries": {
    "documents": {"type": "dir"},
    "documents/rapport.pdf": {
      "type": "file",
      "content": "base64_encoded_data..."
    },
    "image.png": {
      "type": "file", 
      "content": "base64_encoded_data..."
    }
  }
}
```

#### Widgets

| Widget | Description |
|--------|-------------|
| Toolbar | Boutons: Up, New Folder, Upload, Download, Delete, Refresh |
| `path_var` | Label affichant le chemin actuel |
| `listbox` | Liste des fichiers/dossiers (dossiers avec `/` suffix) |

#### Méthodes

| Méthode | Description |
|---------|-------------|
| `container_path()` | Retourne le chemin complet du fichier conteneur |
| `load_container()` | Déchiffre et charge le conteneur en mémoire |
| `save_container()` | Chiffre, sauvegarde le conteneur, **puis déclenche l'auto-chunk** (MODIFIÉ) |
| `refresh()` | Recharge et réaffiche le contenu du dossier actuel |
| `_trigger_auto_chunk()` | **Chunke automatiquement container.dat et distribue** (NOUVEAU) |
| `_delete_old_container_chunks()` | **Supprime les anciens chunks avant re-chunking** (NOUVEAU) |
| `go_up()` | Remonte d'un niveau dans l'arborescence |
| `enter_selected()` | Entre dans le dossier sélectionné |
| `new_folder()` | Crée un nouveau dossier |
| `upload_file()` | Ajoute un fichier au conteneur |
| `download_file()` | Exporte un fichier du conteneur |
| `delete_selected()` | Supprime un fichier/dossier |

#### Flux Upload

```
1. Sélection du fichier (filedialog)
2. Vérification des paramètres de chiffrement
3. Lecture du fichier → encodage Base64
4. Ajout dans container['entries']
5. save_container() → chiffrement → écriture container.dat
6. refresh()
```

#### Flux Download

```
1. Vérification de la sélection (fichier, pas dossier)
2. Récupération du contenu Base64 depuis container
3. Décodage Base64 → données binaires
4. Écriture dans le répertoire choisi
```

---

### 8. `views/encryption_view.py` - Vue paramètres de chiffrement

**Classe**: `EncryptionView(ttk.Frame)`

**Responsabilités**:
- Configuration de l'algorithme de chiffrement
- Gestion de la passphrase
- Création/Import/Export du fichier de rétention

#### Widgets

| Widget | Variable | Description |
|--------|----------|-------------|
| Combobox | `algo_var` | Sélection algorithme (AES-256, ChaCha20) |
| Entry | `passphrase_var` | Saisie de la passphrase |
| Button | - | Appliquer passphrase |
| Button | - | Générer fichier rétention |
| Button | - | Importer fichier rétention |
| Button | - | Exporter fichier rétention |
| Button | `clear_btn` | Oublier passphrase |
| Label | `status_var` | État de la passphrase |

#### Méthodes

| Méthode | Description |
|---------|-------------|
| `create_retention()` | Crée un nouveau fichier de rétention |
| `import_retention()` | Importe un fichier de rétention existant |
| `export_retention()` | Exporte le fichier de rétention actuel |
| `apply_passphrase()` | Vérifie et applique la passphrase |
| `clear_cached_passphrase()` | Efface la passphrase de la mémoire |

---

### 9. `views/p2p_view.py` - Vue réseau P2P (NOUVEAU)

**Classe**: `P2PView(ttk.Frame)`

**Responsabilités**:
- Interface utilisateur pour le chunking et la distribution P2P
- Chunking de fichiers locaux avec Reed-Solomon
- Distribution de chunks vers les pairs
- Récupération de fichiers depuis le réseau P2P
- Gestion du serveur de chunks local

#### Dépendances

| Module | Usage |
|--------|-------|
| `chunking.chunking_mgr` | Orchestrateur principal du chunking |
| `chunking.chunk_db` | Accès aux métadonnées SQLite |
| `asyncio` | Boucle d'événements pour opérations async |
| `threading` | Exécution non-bloquante dans la GUI |

#### Widgets

| Widget | Variable | Description |
|--------|----------|-------------|
| LabelFrame | - | Section "Actions" |
| Button | - | "📂 Chunker un fichier" |
| Button | - | "🌐 Distribuer" |
| Button | - | "📥 Récupérer du réseau" |
| Button | - | "🔄 Rafraîchir" |
| LabelFrame | - | Section "Serveur de chunks" |
| Label | `server_status_var` | État du serveur (🔴/🟢) |
| Entry | `server_port_var` | Port d'écoute (défaut: 6881) |
| Button | - | "▶ Démarrer" / "⏹ Arrêter" |
| LabelFrame | - | Section "Fichiers locaux chunkés" |
| Treeview | `files_tree` | Liste des fichiers (nom, chunks, date) |

#### Méthodes principales

| Méthode | Description |
|---------|-------------|
| `_chunk_file()` | Ouvre dialogue fichier et lance le chunking |
| `_distribute_file()` | Distribue le fichier sélectionné vers les pairs |
| `_fetch_file()` | Télécharge un fichier depuis le réseau P2P |
| `_refresh_local()` | Actualise la liste des fichiers chunkés |
| `_toggle_server()` | Démarre/arrête le serveur de chunks |
| `_delete_file()` | Supprime un fichier chunké localement |
| `_run_async(coro)` | Exécute une coroutine dans un thread séparé |

#### Intégration avec ChunkingManager

```python
# Dans gui.py, le ChunkingManager est initialisé au démarrage
self.chunking_mgr = ChunkingManager(peer_uuid=self._peer_uuid)

# P2PView reçoit la référence
p2p_view = P2PView(content_frame, chunking_mgr=self.chunking_mgr)
```

#### États du serveur

| État | Indicateur | Description |
|------|------------|-------------|
| Arrêté | 🔴 Serveur arrêté | Aucune écoute de connexions |
| En cours | 🟢 Serveur actif | Accepte les requêtes de chunks |

---

## 🔄 Flux de données principaux

### 1. Connexion au tracker

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  GUI Header  │───►│  connection  │───►│   Tracker    │
│   (inputs)   │    │   .announce()│◄───│   (externe)  │
└──────────────┘    └──────────────┘    └──────────────┘
                           │
                           ▼
                    ┌──────────────┐
                    │  PeersView   │
                    │ .update_peers│
                    └──────────────┘
```

### 2. Chiffrement et stockage de fichiers

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ Fichier      │───►│  FilesView   │───►│  container   │
│ utilisateur  │    │ .upload_file │    │  (mémoire)   │
└──────────────┘    └──────────────┘    └──────────────┘
                                               │
                           ┌───────────────────┘
                           ▼
                    ┌──────────────┐    ┌──────────────┐
                    │  crypto.py   │───►│container.dat │
                    │ encrypt_file │    │  (chiffré)   │
                    └──────────────┘    └──────────────┘
```

### 3. Dérivation et validation de clé

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Passphrase  │───►│ keystore.py  │───►│   key.json   │
│ (utilisateur)│    │ PBKDF2+verify│    │ (rétention)  │
└──────────────┘    └──────────────┘    └──────────────┘
                           │
                           ▼
                    ┌──────────────────────────────────┐
                    │ encryption_settings = {          │
                    │   'algorithm': 'AES-256',        │
                    │   'key': '64_chars_hex_key...'   │
                    │ }                                │
                    └──────────────────────────────────┘
```

### 4. Chunking et distribution P2P (NOUVEAU)

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Fichier     │───►│  P2PView     │───►│ChunkingMgr   │
│  source      │    │ _chunk_file()│    │ chunk_file() │
└──────────────┘    └──────────────┘    └──────────────┘
                                               │
                    ┌──────────────────────────┘
                    ▼
             ┌─────────────┐    ┌─────────────┐
             │ ReedSolomon │    │ ChunkStore  │
             │  encode()   │───►│  save_chunk │
             └─────────────┘    └──────┬──────┘
                                       │
                                       ▼
                               ┌─────────────┐
                               │  ~/.decen.  │
                               │  /chunks/   │
                               └─────────────┘
```

### 5. Récupération depuis le réseau P2P

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  P2PView     │───►│ ChunkingMgr  │───►│  PeerRPC     │
│ _fetch_file()│    │ fetch_file() │    │  (clients)   │
└──────────────┘    └──────────────┘    └──────────────┘
                           │                   │
                           │                   ▼
                           │            ┌──────────────┐
                           │            │  Pairs P2P   │
                           │            │  (réseau)    │
                           │            └──────────────┘
                           ▼
                    ┌──────────────┐
                    │ ReedSolomon  │
                    │  decode()    │
                    └──────────────┘
                           │
                           ▼
                    ┌──────────────┐
                    │  Fichier     │
                    │ reconstitué  │
                    └──────────────┘
```

### 6. Auto-sync du container.dat (NOUVEAU)

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  FilesView   │───►│save_container│───►│_trigger_auto_│
│  (action)    │    │     ()       │    │   chunk()    │
└──────────────┘    └──────────────┘    └──────────────┘
                                               │
                                               ▼
                    ┌──────────────────────────────────┐
                    │        Container.dat modifié     │
                    │                                  │
                    │  1. Hash calculé                 │
                    │  2. Ancien chunking supprimé     │
                    │  3. Nouveau chunking créé        │
                    │  4. Distribution aux pairs       │
                    └──────────────────────────────────┘
```

### 7. Restauration automatique du container.dat (NOUVEAU)

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Démarrage   │───►│ _check_and_  │───►│ container.dat│
│  GUI         │    │ restore_     │    │  existe ?    │
└──────────────┘    │ container()  │    └──────────────┘
                    └──────────────┘           │
                                        ┌──────┴──────┐
                                        │             │
                                       OUI           NON
                                        │             │
                                        ▼             ▼
                                    [Rien]    ┌──────────────┐
                                              │ Chunks en    │
                                              │ base ?       │
                                              └──────────────┘
                                                    │
                                              ┌─────┴─────┐
                                              │           │
                                             NON         OUI
                                              │           │
                                              ▼           ▼
                                          [Rien]  ┌──────────────┐
                                                  │reconstruct_  │
                                                  │   file()     │
                                                  └──────────────┘
                                                        │
                                                        ▼
                                                  ┌──────────────┐
                                                  │container.dat │
                                                  │  restauré    │
                                                  └──────────────┘
```

---

## 📂 Fichiers de données

### Emplacement par défaut

Les fichiers de données sont stockés dans un sous-dossier `data/` situé **à côté de l'exécutable** (ou du script `main.py` en mode développement).

Cela permet d'avoir **plusieurs instances indépendantes** du client sur le même ordinateur, chacune avec sa propre configuration et son propre conteneur.

| Mode | Chemin |
|------|--------|
| Script | `<dossier_du_script>/data/` |
| Exécutable (PyInstaller) | `<dossier_de_l_executable>/data/` |

### Fichiers créés

| Fichier | Description |
|---------|-------------|
| `data/key.json` | Fichier de rétention (paramètres KDF + vérification) |
| `data/storage/container.dat` | Conteneur chiffré contenant les fichiers |
| `data/chunks/` | Répertoire des chunks P2P |
| `data/chunk_metadata.db` | Base de données SQLite des métadonnées de chunking |

---

## 🔧 Guide d'extension

### Ajouter une nouvelle vue

1. **Créer le fichier** dans `views/nouvelle_view.py`:
```python
import tkinter as tk
from tkinter import ttk

class NouvelleView(ttk.Frame):
    def __init__(self, parent, app_gui, **kwargs):
        super().__init__(parent, **kwargs)
        self.app_gui = app_gui
        # Construire les widgets...
```

2. **Importer et instancier** dans `gui.py`:
```python
from views.nouvelle_view import NouvelleView

# Dans __init__ de DecentralisGUI:
self.frames['nouvelle'] = NouvelleView(container, self)
self.frames['nouvelle'].grid(row=0, column=0, sticky='nsew')
```

3. **Ajouter au menu**:
```python
view_menu.add_command(label="Ma Vue", command=lambda: self.show_view('nouvelle'))
```

### Ajouter un nouvel algorithme de chiffrement

1. **Modifier `crypto.py`**: Ajouter les cas dans `encrypt_file()` et `decrypt_file()`

2. **Modifier `encryption_view.py`**: Ajouter l'option dans le Combobox

### Intégrer la logique réseau P2P

1. **Étendre `connection/connection.py`**:
   - Ajouter méthodes `send_file(peer, data)`, `receive_file()`
   - Implémenter le protocole d'échange entre peers

2. **Modifier `files_view.py`**:
   - Remplacer/compléter les opérations locales par des appels réseau
   - Ajouter la réplication vers les peers

---

## 📦 Module Chunking P2P (chunking/)

Le module `chunking/` implémente un système complet de fragmentation de fichiers avec codes de correction d'erreurs Reed-Solomon et Local Reconstruction Codes (LRC) pour le stockage distribué P2P.

### Architecture en couches

```
┌─────────────────────────────────────────────────────────────┐
│  Couche Orchestration (chunking_mgr.py, replication_mgr.py) │
│    - Coordination des opérations de haut niveau             │
│    - Gestion du cycle de vie des fichiers (30 jours)        │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────┴─────────────────────────────┐
│          Couche Encodage (reed_solomon.py)                │
│    - Encodage Reed-Solomon (K=6 data, M=4 parité)         │
│    - Local Reconstruction Codes (LRC)                     │
└───────────────────────────────────────────────────────────┘
                              │
┌──────────────────┬──────────┴───────────┬─────────────────┐
│ Couche Stockage  │                      │ Couche Réseau   │
│ (chunk_store.py) │   (chunk_db.py)      │ (peer_rpc.py,   │
│ Stockage disque  │   Métadonnées SQL    │  chunk_net.py)  │
└──────────────────┴──────────────────────┴─────────────────┘
```

### Configuration (config.py)

| Paramètre | Valeur défaut | Description |
|-----------|---------------|-------------|
| `REED_SOLOMON.K` | 6 | Chunks de données originaux |
| `REED_SOLOMON.M` | 4 | Chunks de parité |
| `DEFAULT_CHUNK_SIZE_MB` | 10 | Taille par défaut d'un chunk |
| `RETENTION.DAYS` | 30 | Durée de rétention |
| `LRC.LOCAL_GROUP_SIZE` | 2 | Taille des groupes LRC |
| `MIN_RELIABILITY_SCORE` | 0.5 | Score minimum pour sélection peer |

Variables d'environnement configurables:
- `DECENTRALIS_RS_K`, `DECENTRALIS_RS_M` - Paramètres Reed-Solomon
- `DECENTRALIS_CHUNK_SIZE_MB` - Taille des chunks
- `DECENTRALIS_RETENTION_DAYS` - Durée de rétention

### Modèles de données (models.py)

| Classe | Description |
|--------|-------------|
| `ChunkMetadata` | Métadonnées complètes d'un fichier chunké |
| `StoredChunk` | Chunk stocké localement sur le disque |
| `ChunkAssignment` | Attribution d'un chunk à un peer |
| `ReplicationTask` | Tâche de relocalisation d'un chunk |
| `PeerInfo` | Informations sur un peer du réseau |
| `LocalGroup` | Groupe local pour LRC |

### Reed-Solomon + LRC (reed_solomon.py)

**Classe**: `ReedSolomonEncoder`

L'encodeur implémente:
- **Reed-Solomon Erasure Coding**: Permet de reconstruire les données avec n'importe quels K chunks sur N (K+M)
- **LRC (Local Reconstruction Codes)**: Groupes locaux permettant une récupération rapide sans accéder à tous les chunks

```python
# Exemple d'utilisation
from chunking import ReedSolomonEncoder

encoder = ReedSolomonEncoder(k=6, m=4)
data_chunks, parity_chunks = encoder.encode_data(file_data)

# Reconstruction avec chunks manquants
available_chunks = {0: chunk0, 2: chunk2, 4: chunk4, 6: parity0, 7: parity1, 8: parity2}
recovered_data = encoder.decode_data(available_chunks, original_size)
```

| Méthode | Description |
|---------|-------------|
| `encode_data(data)` | Encode en K chunks data + M chunks parité |
| `decode_data(chunks, size)` | Reconstruit depuis >= K chunks |
| `create_local_groups(k, group_size)` | Crée les groupes LRC |
| `encode_local_recovery_symbols(chunks, groups)` | Génère symboles LRC |

### Stockage local (chunk_store.py)

**Classe**: `ChunkStore`

Structure du répertoire:
```
~/.decentralis/chunks/
├── {owner_uuid}/
│   ├── {file_uuid}/
│   │   ├── metadata.json
│   │   ├── 0.chunk
│   │   ├── 1.chunk
│   │   └── ...
│   └── {file_uuid2}/
└── {owner_uuid2}/
```

| Méthode | Description |
|---------|-------------|
| `store_chunk(owner, file, idx, data)` | Stocke un chunk sur disque |
| `get_chunk(owner, file, idx)` | Récupère un chunk |
| `store_metadata(owner, file, metadata)` | Stocke les métadonnées JSON |
| `validate_chunk(owner, file, idx, expected_hash)` | Valide l'intégrité |
| `delete_file_chunks(owner, file)` | Supprime tous les chunks d'un fichier |

### Base de données (chunk_db.py)

**Classe**: `ChunkDatabase`

Tables SQLite:
- `file_metadata` - Métadonnées des fichiers chunkés
- `chunks` - Chunks stockés localement
- `chunk_locations` - Index de réplication (où sont les chunks)
- `replication_history` - Historique des relocalisations
- `peers` - Informations sur les peers
- `chunk_assignments` - Assignations chunk → peer

| Méthode | Description |
|---------|-------------|
| `add_file_metadata(metadata)` | Ajoute les métadonnées d'un fichier |
| `get_file_metadata(file_uuid)` | Récupère les métadonnées |
| `get_file_metadata_by_name(filename, owner)` | **Récupère métadonnées par nom** (NOUVEAU) |
| `add_chunk(chunk)` | Ajoute un chunk stocké |
| `get_chunks_by_file(file_uuid)` | Liste les chunks d'un fichier |
| `get_locations_by_peer(peer_uuid)` | Chunks stockés par un peer |
| `get_all_file_metadata()` | **Liste tous les fichiers chunkés** (NOUVEAU) |
| `get_local_stats()` | **Statistiques locales** (NOUVEAU) |
| `cleanup_expired_files()` | Supprime les fichiers expirés |

### Gestionnaire principal (chunking_mgr.py)

**Classe**: `ChunkingManager`

Point d'entrée principal pour toutes les opérations de chunking.

```python
import asyncio
from chunking import ChunkingManager

async def main():
    mgr = ChunkingManager("my-peer-uuid", "/path/to/storage", "/path/to/db.sqlite")
    
    # Chunker un fichier
    file_uuid = await mgr.chunk_file("/path/to/container.dat", "owner-uuid")
    
    # Distribuer aux peers
    result = await mgr.distribute_chunks(file_uuid, "owner-uuid")
    
    # Reconstruire un fichier
    await mgr.reconstruct_file(file_uuid, "owner-uuid", "/path/to/output.dat")
    
    await mgr.shutdown()

asyncio.run(main())
```

| Méthode | Description |
|---------|-------------|
| `chunk_file(path, owner)` | Découpe un fichier en chunks RS+LRC |
| `distribute_chunks(file_uuid, owner)` | Distribue vers les peers |
| `reconstruct_file(file_uuid, owner, output)` | Reconstruit depuis les chunks |
| `get_file_status(file_uuid)` | État d'un fichier (chunks disponibles) |
| `start_background_tasks()` | Lance les tâches de maintenance |
| `shutdown()` | Arrêt propre |

### Réplication (replication_mgr.py)

**Classe**: `ReplicationManager`

Gère la relocalisation des chunks quand un peer se déconnecte.

| Méthode | Description |
|---------|-------------|
| `on_peer_disconnected(peer_uuid)` | Gère la déconnexion d'un peer |
| `process_pending_relocations()` | Traite les relocalisations en attente |
| `select_replacement_peer(chunk)` | Sélectionne un peer de remplacement |
| `cleanup_expired_chunks()` | Nettoie les chunks expirés |

### Communication P2P (peer_rpc.py, chunk_net.py)

**Client RPC** (`PeerRPC`): Communication sortante vers les autres peers.
**Serveur TCP** (`ChunkNetworkServer`): Écoute les requêtes entrantes.

Protocole JSON-RPC 2.0 sur TCP avec préfixe de longueur.

Méthodes RPC disponibles:
- `ping` - Vérification de connexion
- `store_chunk` - Stockage d'un chunk
- `get_chunk` - Récupération d'un chunk
- `delete_chunk` - Suppression d'un chunk
- `get_chunk_info` - Informations sur un chunk
- `list_chunks` - Liste des chunks d'un fichier
- `announce_file` - Annonce d'un nouveau fichier
- `search_file` - Recherche d'un fichier

### Exceptions (exceptions.py)

Hiérarchie d'exceptions spécifiques:

```
ChunkingException (base)
├── ChunkEncodingError      # Erreur d'encodage RS
├── ChunkDecodingError      # Erreur de décodage
├── InsufficientChunksError # Pas assez de chunks pour reconstruction
├── ChunkNotFoundError      # Chunk introuvable
├── ChunkValidationError    # Hash invalide
├── ChunkStorageError       # Erreur de stockage disque
├── ChunkDatabaseError      # Erreur SQL
├── FileMetadataNotFoundError # Métadonnées introuvables
├── PeerCommunicationError  # Erreur réseau P2P
├── ReplicationError        # Erreur de relocalisation
├── ConfigurationError      # Configuration invalide
└── SignatureValidationError # Signature invalide
```

### Flux de chunking complet

```
1. chunk_file(path, owner)
   ├── Lecture du fichier
   ├── Calcul du hash SHA-256
   ├── Encodage Reed-Solomon → K data + M parity chunks
   ├── Création groupes LRC → symboles de récupération locaux
   ├── Stockage local (chunk_store)
   └── Enregistrement métadonnées (chunk_db)

2. distribute_chunks(file_uuid, owner)
   ├── Récupération liste des peers (via tracker)
   ├── Sélection des peers fiables (score >= 0.5)
   ├── Assignation round-robin des chunks
   ├── Envoi via RPC (peer_rpc)
   └── Enregistrement des localisations (chunk_db)

3. reconstruct_file(file_uuid, owner, output)
   ├── Récupération métadonnées
   ├── Collecte des chunks (locaux + distants)
   ├── Décodage Reed-Solomon/LRC
   ├── Vérification hash
   └── Écriture du fichier reconstitué

4. on_peer_disconnected(peer_uuid)
   ├── Identification des chunks affectés
   ├── Création tâches de relocalisation
   ├── Sélection nouveaux peers
   ├── Récupération depuis peers qui ont encore les chunks
   └── Mise à jour des localisations
```

---

## ⚠️ Points d'attention pour les développeurs

### Sécurité
- La clé dérivée est **conservée en mémoire** pendant la session
- Le fichier `key.json` ne contient **jamais** la passphrase
- Les fichiers sont toujours stockés **chiffrés** dans `container.dat`

### Threading
- La connexion tracker utilise un **thread daemon** pour le keepalive
- Les appels réseau sont effectués dans des threads pour ne pas bloquer l'UI
- Utiliser `root.after()` pour les mises à jour UI depuis un thread

### Conventions
- Chemins virtuels dans le conteneur: toujours avec `/` (pas `\`)
- Clés de chiffrement: format hexadécimal (64 caractères pour 32 bytes)
- Encodage des fichiers dans le conteneur: Base64

### Chunking P2P
- Le module `chunking/` utilise **asyncio** pour les opérations réseau
- Les chunks sont stockés avec hash SHA-256 pour validation d'intégrité
- Reed-Solomon permet de perdre jusqu'à **M chunks** et toujours reconstruire
- LRC ajoute une récupération locale rapide sans accéder à tous les chunks
- Toutes les opérations réseau ont un timeout configurable (défaut: 30s)
- Les peers sont sélectionnés par score de fiabilité (0.0 à 1.0)

### Limitations actuelles
- Pas de persistance de la passphrase entre sessions (intentionnel)
- Un seul fichier conteneur par installation

---

## 🚀 Évolutions prévues

- [x] ~~Système de chunking avec Reed-Solomon~~ ✅ Implémenté
- [x] ~~Codes de correction LRC~~ ✅ Implémenté
- [x] ~~Base de données des métadonnées~~ ✅ Implémenté
- [x] ~~Protocole RPC P2P~~ ✅ Implémenté
- [x] ~~Intégration chunking dans GUI~~ ✅ Implémenté (P2PView)
- [x] ~~Auto-chunking du container.dat~~ ✅ Implémenté
- [x] ~~Auto-sync vers les pairs~~ ✅ Implémenté
- [x] ~~Restauration automatique du container.dat~~ ✅ Implémenté
- [ ] Réplication automatique lors de déconnexion peer
- [ ] Interface améliorée (icônes, drag & drop, barre de progression)
- [ ] Stockage sécurisé de la clé via keyring système
- [ ] Support de multiples conteneurs/profils
- [ ] Historique des transferts
- [ ] Chiffrement des chunks avant distribution (hybride avec clés peer)

---

*Document généré pour le projet Decentralis Client - Dernière mise à jour: Janvier 2026*
