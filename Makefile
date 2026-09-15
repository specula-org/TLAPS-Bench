CHECKER_SOURCES := \
	src/common/__init__.py \
	src/common/check_proof.py \
	src/common/cheating_detection.py \
	src/common/proof_from_scratch_grading.py \
	src/common/proof_from_scratch_module.py \
	src/common/proof_libraries.py \
	src/common/task_contract.py \
	src/common/tla_modules.py \
	$(shell find src/tlacheck src/tlacore -type f -name '*.py')

.PHONY: setup build clean FORCE

# Regenerated on every make; the mtime moves only when the version string
# actually changes, so an incremental build can never keep a stale stamp.
src/common/_build_version.py: FORCE
	@printf 'BUILD_VERSION = "%s"\n' "$$(git describe --always --dirty 2>/dev/null || echo unknown)" > $@.tmp
	@if cmp -s $@.tmp $@ 2>/dev/null; then rm -f $@.tmp; else mv $@.tmp $@; fi

FORCE:

check_proof_bin: src/common/_build_version.py $(CHECKER_SOURCES)
	uv run --locked pyinstaller --onefile --name check_proof_bin \
		--paths src/common --paths src \
		--collect-submodules tlacheck \
		--collect-submodules tlacore \
		src/common/check_proof.py
	mv dist/check_proof_bin ./check_proof_bin
	rm -rf dist/ build/ check_proof_bin.spec

build: check_proof_bin

setup:
	bash scripts/setup.sh

clean:
	rm -f check_proof_bin src/common/_build_version.py
	rm -rf dist/ build/ *.spec
