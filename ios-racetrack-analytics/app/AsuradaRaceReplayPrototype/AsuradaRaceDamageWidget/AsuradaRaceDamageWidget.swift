import ActivityKit
import SwiftUI
import WidgetKit

@main
struct AsuradaRaceDamageWidgetBundle: WidgetBundle {
    var body: some Widget {
        RaceDamageLiveActivityWidget()
    }
}

struct RaceDamageLiveActivityWidget: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: RaceDamageActivityAttributes.self) { context in
            RaceDamageLockScreenView(
                carName: context.attributes.carName,
                state: context.state
            )
            .activityBackgroundTint(Color.black.opacity(0.88))
            .activitySystemActionForegroundColor(.red)
        } dynamicIsland: { context in
            DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    GeneratedF1DamageMap(state: context.state)
                        .frame(width: 58, height: 88)
                        .padding(.leading, 4)
                }

                DynamicIslandExpandedRegion(.trailing) {
                    islandDamageReadout(state: context.state)
                        .frame(width: 128, alignment: .trailing)
                        .padding(.trailing, 2)
                }

                DynamicIslandExpandedRegion(.bottom) {
                    islandDamageStatusBar(state: context.state)
                        .padding(.horizontal, 6)
                        .padding(.top, 2)
                }
            } compactLeading: {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(.red)
            } compactTrailing: {
                Text("\(context.state.severityPct)%")
                    .font(.system(.caption, design: .monospaced).monospacedDigit().weight(.black))
                    .foregroundStyle(.red)
            } minimal: {
                ZStack {
                    Circle()
                        .stroke(.red, lineWidth: 2)
                    Text("\(min(99, context.state.severityPct))")
                        .font(.system(size: 8, weight: .black, design: .monospaced))
                        .foregroundStyle(.red)
                }
            }
            .keylineTint(.red)
        }
    }
}

private func islandDamageReadout(state: RaceDamageActivityAttributes.ContentState) -> some View {
    VStack(alignment: .trailing, spacing: 3) {
        Text("DMG")
            .font(.system(size: 8, weight: .black, design: .monospaced))
            .foregroundStyle(.white.opacity(0.50))
            .lineLimit(1)

        Text(primaryZoneDisplay(for: state))
            .font(.system(size: 15, weight: .black, design: .monospaced))
            .foregroundStyle(.red.opacity(0.94))
            .lineLimit(1)
            .minimumScaleFactor(0.54)
            .shadow(color: .red.opacity(0.48), radius: 4)

        HStack(alignment: .firstTextBaseline, spacing: 4) {
            Text("\(primaryMetricValue(for: state))")
                .font(.system(size: 25, weight: .black, design: .monospaced).monospacedDigit())
                .foregroundStyle(.red.opacity(0.90))
                .lineLimit(1)
                .minimumScaleFactor(0.70)
            Text("%")
                .font(.system(size: 9, weight: .black, design: .monospaced))
                .foregroundStyle(.white.opacity(0.58))
        }
    }
}

private func islandDamageStatusBar(state: RaceDamageActivityAttributes.ContentState) -> some View {
    HStack(spacing: 8) {
        HStack(spacing: 3) {
            ForEach(0..<5, id: \.self) { index in
                Capsule()
                    .fill(index < activeDamageLights(for: state) ? damageLightColor(index) : .white.opacity(0.14))
                    .frame(width: 15, height: 4)
                    .shadow(
                        color: index < activeDamageLights(for: state) ? damageLightColor(index).opacity(0.65) : .clear,
                        radius: 4
                    )
            }
        }

        Text(damageMetricLabel(for: state))
            .font(.system(size: 8, weight: .black, design: .monospaced))
            .foregroundStyle(.white.opacity(0.46))
            .lineLimit(1)

        Spacer(minLength: 0)

        Text(state.lapText)
            .font(.system(size: 10, weight: .black, design: .monospaced).monospacedDigit())
            .foregroundStyle(.white.opacity(0.78))
            .lineLimit(1)
            .minimumScaleFactor(0.70)
    }
    .frame(height: 18)
}

private struct RaceDamageLockScreenView: View {
    let carName: String
    let state: RaceDamageActivityAttributes.ContentState

    var body: some View {
        HStack(spacing: 14) {
            GeneratedF1DamageMap(state: state)
                .frame(width: 86, height: 114)

            VStack(alignment: .leading, spacing: 5) {
                Text(carName)
                    .font(.system(.caption2, design: .monospaced).weight(.black))
                    .foregroundStyle(.white.opacity(0.56))
                Text("DAMAGE LIMIT")
                    .font(.system(.subheadline, design: .monospaced).weight(.black))
                    .foregroundStyle(.white)
                Text(state.primaryZone)
                    .font(.system(.caption, design: .monospaced).weight(.black))
                    .foregroundStyle(.red)
                    .lineLimit(1)
                    .minimumScaleFactor(0.72)
                Text(state.lapText)
                    .font(.caption2.weight(.semibold))
                    .lineLimit(1)
                    .minimumScaleFactor(0.72)
                    .foregroundStyle(.white.opacity(0.62))
            }

            Spacer(minLength: 0)

            VStack(alignment: .trailing, spacing: 2) {
                Text("\(state.severityPct)%")
                    .font(.system(.title, design: .monospaced).monospacedDigit().weight(.black))
                    .foregroundStyle(.red.opacity(0.88))
                Text(primaryMetricLabel(for: state))
                    .font(.system(.caption2, design: .monospaced).weight(.black))
                    .foregroundStyle(.white.opacity(0.62))
            }
        }
        .padding(14)
    }
}

private func damageDashReadout(state: RaceDamageActivityAttributes.ContentState) -> some View {
    VStack(alignment: .leading, spacing: 7) {
        HStack(spacing: 4) {
            ForEach(0..<5, id: \.self) { index in
                Capsule()
                    .fill(index < activeDamageLights(for: state) ? damageLightColor(index) : .white.opacity(0.12))
                    .frame(width: 17, height: 5)
                    .shadow(
                        color: index < activeDamageLights(for: state) ? damageLightColor(index).opacity(0.70) : .clear,
                        radius: 5
                    )
            }
        }

        HStack(alignment: .firstTextBaseline, spacing: 7) {
            Text("DMG")
                .font(.system(size: 9, weight: .black, design: .monospaced))
                .foregroundStyle(.white.opacity(0.46))
            Text(primaryZoneDisplay(for: state))
                .font(.system(size: 18, weight: .black, design: .monospaced))
                .lineLimit(1)
                .minimumScaleFactor(0.62)
                .foregroundStyle(.red.opacity(0.94))
                .shadow(color: .red.opacity(0.52), radius: 5)
        }

        HStack(spacing: 7) {
            dashReadoutCell(damageMetricLabel(for: state), value: "\(primaryMetricValue(for: state))%", tint: .red)
            dashReadoutCell("LAP", value: state.lapText, tint: .white)
        }
    }
    .frame(width: 156, alignment: .leading)
}

private func dashReadoutCell(_ label: String, value: String, tint: Color) -> some View {
    VStack(alignment: .leading, spacing: 2) {
        Text(label)
            .font(.system(size: 8, weight: .black, design: .monospaced))
            .foregroundStyle(.white.opacity(0.46))
            .lineLimit(1)
        Text(value)
            .font(.system(size: 13, weight: .black, design: .monospaced).monospacedDigit())
            .foregroundStyle(tint.opacity(0.90))
            .lineLimit(1)
            .minimumScaleFactor(0.66)
            .shadow(color: tint.opacity(0.42), radius: 4)
    }
    .frame(width: 62, alignment: .leading)
    .padding(.horizontal, 7)
    .padding(.vertical, 6)
    .background(.black.opacity(0.58), in: RoundedRectangle(cornerRadius: 6, style: .continuous))
    .overlay(RoundedRectangle(cornerRadius: 6, style: .continuous).stroke(.white.opacity(0.16), lineWidth: 1))
}

private func primaryMetricLabel(for state: RaceDamageActivityAttributes.ContentState) -> String {
    let zone = state.primaryZone.uppercased()
    if zone.contains("TYRE") || zone.contains("BLISTER") {
        return "TYRE"
    }
    if zone.contains("FAULT") {
        return "FAULT"
    }
    if zone.contains("WING") { return "WING" }
    if zone.contains("FLOOR") { return "FLOOR" }
    if zone.contains("DIFFUSER") { return "DIFF" }
    if zone.contains("SIDEPOD") { return "POD" }
    if zone.contains("GEARBOX") { return "GEARBOX" }
    if zone.contains("ENGINE") { return "ENGINE" }
    return "STRUCT"
}

private func damageMetricLabel(for state: RaceDamageActivityAttributes.ContentState) -> String {
    if state.primaryZone.localizedCaseInsensitiveContains("WEAR")
        || state.primaryZone.localizedCaseInsensitiveContains("BLISTER") {
        return "WEAR"
    }
    if state.primaryZone.localizedCaseInsensitiveContains("FAULT") {
        return "FAULT"
    }
    return "DMG"
}

private func primaryMetricValue(for state: RaceDamageActivityAttributes.ContentState) -> Int {
    switch primaryMetricLabel(for: state) {
    case "TYRE":
        return state.tyreWearMaxPct
    case "FAULT":
        return 100
    default:
        return state.structuralMaxPct
    }
}

private func primaryZoneDisplay(for state: RaceDamageActivityAttributes.ContentState) -> String {
    var text = state.primaryZone
    for suffix in [" WEAR", " DAMAGE", " BLISTER"] {
        text = text.replacingOccurrences(of: suffix, with: "", options: [.caseInsensitive])
    }
    return text
}

private func activeDamageLights(for state: RaceDamageActivityAttributes.ContentState) -> Int {
    min(5, max(1, Int((Double(state.severityPct) / 100.0 * 5.0).rounded(.up))))
}

private func damageLightColor(_ index: Int) -> Color {
    if index >= 4 { return .red }
    if index >= 3 { return .white }
    return Color(red: 0.18, green: 0.52, blue: 1.0)
}

private struct GeneratedF1DamageMap: View {
    let state: RaceDamageActivityAttributes.ContentState

    var body: some View {
        GeometryReader { proxy in
            let carRect = fittedCarRect(in: proxy.size)
            let visibleCarRect = visibleCarBodyRect(in: carRect)

            ZStack {
                Image("GlassF1TopView")
                    .resizable()
                    .scaledToFit()
                    .opacity(0.86)
                    .shadow(color: .white.opacity(0.20), radius: 2, x: 0, y: 0)
                    .shadow(color: .black.opacity(0.52), radius: 3, x: 0, y: 1)

                DamageFlashOverlay(state: state, carRect: visibleCarRect)
                    .frame(width: proxy.size.width, height: proxy.size.height)
            }
        }
    }

    private func fittedCarRect(in size: CGSize) -> CGRect {
        let imageAspectRatio = 876.0 / 1796.0
        let containerAspectRatio = size.width / max(size.height, 1)

        let fittedWidth: CGFloat
        let fittedHeight: CGFloat
        if containerAspectRatio > imageAspectRatio {
            fittedHeight = size.height
            fittedWidth = fittedHeight * imageAspectRatio
        } else {
            fittedWidth = size.width
            fittedHeight = fittedWidth / imageAspectRatio
        }

        return CGRect(
            x: (size.width - fittedWidth) / 2,
            y: (size.height - fittedHeight) / 2,
            width: fittedWidth,
            height: fittedHeight
        )
    }

    private func visibleCarBodyRect(in fittedImageRect: CGRect) -> CGRect {
        let sourceWidth = 876.0
        let sourceHeight = 1796.0
        let visibleMinX = 137.0 / sourceWidth
        let visibleMinY = 97.0 / sourceHeight
        let visibleWidth = (732.0 - 137.0) / sourceWidth
        let visibleHeight = (1680.0 - 97.0) / sourceHeight

        return CGRect(
            x: fittedImageRect.minX + fittedImageRect.width * visibleMinX,
            y: fittedImageRect.minY + fittedImageRect.height * visibleMinY,
            width: fittedImageRect.width * visibleWidth,
            height: fittedImageRect.height * visibleHeight
        )
    }
}

private struct DamageFlashOverlay: View {
    let state: RaceDamageActivityAttributes.ContentState
    let carRect: CGRect

    var body: some View {
        ZStack {
            tyreGlow(state.frontLeftTyreCritical, x: carX(0.132), y: carY(0.191), width: carW(0.230), height: carH(0.132))
            tyreGlow(state.frontRightTyreCritical, x: carX(0.873), y: carY(0.191), width: carW(0.224), height: carH(0.132))
            tyreGlow(state.rearLeftTyreCritical, x: carX(0.105), y: carY(0.837), width: carW(0.205), height: carH(0.130))
            tyreGlow(state.rearRightTyreCritical, x: carX(0.894), y: carY(0.837), width: carW(0.205), height: carH(0.130))

            zoneGlow(state.frontWingCritical, points: [
                CGPoint(x: 0.045, y: 0.050), CGPoint(x: 0.130, y: 0.040),
                CGPoint(x: 0.240, y: 0.030), CGPoint(x: 0.360, y: 0.012),
                CGPoint(x: 0.430, y: 0.018), CGPoint(x: 0.410, y: 0.066),
                CGPoint(x: 0.330, y: 0.074), CGPoint(x: 0.250, y: 0.092),
                CGPoint(x: 0.160, y: 0.124), CGPoint(x: 0.055, y: 0.128),
                CGPoint(x: 0.035, y: 0.105)
            ])
            zoneGlow(state.frontWingCritical, points: [
                CGPoint(x: 0.955, y: 0.050), CGPoint(x: 0.870, y: 0.040),
                CGPoint(x: 0.760, y: 0.030), CGPoint(x: 0.640, y: 0.012),
                CGPoint(x: 0.570, y: 0.018), CGPoint(x: 0.590, y: 0.066),
                CGPoint(x: 0.670, y: 0.074), CGPoint(x: 0.750, y: 0.092),
                CGPoint(x: 0.840, y: 0.124), CGPoint(x: 0.945, y: 0.128),
                CGPoint(x: 0.965, y: 0.105)
            ])
            zoneGlow(state.floorCritical, points: [
                CGPoint(x: 0.41, y: 0.40), CGPoint(x: 0.59, y: 0.40),
                CGPoint(x: 0.63, y: 0.82), CGPoint(x: 0.37, y: 0.82)
            ])
            zoneGlow(state.sidepodCritical, points: [
                CGPoint(x: 0.22, y: 0.43), CGPoint(x: 0.42, y: 0.39),
                CGPoint(x: 0.43, y: 0.60), CGPoint(x: 0.31, y: 0.69),
                CGPoint(x: 0.18, y: 0.62)
            ])
            zoneGlow(state.sidepodCritical, points: [
                CGPoint(x: 0.78, y: 0.43), CGPoint(x: 0.58, y: 0.39),
                CGPoint(x: 0.57, y: 0.60), CGPoint(x: 0.69, y: 0.69),
                CGPoint(x: 0.82, y: 0.62)
            ])
            zoneGlow(state.engineCritical, points: [
                CGPoint(x: 0.44, y: 0.50), CGPoint(x: 0.56, y: 0.50),
                CGPoint(x: 0.58, y: 0.68), CGPoint(x: 0.52, y: 0.77),
                CGPoint(x: 0.45, y: 0.72), CGPoint(x: 0.42, y: 0.58)
            ])
            zoneGlow(state.rearWingCritical || state.diffuserCritical, points: [
                CGPoint(x: 0.193, y: 0.902), CGPoint(x: 0.812, y: 0.902),
                CGPoint(x: 0.812, y: 0.940), CGPoint(x: 0.193, y: 0.940)
            ])
            zoneGlow(state.rearWingCritical || state.diffuserCritical, points: [
                CGPoint(x: 0.193, y: 0.947), CGPoint(x: 0.435, y: 0.947),
                CGPoint(x: 0.435, y: 0.978), CGPoint(x: 0.193, y: 0.978)
            ])
            zoneGlow(state.rearWingCritical || state.diffuserCritical, points: [
                CGPoint(x: 0.529, y: 0.947), CGPoint(x: 0.812, y: 0.947),
                CGPoint(x: 0.812, y: 0.978), CGPoint(x: 0.529, y: 0.978)
            ])
            zoneGlow(state.rearWingCritical || state.diffuserCritical, points: [
                CGPoint(x: 0.193, y: 0.902), CGPoint(x: 0.250, y: 0.902),
                CGPoint(x: 0.250, y: 0.994), CGPoint(x: 0.193, y: 0.994)
            ])
            zoneGlow(state.rearWingCritical || state.diffuserCritical, points: [
                CGPoint(x: 0.755, y: 0.902), CGPoint(x: 0.812, y: 0.902),
                CGPoint(x: 0.812, y: 0.994), CGPoint(x: 0.755, y: 0.994)
            ])

            if state.hasFault {
                Image(systemName: "bolt.fill")
                    .font(.system(size: max(10, carRect.width * 0.13), weight: .black))
                    .foregroundStyle(.red.opacity(0.72))
                    .symbolEffect(.pulse, options: .repeating)
                    .shadow(color: .red.opacity(0.45), radius: 4)
                    .opacity(0.82)
                    .position(x: carX(0.50), y: carY(0.61))
            }
        }
    }

    private func carX(_ normalized: CGFloat) -> CGFloat {
        carRect.minX + carRect.width * normalized
    }

    private func carY(_ normalized: CGFloat) -> CGFloat {
        carRect.minY + carRect.height * normalized
    }

    private func carW(_ normalized: CGFloat) -> CGFloat {
        carRect.width * normalized
    }

    private func carH(_ normalized: CGFloat) -> CGFloat {
        carRect.height * normalized
    }

    private func tyreGlow(_ critical: Bool, x: CGFloat, y: CGFloat, width: CGFloat, height: CGFloat) -> some View {
        RoundedRectangle(cornerRadius: max(5, carRect.width * 0.026), style: .continuous)
            .fill(.red.opacity(0.08))
            .overlay(
                RoundedRectangle(cornerRadius: max(5, carRect.width * 0.026), style: .continuous)
                    .stroke(.red.opacity(0.46), lineWidth: 1.1)
            )
            .frame(width: width, height: height)
            .shadow(color: .red.opacity(0.35), radius: 5)
            .opacity(critical ? 1 : 0)
            .position(x: x, y: y)
    }

    private func zoneGlow(_ critical: Bool, points: [CGPoint]) -> some View {
        let path = Path { path in
            guard let first = points.first else { return }
            path.move(to: CGPoint(x: carX(first.x), y: carY(first.y)))
            for point in points.dropFirst() {
                path.addLine(to: CGPoint(x: carX(point.x), y: carY(point.y)))
            }
            path.closeSubpath()
        }

        return path
            .fill(.red.opacity(0.075))
            .overlay(path.stroke(.red.opacity(0.38), lineWidth: 1.05))
            .shadow(color: .red.opacity(0.24), radius: 3)
            .opacity(critical ? 1 : 0)
    }
}
