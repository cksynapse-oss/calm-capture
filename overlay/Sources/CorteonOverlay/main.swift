import AppKit

// Set accessory activation policy so we don't appear in the Dock
NSApplication.shared.setActivationPolicy(.accessory)

let delegate = AppDelegate()
NSApplication.shared.delegate = delegate

NSApplication.shared.run()
