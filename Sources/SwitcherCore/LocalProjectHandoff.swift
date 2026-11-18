import Foundation
#if canImport(CryptoKit)
import CryptoKit
#endif

// Compatibility for the account-scoped renderer format. New Desktop formats
// manage local projects themselves and are deliberately left untouched.
enum LocalProjectHandoff {
    static let rendererKey = "electron-account-renderer-state-v1"

    static func prepare(_ bytes: Data, sourceOwner: String, targetOwner: String) throws -> Data? {
        guard sourceOwner != targetOwner,
              var state = try JSONSerialization.jsonObject(with: bytes) as? [String: Any],
              var renderer = state[rendererKey] as? [String: Any],
              renderer["owner"] as? String == sourceOwner,
              var inactive = renderer["inactive"] as? [String: Any],
              let projects = state["local-projects"] as? [String: Any], !projects.isEmpty
        else { return nil }

        guard inactive[targetOwner] == nil || inactive[targetOwner] is [String: Any] else { return nil }
        var snapshot = inactive[targetOwner] as? [String: Any] ?? [:]
        guard snapshot["globals"] == nil || snapshot["globals"] is [String: Any] else { return nil }
        var globals = snapshot["globals"] as? [String: Any] ?? [:]
        let originalGlobals = globals as NSDictionary
        guard globals["local-projects"] == nil || globals["local-projects"] is [String: Any],
              globals["thread-project-assignments"] == nil || globals["thread-project-assignments"] is [String: String]
        else { return nil }
        var targetProjects = globals["local-projects"] as? [String: Any] ?? [:]
        var imported = Set<String>()
        var eligible = Set<String>()
        for (id, project) in projects {
            // Cloud-backed projects must retain their original account ownership.
            guard !id.hasPrefix("g-p-"), let record = project as? [String: Any],
                  let roots = record["rootPaths"] as? [String], !roots.isEmpty,
                  record["chatGptBacking"] == nil || record["chatGptBacking"] is NSNull,
                  record["backing"] == nil, record["chatgptAccountId"] == nil,
                  record["accountId"] == nil else { continue }
            if let existing = targetProjects[id] as? [String: Any] {
                guard existing["rootPaths"] as? [String] == roots,
                      existing["chatGptBacking"] == nil || existing["chatGptBacking"] is NSNull else { continue }
            } else if targetProjects.values.contains(where: { other in
                guard let other = other as? [String: Any], let paths = other["rootPaths"] as? [String] else { return false }
                return !Set(paths).isDisjoint(with: roots)
            }) { continue }
            eligible.insert(id)
            guard targetProjects[id] == nil else { continue }
            targetProjects[id] = project
            imported.insert(id)
        }
        // Copy assignments only for compatible local projects. Existing target
        // assignments (including deliberate moves) always win.
        guard !eligible.isEmpty else { return nil }
        let assignments = state["thread-project-assignments"] as? [String: String] ?? [:]
        var targetAssignments = globals["thread-project-assignments"] as? [String: String] ?? [:]
        let projectless = Set(globals["projectless-thread-ids"] as? [String] ?? [])
        for (thread, project) in assignments where eligible.contains(project) && targetAssignments[thread] == nil && !projectless.contains(thread) {
            targetAssignments[thread] = project
        }
        globals["local-projects"] = targetProjects
        globals["thread-project-assignments"] = targetAssignments
        var order = globals["project-order"] as? [String] ?? []
        for id in (state["project-order"] as? [String] ?? []).filter({ imported.contains($0) }) where !order.contains(id) {
            order.append(id)
        }
        for id in imported.sorted() where !order.contains(id) { order.append(id) }
        globals["project-order"] = order
        for key in ["app-server-project-id-by-legacy-project-id-by-host", "thread-workspace-root-hints", "thread-project-membership-host-ids", "sidebar-project-thread-orders"] {
            // These maps can have a host level. Merge missing keys recursively;
            // target values are authoritative wherever both sides have a value.
            if let source = state[key] as? [String: Any] {
                let allowed = key == "thread-workspace-root-hints" || key == "thread-project-membership-host-ids"
                    ? Set(assignments.filter { eligible.contains($0.value) }.keys) : eligible
                globals[key] = mergeMissing(filtered(source, allowed: allowed), into: globals[key] as? [String: Any] ?? [:])
            }
        }
        guard !originalGlobals.isEqual(to: globals) else { return nil }
        snapshot["globals"] = globals
        inactive[targetOwner] = snapshot
        renderer["inactive"] = inactive
        state[rendererKey] = renderer
        return try JSONSerialization.data(withJSONObject: state, options: [.sortedKeys])
    }

    private static func filtered(_ source: [String: Any], allowed: Set<String>) -> [String: Any] {
        var result: [String: Any] = [:]
        for (key, value) in source {
            if allowed.contains(key) { result[key] = value }
            else if let nested = value as? [String: Any] {
                let kept = filtered(nested, allowed: allowed)
                if !kept.isEmpty { result[key] = kept }
            }
        }
        return result
    }

    private static func mergeMissing(_ source: [String: Any], into target: [String: Any]) -> [String: Any] {
        var result = target
        for (key, value) in source {
            if result[key] == nil { result[key] = value }
            else if let nested = value as? [String: Any], let existing = result[key] as? [String: Any] {
                result[key] = mergeMissing(nested, into: existing)
            }
        }
        return result
    }

    #if canImport(CryptoKit)
    static func owner(credential: Data) throws -> String? {
        guard let auth = try JSONSerialization.jsonObject(with: credential) as? [String: Any],
              let tokens = auth["tokens"] as? [String: Any],
              let token = tokens["id_token"] as? String else { return nil }
        let parts = token.split(separator: ".", omittingEmptySubsequences: false)
        guard parts.count == 3 else { return nil }
        var encoded = String(parts[1]).replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        encoded += String(repeating: "=", count: (4 - encoded.count % 4) % 4)
        guard let data = Data(base64Encoded: encoded),
              let claims = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let identity = claims["https://api.openai.com/auth"] as? [String: Any],
              let user = identity["chatgpt_user_id"] as? String,
              let account = tokens["account_id"] as? String ?? identity["chatgpt_account_id"] as? String else { return nil }
        let key = try JSONSerialization.data(withJSONObject: [user, account], options: [.withoutEscapingSlashes])
        return SHA256.hash(data: key).map { String(format: "%02x", $0) }.joined()
    }
    #endif
}
