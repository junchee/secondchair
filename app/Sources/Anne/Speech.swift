// Speech.swift: the app hears the sound and turns it into text; the Python program (app.py --remote-speech) does the rest.
//
//   system sound (Core Audio process tap, no BlackHole) ┐
//   microphone (AVAudioEngine)                          ┴-> cut into lines -> WhisperKit -> POST /line
//
// Start, Pause and End come from the page: this file listens to the program's /events and follows the `session` events.
import AVFoundation
import AudioToolbox
import CoreAudio
import Foundation
import WhisperKit

/// Where the models live for now (files made by whisperkit-cli and the prototype). Packaging moves them into the app's data folder.
/// turbo = large-v3-turbo (632 MB): more exact, about twice as slow, and a long first compile; small = the lighter choice for 8 GB Macs.
/// ANNE_MODEL=small|turbo chooses; otherwise turbo when it is there. (Later: by the Mac's memory, 16 GB and more -> turbo.)
struct SpeechModel { let name: String, folder: String, tokenizer: String }
func chooseSpeechModel(prefer: String? = nil) -> SpeechModel? {
    let home = NSHomeDirectory() + "/AnneProto"
    let small = SpeechModel(name: "small", folder: home + "/model", tokenizer: home + "/tokenizer")
    let turbo = SpeechModel(name: "turbo", folder: home + "/turbo/models/argmaxinc/whisperkit-coreml/openai_whisper-large-v3-v20240930_turbo_632MB",
                            tokenizer: home + "/turbo/models/openai/whisper-large-v3")
    func present(_ m: SpeechModel) -> Bool {
        FileManager.default.fileExists(atPath: m.folder + "/AudioEncoder.mlmodelc") && FileManager.default.fileExists(atPath: m.tokenizer + "/tokenizer.json")
    }
    // The page's Developer menu decides (turbo by default); ANNE_MODEL only when the page has said nothing. A missing model falls back to the other.
    let wanted = (prefer?.isEmpty == false ? prefer : nil) ?? ProcessInfo.processInfo.environment["ANNE_MODEL"] ?? "turbo"
    let order = wanted == "small" ? [small, turbo] : [turbo, small]
    return order.first(where: present)
}
func speechModelPresent() -> Bool { chooseSpeechModel() != nil }
let speechLevel: Float = 0.006   // below this the sound is treated as quiet (the program drops a quiet mic line again by its own level)

func footprintMB() -> Int {
    var info = task_vm_info_data_t(); var count = mach_msg_type_number_t(MemoryLayout<task_vm_info_data_t>.size / MemoryLayout<integer_t>.size)
    let r = withUnsafeMutablePointer(to: &info) { $0.withMemoryRebound(to: integer_t.self, capacity: Int(count)) { task_info(mach_task_self_, task_flavor_t(TASK_VM_INFO), $0, &count) } }
    return r == KERN_SUCCESS ? Int(info.phys_footprint / 1_048_576) : -1
}

/// 16 kHz mono samples collected by an audio callback and drained by a line loop.
final class SampleBuffer: @unchecked Sendable {
    private let lock = NSLock(); private var samples: [Float] = []
    func add(_ chunk: [Float]) { lock.lock(); samples.append(contentsOf: chunk); lock.unlock() }
    func take(_ n: Int) -> [Float] { lock.lock(); defer { lock.unlock() }; let out = Array(samples.prefix(n)); samples.removeFirst(min(n, samples.count)); return out }
    func tail(_ n: Int) -> [Float] { lock.lock(); defer { lock.unlock() }; return Array(samples.suffix(n)) }
    var count: Int { lock.lock(); defer { lock.unlock() }; return samples.count }
}

func rms(_ a: [Float]) -> Float { a.isEmpty ? 0 : (a.reduce(0) { $0 + $1 * $1 } / Float(a.count)).squareRoot() }

/// With the Mac's own speakers the microphone would record the meeting again, so it stays off (earphones: on).
func outputIsSpeakers() -> Bool {
    var device = AudioObjectID(0); var size = UInt32(MemoryLayout<AudioObjectID>.size)
    var address = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyDefaultOutputDevice, mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
    guard AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size, &device) == noErr else { return false }
    var transport: UInt32 = 0; size = UInt32(MemoryLayout<UInt32>.size)
    address = AudioObjectPropertyAddress(mSelector: kAudioDevicePropertyTransportType, mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
    guard AudioObjectGetPropertyData(device, &address, 0, nil, &size, &transport) == noErr, transport == kAudioDeviceTransportTypeBuiltIn else { return false }
    var source: UInt32 = 0; size = UInt32(MemoryLayout<UInt32>.size)
    address = AudioObjectPropertyAddress(mSelector: kAudioDevicePropertyDataSource, mScope: kAudioDevicePropertyScopeOutput, mElement: kAudioObjectPropertyElementMain)
    guard AudioObjectGetPropertyData(device, &address, 0, nil, &size, &source) == noErr else { return true }
    return source == 0x6973706B   // 'ispk': the internal speakers ('hdpn' is the headphone jack)
}

/// The sentence being spoken: all sound since the last confirmed sentence (plus a short pre-roll). Nothing is cut by the clock:
/// the whole window goes through the model again and again, so the model always hears the sentence from its start.
/// Speech = a 30 ms frame clearly louder than the background noise (tracked), like the Python side's Segmenter.
final class OpenWindow {
    let frame = 480, frameSeconds = 0.03          // 30 ms at 16 kHz
    private let preroll = 0.3, ratio: Float = 3.0, minRMS: Float = 0.003
    private var noiseFloor: Float = 0.01
    private(set) var samples: [Float] = []
    private var flags: [Bool] = []                // per frame: speech or not
    private var leftover: [Float] = []
    private var speechCount = 0
    var absOffset = 0.0                           // seconds of sound dropped from the front of the window so far (gives times a fixed zero)
    var decodedSeconds = 0.0                      // window length at the last pass through the model
    var silenceStageDone = 0                      // 1 = a 0.6 s pause was already checked, 2 = a 1.2 s pause

    var seconds: Double { Double(flags.count) * frameSeconds }
    var speechSeconds: Double { Double(speechCount) * frameSeconds }
    var tailSilence: Double { Double(flags.reversed().prefix { !$0 }.count) * frameSeconds }

    /// The window without its trailing silence (plus `extra` seconds): a window that ends in silence makes the model invent an ending.
    func samplesWithoutTrailingSilence(extra: Double) -> [Float] {
        guard let last = flags.lastIndex(of: true) else { return samples }
        let end = min(flags.count, last + 1 + Int(extra / frameSeconds))
        return Array(samples[..<(end * frame)])
    }

    func reset() { samples = []; flags = []; leftover = []; speechCount = 0; decodedSeconds = 0; silenceStageDone = 0; absOffset = 0 }

    func add(_ audio: [Float]) {
        var all = leftover + audio
        let full = all.count / frame * frame
        leftover = Array(all[full...]); all = Array(all[..<full])
        var i = 0
        while i < full {
            let f = all[i..<(i + frame)]; i += frame
            let level = (f.reduce(0) { $0 + $1 * $1 } / Float(frame)).squareRoot()
            if level < noiseFloor { noiseFloor = level } else { noiseFloor = 0.999 * noiseFloor + 0.001 * level }   // down at once, up slowly
            let speech = level > max(noiseFloor * ratio, minRMS)
            samples.append(contentsOf: f); flags.append(speech)
            if speech { speechCount += 1; silenceStageDone = 0 }
        }
        if speechCount == 0 {                     // nobody speaks: keep only the pre-roll
            let keep = Int(preroll / frameSeconds)
            if flags.count > keep { let drop = flags.count - keep; samples.removeFirst(drop * frame); flags.removeFirst(drop); decodedSeconds = 0; absOffset += Double(drop) * frameSeconds }
        }
    }

    /// Drops the first `t` seconds: a sentence up to there was confirmed.
    func trim(seconds t: Double) {
        let frames = min(flags.count, max(0, Int(t / frameSeconds)))
        samples.removeFirst(frames * frame); flags.removeFirst(frames)
        speechCount = flags.filter { $0 }.count
        decodedSeconds = max(0, decodedSeconds - Double(frames) * frameSeconds)
        absOffset += Double(frames) * frameSeconds
    }
}

actor Gate {   // one Whisper job at a time, even with two sources
    private var busy = false
    func enter() async { while busy { try? await Task.sleep(nanoseconds: 20_000_000) }; busy = true }
    func leave() { busy = false }
}

final class Speech: @unchecked Sendable {
    let port: Int, token: String
    let log: (String) -> Void
    private let system = SampleBuffer(), mic = SampleBuffer()
    private let gate = Gate()
    private let lock = NSLock()
    private var state = "idle", maxLine = 4.0, pause = 0.2, micEnabled = true
    private var kit: WhisperKit?
    private var wantedModel = "", loadedModel = "", failedModel = "", settingsSeen = false, switching = false
    private var tapIDs: (tap: AudioObjectID, aggregate: AudioObjectID, proc: AudioDeviceIOProcID?)?
    private var micEngine: AVAudioEngine?
    private var stopped = false
    private var lastEnd: [String: Double] = [:]      // per source: where the previous confirmed sentence ended (seconds, same zero as the window)

    init(port: Int, token: String, log: @escaping (String) -> Void) { self.port = port; self.token = token; self.log = log }

    // MARK: life
    func start() {
        Task.detached { [self] in
            Task.detached { [self] in await listenToProgram() }
            for _ in 0..<150 where !get({ settingsSeen }) { try? await Task.sleep(nanoseconds: 200_000_000) }   // the program says which model (up to 30 s)
            tell(model: "loading")
            guard let choice = chooseSpeechModel(prefer: get({ wantedModel })), let loaded = await loadKit(choice) else {
                log("speech: the model could not be loaded"); return
            }
            lock.lock(); kit = loaded; loadedModel = choice.name; lock.unlock()
            tell(model: "ready")
            Task.detached { [self] in await watchInputs() }
            Task.detached { [self] in await lines("SYSTEM", system) { true } }
            Task.detached { [self] in await lines("MIC", mic) { self.micWanted() } }
        }
    }

    private func loadKit(_ choice: SpeechModel) async -> WhisperKit? {
        let t0 = Date()
        guard let loaded = try? await WhisperKit(WhisperKitConfig(
            modelFolder: choice.folder, tokenizerFolder: URL(fileURLWithPath: choice.tokenizer),
            verbose: false, logLevel: .none, prewarm: true, load: true, download: false)) else { return nil }
        log(String(format: "speech: model %@ ready in %.1f s, %d MB", choice.name, Date().timeIntervalSince(t0), footprintMB()))
        return loaded
    }

    /// The Developer menu chose another model: it is loaded when no meeting is running, and the old one is let go.
    private func switchModelIfNeeded() async {
        let (wanted, loaded, busy, failed) = get { (wantedModel, loadedModel, switching, failedModel) }
        guard !wanted.isEmpty, wanted != loaded, wanted != failed, !busy, get({ state }) == "idle" else { return }
        lock.lock(); switching = true; lock.unlock()
        defer { lock.lock(); switching = false; lock.unlock() }
        guard let choice = chooseSpeechModel(prefer: wanted), choice.name != loaded else {
            lock.lock(); failedModel = wanted; lock.unlock(); log("speech: model \(wanted) is not available"); return
        }
        tell(model: "loading")
        await gate.enter()
        if let new = await loadKit(choice) {
            lock.lock(); let old = kit; kit = new; loadedModel = choice.name; lock.unlock()
            await old?.unloadModels()
        } else { lock.lock(); failedModel = wanted; lock.unlock(); log("speech: model \(choice.name) could not be loaded") }
        await gate.leave()
        tell(model: "ready")
    }

    func stop() { stopped = true; stopTap(); stopMic() }

    private func get<T>(_ f: () -> T) -> T { lock.lock(); defer { lock.unlock() }; return f() }
    private func micWanted() -> Bool { get { state == "running" && micEnabled && !outputIsSpeakers() } }

    // MARK: what the program says (Start / Pause / End and the line settings)
    private func listenToProgram() async {
        while !stopped {
            do {
                let (bytes, _) = try await URLSession.shared.bytes(from: URL(string: "http://127.0.0.1:\(port)/events")!)
                for try await line in bytes.lines where line.hasPrefix("data: ") {
                    guard let data = line.dropFirst(6).data(using: .utf8), let event = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { continue }
                    apply(event)
                }
            } catch { }
            try? await Task.sleep(nanoseconds: 1_000_000_000)   // the program is not there yet, or it restarted
        }
    }

    private func apply(_ event: [String: Any]) {
        switch event["type"] as? String {
        case "session":
            if let s = event["state"] as? String { lock.lock(); state = s; lock.unlock(); log("speech: meeting is \(s)") }
        case "settings":
            lock.lock()
            if let v = event["max_line_seconds"] as? Double { maxLine = v }
            if let v = event["pause_seconds"] as? Double { pause = v }
            if let v = event["mic_enabled"] as? Bool { micEnabled = v }
            if let v = event["speech_model"] as? String { wantedModel = v }
            settingsSeen = true
            lock.unlock()
        default: break
        }
    }

    /// Follows the state: the sound tap runs while a meeting runs or is paused, the microphone only when wanted.
    private func watchInputs() async {
        while !stopped {
            let (s, wantMic) = (get { state }, micWanted())
            if s == "running" || s == "paused" { if tapIDs == nil, let error = startTap() { log("speech: sound capture: \(error)") } } else { stopTap() }
            if wantMic { if micEngine == nil, let error = await startMic() { log("speech: microphone: \(error)") } } else { stopMic() }
            await switchModelIfNeeded()
            try? await Task.sleep(nanoseconds: 700_000_000)
        }
    }

    // MARK: sound capture
    private func startTap() -> String? {
        let desc = CATapDescription(stereoGlobalTapButExcludeProcesses: [])
        desc.uuid = UUID(); desc.name = "Anne"; desc.isPrivate = true; desc.muteBehavior = .unmuted
        var tapID = AudioObjectID(kAudioObjectUnknown)
        var st = AudioHardwareCreateProcessTap(desc, &tapID)
        if st != noErr { return "AudioHardwareCreateProcessTap failed (\(st))" }
        var addr = AudioObjectPropertyAddress(mSelector: kAudioTapPropertyFormat, mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
        var fmt = AudioStreamBasicDescription(); var size = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
        st = AudioObjectGetPropertyData(tapID, &addr, 0, nil, &size, &fmt)
        if st != noErr { AudioHardwareDestroyProcessTap(tapID); return "tap format failed (\(st))" }
        let ratio = fmt.mSampleRate / 16000, channels = max(Int(fmt.mChannelsPerFrame), 1)
        let agg: [String: Any] = [
            kAudioAggregateDeviceNameKey: "Anne-tap", kAudioAggregateDeviceUIDKey: UUID().uuidString,
            kAudioAggregateDeviceIsPrivateKey: true, kAudioAggregateDeviceIsStackedKey: false, kAudioAggregateDeviceTapAutoStartKey: true,
            kAudioAggregateDeviceTapListKey: [[kAudioSubTapUIDKey: desc.uuid.uuidString, kAudioSubTapDriftCompensationKey: true]]]
        var aggID = AudioObjectID(kAudioObjectUnknown)
        st = AudioHardwareCreateAggregateDevice(agg as CFDictionary, &aggID)
        if st != noErr { AudioHardwareDestroyProcessTap(tapID); return "aggregate device failed (\(st))" }
        var proc: AudioDeviceIOProcID?
        var phase = 0.0
        let buffer = system
        st = AudioDeviceCreateIOProcIDWithBlock(&proc, aggID, nil) { _, input, _, _, _ in
            let bufs = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: input))
            guard let b = bufs.first, let data = b.mData else { return }
            let n = Int(b.mDataByteSize) / 4 / channels
            let p = data.bindMemory(to: Float.self, capacity: n * channels)
            var out: [Float] = []; out.reserveCapacity(Int(Double(n) / ratio) + 1)
            while Int(phase + ratio) <= n {              // 48 kHz -> 16 kHz: average the samples of each step (a plain skip distorts the sound), mono mix
                let from = Int(phase), to = max(from + 1, Int(phase + ratio))
                var s: Float = 0
                for i in from..<to { for c in 0..<channels { s += p[i * channels + c] } }
                out.append(s / Float((to - from) * channels)); phase += ratio
            }
            phase = max(0, phase - Double(n))   // a partial step at the end of the block is dropped (under 3 samples)
            buffer.add(out)
        }
        if st != noErr { AudioHardwareDestroyAggregateDevice(aggID); AudioHardwareDestroyProcessTap(tapID); return "IOProc failed (\(st))" }
        st = AudioDeviceStart(aggID, proc)
        if st != noErr { return "AudioDeviceStart failed (\(st))" }
        tapIDs = (tapID, aggID, proc)
        log("speech: system sound capture started")
        return nil
    }

    private func stopTap() {
        guard let ids = tapIDs else { return }
        AudioDeviceStop(ids.aggregate, ids.proc)
        if let proc = ids.proc { AudioDeviceDestroyIOProcID(ids.aggregate, proc) }
        AudioHardwareDestroyAggregateDevice(ids.aggregate)
        AudioHardwareDestroyProcessTap(ids.tap)
        tapIDs = nil
        _ = system.take(system.count)
        log("speech: system sound capture stopped")
    }

    // MARK: microphone
    private func startMic() async -> String? {
        let granted = await withCheckedContinuation { c in AVCaptureDevice.requestAccess(for: .audio) { c.resume(returning: $0) } }
        guard granted else { return "permission denied" }
        let engine = AVAudioEngine(); let input = engine.inputNode
        let inFmt = input.inputFormat(forBus: 0)
        guard inFmt.sampleRate > 0, let outFmt = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 16000, channels: 1, interleaved: false),
              let conv = AVAudioConverter(from: inFmt, to: outFmt) else { return "no microphone format" }
        let buffer = mic
        input.installTap(onBus: 0, bufferSize: 4096, format: inFmt) { buf, _ in
            let cap = AVAudioFrameCount(Double(buf.frameLength) * 16000 / inFmt.sampleRate) + 16
            guard let out = AVAudioPCMBuffer(pcmFormat: outFmt, frameCapacity: cap) else { return }
            var fed = false
            conv.convert(to: out, error: nil) { _, status in if fed { status.pointee = .noDataNow; return nil }; fed = true; status.pointee = .haveData; return buf }
            if let p = out.floatChannelData?[0] { buffer.add(Array(UnsafeBufferPointer(start: p, count: Int(out.frameLength)))) }
        }
        do { try engine.start() } catch { return "start failed: \(error.localizedDescription)" }
        micEngine = engine
        log("speech: microphone started")
        return nil
    }

    private func stopMic() {
        guard let engine = micEngine else { return }
        engine.inputNode.removeTap(onBus: 0); engine.stop(); micEngine = nil
        _ = mic.take(mic.count)
        log("speech: microphone stopped")
    }

    // MARK: sentences
    /// One reader per source. All sound is kept in an open window; about every second the whole window goes through the model.
    /// A sentence that is followed by more text is final; the last one is final after a pause. The rest is shown as a draft.
    private func lines(_ label: String, _ src: SampleBuffer, enabled: @escaping () -> Bool) async {
        let window = OpenWindow()
        var draftShown = false
        while !stopped {
            try? await Task.sleep(nanoseconds: 100_000_000)
            if get({ state }) != "running" || !enabled() {          // paused, ended, or this source is off
                _ = src.take(src.count)
                if window.seconds > 0 { window.reset(); lock.lock(); lastEnd[label] = nil; lock.unlock() }
                if draftShown { draftShown = false; await postWait(["partial": true, "source": label, "clear": true]) }
                continue
            }
            window.add(src.take(src.count))
            guard window.speechSeconds >= 0.3 else { continue }
            let silence = window.tailSilence
            let stage = silence >= 1.2 ? 2 : (silence >= 0.6 ? 1 : 0)
            guard window.seconds - window.decodedSeconds >= 0.8 || stage > window.silenceStageDone else { continue }
            window.silenceStageDone = stage
            draftShown = await decode(label, window, stage: stage, draft: draftShown)
        }
    }

    private func endsSentence(_ text: String) -> Bool {
        var t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        while let last = t.last, "\"'”’)」』]".contains(last) { t.removeLast() }
        if t.hasSuffix("…") || t.hasSuffix("...") { return false }    // trailing off: the sentence is not over
        guard let last = t.last else { return false }
        return ".?!。？！".contains(last)
    }

    private func stripTurnMark(_ text: String) -> String {
        var t = Substring(text)
        while let c = t.first, c == "-" || c == "–" || c == " " { t = t.dropFirst() }
        return String(t)
    }

    private func isKorean(_ text: String) -> Bool {
        text.unicodeScalars.contains { (0xAC00...0xD7A3).contains($0.value) || (0x1100...0x11FF).contains($0.value) }
    }

    /// One pass through the model over the open window. Returns whether a draft is now shown.
    private func decode(_ label: String, _ window: OpenWindow, stage: Int, draft: Bool) async -> Bool {
        let pcm = window.samplesWithoutTrailingSilence(extra: 0.2), length = window.seconds
        await gate.enter()
        guard let kit = get({ self.kit }) else { await gate.leave(); return draft }
        let started = Date()
        // Same settings as the command line tool, which read the saved lines correctly: prefill off (it made English nonsense of Korean
        // speech) and timestamps on (without them more text was invented). The model finds the language itself.
        let options = DecodingOptions(task: .transcribe, language: nil, temperatureFallbackCount: 2, usePrefillPrompt: false, usePrefillCache: false, detectLanguage: true, skipSpecialTokens: true, withoutTimestamps: false)
        let results = try? await kit.transcribe(audioArray: pcm, decodeOptions: options)
        await gate.leave()
        window.decodedSeconds = length
        guard get({ state }) == "running", let first = results?.first else { return draft }
        let segments = first.segments.filter { !$0.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

        // segments -> sentences (a sentence ends where the text ends with . ? !)
        // A segment that starts with "- " is Whisper's way of marking that another person speaks: what came before is final.
        func isTurn(_ s: TranscriptionSegment) -> Bool { s.text.trimmingCharacters(in: .whitespaces).hasPrefix("-") }
        var sentences: [[TranscriptionSegment]] = [], current: [TranscriptionSegment] = []
        for segment in segments {
            if isTurn(segment), !current.isEmpty { sentences.append(current); current = [] }
            current.append(segment)
            if endsSentence(current.map { $0.text }.joined()) { sentences.append(current); current = [] }
        }
        var tail = current
        var confirm = sentences
        let silence = window.tailSilence
        if length >= 20 {                                            // too long: confirm everything
            if !tail.isEmpty { confirm.append(tail); tail = [] }
        } else if tail.isEmpty, !confirm.isEmpty, silence < 0.6 {    // the last sentence may still go on: wait for a pause
            tail = confirm.removeLast()
        } else if !tail.isEmpty, stage >= 2 {                        // a long pause: no punctuation needed
            confirm.append(tail); tail = []
        }

        // Korean often has no full stop where a phrase ends, so the draft would grow for many seconds and then come out all at once.
        // Segments that end more than 3.5 s before the newest sound are stable: confirm them now (as one line; the page joins it with
        // what follows while the sentence has no end), the rest stays the draft.
        if length < 20, tail.count > 1 {
            let speechEnd = Double(pcm.count) / 16000
            var stable: [TranscriptionSegment] = []
            while tail.count > 1, Double(tail[0].end) <= speechEnd - 3.5 { stable.append(tail.removeFirst()) }
            if !stable.isEmpty { confirm.append(stable) }
        }
        log(String(format: "speech: pass %@ window %.1fs, %d segments, confirm %d, draft %d", label, length, segments.count, confirm.count, tail.count))
        var cut = 0.0
        for sentence in confirm {
            let turn = isTurn(sentence.first!)
            let text = stripTurnMark(sentence.map { $0.text }.joined().trimmingCharacters(in: .whitespacesAndNewlines))
            guard !text.isEmpty else { continue }
            let from = Int(Double(sentence.first!.start) * 16000), to = Int(Double(sentence.last!.end) * 16000)
            let clip = (from < to && to <= pcm.count) ? Array(pcm[max(0, from)..<to]) : pcm
            let file = saveLine(label, clip)
            let parts = sentence.map { ["text": $0.text.trimmingCharacters(in: .whitespacesAndNewlines), "avg_logprob": $0.avgLogprob, "no_speech_prob": $0.noSpeechProb] as [String: Any] }
            let korean = isKorean(text)
            let startAbs = window.absOffset + Double(sentence.first!.start), endAbs = window.absOffset + Double(sentence.last!.end)
            let gap = get { lastEnd[label] }.map { max(0, startAbs - $0) } ?? 99      // quiet since the previous sentence (99 = none before)
            let body: [String: Any] = ["source": label, "lang": korean ? "ko" : "en", "text": text, "segments": parts, "level": rms(clip), "language_share": (korean || first.language == "en") ? 1 : 0, "turn": turn, "gap": gap]
            lock.lock(); lastEnd[label] = endAbs; lock.unlock()
            log(String(format: "speech: %@ %@ sentence (window %.1fs, whisper %.2fs): %@", label, file, length, Date().timeIntervalSince(started), String(text.prefix(200))))
            await postWait(body)
            cut = max(cut, Double(sentence.last!.end))
        }
        if cut > 0 { window.trim(seconds: min(cut, window.seconds)) }

        // the unfinished rest: a draft for them (the microphone shows none, like the Python side)
        let tailText = stripTurnMark(tail.map { $0.text }.joined().trimmingCharacters(in: .whitespacesAndNewlines))
        if label == "SYSTEM", !tailText.isEmpty {
            let tailStart = window.absOffset + Double(tail.first!.start)
            let tailGap = get { lastEnd[label] }.map { max(0, tailStart - $0) } ?? 99
            await postWait(["partial": true, "source": label, "lang": isKorean(tailText) ? "ko" : "en", "text": tailText, "gap": tailGap, "turn": isTurn(tail.first!)])
            return true
        }
        if draft { await postWait(["partial": true, "source": label, "clear": true]) }
        return false
    }

    /// While the Swift speech is being tuned: each line's sound is kept in ~/AnneProto/lines2 (ANNE_SAVE_LINES=0 turns it off),
    /// so the same sound can be run through another engine or setting.
    private var savedCount = 0
    private func saveLine(_ label: String, _ pcm: [Float]) -> String {
        guard ProcessInfo.processInfo.environment["ANNE_SAVE_LINES"] != "0" else { return "" }
        lock.lock(); savedCount += 1; let n = savedCount; lock.unlock()
        let dir = NSHomeDirectory() + "/AnneProto/lines2"; try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        var d = Data(); func u32(_ v: UInt32) { var x = v.littleEndian; d.append(Data(bytes: &x, count: 4)) }; func u16(_ v: UInt16) { var x = v.littleEndian; d.append(Data(bytes: &x, count: 2)) }
        d.append("RIFF".data(using: .ascii)!); u32(UInt32(36 + pcm.count * 2)); d.append("WAVEfmt ".data(using: .ascii)!); u32(16); u16(1); u16(1); u32(16000); u32(32000); u16(2); u16(16)
        d.append("data".data(using: .ascii)!); u32(UInt32(pcm.count * 2))
        for f in pcm { var v = Int16(max(-1, min(1, f)) * 32767).littleEndian; d.append(Data(bytes: &v, count: 2)) }
        let name = String(format: "%@%04d.wav", label, n)
        try? d.write(to: URL(fileURLWithPath: dir + "/" + name))
        return name
    }

    // MARK: to the program
    /// Sent one after another from the reading task, so a draft never overtakes the sentence before it.
    private func postWait(_ body: [String: Any]) async {
        guard let data = try? JSONSerialization.data(withJSONObject: body) else { return }
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(port)/line")!)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(token, forHTTPHeaderField: "X-Anne-Token")
        request.httpBody = data
        request.timeoutInterval = 5
        if let (_, response) = try? await URLSession.shared.data(for: request), let code = (response as? HTTPURLResponse)?.statusCode, code >= 400 { log("speech: /line refused (\(code))") }
    }

    private func tell(model state: String) { post("/line", ["model": state]) }

    private func post(_ path: String, _ body: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: body) else { return }
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(port)\(path)")!)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(token, forHTTPHeaderField: "X-Anne-Token")
        request.httpBody = data
        request.timeoutInterval = 5
        URLSession.shared.dataTask(with: request) { [log] _, response, error in
            if let error = error { log("speech: /line failed: \(error.localizedDescription)") }
            else if let code = (response as? HTTPURLResponse)?.statusCode, code >= 400 { log("speech: /line refused (\(code))") }
        }.resume()
    }
}
