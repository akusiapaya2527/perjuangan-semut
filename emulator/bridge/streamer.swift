import Foundation
import ScreenCaptureKit
import CoreMedia
import CoreVideo
import CoreImage
import CoreGraphics
import ImageIO
import ApplicationServices

// MARK: - FrameSender: push JPEG frames to Python over loopback TCP

final class FrameSender {
    private let port: UInt16
    private let queue = DispatchQueue(label: "framesender")
    private var sock: Int32 = -1
    private var connected = false
    private var width = 0

    init(port: UInt16) { self.port = port }

    func connect() {
        queue.async { [self] in
            guard sock < 0 else { return }
            let s = socket(AF_INET, SOCK_STREAM, 0)
            guard s >= 0 else { return }
            var addr = sockaddr_in()
            addr.sin_family = sa_family_t(AF_INET)
            addr.sin_port = port.bigEndian
            addr.sin_addr.s_addr = inet_addr("127.0.0.1")
            let r = withUnsafeMutablePointer(to: &addr) { ptr in
                ptr.withMemoryRebound(to: sockaddr.self, capacity: 1) { Darwin.connect(s, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) }
            }
            if r == 0 {
                sock = s
                connected = true
                print("[streamer] frame link up 127.0.0.1:\(port)")
            } else {
                close(s)
                print("[streamer] frame link connect failed, will retry")
            }
        }
    }

    func send(jpeg: Data, width w: Int) {
        queue.async { [self] in
            width = w
            guard connected, sock >= 0 else { return }
            var len = UInt32(jpeg.count).bigEndian
            var out = Data()
            withUnsafeBytes(of: &len) { out.append(contentsOf: $0) }
            out.append(jpeg)
            let n = out.withUnsafeBytes { write(sock, $0.baseAddress, $0.count) }
            if n < 0 {
                close(sock)
                sock = -1
                connected = false
                print("[streamer] frame link lost, reconnecting...")
                connect()
            }
        }
    }

    func currentJpegWidth() -> Int { queue.sync { width } }
}

// MARK: - InputServer: receive input commands from Python, post CGEvent to pid

final class InputServer {
    private let pid: pid_t
    private let port: UInt16
    private let window: SCWindow
    private let frameWidth: () -> Int
    private var downButton: CGMouseButton?

    init(pid: pid_t, port: UInt16, window: SCWindow, frameWidth: @escaping () -> Int) {
        self.pid = pid
        self.port = port
        self.window = window
        self.frameWidth = frameWidth
    }

    func start() {
        DispatchQueue.global(qos: .userInteractive).async { self.run() }
    }

    private func run() {
        let s = socket(AF_INET, SOCK_STREAM, 0)
        guard s >= 0 else { return }
        var on: Int32 = 1
        setsockopt(s, SOL_SOCKET, SO_REUSEADDR, &on, socklen_t(MemoryLayout<Int32>.size))
        var addr = sockaddr_in()
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = port.bigEndian
        addr.sin_addr.s_addr = inet_addr("127.0.0.1")
        let bound = withUnsafeMutablePointer(to: &addr) { ptr in
            ptr.withMemoryRebound(to: sockaddr.self, capacity: 1) { bind(s, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) }
        }
        guard bound == 0 else {
            print("[streamer] bind input port \(port) failed")
            close(s)
            return
        }
        listen(s, 4)
        print("[streamer] input server on 127.0.0.1:\(port)")
        while true {
            let c = accept(s, nil, nil)
            if c < 0 { continue }
            handle(conn: c)
            close(c)
        }
    }

    private func handle(conn: Int32) {
        var buf = [UInt8]()
        var byte = UInt8(0)
        while true {
            let n = read(conn, &byte, 1)
            if n <= 0 { return }
            if byte == 10 {
                if let line = String(bytes: buf, encoding: .utf8)?
                    .trimmingCharacters(in: .whitespacesAndNewlines), !line.isEmpty {
                    process(line)
                }
                buf.removeAll(keepingCapacity: true)
            } else {
                buf.append(byte)
            }
        }
    }

    private func process(_ line: String) {
        let p = line.split(separator: " ").map(String.init)
        guard p.count >= 1 else { return }
        switch p[0] {
        case "MOVE":
            guard p.count >= 3, let x = Double(p[1]), let y = Double(p[2]) else { return }
            let pt = global(x, y)
            if let b = downButton {
                postMouse(dragType(for: b), at: pt, button: b)
            } else {
                postMouse(.mouseMoved, at: pt, button: .left)
            }
        case "DOWN":
            guard p.count >= 4, let x = Double(p[1]), let y = Double(p[2]), let b = Int(p[3]) else { return }
            let btn = mouseButton(b)
            downButton = btn
            postMouse(mouseDownType(btn), at: global(x, y), button: btn)
        case "UP":
            guard p.count >= 4, let x = Double(p[1]), let y = Double(p[2]), let b = Int(p[3]) else { return }
            let btn = mouseButton(b)
            downButton = nil
            postMouse(mouseUpType(btn), at: global(x, y), button: btn)
        case "KEY":
            guard p.count >= 3, let c = UInt16(p[1]), let d = Int(p[2]) else { return }
            postKey(code: c, down: d != 0)
        default:
            break
        }
    }

    private func global(_ x: Double, _ y: Double) -> CGPoint {
        let f = window.frame
        let jw = frameWidth()
        let scale = (f.width > 0 && jw > 0) ? f.width / Double(jw) : 0
        return CGPoint(x: f.origin.x + x * scale, y: f.origin.y + y * scale)
    }

    private func mouseButton(_ b: Int) -> CGMouseButton {
        b == 1 ? .right : (b == 2 ? .center : .left)
    }
    private func mouseDownType(_ b: CGMouseButton) -> CGEventType {
        switch b { case .right: return .rightMouseDown; case .center: return .otherMouseDown; default: return .leftMouseDown }
    }
    private func mouseUpType(_ b: CGMouseButton) -> CGEventType {
        switch b { case .right: return .rightMouseUp; case .center: return .otherMouseUp; default: return .leftMouseUp }
    }
    private func dragType(for b: CGMouseButton) -> CGEventType {
        switch b { case .right: return .rightMouseDragged; case .center: return .otherMouseDragged; default: return .leftMouseDragged }
    }
    private func postMouse(_ type: CGEventType, at pt: CGPoint, button: CGMouseButton) {
        guard let e = CGEvent(mouseEventSource: nil, mouseType: type, mouseCursorPosition: pt, mouseButton: button) else { return }
        e.postToPid(pid)
    }
    private func postKey(code: UInt16, down: Bool) {
        guard let e = CGEvent(keyboardEventSource: nil, virtualKey: CGKeyCode(code), keyDown: down) else { return }
        e.postToPid(pid)
    }
}

// MARK: - CaptureController: SCK output → JPEG

final class CaptureController: NSObject, SCStreamOutput {
    private let sender: FrameSender
    private let ciContext = CIContext(options: [.useSoftwareRenderer: false])
    private var processing = false
    private let maxWidth = 1280

    init(sender: FrameSender) { self.sender = sender }

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .screen, !processing else { return }
        processing = true
        defer { processing = false }

        guard let pb = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        let ci = CIImage(cvPixelBuffer: pb)
        guard let cg = ciContext.createCGImage(ci, from: ci.extent) else { return }

        let w = cg.width, h = cg.height
        var out = cg
        if w > maxWidth {
            let newW = maxWidth
            let newH = max(1, h * maxWidth / w)
            if let b = CGContext(data: nil, width: newW, height: newH, bitsPerComponent: 8, bytesPerRow: 0,
                                 space: CGColorSpaceCreateDeviceRGB(),
                                 bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue) {
                b.interpolationQuality = .high
                b.draw(cg, in: CGRect(x: 0, y: 0, width: newW, height: newH))
                if let made = b.makeImage() { out = made }
            }
        }

        let data = NSMutableData()
        guard let dest = CGImageDestinationCreateWithData(data, "public.jpeg" as CFString, 1, nil) else { return }
        CGImageDestinationAddImage(dest, out, [kCGImageDestinationLossyCompressionQuality: 0.65] as CFDictionary)
        guard CGImageDestinationFinalize(dest) else { return }
        sender.send(jpeg: data as Data, width: out.width)
    }
}

// MARK: - Window discovery

func findWindow(pid: pid_t) async -> SCWindow? {
    guard let content = try? await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true) else {
        return nil
    }
    return content.windows.first { $0.owningApplication?.processID == pid }
}

// MARK: - main

@main
struct Streamer {
    static func main() async {
        setvbuf(stdout, nil, _IONBF, 0)  // unbuffered so web.sh can grep logs live
        let args = CommandLine.arguments
        guard args.count >= 4,
              let pid = pid_t(args[1]),
              let framePort = UInt16(args[2]),
              let inputPort = UInt16(args[3]) else {
            print("usage: streamer <pid> <framePort> <inputPort>")
            exit(2)
        }

        if !AXIsProcessTrusted() {
            print("[streamer] WARNING: Accessibility not granted — input clicks/keys may be ignored.")
            print("[streamer]   Grant to your terminal app: System Settings > Privacy & Security > Accessibility, then relaunch.")
        }
        if !CGPreflightScreenCaptureAccess() {
            print("[streamer] ERROR: Screen Recording not granted — stream will be black.")
            print("[streamer]   Grant to your terminal app: System Settings > Privacy & Security > Screen Recording, then relaunch.")
        }

        let sender = FrameSender(port: framePort)
        sender.connect()

        var win: SCWindow? = nil
        for attempt in 1...60 {
            if let w = await findWindow(pid: pid) { win = w; break }
            if attempt % 5 == 0 || attempt == 1 {
                print("[streamer] window for pid \(pid) not found (attempt \(attempt)/60), retrying...")
            }
            try? await Task.sleep(for: .seconds(1))
        }
        guard let w = win else {
            print("[streamer] ERROR: no window for pid \(pid). Is the game client running?")
            exit(1)
        }
        print("[streamer] targeting '\(w.title ?? "untitled")' frame=\(w.frame)")

        let input = InputServer(pid: pid, port: inputPort, window: w, frameWidth: { sender.currentJpegWidth() })
        input.start()

        let controller = CaptureController(sender: sender)
        let filter = SCContentFilter(desktopIndependentWindow: w)
        let config = SCStreamConfiguration()
        config.minimumFrameInterval = CMTime(value: 1, timescale: 25)
        config.queueDepth = 3
        config.capturesAudio = false
        config.showsCursor = false

        let stream = SCStream(filter: filter, configuration: config, delegate: nil)
        do {
            try stream.addStreamOutput(controller, type: .screen, sampleHandlerQueue: .global(qos: .userInteractive))
        } catch {
            print("[streamer] ERROR addStreamOutput: \(error)")
            exit(1)
        }
        do {
            try await stream.startCapture()
        } catch {
            print("[streamer] ERROR startCapture: \(error)")
            print("[streamer]   If this is a permission error, grant Screen Recording to the terminal app and relaunch.")
            exit(1)
        }
        print("[streamer] capture started")

        while true { try? await Task.sleep(for: .seconds(3600)) }
    }
}
