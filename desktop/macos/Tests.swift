import Foundation

enum TestFailure: Error { case failed(String) }
func check(_ value: @autoclosure () -> Bool, _ message: String) throws {
    if !value() { throw TestFailure.failed(message) }
}
final class MockTransport: HTTPTransport {
    var replies: [(Int, [String: Any])]
    var requests: [URLRequest] = []
    init(_ replies: [(Int, [String: Any])]) { self.replies = replies }
    func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        requests.append(request)
        guard !replies.isEmpty else { throw TestFailure.failed("Unexpected extra network request") }
        let (status, body) = replies.removeFirst()
        return (try JSONSerialization.data(withJSONObject: body),
                HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: "HTTP/1.1", headerFields: nil)!)
    }
}

@main struct Tests {
    static let quota: [String: Any] = ["planName": "Test Home", "balances": [
        ["name": "Data", "originalBalance": "1000 GB", "consumed": "22.7 GB", "balance": "977.3 GB", "category": "DATA"],
        ["name": "Calls", "originalBalance": "100", "balance": "90", "type": "VOICE"],
        ["name": "Extra", "members": [["name": "Roaming data", "balance": "1024000"]]]
    ]]

    @MainActor static func main() async throws {
        var passed: [String] = []
        let transport = MockTransport([(200, ["data": ["accessToken": "A", "refreshToken": "R", "expiresIn": 3600]])])
        let api = APIClient(transport: transport)
        let result = try await api.login(email: "test@example.invalid", password: "unchanged + password", deviceID: "DEVICE-UUID")
        let request = transport.requests[0]
        let body = try JSONSerialization.jsonObject(with: request.httpBody!) as! [String: Any]
        try check(request.url!.absoluteString == "https://api-myumobileapp.u.com.my/mobile/auth/v1/auth/login/email", "Login URL")
        try check(request.httpMethod == "POST", "Login method")
        try check(body["password"] as? String == "unchanged + password", "Unchanged password")
        try check(Set(body.keys) == Set(["email", "password", "deviceId", "deviceInfo"]), "Login wire fields")
        let info = body["deviceInfo"] as! [String: Any]
        try check(info["platform"] as? String == "IOS", "Platform literal")
        try check(Set(info.keys) == Set(["platform", "osVersion", "appVersion", "manufacturer", "model"]), "Device info object")
        try check(request.value(forHTTPHeaderField: "Authorization") == nil, "No bearer on login")
        try check(request.value(forHTTPHeaderField: "Cookie") == nil, "No cookie on login")
        try check(TokenSession.parse(result)?.refreshToken == "R", "Nested login envelope")
        try check(TokenSession.parse(["accessToken": "A", "refreshToken": "R"]) != nil, "Flat login envelope")
        try check(TokenSession.parse(["status": "PENDING", "secretToken": "S"]) == nil, "Approval is not authentication")
        passed.append("login payload, headers, envelopes, and pending approval")

        let retry = MockTransport([(401, ["message": "Unauthorized"]), (200, ["data": ["accessToken": "NEW-A", "refreshToken": "NEW-R"]]), (200, ["data": quota])])
        let retryAPI = APIClient(transport: retry)
        var current = TokenSession(accessToken: "OLD-A", refreshToken: "OLD-R")
        var saved: TokenSession?
        let snapshot = try await retryAPI.balance(session: &current) { value in
            try check(retry.requests.count == 2, "Persist rotation before retry")
            saved = value
        }
        try check(retry.requests.count == 3, "One refresh and retry")
        try check(retry.requests[1].value(forHTTPHeaderField: "Authorization") == nil, "Refresh has no bearer")
        let refreshBody = try JSONSerialization.jsonObject(with: retry.requests[1].httpBody!) as! [String: String]
        try check(refreshBody == ["refreshToken": "OLD-R"], "Refresh wire body")
        try check(retry.requests[2].value(forHTTPHeaderField: "Authorization") == "Bearer NEW-A", "Rotated bearer")
        try check(current.refreshToken == "NEW-R" && saved?.refreshToken == "NEW-R", "Rotated refresh persisted")
        try check(retry.requests[2].httpBody == nil, "Balance GET has no body")
        try check(snapshot.pools.count == 3 && snapshot.pools[0].remaining == "977.3 GB", "Balance parse")
        try check(snapshot.pools[2].remaining == "1024000", "Unknown units preserved")
        try check(snapshot.pools[0].isData && !snapshot.pools[1].isData, "Data pool identification")
        passed.append("401 recovery, token rotation ordering, nested balances, and unchanged units")

        let expired = MockTransport([(200, ["accessToken": "B", "refreshToken": "S"]), (200, quota)])
        var old = TokenSession(accessToken: "A", refreshToken: "R", expiresAt: Date(timeIntervalSinceNow: -1))
        _ = try await APIClient(transport: expired).balance(session: &old) { _ in }
        try check(expired.requests[0].url!.path.hasSuffix("/refresh"), "Preemptive refresh")
        passed.append("expired token refreshed before requesting quota")

        let rejected = MockTransport([(401, [:]), (200, ["accessToken": "B", "refreshToken": "S"]), (401, [:])])
        var stale = TokenSession(accessToken: "A", refreshToken: "R")
        do {
            _ = try await APIClient(transport: rejected).balance(session: &stale) { _ in }
            throw TestFailure.failed("Should reject final 401")
        } catch let e as APIProblem { try check(e.status == 401, "Final rejection") }
        try check(rejected.requests.count == 3, "No retry loop")
        try check(stale.refreshToken == "S", "Retain rotated token after failed retry")
        passed.append("bounded refresh attempts and retained rotation on failure")

        let wrappedError = MockTransport([(200, ["statusCode": 403, "message": "Device approval required"])])
        do {
            _ = try await APIClient(transport: wrappedError).login(email: "x", password: "y", deviceID: "z")
            throw TestFailure.failed("Should reject application error")
        } catch let e as APIProblem { try check(e.status == 403, "Application status respected") }
        do { _ = try BalanceSnapshot.parse(["data": ["unknown": 1]]); throw TestFailure.failed("Invented quota") }
        catch let e as APIProblem { try check(e.status == 200, "Unfamiliar balance handled") }
        passed.append("application errors and unfamiliar quota responses")

        let diagnostic = APIClient.shape(["accessToken": "SECRET-ACCESS", "data": ["email": "PRIVATE-EMAIL", "secretToken": "PRIVATE-SECRET"]])
        let encoded = String(data: try JSONSerialization.data(withJSONObject: diagnostic), encoding: .utf8)!
        try check(!encoded.contains("SECRET-ACCESS") && !encoded.contains("PRIVATE-"), "No diagnostic secret values")
        var redirected: URLRequest? = URLRequest(url: URL(string: "https://example.invalid")!)
        let direct = DirectTransport()
        direct.urlSession(URLSession.shared, task: URLSession.shared.dataTask(with: APIClient.baseURL),
            willPerformHTTPRedirection: HTTPURLResponse(url: APIClient.baseURL, statusCode: 302, httpVersion: nil, headerFields: nil)!,
            newRequest: redirected!) { redirected = $0 }
        try check(redirected == nil, "Redirects rejected")
        passed.append("value-free diagnostics and rejected credential redirects")

        let approvalTransport = MockTransport([(200, ["data": ["sessionId": "SESSION", "sseToken": "SSE", "expiresIn": 120]]),
            (200, ["data": ["approved": true, "status": "APPROVED"]]),
            (200, ["data": ["accessToken": "ACCESS", "refreshToken": "REFRESH"]]),
            (200, ["data": ["accessToken": "ACCESS", "refreshToken": "REFRESH"]])])
        let approvalAPI = APIClient(transport: approvalTransport)
        _ = try await approvalAPI.requestApproval(secret: "BIND-SECRET", deviceID: "DEVICE", type: "PRIMARY")
        _ = try await approvalAPI.pollApproval(secret: "BIND-SECRET", deviceID: "DEVICE", sessionID: "SESSION")
        _ = try await approvalAPI.completeApproval(secret: "BIND-SECRET", deviceID: "DEVICE", sessionID: "SESSION")
        _ = try await approvalAPI.verifyTAC(secret: "BIND-SECRET", deviceID: "DEVICE", sessionID: "SESSION", code: "123456")
        for request in approvalTransport.requests {
            try check(request.httpMethod == "POST", "Approval uses POST")
            try check(request.value(forHTTPHeaderField: "Authorization") == "Bearer BIND-SECRET", "Approval secret bearer")
        }
        let approvalBodies = try approvalTransport.requests.map { try JSONSerialization.jsonObject(with: $0.httpBody!) as! [String: Any] }
        try check(Set(approvalBodies[0].keys) == Set(["deviceId", "platform", "osVersion", "appVersion", "manufacturer", "model", "type"]), "Flat approval metadata")
        try check(approvalBodies[0]["type"] as? String == "PRIMARY", "Primary approval mode")
        try check(Set(approvalBodies[1].keys) == Set(["deviceId", "sessionId"]), "Poll body")
        try check(Set(approvalBodies[2].keys) == Set(["deviceId", "sessionId"]), "Complete body")
        try check(Set(approvalBodies[3].keys) == Set(["deviceId", "sessionId", "code"]), "No unsolicited removal or primary change")
        passed.append("device approval bodies, secret-token authorization, and bounded account changes")

        let realPool = BalancePool(id: "live-format-fixture", name: "ULTRA Home 5G", total: "1073741824000", used: "4294967296",
            remaining: "1069446856704", expiry: nil, type: "DATA", category: "PLAN")
        try check(realPool.display(realPool.used) == "4.00 GB", "iPhone-verified byte conversion")
        try check(realPool.display(realPool.remaining) == "996.00 GB", "Remaining GB")
        try check(realPool.display("Unlimited") == "Unlimited", "Non-numeric quota preserved")
        try check(snapshot.pools[1].display("90") == "90", "No conversion of non-data balance")
        try check(realPool.usedFraction != nil, "Usage progress")
        let reversed = try BalanceSnapshot.parse(["balances": (quota["balances"] as! [[String: Any]]).reversed().map { $0 }])
        try check(snapshot.pools.first { $0.name == "Data" }?.id == reversed.pools.first { $0.name == "Data" }?.id, "Pool identity survives reordering")
        passed.append("iPhone-verified GB formatting and stable balance selection")

        let report: [String: Any] = ["passed": true, "groups": passed, "liveAuthenticationTested": false,
            "time": ISO8601DateFormatter().string(from: Date())]
        print(String(data: try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]), encoding: .utf8)!)
    }
}
