"""
Per-user vault stored at ~/.labreserve/vault.yml.

Each user who makes reservations gets their own vault, protected by their
own vault password.  The only thing stored here is the random password
for each machine they currently have reserved — enough to recover it if
they forget what was shown at reservation time.

Vault structure (plaintext before encryption):
  reservations:
    machine-hostname:
      password: <random string>
      expires_at: "2026-04-02T18:00"
"""
import os
import subprocess
import tempfile

import yaml

# Filenames within the user's ~/.labreserve/ directory
_VAULT_FILE = 'vault.yml'
_VAULT_PASS_FILE = '.vault_pass'


def _vault_path(user_dir):
    return os.path.join(user_dir, _VAULT_FILE)


def _vault_pass_path(user_dir):
    return os.path.join(user_dir, _VAULT_PASS_FILE)


def _ensure_dir(user_dir, username=None):
    """Create ~/.labreserve with correct ownership if it doesn't exist."""
    os.makedirs(user_dir, mode=0o700, exist_ok=True)
    # If we're running as root (e.g. via sudo), fix ownership so the actual
    # user owns their own config directory.
    if os.geteuid() == 0 and username:
        import pwd
        pw = pwd.getpwnam(username)
        os.chown(user_dir, pw.pw_uid, pw.pw_gid)


def is_initialized(user_dir):
    return os.path.exists(_vault_pass_path(user_dir))


def init_user_vault(user_dir, username=None):
    """Prompt the user to set a personal vault password and create the vault."""
    import click
    _ensure_dir(user_dir, username)
    vault_pass = click.prompt(
        'Set a personal vault password to protect your reservation credentials',
        hide_input=True,
        confirmation_prompt=True,
    )
    pass_file = _vault_pass_path(user_dir)
    with open(pass_file, 'w') as f:
        f.write(vault_pass + '\n')
    os.chmod(pass_file, 0o600)
    if os.geteuid() == 0 and username:
        import pwd
        pw = pwd.getpwnam(username)
        os.chown(pass_file, pw.pw_uid, pw.pw_gid)
    # Write and encrypt an empty vault to establish the file.
    _save_vault(user_dir, {})


def _load_vault(user_dir):
    vault_file = _vault_path(user_dir)
    if not os.path.exists(vault_file):
        return {}
    result = subprocess.run(
        ['ansible-vault', 'decrypt',
         '--vault-password-file', _vault_pass_path(user_dir),
         '--output', '-',
         vault_file],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError('Failed to decrypt personal vault: {}'.format(result.stderr.strip()))
    return yaml.safe_load(result.stdout) or {}


def _save_vault(user_dir, data):
    vault_file = _vault_path(user_dir)
    plaintext = yaml.dump(data, default_flow_style=False)
    fd, tmpfile = tempfile.mkstemp(suffix='.yml')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(plaintext)
        subprocess.run(
            ['ansible-vault', 'encrypt',
             '--vault-password-file', _vault_pass_path(user_dir),
             '--output', vault_file,
             tmpfile],
            check=True,
            capture_output=True,
        )
    finally:
        if os.path.exists(tmpfile):
            os.unlink(tmpfile)
    os.chmod(vault_file, 0o600)
    # Fix ownership if running as root
    if os.geteuid() == 0:
        pass_stat = os.stat(_vault_pass_path(user_dir))
        os.chown(vault_file, pass_stat.st_uid, pass_stat.st_gid)


def store_reservation_password(user_dir, machine, password, expires_at):
    """Save the random password for a reservation into the user's vault."""
    data = _load_vault(user_dir)
    data.setdefault('reservations', {})[machine] = {
        'password': password,
        'expires_at': expires_at.isoformat(timespec='seconds'),
    }
    _save_vault(user_dir, data)


def get_reservation_password(user_dir, machine):
    """Return the stored password for a machine, or None if not found."""
    data = _load_vault(user_dir)
    entry = data.get('reservations', {}).get(machine)
    return entry  # dict with 'password' and 'expires_at', or None


def remove_reservation_password(user_dir, machine):
    """Remove the stored password for a machine after it is released."""
    data = _load_vault(user_dir)
    reservations = data.get('reservations', {})
    if machine in reservations:
        del reservations[machine]
        data['reservations'] = reservations
        _save_vault(user_dir, data)
