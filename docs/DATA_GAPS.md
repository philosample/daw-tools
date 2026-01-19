# Data Gaps and Opportunities

## Ableton Live Sets
- Deep parsing of ALS/ALSX:
  - Track hierarchy, clip metadata, devices, and routing (baseline now captured).
  - Warp markers, automation, and device parameters.
  - Plugin preset names and per-device settings.

## Samples and Audio
- Audio analysis:
  - duration, sample rate, RMS, peak, LUFS.
  - key/BPM detection.
  - waveform fingerprints for duplicate detection.

## Plugins
- Detect AU/VST/VST3 metadata:
  - vendor, version, component IDs.
  - scan plugin folders from preferences.

## Usage Signals
- Last opened time per ALS or project.
- Frequency of device usage across projects.
- References from templates or default sets.

## Preferences
- Decode binary fields to structured values.
- Extract user library root, packs, and custom locations.
