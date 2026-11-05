from Components.ActionMap import HelpableActionMap
from Components.config import config
from Components.NetworkTime import ntpSyncPoller
from Components.Sources.StaticText import StaticText
from Screens.MessageBox import MessageBox
from Screens.Setup import Setup
from Tools.Geolocation import geolocation


class Time(Setup):
	def __init__(self, session):
		Setup.__init__(self, session=session, setup="Time")
		self.originalTimeSettings = ntpSyncPoller.getSettings()
		self.timeSettingsTouched = False
		self.applyingTimeSettings = False
		if not ntpSyncPoller.isDebian:
			self.addSaveNotifier(self.updateNetworkTime)
		self["key_yellow"] = StaticText()
		self["geolocationActions"] = HelpableActionMap(self, "ColorActions", {
			"yellow": (self.keyUseGeolocation, _("Use geolocation to set the current time zone location"))
		}, prio=0, description=_("Time Setup Actions"))
		self.actionMaps.append("geolocationActions")
		self.selectionChanged()

	def updateNetworkTime(self):
		if config.misc.SyncTimeUsing.isChanged() or config.misc.NTPserver.isChanged() or config.misc.useNTPminutes.isChanged():
			ntpSyncPoller.timeCheck()

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
			self.setFootnote("")
			if error:
				self.session.open(MessageBox, _("Unable to apply time settings: %s") % error, type=MessageBox.TYPE_ERROR)
			else:
				# Do not change saved_value before OS application succeeds.  Setup
				# also preserves the cancel target if writing settings fails.
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
		if not result or not self.timeSettingsTouched:
			Setup.cancelConfirm(self, result)
			return
		self.applyingTimeSettings = True
		self.suspendAllActionMaps()
		self.setFootnote(_("Restoring previous time settings..."))

		def restored(error):
			self.applyingTimeSettings = False
			self.resumeAllActionMaps()
			self.setFootnote("")
			if error:
				# Cancel still restores the user's configuration when the OS is
				# unavailable, but never hides a failed backend restoration.
				self.session.openWithCallback(lambda answer: Setup.cancelConfirm(self, True), MessageBox, _("Unable to restore previous time settings: %s") % error, type=MessageBox.TYPE_ERROR)
			else:
				Setup.cancelConfirm(self, True)

		ntpSyncPoller.applySettings(self.originalTimeSettings, restored)

	def selectionChanged(self):
		if Setup.getCurrentItem(self) in (config.timezone.area, config.timezone.val):
			self["key_yellow"].setText(_("Use Geolocation"))
			self["geolocationActions"].setEnabled(True)
		else:
			self["key_yellow"].setText("")
			self["geolocationActions"].setEnabled(False)
		Setup.selectionChanged(self)

	def keyUseGeolocation(self):
		def keyUseGeolocationCallback(geolocationData):
			if geolocationData.get("proxy", True):
				self.setFootnote(_("Geolocation data is not available."))
				return
			tz = geolocationData.get("timezone", None)
			if tz is None:
				self.setFootnote(_("Geolocation data does not contain time zone information."))
			else:
				areaItem = None
				valItem = None
				for item in self["config"].list:
					if item[1] is config.timezone.area:
						areaItem = item
					if item[1] is config.timezone.val:
						valItem = item
				area, zone = tz.split("/", 1)
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
