import Foundation

struct DeviceInfo: Codable {
    var platform = "IOS" // The installed iOS-on-Mac app uses this protocol value.
    var osVersion: String = {
        let v = ProcessInfo.processInfo.operatingSystemVersion
        return "\(v.majorVersion).\(v.minorVersion).\(v.patchVersion)"
    }()
    var appVersion = "4.0.2"
    var manufacturer = "Apple"
    var model = "Mac"
}

struct TokenSession: Codable {
    var accessToken: String
    var refreshToken: String
    var expiresAt: Date?

    static func parse(_ object: [String: Any], previousRefresh: String? = nil) -> TokenSession? {
        let data = APIClient.unwrap(object)
        guard let access = data["accessToken"] as? String, !access.isEmpty,
              let refresh = (data["refreshToken"] as? String) ?? previousRefresh, !refresh.isEmpty else { return nil }
        let seconds = (data["expiresIn"] as? NSNumber)?.doubleValue ?? Double(data["expiresIn"] as? String ?? "")
        return TokenSession(accessToken: access, refreshToken: refresh,
                            expiresAt: seconds.flatMap { $0 > 0 ? Date().addingTimeInterval($0) : nil })
    }
}

struct APIProblem: LocalizedError {
    let status: Int
    let message: String
    let payload: [String: Any]
    var errorDescription: String? { "HTTP \(status): \(message)" }
}

protocol HTTPTransport {
    func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse)
}

final class DirectTransport: NSObject, HTTPTransport, URLSessionTaskDelegate {
    private lazy var session: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.httpCookieAcceptPolicy = .never
        config.httpShouldSetCookies = false
        config.urlCache = nil
        config.timeoutIntervalForRequest = 25
        config.timeoutIntervalForResource = 40
        return URLSession(configuration: config, delegate: self, delegateQueue: nil)
    }()

    func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        let (data, response) = try await session.data(for: request)
        guard let response = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
        return (data, response)
    }

    // Never forward credentials or tokens to a redirect destination.
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
                    completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }
}

struct BalancePool: Identifiable, Codable {
    let id: String
    let name: String
    let total: String?
    let used: String?
    let remaining: String?
    let expiry: String?
    let type: String?
    let category: String?

    var isData: Bool {
        let s = [name, type ?? "", category ?? ""].joined(separator: " ").lowercased()
        return ["data", "internet", "broadband", "5g", "quota"].contains { s.contains($0) }
    }

    func display(_ quantity: String?) -> String {
        guard let quantity else { return "—" }
        // MyUMobile uses bytes / 2^30 and labels the result GB.
        guard type?.uppercased() == "DATA", let bytes = Double(quantity), bytes.isFinite, bytes >= 0 else { return quantity }
        return String(format: "%.2f GB", locale: Locale(identifier: "en_US_POSIX"), bytes / 1_073_741_824)
    }

    var usedFraction: Double? {
        guard type?.uppercased() == "DATA", let used = Double(used ?? ""), let total = Double(total ?? ""),
              total > 0, used >= 0, used <= total else { return nil }
        return used / total
    }
}

struct BalanceSnapshot: Codable {
    let plan: String
    let pools: [BalancePool]
    let updatedAt: Date

    static func parse(_ object: [String: Any]) throws -> BalanceSnapshot {
        let data = APIClient.unwrap(object)
        guard let balances = data["balances"] as? [[String: Any]] else {
            throw APIProblem(status: 200, message: "The balance response has an unfamiliar format. No quota has been inferred.", payload: object)
        }
        var pools: [BalancePool] = []
        func text(_ row: [String: Any], _ key: String) -> String? {
            if let s = row[key] as? String, !s.isEmpty { return s }
            if let n = row[key] as? NSNumber { return n.stringValue }
            return nil
        }
        func add(_ row: [String: Any], path: String, fallback: String, ordinal: Int) {
            let name = text(row, "name") ?? text(row, "offerName") ?? fallback
            let identity = [text(row, "code"), text(row, "offerCode"), text(row, "name")].compactMap { $0 }.joined(separator: "|")
            let poolID = path + "/" + (identity.isEmpty ? String(ordinal) : identity)
            let total = text(row, "originalBalance"), used = text(row, "consumed"), remaining = text(row, "balance")
            if total != nil || used != nil || remaining != nil {
                pools.append(BalancePool(id: poolID, name: name, total: total, used: used, remaining: remaining,
                    expiry: text(row, "expirationDate"), type: text(row, "type"), category: text(row, "category")))
            }
            for (i, child) in ((row["members"] as? [[String: Any]]) ?? []).enumerated() {
                add(child, path: poolID, fallback: name, ordinal: i)
            }
        }
        for (i, row) in balances.enumerated() { add(row, path: "", fallback: "Balance \(i + 1)", ordinal: i) }
        return BalanceSnapshot(plan: data["planName"] as? String ?? "U Mobile", pools: pools, updatedAt: Date())
    }
}

@MainActor final class APIClient {
    nonisolated static let baseURL = URL(string: "https://api-myumobileapp.u.com.my/mobile")!
    let transport: HTTPTransport
    var record: (([String: Any]) -> Void)?

    init(transport: HTTPTransport = DirectTransport()) { self.transport = transport }
    nonisolated static func unwrap(_ object: [String: Any]) -> [String: Any] { object["data"] as? [String: Any] ?? object }

    nonisolated static func shape(_ object: [String: Any], depth: Int = 0) -> [String: Any] {
        object.mapValues { value in
            if let row = value as? [String: Any], depth < 2 { return shape(row, depth: depth + 1) }
            if let rows = value as? [Any] {
                if let row = rows.first as? [String: Any], depth < 2 { return [shape(row, depth: depth + 1)] }
                return "array(\(rows.count))"
            }
            if value is NSNull { return "null" }
            if value is String { return "string" }
            if value is NSNumber { return "number/bool" }
            return "object"
        }
    }

    func request(_ path: String, method: String, body: [String: Any]? = nil, bearer: String? = nil) async throws -> [String: Any] {
        let allowed = ["/auth/v1/auth/login/email", "/auth/v1/auth/refresh", "/user/v1/balance",
            "/auth/v1/device/request-confirm", "/auth/v1/device/poll-result", "/auth/v1/device/complete", "/auth/v1/device/approve-by-tac"]
        guard allowed.contains(path) else { throw URLError(.unsupportedURL) }
        var request = URLRequest(url: URL(string: Self.baseURL.absoluteString + path)!)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("en", forHTTPHeaderField: "Accept-Language")
        if let body {
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        if let bearer { request.setValue("Bearer " + bearer, forHTTPHeaderField: "Authorization") }
        let response: HTTPURLResponse, bytes: Data
        do { (bytes, response) = try await transport.send(request) }
        catch {
            record?(["path": path, "method": method, "networkError": (error as NSError).code])
            throw error
        }
        let object = (try? JSONSerialization.jsonObject(with: bytes)) as? [String: Any] ?? [:]
        var event: [String: Any] = ["path": path, "method": method, "httpStatus": response.statusCode,
                                    "responseShape": Self.shape(object)]
        // Only an enum-like error code is retained; response values and secrets are never logged.
        if let code = object["errorCode"] as? String, code.range(of: "^[A-Za-z_][A-Za-z0-9_ .-]{0,79}$", options: .regularExpression) != nil {
            event["errorCode"] = code
        }
        record?(event)
        let reported = (object["statusCode"] as? Int) ?? response.statusCode
        guard (200..<300).contains(response.statusCode), reported < 400 else {
            let message = (object["message"] as? String) ?? (object["message"] as? [String])?.joined(separator: "; ") ?? "Request failed"
            throw APIProblem(status: max(reported, response.statusCode), message: message, payload: object)
        }
        guard !object.isEmpty else { throw APIProblem(status: response.statusCode, message: "The server did not return JSON.", payload: [:]) }
        return object
    }

    func login(email: String, password: String, deviceID: String) async throws -> [String: Any] {
        let info = try JSONSerialization.jsonObject(with: JSONEncoder().encode(DeviceInfo()))
        return try await request("/auth/v1/auth/login/email", method: "POST",
            body: ["email": email, "password": password, "deviceId": deviceID, "deviceInfo": info])
    }

    func requestApproval(secret: String, deviceID: String, type: String) async throws -> [String: Any] {
        guard ["PRIMARY", "TAC"].contains(type) else { throw URLError(.badURL) }
        var body = try JSONSerialization.jsonObject(with: JSONEncoder().encode(DeviceInfo())) as! [String: Any]
        body["deviceId"] = deviceID; body["type"] = type
        return try await request("/auth/v1/device/request-confirm", method: "POST", body: body, bearer: secret)
    }

    func pollApproval(secret: String, deviceID: String, sessionID: String) async throws -> [String: Any] {
        try await request("/auth/v1/device/poll-result", method: "POST",
            body: ["deviceId": deviceID, "sessionId": sessionID], bearer: secret)
    }

    func completeApproval(secret: String, deviceID: String, sessionID: String) async throws -> [String: Any] {
        try await request("/auth/v1/device/complete", method: "POST",
            body: ["deviceId": deviceID, "sessionId": sessionID], bearer: secret)
    }

    func verifyTAC(secret: String, deviceID: String, sessionID: String, code: String) async throws -> [String: Any] {
        // Optional device-removal and primary-device changes are intentionally omitted.
        try await request("/auth/v1/device/approve-by-tac", method: "POST",
            body: ["deviceId": deviceID, "sessionId": sessionID, "code": code], bearer: secret)
    }

    func refresh(_ session: TokenSession) async throws -> TokenSession {
        let response = try await request("/auth/v1/auth/refresh", method: "POST", body: ["refreshToken": session.refreshToken])
        guard let next = TokenSession.parse(response, previousRefresh: session.refreshToken) else {
            throw APIProblem(status: 200, message: "The server did not return refreshed tokens. Sign in again.", payload: response)
        }
        return next
    }

    // Persist a rotated token before the next balance request, including when that request fails.
    func balance(session: inout TokenSession, onRotation: (TokenSession) throws -> Void) async throws -> BalanceSnapshot {
        var refreshed = false
        if let expiry = session.expiresAt, expiry.timeIntervalSinceNow < 45 {
            session = try await refresh(session); try onRotation(session); refreshed = true
        }
        let response: [String: Any]
        do { response = try await request("/user/v1/balance", method: "GET", bearer: session.accessToken) }
        catch let problem as APIProblem where problem.status == 401 && !refreshed {
            session = try await refresh(session); try onRotation(session)
            response = try await request("/user/v1/balance", method: "GET", bearer: session.accessToken)
        }
        return try BalanceSnapshot.parse(response)
    }
}
