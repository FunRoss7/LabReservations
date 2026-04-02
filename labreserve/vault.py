"""
Thin wrapper around ansible-vault for managing the credentials file.

Vault structure (plaintext before encryption):
  machines:
    hostname-or-ip:
      ansible_user: shareduser
      default_password: theoriginalpassword
"""
import os
import subprocess
import tempfile

import yaml

from labreserve.config import VAULT_PATH, VAULT_PASS_FILE


def vault_exists():
    return os.path.exists(VAULT_PATH)


def load_vault():
    """Decrypt vault and return contents as a dict."""
    result = subprocess.run(
        ['ansible-vault', 'decrypt',
         '--vault-password-file', VAULT_PASS_FILE,
         '--output', '-',
         VAULT_PATH],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError('Failed to decrypt vault: {}'.format(result.stderr.strip()))
    return yaml.safe_load(result.stdout) or {}


def save_vault(data):
    """Encrypt data dict and write it to the vault file."""
    plaintext = yaml.dump(data, default_flow_style=False)
    fd, tmpfile = tempfile.mkstemp(suffix='.yml')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(plaintext)
        subprocess.run(
            ['ansible-vault', 'encrypt',
             '--vault-password-file', VAULT_PASS_FILE,
             '--output', VAULT_PATH,
             tmpfile],
            check=True,
            capture_output=True
        )
    finally:
        if os.path.exists(tmpfile):
            os.unlink(tmpfile)


def add_machine(hostname, ansible_user, default_password):
    data = load_vault() if vault_exists() else {}
    data.setdefault('machines', {})[hostname] = {
        'ansible_user': ansible_user,
        'default_password': default_password,
    }
    save_vault(data)


def get_machine(hostname):
    data = load_vault()
    machines = data.get('machines', {})
    if hostname not in machines:
        raise KeyError("Machine '{}' not found in vault. Run 'labreserve init' to add it.".format(hostname))
    return machines[hostname]
