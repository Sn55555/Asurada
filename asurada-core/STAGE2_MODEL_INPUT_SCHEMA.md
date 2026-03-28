# Stage Two Model Input Schema

## Purpose

This document defines the recommended stage-two model input contract for Asurada Core.

It contains:
- input schema
- feature grouping
- units and expected value ranges
- readiness notes

Use this file together with:
- [PACKET_FIELD_COVERAGE.md](PACKET_FIELD_COVERAGE.md)
- [UNRESOLVED_PACKET_FIELDS.md](UNRESOLVED_PACKET_FIELDS.md)

## Recommended Input Object

```json
{
  "frame_meta": {},
  "session_features": {},
  "lap_features": {},
  "driver_features": {},
  "tyre_damage_features": {},
  "motion_features": {},
  "motion_ex_features": {},
  "track_semantic_features": {},
  "context_features": {},
  "rival_features": [],
  "strategy_debug_features": {}
}
```

## Feature Groups

### 1. Frame Meta

Purpose:
- frame identity
- replay ordering
- time alignment

Fields:
- `session_uid`
- `frame_identifier`
- `overall_frame_identifier`
- `source_timestamp_ms`
- `session_time_s`
- `track`
- `lap_number`

### 2. Session Features

Purpose:
- global race / session context
- environmental conditions

Fields:
- `weather`
- `safety_car`
- `total_laps`
- `track_length_m`
- `track_temperature_c`
- `air_temperature_c`
- `pit_speed_limit_kph`
- `marshal_zones`
- `weather_forecast_samples`
- `forecast_accuracy`
- `ai_difficulty`
- `season_link_identifier`
- `weekend_link_identifier`
- `session_link_identifier`
- `pit_stop_window_ideal_lap`
- `pit_stop_window_latest_lap`
- `pit_stop_rejoin_position`
- `game_mode`
- `rule_set`
- `time_of_day_minutes`
- `session_length`
- `num_safety_car_periods`
- `num_virtual_safety_car_periods`
- `num_red_flag_periods`
- `weekend_structure`
- `sector2_lap_distance_start_m`
- `sector3_lap_distance_start_m`

### 2.5 Lobby Features

Purpose:
- multiplayer participant context
- human / AI / ready-state metadata

Fields:
- `lobby_info.num_players`
- `lobby_info.player`
- `lobby_info.active_players`
- `lobby_info.all_players`

### 3. Lap Features

Purpose:
- lap progress
- timing state
- pit / penalty state

Fields:
- `lap_distance_m`
- `total_distance_m`
- `current_lap_time_ms`
- `last_lap_time_ms`
- `sector`
- `sector1_time_ms`
- `sector2_time_ms`
- `delta_to_car_in_front_ms`
- `delta_to_race_leader_ms`
- `pit_status`
- `num_pit_stops`
- `penalties`
- `total_warnings`
- `corner_cutting_warnings`
- `driver_status`
- `result_status`
- `lap_positions.num_laps`
- `lap_positions.lap_start`
- `lap_positions.player_lap_positions`

### 4. Driver Features

Purpose:
- player resource state
- control input state
- pace state

Fields:
- `position`
- `gap_ahead_s` (official-only normalized player gap)
- `gap_behind_s` (official-only normalized player gap)
- `timing_mode`
- `timing_support_level`
- `official_gap_ahead_s`
- `official_gap_behind_s`
- `official_gap_source_ahead`
- `official_gap_source_behind`
- `official_gap_confidence_ahead`
- `official_gap_confidence_behind`
- `estimated_gap_ahead_s` (debug only, do not train on)
- `estimated_gap_behind_s` (debug only, do not train on)
- `speed_kph`
- `throttle`
- `brake`
- `steer`
- `gear`
- `rpm`
- `fuel_in_tank`
- `fuel_capacity`
- `fuel_laps_remaining`
- `ers_store_energy`
- `ers_pct`
- `ers_deploy_mode`
- `drs_available`
- `status_tags`

### 5. Tyre And Damage Features

Purpose:
- degradation
- durability
- grip loss risk

Fields:
- `tyre.compound`
- `tyre.age_laps`
- `tyre.wear_pct`
- `tyres_wear_pct[4]`
- `tyres_damage_pct[4]`
- `tyre_blisters_pct[4]`
- `brakes_damage_pct[4]`
- `wing_damage_pct`
- `floor_damage_pct`
- `diffuser_damage_pct`
- `sidepod_damage_pct`
- `gearbox_damage_pct`
- `engine_damage_pct`
- `engine_components_damage_pct`
- `engine_blown`
- `engine_seized`

### 6. Motion Features

Purpose:
- car attitude
- global movement

Fields:
- `g_force_lateral`
- `g_force_longitudinal`
- `g_force_vertical`
- `yaw`
- `pitch`
- `roll`
- `world_position_x`
- `world_position_y`
- `world_position_z`
- `world_forward_dir`
- `world_right_dir`

### 7. MotionEx Features

Purpose:
- detailed tyre / chassis dynamics
- local-frame motion behavior

Fields:
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
- `height_of_cog_above_ground`

### 8. Track Semantic Features

Purpose:
- convert telemetry into track-aware semantics

Fields:
- `track_zone`
- `track_segment`
- `track_usage`

### 9. Context Features

Purpose:
- short-window model context
- trend state

Fields:
- `recent_unstable_ratio`
- `recent_front_overload_ratio`
- `driving_mode`
- `tyre_age_factor`
- `brake_phase_factor`
- `throttle_phase_factor`
- `steering_phase_factor`

### 10. Rival Features

Purpose:
- front / rear competitive pressure

Fields per rival:
- `name`
- `position`
- `lap`
- `official_gap_ahead_s`
- `official_gap_behind_s`
- `gap_source`
- `gap_confidence`
- `fuel_laps_remaining`
- `ers_pct`
- `drs_available`
- `speed_kph`
- `tyre.compound`
- `tyre.wear_pct`
- `tyre.age_laps`

### 11. Strategy Debug Features

Purpose:
- supervision and explanation targets
- alignment between features and strategy output

Fields:
- `assessment`
- `risk_profile`
- `risk_explain`
- `usage_bias`
- `candidates`
- `messages`

## Timing Feature Notes

- `timing_mode`
  - meaning: current session family for timing interpretation
  - expected values: `time_trial_disabled`, `qualifying_like`, `race_like`, `session_type_estimated`
- `timing_support_level`
  - meaning: whether timing deltas are fit for direct strategy/model use
  - expected values: `disabled`, `official_preferred`, `estimated_only`
- `gap_source_*`
  - meaning: provenance of each normalized gap value
  - expected values: `official_lapdata_adjacent`, `estimated_total_distance_same_lap`, `estimated_total_distance_cross_lap`, `estimated_lap_distance_wrap`, `session_type_time_trial_disabled`, `unavailable`
- `gap_confidence_*`
  - meaning: reliability tier derived from timing provenance
  - expected values: `high`, `medium`, `low`, `none`
- training guidance:
  - prefer `official_preferred + high`
  - treat `medium` as contextual support features
  - treat `low` as weak or masked features
  - drop `none` from supervised timing tasks
  - current capture validation already supports race-like session codes `15 / 16`
  - current capture validation also supports `session_type 13` as `qualifying_like + official_preferred`
  - current capture validation does not support promoting `session_type 8` beyond `estimated_only`

## Units And Expected Ranges

### Scalar Units

- `speed_kph`
  - unit: km/h
  - expected range: `0 .. 380`
- `lap_distance_m`
  - unit: m
  - expected range: `0 .. track_length_m`
- `total_distance_m`
  - unit: m
  - expected range: non-negative, session-dependent
- `current_lap_time_ms`, `last_lap_time_ms`, `sector1_time_ms`, `sector2_time_ms`
  - unit: ms
  - expected range: `0 .. 300000`
- `fuel_in_tank`, `fuel_capacity`
  - unit: liters-equivalent game value
  - expected range: `0 .. 120`
- `fuel_laps_remaining`
  - unit: laps
  - expected range: `0 .. 99`
- `ers_store_energy`
  - unit: game energy units
  - expected range: `0 .. 4000000`
- `ers_pct`
  - unit: percent
  - expected range: `0 .. 100`
- damage / wear / blister / brake percentages
  - unit: percent
  - expected range: `0 .. 100`
- `throttle`, `brake`
  - unit: normalized scalar
  - expected range: `0 .. 1`
- `steer`
  - unit: normalized scalar
  - expected range: `-1 .. 1`
- `g_force_*`
  - unit: g
  - expected range: approximately `-6 .. 6`
- `yaw`, `pitch`, `roll`
  - unit: radians
  - expected range: track-dependent
- `wheel_slip_ratio`
  - unit: normalized ratio
  - expected range: approximately `-1 .. 1`
- `wheel_slip_angle`
  - unit: radians-like game float
  - expected range: approximately `-1 .. 1`
- `wheel_*_force`
  - unit: game force scalar
  - expected range: track-dependent, non-stationary
- `front_aero_height`, `rear_aero_height`, `height_of_cog_above_ground`
  - unit: meters-like game float
  - expected range: small positive floats
- `official_gap_ahead_s`, `official_gap_behind_s`
  - unit: seconds
  - expected range: `0 .. 999`

### Categorical Fields

- `weather`
- `safety_car`
- `pit_status`
- `driving_mode`
- `track_zone`
- `track_segment`
- `track_usage`
- `assessment.*`
- `tyre.compound`

Recommendation:
- encode as integer vocabulary or learned embedding

### Variable-Length Arrays

- `marshal_zones`
- `weather_forecast_samples`
- `rivals`
- `status_tags`
- `candidates`
- `messages`

Recommendation:
- use truncation + padding or summary pooling depending on model architecture

## Readiness Notes

### Ready For Model Use

- session temperatures and weather forecast
- lap progress and timing
- fuel / ERS state
- tyre wear / damage
- high-value motion and motion-ex features
- track semantics
- short-window context
- strategy debug targets

### Use With Caution

- `delta_to_car_in_front_ms`
- `delta_to_race_leader_ms`
- `official_gap_ahead_s`
- `official_gap_behind_s`

Reason:
- time assembly and source tagging are now explicit
- race-like `15 / 16` and qualifying-like `13` now have usable validation
- `session_type 8` and any remaining unknown codes still need caution before being treated as protocol-final timing features

### Additional Structured History Features

- `raw.lap_positions.num_laps`
- `raw.lap_positions.lap_start`
- `raw.lap_positions.player_lap_positions`
- `raw.lap_positions.lap_positions`

Reason:
- useful for stage-two sequence / history models
- not yet promoted into stage-one strategy logic

## Suggested Training Views

### Sequence Model View

Use:
- last `N` normalized frames
- include `context_features` and `track_semantic_features`
- optionally include top `K` rivals

### Segment Model View

Use:
- aggregate by `track_segment`
- summarize:
  - speed
  - slip
  - tyre load
  - brake / throttle traces
  - strategy message density

### Strategy Supervision View

Use:
- current frame features
- `assessment`
- `risk_profile`
- `candidates`
- `messages`

This is suitable for:
- policy imitation
- ranking models
- explanation alignment
