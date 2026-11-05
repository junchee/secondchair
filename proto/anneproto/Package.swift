// swift-tools-version:5.9
import PackageDescription
let package = Package(
    name: "proto",
    platforms: [.macOS("14.2")],
    dependencies: [.package(url: "https://github.com/argmaxinc/WhisperKit.git", from: "0.9.0")],
    targets: [.executableTarget(name: "proto", dependencies: [.product(name: "WhisperKit", package: "WhisperKit")])]
)
