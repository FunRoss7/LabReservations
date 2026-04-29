#!/bin/bash
# labreserve integration test suite
# Exercises reserve, status, conflict detection, release, and cancel script.
#
# Usage:
#   make test-el8                   (EL8 — preferred, ensures RPM is current)
#   make test-el9                   (EL9)
#   make test                       (both)
#
# Or directly, supplying the EL version and RPM filename:
#   EL_VERSION=8 RPM_FILE=labreserve-0.1.0-1.el8.noarch.rpm bash test/run_tests.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

EL_VERSION="${EL_VERSION:-9}"
RPM_FILE="${RPM_FILE:-labreserve-0.1.0-1.el9.noarch.rpm}"

# Each EL version gets its own compose project so containers do not collide
# when el8 and el9 tests run back-to-back (or in parallel).
PROJECT="labreserve-el${EL_VERSION}"
COMPOSE="docker compose -f $SCRIPT_DIR/docker-compose.yml -p $PROJECT"

SSH_DIR="$SCRIPT_DIR/ssh"
INITIAL_PASSWORD="LabDefault123!"
RESERVATION_PASSWORD="TestReservation123!"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RESET='\033[0m'
PASS=0; FAIL=0

section() { echo -e "\n${YELLOW}[EL${EL_VERSION}] ==> $1${RESET}"; }
pass()    { echo -e "  ${GREEN}PASS${RESET}  $1"; PASS=$((PASS+1)); }
fail()    { echo -e "  ${RED}FAIL${RESET}  $1"; FAIL=$((FAIL+1)); }

# Run a command on the jumpbox service (-T disables TTY so stdin pipes work)
jexec() { $COMPOSE exec -T jumpbox bash -c "$1"; }

# Run a command on a target service: texec lab01 "command"
texec() { $COMPOSE exec -T "$1" bash -c "$2"; }

cleanup() {
    section "Cleanup"
    $COMPOSE down -v 2>/dev/null || true
}
trap cleanup EXIT

# ── Pre-flight ────────────────────────────────────────────────────────────────
section "Pre-flight checks"
[[ -f "$SCRIPT_DIR/$RPM_FILE" ]] \
    || { echo "RPM not found: $SCRIPT_DIR/$RPM_FILE"; \
         echo "Run 'make rpm-el${EL_VERSION}' first."; exit 1; }
command -v docker > /dev/null \
    || { echo "docker not found"; exit 1; }
echo "  EL version : ${EL_VERSION}"
echo "  RPM        : $RPM_FILE"
echo "  Project    : $PROJECT"

# ── SSH key pair ──────────────────────────────────────────────────────────────
section "SSH key pair"
mkdir -p "$SSH_DIR"
chmod 700 "$SSH_DIR"
if [[ ! -f "$SSH_DIR/id_ed25519" ]]; then
    ssh-keygen -t ed25519 -f "$SSH_DIR/id_ed25519" -N "" -q
    echo "  Generated new key pair"
else
    echo "  Reusing existing key pair"
fi
chmod 600 "$SSH_DIR/id_ed25519"
PUBKEY="$(cat "$SSH_DIR/id_ed25519.pub")"

# ── Build + start containers ──────────────────────────────────────────────────
section "Starting containers (rockylinux:${EL_VERSION})"
ROCKY_VERSION="$EL_VERSION" RPM_FILE="$RPM_FILE" $COMPOSE up --build -d

for host in lab01 lab02; do
    echo -n "  Waiting for $host sshd"
    for _ in $(seq 1 30); do
        $COMPOSE exec -T "$host" bash -c \
            "ss -tlnp | grep -q ':22'" 2>/dev/null && break
        echo -n "."
        sleep 1
    done
    echo " ready"
done

# ── Distribute SSH public key to targets ──────────────────────────────────────
section "Authorizing SSH key on targets"
for host in lab01 lab02; do
    $COMPOSE exec -T "$host" bash -c "
        printf '%s\n' '$PUBKEY' > /home/labuser/.ssh/authorized_keys
        chmod 600 /home/labuser/.ssh/authorized_keys
        chown labuser:labuser /home/labuser/.ssh/authorized_keys
    "
    echo "  $host: OK"
done

# ── Jump box setup ────────────────────────────────────────────────────────────
section "Jump box setup"

# Write test inventory (piped heredoc into compose exec)
cat << 'EOF' | $COMPOSE exec -T jumpbox bash -c "cat > /etc/labreserve/hosts.yml"
all:
  hosts:
    lab01:
      ansible_host: lab01
      ansible_user: labuser
      ansible_ssh_private_key_file: /root/.ssh/id_ed25519
      ansible_ssh_extra_args: '-o StrictHostKeyChecking=no'
    lab02:
      ansible_host: lab02
      ansible_user: labuser
      ansible_ssh_private_key_file: /root/.ssh/id_ed25519
      ansible_ssh_extra_args: '-o StrictHostKeyChecking=no'
EOF
echo "  Inventory written"

jexec "touch /etc/labreserve/reservations.db && chmod 664 /etc/labreserve/reservations.db"
echo "  Database initialised"

# Bootstrap reservation profile directly (bypasses the interactive passwd prompt)
jexec "
    mkdir -p /root/.labreserve && chmod 700 /root/.labreserve
    openssl rand -base64 32 > /root/.labreserve/profile.key
    chmod 600 /root/.labreserve/profile.key
    printf '%s' '$RESERVATION_PASSWORD' \
        | openssl enc -aes-256-cbc -pbkdf2 \
              -pass file:/root/.labreserve/profile.key \
              -out /root/.labreserve/profile.enc
    chmod 600 /root/.labreserve/profile.enc
"
echo "  Reservation profile created (password: $RESERVATION_PASSWORD)"

# ── Test: reserve lab01 ───────────────────────────────────────────────────────
section "Reserve lab01 --duration 2h"
HASH_BEFORE=$(texec lab01 "getent shadow labuser | cut -d: -f2")

printf 'y\n' | $COMPOSE exec -T jumpbox \
    labreserve reserve lab01 --duration 2h

HASH_AFTER=$(texec lab01 "getent shadow labuser | cut -d: -f2")

[[ "$HASH_BEFORE" != "$HASH_AFTER" ]] \
    && pass "Password hash changed on lab01" \
    || fail "Password hash unchanged on lab01"

texec lab01 "grep -q 'MACHINE RESERVED' /etc/motd" \
    && pass "Reservation MOTD set" \
    || fail "Reservation MOTD not set"

texec lab01 "grep -q 'MACHINE RESERVED' /etc/issue.net" \
    && pass "Reservation issue.net set" \
    || fail "Reservation issue.net not set"

texec lab01 "test -f /usr/local/lib/labreserve/revert.sh" \
    && pass "Revert script deployed" \
    || fail "Revert script missing"

texec lab01 "test -f /usr/local/lib/labreserve/original_motd" \
    && pass "Original MOTD stored for revert" \
    || fail "Original MOTD not stored"

texec lab01 "test -f /usr/local/lib/labreserve/original_issue.net" \
    && pass "Original issue.net stored for revert" \
    || fail "Original issue.net not stored"

texec lab01 "test -f /etc/cron.d/labreserve-timed" \
    && pass "Timed cron entry deployed" \
    || fail "Timed cron entry missing"

texec lab01 "test -f /etc/cron.d/labreserve-reboot" \
    && pass "Reboot cron entry deployed" \
    || fail "Reboot cron entry missing"

texec lab01 "test -f /root/cancel_reservation" \
    && pass "Cancel script deployed in /root/" \
    || fail "Cancel script missing from /root/"

# Verify reservation password grants SSH access
$COMPOSE exec -T jumpbox \
    sshpass -p "$RESERVATION_PASSWORD" \
        ssh -o StrictHostKeyChecking=no -o PreferredAuthentications=password \
        labuser@lab01 'echo ok' > /dev/null 2>&1 \
    && pass "Reservation password grants SSH access" \
    || fail "Reservation password does not grant SSH access"

# Verify original password is now rejected
$COMPOSE exec -T jumpbox \
    sshpass -p "$INITIAL_PASSWORD" \
        ssh -o StrictHostKeyChecking=no -o PreferredAuthentications=password \
        labuser@lab01 'echo ok' > /dev/null 2>&1 \
    && fail "Original password still works after reservation (should be rejected)" \
    || pass "Original password correctly rejected after reservation"

# ── Test: status ──────────────────────────────────────────────────────────────
section "Status"
STATUS=$(jexec "labreserve status")
printf '%s\n' "$STATUS"
echo "$STATUS" | grep -q "lab01" \
    && pass "lab01 appears in status" \
    || fail "lab01 missing from status"
echo "$STATUS" | grep -q "ACTIVE" \
    && pass "Status shows ACTIVE" \
    || fail "Status does not show ACTIVE"

# ── Test: conflict detection ──────────────────────────────────────────────────
section "Conflict detection"
CONFLICT=$(printf 'n\n' | $COMPOSE exec -T jumpbox \
    labreserve reserve lab01 --duration 1h 2>&1 || true)
echo "$CONFLICT" | grep -qi "already reserved" \
    && pass "Conflict detected for reserved machine" \
    || fail "Conflict not detected"

# ── Test: reserve second machine ──────────────────────────────────────────────
section "Reserve lab02 (second machine)"
printf 'y\n' | $COMPOSE exec -T jumpbox \
    labreserve reserve lab02 --duration 1h

STATUS2=$(jexec "labreserve status")
echo "$STATUS2" | grep -q "lab02" \
    && pass "lab02 appears in status after reservation" \
    || fail "lab02 missing from status"

# ── Test: cancel script (local revert) ───────────────────────────────────────
section "Cancel script on lab02"
# Rewind the expiry to the past so the guard check passes
texec lab02 "sed -i 's/^EXPIRY=.*/EXPIRY=\"2000-01-01T00:00\"/' \
    /usr/local/lib/labreserve/revert.sh"
texec lab02 "bash /root/cancel_reservation"

texec lab02 "test ! -f /usr/local/lib/labreserve/revert.sh" \
    && pass "Revert script removed after cancel" \
    || fail "Revert script still present after cancel"

texec lab02 "test ! -f /root/cancel_reservation" \
    && pass "Cancel script self-removed after running" \
    || fail "Cancel script still present"

texec lab02 "test ! -f /etc/cron.d/labreserve-timed" \
    && pass "Cron entries removed after cancel" \
    || fail "Cron entries still present after cancel"

texec lab02 "! grep -q 'MACHINE RESERVED' /etc/motd 2>/dev/null" \
    && pass "MOTD restored after cancel" \
    || fail "MOTD still shows reservation banner after cancel"

# ── Test: release lab01 ───────────────────────────────────────────────────────
section "Release lab01"
printf 'y\n' | $COMPOSE exec -T jumpbox labreserve release lab01

HASH_RELEASED=$(texec lab01 "getent shadow labuser | cut -d: -f2")
[[ "$HASH_BEFORE" == "$HASH_RELEASED" ]] \
    && pass "Password hash restored to original" \
    || fail "Password hash not restored (got: ${HASH_RELEASED:0:20}...)"

texec lab01 "! grep -q 'MACHINE RESERVED' /etc/motd 2>/dev/null" \
    && pass "MOTD restored" \
    || fail "MOTD still shows reservation banner"

texec lab01 "test ! -f /usr/local/lib/labreserve/revert.sh" \
    && pass "Revert script removed" \
    || fail "Revert script still present"

texec lab01 "test ! -f /etc/cron.d/labreserve-timed" \
    && pass "Timed cron entry removed" \
    || fail "Timed cron entry still present"

texec lab01 "test ! -f /root/cancel_reservation" \
    && pass "Cancel script removed on release" \
    || fail "Cancel script still present after release"

# Verify original password grants SSH access again
$COMPOSE exec -T jumpbox \
    sshpass -p "$INITIAL_PASSWORD" \
        ssh -o StrictHostKeyChecking=no -o PreferredAuthentications=password \
        labuser@lab01 'echo ok' > /dev/null 2>&1 \
    && pass "Original password grants SSH access after release" \
    || fail "Original password does not work after release"

# Verify reservation password is now rejected
$COMPOSE exec -T jumpbox \
    sshpass -p "$RESERVATION_PASSWORD" \
        ssh -o StrictHostKeyChecking=no -o PreferredAuthentications=password \
        labuser@lab01 'echo ok' > /dev/null 2>&1 \
    && fail "Reservation password still works after release (should be rejected)" \
    || pass "Reservation password correctly rejected after release"

# ── Summary ───────────────────────────────────────────────────────────────────
section "Results"
TOTAL=$((PASS + FAIL))
echo "  Passed: $PASS / $TOTAL"
if [[ $FAIL -gt 0 ]]; then
    echo -e "  ${RED}Failed: $FAIL / $TOTAL${RESET}"
    exit 1
else
    echo -e "  ${GREEN}All $TOTAL tests passed.${RESET}"
fi
