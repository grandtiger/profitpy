#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2007 Troy Melhase <troy@gci.net>
# Distributed under the terms of the GNU General Public License v2

from cPickle import dump, load
from os.path import split

from PyQt4.QtCore import QVariant, Qt, pyqtSignature
from PyQt4.QtGui import QApplication, QBrush, QColor, QComboBox
from PyQt4.QtGui import QDoubleSpinBox, QFileDialog, QIcon, QImageReader
from PyQt4.QtGui import QLabel, QLineEdit, QMainWindow, QMessageBox, QPixmap
from PyQt4.QtGui import QSizePolicy, QSpinBox, QStandardItem
from PyQt4.QtGui import QStandardItemModel, QToolBar

from ib.ext.Contract import Contract
from ib.ext.TickType import TickType
from ib.opt import message

from profit import series
from profit.lib.core import Settings, Signals
from profit.widgets.settingsdialog import SysPathDialog, sysPathSelectMethod
from profit.widgets.ui_tickerdesigner import Ui_TickerDesigner


def tickerFieldTypes():
    """ Creates mapping of ticker data fields to field names.

    @return field to field name mapping
    """
    items = [(k, getattr(TickType, k)) for k in dir(TickType)]
    items = [(k, v) for k, v in items if isinstance(v, int)]
    unknown = TickType.getField(-1)
    items = [(v, TickType.getField(v)) for k, v in items]
    return dict([(k, v) for k, v in items if v != unknown])


def seriesIndexTypes():
    """ Creates mapping of index class names to index types.

    @return index class name to index class mapping.
    """
    def isIndexType(obj):
        return hasattr(obj, 'params')
    items = [(k, getattr(series, k)) for k in dir(series)]
    return dict([(k, v) for k, v in items if isIndexType(v)])


class SchemaItem(QStandardItem):
    """ Base class for schema tree items.

    """
    def __init__(self, text):
        """ Constructor.

        @param text string value for item
        """
        QStandardItem.__init__(self, text)
        self.setEditable(False)
        self.cutSource = self.copySource = False

    def canCopy(self):
        return False

    def canCut(self):
        return False

    def canDelete(self):
        return True

    def canInsert(self, *types):
        return any([t in types for t in self.rootTypes()])

    def rootTypes(self):
        return [CallableItem, TickerItem]

    def canPaste(self, item):
        return False

    @property
    def children(self):
        """ Yields all children of this item.

        """
        for r in range(self.rowCount()):
            child = self.child(r, 0)
            yield child
            for c in child.children:
                yield c

    @property
    def immediateChildren(self):
        """ Yields each immediate child of this item.

        """
        for row in range(self.rowCount()):
            yield self.child(row)

    def resetForeground(self):
        """ Sets the foreground brush for this item to the original.

        This implementation uses the palette from the active window,
        which produces the desired result.  There might be an easier
        way, but using the default foreground brush from the item did
        not work (default foreground brush is black).

        @return None
        """
        self.setForeground(QApplication.activeWindow().palette().text())

    def setCopy(self):
        """ Called to indicate this instance is copied.

        @return None
        """
        self.copySource = True
        self.cutSource = False
        self.setForeground(QBrush(QColor(Qt.blue)))

    def setCut(self):
        """ Called to indicate this instance is cut.

        @return None
        """
        self.cutSource = True
        self.copySource = False
        self.setForeground(QBrush(QColor(Qt.red)))

    @property
    def siblings(self):
        """ Yields each sibling of this item.

        """
        parent = self.parent()
        for row in range(parent.rowCount()):
            child = parent.child(row, 0)
            if child is not self:
                yield child

    @property
    def root(self):
        """ Returns the top-most parent of this item.

        """
        item = self
        while True:
            if item.parent():
                item = item.parent()
            else:
                break
        return item


class CallableItem(SchemaItem):
    """ Schema tree root-level item type for callables

    """
    def __init__(self, name):
        SchemaItem.__init__(self, name)
        self.name = name
        self.threadInterval = 0
        self.scriptName = ''
        self.syspathName = ''
        self.execType = ''
        self.srcType = ''
        self.messageTyeps = []

    def canInsert(self, *types):
        return False

    @classmethod
    def fromSchema(cls, data):
        """ Creates a CallableItem from a schema.

        @param data schema dictionary
        @return CallableItem instance
        """
        instance = cls(data.get('name', 'Unknown'))
        instance.threadInterval = data.get('threadInterval', 0)
        instance.scriptName = data.get('scriptName', '')
        instance.syspathName = data.get('syspathName', '')
        instance.execType = data.get('execType', '')
        instance.srcType = data.get('srcType', '')
        instance.messageTypes = data.get('messageTypes', [])
        return instance

    def toSchema(self):
        return dict(name=self.name,
                    threadInterval=self.threadInterval,
                    scriptName=self.scriptName,
                    syspathName=self.syspathName,
                    execType=self.execType,
                    srcType=self.srcType,
                    messageTypes=self.messageTypes)


class TickerItem(SchemaItem):
    """ Schema tree root-level item type for tickers.

    TickerItems may not be cut or copied because the class does not
    provide a clone method.

    TickerItems may contain FieldItems only.
    """
    def __init__(self, tickerId, symbol, exchange='', secType='',
                 expiry='', right='', strike=0.0, currency=''):
        """ Constructor.

        @param tickerId numeric identifier of ticker
        @param symbol underlying ticker symbol as string
        """
        SchemaItem.__init__(self, symbol)
        self.tickerId = tickerId
        self.symbol = symbol
        self.exchange = exchange
        self.secType = secType
        self.expiry = expiry
        self.right = right
        self.strike = strike
        self.currency = currency

    def canInsert(self, *types):
        return FieldItem in types

    def canPaste(self, item):
        return isinstance(item, FieldItem)

    def loadIcon(self, settings):
        """ Load and set an icon appropriate for this item.

        @param settings QSettings instance
        @return None
        """
        name = self.symbol.lower()
        icon = settings.value('%s/icon' % name)
        if icon.isValid():
            icon = QIcon(icon)
        else:
            path = ':images/tickers/%s.png' % name
            if QPixmap(path).isNull():
                icon = QIcon(':images/icons/mime_empty.png')
            else:
                icon = QIcon(path)
        self.setIcon(icon)

    def toSchema(self):
        """ Generated schema dictionary for this item.

        @return schema as a dictionary
        """
        return dict(tickerId=self.tickerId,
                    symbol=self.symbol,
                    exchange=self.exchange,
                    secType=self.secType,
                    expiry=self.expiry,
                    right=self.right,
                    strike=self.strike,
                    currency=self.currency,
                    fields=[c.toSchema() for c in self.immediateChildren])

    @classmethod
    def fromSchema(cls, data):
        """ Creates a TickerItem from a schema.

        @param data schema dictionary
        @return TickerItem instance
        """
        instance = cls(tickerId=data['tickerId'],
                       symbol=data['symbol'],
                       exchange=data.get('exchange', ''),
                       secType=data.get('secType', ''),
                       expiry=data.get('expiry', ''),
                       right=data.get('right', ''),
                       strike=data.get('strike', 0.0),
                       currency=data.get('currency', ''))
        for fieldschema in data.get('fields', []):
            instance.appendRow(FieldItem.fromSchema(fieldschema))
        return instance


class FieldItem(SchemaItem):
    """ Child item type for TickerItems.

    FieldItems store a ticker data field that corresponds to the data
    field of incoming market data.
    """
    def __init__(self, name):
        """ Constructor.

        @param name string value for item
        """
        SchemaItem.__init__(self, name)
        self.id = -1

    def canCopy(self):
        return True

    def canCut(self):
        return True

    def canInsert(self, *types):
        return IndexItem in types

    def canPaste(self, item):
        return isinstance(item, IndexItem)

    def clone(self):
        """ Creates copy of this item.

        @return new FieldItem instance
        """
        clone = FieldItem(self.text())
        clone.id = self.id
        for child in self.immediateChildren:
            clone.appendRow(child.clone())
        return clone

    @classmethod
    def fromSchema(cls, data):
        """ Creates a FieldItem from a schema.

        @param data schema dictionary
        @return FieldItem instance
        """
        instance = cls(data['name'])
        instance.id = data['id']
        for indexschema in data.get('indexes', []):
            instance.appendRow(IndexItem.fromSchema(indexschema))
        return instance

    def toSchema(self):
        """ Generated schema dictionary for this item.

        @return schema as a dictionary
        """
        indexes = [child.toSchema() for child in self.immediateChildren]
        return dict(name=str(self.text()), id=self.id, indexes=indexes)


class IndexItem(SchemaItem):
    """ Child item type for FieldItems and other IndexItems.

    IndexItems store the name of the class to construct the index, as
    well as a dictionary of parameters for the index class
    constructor.
    """
    def __init__(self, typeName):
        """ Constructor.

        @param typeName index class name as string
        """
        SchemaItem.__init__(self, typeName)
        self.typeName = typeName
        self.parameters = {}

    def canCopy(self):
        return True

    def canCut(self):
        return True

    def canInsert(self, *types):
        return IndexItem in types

    def canPaste(self, item):
        return isinstance(item, IndexItem)

    def clone(self):
        """ Creates copy of this item.

        @return new IndexItem instance
        """
        clone = IndexItem(self.text())
        clone.typeName = self.typeName
        clone.parameters = self.parameters.copy()
        self.deepClone(self, clone)
        return clone

    def deepClone(self, source, target):
        """ Recursively clones children of source item to target item.

        @param source IndexItem instance
        @param target IndexItem instance
        @return None
        """
        for child in source.immediateChildren:
            clone = child.clone()
            target.appendRow(clone)
            self.deepClone(child, clone)

    def toSchema(self):
        """ Generated schema dictionary for this item.

        @return schema as a dictionary
        """
        typeName = self.typeName
        parameters = self.parameters.copy()
        name = str(self.text())
        indexes = [child.toSchema() for child in self.immediateChildren]
        return dict(typeName=typeName, indexes=indexes,
                    parameters=parameters, name=name)

    @classmethod
    def fromSchema(cls, data):
        """ Creates an IndexItem from a schema.

        @param data schema dictionary
        @return IndexItem instance
        """
        instance = cls(data['typeName'])
        instance.setText(data.get('name', instance.typeName))
        instance.parameters = data.get('parameters', {})
        for indexschema in data.get('indexes', []):
            instance.appendRow(cls.fromSchema(indexschema))
        return instance


def itemSenderPropMatchMethod(name):
    @pyqtSignature('bool')
    def method(self, checked):
        item = self.editItem
        sender = self.sender()
        if item and sender and checked:
            setattr(item, name, str(sender.property(name).toString()))
            self.emit(Signals.modified)
    return method


class TickerDesigner(QMainWindow, Ui_TickerDesigner):
    """ Ticker Designer main window class.

    """
    defaultText = 'Unknown'
    fieldTypes = tickerFieldTypes()
    indexTypes = seriesIndexTypes()
    itemTypePages = {TickerItem:1, FieldItem:2, IndexItem:3, CallableItem:4}

    def __init__(self, filename=None, parent=None):
        """ Constructor.

        @param parent ancestor of this widget
        """
        QMainWindow.__init__(self, parent)
        self.setupUi(self)
        self.editItem = None
        self.clipItem = None
        self.savedSchema = None
        self.schemaFile = None
        self.setupWidgets()
        self.readSettings()
        if filename:
            self.on_actionOpenSchema_triggered(filename)
        else:
            self.resetWindowTitle()

    # index parameter and documentation group methods

    def buildIndexParamWidgets(self, cls, item):
        """ Rebuilds the index parameter group widgets.

        @param cls index class object
        @param item IndexItem instance
        @return None
        """
        parent = self.indexParamGroup
        layout = parent.layout().children()[0]
        parent.setVisible(bool(cls.params))
        for row, (name, props) in enumerate(cls.params):
            builder = getattr(self, '%sEditor' % props.get('type', 'unknown'),
                              self.unknownEditor)
            label = QLabel(name, parent)
            label.setAlignment(Qt.AlignRight|Qt.AlignTrailing|Qt.AlignVCenter)
            sp = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            label.setSizePolicy(sp)
            layout.addWidget(label, row, 0)
            layout.addWidget(builder(name, item, props, parent), row, 1)

    def buildIndexDocWidgets(self, cls):
        """ Rebuilds the index parameter documentation widgets.

        @param cls index class object or None
        @return None
        """
        if cls:
            doc = (cls.__doc__ or '').strip()
        else:
            doc = ''
        self.indexParamDoc.setText(doc)
        self.indexDocGroup.setVisible(bool(doc))

    def resetIndexWidgets(self):
        """ Removes parameter group widgets, hides parameter and doc groups.

        @return None
        """
        self.buildIndexDocWidgets(None)
        group = self.indexParamGroup
        layout = group.layout().children()[0]
        child = layout.takeAt(0)
        while child:
             child.widget().deleteLater()
             child = layout.takeAt(0)
        group.setVisible(False)

    # parameter editor widget builder methods

    def buildSpinEditor(self, cls, name, item, props, parent):
        """ Creates a new editor suitable for integer values.

        @param cls widget type, either QSpinBox or QDoubleSpinBox
        @param name item parameter name, as string, to receive value updates
        @param item IndexItem instance
        @param props mapping of index class constructor properties
        @param parent ancestor of new widget
        @return QSpinBox or QDoubleSpinBox widget
        """
        editor = cls(parent)
        editor.setButtonSymbols(editor.PlusMinus)
        editor.setAlignment(Qt.AlignRight)
        try:
            minv = props['min']
        except (KeyError, ):
            pass
        else:
            editor.setMinimum(minv)
        try:
            default = props['default']
        except (KeyError, ):
            pass
        else:
            editor.setValue(default)
        try:
            editor.setValue(item.parameters[name])
        except (KeyError, ):
            item.parameters[name] = editor.value()
        def onChange(value):
            item.parameters[name] = value
            self.emit(Signals.modified)
        editor.onChange = onChange
        return editor

    def intEditor(self, name, item, props, parent):
        """ Creates a new editor suitable for integer values.

        @param name item parameter name, as string, to receive value updates
        @param item IndexItem instance
        @param props mapping of index class constructor properties
        @param parent ancestor of new widget
        @return QSpinBox widget
        """
        editor = self.buildSpinEditor(QSpinBox, name, item, props, parent)
        editor.connect(editor, Signals.intValueChanged, editor.onChange)
        return editor

    def floatEditor(self, name, item, props, parent):
        """ Creates a new editor suitable for float values.

        @param name item parameter name, as string, to receive value updates
        @param item IndexItem instance
        @param props mapping of index class constructor properties
        @param parent ancestor of new widget
        @return QDoubleSpinBox widget
        """
        editor = self.buildSpinEditor(
            QDoubleSpinBox, name, item, props, parent)
        editor.setSingleStep(0.01)
        editor.connect(editor, Signals.doubleValueChanged, editor.onChange)
        return editor

    def lineEditor(self, name, item, props, parent):
        """ Creates a new editor suitable for selecting a series or index.

        @param name item parameter name, as string, to receive value updates
        @param item IndexItem instance
        @param props mapping of index class constructor properties
        @param parent ancestor of new widget
        @return QComboBox widget
        """
        children = list(item.root.children)
        editor = QComboBox(parent)
        editor.addItem('')
        exclude = [item.text(), self.defaultText]
        items = [c.text() for c in children if c.text() not in exclude]
        editor.addItems(items)
        try:
            editor.setCurrentIndex(editor.findText(item.parameters[name]))
        except (KeyError, ):
            item.parameters[name] = ''
        @pyqtSignature('int')
        def onChange(index):
            item.parameters[name] = str(editor.currentText())
            self.emit(Signals.modified)
        editor.onChange = onChange
        editor.connect(editor, Signals.currentIndexChanged, onChange)
        return editor

    def unknownEditor(self, name, item, props, parent):
        """ Creates a new display widget for an unknown parameter type.

        @param name item parameter name, as string, to receive value updates
        @param item IndexItem instance
        @param props mapping of index class constructor properties
        @param parent ancestor of new widget
        @return QLabel widget
        """
        editor = QLabel('unknown type', parent)
        return editor

    # ordinary methods

    def addSchemaItem(self, **kwds):
        try:
            hasExec = kwds['execType']
            return self.addCallableItem(**kwds)
        except (KeyError, ):
            pass
        try:
            hasTickerId = kwds['tickerId']
            return self.addTickerItem(**kwds)
        except (KeyError, ):
            pass
        raise NotImplemented(str(kwds))

    def addCallableItem(self, **kwds):
        """ Creates new TickerItem at the model root.

        Caller is responsible for emitting the modified signal.

        @param **kwds key-value pairs passed to TickerItem constructor
        @return created TickerItem instance
        """
        item = CallableItem.fromSchema(kwds)
        item.setIcon(self.actionInsertCallable.icon())
        self.model.appendRow(item)
        return item

    def addTickerItem(self, **kwds):
        """ Creates new TickerItem at the model root.

        Caller is responsible for emitting the modified signal.

        @param **kwds key-value pairs passed to TickerItem constructor
        @return created TickerItem instance
        """
        item = TickerItem.fromSchema(kwds)
        item.loadIcon(self.settings)
        self.model.appendRow(item)
        return item

    def addFieldItem(self):
        """ Creates new FieldItem as child of the current selection.

        Caller is responsible for emitting the modified signal.

        @return created FieldItem instance
        """
        item = FieldItem(self.defaultText)
        item.setIcon(self.actionInsertField.icon())
        self.editItem.appendRow(item)
        self.treeView.expand(item.parent().index())
        return item

    def addIndexItem(self):
        """ Creates new IndexItem as child of the current selection.

        Caller is responsible for emitting the modified signal.

        @return created IndexItem instance
        """
        item = IndexItem(self.defaultText)
        item.setIcon(self.actionInsertIndex.icon())
        self.editItem.appendRow(item)
        self.treeView.expand(item.parent().index())
        return item

    def checkClose(self):
        """ Prompts user for next action if schema is modified.

        @return True if schema can be closed
        """
        check = True
        if self.isWindowModified():
            buttons = QMessageBox.Save|QMessageBox.Discard|QMessageBox.Cancel
            msg = QMessageBox.question(
                self, self.initialTitle, 'This schema has been modified.\n'
                'Do you want to save your changes?', buttons,
                QMessageBox.Save)
            if msg == QMessageBox.Discard:
                pass
            elif msg == QMessageBox.Cancel:
                check = False
            elif msg == QMessageBox.Save:
                self.actionSaveSchema.trigger()
        return check

    def checkModified(self):
        """ Sets the window modified flag if the schema has changed.

        @return None
        """
        self.setWindowModified(self.savedSchema != self.schema)

    def closeEvent(self, event):
        """ Framework close event handler.  Writes settings and accepts event.

        @param event QCloseEvent instance
        @return None
        """
        if self.checkClose():
            self.writeSettings()
            event.accept()
        else:
            event.ignore()

    def enableActions(self, index):
        """ Enables or disables edit and design actions.

        @param index QModelIndex instance or None
        @return None
        """
        up = down = cut = delete = copy = paste = False
        insertindex = insertfield = False
        if index and index.isValid():
            model = index.model()
            up = model.sibling(index.row()-1, 0, index).isValid()
            down = model.sibling(index.row()+1, 0, index).isValid()
            item = model.itemFromIndex(index)
            delete = item.canDelete()
            cut = item.canCut()
            copy = item.canCopy()
            clip = self.clipItem
            paste = item.canPaste(clip)
            if clip and clip.cutSource and clip == item:
                paste = False
            insertindex = item.canInsert(IndexItem)
            insertfield = item.canInsert(FieldItem)
        self.actionMoveUp.setEnabled(up)
        self.actionMoveDown.setEnabled(down)
        self.actionInsertIndex.setEnabled(insertindex)
        self.actionInsertField.setEnabled(insertfield)
        self.actionCut.setEnabled(cut)
        self.actionDelete.setEnabled(delete)
        self.actionCopy.setEnabled(copy)
        self.actionPaste.setEnabled(paste)

    def moveItem(self, item, offset):
        """ Moves item up or down schema tree.

        @param item SchemaItem instance to move.
        @param offset -1 to move up, 1 to move down
        @return None
        """
        model = self.model
        index = model.indexFromItem(item)
        tree = self.treeView
        tree.collapse(index)
        row = index.row()
        otherindex = index.sibling(row+offset, 0)
        tree.collapse(otherindex)
        other = model.itemFromIndex(otherindex)
        parent = item.parent()
        if not parent:
            parent = model.invisibleRootItem()
        parent.takeChild(row+offset, 0)
        parent.takeChild(row, 0)
        parent.setChild(row+offset, item)
        parent.setChild(row, other)
        newindex = model.indexFromItem(item)
        selectmodel = tree.selectionModel()
        selectmodel.clear()
        selectmodel.select(newindex, selectmodel.Select)
        self.enableActions(newindex)
        self.emit(Signals.modified)

    def readSettings(self):
        """ Applies stored setting values to instance.

        @return None
        """
        self.settings = obj = Settings()
        obj.beginGroup(obj.keys.designer)
        self.resize(obj.value(obj.keys.size, obj.defaultSize).toSize())
        self.move(obj.value(obj.keys.position, obj.defaultPosition).toPoint())
        if obj.value(obj.keys.maximized, False).toBool():
            self.showMaximized()
        self.restoreState(
            obj.value(obj.keys.winstate, QVariant()).toByteArray())
        self.splitter.restoreState(
            obj.value(obj.keys.splitstate, QVariant()).toByteArray())

    def updateLines(self, item, previous, current):
        """ Modifies line references in response to a new line name.

        @param item changed FieldItem or IndexItem instance
        @param previous old line name
        @param current new line name
        @return count of modified references
        """
        modified = 0
        if item:
            previous, current = str(previous), str(current)
            def pred(obj):
                return obj != item and hasattr(obj, 'parameters')
            for child in [c for c in item.root.children if pred(c)]:
                for key, value in child.parameters.items():
                    if value == previous:
                        child.parameters[key] = current
                        modified += 1
        if modified:
            self.emit(Signals.modified)
        return modified

    def resetSchema(self):
        """ Clears the schema model and resets the window widgets.

        @return None
        """
        self.model.clear()
        self.schemaFile = None
        self.resetWindowTitle()
        self.setWindowModified(False)
        self.controlStack.setCurrentIndex(0)
        self.enableActions(None)

    def resetWindowTitle(self):
        """ Sets window title to account for schema filename, if any.

        @return None
        """
        name = self.schemaFile
        if name:
            title = '%s - %s[*]' % (self.initialTitle, split(name)[1])
        else:
            title = '%s - unnamed[*]' % (self.initialTitle, )
        self.setWindowTitle(title)

    def schema(self):
        """ Constructs and returns ticker schema.

        @return schema as list of dictionaries.
        """
        root = self.model.invisibleRootItem()
        return [root.child(row).toSchema() for row in range(root.rowCount())]

    def setupCallableItem(self, item):
        self.callableName.setText(item.name)
        self.callableThreadInterval.setValue(item.threadInterval)
        self.callableScriptEdit.setText(item.scriptName)
        self.callableSysPathEdit.setText(item.syspathName)
        if item.srcType == 'script':
            self.callableScriptButton.setChecked(True)
        else:
            self.callableSysPathButton.setChecked(True)
        if item.execType == 'message':
            self.callableMessageHandlerButton.setChecked(True)
        elif item.execType == 'thread':
            self.callableThreadButton.setChecked(True)
        else:
            self.callableSingleShotButton.setChecked(True)
        self.allTypeNames = [c.typeName for c in message.registry.values()]
        widget = self.callableMessageTypes
        widget.clear()
        self.allTypeNames = [c.typeName for c in message.registry.values()]
        itemTypes = item.messageTypes
        for row, typeName in enumerate(sorted(self.allTypeNames)):
            widget.addItem(typeName)
            item = widget.item(row)
            item.setCheckState(
                Qt.Checked if typeName in itemTypes else Qt.Unchecked)

    def setupTickerItem(self, item):
        """ Configures ticker page widgets from given item.

        @param item TickerItem instance
        @return None
        """
        self.idSpin.setValue(item.tickerId)
        self.symbolEdit.setText(item.symbol)
        combo = self.secTypeCombo
        combo.setCurrentIndex(combo.findText(item.secType))
        self.exchangeEdit.setText(item.exchange)
        self.iconPreview.setPixmap(item.icon().pixmap(32, 32))
        self.expiryEdit.setText(item.expiry)
        self.strikeSpin.setValue(item.strike)
        self.currencyEdit.setText(item.currency)
        combo = self.rightCombo
        combo.setCurrentIndex(combo.findText(item.right))

    def setupFieldItem(self, item):
        """ Configures field page widgets from given item.

        @param item FieldItem instance
        @return None
        """
        combo = self.fieldCombo
        combo.setCurrentIndex(combo.findData(QVariant(item.id)))

    def setupIndexItem(self, item):
        """ Configures index page widgets from given item.

        @param item IndexItem instance
        @return None
        """
        self.indexName.setText(item.text())
        combo = self.indexCombo
        index = combo.findData(QVariant(item.typeName))
        combo.setCurrentIndex(index)
        data = self.indexCombo.itemData(index)
        if data.isValid():
            name = str(data.toString())
            self.resetIndexWidgets()
            try:
                cls = self.indexTypes[name]
            except (KeyError, ):
                pass
            else:
                self.buildIndexParamWidgets(cls, item)
                self.buildIndexDocWidgets(cls)

    def setupWidgets(self):
        """ Configures window widgets for initial display.

        @return None
        """
        self.model = QStandardItemModel(self)
        self.treeView.setModel(self.model)
        self.treeView.header().hide()
        self.initialTitle = self.windowTitle()
        self.connect(self, Signals.modified, self.checkModified)
        for toolbar in self.findChildren(QToolBar):
            self.menuToolbars.addAction(toolbar.toggleViewAction())
        self.indexCombo.addItem('<none>', QVariant())
        for name in sorted(self.indexTypes):
            self.indexCombo.addItem(name, QVariant(name))
        self.fieldCombo.addItem('<none>', QVariant())
        for id, name in sorted(self.fieldTypes.items()):
            self.fieldCombo.addItem(name, QVariant(id))
        self.callableMessageHandlerButton.setProperty(
            'execType', QVariant('message'))
        self.callableSingleShotButton.setProperty(
            'execType', QVariant('singleshot'))
        self.callableThreadButton.setProperty(
            'execType', QVariant('thread'))
        self.callableScriptButton.setProperty(
            'scrType', QVariant('script'))
        self.callableSysPathButton.setProperty(
            'scrType', QVariant('syspath'))

    def showMessage(self, text, duration=3000):
        """ Displays text in the window status bar.

        @param text message to display
        @param duration=3000 time to display message in milliseconds
        @return None
        """
        self.statusBar().showMessage(text, duration)

    def readSchema(self, schema, filename):
        """ Creates tree items from given schema.

        @param schema ticker schema as dictionary
        @return None
        """
        try:
            for data in schema:
                self.addSchemaItem(**data)
        except (Exception, ), ex:
            print '##', ex
            QMessageBox.warning(self, 'Warning', 'Unable to read schema.')
            self.resetSchema()
        else:
            self.savedSchema = schema
            self.schemaFile = filename
            self.resetWindowTitle()
            self.treeView.expandAll()
            root = self.model.invisibleRootItem()
            items = [root.child(row) for row in range(root.rowCount())]
            for item in items:
                for c in item.children:
                    if type(c) == FieldItem:
                        c.setIcon(self.actionInsertField.icon())
                    elif type(c) == IndexItem:
                        c.setIcon(self.actionInsertIndex.icon())

    def writeSettings(self):
        """ Saves window settings and state.

        @return None
        """
        settings = self.settings
        settings.setValue(settings.keys.size, self.size())
        settings.setValue(settings.keys.position, self.pos())
        settings.setValue(settings.keys.maximized, self.isMaximized())
        settings.setValue(settings.keys.winstate, self.saveState())
        settings.setValue(settings.keys.splitstate, self.splitter.saveState())

    def maybeChangeIndexName(self, item, previous):
        """ Changes index name if appropriate.

        @param item IndexItem instance
        @param previous last index type name
        @return None
        """
        widget = self.indexName
        current = str(widget.text())
        include = [self.defaultText, '']
        if current in include or current.startswith('%s-' % previous):
            flags = Qt.MatchStartsWith | Qt.MatchRecursive
            matches = self.model.findItems(item.typeName, flags)
            suffix = 1
            for match in matches:
                if item.root == match.root:
                    try:
                        name = str(match.text())
                        offset = int(name.split('-')[1])
                    except (ValueError, IndexError, ), ex:
                        pass
                    else:
                        suffix = max(suffix, offset+1)
            widget.setText('%s-%s' % (item.typeName, suffix))
            self.emit(Signals.modified)

    # widget signal handlers

    def on_currencyEdit_textEdited(self, text):
        """ Signal handler for ticker currency line edit widget text changes.

        @param text new value for line edit
        @return None
        """
        item = self.editItem
        if item:
            item.currency = str(text)
            self.emit(Signals.modified)

    def on_exchangeEdit_textEdited(self, text):
        """ Signal handler for exchange line edit widget text changes.

        @param text new value for line edit
        @return None
        """
        if self.editItem:
            self.editItem.exchange = str(text)
            self.emit(Signals.modified)

    def on_expiryEdit_textEdited(self, text):
        """ Signal handler for ticker expiry line edit widget text changes.

        @param text new value for line edit
        @return None
        """
        item = self.editItem
        if item:
            item.expiry = str(text)
            self.emit(Signals.modified)

    @pyqtSignature('int')
    def on_fieldCombo_currentIndexChanged(self, index):
        """ Signal handler for field type combobox selection changes.

        @param index selected item index
        @return None
        """
        item = self.editItem
        if item:
            data = self.fieldCombo.itemData(index)
            if data.isValid():
                fid = data.toInt()[0]
                if fid in [other.id for other in item.siblings]:
                    self.showMessage('Duplicate ticker fields not allowed.')
                    self.fieldCombo.setCurrentIndex(0)
                    return
                old = item.text()
                try:
                    new = self.fieldTypes[fid]
                    item.setText(new)
                except (KeyError, ):
                    pass
                else:
                    item.id = fid
                    if not self.updateLines(item, old, new):
                        self.emit(Signals.modified)
            else:
                self.emit(Signals.modified)

    @pyqtSignature('')
    def on_iconSelect_clicked(self):
        """ Signal handler for select icon button.

        @return None
        """
        item = self.editItem
        if item:
            formats = str.join(' ', ['*.%s' % str(fmt) for fmt in
                                     QImageReader.supportedImageFormats()])
            filename = QFileDialog.getOpenFileName(
                self, 'Select Symbol Icon', '', 'Images (%s)' % formats)
            if filename:
                icon = QIcon(filename)
                item.setIcon(icon)
                self.iconPreview.setPixmap(icon.pixmap(32,32))
                settings = self.settings
                settings.setValue('%s/icon' % item.symbol, icon)
                self.emit(Signals.modified)

    @pyqtSignature('int')
    def on_idSpin_valueChanged(self, value):
        """ Signal handler for ticker id spin box changes.

        @param value new value of spinbox
        @return None
        """
        item = self.editItem
        if item:
            item.tickerId = value
            self.emit(Signals.modified)

    @pyqtSignature('int')
    def on_indexCombo_currentIndexChanged(self, index):
        """ Signal handler for index type combobox selection changes.

        @param index selected item index
        @return None
        """
        self.resetIndexWidgets()
        item = self.editItem
        if item:
            data = self.indexCombo.itemData(index)
            if data.isValid():
                typeName = str(data.toString())
                try:
                    cls = self.indexTypes[typeName]
                except (KeyError, ):
                    pass
                else:
                    old = item.typeName
                    item.typeName = typeName
                    self.buildIndexParamWidgets(cls, item)
                    self.buildIndexDocWidgets(cls)
                    self.maybeChangeIndexName(item, old)
                    self.emit(Signals.modified)

    def on_indexName_textChanged(self, text):
        """ Signal handler for index name line edit widget changes.

        @param text new value for line edit
        @return None
        """
        try:
            old = self.indexName.oldText
        except (AttributeError, ):
            old = self.indexName.oldText = ''
        renamed = self.updateLines(self.editItem, old, text)
        self.indexName.oldText = str(text)
        if self.editItem:
            self.editItem.symbol = str(text)
            self.editItem.setText(text)
            if not renamed:
                self.emit(Signals.modified)

    @pyqtSignature('int')
    def on_rightCombo_currentIndexChanged(self, index):
        """ Signal handler for security right combobox selection changes.

        @param index selected item index
        @return None
        """
        item = self.editItem
        if item:
            item.right = str(self.rightCombo.currentText())
            self.emit(Signals.modified)

    @pyqtSignature('int')
    def on_secTypeCombo_currentIndexChanged(self, index):
        """ Signal handler for security type combobox selection changes.

        @param index selected item index
        @return None
        """
        if self.editItem:
            self.editItem.secType = str(self.secTypeCombo.currentText())
            self.emit(Signals.modified)

    @pyqtSignature('double')
    def on_strikeSpin_valueChanged(self, value):
        """ Signal handler for ticker strike price spin box changes.

        @param value new value of spinbox
        @return None
        """
        item = self.editItem
        if item:
            item.strike = value
            self.emit(Signals.modified)

    def on_symbolEdit_textEdited(self, text):
        """ Signal handler for symbol name line edit widget changes.

        @param text new value for line edit
        @return None
        """
        item = self.editItem
        if item:
            item.symbol = str(text)
            item.setText(text)
            item.loadIcon(self.settings)
            self.iconPreview.setPixmap(item.icon().pixmap(32, 32))
            self.emit(Signals.modified)

    def on_treeView_pressed(self, index):
        #print '## index pressed', index, index.isValid()
        pass

    def on_treeView_clicked(self, index):
        """ Signal handler for schema tree mouse click.

        @param index QModelIndex instance
        @return None
        """
        self.enableActions(index)
        item = self.model.itemFromIndex(index)
        itemtype = type(item)
        try:
            pageindex = self.itemTypePages[itemtype]
        except (KeyError, ):
            pass
        else:
            self.controlStack.setCurrentIndex(pageindex)
            setup = getattr(self, 'setup%s' % itemtype.__name__, None)
            if setup:
                try:
                    self.editItem = None
                    setup(item)
                finally:
                    self.editItem = item

    # action signal handlers

    @pyqtSignature('')
    def on_actionCloseSchema_triggered(self):
        """ Signal handler for close action.

        @return None
        """
        if self.checkClose():
            self.resetSchema()

    @pyqtSignature('')
    def on_actionCopy_triggered(self):
        """ Signal handler for copy action.

        @return None
        """
        if not self.actionCopy.isEnabled():
            return
        if self.clipItem:
            self.clipItem.resetForeground()
        self.clipItem = self.editItem
        self.clipItem.setCopy()

    @pyqtSignature('')
    def on_actionCut_triggered(self):
        """ Signal handler for cut action.

        @return None
        """
        if not self.actionCut.isEnabled():
            return
        if self.clipItem:
            self.clipItem.resetForeground()
        self.clipItem = self.editItem
        self.clipItem.setCut()

    @pyqtSignature('')
    def on_actionDelete_triggered(self):
        """ Signal handler for item delete action; removes item from tree.

        @return None
        """
        item = self.editItem
        if item:
            self.editItem = None
            index = self.model.indexFromItem(item)
            self.model.removeRow(index.row(), index.parent())
            self.enableActions(None)
            self.treeView.selectionModel().clear()
            self.controlStack.setCurrentIndex(0)
            self.emit(Signals.modified)

    @pyqtSignature('')
    def on_actionInsertCallable_triggered(self):
        self.addCallableItem(name=self.defaultText)
        self.emit(Signals.modified)

    @pyqtSignature('')
    def on_actionInsertTicker_triggered(self):
        """ Signal handler for insert ticker action; adds ticker item to tree.

        @return None
        """
        tickerId = 1
        root = self.model.invisibleRootItem()
        items = [root.child(r, 0) for r in range(root.rowCount())]
        if items:
            tickerId += max([getattr(i, 'tickerId', 0) for i in items])
        self.addTickerItem(tickerId=tickerId, symbol=self.defaultText)
        self.emit(Signals.modified)

    @pyqtSignature('')
    def on_actionInsertField_triggered(self):
        """ Signal handler for insert field action; adds field item to tree.

        @return None
        """
        self.addFieldItem()
        self.emit(Signals.modified)

    @pyqtSignature('')
    def on_actionInsertIndex_triggered(self):
        """ Signal handler for insert index action; adds index item to tree.

        """
        self.addIndexItem()
        self.emit(Signals.modified)

    @pyqtSignature('')
    def on_actionMoveDown_triggered(self):
        """ Signal handler for item move down action; moves item down tree.

        @return None
        """
        item = self.editItem
        if item:
            self.moveItem(item, 1)

    @pyqtSignature('')
    def on_actionMoveUp_triggered(self):
        """ Signal handler for item move up action; moves item up tree.

        @return None
        """
        item = self.editItem
        if item:
            self.moveItem(item, -1)

    @pyqtSignature('')
    def on_actionNewSchema_triggered(self):
        """ Signal handler for new schema action.

        @return None
        """
        if self.checkClose():
            self.resetSchema()

    @pyqtSignature('')
    def on_actionOpenSchema_triggered(self, filename=None):
        """ Signal handler for open schema action.

        @return None
        """
        if self.checkClose():
            if not filename:
                filename = QFileDialog.getOpenFileName(self, 'Open Schema')
            if filename:
                filename = str(filename)
                try:
                    handle = open(filename, 'rb')
                except (Exception, ):
                    QMessageBox.warning(
                        self, 'Error', 'IO error reading schema file.')
                else:
                    try:
                        schema = load(handle)
                    except (Exception, ):
                        QMessageBox.warning(
                            self, 'Error', 'Unable to read schema file.')
                    else:
                        self.resetSchema()
                        self.readSchema(schema, filename)
                    finally:
                        handle.close()

    @pyqtSignature('')
    def on_actionPaste_triggered(self):
        """ Signal handler for paste action.

        @return None
        """
        if not self.actionPaste.isEnabled():
            return
        sourceitem = self.clipItem
        targetitem = self.editItem
        model = self.model
        sourcerow = model.indexFromItem(sourceitem).row()
        sourceparent = sourceitem.parent()
        if sourceitem.cutSource:
            sourceparent.takeChild(sourcerow, 0)
            newchild = sourceitem
        else:
            newchild = sourceitem.clone()
        targetitem.setChild(targetitem.rowCount(), newchild)
        if sourceitem.cutSource:
            newchild.resetForeground()
            model.removeRow(sourcerow, sourceparent.index())
            self.clipItem = None
        self.enableActions(model.indexFromItem(targetitem))
        self.emit(Signals.modified)

    @pyqtSignature('')
    def on_actionSaveSchema_triggered(self):
        """ Signal handler for save schema action.

        @return None
        """
        if not self.schemaFile:
            self.actionSaveSchemaAs.trigger()
        else:
            try:
                handle = open(self.schemaFile, 'wb')
            except (Exception, ):
                QMessageBox.warning(
                    self, 'Error', 'IO error opening file for writing.')
            else:
                try:
                    dump(self.schema(), handle)
                except (Exception, ):
                    QMessageBox.warning(
                        self, 'Error', 'Unable to save schema file.')
                else:
                    self.setWindowModified(False)
                finally:
                    handle.close()

    @pyqtSignature('')
    def on_actionSaveSchemaAs_triggered(self):
        """ Signal handler for save as action.

        @return None
        """
        filename = QFileDialog.getSaveFileName(self, 'Save Schema As')
        if filename:
            self.schemaFile = str(filename)
            self.actionSaveSchema.trigger()
            self.resetWindowTitle()

    # callable editor widget signal handlers

    on_callableSingleShotButton_clicked = \
        itemSenderPropMatchMethod('execType')

    on_callableThreadButton_clicked = \
        itemSenderPropMatchMethod('execType')

    on_callableMessageHandlerButton_clicked = \
        itemSenderPropMatchMethod('execType')

    on_callableScriptButton_clicked = \
        itemSenderPropMatchMethod('srcType')

    on_callableSysPathButton_clicked = \
        itemSenderPropMatchMethod('srcType')

    def on_callableName_textEdited(self, text):
        item = self.editItem
        if item:
            item.setText(text)
            item.name = str(text)
            self.emit(Signals.modified)

    @pyqtSignature('int')
    def on_callableThreadInterval_valueChanged(self, value):
        item = self.editItem
        if item:
            item.threadInterval = value
            self.emit(Signals.modified)

    def on_callableMessageTypes_itemChanged(self, messageItem):
        checked = messageItem.checkState()==Qt.Checked
        key = str(messageItem.text())
        item = self.editItem
        if item:
            if checked and key not in item.messageTypes:
                item.messageTypes.append(key)
            elif not checked and key in item.messageTypes:
                item.messageTypes.remove(key)

    def on_callableScriptEdit_textChanged(self, text):
        item = self.editItem
        if item:
            item.scriptName = str(text)
            self.emit(Signals.modified)

    def on_callableSysPathEdit_textChanged(self, text):
        item = self.editItem
        if item:
            item.syspathName = str(text)
            self.emit(Signals.modified)

    @pyqtSignature('')
    def on_callableScriptSelectButton_clicked(self):
        item = self.editItem
        if item:
            filename = QFileDialog.getOpenFileName(
                self, 'Select Script', '', 'Executable file (*.*)')
            if filename:
                self.callableScriptEdit.setText(filename)

    on_callableSysPathSelectButton_clicked = \
        sysPathSelectMethod('callableSysPathEdit')

    @pyqtSignature('')
    def on_actionPrintSchema_triggered(self):
        import pprint
        pprint.pprint(self.schema())



if __name__ == '__main__':
    import sys
    app = QApplication(sys.argv)
    try:
        filename = sys.argv[1]
    except (IndexError, ):
        filename = None
    window = TickerDesigner(filename)
    window.show()
    sys.exit(app.exec_())
