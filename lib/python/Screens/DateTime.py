from Components.ActionMap import HelpableActionMap
from Components.config import config
from Components.DateTimes import dateTimes
from Components.NetworkTime import ntpSyncPoller
from Components.Sources.StaticText import StaticText
from Screens.MessageBox import MessageBox
from Screens.Setup import Setup
from Tools.Geolocation import geolocation


class DateTime(Setup):
	def __init__(self, session):
		def updatePreviews(configElement):
			dateTimes.updateDatesAndTimes()
			self.setFootnote(f"{_("Preview")}:  {dateTimes.getDateTime()}")

		def updateNetworkTime():
			if config.misc.SyncTimeUsing.isChanged() or config.misc.NTPserver.isChanged() or config.misc.useNTPminutes.isChanged():
				ntpSyncPoller.timeCheck()

		def removeNotifiers():
			for configElement in self.configElements:
				configElement.removeNotifier(updatePreviews)
			dateTimes.updateDatesAndTimes()

		Setup.__init__(self, session=session, setup="DateTime")
		self.originalTimeSettings = ntpSyncPoller.getSettings()
		self.timeSettingsTouched = False
		self.applyingTimeSettings = False
		self["key_yellow"] = StaticText()
		self["geolocationActions"] = HelpableActionMap(self, "ColorActions", {
			"yellow": (self.keyUseGeolocation, _("Use geolocation to set the current time zone location"))
		}, prio=0, description=_("Date and Time Setup Actions"))
		self.actionMaps.append("geolocationActions")
		self.configElements = dateTimes.getConfigElements()
		for configElement in self.configElements:
			configElement.addNotifier(updatePreviews, initial_call=False)
		if not ntpSyncPoller.isDebian:
			self.addSaveNotifier(updateNetworkTime)
		updatePreviews(None)
		self.selectionChanged()
		self.onClose.append(removeNotifiers)

	def selectionChanged(self):
		if Setup.getCurrentItem(self) in (config.timezone.area, config.timezone.val):
			self["key_yellow"].setText(_("Use Geolocation"))
			self["geolocationActions"].setEnabled(True)
		else:
			self["key_yellow"].setText("")
			self["geolocationActions"].setEnabled(False)
		Setup.selectionChanged(self)
		if Setup.getCurrentItem(self) in self.configElements:
			self.setFootnote(f"{_("Preview")}:  {dateTimes.getDateTime()}")

	def getConfigList(self):
		items = Setup.getConfigList(self)
		# Hidden formatting controls belong to the same save/cancel transaction,
		# including rollback of saved_value if writing the settings fails.
		for label, configElement in ((_("Day separator"), config.usage.date.daySeparator), (_("Meridiem (AM/PM) display"), config.usage.time.meridiemFormat)):
			if not any(len(item) > 1 and item[1] is configElement for item in items):
				items.append((label, configElement))
		return items

	def keySave(self):
		if self.applyingTimeSettings:
			return
		if not ntpSyncPoller.isDebian:
			Setup.keySave(self)
			return
		self.timeSettingsTouched = True
		self.applyingTimeSettings = True
		self.suspendAllActionMaps()
		self.setFootnote(_("Applying time settings..."))

		def applied(error):
			self.applyingTimeSettings = False
			self.resumeAllActionMaps()
			self.selectionChanged()
			if error:
				self.session.open(MessageBox, _("Unable to apply time settings: %s") % error, type=MessageBox.TYPE_ERROR)
			else:
				# Only commit config after the backend succeeds. Setup preserves
				# the cancel target if writing the settings then fails.
				Setup.keySave(self)

		ntpSyncPoller.applySettings(ntpSyncPoller.getSettings(), applied)

	def closeConfigList(self, closeParameters=()):
		if self.applyingTimeSettings:
			return
		if self.timeSettingsTouched and not any(item[1].isChanged() for item in self.getConfigList() if len(item) > 1):
			self.closeParameters = closeParameters
			self.cancelConfirm(True)
		else:
			Setup.closeConfigList(self, closeParameters)

	def cancelConfirm(self, result):
		if self.applyingTimeSettings:
			return
		if not result or not self.timeSettingsTouched:
			Setup.cancelConfirm(self, result)
			return
		self.applyingTimeSettings = True
		self.suspendAllActionMaps()
		self.setFootnote(_("Restoring previous time settings..."))

		def restored(error):
			self.applyingTimeSettings = False
			self.resumeAllActionMaps()
			self.selectionChanged()
			if error:
				# Still discard edits if the OS is unavailable, but show the
				# restoration failure before closing the screen.
				self.session.openWithCallback(lambda answer: Setup.cancelConfirm(self, True), MessageBox, _("Unable to restore previous time settings: %s") % error, type=MessageBox.TYPE_ERROR)
			else:
				Setup.cancelConfirm(self, True)

		ntpSyncPoller.applySettings(self.originalTimeSettings, restored)

	def cancelConfirmed(self):
		config.usage.date.daySeparator.cancel()  # Cancel any changes to this value in case it is hidden.
		config.usage.time.meridiemFormat.cancel()  # Cancel any changes to this value in case it is hidden.
		Setup.cancelConfirmed(self)

	def keyUseGeolocation(self):
		def keyUseGeolocationCallback(geolocationData):
			if geolocationData.get("proxy", True):
				self.setFootnote(_("Geolocation data is not available."))
			else:
				tz = geolocationData.get("timezone", None)
				if tz is None or "/" not in tz:
					self.setFootnote(_("Geolocation data does not contain time zone information."))
				else:
					areaItem = None
					valItem = None
					for item in self["config"].list:
						if len(item) > 1 and item[1] is config.timezone.area:
							areaItem = item
						if len(item) > 1 and item[1] is config.timezone.val:
							valItem = item
					area, zone = tz.split("/", 1)  # All timezones should be in IANA Time Zones format (Area/Location).
					config.timezone.area.value = area
					if areaItem is not None:
						areaItem[1].changed()
					self["config"].invalidate(areaItem)
					config.timezone.val.value = zone
					if valItem is not None:
						valItem[1].changed()
					self["config"].invalidate(valItem)
					self.setFootnote(_("Geolocation data has been used to set the time zone."))

		geolocation.getGeolocationData(fields="status,message,timezone,proxy", screen=self, callback=keyUseGeolocationCallback)

	def yellow(self):  # Invoked from the Wizard.
		self.keyUseGeolocation()
