@testable import SwitcherCore
import Foundation
import Testing

struct LocalProjectHandoffTests {
    @Test func excludesCloudBackingsAndDuplicateRoots() throws {
        let state: [String: Any] = [
            "local-projects": [
                "cloud": ["rootPaths": ["/cloud"], "chatGptBacking": ["accountId": "a"]],
                "duplicate": ["rootPaths": ["/same"]],
            ],
            LocalProjectHandoff.rendererKey: ["owner": "a", "inactive": [
                "b": ["globals": ["local-projects": ["original": ["rootPaths": ["/same"]]]]],
            ]],
        ]
        let bytes = try JSONSerialization.data(withJSONObject: state)
        // No eligible project or assignment: no state rewrite at all.
        #expect(try LocalProjectHandoff.prepare(bytes, sourceOwner: "a", targetOwner: "b") == nil)
    }
    @Test func carriesNewChatsForExistingProjectsOnLaterSwitches() throws {
        let state: [String: Any] = [
            "local-projects": ["local": ["rootPaths": ["/local"]]],
            "thread-project-assignments": ["later-chat": "local"],
            LocalProjectHandoff.rendererKey: ["owner": "b", "inactive": [
                "a": ["globals": ["local-projects": ["local": ["rootPaths": ["/local"]]]]],
            ]],
        ]
        let result = try #require(try LocalProjectHandoff.prepare(try JSONSerialization.data(withJSONObject: state), sourceOwner: "b", targetOwner: "a"))
        let decoded = try #require(JSONSerialization.jsonObject(with: result) as? [String: Any])
        let renderer = try #require(decoded[LocalProjectHandoff.rendererKey] as? [String: Any])
        let inactive = try #require(renderer["inactive"] as? [String: Any])
        let snapshot = try #require(inactive["a"] as? [String: Any])
        let globals = try #require(snapshot["globals"] as? [String: Any])
        #expect(globals["thread-project-assignments"] as? [String: String] == ["later-chat": "local"])
    }

    @Test func preservesTargetConflictsAndSourceSnapshot() throws {
        let state: [String: Any] = [
            "local-projects": ["local": ["rootPaths": ["/local"]], "g-p-cloud": ["rootPaths": ["/cloud"]]],
            "project-order": ["local", "g-p-cloud"],
            "thread-project-assignments": ["new": "local", "moved": "local", "cloud-chat": "g-p-cloud"],
            LocalProjectHandoff.rendererKey: ["owner": "a", "inactive": [
                "b": ["atoms": ["keep": true], "globals": ["thread-project-assignments": ["moved": "other"]]],
                "unrelated": ["globals": ["keep": true]],
            ]],
        ]
        let bytes = try JSONSerialization.data(withJSONObject: state)
        let updated = try #require(try LocalProjectHandoff.prepare(bytes, sourceOwner: "a", targetOwner: "b"))
        let result = try #require(JSONSerialization.jsonObject(with: updated) as? [String: Any])
        #expect((result["local-projects"] as? NSDictionary) == (state["local-projects"] as? NSDictionary))
        let renderer = try #require(result[LocalProjectHandoff.rendererKey] as? [String: Any])
        #expect(renderer["owner"] as? String == "a")
        let inactive = try #require(renderer["inactive"] as? [String: Any])
        let target = try #require(inactive["b"] as? [String: Any])
        let globals = try #require(target["globals"] as? [String: Any])
        let assignments = try #require(globals["thread-project-assignments"] as? [String: String])
        #expect(assignments == ["new": "local", "moved": "other"])
        #expect((globals["local-projects"] as? [String: Any])?.count == 1)
        #expect((target["atoms"] as? [String: Bool]) == ["keep": true])
        #expect(try LocalProjectHandoff.prepare(updated, sourceOwner: "a", targetOwner: "b") == nil)
    }

    @Test func leavesModernFormatsAndMismatchedOwnersUntouched() throws {
        let modern = Data(#"{"local-projects":{"local":{"path":"/local"}}}"#.utf8)
        #expect(try LocalProjectHandoff.prepare(modern, sourceOwner: "a", targetOwner: "b") == nil)
        let other = Data(#"{"electron-account-renderer-state-v1":{"owner":"other","inactive":{}},"local-projects":{"local":{"path":"/local"}}}"#.utf8)
        #expect(try LocalProjectHandoff.prepare(other, sourceOwner: "a", targetOwner: "b") == nil)
    }
}
