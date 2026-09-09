# Cartridge Store publishing

`Spiriti! Napoli '97` is prepared for the PRG32 Cartridge Store on the `development-c6` ABI. The release contains portable packages for physical ESP32-C6 and the ESP32-C3 QEMU runtime, embedded Store metadata, a 256x256 icon, a 320x200 gameplay screenshot, a colophon and a real 30-second audiovisual QEMU preview.

## Release artifacts

- `dist/store/spiriti-napoli97-esp32c6.prg32`
- `dist/store/spiriti-napoli97-qemu.prg32`
- `dist/spiriti-napoli97-1.2.3-store.zip`
- `icon.png`
- `screenshot.png`
- `preview.mp4`
- `metadata.json`, `manifest.json`, and `colophon.json`

The MP4 is repository/catalog media and is intentionally excluded from the Store ZIP so the two-architecture bundle stays below 128 KiB.

## Build and validate

```sh
source /path/to/esp-idf/export.sh
export PRG32_REPO=/path/to/PRG32
./test.sh
./build.sh
python3 -m prg32 store inspect-metadata dist/store/spiriti-napoli97-esp32c6.prg32
python3 -m prg32 store inspect-metadata dist/store/spiriti-napoli97-qemu.prg32
```

Before submission, inspect the ZIP contents and confirm the release version matches in the manifest, metadata and colophon. Physical ESP32-C6 testing remains required for final hardware sign-off.

## Submit

Use the configured Store endpoint and credentials from the PRG32 environment:

```sh
cd "$PRG32_REPO"
python3 -m prg32 store publish-bundle /path/to/spiriti-napoli97/dist/spiriti-napoli97-1.2.3-store.zip
```

Submission may enter the Store review queue. Do not claim official Ghostbusters affiliation; the embedded colophon and metadata contain the required tribute and rights notice.
