#include "PCH.h"

#include "Config.h"
#include "Companion.h"

#include <windows.h>

namespace FoggyMap::Companion
{
	namespace
	{
		HANDLE g_process{ nullptr };

		bool StillRunning()
		{
			if (!g_process) {
				return false;
			}
			return WaitForSingleObject(g_process, 0) == WAIT_TIMEOUT;
		}
	}

	void Launch()
	{
		const auto& config = Config::Get();
		if (!config.autoLaunchCompanion || config.companionCommand.empty()) {
			return;
		}
		if (StillRunning()) {
			return;
		}

		// Capture the child's output. Launched with pythonw and no console, anything it
		// prints -- including the traceback from a crash -- would otherwise vanish, and a
		// companion that dies silently looks exactly like a companion that is idle.
		const auto logPath = config.outputDir / "companion.log";
		std::error_code error;
		std::filesystem::create_directories(config.outputDir, error);

		SECURITY_ATTRIBUTES inheritable{};
		inheritable.nLength = sizeof(inheritable);
		inheritable.bInheritHandle = TRUE;

		HANDLE log = CreateFileW(
			logPath.c_str(), FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
			std::addressof(inheritable), CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
		const bool haveLog = log != INVALID_HANDLE_VALUE;

		STARTUPINFOW startup{};
		startup.cb = sizeof(startup);
		startup.dwFlags = STARTF_USESHOWWINDOW;
		// Minimised and not activated: any window appears on the taskbar ready to
		// click, without stealing focus from the game.
		startup.wShowWindow = SW_SHOWMINNOACTIVE;
		if (haveLog) {
			startup.dwFlags |= STARTF_USESTDHANDLES;
			startup.hStdOutput = log;
			startup.hStdError = log;
		}

		PROCESS_INFORMATION process{};

		// CreateProcessW may modify the command line buffer, so hand it a copy.
		std::wstring commandLine = config.companionCommand;
		commandLine.push_back(L'\0');

		// Handles must be inheritable for the child to write to the log.
		const BOOL inherit = haveLog ? TRUE : FALSE;
		const bool started = CreateProcessW(
			nullptr, commandLine.data(), nullptr, nullptr, inherit,
			CREATE_NO_WINDOW, nullptr, nullptr, &startup, &process);
		if (haveLog) {
			CloseHandle(log);
		}
		if (!started) {
			REX::WARN("could not launch the companion (error {})", GetLastError());
			return;
		}

		CloseHandle(process.hThread);
		g_process = process.hProcess;
		REX::INFO("companion launched; its output goes to {}", logPath.string());
	}

	void Terminate()
	{
		if (!g_process) {
			return;
		}
		if (StillRunning()) {
			// The companion has no windows worth closing gracefully and holds no state
			// of its own, so terminating it is safe.
			TerminateProcess(g_process, 0);
			REX::INFO("companion closed");
		}
		CloseHandle(g_process);
		g_process = nullptr;
	}
}
