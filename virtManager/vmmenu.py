# Copyright (C) 2009, 2013, 2014 Red Hat, Inc.
# Copyright (C) 2009 Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import logging

from gi.repository import Gtk

from .asyncjob import vmmAsyncJob


####################################################################
# Build toolbar shutdown button menu (manager and details toolbar) #
####################################################################

class _VMMenu(Gtk.Menu):
    def __init__(self, src, current_vm_cb, show_open=True):
        Gtk.Menu.__init__(self)
        self._parent = src
        self._current_vm_cb = current_vm_cb
        self._show_open = show_open

        self._init_state()

    def _add_action(self, label, widgetname, cb,
                    iconname="system-shutdown"):
        if label.startswith("gtk-"):
            item = Gtk.ImageMenuItem.new_from_stock(label, None)
        else:
            item = Gtk.ImageMenuItem.new_with_mnemonic(label)

        if iconname:
            if iconname.startswith("gtk-"):
                icon = Gtk.Image.new_from_stock(iconname, Gtk.IconSize.MENU)
            else:
                icon = Gtk.Image.new_from_icon_name(iconname,
                                                    Gtk.IconSize.MENU)
            item.set_image(icon)

        item.vmm_widget_name = widgetname
        if cb:
            def _cb(_menuitem):
                _vm = self._current_vm_cb()
                if _vm:
                    return cb(self._parent, _vm)
            item.connect("activate", _cb)

        self.add(item)
        return item

    def _init_state(self):
        raise NotImplementedError()
    def update_widget_states(self, vm):
        raise NotImplementedError()


class VMShutdownMenu(_VMMenu):
    """
    Shutdown submenu for reboot, forceoff, reset, etc.
    """
    def _init_state(self):
        self._add_action(_("_Reboot"), "reboot", VMActionUI.reboot)
        self._add_action(_("_Shut Down"), "shutdown", VMActionUI.shutdown)
        self._add_action(_("F_orce Reset"), "reset", VMActionUI.reset)
        self._add_action(_("_Force Off"), "destroy", VMActionUI.destroy)
        self.add(Gtk.SeparatorMenuItem())
        self._add_action(_("Sa_ve"), "save", VMActionUI.save,
                iconname=Gtk.STOCK_SAVE)

        self.show_all()

    def update_widget_states(self, vm):
        statemap = {
            "reboot": bool(vm and vm.is_stoppable()),
            "shutdown": bool(vm and vm.is_stoppable()),
            "reset": bool(vm and vm.is_stoppable()),
            "destroy": bool(vm and vm.is_destroyable()),
            "save": bool(vm and vm.is_destroyable()),
        }

        for child in self.get_children():
            name = getattr(child, "vmm_widget_name", None)
            if name in statemap:
                child.set_sensitive(statemap[name])

            if name == "reset":
                child.set_tooltip_text(None)
                if vm and not vm.conn.check_support(
                        vm.conn.SUPPORT_CONN_DOMAIN_RESET):
                    child.set_tooltip_text(_("Hypervisor does not support "
                        "domain reset."))
                    child.set_sensitive(False)


class VMActionMenu(_VMMenu):
    """
    VM submenu for run, pause, shutdown, clone, etc
    """
    def _init_state(self):
        self._add_action(_("_Run"), "run", VMActionUI.run,
                iconname=Gtk.STOCK_MEDIA_PLAY)
        self._add_action(_("_Pause"), "suspend", VMActionUI.suspend,
                Gtk.STOCK_MEDIA_PAUSE)
        self._add_action(_("R_esume"), "resume", VMActionUI.resume,
                Gtk.STOCK_MEDIA_PAUSE)
        s = self._add_action(_("_Shut Down"), "shutdown", None)
        s.set_submenu(VMShutdownMenu(self._parent, self._current_vm_cb))

        self.add(Gtk.SeparatorMenuItem())
        self._add_action(_("Clone..."), "clone",
                VMActionUI.clone, iconname=None)
        self._add_action(_("Migrate..."), "migrate",
                VMActionUI.migrate, iconname=None)
        self._add_action(_("_Delete"), "delete",
                VMActionUI.delete, iconname=Gtk.STOCK_DELETE)

        if self._show_open:
            self.add(Gtk.SeparatorMenuItem())
            self._add_action(Gtk.STOCK_OPEN, "show",
                VMActionUI.show, iconname=None)

        self.show_all()

    def update_widget_states(self, vm):
        statemap = {
            "run": bool(vm and vm.is_runable()),
            "shutdown": bool(vm and vm.is_stoppable()),
            "suspend": bool(vm and vm.is_stoppable()),
            "resume": bool(vm and vm.is_paused()),
            "migrate": bool(vm and vm.is_stoppable()),
            "clone": bool(vm and vm.is_clonable()),
        }
        vismap = {
            "suspend": bool(vm and not vm.is_paused()),
            "resume": bool(vm and vm.is_paused()),
        }

        for child in self.get_children():
            name = getattr(child, "vmm_widget_name", None)
            if child.get_submenu():
                child.get_submenu().update_widget_states(vm)
            if name in statemap:
                child.set_sensitive(statemap[name])
            if name in vismap:
                child.set_visible(vismap[name])

    def change_run_text(self, text):
        for child in self.get_children():
            if getattr(child, "vmm_widget_name", None) == "run":
                child.get_child().set_label(text)


class VMActionUI(object):
    """
    Singleton object for handling VM actions, asking for confirmation,
    showing errors/progress dialogs, etc.
    """

    @staticmethod
    def save_cancel(asyncjob, vm):
        logging.debug("Cancelling save job")
        if not vm:
            return

        try:
            vm.abort_job()
        except Exception as e:
            logging.exception("Error cancelling save job")
            asyncjob.show_warning(_("Error cancelling save job: %s") % str(e))
            return

        asyncjob.job_canceled = True
        return

    @staticmethod
    def save(src, vm):
        if not src.err.chkbox_helper(src.config.get_confirm_poweroff,
                src.config.set_confirm_poweroff,
                text1=_("Are you sure you want to save '%s'?") % vm.get_name()):
            return

        _cancel_cb = None
        if vm.getjobinfo_supported:
            _cancel_cb = (VMActionUI.save_cancel, vm)

        def cb(asyncjob):
            vm.save(meter=asyncjob.get_meter())
        def finish_cb(error, details):
            if error is not None:
                error = _("Error saving domain: %s") % error
                src.err.show_err(error, details=details)

        progWin = vmmAsyncJob(cb, [],
                    finish_cb, [],
                    _("Saving Virtual Machine"),
                    _("Saving virtual machine memory to disk "),
                    src.topwin, cancel_cb=_cancel_cb)
        progWin.run()

    @staticmethod
    def destroy(src, vm):
        if not src.err.chkbox_helper(
            src.config.get_confirm_forcepoweroff,
            src.config.set_confirm_forcepoweroff,
            text1=_("Are you sure you want to force poweroff '%s'?" %
                    vm.get_name()),
            text2=_("This will immediately poweroff the VM without "
                    "shutting down the OS and may cause data loss.")):
            return

        logging.debug("Destroying vm '%s'", vm.get_name())
        vmmAsyncJob.simple_async_noshow(vm.destroy, [], src,
                                        _("Error shutting down domain"))

    @staticmethod
    def suspend(src, vm):
        if not src.err.chkbox_helper(src.config.get_confirm_pause,
            src.config.set_confirm_pause,
            text1=_("Are you sure you want to pause '%s'?" %
                    vm.get_name())):
            return

        logging.debug("Pausing vm '%s'", vm.get_name())
        vmmAsyncJob.simple_async_noshow(vm.suspend, [], src,
                                        _("Error pausing domain"))

    @staticmethod
    def resume(src, vm):
        logging.debug("Unpausing vm '%s'", vm.get_name())
        vmmAsyncJob.simple_async_noshow(vm.resume, [], src,
                                        _("Error unpausing domain"))

    @staticmethod
    def run(src, vm):
        logging.debug("Starting vm '%s'", vm.get_name())

        if vm.has_managed_save():
            def errorcb(error, details):
                # This is run from the main thread
                res = src.err.show_err(
                    _("Error restoring domain") + ": " + error,
                    details=details,
                    text2=_(
                        "The domain could not be restored. Would you like\n"
                        "to remove the saved state and perform a regular\n"
                        "start up?"),
                    dialog_type=Gtk.MessageType.WARNING,
                    buttons=Gtk.ButtonsType.YES_NO,
                    modal=True)

                if not res:
                    return

                try:
                    vm.remove_saved_image()
                    VMActionUI.run(src, vm)
                except Exception as e:
                    src.err.show_err(_("Error removing domain state: %s")
                                     % str(e))

            # VM will be restored, which can take some time, so show progress
            title = _("Restoring Virtual Machine")
            text = _("Restoring virtual machine memory from disk")
            vmmAsyncJob.simple_async(vm.startup, [], src,
                                     title, text, "", errorcb=errorcb)

        else:
            # Regular startup
            errorintro  = _("Error starting domain")
            vmmAsyncJob.simple_async_noshow(vm.startup, [], src, errorintro)

    @staticmethod
    def shutdown(src, vm):
        if not src.err.chkbox_helper(src.config.get_confirm_poweroff,
            src.config.set_confirm_poweroff,
            text1=_("Are you sure you want to poweroff '%s'?" %
                    vm.get_name())):
            return

        logging.debug("Shutting down vm '%s'", vm.get_name())
        vmmAsyncJob.simple_async_noshow(vm.shutdown, [], src,
                                        _("Error shutting down domain"))

    @staticmethod
    def reboot(src, vm):
        if not src.err.chkbox_helper(src.config.get_confirm_poweroff,
            src.config.set_confirm_poweroff,
            text1=_("Are you sure you want to reboot '%s'?" %
                    vm.get_name())):
            return

        logging.debug("Rebooting vm '%s'", vm.get_name())
        vmmAsyncJob.simple_async_noshow(vm.reboot, [], src,
            _("Error rebooting domain"))

    @staticmethod
    def reset(src, vm):
        if not src.err.chkbox_helper(
            src.config.get_confirm_forcepoweroff,
            src.config.set_confirm_forcepoweroff,
            text1=_("Are you sure you want to force reset '%s'?" %
                    vm.get_name()),
            text2=_("This will immediately reset the VM without "
                    "shutting down the OS and may cause data loss.")):
            return

        logging.debug("Resetting vm '%s'", vm.get_name())
        vmmAsyncJob.simple_async_noshow(vm.reset, [], src,
                                        _("Error resetting domain"))

    @staticmethod
    def delete(src, vm):
        from .delete import vmmDeleteDialog
        vmmDeleteDialog.show_instance(src, vm)

    @staticmethod
    def migrate(src, vm):
        from .migrate import vmmMigrateDialog
        vmmMigrateDialog.show_instance(src, vm)

    @staticmethod
    def clone(src, vm):
        from .clone import vmmCloneVM
        vmmCloneVM.show_instance(src, vm)

    @staticmethod
    def show(src, vm):
        from .details import vmmDetails
        vmmDetails.get_instance(src, vm).show()
