.PHONY: assets check build screens capture
assets:
	python3 tools/generate_assets.py
	python3 tools/generate_audio.py
check:
	./test.sh
build:
	./build.sh
screens:
	python3 tools/render_screens.py
capture:
	python3 tools/qemu_capture.py
