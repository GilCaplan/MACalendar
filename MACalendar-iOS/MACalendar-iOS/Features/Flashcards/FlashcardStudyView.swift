import SwiftUI
import UIKit

// MARK: - A study round
//
// One card at a time, every type FORMAT.md describes. Self-graded types end in
// Again / Hard / Good / Easy with FSRS.swift's next interval under each; mc and
// order mark themselves (Good if right, Again if wrong). Again puts the card
// back 4-7 places later in this round. Exam mode sends no reviews and puts
// nothing back — it only scores.

struct FlashcardStudyView: View {
    @EnvironmentObject var api: APIClient
    @EnvironmentObject var settings: AppSettings
    @Environment(\.dismiss) private var dismiss
    @ObservedObject private var store = FlashcardStore.shared

    let mode: StudyMode
    @State private var queue: [StudyItem]
    @State private var index = 0
    /// Per study item, whether the FIRST answer this round was right.
    @State private var firstTry: [String: Bool] = [:]
    @State private var seenOrder: [String] = []
    @State private var info: [String: StudyItem] = [:]
    @State private var finished = false

    init(session: StudySession) {
        mode = session.mode
        _queue = State(initialValue: session.items)
    }

    private static func key(_ e: StudyItem) -> String { "\(e.setId)-\(e.card.id)-\(e.item)" }

    var body: some View {
        VStack(spacing: 0) {
            header
            if finished || queue.isEmpty {
                summary
            } else {
                CardFace(entry: queue[index], mode: mode, accent: settings.accentColor) { grade, right in
                    answer(grade: grade, right: right)
                }
                .id(queue[index].id)
                .transition(.opacity)
            }
        }
        .background(Color(.systemBackground).ignoresSafeArea())
    }

    // MARK: - Header

    private var header: some View {
        VStack(spacing: 6) {
            HStack {
                Button(finished ? "Close" : "End") {
                    if finished || firstTry.isEmpty { dismiss() } else { finished = true }
                }
                .accessibilityIdentifier("flashcards-end")
                Spacer()
                if !finished {
                    Text("\(max(0, queue.count - index)) left")
                        .font(.subheadline.monospacedDigit())
                        .foregroundColor(.secondary)
                }
                Spacer()
                Text(mode.label).font(.caption).foregroundColor(.secondary)
            }
            ProgressBar(value: queue.isEmpty ? 1 : Double(finished ? queue.count : index) / Double(queue.count),
                        color: settings.accentColor)
                .frame(height: 3)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
    }

    // MARK: - Answering

    private func answer(grade: Int, right: Bool) {
        let entry = queue[index]
        let k = Self.key(entry)
        if firstTry[k] == nil {
            firstTry[k] = right
            seenOrder.append(k)
            info[k] = entry
        }
        if mode != .exam {
            store.review(entry, grade: grade, api: api)
            if grade == 1 {
                // Back in this round, a few cards on: long enough not to be
                // remembered from a moment ago, soon enough to fix it today.
                let again = StudyItem(setId: entry.setId, setName: entry.setName, dir: entry.dir,
                                      card: entry.card, item: entry.item,
                                      progress: store.progress(setId: entry.setId, cardId: entry.card.id,
                                                               item: entry.item))
                let at = min(queue.count, index + 1 + Int.random(in: 4...7))
                queue.insert(again, at: at)
            }
        }
        withAnimation(.easeInOut(duration: 0.15)) {
            if index + 1 >= queue.count { finished = true } else { index += 1 }
        }
    }

    // MARK: - Summary

    private var summary: some View {
        let total = firstTry.count
        let right = firstTry.values.filter { $0 }.count
        let misses = seenOrder.filter { firstTry[$0] == false }
        var bySet: [(String, Int, Int)] = []
        for k in seenOrder {
            guard let e = info[k] else { continue }
            if let i = bySet.firstIndex(where: { $0.0 == e.setName }) {
                bySet[i].1 += firstTry[k] == true ? 1 : 0
                bySet[i].2 += 1
            } else {
                bySet.append((e.setName, firstTry[k] == true ? 1 : 0, 1))
            }
        }
        return ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                if total == 0 {
                    Text("Nothing answered.")
                        .font(.title3.weight(.semibold))
                } else {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("\(Int((Double(right) / Double(total) * 100).rounded()))%")
                            .font(.system(size: 52, weight: .bold, design: .rounded))
                            .foregroundColor(settings.accentColor)
                            .accessibilityIdentifier("flashcards-score")
                        Text("right first time — \(right) of \(total)")
                            .foregroundColor(.secondary)
                    }
                    if bySet.count > 1 {
                        VStack(alignment: .leading, spacing: 6) {
                            Text("By set").font(.headline)
                            ForEach(bySet, id: \.0) { name, r, n in
                                HStack {
                                    Text(name)
                                    Spacer()
                                    Text("\(r)/\(n)").monospacedDigit().foregroundColor(.secondary)
                                }
                                .font(.subheadline)
                            }
                        }
                    }
                    if !misses.isEmpty {
                        VStack(alignment: .leading, spacing: 6) {
                            Text("Missed").font(.headline)
                            ForEach(misses, id: \.self) { k in
                                if let e = info[k] {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(CardFace.promptLine(e)).font(.subheadline)
                                        Text(CardFace.answerLine(e)).font(.caption).foregroundColor(.secondary)
                                    }
                                    .padding(.vertical, 2)
                                }
                            }
                        }
                    }
                }
                VStack(spacing: 10) {
                    if !misses.isEmpty {
                        Button {
                            practise(misses.compactMap { info[$0] })
                        } label: {
                            Text("Practise mistakes").frame(maxWidth: .infinity).padding(.vertical, 6)
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(settings.accentColor)
                        .accessibilityIdentifier("flashcards-practise")
                    }
                    Button { dismiss() } label: {
                        Text("Back").frame(maxWidth: .infinity).padding(.vertical, 6)
                    }
                    .buttonStyle(.bordered)
                    .accessibilityIdentifier("flashcards-back")
                }
            }
            .padding(20)
        }
    }

    private func practise(_ entries: [StudyItem]) {
        queue = entries.shuffled().map { e in
            StudyItem(setId: e.setId, setName: e.setName, dir: e.dir, card: e.card, item: e.item,
                      progress: store.progress(setId: e.setId, cardId: e.card.id, item: e.item))
        }
        index = 0
        firstTry = [:]
        seenOrder = []
        info = [:]
        finished = false
    }
}

// MARK: - One card

struct CardFace: View {
    @EnvironmentObject var api: APIClient
    let entry: StudyItem
    let mode: StudyMode
    let accent: Color
    let onAnswer: (_ grade: Int, _ right: Bool) -> Void

    @State private var revealed = false
    // mc
    @State private var choices: [String] = []
    @State private var picked: String?
    // order
    @State private var pool: [Int] = []
    @State private var placed: [Int] = []
    @State private var checked = false
    // typed
    @State private var typed = ""
    // occlusion, all at once
    @State private var opened: Set<Int> = []
    /// The question's English, folded away until asked for; remembered, so
    /// someone who always wants it open opens it once (Gil, 2026-10-12).
    @AppStorage("flashcardsEnglishOpen") private var englishOpen = false

    private var card: FlashCard { entry.card }

    var body: some View {
        VStack(spacing: 0) {
            Group {
                if card.type == "occlusion" {
                    occlusion
                } else {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 16) {
                            kicker
                            content
                            if showsNotes { notes }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(20)
                    }
                }
            }
            .environment(\.layoutDirection, entry.isRTL ? .rightToLeft : .leftToRight)
            Divider()
            controls
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
        }
        .onAppear(perform: setUp)
    }

    private func setUp() {
        if card.type == "mc", choices.isEmpty { choices = (card.choices ?? []).shuffled() }
        if card.type == "order", pool.isEmpty, placed.isEmpty {
            let n = card.steps?.count ?? 0
            var p = Array(0..<n).shuffled()
            if n > 1 && p == Array(0..<n) { p.reverse() }     // never hand it over solved
            pool = p
        }
    }

    private var kicker: some View {
        Text("\(entry.setName) · \(FlashTypes.label(card.type))")
            .font(.caption)
            .foregroundColor(.secondary)
    }

    private var showsNotes: Bool {
        let done = revealed || picked != nil || checked
        return done && (card.explain != nil || card.page != nil || card.note != nil)
    }

    private var notes: some View {
        VStack(alignment: .leading, spacing: 4) {
            if let e = card.explain { Text(e) }
            if let e = card.en?.explain { EnglishLine(text: e) }
            if let n = card.note { Text(n).foregroundColor(.secondary) }
            if let n = card.en?.note { EnglishLine(text: n) }
            if let p = card.page { Text("Page \(p)").foregroundColor(.secondary) }
        }
        .font(.callout)
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.secondary.opacity(0.1), in: RoundedRectangle(cornerRadius: Theme.radiusMD))
    }

    // MARK: Content per type

    @ViewBuilder private var content: some View {
        switch card.type {
        case "basic": basic
        case "image": image
        case "cloze": cloze
        case "mc": mc
        case "order": order
        case "typed": typedCard
        default:
            Text("This app doesn't know a \(card.type) card yet.").foregroundColor(.secondary)
        }
    }

    private var basic: some View {
        let rev = entry.item == "rev"
        return VStack(alignment: .leading, spacing: 16) {
            Text((rev ? card.back : card.front) ?? "")
                .font(.title2.weight(.semibold))
                .multilineTextAlignment(.leading)
                .accessibilityIdentifier("flashcards-prompt")
            promptEnglish
            if revealed {
                Divider()
                Text((rev ? card.front : card.back) ?? "")
                    .font(.title3)
                    .foregroundColor(accent)
                    .multilineTextAlignment(.leading)
                    .accessibilityIdentifier("flashcards-answer")
                answerEnglish
            }
        }
    }

    @ViewBuilder private var image: some View {
        let rev = entry.item == "rev"
        if rev {
            Text(card.back ?? "").font(.title2.weight(.semibold))
            promptEnglish
            Text("Picture it, then show the answer.").font(.footnote).foregroundColor(.secondary)
            if revealed, let path = card.image {
                FlashPicture(setId: entry.setId, path: path)
                    .clipShape(RoundedRectangle(cornerRadius: Theme.radiusMD))
            }
        } else {
            if let path = card.image {
                FlashPicture(setId: entry.setId, path: path)
                    .clipShape(RoundedRectangle(cornerRadius: Theme.radiusMD))
                    .frame(maxHeight: 360)
            }
            Text(card.front ?? "What is this?").font(.title3.weight(.semibold))
            promptEnglish
            if revealed {
                Text(card.back ?? "").font(.title3).foregroundColor(accent)
                    .accessibilityIdentifier("flashcards-answer")
                answerEnglish
            }
        }
    }

    private var clozeIndex: Int { Int(entry.item.dropFirst()) ?? 0 }

    private var cloze: some View {
        VStack(alignment: .leading, spacing: 12) {
            clozeText(card.text ?? "", hide: clozeIndex)
                .font(.title3)
                .multilineTextAlignment(.leading)
                .accessibilityIdentifier("flashcards-prompt")
            promptEnglish
            if revealed { answerEnglish }
        }
    }

    /// The cloze with gap `hide` blanked (or, once revealed, shown in the
    /// accent) and every other gap's answer in place.
    private func clozeText(_ text: String, hide: Int) -> Text {
        let ns = text as NSString
        var out = Text("")
        var cursor = 0
        let matches = Cloze.regex.matches(in: text, range: NSRange(location: 0, length: ns.length))
        for (i, m) in matches.enumerated() {
            out = out + Text(ns.substring(with: NSRange(location: cursor, length: m.range.location - cursor)))
            let answer = ns.substring(with: m.range(at: 1))
            if i == hide {
                out = out + (revealed
                    ? Text(answer).bold().foregroundColor(accent).underline()
                    : Text(" [ … ] ").bold().foregroundColor(accent))
            } else {
                out = out + Text(answer)
            }
            cursor = m.range.location + m.range.length
        }
        return out + Text(ns.substring(from: cursor))
    }

    private var mc: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(card.question ?? "").font(.title3.weight(.semibold))
                .accessibilityIdentifier("flashcards-prompt")
            promptEnglish
            ForEach(choices, id: \.self) { choice in
                let isAnswer = choice == card.answer
                let isPicked = choice == picked
                Button {
                    guard picked == nil else { return }
                    picked = choice
                } label: {
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(choice).multilineTextAlignment(.leading)
                            if englishOpen || picked != nil, let e = english(of: choice, in: card.choices, card.en?.choices) {
                                EnglishLine(text: e)
                            }
                        }
                        Spacer()
                        if picked != nil && isAnswer { Image(systemName: "checkmark.circle.fill") }
                        else if isPicked { Image(systemName: "xmark.circle.fill") }
                    }
                    .padding(12)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .foregroundColor(picked == nil ? .primary : (isAnswer ? .green : (isPicked ? .red : .secondary)))
                    .background(
                        RoundedRectangle(cornerRadius: Theme.radiusMD)
                            .stroke(picked == nil ? Color.secondary.opacity(0.4)
                                    : (isAnswer ? .green : (isPicked ? .red : Color.secondary.opacity(0.2))),
                                    lineWidth: picked != nil && (isAnswer || isPicked) ? 2 : 1))
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("flashcards-choice")
            }
            if picked != nil { answerEnglish }
        }
    }

    private var order: some View {
        let steps = card.steps ?? []
        return VStack(alignment: .leading, spacing: 12) {
            Text(card.prompt ?? "Put these in order").font(.title3.weight(.semibold))
                .accessibilityIdentifier("flashcards-prompt")
            promptEnglish
            VStack(alignment: .leading, spacing: 6) {
                ForEach(Array(placed.enumerated()), id: \.offset) { pos, step in
                    HStack(alignment: .top) {
                        Text("\(pos + 1).").monospacedDigit().foregroundColor(.secondary)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(steps[step])
                            if englishOpen || checked, let e = card.en?.steps, step < e.count { EnglishLine(text: e[step]) }
                        }
                        Spacer()
                        if checked {
                            Image(systemName: step == pos ? "checkmark.circle.fill" : "xmark.circle.fill")
                                .foregroundColor(step == pos ? .green : .red)
                        }
                    }
                    .padding(10)
                    .background(Color.secondary.opacity(0.1), in: RoundedRectangle(cornerRadius: Theme.radiusSM))
                }
                if placed.isEmpty {
                    Text("Tap the steps below in order.").font(.footnote).foregroundColor(.secondary)
                }
            }
            if !checked {
                Divider()
                ForEach(pool, id: \.self) { step in
                    Button {
                        pool.removeAll { $0 == step }
                        placed.append(step)
                    } label: {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(steps[step])
                            if englishOpen, let e = card.en?.steps, step < e.count { EnglishLine(text: e[step]) }
                        }
                            .padding(10)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .overlay(RoundedRectangle(cornerRadius: Theme.radiusSM)
                                .stroke(Color.secondary.opacity(0.4)))
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("flashcards-step")
                }
            } else if placed != Array(0..<steps.count) {
                Divider()
                Text("The right order").font(.headline)
                ForEach(Array(steps.enumerated()), id: \.offset) { i, s in
                    VStack(alignment: .leading, spacing: 2) {
                        Text("\(i + 1). \(s)").foregroundColor(accent)
                        if let e = card.en?.steps, i < e.count { EnglishLine(text: e[i]) }
                    }
                }
            }
            if checked { answerEnglish }
        }
    }

    private var typedCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(card.front ?? "").font(.title3.weight(.semibold))
                .accessibilityIdentifier("flashcards-prompt")
            promptEnglish
            if !revealed {
                TextEditor(text: $typed)
                    .frame(minHeight: 140)
                    .padding(4)
                    .overlay(RoundedRectangle(cornerRadius: Theme.radiusSM).stroke(Color.secondary.opacity(0.4)))
                    .accessibilityIdentifier("flashcards-typed")
            } else {
                if !typed.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    Text("You wrote").font(.caption).foregroundColor(.secondary)
                    Text(typed).foregroundColor(.secondary)
                }
                let lines = TypedCheck.marks(answer: card.answer ?? "", typed: typed)
                let missed = lines.flatMap { $0 }.filter { !$0.hit }.count
                Text(missed == 0 ? "Every word is there." : "\(missed) word\(missed == 1 ? "" : "s") missing — marked below.")
                    .font(.caption).foregroundColor(missed == 0 ? .green : .orange)
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(Array(lines.enumerated()), id: \.offset) { _, line in
                        line.reduce(Text("")) { acc, w in
                            acc + (w.hit ? Text(w.word + " ")
                                         : Text(w.word).foregroundColor(.red).bold().underline() + Text(" "))
                        }
                    }
                }
                .font(.body)
                .accessibilityIdentifier("flashcards-answer")
                answerEnglish
            }
        }
    }

    // MARK: Occlusion

    private var labelIndex: Int? {
        entry.item.hasPrefix("l") ? Int(entry.item.dropFirst()) : nil
    }

    private var occlusion: some View {
        let labels = card.labels ?? []
        let one = labelIndex
        return VStack(alignment: .leading, spacing: 8) {
            kicker
            Text(card.prompt ?? (one != nil ? "Name the highlighted label" : "Name every hidden label"))
                .font(.headline)
                .accessibilityIdentifier("flashcards-prompt")
            promptEnglish
            if let path = card.image {
                ZoomableContainer {
                    FlashPicture(setId: entry.setId, path: path) { size in
                        OcclusionBoxes(labels: labels, size: size, target: one,
                                       revealed: one.map { revealed ? [$0] : [] } ?? opened,
                                       accent: accent,
                                       onTap: one == nil ? { i in opened.insert(i) } : nil)
                    }
                }
                .frame(maxHeight: .infinity)
                .clipped()
            }
            if let one, revealed, one < labels.count {
                Text(labels[one].text).font(.title3.weight(.semibold)).foregroundColor(accent)
                    .accessibilityIdentifier("flashcards-answer")
                answerEnglish
            }
            if one == nil && !allOpen {
                Text("Tap a box to reveal it — \(opened.count) of \(labels.count) shown.")
                    .font(.caption).foregroundColor(.secondary)
            }
            if showsNotes { notes }
        }
        .padding(.horizontal, 16)
        .padding(.top, 12)
    }

    private var allOpen: Bool { opened.count >= (card.labels?.count ?? 0) }

    // MARK: English (`en`)

    /// Under the question: the folded "English" toggle on the left when the
    /// card has English (opened with a tap, and left open for the next card),
    /// and a copy button on the right (Gil, 2026-10-12: "a copy option … at
    /// the bottom right").
    private var promptEnglish: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 4) {
                if englishPrompt != nil {
                    Button {
                        withAnimation(.easeInOut(duration: 0.15)) { englishOpen.toggle() }
                    } label: {
                        HStack(spacing: 4) {
                            Image(systemName: englishOpen ? "chevron.down" : "chevron.right")
                                .font(.caption2.weight(.semibold))
                            Text("English").font(.caption.weight(.semibold))
                        }
                        .foregroundColor(.secondary)
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("flashcards-english-toggle")
                }
                Spacer()
                CopyButton(text: Self.promptLine(entry))
                    .accessibilityIdentifier("flashcards-copy-prompt")
            }
            .environment(\.layoutDirection, .leftToRight)
            if englishOpen, let e = englishPrompt {
                EnglishLine(text: e, prominent: true)
                    .accessibilityIdentifier("flashcards-english-prompt")
            }
        }
    }

    /// Under the answer: its English, and a copy button at the bottom right.
    private var answerEnglish: some View {
        HStack(alignment: .top, spacing: 8) {
            if let e = englishAnswer {
                EnglishLine(text: e, prominent: true)
                    .accessibilityIdentifier("flashcards-english-answer")
            } else {
                Spacer()
            }
            CopyButton(text: Self.answerLine(entry))
                .accessibilityIdentifier("flashcards-copy-answer")
        }
        .environment(\.layoutDirection, .leftToRight)
    }

    private var englishPrompt: String? {
        guard let e = card.en else { return nil }
        let rev = entry.item == "rev"
        switch card.type {
        case "basic", "image": return rev ? e.back : e.front
        case "cloze":
            // An English sentence without gaps would give the answer away.
            guard let t = e.text, !Cloze.gaps(t).isEmpty else { return nil }
            return Cloze.masked(t, hide: clozeIndex)
        case "mc": return e.question
        case "order", "occlusion": return e.prompt
        case "typed": return e.front
        default: return nil
        }
    }

    private var englishAnswer: String? {
        guard let e = card.en else { return nil }
        let rev = entry.item == "rev"
        switch card.type {
        case "basic": return rev ? e.front : e.back
        case "image": return rev ? nil : e.back
        case "cloze":
            guard let t = e.text else { return nil }
            return Cloze.masked(t, hide: clozeIndex, reveal: true)
        case "typed": return e.answer
        case "occlusion":
            guard let i = labelIndex, let l = e.labels, i < l.count else { return nil }
            return l[i]
        default: return nil
        }
    }

    /// A choice's English: the same place in `en.choices` as it holds in the card's.
    private func english(of choice: String, in own: [String]?, _ en: [String]?) -> String? {
        guard let own, let en, let i = own.firstIndex(of: choice), i < en.count else { return nil }
        return en[i]
    }

    // MARK: Controls

    @ViewBuilder private var controls: some View {
        switch card.type {
        case "mc":
            if picked != nil {
                continueButton(right: picked == card.answer)
            } else {
                Text("Pick one").font(.subheadline).foregroundColor(.secondary)
                    .frame(maxWidth: .infinity, minHeight: 44)
            }
        case "order":
            if checked {
                continueButton(right: placed == Array(0..<(card.steps?.count ?? 0)))
            } else {
                HStack {
                    Button("Undo") {
                        if let last = placed.popLast() { pool.append(last) }
                    }
                    .disabled(placed.isEmpty)
                    .buttonStyle(.bordered)
                    Spacer()
                    Button("Check") { checked = true }
                        .disabled(!pool.isEmpty)
                        .buttonStyle(.borderedProminent)
                        .tint(accent)
                        .accessibilityIdentifier("flashcards-check")
                }
            }
        case "occlusion" where labelIndex == nil:
            if allOpen || revealed {
                gradeButtons
            } else {
                Button {
                    opened = Set(0..<(card.labels?.count ?? 0))
                    revealed = true
                } label: { Text("Reveal all").frame(maxWidth: .infinity, minHeight: 36) }
                .buttonStyle(.borderedProminent).tint(accent)
                .accessibilityIdentifier("flashcards-reveal")
            }
        default:
            if revealed {
                gradeButtons
            } else {
                Button { revealed = true } label: {
                    Text(card.type == "typed" ? "Check" : "Show answer")
                        .frame(maxWidth: .infinity, minHeight: 36)
                }
                .buttonStyle(.borderedProminent).tint(accent)
                .accessibilityIdentifier("flashcards-reveal")
            }
        }
    }

    private func continueButton(right: Bool) -> some View {
        Button {
            onAnswer(right ? 3 : 1, right)
        } label: {
            HStack {
                Image(systemName: right ? "checkmark.circle.fill" : "xmark.circle.fill")
                Text(right ? "Right — Continue" : "Not quite — Continue")
            }
            .frame(maxWidth: .infinity, minHeight: 36)
        }
        .buttonStyle(.borderedProminent)
        .tint(right ? .green : .red)
        .accessibilityIdentifier("flashcards-continue")
    }

    private var gradeButtons: some View {
        let p = FlashcardStore.shared.progress(setId: entry.setId, cardId: card.id, item: entry.item)
            ?? entry.progress
        let grades: [(Int, String, Color)] = [(1, "Again", .red), (2, "Hard", .orange),
                                              (3, "Good", accent), (4, "Easy", .green)]
        return HStack(spacing: 8) {
            ForEach(grades, id: \.0) { g, name, color in
                Button { onAnswer(g, g >= 2) } label: {
                    VStack(spacing: 2) {
                        Text(name).font(.subheadline.weight(.semibold))
                        if mode != .exam {
                            Text(FSRS.hint(p, grade: g)).font(.caption2).monospacedDigit().opacity(0.8)
                        }
                    }
                    .frame(maxWidth: .infinity, minHeight: 40)
                }
                .buttonStyle(.bordered)
                .tint(color)
                .accessibilityIdentifier("flashcards-grade-\(name.lowercased())")
            }
        }
    }

    // MARK: Lines for the summary

    static func promptLine(_ e: StudyItem) -> String {
        let c = e.card
        switch c.type {
        case "basic": return (e.item == "rev" ? c.back : c.front) ?? ""
        case "image": return e.item == "rev" ? (c.back ?? "") : (c.front ?? "Picture")
        case "cloze": return Cloze.masked(c.text ?? "", hide: Int(e.item.dropFirst()) ?? 0)
        case "mc": return c.question ?? ""
        case "order": return c.prompt ?? "Order"
        case "typed": return c.front ?? ""
        case "occlusion": return c.prompt ?? "Labelled picture"
        default: return c.title
        }
    }

    static func answerLine(_ e: StudyItem) -> String {
        let c = e.card
        switch c.type {
        case "basic": return (e.item == "rev" ? c.front : c.back) ?? ""
        case "image": return e.item == "rev" ? "the picture" : (c.back ?? "")
        case "cloze":
            let gaps = Cloze.gaps(c.text ?? "")
            let i = Int(e.item.dropFirst()) ?? 0
            return i < gaps.count ? gaps[i] : ""
        case "mc": return c.answer ?? ""
        case "order": return (c.steps ?? []).joined(separator: " → ")
        case "typed": return c.answer ?? ""
        case "occlusion":
            let labels = c.labels ?? []
            if e.item.hasPrefix("l"), let i = Int(e.item.dropFirst()), i < labels.count { return labels[i].text }
            return labels.map(\.text).joined(separator: ", ")
        default: return ""
        }
    }
}

/// One line of English under Hebrew (or any right-to-left text): always
/// left-to-right, quieter than the card's own words.
struct EnglishLine: View {
    let text: String
    var prominent = false

    var body: some View {
        Text(text)
            .font(prominent ? .body : .footnote)
            .foregroundColor(.secondary)
            .multilineTextAlignment(.leading)
            .frame(maxWidth: .infinity, alignment: .leading)
            .environment(\.layoutDirection, .leftToRight)
    }
}

/// Copies a card's own words, to paste into a translator or a note. Shows a
/// tick for a moment so a tap is seen to have done something.
struct CopyButton: View {
    let text: String
    @State private var copied = false

    var body: some View {
        Button {
            UIPasteboard.general.string = text
            copied = true
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) { copied = false }
        } label: {
            Image(systemName: copied ? "checkmark" : "doc.on.doc")
                .font(.footnote)
                .foregroundColor(copied ? .green : .secondary)
                .frame(width: 32, height: 28)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(text.isEmpty)
        .accessibilityLabel(copied ? "Copied" : "Copy")
    }
}
