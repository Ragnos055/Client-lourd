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
│       └── views/                   # Vues de l'interface
│           ├── __init__.py
│           ├── peers_view.py        # Vue liste des pairs
│           ├── files_view.py        # Vue gestionnaire de fichiers
│           └── encryption_view.py   # Vue paramètres de chiffrement
├── assets/                          # Ressources (icônes, images)
├── build_windows.ps1                # Script de build Windows
├── build_linux.sh                   # Script de build Linux
├── requirements.txt                 # Dépendances Python
├── README.md                        # Documentation utilisateur
├── README_BUILD.md                  # Instructions de build
└── ARCHITECTURE.md                  # Ce fichier
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
          ┌────────────────┼────────────────┐
          │                │                │
          ▼                ▼                ▼
   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
   │ peers_view  │  │ files_view  │  │encryption_  │
   │             │  │             │  │   view      │
   └─────────────┘  └──────┬──────┘  └──────┬──────┘
                           │                │
                           ▼                ▼
                    ┌─────────────┐  ┌─────────────┐
                    │  crypto.py  │  │ keystore.py │
                    └─────────────┘  └─────────────┘

   ┌───────────────────────────────────────────────┐
   │            connection/connection.py           │
   │         (Gestion tracker indépendante)        │
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
| `config_dir` | `str` | Dossier de configuration (`~/.decentralis`) |
| `storage_dir` | `str` | Dossier de stockage (`~/.decentralis/storage`) |
| `retention_path` | `str` | Chemin du fichier de rétention (`~/.decentralis/key.json`) |
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
| `show_view(name)` | Affiche une vue (`peers`, `files`, `encryption`) |
| `_on_connect_click()` | Connexion/Déconnexion du tracker |
| `_disconnect()` | Ferme la connexion proprement |
| `_update_peers()` | Mise à jour périodique des pairs (toutes les 2s) |
| `_ensure_retention_file()` | Vérifie/crée le fichier de rétention au démarrage |

#### Flux de démarrage

```
1. Création de la fenêtre et du header
2. Création du menu Vue
3. Création du conteneur principal
4. Initialisation des répertoires (~/.decentralis, ~/.decentralis/storage)
5. Création de PeersView et EncryptionView
6. _ensure_retention_file() :
   - Si key.json existe → demande passphrase (3 tentatives max)
   - Sinon → propose création ou import
7. Création de FilesView (nécessite encryption_settings)
8. Affichage de la vue files par défaut
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

#### Constantes

| Constante | Valeur | Description |
|-----------|--------|-------------|
| `CONTAINER_NAME` | `'container.dat'` | Nom du fichier conteneur chiffré |

#### Attributs

| Attribut | Type | Description |
|----------|------|-------------|
| `app_gui` | `DecentralisGUI` | Référence à l'application principale |
| `cwd` | `str` | Chemin virtuel actuel ('' = racine) |
| `container` | `dict` | Structure en mémoire du conteneur |

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
| `save_container()` | Chiffre et sauvegarde le conteneur |
| `refresh()` | Recharge et réaffiche le contenu du dossier actuel |
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

---

## 📂 Fichiers de données

### Emplacement par défaut

| OS | Chemin |
|----|--------|
| Windows | `C:\Users\<username>\.decentralis\` |
| Linux/Mac | `~/.decentralis/` |

### Fichiers créés

| Fichier | Description |
|---------|-------------|
| `key.json` | Fichier de rétention (paramètres KDF + vérification) |
| `storage/container.dat` | Conteneur chiffré contenant les fichiers |

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

### Limitations actuelles
- Le gestionnaire de fichiers est **local uniquement** (pas de transfert P2P)
- Pas de persistance de la passphrase entre sessions (intentionnel)
- Un seul fichier conteneur par installation

---

## 🚀 Évolutions prévues

- [ ] Intégration complète du protocole P2P pour envoi/réception de fichiers
- [ ] Réplication des fichiers vers plusieurs peers
- [ ] Interface améliorée (icônes, drag & drop, barre de progression)
- [ ] Stockage sécurisé de la clé via keyring système
- [ ] Support de multiples conteneurs/profils
- [ ] Historique des transferts

---

*Document généré pour le projet Decentralis Client - Dernière mise à jour: Janvier 2026*
