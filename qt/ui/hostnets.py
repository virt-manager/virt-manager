from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QMessageBox, QTabWidget,
    QFormLayout, QGroupBox, QLineEdit, QCheckBox, QTextEdit
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from .lib.i18n import _


ICON_RUNNING = "state_running"
ICON_SHUTOFF = "state_shutoff"


class vmmHostNets(QWidget):
    def __init__(self, conn, engine):
        super().__init__()
        self.conn = conn
        self.engine = engine
        
        self._addnet = None
        self._init_ui()
        self._populate_networks()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        self._net_list = QTreeWidget()
        self._net_list.setHeaderLabels([_("Networks"), _("State")])
        self._net_list.setColumnWidth(0, 300)
        self._net_list.itemClicked.connect(self._net_selected)
        layout.addWidget(self._net_list)

        button_layout = QHBoxLayout()

        net_add = QPushButton(_("Add Network..."))
        net_add.clicked.connect(self._add_network)
        button_layout.addWidget(net_add)

        self._net_start = QPushButton(_("Start"))
        self._net_start.clicked.connect(self._start_network)
        button_layout.addWidget(self._net_start)

        self._net_stop = QPushButton(_("Stop"))
        self._net_stop.clicked.connect(self._stop_network)
        button_layout.addWidget(self._net_stop)

        self._net_delete = QPushButton(_("Delete"))
        self._net_delete.clicked.connect(self._delete_network)
        button_layout.addWidget(self._net_delete)
        
        button_layout.addStretch()
        
        layout.addLayout(button_layout)
        
        self._details_widget = QWidget()
        self._details_layout = QFormLayout(self._details_widget)
        layout.addWidget(self._details_widget)

    def _populate_networks(self):
        self._net_list.clear()
        
        for net in self.conn.list_nets():
            item = QTreeWidgetItem(self._net_list)
            item.setText(0, net.get_name())
            item.setText(1, net.run_status())
            item.setData(0, Qt.ItemDataRole.UserRole, net)

    def _net_selected(self, item, column):
        net = item.data(0, Qt.ItemDataRole.UserRole)
        if not net:
            return
        
        self._details_layout.removeRow(0)
        while self._details_layout.count():
            child = self._details_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        active = net.is_active()
        self._net_start.setEnabled(not active)
        self._net_stop.setEnabled(active)
        self._net_delete.setEnabled(not active)

        self._details_layout.addRow(_("Name:"), QLabel(net.get_name()))
        self._details_layout.addRow(_("State:"), QLabel(net.run_status()))
        self._details_layout.addRow(_("Autostart:"), QLabel(_("Yes") if net.get_autostart() else _("No")))

        try:
            ipv4_net, dhcp_range = net.get_ipv4_network()
            if ipv4_net:
                self._details_layout.addRow(_("IPv4 Network:"), QLabel(ipv4_net))
                if dhcp_range[0]:
                    self._details_layout.addRow(_("DHCP Range:"), QLabel(f"{dhcp_range[0]} - {dhcp_range[1]}"))
        except Exception:
            pass

    def _add_network(self):
        from .dialogs.createnet import vmmCreateNetwork
        dialog = vmmCreateNetwork(self.conn, self.engine)
        dialog.exec()
        self._populate_networks()

    def _start_network(self):
        item = self._net_list.currentItem()
        if not item:
            return
        net = item.data(0, Qt.ItemDataRole.UserRole)
        if net:
            from .asyncjob import vmmAsyncJob
            vmmAsyncJob.simple_async_noshow(
                net.start, [], self, f"Error starting network '{net.get_name()}'"
            )
            self._populate_networks()

    def _stop_network(self):
        item = self._net_list.currentItem()
        if not item:
            return
        net = item.data(0, Qt.ItemDataRole.UserRole)
        if net:
            from .asyncjob import vmmAsyncJob
            vmmAsyncJob.simple_async_noshow(
                net.stop, [], self, f"Error stopping network '{net.get_name()}'"
            )
            self._populate_networks()

    def _delete_network(self):
        item = self._net_list.currentItem()
        if not item:
            return
        net = item.data(0, Qt.ItemDataRole.UserRole)
        if net:
            result = QMessageBox.question(
                self, _("Delete Network"),
                f"Are you sure you want to permanently delete the network {net.get_name()}?"
            )
            if result == QMessageBox.StandardButton.Yes:
                from .asyncjob import vmmAsyncJob
                vmmAsyncJob.simple_async_noshow(
                    net.delete, [], self, _("Error deleting network '%s'") % net.get_name()
                )
                self._populate_networks()

    def refresh_page(self):
        self._populate_networks()
        self.conn.schedule_priority_tick(pollnet=True)

    def close(self):
        if self._addnet:
            self._addnet.close()

    def cleanup(self):
        self.conn = None
