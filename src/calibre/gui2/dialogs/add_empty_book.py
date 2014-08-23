#!/usr/bin/env python
__copyright__ = '2008, Kovid Goyal kovid@kovidgoyal.net'
__docformat__ = 'restructuredtext en'
__license__   = 'GPL v3'


from PyQt5.Qt import QDialog, QGridLayout, QLabel, QDialogButtonBox,  \
            QApplication, QSpinBox, QToolButton, QIcon, QCheckBox
from calibre.ebooks.metadata import string_to_authors
from calibre.gui2.complete2 import EditWithComplete
from calibre.utils.config import tweaks
from calibre.gui2 import gprefs

class AddEmptyBookDialog(QDialog):

    def __init__(self, parent, db, author, series=None):
        QDialog.__init__(self, parent)
        self.db = db

        self.setWindowTitle(_('How many empty books?'))

        self._layout = QGridLayout(self)
        self.setLayout(self._layout)

        self.qty_label = QLabel(_('How many empty books should be added?'))
        self._layout.addWidget(self.qty_label, 0, 0, 1, 2)

        self.qty_spinbox = QSpinBox(self)
        self.qty_spinbox.setRange(1, 10000)
        self.qty_spinbox.setValue(1)
        self._layout.addWidget(self.qty_spinbox, 1, 0, 1, 2)

        self.author_label = QLabel(_('Set the author of the new books to:'))
        self._layout.addWidget(self.author_label, 2, 0, 1, 2)

        self.authors_combo = EditWithComplete(self)
        self.authors_combo.setSizeAdjustPolicy(
                self.authors_combo.AdjustToMinimumContentsLengthWithIcon)
        self.authors_combo.setEditable(True)
        self._layout.addWidget(self.authors_combo, 3, 0, 1, 1)
        self.initialize_authors(db, author)

        self.clear_button = QToolButton(self)
        self.clear_button.setIcon(QIcon(I('trash.png')))
        self.clear_button.setToolTip(_('Reset author to Unknown'))
        self.clear_button.clicked.connect(self.reset_author)
        self._layout.addWidget(self.clear_button, 3, 1, 1, 1)

        self.series_label = QLabel(_('Set the series of the new books to:'))
        self._layout.addWidget(self.series_label, 4, 0, 1, 2)

        self.series_combo = EditWithComplete(self)
        self.authors_combo.setSizeAdjustPolicy(
                self.authors_combo.AdjustToMinimumContentsLengthWithIcon)
        self.series_combo.setEditable(True)
        self._layout.addWidget(self.series_combo, 5, 0, 1, 1)
        self.initialize_series(db, series)

        self.sclear_button = QToolButton(self)
        self.sclear_button.setIcon(QIcon(I('trash.png')))
        self.sclear_button.setToolTip(_('Reset series'))
        self.sclear_button.clicked.connect(self.reset_series)
        self._layout.addWidget(self.sclear_button, 5, 1, 1, 1)

        self.create_epub = c = QCheckBox(_('Create an empty EPUB file as well'))
        c.setChecked(gprefs.get('create_empty_epub_file', False))
        c.setToolTip(_('Also create an empty EPUB file that you can subsequently edit'))
        self._layout.addWidget(c, 6, 0, 1, -1)

        button_box = self.bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        self._layout.addWidget(button_box, 7, 0, 1, -1)
        self.resize(self.sizeHint())

    def accept(self):
        oval = gprefs.get('create_empty_epub_file', False)
        if self.create_epub.isChecked() != oval:
            gprefs['create_empty_epub_file'] = self.create_epub.isChecked()
        return QDialog.accept(self)

    def reset_author(self, *args):
        self.authors_combo.setEditText(_('Unknown'))

    def reset_series(self):
        self.series_combo.setEditText('')

    def initialize_authors(self, db, author):
        au = author
        if not au:
            au = _('Unknown')
        self.authors_combo.show_initial_value(au.replace('|', ','))

        self.authors_combo.set_separator('&')
        self.authors_combo.set_space_before_sep(True)
        self.authors_combo.set_add_separator(tweaks['authors_completer_append_separator'])
        self.authors_combo.update_items_cache(db.all_author_names())

    def initialize_series(self, db, series):
        self.series_combo.show_initial_value(series or '')
        self.series_combo.update_items_cache(db.all_series_names())
        self.series_combo.set_separator(None)

    @property
    def qty_to_add(self):
        return self.qty_spinbox.value()

    @property
    def selected_authors(self):
        return string_to_authors(unicode(self.authors_combo.text()))

    @property
    def selected_series(self):
        return unicode(self.series_combo.text())

if __name__ == '__main__':
    app = QApplication([])
    d = AddEmptyBookDialog()
    d.exec_()
