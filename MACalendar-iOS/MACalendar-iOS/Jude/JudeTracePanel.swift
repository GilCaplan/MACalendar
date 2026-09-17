import SwiftUI

/// The pipeline trace under a finished answer: what each stage did, how long
/// it took, which tools fired, and the timing breakdown from the `done` event.
///
/// Collapsed by default here, unlike Jude's own web UI which opens it. A
/// desktop sidebar has room to show the machinery beside the answer; a phone
/// screen does not, and pushing a cited answer below five rows of diagnostics
/// buries the thing you asked for. It stays one tap away because the trace is
/// how you tell "it found nothing" from "it found the wrong thing" — the same
/// reason the assistant's own thinking timeline exists.
struct JudeTracePanel: View {
    let steps: [JudeStep]
    let toolCalls: [JudeToolCall]
    let timing: JudeTiming?

    @State private var expanded = false
    @EnvironmentObject var settings: AppSettings

    private var hasContent: Bool {
        !steps.isEmpty || !toolCalls.isEmpty || timing != nil
    }

    var body: some View {
        if hasContent {
            VStack(alignment: .leading, spacing: 6) {
                Button {
                    withAnimation(.easeInOut(duration: 0.15)) { expanded.toggle() }
                } label: {
                    HStack(spacing: 6) {
                        Image(systemName: "magnifyingglass").font(.caption2)
                        Text("Pipeline trace").font(.caption.weight(.semibold))
                        if let total = timing?.totalMs {
                            Text(judeFormatMs(total))
                                .font(.caption2.monospacedDigit())
                                .foregroundColor(settings.accentColor)
                        }
                        Image(systemName: expanded ? "chevron.up" : "chevron.down")
                            .font(.caption2)
                        Spacer()
                    }
                    .foregroundColor(.secondary)
                }
                .buttonStyle(.plain)

                if expanded {
                    VStack(alignment: .leading, spacing: 6) {
                        ForEach(steps) { stepRow($0) }
                        if !toolCalls.isEmpty { toolSection }
                        if let timing { timingSection(timing) }
                    }
                    .padding(.leading, 4)
                }
            }
            .padding(8)
            .background(Color(.secondarySystemBackground).opacity(0.6))
            .cornerRadius(Theme.radiusMD)
        }
    }

    // MARK: - Steps

    /// One module's row. The three modules Jude ships get a reading of their
    /// own `result`; anything else falls through to a generic key/value dump
    /// rather than vanishing — Jude is a separate project still gaining
    /// stages, and a trace that silently omits a new one is worse than an ugly
    /// line, because it looks like the stage never ran.
    @ViewBuilder
    private func stepRow(_ step: JudeStep) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(step.module)
                    .font(.caption2.weight(.bold))
                    .frame(width: 66, alignment: .leading)
                Text(judeFormatMs(step.durationMs))
                    .font(.caption2.monospacedDigit())
                    .foregroundColor(.secondary)
                Text(summary(for: step))
                    .font(.caption2)
                    .foregroundColor(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 0)
            }
            if step.module == "Router" {
                let queries = step.result["search_queries"]?.stringArray ?? []
                if !queries.isEmpty {
                    Text(queries.map { "“\($0)”" }.joined(separator: " · "))
                        .font(.caption2)
                        .foregroundColor(.secondary.opacity(0.8))
                        .padding(.leading, 72)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    private func summary(for step: JudeStep) -> String {
        let r = step.result
        switch step.module {
        case "Router":
            let tier = r["tier"]?.stringValue ?? ""
            let depth = r["depth"]?.stringValue ?? ""
            let cats = (r["categories"]?.stringArray ?? []).prefix(4).joined(separator: " › ")
            return [tier, depth == "light" ? "light" : "", cats]
                .filter { !$0.isEmpty }.joined(separator: " · ")
        case "Retrieval":
            let found = r["sources_found"]?.intValue ?? 0
            let top = r["top_source"]?.stringValue ?? ""
            return top.isEmpty ? "\(found) source(s)" : "\(found) source(s) — \(top)"
        case "Filter":
            let kept = r["kept"]?.intValue ?? 0
            let dropped = r["dropped"]?.intValue ?? 0
            return "\(kept) kept (\(dropped) dropped)"
        default:
            return r.compactMap { key, value in
                value.stringValue.map { "\(key): \($0)" }
            }
            .sorted().joined(separator: " · ")
        }
    }

    // MARK: - Tools

    private var toolSection: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 6) {
                Text("🔧 Tools").font(.caption2.weight(.bold))
                Text("\(toolCalls.count) call(s)").font(.caption2).foregroundColor(.secondary)
            }
            .padding(.top, 2)
            ForEach(toolCalls) { call in
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(call.tool)
                        .font(.caption2.weight(.semibold))
                        .foregroundColor(settings.accentColor)
                    if !call.headlineArg.isEmpty {
                        Text("“\(call.headlineArg.prefix(40))\(call.headlineArg.count > 40 ? "…" : "")”")
                            .font(.caption2).foregroundColor(.secondary)
                    }
                    if let category = call.args["category"]?.stringValue, !category.isEmpty {
                        Text("[\(category)]").font(.caption2).foregroundColor(.secondary)
                    }
                    Text("→ \(call.resultSummary)")
                        .font(.caption2).foregroundColor(.secondary.opacity(0.8))
                    Spacer(minLength: 0)
                }
            }
        }
    }

    // MARK: - Timing

    private func timingSection(_ timing: JudeTiming) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Divider().padding(.vertical, 2)
            ForEach(timing.steps) { leg in
                HStack(spacing: 6) {
                    Text(leg.name)
                        .font(.caption2)
                        .frame(width: 66, alignment: .leading)
                        .foregroundColor(.secondary)
                    Text(judeFormatMs(leg.ms)).font(.caption2.monospacedDigit())
                    // Synthesis is the leg that takes the 30–90 seconds, so
                    // its first token is the number that explains the wait:
                    // "slow to start" and "slow throughout" are different
                    // problems with the same total.
                    if leg.name == "Synthesis", let first = timing.synthFirstTokenMs {
                        Text("first token \(judeFormatMs(first))")
                            .font(.caption2).foregroundColor(.secondary)
                    }
                    Spacer(minLength: 0)
                }
            }
            if let total = timing.totalMs {
                HStack(spacing: 6) {
                    Text("Total")
                        .font(.caption2.weight(.bold))
                        .frame(width: 66, alignment: .leading)
                    Text(judeFormatMs(total))
                        .font(.caption2.monospacedDigit().weight(.bold))
                        .foregroundColor(settings.accentColor)
                    Spacer(minLength: 0)
                }
            }
        }
    }
}
