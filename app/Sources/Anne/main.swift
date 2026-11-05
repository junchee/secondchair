// Anne.app, step 1: a thin shell around the existing Python program.
// It starts app.py (no browser), shows the page in its own window, and stops the program when you quit.
// Later steps put Python and the models inside the app; this file stays the same shape.
import Cocoa
@preconcurrency import WebKit

let port = 8765
// Speech: the app itself hears the sound and writes it down (Speech.swift) when the model is there; ANNE_SPEECH=python keeps the old way.
let swiftSpeech = ProcessInfo.processInfo.environment["ANNE_SPEECH"] != "python" && speechModelPresent()
let pageURL = URL(string: "http://127.0.0.1:\(port)/")!
let logURL = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/Anne.log")

func shellQuote(_ s: String) -> String { "'" + s.replacingOccurrences(of: "'", with: "'\\''") + "'" }

func serverIsUp() -> Bool {
    var up = false
    let done = DispatchSemaphore(value: 0)
    var request = URLRequest(url: pageURL)
    request.timeoutInterval = 1.0
    URLSession.shared.dataTask(with: request) { _, response, _ in
        up = (response as? HTTPURLResponse)?.statusCode == 200
        done.signal()
    }.resume()
    _ = done.wait(timeout: .now() + 1.5)
    return up
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKUIDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var child: Process?
    var attached = false            // an Anne server was already running: we did not start it and do not stop it
    var quitReply = false           // we are waiting for the program to finish before the app exits
    var waitTimer: Timer?
    var speech: Speech?

    // MARK: start
    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMenu()
        web = WKWebView(frame: .zero, configuration: WKWebViewConfiguration())
        web.uiDelegate = self
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1100, height: 780),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Anne"
        window.contentView = web
        window.delegate = self
        window.setFrameAutosaveName("AnneMain")
        if !window.setFrameUsingName("AnneMain") { window.center() }
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        show("Anne을 시작하는 중…")
        if serverIsUp() { attached = true; web.load(URLRequest(url: pageURL)) } else { startProgram(); waitForServer() }
    }

    func show(_ message: String) {
        web.loadHTMLString("<body style='font:16px -apple-system;display:flex;align-items:center;justify-content:center;height:90vh;color:#888;text-align:center'><div>\(message)</div></body>", baseURL: nil)
    }

    func startProgram() {
        let home = (Bundle.main.object(forInfoDictionaryKey: "AnneHome") as? String) ?? NSHomeDirectory() + "/secondchair"
        let python = ProcessInfo.processInfo.environment["ANNE_PYTHON"] ?? home + "/.venv/bin/python"
        FileManager.default.createFile(atPath: logURL.path, contents: nil)
        let log = try? FileHandle(forWritingTo: logURL)
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/zsh")
        // zsh reads ~/.zshrc for OPENROUTER_API_KEY (step 2 moves the key into the Keychain)
        var launch = "app.py --no-browser --port \(port)"
        var token = ""
        if swiftSpeech {   // the program receives lines from this app, with a secret only this app and the program know
            token = UUID().uuidString
            launch += " --remote-speech"
        }
        p.arguments = ["-c", "source ~/.zshrc 2>/dev/null; cd \(shellQuote(home)) && \(token.isEmpty ? "" : "ANNE_TOKEN=\(token) ")exec \(shellQuote(python)) \(launch)"]
        p.standardOutput = log
        p.standardError = log
        p.terminationHandler = { [weak self] _ in DispatchQueue.main.async { self?.programEnded() } }
        do { try p.run(); child = p } catch { show("Anne을 시작하지 못했습니다: \(error.localizedDescription)"); return }
        if swiftSpeech {
            let logFile = log
            speech = Speech(port: port, token: token) { line in logFile?.write(Data((line + "\n").utf8)) }
            speech?.start()
        }
    }

    func waitForServer() {
        let started = Date()
        waitTimer = Timer.scheduledTimer(withTimeInterval: 0.6, repeats: true) { [weak self] timer in
            guard let self = self else { timer.invalidate(); return }
            DispatchQueue.global().async {
                let up = serverIsUp()
                DispatchQueue.main.async {
                    if up { timer.invalidate(); self.web.load(URLRequest(url: pageURL)) }
                    else if Date().timeIntervalSince(started) > 120 {
                        timer.invalidate()
                        self.show("시작하는 데 너무 오래 걸립니다. 메뉴의 ‘로그 보기’를 확인해 주세요.")
                    }
                }
            }
        }
    }

    func programEnded() {
        child = nil
        if quitReply { NSApp.reply(toApplicationShouldTerminate: true) } else { NSApp.terminate(nil) }
    }

    // MARK: quit: ask the program to end the meeting properly (summary, save), then exit
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        speech?.stop()
        guard let p = child, p.isRunning, !attached else { return .terminateNow }
        quitReply = true
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(port)/quit")!)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = Data("{}".utf8)
        URLSession.shared.dataTask(with: request).resume()
        DispatchQueue.main.asyncAfter(deadline: .now() + 60) { if p.isRunning { p.terminate() } }   // the summary can take a while
        return .terminateLater
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        let alert = NSAlert()
        alert.messageText = "Anne을 종료할까요?"
        alert.informativeText = "진행 중인 회의가 있으면 요약하고 저장한 뒤 종료합니다."
        alert.addButton(withTitle: "종료")
        alert.addButton(withTitle: "취소")
        return alert.runModal() == .alertFirstButtonReturn
    }

    // MARK: the page uses confirm() for Quit: WKWebView needs these to show it
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.addButton(withTitle: "확인")
        alert.addButton(withTitle: "취소")
        completionHandler(alert.runModal() == .alertFirstButtonReturn)
    }

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.runModal()
        completionHandler()
    }

    // MARK: menu bar (names follow the system language; each item runs the page's own function, see window.anne)
    let korean = (Locale.preferredLanguages.first ?? "en").hasPrefix("ko")
    func tr(_ en: String, _ ko: String) -> String { korean ? ko : en }

    @objc func showLog() { NSWorkspace.shared.open(logURL) }
    @objc func reload() { web.reload() }
    @objc func openHelp() { NSWorkspace.shared.open(URL(string: "https://junchee.github.io/secondchair/")!) }
    @objc func runJS(_ sender: NSMenuItem) {
        if let code = sender.representedObject as? String { web.evaluateJavaScript(code, completionHandler: nil) }
    }

    func buildMenu() {
        let bar = NSMenu()
        func menu(_ title: String, _ build: (NSMenu) -> Void) {
            let top = NSMenuItem(); bar.addItem(top)
            let m = NSMenu(title: title); top.submenu = m
            build(m)
        }
        func js(_ m: NSMenu, _ title: String, _ code: String, _ key: String = "", _ mods: NSEvent.ModifierFlags = [.command]) {
            let item = NSMenuItem(title: title, action: #selector(runJS(_:)), keyEquivalent: key)
            item.target = self
            item.representedObject = "window.anne && window.anne.\(code)"
            item.keyEquivalentModifierMask = mods
            m.addItem(item)
        }
        func native(_ m: NSMenu, _ title: String, _ action: Selector, _ key: String = "", _ mods: NSEvent.ModifierFlags = [.command], target: AnyObject? = nil) {
            let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
            item.keyEquivalentModifierMask = mods
            if let t = target { item.target = t }
            m.addItem(item)
        }
        menu("Anne") { m in
            native(m, tr("About Anne", "Anne에 대하여"), #selector(NSApplication.orderFrontStandardAboutPanel(_:)))
            m.addItem(.separator())
            js(m, tr("Settings…", "설정…"), "openView()", ",")
            m.addItem(.separator())
            native(m, tr("Quit Anne", "Anne 종료"), #selector(NSApplication.terminate(_:)), "q")
        }
        menu(tr("Meeting", "회의")) { m in
            js(m, tr("Start", "시작"), "start()", "n")
            js(m, tr("Pause / Resume", "일시정지 / 다시 시작"), "pauseResume()", "p")
            js(m, tr("End", "종료"), "end()", ".")
            m.addItem(.separator())
            js(m, tr("Summary", "요약"), "summary()", "s", [.command, .shift])
            js(m, tr("Ask Anne", "Anne에게 묻기"), "ask()", "/")
            js(m, tr("Briefing…", "브리핑…"), "background()", "b")
            m.addItem(.separator())
            js(m, tr("Microphone on / off", "마이크 켜기 / 끄기"), "mic()", "m", [.command, .shift])
        }
        menu(tr("Edit", "편집")) { m in
            native(m, tr("Undo", "실행 취소"), Selector(("undo:")), "z")
            m.addItem(.separator())
            native(m, tr("Cut", "잘라내기"), #selector(NSText.cut(_:)), "x")
            native(m, tr("Copy", "복사"), #selector(NSText.copy(_:)), "c")
            native(m, tr("Paste", "붙여넣기"), #selector(NSText.paste(_:)), "v")
            native(m, tr("Select All", "전체 선택"), #selector(NSText.selectAll(_:)), "a")
        }
        menu(tr("View", "보기")) { m in
            js(m, tr("Light", "밝게"), "theme('light')")
            js(m, tr("Dark", "어둡게"), "theme('dark')")
            js(m, tr("Automatic", "자동"), "theme('auto')")
            m.addItem(.separator())
            js(m, tr("Bigger text", "글자 키우기"), "textSize(1)", "+")
            js(m, tr("Smaller text", "글자 줄이기"), "textSize(-1)", "-")
            js(m, tr("Default text size", "기본 크기"), "textSize(0)", "0")
            m.addItem(.separator())
            js(m, tr("Compact view", "간단히 보기"), "compact()", "c", [.command, .shift])
            js(m, tr("Turn translation off / on", "번역 끄기 / 켜기"), "translateOff()")
            m.addItem(.separator())
            native(m, tr("Reload", "새로고침"), #selector(reload), "r", target: self)
        }
        menu(tr("Developer", "개발자")) { m in
            js(m, tr("Tuning…", "튜닝…"), "tuning()")
            native(m, tr("Show log", "로그 보기"), #selector(showLog), "l", target: self)
            js(m, tr("Show / hide the Developer menu in the page", "페이지의 개발자 메뉴 보이기 / 숨기기"), "developerMenu()")
        }
        menu(tr("Window", "윈도우")) { m in
            native(m, tr("Minimize", "최소화"), #selector(NSWindow.performMiniaturize(_:)), "m")
        }
        menu(tr("Help", "도움말")) { m in
            native(m, tr("Anne guide", "Anne 사용 안내"), #selector(openHelp), "", [], target: self)
        }
        NSApp.mainMenu = bar
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
