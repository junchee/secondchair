// AnneProto: system audio (Core Audio process tap, no BlackHole) -> WhisperKit small -> lines in a window.
// Each line shows: audio seconds, Whisper seconds, delay from the end of speech, and the app's memory.
import AppKit
import AVFoundation
import AudioToolbox
import CoreAudio
import Foundation
import WhisperKit

let modelFolder = NSHomeDirectory() + "/AnneProto/model"
let logPath = NSHomeDirectory() + "/Library/Logs/AnneProto.log"
let maxLine = 4.0, pause = 0.2          // Anne's defaults
let speechLevel: Float = 0.006          // Anne's "Normal" level

func footprintMB() -> Int {
    var info = task_vm_info_data_t(); var count = mach_msg_type_number_t(MemoryLayout<task_vm_info_data_t>.size / MemoryLayout<integer_t>.size)
    let r = withUnsafeMutablePointer(to: &info) { $0.withMemoryRebound(to: integer_t.self, capacity: Int(count)) { task_info(mach_task_self_, task_flavor_t(TASK_VM_INFO), $0, &count) } }
    return r == KERN_SUCCESS ? Int(info.phys_footprint / 1_048_576) : -1
}

final class Audio {            // 16 kHz mono samples, appended by the tap's callback
    let lock = NSLock(); var samples: [Float] = []; var total = 0
    func add(_ chunk: [Float]) { lock.lock(); samples.append(contentsOf: chunk); total += chunk.count; lock.unlock() }
    func take(_ n: Int) -> [Float] { lock.lock(); defer { lock.unlock() }; let out = Array(samples.prefix(n)); samples.removeFirst(min(n, samples.count)); return out }
    var count: Int { lock.lock(); defer { lock.unlock() }; return samples.count }
    func tail(_ n: Int) -> [Float] { lock.lock(); defer { lock.unlock() }; return Array(samples.suffix(n)) }
}
let audio = Audio()      // system sound ("상대")
let micAudio = Audio()   // Jun's microphone ("나")

func startTap() -> String? {
    let desc = CATapDescription(stereoGlobalTapButExcludeProcesses: [])
    desc.uuid = UUID(); desc.name = "AnneProto"; desc.isPrivate = true; desc.muteBehavior = .unmuted
    var tapID = AudioObjectID(kAudioObjectUnknown)
    var st = AudioHardwareCreateProcessTap(desc, &tapID)
    if st != noErr { return "AudioHardwareCreateProcessTap failed (\(st))" }
    var addr = AudioObjectPropertyAddress(mSelector: kAudioTapPropertyFormat, mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
    var fmt = AudioStreamBasicDescription(); var size = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
    st = AudioObjectGetPropertyData(tapID, &addr, 0, nil, &size, &fmt)
    if st != noErr { return "tap format failed (\(st))" }
    let ratio = fmt.mSampleRate / 16000, channels = Int(fmt.mChannelsPerFrame)
    let agg: [String: Any] = [
        kAudioAggregateDeviceNameKey: "AnneProto-tap", kAudioAggregateDeviceUIDKey: UUID().uuidString,
        kAudioAggregateDeviceIsPrivateKey: true, kAudioAggregateDeviceIsStackedKey: false, kAudioAggregateDeviceTapAutoStartKey: true,
        kAudioAggregateDeviceTapListKey: [[kAudioSubTapUIDKey: desc.uuid.uuidString, kAudioSubTapDriftCompensationKey: true]]]
    var aggID = AudioObjectID(kAudioObjectUnknown)
    st = AudioHardwareCreateAggregateDevice(agg as CFDictionary, &aggID)
    if st != noErr { return "aggregate device failed (\(st))" }
    var proc: AudioDeviceIOProcID?
    var phase = 0.0
    st = AudioDeviceCreateIOProcIDWithBlock(&proc, aggID, nil) { _, input, _, _, _ in
        let bufs = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: input))
        guard let b = bufs.first, let data = b.mData else { return }
        let n = Int(b.mDataByteSize) / 4 / max(channels, 1)
        let p = data.bindMemory(to: Float.self, capacity: n * channels)
        var out: [Float] = []; out.reserveCapacity(Int(Double(n) / ratio) + 1)
        while Int(phase) < n {                       // nearest-sample downsampling, mono mix
            var s: Float = 0; for c in 0..<channels { s += p[Int(phase) * channels + c] }
            out.append(s / Float(channels)); phase += ratio
        }
        phase -= Double(n)
        audio.add(out)
    }
    if st != noErr { return "IOProc failed (\(st))" }
    st = AudioDeviceStart(aggID, proc)
    return st == noErr ? nil : "AudioDeviceStart failed (\(st))"
}


var micEngine: AVAudioEngine?
func startMic() -> String? {
    let engine = AVAudioEngine(); let input = engine.inputNode
    let inFmt = input.inputFormat(forBus: 0)
    guard inFmt.sampleRate > 0, let outFmt = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 16000, channels: 1, interleaved: false),
          let conv = AVAudioConverter(from: inFmt, to: outFmt) else { return "no microphone format" }
    input.installTap(onBus: 0, bufferSize: 4096, format: inFmt) { buf, _ in
        let cap = AVAudioFrameCount(Double(buf.frameLength) * 16000 / inFmt.sampleRate) + 16
        guard let out = AVAudioPCMBuffer(pcmFormat: outFmt, frameCapacity: cap) else { return }
        var fed = false
        conv.convert(to: out, error: nil) { _, status in if fed { status.pointee = .noDataNow; return nil }; fed = true; status.pointee = .haveData; return buf }
        if let p = out.floatChannelData?[0] { micAudio.add(Array(UnsafeBufferPointer(start: p, count: Int(out.frameLength)))) }
    }
    do { try engine.start() } catch { return "microphone start failed: \(error.localizedDescription)" }
    micEngine = engine
    return nil
}

// one Whisper at a time, even with two sources
actor Gate { var busy = false
    func enter() async { while busy { try? await Task.sleep(nanoseconds: 20_000_000) }; busy = true }
    func leave() { busy = false } }
let gate = Gate()

// ---- window ----
let app = NSApplication.shared; app.setActivationPolicy(.regular)
let window = NSWindow(contentRect: NSRect(x: 200, y: 200, width: 760, height: 520), styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
window.title = "AnneProto (WhisperKit small, no BlackHole)"
let scroll = NSScrollView(frame: window.contentView!.bounds); scroll.autoresizingMask = [.width, .height]; scroll.hasVerticalScroller = true
let text = NSTextView(frame: scroll.bounds); text.isEditable = false; text.font = .systemFont(ofSize: 15); text.autoresizingMask = [.width]
scroll.documentView = text; window.contentView!.addSubview(scroll); window.makeKeyAndOrderFront(nil); app.activate(ignoringOtherApps: true)

func show(_ s: String) {
    DispatchQueue.main.async {
        text.textStorage?.append(NSAttributedString(string: s + "\n", attributes: [.font: NSFont.systemFont(ofSize: 15), .foregroundColor: NSColor.textColor]))
        text.scrollToEndOfDocument(nil)
    }
    if let h = FileHandle(forWritingAtPath: logPath) ?? { FileManager.default.createFile(atPath: logPath, contents: nil); return FileHandle(forWritingAtPath: logPath) }() {
        h.seekToEndOfFile(); h.write((s + "\n").data(using: .utf8)!); h.closeFile()
    }
}

func saveWav(_ pcm: [Float], name: String) {      // keep each line's sound so another engine can read the same audio
    let dir = NSHomeDirectory() + "/AnneProto/lines"; try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
    var d = Data(); func u32(_ v: UInt32) { var x = v.littleEndian; d.append(Data(bytes: &x, count: 4)) }; func u16(_ v: UInt16) { var x = v.littleEndian; d.append(Data(bytes: &x, count: 2)) }
    d.append("RIFF".data(using: .ascii)!); u32(UInt32(36 + pcm.count * 2)); d.append("WAVEfmt ".data(using: .ascii)!); u32(16); u16(1); u16(1); u32(16000); u32(32000); u16(2); u16(16)
    d.append("data".data(using: .ascii)!); u32(UInt32(pcm.count * 2))
    for f in pcm { var v = Int16(max(-1, min(1, f)) * 32767).littleEndian; d.append(Data(bytes: &v, count: 2)) }
    try? d.write(to: URL(fileURLWithPath: dir + "/" + name + ".wav"))
}

func rms(_ a: ArraySlice<Float>) -> Float { a.isEmpty ? 0 : (a.reduce(0) { $0 + $1 * $1 } / Float(a.count)).squareRoot() }

func runStream(_ label: String, _ src: Audio, _ kit: WhisperKit, enabled: @escaping () -> Bool) async {
    var speechSamples = 0, quietSamples = 0, lines = 0
    while true {
        try? await Task.sleep(nanoseconds: 100_000_000)
        if !enabled() { _ = src.take(src.count); speechSamples = 0; quietSamples = 0; continue }
        let fresh = src.tail(1600)
        if rms(fresh[...]) > speechLevel { speechSamples += 1600; quietSamples = 0 } else { quietSamples += 1600 }
        let have = src.count
        if speechSamples == 0 { _ = src.take(max(0, have - 8000)); continue }
        let cut = Double(quietSamples) / 16000 >= pause || Double(have) / 16000 >= maxLine
        guard cut else { continue }
        let pcm = src.take(have); speechSamples = 0; quietSamples = 0
        let ended = Date(); let secs = Double(pcm.count) / 16000
        if secs < 0.5 { continue }
        lines += 1
        saveWav(pcm, name: label + String(format: "%03d", lines))
        let opts = DecodingOptions(task: .transcribe, language: nil, detectLanguage: true, withoutTimestamps: true)
        await gate.enter()
        let w0 = Date()
        let result = try? await kit.transcribe(audioArray: pcm, decodeOptions: opts)
        let wsec = Date().timeIntervalSince(w0)
        await gate.leave()
        let line = (result?.first?.text ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        show(String(format: "[%@ %d] %.1fs audio | whisper %.2fs | delay %.2fs | %d MB\n    %@", label, lines, secs, wsec, Date().timeIntervalSince(ended), footprintMB(), line))
    }
}

var micOn = false
Task {
    show("memory at start: \(footprintMB()) MB. Loading the model ...")
    let t0 = Date()
    guard let kit = try? await WhisperKit(WhisperKitConfig(modelFolder: modelFolder, tokenizerFolder: URL(fileURLWithPath: NSHomeDirectory() + "/AnneProto/tokenizer"), verbose: false, logLevel: .none, prewarm: true, load: true, download: false)) else { show("model failed to load"); return }
    show(String(format: "model ready in %.1f s, memory %d MB", Date().timeIntervalSince(t0), footprintMB()))
    if let err = startTap() { show("sound capture: \(err)"); return }
    show("capturing the system sound (상대). Use earphones if you turn the microphone on.")
    DispatchQueue.main.async {
        let b = NSButton(checkboxWithTitle: "Microphone (나)", target: nil, action: nil)
        b.frame = NSRect(x: 10, y: 4, width: 220, height: 22); window.contentView!.addSubview(b); scroll.frame = NSRect(x: 0, y: 30, width: window.contentView!.bounds.width, height: window.contentView!.bounds.height - 30)
        class Toggle: NSObject { @objc func flip(_ b: NSButton) {
            if b.state == .on { AVCaptureDevice.requestAccess(for: .audio) { ok in
                DispatchQueue.main.async { if !ok { b.state = .off; show("microphone permission denied"); return }
                    if micEngine == nil, let err = startMic() { b.state = .off; show("microphone: \(err)"); return }
                    micOn = true; show("microphone on") } } }
            else { micOn = false; show("microphone off") } } }
        let t = Toggle(); b.target = t; b.action = #selector(Toggle.flip(_:)); objc_setAssociatedObject(b, "t", t, .OBJC_ASSOCIATION_RETAIN)
    }
    Task {   // diagnostics every 5 s: how much sound arrived and how loud
        var last = (0, 0)
        while true {
            try? await Task.sleep(nanoseconds: 5_000_000_000)
            let a = audio.total, m = micAudio.total
            show(String(format: "[diag] system +%.1fs level %.4f | mic +%.1fs level %.4f | mic %@", Double(a - last.0) / 16000, rms(audio.tail(16000)[...]), Double(m - last.1) / 16000, rms(micAudio.tail(16000)[...]), micOn ? "on" : "off"))
            last = (a, m)
        }
    }
    Task { await runStream("상대", audio, kit, enabled: { true }) }
    await runStream("나", micAudio, kit, enabled: { micOn })
}
app.run()
