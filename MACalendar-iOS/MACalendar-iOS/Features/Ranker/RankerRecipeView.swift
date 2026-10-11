import SwiftUI

// MARK: - The recipe sheet
//
// What makes a row better, and nothing else up front: "Rank by" rows — a
// column of THIS table, Higher or Lower — and "+ Add". Everything else waits
// under "More options": how much each column counts, conditions a row must
// meet, and the saved rankings (load / save / delete). The column the
// picture's numbers match is not asked: the Mac picks it from the data.
// Apply re-ranks with this recipe without saving it; Save keeps it under its
// name (`PUT /ranker/presets/<name>`). The recipe's `show` (the columns a
// ranking shows) rides along untouched — the Columns control sets it.

struct RankerRecipeView: View {
    @EnvironmentObject var settings: AppSettings
    @Environment(\.dismiss) private var dismiss

    let presets: [RankerRecipe]
    /// The table's own columns; the recipe's derived ones are added to them.
    let tableColumns: [RankerColumn]
    let onApply: (RankerRecipe) -> Void
    /// Each answers nil when done, or the sentence the Mac refused it with.
    let onSave: (RankerRecipe) async -> String?
    let onDelete: (String) async -> String?

    @State private var recipe: RankerRecipe
    @State private var working = false
    @State private var refusal: String?
    @State private var confirmDelete = false
    @State private var moreOpen = false

    init(recipe: RankerRecipe, presets: [RankerRecipe], tableColumns: [RankerColumn],
         onApply: @escaping (RankerRecipe) -> Void,
         onSave: @escaping (RankerRecipe) async -> String?,
         onDelete: @escaping (String) async -> String?) {
        _recipe = State(initialValue: recipe)
        self.presets = presets
        self.tableColumns = tableColumns
        self.onApply = onApply
        self.onSave = onSave
        self.onDelete = onDelete
    }

    /// Every column a recipe may name: the table's, then the sums it makes,
    /// then anything it already names that this table lacks (so a picker never
    /// silently swaps a column the person chose).
    private var columns: [RankerColumn] {
        var out = tableColumns
        for d in recipe.derived where !out.contains(where: { $0.name == d.name }) {
            out.append(RankerColumn(name: d.name, label: d.label))
        }
        let named = recipe.criteria.map(\.column) + recipe.filters.map(\.column)
        for n in named where !n.isEmpty && !out.contains(where: { $0.name == n }) {
            out.append(RankerColumn(name: n, label: n))
        }
        return out
    }

    private func label(_ name: String) -> String {
        columns.first { $0.name == name }?.label ?? name
    }

    private var isSaved: Bool { presets.contains { $0.name == recipe.name } }

    var body: some View {
        StackNavigation {
            Form {
                criteriaSection
                Section {
                    DisclosureGroup(isExpanded: $moreOpen) {
                        moreOptions
                    } label: {
                        Text("More options")
                    }
                    .accessibilityIdentifier("ranker-recipe-more")
                } footer: {
                    Text("How much each column counts, conditions a row must meet, and saved rankings.")
                }
            }
            .navigationTitle("Rank by")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Apply") { onApply(recipe); dismiss() }
                        .accessibilityIdentifier("ranker-recipe-apply")
                }
            }
            .disabled(working)
        }
        .tint(settings.accentColor)
        .alert("Couldn't do that", isPresented: Binding(
            get: { refusal != nil }, set: { if !$0 { refusal = nil } })) {
            Button("OK", role: .cancel) {}
        } message: { Text(refusal ?? "") }
        .confirmationDialog("Delete this ranking?", isPresented: $confirmDelete,
                            titleVisibility: .visible) {
            Button("Delete \(recipe.name)", role: .destructive) {
                Task {
                    working = true
                    refusal = await onDelete(recipe.name)
                    working = false
                    if refusal == nil { dismiss() }
                }
            }
        }
    }

    // MARK: Rank by

    private var criteriaSection: some View {
        Section {
            ForEach($recipe.criteria) { $c in
                HStack(spacing: 10) {
                    columnMenu(selection: $c.column)
                    Spacer(minLength: 4)
                    Picker("Better", selection: $c.better) {
                        Text("Higher").tag("higher")
                        Text("Lower").tag("lower")
                    }
                    .pickerStyle(.segmented)
                    .frame(maxWidth: 140)
                    Button {
                        recipe.criteria.removeAll { $0.id == c.id }
                    } label: {
                        Image(systemName: "minus.circle.fill").foregroundColor(.red)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Remove \(label(c.column))")
                }
            }
            .onDelete { recipe.criteria.remove(atOffsets: $0) }
            Button {
                let used = Set(recipe.criteria.map(\.column))
                let next = columns.first { !used.contains($0.name) } ?? columns.first
                recipe.criteria.append(RankerCriterion(column: next?.name ?? ""))
            } label: { Label("Add", systemImage: "plus") }
            .disabled(columns.isEmpty)
            .accessibilityIdentifier("ranker-recipe-add")
        } header: {
            Text("Rank by")
        } footer: {
            if columns.isEmpty {
                Text("Add a table first — its columns are what you can rank by.")
            } else if recipe.criteria.isEmpty {
                Text("Nothing yet: rows stay in the table's own order. Add a column to rank by it.")
            } else {
                Text("Score 0–100: how each row places against the others on these columns.")
            }
        }
    }

    // MARK: More options

    @ViewBuilder private var moreOptions: some View {
        if !recipe.criteria.isEmpty {
            subheading("How much each counts")
            ForEach($recipe.criteria) { $c in
                Stepper(value: $c.weight, in: 0...10, step: 0.5) {
                    HStack {
                        Text(label(c.column)).lineLimit(1)
                        Spacer()
                        Text("x\(RankerCell.trim(c.weight, places: 1))")
                            .monospacedDigit()
                            .foregroundColor(.secondary)
                    }
                }
            }
        }

        subheading("Only rows where")
        ForEach($recipe.filters) { $f in
            HStack {
                columnMenu(selection: $f.column)
                Spacer()
                Picker("", selection: $f.op) {
                    ForEach(RankerCondition.ops, id: \.self) { Text($0).tag($0) }
                }
                .labelsHidden()
                .fixedSize()
                TextField("value", text: $f.value)
                    .multilineTextAlignment(.trailing)
                    .frame(maxWidth: 70)
                Button {
                    recipe.filters.removeAll { $0.id == f.id }
                } label: {
                    Image(systemName: "minus.circle.fill").foregroundColor(.red)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Remove condition")
            }
        }
        Button {
            recipe.filters.append(RankerCondition(column: columns.first?.name ?? ""))
        } label: { Label("Add a condition", systemImage: "plus") }
        .disabled(columns.isEmpty)

        subheading("Saved rankings")
        if presets.count > 1 || !isSaved {
            Picker("Load", selection: Binding(
                get: { isSaved ? recipe.name : "" },
                set: { name in if let p = presets.first(where: { $0.name == name }) { recipe = p } })) {
                if !isSaved { Text("Unsaved").tag("") }
                ForEach(presets) { p in Text(p.name).tag(p.name) }
            }
        }
        TextField("Name", text: $recipe.name)
        Button {
            Task {
                working = true
                var r = recipe
                r.name = r.name.trimmingCharacters(in: .whitespaces)
                refusal = await onSave(r)
                working = false
                if refusal == nil { dismiss() }
            }
        } label: {
            Label(isSaved ? "Save changes" : "Save this ranking", systemImage: "square.and.arrow.down")
        }
        .disabled(recipe.name.trimmingCharacters(in: .whitespaces).isEmpty)
        if isSaved {
            Button(role: .destructive) { confirmDelete = true } label: {
                Label("Delete this ranking", systemImage: "trash")
            }
            .disabled(presets.count < 2)
        }
    }

    private func subheading(_ text: String) -> some View {
        Text(text)
            .font(.caption.weight(.semibold))
            .foregroundColor(.secondary)
            .textCase(.uppercase)
            .padding(.top, 6)
    }

    // MARK: Pieces

    private func columnMenu(selection: Binding<String>) -> some View {
        Menu {
            ForEach(columns) { c in
                Button { selection.wrappedValue = c.name } label: {
                    if c.name == selection.wrappedValue { Label(c.label, systemImage: "checkmark") }
                    else { Text(c.label) }
                }
            }
        } label: {
            HStack(spacing: 4) {
                Text(selection.wrappedValue.isEmpty ? "Column" : label(selection.wrappedValue))
                    .foregroundColor(.primary)
                    .lineLimit(1)
                Image(systemName: "chevron.up.chevron.down").font(.caption2)
                    .foregroundColor(.secondary)
            }
        }
    }
}
