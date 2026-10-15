// audiotap: capture all system audio with a Core Audio process tap (macOS 14.2+).
//
// Writes 32-bit float PCM to stdout and status lines to stderr.
// Does not change any audio device: the tap reads app audio before it reaches the output,
// and the aggregate device that carries it is private to this process.
//
// Build: swiftc -O native/audiotap.swift -o native/audiotap
// Run:   native/audiotap > /dev/null        (prints levels to stderr)

import AudioToolbox
import CoreAudio
import Foundation

func fail(_ what: String, _ status: OSStatus) -> Never {
    FileHandle.standardError.write("audiotap: \(what) failed (OSStatus \(status))\n".data(using: .utf8)!)
    exit(1)
}

func say(_ line: String) {
    FileHandle.standardError.write((line + "\n").data(using: .utf8)!)
}

// 1. Tap: every process, mixed down to stereo. The meeting app keeps playing normally.
let tapDescription = CATapDescription(stereoGlobalTapButExcludeProcesses: [])
tapDescription.uuid = UUID()
tapDescription.name = "secondchair"
tapDescription.isPrivate = true
tapDescription.muteBehavior = .unmuted

var tapID = AudioObjectID(kAudioObjectUnknown)
var status = AudioHardwareCreateProcessTap(tapDescription, &tapID)
guard status == noErr else { fail("AudioHardwareCreateProcessTap", status) }

var formatAddress = AudioObjectPropertyAddress(
    mSelector: kAudioTapPropertyFormat,
    mScope: kAudioObjectPropertyScopeGlobal,
    mElement: kAudioObjectPropertyElementMain
)
var format = AudioStreamBasicDescription()
var formatSize = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
status = AudioObjectGetPropertyData(tapID, &formatAddress, 0, nil, &formatSize, &format)
guard status == noErr else { fail("reading tap format", status) }
say("format rate=\(Int(format.mSampleRate)) channels=\(format.mChannelsPerFrame) bits=\(format.mBitsPerChannel)")

// 2. Private aggregate device holding only the tap. No output sub-device, so the
//    capture does not depend on which speakers or headphones are connected.
let aggregate: [String: Any] = [
    kAudioAggregateDeviceNameKey: "secondchair-tap",
    kAudioAggregateDeviceUIDKey: UUID().uuidString,
    kAudioAggregateDeviceIsPrivateKey: true,
    kAudioAggregateDeviceIsStackedKey: false,
    kAudioAggregateDeviceTapAutoStartKey: true,
    kAudioAggregateDeviceTapListKey: [
        [kAudioSubTapUIDKey: tapDescription.uuid.uuidString, kAudioSubTapDriftCompensationKey: true]
    ],
]
var aggregateID = AudioObjectID(kAudioObjectUnknown)
status = AudioHardwareCreateAggregateDevice(aggregate as CFDictionary, &aggregateID)
guard status == noErr else { fail("AudioHardwareCreateAggregateDevice", status) }

// 3. Read buffers: write PCM to stdout, keep a running level for the status line.
let stdout = FileHandle.standardOutput
let levelLock = NSLock()
var sumSquares = 0.0
var sampleCount = 0

var ioProcID: AudioDeviceIOProcID?
status = AudioDeviceCreateIOProcIDWithBlock(&ioProcID, aggregateID, nil) { _, inputData, _, _, _ in
    let buffers = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: inputData))
    for buffer in buffers {
        guard let data = buffer.mData, buffer.mDataByteSize > 0 else { continue }
        let count = Int(buffer.mDataByteSize) / MemoryLayout<Float>.size
        let samples = data.bindMemory(to: Float.self, capacity: count)
        var squares = 0.0
        for i in 0..<count { squares += Double(samples[i] * samples[i]) }
        levelLock.lock(); sumSquares += squares; sampleCount += count; levelLock.unlock()
        stdout.write(Data(bytes: data, count: Int(buffer.mDataByteSize)))
    }
}
guard status == noErr, let ioProcID else { fail("AudioDeviceCreateIOProcIDWithBlock", status) }
status = AudioDeviceStart(aggregateID, ioProcID)
guard status == noErr else { fail("AudioDeviceStart", status) }
say("capturing (Ctrl+C to stop)")

func cleanUp() {
    AudioDeviceStop(aggregateID, ioProcID)
    AudioDeviceDestroyIOProcID(aggregateID, ioProcID)
    AudioHardwareDestroyAggregateDevice(aggregateID)
    AudioHardwareDestroyProcessTap(tapID)
}

for sig in [SIGINT, SIGTERM] {
    signal(sig, SIG_IGN)
    let source = DispatchSource.makeSignalSource(signal: sig, queue: .main)
    source.setEventHandler { cleanUp(); say("stopped"); exit(0) }
    source.resume()
    _ = Unmanaged.passRetained(source)  // keep the handler alive
}

// Status line every half second: level in dBFS, or "silence".
let timer = DispatchSource.makeTimerSource(queue: .main)
timer.schedule(deadline: .now() + 0.5, repeating: 0.5)
timer.setEventHandler {
    levelLock.lock()
    let rms = sampleCount > 0 ? (sumSquares / Double(sampleCount)).squareRoot() : 0
    let frames = sampleCount
    sumSquares = 0; sampleCount = 0
    levelLock.unlock()
    let level = rms > 0 ? String(format: "%.1f dBFS", 20 * log10(rms)) : "silence"
    say("level \(level)  samples \(frames)")
}
timer.resume()

dispatchMain()
