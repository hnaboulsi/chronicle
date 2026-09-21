import OSLog

private let chronicleLogger = Logger(
    subsystem: "com.naboulsi.chronicle",
    category: "app"
)

func log(_ message: String) {
    chronicleLogger.info("\(message, privacy: .public)")
}
