// swift-tools-version: 5.8
// The swift-tools-version declares the minimum version of Swift required to build this package.

import PackageDescription

let package = Package(
    name: "CorteonOverlay",
    platforms: [
        .macOS(.v13)
    ],
    products: [
        .executable(
            name: "CorteonOverlay",
            targets: ["CorteonOverlay"]
        )
    ],
    dependencies: [],
    targets: [
        .executableTarget(
            name: "CorteonOverlay",
            dependencies: [],
            path: "Sources/CorteonOverlay"
        )
    ]
)
