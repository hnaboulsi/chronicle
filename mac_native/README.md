# Chronicle Native macOS

This directory contains the native macOS app for Chronicle:

- `LifeManager`: the visible SwiftUI settings app (builds as **Chronicle.app**)
- `LifeManagerAgent`: the hidden login helper (background tracking agent)
- `Shared`: code compiled into both targets

The project is generated from `project.yml` using XcodeGen.

## Build & Install

```bash
cd mac_native
./install.sh
```

This runs XcodeGen, builds, copies to `/Applications/Chronicle.app`, and launches the app.

## Manual Xcode workflow

Requirements:
1. Full Xcode installed
2. `xcode-select` pointed at `/Applications/Xcode.app/Contents/Developer`

```bash
xcodegen generate
open LifeManager.xcodeproj
```
