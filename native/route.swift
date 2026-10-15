// route: while secondchair runs, play the system output on the user's real output device
// and on BlackHole 2ch at the same time, so the meeting audio can be captured.
//
// The audio settings stay the user's own: on start this creates a temporary multi-output
// device (real device + BlackHole) and makes it the default output; on exit it restores the
// real device and deletes the temporary one. It follows the user while running: headphones
// plugged or unplugged, AirPods connected, another output picked in the menu bar.
//
// Exits cleanly on SIGINT/SIGTERM and when its parent process dies. A device left behind by
// a crash is deleted on the next start.
//
// Build: swiftc -O native/route.swift -o native/route
// Stdout, one line per change: "route <headphones|speakers> <device name>", "restored <name>"

import CoreAudio
import Foundation

let system = AudioObjectID(kAudioObjectSystemObject)
let routeUIDPrefix = "secondchair.route."
let captureUID = "BlackHole2ch_UID"

// MARK: Core Audio property helpers

func address(_ selector: AudioObjectPropertySelector,
             _ scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal) -> AudioObjectPropertyAddress {
    AudioObjectPropertyAddress(mSelector: selector, mScope: scope, mElement: kAudioObjectPropertyElementMain)
}

func string(_ id: AudioObjectID, _ selector: AudioObjectPropertySelector) -> String {
    var a = address(selector)
    var size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
    var value: Unmanaged<CFString>?
    guard AudioObjectGetPropertyData(id, &a, 0, nil, &size, &value) == noErr, let value else { return "" }
    return value.takeRetainedValue() as String
}

func uint32(_ id: AudioObjectID, _ selector: AudioObjectPropertySelector,
            _ scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal) -> UInt32? {
    var a = address(selector, scope)
    var size = UInt32(4)
    var value: UInt32 = 0
    return AudioObjectGetPropertyData(id, &a, 0, nil, &size, &value) == noErr ? value : nil
}

func name(_ id: AudioObjectID) -> String { string(id, kAudioObjectPropertyName) }
func uid(_ id: AudioObjectID) -> String { string(id, kAudioDevicePropertyDeviceUID) }

func outputChannels(_ id: AudioObjectID) -> Int {
    var a = address(kAudioDevicePropertyStreamConfiguration, kAudioObjectPropertyScopeOutput)
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(id, &a, 0, nil, &size) == noErr, size > 0 else { return 0 }
    let raw = UnsafeMutableRawPointer.allocate(byteCount: Int(size), alignment: 16)
    defer { raw.deallocate() }
    guard AudioObjectGetPropertyData(id, &a, 0, nil, &size, raw) == noErr else { return 0 }
    let list = UnsafeMutableAudioBufferListPointer(raw.assumingMemoryBound(to: AudioBufferList.self))
    return list.reduce(0) { $0 + Int($1.mNumberChannels) }
}

func devices() -> [AudioObjectID] {
    var a = address(kAudioHardwarePropertyDevices)
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(system, &a, 0, nil, &size) == noErr else { return [] }
    var ids = [AudioObjectID](repeating: 0, count: Int(size) / MemoryLayout<AudioObjectID>.size)
    guard AudioObjectGetPropertyData(system, &a, 0, nil, &size, &ids) == noErr else { return [] }
    return ids
}

func defaultOutput() -> AudioObjectID {
    uint32(system, kAudioHardwarePropertyDefaultOutputDevice) ?? AudioObjectID(kAudioObjectUnknown)
}

@discardableResult
func setDefaultOutput(_ id: AudioObjectID) -> Bool {
    var a = address(kAudioHardwarePropertyDefaultOutputDevice)
    var value = id
    return AudioObjectSetPropertyData(system, &a, 0, nil, UInt32(MemoryLayout<AudioObjectID>.size), &value) == noErr
}

// MARK: Classifying devices

/// A device a person can listen on: has outputs and is neither virtual (BlackHole, Camo,
/// Teams loopback) nor an aggregate (our route, or a Multi-Output Device made by hand).
func isReal(_ id: AudioObjectID) -> Bool {
    guard outputChannels(id) > 0, let transport = uint32(id, kAudioDevicePropertyTransportType) else { return false }
    return ![kAudioDeviceTransportTypeVirtual, kAudioDeviceTransportTypeAggregate,
             kAudioDeviceTransportTypeAutoAggregate].contains(transport)
}

/// "speakers" when the room hears it (and so does the mic), else "headphones".
/// Built-in output reports a data source: 'ispk' speakers, 'hdpn' headphone jack.
func kind(_ id: AudioObjectID) -> String {
    let transport = uint32(id, kAudioDevicePropertyTransportType)
    if transport == kAudioDeviceTransportTypeHDMI || transport == kAudioDeviceTransportTypeDisplayPort {
        return "speakers"
    }
    if transport == kAudioDeviceTransportTypeBuiltIn {
        let headphoneJack: UInt32 = 0x6864_706E  // 'hdpn'
        return uint32(id, kAudioDevicePropertyDataSource, kAudioObjectPropertyScopeOutput) == headphoneJack
            ? "headphones" : "speakers"
    }
    return "headphones"  // Bluetooth and USB outputs are almost always headsets
}

/// What to use when there is no clear choice: built-in headphones, then built-in speakers,
/// then any real device.
func fallbackReal() -> AudioObjectID? {
    let real = devices().filter(isReal)
    let builtIn = real.filter { uint32($0, kAudioDevicePropertyTransportType) == kAudioDeviceTransportTypeBuiltIn }
    return builtIn.first { kind($0) == "headphones" } ?? builtIn.first ?? real.first
}

// MARK: The temporary route device

func createRoute(for real: AudioObjectID) -> AudioObjectID? {
    let realUID = uid(real)
    let description: [String: Any] = [
        kAudioAggregateDeviceNameKey: "secondchair (\(name(real)))",
        kAudioAggregateDeviceUIDKey: routeUIDPrefix + UUID().uuidString,
        kAudioAggregateDeviceIsPrivateKey: false,  // public, so meeting apps can play into it
        kAudioAggregateDeviceIsStackedKey: true,  // multi-output: every sub-device plays everything
        kAudioAggregateDeviceMainSubDeviceKey: realUID,  // the real device sets the clock
        kAudioAggregateDeviceSubDeviceListKey: [
            [kAudioSubDeviceUIDKey: realUID],
            [kAudioSubDeviceUIDKey: captureUID, kAudioSubDeviceDriftCompensationKey: 1],
        ],
    ]
    var id = AudioObjectID(kAudioObjectUnknown)
    let status = AudioHardwareCreateAggregateDevice(description as CFDictionary, &id)
    guard status == noErr else {
        FileHandle.standardError.write("route: could not create device (OSStatus \(status))\n".data(using: .utf8)!)
        return nil
    }
    Thread.sleep(forTimeInterval: 0.3)  // let Core Audio publish it before it becomes the default
    return id
}

func deleteLeftovers() {
    for id in devices() where uid(id).hasPrefix(routeUIDPrefix) {
        AudioHardwareDestroyAggregateDevice(id)
    }
}

func report(_ line: String) {
    print(line)
    fflush(stdout)
}

// MARK: State and reconciliation

guard devices().contains(where: { uid($0) == captureUID }) else {
    FileHandle.standardError.write("route: BlackHole 2ch is not installed\n".data(using: .utf8)!)
    exit(1)
}

let startDefault = defaultOutput()
deleteLeftovers()
guard var real = isReal(startDefault) ? startDefault : fallbackReal(),
      var route = createRoute(for: real) else {
    FileHandle.standardError.write("route: no usable output device\n".data(using: .utf8)!)
    exit(1)
}
setDefaultOutput(route)
report("route \(kind(real)) \(name(real))")

var known = Set(devices())
var pending: DispatchWorkItem?

func reconcile() {
    let now = Set(devices())
    let added = now.subtracting(known)
    known = now
    let current = defaultOutput()

    var next = real
    if current != route && isReal(current) {
        next = current  // macOS switched (AirPods connected) or the user picked a device
    } else if !now.contains(real) || !isReal(real) {
        next = fallbackReal() ?? real  // our device went away (headphones unplugged)
    } else if kind(real) == "speakers",
              let plugged = added.first(where: { isReal($0) && kind($0) == "headphones" }) {
        next = plugged  // headphones plugged in while playing on speakers
    }

    if next != real, let newRoute = createRoute(for: next) {
        let old = route
        setDefaultOutput(newRoute)
        AudioHardwareDestroyAggregateDevice(old)
        real = next
        route = newRoute
        known = Set(devices())
        report("route \(kind(real)) \(name(real))")
    } else if defaultOutput() != route {
        setDefaultOutput(route)  // something else took the default (e.g. a hand-made aggregate)
    }
}

func scheduleReconcile() {
    pending?.cancel()
    let work = DispatchWorkItem { reconcile() }
    pending = work
    DispatchQueue.main.asyncAfter(deadline: .now() + 0.3, execute: work)  // coalesce bursts of events
}

for selector in [kAudioHardwarePropertyDevices, kAudioHardwarePropertyDefaultOutputDevice] {
    var a = address(selector)
    AudioObjectAddPropertyListenerBlock(system, &a, DispatchQueue.main) { _, _ in scheduleReconcile() }
}

// MARK: Exit

func restoreAndExit() -> Never {
    let restore = devices().contains(real) && isReal(real) ? real : (fallbackReal() ?? real)
    setDefaultOutput(restore)
    AudioHardwareDestroyAggregateDevice(route)
    report("restored \(name(restore))")
    exit(0)
}

var keepAlive: [DispatchSourceProtocol] = []
for sig in [SIGINT, SIGTERM, SIGHUP] {
    signal(sig, SIG_IGN)
    let source = DispatchSource.makeSignalSource(signal: sig, queue: .main)
    source.setEventHandler { restoreAndExit() }
    source.resume()
    keepAlive.append(source)
}

// If secondchair dies without stopping us, we are re-parented to launchd (pid 1).
let parent = getppid()
let watchdog = DispatchSource.makeTimerSource(queue: .main)
watchdog.schedule(deadline: .now() + 1, repeating: 1)
watchdog.setEventHandler { if getppid() != parent { restoreAndExit() } }
watchdog.resume()
keepAlive.append(watchdog)

dispatchMain()
