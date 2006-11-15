  Notes on translation process
  ============================

The translations for virt-manager are currently handled by the Fedora translations
team. Thus the translators work on .po files which are in the master Fedora CVS
repo for i18n stuff. Before each new release, the latest translated .po files are
pulled back into the master HG repo for virt-manager, and a new virt-manager.pot
file pushed out.

The process for updates is this:


 - Get checkout of 'virt-manager' from hg.et.redhat.com/virt/ repo
 - Get checkout of 'virt-manager' from elvis.redhat.com:/usr/local/CVS repo
 - Copy all the .po files from CVS repo into the po/ directory from HG
 - Run 'make update-po'. This
     - Rebuilds the virt-manager.pot to pull in latest strings from source
       code files
     - Runs 'msgmerge' on each .po file to add entries for new messages
       and disable old ones, etc
 - Commit this to HG repo
 - Copy the virt-manager.pot & msgmerge'd  .po files back to CVS repo
 - Commit the CVS repo

Running this only at time of release isn't entirely ideal since translators 
will always be one release behind the latest source strings. Thus ideally
the sync-up should be done on a weekly basis, as well as immediately before
release.
