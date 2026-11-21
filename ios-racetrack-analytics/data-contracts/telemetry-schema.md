# Telemetry Schema Draft

## File Shape

Recommended normalized JSON structure:

```json
{
  "sessionId": "session_001",
  "track": "Shanghai International Circuit",
  "driver": "Driver A",
  "vehicle": "GT4",
  "startTime": "2026-03-19T10:00:00Z",
  "laps": [
    {
      "lapNumber": 1,
      "lapTimeMs": 122345,
      "valid": true,
      "samples": [
        {
          "timestampMs": 0,
          "latitude": 31.338,
          "longitude": 121.22,
          "speedKph": 132.4,
          "throttlePct": 84,
          "brakePct": 0,
          "steeringDeg": -6.5,
          "gear": 4,
          "rpm": 6520,
          "lateralG": 1.2,
          "longitudinalG": 0.3
        }
      ]
    }
  ]
}
```

## Import Rules

- all timestamps use milliseconds
- all laps must contain ordered samples
- missing values should be nullable, not guessed during import
- derived metrics should be stored separately from raw input when possible

## Future Extensions

- tire temperature
- suspension travel
- brake pressure
- GPS heading
- camera/video offset
