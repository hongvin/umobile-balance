import Foundation
import Security

struct SavedIdentity: Codable {
    var deviceID: String
    var session: TokenSession?
    var selectedPoolID: String?
}

enum SecureStore {
    static let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: "local.hongvin.umobile-widget",
        kSecAttrAccount as String: "session-v1"]

    static func load() throws -> SavedIdentity? {
        var query = self.query
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = result as? Data else { throw failure(status) }
        return try JSONDecoder().decode(SavedIdentity.self, from: data)
    }

    static func save(_ value: SavedIdentity) throws {
        let data = try JSONEncoder().encode(value)
        let update = [kSecValueData as String: data]
        let status = SecItemUpdate(query as CFDictionary, update as CFDictionary)
        if status == errSecItemNotFound {
            var add = query
            add[kSecValueData as String] = data
            add[kSecAttrLabel as String] = "U Mobile Widget session"
            add[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
            let added = SecItemAdd(add as CFDictionary, nil)
            guard added == errSecSuccess else { throw failure(added) }
        } else if status != errSecSuccess { throw failure(status) }
    }

    static func failure(_ status: OSStatus) -> NSError {
        NSError(domain: "UMobileWidget.Keychain", code: Int(status), userInfo: [NSLocalizedDescriptionKey:
            "Keychain: \(SecCopyErrorMessageString(status, nil) as String? ?? String(status))"])
    }
}
