VERSION := 0.1.0
RELEASE := 1

RPM_EL8 := test/labreserve-$(VERSION)-$(RELEASE).el8.noarch.rpm
RPM_EL9 := test/labreserve-$(VERSION)-$(RELEASE).el9.noarch.rpm

.PHONY: all rpm rpm-el8 rpm-el9 test test-el8 test-el9 clean

all: rpm test

rpm: rpm-el8 rpm-el9

test: test-el8 test-el9

# ── RPM builds ────────────────────────────────────────────────────────────────
# RPM targets are phony so they always clean and rebuild — no stale packages.
# Each build runs inside a throwaway container matching the target EL version
# so the host needs no rpm-build toolchain.

define build_rpm
	@echo "==> Building EL$(1) RPM in rockylinux:$(1) container"
	@mkdir -p test
	@rm -f test/labreserve-$(VERSION)-$(RELEASE).el$(1).noarch.rpm
	docker run --rm \
		-v "$(CURDIR):/src:ro" \
		-v "$(CURDIR)/test:/out" \
		rockylinux:$(1) bash -c '\
		    set -euo pipefail && \
		    dnf install -y rpm-build > /dev/null && \
		    mkdir -p ~/rpmbuild/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS} && \
		    mkdir -p /tmp/labreserve-$(VERSION) && \
		    cp -r /src/bin /src/playbooks /src/inventory /src/LICENSE \
		          /tmp/labreserve-$(VERSION)/ && \
		    tar -czf ~/rpmbuild/SOURCES/labreserve-$(VERSION).tar.gz \
		        -C /tmp labreserve-$(VERSION) && \
		    cp /src/labreserve.spec ~/rpmbuild/SPECS/ && \
		    rpmbuild -bb ~/rpmbuild/SPECS/labreserve.spec 2>&1 && \
		    cp ~/rpmbuild/RPMS/noarch/labreserve-$(VERSION)-$(RELEASE).el$(1).noarch.rpm /out/'
	@echo "==> RPM written to test/labreserve-$(VERSION)-$(RELEASE).el$(1).noarch.rpm"
endef

rpm-el8:
	$(call build_rpm,8)

rpm-el9:
	$(call build_rpm,9)

# ── Tests ─────────────────────────────────────────────────────────────────────
# Each test target rebuilds its RPM first so the installed package is always
# current.

test-el8: rpm-el8
	@echo "==> Running EL8 container tests"
	EL_VERSION=8 RPM_FILE=labreserve-$(VERSION)-$(RELEASE).el8.noarch.rpm \
	    bash test/run_tests.sh

test-el9: rpm-el9
	@echo "==> Running EL9 container tests"
	EL_VERSION=9 RPM_FILE=labreserve-$(VERSION)-$(RELEASE).el9.noarch.rpm \
	    bash test/run_tests.sh

# ── Cleanup ───────────────────────────────────────────────────────────────────

clean:
	rm -f test/labreserve-*.rpm
	rm -rf test/ssh
