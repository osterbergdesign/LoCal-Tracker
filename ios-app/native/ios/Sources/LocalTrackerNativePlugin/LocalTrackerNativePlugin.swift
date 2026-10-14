import AVFoundation
import Capacitor
import Foundation
import HealthKit
import UIKit

/// Native features for the LoCal iPhone app:
///  - scanBarcode: Apple's camera barcode reader (works without HTTPS, unlike the browser's)
///  - healthAvailable / healthRequest / healthSaveDay: write daily nutrition totals to Apple Health
@objc(LocalTrackerNativePlugin)
public class LocalTrackerNativePlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "LocalTrackerNativePlugin"
    public let jsName = "LocalTrackerNative"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "scanBarcode", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "healthAvailable", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "healthRequest", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "healthSaveDay", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "appInfo", returnType: CAPPluginReturnPromise),
    ]

    private let healthStore = HKHealthStore()

    /// False when the app was built without the Apple Health entitlement (HEALTH=0),
    /// e.g. for a free Apple ID that can't sign HealthKit.
    private var healthBuiltIn: Bool {
        (Bundle.main.object(forInfoDictionaryKey: "LocalTrackerHealth") as? Bool ?? false) && HKHealthStore.isHealthDataAvailable()
    }

    // MARK: - Barcode scanning

    @objc func scanBarcode(_ call: CAPPluginCall) {
        let present = {
            DispatchQueue.main.async {
                guard let host = self.bridge?.viewController else {
                    call.reject("The app isn't ready yet. Try again.", "unavailable")
                    return
                }
                let scanner = ScannerViewController()
                scanner.modalPresentationStyle = .fullScreen
                scanner.onFinish = { code in
                    if let code = code {
                        call.resolve(["code": code])
                    } else {
                        call.reject("Scanning was cancelled.", "cancelled")
                    }
                }
                host.present(scanner, animated: true)
            }
        }
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            present()
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { granted in
                if granted {
                    present()
                } else {
                    call.reject("Camera access is off. Turn it on in Settings → LoCal → Camera.", "denied")
                }
            }
        default:
            call.reject("Camera access is off. Turn it on in Settings → LoCal → Camera.", "denied")
        }
    }

    // MARK: - Apple Health

    private var nutritionTypes: [String: (HKQuantityType, HKUnit)] {
        var types: [String: (HKQuantityType, HKUnit)] = [:]
        let pairs: [(String, HKQuantityTypeIdentifier, HKUnit)] = [
            ("kcal", .dietaryEnergyConsumed, .kilocalorie()),
            ("protein", .dietaryProtein, .gram()),
            ("carbs", .dietaryCarbohydrates, .gram()),
            ("fat", .dietaryFatTotal, .gram()),
            ("fiber", .dietaryFiber, .gram()),
        ]
        for (key, id, unit) in pairs {
            if let type = HKObjectType.quantityType(forIdentifier: id) {
                types[key] = (type, unit)
            }
        }
        return types
    }

    @objc func healthAvailable(_ call: CAPPluginCall) {
        call.resolve(["available": healthBuiltIn])
    }

    @objc func healthRequest(_ call: CAPPluginCall) {
        guard healthBuiltIn else {
            call.reject("Apple Health isn't available on this device.", "unavailable")
            return
        }
        let share = Set(nutritionTypes.values.map { $0.0 as HKSampleType })
        healthStore.requestAuthorization(toShare: share, read: nil) { done, error in
            if let error = error {
                call.reject("Couldn't ask for Health access: \(error.localizedDescription)", "error")
                return
            }
            let energy = self.nutritionTypes["kcal"]!.0
            let allowed = self.healthStore.authorizationStatus(for: energy) == .sharingAuthorized
            call.resolve(["requested": done, "allowed": allowed])
        }
    }

    /// Writes one day's totals. Each value gets a stable sync identifier per user and day,
    /// so saving the same day again replaces the earlier sample instead of adding to it.
    @objc func healthSaveDay(_ call: CAPPluginCall) {
        guard healthBuiltIn else {
            call.reject("Apple Health isn't available on this device.", "unavailable")
            return
        }
        guard let dateString = call.getString("date"), let start = Self.dayStart(dateString) else {
            call.reject("Expected a date like 2026-10-14.", "bad_input")
            return
        }
        let user = call.getString("user") ?? "me"
        let now = Date()
        if start > now {
            call.resolve(["saved": 0])  // future days aren't written
            return
        }
        let dayEnd = Calendar.current.date(byAdding: .day, value: 1, to: start)!.addingTimeInterval(-1)
        let end = min(dayEnd, now)
        let version = NSNumber(value: Int(now.timeIntervalSince1970))

        var samples: [HKQuantitySample] = []
        for (key, (type, unit)) in nutritionTypes {
            guard let value = call.getDouble(key), value >= 0 else { continue }
            guard healthStore.authorizationStatus(for: type) == .sharingAuthorized else { continue }
            let metadata: [String: Any] = [
                HKMetadataKeySyncIdentifier: "local-tracker-\(user)-\(dateString)-\(key)",
                HKMetadataKeySyncVersion: version,
            ]
            samples.append(HKQuantitySample(
                type: type, quantity: HKQuantity(unit: unit, doubleValue: value),
                start: start, end: end, metadata: metadata))
        }
        if samples.isEmpty {
            call.reject("LoCal isn't allowed to write to Apple Health. Turn it on in the Health app → Sharing → Apps → LoCal.", "denied")
            return
        }
        healthStore.save(samples) { ok, error in
            if ok {
                call.resolve(["saved": samples.count])
            } else {
                call.reject("Couldn't save to Apple Health: \(error?.localizedDescription ?? "unknown error")", "error")
            }
        }
    }

    @objc func appInfo(_ call: CAPPluginCall) {
        let info = Bundle.main.infoDictionary ?? [:]
        call.resolve([
            "version": info["CFBundleShortVersionString"] as? String ?? "",
            "build": info["CFBundleVersion"] as? String ?? "",
        ])
    }

    private static func dayStart(_ s: String) -> Date? {
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = .current
        f.dateFormat = "yyyy-MM-dd"
        guard let d = f.date(from: s) else { return nil }
        return Calendar.current.startOfDay(for: d)
    }
}

// MARK: - Scanner screen

final class ScannerViewController: UIViewController, AVCaptureMetadataOutputObjectsDelegate {
    var onFinish: ((String?) -> Void)?

    private let session = AVCaptureSession()
    private let sessionQueue = DispatchQueue(label: "local-tracker.scanner")
    private var previewLayer: AVCaptureVideoPreviewLayer?
    private var device: AVCaptureDevice?
    private var finished = false
    private var setupFailed = false
    private let torchButton = UIButton(type: .system)

    override var preferredStatusBarStyle: UIStatusBarStyle { .lightContent }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black

        guard let device = AVCaptureDevice.default(for: .video),
              let input = try? AVCaptureDeviceInput(device: device),
              session.canAddInput(input) else {
            setupFailed = true
            return
        }
        self.device = device
        session.beginConfiguration()
        session.sessionPreset = .high
        session.addInput(input)
        let output = AVCaptureMetadataOutput()
        guard session.canAddOutput(output) else {
            session.commitConfiguration()
            setupFailed = true
            return
        }
        session.addOutput(output)
        output.setMetadataObjectsDelegate(self, queue: .main)
        let wanted: [AVMetadataObject.ObjectType] = [.ean13, .ean8, .upce, .code128]
        output.metadataObjectTypes = wanted.filter { output.availableMetadataObjectTypes.contains($0) }
        session.commitConfiguration()

        if (try? device.lockForConfiguration()) != nil {
            if device.isAutoFocusRangeRestrictionSupported { device.autoFocusRangeRestriction = .near }
            if device.isFocusModeSupported(.continuousAutoFocus) { device.focusMode = .continuousAutoFocus }
            device.unlockForConfiguration()
        }

        let layer = AVCaptureVideoPreviewLayer(session: session)
        layer.videoGravity = .resizeAspectFill
        layer.frame = view.bounds
        view.layer.addSublayer(layer)
        previewLayer = layer

        buildOverlay(hasTorch: device.hasTorch)
    }

    private func buildOverlay(hasTorch: Bool) {
        let aim = UIView()
        aim.translatesAutoresizingMaskIntoConstraints = false
        aim.layer.borderColor = UIColor.white.cgColor
        aim.layer.borderWidth = 3
        aim.layer.cornerRadius = 14
        view.addSubview(aim)

        let label = UILabel()
        label.translatesAutoresizingMaskIntoConstraints = false
        label.text = "Point the camera at the barcode"
        label.textColor = .white
        label.font = .systemFont(ofSize: 17, weight: .semibold)
        label.textAlignment = .center
        view.addSubview(label)

        let cancel = UIButton(type: .system)
        cancel.translatesAutoresizingMaskIntoConstraints = false
        cancel.setTitle("Cancel", for: .normal)
        cancel.titleLabel?.font = .systemFont(ofSize: 18, weight: .semibold)
        cancel.tintColor = .white
        cancel.backgroundColor = UIColor(white: 0, alpha: 0.45)
        cancel.layer.cornerRadius = 24
        cancel.contentEdgeInsets = UIEdgeInsets(top: 12, left: 28, bottom: 12, right: 28)
        cancel.addTarget(self, action: #selector(cancelTapped), for: .touchUpInside)
        view.addSubview(cancel)

        var constraints = [
            aim.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            aim.centerYAnchor.constraint(equalTo: view.centerYAnchor, constant: -40),
            aim.widthAnchor.constraint(equalTo: view.widthAnchor, multiplier: 0.78),
            aim.heightAnchor.constraint(equalTo: aim.widthAnchor, multiplier: 0.45),
            label.topAnchor.constraint(equalTo: aim.bottomAnchor, constant: 20),
            label.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 16),
            label.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -16),
            cancel.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -24),
            cancel.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 24),
        ]

        if hasTorch {
            torchButton.translatesAutoresizingMaskIntoConstraints = false
            torchButton.setTitle("Light", for: .normal)
            torchButton.titleLabel?.font = .systemFont(ofSize: 18, weight: .semibold)
            torchButton.tintColor = .white
            torchButton.backgroundColor = UIColor(white: 0, alpha: 0.45)
            torchButton.layer.cornerRadius = 24
            torchButton.contentEdgeInsets = UIEdgeInsets(top: 12, left: 28, bottom: 12, right: 28)
            torchButton.addTarget(self, action: #selector(torchTapped), for: .touchUpInside)
            view.addSubview(torchButton)
            constraints += [
                torchButton.bottomAnchor.constraint(equalTo: cancel.bottomAnchor),
                torchButton.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -24),
            ]
        }
        NSLayoutConstraint.activate(constraints)
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        previewLayer?.frame = view.bounds
    }

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        if setupFailed {
            finish(nil)
            return
        }
        sessionQueue.async { [session] in
            if !session.isRunning { session.startRunning() }
        }
    }

    override func viewWillDisappear(_ animated: Bool) {
        super.viewWillDisappear(animated)
        setTorch(false)
        sessionQueue.async { [session] in
            if session.isRunning { session.stopRunning() }
        }
    }

    func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput metadataObjects: [AVMetadataObject],
                        from connection: AVCaptureConnection) {
        guard !finished,
              let object = metadataObjects.first as? AVMetadataMachineReadableCodeObject,
              let code = object.stringValue, !code.isEmpty else { return }
        UINotificationFeedbackGenerator().notificationOccurred(.success)
        finish(code)
    }

    @objc private func cancelTapped() { finish(nil) }

    @objc private func torchTapped() {
        guard let device = device, device.hasTorch else { return }
        setTorch(device.torchMode != .on)
    }

    private func setTorch(_ on: Bool) {
        guard let device = device, device.hasTorch, (try? device.lockForConfiguration()) != nil else { return }
        device.torchMode = on ? .on : .off
        device.unlockForConfiguration()
        torchButton.setTitle(on ? "Light off" : "Light", for: .normal)
    }

    private func finish(_ code: String?) {
        guard !finished else { return }
        finished = true
        let callback = onFinish
        dismiss(animated: true) { callback?(code) }
    }
}
