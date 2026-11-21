# Packet Field Coverage

## Purpose

This document lists the packet families and high-value fields that are currently parsed in Asurada Core.

It is intended as a stage-two feature reference for:
- model feature engineering
- strategy expansion
- replay analytics
- dashboard/HUD extensions

## Decoder rejection contract (2026-09-16)

The public entry point remains `asurada.pdu_decoder.F125PacketDecoder.decode_raw`.
Family implementations live under `asurada/decoders/`; moving them does not change
packet envelopes or existing field names.

- Supported wire identity: packet format `2025`, game year `25`, packet version `1`.
  A game major/minor build change alone is accepted when the wire layout is unchanged.
- All 16 known packet families require their complete documented fixed size.
  Session requires **753 bytes**. There is no evidence that unknown 760/800-byte
  layouts preserve existing field offsets, so they are rejected explicitly.
- A rejected datagram raises `PacketDecodeError`; it never becomes a partial
  normal envelope, refreshes a Session cache, or enters a strategy snapshot.
- Wire-reading failures (`struct.error`, `IndexError`, `UnicodeDecodeError`) become
  `PacketDecodeError`. Unrelated programming errors continue to propagate.
- Live/capture loops expose bounded `decode_diagnostics` counters and the latest
  error. Capture summaries, review projection manifests and per-sample training
  export summaries include the same diagnostic information. Log messages name
  the packet family, format, version, received size and expected size.
- Unknown packet IDs retain the prior empty-body behavior; no guessed fields are decoded.

This is controlled degradation with a visible error, not support for future layouts.
It does not add a dashboard protocol-error indicator or claim 30-minute live fault
injection acceptance.

## Current Packet Coverage

Current decoded packet kinds in the main capture path:
- `Session`
- `LapData`
- `Participants`
- `CarSetups`
- `CarTelemetry`
- `CarStatus`
- `FinalClassification`
- `CarDamage`
- `SessionHistory`
- `TyreSets`
- `Motion`
- `MotionEx`
- `Event`
- `LapPositions`

Additional parser support available outside the current capture sample:
- `LobbyInfo`
- `TimeTrial`

## Normalized Hot-Path State

These fields already flow into `SessionState` and `raw`.

### Session

- `track`
- `weather`
- `safety_car`
- `total_laps`
- `session_type`
- `track_length_m`
- `track_temperature_c`
- `air_temperature_c`
- `pit_speed_limit_kph`
- `marshal_zones`
- `num_weather_forecast_samples`
- `weather_forecast_samples`
- `forecast_accuracy`
- `ai_difficulty`
- `season_link_identifier`
- `weekend_link_identifier`
- `session_link_identifier`
- `pit_stop_window_ideal_lap`
- `pit_stop_window_latest_lap`
- `pit_stop_rejoin_position`
- assist / ruleset settings:
  - `steering_assist`
  - `braking_assist`
  - `gearbox_assist`
  - `pit_assist`
  - `pit_release_assist`
  - `ers_assist`
  - `drs_assist`
  - `dynamic_racing_line`
  - `dynamic_racing_line_type`
  - `game_mode`
  - `rule_set`
- session environment / configuration:
  - `time_of_day_minutes`
  - `session_length`
  - speed / temperature units
  - safety-car / red-flag counters
  - equal performance / recovery / flashback / surface / low-fuel settings
  - race starts / tyre temperature / pit-lane tyre sim
  - damage / collisions / corner-cutting / parc ferme / pit-stop experience
  - `safety_car_setting`
  - `formation_lap`
  - `red_flags_setting`
  - `num_sessions_in_weekend`
  - `weekend_structure`
  - `sector2_lap_distance_start_m`
  - `sector3_lap_distance_start_m`
- `session_trailer_hex`

### LapData

- `lap_number`
- `position`
- `lap_distance_m`
- `total_distance_m`
- `current_lap_time_ms`
- `last_lap_time_ms`
- `sector1_time_ms`
- `sector2_time_ms`
- `delta_to_car_in_front_minutes`
- `delta_to_car_in_front_ms`
- `delta_to_race_leader_minutes`
- `delta_to_race_leader_ms`
- `official_delta_to_car_in_front_s`
- `official_delta_to_race_leader_s`
- `timing_mode`
- `timing_support_level`
- `official_gap_ahead_s`
- `official_gap_behind_s`
- `official_gap_source_ahead`
- `official_gap_source_behind`
- `official_gap_confidence_ahead`
- `official_gap_confidence_behind`
- `estimated_gap_ahead_s` (debug only)
- `estimated_gap_behind_s` (debug only)
- `estimated_gap_source_ahead` (debug only)
- `estimated_gap_source_behind` (debug only)
- `estimated_gap_confidence_ahead` (debug only)
- `estimated_gap_confidence_behind` (debug only)
- `rival_gap_sources`
- `sector`
- `pit_status`
- `car_position`
- `num_pit_stops`
- `penalties`
- `warnings`
- `driver_status`
- `result_status`

Also available for all cars:
- lap distance
- lap number
- car position
- sector
- pit status

### LapData parser additions (not promoted to normalized driving state)

Each 57-byte car record now exposes:

- `speed_trap_fastest_speed_kph`: little-endian float at record offset 52, km/h.
- `speed_trap_fastest_lap`: byte at record offset 56; `255` means not set.

Both fields appear in the selected-player body and `all_cars`. The two Time Trial
indices remain at packet offsets 1283 and 1284. These fields are historical speed
trap maxima, not the current speed, and are not used for strategy or model labels.

### Participants

- `name`
- `team_id`
- `race_number`
- `nationality`
- `driver_id`
- `network_id`
- `ai_controlled`

Participant records follow the F1 25 57-byte layout: the UTF-8 name occupies
record offsets 7–38 (32 bytes), `telemetry_setting` is at 39, and
`show_online_names` is at 40. The decoder additionally names `tech_level` (41–42),
`platform` (43), `num_colours` (44) and up to four RGB `livery_colours` (45–56).
These metadata bytes are no longer interpreted as part of a 48-byte name.

### LobbyInfo

- `num_players`
- `player`
- `active_players`
- `all_players`

Also available for each lobby player:
- `ai_controlled`
- `team_id`
- `nationality`
- `platform`
- `name`
- `car_number`
- `telemetry_setting`
- `show_online_names`
- `tech_level`
- `ready_status`

### CarSetups

- front / rear wing
- on / off throttle diff
- front / rear camber
- front / rear toe
- suspension
- anti-roll bars
- ride height
- brake pressure
- brake bias
- `engine_braking`
- four tyre pressures
- ballast
- fuel load

### CarTelemetry

- `speed_kph`
- `throttle`
- `steer`
- `brake`
- `gear`
- `engine_rpm`
- `drs`
- rev lights
- brake temperatures
- tyre surface temperatures
- tyre inner temperatures
- tyre pressures
- engine temperature
- surface type

Also available for all cars:
- speed
- throttle
- steer
- brake
- gear
- rpm
- drs

### CarStatus

- fuel in tank
- fuel capacity
- fuel remaining laps
- max rpm
- idle rpm
- max gears
- drs allowed
- drs activation distance
- actual tyre compound
- visual tyre compound
- tyre age laps
- FIA flags
- engine power ICE
- engine power MGU-K
- ers store energy
- ers deploy mode
- ers harvested MGU-K
- ers harvested MGU-H
- ers deployed this lap

Also available for all cars:
- fuel remaining laps
- tyre compound
- tyre age
- ers store energy

### CarDamage

- `tyres_wear_pct[4]`
- `tyres_damage_pct[4]`
- `tyre_blisters_pct[4]`
- `brakes_damage_pct[4]`
- wing damage
- floor / diffuser / sidepod damage
- gearbox / engine damage
- engine component damage:
  - `mguh`
  - `energy_store`
  - `control_electronics`
  - `ice`
  - `mguk`
  - `turbo_charger`
- `engine_blown`
- `engine_seized`
- `drs_fault`
- `ers_fault`

Also available for all cars:
- tyre wear
- tyre damage
- blistering
- brake damage
- aero / drivetrain damage

### Motion

- world position
- world velocity
- world forward direction
- world right direction
- g-force
- orientation:
  - yaw
  - pitch
  - roll

### MotionEx

- suspension position / velocity / acceleration
- wheel speed
- wheel slip ratio
- wheel slip angle
- wheel lateral force
- wheel longitudinal force
- wheel vertical force
- local velocity
- angular velocity
- angular acceleration
- front wheels angle
- front / rear aero height
- front / rear roll angle
- chassis yaw
- chassis pitch
- wheel camber
- wheel camber gain
- height of COG above ground

### SessionHistory

- `num_laps`
- `num_tyre_stints`
- best lap / sector lap numbers
- `lap_history_data[100]`
  - lap time
  - sector 1 time
  - sector 2 time
  - sector 3 time
  - lap valid flags
- `tyre_stints_history_data[8]`
  - stint end lap
  - actual compound
  - visual compound

### FinalClassification

- final position
- laps completed
- grid position
- points
- pit stops
- result status
- best lap time
- total race time
- penalties
- tyre stints summary

### TyreSets

- set index
- actual tyre compound
- visual tyre compound
- wear
- availability
- recommended session
- life span
- usable life
- lap delta time
- fitted
- fitted index
- requested fitted index

### Event

- `event_code`
- `event_detail`
- `button_status` for `BUTN`

### TimeTrial

- `player_session_best`
- `personal_best`
- `rival_session_best`
- lap / sector times
- assist settings
- setup validity flags

### LapPositions

Current status:
- fully identified and named from packet id 15
- exposes lap-position history matrix for up to `50` laps and `22` cars
- selected position-trend summaries are now promoted into deterministic answers and LLM state summaries
- full lap-position history matrix remains retained in `raw` and coverage/debug paths

## Main Raw Snapshots For Stage Two

The most useful `raw` branches for stage-two work are:
- `raw.car_setup`
- `raw.session_history`
- `raw.session_history_summary`
- `raw.final_classification`
- `raw.tyre_sets`
- `raw.participants`
- `raw.lobby_info`
- `raw.lap_positions`
- `raw.auxiliary_packet_15` (backward-compatible alias)

The most useful flattened model features already exposed are:
- tyre wear / damage / blistering
- engine component wear
- sector split times
- deltas to front / leader
- slip ratio / slip angle
- wheel forces
- local velocity
- angular velocity / acceleration
- motion direction vectors
- front wheel angle
- aero heights
- chassis yaw / pitch
- session temperatures
- weather forecast samples
- fuel / ERS values
- tyre temperatures / pressures

## Known Boundaries

- some race-gap semantics for unknown session codes are still not protocol-final
- `session_type 8` is now explicitly routed as `result_like / disabled / non-actionable` rather than treated as an estimated timing mode
- packet coverage is broad, but not every auxiliary field is yet promoted into strategy logic
