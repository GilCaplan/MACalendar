import SwiftUI
import UIKit

/// A card's picture, from the phone's cache — fetched from the Mac only if the
/// set's download has not reached it yet. Says so in a sentence when neither
/// has it, rather than drawing an empty frame.
struct FlashPicture<Overlay: View>: View {
    @EnvironmentObject var api: APIClient
    let setId: Int
    let path: String
    var overlay: (CGSize) -> Overlay

    @State private var image: UIImage?
    @State private var tried = false

    init(setId: Int, path: String, @ViewBuilder overlay: @escaping (CGSize) -> Overlay) {
        self.setId = setId
        self.path = path
        self.overlay = overlay
    }

    var body: some View {
        Group {
            if let image {
                Image(uiImage: image)
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    // The overlay is laid on the FITTED picture, so a box in
                    // percent lands on the same spot at any size or zoom.
                    .overlay(GeometryReader { geo in overlay(geo.size) })
            } else if tried {
                Text("This picture isn't on the phone yet — open the tab once while your Mac is reachable to download it.")
                    .font(.footnote)
                    .foregroundColor(.secondary)
                    .frame(maxWidth: .infinity, minHeight: 120)
                    .background(Color.secondary.opacity(0.1))
            } else {
                ProgressView().frame(maxWidth: .infinity, minHeight: 120)
            }
        }
        .task(id: "\(setId)/\(path)") {
            image = await FlashcardStore.shared.loadImage(setId: setId, path: path, api: api)
            tried = true
        }
    }
}

extension FlashPicture where Overlay == EmptyView {
    init(setId: Int, path: String) {
        self.init(setId: setId, path: path) { _ in EmptyView() }
    }
}

/// Pinch to zoom and scroll — for the tall map with forty labels on it.
struct ZoomableContainer<Content: View>: View {
    @ViewBuilder var content: () -> Content
    @State private var scale: CGFloat = 1
    @GestureState private var pinch: CGFloat = 1

    var body: some View {
        GeometryReader { geo in
            ScrollView([.horizontal, .vertical], showsIndicators: false) {
                content()
                    .frame(width: geo.size.width * scale * pinch)
                    .frame(minHeight: geo.size.height)
            }
            .simultaneousGesture(
                MagnificationGesture()
                    .updating($pinch) { value, state, _ in state = value }
                    .onEnded { value in scale = min(5, max(1, scale * value)) }
            )
            .overlay(alignment: .bottomTrailing) {
                if scale > 1 {
                    Button { withAnimation { scale = 1 } } label: {
                        Image(systemName: "arrow.down.right.and.arrow.up.left")
                            .padding(8)
                            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: Theme.radiusSM))
                    }
                    .padding(8)
                    .accessibilityLabel("Fit picture")
                }
            }
        }
    }
}

/// The boxes of an occlusion card over its picture.
///
/// - `target`: the one label being asked (one_at_a_time), drawn in the accent.
/// - `revealed`: labels whose text is showing.
/// - `onTap`: tapping a box (all_at_once reveals it).
struct OcclusionBoxes: View {
    let labels: [FlashLabel]
    let size: CGSize
    var target: Int?
    var revealed: Set<Int>
    var accent: Color
    var onTap: ((Int) -> Void)?

    var body: some View {
        ZStack(alignment: .topLeading) {
            ForEach(Array(labels.enumerated()), id: \.offset) { i, label in
                let r = label.rect
                let frame = CGRect(x: r.minX * size.width, y: r.minY * size.height,
                                   width: r.width * size.width, height: r.height * size.height)
                let open = revealed.contains(i)
                ZStack {
                    Rectangle()
                        .fill(open ? Color(.systemBackground).opacity(0.9)
                                   : (i == target ? accent : Color(.systemGray)))
                    Rectangle()
                        .stroke(i == target ? accent : Color.primary.opacity(0.5), lineWidth: i == target ? 2 : 1)
                    if open {
                        Text(label.text)
                            .font(.system(size: max(8, min(14, frame.height * 0.7))))
                            .minimumScaleFactor(0.4)
                            .lineLimit(1)
                            .foregroundColor(.primary)
                            .padding(.horizontal, 1)
                    }
                }
                .frame(width: max(frame.width, 6), height: max(frame.height, 6))
                .offset(x: frame.minX, y: frame.minY)
                .contentShape(Rectangle())
                .onTapGesture { onTap?(i) }
                .accessibilityElement()
                .accessibilityLabel(open ? label.text : "Hidden label \(i + 1)")
                .accessibilityAddTraits(onTap == nil ? [] : .isButton)
            }
        }
        .frame(width: size.width, height: size.height, alignment: .topLeading)
        // Boxes are measured from the picture's top-left whatever the language.
        .environment(\.layoutDirection, .leftToRight)
    }
}
