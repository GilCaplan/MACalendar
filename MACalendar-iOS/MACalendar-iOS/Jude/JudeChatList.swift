import SwiftUI

/// Past conversations, as a sheet.
///
/// Jude's own web UI keeps this as a permanent sidebar. A phone has no room
/// for one, and the choice made here is that the answer gets the whole screen
/// — history is something you reach for occasionally, so it is a toolbar
/// button away rather than permanently costing a third of the width.
///
/// There is no offline copy of this list, deliberately. The conversations live
/// on the Mac beside the corpus that produced them; a cached list of titles
/// you cannot open is a menu for a closed kitchen.
struct JudeChatList: View {
    let currentChatId: String?
    let onOpen: (JudeChatSummary) -> Void
    let onNew: () -> Void

    @EnvironmentObject var api: APIClient
    @EnvironmentObject var settings: AppSettings
    @Environment(\.dismiss) private var dismiss

    @State private var chats: [JudeChatSummary] = []
    @State private var loading = true

    var body: some View {
        NavigationView {
            Group {
                if loading {
                    ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if chats.isEmpty {
                    empty
                } else {
                    list
                }
            }
            .navigationTitle("Conversations")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button("Close") { dismiss() }
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button {
                        onNew()
                        dismiss()
                    } label: { Image(systemName: "square.and.pencil") }
                        .accessibilityLabel("New conversation")
                }
            }
        }
        .task { await reload() }
    }

    private var list: some View {
        List {
            ForEach(chats) { chat in
                Button {
                    onOpen(chat)
                    dismiss()
                } label: {
                    HStack(spacing: 8) {
                        if chat.id == currentChatId {
                            Circle().fill(settings.accentColor).frame(width: 6, height: 6)
                        }
                        VStack(alignment: .leading, spacing: 2) {
                            Text(chat.title.isEmpty ? "Untitled" : chat.title)
                                .font(.subheadline)
                                .lineLimit(2)
                                .foregroundColor(.primary)
                            if !chat.createdAt.isEmpty {
                                Text(chat.createdAt)
                                    .font(.caption2).foregroundColor(.secondary)
                            }
                        }
                        Spacer()
                        if !chat.modeGlyph.isEmpty { Text(chat.modeGlyph).font(.caption) }
                    }
                }
            }
            .onDelete(perform: delete)
        }
        .listStyle(.plain)
        .refreshable { await reload() }
    }

    private var empty: some View {
        VStack(spacing: 10) {
            Image(systemName: "text.book.closed")
                .font(.system(size: 34)).foregroundColor(.secondary)
            Text("No conversations yet").font(.headline)
            Text("Anything you ask Jude is kept on the Mac, so you can come back to it.")
                .font(.footnote).foregroundColor(.secondary)
                .multilineTextAlignment(.center).padding(.horizontal, 32)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func reload() async {
        loading = true
        chats = await api.judeChats()
        loading = false
    }

    /// Delete on the Mac first, then locally — and if the Mac refuses, put the
    /// row back by reloading. The rows are not a local list with a sync behind
    /// it; the Mac's copy IS the list, so a row that disappears here while
    /// surviving there is a lie the next refresh would contradict.
    private func delete(at offsets: IndexSet) {
        let doomed = offsets.map { chats[$0] }
        chats.remove(atOffsets: offsets)
        Task {
            for chat in doomed {
                do { try await api.judeDeleteChat(chat.id) }
                catch { await reload(); return }
            }
        }
    }
}
