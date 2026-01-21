# Déploiement Ansible sur Proxmox VMs

Ce dossier contient les playbooks Ansible pour déployer automatiquement le client Decentralis sur des VMs Proxmox (Windows et Linux).

## 📋 Prérequis

### Sur les VMs Windows
1. **WinRM activé** - Exécuter en tant qu'administrateur :
   ```powershell
   # Activer WinRM
   Enable-PSRemoting -Force
   
   # Configurer WinRM pour les connexions non-SSL (pour environnement interne)
   winrm quickconfig
   winrm set winrm/config/service '@{AllowUnencrypted="true"}'
   winrm set winrm/config/service/auth '@{Basic="true"}'
   
   # Ouvrir le pare-feu
   New-NetFirewallRule -Name "WinRM-HTTP" -DisplayName "WinRM HTTP" -Protocol TCP -LocalPort 5985 -Action Allow
   ```

### Sur les VMs Linux
1. **Python 3 installé**
2. **SSH activé**
3. **Clé SSH autorisée** pour l'utilisateur de déploiement

## 🔐 Configuration des Secrets GitHub

Ajoutez ces secrets dans votre repository GitHub (`Settings > Secrets and variables > Actions`) :

### Secrets Obligatoires

| Secret | Description | Exemple |
|--------|-------------|---------|
| `PROXMOX_SSH_PRIVATE_KEY` | Clé SSH privée pour accéder aux VMs Linux | Contenu du fichier `~/.ssh/id_rsa` |
| `LINUX_ANSIBLE_USER` | Utilisateur SSH sur les VMs Linux | `deploy` |
| `WINDOWS_ANSIBLE_USER` | Utilisateur Windows (admin) | `Administrator` |
| `WINDOWS_ANSIBLE_PASSWORD` | Mot de passe Windows | `VotreMotDePasse` |

### Configuration des Hosts (YAML)

#### `PROXMOX_WINDOWS_HOSTS_YAML`
```yaml
          win-vm-01:
            ansible_host: 192.168.1.100
          win-vm-02:
            ansible_host: 192.168.1.101
          win-vm-03:
            ansible_host: 192.168.1.102
```

#### `PROXMOX_LINUX_HOSTS_YAML`
```yaml
          linux-vm-01:
            ansible_host: 192.168.1.110
          linux-vm-02:
            ansible_host: 192.168.1.111
```

### Secrets Optionnels (VPN)

| Secret | Description |
|--------|-------------|
| `WIREGUARD_CONFIG` | Configuration WireGuard complète pour accéder au réseau Proxmox |
| `PROXMOX_KNOWN_HOSTS` | IP/hostnames des VMs pour ssh-keyscan (séparés par espaces) |

### Variables de Repository (optionnel)

| Variable | Description | Valeur |
|----------|-------------|--------|
| `AUTO_DEPLOY_PROXMOX` | Déployer automatiquement lors d'un tag | `true` ou `false` |

## 🌐 Configuration Réseau

### Option 1 : VMs accessibles publiquement
Si vos VMs ont des IPs publiques ou sont exposées via port forwarding, aucune configuration VPN n'est nécessaire.

### Option 2 : Utilisation de WireGuard VPN
Pour accéder à un réseau Proxmox privé depuis GitHub Actions :

1. Configurez un serveur WireGuard sur votre réseau
2. Créez un peer pour GitHub Actions
3. Ajoutez la configuration dans le secret `WIREGUARD_CONFIG` :

```ini
[Interface]
PrivateKey = <VOTRE_CLE_PRIVEE>
Address = 10.0.0.2/24

[Peer]
PublicKey = <CLE_PUBLIQUE_SERVEUR>
AllowedIPs = 192.168.1.0/24
Endpoint = votre-serveur.com:51820
PersistentKeepalive = 25
```

### Option 3 : Utilisation d'un Runner Self-Hosted
Pour un meilleur contrôle, installez un [GitHub Actions self-hosted runner](https://docs.github.com/en/actions/hosting-your-own-runners) directement dans votre réseau Proxmox.

## 🚀 Utilisation

### Déploiement Manuel
1. Allez dans l'onglet **Actions** de votre repository
2. Sélectionnez **Build Artifacts**
3. Cliquez sur **Run workflow**
4. Cochez **Deploy to Proxmox VMs after build**
5. Choisissez les plateformes à déployer

### Déploiement Automatique
Définissez la variable `AUTO_DEPLOY_PROXMOX=true` pour déployer automatiquement à chaque nouveau tag.

## 📁 Structure des Fichiers Déployés

### Windows
```
C:\Users\<user>\Desktop\
├── decentralis-client-v1.0.0-123.exe    # Exécutable daté
└── Decentralis Client.lnk               # Raccourci
```

### Linux
```
~/Desktop/
├── decentralis-client-v1.0.0-123.AppImage  # AppImage datée
└── decentralis-client.desktop              # Fichier .desktop
```

## 🧪 Test Local

Pour tester les playbooks localement :

```bash
cd ansible

# Installer les dépendances
pip install ansible pywinrm

# Installer les collections
ansible-galaxy collection install -r requirements.yml

# Tester la connectivité Windows
ansible windows_vms -i inventory/hosts.yml -m ansible.windows.win_ping

# Tester la connectivité Linux
ansible linux_vms -i inventory/hosts.yml -m ping

# Exécuter le déploiement Windows
ansible-playbook -i inventory/hosts.yml playbooks/deploy-windows.yml \
  -e "artifact_source=/path/to/decentralis-client.exe" \
  -e "version_date=2024-01-15"

# Exécuter le déploiement Linux
ansible-playbook -i inventory/hosts.yml playbooks/deploy-linux.yml \
  -e "artifact_source_appimage=/path/to/decentralis-client.AppImage" \
  -e "version_date=2024-01-15"
```

## 🔧 Dépannage

### Erreur WinRM "Connection refused"
- Vérifiez que WinRM est activé sur la VM Windows
- Vérifiez le pare-feu Windows (port 5985)
- Testez avec : `Test-WSMan -ComputerName <IP>`

### Erreur SSH "Permission denied"
- Vérifiez que la clé SSH est ajoutée au fichier `~/.ssh/authorized_keys` sur la VM
- Vérifiez les permissions : `chmod 600 ~/.ssh/authorized_keys`

### Erreur "No route to host"
- Vérifiez la configuration VPN/réseau
- Assurez-vous que GitHub Actions peut atteindre vos VMs
