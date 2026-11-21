# Low-Fidelity Wireframes

This document defines the first-pass low-fidelity layout for the core iPhone screens of the racetrack telemetry analysis and replay app.

## Device Baseline

- Primary target: iPhone Pro size
- Design baseline: 393 x 852 pt class
- Native pattern: iOS tab app with navigation stacks and bottom sheets

## Navigation Structure

Bottom tabs:

1. Home
2. Sessions
3. Replay
4. Compare
5. Profile

Recommended default launch tab: `Home`

---

## 1. Home

### Goal

Help the user continue recent analysis in one tap and surface quick performance insights.

### Layout

Top to bottom:

1. Navigation bar
   - Title: `Home`
   - Right action: import button
2. Driver summary card
   - Driver name
   - Current car / current track
   - Best recent lap
3. Quick insight section
   - 2 to 3 cards
   - Example:
     - "Turn 6 entry speed improved +4.2 km/h"
     - "Brake release is inconsistent in Sector 2"
4. Recent sessions section
   - Vertical list of session cards
   - Each card shows date, track, car, fastest lap, session type
5. Quick actions row
   - Start replay
   - Compare laps
   - Import session

### Wireframe Notes

- Use grouped list sections
- Keep above-the-fold focused on “resume work”
- Quick insights should feel actionable, not decorative

### Primary Interaction

- Tap a recent session -> Session Detail
- Tap quick insight -> Session Detail at relevant lap/event
- Tap import -> file import flow

---

## 2. Session Detail

### Goal

Summarize one session clearly and funnel the user into replay or compare.

### Layout

Top to bottom:

1. Navigation bar
   - Back
   - Title: track or session name
   - Right action: share
2. Session summary header
   - Track
   - Date/time
   - Car
   - Weather
   - Fastest lap
   - Total laps
3. Session KPIs row
   - Best lap
   - Avg lap
   - Best sector
   - Consistency score
4. Lap list section
   - Ranked laps as tappable rows
   - Each row:
     - lap number
     - lap time
     - sector mini split
     - valid/invalid state
5. Event timeline preview
   - Horizontal event strip
   - lockup / oversteer / off-throttle / pit markers
6. Action dock
   - Replay selected lap
   - Compare with best lap
7. Optional notes section
   - setup
   - tires
   - weather notes

### Wireframe Notes

- Lap list is the center of gravity on this screen
- Best lap should be visually pinned
- Event timeline should be compact here and expand later in replay

### Primary Interaction

- Tap lap row -> lap detail sheet or direct replay
- Tap replay -> Replay screen with selected lap
- Tap compare -> Compare screen with selected lap vs best lap prefilled

---

## 3. Replay

### Goal

Give the user a fluid, single-lap or session replay experience with synchronized telemetry.

### Layout

Top to bottom:

1. Navigation bar
   - Title: `Replay`
   - Subtitle: session + lap
   - Right action: video toggle or more menu
2. Track map stage
   - Main canvas area
   - Track outline
   - Moving car marker
   - Optional ghost/reference marker
   - Sector markers
3. Telemetry summary strip
   - Current speed
   - Throttle
   - Brake
   - Gear
   - Lap delta
4. Timeline scrubber block
   - Play / pause
   - Skip sector back / forward
   - Slider scrubber
   - Current timestamp
5. Expandable telemetry panel
   - Segmented control:
     - Speed
     - Throttle/Brake
     - Steering
     - G-force
   - Chart updates with scrubber position
6. Event markers row
   - Lockup
   - Lift
   - Oversteer
   - Apex
   - Sector split
7. Bottom sheet
   - Collapsed: lap summary
   - Expanded: corner notes, detected events, coaching hints

### Wireframe Notes

- Track map should own the top half of the screen
- Playback controls must remain thumb-friendly
- Telemetry charts should never compete with the map at the same hierarchy level
- The bottom sheet is the right place for dense context

### Primary Interaction

- Drag scrubber -> move car marker, update telemetry, jump chart cursor
- Tap event marker -> snap playback to event time
- Switch telemetry segment -> chart changes, playback remains continuous
- Pull up bottom sheet -> reveal deeper analysis without leaving replay

### Native iOS Components

- `NavigationStack`
- `Toolbar`
- `Canvas`
- `Segmented Control`
- `Sheet` / `presentationDetents`
- `Chart`
- `Slider`

---

## 4. Compare

### Goal

Make lap-to-lap differences obvious and actionable.

### Layout

Top to bottom:

1. Navigation bar
   - Title: `Compare`
   - Right action: swap laps
2. Compare selector card
   - Lap A picker
   - Lap B picker
   - Track and session context
3. Delta hero block
   - Total lap delta
   - Faster/slower result
   - Key explanation sentence
4. Delta by track section
   - Horizontal mini track map or progress bar
   - Color-coded gain/loss zones
5. Chart section
   - Segmented control:
     - Delta
     - Speed
     - Throttle/Brake
     - Steering
   - Two traces + one highlighted cursor
6. Corner analysis cards
   - Corner name / number
   - Entry speed difference
   - Mid-corner minimum speed
   - Exit speed difference
   - Brief insight text
7. Summary insight section
   - Top 3 gain opportunities
   - Most consistent section
   - Most unstable section

### Wireframe Notes

- This screen should answer “where exactly was time won or lost?”
- Use a strong summary at the top, then give evidence below
- The comparison selector must be quick to edit without leaving screen

### Primary Interaction

- Change lap selectors -> instant recompute
- Drag chart cursor -> sync delta point and track position
- Tap a corner card -> jump chart to that corner region

### Native iOS Components

- `Picker`
- `Segmented Control`
- `Chart`
- `ScrollView`
- `InsetGrouped` card sections

---

## Shared Component System

### 1. Session Card

- track name
- date
- car
- best lap
- chip for session type

### 2. Lap Row

- lap number
- lap time
- mini sector bars
- status chip

### 3. Telemetry Stat Chip

- label
- current value
- unit
- optional trend color

### 4. Event Pill

- icon
- event name
- timestamp

### 5. Insight Card

- short title
- one-sentence finding
- optional recommendation

---

## Interaction Rules

### Replay Rules

- playback clock is the source of truth
- map, charts, stat chips, and video all sync to the same timestamp
- sector skip uses snapping behavior
- dragging scrubber pauses playback until release

### Compare Rules

- default compare mode: selected lap vs session best lap
- chart cursor and track position remain linked
- use color only for meaningful gain/loss emphasis

### Session Rules

- selecting a lap should persist across transitions into Replay and Compare

---

## First Figma Frames To Draw

Start with these four frames only:

1. Home overview
2. Session Detail with lap list
3. Replay with collapsed bottom sheet
4. Compare with delta chart and first three corner cards

Once these are solid, expand to:

- Replay expanded bottom sheet
- Lap picker modal
- Import flow
- Profile/settings
