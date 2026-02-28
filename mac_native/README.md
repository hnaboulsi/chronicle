# Life Manager Native macOS Scaffold

This directory contains the native macOS app scaffold for the hidden helper rollout:

- `LifeManager`: the visible SwiftUI settings app
- `LifeManagerAgent`: the hidden login helper
- `Shared`: code compiled into both targets

The project is generated from `project.yml` using XcodeGen.

Requirements:

1. Full Xcode installed
2. `xcode-select` pointed at `/Applications/Xcode.app/Contents/Developer`
3. Accept the Xcode license and finish first-launch setup:

```bash
sudo xcodebuild -license accept
sudo xcodebuild -runFirstLaunch
```

4. Run:

```bash
cd mac_native
xcodegen generate
open LifeManager.xcodeproj
```

Notes:

- The helper is scaffolded as a background-only app target.
- Embedding the helper under `Contents/Library/LoginItems` should be finalized in Xcode once full Xcode is installed.
- The native sources typecheck with the macOS SDK, but `xcodebuild` will fail until the Xcode license is accepted on the machine.
- The repo's existing Python client remains available during the migration period.
