import Combine
import SwiftUI

struct RootTabView: View {
    @StateObject private var appState = AppState()
    private let livePollingTimer = Timer.publish(every: 0.05, on: .main, in: .common).autoconnect()

    var body: some View {
        ZStack(alignment: .top) {
            TabView(selection: $appState.selectedTab) {
                NavigationStack {
                    HomeView()
                }
                .tag(AppTab.home)
                .tabItem {
                    Label("Home", systemImage: "house")
                }

                NavigationStack {
                    SessionsView()
                }
                .tag(AppTab.sessions)
                .tabItem {
                    Label("Sessions", systemImage: "clock.arrow.circlepath")
                }

                NavigationStack {
                    ReplayView()
                }
                .tag(AppTab.replay)
                .tabItem {
                    Label("Replay", systemImage: "play.square")
                }

                NavigationStack {
                    CompareView()
                }
                .tag(AppTab.compare)
                .tabItem {
                    Label("Compare", systemImage: "chart.xyaxis.line")
                }

                NavigationStack {
                    ProfileView()
                }
                .tag(AppTab.profile)
                .tabItem {
                    Label("Profile", systemImage: "person.crop.circle")
                }
            }

            if let state = appState.foregroundDamageIslandState {
                ForegroundDamageIsland(
                    state: state,
                    expanded: appState.foregroundDamageIslandExpanded
                )
                .padding(.top, appState.foregroundDamageIslandExpanded ? 50 : 54)
                .ignoresSafeArea(.container, edges: .top)
                .transition(.move(edge: .top).combined(with: .opacity))
                .zIndex(20)
            }
        }
        .environmentObject(appState)
        .tint(SaabTheme.blue)
        .toolbarBackground(SaabTheme.black, for: .tabBar)
        .toolbarBackground(.visible, for: .tabBar)
        .toolbarColorScheme(.dark, for: .tabBar)
        .saabScreen()
        .onReceive(livePollingTimer) { _ in
            if appState.isUSBLiveMode {
                appState.pollUSBBridgeNow()
            }
        }
        .animation(.spring(response: 0.42, dampingFraction: 0.82), value: appState.foregroundDamageIslandExpanded)
        .animation(.easeInOut(duration: 0.18), value: appState.foregroundDamageIslandState)
    }
}

private struct ForegroundDamageIsland: View {
    let state: RaceDamageActivityAttributes.ContentState
    let expanded: Bool

    var body: some View {
        GeometryReader { proxy in
            let expandedWidth = min(proxy.size.width - 22, 368)
            let compactWidth = min(proxy.size.width - 180, 156)
            let width = expanded ? expandedWidth : max(128, compactWidth)

            islandContent
                .frame(width: width, height: expanded ? 128 : 38)
                .background(islandBackground)
                .clipShape(Capsule(style: .continuous))
                .overlay(Capsule(style: .continuous).strokeBorder(SaabTheme.line, lineWidth: 1))
                .shadow(color: SaabTheme.red.opacity(expanded ? 0.32 : 0.20), radius: expanded ? 18 : 10)
                .frame(maxWidth: .infinity, alignment: .top)
        }
        .frame(height: expanded ? 134 : 44)
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }

    @ViewBuilder
    private var islandContent: some View {
        if expanded {
            HStack(spacing: 12) {
                ForegroundF1DamageMap(state: state)
                    .frame(width: 72, height: 104)

                VStack(alignment: .leading, spacing: 8) {
                    damageLightRow

                    VStack(alignment: .leading, spacing: 3) {
                        Text(primaryZoneDisplay(for: state))
                            .font(.system(size: 18, weight: .black, design: .monospaced))
                            .foregroundStyle(SaabTheme.red.opacity(0.94))
                            .lineLimit(1)
                            .minimumScaleFactor(0.50)
                            .shadow(color: SaabTheme.red.opacity(0.50), radius: 5)

                        Text(damageMetricLabel(for: state))
                            .font(.system(size: 8, weight: .black, design: .monospaced))
                            .foregroundStyle(SaabTheme.dim)
                            .lineLimit(1)
                    }

                    HStack(alignment: .lastTextBaseline, spacing: 9) {
                        HStack(alignment: .lastTextBaseline, spacing: 3) {
                            Text("\(primaryMetricValue(for: state))")
                                .font(.system(size: 30, weight: .black, design: .monospaced).monospacedDigit())
                                .foregroundStyle(SaabTheme.red.opacity(0.92))
                                .lineLimit(1)
                                .minimumScaleFactor(0.62)
                            Text("%")
                                .font(.system(size: 10, weight: .black, design: .monospaced))
                                .foregroundStyle(SaabTheme.dim)
                        }

                        Text(state.lapText)
                            .font(.system(size: 12, weight: .black, design: .monospaced).monospacedDigit())
                            .foregroundStyle(SaabTheme.white.opacity(0.80))
                            .lineLimit(1)
                            .minimumScaleFactor(0.70)
                            .padding(.horizontal, 7)
                            .padding(.vertical, 4)
                            .background(.white.opacity(0.08), in: Capsule(style: .continuous))
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(.horizontal, 18)
            .padding(.vertical, 12)
        } else {
            HStack(spacing: 7) {
                Circle()
                    .fill(SaabTheme.red)
                    .frame(width: 7, height: 7)
                    .shadow(color: SaabTheme.red.opacity(0.85), radius: 5)

                Text("\(primaryMetricValue(for: state))%")
                    .font(.system(size: 14, weight: .black, design: .monospaced).monospacedDigit())
                    .foregroundStyle(SaabTheme.red.opacity(0.94))
                    .lineLimit(1)

                Text(primaryMetricLabel(for: state))
                    .font(.system(size: 9, weight: .black, design: .monospaced))
                    .foregroundStyle(SaabTheme.dim)
                    .lineLimit(1)
                    .minimumScaleFactor(0.70)
            }
            .padding(.horizontal, 14)
        }
    }

    private var islandBackground: some ShapeStyle {
        LinearGradient(
            colors: [
                Color(red: 0.030, green: 0.034, blue: 0.044).opacity(0.98),
                Color.black.opacity(0.98)
            ],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }

    private var damageLightRow: some View {
        HStack(spacing: 4) {
            ForEach(0..<5, id: \.self) { index in
                Capsule()
                    .fill(index < activeDamageLights(for: state) ? damageLightColor(index) : SaabTheme.white.opacity(0.14))
                    .frame(width: 18, height: 5)
                    .shadow(
                        color: index < activeDamageLights(for: state) ? damageLightColor(index).opacity(0.75) : .clear,
                        radius: 6
                    )
            }
        }
    }
}

private struct ForegroundF1DamageMap: View {
    let state: RaceDamageActivityAttributes.ContentState

    var body: some View {
        GeometryReader { proxy in
            let carRect = fittedCarRect(in: proxy.size)
            let visibleCarRect = visibleCarBodyRect(in: carRect)

            ZStack {
                Image("GlassF1TopView")
                    .resizable()
                    .scaledToFit()
                    .opacity(0.80)
                    .shadow(color: SaabTheme.white.opacity(0.24), radius: 2)
                    .shadow(color: Color.black.opacity(0.55), radius: 4, x: 0, y: 1)

                ForegroundDamageFlashOverlay(state: state, carRect: visibleCarRect)
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

private struct ForegroundDamageFlashOverlay: View {
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
                    .font(.system(size: max(9, carRect.width * 0.13), weight: .black))
                    .foregroundStyle(SaabTheme.red.opacity(0.66))
                    .symbolEffect(.pulse, options: .repeating)
                    .shadow(color: SaabTheme.red.opacity(0.42), radius: 4)
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
        RoundedRectangle(cornerRadius: max(4, carRect.width * 0.024), style: .continuous)
            .fill(SaabTheme.red.opacity(0.07))
            .overlay(
                RoundedRectangle(cornerRadius: max(4, carRect.width * 0.024), style: .continuous)
                    .stroke(SaabTheme.red.opacity(0.42), lineWidth: 1)
            )
            .frame(width: width, height: height)
            .shadow(color: SaabTheme.red.opacity(0.36), radius: 5)
            .opacity(critical ? 1 : 0)
            .position(x: x, y: y)
            .symbolEffect(.pulse, options: .repeating, value: critical)
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
            .fill(SaabTheme.red.opacity(0.065))
            .overlay(path.stroke(SaabTheme.red.opacity(0.34), lineWidth: 0.95))
            .shadow(color: SaabTheme.red.opacity(0.24), radius: 3)
            .opacity(critical ? 1 : 0)
    }
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
        return "WEAR LIMIT"
    }
    if state.primaryZone.localizedCaseInsensitiveContains("FAULT") {
        return "FAULT"
    }
    return "STRUCT LIMIT"
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
    if index >= 4 { return SaabTheme.red }
    if index >= 3 { return SaabTheme.white }
    return SaabTheme.blue
}
