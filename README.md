# Decentralis Client

## Présentation

Client-lourd est un client GUI pour un réseau pair-à-pair décentralisé. L'objectif principal est
de permettre :

- la connexion à un serveur d'annonce (tracker) pour découvrir des pairs ;
- l'envoi et la réception de fichiers via le réseau P2P (les fichiers doivent être stockés chiffrés
  par les pairs) ;
- la gestion locale d'un espace de stockage qui sert de cache / dépôt pour les fichiers du réseau.

Cette application fournit une interface graphique simple (Tkinter) avec plusieurs vues :

- `Pairs` : liste des pairs fournis par le tracker (actualisée régulièrement),
- `Gestionnaire de fichiers` : navigation, création de dossiers, upload (copie locale), téléchargement (export) et suppression,
- `Chiffrement` : génération / saisie de clé et choix d'algorithme (préparatoire au chiffrement des fichiers).

Note : la logique réseau (envoi chiffré vers les pairs et récupération depuis le réseau) est prévue
mais dans l'état actuel la vue fichiers effectue des opérations locales (copie/suppression).

## Architecture et fichiers importants

- `src/decentralis-client/main.py` : point d'entrée qui lance l'interface graphique.
- `src/decentralis-client/connection/connection.py` : logique de connexion au tracker (announce, get_peers, keepalive).
- `src/decentralis-client/gui.py` : structure principale de l'UI (menu, header, gestion des vues).
- `src/decentralis-client/views/` : vues détachées : `peers_view.py`, `files_view.py`, `encryption_view.py`.
- `build_windows.ps1`, `build_linux.sh` : scripts locaux pour construire l'exécutable.
- `.github/workflows/build-artifacts.yml` : workflow CI pour produire `.exe` et `AppImage` et publier les artefacts.
- `README_BUILD.md` : instructions de build détaillées.

## Exigences

- Python 3.8+ (3.11 recommandé).
- `tkinter` (package système - sous Debian/Ubuntu : `sudo apt install python3-tk`).
- Pour la génération d'exécutables : `pyinstaller` (le script de build installe automatiquement les dépendances dans un venv).

Le fichier `requirements.txt` contient les dépendances utilisées pour les builds.

## Lancer l'application (développement)

1. Ouvrir un terminal dans la racine du dépôt.
2. Lancer :

```powershell
python .\src\decentralis-client\main.py
```

L'interface s'ouvre. Dans l'en-tête, entrez l'IP et le port du tracker, renseignez votre IP/port de peer local, puis cliquez `Connexion`.

## Utilisation de l'interface

- Vue `Pairs` : affiche les pairs fournis par le tracker. La liste s'actualise automatiquement toutes les 2 secondes.
- Vue `Gestionnaire de fichiers` :

  - `Up` : remonter d'un dossier ; double‑clic sur un dossier pour y entrer.
  - `New Folder` : créer un nouveau dossier (boîte de dialogue).
  - `Upload` : copier un fichier de votre disque vers le stockage local de l'application.
  - `Download` : exporter un fichier sélectionné vers un dossier de votre choix.
  - `Delete` : supprimer le fichier ou dossier sélectionné (confirmation demandée).

  Par défaut, le stockage local est situé dans :

```
~/.decentralis/storage
```

    (sur Windows,`~` correspond au dossier utilisateur, p.ex. `C:\Users\VotreNom`).

- Vue `Chiffrement` : choisir l'algorithme (ex : `AES-256`) et générer une clé hex. Les paramètres sont conservés en mémoire
  dans l'instance de l'application (`DecentralisGUI.encryption_settings`) — ils ne sont pas encore persistés sur disque.

## Build et distribution

Voir `README_BUILD.md` pour les instructions détaillées. En synthèse :

- Windows : exécuter `build_windows.ps1` (crée un `.exe` via PyInstaller).
- Linux : exécuter `build_linux.sh` (crée un binaire puis un `AppImage`).
- CI : le workflow `.github/workflows/build-artifacts.yml` peut être déclenché manuellement depuis l'onglet Actions ou automatiquement par push de tag `v*`.

Les artefacts produits par le workflow sont téléversés et peuvent être téléchargés depuis l'interface GitHub Actions ; le workflow peut aussi attacher
les fichiers à une Release pour les tags poussés.

## Limites actuelles et prochaines étapes possibles

- Le gestionnaire de fichiers effectue actuellement des opérations locales (copie/suppression/export). Il faut intégrer la logique réseau pour :
  - chiffrer les fichiers avant envoi,
  - mettre en place le protocole d'échange avec les peers (envoi, réplication, récupération),
  - stocker localement les fichiers reçus de manière chiffrée et gérer l'espace disque.
- Améliorations UX : arbre de dossiers, drag & drop, icônes, barre d'état, historique des transferts.
- Sécurité : stockage sécurisé de la clé (keyring ou fichier chiffré), validation et rotation de clé.

## Dépannage rapide

- Si l'interface n'apparaît pas, vérifiez que `tkinter` est installé pour votre version Python.
- Si la construction AppImage échoue sur GitHub Actions, vérifiez les logs du job `build-linux` (problèmes fréquents : dépendances système, icônes manquantes ou FUSE). Le workflow contient des étapes pour contourner FUSE et copier une icône placeholder.

## Contribuer

Les contributions sont bienvenues — ouvre une issue ou une pull request. Pour les développements réseau, commencez par étendre `connection/connection.py` puis ajoutez les hooks dans `DecentralisGUI` pour exposer `upload/download` réseau.
