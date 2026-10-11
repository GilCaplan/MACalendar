import SwiftUI

// MARK: - The recipe sheet
//
// What makes a row better (criteria: a column, higher or lower, a weight),
// which rows count at all (conditions), and which column the picture's
// numbers match. Apply re-ranks with this recipe without saving it; Save keeps
// it as a preset under its name (`PUT /ranker/presets/<name>`).

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
        let named = recipe.criteria.map(\.column) + recipe.filters.map(\.column) + [recipe.key].compactMap { $0 }
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
                presetSection
                criteriaSection
                conditionsSection
                keySection
                saveSection
            }
            .navigationTitle("Recipe")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Apply") { onApply(recipe); dismiss() }
                        .disabled(recipe.criteria.isEmpty)
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
        .confirmationDialog("Delete this recipe?", isPresented: $confirmDelete,
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

    // MARK: Sections

    private var presetSection: some View {
        Section {
            if presets.count > 1 {
                Picker("Start from", selection: Binding(
                    get: { isSaved ? recipe.name : "" },
                    set: { name in if let p = presets.first(where: { $0.name == name }) { recipe = p } })) {
                    if !isSaved { Text("Unsaved").tag("") }
                    ForEach(presets) { p in Text(p.name).tag(p.name) }
                }
            }
            TextField("Name", text: $recipe.name)
        } header: { Text("Recipe") }
    }

    private var criteriaSection: some View {
        Section {
            ForEach($recipe.criteria) { $c in
                VStack(alignment: .leading, spacing: 8) {
                    columnMenu(selection: $c.column)
                    HStack {
                        Picker("Better", selection: $c.better) {
                            Text("Higher").tag("higher")
                            Text("Lower").tag("lower")
                        }
                        .pickerStyle(.segmented)
                        .frame(maxWidth: 170)
                        Spacer()
                        Stepper(value: $c.weight, in: 0...10, step: 0.5) {
                            Text("×\(RankerCell.trim(c.weight, places: 1))")
                                .monospacedDigit()
                                .frame(maxWidth: .infinity, alignment: .trailing)
                        }
                        .fixedSize()
                    }
                }
                .padding(.vertical, 2)
            }
            .onDelete { recipe.criteria.remove(atOffsets: $0) }
            Button {
                recipe.criteria.append(RankerCriterion(column: columns.first?.name ?? ""))
            } label: { Label("Rank by another column", systemImage: "plus") }
            .disabled(columns.isEmpty)
        } header: {
            Text("Rank by")
        } footer: {
            Text("Each column ranks the rows against each other, so a column in billions and one in single digits count only by their weights. Weight 0 leaves a column out.")
        }
    }

    private var conditionsSection: some View {
        Section {
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
                        .frame(maxWidth: 80)
                }
            }
            .onDelete { recipe.filters.remove(atOffsets: $0) }
            Button {
                recipe.filters.append(RankerCondition(column: columns.first?.name ?? ""))
            } label: { Label("Add a condition", systemImage: "plus") }
            .disabled(columns.isEmpty)
        } header: {
            Text("Only rows where")
        } footer: {
            if columns.isEmpty {
                Text("Send a table first — its columns are what a recipe can name.")
            }
        }
    }

    private var keySection: some View {
        Section {
            Picker("Numbers match", selection: Binding(
                get: { recipe.key ?? columns.first?.name ?? "" },
                set: { recipe.key = $0 })) {
                ForEach(columns) { c in Text(c.label).tag(c.name) }
            }
        } footer: {
            Text("The column holding the numbers a screenshot is matched against.")
        }
    }

    private var saveSection: some View {
        Section {
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
                Label(isSaved ? "Save changes" : "Save as a recipe", systemImage: "square.and.arrow.down")
            }
            .disabled(recipe.criteria.isEmpty || recipe.name.trimmingCharacters(in: .whitespaces).isEmpty)
            if isSaved {
                Button(role: .destructive) { confirmDelete = true } label: {
                    Label("Delete this recipe", systemImage: "trash")
                }
                .disabled(presets.count < 2)
            }
        } footer: {
            if isSaved && presets.count < 2 { Text("Keep at least one recipe — edit this one instead.") }
        }
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
                Image(systemName: "chevron.up.chevron.down").font(.caption2)
                    .foregroundColor(.secondary)
            }
        }
    }
}
