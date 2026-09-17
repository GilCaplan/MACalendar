import SwiftUI

// MARK: - Sources
//
// The citation list under an answer. This is not decoration: Jude's whole
// claim is that an answer can be checked, and the check is the passage plus
// the Sefaria link. A collapsed card that hides both would keep the claim and
// drop the evidence, so the ref and the link are always visible and only the
// text folds away.

/// One retrieved passage.
///
/// Collapsed it shows the ref, its category and how close the match was;
/// expanded it shows the English, and — when Jude sent one — the Hebrew or
/// Aramaic original behind its own toggle.
struct JudeSourceCard: View {
    let source: JudeSource
    @EnvironmentObject var settings: AppSettings

    @State private var expanded = false
    @State private var showHebrew = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            header
            if expanded {
                if !source.enText.isEmpty {
                    Text("“\(source.enText)”")
                        .font(.footnote)
                        .foregroundColor(.primary)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if source.hasHebrew { hebrew }
            }
        }
        .padding(10)
        .background(Color(.secondarySystemBackground))
        .cornerRadius(Theme.radiusMD)
        .overlay(
            // The accent border is the ONLY visual difference between a
            // primary source and a secondary one, and it is deliberate: the
            // distinction is about where the passage came from (the topic's
            // canonical hierarchy), not about how much to trust it.
            RoundedRectangle(cornerRadius: Theme.radiusMD)
                .stroke(source.isPrimary == true ? settings.accentColor : Color.clear,
                        lineWidth: source.isPrimary == true ? 1.5 : 0)
        )
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                // The link is its own tap target, separate from the expand
                // tap: opening Sefaria and reading the excerpt are different
                // intentions, and one gesture cannot serve both.
                if let url = source.sefariaURL {
                    Link(destination: url) {
                        HStack(spacing: 4) {
                            Text(source.ref).font(.footnote.weight(.semibold))
                            Image(systemName: "arrow.up.right.square").font(.caption2)
                        }
                    }
                    .buttonStyle(.plain)
                    .foregroundColor(settings.accentColor)
                } else {
                    Text(source.ref).font(.footnote.weight(.semibold))
                }
                Spacer(minLength: 4)
                Button {
                    withAnimation(.easeInOut(duration: 0.15)) { expanded.toggle() }
                } label: {
                    Image(systemName: expanded ? "chevron.up" : "chevron.down")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                        .padding(4)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(expanded ? "Collapse source" : "Expand source")
            }

            HStack(spacing: 6) {
                if !source.category.isEmpty {
                    Text(source.category)
                        .font(.caption2)
                        .padding(.horizontal, 6).padding(.vertical, 2)
                        .background(Color(.tertiarySystemBackground))
                        .cornerRadius(Theme.radiusSM)
                }
                if source.isPrimary == true {
                    Label("Primary", systemImage: "scalemass")
                        .font(.caption2.weight(.semibold))
                        .foregroundColor(settings.accentColor)
                }
                if let pct = source.matchPercent {
                    Text("\(pct)% match").font(.caption2).foregroundColor(.secondary)
                }
                if source.hasHebrew {
                    Spacer(minLength: 4)
                    Button {
                        withAnimation(.easeInOut(duration: 0.15)) {
                            // Asking for the Hebrew implies asking for the
                            // card: a toggle that expanded nothing read as a
                            // dead button while collapsed.
                            expanded = true
                            showHebrew.toggle()
                        }
                    } label: {
                        Text(showHebrew ? "עברית ▴" : "עברית ▾").font(.caption2)
                    }
                    .buttonStyle(.plain)
                    .foregroundColor(.secondary)
                }
            }
        }
        .contentShape(Rectangle())
        .onTapGesture { withAnimation(.easeInOut(duration: 0.15)) { expanded.toggle() } }
    }

    @ViewBuilder
    private var hebrew: some View {
        if showHebrew {
            VStack(alignment: .trailing, spacing: 4) {
                Text("Original Hebrew / Aramaic")
                    .font(.caption2).foregroundColor(.secondary)
                Text(source.heText)
                    .font(.footnote)
                    .textSelection(.enabled)
                    .multilineTextAlignment(.trailing)
                    .fixedSize(horizontal: false, vertical: true)
            }
            // Both are needed. `layoutDirection` puts the block and its
            // wrapping on the right; `multilineTextAlignment` handles the last
            // line, which otherwise hung on the left of a right-aligned block.
            .environment(\.layoutDirection, .rightToLeft)
            .frame(maxWidth: .infinity, alignment: .trailing)
            .padding(.top, 2)
        }
    }
}

// MARK: - The list under an answer

/// Every source for one answer, sectioned.
///
/// Two shapes, because the wire has two. When `is_primary` is present at all,
/// Jude ran a dual retrieval for a detected halachic topic and the canonical
/// hierarchy comes first — that ordering IS the halachic claim, so it is not
/// negotiable. Otherwise there is one pool and category is the only grouping
/// that means anything.
struct JudeSourcesSection: View {
    let sources: [JudeSource]
    @EnvironmentObject var settings: AppSettings
    @State private var expanded = true

    private var primaries: [JudeSource] { sources.filter { $0.isPrimary == true } }
    private var secondaries: [JudeSource] { sources.filter { $0.isPrimary == false } }
    private var unranked: [JudeSource] { sources.filter { $0.isPrimary == nil } }
    private var isDual: Bool { !primaries.isEmpty || !secondaries.isEmpty }

    var body: some View {
        if !sources.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                Button {
                    withAnimation(.easeInOut(duration: 0.15)) { expanded.toggle() }
                } label: {
                    HStack(spacing: 6) {
                        Image(systemName: "books.vertical").font(.caption)
                        Text("Sources (\(sources.count))").font(.caption.weight(.semibold))
                        Image(systemName: expanded ? "chevron.up" : "chevron.down")
                            .font(.caption2)
                        Spacer()
                    }
                    .foregroundColor(.secondary)
                }
                .buttonStyle(.plain)

                if expanded {
                    if isDual {
                        if !primaries.isEmpty {
                            group(label: "⚖ Primary Sources (\(primaries.count))",
                                  tint: settings.accentColor, items: primaries)
                        }
                        if !secondaries.isEmpty {
                            group(label: "🔍 Secondary Sources (\(secondaries.count))",
                                  tint: .secondary, items: secondaries)
                        }
                        if !unranked.isEmpty {
                            group(label: "Also retrieved (\(unranked.count))",
                                  tint: .secondary, items: unranked)
                        }
                    } else {
                        byCategory(sources)
                    }
                }
            }
        }
    }

    /// A primary/secondary section, itself split by category — the two
    /// groupings are orthogonal (where a passage sits in the hierarchy vs.
    /// which corpus it is from) and a halachic answer routinely cites four
    /// corpora, so flattening either one buries the shape of the answer.
    @ViewBuilder
    private func group(label: String, tint: Color, items: [JudeSource]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(label).font(.caption2.weight(.bold)).foregroundColor(tint)
            byCategory(items)
        }
    }

    /// Sources mode groups by the category the router PLANNED to draw from,
    /// which is the shape of its answer — "four Talmud, two Shulchan Arukh" is
    /// the plan, and a passage that came back tagged differently still belongs
    /// under the slot it was fetched for. Everywhere else there is no plan and
    /// the passage's own category is the only thing to group on.
    private func groupKey(_ s: JudeSource) -> String {
        if !s.plannedCategory.isEmpty { return s.plannedCategory }
        return s.category.isEmpty ? "Other" : s.category
    }

    @ViewBuilder
    private func byCategory(_ items: [JudeSource]) -> some View {
        // Categories in the order Jude first mentions them, not alphabetical:
        // retrieval returns its best match first and the ordering carries that
        // ranking, which sorting would throw away.
        let order = items.reduce(into: [String]()) { acc, s in
            if !acc.contains(groupKey(s)) { acc.append(groupKey(s)) }
        }
        VStack(alignment: .leading, spacing: 8) {
            ForEach(order, id: \.self) { category in
                let inCategory = items.filter { groupKey($0) == category }
                if order.count > 1 {
                    Text("\(category) · \(inCategory.count)")
                        .font(.caption2).foregroundColor(.secondary)
                        .padding(.top, 2)
                }
                ForEach(inCategory) { JudeSourceCard(source: $0) }
            }
        }
    }
}
