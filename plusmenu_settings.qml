// The Plusmenu-Settings window, run by plusmenu_settings.py with Qt's qml runtime:
//   qml6 -a widget plusmenu_settings.qml -- <API URL> <token>
// Everything it shows and does goes through that local API (see gui() in plusmenu_settings.py).
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.kitemmodels as KItemModels

QtObject {
    // The window is made once the app's domain is set, which gives it the Wayland app ID
    // io.github.plusmenusettings.qml that the menu entry's StartupWMClass matches
    Component.onCompleted: {
        Qt.application.domain = "plusmenusettings.github.io"
        window.createObject(null)
    }

    property Component window: Kirigami.ApplicationWindow {
        id: root

        readonly property var args: Qt.application.arguments
        readonly property string api: args[args.length - 2]
        readonly property string token: args[args.length - 1]

        property string filter: "all"
        property bool showSystem: false
        property var devMode: null  // Steam's developer mode: true, false or null (can't tell)
        property bool loaded: false
        property bool busy: false
        property int hiddenCount: 0
        property string searchText: ""

        title: hiddenCount ? `Plusmenu-Settings (${hiddenCount} hidden)` : "Plusmenu-Settings"
        width: Kirigami.Units.gridUnit * 38
        height: Kirigami.Units.gridUnit * 42
        minimumWidth: Kirigami.Units.gridUnit * 20
        minimumHeight: Kirigami.Units.gridUnit * 20

        // One request to the API; the reply's app list and message are shown, then done(reply) runs
        function call(request, done) {
            busy = true
            const xhr = new XMLHttpRequest()
            xhr.onreadystatechange = () => {
                if (xhr.readyState !== XMLHttpRequest.DONE)
                    return
                let reply
                try {
                    reply = JSON.parse(xhr.responseText)
                } catch (e) {
                    reply = {message: "Plusmenu-Settings didn't answer"}
                }
                if (reply.apps)
                    setApps(reply.apps, reply.dev)
                if (reply.message)
                    showPassiveNotification(reply.message)
                busy = false
                if (done)
                    done(reply)
            }
            xhr.open("POST", api)
            xhr.setRequestHeader("Content-Type", "application/json")
            xhr.setRequestHeader("X-Plusmenu-Token", token)
            xhr.send(JSON.stringify(request))
        }

        // Updates the rows in place when the list is the same apps, so the view keeps its place
        function setApps(apps, dev) {
            devMode = dev
            const same = apps.length === appModel.count && apps.every((a, i) => appModel.get(i).appId === a.appId)
            if (same) {
                apps.forEach((a, i) => appModel.set(i, a))
            } else {
                appModel.clear()
                apps.forEach(a => appModel.append(a))
            }
            hiddenCount = apps.filter(a => a.status === "hidden").length
            loaded = true
            filtered.invalidateFilter()
        }

        function load(refresh) {
            call({action: "load", refresh: refresh})
        }

        onFilterChanged: filtered.invalidateFilter()
        onShowSystemChanged: filtered.invalidateFilter()
        onSearchTextChanged: filtered.invalidateFilter()
        Component.onCompleted: load(false)

        ListModel {
            id: appModel
        }

        KItemModels.KSortFilterProxyModel {
            id: filtered
            sourceModel: appModel
            filterRowCallback: (row, parent) => {
                const app = appModel.get(row)
                if (app.status === "system" && !root.showSystem)
                    return false
                if (root.filter !== "all" && app.status !== root.filter)
                    return false
                const q = root.searchText.trim().toLowerCase()
                return !q || app.name.toLowerCase().includes(q) || app.appId.toLowerCase().includes(q)
            }
        }

        pageStack.initialPage: Kirigami.ScrollablePage {
            id: page
            title: "Apps"

            titleDelegate: Kirigami.SearchField {
                Layout.fillWidth: true
                Layout.maximumWidth: Kirigami.Units.gridUnit * 20
                placeholderText: "Search apps"
                onTextChanged: root.searchText = text
            }

            actions: [
                Kirigami.Action {
                    text: "All"
                    checkable: true
                    checked: root.filter === "all"
                    onTriggered: root.filter = "all"
                },
                Kirigami.Action {
                    text: "Shown"
                    checkable: true
                    checked: root.filter === "shown"
                    onTriggered: root.filter = "shown"
                },
                Kirigami.Action {
                    text: "Hidden"
                    checkable: true
                    checked: root.filter === "hidden"
                    onTriggered: root.filter = "hidden"
                },
                Kirigami.Action {
                    icon.name: "view-refresh"
                    text: "Rescan"
                    displayHint: Kirigami.DisplayHint.IconOnly
                    enabled: !root.busy
                    onTriggered: root.load(true)
                },
                Kirigami.Action {
                    icon.name: "view-visible"
                    text: "Show All Hidden Apps Again"
                    displayHint: Kirigami.DisplayHint.AlwaysHide
                    enabled: !root.busy && root.hiddenCount > 0
                    onTriggered: root.call({action: "show-all"})
                },
                Kirigami.Action {
                    icon.name: "view-list-details"
                    text: "List Entries the Menu Never Shows"
                    displayHint: Kirigami.DisplayHint.AlwaysHide
                    checkable: true
                    checked: root.showSystem
                    onTriggered: root.showSystem = checked
                }
            ]

            header: ColumnLayout {
                spacing: 0

                Kirigami.InlineMessage {
                    Layout.fillWidth: true
                    Layout.margins: Kirigami.Units.smallSpacing
                    position: Kirigami.InlineMessage.Position.Header
                    visible: true
                    type: root.devMode === null && root.loaded ? Kirigami.MessageType.Warning : Kirigami.MessageType.Information
                    text: {
                        const hint = "The switch sets whether the app is listed under “Launch Program” in the "
                            + "Steam Frame dashboard's + menu. Desktop Mode and Frametop still list it. Reopen the + menu "
                            + "to see changes."
                        if (!root.loaded)
                            return hint
                        if (root.devMode === true)
                            return hint + "\nSteam developer mode is on."
                        if (root.devMode === false)
                            return hint + "\nSteam developer mode is off: VLC, Konsole and a few others aren't listed."
                        return hint + "\nCan't tell whether Steam developer mode is on (Steam isn't reachable). "
                            + "VLC, Konsole and a few others are only listed when it is."
                    }
                }
            }

            ListView {
                id: list
                model: filtered
                reuseItems: true

                delegate: QQC2.ItemDelegate {
                    id: row

                    required property string appId
                    required property string name
                    required property string subtitle
                    required property string iconSource
                    required property string status
                    required property bool locked

                    width: ListView.view.width
                    enabled: !locked
                    // The switch follows the model: the API's reply flips it, or leaves it on an error
                    onClicked: if (!root.busy) root.call({action: status === "shown" ? "hide" : "show", appId: appId})

                    contentItem: RowLayout {
                        spacing: Kirigami.Units.largeSpacing

                        Kirigami.Icon {
                            source: row.iconSource || "application-x-executable"
                            fallback: "application-x-executable"
                            Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                            Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0

                            QQC2.Label {
                                Layout.fillWidth: true
                                text: row.name
                                textFormat: Text.PlainText
                                elide: Text.ElideRight
                            }
                            QQC2.Label {
                                Layout.fillWidth: true
                                text: row.subtitle
                                textFormat: Text.PlainText
                                elide: Text.ElideRight
                                font: Kirigami.Theme.smallFont
                                opacity: 0.7
                            }
                        }

                        QQC2.Switch {
                            checkable: false
                            checked: row.status === "shown"
                            onClicked: row.clicked()
                        }
                    }
                }

                Kirigami.LoadingPlaceholder {
                    anchors.centerIn: parent
                    visible: !root.loaded
                }

                Kirigami.PlaceholderMessage {
                    anchors.centerIn: parent
                    width: parent.width - Kirigami.Units.gridUnit * 4
                    visible: root.loaded && list.count === 0
                    icon.name: root.searchText ? "edit-find" : "view-list-symbolic"
                    text: root.searchText ? "No apps match" : root.filter === "hidden" ? "No hidden apps" : "No apps"
                }
            }
        }
    }
}
