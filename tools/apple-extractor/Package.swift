// swift-tools-version: 6.2
import PackageDescription

let package = Package(
    name: "apple-extractor",
    platforms: [.macOS(.v26)],
    targets: [
        .executableTarget(name: "apple-extractor", path: "Sources"),
    ]
)
