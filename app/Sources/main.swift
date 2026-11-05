// Anne.app, step 1: a thin shell around the existing Python program.
// It starts app.py (no browser), shows the page in its own window, and stops the program when you quit.
// Later steps put Python and the models inside the app; this file stays the same shape.
import Cocoa
@preconcurrency import WebKit

let port = 8765
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
        p.arguments = ["-c", "source ~/.zshrc 2>/dev/null; cd \(shellQuote(home)) && exec \(shellQuote(python)) app.py --no-browser --port \(port)"]
        p.standardOutput = log
        p.standardError = log
        p.terminationHandler = { [weak self] _ in DispatchQueue.main.async { self?.programEnded() } }
        do { try p.run(); child = p } catch { show("Anne을 시작하지 못했습니다: \(error.localizedDescription)") }
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

    // MARK: menu
    @objc func showLog() { NSWorkspace.shared.open(logURL) }

    func buildMenu() {
        let bar = NSMenu()
        func add(_ title: String, _ items: [(String, Selector?, String)]) {
            let top = NSMenuItem(); bar.addItem(top)
            let menu = NSMenu(title: title); top.submenu = menu
            for (label, action, key) in items {
                if label == "-" { menu.addItem(.separator()); continue }
                menu.addItem(NSMenuItem(title: label, action: action, keyEquivalent: key))
            }
        }
        add("Anne", [("Anne 종료", #selector(NSApplication.terminate(_:)), "q")])
        add("편집", [("실행 취소", Selector(("undo:")), "z"), ("-", nil, ""), ("잘라내기", #selector(NSText.cut(_:)), "x"),
                   ("복사", #selector(NSText.copy(_:)), "c"), ("붙여넣기", #selector(NSText.paste(_:)), "v"),
                   ("전체 선택", #selector(NSText.selectAll(_:)), "a")])
        add("보기", [("로그 보기", #selector(showLog), "l"), ("새로고침", #selector(reload), "r")])
        add("윈도우", [("최소화", #selector(NSWindow.performMiniaturize(_:)), "m")])
        NSApp.mainMenu = bar
    }

    @objc func reload() { web.reload() }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
