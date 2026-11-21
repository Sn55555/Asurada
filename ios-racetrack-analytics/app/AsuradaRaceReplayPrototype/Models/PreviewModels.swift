import Foundation

struct SessionSummary: Identifiable, Hashable {
    let id: UUID
    let title: String
    let trackName: String
    let carName: String
    let sessionType: String
    let dateText: String
    let bestLap: String
    let consistencyScore: Int
    let weather: String
    let laps: [LapSummary]
    let events: [EventMarker]
}

struct LapSummary: Identifiable, Hashable {
    let id: UUID
    let lapNumber: Int
    let lapTime: String
    let sectorTimes: [String]
    let deltaText: String
    let isValid: Bool
}

struct EventMarker: Identifiable, Hashable {
    let id: UUID
    let title: String
    let timeText: String
    let symbol: String
}

struct TelemetryPoint: Identifiable, Hashable {
    let second: Double
    let speed: Double
    let throttle: Double
    let brake: Double
    let delta: Double
    let steer: Double
    let gear: Int
    let rpm: Int
    let drs: Bool
    let revLightsPercent: Int

    var id: Double { second }
}

struct WorldPoint: Hashable {
    let x: Double
    let y: Double
}

struct LiveLapRecord: Identifiable, Hashable {
    let id: UUID
    let lapNumber: Int
    let lapTimeSec: Double
    let telemetry: [TelemetryPoint]
    let isComplete: Bool
}

struct CarDamageState: Hashable {
    var tyresWearPct: [Double] = []
    var tyresDamagePct: [Int] = []
    var brakesDamagePct: [Int] = []
    var tyreBlistersPct: [Int] = []
    var frontLeftWingDamagePct: Int = 0
    var frontRightWingDamagePct: Int = 0
    var rearWingDamagePct: Int = 0
    var floorDamagePct: Int = 0
    var diffuserDamagePct: Int = 0
    var sidepodDamagePct: Int = 0
    var gearboxDamagePct: Int = 0
    var engineDamagePct: Int = 0
    var drsFault: Bool = false
    var ersFault: Bool = false
    var engineBlown: Bool = false
    var engineSeized: Bool = false

    static let empty = CarDamageState()

    var hasTelemetry: Bool {
        !tyresWearPct.isEmpty
            || !tyresDamagePct.isEmpty
            || !brakesDamagePct.isEmpty
            || !tyreBlistersPct.isEmpty
            || structuralValues.contains(where: { $0 > 0 })
            || drsFault
            || ersFault
            || engineBlown
            || engineSeized
    }

    var structuralValues: [Int] {
        [
            frontLeftWingDamagePct,
            frontRightWingDamagePct,
            rearWingDamagePct,
            floorDamagePct,
            diffuserDamagePct,
            sidepodDamagePct,
            gearboxDamagePct,
            engineDamagePct
        ]
    }
}

struct DamageAlert: Identifiable, Hashable {
    let id: String
    let title: String
    let subtitle: String
    let maxSeverityPct: Double
    let warnings: [DamageZoneWarning]
    let damage: CarDamageState
}

struct DamageZoneWarning: Identifiable, Hashable {
    let id: String
    let label: String
    let valuePct: Double
    let kind: DamageWarningKind
}

enum DamageWarningKind: String, Hashable {
    case tyreWear
    case tyreDamage
    case structure
    case fault
}
