import Foundation
import Combine

struct DeviceApproval {
    let secret: String
    var expiresAt: Date
    var sessionID: String?
    var mode: String?
}

@MainActor final class WidgetModel: ObservableObject {
    @Published var email = ""
    @Published var password = ""
    @Published var remember = true
    @Published var busy = false
    @Published var message = "Sign in with the email used for your U Home broadband account."
    @Published var snapshot: BalanceSnapshot?
    @Published var session: TokenSession?
    @Published var selectedPoolID: String?
    @Published var approval: DeviceApproval?
    @Published var verificationCode = ""
    @Published var waitingForApproval = false
    var initialized = false
    var signedIn: Bool { session != nil }
    var displayPools: [BalancePool] {
        let all = snapshot?.pools ?? []
        let data = all.filter { $0.isData }
        return data.isEmpty ? all : data
    }
    var pool: BalancePool? { displayPools.first { $0.id == selectedPoolID } ?? displayPools.first }
    var menuTitle: String {
        if let pool { return "U · \(pool.display(pool.remaining))" }
        return "U Mobile"
    }
    private var deviceID = UUID().uuidString
    private let api = APIClient()
    private var events: [[String: Any]] = []
    private var timer: Task<Void, Never>?
    private var approvalTimer: Task<Void, Never>?
    private let statusURL: URL? = {
        guard let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first else { return nil }
        let directory = base.appendingPathComponent("U Mobile Balance", isDirectory: true)
        do { try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
                  attributes: [.posixPermissions: 0o700]) } catch { return nil }
        return directory.appendingPathComponent("status.json")
    }()

    func start() {
        guard !initialized else { return }; initialized = true
        api.record = { [weak self] event in self?.record(event) }
        do {
            if let identity = try SecureStore.load() {
                deviceID = identity.deviceID; session = identity.session; selectedPoolID = identity.selectedPoolID
            } else { try save() }
            if signedIn { Task { await updateBalance() } }
        } catch { message = error.localizedDescription }
        timer = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(300))
                guard !Task.isCancelled else { break }
                await self?.updateBalance()
            }
        }
        writeStatus()
    }

    func signIn() async {
        guard !busy else { return }
        let inputEmail = email.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !inputEmail.isEmpty, !password.isEmpty else { message = "Enter your email and password."; return }
        busy = true; message = "Signing in…"
        let secret = password
        password = ""
        defer { busy = false; writeStatus() }
        do {
            let result = try await api.login(email: inputEmail, password: secret, deviceID: deviceID)
            guard let value = TokenSession.parse(result) else {
                let data = APIClient.unwrap(result)
                let status = data["status"] as? String ?? "Approval required"
                message = "\(status). This login needs an additional device-approval step. The response format has been recorded without its values."
                record(["stage": "login-needs-approval", "responseShape": APIClient.shape(result)])
                return
            }
            session = value
            try save()
            email = ""
            message = "Signed in. Loading balance…"
            try await fetch()
        } catch let problem as APIProblem {
            let data = APIClient.unwrap(problem.payload)
            if problem.payload["errorCode"] as? String == "LOGIN_BIND_DEVICE_VERIFY",
               let secret = data["secretToken"] as? String, !secret.isEmpty {
                let seconds = (data["expiresIn"] as? NSNumber)?.doubleValue ?? 300
                approval = DeviceApproval(secret: secret, expiresAt: Date().addingTimeInterval(max(1, seconds)))
                email = ""
                message = "Approve this Mac using MyUMobile on your primary device, or request a verification code."
                record(["stage": "device-approval-required"])
            } else { message = problem.localizedDescription; record(["stage": "login-failed"]) }
        } catch { message = error.localizedDescription; record(["stage": "login-failed"]) }
    }

    func beginApproval(_ mode: String) async {
        guard !busy, var pending = approval else { return }
        guard pending.expiresAt > Date() else { cancelApproval(); message = "Approval expired. Sign in again."; return }
        approvalTimer?.cancel(); waitingForApproval = false
        busy = true; verificationCode = ""; message = "Requesting device approval…"
        defer { busy = false; writeStatus() }
        do {
            let result = try await api.requestApproval(secret: pending.secret, deviceID: deviceID, type: mode)
            let data = APIClient.unwrap(result)
            guard let id = data["sessionId"] as? String, !id.isEmpty else {
                throw APIProblem(status: 200, message: "The approval response did not include a session ID.", payload: result)
            }
            pending.sessionID = id; pending.mode = mode
            if let seconds = (data["expiresIn"] as? NSNumber)?.doubleValue, seconds > 0 {
                pending.expiresAt = min(pending.expiresAt, Date().addingTimeInterval(seconds))
            }
            approval = pending
            if mode == "PRIMARY" {
                waitingForApproval = true
                message = "Open MyUMobile on your primary device and approve this Mac. Waiting for approval…"
                approvalTimer = Task { [weak self] in
                    while !Task.isCancelled {
                        do { try await Task.sleep(for: .seconds(10)) } catch { break }
                        guard let self, self.waitingForApproval, self.approval != nil else { break }
                        await self.checkApproval()
                    }
                }
            } else { message = "Enter the verification code sent by U Mobile. Check the broadband SIM’s messages if necessary." }
            record(["stage": "device-approval-requested", "mode": mode])
        } catch { message = error.localizedDescription; record(["stage": "device-approval-request-failed"]) }
    }

    func checkApproval() async {
        guard !busy, let pending = approval, let id = pending.sessionID else { return }
        guard pending.expiresAt > Date() else { cancelApproval(); message = "Approval expired. Sign in again."; return }
        busy = true
        defer { busy = false; writeStatus() }
        do {
            let result = try await api.pollApproval(secret: pending.secret, deviceID: deviceID, sessionID: id)
            let data = APIClient.unwrap(result)
            let status = (data["status"] as? String ?? "").uppercased()
            if data["approved"] as? Bool == true {
                waitingForApproval = false
                let completed = try await api.completeApproval(secret: pending.secret, deviceID: deviceID, sessionID: id)
                try await acceptApproval(completed)
            } else if data["pending"] as? Bool == false || ["REJECTED", "DENIED", "EXPIRED", "CANCELLED"].contains(status) {
                waitingForApproval = false; message = "Device approval was declined or ended. You can request approval again."
            }
        } catch {
            waitingForApproval = false
            message = error.localizedDescription
            record(["stage": "device-approval-check-failed"])
        }
    }

    func submitCode() async {
        guard !busy, let pending = approval, let id = pending.sessionID else { return }
        let code = verificationCode.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !code.isEmpty else { return }
        guard pending.expiresAt > Date() else { cancelApproval(); message = "Approval expired. Sign in again."; return }
        busy = true; verificationCode = ""
        defer { busy = false; writeStatus() }
        do {
            let result = try await api.verifyTAC(secret: pending.secret, deviceID: deviceID, sessionID: id, code: code)
            try await acceptApproval(result)
        } catch { message = error.localizedDescription; record(["stage": "device-code-verification-failed"]) }
    }

    private func acceptApproval(_ result: [String: Any]) async throws {
        guard let tokens = TokenSession.parse(result) else {
            let data = APIClient.unwrap(result)
            if data["maxCapacityReached"] as? Bool == true || data["status"] as? String == "PENDING_MAX" {
                message = "U Mobile’s device limit has been reached. Manage devices in MyUMobile, then try again."
            } else { message = "Approval did not return login tokens. The response format was recorded for investigation." }
            record(["stage": "approval-without-tokens", "responseShape": APIClient.shape(result)])
            return
        }
        // The poll task may be executing this method. Let its loop exit without cancelling the balance fetch.
        session = tokens; approval = nil; waitingForApproval = false
        try save()
        message = "Approved. Loading balance…"
        record(["stage": "device-approval-complete"])
        try await fetch()
    }

    func cancelApproval() {
        guard !busy else { return }
        approvalTimer?.cancel(); approval = nil; waitingForApproval = false; verificationCode = ""
        message = "Approval cancelled on this Mac. You can sign in again."
        record(["stage": "device-approval-cancelled"])
    }

    func updateBalance() async {
        guard signedIn, !busy else { return }
        busy = true
        defer { busy = false; writeStatus() }
        do { try await fetch() }
        catch { message = error.localizedDescription; record(["stage": "balance-failed"]) }
    }

    private func fetch() async throws {
        guard var current = session else { return }
        do {
            let result = try await api.balance(session: &current) { [weak self] rotated in
                guard let self else { return }
                self.session = rotated; try self.save()
            }
            session = current
            snapshot = result
            try save()
            message = result.pools.isEmpty ? "Signed in; the API returned no balance pools." : "Updated directly from U Mobile."
            record(["stage": "balance-success", "poolCount": result.pools.count])
        } catch {
            session = current
            // A failed refresh is retried only on a user action or the next timer tick.
            throw error
        }
    }

    func select(_ id: String) {
        selectedPoolID = id
        do { try save() } catch { message = error.localizedDescription }
        writeStatus()
    }

    func signOut() {
        guard !busy else { return }
        session = nil; snapshot = nil; password = ""; email = ""
        do { try save(); message = "Signed out on this Mac." }
        catch { message = error.localizedDescription }
        record(["stage": "signed-out"])
    }

    private func save() throws {
        try SecureStore.save(SavedIdentity(deviceID: deviceID, session: remember ? session : nil, selectedPoolID: selectedPoolID))
    }

    private func record(_ event: [String: Any]) {
        var event = event; event["time"] = ISO8601DateFormatter().string(from: Date())
        events.append(event); events = Array(events.suffix(30)); writeStatus()
    }

    private func writeStatus() {
        guard let statusURL else { return }
        var report: [String: Any] = ["updatedAt": ISO8601DateFormatter().string(from: Date()),
            "signedIn": signedIn, "busy": busy, "events": events,
            "deviceApprovalRequired": approval != nil, "waitingForApproval": waitingForApproval,
            "credentialsLogged": false, "transport": "direct HTTPS; standard certificate validation"]
        let encoder = JSONEncoder(); encoder.dateEncodingStrategy = .iso8601
        if let snapshot, let encoded = try? encoder.encode(snapshot), var value = (try? JSONSerialization.jsonObject(with: encoded)) as? [String: Any] {
            value["pools"] = displayPools.map { pool -> [String: Any] in
                var row: [String: Any] = ["id": pool.id, "name": pool.name,
                    "displayRemaining": pool.display(pool.remaining), "displayUsed": pool.display(pool.used), "displayTotal": pool.display(pool.total)]
                row["remaining"] = pool.remaining; row["used"] = pool.used; row["total"] = pool.total
                row["type"] = pool.type; row["category"] = pool.category; row["expiry"] = pool.expiry
                return row
            }
            report["balance"] = value
        }
        guard let bytes = try? JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]) else { return }
        try? bytes.write(to: statusURL, options: .atomic)
        try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: statusURL.path)
    }
}
