// swift-tools-version:5.9
// Anne.app: the window and menus (main.swift) and the speech part (Speech.swift, WhisperKit). Built by build.sh.
import PackageDescription

let package = Package(
    name: "Anne",
    platforms: [.macOS("14.2")],
    dependencies: [.package(url: "https://github.com/argmaxinc/WhisperKit.git", from: "0.9.0")],
    targets: [.executableTarget(name: "Anne", dependencies: [.product(name: "WhisperKit", package: "WhisperKit")], path: "Sources/Anne")]
)
