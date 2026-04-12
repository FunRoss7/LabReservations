# labreserve

A jump-box tool for time-limited reservations of shared lab machines. When a
machine is reserved, the shared account password is changed to one the reserver
chooses, the login banner is updated to show who has it and until when, and a
self-contained revert mechanism is installed on the target machine to restore
everything automatically when the reservation expires — even if the machine was
down at expiry time.

---

## How it works

```
jump box                              target machine
─────────────────────────────────     ────────────────────────────────────────
labreserve reserve lab01 -d 2h
  │
  ├─ reads ~/.labreserve/profile.enc  (reservation password)
  ├─ ansible-playbook reserve.yml ──► reads /etc/shadow hash (pre-change)
  │                                  sets password → reservation password
  │                                  writes /etc/motd  (reserved by / until)
  │                                  writes /etc/issue.net
  │                                  drops /usr/local/lib/labreserve/revert.sh
  │                                  drops /etc/cron.d/labreserve-timed
  │                                  drops /etc/cron.d/labreserve-reboot
  └─ records reservation in shared SQLite DB

At expiry (or on next boot if machine was down):
  cron ──────────────────────────────► revert.sh runs:
                                         restores original /etc/shadow hash
                                         clears /etc/motd and /etc/issue.net
                                         removes cron entries and itself
```

### Expiry and the reboot guard

Two cron entries are installed on the target machine at reservation time:

- **`labreserve-timed`** — fires at the exact expiry timestamp.
- **`labreserve-reboot`** — fires on every boot. The revert script checks
  whether the expiry has passed before doing anything; if the machine boots
  before expiry this entry is a no-op. If the machine was **down** at expiry
  time, this entry ensures the revert runs as soon as it comes back up.

Both entries and the revert script remove themselves when the revert runs.

### Credential storage

Each user has a profile at `~/.labreserve/` containing:

| File | Contents |
|------|----------|
| `profile.key` | Random AES-256 key (chmod 600) |
| `profile.enc` | Reservation password encrypted with that key (chmod 600) |

The key and encrypted file are adjacent, which satisfies org policies requiring
credentials not to be stored in plaintext while keeping the tool simple.
Encryption uses `openssl enc -aes-256-cbc -pbkdf2`.

### Shared state

The reservation database lives at `/etc/labreserve/reservations.db` (SQLite).
All users on the jump box read and write the same file, so `labreserve status`
always shows the full picture. The DB is the authoritative record of *who*
reserved *what* and *until when*; the actual enforcement of the reservation
happens on the target machine itself.

When a reservation expires via the target's cron job, the DB is not notified.
The next time any `labreserve` command runs it will automatically mark
past-expiry active entries as `expired` so the DB stays consistent.

---

## Requirements

### Jump box

| Dependency | Notes |
|------------|-------|
| `bash` | Any version shipped with RHEL 8 |
| `openssl` | For profile encryption |
| `sqlite3` | For the shared reservation DB |
| `ansible-core` | For running playbooks against target machines (available in Rocky/RHEL 9 AppStream; use EPEL on RHEL 8) |

### Target machines

- A shared account (e.g. `labuser`) accessible via SSH from the jump box.
- `sudo` / root access for the ansible connection user (to modify `/etc/shadow`,
  `/etc/motd`, and `/etc/cron.d/`).
- `usermod`, `cron` — standard on any RHEL 8 system.

---

## Installation

### From RPM (recommended)

```bash
sudo dnf install labreserve-0.1.0-1.el8.noarch.rpm
```

### From source

```bash
git clone <repo>
cd labreserve
sudo install -Dm 0755 bin/labreserve /usr/bin/labreserve
sudo cp -r playbooks /usr/share/labreserve/playbooks
sudo mkdir -p /etc/labreserve
```

### Admin setup (once per jump box)

1. **Create the inventory** at `/etc/labreserve/hosts.yml`.
   An example is at `/usr/share/labreserve/examples/hosts.yml.example`.

   ```yaml
   all:
     hosts:
       lab-machine-01:
         ansible_host: 192.168.1.10
         ansible_user: labuser
       lab-machine-02:
         ansible_host: 192.168.1.11
         ansible_user: labuser
   ```

   `ansible_user` must be the shared account on each target machine.
   Passwords are **not** stored here.

2. **Set permissions** so all authorized jump-box users can write to the DB:

   ```bash
   sudo touch /etc/labreserve/reservations.db
   sudo chown root:labteam /etc/labreserve/reservations.db
   sudo chmod 664 /etc/labreserve/reservations.db
   sudo chmod g+s /etc/labreserve
   ```

   Replace `labteam` with the appropriate group for your org.

That is all the admin setup required. Users manage their own credentials.

---

## User guide

### First use — set your reservation password

Your reservation password is the password that will be set on the shared
account of any machine you reserve. You only set it once (and can change it
later with `labreserve passwd`).

```
$ labreserve passwd
No reservation password found — let's set one up first.
New reservation password: ········
Confirm: ········
Reservation password saved to /home/alice/.labreserve
```

This is called automatically on your first `reserve` if you skip it.

### Reserving a machine

```bash
# Reserve for a duration
labreserve reserve lab-machine-01 --duration 2h
labreserve reserve lab-machine-01 --duration 1h30m

# Reserve until a specific time
labreserve reserve lab-machine-01 --until 2026-04-02T18:00

# Reserve multiple machines at once
labreserve reserve lab-machine-01 lab-machine-02 --duration 4h
```

You will be shown a summary and asked to confirm before anything runs.

The first time you run this against a machine, ansible needs SSH access using
the machine's **current** (default) password. Pass `--ask-pass` if your
inventory does not already have SSH keys configured:

```bash
labreserve reserve lab-machine-01 --duration 2h --ask-pass
```

If your environment uses an ansible vault to manage SSH credentials, pass it
with `--vault-file`:

```bash
labreserve reserve lab-machine-01 --duration 2h --vault-file ~/my-vault.yml
```

After a successful reservation, SSH into the machine with the reservation
password you set via `labreserve passwd`. If you forget it:

```bash
labreserve passwd   # shows current password before prompting to change
```

### Checking reservations

```bash
# Active reservations only (default)
labreserve status

# Full history including released and expired
labreserve status --all
```

Example output:

```
Machine                Reserved By      Status     Reserved At          Expires At
------------------------------------------------------------------------------------------
lab-machine-01         alice            ACTIVE     2026-04-02 10:00     2026-04-02 12:00
lab-machine-02         bob              ACTIVE     2026-04-02 09:30     2026-04-02 11:30
```

### Releasing a machine early

```bash
labreserve release lab-machine-01
labreserve release lab-machine-01 lab-machine-02
```

This immediately restores the default password and clears the login banner.
The cron entries on the target machine are also removed so the revert does
not fire again at the originally scheduled time.

### Changing your reservation password

```bash
labreserve passwd
```

This is blocked if you have active reservations — your reserved machines
currently have your existing password set, so changing it would lock you out.
Release all active reservations first, then run `passwd`.

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LABRESERVE_HOME` | `/etc/labreserve` | Override system config directory |
| `LABRESERVE_INVENTORY` | `$LABRESERVE_HOME/hosts.yml` | Override ansible inventory path |
| `LABRESERVE_JUMP_BOX` | _(unset)_ | Hostname or IP of this jump box. When set, the cancel script dropped on target machines will SSH back here to update the reservation database immediately on cancellation. Requires a `labreserve-agent` user on the jump box with a forced-command authorized key (see below). |

---

## Dual-boot machines

`labreserve` automatically handles machines with multiple bootable OS
installations (e.g. two leap-frogging software stacks on the same hardware).

At reservation time, the playbook inspects the running system's mount table and
identifies alternate OS roots — top-level mount points (e.g. `/mnt/op2`) that
contain their own `/etc/shadow` on a separate physical partition.  For each
discovered root it:

- applies the reservation password hash directly to that root's `/etc/shadow`
- writes the reservation banner to that root's `/etc/motd` and `/etc/issue.net`
  (skipped if the file lives on a partition already handled by another root —
  this covers diamond-mounted shared partitions such as a common `/opt`)
- stores the original motd/issue.net content and installs a self-contained
  revert script + cron entries inside that root's own filesystem

When the machine boots into an alternate OS, that OS's cron-on-boot entry fires
the revert script, which restores the original password hash and banners for
that OS.  No cross-OS coordination is required.

No inventory changes are needed.  The playbooks discover alternate roots
dynamically and apply the same process generically to however many are present.

### Cancel script and remote DB update (optional)

A `cancel_reservation` script is placed in `/root/` on every OS root.  Anyone
with root access to the physical machine can run it to immediately release the
reservation without waiting for expiry.

The cancel script will attempt to SSH back to the jump box to update the
reservation database if `LABRESERVE_JUMP_BOX` is set.  To enable this, create
a dedicated user on the jump box and restrict it to the single sqlite3 command:

```bash
# On the jump box — one-time admin setup
sudo useradd -r -s /usr/sbin/nologin labreserve-agent
sudo mkdir -p /home/labreserve-agent/.ssh
# Generate or supply a key pair; put the private key on target machines as
# /root/.ssh/labreserve_agent (chmod 600, owned by root).
# Add the public key with a forced command:
echo 'command="sqlite3 /etc/labreserve/reservations.db",no-pty,no-port-forwarding <pubkey>' \
    | sudo tee /home/labreserve-agent/.ssh/authorized_keys
sudo chmod 700 /home/labreserve-agent/.ssh
sudo chmod 600 /home/labreserve-agent/.ssh/authorized_keys
sudo chown -R labreserve-agent: /home/labreserve-agent/.ssh
```

If the SSH key is not present or the connection fails, the cancel script falls
back gracefully: it still completes the local revert and prints instructions for
running `labreserve release` on the jump box manually.

---

## File layout

```
/usr/bin/labreserve                       executable
/usr/share/labreserve/playbooks/          ansible playbooks and roles
/etc/labreserve/hosts.yml                 ansible inventory (admin-managed)
/etc/labreserve/reservations.db           shared SQLite reservation database

~/.labreserve/profile.key                 per-user AES key (chmod 600)
~/.labreserve/profile.enc                 per-user encrypted reservation password (chmod 600)

# Installed on each OS root of target machines during reservation (removed on release/expiry).
# On single-boot machines this is just /; on dual-boot machines these appear
# under each discovered alternate root (e.g. /mnt/op2/usr/local/lib/...) as well.
/usr/local/lib/labreserve/revert.sh       self-contained revert script
/usr/local/lib/labreserve/original_motd   original /etc/motd saved at reservation time
/usr/local/lib/labreserve/original_issue.net  original /etc/issue.net saved at reservation time
/etc/cron.d/labreserve-timed              fires at expiry time
/etc/cron.d/labreserve-reboot             fires on boot, no-ops until expiry
/root/cancel_reservation                  emergency cancel script (run as root on target)
```
