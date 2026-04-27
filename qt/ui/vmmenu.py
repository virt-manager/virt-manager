from PyQt6.QtWidgets import QMenu
from PyQt6.QtCore import pyqtSignal

from .lib.i18n import _


class VMShutdownMenu(QMenu):
    def __init__(self, parent, current_vm_cb):
        super().__init__(parent)
        self._parent = parent
        self._current_vm_cb = current_vm_cb
        self._init_state()

    def _init_state(self):
        self.addAction(_("Reboot"), self._make_cb("reboot"))
        self.addAction(_("Shut Down"), self._make_cb("shutdown"))
        self.addAction(_("Force Reset"), self._make_cb("reset"))
        self.addAction(_("Force Off"), self._make_cb("destroy"))
        self.addSeparator()
        self.addAction(_("Save"), self._make_cb("save"))

    def _make_cb(self, action):
        def cb():
            vm = self._current_vm_cb()
            if vm:
                VMActionUI.trigger_action(self._parent, vm, action)
        return cb

    def update_widget_states(self, vm):
        is_running = vm and vm.is_active()
        is_shutoff = vm and not vm.is_active()
        
        for action in self.actions():
            power_actions = [_("Reboot"), _("Shut Down"), _("Force Reset"), _("Force Off")]
            if action.text() in power_actions:
                action.setEnabled(is_running)
            elif action.text() == _("Save"):
                action.setEnabled(is_shutoff)


class VMActionMenu(QMenu):
    def __init__(self, parent, current_vm_cb, show_open=True):
        super().__init__(parent)
        self._parent = parent
        self._current_vm_cb = current_vm_cb
        self._show_open = show_open
        self._init_state()

    def _init_state(self):
        self.addAction(_("Run"), self._make_cb("run"))
        self.addAction(_("Pause"), self._make_cb("suspend"))
        self.addAction(_("Resume"), self._make_cb("resume"))

        shutdown_menu = self.addMenu(_("Shut Down"))
        shutdown_menu.setMenu(VMShutdownMenu(shutdown_menu, self._current_vm_cb))

        self.addSeparator()
        self.addAction(_("Clone..."), self._make_cb("clone"))
        self.addAction(_("Migrate..."), self._make_cb("migrate"))
        self.addAction(_("Delete"), self._make_cb("delete"))

        if self._show_open:
            self.addSeparator()
            self.addAction(_("Open"), self._make_cb("show"))

    def _make_cb(self, action):
        def cb():
            vm = self._current_vm_cb()
            if vm:
                VMActionUI.trigger_action(self._parent, vm, action)
        return cb

    def update_widget_states(self, vm):
        is_running = vm and vm.is_active()
        is_shutoff = vm and not vm.is_active()
        
        for action in self.actions():
            action.setEnabled(True)
        
        if not vm:
            for action in self.actions():
                action.setEnabled(False)


class VMActionUI:
    @staticmethod
    def trigger_action(src, vm, action):
        from PyQt6.QtWidgets import QMessageBox
        
        if action == "run":
            VMActionUI._run(src, vm)
        elif action == "shutdown":
            VMActionUI._shutdown(src, vm)
        elif action == "reboot":
            VMActionUI._reboot(src, vm)
        elif action == "destroy":
            VMActionUI._destroy(src, vm)
        elif action == "suspend":
            VMActionUI._suspend(src, vm)
        elif action == "resume":
            VMActionUI._resume(src, vm)
        elif action == "reset":
            VMActionUI._reset(src, vm)
        elif action == "save":
            VMActionUI._save(src, vm)
        elif action == "delete":
            VMActionUI._delete(src, vm)
        elif action == "clone":
            VMActionUI._clone(src, vm)
        elif action == "migrate":
            VMActionUI._migrate(src, vm)
        elif action == "show":
            VMActionUI._show(src, vm)

    @staticmethod
    def _save(src, vm):
        from .asyncjob import vmmAsyncJob

        def async_save(job):
            vm.save(meter=job.get_meter())

        def finish_cb(error, details):
            if error:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.critical(src, _("Error"), f"Error saving domain: {error}\n{details}")

        vmmAsyncJob(
            async_save,
            [],
            finish_cb,
            [],
            _("Saving Virtual Machine"),
            _("Saving virtual machine memory to disk"),
            src
        ).run()

    @staticmethod
    def _destroy(src, vm):
        reply = QMessageBox.question(
            src, _("Confirm Force Power Off"),
            f"Are you sure you want to force poweroff '{vm.get_name()}'?\n\n"
            "This will immediately poweroff the VM without shutting down the OS "
            "and may cause data loss.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            from .asyncjob import vmmAsyncJob
            vmmAsyncJob.simple_async_noshow(
                vm.destroy, [], src, _("Error shutting down domain")
            )

    @staticmethod
    def _suspend(src, vm):
        reply = QMessageBox.question(
            src, _("Confirm Pause"),
            f"Are you sure you want to pause '{vm.get_name()}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            from .asyncjob import vmmAsyncJob
            vmmAsyncJob.simple_async_noshow(
                vm.suspend, [], src, _("Error pausing domain")
            )

    @staticmethod
    def _resume(src, vm):
        from .asyncjob import vmmAsyncJob
        vmmAsyncJob.simple_async_noshow(
            vm.resume, [], src, _("Error unpausing domain")
        )

    @staticmethod
    def _run(src, vm):
        from .asyncjob import vmmAsyncJob

        if vm.has_managed_save():
            def async_start(job):
                vm.startup(meter=job.get_meter())

            def finish_cb(error, details):
                if error:
                    from PyQt6.QtWidgets import QMessageBox
                    QMessageBox.critical(src, _("Error"), f"Error restoring domain: {error}")

            vmmAsyncJob(
                async_start,
                [],
                finish_cb,
                [],
                _("Restoring Virtual Machine"),
                _("Restoring virtual machine memory from disk"),
                src
            ).run()
        else:
            vmmAsyncJob.simple_async_noshow(
                vm.startup, [], src, _("Error starting domain")
            )

    @staticmethod
    def _shutdown(src, vm):
        reply = QMessageBox.question(
            src, _("Confirm Power Off"),
            f"Are you sure you want to poweroff '{vm.get_name()}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            from .asyncjob import vmmAsyncJob
            vmmAsyncJob.simple_async_noshow(
                vm.shutdown, [], src, _("Error shutting down domain")
            )

    @staticmethod
    def _reboot(src, vm):
        reply = QMessageBox.question(
            src, _("Confirm Reboot"),
            f"Are you sure you want to reboot '{vm.get_name()}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            from .asyncjob import vmmAsyncJob
            vmmAsyncJob.simple_async_noshow(
                vm.reboot, [], src, _("Error rebooting domain")
            )

    @staticmethod
    def _reset(src, vm):
        reply = QMessageBox.question(
            src, _("Confirm Force Reset"),
            f"Are you sure you want to force reset '{vm.get_name()}'?\n\n"
            "This will immediately reset the VM without shutting down the OS "
            "and may cause data loss.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            from .asyncjob import vmmAsyncJob
            vmmAsyncJob.simple_async_noshow(
                vm.reset, [], src, _("Error resetting domain")
            )

    @staticmethod
    def _delete(src, vm):
        from .dialogs.delete import vmmDeleteDialog
        dialog = vmmDeleteDialog(vm, src.conn, src.engine)
        dialog.exec()

    @staticmethod
    def _clone(src, vm):
        from .dialogs.clone import vmmClone
        dialog = vmmClone(src.conn, vm, src.engine)
        dialog.exec()

    @staticmethod
    def _migrate(src, vm):
        from .dialogs.clone import vmmClone
        dialog = vmmClone(src.conn, vm, src.engine)
        dialog.show_migrate_tab()
        dialog.exec()

    @staticmethod
    def _show(src, vm):
        from .details.details import vmmDetails
        details_window = vmmDetails(vm, src.conn, src.engine)
        details_window.show()
