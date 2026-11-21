# Technical Architecture

## Recommended Stack

- UI: SwiftUI
- Local storage: SwiftData or Core Data
- Charts: Swift Charts
- Mapping/render: custom Canvas + Path rendering
- Media sync: AVFoundation
- Background import/parsing: Swift concurrency

## App Modules

### 1. App Shell

- navigation
- dependency setup
- theme/design tokens

### 2. Session Domain

- session metadata
- lap model
- sector model
- event model

### 3. Replay Engine

- playback clock
- telemetry interpolation
- track position rendering
- chart synchronization
- video synchronization

### 4. Analytics Engine

- sector scoring
- delta computation
- corner segmentation
- anomaly detection

### 5. Data Import

- local file import
- cloud import
- format adapters
- validation and normalization

## Suggested Data Model

### Session

- id
- trackId
- driverId
- vehicleId
- date
- weather
- laps[]
- events[]

### Lap

- lapNumber
- lapTimeMs
- sectorTimes[]
- samples[]
- validity

### Telemetry Sample

- timestampMs
- latitude
- longitude
- speedKph
- throttlePct
- brakePct
- steeringDeg
- gear
- rpm
- lateralG
- longitudinalG

## Replay Flow

1. Load session
2. Normalize samples to a shared timeline
3. Interpolate position and telemetry between samples
4. Update track marker, charts, and event labels from a single playback clock
5. If video exists, keep AVPlayer synced to telemetry timebase

## Non-Functional Priorities

- smooth 60fps replay on mainstream iPhones
- offline-first session browsing
- resilient import for imperfect data files
- deterministic calculations for compare results
- battery-aware background parsing
