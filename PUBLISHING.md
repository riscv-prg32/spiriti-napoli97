# Cartridge Store publishing

The release bundle is checked in:

- `dist/spiriti-napoli97-2.0.0-store.zip` — manifest, icon, screenshot and both cartridges
- `dist/store/` — the same files, unpacked
- `dist/SHA256SUMS`

The manifest (`tools/store_manifest.py`) is the Store's `prg32-metadata-1.0` form: the metadata fields, `architectures`, `assets.icon`, `assets.splash` and the colophon inline. The Store rebuilds each cartridge from it. `preview.mp4` is repository media and is not part of the bundle.

## Rebuild and check

```sh
export PRG32_REPO=/path/to/PRG32
export CARTRIDGE_STORE_ROOT=/path/to/CartridgeStore   # optional: runs the Store's intake code
./build.sh
```

## Submit

With the Store endpoint and a developer token configured in the PRG32 environment:

```sh
cd "$PRG32_REPO"
python3 -m prg32 store publish-bundle /path/to/spiriti-napoli97/dist/spiriti-napoli97-2.0.0-store.zip
```

The submission enters the Store's review queue. The physical ESP32-C6 run in [STORE_CHECKLIST.md](STORE_CHECKLIST.md) is still open. Do not claim Ghostbusters affiliation; the colophon and metadata carry the tribute notice.
