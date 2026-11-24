UNIT_TESTS = test_omnibox test_store test_shield test_security test_theme test_vault

.PHONY: test test-unit run package install install-user uninstall-user lint clean

test:
	python3 -m unittest discover -s tests -v

test-unit:
	python3 -m unittest -v $(addprefix tests.,$(UNIT_TESTS))

run:
	python3 bin/cruxx-browser

package:
	cd packaging/arch && makepkg -f --cleanbuild

install:
	cd packaging/arch && makepkg -fsi

install-user:
	packaging/user/install.sh install

uninstall-user:
	packaging/user/install.sh uninstall

lint:
	find . -name '*.py' -not -path './.venv/*' -not -path './packaging/arch/pkg/*' -not -path './packaging/arch/src/*' -print0 | xargs -0 python3 -m py_compile
	@if python3 -c 'import pyflakes' 2>/dev/null; then \
		find . -name '*.py' -not -path './.venv/*' -not -path './packaging/arch/pkg/*' -not -path './packaging/arch/src/*' -print0 | xargs -0 python3 -m pyflakes; \
	else \
		echo "pyflakes not installed, skipped"; \
	fi

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf packaging/arch/pkg packaging/arch/src
	rm -f packaging/arch/*.pkg.tar.* packaging/arch/*.log
