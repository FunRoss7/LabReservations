VERSION := 0.1.0
RELEASE := 1
RPM_FILE := labreserve-$(VERSION)-$(RELEASE).el9.noarch.rpm
RPM      := test/$(RPM_FILE)

.PHONY: all rpm test clean

all: rpm test

# Build the RPM inside a throwaway Rocky Linux 9 container so the host
# needs no rpm-build toolchain.  Source files are mounted read-only; the
# finished RPM lands in test/ where Dockerfile.jumpbox can COPY it.
rpm: $(RPM)

$(RPM):
	@echo "==> Building RPM in Rocky Linux 9 container"
	@mkdir -p test
	docker run --rm \
		-v "$(CURDIR):/src:ro" \
		-v "$(CURDIR)/test:/out" \
		rockylinux:9 bash -c '\
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
		    cp ~/rpmbuild/RPMS/noarch/$(RPM_FILE) /out/'
	@echo "==> RPM written to $(RPM)"

# Run the container test suite.  Requires the RPM to have been built first.
test: $(RPM)
	@echo "==> Running container tests"
	bash test/run_tests.sh

clean:
	rm -f test/labreserve-*.rpm
	rm -rf test/ssh
