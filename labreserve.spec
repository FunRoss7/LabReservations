Name:           labreserve
Version:        0.1.0
Release:        1%{?dist}
Summary:        Lab machine reservation tool via Ansible

License:        MIT
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  python3-devel
BuildRequires:  python3-setuptools

Requires:       python3 >= 3.6.8
Requires:       python3-click >= 7.0
Requires:       python3-PyYAML >= 5.1
Requires:       ansible >= 2.16.3
Requires:       cronie

%description
labreserve manages time-limited reservations of shared lab machines.
It uses Ansible to rotate the shared account password on the target
machine, updates the login banner, and schedules automatic reversion
via a cron.d entry on the jump box.

%prep
%autosetup

%build
%py3_build

%install
%py3_install

# Install playbooks to /usr/share/labreserve/playbooks
install -d %{buildroot}/usr/share/labreserve
cp -r playbooks %{buildroot}/usr/share/labreserve/

# Install example inventory
install -d %{buildroot}/usr/share/labreserve/examples
install -m 0644 inventory/hosts.yml.example %{buildroot}/usr/share/labreserve/examples/

# Runtime config directory (empty; populated by labreserve init)
install -d %{buildroot}/etc/labreserve

%files
%license LICENSE
%{python3_sitelib}/labreserve/
%{python3_sitelib}/labreserve-*.egg-info/
%{_bindir}/labreserve
/usr/share/labreserve/playbooks/
/usr/share/labreserve/examples/
%dir /etc/labreserve

%post
echo "Run 'labreserve init' as root to configure the vault and add machines."

%changelog
* Wed Apr 02 2026 Ross Carlson <ross@example.com> - 0.1.0-1
- Initial package
