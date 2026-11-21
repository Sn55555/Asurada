import ActivityKit
import Foundation

struct RaceDamageActivityAttributes: ActivityAttributes {
    struct ContentState: Codable, Hashable {
        var title: String
        var primaryZone: String
        var trackName: String
        var lapText: String
        var severityPct: Int
        var affectedCount: Int
        var tyreWearMaxPct: Int
        var structuralMaxPct: Int
        var frontLeftTyreCritical: Bool
        var frontRightTyreCritical: Bool
        var rearLeftTyreCritical: Bool
        var rearRightTyreCritical: Bool
        var frontWingCritical: Bool
        var rearWingCritical: Bool
        var floorCritical: Bool
        var diffuserCritical: Bool
        var sidepodCritical: Bool
        var engineCritical: Bool
        var hasFault: Bool
    }

    var carName: String
}
