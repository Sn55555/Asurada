# Unresolved Packet Fields

## Purpose

This document lists packet fields and packet families that are not yet fully finalized.

It is intended for:
- stage-two parser completion
- model feature planning
- protocol validation follow-up

The current status is split into three buckets:
- usable now
- needs refinement
- unnamed

## Usable Now

These fields already have stable parsing and are suitable for stage-two model ingestion.

### Session

- `weather`
- `track_temperature_c`
- `air_temperature_c`
- `total_laps`
- `track_length_m`
- `track_id`
- `pit_speed_limit_kph`
- `marshal_zones`
- `weather_forecast_samples`

### LapData

- `lap_distance_m`
- `total_distance_m`
- `current_lap_time_ms`
- `last_lap_time_ms`
- `sector`
- `sector1_time_ms`
- `sector2_time_ms`
- `pit_status`
- `num_pit_stops`
- `penalties`
- `warnings`
- `driver_status`
- `result_status`

### Participants

- `name`
- `team_id`
- `race_number`
- `nationality`
- `driver_id`
- `network_id`

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
- tyre pressures
- `ballast`
- `fuel_load`

### CarTelemetry

- `speed_kph`
- `throttle`
- `steer`
- `brake`
- `gear`
- `engine_rpm`
- `drs`
- brake temperatures
- tyre surface / inner temperatures
- tyre pressures
- engine temperature

### CarStatus

- `fuel_in_tank`
- `fuel_capacity`
- `fuel_remaining_laps`
- `drs_allowed`
- tyre compounds
- `tyres_age_laps`
- `ers_store_energy`
- `ers_deploy_mode`
- ERS harvest / deploy values

### CarDamage

- `tyres_wear_pct`
- `tyres_damage_pct`
- `tyre_blisters_pct`
- `brakes_damage_pct`
- wing damage
- floor / diffuser / sidepod damage
- gearbox / engine damage
- `engine_components_damage_pct`
- `engine_blown`
- `engine_seized`

### Motion

- world position
- world velocity
- `g_force`
- `yaw`
- `pitch`
- `roll`
- `world_forward_dir`
- `world_right_dir`

### MotionEx

- suspension position / velocity / acceleration
- `wheel_speed`
- `wheel_slip_ratio`
- `wheel_slip_angle`
- `wheel_lat_force`
- `wheel_long_force`
- `wheel_vert_force`
- `local_velocity`
- `angular_velocity`
- `angular_acceleration`
- `front_wheels_angle`
- `front_aero_height`
- `rear_aero_height`
- `front_roll_angle`
- `rear_roll_angle`
- `chassis_yaw`
- `chassis_pitch`
- `wheel_camber`
- `wheel_camber_gain`

### SessionHistory

- `num_laps`
- `num_tyre_stints`
- best lap / sector lap numbers
- `lap_history_data`
- `tyre_stints_history_data`

### FinalClassification

- `position`
- `num_laps`
- `grid_position`
- `points`
- `num_pit_stops`
- `result_status`
- `best_lap_time_ms`
- `total_race_time_s`
- penalty summary
- tyre stint summary

### TyreSets

- set compound
- wear
- availability
- recommended session
- life span
- usable life
- lap delta
- fitted state

### Event

- `event_code`
- `BUTN`
- `FTLP`
- `PENA`
- `OVTK`
- `STLG`
- `LGOT`
- common single-vehicle event detail payloads

### TimeTrial

- `player_session_best`
- `personal_best`
- `rival_session_best`

## Needs Refinement

These fields are already present or partially usable, but are not yet protocol-final.

### LapData

- `delta_to_car_in_front_ms`
- `delta_to_race_leader_ms`

Current status:
- decoded and exposed
- minute-part assembly is now applied and normalized seconds are exposed
- `timing_mode`, `timing_support_level`, and explicit gap-source metadata are now exposed
- gap confidence tiers are now exposed for player and rival timing
- current capture now includes race-like session types `15 / 16`, and those paths have been promoted to `official_preferred`
- `session_type 13` now has qualifying-like sample validation and remains `official_preferred`
- `session_type 8` remains mixed and stays in `estimated_only`
- still needs final validation for any remaining non-time-trial session codes before being treated as protocol-final across all modes

### Rival Gap Semantics

- `official_gap_ahead_s`
- `official_gap_behind_s`
- `estimated_gap_ahead_s` (debug only)
- `estimated_gap_behind_s` (debug only)

Current status:
- normalized state and player-facing `gap_ahead_s / gap_behind_s` now use official-only timing
- estimated gap values remain available only as debug-sidecar fields
- `official_lapdata_adjacent` is the only high-confidence mainline source
- race-like sample validation now exists for session types `15 / 16`
- qualifying-like sample validation now exists for `session_type 13`
- `session_type 8` still lacks stable official timing coverage and remains non-final for timing use
- still needs final validation for any remaining unknown session codes before being treated as protocol-final timing

### TyreSets

Current status:
- stable and useful summary parse exists
- some bytes still need a more protocol-faithful named breakdown

### FinalClassification

Current status:
- usable conservative parse
- some tail semantics still need finer protocol naming

### SessionHistory

Current status:
- main history blocks are available
- higher-level derived features are not yet formalized

### MotionEx

Current status:
- high-value fields are exposed
- per-field physics validation and unit annotation are still incomplete

### CarDamage Multi-Car Use

Current status:
- multi-car damage arrays are parsed
- downstream strategy / dashboard usage is still shallow

### Event Coverage

Current status:
- common event detail payloads are named
- standard union-backed detail payloads are named
- remaining work is mainly real-sample validation for rare codes not present in the current capture

### Participants Integration

Current status:
- identity fields are parsed
- not yet fully promoted into all downstream displays and summaries

### TimeTrial

Current status:
- parser support exists
- current capture sample does not cover this packet for runtime validation

## Unnamed

These packet families or fields remain unnamed or intentionally unpromoted.

### Session Trailer Remainder

Current status:
- fixed-width tail settings block is now promoted into named fields
- `session_trailer_hex` only remains as a defensive fallback for unexpected extra bytes

### Uncovered Event Detail Variants

Current status:
- `event_code` is visible
- detail payload for some rare or unseen codes still needs runtime validation

## Practical Use For Stage Two

For stage-two work:
- use [PACKET_FIELD_COVERAGE.md](/Users/sn5/Asurada/asurada-core/PACKET_FIELD_COVERAGE.md) for fields that are already model-ready
- use this file to identify which parser areas still need protocol completion
