# Development progress

## Phase 1 — research and foundation

- Located `/home/edwin/coding` and created this independent repository.
- Researched upstream source, activity, authentication transition and licenses;
  selected Python/GTK4/Libadwaita, FFmpeg, Mutagen and audible 0.13.1.
- Native application shell launched under Xvfb with GTK 4.22 and Libadwaita 1.9.
- Foundation tests: **6 passed**, including actual native window creation,
  preferences persistence, dependency checks and no-clobber transactions.
- Host is headless Ubuntu, not the requested CachyOS desktop. Native runtime
  packages were extracted into ignored `.deps/`; no system packages installed.

## Work underway

Local media engine and metadata modules are being implemented. Audible live
authentication requires the account owner's browser and remains unverified.
