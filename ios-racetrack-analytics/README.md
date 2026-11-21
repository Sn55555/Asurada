# iOS Racetrack Analytics Replay App

This folder contains the initial product and technical planning package for an iOS app focused on racetrack session analytics and replay.

## Goal

Build an iPhone-first app that helps drivers, coaches, and track-day teams:

- ingest lap/session data
- analyze lap performance and driving behavior
- replay a session on track with synchronized telemetry
- compare laps, drivers, and sessions

## Folder Structure

- `docs/`: product, feature, architecture, and roadmap documents
- `design/`: UI direction, design principles, and future wireframes
- `app/`: reserved for the future SwiftUI/Xcode project
- `data-contracts/`: telemetry model and API/data format drafts

## Suggested MVP

1. Session import
2. Track map replay
3. Lap comparison
4. Sector analysis
5. Event timeline
6. Video + telemetry sync

## Next Build Step

Create a SwiftUI app in `app/` with modules for `Session`, `Replay`, `Analysis`, and `Compare`.
