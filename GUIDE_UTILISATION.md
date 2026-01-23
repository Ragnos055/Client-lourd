# Guide d’utilisation — Decentralis Client


## Prérequis

- Python 3.8+ (3.11 recommandé)
- Tkinter installé (sur Linux : `sudo apt install python3-tk`)
- Dépendances Python via [requirements.txt](requirements.txt)

Optionnel : pour la génération d’exécutables, PyInstaller est utilisé par les scripts de build (voir plus bas).

---

## Installation (développement)

1. Créez et activez un environnement virtuel.
2. Installez les dépendances depuis [requirements.txt](requirements.txt).

---

## Lancer l’application

### Mode standard

- Lancez le point d’entrée : [src/decentralis-client/main.py](src/decentralis-client/main.py)

### Mode debug

- Ajoutez l’argument `--debug` (ou définissez `DECENTRALIS_DEBUG=1`).
- Sur Windows, vous pouvez utiliser [run_debug.bat](run_debug.bat).

---

## Connexion au tracker

1. Dans l’en‑tête de l’application, renseignez l’IP et le port du tracker.
2. Renseignez également votre IP/port local (utilisés pour la communication P2P).
3. Cliquez sur « Connexion ».

La liste des pairs se met à jour automatiquement dans la vue Pairs.

---

## Vues principales

### Vue Pairs

- Affiche les pairs connus (liste rafraîchie périodiquement).

### Vue Gestionnaire de fichiers

Fonctions principales :

- navigation dans l’arborescence locale ;
- création de dossiers ;
- upload (copie locale) ;
- download (export vers un dossier) ;
- suppression (avec confirmation).

### Vue P2P

Fonctions principales :

- **Chunker un fichier** : découpage + métadonnées locales.
- **Distribuer** : envoi des chunks vers les pairs (suppression locale après confirmation).
- **Récupérer** : reconstruction depuis les chunks du réseau.
- **Démarrer le serveur P2P** : indispensable pour recevoir des chunks.

Indicateurs réseau : nombre de peers, état serveur P2P, nombre de chunks stockés et chunks étrangers hébergés.

### Vue Chiffrement

- Choix d’algorithme (ex : AES‑256)
- Génération d’une clé hexadécimale

---

## Workflow P2P recommandé

1. **Connectez‑vous au tracker**.
2. **Uploader un fichier** dans la vue gestionnaire de fichier.
4. **Distribuer et chunker** le fichier est automatiquement découpé et distribuer vers les peers.
5. **Rebuild** Si vous souhaitez consulter un fichier qui a était mis dans le réseau, cliquer sur rebuild, laisser faire le logiciel, puis ouvrez votre ficheir avec ouvrir.

Notes utiles :
- La distribution supprime les chunks locaux après confirmation par les peers.
- La reconstruction nécessite au minimum le nombre de chunks de données requis par Reed‑Solomon.

---

## Builds et exécutable

- Windows : [build_windows.ps1](build_windows.ps1)
- Linux : [build_linux.sh](build_linux.sh)

Un exécutable Windows peut être lancé en mode debug via [run_exe_debug.bat](run_exe_debug.bat).

---
 Bonne utilisation !
