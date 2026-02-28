import SwiftUI

struct ChatView: View {
    @EnvironmentObject private var model: NativeAppModel
    @State private var inputText = ""
    @State private var isSending = false

    var body: some View {
        VStack(spacing: 0) {
            if model.chatTurns.isEmpty {
                emptyState
            } else {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(spacing: Spacing.lg) {
                            ForEach(Array(model.chatTurns.enumerated()), id: \.offset) { index, turn in
                                VStack(spacing: Spacing.xs) {
                                    Text(turn.time)
                                        .font(.caption2)
                                        .foregroundStyle(.tertiary)
                                        .frame(maxWidth: .infinity)
                                    ChatBubble(text: turn.user, isUser: true)
                                    ChatBubble(text: turn.reply, isUser: false)
                                }
                                .id(index)
                            }
                        }
                        .padding(Spacing.lg)
                    }
                    .onAppear {
                        proxy.scrollTo(model.chatTurns.count - 1, anchor: .bottom)
                    }
                    .onChange(of: model.chatTurns.count) { _ in
                        withAnimation(.easeOut(duration: 0.2)) {
                            proxy.scrollTo(model.chatTurns.count - 1, anchor: .bottom)
                        }
                    }
                }
            }

            Divider()

            HStack(alignment: .center, spacing: Spacing.sm) {
                TextField("Reply to Vero...", text: $inputText)
                    .textFieldStyle(.plain)
                    .padding(.horizontal, Spacing.md)
                    .padding(.vertical, Spacing.sm)
                    .background(Color(NSColor.controlBackgroundColor), in: RoundedRectangle(cornerRadius: 10))
                    .onSubmit { sendReply() }

                Button(action: sendReply) {
                    Image(systemName: isSending ? "clock.fill" : "arrow.up.circle.fill")
                        .font(.system(size: 26))
                        .foregroundStyle(canSend ? Color.indigo : Color.secondary.opacity(0.4))
                }
                .buttonStyle(.plain)
                .disabled(!canSend)
            }
            .padding(Spacing.md)
        }
        .navigationTitle("Chat")
    }

    private var emptyState: some View {
        VStack {
            Spacer()
            VStack(spacing: Spacing.sm) {
                Image(systemName: "bubble.left.and.bubble.right")
                    .font(.system(size: 32))
                    .foregroundStyle(.secondary)
                Text("No conversations yet")
                    .foregroundStyle(.secondary)
                    .font(.subheadline)
            }
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var canSend: Bool {
        !inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !isSending
    }

    private func sendReply() {
        let text = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !isSending else { return }
        inputText = ""
        isSending = true
        Task {
            await model.sendReply(text)
            isSending = false
        }
    }
}
