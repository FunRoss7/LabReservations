import getpass
import json
import os
import pwd
import re
import secrets
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta

import click
import yaml

from labreserve import config
from labreserve import user_vault as user_vaultlib
from labreserve import vault as vaultlib
from labreserve.db import (
    get_active_reservation,
    init_db,
    list_reservations,
    record_release,
    record_reservation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_duration(s):
    """'2h', '30m', '1h30m' -> timedelta.  Raises ValueError on bad input."""
    m = re.match(r'^(?:(\d+)h)?(?:(\d+)m)?$', s.strip())
    if not m or (not m.group(1) and not m.group(2)):
        raise ValueError("Invalid duration '{}'. Use formats like '2h', '30m', '1h30m'.".format(s))
    return timedelta(hours=int(m.group(1) or 0), minutes=int(m.group(2) or 0))


def _parse_expiry(duration_str, until_str):
    if duration_str and until_str:
        raise click.UsageError("Specify either --duration or --until, not both.")
    if until_str:
        for fmt in ('%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S'):
            try:
                return datetime.strptime(until_str, fmt)
            except ValueError:
                continue
        raise click.UsageError("Cannot parse --until '{}'. Use YYYY-MM-DDTHH:MM.".format(until_str))
    if duration_str:
        try:
            return datetime.now() + _parse_duration(duration_str)
        except ValueError as e:
            raise click.UsageError(str(e))
    raise click.UsageError("Provide --duration or --until.")


def _run_playbook(playbook, machines, extra_vars=None, vars_file=None):
    """Run ansible-playbook against the given machines.

    vars_file: path to a JSON/YAML file passed as -e @file.  Use this for
    sensitive values (passwords) to avoid exposing them in the process list.
    """
    limit = ','.join(machines)
    cmd = [
        'ansible-playbook',
        '-i', config.INVENTORY_PATH,
        '--vault-password-file', config.VAULT_PASS_FILE,
        '--limit', limit,
        os.path.join(config.PLAYBOOK_DIR, playbook),
    ]
    if vars_file:
        cmd += ['-e', '@{}'.format(vars_file)]
    if extra_vars:
        for k, v in extra_vars.items():
            cmd += ['-e', '{}={}'.format(k, v)]
    result = subprocess.run(cmd)
    return result.returncode == 0


def _write_cron_job(machine, expires_at):
    """Drop a cron.d file so the reservation auto-releases at expiry."""
    sanitized = re.sub(r'[^a-zA-Z0-9_-]', '-', machine)
    cron_file = os.path.join(config.CRON_D_DIR, '{}{}'.format(config.CRON_PREFIX, sanitized))
    line = '{min} {hour} {day} {month} * root labreserve release {machine} --non-interactive\n'.format(
        min=expires_at.minute,
        hour=expires_at.hour,
        day=expires_at.day,
        month=expires_at.month,
        machine=machine,
    )
    with open(cron_file, 'w') as f:
        f.write('# Auto-release labreserve reservation for {}\n'.format(machine))
        f.write(line)
    os.chmod(cron_file, 0o644)


def _remove_cron_job(machine):
    sanitized = re.sub(r'[^a-zA-Z0-9_-]', '-', machine)
    cron_file = os.path.join(config.CRON_D_DIR, '{}{}'.format(config.CRON_PREFIX, sanitized))
    if os.path.exists(cron_file):
        os.unlink(cron_file)


def _add_to_inventory(hostname, ansible_user):
    if os.path.exists(config.INVENTORY_PATH):
        with open(config.INVENTORY_PATH) as f:
            inv = yaml.safe_load(f) or {}
    else:
        inv = {}
    inv.setdefault('all', {}).setdefault('hosts', {})[hostname] = {
        'ansible_user': ansible_user
    }
    with open(config.INVENTORY_PATH, 'w') as f:
        yaml.dump(inv, f, default_flow_style=False)
    os.chmod(config.INVENTORY_PATH, 0o640)


def _ensure_user_vault(user_dir, username):
    """Initialize the personal vault if the user hasn't set one up yet."""
    if not user_vaultlib.is_initialized(user_dir):
        click.echo("\nYou don't have a personal vault yet. It will store your reservation passwords.")
        user_vaultlib.init_user_vault(user_dir, username)
        click.echo('Personal vault created at {}'.format(user_dir))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.group()
def cli():
    """Lab machine reservation tool."""
    pass


@cli.command()
def init():
    """Initialize the system vault and add machines (run as root)."""
    os.makedirs(config.BASE_DIR, mode=0o750, exist_ok=True)

    click.echo("Step 1/3  Set vault password (protects default credentials)")
    vault_pass = click.prompt('Vault password', hide_input=True, confirmation_prompt=True)
    with open(config.VAULT_PASS_FILE, 'w') as f:
        f.write(vault_pass + '\n')
    os.chmod(config.VAULT_PASS_FILE, 0o600)
    click.echo('Vault password saved to {}'.format(config.VAULT_PASS_FILE))

    click.echo('\nStep 2/3  Initialize reservation database')
    init_db()
    click.echo('Database ready at {}'.format(config.DB_PATH))

    click.echo('\nStep 3/3  Add machines (leave hostname blank when done)')
    while True:
        hostname = click.prompt('\nMachine hostname or IP', default='').strip()
        if not hostname:
            break
        ansible_user = click.prompt('Shared account username on {}'.format(hostname))
        default_password = click.prompt(
            'Default password for {}'.format(hostname), hide_input=True
        )

        click.echo('Validating SSH access to {}...'.format(hostname))
        test = subprocess.run(
            ['ansible', hostname,
             '-i', '{},'.format(hostname),
             '-m', 'ping',
             '-u', ansible_user,
             '-e', 'ansible_password={}'.format(default_password),
             '-e', 'ansible_ssh_common_args="-o StrictHostKeyChecking=no"'],
            capture_output=True
        )
        if test.returncode == 0:
            click.echo('  Connection OK.')
        else:
            click.echo('  Warning: could not connect. Saving credentials anyway.')

        vaultlib.add_machine(hostname, ansible_user, default_password)
        _add_to_inventory(hostname, ansible_user)
        click.echo('  Added {} to vault and inventory.'.format(hostname))

    click.echo('\nDone. Summary:')
    click.echo('  Vault:     {}'.format(config.VAULT_PATH))
    click.echo('  Inventory: {}'.format(config.INVENTORY_PATH))
    click.echo('  Database:  {}'.format(config.DB_PATH))
    click.echo('  Playbooks: {}'.format(config.PLAYBOOK_DIR))


@cli.command()
@click.argument('machines', nargs=-1, required=True)
@click.option('--duration', '-d', default=None,
              help="How long to reserve, e.g. '2h', '30m', '1h30m'")
@click.option('--until', '-u', default=None,
              help="Reserve until a specific time, e.g. '2026-04-02T18:00'")
@click.option('--non-interactive', is_flag=True, hidden=True)
def reserve(machines, duration, until, non_interactive):
    """Reserve one or more lab machines."""
    expires_at = _parse_expiry(duration, until)
    username = config.get_username()
    user_dir = config.get_user_dir()

    # Check for conflicts
    conflicts = []
    for machine in machines:
        existing = get_active_reservation(machine)
        if existing:
            conflicts.append((machine, existing))

    if conflicts:
        click.echo('The following machines are already reserved:')
        for machine, res in conflicts:
            click.echo('  {}: held by {} until {}'.format(
                machine, res['reserved_by'], res['expires_at']
            ))
        if not non_interactive:
            click.confirm('Override existing reservations?', abort=True)

    click.echo('\nReservation summary:')
    click.echo('  Machines:    {}'.format(', '.join(machines)))
    click.echo('  Reserved by: {}'.format(username))
    click.echo('  Expires at:  {}'.format(expires_at.strftime('%Y-%m-%d %H:%M')))
    if not non_interactive:
        click.confirm('\nProceed?', abort=True)

    # Ensure the user has a personal vault to store their passwords in.
    if not non_interactive:
        _ensure_user_vault(user_dir, username)

    failed = []
    for machine in machines:
        # Generate a unique random password per machine here in Python so we
        # can (a) store it in the user's vault and (b) display it — without
        # ever letting it appear in a process listing.
        random_password = secrets.token_urlsafe(24)

        # Write to a temp file and pass as -e @file rather than -e key=value
        fd, vars_file = tempfile.mkstemp(suffix='.json')
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump({'random_password': random_password}, f)
            os.chmod(vars_file, 0o600)

            click.echo('\n[{}] Running reservation playbook...'.format(machine))
            success = _run_playbook(
                'reserve.yml', [machine],
                extra_vars={
                    'reserved_by': username,
                    'expires_at': expires_at.strftime('%Y-%m-%dT%H:%M'),
                },
                vars_file=vars_file,
            )
        finally:
            if os.path.exists(vars_file):
                os.unlink(vars_file)

        if success:
            record_reservation(machine, username, expires_at)
            _write_cron_job(machine, expires_at)
            if not non_interactive:
                user_vaultlib.store_reservation_password(user_dir, machine, random_password, expires_at)
            click.echo('[{}] Reserved until {}.'.format(machine, expires_at.strftime('%Y-%m-%d %H:%M')))
            click.echo('[{}] Password: {}'.format(machine, random_password))
            if not non_interactive:
                click.echo('[{}] Password also saved to your personal vault. Retrieve with: labreserve credentials {}'.format(machine, machine))
        else:
            click.echo('[{}] Playbook failed — reservation NOT recorded.'.format(machine), err=True)
            failed.append(machine)

    if failed:
        sys.exit(1)


@cli.command()
@click.argument('machines', nargs=-1, required=True)
@click.option('--non-interactive', is_flag=True, hidden=True)
def release(machines, non_interactive):
    """Release one or more machine reservations."""
    to_release = []
    for machine in machines:
        res = get_active_reservation(machine)
        if not res:
            click.echo('{}: no active reservation, skipping.'.format(machine))
        else:
            to_release.append((machine, res))

    if not to_release:
        return

    click.echo('Releasing:')
    for machine, res in to_release:
        click.echo('  {} (reserved by {}, expires {})'.format(
            machine, res['reserved_by'], res['expires_at']
        ))
    if not non_interactive:
        click.confirm('\nProceed?', abort=True)

    failed = []
    for machine, res in to_release:
        click.echo('\n[{}] Running release playbook...'.format(machine))
        success = _run_playbook('release.yml', [machine])
        if success:
            record_release(machine)
            _remove_cron_job(machine)
            # Clean the password out of the original reserver's personal vault.
            # This works whether the release was triggered manually or by cron.
            try:
                reserver_dir = config.get_user_dir(username=res['reserved_by'])
                if user_vaultlib.is_initialized(reserver_dir):
                    user_vaultlib.remove_reservation_password(reserver_dir, machine)
            except (KeyError, RuntimeError):
                pass  # If their vault is gone or unreadable, don't block release
            click.echo('[{}] Released.'.format(machine))
        else:
            click.echo('[{}] Playbook failed — reservation NOT cleared.'.format(machine), err=True)
            failed.append(machine)

    if failed:
        sys.exit(1)


@cli.command()
@click.argument('machine')
def credentials(machine):
    """Show the stored password for a machine you have reserved."""
    user_dir = config.get_user_dir()
    if not user_vaultlib.is_initialized(user_dir):
        click.echo('No personal vault found. Reserve a machine first.', err=True)
        sys.exit(1)

    entry = user_vaultlib.get_reservation_password(user_dir, machine)
    if not entry:
        click.echo("No stored credentials for '{}'. Either it was never reserved by you, "
                   "or it has already been released.".format(machine), err=True)
        sys.exit(1)

    click.echo('Machine:    {}'.format(machine))
    click.echo('Password:   {}'.format(entry['password']))
    click.echo('Expires at: {}'.format(entry['expires_at']))


@cli.command()
@click.option('--all', 'show_all', is_flag=True, help='Include past reservations')
def status(show_all):
    """Show reservation status."""
    reservations = list_reservations(active_only=not show_all)
    if not reservations:
        click.echo('No reservations found.')
        return

    now = datetime.now()
    col = '{:<22} {:<16} {:<10} {:<20} {:<20}'
    click.echo(col.format('Machine', 'Reserved By', 'Status', 'Reserved At', 'Expires At'))
    click.echo('-' * 90)
    for r in reservations:
        expires = datetime.fromisoformat(r['expires_at'])
        if r['status'] == 'active' and expires < now:
            label = 'EXPIRED'
        else:
            label = r['status'].upper()
        click.echo(col.format(
            r['machine'], r['reserved_by'], label,
            r['reserved_at'][:16], r['expires_at'][:16]
        ))


def main():
    cli()
