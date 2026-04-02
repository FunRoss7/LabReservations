import os
import pwd

# System-wide paths (root-owned, shared across all users)
BASE_DIR = os.environ.get('LABRESERVE_HOME', '/etc/labreserve')
DB_PATH = os.path.join(BASE_DIR, 'reservations.db')
VAULT_PATH = os.path.join(BASE_DIR, 'vault.yml')
VAULT_PASS_FILE = os.path.join(BASE_DIR, '.vault_pass')
INVENTORY_PATH = os.path.join(BASE_DIR, 'hosts.yml')
PLAYBOOK_DIR = '/usr/share/labreserve/playbooks'
CRON_D_DIR = '/etc/cron.d'
CRON_PREFIX = 'labreserve-'


def get_user_dir(username=None):
    """Return ~/.labreserve for the given user (or the actual invoking user).

    Handles the sudo case: if SUDO_USER is set and no explicit username is
    given, use the pre-sudo user's home directory so personal vault files
    land in the right place even when the command is run as root.
    """
    if username:
        home = pwd.getpwnam(username).pw_dir
    else:
        sudo_user = os.environ.get('SUDO_USER')
        if sudo_user:
            home = pwd.getpwnam(sudo_user).pw_dir
        else:
            home = os.path.expanduser('~')
    return os.path.join(home, '.labreserve')


def get_username():
    """Return the name of the actual invoking user (pre-sudo if applicable)."""
    return os.environ.get('SUDO_USER') or pwd.getpwuid(os.getuid()).pw_name
