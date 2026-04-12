Name:           labreserve
Version:        0.1.0
Release:        1%{?dist}
Summary:        Lab machine reservation tool via Ansible

License:        MIT
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch

Requires:       bash
Requires:       openssl
Requires:       sqlite
Requires:       ansible-core
Requires:       cronie

%description
labreserve manages time-limited reservations of shared lab machines via a
jump box.  When a user reserves a machine, the shared account password is
changed to one they choose.  A self-contained revert script and two cron
entries (timed + @reboot) are dropped on the target machine — no jump-box
cron entries are needed.  If the machine is down at expiry, the revert runs
automatically on next boot.

Each user stores one reservation password in an openssl-encrypted profile
under ~/.labreserve/.  The only system-level setup required is an ansible
inventory at /etc/labreserve/hosts.yml.

%prep
%autosetup

%install
install -Dm 0755 bin/labreserve %{buildroot}%{_bindir}/labreserve

install -d %{buildroot}/usr/share/labreserve
cp -r playbooks %{buildroot}/usr/share/labreserve/

install -d %{buildroot}/usr/share/labreserve/examples
install -m 0644 inventory/hosts.yml.example \
    %{buildroot}/usr/share/labreserve/examples/

install -d %{buildroot}/etc/labreserve

%files
%license LICENSE
%{_bindir}/labreserve
/usr/share/labreserve/playbooks/
/usr/share/labreserve/examples/
%dir /etc/labreserve

%post
echo "Copy /usr/share/labreserve/examples/hosts.yml.example to /etc/labreserve/hosts.yml and populate it."
echo "Users run 'labreserve passwd' once to set up their reservation password."

%changelog
* Wed Apr 02 2026 Ross Carlson <ross@example.com> - 0.1.0-1
- Initial package
