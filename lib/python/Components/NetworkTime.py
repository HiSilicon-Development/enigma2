from ipaddress import ip_address
from os import fsync, makedirs, rename
from re import fullmatch
from time import ctime, time

from enigma import eDVBLocalTimeHandler, eEPGCache, eTimer

from Components.config import config
from Components.Console import Console
from Components.SystemInfo import BoxInfo
from Tools.StbHardware import setRTCtime


class NTPSyncPoller:
	"""Automatically Poll NTP"""

	def __init__(self):
		self.timer = eTimer()
		self.Console = Console()
		self.onTimeUpdated = []
		self.previousTime = time()
		self.isDebian = BoxInfo.getItem("distro") == "debian"
		self.appliedSettings = None
		self.applyAttempted = False
		self.applying = False
		self.applyError = None
		self.generation = 0

	def startTimer(self):
		if self.timeCheck not in self.timer.callback:
			self.timer.callback.append(self.timeCheck)
		self.timer.startLongTimer(0)

	def stopTimer(self):
		if self.timeCheck in self.timer.callback:
			self.timer.callback.remove(self.timeCheck)
		self.timer.stop()

	@staticmethod
	def getSettings():
		return (config.misc.SyncTimeUsing.value, config.misc.NTPserver.value, int(config.misc.useNTPminutes.value))

	def applySettings(self, settings, callback):
		"""Apply Debian's time source before the UI commits its configuration."""
		if self.applying:
			callback(_("Time settings are already being applied."))
			return
		if settings == self.appliedSettings and not self.applyError:
			callback(None)
			return
		self.applyAttempted = True
		source, server, minutes = settings
		if source not in ("0", "1") or minutes < 1:
			callback(_("Invalid time source or synchronization interval."))
			return
		if source == "1":
			# Only one literal address or DNS name is allowed in the INI value.
			validServer = False
			if fullmatch(r"[0-9A-Fa-f:.]+", server):
				try:
					ip_address(server)
					validServer = True
				except ValueError:
					pass  # It may still be a DNS name, e.g. a hexadecimal label.
			if not validServer and len(server) <= 254:
				validServer = fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.?", server) is not None
			if not validServer:
				callback(_("Enter a single NTP server hostname or IP address."))
				return
			filename = "/etc/systemd/timesyncd.conf.d/90-enigma2.conf"
			try:
				makedirs("/etc/systemd/timesyncd.conf.d", exist_ok=True)
				with open(f"{filename}.writing", "w", encoding="UTF-8") as fd:
					fd.write(f"# Managed by Enigma2 Time Settings.\n[Time]\nNTP=\nNTP={server}\nFallbackNTP=\nPollIntervalMinSec={minutes * 60}\nPollIntervalMaxSec={minutes * 60}\n")
					fd.flush()
					fsync(fd.fileno())
				rename(f"{filename}.writing", filename)
			except OSError as error:
				self.applyError = str(error)
				callback(self.applyError)
				return
			commands = [
				["/usr/bin/systemctl", "/usr/bin/systemctl", "enable", "systemd-timesyncd.service"],
				["/usr/bin/timedatectl", "/usr/bin/timedatectl", "set-ntp", "true"],
				["/usr/bin/systemctl", "/usr/bin/systemctl", "restart", "systemd-timesyncd.service"],
				["/usr/bin/systemctl", "/usr/bin/systemctl", "is-active", "--quiet", "systemd-timesyncd.service"]
			]
		else:
			commands = [
				["/usr/bin/timedatectl", "/usr/bin/timedatectl", "set-ntp", "false"],
				["/usr/bin/systemctl", "/usr/bin/systemctl", "disable", "--now", "systemd-timesyncd.service"]
			]
		commands.append(["/usr/bin/timedatectl", "/usr/bin/timedatectl", "show", "--property=NTP", "--value"])
		self.timer.stop()
		self.applying = True
		self.generation += 1

		def finished(error):
			self.applying = False
			self.applyError = error
			if error is None:
				self.appliedSettings = settings
				eDVBLocalTimeHandler.getInstance().setUseDVBTime(source == "0")
			callback(error)
			self.timeCheck()

		def runCommand(index):
			command = commands[index]

			def commandFinished(data, retVal, extraArgs):
				if retVal:
					finished(_("%s failed (exit status %s):\n%s") % (" ".join(command[1:]), retVal, data.strip()))
				elif index + 1 < len(commands):
					runCommand(index + 1)
				elif data.strip() != ("yes" if source == "1" else "no"):
					finished(_("The operating system did not select the requested time source: %s") % data.strip())
				else:
					finished(None)

			self.Console.ePopen(command, commandFinished)

		runCommand(0)

	def timeCheck(self):
		if self.isDebian:
			if self.applying:
				return
			if not self.applyAttempted:
				self.applySettings(self.getSettings(), self.initialApplyFinished)
				return
			if self.appliedSettings is None or self.applyError:
				self.timer.startLongTimer(10)
				return
			if self.appliedSettings[0] == "0":
				self.updateSchedule()
			else:
				generation = self.generation

				def statusFinished(data, retVal, extraArgs):
					if generation != self.generation or self.applying or self.applyError:
						return
					if retVal:
						self.updateSchedule(data, retVal)
					elif data.strip() == "yes":
						self.updateSchedule()
					else:
						print(f"[NetworkTime] Internet time is not synchronized (NTPSynchronized={data.strip()}).")
						self.timer.startLongTimer(10)

				self.Console.ePopen(["/usr/bin/timedatectl", "/usr/bin/timedatectl", "show", "--property=NTPSynchronized", "--value"], statusFinished)
		else:
			eDVBLocalTimeHandler.getInstance().setUseDVBTime(config.misc.SyncTimeUsing.value == "0")
			if config.misc.SyncTimeUsing.value == "1":
				self.Console.ePopen(["/usr/sbin/ntpd", "/usr/sbin/ntpd", "-nq", "-p", config.misc.NTPserver.value], self.updateSchedule)
			else:
				self.updateSchedule()

	def initialApplyFinished(self, error):
		if error:
			print(f"[NetworkTime] Unable to apply time settings: {error}")

	def updateSchedule(self, data=None, retVal=None, extraArgs=None):
		if retVal:
			print(f"[NetworkTime] Error {retVal}: Unable to synchronize the time!\n{(data or '').strip()}")
			self.timer.startLongTimer(10)
			return
		nowTime = int(time())
		if nowTime > 10000:
			timeSource, server, minutes = self.appliedSettings if self.isDebian else self.getSettings()
			print(f"[NetworkTime] Setting time to '{ctime(nowTime)}' ({str(nowTime)}) from '{config.misc.SyncTimeUsing.toDisplayString(timeSource)}'.")
			setRTCtime(nowTime)
			eDVBLocalTimeHandler.getInstance().setUseDVBTime(timeSource == "0")
			eEPGCache.getInstance().timeUpdated()
			self.timer.startLongTimer(minutes * 60)
			if abs(time() - self.previousTime) > 60:
				for func in self.onTimeUpdated:
					if callable(func):
						func()
		else:
			print("[NetworkTime] System time not yet available.")
			self.timer.startLongTimer(10)

	def addTimeUpdatedCallback(self, func):
		if func not in self.onTimeUpdated:
			self.onTimeUpdated.append(func)

	def removeTimeUpdatedCallback(self, func):
		if func in self.onTimeUpdated:
			self.onTimeUpdated.remove(func)


ntpSyncPoller = NTPSyncPoller()
ntpsyncpoller = ntpSyncPoller  # This is used by some plugins like ABM
