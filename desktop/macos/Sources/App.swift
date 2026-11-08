import AppKit
import SwiftUI

@main struct UMobileWidget: App {
    @StateObject private var model = WidgetModel()

    var body: some Scene {
        Window("U Mobile Balance", id: "balance") {
            Dashboard(model: model)
                .task { model.start() }
                .onReceive(NSWorkspace.shared.notificationCenter.publisher(for: NSWorkspace.didWakeNotification)) { _ in
                    Task { await model.updateBalance() }
                }
        }
        .defaultSize(width: 410, height: 540)
        .windowResizability(.contentSize)

        MenuBarExtra(model.menuTitle, systemImage: "antenna.radiowaves.left.and.right") {
            MenuContent(model: model)
        }.menuBarExtraStyle(.window)
    }
}

struct Dashboard: View {
    @ObservedObject var model: WidgetModel
    var body: some View {
        VStack(alignment: .leading, spacing: 22) {
            HStack(spacing: 12) {
                Image(systemName: "antenna.radiowaves.left.and.right").font(.title).foregroundStyle(.orange)
                VStack(alignment: .leading, spacing: 3) {
                    Text("U Mobile").font(.title2.bold())
                    Text("Home broadband balance").foregroundStyle(.secondary)
                }
                Spacer()
                if model.busy { ProgressView().controlSize(.small) }
            }
            if model.signedIn {
                BalanceView(model: model)
            } else if model.approval != nil {
                ApprovalView(model: model)
            } else {
                SignInView(model: model)
            }
            Text(model.message).font(.callout).foregroundStyle(.secondary).textSelection(.enabled)
                .id(model.message).fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier("connection-status")
            Spacer(minLength: 0)
            HStack {
                Label("Direct HTTPS", systemImage: "lock.shield").font(.caption).foregroundStyle(.secondary)
                Spacer()
                if model.signedIn {
                    Button("Sign out") { model.signOut() }.disabled(model.busy)
                }
            }
        }
        .padding(28)
        .frame(width: 410, height: 540)
    }
}

struct SignInView: View {
    @ObservedObject var model: WidgetModel
    var body: some View {
        VStack(alignment: .leading, spacing: 15) {
            Text("Sign in to your broadband account").font(.headline)
            Text("Use your MyUMobile email and password. Any device approval required by U Mobile still applies.")
                .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            VStack(alignment: .leading, spacing: 6) {
                Text("Email").font(.caption).foregroundStyle(.secondary)
                TextField("you@example.com", text: $model.email).textContentType(.username)
                    .accessibilityIdentifier("login-email")
            }
            VStack(alignment: .leading, spacing: 6) {
                Text("Password").font(.caption).foregroundStyle(.secondary)
                SecureField("MyUMobile password", text: $model.password).textContentType(.password)
                    .accessibilityIdentifier("login-password")
                    .onSubmit { Task { await model.signIn() } }
            }
            Toggle("Keep me signed in using Keychain", isOn: $model.remember).font(.callout)
            Text("Your password is sent to U Mobile and is never saved.").font(.caption).foregroundStyle(.secondary)
            Button { Task { await model.signIn() } } label: {
                Text(model.busy ? "Signing in…" : "Sign in").frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent).controlSize(.large).tint(.orange)
            .disabled(model.busy || model.email.isEmpty || model.password.isEmpty)
            .accessibilityIdentifier("login-submit")
        }
        .textFieldStyle(.roundedBorder)
        .disabled(model.busy)
    }
}

struct BalanceView: View {
    @ObservedObject var model: WidgetModel
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(model.snapshot?.plan ?? "U Mobile").font(.headline)
            if let pool = model.pool {
                Text(pool.name).font(.callout).foregroundStyle(.secondary)
                Text(pool.display(pool.remaining)).font(.system(size: 46, weight: .semibold, design: .rounded))
                    .minimumScaleFactor(0.5).lineLimit(1).textSelection(.enabled)
                    .id(pool.remaining)
                Text("Remaining · as reported by U Mobile").font(.caption).foregroundStyle(.secondary)
                if let fraction = pool.usedFraction { ProgressView(value: fraction).tint(.orange).accessibilityLabel("Data used") }
                HStack {
                    Metric(label: "Used", value: pool.display(pool.used))
                    Spacer()
                    Metric(label: "Allowance", value: pool.display(pool.total))
                }
                if let expiry = pool.expiry { Text("Expires \(expiry)").font(.caption).foregroundStyle(.secondary) }
                if model.displayPools.count > 1 {
                    Picker("Balance", selection: Binding(get: { model.pool?.id ?? "" }, set: { model.select($0) })) {
                        ForEach(model.displayPools) { Text($0.name).tag($0.id) }
                    }.font(.callout)
                }
            } else {
                Text("Waiting for balance").font(.title3).foregroundStyle(.secondary)
            }
            HStack {
                if let date = model.snapshot?.updatedAt { Text(date, style: .time).font(.caption).foregroundStyle(.secondary) }
                Spacer()
                Button("Refresh") { Task { await model.updateBalance() } }.disabled(model.busy)
            }
            Text("Refreshes every 5 minutes while running.").font(.caption).foregroundStyle(.secondary)
        }
    }
}

struct ApprovalView: View {
    @ObservedObject var model: WidgetModel
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label("Approve this Mac", systemImage: "iphone.and.arrow.forward").font(.headline)
            Text("U Mobile requires verification before this device can sign in.")
                .font(.callout).foregroundStyle(.secondary)
            if model.approval?.mode == "TAC" {
                TextField("Verification code", text: $model.verificationCode)
                    .textFieldStyle(.roundedBorder).textContentType(.oneTimeCode)
                    .accessibilityIdentifier("approval-code")
                    .onSubmit { Task { await model.submitCode() } }
                Button("Verify code") { Task { await model.submitCode() } }
                    .buttonStyle(.borderedProminent).tint(.orange)
                    .disabled(model.busy || model.verificationCode.isEmpty)
            } else {
                Button(model.waitingForApproval ? "Waiting for iPhone approval…" : "Approve using MyUMobile on iPhone") {
                    Task { await model.beginApproval("PRIMARY") }
                }.buttonStyle(.borderedProminent).tint(.orange)
                    .disabled(model.busy || model.waitingForApproval)
                if model.approval?.sessionID != nil {
                    Button("Check approval now") { Task { await model.checkApproval() } }.disabled(model.busy)
                }
            }
            HStack {
                Button(model.approval?.mode == "TAC" ? "Send a new code" : "Send verification code instead") {
                    Task { await model.beginApproval("TAC") }
                }.disabled(model.busy)
                Spacer()
                Button("Cancel") { model.cancelApproval() }.disabled(model.busy)
            }.font(.callout)
        }
    }
}

struct Metric: View {
    let label: String
    let value: String?
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label).font(.caption).foregroundStyle(.secondary)
            Text(value ?? "—").font(.body.monospacedDigit())
        }
    }
}

struct MenuContent: View {
    @ObservedObject var model: WidgetModel
    @Environment(\.openWindow) private var openWindow
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(model.snapshot?.plan ?? "U Mobile Balance").font(.headline)
            if let pool = model.pool {
                Text(pool.display(pool.remaining)).font(.largeTitle.bold())
                Text("Remaining · \(pool.name)").font(.caption).foregroundStyle(.secondary)
                if let date = model.snapshot?.updatedAt { Text("Updated \(date.formatted(date: .omitted, time: .shortened))").font(.caption) }
                Button("Refresh now") { Task { await model.updateBalance() } }.disabled(model.busy)
            } else { Text(model.signedIn ? "Loading balance…" : "Sign in to see your data balance.").foregroundStyle(.secondary) }
            Button("Open balance window") { openWindow(id: "balance"); NSApp.activate(ignoringOtherApps: true) }
            Divider()
            Button("Quit") { NSApp.terminate(nil) }
        }.padding(20).frame(width: 290)
    }
}
